"""End-to-end Lean bridge tests with deterministic, untrusted proposals.

These tests invoke the real Lean compiler and native Llm tactic. They make
no model/API calls. A successful test must compile and audit the fixed goal;
text, cache entries, and proposal metadata are never treated as proof evidence.
"""

from __future__ import annotations

import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

if __package__:
    from . import bridge
else:
    import bridge


class LeanBridgeChecks(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="lean-llm-test-")
        self.root = Path(self.directory.name)
        self.cache = self.root / "cache"

    def tearDown(self):
        self.directory.cleanup()

    def request(self, statement="True", context="", name="test_goal"):
        return dict(name=name, context=context, statement=statement)

    def solve_sequence(self, request, candidates, **options):
        payloads = []
        candidates = iter(candidates)
        options.setdefault("timeout_seconds", 60.0)
        options.setdefault("lean_timeout_seconds", 15.0)

        def proposer(payload):
            payloads.append(copy.deepcopy(payload))
            candidate = next(candidates, {"proof": "", "reason": "test proposals exhausted"})
            return candidate if isinstance(candidate, dict) else {"proof": candidate}

        result = bridge.solve(request, cache_dir=self.cache, proposer=proposer, **options)
        self.assertIn(result["status"], ("proved", "unknown"))
        self.assertIsInstance(result["attempts"], list)
        self.assertIsInstance(result["cache_hit"], bool)
        if result["status"] == "proved":
            self.assertIsInstance(result["proof"], str)
            self.assertTrue(Path(result["verified_file"]).is_file())
        return result, payloads

    def test_actual_lean_accepts_a_kernel_checked_proof(self):
        result, payloads = self.solve_sequence(self.request(), ["exact True.intro"], max_attempts=1)
        self.assertEqual(result["status"], "proved", result)
        self.assertFalse(result["cache_hit"])
        self.assertEqual(len(payloads), 1)
        self.assertEqual(payloads[0]["statement"], "True")
        self.assertIn("True", payloads[0]["goal"])

    def test_context_and_quantified_goal_reach_the_actual_compiler(self):
        request = self.request("∀ n : Nat, localIdentity n = n", "def localIdentity (n : Nat) := n")
        result, _ = self.solve_sequence(request, ["intro n\nrfl"], max_attempts=1)
        self.assertEqual(result["status"], "proved", result)

    def test_false_goal_cannot_be_changed_by_proposal_metadata(self):
        request = self.request("False")
        before = copy.deepcopy(request)
        candidate = dict(proof="exact True.intro", statement="True", context="", name="changed_goal")
        result, payloads = self.solve_sequence(request, [candidate], max_attempts=1)
        self.assertEqual(result["status"], "unknown", result)
        self.assertIsNone(result["proof"])
        self.assertEqual(payloads[0]["statement"], "False")
        self.assertEqual(request, before)

    def test_change_tactic_cannot_replace_a_false_goal_with_true(self):
        result, _ = self.solve_sequence(self.request("False"), ["change True\nexact True.intro"], max_attempts=1)
        self.assertEqual(result["status"], "unknown", result)

    def test_statement_cannot_inject_a_different_top_level_theorem(self):
        # Previously this source fragment closed target, created another goal,
        # and could make the driver audit a theorem different from the goal.
        request = self.request("True := by trivial\ntheorem decoy : True")
        result, payloads = self.solve_sequence(request, ["exact True.intro"], max_attempts=1)
        self.assertEqual(result["status"], "unknown", result)
        self.assertIsNone(result["verified_file"])
        self.assertEqual(len(payloads), 0)

    def test_real_lean_error_is_fed_back_before_retry(self):
        result, payloads = self.solve_sequence(self.request(), ["exact Nat.zero", "exact True.intro"], max_attempts=2)
        self.assertEqual(result["status"], "proved", result)
        self.assertEqual(len(payloads), 2)
        diagnostics = str(payloads[1]["diagnostics"])
        self.assertTrue(diagnostics.strip())
        self.assertIn("Nat", diagnostics)
        self.assertIn("True", diagnostics)
        self.assertEqual(payloads[1]["statement"], "True")

    def test_sorry_admit_axiom_unsafe_and_native_decide_are_rejected(self):
        candidates = ["sorry", "admit", "exact (by sorry)",
                      "axiom fabricated : False\nexact fabricated",
                      "exact unsafeCast True.intro", "native_decide"]
        for candidate in candidates:
            with self.subTest(candidate=candidate):
                result, _ = self.solve_sequence(self.request("False"), [candidate], max_attempts=1)
                self.assertEqual(result["status"], "unknown", result)
                self.assertIsNone(result["proof"])

    def test_unsupported_axiom_in_context_cannot_be_audited_as_proved(self):
        request = self.request("False", "axiom fabricated : False")
        # Driver validation may reject the context before a proposer is called.
        try:
            result, _ = self.solve_sequence(request, ["exact fabricated"], max_attempts=1)
        except ValueError:
            return
        self.assertEqual(result["status"], "unknown", result)

    def test_native_decide_is_rejected_even_for_a_true_goal(self):
        result, _ = self.solve_sequence(self.request(), ["native_decide"], max_attempts=1)
        self.assertEqual(result["status"], "unknown", result)

    def test_native_audit_rejects_a_transitive_sorry_without_lexical_guard(self):
        bridge.ensure_module()
        request = self.request("False", "theorem fabricated : False := by sorry")
        result = bridge._check(request, "exact fabricated", timeout=15.0, explicit=True)
        self.assertFalse(result["accepted"], result)
        self.assertIn("LLM_AUDIT_REJECTED", result["diagnostics"])
        self.assertNotIn("LLM_AUDIT_OK", result["diagnostics"])

    def test_native_audit_rejects_a_transitive_custom_axiom_without_lexical_guard(self):
        bridge.ensure_module()
        request = self.request("False", "axiom fabricated : False\ntheorem wrapped : False := fabricated")
        result = bridge._check(request, "exact wrapped", timeout=15.0, explicit=True)
        self.assertFalse(result["accepted"], result)
        self.assertIn("LLM_AUDIT_REJECTED", result["diagnostics"])
        self.assertIn("fabricated", result["diagnostics"])
        self.assertNotIn("LLM_AUDIT_OK", result["diagnostics"])

    def test_trailing_declarations_and_prose_are_not_executed_as_proofs(self):
        candidates = ["exact True.intro\n\naxiom fabricated : False",
                      "exact True.intro\n\ntheorem changed : False := by sorry",
                      "exact True.intro\n\ntheorem injected : True := by\n  trivial",
                      "Here is the proof: exact True.intro",
                      "```lean\nexact True.intro\n```"]
        for candidate in candidates:
            with self.subTest(candidate=candidate):
                result, _ = self.solve_sequence(self.request(), [candidate], max_attempts=1)
                self.assertEqual(result["status"], "unknown", result)

    def test_metaprogramming_candidate_cannot_write_a_file(self):
        marker = self.root / "forbidden-marker.txt"
        candidate = ("run_tac do\n"
                     f"  liftIO <| IO.FS.writeFile {json.dumps(str(marker))} \"executed\"\n"
                     "exact True.intro")
        result, _ = self.solve_sequence(self.request(), [candidate], max_attempts=1)
        self.assertEqual(result["status"], "unknown", result)
        self.assertFalse(marker.exists())

    def test_metaprogramming_candidate_cannot_expose_a_local_canary(self):
        secret = "LEAN_BRIDGE_PRIVATE_TEST_CANARY_604195"
        path = self.root / "private-canary.txt"
        path.write_text(secret)
        candidate = ("run_tac do\n"
                     f"  let contents ← liftIO <| IO.FS.readFile {json.dumps(str(path))}\n"
                     "  Lean.logInfo contents\n"
                     "exact True.intro")
        result, payloads = self.solve_sequence(self.request(), [candidate], max_attempts=1)
        self.assertEqual(result["status"], "unknown", result)
        self.assertNotIn(secret, json.dumps(result))
        self.assertNotIn(secret, json.dumps(payloads))

    def test_os_sandbox_denies_canary_read_even_without_lexical_guard(self):
        bridge.ensure_module()
        secret = "OS_SANDBOX_PRIVATE_TEST_CANARY_871043"
        path = self.root / "os-read-canary.txt"
        path.write_text(secret)
        request = self.request(context=f"#eval IO.FS.readFile {json.dumps(str(path))}")
        # _check runs the actual compiler sandbox. Calling it directly bypasses
        # trusted-request token filtering, so the OS must block this #eval IO.
        result = bridge._check(request, "exact True.intro", timeout=15.0, explicit=True)
        self.assertFalse(result["accepted"], result)
        self.assertFalse(result.get("timed_out"), result)
        self.assertIn("os-read-canary.txt", result["diagnostics"])
        self.assertRegex(result["diagnostics"].lower(), "operation not permitted|permission denied")
        self.assertNotIn(secret, result["diagnostics"])
        self.assertEqual(path.read_text(), secret)

    def test_os_sandbox_denies_canary_write_even_without_lexical_guard(self):
        bridge.ensure_module()
        path = self.root / "os-write-canary.txt"
        path.write_text("unchanged")
        request = self.request(context=f"#eval IO.FS.writeFile {json.dumps(str(path))} \"changed\"")
        result = bridge._check(request, "exact True.intro", timeout=15.0, explicit=True)
        self.assertFalse(result["accepted"], result)
        self.assertFalse(result.get("timed_out"), result)
        self.assertIn("os-write-canary.txt", result["diagnostics"])
        self.assertRegex(result["diagnostics"].lower(), "operation not permitted|permission denied")
        self.assertEqual(path.read_text(), "unchanged")

    def test_failed_proposals_exhaust_attempts_without_a_proof(self):
        result, payloads = self.solve_sequence(self.request("False"), ["exact True.intro"] * 3, max_attempts=3)
        self.assertEqual(result["status"], "unknown", result)
        self.assertEqual(len(payloads), 3)
        self.assertIsNone(result["proof"])
        self.assertIsNone(result["verified_file"])

    def test_empty_model_response_is_unknown(self):
        result, _ = self.solve_sequence(self.request(), [{"proof": "", "reason": "no candidate"}], max_attempts=1)
        self.assertEqual(result["status"], "unknown", result)

    def test_lean_subprocess_timeout_is_unknown(self):
        result, _ = self.solve_sequence(self.request(), ["exact True.intro"],
                                        max_attempts=1, lean_timeout_seconds=0.001)
        self.assertEqual(result["status"], "unknown", result)
        self.assertIsNone(result["proof"])

    def test_valid_cached_proof_is_rechecked_without_proposer(self):
        request = self.request()
        first, _ = self.solve_sequence(request, ["exact True.intro"], max_attempts=1)
        self.assertEqual(first["status"], "proved", first)

        def never_called(payload):
            self.fail("A valid checked cache hit should not invoke the proposer.")

        second = bridge.solve(request, cache_dir=self.cache, proposer=never_called, max_attempts=1,
                              timeout_seconds=60.0, lean_timeout_seconds=15.0)
        self.assertEqual(second["status"], "proved", second)
        self.assertTrue(second["cache_hit"])

    def test_tampered_cached_proof_is_rejected_and_replaced(self):
        request = self.request()
        first, _ = self.solve_sequence(request, ["exact True.intro"], max_attempts=1)
        self.assertEqual(first["status"], "proved", first)
        cached = self.cache / bridge.request_key(request) / "proof.json"
        content = json.loads(cached.read_text())
        content["proof"] = "exact Nat.zero"
        cached.write_text(json.dumps(content))
        second, payloads = self.solve_sequence(request, ["exact True.intro"], max_attempts=1)
        self.assertEqual(second["status"], "proved", second)
        self.assertFalse(second["cache_hit"])
        self.assertEqual(len(payloads), 1)
        self.assertEqual(json.loads(cached.read_text())["proof"], "exact True.intro")

    def test_non_object_cache_json_is_ignored_and_replaced(self):
        request = self.request()
        first, _ = self.solve_sequence(request, ["exact True.intro"], max_attempts=1)
        self.assertEqual(first["status"], "proved", first)
        cached = self.cache / bridge.request_key(request) / "proof.json"
        cached.write_text("[]\n")
        second, payloads = self.solve_sequence(request, ["exact True.intro"], max_attempts=1)
        self.assertEqual(second["status"], "proved", second)
        self.assertFalse(second["cache_hit"])
        self.assertEqual(len(payloads), 1)
        self.assertIsInstance(json.loads(cached.read_text()), dict)

    def test_cache_recheck_restores_a_tampered_verified_export(self):
        request = self.request()
        first, _ = self.solve_sequence(request, ["exact True.intro"], max_attempts=1)
        self.assertEqual(first["status"], "proved", first)
        export = Path(first["verified_file"])
        export.write_text("theorem target : False := by sorry\n")

        def never_called(payload):
            self.fail("The checked proof cache remains valid despite export tampering.")

        second = bridge.solve(request, cache_dir=self.cache, proposer=never_called, max_attempts=1,
                              timeout_seconds=60.0, lean_timeout_seconds=15.0)
        self.assertEqual(second["status"], "proved", second)
        verified = Path(second["verified_file"]).read_text()
        self.assertNotIn("by sorry", verified)
        self.assertIn("True", verified)

    def test_goal_and_context_changes_cannot_reuse_a_different_theorem(self):
        first_request = self.request("localValue = 0", "def localValue : Nat := 0")
        other_context = self.request("localValue = 0", "def localValue : Nat := 1")
        other_goal = self.request("localValue = 1", "def localValue : Nat := 0")
        self.assertNotEqual(bridge.request_key(first_request), bridge.request_key(other_context))
        self.assertNotEqual(bridge.request_key(first_request), bridge.request_key(other_goal))
        first, _ = self.solve_sequence(first_request, ["rfl"], max_attempts=1)
        self.assertEqual(first["status"], "proved", first)
        for request in (other_context, other_goal):
            result, payloads = self.solve_sequence(request, ["rfl"], max_attempts=1)
            self.assertEqual(result["status"], "unknown", result)
            self.assertFalse(result["cache_hit"])
            self.assertEqual(len(payloads), 1)

    def test_changed_toolchain_identity_uses_a_new_checked_cache_entry(self):
        request = self.request()
        identity = bridge.toolchain_fingerprint()
        self.assertIsInstance(identity, str)
        self.assertTrue(identity)
        original_key = bridge.request_key(request)
        first, _ = self.solve_sequence(request, ["exact True.intro"], max_attempts=1)
        self.assertEqual(first["status"], "proved", first)
        # Simulate an identity change without replacing or trusting a fake
        # compiler: the second proposal still runs through the actual Lean.
        with patch.object(bridge, "toolchain_fingerprint", return_value=identity + "-changed-for-test"):
            self.assertNotEqual(bridge.request_key(request), original_key)
            second, payloads = self.solve_sequence(request, ["exact True.intro"], max_attempts=1)
            self.assertEqual(second["status"], "proved", second)
            self.assertFalse(second["cache_hit"])
            self.assertEqual(len(payloads), 1)


