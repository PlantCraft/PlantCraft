"""The owner's private stats page (/stats): who reads the site, who visits the demo, what the chat
is asked and who asked to be contacted. Behind a password (SITE_STATS_PASSWORD); without one the
page is a 404.

The demo's numbers come from the demo itself (GET /api/demo/stats with
PLANTCRAFT_PUBLIC_DEMO_STATS_KEY), read when the page opens; the site's from visits.py, the chat's
and the contacts' from the data folder (contacts.py). Nothing here holds an address.
"""

from __future__ import annotations

import json
import statistics
import time
import urllib.error
import urllib.request
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta
from html import escape
from pathlib import Path
from zoneinfo import ZoneInfo

ONLINE_SECONDS = 75
USER_AGENT = "PlantCraft-site-stats/1"
DAYS = 14


@dataclass
class DemoSource:
    url: str = ""
    key: str = ""

    def read(self, days: int = 31) -> dict | str:
        """The demo's numbers, or why they could not be read."""
        if not self.url or not self.key:
            return "not set up (SITE_DEMO_STATS_URL and SITE_DEMO_STATS_KEY_FILE)"
        # A user agent of its own: Cloudflare turns away Python's default one (a 403 before the
        # request reaches the demo), and the demo is read through its public name.
        request = urllib.request.Request(
            f"{self.url}?days={days}",
            headers={"Authorization": f"Bearer {self.key}", "User-Agent": USER_AGENT},
        )
        try:
            with urllib.request.urlopen(request, timeout=8) as response:
                return json.loads(response.read())
        except urllib.error.HTTPError as exc:
            return f"not reachable (HTTP {exc.code})"
        except Exception as exc:  # noqa: BLE001 - the page shows the rest anyway
            return f"not reachable ({type(exc).__name__})"


def _lines(path: Path) -> list[dict]:
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            out.append(json.loads(line))
        except ValueError:
            continue
    return out


def _stamp(value: str) -> float:
    try:
        return datetime.fromisoformat(value).timestamp()
    except (TypeError, ValueError):
        return 0.0


def _duration(seconds: float | None) -> str:
    if seconds is None:
        return "–"
    seconds = int(round(seconds))
    if seconds < 60:
        return f"{seconds} s"
    minutes, seconds = divmod(seconds, 60)
    if minutes < 60:
        return f"{minutes} min {seconds:02d} s"
    hours, minutes = divmod(minutes, 60)
    return f"{hours} h {minutes:02d} min"


def _typical(values: list[float]) -> str:
    """Median and mean: one long visit should not hide that most are short."""
    if not values:
        return "–"
    return f"{_duration(statistics.median(values))} (mean {_duration(statistics.fmean(values))})"


