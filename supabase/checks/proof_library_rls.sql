-- Lean2LLM private proof-table RLS smoke test.
-- RUN ONLY in the NEW dedicated Lean2LLM project, after its migration.
-- Recorded dedicated-project run: examples/public_platform/dedicated-cloud-result.json.
-- It creates no emails, passwords, identities, OTPs, or outbound Auth requests.
-- The auth.users fixtures contain only two fresh, explicit IDs.
-- All fixture queries are restricted to those IDs and their explicit content IDs.
--
-- Inspect the returned pass boolean and NOTICE/WARNING. A generic SQL-editor
-- "query executed" message is not a passing test. Caught failures deliberately
-- return pass=false so that the trailing ROLLBACK can always run.
--
-- Both successful and unsuccessful tests roll back their fixture subtransaction
-- BEFORE emitting the result. The outer ROLLBACK also removes the temporary
-- result table. Never replace ROLLBACK with COMMIT or execute a partial block.

begin;

create temporary table lean2llm_rls_smoke_result (
  pass boolean not null,
  detail text not null
) on commit drop;

do $smoke$
declare
  user_a constant uuid := 'a48ee60c-abb2-4471-81ba-bc3355630e12';
  user_b constant uuid := 'd0ba37fe-1cda-41c7-a8aa-1df78d180cad';
  content_a constant text := repeat('a', 64);
  content_b constant text := repeat('b', 64);
  content_c constant text := repeat('c', 64);
  content_d constant text := repeat('d', 64);
  affected bigint;
  visible bigint;
  denied boolean;
  reached_end boolean := false;
  passed boolean := false;
  failure_state text;
  failure_message text;
  failure_detail text;
  original_role text := current_user;
