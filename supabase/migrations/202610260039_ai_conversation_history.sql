begin;
create table we2day_private.ai_conversations (
 id uuid primary key, owner_id uuid not null references auth.users(id) on delete cascade,
 couple_id uuid not null, title text not null check(length(title) between 1 and 80),
 version integer not null default 0 check(version>=0),
 created_at timestamptz not null default now(), updated_at timestamptz not null default now()
);
create index ai_conversations_owner_updated on we2day_private.ai_conversations(owner_id,updated_at desc);
create table we2day_private.ai_conversation_turns (
 conversation_id uuid not null references we2day_private.ai_conversations(id) on delete cascade,
 request_id uuid not null, version integer not null check(version>0),
 user_text text not null check(length(user_text) between 1 and 4000),
 result jsonb not null check(jsonb_typeof(result)='object' and octet_length(result::text)<=32768),
 prompt_version text not null check(length(prompt_version)<=80),
 created_at timestamptz not null default now(),
 primary key(conversation_id,version), unique(conversation_id,request_id)
);
alter table we2day_private.ai_conversations enable row level security;
alter table we2day_private.ai_conversation_turns enable row level security;
revoke all on we2day_private.ai_conversations,we2day_private.ai_conversation_turns from public,anon,authenticated;

create function public.read_ai_conversations(p_id uuid default null, p_before integer default null) returns jsonb
language plpgsql security definer set search_path='' as $$
declare c we2day_private.ai_conversations; pair uuid := (public.get_my_couple()->>'id')::uuid; rows jsonb;
begin
 if auth.uid() is null or pair is null then raise sqlstate 'PT403' using message='couple_required'; end if;
 if p_id is null then
  return coalesce((select jsonb_agg(to_jsonb(x) order by x.updated_at desc) from
   (select id,title,version,updated_at from we2day_private.ai_conversations where owner_id=auth.uid() and couple_id=pair order by updated_at desc limit 100) x),'[]'::jsonb);
 end if;
 select * into c from we2day_private.ai_conversations where id=p_id;
 if not found then return null; end if;
 if c.owner_id<>auth.uid() or c.couple_id<>pair then raise sqlstate 'PT404' using message='ai_conversation_not_found'; end if;
 select coalesce(jsonb_agg(to_jsonb(x) order by x.version),'[]'::jsonb) into rows from
  (select request_id,version,user_text,result,prompt_version,created_at from we2day_private.ai_conversation_turns
   where conversation_id=p_id and (p_before is null or version<p_before) order by version desc limit 50) x;
 return jsonb_build_object('id',c.id,'title',c.title,'version',c.version,'turns',rows,'proposal',(select result->'plan' from we2day_private.ai_conversation_turns where conversation_id=p_id and result->'plan' is not null and result->'plan'<>'null'::jsonb order by version desc limit 1));
end; $$;

create function public.append_ai_conversation(p_id uuid,p_request uuid,p_version integer,p_user text,p_result jsonb,p_prompt text) returns jsonb
language plpgsql security definer set search_path='' as $$
declare c we2day_private.ai_conversations; t we2day_private.ai_conversation_turns; pair uuid := (public.get_my_couple()->>'id')::uuid;
begin
 if auth.uid() is null or pair is null then raise sqlstate 'PT403' using message='couple_required'; end if;
 if p_id is null or p_request is null or p_version is null or p_version<0 or p_user is null or length(p_user) not between 1 and 4000 or p_result is null or jsonb_typeof(p_result)<>'object' or octet_length(p_result::text)>32768 or length(coalesce(p_result->>'reply','')) not between 1 and 4000 or p_prompt is null or length(p_prompt) not between 1 and 80 then
  raise sqlstate 'PT422' using message='invalid_request';
 end if;
 insert into we2day_private.ai_conversations(id,owner_id,couple_id,title) values(p_id,auth.uid(),pair,left(p_user,80)) on conflict(id) do nothing;
 select * into c from we2day_private.ai_conversations where id=p_id for update;
 if c.owner_id<>auth.uid() or c.couple_id<>pair then raise sqlstate 'PT404' using message='ai_conversation_not_found'; end if;
 select * into t from we2day_private.ai_conversation_turns where conversation_id=p_id and request_id=p_request;
 if found then
  if t.user_text<>p_user then raise sqlstate 'PT409' using message='request_conflict'; end if;
  return jsonb_build_object('version',t.version,'result',t.result);
 end if;
 if c.version<>p_version then raise sqlstate 'PT409' using message='version_conflict'; end if;
 insert into we2day_private.ai_conversation_turns(conversation_id,request_id,version,user_text,result,prompt_version) values(p_id,p_request,c.version+1,p_user,p_result,p_prompt);
 update we2day_private.ai_conversations set version=c.version+1,updated_at=now() where id=p_id;
 return jsonb_build_object('version',c.version+1,'result',p_result);
end; $$;
revoke all on function public.read_ai_conversations(uuid,integer),public.append_ai_conversation(uuid,uuid,integer,text,jsonb,text) from public,anon;
grant execute on function public.read_ai_conversations(uuid,integer),public.append_ai_conversation(uuid,uuid,integer,text,jsonb,text) to authenticated;
notify pgrst,'reload schema';
commit;
