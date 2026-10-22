# Browser Lean runtime provenance

The web application vendors the MIT-licensed `packages/lean-wasm` package from
[live-codes/browser-lean](https://github.com/live-codes/browser-lean), commit
`a8aed095534e67061e2626b94e8e69193099091d`. The package advertises version 0.1.0,
but was unavailable from the npm registry during this implementation, so the
pinned package source is used instead of an unresolvable package reference.
A small local patch to `src/compiler.js` accepts an AbortSignal and disposes
a worker during startup when the user cancels. Another local patch preserves
worker failure details as `runtimeError`. The workbench retries a runtime fault
once in a fresh worker and disposes the worker after every check, including
successful ones. This avoids state corruption observed when the pinned WASM
compiler is reused after a run. Downloaded assets remain browser-cacheable. These changes
do not alter Lean elaboration or kernel checking.
`vendor/lean-wasm/LICENSE` and `THIRD-PARTY-NOTICES.md` preserve its notices.

The browser compiler is separate from the original native bridge's
`leanprover/lean4:v4.33.1` toolchain. Its core layer identifies Lean commit
`62b6a2291302d4bbeace37642a066b7510d0145c`, built by the cauli Lean WebAssembly fork.
The compiler and core libraries use Apache-2.0. The asset-fetcher pins the upstream
artifact version `62b6a2291302d4bbeace37642a066b7510d0145c-dlsym1-compact1`.

`runtime-assets.sha256.json` lists all deployed core artifact hashes. CI sets
`LEAN2LLM_ASSET_MIRROR=https://lean2llm.com/lean` to download these exact nine
files from the first-party deployment. Every response is SHA256-checked before
an atomic rename installs it; corrupt downloads and corrupt cached files fail
the build. Without this setting, the pinned upstream fetcher bootstraps the
assets, with the same first-party mirror as a fallback when upstream access
fails (for example, an HTTP 403 from a CI network). `npm run
assets:lean` fetches absent artifacts and verifies every hash. `npm run build`
also runs this step, so a clean Vercel build receives the same pinned assets.
Generated artifacts live under `public/lean` and are excluded from Git. The core
payload is approximately 47.6 MiB compressed and excludes optional Mathlib,
Batteries, Std and Lean metaprogramming layers.

The site uses the real runtime in a fresh isolated worker for each check. The browser check assembles
a core Lean theorem from the requested context, proposition and tactics, then
requires a matching `#print axioms` report. A verification record names this
browser checker and its version; it is a local observation, not a signed server
attestation. Imported records are unverified until checked again.

The Vite development server explicitly returns 404 for missing runtime assets;
Vercel's SPA rewrite excludes the runtime directory. This prevents missing files
from being silently replaced by the application's HTML entry point.