begin
  -- An EXCEPTION block is a subtransaction. The explicit success sentinel also
  -- aborts it, ensuring fixtures are removed even before the outer ROLLBACK.
  begin
    if exists (select 1 from auth.users where id in (user_a, user_b)) then
      raise exception 'A fixture UUID already exists. Stop; do not reuse or delete that user.';
    end if;
    if exists (
      select 1 from public.lean2llm_proofs
      where user_id in (user_a, user_b)
    ) then
      raise exception 'A fixture owner already has rows. Stop without changing them.';
    end if;

    -- No email/password/provider information is inserted. These rows are
    -- temporary FK fixtures, not sign-in-capable test accounts.
    insert into auth.users (id) values (user_a), (user_b);

    -- Minimal JSON valid for the TABLE constraints, intentionally not a claimed
    -- verified formal proof. These records never leave the rolled-back fixture.
    insert into public.lean2llm_proofs (user_id, content_id, record)
    values
      (user_a, content_a, jsonb_build_object(
        'schema', 'lean2llm.proof/v1', 'id', content_a,
        'content', jsonb_build_object('title', 'Temporary RLS fixture A'))),
      (user_b, content_b, jsonb_build_object(
        'schema', 'lean2llm.proof/v1', 'id', content_b,
        'content', jsonb_build_object('title', 'Temporary RLS fixture B')));

    execute 'set local role authenticated';
    perform set_config('request.jwt.claim.sub', user_a::text, true);
    perform set_config('request.jwt.claims',
      jsonb_build_object('sub', user_a::text, 'role', 'authenticated')::text, true);

    if current_user <> 'authenticated' then
      raise exception 'RLS test is not running as authenticated; actual role: %', current_user;
    end if;
    if auth.uid() is distinct from user_a then
      raise exception 'The JWT subject did not become fixture user A.';
    end if;
    if not row_security_active('public.lean2llm_proofs'::regclass) then
      raise exception 'Row-level security is not active for this test role.';
    end if;

    select count(*) into visible from public.lean2llm_proofs
      where user_id = user_a and content_id = content_a;
    if visible <> 1 then raise exception 'Owner A cannot read its own fixture row.'; end if;

    select count(*) into visible from public.lean2llm_proofs
      where user_id = user_b and content_id = content_b;
    if visible <> 0 then raise exception 'Owner A can read owner B''s fixture row.'; end if;

    update public.lean2llm_proofs set updated_at = now()
      where user_id = user_a and content_id = content_a;
    get diagnostics affected = row_count;
    if affected <> 1 then raise exception 'Owner A cannot update its own fixture row.'; end if;

    update public.lean2llm_proofs set updated_at = now()
      where user_id = user_b and content_id = content_b;
    get diagnostics affected = row_count;
    if affected <> 0 then raise exception 'Owner A updated owner B''s fixture row.'; end if;

    delete from public.lean2llm_proofs
      where user_id = user_b and content_id = content_b;
    get diagnostics affected = row_count;
    if affected <> 0 then raise exception 'Owner A deleted owner B''s fixture row.'; end if;

    -- Prove ordinary owner INSERT/DELETE grants work before treating a
    -- cross-owner insufficient_privilege error as an expected RLS rejection.
    insert into public.lean2llm_proofs (user_id, content_id, record)
      values (user_a, content_d, jsonb_build_object(
        'schema', 'lean2llm.proof/v1', 'id', content_d,
        'content', jsonb_build_object('title', 'Temporary owner CRUD fixture')));
    delete from public.lean2llm_proofs
      where user_id = user_a and content_id = content_d;
    get diagnostics affected = row_count;
    if affected <> 1 then raise exception 'Owner A cannot delete its own inserted fixture.'; end if;

    denied := false;
    begin
      insert into public.lean2llm_proofs (user_id, content_id, record)
        values (user_b, content_c, jsonb_build_object(
          'schema', 'lean2llm.proof/v1', 'id', content_c,
          'content', jsonb_build_object('title', 'Must be denied')));
    exception when insufficient_privilege then
      denied := true;
    end;
    if not denied then raise exception 'Owner A inserted a record owned by B.'; end if;

    denied := false;
    begin
      update public.lean2llm_proofs set user_id = user_b
        where user_id = user_a and content_id = content_a;
    exception when insufficient_privilege then
      denied := true;
    end;
    if not denied then raise exception 'Owner A transferred its fixture ownership to B.'; end if;

    -- Rebind the subject while retaining the actual authenticated SQL role.
    perform set_config('request.jwt.claim.sub', user_b::text, true);
    perform set_config('request.jwt.claims',
      jsonb_build_object('sub', user_b::text, 'role', 'authenticated')::text, true);
    if current_user <> 'authenticated' or auth.uid() is distinct from user_b then
      raise exception 'The second fixture role/subject is incorrect.';
    end if;
    select count(*) into visible from public.lean2llm_proofs
      where user_id = user_b and content_id = content_b;
    if visible <> 1 then raise exception 'Owner B cannot read its own preserved fixture.'; end if;
    select count(*) into visible from public.lean2llm_proofs
      where user_id = user_a and content_id = content_a;
    if visible <> 0 then raise exception 'Owner B can read owner A''s fixture.'; end if;

    execute 'reset role';
    reached_end := true;
    raise sqlstate 'L2R01' using message = 'LEAN2LLM_RLS_SMOKE_SUCCESS_SENTINEL';
  exception
    when sqlstate 'L2R01' then
      -- The fixture subtransaction has already been rolled back here.
      passed := reached_end;
      if not reached_end then
        failure_detail := 'Unexpected success-sentinel exception before all checks completed.';
      end if;
    when others then
      -- This handler also runs only after all fixture writes and SET LOCAL
      -- changes in the subtransaction have been rolled back.
      get stacked diagnostics failure_state = returned_sqlstate,
        failure_message = message_text;
      failure_detail := failure_state || ': ' || failure_message;
  end;

  if current_user <> original_role then
    raise exception 'The fixture role was not restored after its subtransaction.';
  end if;

  if passed then
    insert into pg_temp.lean2llm_rls_smoke_result values
      (true, 'PASS: authenticated owner CRUD, cross-owner read/update/delete isolation, and ownership INSERT/UPDATE rejection. Fixture subtransaction rolled back.');
    raise notice 'LEAN2LLM RLS SMOKE: PASS; fixture subtransaction rolled back.';
  else
    insert into pg_temp.lean2llm_rls_smoke_result values
      (false, 'FAIL: ' || coalesce(failure_detail, 'Unspecified failure') || '. Fixture subtransaction rolled back.');
    raise warning 'LEAN2LLM RLS SMOKE: FAIL: %; fixture subtransaction rolled back.', failure_detail;
  end if;
end;
$smoke$;

select pass, detail,
  (select count(*) from auth.users where id in (
    'a48ee60c-abb2-4471-81ba-bc3355630e12'::uuid,
    'd0ba37fe-1cda-41c7-a8aa-1df78d180cad'::uuid
  )) as fixture_auth_rows_remaining,
  (select count(*) from public.lean2llm_proofs where user_id in (
    'a48ee60c-abb2-4471-81ba-bc3355630e12'::uuid,
    'd0ba37fe-1cda-41c7-a8aa-1df78d180cad'::uuid
  )) as fixture_proof_rows_remaining
from pg_temp.lean2llm_rls_smoke_result;

rollback;
