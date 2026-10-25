begin;
alter table public.photos add column preview_sha256 text,
  add column preview_bytes integer, add column preview_width integer, add column preview_height integer,
  add constraint photo_preview_complete check (
    (preview_sha256 is null and preview_bytes is null and preview_width is null and preview_height is null)
    or (preview_sha256 is not null and preview_sha256 ~ '^[0-9a-f]{64}$'
      and preview_bytes is not null and preview_bytes between 1 and 1048576
      and preview_width is not null and preview_width between 1 and 640
      and preview_height is not null and preview_height between 1 and 640));

-- SHARE (not KEY SHARE) blocks concurrent lifecycle UPDATE and parent deletion until INSERT commits.
create function we2day_private.can_insert_photo_preview(p_name text) returns boolean
language plpgsql security definer set search_path='' as $$
declare existing public.photos; actor uuid:=we2day_private.actor();
begin
  select * into existing from public.photos p where
    p.couple_id=we2day_private.my_couple() and p_name=p.couple_id::text||'/'||p.id::text||'.preview.webp'
    and p.trashed_at is null and p.purging_at is null
    and (p.uploaded_at is not null or p.created_by=actor) for share;
  return found;
end $$;
revoke all on function we2day_private.can_insert_photo_preview(text) from public,anon,authenticated;
grant execute on function we2day_private.can_insert_photo_preview(text) to authenticated;

drop policy we2day_photos_insert on storage.objects;
create policy we2day_photos_insert on storage.objects
for insert to authenticated with check (bucket_id='we2day-photos' and (owner_id=(select auth.uid())::text and (
  exists(select 1 from public.photos p where p.created_by=(select auth.uid())
    and p.couple_id=(select we2day_private.my_couple()) and p.uploaded_at is null
    and name=p.couple_id::text||'/'||p.id::text||'.webp')
  or we2day_private.can_insert_photo_preview(name))));

drop policy we2day_photos_insert_guard on storage.objects;
create policy we2day_photos_insert_guard on storage.objects as restrictive
for insert to authenticated with check (bucket_id<>'we2day-photos' or (owner_id=(select auth.uid())::text and (
  exists(select 1 from public.photos p where p.created_by=(select auth.uid())
    and p.couple_id=(select we2day_private.my_couple()) and p.uploaded_at is null
    and name=p.couple_id::text||'/'||p.id::text||'.webp')
  or we2day_private.can_insert_photo_preview(name))));

drop policy we2day_photos_read on storage.objects;
create policy we2day_photos_read on storage.objects
for select to authenticated using (bucket_id='we2day-photos' and (exists(select 1 from public.photos p where p.couple_id=(select we2day_private.my_couple())
  and (p.uploaded_at is not null or p.created_by=(select auth.uid()))
  and name in (p.couple_id::text||'/'||p.id::text||'.webp',
    p.couple_id::text||'/'||p.id::text||'.preview.webp'))));

drop policy we2day_photos_read_guard on storage.objects;
create policy we2day_photos_read_guard on storage.objects as restrictive
for select to authenticated using (bucket_id<>'we2day-photos' or (exists(select 1 from public.photos p where p.couple_id=(select we2day_private.my_couple())
  and (p.uploaded_at is not null or p.created_by=(select auth.uid()))
  and name in (p.couple_id::text||'/'||p.id::text||'.webp',
    p.couple_id::text||'/'||p.id::text||'.preview.webp'))));

drop policy we2day_photos_delete on storage.objects;
create policy we2day_photos_delete on storage.objects
for delete to authenticated using (bucket_id='we2day-photos' and (exists(select 1 from public.photos p where p.couple_id=(select we2day_private.my_couple())
  and p.purging_at is not null and p.purge_after<=now()
  and name in (p.couple_id::text||'/'||p.id::text||'.webp',
    p.couple_id::text||'/'||p.id::text||'.preview.webp'))));

drop policy we2day_photos_delete_guard on storage.objects;
create policy we2day_photos_delete_guard on storage.objects as restrictive
for delete to authenticated using (bucket_id<>'we2day-photos' or (exists(select 1 from public.photos p where p.couple_id=(select we2day_private.my_couple())
  and p.purging_at is not null and p.purge_after<=now()
  and name in (p.couple_id::text||'/'||p.id::text||'.webp',
    p.couple_id::text||'/'||p.id::text||'.preview.webp'))));

create function public.complete_photo_preview(p_id uuid,p_sha256 text,p_bytes integer,
  p_width integer,p_height integer) returns jsonb
language plpgsql security definer set search_path='' as $$
declare actor uuid:=we2day_private.actor(); existing public.photos;
begin
  if p_sha256 is null or p_sha256 !~ '^[0-9a-f]{64}$'
    or p_bytes is null or p_bytes not between 1 and 1048576
    or p_width is null or p_width not between 1 and 640
    or p_height is null or p_height not between 1 and 640 then
    raise sqlstate 'PT422' using message='invalid_photo';
  end if;
  select * into existing from public.photos where id=p_id
    and couple_id=we2day_private.my_couple()
    and (uploaded_at is not null or created_by=actor) for update;
  if not found then raise sqlstate 'PT404' using message='photo_not_found'; end if;
  if existing.trashed_at is not null or existing.purging_at is not null then
    raise sqlstate 'PT409' using message='photo_state_conflict';
  end if;
  if existing.preview_sha256 is not null then
    if (existing.preview_sha256,existing.preview_bytes,existing.preview_width,existing.preview_height)
       is distinct from (p_sha256,p_bytes,p_width,p_height) then
      raise sqlstate 'PT409' using message='request_conflict';
    end if;
    return jsonb_build_object('id',p_id); -- No business version change for a derived cache.
  end if;
  if not exists(select 1 from storage.objects o where o.bucket_id='we2day-photos'
    and o.name=existing.couple_id::text||'/'||existing.id::text||'.preview.webp'
    and o.metadata->>'size'=p_bytes::text and o.metadata->>'mimetype'='image/webp') then
    raise sqlstate 'PT409' using message='photo_upload_incomplete';
  end if;
  update public.photos set preview_sha256=p_sha256,preview_bytes=p_bytes,
    preview_width=p_width,preview_height=p_height where id=p_id;
  return jsonb_build_object('id',p_id);
end $$;
revoke all on function public.complete_photo_preview(uuid,text,integer,integer,integer)
  from public,anon,authenticated;
grant execute on function public.complete_photo_preview(uuid,text,integer,integer,integer) to authenticated;
create or replace function public.finish_photo_purge(p_id uuid) returns jsonb
language plpgsql security definer set search_path='' as $$
declare actor uuid:=we2day_private.actor(); existing public.photos;
begin
  select * into existing from public.photos where id=p_id
    and couple_id=we2day_private.my_couple() for update;
  if not found then raise sqlstate 'PT404' using message='photo_not_found'; end if;
  if existing.purging_at is null or existing.purge_after>now() then
    raise sqlstate 'PT409' using message='photo_state_conflict';
  end if;
  if exists(select 1 from storage.objects where bucket_id='we2day-photos'
    and name in (existing.couple_id::text||'/'||existing.id::text||'.webp',
      existing.couple_id::text||'/'||existing.id::text||'.preview.webp')) then
    raise sqlstate 'PT409' using message='photo_delete_incomplete';
  end if;
  delete from public.photos where id=p_id;
  return jsonb_build_object('id',p_id,'deleted',true);
end $$;

notify pgrst,'reload schema';
commit;
