"""The Notebooks kits: Python and JupyterLab for a person's own computer (Notebooks › Run on your
computer; ``notebooks/kit/build_kit.py`` builds them).

The bundle carries them as an optional part, ``notebook-kits/`` (mounted read-only at
``/notebook-kits``; ``PLANTCRAFT_NOTEBOOK_KITS`` names another folder), with ``kits.json``, their
list. They are offered whenever Notebooks are on; an administrator may take them
away in Settings › Notebooks.

A kit is sent with two files added to it on the way: ``plantcraft.json``, the address the person
downloaded it from, and the installation's local certificate authority when it has one (the kit
then trusts this server's HTTPS). They are appended to the zip as it streams, without reading or
rewriting the hundreds of megabytes before them. Never a token: the person creates one on the page
and "Configure token" keeps it in their system's vault.
"""

from __future__ import annotations

import base64
import hashlib
import io
import json
import os
import re
import struct
import zipfile
from collections.abc import Iterator
from pathlib import Path
from typing import Any

# A kit's token: longer than an assistant's (D5); the kit warns a week before.
KIT_TOKEN_DAYS = 90
KITS_DIR = "/notebook-kits"
BUILT_DIR = "/data/notebook-kits"
ROOT = "PlantCraft Notebooks"
CA_FILE = "plantcraft-ca.pem"
# Where install.sh copies the proxy's local certificate authority (PlantCraft's data folder).
LOCAL_CA = "/data/local-ca-root.crt"
# A connection code: one line the person pastes into PlantCraft Notebooks on their computer.
CODE_PREFIX = "pcnb1:"
_ID = re.compile(r"^[a-z0-9][a-z0-9-]{0,40}$")
_EOCD = b"PK\x05\x06"
CHUNK = 1 << 20


def kits_dir() -> Path:
    """The bundle's kits (``/notebook-kits``), else the ones a deploy built into PlantCraft's data
    (``/data/notebook-kits``: ci/macmini/notebook-kits, left out of backups)."""

    configured = os.environ.get("PLANTCRAFT_NOTEBOOK_KITS", "").strip()
    if configured:
        return Path(configured)
    bundled = Path(KITS_DIR)
    return bundled if (bundled / "kits.json").is_file() else Path(BUILT_DIR)


def connection_code(url: str, token: str, ca: bytes | None) -> str:
    """This server's address, the kit's token and the SHA-256 of the local certificate authority
    (the kit fetches it and keeps it only when it matches), as one line to paste."""

    found = {"url": url.rstrip("/"), "token": token}
    if ca:
        found["ca"] = hashlib.sha256(ca).hexdigest()
    packed = base64.urlsafe_b64encode(json.dumps(found, separators=(",", ":")).encode())
    return CODE_PREFIX + packed.decode("ascii").rstrip("=")


def local_ca() -> bytes | None:
    """The installation's local certificate authority (install.sh copies it into PlantCraft's
    data), or None: with the client's own certificate the person's computer trusts it already."""

    configured = os.environ.get("PLANTCRAFT_LOCAL_CA", "").strip()
    path = Path(configured or LOCAL_CA)
    try:
        data = path.read_bytes()
    except OSError:
        return None
    return data if b"BEGIN CERTIFICATE" in data else None


