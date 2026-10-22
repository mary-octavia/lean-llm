"""Package an already compiled manuscript for author review; never submit it."""
from __future__ import annotations

import gzip
import hashlib
import io
from pathlib import Path
import tarfile


def main() -> None:
    root = Path(__file__).resolve().parent
    source, pdf = root / "main.tex", root / "main.pdf"
    if not pdf.is_file() or not pdf.read_bytes().startswith(b"%PDF-"):
        raise SystemExit("Compile main.tex to main.pdf before packaging")
    if pdf.stat().st_mtime < source.stat().st_mtime:
        raise SystemExit("The PDF predates main.tex; compile the current source first")
    data = source.read_bytes()
    archive_data = io.BytesIO()
    with tarfile.open(fileobj=archive_data, mode="w", format=tarfile.USTAR_FORMAT) as archive:
        info = tarfile.TarInfo("main.tex")
        info.size, info.mtime, info.mode = len(data), 0, 0o644
        archive.addfile(info, io.BytesIO(data))
    target = root / "arxiv" / "source.tar.gz"
    target.write_bytes(gzip.compress(archive_data.getvalue(), mtime=0))
    files = [source, pdf, target]
    (root / "SHA256SUMS").write_text("".join(
        f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.relative_to(root)}\n"
        for path in files
    ))
    print("Prepared local source archive and checksums; no submission performed.")


if __name__ == "__main__":
    main()
