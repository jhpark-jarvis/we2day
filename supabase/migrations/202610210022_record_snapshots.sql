begin;
-- A single statement snapshot under caller visibility; no stored copies or security definer.
create function public.export_record_snapshot(p_kind text,p_start date,p_end date,p_private boolean default false)
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
   (select t.id,t.title,t.date,t.time,t.place,t.note,t.version,t.created_by,t.updated_by,t.created_at,t.updated_at from public.appointments t where t.date between p_start and p_end order by t.id limit 501) r;
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
revoke all on function public.export_record_snapshot(text,date,date,boolean) from public,anon,authenticated;
grant execute on function public.export_record_snapshot(text,date,date,boolean) to authenticated;
notify pgrst,'reload schema';
commit;
