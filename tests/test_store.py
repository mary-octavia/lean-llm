from __future__ import annotations

import copy
import hashlib
from importlib.resources import files
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from lean_llm import ProofStore, create_record
from lean_llm.assets import materialize
from lean_llm.records import canonical, digest, validate_record
from lean_llm.store import safe_name
from lean_llm.certificates import inspect_certificate_bundle, verify_certificate_bundle


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.store = ProofStore(self.root / "proofs.sqlite3")
        self.request = {"name": "identity", "context": "", "statement": "∀ n : Nat, n = n"}
        self.record = create_record(self.request, "intro n\nrfl", title="Natural identity", tags=["induction", "nat"],
                                    toolchain={"pin": "leanprover/lean4:v4.33.1", "fingerprint": "test-compiler"})

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    def test_content_id_is_deterministic_and_metadata_changes_it(self):
        identical = create_record(self.request, "intro n\nrfl", title="Natural identity", tags=["nat", "induction"],
                                  toolchain=self.record["content"]["toolchain"])
        self.assertEqual(identical["id"], self.record["id"])
        changed = copy.deepcopy(self.record)
        changed["content"]["proof"] = "trivial"
        with self.assertRaisesRegex(ValueError, "SHA256"):
            self.store.put(changed)

    def test_content_numbers_are_lossless_safe_integers(self):
        for value in (1.0, 1.5, float("inf"), float("nan"), 2**53, -(2**53)):
            with self.subTest(value=value):
                with self.assertRaisesRegex(ValueError, "safe integers"):
                    create_record(self.request, "intro n\nrfl", metadata={"value": value})
        record = create_record(self.request, "intro n\nrfl", metadata={
            "low": -(2**53-1), "high": 2**53-1, "fraction": "1.5", "nested": [1, True, None]})
        self.assertEqual(validate_record(record)["id"], record["id"])

    def test_canonical_strings_reject_unpaired_unicode_surrogates(self):
        with self.assertRaisesRegex(ValueError, "Unicode"):
            create_record(self.request, "intro n\nrfl", metadata={"bad": "\ud800"})

    def test_source_must_match_exact_goal_even_if_attacker_rehashes(self):
        changed = copy.deepcopy(self.record)
        changed["content"]["source"] = "theorem target : True := by trivial"
        changed["id"] = digest(changed["content"])
        with self.assertRaisesRegex(ValueError, "Source"):
            self.store.put(changed)

    def test_external_verified_flag_is_discarded(self):
        self.record["verification"] = {"status": "verified", "scope": "anything"}
        stored = self.store.put(self.record)
        self.assertEqual(stored["verification"]["status"], "unverified")
        self.assertEqual(self.store.get(stored["id"])["verification"]["scope"], "none")

    def test_fts_finds_title_statement_and_tags(self):
        self.store.put(self.record)
        for query in ("Natural", "Nat", "induction", "Natural identity"):
            with self.subTest(query=query):
                self.assertEqual(self.store.search(query)[0]["id"], self.record["id"])
        self.assertEqual(self.store.search("absent"), [])

    def test_exact_lookup_rejects_changed_context_statement_and_toolchain(self):
        self.store.put(self.record)
        tc = self.record["content"]["toolchain"]
        self.assertEqual(len(self.store.lookup(self.request, tc)), 1)
        for field, value in (("context", "def extra : Nat := 0"), ("statement", "True")):
            changed = {**self.request, field: value}
            self.assertEqual(self.store.lookup(changed, tc), [])
        self.assertEqual(self.store.lookup(self.request, {**tc, "fingerprint": "other"}), [])
        # A display name does not change the mathematical request.
        self.assertEqual(len(self.store.lookup({**self.request, "name": "renamed"}, tc)), 1)

    def test_bundle_round_trip_resets_imported_status(self):
        self.store.put(self.record)
        exported = self.store.export_bundle(self.record["id"], self.root / "proof.zip")
        with ProofStore(self.root / "other.sqlite3") as other:
            imported = other.import_bundle(exported)
            self.assertEqual(imported["id"], self.record["id"])
            self.assertEqual(imported["verification"]["status"], "unverified")
        with zipfile.ZipFile(exported) as archive:
            self.assertIn("checker/Llm.lean", archive.namelist())
            self.assertIn("verify.py", archive.namelist())
            self.assertIn("_driver.py", archive.namelist())

    def _rewrite_bundle(self, path, mutate):
        with zipfile.ZipFile(path) as archive:
            entries = {name: archive.read(name) for name in archive.namelist()}
        mutate(entries)
        with zipfile.ZipFile(path, "w") as archive:
            for name, data in entries.items():
                archive.writestr(name, data)

    def test_bundle_tampering_is_rejected(self):
        self.store.put(self.record)
        path = self.store.export_bundle(self.record["id"], self.root / "proof.zip")
        self._rewrite_bundle(path, lambda entries: entries.__setitem__("source/Proof.lean", b"tampered"))
        with self.assertRaisesRegex(ValueError, "checksum"):
            self.store.import_bundle(path)

    def test_bundle_traversal_is_rejected_before_extracting(self):
        path = self.root / "attack.zip"
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr("../escape", "bad")
        with self.assertRaisesRegex(ValueError, "Unsafe"):
            self.store.import_bundle(path)
        self.assertFalse((self.root.parent / "escape").exists())

    def test_bundle_duplicate_entries_are_rejected(self):
        import warnings
        path = self.root / "duplicate.zip"
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            with zipfile.ZipFile(path, "w") as archive:
                archive.writestr("manifest.json", "{}")
                archive.writestr("manifest.json", "{}")
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            self.store.import_bundle(path)

    def test_bundle_symlink_is_rejected(self):
        path = self.root / "symlink.zip"
        info = zipfile.ZipInfo("record.json")
        info.create_system = 3
        info.external_attr = (0o120777 << 16)
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr(info, "/etc/passwd")
        with self.assertRaisesRegex(ValueError, "ordinary"):
            self.store.import_bundle(path)

    def test_bundle_expanded_size_limit(self):
        self.store.put(self.record)
        path = self.store.export_bundle(self.record["id"], self.root / "proof.zip")
        with patch("lean_llm.store.MAX_BUNDLE_BYTES", 10):
            with self.assertRaisesRegex(ValueError, "expanded"):
                self.store.import_bundle(path)

    def test_import_never_executes_a_bundled_verifier(self):
        self.store.put(self.record)
        path = self.store.export_bundle(self.record["id"], self.root / "proof.zip")
        def malicious(entries):
            entries["verify.py"] = b"raise SystemExit('EXECUTED')"
            manifest = json.loads(entries["manifest.json"])
            manifest["files"]["verify.py"] = {"sha256": hashlib.sha256(entries["verify.py"]).hexdigest(),
                                                   "bytes": len(entries["verify.py"])}
            entries["manifest.json"] = canonical(manifest)
        self._rewrite_bundle(path, malicious)
        self.assertEqual(self.store.import_bundle(path)["verification"]["status"], "unverified")

    def test_database_content_tampering_is_detected_on_read(self):
        self.store.put(self.record)
        tampered = copy.deepcopy(self.record["content"])
        tampered["request"]["statement"] = "False"
        self.store.connection.execute("UPDATE proofs SET content=?", (canonical(tampered).decode(),))
        self.store.connection.commit()
        with self.assertRaisesRegex(ValueError, "SHA256"):
            self.store.get(self.record["id"])

    def test_packaged_assets_exist_and_restore_altered_inputs(self):
        target = self.root / "native"
        materialize(target)
        (target / "Llm.lean").write_text("altered")
        materialize(target)
        self.assertEqual((target / "Llm.lean").read_bytes(),
                         files("lean_llm").joinpath("_assets/Llm.lean").read_bytes())

    def test_cli_store_search_show_and_export_without_lean(self):
        request = self.root / "request.json"
        proof = self.root / "proof.txt"
        request.write_text(json.dumps(self.request))
        proof.write_text("intro n\nrfl")
        from lean_llm.cli import main
        import io
        from contextlib import redirect_stdout
        stream = io.StringIO()
        with redirect_stdout(stream):
            status = main(["--db", str(self.root / "cli.sqlite3"), "store", str(request), "--proof", str(proof)])
        self.assertEqual(status, 0)
        record = json.loads(stream.getvalue())
        self.assertEqual(record["verification"]["status"], "unverified")
        stream = io.StringIO()
        with redirect_stdout(stream):
            status = main(["--db", str(self.root / "cli.sqlite3"), "search", "Nat"])
        self.assertEqual(json.loads(stream.getvalue())[0]["id"], record["id"])


class CertificateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root / "cert.ndjson").write_text("certificate fixture")
        self.manifest = {"certificates": {"solution": {"file": "cert.ndjson",
            "sha256": hashlib.sha256((self.root / "cert.ndjson").read_bytes()).hexdigest()}},
            "reference_files": {}, "source": {"commit": "fixture"}}
        self.write_manifest()

    def tearDown(self):
        self.temp.cleanup()

    def write_manifest(self):
        (self.root / "manifest.json").write_text(json.dumps(self.manifest))

    def test_integrity_is_explicitly_distinct_from_proof_verification(self):
        result = inspect_certificate_bundle(self.root)
        self.assertEqual(result["status"], "integrity-checked")
        self.assertNotIn("accepted", result)

    def test_tampered_certificate_is_rejected(self):
        (self.root / "cert.ndjson").write_text("changed")
        with self.assertRaisesRegex(ValueError, "checksum"):
            inspect_certificate_bundle(self.root)

    def test_certificate_paths_cannot_escape_bundle(self):
        self.manifest["certificates"]["solution"]["file"] = "../outside"
        self.write_manifest()
        with self.assertRaisesRegex(ValueError, "Unsafe"):
            inspect_certificate_bundle(self.root)

    def test_certificate_toolchain_symlink_cannot_read_outside_bundle(self):
        outside = self.root.parent / (self.root.name + "-outside")
        outside.write_text("outside toolchain pin")
        (self.root / "checker").mkdir()
        (self.root / "checker/lean-toolchain").symlink_to(outside)
        try:
            with self.assertRaisesRegex(ValueError, "leaves"):
                inspect_certificate_bundle(self.root)
        finally:
            outside.unlink()

    def test_verifier_requires_explicit_matching_hash(self):
        verifier = self.root / "verify.py"
        verifier.write_text("print('fixture verifier')")
        with self.assertRaisesRegex(ValueError, "SHA256"):
            verify_certificate_bundle(self.root, verifier=verifier, expected_sha256="wrong")
        outcome = verify_certificate_bundle(self.root, verifier=verifier,
                                            expected_sha256=hashlib.sha256(verifier.read_bytes()).hexdigest())
        self.assertEqual(outcome["status"], "verifier-succeeded")
        self.assertIn("explicitly selected", outcome["scope"])


if __name__ == "__main__":
    unittest.main()
