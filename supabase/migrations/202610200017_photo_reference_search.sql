begin;

-- Existing reference metadata only; caller RLS and photo lifecycle still apply.
create function public.search_photo_references(
  p_start date, p_end date, p_query text, p_field text,
  p_uploader text, p_offset integer default 0
) returns table(
  id uuid, date date, caption text, filename text, device text,
  captured_at text, uploaded_at timestamptz, uploaded_by_me boolean
)
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
    or p_field is null or p_field not in ('caption','filename','device')
    or p_uploader is null or p_uploader not in ('all','mine','partner')
    or p_offset is null or p_offset<0 or p_offset>100000 then
    raise sqlstate 'PT422' using message='invalid_photo_search';
  end if;
  return query select p.id,p.date,p.caption,p.filename,p.device,p.captured_at,
      p.uploaded_at,p.created_by=auth.uid()
    from public.photos p
    where p.date between p_start and p_end and p.uploaded_at is not null
      and p.trashed_at is null and p.purging_at is null
      and (p_uploader='all' or (p_uploader='mine' and p.created_by=auth.uid())
        or (p_uploader='partner' and p.created_by<>auth.uid()))
      and strpos(lower(case p_field when 'caption' then p.caption
        when 'filename' then p.filename else coalesce(p.device,'') end),
        lower(btrim(p_query)))>0
    order by p.date desc,p.id limit 51 offset p_offset;
end $$;
revoke all on function public.search_photo_references(date,date,text,text,text,integer)
  from public,anon,authenticated;
grant execute on function public.search_photo_references(date,date,text,text,text,integer)
  to authenticated;
notify pgrst,'reload schema';
commit;
