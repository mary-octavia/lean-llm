#!/usr/bin/env python3
"""Bounded LLM proposals, native Lean checking, and rechecked proof reuse.

The request fixes the context and proposition. The proposer controls only a
tactic sequence. A cache entry is evidence to recheck, never an axiom.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import resource
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import tomllib
from typing import Callable

ROOT = Path(__file__).resolve().parent
# Resolve lazily so importing this module and displaying --help need no toolchain.
TOOLCHAIN: Path | None = None
LEAN: Path | None = None
LAKE: Path | None = None
LIB = ROOT / ".lake/build/lib/lean"
AUDIT = "LLM_AUDIT_OK LlmGenerated.target"
MAX_SOURCE = 64_000
MAX_PROOF = 32_000
MAX_DIAGNOSTICS = 12_000
BLOCKED = re.compile(
    r"(?<![\w'])" + r"(?:sorry|admit|axiom|unsafe|native_decide|run_tac|run_elab|"
    r"elab|macro|syntax|initialize|builtin_initialize|import|set_option|"
    r"attribute|local|scoped|open|namespace|end|export|audit_llm|llm|llm_theorem|"
    r"implemented_by|extern|compiler|IO|Lean)(?![\w'])"
)


def _run(args, *, cwd, env=None, timeout=20.0, input_text=None, limit_files=True):
    """Bounded capture and process-group termination; never execute a shell."""
    started = time.monotonic()
    def limits():
        resource.setrlimit(resource.RLIMIT_FSIZE, (2_000_000, 2_000_000))
    with tempfile.TemporaryFile() as output:
        process = subprocess.Popen(
            [str(a) for a in args], cwd=str(cwd), env=env,
            stdin=subprocess.PIPE if input_text is not None else subprocess.DEVNULL,
            stdout=output, stderr=subprocess.STDOUT, start_new_session=True,
            preexec_fn=limits if limit_files else None,
        )
        timed_out = False
        try:
            process.communicate(input_text.encode() if input_text is not None else None,
                                timeout=max(0.01, timeout))
        except subprocess.TimeoutExpired:
            timed_out = True
            os.killpg(process.pid, signal.SIGKILL)
            process.communicate()
        output.seek(0)
        text = output.read(MAX_DIAGNOSTICS).decode("utf-8", errors="replace")
    return {"returncode": process.returncode, "diagnostics": text,
            "timed_out": timed_out, "seconds": time.monotonic() - started}


def _executable(path: Path, label: str) -> Path:
    path = path.expanduser().resolve()
    if not path.is_file() or not os.access(path, os.X_OK):
        raise RuntimeError(f"{label} is not an executable file: {path}")
    return path


def _pinned_version() -> tuple[str, str]:
    pin = (ROOT / "lean-toolchain").read_text(encoding="utf-8").strip()
    match = re.fullmatch(r"leanprover/lean4:v([0-9]+\.[0-9]+\.[0-9]+(?:-[A-Za-z0-9.+-]+)?)", pin)
    if not match:
        raise RuntimeError(f"Unsupported lean-toolchain pin: {pin!r}; expected leanprover/lean4:vVERSION")
    return pin, match.group(1)


def _validate_toolchain(root: Path, expected: str) -> Path:
    root = root.expanduser().resolve()
    lean = _executable(root / "bin/lean", "Lean")
    _executable(root / "bin/lake", "Lake")
    result = _run([lean, "--version"], cwd=ROOT, timeout=10, limit_files=False)
    match = re.search(r"\bLean \(version ([^,\s)]+)", result["diagnostics"])
    if result["returncode"] != 0 or not match:
        raise RuntimeError(f"Cannot determine Lean version from {lean}: {result['diagnostics'].strip()}")
    if match.group(1) != expected:
        raise RuntimeError(f"Lean version mismatch: lean-toolchain requires {expected}, "
                           f"but {lean} reports {match.group(1)}")
    return root


def _discover_toolchain() -> Path:
    """Find the real pinned toolchain, never a project-dependent elan shim."""
    pin, expected = _pinned_version()
    override = os.environ.get("LEAN_LLM_TOOLCHAIN", "").strip()
    if override:
        # An explicit override is authoritative: a typo must not select another compiler.
        return _validate_toolchain(Path(override), expected)

    failures = []
    candidates = []
    elan = shutil.which("elan")
    if elan:
        result = _run([elan, "which", "lean"], cwd=ROOT, timeout=10, limit_files=False)
        if result["returncode"] == 0 and result["diagnostics"].strip():
            candidates.append(Path(result["diagnostics"].strip()))
        else:
            failures.append("elan: " + result["diagnostics"].strip())
    path_lean = shutil.which("lean")
    if path_lean:
        candidates.append(Path(path_lean))
    for candidate in candidates:
        try:
            executable = _executable(candidate, "Lean")
            result = _run([executable, "--print-prefix"], cwd=ROOT, timeout=10,
                          limit_files=False)
            if result["returncode"] != 0 or not result["diagnostics"].strip():
                raise RuntimeError(f"Cannot resolve Lean prefix: {result['diagnostics'].strip()}")
            return _validate_toolchain(Path(result["diagnostics"].strip()), expected)
        except (OSError, RuntimeError, subprocess.SubprocessError) as error:
            failures.append(str(error))
    details = (" Details: " + "; ".join(failures)) if failures else ""
    raise RuntimeError(f"No usable Lean {expected} toolchain found. Install {pin} with elan "
                       "and put elan on PATH, or set LEAN_LLM_TOOLCHAIN to its toolchain root."
                       + details)


def _configure_toolchain():
    global TOOLCHAIN, LEAN, LAKE
    if TOOLCHAIN is None:
        TOOLCHAIN = _discover_toolchain()
        LEAN = TOOLCHAIN / "bin/lean"
        LAKE = TOOLCHAIN / "bin/lake"


def _discover_codex() -> Path:
    """Find a Codex executable without running it or changing authentication."""
    override = os.environ.get("LEAN_LLM_CODEX", "").strip()
    if override:
        return _executable(Path(override), "LEAN_LLM_CODEX")
    binary = shutil.which("codex")
    if binary:
        return _executable(Path(binary), "Codex")
    if sys.platform == "darwin":
        for app in ("Codex.app", "ChatGPT.app"):
            binary = Path("/Applications") / app / "Contents/Resources/codex"
            if binary.is_file() and os.access(binary, os.X_OK):
                return binary.resolve()
    raise RuntimeError("Codex executable not found; put codex on PATH or set LEAN_LLM_CODEX")


def ensure_module():
    _configure_toolchain()
    source = ROOT / "Llm.lean"
    artifact = LIB / "Llm.olean"
    if not artifact.exists() or artifact.stat().st_mtime < source.stat().st_mtime:
        env = dict(os.environ)
        env["PATH"] = str(TOOLCHAIN / "bin") + os.pathsep + env.get("PATH", "")
        result = _run([LAKE, "build", "Llm"], cwd=ROOT, env=env, timeout=60)
        if result["returncode"] != 0:
            raise RuntimeError("Building the trusted bridge failed: " + result["diagnostics"])


def toolchain_fingerprint() -> str:
    """Pinned executable identity, native bridge, and Python checking policy."""
    _configure_toolchain()
    digest = hashlib.sha256()
    version = subprocess.run([str(LEAN), "--version"], capture_output=True,
                             text=True, timeout=5, check=True).stdout
    digest.update(version.encode())
    for path in (LEAN, ROOT / "Llm.lean", LIB / "Llm.olean", Path(__file__)):
        digest.update(str(path).encode())
        if path.exists():
            digest.update(path.read_bytes())
    return digest.hexdigest()


def _request(request: dict) -> dict:
    if not isinstance(request, dict):
        raise ValueError("Request must be an object")
    result = {"name": request.get("name", "proof"),
              "context": request.get("context", ""),
              "statement": request.get("statement", "")}
    if not all(isinstance(v, str) for v in result.values()):
        raise ValueError("name, context, and statement must be strings")
    if not result["statement"].strip():
        raise ValueError("A fixed statement is required")
    if sum(len(v.encode()) for v in result.values()) > MAX_SOURCE:
        raise ValueError("Request exceeds source budget")
    for field in ("context", "statement"):
        match = BLOCKED.search(result[field])
        if match:
            raise ValueError(f"Disallowed {field} token: {match.group()}")
    return result


def request_key(request: dict) -> str:
    payload = {"request": _request(request), "toolchain": toolchain_fingerprint()}
    return hashlib.sha256(json.dumps(payload, sort_keys=True,
                                    ensure_ascii=False).encode()).hexdigest()


def _source(request, proof=None):
    body = "llm" if proof is None else proof
    indented = "\n".join("  " + line for line in body.splitlines())
    declaration = ("llm_theorem target\n" if proof is None else
                   "theorem target :\n  " + request["statement"] + " := by\n" + indented + "\n")
    return ("import Llm\n\nnamespace LlmGenerated\n\n" + request["context"] +
            "\n\n" + declaration + "\naudit_llm target\n\nend LlmGenerated\n")


def _sandbox(scratch: Path):
    if sys.platform != "darwin" or not Path("/usr/bin/sandbox-exec").exists():
        raise RuntimeError("This prototype requires macOS sandbox-exec; no unsandboxed fallback")
    _configure_toolchain()
    read_dirs = [TOOLCHAIN.resolve(), LIB.resolve(), scratch.resolve(),
                 Path("/System"), Path("/usr/lib"), Path("/Library/Apple")]
    reads = "\n".join(f"  (subpath {json.dumps(str(p))})" for p in read_dirs)
    return ("(version 1)\n(deny default)\n(allow process-exec)\n"
            "(allow sysctl-read)\n(allow mach-lookup)\n(allow file-read-metadata)\n"
            '(allow file-read-data (literal "/") (literal "/dev/urandom"))\n'
            f"(allow file-read*\n{reads}\n  (literal \"/dev/null\"))\n")


def _check(request, proof, *, timeout, explicit=False):
    if proof is not None:
        if not isinstance(proof, str) or not proof.strip():
            return {"accepted": False, "diagnostics": "Empty or non-string proof", "seconds": 0}
        if len(proof.encode()) > MAX_PROOF:
            return {"accepted": False, "diagnostics": "Proof exceeds size budget", "seconds": 0}
        bad = BLOCKED.search(proof)
        if bad or "```" in proof:
            token = bad.group() if bad else "Markdown code fence"
            return {"accepted": False, "diagnostics": "Disallowed proof token: " + token, "seconds": 0}
    with tempfile.TemporaryDirectory(prefix="lean-llm-check-") as tmp:
        scratch = Path(tmp).resolve()
        goal = scratch / "Goal.lean"
        goal.write_text(_source(request, proof if explicit else None))
        policy = scratch / "sandbox.sb"
        policy.write_text(_sandbox(scratch))
        env = {"PATH": str(TOOLCHAIN / "bin") + ":/usr/bin:/bin",
               "LEAN_PATH": str(LIB), "LANG": "en_US.UTF-8", "HOME": str(scratch),
               "TMPDIR": str(scratch)}
        statement_file = scratch / "statement.txt"
        statement_file.write_text(request["statement"])
        env["LLM_STATEMENT_FILE"] = str(statement_file)
        if proof is not None and not explicit:
            candidate = scratch / "proposal.txt"
            candidate.write_text(proof)
            env["LLM_PROOF_FILE"] = str(candidate)
        result = _run(["/usr/bin/sandbox-exec", "-f", policy, LEAN,
                       "-M", "2048", "-j", "1", goal],
                      cwd=scratch, env=env, timeout=timeout)
        result["accepted"] = result["returncode"] == 0 and AUDIT in result["diagnostics"]
        if result["returncode"] != 0 and not result["diagnostics"].strip():
            result["diagnostics"] = f"Lean exited {result['returncode']} without diagnostics"
        if result["timed_out"]:
            result["diagnostics"] += "\nLean timed out; no proof accepted."
        result["resource_failure"] = result["timed_out"] or any(
            text in result["diagnostics"].lower() for text in (
                "excessive memory consumption", "out of memory", "stack overflow"))
        return result


def solve(request: dict, *, cache_dir: Path, proposer: Callable,
          max_attempts=3, timeout_seconds=60.0, lean_timeout_seconds=15.0) -> dict:
    started = time.monotonic()
    result = {"status": "unknown", "cache_hit": False, "attempts": [],
              "proof": None, "verified_file": None, "reason": "",
              "metrics": {"model_calls": 0, "proposer_calls": 0, "lean_checks": 0}}
    def finish(reason):
        result["reason"] = reason
        result["metrics"]["seconds"] = time.monotonic() - started
        return result
    try:
        request = _request(request)
        if max_attempts < 0 or timeout_seconds <= 0 or lean_timeout_seconds <= 0:
            raise ValueError("Invalid attempt or time budget")
        ensure_module()
        key = request_key(request)
        entry = Path(cache_dir).resolve() / key
        result["key"] = key
        def check(proof, explicit=False):
            remaining = timeout_seconds - (time.monotonic() - started)
            if remaining <= 0:
                return {"accepted": False, "diagnostics": "Total time budget exhausted", "seconds": 0}
            result["metrics"]["lean_checks"] += 1
            return _check(request, proof, timeout=min(remaining, lean_timeout_seconds), explicit=explicit)
        def accept(proof, cache_hit):
            # Check the exact exported source too; indentation/context cannot alter its meaning.
            exported = check(proof, explicit=True)
            if not exported["accepted"]:
                return exported
            entry.mkdir(parents=True, exist_ok=True)
            path = entry / "Verified.lean"
            path.write_text(_source(request, proof))
            (entry / "proof.json").write_text(json.dumps(
                {"key": key, "request": request, "proof": proof}, indent=2, ensure_ascii=False) + "\n")
            result.update(status="proved", proof=proof, cache_hit=cache_hit,
                          verified_file=str(path))
            return exported
        if (entry / "proof.json").is_file():
            try:
                if (entry / "proof.json").stat().st_size > MAX_SOURCE + MAX_PROOF + 10_000:
                    raise ValueError("Cache record exceeds size budget")
                record = json.loads((entry / "proof.json").read_text())
                if not isinstance(record, dict):
                    raise ValueError("Cache record is not an object")
                cached = record.get("proof")
                if record.get("key") == key and record.get("request") == request and check(cached)["accepted"]:
                    if accept(cached, True)["accepted"]:
                        return finish("Cached proof rechecked by Lean")
            except (ValueError, OSError, TypeError):
                pass
        initial = check(None)
        if initial.get("resource_failure"):
            return finish("Lean resource limit reached while reading the goal; no model call")
        goal = ""
        for line in initial["diagnostics"].splitlines():
            if "LLM_GOAL_REQUEST " in line:
                try:
                    goal = json.loads(line.split("LLM_GOAL_REQUEST ", 1)[1])["goal"]
                except (ValueError, KeyError):
                    pass
        if not goal:
            return finish("Unable to elaborate fixed goal: " + initial["diagnostics"])
        diagnostics, previous = "", ""
        for attempt in range(1, max_attempts + 1):
            remaining = timeout_seconds - (time.monotonic() - started)
            if remaining <= 0:
                return finish("Total time budget exhausted")
            payload = {**request, "goal": goal, "diagnostics": diagnostics,
                       "attempt": attempt, "previous_proof": previous,
                       "remaining_seconds": remaining}
            result["metrics"]["proposer_calls"] += 1
            if isinstance(proposer, CodexProposer):
                result["metrics"]["model_calls"] += 1
            try:
                proposal = proposer(payload)
                proof = proposal.get("proof", "") if isinstance(proposal, dict) else ""
            except Exception as error:
                return finish("Proposer failed: " + str(error)[:2000])
            checked = check(proof)
            if checked["accepted"]:
                checked = accept(proof, False)
            result["attempts"].append({"attempt": attempt, "proof": proof,
                                       "accepted": checked["accepted"],
                                       "diagnostics": checked["diagnostics"]})
            if checked["accepted"]:
                return finish("Proof checked by Lean and axiom audit")
            if checked.get("resource_failure"):
                return finish("Lean resource limit reached; no further model call")
            diagnostics = checked["diagnostics"]
            previous = proof if isinstance(proof, str) else ""
        return finish("No verified proof within attempt budget")
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        return finish(str(error))


class CodexProposer:
    """Text-only Codex exec using existing ChatGPT auth, with a wall-clock limit."""
    def __init__(self, *, timeout_seconds=90.0):
        self.timeout_seconds = timeout_seconds
        self.binary = _discover_codex()
        auth_env = dict(os.environ)
        for name in ("OPENAI_API_KEY", "CODEX_API_KEY"):
            auth_env.pop(name, None)
        auth = _run([self.binary, "login", "status"], cwd=ROOT, env=auth_env,
                    timeout=10, limit_files=False)
        if auth["returncode"] != 0 or "logged in using chatgpt" not in auth["diagnostics"].lower():
            raise RuntimeError("This adapter requires the existing Codex ChatGPT sign-in")
        config_path = Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex"))) / "config.toml"
        config = tomllib.loads(config_path.read_text()) if config_path.exists() else {}
        # Preserve the configured model; exclude plugins, hooks, MCPs, and unrelated settings.
        self.model = config.get("model")

    def __call__(self, payload):
        with tempfile.TemporaryDirectory(prefix="lean-llm-proposer-") as tmp:
            scratch = Path(tmp)
            output = scratch / "answer.json"
            schema = scratch / "schema.json"
            schema.write_text(json.dumps({"type": "object", "properties": {
                "proof": {"type": "string"}}, "required": ["proof"], "additionalProperties": False}))
            prompt = (
                "You propose a Lean 4.33.1 proof. Return JSON with only a proof field containing "
                "a tactic sequence, WITHOUT leading by, Markdown fences, theorem declarations, or prose. "
                "Only Lean/Std are imported; mathlib is unavailable. The context and statement are fixed. "
                "You may use induction and local have lemmas. Never use sorry, admit, custom axioms, "
                "native_decide, metaprogramming, IO, tools, or edits. Produce a kernel-checkable proof. "
                "If previous_proof failed, use the exact Lean diagnostics to repair it. "
                "If you cannot find a proof, return an empty string.\n\n" +
                json.dumps(payload, ensure_ascii=False))
            args = [self.binary, "exec", "--ignore-user-config", "--ignore-rules",
                    "--ephemeral", "--skip-git-repo-check", "--sandbox", "read-only",
                    "--color", "never", "-C", scratch, "--output-schema", schema,
                    "--output-last-message", output, "-c", 'model_reasoning_effort="low"',
                    "-c", 'web_search="disabled"', "-c", 'approval_policy="never"']
            if self.model:
                args.extend(["--model", self.model])
            for feature in ("shell_tool", "unified_exec", "apps", "plugins", "hooks",
                            "multi_agent", "browser_use", "computer_use", "image_generation",
                            "code_mode_host", "tool_suggest", "workspace_dependencies"):
                args.extend(["--disable", feature])
            args.append("-")
            env = dict(os.environ)
            for name in ("OPENAI_API_KEY", "CODEX_API_KEY"):
                env.pop(name, None)
            run = _run(args, cwd=scratch, env=env,
                       timeout=min(self.timeout_seconds, payload["remaining_seconds"]),
                       input_text=prompt, limit_files=False)
            if run["timed_out"]:
                raise RuntimeError("Codex proposal timed out")
            if run["returncode"] != 0 or not output.exists():
                # CLI errors may include configuration paths; do not dump the full child log.
                raise RuntimeError(f"Codex exited {run['returncode']} without a proposal")
            return json.loads(output.read_text())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("request", type=Path, help="JSON with name, context, statement")
    parser.add_argument("--cache-dir", type=Path, default=ROOT / "cache")
    parser.add_argument("--max-attempts", type=int, default=3)
    parser.add_argument("--timeout", type=float, default=120)
    parser.add_argument("--lean-timeout", type=float, default=15)
    parser.add_argument("--proof-file", type=Path, help="Check a local tactic file, with no model call")
    parser.add_argument("--cache-only", action="store_true", help="Only replay a cache entry; never call a model")
    args = parser.parse_args()
    request = json.loads(args.request.read_text())
    if args.proof_file:
        proposer = lambda _: {"proof": args.proof_file.read_text()}
    elif args.cache_only:
        proposer = lambda _: {"proof": ""}
    else:
        proposer = CodexProposer(timeout_seconds=args.timeout)
    result = solve(request, cache_dir=args.cache_dir, proposer=proposer,
                   max_attempts=0 if args.cache_only else args.max_attempts,
                   timeout_seconds=args.timeout, lean_timeout_seconds=args.lean_timeout)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if result["status"] == "proved" else 2


if __name__ == "__main__":
    raise SystemExit(main())
