"""A deterministic, local proof-store round trip. No model calls."""
import json
from pathlib import Path

from lean_llm import ProofStore, solve

root = Path(__file__).resolve().parent
request = json.loads((root / "request.json").read_text())
with ProofStore("proofs.sqlite3") as vault:
    result = solve(request, proposer=lambda _: {"proof": (root / "proof.txt").read_text()},
                   store=vault, max_attempts=1, tags=["nat", "equality"])
    print(json.dumps(result, indent=2, ensure_ascii=False))
    if result["status"] == "proved":
        print(vault.export_bundle(result["proof_id"], "natural-identity.proof.zip"))
