"""The host's health, live: what the "Now" panel of /stats shows and what pushes an alert.

`python -m sitechat watch` runs as root beside the site (deploy/cloud/plantcraft-watch.service,
installed by vm.sh site). Every WATCH_INTERVAL seconds (default 30) it reads the machine (CPU,
memory, disk, load), the Docker containers (running, healthy, restarts, CPU and memory each),
the services on the host (cloudflared, the site), the answer of the site and of the demo (from
the host and through Cloudflare, with the time each took) and the tunnel's request counters
(cloudflared's own metrics: requests and 5xx answers). One sample is one line of
health.jsonl in SITE_DATA_DIR, kept HISTORY_HOURS; the site only reads it.

When something stays wrong (a probe failing, a container down or restarting, a full disk, the
memory or the CPU at the top, many 5xx answers) it posts once to WATCH_NTFY_URL (an ntfy topic:
a push on the phone with the ntfy app; WATCH_EMAIL also mails it), and once more when it is
back. Alerts are kept in alerts.jsonl. Nothing here holds a visitor's address.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

HISTORY_HOURS = 24
STALE_SECONDS = 120
METRICS_PORTS = range(20241, 20246)  # where cloudflared serves its metrics when not told
USER_AGENT = "PlantCraft-watch/1"

# How long (in samples) a problem lasts before it alerts: one slow answer is not an outage.
SAMPLES_TO_ALERT = {
    "probe": 2,
    "container": 2,
    "restart": 1,
    "unit": 2,
    "disk": 1,
    "memory": 4,
    "cpu": 10,
    "errors": 1,
    "slow": 4,
}
DISK_FREE_MIN = 10.0  # % of the disk
MEMORY_FREE_MIN = 8.0  # % of the memory available
CPU_MAX = 90.0
SLOW_SECONDS = 5.0
ERRORS_MAX = 5.0  # % of the tunnel's answers that were 5xx over the last 5 minutes
ERRORS_MIN_REQUESTS = 30


# --- reading the machine ------------------------------------------------------------------------


def _cpu_times() -> tuple[int, int]:
    """(busy, total) jiffies since boot, from /proc/stat."""
    with open("/proc/stat", encoding="ascii") as f:
        parts = [int(x) for x in f.readline().split()[1:]]
    idle = parts[3] + (parts[4] if len(parts) > 4 else 0)
    return sum(parts) - idle, sum(parts)


def _memory() -> dict:
    info = {}
    with open("/proc/meminfo", encoding="ascii") as f:
        for line in f:
            key, _, rest = line.partition(":")
            info[key] = int(rest.split()[0]) * 1024
    total, available = info.get("MemTotal", 0), info.get("MemAvailable", 0)
    return {
        "total": total,
        "used": total - available,
        "swap_used": info.get("SwapTotal", 0) - info.get("SwapFree", 0),
    }


def _run(cmd: list[str], timeout: float = 20) -> str:
    try:
        return subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout, check=False
        ).stdout
    except (OSError, subprocess.TimeoutExpired):
        return ""


def _size(text: str) -> float:
    """Docker's "1.5GiB" / "200MiB" / "12kB" in bytes."""
    m = re.match(r"([\d.]+)\s*([KMGT]?)i?B", text.strip(), re.I)
    if not m:
        return 0.0
    return float(m.group(1)) * 1024 ** "_KMGT".index((m.group(2) or "_").upper())


def containers() -> list[dict]:
    """Every container: name, state, health, restarts, whether it should be up, CPU and memory."""
    ids = _run(["docker", "ps", "-aq"]).split()
    if not ids:
        return []
    out = {}
    for item in json.loads(_run(["docker", "inspect", *ids]) or "[]"):
        state = item.get("State", {})
        labels = item.get("Config", {}).get("Labels") or {}
        name = labels.get("com.docker.compose.service") or item.get("Name", "").lstrip("/")
        out[item.get("Name", "").lstrip("/")] = {
            "name": name,
            "state": state.get("Status", ""),
            "health": (state.get("Health") or {}).get("Status", ""),
            "restarts": item.get("RestartCount", 0),
            # A one-off container (a backup, an update) is not one that must stay up.
            "wanted": (item.get("HostConfig", {}).get("RestartPolicy") or {}).get("Name", "no")
            not in ("", "no"),
            "cpu": 0.0,
            "mem": 0.0,
        }
    for line in _run(["docker", "stats", "--no-stream", "--format", "{{json .}}"]).splitlines():
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if row.get("Name") in out:
            out[row["Name"]]["cpu"] = float(row.get("CPUPerc", "0").rstrip("%") or 0)
            out[row["Name"]]["mem"] = _size(row.get("MemUsage", "").split("/")[0])
    return sorted(out.values(), key=lambda c: c["name"])


