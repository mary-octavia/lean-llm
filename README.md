# Lean–LLM

**Let a language model propose the proof. Let Lean check it.**

A small local bridge between Codex and Lean 4. Write a proposition; the model receives Lean's actual goal, proposes a tactic sequence, and gets compiler errors back when an attempt fails. Accepted proofs are exported as ordinary Lean source and cached. Every cache hit is checked again.

```text
fixed proposition → Lean goal → LLM proposal → Lean + axiom audit
                                     ↑               │
                                     └── errors ─────┘
                                                     │ accepted
                                                     ▼
                                              reusable proof
```

The native tactic is `by llm`. It receives a proposal from the Python driver; Lean itself makes no network request. Proposals can use induction, local lemmas, rewriting, and standard Lean/Std tactics.

## Quick start

Requirements: **macOS**, **Python 3.11+**, Lean **4.33.1**, and a compatible Codex CLI signed in with ChatGPT for model-generated proposals. Offline checks and tests need no Codex account or model calls.

Install Lean using the official [Lean setup instructions](https://lean-lang.org/install/) and [elan](https://github.com/leanprover/elan). Install and sign in to Codex using the official [Codex CLI instructions](https://developers.openai.com/codex/cli/).

```sh
git clone https://github.com/mary-octavia/lean-llm.git
cd lean-llm
elan toolchain install leanprover/lean4:v4.33.1
lake build Llm
python3 bridge.py examples/involution.json --max-attempts 3 --timeout 120
```

The JSON result reports `proved` or `unknown`, diagnostics, the accepted proof, and its exported `Verified.lean` path. `unknown` means this run did not produce an accepted proof within its limits.

Repeat a successful request without contacting a model:

```sh
python3 bridge.py examples/involution.json --cache-only
```

The checker requires macOS `sandbox-exec`. It fails closed on other platforms. There is no unsandboxed fallback or hosted execution service.

## The example: induction over any number of rounds

[The example request](examples/involution.json) defines a recurrence that applies an involution twice per round. An involution is a function where applying it twice returns the starting value. The goal quantifies over its type, function, starting value, and number of rounds.

The model generated [this accepted proof](examples/Verified.lean):

```lean
intro α f hf n
induction n with
| zero =>
    intro x
    rfl
| succ n ih =>
    intro x
    change pairedSteps f n (f (f x)) = x
    rw [hf x]
    exact ih x
```

This proves the stated cancellation property for arbitrary round counts. The successful development run used one live model proposal and three Lean checks, taking about 14 seconds, locally.

Check the supplied proof without an LLM:

```sh
lake env lean examples/Verified.lean
```

The example does not establish a polynomial algorithm for arbitrary SAT or settle P versus NP. To do that, I'd recommend you:

## Bring your own proposition

Create a JSON file with a fixed context and statement:

```json
{
  "name": "identity",
  "context": "def identityNat (n : Nat) := n",
  "statement": "∀ n : Nat, identityNat n = n"
}
```

Run `python3 bridge.py your_goal.json`. Only the proof body is supplied by the model. Context and proposition remain fixed across retries.

To check a tactic file you already have:

```sh
python3 bridge.py your_goal.json --proof-file proposed_tactics.txt
```

The tactic file contains a sequence such as `intro n` followed by `rfl`, without the outer `by` or Markdown fences.

Python callers can use `solve(request, cache_dir=..., proposer=...)`. A proposer receives the statement, context, goal, previous proof, Lean diagnostics, attempt number, and remaining time. It returns `{"proof": "..."}`. Custom proposers must respect that budget; the supplied Codex adapter enforces its subprocess deadline.

## Verification and execution boundaries

- The statement is parsed as one complete Lean term, then the theorem is constructed structurally. Extra declarations cannot replace the target.
- A proposal is parsed as a complete tactic sequence. Both the native tactic result and the explicit exported proof must pass Lean.
- `audit_llm` checks the exact theorem and its transitive axioms. It permits only `propext`, `Classical.choice`, and `Quot.sound`. Placeholders and additional axioms are rejected.
- `sorry`, `admit`, `native_decide`, new imports, custom syntax, and metaprogramming are outside this prototype's accepted input. The conservative token filter may also reject those words inside comments or strings.
- Checking processes have a deadline, a Lean memory limit, and a macOS sandbox. They have no network permission or filesystem writes. File-content reads are limited to temporary input, the toolchain, trusted compiled modules, and specified OS runtime paths.
- Cached proofs are rechecked. Keys include the exact request and checker fingerprint. A damaged export is rebuilt from a freshly checked proof.

Lean checks the submitted proofs, while automated tests cover the orchestration, caching and error handling done by the Python driver. This is a research prototype meant to run locally.

Cache lookup currently matches exact requests. A universal theorem covers all values quantified in its statement; automatically retrieving applicable lemmas for different statements is a further feature. No completeness or polynomial runtime claim is made for proof search.

## Model connection

The adapter uses installed `codex exec` and requires its existing ChatGPT sign-in. It removes API-key environment variables from the child process, excludes user plugins, hooks, and MCP configuration, disables tools, preserves the configured model, and requests low reasoning effort.

Model requests consume the user's normal Codex allowance. The default CLI run is bounded to three proposals and 120 seconds. No background job is installed.

Set `LEAN_LLM_TOOLCHAIN` to a Lean installation directory or `LEAN_LLM_CODEX` to the Codex executable when discovery needs an explicit location. The project requires the version in `lean-toolchain`.

## Tests

```sh
python3 -m unittest test_bridge -v
```

Tests use deterministic proposals and the real Lean compiler. They cover valid and invalid proofs, feedback and retry, time budgets, cache corruption, statement injection, direct native axiom auditing, and actual sandbox denial of canary file reads and writes. Network permissions are configured but have not been independently penetration-tested.

[Recorded results](examples/test-results.txt) accompany the source. GitHub Actions repeats offline checks on macOS without model credentials.

## Project status

Created through collaboration between Octavia Sulea and OpenAI Codex. The demonstration proof was proposed by a model and checked by Lean. This initial release is intended for inspection, reproduction, and further development.

No project license has been selected yet.
