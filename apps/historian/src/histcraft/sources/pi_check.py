"""First-day diagnosis of a PI Web API source: the logic of ``histcraft pi check``.

Walks the path a read takes (proxy, DNS, TCP, TLS, authentication, Data
Archive, each tag) and says, for every step, what answered or what to fix. The
same report can be written to a Markdown file to send to whoever supports the
installation. Ported from PlantCraft (``industrial_data/pi_check.py``); the
per-loop coverage checks stay with the apps that know the loops.
"""

from __future__ import annotations

import shutil
import socket
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

import pandas as pd
import requests

from histcraft.i18n import t
from histcraft.sources.config import SourceConfig, from_source
from histcraft.sources.pi_web_api import PiError, PiWebApiSource

OK, WARN, FAIL = "ok", "warning", "fail"
_MARK = {OK: "✓", WARN: "!", FAIL: "✗"}


@dataclass
class Check:
    step: str
    status: str
    detail: str


@dataclass
class Report:
    source: str
    checks: list[Check] = field(default_factory=list)
    tags: list[dict[str, Any]] = field(default_factory=list)

    def add(self, step: str, status: str, detail: str) -> Check:
        check = Check(step, status, detail)
        self.checks.append(check)
        return check

    @property
    def failed(self) -> bool:
        return any(check.status == FAIL for check in self.checks)

    def markdown(self) -> str:
        lines = [
            "# " + t("PI diagnosis · {source}", source=self.source),
            "",
            t("Generated at {time}.", time=f"{datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC")
            + " "
            + (
                "**"
                + (t("There are failures to fix.") if self.failed else t("Ready for the pilot."))
                + "**"
            ),
            "",
            "| | " + t("Step") + " | " + t("Result") + " |",
            "| --- | --- | --- |",
        ]
        lines += [f"| {_MARK[c.status]} | {c.step} | {_cell(c.detail)} |" for c in self.checks]
        if self.tags:
            lines += [
                "",
                "## Tags",
                "",
                "| | "
                + " | ".join(
                    [
                        t("Tag"),
                        t("Type"),
                        t("Unit"),
                        t("Events"),
                        t("Bad"),
                        t("Last value"),
                        t("Note"),
                    ]
                )
                + " |",
                "| --- | --- | --- | --- | ---: | ---: | --- | --- |",
            ]
            lines += [
                f"| {_MARK[tag['status']]} | {tag['tag']} | {tag.get('type', '')} | {tag.get('unit', '')} "
                f"| {tag.get('events', '')} | {tag.get('bad', '')} | {tag.get('last', '')} "
                f"| {_cell(tag.get('note', ''))} |"
                for tag in self.tags
            ]
        return "\n".join(lines) + "\n"

    def text(self) -> str:
        width = max(len(c.step) for c in self.checks) if self.checks else 10
        lines = [t("PI diagnosis · {source}", source=self.source), ""]
        lines += [f" {_MARK[c.status]} {c.step:<{width}}  {c.detail}" for c in self.checks]
        problems = [tag for tag in self.tags if tag["status"] != OK]
        if problems:
            lines += ["", t("Tags with problems:")]
            lines += [f" {_MARK[tag['status']]} {tag['tag']}: {tag['note']}" for tag in problems]
        verdict = t("there are failures to fix.") if self.failed else t("ready for the pilot.")
        lines += ["", t("Result: {verdict}", verdict=verdict)]
        return "\n".join(lines)


