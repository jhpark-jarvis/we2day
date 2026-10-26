begin;
-- Existing keys remain read/new-draft only. Scope cannot be changed through table grants.
alter table public.agent_connections add column can_manage boolean not null default false;
grant select(can_manage) on public.agent_connections to authenticated;
create function public.create_managed_agent_connection(p_label text,p_manage boolean) returns jsonb
language plpgsql security definer set search_path='' as $$
declare result jsonb;
begin
 if p_manage is null then raise sqlstate 'PT422' using message='invalid_agent_scope'; end if;
 result:=public.create_agent_connection(p_label);
 update public.agent_connections set can_manage=p_manage where id=(result->>'id')::uuid;
 return result||jsonb_build_object('can_manage',p_manage);
end $$;
revoke all on function public.create_managed_agent_connection(text,boolean) from public,anon;
grant execute on function public.create_managed_agent_connection(text,boolean) to authenticated;

-- Request receipts survive target deletion and never store content or raw credentials.
create table we2day_private.agent_changes (
 connection_id uuid not null references public.agent_connections(id) on delete cascade,
 request_id uuid not null, couple_id uuid not null references public.couples(id),
 target_id uuid not null, entity text not null check(entity in ('plan','appointment')),
 action text not null, fingerprint text not null, result jsonb not null,
 created_at timestamptz not null default now(), primary key(connection_id,request_id)
);
alter table we2day_private.agent_changes enable row level security;
revoke all on we2day_private.agent_changes from public,anon,authenticated;
create index agent_changes_daily on we2day_private.agent_changes(couple_id,created_at);

-- Minimal projection for one shared appointment; no identity/profile or personal schedules.
create function public.agent_appointment(p_key text,p_id uuid) returns jsonb
language plpgsql security definer set search_path='' as $$
declare item public.agent_connections:=we2day_private.authorize_agent(p_key); result jsonb;
begin
 select jsonb_build_object('id',a.id,'title',a.title,'date',a.date,'time',a.time,
 'place',a.place,'note',a.note,'version',a.version,'plan_id',p.id)
 into result from public.appointments a left join public.date_plans p on p.appointment_id=a.id
 where a.id=p_id and a.couple_id=item.couple_id and a.kind='shared';
 if result is null then raise sqlstate 'PT404' using message='appointment_not_found'; end if;
 return result;
end $$;
revoke all on function public.agent_appointment(text,uuid) from public;
grant execute on function public.agent_appointment(text,uuid) to anon,authenticated;

-- Delegate existing plan invariants only after key authorization. Claims are transaction local
-- and restored before return; no caller-supplied user/couple identity is accepted.
create function public.agent_change(p_key text,p_entity text,p_id uuid,p_action text,
 p_content jsonb,p_expected_version integer,p_expected_appointment_version integer,
 p_request_id uuid,p_confirmed boolean default false) returns jsonb
language plpgsql security definer set search_path='' as $$
declare item public.agent_connections:=we2day_private.authorize_agent(p_key);
 prior we2day_private.agent_changes; fp text; result jsonb; plan public.date_plans;
 appt public.appointments; previous_sub text; previous_claims text;
