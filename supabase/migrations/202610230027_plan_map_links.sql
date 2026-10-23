begin;

-- Optional caller-pasted share link; old plan payloads remain valid.
create or replace function we2day_private.validate_plan(c jsonb) returns void
language plpgsql set search_path='' as $$
declare a jsonb; d date;
begin
  if c is null or jsonb_typeof(c)<>'object' or octet_length(c::text)>32768
    or not (c ?& array['title','date','budget','transport','activities','preparation'])
    or (c-array['title','date','budget','transport','activities','preparation'])<>'{}'::jsonb
    or jsonb_typeof(c->'title')<>'string' or char_length(btrim(c->>'title')) not between 1 and 100
    or jsonb_typeof(c->'date')<>'string' or (c->>'date') !~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}$'
    or jsonb_typeof(c->'transport')<>'string' or char_length(c->>'transport')>40
    or jsonb_typeof(c->'activities')<>'array' or jsonb_array_length(c->'activities')>20
    or jsonb_typeof(c->'preparation')<>'array' or jsonb_array_length(c->'preparation')>30 then
    raise sqlstate 'PT422' using message='invalid_plan';
  end if;
  d:=(c->>'date')::date;
  if d not between date '2000-01-01' and date '2100-12-31'
    or jsonb_typeof(c->'budget') not in ('null','number')
    or (c->>'budget' is not null and ((c->>'budget') !~ '^[0-9]{1,10}$'
      or (c->>'budget')::numeric>1000000000)) then
    raise sqlstate 'PT422' using message='invalid_plan';
  end if;
  for a in select value from jsonb_array_elements(c->'activities') loop
    if jsonb_typeof(a)<>'object'
      or not (a ?& array['title','time','place','cost','note'])
      or (a-array['title','time','place','cost','note','map_url'])<>'{}'::jsonb
      or jsonb_typeof(a->'title')<>'string' or char_length(btrim(a->>'title')) not between 1 and 100
      or jsonb_typeof(a->'place')<>'string' or char_length(a->>'place')>200
      or (a ? 'map_url' and (jsonb_typeof(a->'map_url')<>'string' or (a->>'map_url') !~ '^(https://naver[.]me/[A-Za-z0-9_-]{1,80})?$'))
      or jsonb_typeof(a->'note')<>'string' or char_length(a->>'note')>1000
      or (a->>'time' is not null and (a->>'time') !~ '^([01][0-9]|2[0-3]):[0-5][0-9]$')
      or jsonb_typeof(a->'cost') not in ('null','number')
      or (a->>'cost' is not null and ((a->>'cost') !~ '^[0-9]{1,10}$'
        or (a->>'cost')::numeric>1000000000)) then
      raise sqlstate 'PT422' using message='invalid_plan';
    end if;
  end loop;
  for a in select value from jsonb_array_elements(c->'preparation') loop
    if jsonb_typeof(a)<>'string' or char_length(btrim(a#>>'{}')) not between 1 and 200 then
      raise sqlstate 'PT422' using message='invalid_plan';
    end if;
  end loop;
exception when invalid_text_representation or datetime_field_overflow
  or numeric_value_out_of_range or invalid_parameter_value then
  raise sqlstate 'PT422' using message='invalid_plan';
end $$;
revoke all on function we2day_private.validate_plan(jsonb) from public,anon,authenticated;


commit;
