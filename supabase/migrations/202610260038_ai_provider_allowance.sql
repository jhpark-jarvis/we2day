begin;
-- Workers Free enforces the provider's daily neuron allocation, not a fixed request count.
-- Retain the existing private daily counter and cross-process burst protection.
alter table we2day_private.ai_planner_budget
  drop constraint ai_planner_budget_requests_check;
alter table we2day_private.ai_planner_budget
  add constraint ai_planner_budget_requests_check check(requests>=0);
create or replace function public.reserve_ai_planner_request() returns boolean
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
    where we2day_private.ai_planner_budget.requests<2147483647
    and we2day_private.ai_planner_budget.last_request<clock_timestamp()-interval '5 seconds'
  returning requests into used;
  return used is not null;
end;
$$;
revoke all on function public.reserve_ai_planner_request() from public,anon;
grant execute on function public.reserve_ai_planner_request() to authenticated;
notify pgrst,'reload schema';
commit;
