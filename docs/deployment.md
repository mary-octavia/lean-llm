# Deploying Lean2LLM

The web application lives in `web/`. The production Vercel project is `lean2llm` in the `codestars-clothing` team, with its project root set to `web` and Node.js 22. Its primary domain is `lean2llm.com`; `lean4llm.com`, `langlean.si`, and their `www` variants redirect to it.

```sh
cd web
npm ci
npm test
npm run test:assets
npm run build
cd ..
npx vercel deploy --prod --yes --scope codestars-clothing --project lean2llm --verify
```

The build downloads and validates the pinned browser compiler assets using `runtime-assets.sha256.json`. CI uses `LEAN2LLM_ASSET_MIRROR=https://lean2llm.com/lean` to avoid upstream download restrictions; each file still requires the expected SHA-256 digest. `vercel.json` supplies the isolation headers needed by the WebAssembly worker, static-file routes, and domain redirects. See `RUNTIME-PROVENANCE.md` for compiler revisions and licenses. Production deployment currently uses the CLI; the Vercel account's GitHub connection has not been configured for this repository.

Before a release, rebuild the Python distributions, copy them and the standalone example bundle from `dist/` into `web/public/downloads/`, and copy the current paper PDF and source into `web/public/paper/main.pdf` and `main.tex`. Keep the published artifact manifest synchronized with the distributions.

## Private proof synchronization

Lean2LLM has a dedicated Supabase project in the Codestars organization: `ovttidsabezpbkswnlhf`, at `https://ovttidsabezpbkswnlhf.supabase.co`. It was created on the Free plan in Oregon (`us-west-2`). Its database and Auth configuration are separate from the clothing site's `csc-website` project.

The migration in `supabase/migrations/20261022185055_lean2llm_proof_library.sql` was applied once to the dedicated project through the dashboard SQL editor on October 22, 2026. It creates the `lean2llm_proofs` table, ownership policies, constraints and indexes. Both the earlier shared-project installation and this dedicated-project installation used the SQL editor, which does not register the application in Supabase CLI migration history. Reconcile migration history before using `supabase db push`, and do not rerun existing policy/index creation blindly.

Configure these browser-safe Vercel build variables for Production and each Preview environment that should use the dedicated project:

- `VITE_SUPABASE_URL`
- `VITE_SUPABASE_PUBLISHABLE_KEY`

Production was rebuilt with `https://ovttidsabezpbkswnlhf.supabase.co` and the dedicated project's matching publishable key. The October 22 cutover deployment, `dpl_FEoyVK4dXLmeNkVx1bKoXBq8teGF`, was ready, and `https://lean2llm.com` returned HTTP 200. Its compiled JavaScript contained the new project reference and matching public key; the former shared-project reference was absent. The deployment URL, asset SHA-256 and validation details are recorded in `examples/public_platform/dedicated-cloud-result.json`. For future configuration changes, replace both values together, remove any stale legacy `VITE_SUPABASE_ANON_KEY` configuration, and rebuild/redeploy: Vite embeds these values in the generated JavaScript. Validate Preview environments separately. Administrative keys and SMTP credentials belong in service settings.

The migration `supabase/migrations/20261022203951_restrict_auto_rls_helper_execute.sql` was also applied through the SQL editor, without a CLI migration-history entry. It narrows execution privileges for the platform automatic-RLS helper `public.rls_auto_enable()`: projects without the helper are skipped, while an existing helper must have the expected zero-argument `SECURITY DEFINER` event-trigger signature. Execution was revoked from `PUBLIC`, `anon` and `authenticated`, preserving the function and event trigger. The rollback-only manual check in `supabase/checks/automatic_rls.sql` confirmed anonymous and authenticated execution privileges were revoked, newly created public tables still received automatic RLS, and the fixture table was removed. The proof-library RLS smoke test passed again with zero remaining fixtures. A fresh Security Advisor run reported zero errors, zero warnings and zero informational findings. Script hashes and results are recorded in `examples/public_platform/dedicated-cloud-result.json`.

The table requires an authenticated user and enforces ownership for every operation through row-level security. Anonymous access is revoked. Cloud records are imported as unverified candidates and must be checked again locally.

For a manual policy smoke test, run the complete `supabase/checks/proof_library_rls.sql` file in the dedicated project's SQL editor. This plain SQL/PLpgSQL check uses two temporary Auth UUIDs, switches to the actual `authenticated` SQL role, and checks owner CRUD, cross-owner isolation and ownership-transfer rejection. Its fixture subtransaction rolls back before returning the result, and the complete script ends with an outer `ROLLBACK`. Inspect the returned `pass` value and both remaining-fixture counts; a generic successful-execution label alone does not establish a pass. The dedicated-project run returned `pass=true`, zero remaining Auth fixtures and zero remaining proof fixtures. The recorded result is `examples/public_platform/dedicated-cloud-result.json`. Live API smoke checks also passed: `/auth/v1/health` returned HTTP 200 for GoTrue, and an anonymous proof-table request returned the expected HTTP 401 with PostgreSQL code `42501` and `permission denied for table lean2llm_proofs`. Authenticated end-to-end synchronization and email-delivery checks remain pending.

The dedicated project's Auth site URL was saved as `https://lean2llm.com`, together with four named application redirect origins. Keep its email templates and SMTP configuration independent. The intended sender is `octavia@octav.ai` through Neo Mail (`smtp0001.neo.space`, port 465 with TLS, username `octavia@octav.ai`). The dedicated SMTP form has its public fields prepared, with an empty password field and unsaved settings. Private owner credential entry and end-to-end email delivery remain pending. Choose the SMTP credential according to the mailbox's existing Neo security setting: use the mailbox password while 2FA is off, or a dedicated application password when 2FA is enabled. Then test the sign-in email and return to the proof library.

The clothing project's tables, proof table and Auth users are preserved. A count-only query returned zero proof rows and zero proof owners in its `lean2llm_proofs` table at inventory time, so no existing cloud proof records required migration then. No cloud rows were migrated. The four Lean2LLM redirect URLs were removed from the clothing project, leaving its redirect list empty, while its original `http://localhost:3000` site URL was preserved. Its custom SMTP toggle was already off, matching the original configuration, so its SMTP configuration and credentials were left untouched. A production-browser reload preserved one existing local proof record and displayed the configured private-cloud sign-in UI. Existing browser-local proofs remain available at the same origin. Signing into the dedicated project establishes a new Auth identity; records can be exported and resynchronized under that identity without changing their proof content IDs. Do not copy old cloud owner IDs directly into the new project's `auth.users` foreign key.

The local library works without a Supabase account. No model API credentials are included in the website. The Python proposal loop uses the caller's explicitly configured proposer.

## Release checks

Run the native bridge and installed Python package suites, the web tests, and the production build. In a real browser, confirm a valid proof succeeds, an invalid proof fails, a saved proof can be searched and reopened, and imported verification is reset. After deployment, check the isolation headers, compiler assets, paper, wheel, and domain redirects on the public origin.
