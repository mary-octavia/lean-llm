"""Lean2LLM: propose, check, store, retrieve, and recheck Lean proofs."""
from __future__ import annotations

from pathlib import Path
import tempfile
import time

from .checker import NativeChecker, check
from .core import CodexProposer
from .records import create_record, now
from .store import ProofStore

__version__ = "0.2.0"
__all__ = ["ProofStore", "NativeChecker", "CodexProposer", "create_record", "check", "solve",
           "verify_certificate_bundle", "inspect_certificate_bundle"]


def solve(request: dict, *, proposer, store: ProofStore | None = None,
          cache_dir: str | Path | None = None, max_attempts=3,
          timeout_seconds=60.0, lean_timeout_seconds=15.0,
          title=None, tags=(), metadata=None) -> dict:
    """Run the original bounded proof loop, optionally using a searchable vault.

    A proposer is explicit: installing, importing, searching, and native checks
    never call a model. CodexProposer uses an existing ChatGPT-authenticated CLI.
    """
    from . import core
    started = time.monotonic()
    if store is not None:
        try:
            reused = store.reuse(request, timeout_seconds=timeout_seconds,
                                 lean_timeout_seconds=lean_timeout_seconds)
        except (ValueError, RuntimeError, OSError) as error:
            return {"status": "unknown", "reason": str(error), "proof": None,
                    "cache_hit": False, "record": None,
                    "metrics": {"model_calls": 0, "proposer_calls": 0, "lean_checks": 0}}
        if reused is not None:
            return {"status": "proved", "reason": "Vault proof rechecked by Lean",
                    "proof": reused["content"]["proof"], "cache_hit": True,
                    "record": reused, "proof_id": reused["id"], "attempts": [],
                    "verified_file": None,
                    "metrics": {"model_calls": 0, "proposer_calls": 0,
                                "lean_checks": store.last_reuse_checks,
                                "seconds": time.monotonic() - started}}
    with tempfile.TemporaryDirectory(prefix="lean2llm-cache-") as scratch:
        result = core.solve(request, cache_dir=Path(cache_dir or scratch), proposer=proposer,
                            max_attempts=max_attempts,
                            timeout_seconds=max(0.001, timeout_seconds - (time.monotonic() - started)),
                            lean_timeout_seconds=lean_timeout_seconds)
        if store is not None:
            result["metrics"]["lean_checks"] += store.last_reuse_checks
        result["metrics"]["seconds"] = time.monotonic() - started
        if result["status"] == "proved" and store is not None:
            toolchain = {"pin": core._pinned_version()[0], "fingerprint": core.toolchain_fingerprint()}
            record = create_record(request, result["proof"], title=title, tags=tags,
                                   metadata=metadata, toolchain=toolchain)
            record["verification"] = {"status": "verified",
                "scope": "fixed-statement Lean kernel check and transitive axiom audit",
                "checked_at": now(), "diagnostics": result["reason"],
                "checker_fingerprint": toolchain["fingerprint"]}
            result["record"] = store._put(record, locally_checked=True)
            result["proof_id"] = record["id"]
        if cache_dir is None:
            # Temporary workspaces disappear; the record carries portable source.
            result["verified_file"] = None
        return result


from .certificates import inspect_certificate_bundle, verify_certificate_bundle
