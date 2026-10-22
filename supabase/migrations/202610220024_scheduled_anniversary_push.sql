begin;

-- A separate, initially non-login principal. Provision its password outside migrations.
create role we2day_reminder_worker nologin noinherit nosuperuser nocreatedb nocreaterole
  noreplication nobypassrls connection limit 2;
alter role we2day_reminder_worker set statement_timeout = '10s';
alter role we2day_reminder_worker set lock_timeout = '2s';
alter role we2day_reminder_worker set idle_in_transaction_session_timeout = '15s';

alter table public.push_subscriptions
  add column automatic_enabled boolean not null default false,
  add column automatic_since timestamptz,
  add column generation uuid not null default gen_random_uuid(),
  add constraint automatic_consent check (automatic_enabled = (automatic_since is not null));

create or replace function public.manage_push_subscription(
  p_action text, p_endpoint text default '', p_p256dh text default '',
  p_auth text default '', p_vapid_key text default ''
) returns jsonb language plpgsql security definer set search_path = '' as $$
declare
  actor uuid := we2day_private.actor();
  row public.push_subscriptions;
begin
  perform 1 from auth.users where id = actor for update;
  if p_action = 'remove_all' then
    delete from public.push_subscriptions where owner_id = actor;
    return jsonb_build_object('enabled',false);
  end if;
  if p_action is null or p_action not in
    ('register','status','remove','claim','automatic_on','automatic_off')
    or p_endpoint is null or char_length(p_endpoint) > 2048
    or p_endpoint !~ '^https://(web[.]push[.]apple[.]com/[A-Za-z0-9_/-]+|fcm[.]googleapis[.]com/fcm/send/[A-Za-z0-9_-]+|updates[.]push[.]services[.]mozilla[.]com/wpush/v2/[A-Za-z0-9_-]+)$'
  then raise sqlstate 'PT422' using message = 'invalid_push_subscription'; end if;
  if p_action = 'remove' then
    delete from public.push_subscriptions where owner_id = actor and endpoint = p_endpoint;
    return jsonb_build_object('enabled',false);
  end if;
  select * into row from public.push_subscriptions where owner_id = actor and endpoint = p_endpoint;
  if p_action = 'automatic_off' then
    update public.push_subscriptions set automatic_enabled=false, automatic_since=null,
      generation=gen_random_uuid() where owner_id=actor and endpoint=p_endpoint;
    return jsonb_build_object('automatic_enabled',false);
  end if;
  if p_action = 'status' then
    return jsonb_build_object(
      'enabled',coalesce(row.expires_at>now() and row.vapid_key=p_vapid_key,false),
      'automatic_enabled',coalesce(row.automatic_enabled and row.expires_at>now()
        and row.vapid_key=p_vapid_key and we2day_private.my_couple() is not null,false));
  end if;
  if we2day_private.my_couple() is null then
    raise sqlstate 'PT409' using message = 'couple_required';
  end if;
  if p_action = 'register' then
    if p_p256dh is null or p_p256dh !~ '^[A-Za-z0-9_-]{87}$'
      or p_auth is null or p_auth !~ '^[A-Za-z0-9_-]{22}$'
      or p_vapid_key is null or p_vapid_key !~ '^[A-Za-z0-9_-]{87}$'
    then raise sqlstate 'PT422' using message = 'invalid_push_subscription'; end if;
    delete from public.push_subscriptions where owner_id=actor and expires_at<=now();
    if not exists(select 1 from public.push_subscriptions where owner_id=actor and endpoint=p_endpoint)
      and (select count(*) from public.push_subscriptions where owner_id=actor)>=5 then
      raise sqlstate 'PT409' using message = 'push_device_limit';
    end if;
    insert into public.push_subscriptions(owner_id,endpoint,p256dh,auth_key,vapid_key,expires_at)
    values(actor,p_endpoint,p_p256dh,p_auth,p_vapid_key,now()+interval '30 days')
    on conflict(owner_id,endpoint) do update set
      p256dh=excluded.p256dh,auth_key=excluded.auth_key,vapid_key=excluded.vapid_key,
      expires_at=excluded.expires_at,
      automatic_enabled=case when push_subscriptions.p256dh=excluded.p256dh
        and push_subscriptions.auth_key=excluded.auth_key
        and push_subscriptions.vapid_key=excluded.vapid_key
        then push_subscriptions.automatic_enabled else false end,
      automatic_since=case when push_subscriptions.p256dh=excluded.p256dh
        and push_subscriptions.auth_key=excluded.auth_key
        and push_subscriptions.vapid_key=excluded.vapid_key
        then push_subscriptions.automatic_since else null end,
      generation=case when push_subscriptions.p256dh=excluded.p256dh
        and push_subscriptions.auth_key=excluded.auth_key
        and push_subscriptions.vapid_key=excluded.vapid_key
        then push_subscriptions.generation else gen_random_uuid() end;
    return jsonb_build_object('enabled',true);
  end if;
  if row.owner_id is null or row.expires_at<=now() or row.vapid_key<>p_vapid_key then
    raise sqlstate 'PT409' using message = 'push_registration_required';
  end if;
  if p_action = 'automatic_on' then
    update public.push_subscriptions set automatic_enabled=true,
      automatic_since=coalesce(automatic_since,now()),
      generation=case when automatic_enabled then generation else gen_random_uuid() end
      where owner_id=actor and endpoint=p_endpoint;
    return jsonb_build_object('automatic_enabled',true);
  end if;
  if row.last_test_at > now()-interval '60 seconds' then
    raise sqlstate 'PT409' using message = 'push_test_limited';
  end if;
  update public.push_subscriptions set last_test_at=now()
    where owner_id=actor and endpoint=p_endpoint;
  return jsonb_build_object('endpoint',row.endpoint,'keys',
    jsonb_build_object('p256dh',row.p256dh,'auth',row.auth_key));
