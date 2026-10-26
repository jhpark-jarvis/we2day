begin;
-- OAuth metadata is not exposed through the owner column grants.
alter table public.agent_connections add column oauth_resource text;
create table we2day_private.agent_oauth_codes (
 code_hash bytea primary key check(octet_length(code_hash)=32),
 user_id uuid not null references auth.users(id) on delete cascade,
 couple_id uuid not null references public.couples(id),
 client_id text not null, redirect_uri text not null, resource text not null,
 challenge text not null, created_at timestamptz not null default now(),
 expires_at timestamptz not null default now()+interval '5 minutes', used_at timestamptz
);
alter table we2day_private.agent_oauth_codes enable row level security;
revoke all on we2day_private.agent_oauth_codes from public,anon,authenticated;
create index agent_oauth_codes_owner on we2day_private.agent_oauth_codes(user_id,created_at);

create function public.approve_agent_oauth(p_client_id text,p_redirect_uri text,
 p_resource text,p_challenge text) returns text
language plpgsql security definer set search_path='' as $$
declare actor uuid:=we2day_private.actor(); space uuid:=we2day_private.my_couple(); code text;
begin
 if space is null then raise sqlstate 'PT409' using message='couple_required'; end if;
 if p_client_id is distinct from 'https://chatgpt.com/oauth/client.json'
 or p_redirect_uri is distinct from 'https://chatgpt.com/connector_platform_oauth_redirect'
 or p_resource is null or p_resource !~ '^https://[a-zA-Z0-9.-]+/api/agent/mcp$'
 or p_challenge is null or p_challenge !~ '^[A-Za-z0-9_-]{43}$' then
  raise sqlstate 'PT422' using message='invalid_oauth_request'; end if;
 perform 1 from public.couples where id=space for update;
 if (select count(*) from we2day_private.agent_oauth_codes where user_id=actor
 and created_at>now()-interval '1 hour')>=20 then
  raise sqlstate 'PT429' using message='oauth_request_limit'; end if;
 code:=encode(extensions.gen_random_bytes(32),'hex');
 insert into we2day_private.agent_oauth_codes(code_hash,user_id,couple_id,client_id,
 redirect_uri,resource,challenge) values(extensions.digest(code,'sha256'),actor,space,
 p_client_id,p_redirect_uri,p_resource,p_challenge);
 return code;
end $$;
revoke all on function public.approve_agent_oauth(text,text,text,text) from public,anon;
grant execute on function public.approve_agent_oauth(text,text,text,text) to authenticated;

create function public.exchange_agent_oauth(p_code text,p_client_id text,p_redirect_uri text,
 p_resource text,p_verifier text) returns jsonb
language plpgsql security definer set search_path='' as $$
declare item we2day_private.agent_oauth_codes; result jsonb; previous_sub text; previous_claims text;
begin
 if p_code is null or p_code !~ '^[0-9a-f]{64}$' or p_verifier is null
 or p_verifier !~ '^[A-Za-z0-9._~-]{43,128}$' then
  raise sqlstate 'PT401' using message='invalid_grant'; end if;
 select * into item from we2day_private.agent_oauth_codes
 where code_hash=extensions.digest(p_code,'sha256') for update;
 if not found or item.used_at is not null or item.expires_at<=now()
 or item.client_id is distinct from p_client_id or item.redirect_uri is distinct from p_redirect_uri
 or item.resource is distinct from p_resource
 or item.challenge is distinct from rtrim(translate(encode(extensions.digest(p_verifier,'sha256'),
 'base64'),'+/','-_'),'=')
 or not exists(select 1 from public.couple_members where user_id=item.user_id
 and couple_id=item.couple_id) then raise sqlstate 'PT401' using message='invalid_grant'; end if;
 previous_sub:=current_setting('request.jwt.claim.sub',true);
 previous_claims:=current_setting('request.jwt.claims',true);
 perform set_config('request.jwt.claim.sub',item.user_id::text,true);
 perform set_config('request.jwt.claims',jsonb_build_object('sub',item.user_id,'role','authenticated')::text,true);
 result:=public.create_managed_agent_connection('ChatGPT OAuth',true);
 update public.agent_connections set oauth_resource=item.resource where id=(result->>'id')::uuid;
 update we2day_private.agent_oauth_codes set used_at=now() where code_hash=item.code_hash;
 perform set_config('request.jwt.claim.sub',coalesce(previous_sub,''),true);
 perform set_config('request.jwt.claims',coalesce(previous_claims,''),true);
 return jsonb_build_object('access_token',result->>'key','token_type','Bearer',
 'expires_in',floor(extract(epoch from ((result->>'expires_at')::timestamptz-now())))::integer,
 'scope','we2day:manage','resource',item.resource);
