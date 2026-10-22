# Lean2LLM Python library

Lean2LLM joins the original Lean–LLM proof loop with a searchable local proof
vault and self-contained proof bundles. The distribution is named `lean2llm`;
the Python import is `lean_llm`. Python 3.11 or later is required. The runtime
library uses the standard library and has no Python runtime dependencies.

## Install from this repository

```sh
python3 -m pip install .
lean2llm --help
```

Storage, search, import, and export work without a Lean installation. Native
tactic checking uses the original bridge's macOS `sandbox-exec` process policy
and Lean `leanprover/lean4:v4.33.1`. Install that exact toolchain using elan, or
set `LEAN_LLM_TOOLCHAIN` to the real distribution directory containing
`bin/lean` and `bin/lake`. An explicit mismatched toolchain is rejected.
Packaged Lean source and Lake configuration are copied into a writable,
content-addressed cache under `~/.cache/lean2llm/native/`. Set `LEAN_LLM_HOME`
to choose another cache root. Installation directories stay read-only.

## Store and find proofs

```python
from lean_llm import ProofStore

request = {
    "name": "identity",
    "context": "",
    "statement": "∀ n : Nat, n = n",
}

with ProofStore("proofs.sqlite3") as proofs:
    candidate = proofs.add(
        request, "intro n\nrfl",
        title="Natural-number identity", tags=["nat", "equality"],
    )
    print(candidate["id"])
    print(proofs.search("equality"))
    outcome = proofs.check(candidate["id"])
    print(outcome["check"]["accepted"])
    checked = outcome["record"]
    proofs.export_bundle(checked["id"], "identity.proof.zip")
```

`add` stores a candidate as **unverified**. `check` runs native Lean twice: once
through the fixed-statement bridge, then against the exact exported source.
Both checks must complete successfully and emit the theorem-specific axiom
audit marker. The audit rejects placeholders and transitive custom axioms,
allowing `propext`, `Classical.choice`, and `Quot.sound`. Proof proposals remain
subject to the original source/token restrictions and process resource limits.

A check resolves the current compiler fingerprint. If the original candidate
used `unresolved` or another compiler identity, the checked content receives a
new immutable ID; read `outcome["record"]["id"]`.

`search` uses SQLite FTS5 over title, proposition, and tags. Search results are
discovery candidates. `lookup(request, toolchain)` requires the exact context,
exact statement, toolchain pin, and compiler/checker fingerprint. Display names
do not affect this lookup. `reuse(request)` always rechecks a matching candidate
with the current native checker before returning it. The package does not infer
semantic equivalence from similar text or reuse a theorem across different
contexts without a supplied and checked proof.

## Propose with the original bounded loop

```python
from lean_llm import ProofStore, solve

def proposer(payload):
    # payload includes the fixed request, actual goal, prior proof, diagnostics,
    # attempt count, and remaining search time.
    return {"proof": "intro n\nrfl"}

with ProofStore("proofs.sqlite3") as proofs:
    result = solve(request, proposer=proposer, store=proofs, max_attempts=2)
    print(result["status"], result.get("proof_id"))
```

The proposer is explicit. A deterministic function makes no model calls.
`CodexProposer` provides the original text-only adapter to an existing
ChatGPT-authenticated Codex CLI; use it deliberately. Source restrictions,
native goal feedback, proof repair, resource failure handling, and native
cache rechecks follow the public bridge. Setup/build/version discovery have
their own budgets; a custom proposer is responsible for respecting its supplied
deadline. Native checking is currently supported by the macOS sandbox profile.

## Command line

`--db` selects the vault and precedes the subcommand. Its default is
`~/.local/share/lean2llm/proofs.sqlite3`; `LEAN_LLM_STORE` overrides it.

```sh
lean2llm --db proofs.sqlite3 store request.json --proof proof.txt --tag nat
lean2llm --db proofs.sqlite3 search "identity"
lean2llm --db proofs.sqlite3 show FULL_SHA256_ID
lean2llm --db proofs.sqlite3 check FULL_SHA256_ID
lean2llm --db proofs.sqlite3 export FULL_SHA256_ID identity.proof.zip
lean2llm --db another.sqlite3 import identity.proof.zip
lean2llm --db proofs.sqlite3 solve request.json --proof proof.txt
lean2llm --db proofs.sqlite3 solve request.json --cache-only
# Explicit model use through the existing Codex sign-in:
lean2llm --db proofs.sqlite3 solve request.json --codex --attempts 2
```

