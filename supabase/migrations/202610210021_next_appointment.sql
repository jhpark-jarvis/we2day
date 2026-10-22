begin;
-- Unknown time today remains a date-only candidate, never fabricated midnight.
create function public.get_next_appointment()
returns table(id uuid,title text,date date,"time" time,place text)
language plpgsql stable security invoker set search_path='' as $$
declare local_now timestamp := statement_timestamp() at time zone 'Asia/Seoul';
begin
  if auth.uid() is null then raise sqlstate 'PT401' using message='authentication_required'; end if;
  if we2day_private.my_couple() is null then
    raise sqlstate 'PT409' using message='couple_required'; end if;
  return query select a.id,a.title,a.date,a.time,a.place from public.appointments a
    where a.date>=local_now::date
      and (a.time is null or a.date+a.time>=local_now)
    order by a.date,a.time nulls last,a.id limit 1;
end $$;
revoke all on function public.get_next_appointment() from public,anon,authenticated;
grant execute on function public.get_next_appointment() to authenticated;
notify pgrst,'reload schema';
commit;