def summary(
    views,
    demo: dict | str,
    questions: list[dict],
    contacts: list[dict],
    tz: ZoneInfo,
    now: float | None = None,
    clicks: list[tuple[str, int]] | None = None,
    paths: list[dict] | None = None,
) -> dict:
    now = time.time() if now is None else now
    today = datetime.fromtimestamp(now, tz).date()
    days = [today - timedelta(days=i) for i in range(DAYS)]

    def day(ts: float):
        return datetime.fromtimestamp(ts, tz).date()

    # The site: one visitor a day per hash; their time is from their first view to their last.
    people: dict[str, list[float]] = {}
    pages, referrers, countries = Counter(), Counter(), Counter()
    seen = set()
    online = 0
    for row in views:
        span = people.setdefault(row["visitor"], [row["started"], row["last_seen"]])
        span[0] = min(span[0], row["started"])
        span[1] = max(span[1], row["last_seen"])
        if now - row["last_seen"] <= ONLINE_SECONDS:
            online += 1
        pages[row["page"]] += 1
        if row["visitor"] not in seen:
            seen.add(row["visitor"])
            if row["referrer"]:
                referrers[row["referrer"]] += 1
            if row["country"]:
                countries[row["country"]] += 1
    site_day: dict = defaultdict(list)
    views_day: Counter = Counter(day(row["started"]) for row in views)
    for start, last in people.values():
        site_day[day(start)].append(last - start)

    demo_rows = demo.get("visits", []) if isinstance(demo, dict) else []
    demo_day: dict = defaultdict(list)
    waited_day: Counter = Counter()
    for visit in demo_rows:
        demo_day[day(visit["started"])].append(visit["seconds"])
        if visit.get("waited", 0) >= 5:
            waited_day[day(visit["started"])] += 1
    questions_day = Counter(day(_stamp(q.get("time"))) for q in questions)
    contacts_day = Counter(day(_stamp(c.get("time"))) for c in contacts)

    def total(span: int) -> dict:
        within = set(days[:span])
        return {
            "visitors": sum(len(v) for d, v in site_day.items() if d in within),
            "site_time": _typical([s for d, v in site_day.items() if d in within for s in v]),
            "demo": sum(len(v) for d, v in demo_day.items() if d in within),
            "demo_time": _typical([s for d, v in demo_day.items() if d in within for s in v]),
            "questions": sum(n for d, n in questions_day.items() if d in within),
            "contacts": sum(n for d, n in contacts_day.items() if d in within),
        }

    return {
        "online": online,
        "demo_now": demo.get("now") if isinstance(demo, dict) else None,
        "demo_error": demo if isinstance(demo, str) else "",
        "totals": {"Today": total(1), "Last 7 days": total(7), "Last 14 days": total(14)},
        "days": [
            {
                "day": d,
                "visitors": len(site_day.get(d, [])),
                "views": views_day.get(d, 0),
                "site_time": _typical(site_day.get(d, [])),
                "demo": len(demo_day.get(d, [])),
                "demo_time": _typical(demo_day.get(d, [])),
                "waited": waited_day.get(d, 0),
                "questions": questions_day.get(d, 0),
                "contacts": contacts_day.get(d, 0),
            }
            for d in days
        ],
        "pages": pages.most_common(10),
        "clicks": clicks or [],
        "journeys": (paths or [])[:60],
        "demo_pages": [
            (p.get("page", ""), p.get("visits", 0))
            for p in (demo.get("pages", []) if isinstance(demo, dict) else [])
        ][:20],
        "referrers": referrers.most_common(10),
        "countries": countries.most_common(10),
        "questions": sorted(questions, key=lambda q: q.get("time", ""), reverse=True)[:50],
        "contacts": sorted(contacts, key=lambda c: c.get("time", ""), reverse=True)[:20],
    }


def journeys(views, clicks, demo: dict | str) -> list[dict]:
    """Each site visitor's and each demo visit's steps in order: [seconds since epoch, what].
    Newest first. A site visitor is one browser on one day; a demo visit is one visit."""

    owner = {row["id"]: row["visitor"] for row in views}
    people: dict[str, list] = {}
    for row in views:
        came = []
        if row["referrer"]:
            came.append(f"from {row['referrer']}")
        if row["country"]:
            came.append(row["country"])
        detail = f"opened {row['page']}" + (f" ({', '.join(came)})" if came else "")
        people.setdefault(row["visitor"], []).append([row["started"], detail])
        people[row["visitor"]].append([row["last_seen"], None])
    for row in clicks:
        if row["id"] in owner:
            people[owner[row["id"]]].append([row["at"], f"clicked {row['label']}"])
    out = []
    for visitor, steps in people.items():
        steps.sort(key=lambda step: step[0])
        last = steps[-1][0]
        out.append(
            {
                "source": "site",
                "visitor": visitor[:8],
                "started": steps[0][0],
                "seconds": last - steps[0][0],
                "steps": [step for step in steps if step[1]],
            }
        )
    for visit in demo.get("journeys", []) if isinstance(demo, dict) else []:
        steps = [[visit["started"], "entered the demo"]]
        if visit.get("waited", 0) >= 5:
            steps[0][1] += f" after {_duration(visit['waited'])} in line"
        steps += [[visit["started"] + at, f"opened {page}"] for page, at in visit.get("pages", [])]
        out.append(
            {
                "source": "demo",
                "visitor": visit.get("visitor", ""),
                "started": visit["started"],
                "seconds": visit.get("seconds", 0),
                "steps": steps,
            }
        )
    out.sort(key=lambda j: j["started"], reverse=True)
    return out


