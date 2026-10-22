# Lean2LLM

**Propose a proof. Check it with Lean. Save it and find it again.**

Lean2LLM develops the original Lean–LLM bridge into a browser workbench, an installable Python library, and a portable proof library. A fixed proposition passes through bounded proposal and diagnostic feedback; Lean checks the accepted proof and its axioms. Retrieved candidates are checked again before reuse.

Website: [lean2llm.com](https://lean2llm.com). Source: [mary-octavia/lean-llm](https://github.com/mary-octavia/lean-llm).

## Use the Python library

Python 3.11 or later; the storage library uses the standard library. Install from this checkout or from the published platform branch:

```sh
python3 -m pip install .
# Or:
python3 -m pip install 'git+https://github.com/mary-octavia/lean-llm.git@codex/lean2llm-platform'
lean2llm --help
```

```python
from lean_llm import ProofStore

request = {"name": "identity", "context": "", "statement": "∀ n : Nat, n = n"}
with ProofStore("proofs.sqlite3") as proofs:
    candidate = proofs.add(request, "intro n\nrfl",
                           title="Natural identity", tags=["nat", "equality"])
    print(proofs.search("equality"))
    checked = proofs.check(candidate["id"])
    print(checked["check"]["accepted"])
    proofs.export_bundle(checked["record"]["id"], "identity.proof.zip")
```

Storage and search run without Lean. Native checking requires macOS and the pinned Lean 4.33.1 toolchain because it retains the original sandbox policy. Install it with `elan toolchain install leanprover/lean4:v4.33.1`, or set `LEAN_LLM_TOOLCHAIN` to that distribution.

The CLI provides `store`, `search`, `show`, `check`, `solve`, `export`, and `import`. [Library documentation](docs/library.md) covers complete examples, the record schema, and certificate checking.

## Proof storage and retrieval

Every record includes its statement, context, proof, source, toolchain fingerprint, title, tags, and verification evidence. Its immutable content has a SHA256 identity. SQLite full-text search finds candidates by title, proposition, and tags; exact lookup includes the context and compiler identity. A candidate imported from another library starts unverified. A cache hit is checked again before reuse.

Portable bundles include source, hashes, pinned checker files, and reproduction instructions. The certificate adapter supports the separate verification profile used by [navier-stokes-proof](https://github.com/mary-octavia/navier-stokes-proof), with explicit verifier selection and provenance.

## Browser workbench

The website in `web/` provides an editor, real Lean checking through WebAssembly, a searchable local proof library, JSON exchange, and private Supabase synchronization. Browser checks record their own compiler identity. Opening a saved candidate restores the work; checking it produces fresh evidence.

```sh
cd web
npm ci
npm run dev
```

The browser compiler and its dependencies require an initial download. Runtime assets are pinned and reproducibly prepared by the web build. Lean checking runs in a worker in the visitor’s browser. The native proposal loop remains available through the Python CLI and an explicitly selected proposer.

## Original proof loop

The original entry points remain available:

```sh
python3 bridge.py examples/involution.json --max-attempts 3 --timeout 120
python3 bridge.py examples/involution.json --cache-only
```

The native `by llm` tactic receives a proposal from the external driver. The fixed statement and context remain unchanged across attempts. Both the tactic path and exported theorem pass Lean and an axiom audit allowing `propext`, `Classical.choice`, and `Quot.sound`.

Lean checks the submitted proofs, while automated tests cover the orchestration, caching and error handling done by the Python driver. This is a research prototype meant to run locally.

The [original bridge documentation](docs/original-bridge.md) preserves the initial release and its recorded induction example.

## Paper and reproducibility

The [paper](paper/main.pdf), [editable LaTeX](paper/main.tex), [evidence record](paper/evidence.json), and [statement-alignment template](paper/statement-alignment-template.md) describe the architecture, checking scopes, inherited results, and new library tests. The [arXiv preparation folder](paper/arxiv/) contains submission metadata and source preparation instructions.

The recorded initial demonstration used one model proposal and three Lean checks, about 14 seconds. The Navier–Stokes certificate log records 94,719 declarations checked against its supplied formal challenge. The paper distinguishes these inherited observations from the current implementation and its tests.

## Development

```sh
python3 -m unittest test_bridge -v
PYTHONPATH=src python3 -m unittest discover -s tests -v
LEAN_LLM_NATIVE_TESTS=1 PYTHONPATH=src python3 -m unittest discover -s tests -v
python3 -m build
cd web
npm test
npm run test:assets
npm run build
```

Created through collaboration between Octavia Sulea and AI coding assistants. The original demonstration proof was model-proposed and Lean-checked. Upstream compiler and dependency licenses are retained. No repository-wide license has been selected for newly authored material.
