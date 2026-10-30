"""Print the tables a fresh PlantCraft has, for tests/schemas/<version>.sql (scale review E10).

Run it at each release, from a checkout of the release commit:

    git worktree add /tmp/release <commit>
    cd /tmp/release && python -I <repo>/dev/schema-snapshot/dump.py > <repo>/tests/schemas/<version>.sql

then add the two comment lines at the top (version and commit). ``tests/test_upgrade_schema.py``
opens every snapshot with the current code and expects the current tables.
"""

import json
import os
import sqlite3
import sys
import tempfile
from pathlib import Path

root = Path.cwd()
tmp = Path(tempfile.mkdtemp())
scenario = json.loads((root / "scenarios" / "generic_demo.json").read_text())
scenario["storage"]["sqlite_path"] = str(tmp / "workspace.sqlite3")
scenario["source"]["path"] = str(root / scenario["source"]["path"])
(tmp / "scenario.json").write_text(json.dumps(scenario))
os.environ.update(
    PLANTCRAFT_SCENARIO=str(tmp / "scenario.json"),
    PLANTCRAFT_PREWARM_HISTORY="false",
    PLANTCRAFT_WATCH="false",
    PLANTCRAFT_MAIL_OUTBOX="false",
    PLANTCRAFT_APPS="linkcraft=/link/,histcraft=/hist/",
)
sys.path.insert(0, str(root))
from fastapi.testclient import TestClient

from plantcraft.api.app import create_app

with TestClient(create_app()) as client:
    client.get("/api/health")
con = sqlite3.connect(tmp / "workspace.sqlite3")
rows = con.execute(
    "SELECT sql FROM sqlite_master WHERE sql IS NOT NULL AND name NOT LIKE 'sqlite_%' ORDER BY type DESC, name"
).fetchall()
print("\n".join(r[0].strip() + ";" for r in rows))
