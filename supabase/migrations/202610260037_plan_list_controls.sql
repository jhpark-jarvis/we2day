begin;
-- Keep the old two-argument projection for existing clients.
create function public.list_plan_summaries(p_archived boolean,p_offset integer,p_sort text)
returns table(id uuid,title text,date date,transport text,activity_count integer,status text,archived boolean)
language plpgsql stable security invoker set search_path='' as $$
begin
  if p_archived is null or p_offset is null or p_offset not between 0 and 100000
    or p_sort is null or p_sort not in ('date_desc','date_asc','updated_desc','title_asc') then
    raise sqlstate 'PT422' using message='invalid_plan';
  end if;
  return query select p.id,p.content->>'title',(p.content->>'date')::date,
    coalesce(p.content->>'transport',''),jsonb_array_length(p.content->'activities'),
    case when p.archived then 'archived' when p.published_content is null then 'draft'
      when p.content=p.published_content then 'confirmed' else 'changed' end,p.archived
    from public.date_plans p where p.archived=p_archived
    order by
      case when p_sort='date_desc' then (p.content->>'date')::date end desc,
      case when p_sort='date_asc' then (p.content->>'date')::date end asc,
      case when p_sort='updated_desc' then p.updated_at end desc,
      case when p_sort='title_asc' then p.content->>'title' end asc,
      p.id asc limit 50 offset p_offset;
end $$;
revoke all on function public.list_plan_summaries(boolean,integer,text) from public,anon;
grant execute on function public.list_plan_summaries(boolean,integer,text) to authenticated;

-- Only never-published drafts. Row lock and version protect a concurrent confirmation/edit.
create function public.delete_plan_draft(p_id uuid,p_expected_version integer) returns void
language plpgsql security definer set search_path='' as $$
declare space uuid; item public.date_plans;
begin
  if auth.uid() is null then raise sqlstate 'PT403' using message='couple_required'; end if;
  select couple_id into space from public.couple_members where user_id=auth.uid();
  if space is null then raise sqlstate 'PT403' using message='couple_required'; end if;
  if p_id is null or p_expected_version is null or p_expected_version<1 then
    raise sqlstate 'PT422' using message='invalid_plan';
  end if;
  select * into item from public.date_plans where id=p_id and couple_id=space for update;
  if not found then return; end if;
  if item.version<>p_expected_version then
    raise sqlstate 'PT409' using message='version_conflict';
  end if;
  if item.published_content is not null or item.appointment_id is not null
    or item.published_revision<>0 then
    raise sqlstate 'PT409' using message='plan_draft_required';
  end if;
  delete from public.date_plans where id=item.id;
end $$;
revoke all on function public.delete_plan_draft(uuid,integer) from public,anon;
grant execute on function public.delete_plan_draft(uuid,integer) to authenticated;
notify pgrst,'reload schema';
commit;
