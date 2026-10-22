begin;

create table public.meeting_days (
  couple_id uuid not null references public.couples(id),
  date date not null check(date between date '2000-01-01' and date '2100-12-31'),
  met boolean not null,
  note text not null check(char_length(note)<=2000),
  version integer not null check(version>0),
  updated_by uuid not null references auth.users(id),
  updated_at timestamptz not null default now(),
  last_request_id uuid not null,
  last_fingerprint text not null,
  primary key(couple_id,date)
);
alter table public.meeting_days enable row level security;
revoke all on public.meeting_days from public,anon,authenticated;
grant select on public.meeting_days to authenticated;
create policy meeting_days_read on public.meeting_days for select to authenticated
  using(couple_id=(select we2day_private.my_couple()));

create function public.save_meeting_day(p_date date,p_met boolean,p_note text,
  p_expected_version integer,p_request_id uuid) returns setof public.meeting_days
language plpgsql security definer set search_path='' as $$
declare actor uuid:=we2day_private.actor(); space uuid:=we2day_private.my_couple();
  existing public.meeting_days; fingerprint text;
begin
  if space is null then raise sqlstate 'PT409' using message='couple_required'; end if;
  if p_date is null or p_date not between date '2000-01-01' and date '2100-12-31'
    or p_date>(now() at time zone 'Asia/Seoul')::date or p_met is null
    or p_note is null or char_length(p_note)>2000 or p_request_id is null
    or p_expected_version is null or p_expected_version not between 0 and 2147483646 then
    raise sqlstate 'PT422' using message='invalid_meeting_day';
  end if;
  fingerprint:=encode(extensions.digest(jsonb_build_array(p_date,p_met,p_note,
    p_expected_version)::text,'sha256'),'hex');
  perform 1 from public.couples where id=space for update;
  select * into existing from public.meeting_days where couple_id=space and date=p_date;
  if found then
    if existing.last_request_id=p_request_id then
      if existing.updated_by<>actor or existing.last_fingerprint<>fingerprint then
        raise sqlstate 'PT409' using message='request_conflict';
      end if;
      return next existing; return;
    end if;
    if existing.version<>p_expected_version then
      raise sqlstate 'PT409' using message='version_conflict';
    end if;
    return query update public.meeting_days set met=p_met,note=p_note,version=version+1,
      updated_by=actor,updated_at=clock_timestamp(),last_request_id=p_request_id,
      last_fingerprint=fingerprint where couple_id=space and date=p_date returning *;
  else
    if p_expected_version<>0 then
      raise sqlstate 'PT409' using message='version_conflict';
    end if;
    return query insert into public.meeting_days(couple_id,date,met,note,version,updated_by,
      last_request_id,last_fingerprint)
      values(space,p_date,p_met,p_note,1,actor,p_request_id,fingerprint) returning *;
  end if;
end $$;
revoke all on function public.save_meeting_day(date,boolean,text,integer,uuid)
  from public,anon,authenticated;
grant execute on function public.save_meeting_day(date,boolean,text,integer,uuid) to authenticated;
notify pgrst,'reload schema';
commit;
