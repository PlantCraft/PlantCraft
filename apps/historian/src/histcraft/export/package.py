"""A data package: the Historian's series and the plant's metadata in open files.

One ZIP that someone outside opens in any tool, and in a PlantCraft of their own:

- ``series.csv``: the samples, wide and sparse (first column the UTC time, one column per tag),
  the format the Historian reads as a CSV source;
- ``signals.csv``: every tag with its name, unit, limits and the assets it serves (role);
- ``assets.csv``: the chosen part of the asset tree (loops, units, equipment) with their tags by
  role, and ``plant-map.json``, the loops and signals in PlantCraft's plant map format
  (``processcraft-map``), which Setup > Import a plant map reads;
- ``manifest.json`` (what, when, which period, how, a SHA-256 per file) and ``README.txt``.

With ``anonymize`` every tag and asset becomes an alias (``S001``, ``A001``) and names and
descriptions are left out; the key (alias -> real id) is a separate download that never
travels in the package. Aliases follow the sorted ids, so the same choice always gives the same
key.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import zipfile
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import pandas as pd

from histcraft.i18n import t

FORMAT = "processcraft-data-package"
VERSION = 2
ROLES = ("pv", "sp", "op", "mode", "secondary")


def tag_of(signal_id: str) -> str:
    """The tag of a signal id (``plant:FIC-101.PV`` -> ``FIC-101.PV``)."""

    return signal_id.split(":", 1)[1] if ":" in signal_id else signal_id


def is_loop(asset: dict[str, Any]) -> bool:
    return asset.get("kind") == "loop" or "loop" in (asset.get("type_path") or [])


@dataclass
class Selection:
    """What goes in a package: the signals (Historian points) and the assets they serve."""

    signals: list[dict[str, Any]] = field(default_factory=list)
    assets: list[dict[str, Any]] = field(default_factory=list)
    # Signals an asset names that the Historian does not hold: id -> why.
    missing: dict[str, str] = field(default_factory=dict)

    def signal_ids(self) -> list[str]:
        return sorted(dict.fromkeys(item["signal"] for item in self.signals))


@dataclass
class Aliases:
    """Tags and assets as they appear in the package (themselves, or aliases)."""

    anonymize: bool
    signals: dict[str, str] = field(default_factory=dict)
    assets: dict[str, str] = field(default_factory=dict)

    @classmethod
    def build(cls, selection: Selection, anonymize: bool) -> Aliases:
        found = cls(anonymize)
        ids = selection.signal_ids()
        # One tag in two sources (an import of the same tags, say) keeps both columns: each
        # is then named by its whole id (``import-1:FI-101.PV``).
        shared = {tag for tag, count in Counter(map(tag_of, ids)).items() if count > 1}
        for index, signal_id in enumerate(ids, start=1):
            tag = tag_of(signal_id)
            found.signals[signal_id] = (
                f"S{index:03d}" if anonymize else signal_id if tag in shared else tag
            )
        for index, asset_id in enumerate(sorted(item["id"] for item in selection.assets), 1):
            found.assets[asset_id] = f"A{index:03d}" if anonymize else asset_id
        return found

    def signal(self, signal_id: str | None) -> str:
        return self.signals.get(signal_id or "", "") if signal_id else ""

    def text(self, value: Any) -> str:
        """A free text (name, description): left out of an anonymized package."""

        return "" if self.anonymize else str(value or "")

    def key_rows(self) -> list[dict[str, str]]:
        rows = [
            {"kind": "signal", "alias": alias, "id": key} for key, alias in self.signals.items()
        ]
        rows += [{"kind": "asset", "alias": alias, "id": key} for key, alias in self.assets.items()]
        return rows


def _csv(rows: list[dict[str, Any]], columns: list[str]) -> bytes:
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=columns, extrasaction="ignore", lineterminator="\n")
    writer.writeheader()
    for row in rows:
        writer.writerow({key: "" if row.get(key) is None else row.get(key) for key in columns})
    return buffer.getvalue().encode("utf-8")


def key_csv(selection: Selection) -> bytes:
    """The anonymization key of a choice: alias -> the real tag or asset."""

    return _csv(Aliases.build(selection, True).key_rows(), ["kind", "alias", "id"])


def series_csv(samples: dict[str, pd.Series], aliases: Aliases) -> tuple[bytes, int]:
    """The samples as one wide, sparse CSV (UTC times with ``Z``), and its row count."""

    columns = {
        aliases.signal(signal_id): values
        for signal_id, values in sorted(samples.items())
        if values is not None and not values.empty
    }
    if not columns:
        return b"time\n", 0
    frame = pd.DataFrame(columns).sort_index()
    frame.index = [stamp.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z" for stamp in frame.index]
    frame.index.name = "time"
    return frame.to_csv(lineterminator="\n").encode("utf-8"), len(frame)


def _roles(selection: Selection) -> dict[str, list[tuple[str, str]]]:
    roles: dict[str, list[tuple[str, str]]] = {}
    for asset in selection.assets:
        for role, signal_id in (asset.get("signals") or {}).items():
            if signal_id:
                roles.setdefault(signal_id, []).append((asset["id"], role))
    return roles


def _signal_rows(selection: Selection, aliases: Aliases) -> list[dict[str, Any]]:
    roles = _roles(selection)
    rows = []
    for item in sorted(selection.signals, key=lambda point: aliases.signal(point["signal"])):
        used = roles.get(item["signal"], [])
        rows.append(
            {
                "tag": aliases.signal(item["signal"]),
                "source": "" if aliases.anonymize else item.get("source_id") or "",
                "name": aliases.text(item.get("name")),
                "description": aliases.text(item.get("description")),
                "unit": item.get("unit") or "",
                "kind": item.get("kind") or "number",
                "low": item.get("low"),
                "high": item.get("high"),
                "asset": aliases.assets.get(used[0][0], "") if used else "",
                "role": used[0][1] if used else "",
            }
        )
    return rows


def _asset_rows(selection: Selection, aliases: Aliases) -> list[dict[str, Any]]:
    rows = []
    for asset in sorted(selection.assets, key=lambda item: aliases.assets[item["id"]]):
        signals = asset.get("signals") or {}
        attributes = asset.get("attributes") or {}
        parent = asset.get("parent_id")
        rows.append(
            {
                "asset_id": aliases.assets[asset["id"]],
                "name": aliases.text(asset.get("name")) or aliases.assets[asset["id"]],
                "kind": asset.get("kind") or "",
                "parent_id": aliases.assets.get(parent, "") if parent else "",
                "description": aliases.text(attributes.get("description")),
                **{role: aliases.signal(signals.get(role)) for role in ROLES},
                "loop_type": attributes.get("loop_type") or "",
                "criticality": attributes.get("criticality") or "",
                "action": attributes.get("action") or "",
                "controller": attributes.get("controller") or "",
            }
        )
    return rows


README = """PlantCraft data package
=========================

