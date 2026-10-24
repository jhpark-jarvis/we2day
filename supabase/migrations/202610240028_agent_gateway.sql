begin;

create table public.agent_connections (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  couple_id uuid not null references public.couples(id),
  label text not null check(char_length(btrim(label)) between 1 and 60),
  token_hash bytea not null unique check(octet_length(token_hash)=32),
  created_at timestamptz not null default now(),
  expires_at timestamptz not null default now()+interval '30 days',
  revoked_at timestamptz,
  last_used_at timestamptz,
  window_start timestamptz not null default now(),
  window_count integer not null default 0
);
alter table public.agent_connections enable row level security;
revoke all on public.agent_connections from public,anon,authenticated;
grant select(id,label,created_at,expires_at,revoked_at,last_used_at)
  on public.agent_connections to authenticated;
create policy agent_connections_owner on public.agent_connections for select to authenticated
  using(user_id=(select auth.uid()));

create table we2day_private.agent_drafts (
  plan_id uuid primary key references public.date_plans(id) on delete cascade,
  connection_id uuid not null references public.agent_connections(id),
  couple_id uuid not null references public.couples(id),
  request_id uuid not null,
  fingerprint text not null,
  created_at timestamptz not null default now(),
  unique(connection_id,request_id)
);
alter table we2day_private.agent_drafts enable row level security;
revoke all on we2day_private.agent_drafts from public,anon,authenticated;
create index agent_drafts_daily on we2day_private.agent_drafts(couple_id,created_at);

create function public.create_agent_connection(p_label text) returns jsonb
language plpgsql security definer set search_path='' as $$
declare actor uuid:=we2day_private.actor(); space uuid:=we2day_private.my_couple();
  secret text; item public.agent_connections;
begin
  if space is null then raise sqlstate 'PT409' using message='couple_required'; end if;
  if p_label is null or char_length(btrim(p_label)) not between 1 and 60
    or p_label ~ '[[:cntrl:]]' then
    raise sqlstate 'PT422' using message='invalid_agent_connection'; end if;
  perform 1 from public.couples where id=space for update;
  if (select count(*) from public.agent_connections
      where user_id=actor and revoked_at is null and expires_at>now())>=5 then
    raise sqlstate 'PT409' using message='agent_connection_limit'; end if;
  secret:='w2d_agent_'||encode(extensions.gen_random_bytes(32),'hex');
  insert into public.agent_connections(user_id,couple_id,label,token_hash)
    values(actor,space,btrim(p_label),extensions.digest(secret,'sha256')) returning * into item;
  return jsonb_build_object('id',item.id,'label',item.label,'created_at',item.created_at,
    'expires_at',item.expires_at,'revoked_at',null,'last_used_at',null,'key',secret);
end $$;
revoke all on function public.create_agent_connection(text) from public,anon;
grant execute on function public.create_agent_connection(text) to authenticated;

create function public.revoke_agent_connection(p_id uuid) returns boolean
language plpgsql security definer set search_path='' as $$
begin
  update public.agent_connections set revoked_at=coalesce(revoked_at,now())
    where id=p_id and user_id=we2day_private.actor();
  if not found then raise sqlstate 'PT404' using message='agent_connection_not_found'; end if;
  return true;
end $$;
revoke all on function public.revoke_agent_connection(uuid) from public,anon;
grant execute on function public.revoke_agent_connection(uuid) to authenticated;

create function we2day_private.authorize_agent(p_key text) returns public.agent_connections
language plpgsql set search_path='' as $$
declare item public.agent_connections;
begin
  if p_key is null or p_key !~ '^w2d_agent_[0-9a-f]{64}$' then
    raise sqlstate 'PT401' using message='invalid_agent_key'; end if;
  select * into item from public.agent_connections
    where token_hash=extensions.digest(p_key,'sha256') for update;
  if not found or item.revoked_at is not null or item.expires_at<=now()
    or not exists(select 1 from public.couple_members
      where user_id=item.user_id and couple_id=item.couple_id) then
    raise sqlstate 'PT401' using message='invalid_agent_key'; end if;
  if item.window_start<=now()-interval '1 minute' then
    item.window_start:=now(); item.window_count:=0;
  end if;
  if item.window_count>=60 then raise sqlstate 'PT429' using message='agent_rate_limit'; end if;
  update public.agent_connections set window_start=item.window_start,
    window_count=item.window_count+1,last_used_at=now() where id=item.id;
  return item;
