begin;

-- A publication changes only when confirmed content changes, never on draft edits.
alter table public.date_plans add column published_revision integer not null default 0
  check(published_revision>=0);
update public.date_plans set published_revision=1 where published_content is not null;

create function we2day_private.track_plan_publication() returns trigger
language plpgsql set search_path='' as $$
begin
  if tg_op='INSERT' then
    new.published_revision:=case when new.published_content is null then 0 else 1 end;
  elsif new.published_content is distinct from old.published_content then
    new.published_revision:=old.published_revision+1;
  else
    new.published_revision:=old.published_revision;
  end if;
  return new;
end $$;
revoke all on function we2day_private.track_plan_publication() from public,anon,authenticated;
create trigger date_plan_publication before insert or update on public.date_plans
  for each row execute function we2day_private.track_plan_publication();

create table public.plan_visit_progress (
  plan_id uuid not null references public.date_plans(id),
  publication integer not null check(publication>0),
  couple_id uuid not null references public.couples(id),
  snapshot jsonb not null,
  states text[] not null check(array_ndims(states)=1 and cardinality(states) between 1 and 20
    and array_position(states,null) is null and states <@ array['planned','visited','skipped']
    and cardinality(states)=jsonb_array_length(snapshot->'activities')),
  version integer not null check(version>0),
  updated_by uuid not null references auth.users(id),
  updated_at timestamptz not null default now(),
  last_request_id uuid not null,
  last_fingerprint text not null,
  primary key(plan_id,publication)
);
alter table public.plan_visit_progress enable row level security;
revoke all on public.plan_visit_progress from public,anon,authenticated;
grant select on public.plan_visit_progress to authenticated;
create policy plan_visit_progress_read on public.plan_visit_progress for select to authenticated
  using(couple_id=(select we2day_private.my_couple()));

create function public.change_visit_progress(p_plan_id uuid,p_publication integer,
  p_activity integer,p_state text,p_expected_version integer,p_request_id uuid)
returns setof public.plan_visit_progress
language plpgsql security definer set search_path='' as $$
declare actor uuid:=we2day_private.actor(); space uuid:=we2day_private.my_couple();
  plan public.date_plans; saved public.plan_visit_progress; fingerprint text; values_ text[];
begin
  if space is null then raise sqlstate 'PT409' using message='couple_required'; end if;
  if p_plan_id is null or p_publication is null or p_publication<1
    or p_activity is null or p_activity not between 0 and 19
    or p_state is null or p_state not in ('planned','visited','skipped')
    or p_expected_version is null or p_expected_version not between 0 and 2147483646
    or p_request_id is null then
    raise sqlstate 'PT422' using message='invalid_visit_progress';
  end if;
  fingerprint:=encode(extensions.digest(jsonb_build_array(p_plan_id,p_publication,
    p_activity,p_state,p_expected_version)::text,'sha256'),'hex');
  -- Same lock order as plan confirmation; stale publications cannot receive writes.
  perform 1 from public.couples where id=space for update;
  select * into plan from public.date_plans where id=p_plan_id and couple_id=space for update;
  if not found then raise sqlstate 'PT404' using message='plan_not_found'; end if;
  select * into saved from public.plan_visit_progress
    where plan_id=p_plan_id and publication=p_publication and couple_id=space for update;
  if found and saved.last_request_id=p_request_id then
    if saved.updated_by<>actor or saved.last_fingerprint<>fingerprint then
      raise sqlstate 'PT409' using message='request_conflict'; end if;
    return next saved; return;
  end if;
  if plan.published_content is null or plan.published_revision<>p_publication then
    raise sqlstate 'PT409' using message='publication_changed'; end if;
  if plan.archived then raise sqlstate 'PT409' using message='plan_archived'; end if;
  if (plan.published_content->>'date')::date>(now() at time zone 'Asia/Seoul')::date
    or p_activity>=jsonb_array_length(plan.published_content->'activities') then
    raise sqlstate 'PT422' using message='invalid_visit_progress'; end if;
  if saved.plan_id is null then
    if p_expected_version<>0 then
      raise sqlstate 'PT409' using message='version_conflict'; end if;
    values_:=array_fill('planned'::text,array[jsonb_array_length(plan.published_content->'activities')]);
    values_[p_activity+1]:=p_state;
    return query insert into public.plan_visit_progress
      (plan_id,publication,couple_id,snapshot,states,version,updated_by,last_request_id,last_fingerprint)
      values(p_plan_id,p_publication,space,plan.published_content,values_,1,actor,p_request_id,fingerprint)
      returning *;
  else
    if saved.version<>p_expected_version then
      raise sqlstate 'PT409' using message='version_conflict'; end if;
    values_:=saved.states; values_[p_activity+1]:=p_state;
    return query update public.plan_visit_progress set states=values_,version=version+1,
      updated_by=actor,updated_at=clock_timestamp(),last_request_id=p_request_id,
      last_fingerprint=fingerprint where plan_id=p_plan_id and publication=p_publication returning *;
  end if;
end $$;
revoke all on function public.change_visit_progress(uuid,integer,integer,text,integer,uuid)
  from public,anon,authenticated;
grant execute on function public.change_visit_progress(uuid,integer,integer,text,integer,uuid)
  to authenticated;
notify pgrst,'reload schema';
commit;
