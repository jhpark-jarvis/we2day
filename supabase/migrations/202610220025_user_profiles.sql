begin;
create table public.user_profiles (
  user_id uuid primary key references auth.users(id),
  display_name text not null check(display_name=btrim(display_name)
    and char_length(display_name) between 1 and 40 and display_name !~ '[[:cntrl:]]'),
  version integer not null check(version>0),
  updated_at timestamptz not null default now(),
  last_request_id uuid not null,
  last_fingerprint text not null
);
alter table public.user_profiles enable row level security;
revoke all on public.user_profiles from public,anon,authenticated;
grant select(user_id,display_name,version,updated_at) on public.user_profiles to authenticated;
create policy profiles_read on public.user_profiles for select to authenticated
  using(user_id=(select auth.uid()) or exists(select 1 from public.couple_members member
    where member.user_id=user_profiles.user_id and member.couple_id=(select we2day_private.my_couple())));

create function public.save_profile(p_display_name text,p_expected_version integer,p_request_id uuid)
returns table(user_id uuid,display_name text,version integer,updated_at timestamptz)
language plpgsql security definer set search_path='' as $$
declare actor uuid:=we2day_private.actor(); saved public.user_profiles; fp text;
begin
  if p_display_name is null or p_display_name<>btrim(p_display_name)
    or char_length(p_display_name) not between 1 and 40 or p_display_name ~ '[[:cntrl:]]'
    or p_expected_version is null or p_expected_version not between 0 and 2147483646
    or p_request_id is null then raise sqlstate 'PT422' using message='invalid_profile'; end if;
  perform 1 from auth.users where id=actor for update;
  fp:=encode(extensions.digest(jsonb_build_array(p_display_name,p_expected_version)::text,'sha256'),'hex');
  select p.* into saved from public.user_profiles p where p.user_id=actor for update;
  if found then
    if saved.last_request_id=p_request_id then
      if saved.last_fingerprint<>fp then raise sqlstate 'PT409' using message='request_conflict'; end if;
      return query select saved.user_id,saved.display_name,saved.version,saved.updated_at; return;
    end if;
    if saved.version<>p_expected_version then raise sqlstate 'PT409' using message='version_conflict'; end if;
    return query update public.user_profiles p set display_name=p_display_name,version=p.version+1,
      updated_at=clock_timestamp(),last_request_id=p_request_id,last_fingerprint=fp
      where p.user_id=actor returning p.user_id,p.display_name,p.version,p.updated_at;
  else
    if p_expected_version<>0 then raise sqlstate 'PT409' using message='version_conflict'; end if;
    return query insert into public.user_profiles as p(user_id,display_name,version,last_request_id,last_fingerprint)
      values(actor,p_display_name,1,p_request_id,fp) returning p.user_id,p.display_name,p.version,p.updated_at;
  end if;
end $$;
revoke all on function public.save_profile(text,integer,uuid) from public,anon,authenticated;
grant execute on function public.save_profile(text,integer,uuid) to authenticated;
notify pgrst,'reload schema';
commit;
