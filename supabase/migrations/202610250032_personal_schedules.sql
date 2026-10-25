begin;
alter table public.appointments add column kind text not null default 'shared'
  check(kind in ('shared','personal')),
  add constraint personal_appointment_no_place check(kind<>'personal' or place='');

create function public.create_personal_appointment(
  p_title text, p_date date, p_time time, p_place text, p_note text, p_request_id uuid
) returns setof public.appointments
language plpgsql security definer set search_path = '' as $$
declare actor uuid := we2day_private.actor(); space uuid := we2day_private.my_couple();
  fingerprint text; existing public.appointments;
begin
  if space is null then raise sqlstate 'PT409' using message = 'couple_required'; end if;
  perform we2day_private.validate_appointment(p_title, p_date, p_time, p_place, p_note);
  if p_request_id is null then raise sqlstate 'PT422' using message = 'invalid_request'; end if;
  if p_place is distinct from '' then raise sqlstate 'PT422' using message='invalid_appointment'; end if;
  fingerprint := encode(extensions.digest(
    jsonb_build_array('personal',btrim(p_title),p_date,p_time,p_place,p_note)::text, 'sha256'), 'hex');
  perform pg_advisory_xact_lock(hashtextextended(actor::text || p_request_id::text, 0));
  select * into existing from public.appointments where created_by = actor and request_id = p_request_id;
  if found then
    if existing.creation_fingerprint <> fingerprint or existing.kind<>'personal' then
      raise sqlstate 'PT409' using message = 'request_conflict';
    end if;
    return next existing;
    return;
  end if;
  return query insert into public.appointments(kind,couple_id,title,date,time,place,note,
    created_by,updated_by,request_id,creation_fingerprint)
    values('personal',space,btrim(p_title),p_date,p_time,p_place,p_note,actor,actor,p_request_id,fingerprint)
    returning *;
end;
$$;
create or replace function public.update_appointment(
  p_id uuid, p_expected_version integer, p_title text, p_date date,
  p_time time, p_place text, p_note text
) returns setof public.appointments
language plpgsql security definer set search_path = '' as $$
declare actor uuid := we2day_private.actor(); space uuid := we2day_private.my_couple();
  existing public.appointments;
begin
  perform we2day_private.validate_appointment(p_title, p_date, p_time, p_place, p_note);
  select * into existing from public.appointments where id = p_id and couple_id = space for update;
  if not found then raise sqlstate 'PT404' using message = 'appointment_not_found'; end if;
  if existing.kind='personal' and existing.created_by<>actor then
    raise sqlstate 'PT403' using message='appointment_owner_required'; end if;
  if existing.kind='personal' and p_place<>'' then
    raise sqlstate 'PT422' using message='invalid_appointment'; end if;
  if p_expected_version is null or p_expected_version <> existing.version then
    raise sqlstate 'PT409' using message = 'version_conflict';
  end if;
  return query update public.appointments set title = btrim(p_title), date = p_date, time = p_time,
    place = p_place, note = p_note, version = version + 1, updated_by = actor,
    updated_at = clock_timestamp() where id = p_id returning *;
end;
$$;

create function public.delete_personal_appointment(p_id uuid,p_expected_version integer)
returns jsonb language plpgsql security definer set search_path='' as $$
declare actor uuid:=we2day_private.actor(); existing public.appointments;
begin
  select * into existing from public.appointments where id=p_id
    and couple_id=we2day_private.my_couple() for update;
  if not found then raise sqlstate 'PT404' using message='appointment_not_found'; end if;
  if existing.kind<>'personal' then raise sqlstate 'PT409' using message='personal_appointment_required'; end if;
  if existing.created_by<>actor then raise sqlstate 'PT403' using message='appointment_owner_required'; end if;
  if p_expected_version is null or p_expected_version<>existing.version then
    raise sqlstate 'PT409' using message='version_conflict'; end if;
  delete from public.appointments where id=p_id;
  return jsonb_build_object('deleted',true);
end $$;
revoke all on function public.create_personal_appointment(text,date,time,text,text,uuid),
  public.delete_personal_appointment(uuid,integer) from public,anon,authenticated;