def events_csv(paths: list[dict], tz: ZoneInfo) -> str:
    """Every step of every journey, one per line, for a spreadsheet or a notebook."""
    import csv
    import io

    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["source", "visitor", "time", "seconds_into_visit", "step"])
    for journey in sorted(paths, key=lambda j: j["started"]):
        for at, what in journey["steps"]:
            writer.writerow(
                [
                    journey["source"],
                    journey["visitor"],
                    datetime.fromtimestamp(at, tz).isoformat(timespec="seconds"),
                    round(at - journey["started"]),
                    what,
                ]
            )
    return buffer.getvalue()


def _journey_html(journey: dict, tz: ZoneInfo) -> str:
    start = journey["started"]
    head = (
        f"<b>{escape(journey['source'])} {escape(journey['visitor'])}</b> "
        f"{datetime.fromtimestamp(start, tz).strftime('%d/%m %H:%M')} · "
        f"{_duration(journey['seconds'])} · {len(journey['steps'])} steps"
    )
    steps = "".join(
        f"<li><time>+{_duration(at - start)}</time> {escape(what)}</li>"
        for at, what in journey["steps"][:60]
    )
    return f"<li><details><summary>{head}</summary><ol>{steps}</ol></details></li>"


def _when(value: str, tz: ZoneInfo) -> str:
    stamp = _stamp(value)
    return datetime.fromtimestamp(stamp, tz).strftime("%d/%m %H:%M") if stamp else ""


def _bytes(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.0f} {unit}" if unit in ("B", "KB", "MB") else f"{n:.1f} {unit}"
        n /= 1024
    return ""


def _spark(points: list[tuple[float, float]], top: float | None = None) -> str:
    """A small line of the last two hours (an SVG: no script, the page's CSP stays strict)."""
    points = [(t, v) for t, v in points if v is not None]
    if len(points) < 2:
        return ""
    t0, t1 = points[0][0], points[-1][0]
    high = top or max(v for _, v in points) or 1
    xy = " ".join(
        f"{100 * (t - t0) / max(t1 - t0, 1):.1f},{30 - 28 * min(v / high, 1):.1f}"
        for t, v in points
    )
    return (
        "<svg class='spark' viewBox='0 0 100 31' preserveAspectRatio='none' aria-hidden='true'>"
        f"<polyline points='{xy}' fill='none' vector-effect='non-scaling-stroke'/></svg>"
    )


def _tile(value: str, label: str, spark: str = "", state: str = "") -> str:
    cls = f"tile {state}".strip()
    return f"<div class='{cls}'><b>{escape(value)}</b><span>{escape(label)}</span>{spark}</div>"


