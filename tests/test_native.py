"""Real Lean integration tests. Zero model calls; explicitly opt in."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from lean_llm import check, create_record, ProofStore, solve


@unittest.skipUnless(os.environ.get("LEAN_LLM_NATIVE_TESTS") == "1", "Set LEAN_LLM_NATIVE_TESTS=1 for real Lean checks")
class NativeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.store = ProofStore(self.root / "proofs.sqlite3")
        self.request = {"name": "identity", "context": "", "statement": "∀ n : Nat, n = n"}

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    def test_actual_kernel_accepts_fixed_statement(self):
        result = check(self.request, "intro n\nrfl")
        self.assertTrue(result["check"]["accepted"], result)
        self.assertEqual(len(result["check"]["checks"]), 2)
        self.assertEqual(result["record"]["verification"]["status"], "verified")

    def test_wrong_proof_and_placeholders_are_rejected(self):
        for proof in ("exact True.intro", "sorry", "native_decide"):
            with self.subTest(proof=proof):
                result = check({"name": "false", "context": "", "statement": "False"}, proof)
                self.assertFalse(result["check"]["accepted"], result)
                self.assertEqual(result["record"]["verification"]["status"], "unverified")

    def test_store_check_changes_unresolved_identity_and_rechecks_hits(self):
        stored = self.store.add(self.request, "intro n\nrfl")
        result = self.store.check(stored["id"])
        self.assertTrue(result["check"]["accepted"], result)
        self.assertNotEqual(result["record"]["id"], stored["id"])
        with patch("lean_llm.checker.NativeChecker.check", wraps=__import__("lean_llm").NativeChecker().check) as native:
            reused = self.store.reuse(self.request)
            self.assertIsNotNone(reused)
            self.assertEqual(native.call_count, 1)

    def test_rejected_recheck_clears_prior_local_status(self):
        record = self.store.add(self.request, "intro n\nrfl")
        result = self.store.check(record["id"])
        checked_id = result["record"]["id"]
        rejected = {"record": {**result["record"], "verification": {
            "status": "unverified", "scope": "none", "checked_at": None,
            "diagnostics": "Rejected in test", "checker_fingerprint": None}},
            "check": {"accepted": False, "checks": [], "diagnostics": "Rejected in test"}}
        with patch("lean_llm.checker.check", return_value=rejected):
            self.store.check(checked_id)
        self.assertEqual(self.store.get(checked_id)["verification"]["status"], "unverified")

    def test_original_proposer_feedback_and_vault_reuse(self):
        calls = []
        def proposer(payload):
            calls.append(payload)
            return {"proof": "intro n\nrfl"}
        result = solve(self.request, proposer=proposer, store=self.store, max_attempts=1)
        self.assertEqual(result["status"], "proved", result)
        self.assertEqual(len(calls), 1)
        second = solve(self.request, proposer=lambda _: self.fail("cache hit must not call proposer"), store=self.store)
        self.assertTrue(second["cache_hit"], second)
        self.assertEqual(second["metrics"]["proposer_calls"], 0)
        self.assertEqual(second["metrics"]["lean_checks"], 2)

    def test_standalone_export_replays_without_importing_installed_package(self):
        stored = self.store.add(self.request, "intro n\nrfl")
        bundle = self.store.export_bundle(stored["id"], self.root / "proof.zip")
        target = self.root / "unpacked"
        with zipfile.ZipFile(bundle) as archive:
            archive.extractall(target)
        env = {key: value for key, value in os.environ.items() if key != "PYTHONPATH"}
        result = subprocess.run([sys.executable, "-I", str(target / "verify.py")], cwd=target,
                                env=env, text=True, capture_output=True, timeout=90)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("LEAN2LLM_BUNDLE_VERIFIED", result.stdout)

    def test_native_audit_rejects_transitive_custom_axiom(self):
        from lean_llm import core
        core.ensure_module()
        request = {"name": "audit", "context": "axiom fabricated : False", "statement": "False"}
        result = core._check(request, "exact fabricated", timeout=15, explicit=True)
        self.assertFalse(result["accepted"], result)
        self.assertIn("LLM_AUDIT_REJECTED", result["diagnostics"])

    def test_forged_import_status_requires_and_fails_real_native_recheck(self):
        forged = create_record({"name": "forged", "context": "", "statement": "False"}, "exact True.intro")
        forged["verification"] = {"status": "verified", "scope": "forged external claim"}
        self.store.put(forged)
        archive = self.store.export_bundle(forged["id"], self.root / "forged.zip")
        with ProofStore(self.root / "imported.sqlite3") as imported:
            candidate = imported.import_bundle(archive)
            self.assertEqual(candidate["verification"]["status"], "unverified")
            checked = imported.check(candidate["id"])
            self.assertFalse(checked["check"]["accepted"], checked)
            self.assertEqual(checked["record"]["verification"]["status"], "unverified")


if __name__ == "__main__":
    unittest.main()
