begin;

-- Private bucket; never silently reuse a public or less restricted bucket.
insert into storage.buckets(id,name,public,file_size_limit,allowed_mime_types)
values('we2day-photos','we2day-photos',false,1048576,array['image/webp'])
on conflict(id) do nothing;
do $$ begin
  if not exists(select 1 from storage.buckets where id='we2day-photos' and not public
    and file_size_limit=1048576 and allowed_mime_types=array['image/webp']::text[]) then
    raise exception 'we2day-photos bucket must be private, 1MiB, image/webp only';
  end if;
end $$;

create table public.photos (
  id uuid primary key default gen_random_uuid(),
  couple_id uuid not null references public.couples(id),
  date date not null check(date between date '2000-01-01' and date '2100-12-31'),
  caption text not null check(char_length(caption)<=500),
  filename text not null check(char_length(filename) between 1 and 255),
  device text check(char_length(device)<=255),
  captured_at text check(captured_at ~ '^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$'),
  file_modified timestamptz,
  width integer not null check(width between 1 and 1600),
  height integer not null check(height between 1 and 1600),
  bytes integer not null check(bytes between 1 and 1048576),
  sha256 text not null check(sha256 ~ '^[0-9a-f]{64}$'),
  created_by uuid not null references auth.users(id),
  created_at timestamptz not null default now(),
  uploaded_at timestamptz,
  request_id uuid not null,
  creation_fingerprint text not null,
  unique(created_by,request_id)
);
create index photos_day on public.photos(couple_id,date,id);
alter table public.photos enable row level security;
revoke all on public.photos from public,anon,authenticated;
grant select on public.photos to authenticated;
create policy photos_read on public.photos for select to authenticated using (
  couple_id=(select we2day_private.my_couple())
  and (uploaded_at is not null or created_by=(select auth.uid()))
);

-- INSERT permits the caller's exact pending reservation only. No overwrite/delete policy.
create policy we2day_photos_insert on storage.objects for insert to authenticated with check (
  bucket_id='we2day-photos' and owner_id=(select auth.uid())::text
  and exists(select 1 from public.photos p where p.created_by=(select auth.uid())
    and p.couple_id=(select we2day_private.my_couple()) and p.uploaded_at is null
    and name=p.couple_id::text||'/'||p.id::text||'.webp')
);
create policy we2day_photos_read on storage.objects for select to authenticated using (
  bucket_id='we2day-photos' and exists(select 1 from public.photos p
    where p.couple_id=(select we2day_private.my_couple())
      and (p.uploaded_at is not null or p.created_by=(select auth.uid()))
      and name=p.couple_id::text||'/'||p.id::text||'.webp')
);

-- Restrictive guards also apply if another app left a broad permissive Storage policy.
-- Other buckets keep their own existing access rules.
create policy we2day_photos_read_guard on storage.objects as restrictive
for select to authenticated using (
  bucket_id<>'we2day-photos' or exists(select 1 from public.photos p
    where p.couple_id=(select we2day_private.my_couple())
      and (p.uploaded_at is not null or p.created_by=(select auth.uid()))
      and name=p.couple_id::text||'/'||p.id::text||'.webp')
);
create policy we2day_photos_insert_guard on storage.objects as restrictive
for insert to authenticated with check (
  bucket_id<>'we2day-photos' or (owner_id=(select auth.uid())::text
    and exists(select 1 from public.photos p where p.created_by=(select auth.uid())
      and p.couple_id=(select we2day_private.my_couple()) and p.uploaded_at is null
      and name=p.couple_id::text||'/'||p.id::text||'.webp'))
);
create policy we2day_photos_update_guard on storage.objects as restrictive
for update to authenticated using(bucket_id<>'we2day-photos')
with check(bucket_id<>'we2day-photos');
create policy we2day_photos_delete_guard on storage.objects as restrictive
for delete to authenticated using(bucket_id<>'we2day-photos');
create policy we2day_photos_anonymous_guard on storage.objects as restrictive
for all to anon using(bucket_id<>'we2day-photos') with check(bucket_id<>'we2day-photos');

create function public.reserve_photo(p_date date,p_caption text,p_filename text,p_device text,
  p_captured_at text,p_file_modified timestamptz,p_width integer,p_height integer,
  p_bytes integer,p_sha256 text,p_request_id uuid)
returns setof public.photos language plpgsql security definer set search_path='' as $$
declare actor uuid:=we2day_private.actor(); space uuid:=we2day_private.my_couple();
  fingerprint text; existing public.photos;
begin
  if space is null then raise sqlstate 'PT409' using message='couple_required'; end if;
  if p_date is null or p_date not between date '2000-01-01' and date '2100-12-31'
    or p_caption is null or char_length(p_caption)>500
    or p_filename is null or char_length(btrim(p_filename)) not between 1 and 255
    or char_length(p_device)>255
    or (p_captured_at is not null and p_captured_at !~ '^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$')
    or p_width is null or p_width not between 1 and 1600
    or p_height is null or p_height not between 1 and 1600
    or p_bytes is null or p_bytes not between 1 and 1048576
    or p_sha256 is null or p_sha256 !~ '^[0-9a-f]{64}$' or p_request_id is null then
    raise sqlstate 'PT422' using message='invalid_photo';
  end if;
  fingerprint:=encode(extensions.digest(jsonb_build_array(p_date,p_caption,btrim(p_filename),
    p_device,p_captured_at,p_file_modified,p_width,p_height,p_bytes,p_sha256)::text,'sha256'),'hex');
  perform 1 from public.couples where id=space for update;
  select * into existing from public.photos where created_by=actor and request_id=p_request_id;
  if found then
    if existing.creation_fingerprint<>fingerprint then
      raise sqlstate 'PT409' using message='request_conflict';
    end if;
    return next existing; return;
  end if;
  return query insert into public.photos(couple_id,date,caption,filename,device,captured_at,
    file_modified,width,height,bytes,sha256,created_by,request_id,creation_fingerprint)
    values(space,p_date,p_caption,btrim(p_filename),p_device,p_captured_at,p_file_modified,
      p_width,p_height,p_bytes,p_sha256,actor,p_request_id,fingerprint) returning *;
end $$;

create function public.complete_photo(p_id uuid) returns setof public.photos
language plpgsql security definer set search_path='' as $$
declare actor uuid:=we2day_private.actor(); existing public.photos;
begin
  select * into existing from public.photos where id=p_id and created_by=actor
    and couple_id=we2day_private.my_couple() for update;
  if not found then raise sqlstate 'PT404' using message='photo_not_found'; end if;
  if existing.uploaded_at is not null then return next existing; return; end if;
  -- Object presence/metadata is not a certificate that bytes passed through our API.
  if not exists(select 1 from storage.objects o where o.bucket_id='we2day-photos'
    and o.name=existing.couple_id::text||'/'||existing.id::text||'.webp'
    and o.owner_id=actor::text and o.metadata->>'size'=existing.bytes::text
    and o.metadata->>'mimetype'='image/webp') then
    raise sqlstate 'PT409' using message='photo_upload_incomplete';
  end if;
  return query update public.photos set uploaded_at=clock_timestamp() where id=p_id returning *;
end $$;

revoke all on function public.reserve_photo(date,text,text,text,text,timestamptz,integer,integer,
  integer,text,uuid),public.complete_photo(uuid) from public,anon,authenticated;
grant execute on function public.reserve_photo(date,text,text,text,text,timestamptz,integer,integer,
  integer,text,uuid),public.complete_photo(uuid) to authenticated;

notify pgrst,'reload schema';
commit;
