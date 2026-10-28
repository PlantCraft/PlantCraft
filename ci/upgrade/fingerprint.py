"""What an installation holds, read through its HTTP APIs, so an upgrade test can prove nothing
was lost (ci/e2e-upgrade.sh, docs/operations.md section 3).

    python3 ci/upgrade/fingerprint.py seed  --url https://host/ --password-file FILE
    python3 ci/upgrade/fingerprint.py take  --url https://host/ --password-file FILE --out before.json
    python3 ci/upgrade/fingerprint.py check --url https://host/ --password-file FILE --before before.json [--versions 0.3.1]

``seed`` adds marked records an upgrade must keep (an asset with its record, an action with a
checklist item, a group). ``take`` writes, for every list the suite's apps serve, the ids it
holds, plus the exact values of a few signals over a closed past hour, the results the apps
published and the counts of the audit log and the events. ``check`` reads them again and fails
when an id, a value or a result is gone, a list that answered no longer answers, or a count went
down; new items are fine (the suite keeps working while it is tested). Only the standard
library: it runs on the server that holds the installation.
"""

from __future__ import annotations

import argparse
import http.cookiejar
import json
import ssl
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

MARK = "UPG-CHECK"
# Every list the fingerprint holds: (name, path under the suite's address). An answer that is a
# list of objects gives its ids (the key named, else the first of ID_KEYS a row has); an object
# with "items" the same. A list that is not served
# before the upgrade (404, an app that is not installed) is left out of the comparison.
LISTS = [
    ("plantcraft.assets", "api/assets", "asset_id"),
    ("plantcraft.asset_types", "api/v1/asset-types", "id"),
    ("plantcraft.people", "api/users", "username"),
    ("plantcraft.groups", "api/groups", "group_id"),
    ("plantcraft.actions", "api/actions?view=visible", "action_id"),
    ("plantcraft.app_keys", "api/app-keys", "key_id"),
    ("plantcraft.signals", "api/v1/signals", "id"),
    ("plantcraft.schedules", "api/v1/schedules", "id"),
    ("historian.sources", "hist/api/sources", "source_id"),
    ("historian.points", "hist/api/points?limit=5000", None),
    ("link.loops", "link/api/loops", "loop_id"),
    ("link.algorithms", "link/api/algorithms", None),
    ("link.schedules", "link/api/schedules", None),
    ("link.models", "link/api/models", None),
    ("view.dashboards", "dash/api/dashboards", "id"),
    ("view.trends", "dash/api/trends", "id"),
    ("view.folders", "dash/api/folders", "id"),
    ("alarms.alarms", "alarm/api/alarms", "alarm_id"),
    ("alarms.rules", "alarm/api/rules", None),
    ("models.projects", "model/api/projects", "id"),
    ("models.blocks", "model/api/blocks", "id"),
]
ID_KEYS = (
    "id", "asset_id", "username", "group_id", "action_id", "key_id", "signal_id", "point_id",
    "source_id", "loop_id", "algorithm_id", "schedule_id", "dashboard_id", "trend_id",
    "folder_id", "alarm_id", "rule_id", "project_id", "library_id", "model_id", "name", "tag",
)  # fmt: skip
SERIES_SIGNALS = 6
LIST_KEYS = ("items", "groups", "keys", "libraries", "projects", "rows")


class Suite:
    """A signed-in session on the installation (the session and token cookies)."""

    def __init__(self, url: str, password: str, *, user: str = "admin", verify: bool = False):
        self.url = url.rstrip("/") + "/"
        context = ssl.create_default_context()
        if not verify:  # the installation's own CA is not in this machine's trust store
            context.check_hostname = False
            context.verify_mode = ssl.CERT_NONE
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPSHandler(context=context),
            urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()),
            urllib.request.ProxyHandler({}),
        )
        status, body = self.call("POST", "api/login", {"username": user, "password": password})
        if status != 200:
            raise SystemExit(f"sign-in as {user} failed: {status} {str(body)[:200]}")

    def call(self, method: str, path: str, body: Any = None) -> tuple[int, Any]:
        data = None if body is None else json.dumps(body).encode()
        request = urllib.request.Request(self.url + path, data=data, method=method)
        request.add_header("Accept", "application/json")
        if data is not None:
            request.add_header("Content-Type", "application/json")
        try:
            with self.opener.open(request, timeout=60) as response:
                raw = response.read()
                status = response.status
        except urllib.error.HTTPError as exc:
            raw, status = exc.read(), exc.code
        except (urllib.error.URLError, TimeoutError) as exc:
            return 0, str(exc)
        try:
            return status, json.loads(raw) if raw else None
        except ValueError:
            return status, raw[:200].decode(errors="replace")

    def get(self, path: str) -> Any:
        status, body = self.call("GET", path)
        return body if status == 200 else None


