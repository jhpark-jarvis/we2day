begin;
create function we2day_private.valid_roulette_candidates(candidates jsonb) returns boolean
language plpgsql immutable set search_path='' as $$
declare item jsonb; labels text[]:='{}'; label text;
begin
  if candidates is null or jsonb_typeof(candidates)<>'array' then return false; end if;
  if jsonb_array_length(candidates) not between 2 and 20 then return false; end if;
  for item in select value from jsonb_array_elements(candidates) loop
    if jsonb_typeof(item)<>'string' then return false; end if;
    label:=btrim(item#>>'{}');
    if char_length(label) not between 1 and 100 or label=any(labels) then return false; end if;
    labels:=array_append(labels,label);
  end loop;
  return true;
end $$;
revoke all on function we2day_private.valid_roulette_candidates(jsonb) from public,anon,authenticated;
create table public.roulette_wheels (
  id uuid primary key,
  couple_id uuid not null references public.couples(id),
  title text not null check(char_length(btrim(title)) between 1 and 100),
  candidates jsonb not null check(we2day_private.valid_roulette_candidates(candidates)),
  archived boolean not null,
  version integer not null check(version>0),
  updated_by uuid not null references auth.users(id),
  updated_at timestamptz not null default now(),
  last_request_id uuid not null,
  last_fingerprint text not null
);
create index roulette_wheels_space on public.roulette_wheels(couple_id,archived,updated_at desc,id);
create table public.roulette_draws (
  id uuid primary key,
  wheel_id uuid not null references public.roulette_wheels(id),
  couple_id uuid not null references public.couples(id),
  wheel_version integer not null,
  candidates jsonb not null,
  selected_index integer not null check(selected_index>=0),
  drawn_by uuid not null references auth.users(id),
  drawn_at timestamptz not null default clock_timestamp(),
  check(selected_index<jsonb_array_length(candidates))
);
create index roulette_draws_history on public.roulette_draws(couple_id,wheel_id,drawn_at desc,id);
alter table public.roulette_wheels enable row level security;
alter table public.roulette_draws enable row level security;
revoke all on public.roulette_wheels,public.roulette_draws from public,anon,authenticated;
grant select on public.roulette_wheels,public.roulette_draws to authenticated;
create policy wheels_read on public.roulette_wheels for select to authenticated
  using(couple_id=(select we2day_private.my_couple()));
create policy draws_read on public.roulette_draws for select to authenticated
  using(couple_id=(select we2day_private.my_couple()));
create function public.save_roulette(p_id uuid,p_title text,p_candidates jsonb,p_archived boolean,
  p_expected_version integer,p_request_id uuid) returns setof public.roulette_wheels
language plpgsql security definer set search_path='' as $$
declare actor uuid:=we2day_private.actor(); space uuid:=we2day_private.my_couple();
  saved public.roulette_wheels; fp text;
begin
  if space is null then raise sqlstate 'PT409' using message='couple_required'; end if;
  if p_id is null or p_title is null or char_length(btrim(p_title)) not between 1 and 100
    or not we2day_private.valid_roulette_candidates(p_candidates) or p_archived is null
    or p_expected_version is null or p_expected_version not between 0 and 2147483646
    or p_request_id is null then raise sqlstate 'PT422' using message='invalid_roulette'; end if;
  fp:=encode(extensions.digest(jsonb_build_array(p_id,p_title,p_candidates,p_archived,
    p_expected_version)::text,'sha256'),'hex');
  perform 1 from public.couples where id=space for update;
  select * into saved from public.roulette_wheels where id=p_id and couple_id=space for update;
  if found then
    if saved.last_request_id=p_request_id then
      if saved.updated_by<>actor or saved.last_fingerprint<>fp then
        raise sqlstate 'PT409' using message='request_conflict'; end if;
      return next saved; return;
    end if;
    if saved.version<>p_expected_version then raise sqlstate 'PT409' using message='version_conflict'; end if;
    return query update public.roulette_wheels set title=btrim(p_title),candidates=p_candidates,
      archived=p_archived,version=version+1,updated_by=actor,updated_at=clock_timestamp(),
      last_request_id=p_request_id,last_fingerprint=fp where id=p_id returning *;
  else
    if exists(select 1 from public.roulette_wheels where id=p_id) then
      raise sqlstate 'PT404' using message='roulette_not_found'; end if;
    if p_expected_version<>0 then raise sqlstate 'PT409' using message='version_conflict'; end if;
    return query insert into public.roulette_wheels
      (id,couple_id,title,candidates,archived,version,updated_by,last_request_id,last_fingerprint)
      values(p_id,space,btrim(p_title),p_candidates,p_archived,1,actor,p_request_id,fp) returning *;
  end if;
end $$;
create function public.draw_roulette(p_wheel_id uuid,p_expected_version integer,p_request_id uuid)
returns setof public.roulette_draws language plpgsql security definer set search_path='' as $$
declare actor uuid:=we2day_private.actor(); space uuid:=we2day_private.my_couple();
  wheel public.roulette_wheels; draw public.roulette_draws;
begin
  if space is null then raise sqlstate 'PT409' using message='couple_required'; end if;
  if p_expected_version is null or p_expected_version<1 or p_request_id is null then
    raise sqlstate 'PT422' using message='invalid_roulette'; end if;
  perform 1 from public.couples where id=space for update;
  select * into draw from public.roulette_draws where id=p_request_id;
  if found then
    if draw.couple_id<>space or draw.wheel_id<>p_wheel_id or draw.drawn_by<>actor
      or draw.wheel_version<>p_expected_version then
      raise sqlstate 'PT409' using message='request_conflict'; end if;
    return next draw; return;
  end if;
  select * into wheel from public.roulette_wheels where id=p_wheel_id and couple_id=space for update;
  if not found then raise sqlstate 'PT404' using message='roulette_not_found'; end if;
  if wheel.version<>p_expected_version then raise sqlstate 'PT409' using message='version_conflict'; end if;
  if wheel.archived then raise sqlstate 'PT409' using message='roulette_archived'; end if;
  return query insert into public.roulette_draws
    (id,wheel_id,couple_id,wheel_version,candidates,selected_index,drawn_by)
    values(p_request_id,p_wheel_id,space,wheel.version,wheel.candidates,
      floor(random()*jsonb_array_length(wheel.candidates))::integer,actor) returning *;
end $$;
revoke all on function public.save_roulette(uuid,text,jsonb,boolean,integer,uuid),
  public.draw_roulette(uuid,integer,uuid) from public,anon,authenticated;
grant execute on function public.save_roulette(uuid,text,jsonb,boolean,integer,uuid),
  public.draw_roulette(uuid,integer,uuid) to authenticated;
notify pgrst,'reload schema';
commit;
