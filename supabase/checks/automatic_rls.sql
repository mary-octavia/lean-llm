-- Manual check for the dedicated project's automatic-RLS helper.
-- Run the complete script as postgres after the helper-grant migration.
-- The uniquely named fixture table exists only inside this rolled-back
-- transaction. An existing table of this name causes CREATE TABLE to fail.
begin;

create table public.lean2llm_rls_trigger_smoke_20261022 (id integer);

select
  not has_function_privilege('anon', 'public.rls_auto_enable()', 'EXECUTE')
    as anonymous_execute_revoked,
  not has_function_privilege('authenticated', 'public.rls_auto_enable()', 'EXECUTE')
    as authenticated_execute_revoked,
  (select relrowsecurity from pg_class
    where oid = 'public.lean2llm_rls_trigger_smoke_20261022'::regclass)
    as automatic_rls_enabled;

rollback;

-- In a separate query after the rollback, this must return true:
-- select to_regclass('public.lean2llm_rls_trigger_smoke_20261022') is null
--   as fixture_removed;