def ids_of(answer: Any, id_key: str | None = None) -> list[str] | None:
    rows = answer
    if isinstance(answer, dict):
        # {"items": [...]}, {"groups": [...], "kinds": [...]}, {"keys": [...]}: its first list.
        rows = next((answer[key] for key in LIST_KEYS if isinstance(answer.get(key), list)), None)
    if not isinstance(rows, list):
        return None
    found = []
    for row in rows:
        if isinstance(row, dict):
            keys = (id_key,) if id_key and id_key in row else ID_KEYS
            key = next((key for key in keys if row.get(key) not in (None, "")), None)
            found.append(str(row[key]) if key else json.dumps(row, sort_keys=True)[:200])
            # A renamed item answers to its old ids too (Link's built-in algorithms, round 6).
            aliases = row.get("aliases")
            if isinstance(aliases, list):
                found += [str(alias) for alias in aliases if alias not in (None, "")]
        else:
            found.append(str(row))
    return sorted(set(found))


def seed(suite: Suite) -> None:
    """Records the upgrade must keep, each marked UPG-CHECK."""

    status, body = suite.call(
        "POST",
        "api/assets",
        {
            "asset_id": f"{MARK}-001",
            "name": "Upgrade check vessel",
            "kind": "equipment",
            "description": "Written before an upgrade; it must still be here after it.",
        },
    )
    if status not in (200, 201, 409):
        raise SystemExit(f"seeding the asset failed: {status} {str(body)[:200]}")
    status, action = suite.call(
        "POST",
        "api/actions",
        {"title": f"{MARK} action kept across the upgrade", "refs": [f"asset:{MARK}-001"]},
    )
    if status not in (200, 201):
        raise SystemExit(f"seeding the action failed: {status} {str(action)[:200]}")
    action_id = action.get("action_id") if isinstance(action, dict) else None
    if action_id:
        suite.call("POST", f"api/actions/{action_id}/items", {"text": f"{MARK} checklist item"})
    status, body = suite.call(
        "POST", "api/groups", {"name": f"{MARK} group", "description": "Upgrade check"}
    )
    if status not in (200, 201, 409):
        print(f"note: the group was not seeded ({status})", file=sys.stderr)
    print(f"seeded asset {MARK}-001, action {action_id}, group")


def take(suite: Suite, *, at: datetime | None = None) -> dict[str, Any]:
    at = (at or datetime.now(UTC)).replace(minute=0, second=0, microsecond=0)
    lists: dict[str, list[str]] = {}
    for name, path, id_key in LISTS:
        found = ids_of(suite.get(path), id_key)
        if found is not None:
            lists[name] = found
    # A closed past hour of a few signals: the archive must give the very same values back.
    start, end = at - timedelta(hours=2), at - timedelta(hours=1)
    series: dict[str, Any] = {}
    signals = suite.get("api/v1/signals") or []
    # Measured signals, not the apps' derived ones (an app may write those again).
    numeric = [
        item["id"]
        for item in signals
        if isinstance(item, dict)
        and item.get("kind", "number") == "number"
        and item.get("source_kind") != "derived"
    ]
    for signal_id in sorted(numeric):
        if len(series) >= SERIES_SIGNALS:
            break
        query = urllib.parse.urlencode({"start": start.isoformat(), "end": end.isoformat()})
        answer = suite.get(
            f"api/v1/signals/{urllib.parse.quote(signal_id, safe=':')}/series?{query}"
        )
        if isinstance(answer, dict) and answer.get("t"):
            series[signal_id] = {"t": answer["t"], "v": answer.get("v")}
    results = suite.get("api/v1/results") or []
    audit = suite.get("api/audit?days=365&limit=5000") or {}
    events = suite.get("api/v1/events?limit=500") or []
    apps = suite.get("api/v1/apps") or []
    return {
        "taken_at": datetime.now(UTC).isoformat(),
        "window": [start.isoformat(), end.isoformat()],
        "versions": {item["id"]: item.get("version") for item in apps if isinstance(item, dict)},
        "lists": lists,
        "series": series,
        # Series an app retired (Link 0.4 stops writing a loop's `.status` and per-block series):
        # no longer listed, their archive kept by the Historian for its retired days.
        "archived": sorted(
            {
                str(value)
                for item in (suite.get("hist/api/points/retired") or {}).get("points", [])
                if isinstance(item, dict)
                for value in (item.get("id"), item.get("signal"))
                if value not in (None, "")
            }
        ),
        "results": sorted(
            {
                f"{item['app']}|{item['subject']}|{item['kind']}"
                for item in results
                if isinstance(item, dict)
            }
        ),
        "audit_total": len(audit["rows"]) if isinstance(audit, dict) and "rows" in audit else None,
        "events": len(events) if isinstance(events, list) else None,
        "marked": {
            "asset": suite.get(f"api/assets/{MARK}-001") is not None,
        },
    }


