begin;
alter table public.photos
  add column metadata_request_id uuid,
  add column metadata_actor uuid references auth.users(id),
  add column metadata_fingerprint text;

create function public.edit_photo(p_id uuid,p_date date,p_caption text,
  p_expected_version integer,p_request_id uuid) returns setof public.photos
language plpgsql security definer set search_path='' as $$
declare actor uuid:=we2day_private.actor(); existing public.photos; fingerprint text;
begin
  if p_date is null or p_date not between date '2000-01-01' and date '2100-12-31'
    or p_caption is null or char_length(p_caption)>500 or p_caption ~ '[[:cntrl:]]'
    or p_expected_version is null or p_expected_version not between 1 and 2147483646
    or p_request_id is null then
    raise sqlstate 'PT422' using message='invalid_photo_metadata';
  end if;
  select * into existing from public.photos where id=p_id
    and couple_id=we2day_private.my_couple() and uploaded_at is not null for update;
  if not found then raise sqlstate 'PT404' using message='photo_not_found'; end if;
  fingerprint:=encode(extensions.digest(jsonb_build_array(p_date,p_caption,p_expected_version)::text,'sha256'),'hex');
  if existing.metadata_request_id=p_request_id then
    if existing.metadata_actor<>actor or existing.metadata_fingerprint<>fingerprint then
      raise sqlstate 'PT409' using message='request_conflict';
    end if;
    return next existing; return;
  end if;
  if existing.trashed_at is not null or existing.purging_at is not null then
    raise sqlstate 'PT409' using message='photo_state_conflict';
  end if;
  if existing.lifecycle_version<>p_expected_version then
    raise sqlstate 'PT409' using message='version_conflict';
  end if;
  return query update public.photos set date=p_date,caption=p_caption,
    lifecycle_version=lifecycle_version+1,metadata_request_id=p_request_id,
    metadata_actor=actor,metadata_fingerprint=fingerprint where id=p_id returning *;
end $$;
revoke all on function public.edit_photo(uuid,date,text,integer,uuid) from public,anon,authenticated;
grant execute on function public.edit_photo(uuid,date,text,integer,uuid) to authenticated;
notify pgrst,'reload schema';
commit;
