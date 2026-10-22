begin;

-- Read-only aggregation under the caller's existing table RLS. No stored copies.
create function public.get_monthly_memories(p_month date) returns jsonb
language plpgsql stable security invoker set search_path='' as $$
declare result jsonb; finish date;
begin
  if auth.uid() is null then
    raise sqlstate 'PT401' using message='authentication_required';
  end if;
  if we2day_private.my_couple() is null then
    raise sqlstate 'PT409' using message='couple_required';
  end if;
  if p_month is null or p_month not between date '2000-01-01' and date '2100-12-01'
    or extract(day from p_month)<>1 then
    raise sqlstate 'PT422' using message='invalid_request';
  end if;
  finish:=(p_month+interval '1 month')::date;
  with events as (
    select date,1::bigint as met,0::bigint as photos,0::bigint as route
      from public.meeting_days where met and date>=p_month and date<finish
    union all
    select date,0,count(*),0 from public.photos
      where date>=p_month and date<finish and uploaded_at is not null
        and trashed_at is null and purging_at is null group by date
    union all
    select date,0,0,1 from public.meeting_routes where date>=p_month and date<finish
  ), days as (
    select date,bool_or(met>0) as met,sum(photos)::integer as photo_count,
      bool_or(route>0) as route_recorded from events group by date
  )
  select jsonb_build_object(
    'month',to_char(p_month,'YYYY-MM'),
    'meeting_count',count(*) filter(where met),
    'photo_count',coalesce(sum(photo_count),0),
    'route_count',count(*) filter(where route_recorded),
    'days',coalesce(jsonb_agg(to_jsonb(days) order by date),'[]'::jsonb),
    'photos',(select coalesce(jsonb_agg(to_jsonb(preview) order by preview.date desc,preview.id),'[]'::jsonb)
      from (select id,date,caption from public.photos where date>=p_month and date<finish
        and uploaded_at is not null and trashed_at is null and purging_at is null
        order by date desc,id limit 6) preview)
  ) into result from days;
  return result;
end $$;
revoke all on function public.get_monthly_memories(date) from public,anon,authenticated;
grant execute on function public.get_monthly_memories(date) to authenticated;
notify pgrst,'reload schema';
commit;
