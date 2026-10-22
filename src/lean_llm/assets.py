"""Copy the packaged, pinned Lean bridge into a writable build directory."""
from __future__ import annotations

import hashlib
import os
import tempfile
from importlib.resources import files
from pathlib import Path

NAMES = ("Llm.lean", "lean-toolchain", "lakefile.toml", "lake-manifest.json")


def bundled_files() -> dict[str, bytes]:
    root = files("lean_llm").joinpath("_assets")
    return {name: root.joinpath(name).read_bytes() for name in NAMES}


def workspace_path() -> Path:
    digest = hashlib.sha256()
    for name, content in bundled_files().items():
        digest.update(name.encode() + b"\0" + content)
    base = Path(os.environ.get("LEAN_LLM_HOME", Path.home() / ".cache" / "lean2llm"))
    return base.expanduser().resolve() / "native" / digest.hexdigest()[:24]


def materialize(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    for name, data in bundled_files().items():
        target = root / name
        if target.exists() and target.read_bytes() == data:
            continue
        # A corrupt or altered local build input is restored before compilation.
        with tempfile.NamedTemporaryFile(dir=root, prefix=name + ".", delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(data)
        try:
            temporary.replace(target)
        finally:
            temporary.unlink(missing_ok=True)


def pin() -> str:
    return bundled_files()["lean-toolchain"].decode().strip()