end;
$$;

create schema we2day_reminders;
revoke all on schema we2day_reminders from public, anon, authenticated;
grant usage on schema we2day_reminders to we2day_reminder_worker;

create table we2day_reminders.deliveries (
  id uuid primary key default gen_random_uuid(),
  anniversary_id uuid not null references public.anniversaries(id) on delete cascade,
  source_version integer not null,
  couple_id uuid not null references public.couples(id),
  owner_id uuid not null references auth.users(id) on delete cascade,
  device_digest text not null check (device_digest ~ '^[0-9a-f]{64}$'),
  generation uuid not null,
  occurrence_date date not null,
  lead_days integer not null check (lead_days in (7,1,0)),
  scheduled_at timestamptz not null,
  deadline timestamptz not null,
  state text not null default 'queued' check
    (state in ('queued','leased','sending','accepted','expired','cancelled','failed','unknown')),
  attempts integer not null default 0 check (attempts between 0 and 3),
  not_before timestamptz not null default now(),
  lease uuid,
  lease_until timestamptz,
  updated_at timestamptz not null default now(),
  unique(anniversary_id,occurrence_date,lead_days,owner_id,device_digest)
);
alter table we2day_reminders.deliveries enable row level security;
revoke all on we2day_reminders.deliveries from public, anon, authenticated, we2day_reminder_worker;
create index reminder_pending on we2day_reminders.deliveries(state,not_before,scheduled_at);

-- Pure Gregorian occurrence, matching the API's originals and Feb-29 clamping.
create function we2day_reminders.occurrence(
  p_date date,p_month integer,p_day integer,p_annual boolean,p_target date
) returns boolean language sql immutable set search_path='' as $$
  select case when not p_annual then p_date=p_target else
    (p_date is null or p_target>=p_date) and
    p_target=make_date(extract(year from p_target)::integer,
      coalesce(extract(month from p_date)::integer,p_month),
      least(coalesce(extract(day from p_date)::integer,p_day),
        extract(day from (make_date(extract(year from p_target)::integer,
          coalesce(extract(month from p_date)::integer,p_month),1)
          +interval '1 month - 1 day'))::integer))
    end;
$$;
revoke all on function we2day_reminders.occurrence(date,integer,integer,boolean,date)
  from public,anon,authenticated,we2day_reminder_worker;