def units(names: list[str]) -> dict[str, str]:
    return {n: _run(["systemctl", "is-active", n], 5).strip() or "unknown" for n in names}


def probe(name: str, url: str, resolve: str = "") -> dict:
    """One page asked for with curl: its HTTP code and how long it took (code 0: no answer)."""
    cmd = [
        "curl",
        "-sk",
        "-o",
        "/dev/null",
        "-m",
        "15",
        "-A",
        USER_AGENT,
        "-w",
        "%{http_code} %{time_total}",
    ]
    if resolve:
        cmd += ["--resolve", resolve]
    code, _, seconds = (_run([*cmd, url], 20).strip() or "0 15").partition(" ")
    return {"name": name, "url": url, "code": int(code or 0), "seconds": float(seconds or 15)}


def tunnel_counters() -> dict | None:
    """cloudflared's request counters (all the hostnames together), or None without them."""
    for port in METRICS_PORTS:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/metrics", timeout=2) as r:
                text = r.read().decode()
        except Exception:  # noqa: BLE001 - try the next port
            continue
        if "cloudflared_tunnel" not in text:
            continue
        total = errors = 0.0
        for line in text.splitlines():
            if line.startswith("cloudflared_tunnel_total_requests"):
                total = float(line.split()[-1])
            m = re.match(
                r'cloudflared_tunnel_response_by_code\{status_code="(\d+)"\}\s+(\S+)', line
            )
            if m and m.group(1).startswith("5"):
                errors += float(m.group(2))
        return {"requests": total, "errors": errors}
    return None


@dataclass
class Watch:
    site_url: str = "http://127.0.0.1:8090/"
    site_host: str = ""
    demo_host: str = ""
    units: list[str] = field(default_factory=lambda: ["cloudflared", "plantcraft-site"])
    _cpu: tuple[int, int] | None = None

    @classmethod
    def from_env(cls) -> "Watch":
        env = os.environ
        return cls(
            site_host=env.get("WATCH_SITE_HOST", "").strip(),
            demo_host=env.get("WATCH_DEMO_HOST", "").strip(),
        )

    def probes(self) -> list[dict]:
        out = [probe("site (host)", self.site_url)]
        if self.demo_host:
            out.append(
                probe(
                    "demo (host)", f"https://{self.demo_host}/", f"{self.demo_host}:443:127.0.0.1"
                )
            )
        if self.site_host:
            out.append(probe("site (internet)", f"https://{self.site_host}/"))
        if self.demo_host:
            out.append(probe("demo (internet)", f"https://{self.demo_host}/"))
        return out

    def sample(self) -> dict:
        busy, total = _cpu_times()
        cpu = None
        if self._cpu and total > self._cpu[1]:
            cpu = round(100 * (busy - self._cpu[0]) / (total - self._cpu[1]), 1)
        self._cpu = (busy, total)
        disk = shutil.disk_usage("/")
        with open("/proc/loadavg", encoding="ascii") as f:
            load = [float(x) for x in f.read().split()[:3]]
        return {
            "at": time.time(),
            "cpu": cpu,
            "cores": os.cpu_count() or 1,
            "load": load,
            "memory": _memory(),
            "disk": {"total": disk.total, "free": disk.free},
            "containers": containers(),
            "units": units(self.units),
            "probes": self.probes(),
            "tunnel": tunnel_counters(),
        }


# --- what is wrong ------------------------------------------------------------------------------


