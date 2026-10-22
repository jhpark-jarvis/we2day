begin;

create table public.anniversaries (
  id uuid primary key default gen_random_uuid(),
  couple_id uuid not null references public.couples(id),
  kind text not null check (kind in ('relationship', 'birthday', 'custom')),
  title text not null check (char_length(btrim(title)) between 1 and 100),
  date date check (date between date '1900-01-01' and date '2100-12-31'),
  month integer,
  day integer,
  annual boolean not null,
  version integer not null default 1 check (version > 0),
  created_by uuid not null references auth.users(id),
  updated_by uuid not null references auth.users(id),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  request_id uuid not null,
  creation_fingerprint text not null,
  unique (created_by, request_id),
  constraint anniversary_original check (
    (kind = 'birthday' and date is null and month is not null and day is not null
      and month between 1 and 12 and day between 1 and
        extract(day from (make_date(2000, month, 1) + interval '1 month - 1 day')) and annual)
    or (kind in ('relationship', 'custom') and date is not null
      and month is null and day is null and (kind <> 'relationship' or annual))
  )
);
create unique index one_relationship_per_couple on public.anniversaries(couple_id)
  where kind = 'relationship';
create index anniversaries_couple on public.anniversaries(couple_id, id);
alter table public.anniversaries enable row level security;
revoke all on public.anniversaries from public, anon, authenticated;
grant select on public.anniversaries to authenticated;
create policy anniversaries_read on public.anniversaries for select to authenticated
  using (couple_id = (select we2day_private.my_couple()));

create function we2day_private.validate_anniversary(
  p_kind text, p_title text, p_date date, p_month integer, p_day integer, p_annual boolean
) returns void language plpgsql immutable set search_path = '' as $$
begin
  if p_kind is null or p_kind not in ('relationship','birthday','custom')
    or p_title is null or char_length(btrim(p_title)) not between 1 and 100
    or p_annual is null then
    raise sqlstate 'PT422' using message = 'invalid_anniversary';
  end if;
  if p_kind = 'birthday' then
    if p_date is not null or p_month is null or p_month not between 1 and 12
      or p_day is null or p_day not between 1 and 31 or not p_annual then
      raise sqlstate 'PT422' using message = 'invalid_anniversary';
    end if;
    if p_day > extract(day from (make_date(2000, p_month, 1) + interval '1 month - 1 day')) then
      raise sqlstate 'PT422' using message = 'invalid_anniversary';
    end if;
  elsif p_date is null or p_date not between date '1900-01-01' and date '2100-12-31'
    or p_month is not null or p_day is not null or (p_kind = 'relationship' and not p_annual) then
    raise sqlstate 'PT422' using message = 'invalid_anniversary';
  end if;
end;
$$;
revoke all on function we2day_private.validate_anniversary(text,text,date,integer,integer,boolean)
  from public, anon, authenticated;

create function public.create_anniversary(
  p_kind text, p_title text, p_date date, p_month integer, p_day integer,
  p_annual boolean, p_request_id uuid
) returns setof public.anniversaries
language plpgsql security definer set search_path = '' as $$
declare actor uuid := we2day_private.actor(); space uuid := we2day_private.my_couple();
  fingerprint text; existing public.anniversaries;
begin
  if space is null then raise sqlstate 'PT409' using message = 'couple_required'; end if;
  perform we2day_private.validate_anniversary(p_kind,p_title,p_date,p_month,p_day,p_annual);
  if p_request_id is null then raise sqlstate 'PT422' using message = 'invalid_request'; end if;
  fingerprint := encode(extensions.digest(
    jsonb_build_array(p_kind,btrim(p_title),p_date,p_month,p_day,p_annual)::text, 'sha256'), 'hex');
  -- Serialize creates/updates within a couple, including the unique relationship baseline.
  perform 1 from public.couples where id = space for update;
  select * into existing from public.anniversaries where created_by = actor and request_id = p_request_id;
  if found then
    if existing.creation_fingerprint <> fingerprint then
      raise sqlstate 'PT409' using message = 'request_conflict';
    end if;
    return next existing;
    return;
  end if;
  if p_kind = 'relationship' and exists(
    select 1 from public.anniversaries where couple_id = space and kind = 'relationship'
  ) then raise sqlstate 'PT409' using message = 'relationship_exists'; end if;
  return query insert into public.anniversaries(couple_id,kind,title,date,month,day,annual,
    created_by,updated_by,request_id,creation_fingerprint)
    values(space,p_kind,btrim(p_title),p_date,p_month,p_day,p_annual,actor,actor,p_request_id,fingerprint)
    returning *;
end;
$$;

create function public.update_anniversary(
  p_id uuid, p_expected_version integer, p_kind text, p_title text, p_date date,
  p_month integer, p_day integer, p_annual boolean
) returns setof public.anniversaries
language plpgsql security definer set search_path = '' as $$
declare actor uuid := we2day_private.actor(); space uuid := we2day_private.my_couple();
  existing public.anniversaries;
begin
  perform we2day_private.validate_anniversary(p_kind,p_title,p_date,p_month,p_day,p_annual);
  perform 1 from public.couples where id = space for update;
  select * into existing from public.anniversaries where id = p_id and couple_id = space for update;
  if not found then raise sqlstate 'PT404' using message = 'anniversary_not_found'; end if;
  if p_expected_version is null or p_expected_version <> existing.version then
    raise sqlstate 'PT409' using message = 'version_conflict';
  end if;
  if p_kind <> existing.kind then
    raise sqlstate 'PT422' using message = 'invalid_anniversary';
  end if;
  return query update public.anniversaries set title=btrim(p_title), date=p_date,
    month=p_month, day=p_day, annual=p_annual, version=version+1,
    updated_by=actor, updated_at=clock_timestamp() where id=p_id returning *;
end;
$$;
revoke all on function public.create_anniversary(text,text,date,integer,integer,boolean,uuid),
  public.update_anniversary(uuid,integer,text,text,date,integer,integer,boolean) from public, anon, authenticated;
grant execute on function public.create_anniversary(text,text,date,integer,integer,boolean,uuid),
  public.update_anniversary(uuid,integer,text,text,date,integer,integer,boolean) to authenticated;

notify pgrst, 'reload schema';
commit;
