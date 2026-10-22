"""Native Lean verification using the original restricted proof loop."""
from __future__ import annotations

import time

from . import core
from .assets import pin
from .records import create_record, now


class NativeChecker:
    """Pinned Lean, fixed proposition, native axiom audit, and exported-source recheck.

    The original process sandbox requires macOS sandbox-exec. Importing the
    library, storing records, and searching require neither Lean nor macOS.
    """
    def __init__(self, *, timeout_seconds=30.0, lean_timeout_seconds=15.0):
        if timeout_seconds <= 0 or lean_timeout_seconds <= 0:
            raise ValueError("Positive time limits are required")
        self.timeout_seconds = timeout_seconds
        self.lean_timeout_seconds = lean_timeout_seconds

    def identity(self) -> dict:
        core.ensure_module()
        return {"pin": pin(), "fingerprint": core.toolchain_fingerprint()}

    def check(self, request: dict, proof: str) -> dict:
        request = core._request(request)
        toolchain = self.identity()
        started = time.monotonic()
        checks = []
        for explicit in (False, True):
            remaining = self.timeout_seconds - (time.monotonic() - started)
            if remaining <= 0:
                return {"accepted": False, "toolchain": toolchain, "checks": checks,
                        "diagnostics": "Total native-check time budget exhausted"}
            result = core._check(request, proof, timeout=min(remaining, self.lean_timeout_seconds),
                                 explicit=explicit)
            checks.append(result)
            if not result["accepted"]:
                return {"accepted": False, "toolchain": toolchain, "checks": checks,
                        "diagnostics": result["diagnostics"]}
        return {"accepted": True, "toolchain": toolchain, "checks": checks,
                "diagnostics": checks[-1]["diagnostics"],
                "scope": "fixed-statement Lean kernel check and transitive axiom audit",
                "checked_at": now()}


def check(request: dict, proof: str, *, title=None, tags=(), metadata=None,
          timeout_seconds=30.0, lean_timeout_seconds=15.0) -> dict:
    """Check a proof without a model call and return a record plus check evidence."""
    outcome = NativeChecker(timeout_seconds=timeout_seconds,
                            lean_timeout_seconds=lean_timeout_seconds).check(request, proof)
    record = create_record(request, proof, title=title, tags=tags, metadata=metadata,
                           toolchain=outcome["toolchain"])
    if outcome["accepted"]:
        record["verification"] = {"status": "verified", "scope": outcome["scope"],
            "checked_at": outcome["checked_at"], "diagnostics": outcome["diagnostics"],
            "checker_fingerprint": outcome["toolchain"]["fingerprint"]}
    else:
        record["verification"]["diagnostics"] = outcome["diagnostics"]
    return {"record": record, "check": outcome}
