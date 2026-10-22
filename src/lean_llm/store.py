"""Content-addressed SQLite proof vault with exact lookup and portable bundles."""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path, PurePosixPath
import sqlite3
import stat
import zipfile
from importlib.resources import files as package_files

from .records import canonical, context_key, create_record, digest, unverified, validate_record
from .assets import NAMES, bundled_files

BUNDLE_SCHEMA = "lean2llm.bundle/v1"
MAX_BUNDLE_BYTES = 16_000_000
MAX_BUNDLE_FILES = 32
BUNDLE_FILES = {"record.json", "source/Proof.lean", "_driver.py", "verify.py"} | {
    "checker/" + name for name in NAMES}


def safe_name(name: str) -> str:
    if not isinstance(name, str) or not name or "\\" in name or ":" in name or "\x00" in name:
        raise ValueError("Unsafe bundle path")
    path = PurePosixPath(name)
    if path.is_absolute() or any(part in (".", "..", "") for part in name.split("/")):
        raise ValueError("Unsafe bundle path")
    return name


class ProofStore:
    """A local vault. Search finds candidates; reuse always performs native checks."""
    def __init__(self, path: str | Path):
        self.path = Path(path).expanduser().resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.path, timeout=15)
        self.connection.row_factory = sqlite3.Row
        self.last_reuse_checks = 0
        self.connection.execute("PRAGMA journal_mode=WAL")
        self.connection.execute("PRAGMA foreign_keys=ON")
        self.connection.executescript("""
            CREATE TABLE IF NOT EXISTS proofs (
              id TEXT PRIMARY KEY, exact_key TEXT NOT NULL,
              content TEXT NOT NULL, verification TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS proofs_exact ON proofs(exact_key);
            CREATE VIRTUAL TABLE IF NOT EXISTS proof_search USING fts5(
              id UNINDEXED, title, statement, tags
            );
        """)

    def close(self):
        self.connection.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    def _put(self, record: dict, *, locally_checked=False) -> dict:
        record = validate_record(record)
        if not locally_checked:
            record["verification"] = unverified(reason="Stored or imported proof requires a local native recheck")
        content = record["content"]
        # Importing the same content never overwrites previous local evidence.
        existing = self.connection.execute("SELECT verification FROM proofs WHERE id=?", (record["id"],)).fetchone()
        if existing and not locally_checked:
            record["verification"] = json.loads(existing[0])
        with self.connection:
            self.connection.execute("INSERT OR REPLACE INTO proofs VALUES (?, ?, ?, ?)", (
                record["id"], context_key(content["request"], content["toolchain"]),
                canonical(content).decode(), canonical(record["verification"]).decode()))
            self.connection.execute("DELETE FROM proof_search WHERE id=?", (record["id"],))
            self.connection.execute("INSERT INTO proof_search VALUES (?, ?, ?, ?)", (
                record["id"], content["title"], content["request"]["statement"], " ".join(content["tags"])))
        return record

    def put(self, record: dict) -> dict:
        """Store an exchange record as unverified, regardless of imported status."""
        return self._put(record)

    def add(self, request: dict, proof: str, **metadata) -> dict:
        return self.put(create_record(request, proof, **metadata))

    @staticmethod
    def _row(row) -> dict:
        record = {"schema": "lean2llm.proof/v1", "id": row["id"],
                  "content": json.loads(row["content"]), "verification": json.loads(row["verification"])}
        return validate_record(record)

    def get(self, proof_id: str) -> dict:
        row = self.connection.execute("SELECT * FROM proofs WHERE id=?", (proof_id,)).fetchone()
        if row is None:
            raise KeyError(proof_id)
        return self._row(row)

    def search(self, query: str = "", *, limit=20) -> list[dict]:
        if not isinstance(query, str) or not isinstance(limit, int) or not 1 <= limit <= 100:
            raise ValueError("query must be a string and limit must be between 1 and 100")
        if not query.strip():
            rows = self.connection.execute("SELECT * FROM proofs ORDER BY rowid DESC LIMIT ?", (limit,))
        else:
            # Ordinary words are literal FTS tokens, rather than executable FTS syntax.
            match = " AND ".join('"' + word.replace('"', '""') + '"' for word in query.split())
            rows = self.connection.execute("""SELECT p.* FROM proof_search
                JOIN proofs p ON p.id=proof_search.id WHERE proof_search MATCH ?
                ORDER BY bm25(proof_search) LIMIT ?""", (match, limit))
        return [self._row(row) for row in rows]

    def lookup(self, request: dict, toolchain: dict) -> list[dict]:
        """Exact context/proposition/compiler matches. Results still require recheck."""
        rows = self.connection.execute("SELECT * FROM proofs WHERE exact_key=? ORDER BY rowid DESC",
                                       (context_key(request, toolchain),))
        return [self._row(row) for row in rows]

    def check(self, proof_id: str, **budgets) -> dict:
        from .checker import check
        record = self.get(proof_id)
        content = record["content"]
        outcome = check(content["request"], content["proof"], title=content["title"],
                        tags=content["tags"], metadata=content["metadata"], **budgets)
        # Resolving an unspecified or changed compiler creates a new immutable ID.
        outcome["record"] = self._put(outcome["record"], locally_checked=True)
        return outcome

    def reuse(self, request: dict, **budgets) -> dict | None:
        """Return the first exact match accepted by the current native checker."""
        from .checker import NativeChecker
        self.last_reuse_checks = 0
        identity = NativeChecker(**budgets).identity()
        for record in self.lookup(request, identity):
            outcome = self.check(record["id"], **budgets)
            self.last_reuse_checks += len(outcome["check"]["checks"])
            if outcome["check"]["accepted"]:
                return outcome["record"]
        return None

    def export_bundle(self, proof_id: str, destination: str | Path) -> Path:
        record = self.get(proof_id)
        files = {"record.json": canonical(record) + b"\n",
                 "source/Proof.lean": record["content"]["source"].encode("utf-8")}
        files.update({"checker/" + name: data for name, data in bundled_files().items()})
        driver = package_files("lean_llm").joinpath("core.py").read_text(encoding="utf-8")
        bootstrap = "from .assets import materialize, workspace_path\n\nROOT = workspace_path()"
        if bootstrap not in driver:
            raise RuntimeError("Packaged core bootstrap has changed; update standalone export")
        driver = driver.replace(bootstrap, "def materialize(_root):\n    pass\n\nROOT = Path(__file__).resolve().parent / 'checker'", 1)
        files["_driver.py"] = driver.encode()
        files["verify.py"] = package_files("lean_llm").joinpath("_assets/bundle_verify.py").read_bytes()
        manifest = {"schema": BUNDLE_SCHEMA, "proof_id": proof_id,
                    "files": {name: {"sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}
                              for name, data in files.items()}}
        destination = Path(destination).expanduser().resolve()
        destination.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("manifest.json", canonical(manifest) + b"\n")
            for name, data in files.items():
                archive.writestr(name, data)
        return destination

    def import_bundle(self, bundle: str | Path) -> dict:
        """Validate hashes and source; keep imported proof evidence untrusted."""
        with zipfile.ZipFile(bundle) as archive:
            infos = archive.infolist()
            names = [safe_name(info.filename) for info in infos]
            if len(infos) > MAX_BUNDLE_FILES or len(names) != len(set(names)):
                raise ValueError("Duplicate or excessive bundle entries")
            if sum(info.file_size for info in infos) > MAX_BUNDLE_BYTES:
                raise ValueError("Bundle exceeds expanded size budget")
            for info in infos:
                mode = info.external_attr >> 16
                if stat.S_ISLNK(mode) or info.is_dir():
                    raise ValueError("Bundle entries must be ordinary files")
            if "manifest.json" not in names:
                raise ValueError("Bundle has no manifest")
            manifest = json.loads(archive.read("manifest.json"))
            if manifest.get("schema") != BUNDLE_SCHEMA or not isinstance(manifest.get("files"), dict):
                raise ValueError("Unsupported bundle manifest")
            if set(manifest["files"]) != BUNDLE_FILES:
                raise ValueError("Unexpected proof bundle files")
            if set(names) != set(manifest["files"]) | {"manifest.json"}:
                raise ValueError("Bundle files do not match manifest")
            data = {}
            for name, expected in manifest["files"].items():
                safe_name(name)
                data[name] = archive.read(name)
                if not isinstance(expected, dict) or expected != {
                        "sha256": hashlib.sha256(data[name]).hexdigest(), "bytes": len(data[name])}:
                    raise ValueError("Bundle checksum mismatch: " + name)
            record = validate_record(json.loads(data["record.json"]))
            if record["id"] != manifest.get("proof_id"):
                raise ValueError("Manifest proof ID mismatch")
            if record["content"]["source"].encode() != data["source/Proof.lean"]:
                raise ValueError("Bundled Lean source differs from proof record")
            return self.put(record)
