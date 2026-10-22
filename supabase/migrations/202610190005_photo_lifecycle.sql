begin;

alter table public.photos
  add column trashed_at timestamptz,
  add column trashed_by uuid references auth.users(id),
  add column purge_after timestamptz,
  add column purging_at timestamptz,
  add column lifecycle_version integer not null default 1 check(lifecycle_version>0),
  add column lifecycle_request_id uuid,
  add column lifecycle_actor uuid references auth.users(id),
  add column lifecycle_fingerprint text,
  add constraint photo_trash_state check (
    (trashed_at is null and trashed_by is null and purge_after is null and purging_at is null)
    or (trashed_at is not null and trashed_by is not null and purge_after is not null
      and purge_after=trashed_at+interval '30 days' and uploaded_at is not null)
  ),
  add constraint photo_purge_state check(purging_at is null or purging_at>=purge_after);
create index photos_trash on public.photos(couple_id,id) where trashed_at is not null;

create function public.change_photo_lifecycle(p_id uuid,p_action text,p_expected_version integer,
  p_request_id uuid,p_confirmation text default '') returns setof public.photos
language plpgsql security definer set search_path='' as $$
declare actor uuid:=we2day_private.actor(); existing public.photos; fingerprint text;
begin
  if p_action is null or p_action not in ('trash','restore','purge')
    or p_expected_version is null or p_expected_version not between 1 and 2147483646
    or p_request_id is null then
    raise sqlstate 'PT422' using message='invalid_photo_action';
  end if;
  if p_action='purge' and p_confirmation is distinct from '영구 삭제' then
    raise sqlstate 'PT422' using message='photo_confirmation_required';
  end if;
  select * into existing from public.photos where id=p_id
    and couple_id=we2day_private.my_couple() and uploaded_at is not null for update;
  if not found then raise sqlstate 'PT404' using message='photo_not_found'; end if;
  fingerprint:=encode(extensions.digest(jsonb_build_array(p_action,p_expected_version,
    coalesce(p_confirmation,''))::text,'sha256'),'hex');
  if existing.lifecycle_request_id=p_request_id then
    if existing.lifecycle_actor<>actor or existing.lifecycle_fingerprint<>fingerprint then
      raise sqlstate 'PT409' using message='request_conflict';
    end if;
    return next existing; return;
  end if;
  if existing.lifecycle_version<>p_expected_version then
    raise sqlstate 'PT409' using message='version_conflict';
  end if;
  if existing.purging_at is not null then
    if p_action='purge' then return next existing; return; end if;
    raise sqlstate 'PT409' using message='photo_deleting';
  end if;
  if (p_action='trash' and existing.trashed_at is not null)
    or (p_action in ('restore','purge') and existing.trashed_at is null) then
    raise sqlstate 'PT409' using message='photo_state_conflict';
  end if;
  if p_action='purge' and now()<existing.purge_after then
    raise sqlstate 'PT409' using message='photo_retention_active';
  end if;
  return query update public.photos set
    trashed_at=case when p_action='trash' then now()
      when p_action='restore' then null else trashed_at end,
    trashed_by=case when p_action='trash' then actor
      when p_action='restore' then null else trashed_by end,
    purge_after=case when p_action='trash' then now()+interval '30 days'
      when p_action='restore' then null else purge_after end,
    purging_at=case when p_action='purge' then now() else null end,
    lifecycle_version=lifecycle_version+1,lifecycle_request_id=p_request_id,
    lifecycle_actor=actor,lifecycle_fingerprint=fingerprint
    where id=p_id returning *;
end $$;

-- Physical file deletion uses the Storage API. SQL only verifies its result.
drop policy we2day_photos_delete_guard on storage.objects;
create policy we2day_photos_delete on storage.objects for delete to authenticated using (
  bucket_id='we2day-photos' and exists(select 1 from public.photos p
    where p.couple_id=(select we2day_private.my_couple()) and p.purging_at is not null
      and p.purge_after<=now() and name=p.couple_id::text||'/'||p.id::text||'.webp')
);
create policy we2day_photos_delete_guard on storage.objects as restrictive
for delete to authenticated using (
  bucket_id<>'we2day-photos' or exists(select 1 from public.photos p
    where p.couple_id=(select we2day_private.my_couple()) and p.purging_at is not null
      and p.purge_after<=now() and name=p.couple_id::text||'/'||p.id::text||'.webp')
);

create function public.finish_photo_purge(p_id uuid) returns jsonb
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
    and name=existing.couple_id::text||'/'||existing.id::text||'.webp') then
    raise sqlstate 'PT409' using message='photo_delete_incomplete';
  end if;
  delete from public.photos where id=p_id;
  return jsonb_build_object('id',p_id,'deleted',true);
end $$;

revoke all on function public.change_photo_lifecycle(uuid,text,integer,uuid,text),
  public.finish_photo_purge(uuid) from public,anon,authenticated;
grant execute on function public.change_photo_lifecycle(uuid,text,integer,uuid,text),
  public.finish_photo_purge(uuid) to authenticated;
notify pgrst,'reload schema';
commit;