def health_html(health: dict | None, tz: ZoneInfo, now: float) -> str:
    """The "Now" panel: the server, the services, the answers and the alerts (health.py)."""
    if health is None:
        return ""
    e = escape
    last = health["last"]
    if last is None:
        return (
            "<h2>Server now</h2><p class='muted'>No health samples yet: the watch "
            "(plantcraft-watch) is not running on this host.</p>"
        )
    series = health["series"]
    head = ""
    if health["stale"]:
        head = (
            f"<p class='alert'>The last health sample is from "
            f"{e(_duration(now - last['at']))} ago: the watch (plantcraft-watch) stopped.</p>"
        )
    if health["open"]:
        head += "".join(
            f"<p class='alert'>{e(_when_ts(a['at'], tz))} {e(a['line'])}</p>"
            for a in health["open"]
        )
    elif not health["stale"]:
        head += "<p class='ok'>All good: every check passes.</p>"
    mem, disk = last["memory"], last["disk"]
    cpu = last.get("cpu")
    mem_pct = 100 * mem["used"] / max(mem["total"], 1)
    disk_free = 100 * disk["free"] / max(disk["total"], 1)
    t = health["traffic"]
    tiles = [
        _tile(
            "–" if cpu is None else f"{cpu:.0f}%",
            f"CPU ({last['cores']} cores, load {last['load'][0]:.1f})",
            _spark([(s["at"], s.get("cpu")) for s in series], 100),
            "warn" if (cpu or 0) >= 85 else "",
        ),
        _tile(
            f"{mem_pct:.0f}%",
            f"memory: {_bytes(mem['used'])} of {_bytes(mem['total'])}",
            _spark([(s["at"], s["memory"]["used"]) for s in series], mem["total"]),
            "warn" if mem_pct >= 90 else "",
        ),
        _tile(
            f"{disk_free:.0f}%",
            f"disk free: {_bytes(disk['free'])} of {_bytes(disk['total'])}",
            "",
            "warn" if disk_free < 15 else "",
        ),
    ]
    if t is not None:
        per_min = [
            (
                b["at"],
                ((b["tunnel"]["requests"] - a["tunnel"]["requests"]) or 0)
                / max((b["at"] - a["at"]) / 60, 1e-9),
            )
            for a, b in zip(series, series[1:])
            if a.get("tunnel")
            and b.get("tunnel")
            and b["tunnel"]["requests"] >= a["tunnel"]["requests"]
        ]
        tiles.append(
            _tile(
                f"{t['per_minute']:.0f}/min",
                f"requests (site + demo, last 5 min); {t['error_pct']:.1f}% errors (5xx)",
                _spark(per_min),
                "warn" if t["error_pct"] >= 5 and t["requests"] >= 30 else "",
            )
        )
    probes = "".join(
        f"<tr><th>{e(p['name'])}</th><td class='{'bad' if not 200 <= p['code'] < 400 else ''}'>"
        f"{p['code'] or 'no answer'}</td><td>{p['seconds'] * 1000:.0f} ms</td><td>"
        + _spark(
            [(s["at"], q["seconds"]) for s in series for q in s["probes"] if q["name"] == p["name"]]
        )
        + "</td></tr>"
        for p in last["probes"]
    )
    wanted = [c for c in last["containers"] if c["wanted"]]
    up = [c for c in wanted if c["state"] == "running" and c["health"] != "unhealthy"]
    services = "".join(
        f"<tr><th>{e(c['name'])}</th><td class='{'' if c in up else 'bad'}'>{e(c['state'])}"
        f"{' · ' + e(c['health']) if c['health'] else ''}</td><td>{c['cpu']:.0f}%</td>"
        f"<td>{_bytes(c['mem'])}</td><td>{c['restarts']}</td></tr>"
        for c in sorted(wanted, key=lambda c: (c in up, -c["cpu"]))
    )
    host_units = ", ".join(f"{n} {s}" for n, s in last["units"].items())
    alerts = (
        "".join(
            f"<li><time>{e(_when_ts(a['at'], tz))}</time> "
            f"{'<em>back</em> ' if a['state'] == 'ok' else ''}{e(a['line'])}</li>"
            for a in health["alerts"]
        )
        or "<li class='muted'>No alerts in the last 7 days.</li>"
    )
    return f"""<h2>Server now</h2>
{head}
<div class="tiles server">{"".join(tiles)}</div>
<div class="cols">
<section><h3>Answers (checked every 30 s)</h3><div class="scroll"><table>
<tr><th></th><th>Code</th><th>Time</th><th>Last 2 h</th></tr>{probes}</table></div></section>
<section><h3>Last alerts</h3><ul class="list">{alerts}</ul></section>
</div>
<details><summary><b>{len(up)} of {len(wanted)}</b> services running · host: {e(host_units)}</summary>
<div class="scroll"><table><tr><th>Service</th><th>State</th><th>CPU</th><th>Memory</th>
<th>Restarts</th></tr>{services}</table></div></details>
<p class="muted">Sample of {e(_when_ts(last["at"], tz))}. Lines: the last 2 hours.</p>"""


def _when_ts(stamp: float, tz: ZoneInfo) -> str:
    return datetime.fromtimestamp(stamp, tz).strftime("%d/%m %H:%M:%S")


