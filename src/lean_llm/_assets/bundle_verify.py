#!/usr/bin/env python3
"""Verify an unpacked Lean2LLM proof bundle with Python and pinned native Lean.

Install the toolchain in checker/lean-toolchain; set LEAN_LLM_TOOLCHAIN to its
real distribution root if elan is unavailable. The process sandbox requires
macOS sandbox-exec. All file hashes are checked before loading the local driver.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path, PurePosixPath


def main():
    root = Path(__file__).resolve().parent
    manifest = json.loads((root / "manifest.json").read_text())
    if manifest.get("schema") != "lean2llm.bundle/v1":
        raise SystemExit("Unsupported proof bundle")
    for name, expected in manifest["files"].items():
        relative = PurePosixPath(name)
        path = (root / relative).resolve()
        if "\\" in name or ":" in name or relative.is_absolute() or ".." in relative.parts or not path.is_relative_to(root):
            raise SystemExit("Unsafe bundle path")
        data = path.read_bytes()
        if expected != {"sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}:
            raise SystemExit("Bundle integrity check failed: " + name)
    record = json.loads((root / "record.json").read_text())
    content = record["content"]
    canonical = json.dumps(content, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()
    if hashlib.sha256(canonical).hexdigest() != record["id"] or record["id"] != manifest["proof_id"]:
        raise SystemExit("Content ID mismatch")
    spec = importlib.util.spec_from_file_location("lean2llm_standalone", root / "_driver.py")
    driver = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(driver)
    request = driver._request(content["request"])
    if driver._source(request, content["proof"]) != content["source"]:
        raise SystemExit("Fixed statement and exported source mismatch")
    if (root / "source/Proof.lean").read_text() != content["source"]:
        raise SystemExit("Source file differs from proof record")
    driver.ensure_module()
    for explicit in (False, True):
        result = driver._check(request, content["proof"], timeout=30, explicit=explicit)
        print(result["diagnostics"])
        if not result["accepted"]:
            raise SystemExit("Native Lean check failed")
    print("LEAN2LLM_BUNDLE_VERIFIED " + record["id"])


if __name__ == "__main__":
    main()