class ReleaseDiscoveryChecks(unittest.TestCase):
    """Packaging checks use temporary executables, never a model invocation."""

    def test_help_works_without_an_installed_toolchain_or_codex(self):
        with tempfile.TemporaryDirectory(prefix="lean-llm-discovery-") as directory:
            env = dict(os.environ, PATH="/usr/bin:/bin",
                       LEAN_LLM_TOOLCHAIN=str(Path(directory) / "missing-lean"),
                       LEAN_LLM_CODEX=str(Path(directory) / "missing-codex"))
            completed = subprocess.run(
                [sys.executable, str(Path(bridge.__file__).resolve()), "--help"],
                cwd=directory, env=env, capture_output=True, text=True, timeout=10,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertIn("usage:", completed.stdout.lower())
            self.assertNotIn("Traceback", completed.stderr)

    def test_invalid_explicit_toolchain_does_not_fall_back(self):
        with tempfile.TemporaryDirectory(prefix="lean-llm-discovery-") as directory:
            with patch.dict(os.environ, {"LEAN_LLM_TOOLCHAIN": directory}):
                with self.assertRaises(RuntimeError):
                    bridge._discover_toolchain()

    def test_invalid_explicit_codex_does_not_fall_back(self):
        with tempfile.TemporaryDirectory(prefix="lean-llm-discovery-") as directory:
            with patch.dict(os.environ, {"LEAN_LLM_CODEX": directory}):
                with self.assertRaises(RuntimeError):
                    bridge._discover_codex()

    def test_toolchain_version_must_match_the_project_pin(self):
        with tempfile.TemporaryDirectory(prefix="lean-llm-discovery-") as directory:
            root = Path(directory)
            binary = root / "bin"
            binary.mkdir()
            lean = binary / "lean"
            lean.write_text("#!/bin/sh\nprintf '%s\\n' 'Lean (version 0.0.0, test fixture)'\n")
            lean.chmod(0o755)
            lake = binary / "lake"
            lake.write_text("#!/bin/sh\nexit 0\n")
            lake.chmod(0o755)
            with patch.dict(os.environ, {"LEAN_LLM_TOOLCHAIN": str(root)}):
                with self.assertRaises(RuntimeError):
                    bridge._discover_toolchain()


if __name__ == "__main__":
    unittest.main()
