begin;

-- Keep the same private queue and three-function worker boundary for both event kinds.
alter table we2day_reminders.deliveries alter column anniversary_id drop not null;
alter table we2day_reminders.deliveries
  add column kind text not null default 'anniversary' check(kind in ('anniversary','appointment_created')),
  add column appointment_id uuid references public.appointments(id) on delete cascade,
  add constraint delivery_source_kind check(
    (kind='anniversary' and anniversary_id is not null and appointment_id is null) or
    (kind='appointment_created' and appointment_id is not null and anniversary_id is null));
create unique index appointment_creation_device_once on we2day_reminders.deliveries
  (appointment_id,owner_id,device_digest) where kind='appointment_created';

create function we2day_private.queue_appointment_created() returns trigger
language plpgsql security definer set search_path='' as $$
begin
  insert into we2day_reminders.deliveries(kind,appointment_id,source_version,couple_id,
    owner_id,device_digest,generation,occurrence_date,lead_days,scheduled_at,deadline)
  select 'appointment_created',new.id,new.version,new.couple_id,s.owner_id,
    encode(extensions.digest(s.endpoint,'sha256'),'hex'),s.generation,new.date,0,
    clock_timestamp(),clock_timestamp()+interval '15 minutes'
  from public.couple_members m join public.push_subscriptions s on s.owner_id=m.user_id
  where m.couple_id=new.couple_id and s.automatic_enabled
    and s.automatic_since<=new.created_at and s.expires_at>now()
  on conflict(appointment_id,owner_id,device_digest) where kind='appointment_created' do nothing;
  return new;
end $$;
revoke all on function we2day_private.queue_appointment_created() from public,anon,authenticated,we2day_reminder_worker;
create trigger appointment_created_notice after insert on public.appointments
  for each row execute function we2day_private.queue_appointment_created();

create or replace function we2day_reminders.claim_due(p_limit integer default 10)
returns jsonb language plpgsql security definer set search_path='' as $$
declare today date := (now() at time zone 'Asia/Seoul')::date;
  scheduled timestamptz; result jsonb;
begin
  if p_limit is null or p_limit not between 1 and 20 then
    raise exception 'invalid_batch';
  end if;
  scheduled := (today+time '09:00') at time zone 'Asia/Seoul';
  -- No replay of yesterday, no catch-up outside the bounded delivery window.

  update we2day_reminders.deliveries set state='unknown',updated_at=now()
    where state='sending' and lease_until<=now();
  update we2day_reminders.deliveries set state='queued',lease=null,lease_until=null,
    updated_at=now() where state='leased' and lease_until<=now();

  update we2day_reminders.deliveries set state='cancelled',updated_at=now()
    where state in ('queued','leased') and deadline<=now();

  if now()>=scheduled and now()<scheduled+interval '1 hour' then
  insert into we2day_reminders.deliveries as target
    (anniversary_id,source_version,couple_id,owner_id,device_digest,generation,
     occurrence_date,lead_days,scheduled_at,deadline)
  select a.id,a.version,a.couple_id,s.owner_id,
    encode(extensions.digest(s.endpoint,'sha256'),'hex'),s.generation,
    today+lead.days,lead.days,scheduled,scheduled+interval '1 hour'
  from public.anniversaries a
  join public.couple_members m on m.couple_id=a.couple_id
  join public.push_subscriptions s on s.owner_id=m.user_id
  cross join (values (7),(1),(0)) as lead(days)
  where s.automatic_enabled and s.automatic_since<=scheduled and s.expires_at>now()
    and we2day_reminders.occurrence(a.date,a.month,a.day,a.annual,today+lead.days)
  on conflict(anniversary_id,occurrence_date,lead_days,owner_id,device_digest)
  do update set source_version=excluded.source_version,generation=excluded.generation,
    state='queued',updated_at=now()
    where target.state in ('queued','cancelled') and target.attempts=0;

  end if;

  with picked as (
    select id from we2day_reminders.deliveries
    where state='queued' and not_before<=now() and scheduled_at<=now() and deadline>now()
    order by scheduled_at,id for update skip locked limit p_limit
  ), claimed as (
    update we2day_reminders.deliveries d set state='leased',lease=gen_random_uuid(),
      lease_until=now()+interval '90 seconds',updated_at=now()
    from picked where d.id=picked.id returning d.id,d.lease
  ) select coalesce(jsonb_agg(jsonb_build_object('id',id,'lease',lease)),'[]'::jsonb)
    into result from claimed;
  return result;
end;
$$;

create or replace function we2day_reminders.authorize_delivery(p_id uuid,p_lease uuid,p_vapid_key text)
returns jsonb language plpgsql security definer set search_path='' as $$
declare job we2day_reminders.deliveries; subscription public.push_subscriptions; valid_source boolean;
  target_date date;
begin
  select * into job from we2day_reminders.deliveries where id=p_id for update;
  if not found or job.state<>'leased' or job.lease is distinct from p_lease
    or job.lease_until<=now() then return null; end if;
  if job.kind='anniversary' then
    select true into valid_source from public.anniversaries a
    where a.id=job.anniversary_id and a.couple_id=job.couple_id and a.version=job.source_version
      and we2day_reminders.occurrence(a.date,a.month,a.day,a.annual,job.occurrence_date);
  else
    select true,a.date into valid_source,target_date from public.appointments a
    where a.id=job.appointment_id and a.couple_id=job.couple_id;
  end if;
  select s.* into subscription from public.push_subscriptions s
    join public.couple_members m on m.user_id=s.owner_id and m.couple_id=job.couple_id
    where s.owner_id=job.owner_id
      and encode(extensions.digest(s.endpoint,'sha256'),'hex')=job.device_digest
      and s.generation=job.generation and s.automatic_enabled
      and s.automatic_since<=job.scheduled_at and s.expires_at>now() and s.vapid_key=p_vapid_key;
  if not found or valid_source is distinct from true or job.deadline<=now() or job.attempts>=3 then
    update we2day_reminders.deliveries set state='cancelled',updated_at=now() where id=p_id;
    return null;
  end if;
  update we2day_reminders.deliveries set state='sending',attempts=attempts+1,
    updated_at=now() where id=p_id;
  return jsonb_build_object('endpoint',subscription.endpoint,'keys',
    jsonb_build_object('p256dh',subscription.p256dh,'auth',subscription.auth_key)) ||
    case when job.kind='appointment_created' then jsonb_build_object('notification',
      jsonb_build_object('type','we2day-appointment-created-v1','date',target_date,'event',job.id))
    else '{}'::jsonb end;
end $$;

-- CREATE OR REPLACE preserves the existing RPC ACL; no additional worker access.
notify pgrst,'reload schema';
commit;
