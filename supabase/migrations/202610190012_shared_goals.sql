begin;

create function we2day_private.valid_goal_steps(steps jsonb) returns boolean
language plpgsql immutable set search_path='' as $$
declare step jsonb; ids text[]:='{}'; step_id text;
begin
  if steps is null or jsonb_typeof(steps)<>'array' then return false; end if;
  if jsonb_array_length(steps)>50 or octet_length(steps::text)>65536 then return false; end if;
  for step in select value from jsonb_array_elements(steps) loop
    if jsonb_typeof(step)<>'object' then return false; end if;
    if (select count(*) from jsonb_object_keys(step))<>3
      or not (step ?& array['id','title','done'])
      or jsonb_typeof(step->'id')<>'string'
      or jsonb_typeof(step->'title')<>'string'
      or jsonb_typeof(step->'done')<>'boolean' then return false; end if;
    step_id:=lower(step->>'id');
    if step_id !~ '^[0-9a-f]{8}-([0-9a-f]{4}-){3}[0-9a-f]{12}$'
      or step_id=any(ids) or char_length(btrim(step->>'title')) not between 1 and 100
      then return false; end if;
    ids:=array_append(ids,step_id);
  end loop;
  return true;
end $$;
revoke all on function we2day_private.valid_goal_steps(jsonb) from public,anon,authenticated;

create table public.shared_goals (
  id uuid primary key,
  couple_id uuid not null references public.couples(id),
  title text not null check(char_length(btrim(title)) between 1 and 100),
  target_date date check(target_date between date '2000-01-01' and date '2100-12-31'),
  steps jsonb not null check(we2day_private.valid_goal_steps(steps)),
  completed boolean not null default false,
  archived boolean not null default false,
  version integer not null check(version>0),
  updated_by uuid not null references auth.users(id),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  last_request_id uuid not null,
  last_fingerprint text not null
);
create index shared_goals_space on public.shared_goals(couple_id,archived,updated_at desc,id);
alter table public.shared_goals enable row level security;
revoke all on public.shared_goals from public,anon,authenticated;
grant select on public.shared_goals to authenticated;
create policy shared_goals_read on public.shared_goals for select to authenticated
  using(couple_id=(select we2day_private.my_couple()));

create function public.save_goal(p_id uuid,p_title text,p_target_date date,p_steps jsonb,
  p_completed boolean,p_archived boolean,p_expected_version integer,p_request_id uuid)
returns setof public.shared_goals language plpgsql security definer set search_path='' as $$
declare actor uuid:=we2day_private.actor(); space uuid:=we2day_private.my_couple();
  saved public.shared_goals; fingerprint text;
begin
  if space is null then raise sqlstate 'PT409' using message='couple_required'; end if;
  if p_id is null or p_title is null or char_length(btrim(p_title)) not between 1 and 100
    or (p_target_date is not null and
      (not isfinite(p_target_date) or p_target_date not between date '2000-01-01' and date '2100-12-31'))
    or not we2day_private.valid_goal_steps(p_steps) or p_completed is null or p_archived is null
    or p_expected_version is null or p_expected_version not between 0 and 2147483646
    or p_request_id is null then raise sqlstate 'PT422' using message='invalid_goal'; end if;
  fingerprint:=encode(extensions.digest(jsonb_build_array(p_id,p_title,p_target_date,p_steps,
    p_completed,p_archived,p_expected_version)::text,'sha256'),'hex');
  perform 1 from public.couples where id=space for update;
  select * into saved from public.shared_goals where id=p_id and couple_id=space for update;
  if not found then
    if exists(select 1 from public.shared_goals where id=p_id) then
      raise sqlstate 'PT404' using message='goal_not_found'; end if;
    if p_expected_version<>0 then raise sqlstate 'PT409' using message='version_conflict'; end if;
    return query insert into public.shared_goals
      (id,couple_id,title,target_date,steps,completed,archived,version,updated_by,
        last_request_id,last_fingerprint)
      values(p_id,space,btrim(p_title),p_target_date,p_steps,p_completed,p_archived,1,actor,
        p_request_id,fingerprint) returning *;
    return;
  end if;
  if saved.last_request_id=p_request_id then
    if saved.updated_by<>actor or saved.last_fingerprint<>fingerprint then
      raise sqlstate 'PT409' using message='request_conflict'; end if;
    return next saved; return;
  end if;
  if saved.version<>p_expected_version then
    raise sqlstate 'PT409' using message='version_conflict'; end if;
  if exists(select 1 from jsonb_array_elements(saved.steps) old_step where not exists
    (select 1 from jsonb_array_elements(p_steps) new_step
      where lower(new_step->>'id')=lower(old_step->>'id'))) then
    raise sqlstate 'PT422' using message='goal_steps_retained'; end if;
  return query update public.shared_goals set title=btrim(p_title),target_date=p_target_date,
    steps=p_steps,completed=p_completed,archived=p_archived,version=version+1,updated_by=actor,
    updated_at=clock_timestamp(),last_request_id=p_request_id,last_fingerprint=fingerprint
    where id=p_id returning *;
end $$;
revoke all on function public.save_goal(uuid,text,date,jsonb,boolean,boolean,integer,uuid)
  from public,anon,authenticated;
grant execute on function public.save_goal(uuid,text,date,jsonb,boolean,boolean,integer,uuid)
  to authenticated;
notify pgrst,'reload schema';
commit;
