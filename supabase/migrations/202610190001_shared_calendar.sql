begin;

create schema if not exists extensions;
create extension if not exists pgcrypto with schema extensions;
create schema we2day_private;
revoke all on schema we2day_private from public;
grant usage on schema we2day_private to authenticated;

create table public.couples (
  id uuid primary key default gen_random_uuid(),
  created_at timestamptz not null default now()
);
create table public.couple_members (
  user_id uuid primary key references auth.users(id),
  couple_id uuid not null references public.couples(id),
  joined_at timestamptz not null default now()
);
create index couple_members_couple on public.couple_members(couple_id);
create table public.couple_invites (
  token_hash text primary key,
  couple_id uuid not null unique references public.couples(id),
  created_by uuid not null references auth.users(id),
  expires_at timestamptz not null
);
create table public.appointments (
  id uuid primary key default gen_random_uuid(),
  couple_id uuid not null references public.couples(id),
  title text not null check (char_length(btrim(title)) between 1 and 100),
  date date not null check (date between date '2000-01-01' and date '2100-12-31'),
  time time without time zone check (time < time '24:00' and extract(second from time) = 0),
  place text not null default '' check (char_length(place) <= 200),
  note text not null default '' check (char_length(note) <= 2000),
  version integer not null default 1 check (version > 0),
  created_by uuid not null references auth.users(id),
  updated_by uuid not null references auth.users(id),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  request_id uuid not null,
  creation_fingerprint text not null,
  unique (created_by, request_id)
);
create index appointments_month on public.appointments(couple_id, date, time, id);

alter table public.couples enable row level security;
alter table public.couple_members enable row level security;
alter table public.couple_invites enable row level security;
alter table public.appointments enable row level security;
revoke all on public.couples, public.couple_members, public.couple_invites,
  public.appointments from public, anon, authenticated;
grant select on public.couples, public.couple_members, public.appointments to authenticated;

create function we2day_private.actor() returns uuid
language plpgsql stable security definer set search_path = '' as $$
declare actor uuid := auth.uid();
begin
  if actor is null then raise sqlstate 'PT401' using message = 'authentication_required'; end if;
  return actor;
end;
$$;

create function we2day_private.my_couple() returns uuid
language sql stable security definer set search_path = '' as $$
  select couple_id from public.couple_members where user_id = auth.uid();
$$;
revoke all on function we2day_private.actor(), we2day_private.my_couple() from public, anon, authenticated;
grant execute on function we2day_private.my_couple() to authenticated;

create policy couples_read on public.couples for select to authenticated
  using (id = (select we2day_private.my_couple()));
create policy members_read on public.couple_members for select to authenticated
  using (couple_id = (select we2day_private.my_couple()));
create policy appointments_read on public.appointments for select to authenticated
  using (couple_id = (select we2day_private.my_couple()));

create function public.get_my_couple() returns jsonb
language plpgsql stable security definer set search_path = '' as $$
declare actor uuid := we2day_private.actor(); space uuid;
begin
  select couple_id into space from public.couple_members where user_id = actor;
  if space is null then return null; end if;
  return jsonb_build_object('id', space, 'member_count',
    (select count(*) from public.couple_members where couple_id = space));
end;
$$;

create function public.create_couple() returns jsonb
language plpgsql security definer set search_path = '' as $$
declare actor uuid := we2day_private.actor(); space uuid;
begin
  perform pg_advisory_xact_lock(hashtextextended(actor::text, 0));
  if exists(select 1 from public.couple_members where user_id = actor) then
    raise sqlstate 'PT409' using message = 'already_connected';
  end if;
  insert into public.couples default values returning id into space;
  insert into public.couple_members(user_id, couple_id) values(actor, space);
  return public.get_my_couple();
end;
$$;

create function public.create_couple_invite() returns jsonb
language plpgsql security definer set search_path = '' as $$
declare actor uuid := we2day_private.actor(); space uuid := we2day_private.my_couple();
  token text; expiry timestamptz := clock_timestamp() + interval '24 hours';
begin
  if space is null then raise sqlstate 'PT409' using message = 'couple_required'; end if;
  perform 1 from public.couples where id = space for update;
  if (select count(*) from public.couple_members where couple_id = space) <> 1 then
    raise sqlstate 'PT409' using message = 'couple_full';
  end if;
  token := encode(extensions.gen_random_bytes(32), 'hex');
  delete from public.couple_invites where couple_id = space;
  insert into public.couple_invites(token_hash, couple_id, created_by, expires_at)
    values(encode(extensions.digest(token, 'sha256'), 'hex'), space, actor, expiry);
  return jsonb_build_object('token', token, 'expires_at', expiry);
end;
$$;

