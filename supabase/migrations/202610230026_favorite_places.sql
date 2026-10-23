begin;
-- User-owned aliases and destination text only; never a provider-response cache.
create table public.favorite_places (
 id uuid primary key,
 couple_id uuid not null references public.couples(id),
 label text not null check(char_length(btrim(label)) between 1 and 100 and label !~ '[[:cntrl:]]'),
 destination text not null check(char_length(btrim(destination)) between 1 and 200 and destination !~ '[[:cntrl:]]'),
 archived boolean not null default false,
 version integer not null check(version>0),
 updated_by uuid not null references auth.users(id),
 created_at timestamptz not null default now(),
 updated_at timestamptz not null default now(),
 last_request_id uuid not null,
 last_fingerprint text not null
);
create index favorite_places_space on public.favorite_places(couple_id,archived,label,id);
alter table public.favorite_places enable row level security;
revoke all on public.favorite_places from public,anon,authenticated;
grant select on public.favorite_places to authenticated;
create policy favorite_places_read on public.favorite_places for select to authenticated
 using(couple_id=(select we2day_private.my_couple()));

create function public.save_favorite_place(p_id uuid,p_label text,p_destination text,
 p_archived boolean,p_expected_version integer,p_request_id uuid)
 returns setof public.favorite_places
language plpgsql security definer set search_path='' as $$
declare actor uuid:=we2day_private.actor(); space uuid:=we2day_private.my_couple();
 favorite public.favorite_places; fingerprint text;
begin
 if space is null then raise sqlstate 'PT409' using message='couple_required'; end if;
 if p_id is null or p_label is null or char_length(btrim(p_label)) not between 1 and 100
  or p_label ~ '[[:cntrl:]]' or p_destination is null
  or char_length(btrim(p_destination)) not between 1 and 200 or p_destination ~ '[[:cntrl:]]'
  or p_archived is null or p_expected_version is null or p_expected_version not between 0 and 2147483646
  or p_request_id is null then raise sqlstate 'PT422' using message='invalid_favorite_place'; end if;
 fingerprint:=encode(extensions.digest(jsonb_build_array(p_id,p_label,p_destination,p_archived,p_expected_version)::text,'sha256'),'hex');
 perform 1 from public.couples where id=space for update;
 select * into favorite from public.favorite_places where id=p_id and couple_id=space for update;
 if not found then
  if exists(select 1 from public.favorite_places where id=p_id) then
   raise sqlstate 'PT404' using message='favorite_place_not_found'; end if;
  if p_expected_version<>0 then raise sqlstate 'PT409' using message='version_conflict'; end if;
  return query insert into public.favorite_places(id,couple_id,label,destination,archived,version,updated_by,last_request_id,last_fingerprint)
   values(p_id,space,btrim(p_label),btrim(p_destination),p_archived,1,actor,p_request_id,fingerprint) returning *;
  return;
 end if;
 if favorite.last_request_id=p_request_id then
  if favorite.updated_by<>actor or favorite.last_fingerprint<>fingerprint then
   raise sqlstate 'PT409' using message='request_conflict'; end if;
  return next favorite; return;
 end if;
 if favorite.version<>p_expected_version then raise sqlstate 'PT409' using message='version_conflict'; end if;
 return query update public.favorite_places set label=btrim(p_label),destination=btrim(p_destination),
  archived=p_archived,version=version+1,updated_by=actor,updated_at=clock_timestamp(),
  last_request_id=p_request_id,last_fingerprint=fingerprint where id=p_id returning *;
end $$;
revoke all on function public.save_favorite_place(uuid,text,text,boolean,integer,uuid) from public,anon,authenticated;
grant execute on function public.save_favorite_place(uuid,text,text,boolean,integer,uuid) to authenticated;
notify pgrst,'reload schema';
commit;
