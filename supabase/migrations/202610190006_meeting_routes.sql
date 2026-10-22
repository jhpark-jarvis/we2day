begin;

create table public.meeting_routes (
  couple_id uuid not null references public.couples(id),
  date date not null check(date between date '2000-01-01' and date '2100-12-31'),
  start_name text not null check(char_length(btrim(start_name)) between 1 and 100),
  start_lat double precision not null check(start_lat between -90 and 90),
  start_lng double precision not null check(start_lng between -180 and 180),
  end_name text not null check(char_length(btrim(end_name)) between 1 and 100),
  end_lat double precision not null check(end_lat between -90 and 90),
  end_lng double precision not null check(end_lng between -180 and 180),
  version integer not null check(version>0),
  updated_by uuid not null references auth.users(id),
  updated_at timestamptz not null default now(),
  last_request_id uuid not null,
  last_fingerprint text not null,
  primary key(couple_id,date)
);
alter table public.meeting_routes enable row level security;
revoke all on public.meeting_routes from public,anon,authenticated;
grant select on public.meeting_routes to authenticated;
create policy meeting_routes_read on public.meeting_routes for select to authenticated
  using(couple_id=(select we2day_private.my_couple()));

create function public.save_meeting_route(p_date date,
  p_start_name text,p_start_lat double precision,p_start_lng double precision,
  p_end_name text,p_end_lat double precision,p_end_lng double precision,
  p_expected_version integer,p_request_id uuid) returns setof public.meeting_routes
language plpgsql security definer set search_path='' as $$
declare actor uuid:=we2day_private.actor(); space uuid:=we2day_private.my_couple();
  existing public.meeting_routes; fingerprint text;
begin
  if space is null then raise sqlstate 'PT409' using message='couple_required'; end if;
  if p_date is null or p_date not between date '2000-01-01' and date '2100-12-31'
    or p_date>(now() at time zone 'Asia/Seoul')::date
    or p_start_name is null or char_length(btrim(p_start_name)) not between 1 and 100
    or p_end_name is null or char_length(btrim(p_end_name)) not between 1 and 100
    or p_start_lat is null or p_start_lat not between -90 and 90
    or p_start_lng is null or p_start_lng not between -180 and 180
    or p_end_lat is null or p_end_lat not between -90 and 90
    or p_end_lng is null or p_end_lng not between -180 and 180 or p_request_id is null
    or p_expected_version is null or p_expected_version not between 0 and 2147483646 then
    raise sqlstate 'PT422' using message='invalid_route';
  end if;
  fingerprint:=encode(extensions.digest(jsonb_build_array(p_date,p_start_name,p_start_lat,p_start_lng,p_end_name,p_end_lat,p_end_lng,
    p_expected_version)::text,'sha256'),'hex');
  perform 1 from public.couples where id=space for update;
  select * into existing from public.meeting_routes where couple_id=space and date=p_date;
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
    return query update public.meeting_routes set start_name=btrim(p_start_name),
      start_lat=p_start_lat,start_lng=p_start_lng,end_name=btrim(p_end_name),
      end_lat=p_end_lat,end_lng=p_end_lng,version=version+1,
      updated_by=actor,updated_at=clock_timestamp(),last_request_id=p_request_id,
      last_fingerprint=fingerprint where couple_id=space and date=p_date returning *;
  else
    if p_expected_version<>0 then
      raise sqlstate 'PT409' using message='version_conflict';
    end if;
    return query insert into public.meeting_routes(couple_id,date,start_name,start_lat,start_lng,end_name,end_lat,end_lng,version,updated_by,
      last_request_id,last_fingerprint)
      values(space,p_date,p_start_name,p_start_lat,p_start_lng,p_end_name,p_end_lat,p_end_lng,1,actor,p_request_id,fingerprint) returning *;
  end if;
end $$;
revoke all on function public.save_meeting_route(date,text,double precision,double precision,text,double precision,double precision,integer,uuid)
  from public,anon,authenticated;
grant execute on function public.save_meeting_route(date,text,double precision,double precision,text,double precision,double precision,integer,uuid) to authenticated;
notify pgrst,'reload schema';
commit;
