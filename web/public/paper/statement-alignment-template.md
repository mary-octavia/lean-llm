# Proof package: statement alignment

Complete this alongside the source or certificate manifest. Keep formal acceptance, mathematical interpretation, and review events explicit.

## Artifact identity

- Title:
- Content identifier and schema version:
- Source repository and exact revision:
- Author(s) and source license(s):
- Related artifacts:

## Exact formal target

- Fully qualified theorem name(s):
- Complete statement, including quantified hypotheses:
- Definitions needed to interpret the statement:
- Lean toolchain pin:
- Dependency manifest or certificate closure:
- Permitted axioms:

## Verification event

- Backend (`lean-tactic`, certificate replay, or another explicit profile):
- Checker source revision and fingerprint:
- Command and environment:
- Checked content digest:
- UTC timestamp, elapsed time and process exit status:
- Saved diagnostics and assumption audit:
- Scope covered by this check:

## Intended mathematical claim

Write the intended statement in ordinary mathematical language. Identify its source and version if it comes from another document.

## Correspondence argument

State the direction being established, for example: "The formal theorem implies the intended claim under the interpretation below."

1. Match the quantified objects and definitions.
2. Match each hypothesis, including boundary, finiteness, regularity or representation requirements.
3. Match the conclusion and its quantifier order.
4. Explain every conversion or auxiliary lemma.
5. List remaining obligations and the evidence needed to discharge each one.

## Review provenance

- Reviewer or reviewing tool and version:
- Material reviewed, identified by digest:
- Review date and method:
- Findings, unresolved questions and corrections:
- Review scope, including whether the correspondence was compiled as a theorem:

## Reproduction

Provide commands to acquire the pinned toolchain, verify integrity, run the designated checker and inspect the formal target. Describe the storage, memory and time needed. List any external services that a fresh generation run uses; keep verification instructions usable independently where the backend permits it.