begin
 if not item.can_manage then raise sqlstate 'PT403' using message='agent_manage_required'; end if;
 if p_entity is null or p_entity not in ('plan','appointment') or p_id is null
 or p_request_id is null or p_action is null or p_expected_version is null
 or p_expected_version not between 0 and 2147483646
 or p_expected_appointment_version is null or p_expected_appointment_version not between 0 and 2147483646
 or p_confirmed is null
 or (p_entity='plan' and p_action not in ('save','confirm','archive','restore'))
 or (p_entity='appointment' and p_action not in ('create','update','delete')) then
  raise sqlstate 'PT422' using message='invalid_agent_change'; end if;
 if p_action in ('confirm','archive','delete') and not p_confirmed then
  raise sqlstate 'PT422' using message='confirmation_required'; end if;
 if (p_action in ('save','create','update')) <> (p_content is not null) then
  raise sqlstate 'PT422' using message='invalid_agent_change'; end if;
 fp:=encode(extensions.digest(jsonb_build_array(p_entity,p_id,p_action,p_content,
 p_expected_version,p_expected_appointment_version,p_confirmed)::text,'sha256'),'hex');
 perform 1 from public.couples where id=item.couple_id for update;
 select * into prior from we2day_private.agent_changes where connection_id=item.id and request_id=p_request_id;
 if found then
  if prior.fingerprint<>fp then raise sqlstate 'PT409' using message='request_conflict'; end if;
  return prior.result||jsonb_build_object('replayed',true);
 end if;
 if (select count(*) from we2day_private.agent_changes where couple_id=item.couple_id
 and (created_at at time zone 'Asia/Seoul')::date=(now() at time zone 'Asia/Seoul')::date)>=100 then
  raise sqlstate 'PT429' using message='agent_change_limit'; end if;
 if p_entity='plan' then
  -- New plans must use the bounded new-draft endpoint, not save(version=0).
  select * into plan from public.date_plans where id=p_id and couple_id=item.couple_id for update;
  if not found then raise sqlstate 'PT404' using message='plan_not_found'; end if;
  previous_sub:=current_setting('request.jwt.claim.sub',true);
  previous_claims:=current_setting('request.jwt.claims',true);
  perform set_config('request.jwt.claim.sub',item.user_id::text,true);
  perform set_config('request.jwt.claims',jsonb_build_object('sub',item.user_id,'role','authenticated')::text,true);
  select * into plan from public.change_date_plan(p_id,p_action,p_content,p_expected_version,
    p_expected_appointment_version,p_request_id);
  perform set_config('request.jwt.claim.sub',coalesce(previous_sub,''),true);
  perform set_config('request.jwt.claims',coalesce(previous_claims,''),true);
  result:=jsonb_build_object('id',plan.id,'version',plan.version,'archived',plan.archived,
   'published_revision',plan.published_revision,'appointment_id',plan.appointment_id);
 else
  select * into appt from public.appointments where id=p_id for update;
  if found then
   if appt.couple_id<>item.couple_id or appt.kind<>'shared' then
    raise sqlstate 'PT404' using message='appointment_not_found'; end if;
   if p_action='create' then raise sqlstate 'PT409' using message='request_conflict'; end if;
   if exists(select 1 from public.date_plans where appointment_id=p_id) then
    raise sqlstate 'PT409' using message='linked_plan_required'; end if;
   if appt.version<>p_expected_version then raise sqlstate 'PT409' using message='version_conflict'; end if;
  elsif p_action<>'create' then raise sqlstate 'PT404' using message='appointment_not_found';
  end if;
  if p_action='delete' then
   delete from public.appointments where id=p_id;
   result:=jsonb_build_object('id',p_id,'deleted',true);
  else
   if jsonb_typeof(p_content) is distinct from 'object'
   or not (p_content ?& array['title','date','time','place','note'])
   or (p_content-array['title','date','time','place','note'])<>'{}'::jsonb
   or jsonb_typeof(p_content->'title') is distinct from 'string'
   or jsonb_typeof(p_content->'date') is distinct from 'string'
   or jsonb_typeof(p_content->'place') is distinct from 'string'
   or jsonb_typeof(p_content->'note') is distinct from 'string'
   or jsonb_typeof(p_content->'time') not in ('string','null')
   or ((p_content->>'time') is not null and (p_content->>'time') !~ '^([01][0-9]|2[0-3]):[0-5][0-9]$') then
    raise sqlstate 'PT422' using message='invalid_appointment'; end if;
   perform we2day_private.validate_appointment(p_content->>'title',(p_content->>'date')::date,
     (p_content->>'time')::time,p_content->>'place',p_content->>'note');
   if p_action='create' then
    if p_expected_version<>0 then raise sqlstate 'PT409' using message='version_conflict'; end if;
    insert into public.appointments(id,couple_id,title,date,time,place,note,created_by,updated_by,
      request_id,creation_fingerprint) values(p_id,item.couple_id,btrim(p_content->>'title'),
      (p_content->>'date')::date,(p_content->>'time')::time,p_content->>'place',p_content->>'note',
      item.user_id,item.user_id,p_request_id,fp) returning * into appt;
   else
    update public.appointments set title=btrim(p_content->>'title'),date=(p_content->>'date')::date,
      time=(p_content->>'time')::time,place=p_content->>'place',note=p_content->>'note',
      version=version+1,updated_by=item.user_id,updated_at=clock_timestamp()
      where id=p_id returning * into appt;
   end if;
   result:=jsonb_build_object('id',appt.id,'version',appt.version);
  end if;
 end if;
 insert into we2day_private.agent_changes(connection_id,request_id,couple_id,target_id,entity,action,fingerprint,result)
 values(item.id,p_request_id,item.couple_id,p_id,p_entity,p_action,fp,result);
 return result||jsonb_build_object('replayed',false);
exception when invalid_text_representation or datetime_field_overflow or numeric_value_out_of_range
 or unique_violation then raise sqlstate 'PT409' using message='request_conflict';
end $$;
revoke all on function public.agent_change(text,text,uuid,text,jsonb,integer,integer,uuid,boolean) from public;
grant execute on function public.agent_change(text,text,uuid,text,jsonb,integer,integer,uuid,boolean) to anon,authenticated;

-- Plan reads include linked version for conflict-safe explicit publication.
create or replace function public.agent_plan(p_key text,p_id uuid) returns jsonb
language plpgsql security definer set search_path='' as $$
declare item public.agent_connections:=we2day_private.authorize_agent(p_key); result jsonb;
begin
 select jsonb_build_object('id',p.id,'content',p.content,'published_content',p.published_content,
 'published_revision',p.published_revision,'version',p.version,'archived',p.archived,
 'appointment_id',p.appointment_id,'appointment_version',coalesce(a.version,0)) into result
 from public.date_plans p left join public.appointments a on a.id=p.appointment_id
 where p.id=p_id and p.couple_id=item.couple_id and (not p.archived or item.can_manage);
 if result is null then raise sqlstate 'PT404' using message='plan_not_found'; end if;
 return result;
end $$;
notify pgrst,'reload schema';
commit;