def run_check(
    source: dict[str, Any],
    password: str,
    tags: list[str],
    *,
    hours: float = 48.0,
) -> Report:
    """Check the Historian source row ``source`` and read ``tags`` over the last ``hours``."""

    report = Report(str(source.get("name") or source.get("id") or "PI"))
    if source.get("kind") != "pi_web_api":
        report.add(
            t("Source"),
            FAIL,
            t("The source is {type}, not PI Web API.", type=source.get("kind")),
        )
        return report
    try:
        config: SourceConfig = from_source(source, password)
    except ValueError as exc:
        report.add(t("Settings"), FAIL, str(exc))
        return report
    config.tags = list(tags)
    if not config.server:
        report.add(t("Settings"), FAIL, t("The PI Web API source needs the server name."))
        return report

    url = urlparse(config.base_url)
    host = url.hostname or ""
    port = url.port or (443 if url.scheme == "https" else 80)
    tls = (
        t("CA at {path}", path=config.ca_bundle)
        if config.ca_bundle
        else (t("certificate verified") if config.verify_ssl else t("certificate verification OFF"))
    )
    report.add(
        t("Settings"),
        OK if config.verify_ssl or config.ca_bundle else WARN,
        t(
            "{url} · server {server} · {auth} · {tls} · read {mode} · {tags} tags",
            url=config.base_url,
            server=config.server,
            auth=config.auth_type,
            tls=tls,
            mode=config.read_mode,
            tags=len(config.tags),
        ),
    )

    proxies = requests.utils.get_environ_proxies(config.base_url)
    proxy = proxies.get(url.scheme) or proxies.get("all")
    if proxy:
        report.add(
            "Proxy",
            WARN,
            t(
                "Calls will go through the proxy {proxy}. An internal PI Web API is usually kept out "
                "of it: add {host} to NO_PROXY.",
                proxy=proxy,
                host=host,
            ),
        )
    else:
        report.add("Proxy", OK, t("Direct access, no proxy."))

    try:
        addresses = sorted({info[4][0] for info in socket.getaddrinfo(host, port)})
        report.add("DNS", OK, f"{host} → {', '.join(addresses)}")
    except OSError as exc:
        report.add(
            "DNS",
            FAIL,
            t("{host} does not resolve: {error}. Check the corporate DNS.", host=host, error=exc),
        )
        return report

    if not proxy:
        started = time.perf_counter()
        try:
            socket.create_connection((host, port), timeout=config.timeout_seconds).close()
            ms = (time.perf_counter() - started) * 1000
            report.add(
                t("Network"), OK, t("Port {port} open ({ms} ms).", port=port, ms=f"{ms:.0f}")
            )
        except OSError as exc:
            report.add(
                t("Network"),
                FAIL,
                t(
                    "Port {port} of {host} closed or filtered: {error}.",
                    port=port,
                    host=host,
                    error=exc,
                ),
            )
            return report

    if config.auth_type == "kerberos":
        _kerberos(report)

    pi = PiWebApiSource(config)
    started = time.perf_counter()
    try:
        server = pi.data_server()
    except Exception as exc:
        report.add("PI Web API", FAIL, str(exc))
        return report
    ms = (time.perf_counter() - started) * 1000
    report.add(
        "PI Web API",
        OK,
        t(
            "Server {name} (PI Data Archive {version}) answered in {ms} ms.",
            name=server.get("Name"),
            version=server.get("ServerVersion", "?"),
            ms=f"{ms:.0f}",
        ),
    )
    try:
        user = pi.user()
        report.add(
            t("User"),
            OK,
            f"{user.get('Name')} ({user.get('IdentityType', t('identity'))}"
            + (f", {user['ImpersonationLevel']}" if user.get("ImpersonationLevel") else "")
            + ")",
        )
    except PiError as exc:
        report.add(t("User"), WARN, t("Could not read system/userinfo: {error}", error=exc))

    if config.tags:
        _tags(report, pi, hours)
    return report


def _kerberos(report: Report) -> None:
    try:
        import requests_kerberos  # noqa: F401
    except ImportError:
        report.add(
            "Kerberos",
            FAIL,
            t("Package requests-kerberos missing: python3 -m pip install -e '.[pi]'."),
        )
        return
    klist = shutil.which("klist")
    if not klist:
        report.add("Kerberos", OK, t("Library present (klist not found to check the ticket)."))
        return
    found = subprocess.run([klist, "-s"], capture_output=True, timeout=10).returncode == 0
    if found:
        principal = subprocess.run([klist], capture_output=True, text=True, timeout=10).stdout
        line = next((ln for ln in principal.splitlines() if "principal" in ln.lower()), "")
        report.add("Kerberos", OK, t("Valid ticket. {principal}", principal=line.strip()))
    else:
        report.add(
            "Kerberos",
            WARN,
            t(
                "No valid ticket (klist -s). Create one with kinit, or with the service user's "
                "keytab: kinit -kt /etc/histcraft/svc.keytab user@DOMAIN."
            ),
        )


