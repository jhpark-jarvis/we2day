begin;

-- Caller-authored content only. No search/geocoder responses or actual visit inference.
create function we2day_private.validate_plan(c jsonb) returns void
language plpgsql set search_path='' as $$
declare a jsonb; d date;
begin
  if c is null or jsonb_typeof(c)<>'object' or octet_length(c::text)>32768
    or not (c ?& array['title','date','budget','transport','activities','preparation'])
    or (c-array['title','date','budget','transport','activities','preparation'])<>'{}'::jsonb
    or jsonb_typeof(c->'title')<>'string' or char_length(btrim(c->>'title')) not between 1 and 100
    or jsonb_typeof(c->'date')<>'string' or (c->>'date') !~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}$'
    or jsonb_typeof(c->'transport')<>'string' or char_length(c->>'transport')>40
    or jsonb_typeof(c->'activities')<>'array' or jsonb_array_length(c->'activities')>20
    or jsonb_typeof(c->'preparation')<>'array' or jsonb_array_length(c->'preparation')>30 then
    raise sqlstate 'PT422' using message='invalid_plan';
  end if;
  d:=(c->>'date')::date;
  if d not between date '2000-01-01' and date '2100-12-31'
    or jsonb_typeof(c->'budget') not in ('null','number')
    or (c->>'budget' is not null and ((c->>'budget') !~ '^[0-9]{1,10}$'
      or (c->>'budget')::numeric>1000000000)) then
    raise sqlstate 'PT422' using message='invalid_plan';
  end if;
  for a in select value from jsonb_array_elements(c->'activities') loop
    if jsonb_typeof(a)<>'object'
      or not (a ?& array['title','time','place','cost','note'])
      or (a-array['title','time','place','cost','note'])<>'{}'::jsonb
      or jsonb_typeof(a->'title')<>'string' or char_length(btrim(a->>'title')) not between 1 and 100
      or jsonb_typeof(a->'place')<>'string' or char_length(a->>'place')>200
      or jsonb_typeof(a->'note')<>'string' or char_length(a->>'note')>1000
      or (a->>'time' is not null and (a->>'time') !~ '^([01][0-9]|2[0-3]):[0-5][0-9]$')
      or jsonb_typeof(a->'cost') not in ('null','number')
      or (a->>'cost' is not null and ((a->>'cost') !~ '^[0-9]{1,10}$'
        or (a->>'cost')::numeric>1000000000)) then
      raise sqlstate 'PT422' using message='invalid_plan';
    end if;
  end loop;
  for a in select value from jsonb_array_elements(c->'preparation') loop
    if jsonb_typeof(a)<>'string' or char_length(btrim(a#>>'{}')) not between 1 and 200 then
      raise sqlstate 'PT422' using message='invalid_plan';
    end if;
  end loop;
exception when invalid_text_representation or datetime_field_overflow
  or numeric_value_out_of_range or invalid_parameter_value then
  raise sqlstate 'PT422' using message='invalid_plan';
end $$;
revoke all on function we2day_private.validate_plan(jsonb) from public,anon,authenticated;

create table public.date_plans (
  id uuid primary key,
  couple_id uuid not null references public.couples(id),
  content jsonb not null,
  published_content jsonb,
  appointment_id uuid unique references public.appointments(id),
  archived boolean not null default false,
  version integer not null check(version>0),
  created_by uuid not null references auth.users(id),
  updated_by uuid not null references auth.users(id),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  last_request_id uuid not null,
  last_fingerprint text not null,
  check((published_content is null)=(appointment_id is null))
);
create index date_plans_space on public.date_plans(couple_id,archived,updated_at desc,id);
alter table public.date_plans enable row level security;
revoke all on public.date_plans from public,anon,authenticated;
grant select on public.date_plans to authenticated;
create policy date_plans_read on public.date_plans for select to authenticated
  using(couple_id=(select we2day_private.my_couple()));

create function public.change_date_plan(p_id uuid,p_action text,p_content jsonb,
  p_expected_version integer,p_expected_appointment_version integer,p_request_id uuid)
returns setof public.date_plans
language plpgsql security definer set search_path='' as $$
declare actor uuid:=we2day_private.actor(); space uuid:=we2day_private.my_couple();
  existing public.date_plans; fingerprint text; appt public.appointments; first_activity jsonb;
begin
  if space is null then raise sqlstate 'PT409' using message='couple_required'; end if;
  if p_id is null or p_request_id is null or p_action is null
    or p_action not in ('save','confirm','archive','restore')
    or p_expected_version is null or p_expected_version not between 0 and 2147483646
    or p_expected_appointment_version is null or p_expected_appointment_version<0
    or (p_action<>'save' and p_content is not null) then
    raise sqlstate 'PT422' using message='invalid_plan';
  end if;
  if p_action='save' then perform we2day_private.validate_plan(p_content); end if;
  fingerprint:=encode(extensions.digest(jsonb_build_array(p_id,p_action,p_content,
    p_expected_version,p_expected_appointment_version)::text,'sha256'),'hex');
  perform 1 from public.couples where id=space for update;
  select * into existing from public.date_plans where id=p_id and couple_id=space for update;
  if not found then
    if p_action<>'save' or p_expected_version<>0 then
      raise sqlstate 'PT404' using message='plan_not_found';
    end if;
    -- A guessed ID from a different couple must not disclose or modify its content.
    if exists(select 1 from public.date_plans where id=p_id) then
      raise sqlstate 'PT404' using message='plan_not_found';
    end if;
    return query insert into public.date_plans(id,couple_id,content,version,created_by,
      updated_by,last_request_id,last_fingerprint)
      values(p_id,space,p_content,1,actor,actor,p_request_id,fingerprint) returning *;
    return;
  end if;
  if existing.last_request_id=p_request_id then
    if existing.updated_by<>actor or existing.last_fingerprint<>fingerprint then
      raise sqlstate 'PT409' using message='request_conflict';
    end if;
    return next existing; return;
  end if;
  if existing.version<>p_expected_version then
    raise sqlstate 'PT409' using message='version_conflict';
  end if;
  if existing.archived and p_action not in ('restore','archive') then
    raise sqlstate 'PT409' using message='plan_archived';
  end if;
  if p_action='confirm' then
    first_activity:=existing.content->'activities'->0;
    if existing.appointment_id is null then
      if p_expected_appointment_version<>0 then
        raise sqlstate 'PT409' using message='version_conflict';
      end if;
      -- Dedicated appointment ID avoids sharing an unrelated idempotency key namespace.
      insert into public.appointments(couple_id,title,date,time,place,note,created_by,
        updated_by,request_id,creation_fingerprint)
        values(space,btrim(existing.content->>'title'),(existing.content->>'date')::date,
          (first_activity->>'time')::time,coalesce(first_activity->>'place',''),
          '데이트 플랜에서 확정한 약속',actor,actor,gen_random_uuid(),fingerprint)
        returning * into appt;
    else
      select * into appt from public.appointments where id=existing.appointment_id and couple_id=space for update;
      select * into appt from public.update_appointment(existing.appointment_id,
        p_expected_appointment_version,btrim(existing.content->>'title'),
        (existing.content->>'date')::date,(first_activity->>'time')::time,
        coalesce(first_activity->>'place',''),appt.note);
    end if;
  end if;
  return query update public.date_plans set
    content=case when p_action='save' then p_content else content end,
    published_content=case when p_action='confirm' then content else published_content end,
    appointment_id=case when p_action='confirm' then appt.id else appointment_id end,
    archived=case when p_action='archive' then true when p_action='restore' then false else archived end,
    version=version+1,updated_by=actor,updated_at=clock_timestamp(),
    last_request_id=p_request_id,last_fingerprint=fingerprint where id=p_id returning *;
end $$;
revoke all on function public.change_date_plan(uuid,text,jsonb,integer,integer,uuid)
  from public,anon,authenticated;
grant execute on function public.change_date_plan(uuid,text,jsonb,integer,integer,uuid) to authenticated;
notify pgrst,'reload schema';
commit;