Made by the PlantCraft Historian on {created} for the period {start} to {end} (UTC).
{anonymized}
Files
-----
series.csv       The samples: the first column is the time (UTC, ISO 8601), one column per tag.
                 Empty cells mean no sample at that time. Aggregation: {aggregation}.
signals.csv      Every tag: name, unit, limits, the asset and role it serves.
assets.csv       The chosen part of the plant: loops, units and equipment, with their tags by
                 role (pv, sp, op, mode) and the loop's type and criticality.
plant-map.json   The loops and signals in PlantCraft's plant map format.
manifest.json    What is in the package, with a SHA-256 for every file.

Open it in a PlantCraft of your own
-------------------------------------
1. In the Historian, add series.csv as a CSV source (time zone UTC).
2. In PlantCraft, Administration > Setup > Import a plant map, with plant-map.json.
3. Link picks the loops up at its next sync and analyses them.
"""

ANONYMIZED = "Tags and assets are aliases (S001, A001); the key stays with whoever made it.\n"


def build(
    *,
    selection: Selection,
    samples: dict[str, pd.Series],
    start: datetime,
    end: datetime,
    anonymize: bool,
    step_seconds: int | None,
    made_by: str,
    aggregate: str = "mean",
    failed: dict[str, str] | None = None,
) -> bytes:
    """The package as ZIP bytes."""

    aliases = Aliases.build(selection, anonymize)
    signal_rows = _signal_rows(selection, aliases)
    asset_rows = _asset_rows(selection, aliases)
    series, sample_rows = series_csv(samples, aliases)
    created = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    loops = {aliases.assets[item["id"]] for item in selection.assets if is_loop(item)}
    files = {
        "series.csv": series,
        "signals.csv": _csv(signal_rows, list(signal_rows[0]) if signal_rows else ["tag"]),
        "assets.csv": _csv(asset_rows, list(asset_rows[0]) if asset_rows else ["asset_id"]),
        "plant-map.json": json.dumps(
            {
                "format": "processcraft-map",
                "signals": [
                    {
                        "tag": row["tag"],
                        "name": row["name"] or row["tag"],
                        "unit": row["unit"],
                        "asset_id": row["asset"],
                        "role": row["role"],
                    }
                    for row in signal_rows
                ],
                "loops": [
                    {"loop_id": row["asset_id"], **{k: row[k] for k in ("name", *ROLES) if row[k]}}
                    for row in asset_rows
                    if row["asset_id"] in loops
                ],
            },
            indent=2,
        ).encode(),
    }
    words = {"mean": "time-weighted mean", "first": "first value", "last": "last value"}
    words |= {"min": "lowest value", "max": "highest value"}
    aggregation = (
        t(
            "{aggregate} over each {seconds} s",
            aggregate=t(words.get(aggregate, aggregate)),
            seconds=step_seconds,
        )
        if step_seconds
        else t("as recorded")
    )
    files["README.txt"] = (
        t(README)
        .format(
            created=created,
            start=start.isoformat(),
            end=end.isoformat(),
            aggregation=aggregation,
            anonymized=t(ANONYMIZED) if anonymize else "",
        )
        .encode()
    )
    not_read = {aliases.signal(key) or key: value for key, value in (failed or {}).items()}
    if not anonymize:
        not_read.update(selection.missing)
    manifest = {
        "format": FORMAT,
        "version": VERSION,
        "made_by": made_by,
        "created_at": created,
        "period": {"start": start.isoformat(), "end": end.isoformat(), "timezone": "UTC"},
        "aggregation": {"step_seconds": step_seconds, "aggregate": aggregate}
        if step_seconds
        else {"raw": True},
        "anonymized": anonymize,
        "counts": {
            "signals": len(signal_rows),
            "assets": len(asset_rows),
            "loops": len(loops),
            "rows": sample_rows,
            "not_in_historian": len(selection.missing),
        },
        "not_read": not_read,
        "files": [
            {"path": name, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}
            for name, data in files.items()
        ],
    }
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("manifest.json", json.dumps(manifest, indent=2))
        for name, data in files.items():
            archive.writestr(name, data)
    return buffer.getvalue()