def render(data: dict, tz: ZoneInfo, now: float | None = None, health: dict | None = None) -> str:
    now = time.time() if now is None else now
    e = escape
    demo_now = data["demo_now"]
    if demo_now:
        demo_tile = (
            f"<b>{demo_now.get('taken', 0)}</b><span>in the demo now, of "
            f"{demo_now.get('seats', 0)} places; {demo_now.get('waiting', 0)} waiting</span>"
        )
    else:
        demo_tile = f"<b>–</b><span>demo: {e(data['demo_error'])}</span>"
    tiles = [
        f"<div class='tile'><b>{data['online']}</b><span>reading the site now</span></div>",
        f"<div class='tile'>{demo_tile}</div>",
    ]
    totals = "".join(
        f"<tr><th>{e(name)}</th><td>{t['visitors']}</td><td>{e(t['site_time'])}</td>"
        f"<td>{t['demo']}</td><td>{e(t['demo_time'])}</td><td>{t['questions']}</td>"
        f"<td>{t['contacts']}</td></tr>"
        for name, t in data["totals"].items()
    )
    days = "".join(
        f"<tr><th>{d['day'].strftime('%a %d/%m')}</th><td>{d['visitors']}</td><td>{d['views']}</td>"
        f"<td>{e(d['site_time'])}</td><td>{d['demo']}</td><td>{e(d['demo_time'])}</td>"
        f"<td>{d['waited']}</td><td>{d['questions']}</td><td>{d['contacts']}</td></tr>"
        for d in data["days"]
    )

    def top(rows, empty):
        if not rows:
            return f"<p class='muted'>{empty}</p>"
        return (
            "<table>"
            + "".join(f"<tr><td>{e(str(k))}</td><td>{n}</td></tr>" for k, n in rows)
            + "</table>"
        )

    questions = (
        "".join(
            f"<li><time>{e(_when(q.get('time', ''), tz))}</time> {e(q.get('question', ''))}"
            + ("" if q.get("answered") else " <em>not answered from the docs</em>")
            + (" <em>offered the contact form</em>" if q.get("contact") else "")
            + "</li>"
            for q in data["questions"]
        )
        or "<li class='muted'>No questions yet.</li>"
    )
    contacts = (
        "".join(
            f"<li><time>{e(_when(c.get('time', ''), tz))}</time> <b>{e(c.get('name', ''))}</b> "
            f"&lt;{e(c.get('email', ''))}&gt;"
            + (f" · {e(c['company'])}" if c.get("company") else "")
            + f"<br>{e(c.get('need', '')[:400])}</li>"
            for c in data["contacts"]
        )
        or "<li class='muted'>No contact requests yet.</li>"
    )
    journeys = "".join(_journey_html(j, tz) for j in data["journeys"]) or (
        "<li class='muted'>No visits yet.</li>"
    )
    stamp = datetime.fromtimestamp(now, tz).strftime("%d/%m/%Y %H:%M")
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex, nofollow">
<meta http-equiv="refresh" content="30">
<title>Stats · PlantCraft</title>
<link rel="stylesheet" href="assets/stats.css">
</head>
<body>
<main>
<h1>PlantCraft stats</h1>
<p class="muted">{e(stamp)} ({e(str(tz))}). Refreshes every 30 s. No addresses are kept:
a visitor is one browser on one day.</p>
<div class="tiles">{"".join(tiles)}</div>
{health_html(health, tz, now)}
<h2>In short</h2>
<div class="scroll"><table>
<tr><th></th><th>Site visitors</th><th>Time on the site</th><th>Demo visits</th>
<th>Time in the demo</th><th>Chat questions</th><th>Contacts</th></tr>
{totals}</table></div>
<h2>Day by day</h2>
<div class="scroll"><table>
<tr><th></th><th>Visitors</th><th>Pages</th><th>Time on the site</th><th>Demo visits</th>
<th>Time in the demo</th><th>Waited in line</th><th>Questions</th><th>Contacts</th></tr>
{days}</table></div>
<p class="muted">Times are the median (and mean) per person: on the site from their first page to
the last moment one was in front; in the demo from entering to their last click.</p>
<div class="cols">
<section><h2>Came from</h2>{top(data["referrers"], "Nobody came from another site yet.")}</section>
<section><h2>Countries</h2>{top(data["countries"], "No country known yet.")}</section>
<section><h2>Pages</h2>{top(data["pages"], "No page views yet.")}</section>
<section><h2>Clicked on the site (page views that clicked)</h2>{top(data["clicks"], "No clicks yet.")}</section>
<section><h2>Demo pages (visits that opened each)</h2>{top(data["demo_pages"], "No demo page yet.")}</section>
</div>
<h2>Journeys</h2>
<p class="muted">The last 60 site visitors and demo visits, newest first; open one to see its
steps. Every step: <a href="stats/events.csv">events.csv</a> (last 14 days).</p>
<ul class="list">{journeys}</ul>
<h2>What the chat was asked</h2>
<ul class="list">{questions}</ul>
<h2>Contact requests</h2>
<ul class="list">{contacts}</ul>
</main>
</body>
</html>
"""
