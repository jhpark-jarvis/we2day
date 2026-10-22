begin;
create table public.couple_questions (
  id uuid primary key,
  couple_id uuid not null references public.couples(id),
  date date not null check(date between date '2000-01-01' and date '2100-12-31'),
  prompt text not null check(char_length(btrim(prompt)) between 1 and 500),
  created_by uuid not null references auth.users(id),
  created_at timestamptz not null default now(),
  request_id uuid not null,
  fingerprint text not null
);
create index couple_questions_date on public.couple_questions(couple_id,date,id);
alter table public.couple_questions enable row level security;
revoke all on public.couple_questions from public,anon,authenticated;
grant select on public.couple_questions to authenticated;
create policy questions_read on public.couple_questions for select to authenticated
  using(couple_id=(select we2day_private.my_couple()));

create table public.question_answers (
  question_id uuid not null references public.couple_questions(id),
  author_id uuid not null references auth.users(id),
  couple_id uuid not null references public.couples(id),
  content text not null check(char_length(content)<=2000),
  shared boolean not null,
  skipped boolean not null,
  version integer not null check(version>0),
  updated_at timestamptz not null default now(),
  last_request_id uuid not null,
  last_fingerprint text not null,
  primary key(question_id,author_id),
  check(not shared or (not skipped and char_length(btrim(content))>0))
);
alter table public.question_answers enable row level security;
revoke all on public.question_answers from public,anon,authenticated;
grant select on public.question_answers to authenticated;
create policy answers_read on public.question_answers for select to authenticated
  using(couple_id=(select we2day_private.my_couple()) and
    (author_id=(select auth.uid()) or (shared and not skipped)));

create function public.create_question(p_id uuid,p_date date,p_prompt text,p_request_id uuid)
returns setof public.couple_questions language plpgsql security definer set search_path='' as $$
declare actor uuid:=we2day_private.actor(); space uuid:=we2day_private.my_couple();
  saved public.couple_questions; fp text;
begin
  if space is null then raise sqlstate 'PT409' using message='couple_required'; end if;
  if p_id is null or p_date is null or not isfinite(p_date)
    or p_date not between date '2000-01-01' and date '2100-12-31'
    or p_prompt is null or char_length(btrim(p_prompt)) not between 1 and 500
    or p_request_id is null then raise sqlstate 'PT422' using message='invalid_question'; end if;
  fp:=encode(extensions.digest(jsonb_build_array(p_id,p_date,p_prompt)::text,'sha256'),'hex');
  perform 1 from public.couples where id=space for update;
  select * into saved from public.couple_questions where id=p_id;
  if found then
    if saved.couple_id<>space then raise sqlstate 'PT404' using message='question_not_found'; end if;
    if saved.created_by<>actor or saved.request_id<>p_request_id or saved.fingerprint<>fp then
      raise sqlstate 'PT409' using message='request_conflict'; end if;
    return next saved; return;
  end if;
  return query insert into public.couple_questions(id,couple_id,date,prompt,created_by,request_id,fingerprint)
    values(p_id,space,p_date,btrim(p_prompt),actor,p_request_id,fp) returning *;
end $$;

create function public.save_question_answer(p_question_id uuid,p_content text,p_shared boolean,
  p_skipped boolean,p_expected_version integer,p_request_id uuid)
returns setof public.question_answers language plpgsql security definer set search_path='' as $$
declare actor uuid:=we2day_private.actor(); space uuid:=we2day_private.my_couple();
  saved public.question_answers; fp text;
begin
  if space is null then raise sqlstate 'PT409' using message='couple_required'; end if;
  if p_content is null or char_length(p_content)>2000 or p_shared is null or p_skipped is null
    or (p_shared and (p_skipped or char_length(btrim(p_content))=0))
    or p_expected_version is null or p_expected_version not between 0 and 2147483646
    or p_request_id is null then raise sqlstate 'PT422' using message='invalid_answer'; end if;
  perform 1 from public.couples where id=space for update;
  if not exists(select 1 from public.couple_questions where id=p_question_id and couple_id=space)
    then raise sqlstate 'PT404' using message='question_not_found'; end if;
  fp:=encode(extensions.digest(jsonb_build_array(p_question_id,p_content,p_shared,p_skipped,
    p_expected_version)::text,'sha256'),'hex');
  select * into saved from public.question_answers where question_id=p_question_id and author_id=actor for update;
  if found then
    if saved.last_request_id=p_request_id then
      if saved.last_fingerprint<>fp then raise sqlstate 'PT409' using message='request_conflict'; end if;
      return next saved; return;
    end if;
    if saved.version<>p_expected_version then raise sqlstate 'PT409' using message='version_conflict'; end if;
    return query update public.question_answers set content=p_content,shared=p_shared,skipped=p_skipped,
      version=version+1,updated_at=clock_timestamp(),last_request_id=p_request_id,last_fingerprint=fp
      where question_id=p_question_id and author_id=actor returning *;
  else
    if p_expected_version<>0 then raise sqlstate 'PT409' using message='version_conflict'; end if;
    return query insert into public.question_answers
      (question_id,author_id,couple_id,content,shared,skipped,version,last_request_id,last_fingerprint)
      values(p_question_id,actor,space,p_content,p_shared,p_skipped,1,p_request_id,fp) returning *;
  end if;
end $$;
revoke all on function public.create_question(uuid,date,text,uuid),
  public.save_question_answer(uuid,text,boolean,boolean,integer,uuid) from public,anon,authenticated;
grant execute on function public.create_question(uuid,date,text,uuid),
  public.save_question_answer(uuid,text,boolean,boolean,integer,uuid) to authenticated;
notify pgrst,'reload schema';
commit;
