"""Versioned proof records; only immutable content contributes to the ID."""
from __future__ import annotations

from datetime import datetime, timezone
import copy
import hashlib
import json

from .assets import pin

SCHEMA = "lean2llm.proof/v1"
MAX_RECORD_BYTES = 2_000_000
MAX_SAFE_INTEGER = 2**53 - 1


def _json_value(value) -> None:
    """Use the lossless JSON subset shared by Python and browser JavaScript.

    Fractional measurements are strings. This avoids Python/ECMAScript float
    formatting and integer precision changing the content ID during exchange.
    """
    if value is None or isinstance(value, bool):
        return
    if isinstance(value, str):
        try:
            value.encode("utf-8")
        except UnicodeEncodeError as error:
            raise ValueError("Proof records require valid Unicode strings") from error
        return
    if isinstance(value, int):
        if abs(value) > MAX_SAFE_INTEGER:
            raise ValueError("Proof JSON numbers must be safe integers; encode larger or fractional values as strings")
        return
    if isinstance(value, list):
        for item in value:
            _json_value(item)
        return
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise ValueError("Proof JSON object keys must be strings")
            _json_value(key)
            _json_value(item)
        return
    raise ValueError("Proof JSON numbers must be safe integers; encode larger or fractional values as strings")


def canonical(value) -> bytes:
    _json_value(value)
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                      allow_nan=False).encode("utf-8")


def digest(value) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def unverified(*, reason="Awaiting a local native check") -> dict:
    return {"status": "unverified", "scope": "none", "checked_at": None,
            "diagnostics": reason, "checker_fingerprint": None}


def create_record(request: dict, proof: str, *, title: str | None = None,
                  tags=(), toolchain: dict | None = None, metadata: dict | None = None) -> dict:
    from .core import _request, _source, MAX_PROOF
    request = _request(request)
    if not isinstance(proof, str) or not proof.strip() or len(proof.encode()) > MAX_PROOF:
        raise ValueError("A nonempty tactic sequence within the proof size budget is required")
    if not isinstance(title, (str, type(None))):
        raise ValueError("title must be a string")
    if isinstance(tags, str):
        raise ValueError("tags must be a sequence of strings")
    tags = list(tags)
    if not all(isinstance(tag, str) for tag in tags):
        raise ValueError("tags must be a sequence of strings")
    if metadata is not None and not isinstance(metadata, dict):
        raise ValueError("metadata must be an object")
    content = {"title": title or request["name"], "tags": sorted(set(tags)),
               "request": request, "proof": proof, "source": _source(request, proof),
               "backend": "lean-tactic", "toolchain": toolchain or {
                   "pin": pin(), "fingerprint": "unresolved"}, "metadata": metadata or {}}
    record = {"schema": SCHEMA, "id": digest(content), "content": content,
              "verification": unverified()}
    return validate_record(record)


def validate_record(record: dict) -> dict:
    if not isinstance(record, dict) or record.get("schema") != SCHEMA:
        raise ValueError("Unsupported proof record schema")
    if len(canonical(record)) > MAX_RECORD_BYTES:
        raise ValueError("Proof record exceeds size budget")
    content = record.get("content")
    if not isinstance(content, dict) or record.get("id") != digest(content):
        raise ValueError("Proof content ID does not match its SHA256 digest")
    expected = {"title", "tags", "request", "proof", "source", "backend", "toolchain", "metadata"}
    if set(content) != expected or content["backend"] != "lean-tactic":
        raise ValueError("Unsupported proof content fields or backend")
    from .core import _request, _source, MAX_PROOF
    request = _request(content["request"])
    if request != content["request"]:
        raise ValueError("Request fields must be name, context, and statement")
    if not isinstance(content["proof"], str) or not content["proof"].strip():
        raise ValueError("Proof must be a nonempty string")
    if len(content["proof"].encode()) > MAX_PROOF:
        raise ValueError("Proof exceeds size budget")
    if content["source"] != _source(request, content["proof"]):
        raise ValueError("Source does not match the fixed request and proof")
    if not isinstance(content["title"], str) or not isinstance(content["metadata"], dict):
        raise ValueError("Invalid title or metadata")
    if not isinstance(content["tags"], list) or not all(isinstance(v, str) for v in content["tags"]):
        raise ValueError("tags must be a list of strings")
    tc = content["toolchain"]
    if not isinstance(tc, dict) or set(tc) != {"pin", "fingerprint"} or not all(
            isinstance(value, str) and 0 < len(value) <= 256 for value in tc.values()):
        raise ValueError("A toolchain pin and fingerprint are required")
    return copy.deepcopy(record)


def context_key(request: dict, toolchain: dict) -> str:
    # Names are presentation metadata. Context, exact proposition, and compiler
    # identity determine eligibility; every hit must still pass the native checker.
    from .core import _request
    request = _request(request)
    return digest({"context": request["context"], "statement": request["statement"],
                   "toolchain": toolchain})
