"""Adapters for independently supplied standalone certificate verifiers.

Imported records and ZIP manifests never choose an executable. The caller
explicitly supplies the local verifier and its expected hash. Its report has a
distinct scope from the package's fixed-statement tactic checker.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys

from .core import _run
from .records import now
from .store import safe_name


def _hash(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _inside(root: Path, relative: str) -> Path:
    safe_name(relative)
    path = (root / relative).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        raise ValueError("Certificate reference is missing or leaves the bundle: " + relative)
    return path


def inspect_certificate_bundle(bundle_dir: str | Path) -> dict:
    """Check the public standalone template's manifest and referenced file hashes.

    This is an integrity inspection. A successful inspection makes no assertion
    about the Lean theorem, its assumptions, or its correspondence to prose.
    """
    root = Path(bundle_dir).expanduser().resolve()
    manifest_path = _inside(root, "manifest.json")
    if manifest_path.stat().st_size > 2_000_000:
        raise ValueError("Certificate manifest exceeds size budget")
    manifest = json.loads(manifest_path.read_text())
    checks = {"manifest.json": _hash(manifest_path)}
    references = manifest.get("reference_files", {})
    if not isinstance(references, dict):
        raise ValueError("reference_files must be an object")
    for name, expected in references.items():
        path = _inside(root, name)
        if _hash(path) != expected:
            raise ValueError("Certificate reference checksum mismatch: " + name)
        checks[name] = expected
    certificates = manifest.get("certificates", {})
    if not isinstance(certificates, dict) or not certificates:
        raise ValueError("Certificate roles are required")
    for entry in certificates.values():
        if not isinstance(entry, dict) or not isinstance(entry.get("file"), str):
            raise ValueError("Invalid certificate entry")
        path = _inside(root, entry["file"])
        if _hash(path) != entry.get("sha256"):
            raise ValueError("Certificate checksum mismatch: " + entry["file"])
        checks[entry["file"]] = entry["sha256"]
    toolchain_file = root / "checker" / "lean-toolchain"
    toolchain_pin = None
    if toolchain_file.exists():
        toolchain_file = _inside(root, "checker/lean-toolchain")
        if toolchain_file.stat().st_size > 1000:
            raise ValueError("Certificate toolchain pin exceeds size budget")
        toolchain_pin = toolchain_file.read_text().strip()
    return {"status": "integrity-checked", "scope": "manifest and referenced file hashes",
            "checked_at": now(), "files": checks,
            "toolchain_pin": toolchain_pin,
            "source": manifest.get("source", {})}


def verify_certificate_bundle(bundle_dir: str | Path, *, verifier: str | Path,
                              expected_sha256: str, timeout_seconds=300.0) -> dict:
    """Run a caller-selected local Python verifier after pinning its exact bytes.

    The caller reviews and trusts this verifier, which is allowed to build its
    own native checker. No command from a proof record or bundle is executed.
    """
    if timeout_seconds <= 0:
        raise ValueError("Positive verifier timeout required")
    integrity = inspect_certificate_bundle(bundle_dir)
    verifier = Path(verifier).expanduser().resolve()
    if verifier.parent != Path(bundle_dir).expanduser().resolve():
        raise ValueError("The explicitly selected verifier must belong to the inspected bundle directory")
    if not verifier.is_file() or _hash(verifier) != expected_sha256:
        raise ValueError("Explicit local verifier SHA256 mismatch")
    result = _run([sys.executable, verifier], cwd=verifier.parent,
                  timeout=timeout_seconds, limit_files=False)
    accepted = result["returncode"] == 0 and not result["timed_out"]
    return {"status": "verifier-succeeded" if accepted else "verifier-failed",
            "scope": "execution of explicitly selected standalone verifier",
            "verifier_sha256": expected_sha256, "checked_at": now(),
            "integrity": integrity, **result}
