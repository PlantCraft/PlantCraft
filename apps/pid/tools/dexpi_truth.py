"""Answer key from a DEXPI (Proteus XML) file: the drawn tags and the equipment-to-equipment
feeds, for scoring the reader on public P&IDs (gitlab.com/dexpi/TrainingTestCases, CC BY 4.0).

Our own reader of the XML (pyDEXPI is AGPL, so it is not used)::

    python tools/dexpi_truth.py C01V01-HEX.EX02.xml
"""

from __future__ import annotations

import json
import re
import sys
import xml.etree.ElementTree as ET  # noqa: S405 - files we chose, read locally
from collections import defaultdict
from pathlib import Path


def norm(tag: str) -> str:
    m = re.match(r"^([A-Z]+)-?(\d.*)$", tag)
    return f"{m.group(1)}-{m.group(2)}" if m else tag


def truth(path: str | Path) -> dict[str, list]:
    root = ET.parse(path).getroot()  # noqa: S314 - local file
    owner: dict[str, tuple[str, str]] = {}  # any ID -> ("eq", tag), ("seg", id) or ("sys", id)
    tags: set[str] = set()
    for e in root.iter("Equipment"):
        if e.get("TagName"):
            tag = norm(e.get("TagName"))
            tags.add(tag)
            for n in e.iter():
                if n.get("ID"):
                    owner[n.get("ID")] = ("eq", tag)
    for p in root.iter("ProcessInstrumentationFunction"):
        ga = {g.get("Name"): g.get("Value") for g in p.iter("GenericAttribute")}
        cat = ga.get("ProcessInstrumentationFunctionCategoryAssignmentClass") or ""
        mod = ga.get("ProcessInstrumentationFunctionModifierAssignmentClass") or ""
        num = ga.get("ProcessInstrumentationFunctionNumberAssignmentClass") or ""
        if cat and num and "-" in num:
            tags.add(f"{cat}{mod}-{num.split('-', 1)[1]}")
        if ga.get("ActuatingFunctionNumberAssignmentClass"):
            tags.add(ga["ActuatingFunctionNumberAssignmentClass"])
    segs = list(root.iter("PipingNetworkSegment"))
    for s in segs:
        for n in s.iter():
            if n.get("ID") and n.get("ID") not in owner:
                owner[n.get("ID")] = ("seg", s.get("ID"))
    for s in root.iter("PipingNetworkSystem"):
        for n in s.iter():
            if n.get("ID") and n.get("ID") not in owner:
                owner[n.get("ID")] = ("sys", s.get("ID"))
    nxt: dict[tuple[str, str], set] = defaultdict(set)
    for s in segs:
        sid = ("seg", s.get("ID"))
        for c in s.findall("Connection"):
            f, t = c.get("FromID"), c.get("ToID")
            if f and f in owner and owner[f] != sid:
                nxt[owner[f]].add(sid)
            if t and t in owner and owner[t] != sid:
                nxt[sid].add(owner[t])
    feeds = set()
    for node in list(nxt):
        if node[0] != "eq":
            continue
        seen, stack = set(), list(nxt[node])
        while stack:
            n = stack.pop()
            if n in seen:
                continue
            seen.add(n)
            if n[0] == "eq":
                if n != node:
                    feeds.add((node[1], n[1]))
                continue
            stack.extend(nxt[n])
    return {"tags": sorted(tags), "feeds": sorted(feeds)}


if __name__ == "__main__":
    print(json.dumps(truth(sys.argv[1]), indent=1))
