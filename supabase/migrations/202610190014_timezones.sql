begin;
create table public.timezone_preferences (
  user_id uuid primary key references auth.users(id),
  timezone text check(timezone is null or char_length(timezone) between 1 and 64),
  version integer not null check(version>0),
  updated_at timestamptz not null default now(),
  last_request_id uuid not null,
  last_fingerprint text not null
);
alter table public.timezone_preferences enable row level security;
revoke all on public.timezone_preferences from public,anon,authenticated;
grant select on public.timezone_preferences to authenticated;
create policy timezones_read on public.timezone_preferences for select to authenticated
  using(user_id=(select auth.uid()) or exists(select 1 from public.couple_members member
    where member.user_id=timezone_preferences.user_id and member.couple_id=(select we2day_private.my_couple())));
create function public.save_timezone(p_timezone text,p_expected_version integer,p_request_id uuid)
returns setof public.timezone_preferences language plpgsql security definer set search_path='' as $$
declare actor uuid:=we2day_private.actor(); saved public.timezone_preferences; fp text;
begin
  if (p_timezone is not null and (char_length(p_timezone) not between 1 and 64 or
    not exists(select 1 from pg_catalog.pg_timezone_names where name=p_timezone)))
    or p_expected_version is null or p_expected_version not between 0 and 2147483646
    or p_request_id is null then raise sqlstate 'PT422' using message='invalid_timezone'; end if;
  -- The user row exists before any preferences; serialize first-save races too.
  perform 1 from auth.users where id=actor for update;
  fp:=encode(extensions.digest(jsonb_build_array(p_timezone,p_expected_version)::text,'sha256'),'hex');
  select * into saved from public.timezone_preferences where user_id=actor for update;
  if found then
    if saved.last_request_id=p_request_id then
      if saved.last_fingerprint<>fp then raise sqlstate 'PT409' using message='request_conflict'; end if;
      return next saved; return;
    end if;
    if saved.version<>p_expected_version then raise sqlstate 'PT409' using message='version_conflict'; end if;
    return query update public.timezone_preferences set timezone=p_timezone,version=version+1,
      updated_at=clock_timestamp(),last_request_id=p_request_id,last_fingerprint=fp
      where user_id=actor returning *;
  else
    if p_expected_version<>0 then raise sqlstate 'PT409' using message='version_conflict'; end if;
    return query insert into public.timezone_preferences(user_id,timezone,version,last_request_id,last_fingerprint)
      values(actor,p_timezone,1,p_request_id,fp) returning *;
  end if;
end $$;
revoke all on function public.save_timezone(text,integer,uuid) from public,anon,authenticated;
grant execute on function public.save_timezone(text,integer,uuid) to authenticated;
notify pgrst,'reload schema';
commit;