Native checking and solving return exit code 0 on acceptance and 2 on failure
or an unresolved goal. Storage and retrieval commands emit JSON. No model is
called by `check`, `search`, `import`, `export`, or `--cache-only`.

## Exchange records and portable bundles

The record schema is `lean2llm.proof/v1`:

```json
{
  "schema": "lean2llm.proof/v1",
  "id": "SHA256_OF_CANONICAL_CONTENT",
  "content": {
    "title": "Natural identity",
    "tags": ["nat"],
    "request": {"name": "identity", "context": "", "statement": "∀ n : Nat, n = n"},
    "proof": "intro n\nrfl",
    "source": "GENERATED_EXACT_LEAN_SOURCE",
    "backend": "lean-tactic",
    "toolchain": {"pin": "leanprover/lean4:v4.33.1", "fingerprint": "unresolved"},
    "metadata": {}
  },
  "verification": {
    "status": "unverified",
    "scope": "none",
    "checked_at": null,
    "diagnostics": "Awaiting a local native check",
    "checker_fingerprint": null
  }
}
```

The content ID hashes UTF-8 JSON with sorted keys, compact separators, preserved
Unicode, and a shared lossless numeric policy: JSON numbers are integers in
`[-9007199254740991, 9007199254740991]`. Encode fractional measurements and larger
integers as strings. Python floats, including `1.0`, are rejected before hashing
so Python and browser serialization cannot assign different IDs to the same
record. Strings must contain valid Unicode. Verification metadata is separate local evidence.
`put(record)` and bundle import discard incoming verification claims. A vault
that already checked identical content retains its existing local evidence;
every reuse still runs native Lean. A failed local recheck clears prior
verification status for that record.

A ZIP bundle includes `manifest.json`, `record.json`, `source/Proof.lean`, the
pinned `checker/Llm.lean` and Lake files, `_driver.py`, and `verify.py`.
The manifest lists each file's SHA256 and byte length. Import validates exact
file membership, duplicate names, symlinks, paths, expanded size, content ID,
and agreement between source, proposition, and proof. It never extracts or
executes imported files. The current limits are 32 entries and 16 MB expanded.

For local rechecking of an imported bundle, import it then run `lean2llm check`
using the installed checker. For a self-contained distribution, unpack the
exported bundle and run `python3 verify.py` with its pinned native Lean
toolchain. That script uses the bundled checker and requires the same macOS
process sandbox. Hashes establish integrity relative to the manifest and
content ID; author authentication requires a separately trusted ID or signature.

## Standalone exported-term certificates

The Navier–Stokes repository uses a different verification profile: exported
challenge and solution terms, pinned source references, and its Lean
4.34.0-rc2 certificate checker. Its toolchain and verification scope stay
separate from the tactic bridge's Lean 4.33.1 profile.

```python
from lean_llm import inspect_certificate_bundle, verify_certificate_bundle

integrity = inspect_certificate_bundle("/path/to/navier-stokes-standalone")
report = verify_certificate_bundle(
    "/path/to/navier-stokes-standalone",
    verifier="/path/to/navier-stokes-standalone/verify.py",
    expected_sha256="HASH_OF_THE_REVIEWED_LOCAL_VERIFIER",
)
```

Inspection checks manifest references and certificate hashes. It reports
`integrity-checked`. Execution requires an explicitly selected local verifier
inside that bundle directory plus its expected SHA256. It reports
`verifier-succeeded` or `verifier-failed`, along with output, source metadata,
toolchain pin, and file hashes. This adapter never executes an imported command
or treats a successful exit as the package's own fixed-statement Lean audit.
The selected standalone verifier defines the mathematical checks it performs.

## Development checks

```sh
PYTHONPATH=src python3 -m unittest discover -s tests -v
LEAN_LLM_NATIVE_TESTS=1 PYTHONPATH=src python3 -m unittest discover -s tests -v
python3 -m build
```

Native tests use deterministic proposals and make no model calls. They cover
actual kernel acceptance and rejection, transitive axiom rejection, mandatory
cache rechecking, and replay of an unpacked standalone export. Storage tests
cover FTS lookup, context/compiler misses, tampering, path traversal, symlinks,
duplicate entries, expanded-size bounds, and imported-status handling.
