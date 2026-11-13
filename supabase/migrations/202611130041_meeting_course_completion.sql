begin;

-- Explicitly marking a day as met completes only its current, linked shared courses.
-- The trigger is in the save transaction: a failed completion cannot leave a half-save.
create function we2day_private.complete_met_day_courses() returns trigger
language plpgsql security definer set search_path='' as $$
declare plan public.date_plans; completed text[]; fingerprint text;
begin
  if not new.met then return new; end if;
  if tg_op='UPDATE' and old.met then return new; end if;
  perform 1 from public.couples where id=new.couple_id for update;
  for plan in
    select p.* from public.date_plans p
      join public.appointments a on a.id=p.appointment_id and a.couple_id=p.couple_id
    where p.couple_id=new.couple_id and not p.archived and a.kind='shared'
      and a.date=new.date and p.published_content->>'date'=new.date::text
      and p.published_revision>0 and jsonb_array_length(p.published_content->'activities')>0
    order by p.id for update of p
  loop
    completed:=array_fill('visited'::text,array[jsonb_array_length(plan.published_content->'activities')]);
    fingerprint:=encode(extensions.digest(jsonb_build_array('met_day',new.date,plan.id,
      plan.published_revision,new.last_request_id)::text,'sha256'),'hex');
    insert into public.plan_visit_progress as target
      (plan_id,publication,couple_id,snapshot,states,version,updated_by,last_request_id,last_fingerprint)
    values(plan.id,plan.published_revision,new.couple_id,plan.published_content,completed,1,
      new.updated_by,new.last_request_id,fingerprint)
    on conflict(plan_id,publication) do update set states=excluded.states,
      version=target.version+1,updated_by=excluded.updated_by,updated_at=clock_timestamp(),
      last_request_id=excluded.last_request_id,last_fingerprint=excluded.last_fingerprint
      where target.states is distinct from excluded.states;
  end loop;
  return new;
end $$;
revoke all on function we2day_private.complete_met_day_courses() from public,anon,authenticated,we2day_reminder_worker;
create trigger meeting_day_course_completion after insert or update of met on public.meeting_days
  for each row execute function we2day_private.complete_met_day_courses();

notify pgrst,'reload schema';
commit;
