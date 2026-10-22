begin;

-- Existing visibility only: caller JWT, invoker rights and each table's RLS.
create function public.search_records(p_kind text,p_start date,p_end date,p_query text,
  p_archived boolean default false,p_offset integer default 0)
returns table(id uuid,date date,title text,excerpt text,state text,visibility text)
language plpgsql stable security invoker set search_path='' as $$
begin
  if auth.uid() is null then raise sqlstate 'PT401' using message='authentication_required'; end if;
  if we2day_private.my_couple() is null then
    raise sqlstate 'PT409' using message='couple_required'; end if;
  if p_kind is null or p_kind not in ('appointment','plan','report','wish')
    or p_start is null or p_end is null or p_start<date '2000-01-01'
    or p_end>date '2100-12-31' or p_end<p_start or p_end-p_start>365
    or p_query is null or length(p_query)>100 or p_query ~ '[[:cntrl:]]'
    or p_archived is null or p_offset is null or p_offset<0 or p_offset>100000 then
    raise sqlstate 'PT422' using message='invalid_record_search'; end if;
  return query
  with records as (
    select a.id,a.date,a.title,concat_ws(' · ',a.place,a.note) as body,
      'appointment'::text as state,null::text as visibility
      from public.appointments a where p_kind='appointment'
    union all
    select p.id,(p.content->>'date')::date,p.content->>'title',
      concat_ws(' · ',p.content->>'transport',
        (select string_agg(concat_ws(' · ',v->>'title',v->>'place',v->>'note'),' · ')
          from jsonb_array_elements(p.content->'activities') v),
        (select string_agg(v,' · ') from jsonb_array_elements_text(p.content->'preparation') v)),
      case when p.archived then 'archived' when p.published_content is null then 'draft'
        when p.content=p.published_content then 'confirmed' else 'changed' end,null::text
      from public.date_plans p where p_kind='plan' and (p_archived or not p.archived)
    union all
    select r.plan_id,(r.plan_snapshot->>'date')::date,r.plan_snapshot->>'title',
      concat_ws(' · ',r.content->>'summary',r.content->>'highlights',r.content->>'next_time',
        (select string_agg(v,' · ') from jsonb_array_elements_text(r.content->'visits') v)),
      'report',case when r.author_id=auth.uid() then
        case when r.shared then 'own_shared' else 'own_private' end else 'partner_shared' end
      from public.date_reports r where p_kind='report'
    union all
    select w.id,(w.created_at at time zone 'Asia/Seoul')::date,w.title,w.note,
      case when w.archived then 'archived' when w.done then 'done' else 'active' end,null::text
      from public.wishes w where p_kind='wish' and (p_archived or not w.archived)
  )
  select r.id,r.date,r.title,left(r.body,280),r.state,r.visibility from records r
    where r.date between p_start and p_end
      and strpos(lower(concat_ws(' · ',r.title,r.body)),lower(btrim(p_query)))>0
    order by r.date desc,r.id,r.visibility nulls first limit 51 offset p_offset;
end $$;
revoke all on function public.search_records(text,date,date,text,boolean,integer)
  from public,anon,authenticated;
grant execute on function public.search_records(text,date,date,text,boolean,integer) to authenticated;
notify pgrst,'reload schema';
commit;
