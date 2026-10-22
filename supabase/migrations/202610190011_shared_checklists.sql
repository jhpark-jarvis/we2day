begin;

create function we2day_private.valid_checklist_items(items jsonb) returns boolean
language plpgsql immutable set search_path='' as $$
declare item jsonb; ids text[]:='{}'; item_id text;
begin
  if items is null or jsonb_typeof(items)<>'array' then return false; end if;
  if jsonb_array_length(items)>50 or octet_length(items::text)>65536 then return false; end if;
  for item in select value from jsonb_array_elements(items) loop
    if jsonb_typeof(item)<>'object' then return false; end if;
    if (select count(*) from jsonb_object_keys(item))<>4
      or not (item ?& array['id','title','quantity','done'])
      or jsonb_typeof(item->'id')<>'string'
      or jsonb_typeof(item->'title')<>'string'
      or jsonb_typeof(item->'quantity')<>'string'
      or jsonb_typeof(item->'done')<>'boolean' then return false; end if;
    item_id:=lower(item->>'id');
    if item_id !~ '^[0-9a-f]{8}-([0-9a-f]{4}-){3}[0-9a-f]{12}$'
      or item_id=any(ids) or char_length(btrim(item->>'title')) not between 1 and 100
      or char_length(item->>'quantity')>100 then return false; end if;
    ids:=array_append(ids,item_id);
  end loop;
  return true;
end $$;
revoke all on function we2day_private.valid_checklist_items(jsonb) from public,anon,authenticated;

create table public.shared_checklists (
  id uuid primary key,
  couple_id uuid not null references public.couples(id),
  title text not null check(char_length(btrim(title)) between 1 and 100),
  note text not null check(char_length(note)<=1000),
  items jsonb not null check(we2day_private.valid_checklist_items(items)),
  archived boolean not null default false,
  version integer not null check(version>0),
  updated_by uuid not null references auth.users(id),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  last_request_id uuid not null,
  last_fingerprint text not null
);
create index shared_checklists_space on public.shared_checklists
  (couple_id,archived,updated_at desc,id);
alter table public.shared_checklists enable row level security;
revoke all on public.shared_checklists from public,anon,authenticated;
grant select on public.shared_checklists to authenticated;
create policy shared_checklists_read on public.shared_checklists for select to authenticated
  using(couple_id=(select we2day_private.my_couple()));

create function public.save_checklist(p_id uuid,p_title text,p_note text,p_items jsonb,
  p_archived boolean,p_expected_version integer,p_request_id uuid)
returns setof public.shared_checklists language plpgsql security definer set search_path='' as $$
declare actor uuid:=we2day_private.actor(); space uuid:=we2day_private.my_couple();
  saved public.shared_checklists; fingerprint text;
begin
  if space is null then raise sqlstate 'PT409' using message='couple_required'; end if;
  if p_id is null or p_title is null or char_length(btrim(p_title)) not between 1 and 100
    or p_note is null or char_length(p_note)>1000
    or not we2day_private.valid_checklist_items(p_items) or p_archived is null
    or p_expected_version is null or p_expected_version not between 0 and 2147483646
    or p_request_id is null then raise sqlstate 'PT422' using message='invalid_checklist'; end if;
  fingerprint:=encode(extensions.digest(jsonb_build_array(p_id,p_title,p_note,p_items,
    p_archived,p_expected_version)::text,'sha256'),'hex');
  perform 1 from public.couples where id=space for update;
  select * into saved from public.shared_checklists where id=p_id and couple_id=space for update;
  if not found then
    if exists(select 1 from public.shared_checklists where id=p_id) then
      raise sqlstate 'PT404' using message='checklist_not_found';
    end if;
    if p_expected_version<>0 then raise sqlstate 'PT409' using message='version_conflict'; end if;
    return query insert into public.shared_checklists
      (id,couple_id,title,note,items,archived,version,updated_by,last_request_id,last_fingerprint)
      values(p_id,space,btrim(p_title),p_note,p_items,p_archived,1,actor,p_request_id,fingerprint)
      returning *;
    return;
  end if;
  if saved.last_request_id=p_request_id then
    if saved.updated_by<>actor or saved.last_fingerprint<>fingerprint then
      raise sqlstate 'PT409' using message='request_conflict';
    end if;
    return next saved; return;
  end if;
  if saved.version<>p_expected_version then
    raise sqlstate 'PT409' using message='version_conflict'; end if;
  if exists(select 1 from jsonb_array_elements(saved.items) old_item where not exists
    (select 1 from jsonb_array_elements(p_items) new_item
      where lower(new_item->>'id')=lower(old_item->>'id'))) then
    raise sqlstate 'PT422' using message='checklist_items_retained'; end if;
  return query update public.shared_checklists set title=btrim(p_title),note=p_note,items=p_items,
    archived=p_archived,version=version+1,updated_by=actor,updated_at=clock_timestamp(),
    last_request_id=p_request_id,last_fingerprint=fingerprint where id=p_id returning *;
end $$;
revoke all on function public.save_checklist(uuid,text,text,jsonb,boolean,integer,uuid)
  from public,anon,authenticated;
grant execute on function public.save_checklist(uuid,text,text,jsonb,boolean,integer,uuid)
  to authenticated;
notify pgrst,'reload schema';
commit;