def problems(sample: dict, before: dict | None, recent: list[dict]) -> dict[str, tuple[str, str]]:
    """Every problem in this sample: key -> (kind, the line to say). `before` is the sample
    before it (restarts), `recent` the last 5 minutes (the tunnel's 5xx share)."""
    found: dict[str, tuple[str, str]] = {}
    for p in sample["probes"]:
        if not 200 <= p["code"] < 400:
            said = f"HTTP {p['code']}" if p["code"] else "no answer in 15 s"
            found[f"probe:{p['name']}"] = ("probe", f"{p['name']} {said} ({p['url']})")
        elif p["seconds"] >= SLOW_SECONDS:
            found[f"slow:{p['name']}"] = ("slow", f"{p['name']} slow: {p['seconds']:.1f} s")
    restarts = {c["name"]: c["restarts"] for c in (before or {}).get("containers", [])}
    for c in sample["containers"]:
        if not c["wanted"]:
            continue
        if c["state"] != "running":
            found[f"container:{c['name']}"] = ("container", f"{c['name']} is {c['state']}")
        elif c["health"] == "unhealthy":
            found[f"container:{c['name']}"] = ("container", f"{c['name']} is unhealthy")
        elif c["restarts"] > restarts.get(c["name"], c["restarts"]):
            found[f"restart:{c['name']}"] = ("restart", f"{c['name']} restarted")
    for name, state in sample["units"].items():
        if state != "active":
            found[f"unit:{name}"] = ("unit", f"{name} is {state}")
    disk_free = 100 * sample["disk"]["free"] / max(sample["disk"]["total"], 1)
    if disk_free < DISK_FREE_MIN:
        found["disk"] = ("disk", f"disk {disk_free:.0f}% free")
    mem = sample["memory"]
    mem_free = 100 * (mem["total"] - mem["used"]) / max(mem["total"], 1)
    if mem_free < MEMORY_FREE_MIN:
        found["memory"] = ("memory", f"memory {mem_free:.0f}% free")
    if sample["cpu"] is not None and sample["cpu"] >= CPU_MAX:
        found["cpu"] = ("cpu", f"CPU {sample['cpu']:.0f}%")
    rate = traffic(recent + [sample])
    if rate and rate["requests"] >= ERRORS_MIN_REQUESTS and rate["error_pct"] >= ERRORS_MAX:
        found["errors"] = (
            "errors",
            f"{rate['error_pct']:.0f}% of answers were errors (5xx) in the last 5 min",
        )
    return found


def traffic(samples: list[dict]) -> dict | None:
    """Requests and 5xx through the tunnel over the samples given (counters reset on restart)."""
    points = [(s["at"], s["tunnel"]) for s in samples if s.get("tunnel")]
    if len(points) < 2:
        return None
    requests = errors = 0.0
    for (_, a), (_, b) in zip(points, points[1:]):
        # A smaller counter: cloudflared restarted and counts from zero again.
        requests += (
            b["requests"] - a["requests"] if b["requests"] >= a["requests"] else b["requests"]
        )
        errors += b["errors"] - a["errors"] if b["errors"] >= a["errors"] else b["errors"]
    minutes = max((points[-1][0] - points[0][0]) / 60, 1e-9)
    return {
        "requests": requests,
        "per_minute": requests / minutes,
        "errors": errors,
        "error_pct": 100 * errors / requests if requests else 0.0,
    }


class Alerts:
    """Turns problems that last into one alert each, and one more when they are gone."""

    def __init__(self, notify):
        self.notify = notify
        self.counts: dict[str, int] = {}
        self.open: dict[str, str] = {}

    def update(self, found: dict[str, tuple[str, str]]) -> list[dict]:
        sent = []
        for key, (kind, line) in found.items():
            self.counts[key] = self.counts.get(key, 0) + 1
            if key not in self.open and self.counts[key] >= SAMPLES_TO_ALERT[kind]:
                self.open[key] = line
                sent.append({"key": key, "state": "problem", "line": line})
        for key in list(self.counts):
            if key not in found:
                del self.counts[key]
                if key in self.open:
                    sent.append({"key": key, "state": "ok", "line": self.open.pop(key)})
        if sent:
            self.notify(sent)
        return sent


# --- telling the owner --------------------------------------------------------------------------


