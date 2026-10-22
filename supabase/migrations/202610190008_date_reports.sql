begin;

create function we2day_private.validate_report(c jsonb) returns void
language plpgsql set search_path='' as $$
declare v jsonb; k text;
begin
  if c is null or jsonb_typeof(c) is distinct from 'object' or octet_length(c::text)>65536
    or not(c ?& array['summary','visits','actual_cost','highlights','next_time','revisit'])
    or (c-array['summary','visits','actual_cost','highlights','next_time','revisit'])<>'{}'::jsonb then
    raise sqlstate 'PT422' using message='invalid_report';
  end if;
  foreach k in array array['summary','highlights','next_time'] loop
    if jsonb_typeof(c->k) is distinct from 'string' or char_length(c->>k)>2000 then
      raise sqlstate 'PT422' using message='invalid_report';
    end if;
  end loop;
  if char_length(btrim(c->>'summary'))=0
    or jsonb_typeof(c->'visits') is distinct from 'array' or jsonb_array_length(c->'visits')>20
    or jsonb_typeof(c->'actual_cost') not in ('null','number')
    or (c->>'actual_cost' is not null and ((c->>'actual_cost') !~ '^[0-9]{1,10}$'
      or (c->>'actual_cost')::numeric>1000000000))
    or jsonb_typeof(c->'revisit') not in ('null','boolean') then
    raise sqlstate 'PT422' using message='invalid_report';
  end if;
  for v in select value from jsonb_array_elements(c->'visits') loop
    if jsonb_typeof(v) is distinct from 'string' or char_length(btrim(v#>>'{}')) not between 1 and 200 then
      raise sqlstate 'PT422' using message='invalid_report';
    end if;
  end loop;
exception when invalid_text_representation or numeric_value_out_of_range or invalid_parameter_value then
  raise sqlstate 'PT422' using message='invalid_report';
end $$;
revoke all on function we2day_private.validate_report(jsonb) from public,anon,authenticated;

create table public.date_reports (
  plan_id uuid not null references public.date_plans(id),
  author_id uuid not null references auth.users(id),
  couple_id uuid not null references public.couples(id),
  observed_plan_version integer not null check(observed_plan_version>0),
  plan_snapshot jsonb not null,
  content jsonb not null,
  shared boolean not null default false,
  version integer not null check(version>0),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  last_request_id uuid not null,
  last_fingerprint text not null,
  primary key(plan_id,author_id)
);
create index date_reports_space on public.date_reports(couple_id,plan_id);
alter table public.date_reports enable row level security;
revoke all on public.date_reports from public,anon,authenticated;
grant select on public.date_reports to authenticated;
create policy date_reports_read on public.date_reports for select to authenticated
  using(couple_id=(select we2day_private.my_couple())
    and (author_id=(select auth.uid()) or shared));

create function public.save_date_report(p_plan_id uuid,p_content jsonb,p_shared boolean,
  p_expected_version integer,p_request_id uuid) returns setof public.date_reports
language plpgsql security definer set search_path='' as $$
declare actor uuid:=we2day_private.actor(); space uuid:=we2day_private.my_couple();
  report public.date_reports; plan public.date_plans; fingerprint text;
begin
  if space is null then raise sqlstate 'PT409' using message='couple_required'; end if;
  if p_plan_id is null or p_shared is null or p_request_id is null or p_expected_version is null
    or p_expected_version not between 0 and 2147483646 then
    raise sqlstate 'PT422' using message='invalid_report';
  end if;
  perform we2day_private.validate_report(p_content);
  fingerprint:=encode(extensions.digest(jsonb_build_array(p_plan_id,p_content,p_shared,
    p_expected_version)::text,'sha256'),'hex');
  perform 1 from public.couples where id=space for update;
  select * into plan from public.date_plans where id=p_plan_id and couple_id=space for update;
  if not found then raise sqlstate 'PT404' using message='plan_not_found'; end if;
  select * into report from public.date_reports where plan_id=p_plan_id and author_id=actor for update;
  if found then
    if report.last_request_id=p_request_id then
      if report.last_fingerprint<>fingerprint then
        raise sqlstate 'PT409' using message='request_conflict';
      end if;
      return next report; return;
    end if;
    if report.version<>p_expected_version then
      raise sqlstate 'PT409' using message='version_conflict';
    end if;
    return query update public.date_reports set content=p_content,shared=p_shared,
      version=version+1,updated_at=clock_timestamp(),last_request_id=p_request_id,
      last_fingerprint=fingerprint where plan_id=p_plan_id and author_id=actor returning *;
    return;
  end if;
  if p_expected_version<>0 then raise sqlstate 'PT409' using message='version_conflict'; end if;
  if plan.published_content is null
    or (plan.published_content->>'date')::date>(clock_timestamp() at time zone 'Asia/Seoul')::date then
    raise sqlstate 'PT409' using message='report_not_ready';
  end if;
  return query insert into public.date_reports(plan_id,author_id,couple_id,observed_plan_version,
    plan_snapshot,content,shared,version,last_request_id,last_fingerprint)
    values(p_plan_id,actor,space,plan.version,plan.published_content,p_content,p_shared,1,
      p_request_id,fingerprint) returning *;
end $$;
revoke all on function public.save_date_report(uuid,jsonb,boolean,integer,uuid)
  from public,anon,authenticated;
grant execute on function public.save_date_report(uuid,jsonb,boolean,integer,uuid) to authenticated;
notify pgrst,'reload schema';
commit;
