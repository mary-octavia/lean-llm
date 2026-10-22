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

The production database is the existing Codestars `csc-website` Supabase project (`dloebutxzgjzcavajizf`). The migration in `supabase/migrations/20261022185055_lean2llm_proof_library.sql` creates the dedicated `lean2llm_proofs` table. It was applied through the authenticated SQL editor during initial setup; its application is not registered in the Supabase CLI migration history. Reconcile migration history before using `supabase db push` against that database.

Configure these browser-safe Vercel build variables:

- `VITE_SUPABASE_URL`
- `VITE_SUPABASE_PUBLISHABLE_KEY`

The table requires an authenticated user and enforces ownership for every operation through row-level security. Anonymous access is revoked. Existing unrelated tables are unchanged. Cloud records are imported as unverified candidates and must be checked again locally.

Allow the production origins in Supabase Auth's redirect URL list. The intended sender is `octavia@octav.ai` through Neo Mail (`smtp0001.neo.space`, port 465 with TLS, username `octavia@octav.ai`). The owner supplies the password privately in Supabase; use a dedicated Neo application password with 2FA enabled. The release checks cover configuration and database policies. Email delivery requires completing that credential step and testing sign-in.

The local library works without a Supabase account. No model API credentials are included in the website. The Python proposal loop uses the caller's explicitly configured proposer.

## Release checks

Run the native bridge and installed Python package suites, the web tests, and the production build. In a real browser, confirm a valid proof succeeds, an invalid proof fails, a saved proof can be searched and reopened, and imported verification is reset. After deployment, check the isolation headers, compiler assets, paper, wheel, and domain redirects on the public origin.