@dataclass
class Notifier:
    url: str = ""  # an ntfy topic, e.g. https://ntfy.sh/plantcraft-<random>
    email: str = ""
    site_host: str = ""

    def __call__(self, alerts: list[dict]) -> None:
        bad = [a for a in alerts if a["state"] == "problem"]
        good = [a for a in alerts if a["state"] == "ok"]
        lines = [f"PROBLEM: {a['line']}" for a in bad] + [f"OK again: {a['line']}" for a in good]
        title = "PlantCraft: " + ("something is wrong" if bad else "back to normal")
        self.send(title, "\n".join(lines), urgent=bool(bad))

    def send(self, title: str, text: str, urgent: bool = False) -> bool:
        print(f"{title}\n{text}", file=sys.stderr, flush=True)
        if not self.url:
            return False
        headers = {
            "Title": title,
            "Priority": "high" if urgent else "default",
            "Tags": "rotating_light" if urgent else "white_check_mark",
            "User-Agent": USER_AGENT,
        }
        if self.site_host:
            headers["Click"] = f"https://{self.site_host}/stats"
        if self.email:
            headers["Email"] = self.email
        request = urllib.request.Request(self.url, data=text.encode(), headers=headers)
        try:
            urllib.request.urlopen(request, timeout=10).close()
            return True
        except Exception as exc:  # noqa: BLE001 - the watch goes on; the alert is in the log
            print(f"alert not sent: {exc}", file=sys.stderr, flush=True)
            return False


# --- the files ----------------------------------------------------------------------------------


def _append(path: Path, row: dict) -> None:
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, separators=(",", ":")) + "\n")


def read(path: Path, since: float = 0.0) -> list[dict]:
    """The rows from `since` on, oldest first (read from the end: the file holds a day)."""
    if not path.exists():
        return []
    out = []
    for line in reversed(path.read_text(encoding="utf-8").splitlines()):
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if row.get("at", 0) < since:
            break
        out.append(row)
    return out[::-1]


def _trim(path: Path, keep_from: float) -> None:
    rows = read(path, keep_from)
    tmp = path.with_suffix(".tmp")
    tmp.write_text("".join(json.dumps(r, separators=(",", ":")) + "\n" for r in rows))
    _share(tmp)
    tmp.replace(path)


def _share(path: Path) -> None:
    """Readable by the site's group (the folder is the site's; this runs as root)."""
    try:
        os.chmod(path, 0o640)
        os.chown(path, -1, path.parent.stat().st_gid)
    except OSError:
        pass


def run(data_dir: Path, interval: float = 30.0) -> None:
    watch = Watch.from_env()
    notify = Notifier(
        os.environ.get("WATCH_NTFY_URL", "").strip(),
        os.environ.get("WATCH_EMAIL", "").strip(),
        watch.site_host,
    )
    history, alerts_file = data_dir / "health.jsonl", data_dir / "alerts.jsonl"

    def record(sent: list[dict]) -> None:
        for alert in sent:
            _append(alerts_file, {"at": time.time(), **alert})
        _share(alerts_file)
        notify(sent)

    alerts = Alerts(record)
    watch.sample()  # the CPU is a difference: the first sample only starts it
    before = None
    recent: list[dict] = []
    notify.send("PlantCraft watch started", "Alerts for the site and the demo will come here.")
    last_trim = 0.0
    while True:
        time.sleep(interval)
        sample = watch.sample()
        _append(history, sample)
        _share(history)
        alerts.update(problems(sample, before, recent))
        recent = [s for s in recent if s["at"] >= sample["at"] - 300] + [sample]
        before = sample
        if sample["at"] - last_trim > 3600:
            _trim(history, sample["at"] - HISTORY_HOURS * 3600)
            last_trim = sample["at"]


# --- the "Now" panel ----------------------------------------------------------------------------


def now(data_dir: Path, at: float | None = None) -> dict:
    """What /stats shows on top: the last sample, the last 2 hours of it and the last alerts."""
    at = time.time() if at is None else at
    samples = read(data_dir / "health.jsonl", at - 2 * 3600)
    # None in the last 2 hours: the last one there is, to say how old it is.
    last = samples[-1] if samples else (read(data_dir / "health.jsonl", 0.0)[-1:] or [None])[0]
    open_alerts: dict[str, dict] = {}
    alerts = read(data_dir / "alerts.jsonl", at - 7 * 86400)
    for alert in alerts:
        if alert["state"] == "problem":
            open_alerts[alert["key"]] = alert
        else:
            open_alerts.pop(alert["key"], None)
    return {
        "last": last,
        "stale": last is None or at - last["at"] > STALE_SECONDS,
        "traffic": traffic([s for s in samples if s["at"] >= at - 300]),
        "series": samples,
        "open": list(open_alerts.values()),
        "alerts": alerts[-15:][::-1],
    }
