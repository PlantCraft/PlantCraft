"""Fetch the International Stiction Database (ISDB) into ``oracles/isdb/`` at a pinned version.

Source: the data sets of Jelali and Huang (2010), *Detection and Diagnosis of Stiction in Control
Loops*, Springer, https://doi.org/10.1007/978-1-84882-775-2, published by the editors on the
book's page at the University of Alberta ("Data sets used in the book", for teaching and research
use). The archive is never committed (``/oracles/`` is gitignored); a new archive is a new pin.

    python tests/oracles/fetch_isdb.py            # download, check sha256, unpack, convert
    python tests/oracles/fetch_isdb.py --archive ISDB.zip   # same, from a copy you downloaded

Converting the MATLAB file needs SciPy (``pip install scipy``, fetch time only; the oracle test
itself reads the CSV files this writes). Each loop becomes ``oracles/isdb/loops/<name>.csv``
(columns ``pv``, ``op`` and, when present, ``sp``) plus a row in ``oracles/isdb/loops.json``
with its sampling time and the text fields the database stores beside the data.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import urllib.request
import zipfile
from pathlib import Path

URL = "https://sites.ualberta.ca/~bhuang/Stiction-Book/ISDB.zip"
# TODO(G3): pin on the first download from a network that reaches the host (it was blocked by
# this project's egress policy on 2026-10-19). Until then the script refuses to unpack unless
# --accept-unpinned is given, and prints the sha256 to pin here.
SHA256: str | None = None

ROOT = Path(__file__).resolve().parents[2]
TARGET = ROOT / "oracles" / "isdb"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def download(target: Path) -> Path:
    archive = target / "ISDB.zip"
    if not archive.exists():
        target.mkdir(parents=True, exist_ok=True)
        print(f"Downloading {URL}")
        with urllib.request.urlopen(URL, timeout=120) as response:  # noqa: S310 (pinned URL)
            archive.write_bytes(response.read())
    return archive


def _loops(node, name: str):
    """Yield (name, fields) for every MATLAB struct that holds a PV and an OP series."""

    fields = getattr(node, "_fieldnames", None)
    if fields is None:
        return
    lower = {field.lower(): field for field in fields}
    if "pv" in lower and "op" in lower:
        yield name, {field: getattr(node, field) for field in fields}
        return
    for field in fields:
        child = getattr(node, field)
        for item in child if isinstance(child, list) else [child]:
            yield from _loops(item, f"{name}.{field}" if name else field)


def convert(archive: Path, target: Path) -> int:
    try:
        import numpy as np
        from scipy.io import loadmat
    except ImportError:
        sys.exit("Converting the ISDB needs SciPy at fetch time: pip install scipy")

    unpacked = target / "raw"
    with zipfile.ZipFile(archive) as bundle:
        for member in bundle.namelist():
            destination = (unpacked / member).resolve()
            if not destination.is_relative_to(unpacked.resolve()):
                sys.exit(f"Refusing an archive member outside the target: {member}")
        bundle.extractall(unpacked)
    loops_dir = target / "loops"
    loops_dir.mkdir(parents=True, exist_ok=True)
    manifest = []
    for mat in sorted(unpacked.rglob("*.mat")):
        data = loadmat(mat, squeeze_me=True, struct_as_record=False)
        for key, value in data.items():
            if key.startswith("__"):
                continue
            for name, fields in _loops(value, key):
                lower = {field.lower(): field for field in fields}
                columns = {
                    role: np.asarray(fields[lower[role]], dtype=float).ravel()
                    for role in ("pv", "op", "sp")
                    if role in lower and np.size(fields[lower[role]]) > 1
                }
                length = min(len(values) for values in columns.values())
                safe = name.replace("/", "_")
                with (loops_dir / f"{safe}.csv").open("w", encoding="utf-8") as handle:
                    handle.write(",".join(columns) + "\n")
                    for i in range(length):
                        handle.write(",".join(repr(float(columns[c][i])) for c in columns) + "\n")
                text = {
                    field: str(fields[field]) for field in fields if isinstance(fields[field], str)
                }
                ts = fields.get(lower.get("ts", ""), None)
                manifest.append(
                    {
                        "loop": safe,
                        "source_file": mat.name,
                        "sample_seconds": float(ts) if np.size(ts) == 1 else None,
                        "samples": int(length),
                        "text": text,
                    }
                )
    (target / "loops.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return len(manifest)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--archive", type=Path, help="a copy of ISDB.zip already downloaded")
    parser.add_argument("--accept-unpinned", action="store_true", help="unpack before pinning")
    args = parser.parse_args(argv)
    archive = args.archive or download(TARGET)
    found = sha256(archive)
    if SHA256 is None:
        print(f"sha256 {found} (not pinned yet: set SHA256 in {Path(__file__).name})")
        if not args.accept_unpinned:
            return 2
    elif found != SHA256:
        print(f"sha256 mismatch: expected {SHA256}, got {found}", file=sys.stderr)
        return 1
    count = convert(archive, TARGET)
    print(f"{count} loops written to {TARGET / 'loops'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
