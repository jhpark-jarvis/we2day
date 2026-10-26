begin;
-- New keys only; existing expiry/revocation/scope are unchanged.
alter table public.agent_connections alter column expires_at set default now()+interval '1 year';
notify pgrst,'reload schema';
commit;