create function we2day_reminders.claim_due(p_limit integer default 10)
returns jsonb language plpgsql security definer set search_path='' as $$
declare today date := (now() at time zone 'Asia/Seoul')::date;
  scheduled timestamptz; result jsonb;
begin
  if p_limit is null or p_limit not between 1 and 20 then
    raise exception 'invalid_batch';
  end if;
  scheduled := (today+time '09:00') at time zone 'Asia/Seoul';
  -- No replay of yesterday, no catch-up outside the bounded delivery window.
  if now()<scheduled or now()>=scheduled+interval '1 hour' then return '[]'::jsonb; end if;
  update we2day_reminders.deliveries set state='unknown',updated_at=now()
    where state='sending' and lease_until<=now();
  update we2day_reminders.deliveries set state='queued',lease=null,lease_until=null,
    updated_at=now() where state='leased' and lease_until<=now();

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

create function we2day_reminders.authorize_delivery(p_id uuid,p_lease uuid,p_vapid_key text)
returns jsonb language plpgsql security definer set search_path='' as $$
declare job we2day_reminders.deliveries; subscription public.push_subscriptions;
begin
  select * into job from we2day_reminders.deliveries where id=p_id for update;
  if not found or job.state<>'leased' or job.lease is distinct from p_lease
    or job.lease_until<=now() then return null; end if;
  select s.* into subscription from public.push_subscriptions s
    join public.couple_members m on m.user_id=s.owner_id and m.couple_id=job.couple_id
    join public.anniversaries a on a.id=job.anniversary_id and a.couple_id=job.couple_id
    where s.owner_id=job.owner_id
      and encode(extensions.digest(s.endpoint,'sha256'),'hex')=job.device_digest
      and s.generation=job.generation and s.automatic_enabled
      and s.automatic_since<=job.scheduled_at and s.expires_at>now()
      and s.vapid_key=p_vapid_key and a.version=job.source_version
      and we2day_reminders.occurrence(a.date,a.month,a.day,a.annual,job.occurrence_date);
  if not found or job.deadline<=now() or job.attempts>=3 then
    update we2day_reminders.deliveries set state='cancelled',updated_at=now() where id=p_id;
    return null;
  end if;
  update we2day_reminders.deliveries set state='sending',attempts=attempts+1,
    updated_at=now() where id=p_id;
  return jsonb_build_object('endpoint',subscription.endpoint,'keys',
    jsonb_build_object('p256dh',subscription.p256dh,'auth',subscription.auth_key));
end;
$$;

create function we2day_reminders.finish_delivery(p_id uuid,p_lease uuid,p_outcome text)
returns boolean language plpgsql security definer set search_path='' as $$
declare job we2day_reminders.deliveries; next_state text;
begin
  if p_outcome is null or p_outcome not in ('accepted','expired','retry','rejected','unknown')
    then raise exception 'invalid_outcome'; end if;
  select * into job from we2day_reminders.deliveries where id=p_id for update;
  if not found or job.state<>'sending' or job.lease is distinct from p_lease
    or job.lease_until<=now() then return false; end if;
  next_state := case p_outcome
    when 'rejected' then 'failed'
    when 'retry' then case when job.attempts<3
      and now()+make_interval(mins=>2*job.attempts)<job.deadline then 'queued' else 'failed' end
    else p_outcome end;
  update we2day_reminders.deliveries set state=next_state,
    not_before=now()+make_interval(mins=>2*job.attempts),updated_at=now() where id=p_id;
  if p_outcome='expired' then
    delete from public.push_subscriptions where owner_id=job.owner_id
      and encode(extensions.digest(endpoint,'sha256'),'hex')=job.device_digest
      and generation=job.generation;
  end if;
  return true;
end;
$$;
revoke all on function we2day_reminders.claim_due(integer),
  we2day_reminders.authorize_delivery(uuid,uuid,text),
  we2day_reminders.finish_delivery(uuid,uuid,text) from public,anon,authenticated;
grant execute on function we2day_reminders.claim_due(integer),
  we2day_reminders.authorize_delivery(uuid,uuid,text),
  we2day_reminders.finish_delivery(uuid,uuid,text) to we2day_reminder_worker;

notify pgrst,'reload schema';
commit;
