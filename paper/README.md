# Lean2LLM paper

Editable source: `main.tex`. The bibliography is embedded, so the manuscript is a standalone LaTeX file suitable for an ordinary PDFLaTeX or Tectonic build.

```sh
pdflatex -interaction=nonstopmode -halt-on-error main.tex
pdflatex -interaction=nonstopmode -halt-on-error main.tex
python3 package.py
```

The author-facing title is **Lean2LLM: Rechecked Proof Search and Portable Proof Storage for Lean**. The author is Octavia Sulea; the contact address is octavia@octav.ai. The AI assistance statement documents drafting, implementation, and verification assistance.

This manuscript describes the public bridge and its storage extension. It does not draw on unpublished mathematical examples or private drafts. It attributes the underlying formalization in the certificate example to the upstream project.

The browser implementation uses a fresh isolated WebAssembly worker for each check. HTTP caching can reuse downloaded runtime assets. The vendored runtime includes local fixes for compiler-error and abort propagation and allows one fresh-worker retry after a runtime fault. Its provenance remains separate from the native Lean 4.33.1 bridge. The frontend suite passes 19 tests; a recorded manual Chrome sequence accepted the bundled induction theorem, rejected a false target with a mismatched proof, and accepted the restored theorem without reloading the page.

## Evidence and release checklist

The inherited results are pinned to public revisions and are reported as historical records:

- `lean-llm` at `a409e42c806426f6f26ad76787fcebf902898d78`: 29 tests, 186.933 seconds in `examples/test-results.txt`; README reports an approximately 14-second induction demonstration with one live proposal and three Lean checks.
- `navier-stokes-proof` at `3b01518b6e33ab99b36a582219aa5c605be5268a`: published log reports a 94,719-declaration replay; its standalone README records 580.518 seconds on 12 September 2026. The tactic bridge and certificate checker use separate toolchain versions.

The new library has a separate recorded run in `examples/public_platform/installed-wheel-tests.txt` and `installed-wheel-result.json`: **30 tests passed in 35.274 seconds**, comprising eight real Lean integration tests and 22 storage/integrity tests, with zero model calls. This run used the installed wheel in a clean virtual environment, isolated Python and a working directory outside the repository. The JSON records the command, Python version and Lean pin. Companion interoperability evidence shows a browser record imported into Python and freshly checked by native Lean; the standalone Navier–Stokes report covers nine manifest/referenced-file integrity entries and records that the full verifier was not run.

Before public submission:

1. Confirm the manuscript matches the final library and website behavior.
2. Review the new library test log against the release revision, and rerun it if the checking or storage implementation changes.
3. Confirm authorship, contact details, source licensing, and submission categories with the author.
4. Read the generated PDF and the complete source archive.
5. Let the author approve the final arXiv submission and its public metadata.

`arxiv/` contains an abstract, submission metadata draft and `source.tar.gz`, containing only the self-contained LaTeX source. `package.py` recreates the archive and `SHA256SUMS` after compilation. No arXiv submission has been made by creating these files. The files intentionally omit an invented institutional affiliation, ORCID, DOI, acceptance, and arXiv identifier. The author chose the personal contact address above.

## Bibliography sources checked

- De Moura and Ullrich, *The Lean 4 Theorem Prover and Programming Language*, CADE 28 (2021): <https://lean-lang.org/papers/lean4.pdf>.
- Yang et al., *LeanDojo: Theorem Proving with Retrieval-Augmented Language Models*, NeurIPS 2023: <https://arxiv.org/abs/2306.15626>.
- Song, Yang and Anandkumar, *Lean Copilot: Large Language Models as Copilots for Theorem Proving in Lean*, v3 (2025): <https://arxiv.org/abs/2404.12534v3>.

Algo2Lean supplies a visual reference for the website. The paper makes no technical performance comparison with Algo2Lean because no controlled comparison was run.