end $$;
revoke all on function we2day_private.authorize_agent(text) from public,anon,authenticated;

create function public.agent_calendar(p_key text,p_start date,p_end date,p_offset integer default 0)
returns jsonb language plpgsql security definer set search_path='' as $$
declare item public.agent_connections:=we2day_private.authorize_agent(p_key);
  appointments jsonb; plans jsonb;
begin
  if p_start is null or p_end is null or p_end<p_start or p_end-p_start>30
    or p_offset is null or p_offset not between 0 and 100000 then
    raise sqlstate 'PT422' using message='invalid_agent_query'; end if;
  select coalesce(jsonb_agg(to_jsonb(a)),'[]') into appointments from
    (select id,title,date,time,place,note,version from public.appointments
      where couple_id=item.couple_id and date between p_start and p_end
      order by date,time nulls last,id limit 50 offset p_offset) a;
  select coalesce(jsonb_agg(to_jsonb(p)),'[]') into plans from
    (select id,content,published_content,published_revision,version from public.date_plans
      where couple_id=item.couple_id and not archived
      and ((content->>'date')::date between p_start and p_end
        or (published_content->>'date')::date between p_start and p_end)
      order by id limit 50 offset p_offset) p;
  return jsonb_build_object('appointments',appointments,'plans',plans,
    'next_offset',case when greatest(jsonb_array_length(appointments),jsonb_array_length(plans))=50
      then p_offset+50 else null end);
end $$;
revoke all on function public.agent_calendar(text,date,date,integer) from public;
grant execute on function public.agent_calendar(text,date,date,integer) to anon,authenticated;

create function public.agent_plan(p_key text,p_id uuid) returns jsonb
language plpgsql security definer set search_path='' as $$
declare item public.agent_connections:=we2day_private.authorize_agent(p_key); result jsonb;
begin
  select jsonb_build_object('id',id,'content',content,'published_content',published_content,
    'published_revision',published_revision,'version',version) into result
    from public.date_plans where id=p_id and couple_id=item.couple_id and not archived;
  if result is null then raise sqlstate 'PT404' using message='plan_not_found'; end if;
  return result;
end $$;
revoke all on function public.agent_plan(text,uuid) from public;
grant execute on function public.agent_plan(text,uuid) to anon,authenticated;

create function public.agent_create_draft(p_key text,p_id uuid,p_content jsonb,p_request_id uuid)
returns jsonb language plpgsql security definer set search_path='' as $$
declare item public.agent_connections:=we2day_private.authorize_agent(p_key);
  prior we2day_private.agent_drafts; fingerprint text;
begin
  if p_id is null or p_request_id is null then
    raise sqlstate 'PT422' using message='invalid_plan'; end if;
  perform we2day_private.validate_plan(p_content);
  fingerprint:=encode(extensions.digest(jsonb_build_array(p_id,p_content)::text,'sha256'),'hex');
  perform 1 from public.couples where id=item.couple_id for update;
  select * into prior from we2day_private.agent_drafts
    where connection_id=item.id and request_id=p_request_id;
  if found then
    if prior.plan_id<>p_id or prior.fingerprint<>fingerprint then
      raise sqlstate 'PT409' using message='request_conflict'; end if;
    return jsonb_build_object('id',p_id,'created',false);
  end if;
  if exists(select 1 from public.date_plans where id=p_id) then
    raise sqlstate 'PT409' using message='request_conflict'; end if;
  if (select count(*) from we2day_private.agent_drafts where couple_id=item.couple_id
    and (created_at at time zone 'Asia/Seoul')::date=(now() at time zone 'Asia/Seoul')::date)>=20 then
    raise sqlstate 'PT429' using message='agent_draft_limit'; end if;
  insert into public.date_plans(id,couple_id,content,version,created_by,updated_by,
    last_request_id,last_fingerprint) values(p_id,item.couple_id,p_content,1,item.user_id,
    item.user_id,p_request_id,encode(extensions.digest(
      jsonb_build_array(p_id,'save',p_content,0,0)::text,'sha256'),'hex'));
  insert into we2day_private.agent_drafts(plan_id,connection_id,couple_id,request_id,fingerprint)
    values(p_id,item.id,item.couple_id,p_request_id,fingerprint);
  return jsonb_build_object('id',p_id,'created',true);
end $$;
revoke all on function public.agent_create_draft(text,uuid,jsonb,uuid) from public;
grant execute on function public.agent_create_draft(text,uuid,jsonb,uuid) to anon,authenticated;

commit;