create function public.accept_couple_invite(p_token text) returns jsonb
language plpgsql security definer set search_path = '' as $$
declare actor uuid := we2day_private.actor(); space uuid; invite public.couple_invites;
  hash text;
begin
  if p_token is null or p_token !~ '^[0-9a-f]{64}$' then
    raise sqlstate 'PT400' using message = 'invalid_invite';
  end if;
  perform pg_advisory_xact_lock(hashtextextended(actor::text, 0));
  if exists(select 1 from public.couple_members where user_id = actor) then
    raise sqlstate 'PT409' using message = 'already_connected';
  end if;
  hash := encode(extensions.digest(p_token, 'sha256'), 'hex');
  select couple_id into space from public.couple_invites where token_hash = hash;
  if space is null then raise sqlstate 'PT400' using message = 'invalid_invite'; end if;
  -- All invite paths lock the couple before the invite to avoid lock inversion.
  perform 1 from public.couples where id = space for update;
  select * into invite from public.couple_invites where token_hash = hash for update;
  if not found or invite.expires_at <= clock_timestamp() or invite.created_by = actor then
    raise sqlstate 'PT400' using message = 'invalid_invite';
  end if;
  if (select count(*) from public.couple_members where couple_id = space) >= 2 then
    raise sqlstate 'PT409' using message = 'couple_full';
  end if;
  insert into public.couple_members(user_id, couple_id) values(actor, space);
  delete from public.couple_invites where couple_id = space;
  return public.get_my_couple();
end;
$$;

create function we2day_private.validate_appointment(
  p_title text, p_date date, p_time time, p_place text, p_note text
) returns void language plpgsql immutable set search_path = '' as $$
begin
  if p_title is null or char_length(btrim(p_title)) not between 1 and 100
    or p_date is null or p_date not between date '2000-01-01' and date '2100-12-31'
    or (p_time is not null and (p_time >= time '24:00' or extract(second from p_time) <> 0))
    or p_place is null or char_length(p_place) > 200
    or p_note is null or char_length(p_note) > 2000 then
    raise sqlstate 'PT422' using message = 'invalid_appointment';
  end if;
end;
$$;
revoke all on function we2day_private.validate_appointment(text,date,time,text,text)
  from public, anon, authenticated;

create function public.create_appointment(
  p_title text, p_date date, p_time time, p_place text, p_note text, p_request_id uuid
) returns setof public.appointments
language plpgsql security definer set search_path = '' as $$
declare actor uuid := we2day_private.actor(); space uuid := we2day_private.my_couple();
  fingerprint text; existing public.appointments;
begin
  if space is null then raise sqlstate 'PT409' using message = 'couple_required'; end if;
  perform we2day_private.validate_appointment(p_title, p_date, p_time, p_place, p_note);
  if p_request_id is null then raise sqlstate 'PT422' using message = 'invalid_request'; end if;
  fingerprint := encode(extensions.digest(
    jsonb_build_array(btrim(p_title),p_date,p_time,p_place,p_note)::text, 'sha256'), 'hex');
  perform pg_advisory_xact_lock(hashtextextended(actor::text || p_request_id::text, 0));
  select * into existing from public.appointments where created_by = actor and request_id = p_request_id;
  if found then
    if existing.creation_fingerprint <> fingerprint then
      raise sqlstate 'PT409' using message = 'request_conflict';
    end if;
    return next existing;
    return;
  end if;
  return query insert into public.appointments(couple_id,title,date,time,place,note,
    created_by,updated_by,request_id,creation_fingerprint)
    values(space,btrim(p_title),p_date,p_time,p_place,p_note,actor,actor,p_request_id,fingerprint)
    returning *;
end;
$$;

create function public.update_appointment(
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
  if p_expected_version is null or p_expected_version <> existing.version then
    raise sqlstate 'PT409' using message = 'version_conflict';
  end if;
  return query update public.appointments set title = btrim(p_title), date = p_date, time = p_time,
    place = p_place, note = p_note, version = version + 1, updated_by = actor,
    updated_at = clock_timestamp() where id = p_id returning *;
end;
$$;

revoke all on function public.get_my_couple(), public.create_couple(),
  public.create_couple_invite(), public.accept_couple_invite(text),
  public.create_appointment(text,date,time,text,text,uuid),
  public.update_appointment(uuid,integer,text,date,time,text,text) from public, anon, authenticated;
grant execute on function public.get_my_couple(), public.create_couple(),
  public.create_couple_invite(), public.accept_couple_invite(text),
  public.create_appointment(text,date,time,text,text,uuid),
  public.update_appointment(uuid,integer,text,date,time,text,text) to authenticated;

notify pgrst, 'reload schema';
commit;
