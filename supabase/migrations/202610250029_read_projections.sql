begin;

-- Projection at the database boundary; the caller's existing SELECT RLS still applies.
create function public.list_plan_summaries(p_archived boolean default false,p_offset integer default 0)
returns table(id uuid,title text,date date,transport text,activity_count integer,status text,archived boolean)
language plpgsql stable security invoker set search_path='' as $$
begin
  if p_archived is null or p_offset is null or p_offset not between 0 and 100000 then
    raise sqlstate 'PT422' using message='invalid_plan';
  end if;
  return query select p.id,p.content->>'title',(p.content->>'date')::date,
    coalesce(p.content->>'transport',''),jsonb_array_length(p.content->'activities'),
    case when p.archived then 'archived' when p.published_content is null then 'draft'
      when p.content=p.published_content then 'confirmed' else 'changed' end,p.archived
    from public.date_plans p where p.archived=p_archived
    order by p.updated_at desc,p.id asc limit 50 offset p_offset;
end $$;

create function public.photo_album_dates(p_month date)
returns table(date date,count bigint)
language plpgsql stable security invoker set search_path='' as $$
begin
  if p_month is null or p_month not between date '2000-01-01' and date '2100-12-01'
    or extract(day from p_month)<>1 then
    raise sqlstate 'PT422' using message='invalid_photo_search';
  end if;
  return query select p.date,count(*) from public.photos p
    where p.uploaded_at is not null and p.trashed_at is null and p.purging_at is null
      and p.date>=p_month and p.date<(p_month+interval '1 month')::date
    group by p.date order by p.date;
end $$;

revoke all on function public.list_plan_summaries(boolean,integer),public.photo_album_dates(date)
  from public,anon,authenticated;
grant execute on function public.list_plan_summaries(boolean,integer),public.photo_album_dates(date)
  to authenticated;
notify pgrst,'reload schema';
commit;