def _tags(report: Report, source: PiWebApiSource, hours: float) -> None:
    config = source.config
    end = pd.Timestamp.now(tz="UTC")
    start = end - pd.Timedelta(hours=hours)
    local_now = end.tz_convert(config.timezone).tz_localize(None)

    def inspect(tag: str) -> dict[str, Any]:
        row: dict[str, Any] = {"tag": tag, "status": OK, "note": ""}
        try:
            point = source.point(tag)
        except PiError as exc:
            return {**row, "status": FAIL, "note": str(exc)}
        row["type"] = point.get("PointType", "")
        row["unit"] = point.get("EngineeringUnits", "")
        step = bool(point.get("Step"))
        try:
            values = source.recorded(tag, start, end)
        except PiError as exc:
            return {**row, "status": FAIL, "note": t("read failed: {error}", error=exc)}
        good = values.dropna()
        row["events"] = len(values)
        row["bad"] = f"{(1 - len(good) / len(values)):.0%}" if len(values) else "—"
        if good.empty:
            try:
                before = source.value_before(tag, start).dropna()
            except PiError:
                before = pd.Series(dtype=object)
            if before.empty:
                return {
                    **row,
                    "status": FAIL,
                    "note": t("no valid value in the last {hours} h", hours=f"{hours:g}"),
                }
            row["last"] = t(
                "{value} at {time}",
                value=_fmt(before.iloc[-1]),
                time=f"{before.index[-1]:%d/%m %H:%M}",
            )
            note = t("no change in the period (normal for SP and mode)")
            return {**row, "status": OK if step else WARN, "note": note}
        age = local_now - good.index[-1]
        row["last"] = t("{value}, {age} ago", value=_fmt(good.iloc[-1]), age=_age(age))
        notes = []
        if len(good) < len(values) * 0.9:
            notes.append(t("more than 10% of the values with bad quality"))
        if age > pd.Timedelta(hours=1) and not step:
            notes.append(t("no new value for {age}", age=_age(age)))
        if notes:
            row["status"] = WARN
            row["note"] = "; ".join(notes)
        return row

    started = time.perf_counter()
    workers = max(1, min(config.max_workers, len(config.tags)))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        report.tags = list(pool.map(inspect, config.tags))
    elapsed = time.perf_counter() - started
    failed = [tag for tag in report.tags if tag["status"] == FAIL]
    warned = [tag for tag in report.tags if tag["status"] == WARN]
    events = sum(tag.get("events", 0) or 0 for tag in report.tags)
    status = FAIL if failed else (WARN if warned else OK)
    report.add(
        "Tags",
        status,
        t("{read} of {total} read", read=len(report.tags) - len(failed), total=len(report.tags))
        + (t(", {count} with warnings", count=len(warned)) if warned else "")
        + t(
            "; {events} events over {hours} h read in {seconds} s.",
            events=events,
            hours=f"{hours:g}",
            seconds=f"{elapsed:.1f}",
        ),
    )


def _fmt(value: Any) -> str:
    return f"{value:.5g}" if isinstance(value, float) else str(value)


def _age(delta: pd.Timedelta) -> str:
    minutes = int(delta.total_seconds() // 60)
    if minutes < 60:
        return f"{max(minutes, 0)} min"
    if minutes < 48 * 60:
        return f"{minutes // 60} h"
    return t("{count} days", count=minutes // 1440)


def _cell(text: str) -> str:
    return str(text).replace("|", "\\|").replace("\n", " ")
