"""Prototype helper (not for merge): keep the e2e server up and write its URL and a fresh token."""
import json, os, time
from pathlib import Path

def test_hold(fake, app_url):
    end = time.time() + int(os.environ.get("HOLD_SECONDS", "10800"))
    while time.time() < end:
        Path("/tmp/claude-0/proto/server.json").write_text(json.dumps({"url": app_url, "token": fake.token("engineer")}))
        time.sleep(240)
