begin;

-- Search shared prompts only. Never join answers or expose response state.
create function public.search_questions(
  p_start date, p_end date, p_query text, p_offset integer default 0
) returns table(id uuid, date date, prompt text)
language plpgsql stable security invoker set search_path='' as $$
begin
  if auth.uid() is null then
    raise sqlstate 'PT401' using message='authentication_required';
  end if;
  if we2day_private.my_couple() is null then
    raise sqlstate 'PT409' using message='couple_required';
  end if;
  if p_start is null or p_end is null
    or p_start < date '2000-01-01' or p_end > date '2100-12-31'
    or p_end < p_start or p_end-p_start > 365
    or p_query is null or length(p_query)>100 or p_query ~ '[[:cntrl:]]'
    or p_offset is null or p_offset<0 or p_offset>100000 then
    raise sqlstate 'PT422' using message='invalid_question_search';
  end if;
  return query select q.id,q.date,q.prompt from public.couple_questions q
    where q.date between p_start and p_end
      and strpos(lower(q.prompt),lower(btrim(p_query)))>0
    order by q.date desc,q.id limit 51 offset p_offset;
end $$;
revoke all on function public.search_questions(date,date,text,integer)
  from public,anon,authenticated;
grant execute on function public.search_questions(date,date,text,integer) to authenticated;
notify pgrst,'reload schema';
commit;
