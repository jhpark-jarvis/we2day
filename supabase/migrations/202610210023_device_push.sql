begin;

create table public.push_subscriptions (
  owner_id uuid not null references auth.users(id) on delete cascade,
  endpoint text not null check (char_length(endpoint) between 20 and 2048),
  p256dh text not null,
  auth_key text not null,
  vapid_key text not null,
  expires_at timestamptz not null,
  last_test_at timestamptz,
  primary key (owner_id, endpoint)
);
alter table public.push_subscriptions enable row level security;
revoke all on public.push_subscriptions from public, anon, authenticated;
grant select on public.push_subscriptions to authenticated;
create policy push_owner_read on public.push_subscriptions for select to authenticated
  using (owner_id = (select auth.uid()));

create function public.manage_push_subscription(
  p_action text, p_endpoint text default '', p_p256dh text default '',
  p_auth text default '', p_vapid_key text default ''
) returns jsonb language plpgsql security definer set search_path = '' as $$
declare
  actor uuid := we2day_private.actor();
  row public.push_subscriptions;
begin
  -- One account lock serializes registration limits, test cooldown and revocation.
  perform 1 from auth.users where id = actor for update;
  if p_action = 'remove_all' then
    delete from public.push_subscriptions where owner_id = actor;
    return jsonb_build_object('enabled',false);
  end if;
  if p_action not in ('register','status','remove','claim') or p_action is null
    or p_endpoint is null or char_length(p_endpoint) > 2048
    or p_endpoint !~ '^https://(web[.]push[.]apple[.]com/[A-Za-z0-9_/-]+|fcm[.]googleapis[.]com/fcm/send/[A-Za-z0-9_-]+|updates[.]push[.]services[.]mozilla[.]com/wpush/v2/[A-Za-z0-9_-]+)$'
  then raise sqlstate 'PT422' using message = 'invalid_push_subscription'; end if;
  if p_action = 'remove' then
    delete from public.push_subscriptions where owner_id = actor and endpoint = p_endpoint;
    return jsonb_build_object('enabled',false);
  end if;
  select * into row from public.push_subscriptions where owner_id = actor and endpoint = p_endpoint;
  if p_action = 'status' then
    return jsonb_build_object('enabled',coalesce(row.expires_at > now() and row.vapid_key = p_vapid_key,false));
  end if;
  if we2day_private.my_couple() is null then
    raise sqlstate 'PT409' using message = 'couple_required';
  end if;
  if p_action = 'register' then
    if p_p256dh is null or p_p256dh !~ '^[A-Za-z0-9_-]{87}$'
      or p_auth is null or p_auth !~ '^[A-Za-z0-9_-]{22}$'
      or p_vapid_key is null or p_vapid_key !~ '^[A-Za-z0-9_-]{87}$'
    then raise sqlstate 'PT422' using message = 'invalid_push_subscription'; end if;
    delete from public.push_subscriptions where owner_id = actor and expires_at <= now();
    if not exists(select 1 from public.push_subscriptions where owner_id = actor and endpoint = p_endpoint) and (select count(*) from public.push_subscriptions where owner_id = actor) >= 5 then
      raise sqlstate 'PT409' using message = 'push_device_limit';
    end if;
    insert into public.push_subscriptions(owner_id,endpoint,p256dh,auth_key,vapid_key,expires_at)
    values(actor,p_endpoint,p_p256dh,p_auth,p_vapid_key,now()+interval '30 days')
    on conflict(owner_id,endpoint) do update set
      p256dh=excluded.p256dh,auth_key=excluded.auth_key,vapid_key=excluded.vapid_key,
      expires_at=excluded.expires_at;
    return jsonb_build_object('enabled',true);
  end if;
  if row.owner_id is null or row.expires_at <= now() or row.vapid_key <> p_vapid_key then
    raise sqlstate 'PT409' using message = 'push_registration_required';
  end if;
  if row.last_test_at > now()-interval '60 seconds' then
    raise sqlstate 'PT409' using message = 'push_test_limited';
  end if;
  update public.push_subscriptions set last_test_at = now()
    where owner_id = actor and endpoint = p_endpoint;
  return jsonb_build_object('endpoint',row.endpoint,'keys',
    jsonb_build_object('p256dh',row.p256dh,'auth',row.auth_key));
end;
$$;
revoke all on function public.manage_push_subscription(text,text,text,text,text) from public, anon, authenticated;
grant execute on function public.manage_push_subscription(text,text,text,text,text) to authenticated;
notify pgrst,'reload schema';
commit;
