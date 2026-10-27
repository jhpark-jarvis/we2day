begin;

alter table we2day_private.ai_conversation_turns add column request_fingerprint text
 check(request_fingerprint is null or request_fingerprint ~ '^[0-9a-f]{64}$');

-- Transient execution ownership only; never conversation text or a second result archive.
create table we2day_private.ai_request_leases (
 conversation_id uuid not null, request_id uuid not null,
 owner_id uuid not null references auth.users(id) on delete cascade,
 couple_id uuid not null, lease_id uuid not null,
 fingerprint text not null check(fingerprint ~ '^[0-9a-f]{64}$'),
 expires_at timestamptz not null,
 primary key(conversation_id,request_id)
);
create index ai_request_leases_owner_expiry on we2day_private.ai_request_leases(owner_id,expires_at);
alter table we2day_private.ai_request_leases enable row level security;
revoke all on we2day_private.ai_request_leases from public,anon,authenticated;

create function public.begin_ai_planner_turn(p_id uuid,p_request uuid,p_version integer,
 p_user text,p_fingerprint text,p_lease uuid) returns jsonb
language plpgsql security definer set search_path='' as $$
declare c we2day_private.ai_conversations; t we2day_private.ai_conversation_turns;
 l we2day_private.ai_request_leases; pair uuid := (public.get_my_couple()->>'id')::uuid;
begin
 if auth.uid() is null or pair is null then raise sqlstate 'PT403' using message='couple_required'; end if;
 if p_id is null or p_request is null or p_lease is null or p_version is null or p_version<0
 or p_user is null or length(p_user) not between 1 and 4000
 or p_fingerprint is null or p_fingerprint !~ '^[0-9a-f]{64}$' then
  raise sqlstate 'PT422' using message='invalid_request'; end if;
 -- Only serialize this conversation's tiny admission/commit transactions, never inference.
 perform pg_catalog.pg_advisory_xact_lock(pg_catalog.hashtextextended(p_id::text,771));
 select * into c from we2day_private.ai_conversations where id=p_id;
 if found and (c.owner_id<>auth.uid() or c.couple_id<>pair) then
  raise sqlstate 'PT404' using message='ai_conversation_not_found'; end if;
 if exists(select 1 from we2day_private.ai_request_leases where conversation_id=p_id
 and (owner_id<>auth.uid() or couple_id<>pair)) then
  raise sqlstate 'PT404' using message='ai_conversation_not_found'; end if;
 select * into t from we2day_private.ai_conversation_turns
 where conversation_id=p_id and request_id=p_request;
 if found then
  if t.user_text<>p_user or (t.request_fingerprint is not null and t.request_fingerprint<>p_fingerprint) then raise sqlstate 'PT409' using message='request_conflict'; end if;
  return jsonb_build_object('replay',jsonb_build_object('version',t.version,
   'result',t.result,'prompt_version',t.prompt_version));
 end if;
 if c.id is null and p_version<>0 then raise sqlstate 'PT404' using message='ai_conversation_not_found'; end if;
 if c.id is not null and c.version<>p_version then raise sqlstate 'PT409' using message='version_conflict'; end if;
 select * into l from we2day_private.ai_request_leases where conversation_id=p_id and request_id=p_request;
 if found and l.fingerprint<>p_fingerprint then
  raise sqlstate 'PT409' using message='request_conflict'; end if;
 if exists(select 1 from we2day_private.ai_request_leases where conversation_id=p_id and expires_at>now()) then
  raise sqlstate 'PT409' using message='ai_request_in_progress'; end if;
 delete from we2day_private.ai_request_leases where owner_id=auth.uid() and expires_at<=now()-interval '1 day';
 delete from we2day_private.ai_request_leases where conversation_id=p_id and expires_at<=now();
 insert into we2day_private.ai_request_leases(conversation_id,request_id,owner_id,couple_id,lease_id,fingerprint,expires_at)
 values(p_id,p_request,auth.uid(),pair,p_lease,p_fingerprint,now()+interval '110 seconds');
 return jsonb_build_object('version',coalesce(c.version,0),
 'context',coalesce((select result->'context' from we2day_private.ai_conversation_turns
  where conversation_id=p_id order by version desc limit 1),'{}'::jsonb),
 'proposal',(select result->'plan' from we2day_private.ai_conversation_turns where conversation_id=p_id
  and result->'plan' is not null and result->'plan'<>'null'::jsonb order by version desc limit 1));
end $$;

create function public.finish_ai_planner_turn(p_id uuid,p_request uuid,p_lease uuid,
 p_version integer,p_user text,p_result jsonb,p_prompt text) returns jsonb
language plpgsql security definer set search_path='' as $$
declare l we2day_private.ai_request_leases; result jsonb;
 pair uuid := (public.get_my_couple()->>'id')::uuid;
begin
 if auth.uid() is null or pair is null then raise sqlstate 'PT403' using message='couple_required'; end if;
 if p_id is null or p_request is null or p_lease is null then
  raise sqlstate 'PT422' using message='invalid_request'; end if;
 perform pg_catalog.pg_advisory_xact_lock(pg_catalog.hashtextextended(p_id::text,771));
 select * into l from we2day_private.ai_request_leases where conversation_id=p_id and request_id=p_request;
 if not found or l.owner_id<>auth.uid() or l.couple_id<>pair or l.lease_id<>p_lease or l.expires_at<=now() then
  raise sqlstate 'PT409' using message='ai_lease_expired'; end if;
 result:=public.append_ai_conversation(p_id,p_request,p_version,p_user,p_result,p_prompt);
 update we2day_private.ai_conversation_turns set request_fingerprint=l.fingerprint
 where conversation_id=p_id and request_id=p_request and request_fingerprint is null;
 delete from we2day_private.ai_request_leases where conversation_id=p_id and request_id=p_request;
 return result;
end $$;

create function public.release_ai_planner_turn(p_id uuid,p_request uuid,p_lease uuid) returns boolean
language plpgsql security definer set search_path='' as $$
begin
 delete from we2day_private.ai_request_leases where conversation_id=p_id and request_id=p_request
 and lease_id=p_lease and owner_id=auth.uid() and couple_id=(public.get_my_couple()->>'id')::uuid;
 return found;
end $$;
revoke all on function public.begin_ai_planner_turn(uuid,uuid,integer,text,text,uuid),
 public.finish_ai_planner_turn(uuid,uuid,uuid,integer,text,jsonb,text),
 public.release_ai_planner_turn(uuid,uuid,uuid) from public,anon;
grant execute on function public.begin_ai_planner_turn(uuid,uuid,integer,text,text,uuid),
 public.finish_ai_planner_turn(uuid,uuid,uuid,integer,text,jsonb,text),
 public.release_ai_planner_turn(uuid,uuid,uuid) to authenticated;
notify pgrst,'reload schema';
commit;
