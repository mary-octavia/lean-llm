import Lean
import Std

/-!
A native bridge from an externally proposed tactic sequence to Lean's normal
elaborator and kernel. This module never calls a model or accepts its claims
as axioms. The external driver supplies the UTF-8 tactic file named by
LLM_PROOF_FILE and decides whether to retry after an ordinary Lean error.

This bridge is not an operating-system sandbox. The driver must independently
restrict untrusted tactic execution, source imports, resources, and output.
The audit concerns the named theorem's kernel proof and transitive axioms.
-/

namespace LeanLlm

open Lean Elab Tactic Command

private def emitGoalRequest : TacticM Unit := do
  let main ← getMainGoal
  let pretty ← Meta.ppGoal main
  let goals ← getGoals
  let request := Json.mkObj [
    ("version", toJson (1 : Nat)),
    ("goal", toJson pretty.pretty),
    ("pending_goals", toJson goals.length)
  ]
  logInfo m!"LLM_GOAL_REQUEST {request.compress}"

syntax (name := llmTactic) "llm" : tactic

/- In Lean 4.33, tacticSeq is a parser alias, not a parser category.
   This category wraps that existing parser so runParserCategory can consume
   exactly one complete tactic sequence without adding source text. -/
declare_syntax_cat llmTacticSeq
syntax (name := llmTacticSequence) tacticSeq : llmTacticSeq

@[tactic llmTactic] def evalLlm : Tactic := fun _ => withMainContext do
  let path : Option String ← liftM <| IO.getEnv "LLM_PROOF_FILE"
  let some path := path | do
    emitGoalRequest
    throwError "LLM_PROOF_FILE is absent; an external proposal is required"
  if path.isEmpty then
    emitGoalRequest
    throwError "LLM_PROOF_FILE is empty; an external proposal is required"
  let script : String ← liftM <| IO.FS.readFile path
  if script.trimAscii.isEmpty then
    throwError "LLM_PROPOSAL_ERROR: the tactic file is empty"
  let environment ← getEnv
  match Parser.runParserCategory environment `llmTacticSeq script path with
  | .error message =>
      throwError "LLM_PROPOSAL_PARSE_ERROR: {message}"
  | .ok wrapped =>
      evalTactic wrapped[0]

/- Keep the fixed proposition out of raw source concatenation. Parsing the
   entire UTF-8 file as one term prevents it from closing this declaration or
   introducing a second theorem whose goal differs from the audited target. -/
elab "llm_theorem " target:ident : command => do
  let path : Option String ← liftM <| IO.getEnv "LLM_STATEMENT_FILE"
  let some path := path |
    throwError "LLM_STATEMENT_ERROR: LLM_STATEMENT_FILE is absent"
  if path.isEmpty then
    throwError "LLM_STATEMENT_ERROR: LLM_STATEMENT_FILE is empty"
  let statement : String ← liftM <| IO.FS.readFile path
  if statement.trimAscii.isEmpty then
    throwError "LLM_STATEMENT_ERROR: the statement file is empty"
  let environment ← getEnv
  match Parser.runParserCategory environment `term statement path with
  | .error message =>
      throwError "LLM_STATEMENT_PARSE_ERROR: {message}"
  | .ok parsed =>
      let proposition : TSyntax `term := ⟨parsed⟩
      elabCommand (← `(theorem $target : $proposition := by llm))

/- Resolve exactly one declaration and inspect the kernel-checked environment.
   Awaiting env.checked also avoids accepting an elaboration-only placeholder.
   The enclosing Lean invocation must still finish successfully: this marker
   is not permission to ignore errors elsewhere in the source file. -/
elab "audit_llm " target:ident : command => do
  let name ← resolveGlobalConstNoOverload target
  let environment ← getEnv
  let some info := environment.checked.get.find? name |
    throwError "LLM_AUDIT_REJECTED: no kernel-checked declaration named {name}"
  let .thmInfo declaration := info |
    throwError "LLM_AUDIT_REJECTED: {name} is not a theorem declaration"
  if declaration.type.hasMVar || declaration.value.hasMVar then
    throwError "LLM_AUDIT_REJECTED: {name} contains unresolved metavariables"
  if declaration.type.hasFVar || declaration.value.hasFVar ||
      declaration.type.hasLooseBVars || declaration.value.hasLooseBVars then
    throwError "LLM_AUDIT_REJECTED: {name} is not a closed declaration"
  if declaration.type.hasSorry || declaration.value.hasSorry then
    throwError "LLM_AUDIT_REJECTED: {name} contains a proof placeholder"
  let allowed := #[``propext, ``Classical.choice, ``Quot.sound]
  let dependencies ← collectAxioms name
  for dependency in dependencies do
    unless allowed.contains dependency do
      throwError "LLM_AUDIT_REJECTED: {name} depends on disallowed axiom {dependency}"
  logInfo m!"LLM_AUDIT_OK {name}"

end LeanLlm