end $$;
revoke all on function public.exchange_agent_oauth(text,text,text,text,text) from public;
grant execute on function public.exchange_agent_oauth(text,text,text,text,text) to anon,authenticated;

create or replace function we2day_private.authorize_agent(p_key text) returns public.agent_connections
language plpgsql set search_path='' as $$
declare item public.agent_connections;
begin
  if p_key is null or p_key !~ '^w2d_agent_[0-9a-f]{64}$' then
    raise sqlstate 'PT401' using message='invalid_agent_key'; end if;
  select * into item from public.agent_connections
    where token_hash=extensions.digest(p_key,'sha256') for update;
  if not found or (item.oauth_resource is not null and item.oauth_resource is distinct from
      nullif(current_setting('we2day.oauth_resource',true),'')) or item.revoked_at is not null or item.expires_at<=now()
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

-- Only this fixed dispatcher establishes the resource context for an OAuth token.
create function public.agent_oauth_dispatch(p_key text,p_resource text,p_function text,p_arguments jsonb)
returns jsonb language plpgsql security definer set search_path='' as $$
declare previous_resource text; result jsonb;
begin
 if p_key is null or not exists(select 1 from public.agent_connections
 where token_hash=extensions.digest(p_key,'sha256') and oauth_resource=p_resource) then
  raise sqlstate 'PT401' using message='invalid_agent_key'; end if;
 previous_resource:=current_setting('we2day.oauth_resource',true);
 perform set_config('we2day.oauth_resource',p_resource,true);
 case p_function
 when 'agent_calendar' then result:=public.agent_calendar(p_key,(p_arguments->>'p_start')::date,
 (p_arguments->>'p_end')::date,(p_arguments->>'p_offset')::integer);
 when 'agent_plan' then result:=public.agent_plan(p_key,(p_arguments->>'p_id')::uuid);
 when 'agent_appointment' then result:=public.agent_appointment(p_key,(p_arguments->>'p_id')::uuid);
 when 'agent_create_draft' then result:=public.agent_create_draft(p_key,(p_arguments->>'p_id')::uuid,
 p_arguments->'p_content',(p_arguments->>'p_request_id')::uuid);
 when 'agent_change' then result:=public.agent_change(p_key,p_arguments->>'p_entity',
 (p_arguments->>'p_id')::uuid,p_arguments->>'p_action',nullif(p_arguments->'p_content','null'::jsonb),
 (p_arguments->>'p_expected_version')::integer,(p_arguments->>'p_expected_appointment_version')::integer,
 (p_arguments->>'p_request_id')::uuid,(p_arguments->>'p_confirmed')::boolean);
 else raise sqlstate 'PT422' using message='invalid_oauth_operation';
 end case;
 perform set_config('we2day.oauth_resource',coalesce(previous_resource,''),true);
 return result;
end $$;
revoke all on function public.agent_oauth_dispatch(text,text,text,jsonb) from public;
grant execute on function public.agent_oauth_dispatch(text,text,text,jsonb) to anon,authenticated;
notify pgrst,'reload schema';
commit;