def catalog(folder: Path | None = None) -> dict[str, Any] | None:
    """``kits.json``, with only the kits whose zip is there; None without any."""

    folder = folder or kits_dir()
    try:
        listing = json.loads((folder / "kits.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    kits = []
    for item in listing.get("kits") or []:
        if not _ID.match(str(item.get("id") or "")):
            continue
        path = folder / Path(str(item.get("file") or "")).name
        if path.suffix == ".zip" and path.is_file():
            found = {**item, "file": path.name}
            # The Windows setup or the macOS app, sent as it is (it is the same for everyone).
            setup = item.get("installer") if isinstance(item.get("installer"), dict) else None
            setup_path = folder / Path(str((setup or {}).get("file") or "-")).name
            if setup and setup_path.suffix in (".exe", ".zip") and setup_path.is_file():
                found["installer"] = {**setup, "file": setup_path.name}
            else:
                found.pop("installer", None)
            kits.append(found)
    if not kits:
        return None
    return {"version": str(listing.get("version") or ""), "kits": kits}


def kit_path(
    kit_id: str, folder: Path | None = None, *, installer: bool = False
) -> tuple[Path, dict[str, Any]] | None:
    """The portable zip of a kit (or its installer) and its entry in ``kits.json``."""

    folder = folder or kits_dir()
    found = catalog(folder)
    item = next((kit for kit in (found or {}).get("kits", []) if kit["id"] == kit_id), None)
    if item and installer:
        item = item.get("installer")
    return (folder / item["file"], item) if item else None


def _tail(path: Path) -> tuple[int, int, int, int]:
    """The zip's last record: (where it is, entries, central directory size and offset)."""

    size = path.stat().st_size
    with path.open("rb") as handle:
        handle.seek(max(0, size - 65_557))
        tail = handle.read()
    at = tail.rfind(_EOCD)
    if at < 0 or size >= 0xFFFFFFFF:
        raise ValueError(f"{path.name}: not a zip this server can extend")
    _sig, _disk, _start, _here, count, cd_size, cd_offset, _comment = struct.unpack(
        "<4sHHHHIIH", tail[at : at + 22]
    )
    if count == 0xFFFF or cd_offset == 0xFFFFFFFF:
        raise ValueError(f"{path.name}: zip64 is not supported")
    return size - len(tail) + at, count, cd_size, cd_offset


def _entries(files: dict[str, bytes]) -> tuple[bytes, bytes]:
    """The local records and the central directory records of ``files``, offsets from 0."""

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, data in files.items():
            info = zipfile.ZipInfo(f"{ROOT}/{name}", (2026, 1, 1, 0, 0, 0))
            info.external_attr = 0o644 << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, data)
    raw = buffer.getvalue()
    at = raw.rfind(_EOCD)
    _sig, _d, _s, _h, _count, cd_size, cd_offset, _c = struct.unpack(
        "<4sHHHHIIH", raw[at : at + 22]
    )
    return raw[:cd_offset], raw[cd_offset : cd_offset + cd_size]


def _moved(central: bytes, by: int) -> bytes:
    """Central directory records with every local record ``by`` bytes further on."""

    out = bytearray(central)
    at = 0
    while at < len(out):
        if out[at : at + 4] != b"PK\x01\x02":
            raise ValueError("unexpected central directory record")
        name, extra, comment = struct.unpack("<HHH", bytes(out[at + 28 : at + 34]))
        offset = struct.unpack("<I", bytes(out[at + 42 : at + 46]))[0]
        out[at + 42 : at + 46] = struct.pack("<I", offset + by)
        at += 46 + name + extra + comment
    return bytes(out)


def personalized(path: Path, files: dict[str, bytes]) -> tuple[int, Iterator[bytes]]:
    """The zip at ``path`` with ``files`` added under ``ROOT``: its length and its bytes, read as
    they are sent. The kit's entries are kept byte for byte; only the directory at the end, which
    lists every entry, is written again."""

    end, count, cd_size, cd_offset = _tail(path)
    local, central = _entries(files)
    central = _moved(central, cd_offset)
    added = len(files)
    record = struct.pack(
        "<4sHHHHIIH",
        _EOCD,
        0,
        0,
        count + added,
        count + added,
        cd_size + len(central),
        cd_offset + len(local),
        0,
    )
    total = cd_offset + len(local) + cd_size + len(central) + len(record)

    def stream() -> Iterator[bytes]:
        with path.open("rb") as handle:
            left = cd_offset
            while left > 0:
                chunk = handle.read(min(CHUNK, left))
                if not chunk:
                    raise ValueError(f"{path.name} changed while it was sent")
                left -= len(chunk)
                yield chunk
            yield local
            handle.seek(cd_offset)
            yield handle.read(cd_size)
        yield central
        yield record

    if end != cd_offset + cd_size:
        raise ValueError(f"{path.name}: unexpected bytes after its central directory")
    return total, stream()


def kit_files(url: str, version: str) -> dict[str, bytes]:
    """What PlantCraft adds to a kit: where it was downloaded from, and the local CA."""

    settings: dict[str, Any] = {"url": url.rstrip("/"), "server_kit_version": version}
    ca = local_ca()
    files: dict[str, bytes] = {}
    if ca:
        settings["ca"] = CA_FILE
        files[CA_FILE] = ca
    files["plantcraft.json"] = (json.dumps(settings, indent=2) + "\n").encode("utf-8")
    return files