def compare(before: dict[str, Any], after: dict[str, Any]) -> list[str]:
    problems: list[str] = []
    for name, ids in before["lists"].items():
        now = after["lists"].get(name)
        if now is None:
            problems.append(f"{name}: answered before the upgrade, not after")
            continue
        gone = sorted(set(ids) - set(now))
        if name in ("plantcraft.signals", "historian.points"):  # retired, archive kept
            gone = [item for item in gone if item not in after.get("archived", [])]
        if name == "alarms.alarms":  # Alarms 0.4: an older alarm became a rule with its id
            gone = [item for item in gone if item not in after["lists"].get("alarms.rules", [])]
        if gone:
            problems.append(f"{name}: {len(gone)} gone ({', '.join(gone[:5])})")
    for signal_id, values in before["series"].items():
        if after["series"].get(signal_id) != values:
            problems.append(f"series of {signal_id} over {before['window']} changed")
    gone = sorted(set(before["results"]) - set(after["results"]))
    if gone:
        problems.append(f"results: {len(gone)} gone ({', '.join(gone[:5])})")
    for key in ("audit_total", "events"):
        if before.get(key) is not None and (after.get(key) or 0) < before[key]:
            problems.append(f"{key}: {before[key]} before, {after.get(key)} after")
    for key, kept in before["marked"].items():
        if kept and not after["marked"].get(key):
            problems.append(f"the seeded {key} {MARK}-001 is gone")
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("action", choices=["seed", "take", "check"])
    parser.add_argument("--url", required=True)
    parser.add_argument("--password-file", required=True, type=Path)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--before", type=Path)
    parser.add_argument("--versions", help="the version every app must report after (check)")
    args = parser.parse_args(argv)
    suite = Suite(args.url, args.password_file.read_text().strip())
    if args.action == "seed":
        seed(suite)
        return 0
    if args.action == "take":
        found = take(suite)
        (args.out or Path("fingerprint.json")).write_text(json.dumps(found, indent=1))
        sizes = {name: len(ids) for name, ids in found["lists"].items()}
        print(
            f"fingerprint: {sizes}, {len(found['series'])} series, {len(found['results'])} results"
        )
        if not found["marked"]["asset"]:
            print(f"warning: the seeded asset {MARK}-001 is not there", file=sys.stderr)
        return 0
    before = json.loads(args.before.read_text())
    window_end = datetime.fromisoformat(before["window"][1]) + timedelta(hours=1)
    after = take(suite, at=window_end)
    if args.out:
        args.out.write_text(json.dumps(after, indent=1))
    problems = compare(before, after)
    if args.versions:
        wrong = {
            app: version
            for app, version in after["versions"].items()
            if version not in (args.versions, None)
        }
        if wrong:
            problems.append(f"versions after: {wrong}, expected {args.versions}")
    for line in problems:
        print(f"LOST: {line}")
    kept = sum(len(ids) for ids in before["lists"].values())
    print(
        f"checked {len(before['lists'])} lists ({kept} ids), {len(before['series'])} series, {len(before['results'])} results: "
        + ("nothing lost" if not problems else f"{len(problems)} problems")
    )
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
