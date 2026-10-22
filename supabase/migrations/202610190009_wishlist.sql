begin;
-- User-authored text only, independent of provider search responses.
create table public.wishes (
  id uuid primary key,
  couple_id uuid not null references public.couples(id),
  title text not null check(char_length(btrim(title)) between 1 and 100),
  kind text not null check(kind in ('place','activity')),
  note text not null check(char_length(note)<=1000),
  done boolean not null default false,
  archived boolean not null default false,
  version integer not null check(version>0),
  updated_by uuid not null references auth.users(id),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  last_request_id uuid not null,
  last_fingerprint text not null
);
create index wishes_space on public.wishes(couple_id,archived,updated_at desc,id);
alter table public.wishes enable row level security;
revoke all on public.wishes from public,anon,authenticated;
grant select on public.wishes to authenticated;
create policy wishes_read on public.wishes for select to authenticated
  using(couple_id=(select we2day_private.my_couple()));

create function public.save_wish(p_id uuid,p_title text,p_kind text,p_note text,p_done boolean,
  p_archived boolean,p_expected_version integer,p_request_id uuid) returns setof public.wishes
language plpgsql security definer set search_path='' as $$
declare actor uuid:=we2day_private.actor(); space uuid:=we2day_private.my_couple();
  wish public.wishes; fingerprint text;
begin
  if space is null then raise sqlstate 'PT409' using message='couple_required'; end if;
  if p_id is null or p_title is null or char_length(btrim(p_title)) not between 1 and 100
    or p_kind is null or p_kind not in ('place','activity') or p_note is null
    or char_length(p_note)>1000 or p_done is null or p_archived is null
    or p_expected_version is null or p_expected_version not between 0 and 2147483646
    or p_request_id is null then raise sqlstate 'PT422' using message='invalid_wish'; end if;
  fingerprint:=encode(extensions.digest(jsonb_build_array(p_id,p_title,p_kind,p_note,p_done,
    p_archived,p_expected_version)::text,'sha256'),'hex');
  perform 1 from public.couples where id=space for update;
  select * into wish from public.wishes where id=p_id and couple_id=space for update;
  if not found then
    if exists(select 1 from public.wishes where id=p_id) then
      raise sqlstate 'PT404' using message='wish_not_found';
    end if;
    if p_expected_version<>0 then raise sqlstate 'PT409' using message='version_conflict'; end if;
    return query insert into public.wishes(id,couple_id,title,kind,note,done,archived,version,
      updated_by,last_request_id,last_fingerprint)
      values(p_id,space,btrim(p_title),p_kind,p_note,p_done,p_archived,1,actor,p_request_id,fingerprint)
      returning *;
    return;
  end if;
  if wish.last_request_id=p_request_id then
    if wish.updated_by<>actor or wish.last_fingerprint<>fingerprint then
      raise sqlstate 'PT409' using message='request_conflict';
    end if;
    return next wish; return;
  end if;
  if wish.version<>p_expected_version then raise sqlstate 'PT409' using message='version_conflict'; end if;
  return query update public.wishes set title=btrim(p_title),kind=p_kind,note=p_note,done=p_done,
    archived=p_archived,version=version+1,updated_by=actor,updated_at=clock_timestamp(),
    last_request_id=p_request_id,last_fingerprint=fingerprint where id=p_id returning *;
end $$;
revoke all on function public.save_wish(uuid,text,text,text,boolean,boolean,integer,uuid)
  from public,anon,authenticated;
grant execute on function public.save_wish(uuid,text,text,text,boolean,boolean,integer,uuid)
  to authenticated;
notify pgrst,'reload schema';
commit;
