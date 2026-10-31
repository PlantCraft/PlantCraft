"""Unpack the SACAC control-loop data repository into ``oracles/sacac/`` at a pinned version.

Source: the Data Repository of the South African Council for Automation and Control (SACAC),
https://sacac.org.za/resources/, which files industrial loops by the cause of their poor
performance (Bauer et al., 2016: Stiction, Tuning, Saturation, Sensor Faults...). The archive
declares no licence (the page asks users to write to SACAC), so it is never committed
(``/oracles/`` is gitignored) and is downloaded only for a test run. A new archive is a new pin.

    python tests/oracles/fetch_sacac.py                       # download, check sha256, unpack
    python tests/oracles/fetch_sacac.py --archive sacac.zip   # same, from a copy you downloaded

Only the Stiction and Tuning categories are kept: the stiction screen should flag the first and
stay quiet on the second (an oscillation that is the controller's, not the valve's). Each case
becomes ``oracles/sacac/loops/<name>.csv`` (columns ``pv``, ``op`` and, when present, ``sp``)
plus a row in ``oracles/sacac/loops.json`` with its category, sampling time and description. A
case without a PV and an OP column (a plant-wide set) is listed as skipped, with its columns.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import re
import sys
import urllib.request
import zipfile
from pathlib import Path

URL = "https://sacac.org.za/Resources/DataRepositories/DataRepositories.zip"
# Downloaded on 2026-10-31 (8,347,372 bytes, 113 entries). This project's cloud egress refuses
# the host, so the pin was taken where it is reachable.
SHA256 = "ed4170220f5cc743493055599b605eca72bf41b5db269c1e7299c3aca0e58ced"
CATEGORIES = {"stiction": "stiction", "tuning": "no_stiction"}
# Column names of a loop's three signals, as the cases spell them.
ROLES = {
    "pv": ("pv", "y", "process variable", "measurement"),
    "op": ("op", "mv", "co", "u", "controller output", "output", "valve"),
    "sp": ("sp", "r", "setpoint", "set point"),
}

ROOT = Path(__file__).resolve().parents[2]
TARGET = ROOT / "oracles" / "sacac"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def download(target: Path) -> Path:
    archive = target / "DataRepositories.zip"
    if not archive.exists():
        target.mkdir(parents=True, exist_ok=True)
        print(f"Downloading {URL}")
        with urllib.request.urlopen(URL, timeout=300) as response:  # noqa: S310 (pinned URL)
            archive.write_bytes(response.read())
    return archive


def sample_seconds(text: str) -> float | None:
    """The first number after "Sampling rate:" (seconds; a mean when the rate varies)."""

    match = re.search(
        r"Sampling rate:\s*[^0-9]*([0-9]+(?:\.[0-9]+)?)\s*(ms|s|sec|min)?", text, re.I
    )
    if not match:
        return None
    value = float(match.group(1))
    unit = (match.group(2) or "s").lower()
    return value / 1000 if unit == "ms" else value * 60 if unit == "min" else value


def _role(header: str) -> str | None:
    name = re.sub(r"[^a-z ]", " ", header.lower()).strip()
    words = name.split()
    for role, names in ROLES.items():
        if name in names or (words and words[0] in names):
            return role
    return None


def read_case(raw: bytes) -> tuple[dict[str, list[float]], list[str]]:
    """The PV, OP and SP columns of a case's CSV, and its header as found."""

    text = raw.decode("utf-8-sig", errors="replace")
    sample = text[:4096]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t ")
    except csv.Error:
        dialect = csv.excel
    rows = [
        row for row in csv.reader(io.StringIO(text), dialect) if any(cell.strip() for cell in row)
    ]
    if not rows:
        return {}, []
    header = [cell.strip() for cell in rows[0]]
    roles: dict[str, int] = {}
    for index, cell in enumerate(header):
        role = _role(cell)
        if role and role not in roles:
            roles[role] = index
    columns: dict[str, list[float]] = {role: [] for role in roles}
    for row in rows[1:]:
        try:
            values = {role: float(row[index]) for role, index in roles.items()}
        except (ValueError, IndexError):
            continue
        for role, value in values.items():
            columns[role].append(value)
    return columns, header


def convert(archive: Path, target: Path) -> tuple[int, list[dict]]:
    loops_dir = target / "loops"
    loops_dir.mkdir(parents=True, exist_ok=True)
    manifest, skipped = [], []
    with zipfile.ZipFile(archive) as bundle:
        names = bundle.namelist()
        texts = {
            Path(name).parent.as_posix(): bundle.read(name).decode("utf-8", errors="replace")
            for name in names
            if name.lower().endswith(".txt")
        }
        for name in sorted(names):
            path = Path(name)
            category = next(
                (CATEGORIES[part.lower()] for part in path.parts if part.lower() in CATEGORIES),
                None,
            )
            if category is None or path.suffix.lower() != ".csv":
                continue
            columns, header = read_case(bundle.read(name))
            if "pv" not in columns or "op" not in columns or len(columns["pv"]) < 50:
                skipped.append({"case": path.stem, "columns": header[:12]})
                continue
            text = texts.get(path.parent.as_posix(), "")
            with (loops_dir / f"{path.stem}.csv").open("w", encoding="utf-8") as handle:
                roles = [role for role in ("pv", "op", "sp") if role in columns]
                handle.write(",".join(roles) + "\n")
                for i in range(len(columns["pv"])):
                    handle.write(",".join(repr(columns[role][i]) for role in roles) + "\n")
            manifest.append(
                {
                    "loop": path.stem,
                    "category": category,
                    "folder": path.parent.as_posix(),
                    "sample_seconds": sample_seconds(text) or 1.0,
                    "samples": len(columns["pv"]),
                    "text": {"description": text.strip()},
                }
            )
    (target / "loops.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    (target / "skipped.json").write_text(json.dumps(skipped, indent=2), encoding="utf-8")
    return len(manifest), skipped


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--archive", type=Path, help="a copy of DataRepositories.zip")
    args = parser.parse_args(argv)
    archive = args.archive or download(TARGET)
    found = sha256(archive)
    if found != SHA256:
        print(f"sha256 mismatch: expected {SHA256}, got {found}", file=sys.stderr)
        return 1
    count, skipped = convert(archive, TARGET)
    print(f"{count} loops written to {TARGET / 'loops'}; skipped (no PV and OP): {skipped}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
