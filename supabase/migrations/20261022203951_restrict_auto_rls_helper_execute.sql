-- Keep the platform automatic-RLS helper and its event trigger, while removing
-- direct execution grants from application roles. Projects without the helper
-- require no action.
begin;

do $migration$
declare
  helper_oid oid := pg_catalog.to_regprocedure('public.rls_auto_enable()');
begin
  if helper_oid is null then
    return;
  end if;

  if not exists (
    select 1 from pg_catalog.pg_proc
    where oid = helper_oid
      and pronargs = 0
      and prokind = 'f'
      and prorettype = 'pg_catalog.event_trigger'::pg_catalog.regtype
      and prosecdef
  ) then
    raise exception 'Unexpected identity for public.rls_auto_enable(); no grants changed';
  end if;

  execute 'revoke execute on function public.rls_auto_enable() from public, anon, authenticated';
end;
$migration$;

commit;
