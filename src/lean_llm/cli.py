"""Command line entry point; no model call is implicit."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys

from . import ProofStore, __version__, solve
from .core import CodexProposer
from .records import create_record


def _json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def main(argv=None):
    parser = argparse.ArgumentParser(prog="lean2llm", description=__doc__)
    parser.add_argument("--version", action="version", version=__version__)
    parser.add_argument("--db", type=Path, default=Path(os.environ.get(
        "LEAN_LLM_STORE", Path.home() / ".local/share/lean2llm/proofs.sqlite3")))
    commands = parser.add_subparsers(dest="command", required=True)
    add = commands.add_parser("store", help="Store a request and tactic file as unverified")
    add.add_argument("request", type=Path)
    add.add_argument("--proof", type=Path, required=True)
    add.add_argument("--title")
    add.add_argument("--tag", action="append", default=[])
    search = commands.add_parser("search", help="Search proof titles, statements, and tags")
    search.add_argument("query", nargs="?", default="")
    search.add_argument("--limit", type=int, default=20)
    show = commands.add_parser("show", help="Read a proof by its full SHA256 content ID")
    show.add_argument("id")
    export = commands.add_parser("export", help="Export a hashed proof bundle")
    export.add_argument("id")
    export.add_argument("destination", type=Path)
    imp = commands.add_parser("import", help="Import a bundle, requiring a local recheck")
    imp.add_argument("bundle", type=Path)
    check = commands.add_parser("check", help="Recheck a stored proof with pinned native Lean")
    check.add_argument("id")
    check.add_argument("--timeout", type=float, default=30)
    check.add_argument("--lean-timeout", type=float, default=15)
    solving = commands.add_parser("solve", help="Run the bounded proof loop and save accepted proofs")
    solving.add_argument("request", type=Path)
    choice = solving.add_mutually_exclusive_group(required=True)
    choice.add_argument("--proof", type=Path, help="Use a local tactic file; zero model calls")
    choice.add_argument("--codex", action="store_true", help="Explicitly use the signed-in Codex CLI")
    choice.add_argument("--cache-only", action="store_true", help="Native-check exact stored matches")
    solving.add_argument("--attempts", type=int, default=3)
    solving.add_argument("--timeout", type=float, default=60)
    solving.add_argument("--lean-timeout", type=float, default=15)
    args = parser.parse_args(argv)
    try:
        with ProofStore(args.db) as vault:
            if args.command == "store":
                result = vault.add(_json(args.request), args.proof.read_text(),
                                   title=args.title, tags=args.tag)
            elif args.command == "search":
                result = vault.search(args.query, limit=args.limit)
            elif args.command == "show":
                result = vault.get(args.id)
            elif args.command == "export":
                result = {"bundle": str(vault.export_bundle(args.id, args.destination))}
            elif args.command == "import":
                result = vault.import_bundle(args.bundle)
            elif args.command == "check":
                result = vault.check(args.id, timeout_seconds=args.timeout,
                                     lean_timeout_seconds=args.lean_timeout)
                print(json.dumps(result, indent=2, ensure_ascii=False))
                return 0 if result["check"]["accepted"] else 2
            elif args.command == "solve":
                proposer = (CodexProposer(timeout_seconds=args.timeout) if args.codex else
                            lambda _: {"proof": args.proof.read_text() if args.proof else ""})
                result = solve(_json(args.request), proposer=proposer, store=vault,
                               max_attempts=0 if args.cache_only else args.attempts,
                               timeout_seconds=args.timeout, lean_timeout_seconds=args.lean_timeout)
                print(json.dumps(result, indent=2, ensure_ascii=False))
                return 0 if result["status"] == "proved" else 2
            print(json.dumps(result, indent=2, ensure_ascii=False))
            return 0
    except (OSError, ValueError, KeyError, RuntimeError) as error:
        print(json.dumps({"error": str(error)}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