grant execute on function public.create_personal_appointment(text,date,time,text,text,uuid),
  public.delete_personal_appointment(uuid,integer) to authenticated;
create or replace function public.get_next_appointment()
returns table(id uuid,title text,date date,"time" time,place text)
language plpgsql stable security invoker set search_path='' as $$
declare local_now timestamp := statement_timestamp() at time zone 'Asia/Seoul';
begin
  if auth.uid() is null then raise sqlstate 'PT401' using message='authentication_required'; end if;
  if we2day_private.my_couple() is null then
    raise sqlstate 'PT409' using message='couple_required'; end if;
  return query select a.id,a.title,a.date,a.time,a.place from public.appointments a
    where a.kind='shared' and a.date>=local_now::date
      and (a.time is null or a.date+a.time>=local_now)
    order by a.date,a.time nulls last,a.id limit 1;
end $$;
create or replace function public.agent_calendar(p_key text,p_start date,p_end date,p_offset integer default 0)
returns jsonb language plpgsql security definer set search_path='' as $$
declare item public.agent_connections:=we2day_private.authorize_agent(p_key);
  appointments jsonb; plans jsonb;
begin
  if p_start is null or p_end is null or p_end<p_start or p_end-p_start>30
    or p_offset is null or p_offset not between 0 and 100000 then
    raise sqlstate 'PT422' using message='invalid_agent_query'; end if;
  select coalesce(jsonb_agg(to_jsonb(a)),'[]') into appointments from
    (select id,title,date,time,place,note,version from public.appointments
      where kind='shared' and couple_id=item.couple_id and date between p_start and p_end
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
create or replace function public.export_record_snapshot(p_kind text,p_start date,p_end date,p_private boolean default false)
returns jsonb language plpgsql stable security invoker set search_path='' as $$
declare result jsonb;
begin
 if auth.uid() is null then raise sqlstate 'PT401' using message='authentication_required'; end if;
 if we2day_private.my_couple() is null then raise sqlstate 'PT409' using message='couple_required'; end if;
 if p_kind is null or p_start is null or p_end is null or p_private is null
   or p_start<date '2000-01-01' or p_end>date '2100-12-31' or p_end<p_start or p_end-p_start>365 then
   raise sqlstate 'PT422' using message='invalid_record_export'; end if;
 case p_kind
 when 'appointments' then
  select coalesce(jsonb_agg(to_jsonb(r)),'[]'::jsonb) into result from
   (select t.id,t.kind,t.title,t.date,t.time,t.place,t.note,t.version,t.created_by,t.updated_by,t.created_at,t.updated_at from public.appointments t where t.date between p_start and p_end order by t.id limit 501) r;
 when 'anniversaries' then
  select coalesce(jsonb_agg(to_jsonb(r)),'[]'::jsonb) into result from
   (select t.id,t.kind,t.title,t.date,t.month,t.day,t.annual,t.version,t.created_by,t.updated_by,t.created_at,t.updated_at from public.anniversaries t order by t.id limit 501) r;
 when 'meeting_days' then
  select coalesce(jsonb_agg(to_jsonb(r)),'[]'::jsonb) into result from
   (select t.date,t.met,t.note,t.version,t.updated_by,t.updated_at from public.meeting_days t where t.date between p_start and p_end order by t.date limit 501) r;
 when 'meeting_routes' then
  select coalesce(jsonb_agg(to_jsonb(r)),'[]'::jsonb) into result from
   (select t.date,t.start_name,t.start_lat,t.start_lng,t.end_name,t.end_lat,t.end_lng,t.version,t.updated_by,t.updated_at from public.meeting_routes t where t.date between p_start and p_end order by t.date limit 501) r;
 when 'date_plans' then
  select coalesce(jsonb_agg(to_jsonb(r)),'[]'::jsonb) into result from
   (select t.id,t.content,t.published_content,t.published_revision,t.appointment_id,t.archived,t.version,t.created_by,t.updated_by,t.created_at,t.updated_at from public.date_plans t where (t.content->>'date')::date between p_start and p_end order by t.id limit 501) r;
 when 'date_reports' then
  select coalesce(jsonb_agg(to_jsonb(r)),'[]'::jsonb) into result from
   (select t.plan_id,t.author_id,t.observed_plan_version,t.plan_snapshot,t.content,t.shared,t.version,t.created_at,t.updated_at from public.date_reports t where (t.plan_snapshot->>'date')::date between p_start and p_end and (t.shared or (p_private and t.author_id=auth.uid())) order by t.plan_id,t.author_id limit 501) r;
 when 'photos' then
  select coalesce(jsonb_agg(to_jsonb(r)),'[]'::jsonb) into result from
   (select t.id,t.date,t.caption,t.filename,t.device,t.captured_at,t.file_modified,t.width,t.height,t.bytes,t.created_by,t.uploaded_at,t.lifecycle_version from public.photos t where t.date between p_start and p_end and t.uploaded_at is not null and t.trashed_at is null and t.purging_at is null order by t.id limit 501) r;
 when 'wishes' then
  select coalesce(jsonb_agg(to_jsonb(r)),'[]'::jsonb) into result from
   (select t.id,t.title,t.kind,t.note,t.done,t.archived,t.version,t.updated_by,t.created_at,t.updated_at from public.wishes t order by t.id limit 501) r;
 when 'shared_checklists' then
  select coalesce(jsonb_agg(to_jsonb(r)),'[]'::jsonb) into result from
   (select t.id,t.title,t.note,t.items,t.archived,t.version,t.updated_by,t.created_at,t.updated_at from public.shared_checklists t order by t.id limit 501) r;
 when 'shared_goals' then
  select coalesce(jsonb_agg(to_jsonb(r)),'[]'::jsonb) into result from
   (select t.id,t.title,t.target_date,t.steps,t.completed,t.archived,t.version,t.updated_by,t.created_at,t.updated_at from public.shared_goals t order by t.id limit 501) r;
 when 'couple_questions' then
  select coalesce(jsonb_agg(to_jsonb(r)),'[]'::jsonb) into result from
   (select t.id,t.date,t.prompt,t.created_by,t.created_at from public.couple_questions t where t.date between p_start and p_end order by t.id limit 501) r;
 when 'question_answers' then
  select coalesce(jsonb_agg(to_jsonb(r)),'[]'::jsonb) into result from
   (select t.question_id,t.author_id,t.content,t.shared,t.skipped,t.version,t.updated_at from public.question_answers t join public.couple_questions q on q.id=t.question_id where q.date between p_start and p_end and (t.shared or (p_private and t.author_id=auth.uid())) order by t.question_id,t.author_id limit 501) r;
 when 'timezone_preferences' then
  select coalesce(jsonb_agg(to_jsonb(r)),'[]'::jsonb) into result from
   (select t.user_id,t.timezone,t.version,t.updated_at from public.timezone_preferences t order by t.user_id limit 501) r;
 when 'roulette_wheels' then
  select coalesce(jsonb_agg(to_jsonb(r)),'[]'::jsonb) into result from
   (select t.id,t.title,t.candidates,t.archived,t.version,t.updated_by,t.updated_at from public.roulette_wheels t order by t.id limit 501) r;
 when 'roulette_draws' then
  select coalesce(jsonb_agg(to_jsonb(r)),'[]'::jsonb) into result from
   (select t.id,t.wheel_id,t.wheel_version,t.candidates,t.selected_index,t.drawn_by,t.drawn_at from public.roulette_draws t where (t.drawn_at at time zone 'Asia/Seoul')::date between p_start and p_end order by t.id limit 501) r;
 when 'plan_visit_progress' then
  select coalesce(jsonb_agg(to_jsonb(r)),'[]'::jsonb) into result from
   (select t.plan_id,t.publication,t.snapshot,t.states,t.version,t.updated_by,t.updated_at from public.plan_visit_progress t where (t.snapshot->>'date')::date between p_start and p_end order by t.plan_id,t.publication limit 501) r;
 else raise sqlstate 'PT422' using message='invalid_record_export';
 end case;
 if jsonb_array_length(result)>500 or octet_length(result::text)>5000000 then
   raise sqlstate 'PT413' using message='record_export_too_large'; end if;
 return result;
end $$;
notify pgrst,'reload schema';
commit;
