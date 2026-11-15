begin;
-- One caller-scoped read snapshot for status totals and the selected page.
create function public.wishlist_overview(p_view text default 'planned',p_offset integer default 0)
returns jsonb language plpgsql stable security invoker set search_path='' as $$
declare totals jsonb; page_items jsonb;
begin
  if auth.uid() is null then raise sqlstate 'PT401' using message='authentication_required'; end if;
  if p_view is null or p_view not in ('planned','done','archived') or p_offset is null
    or p_offset not between 0 and 100000 then
    raise sqlstate 'PT422' using message='invalid_wish';
  end if;
  select jsonb_build_object(
    'planned',count(*) filter(where not w.archived and not w.done),
    'done',count(*) filter(where not w.archived and w.done),
    'archived',count(*) filter(where w.archived)) into totals
  from public.wishes w where w.couple_id=(select we2day_private.my_couple());
  select coalesce(jsonb_agg(to_jsonb(r) order by r.updated_at desc,r.id),'[]'::jsonb)
    into page_items from (
      select w.id,w.title,w.kind,w.note,w.place,w.map_url,w.done,w.archived,
        w.version,w.updated_by,w.updated_at
      from public.wishes w where w.couple_id=(select we2day_private.my_couple()) and
        case p_view when 'archived' then w.archived
          when 'done' then not w.archived and w.done
          else not w.archived and not w.done end
      order by w.updated_at desc,w.id offset p_offset limit 50
    ) r;
  return jsonb_build_object('items',page_items,'counts',totals,
    'has_more',(totals->>p_view)::bigint>p_offset+jsonb_array_length(page_items));
end $$;
revoke all on function public.wishlist_overview(text,integer) from public,anon,authenticated;
grant execute on function public.wishlist_overview(text,integer) to authenticated;
notify pgrst,'reload schema';
commit;
