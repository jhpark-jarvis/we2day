begin;
-- Global daily project allowance; no conversation, prompt, or model output retention.
create table we2day_private.ai_planner_budget (
  day date primary key,
  requests integer not null check(requests between 0 and 50),
  last_request timestamptz not null
);
alter table we2day_private.ai_planner_budget enable row level security;
revoke all on we2day_private.ai_planner_budget from public,anon,authenticated;

create function public.reserve_ai_planner_request() returns boolean
language plpgsql security definer set search_path='' as $$
declare used integer; d date := (now() at time zone 'UTC')::date;
begin
  if auth.uid() is null or public.get_my_couple() is null then
    raise sqlstate 'PT403' using message='couple_required';
  end if;
  insert into we2day_private.ai_planner_budget(day,requests,last_request)
    values(d,1,clock_timestamp())
  on conflict(day) do update set requests=we2day_private.ai_planner_budget.requests+1,
    last_request=clock_timestamp()
    where we2day_private.ai_planner_budget.requests<50
    and we2day_private.ai_planner_budget.last_request<clock_timestamp()-interval '5 seconds'
  returning requests into used;
  return used is not null;
end;
$$;
revoke all on function public.reserve_ai_planner_request() from public,anon;
grant execute on function public.reserve_ai_planner_request() to authenticated;
notify pgrst,'reload schema';
commit;
