"""Every time a person reads is on their clock (owner, 2026-10-23 and 2026-10-27: "Deixe tudo no
time zone do usuário"): stored and computed in UTC, shown in the installation's zone or the one
the person chose in their Preferences.

This reads the interfaces of every app and the texts the servers write for people, and fails on
the ways a UTC time slipped onto a screen before:

- a time cut out of ``toISOString()`` (that is UTC's wall clock);
- a date written with ``timeZone: "UTC"`` (a due day "YYYY-MM-DD" may: mark it ``utc-day``);
- a time of day written by ``toLocaleString``/``toLocaleTimeString`` without a ``timeZone`` (it
  follows the device, not the person's choice; FullCalendar's pages say ``device clock``);
- "UTC" written into a sentence or a document a person reads (``t("... UTC")``,
  ``strftime("... UTC")``).

``ui/src/timeZone.ts`` is where UTC becomes local time, so it is the one place left out.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INTERFACES = [ROOT / "frontend" / "src", ROOT / "ui" / "src"] + sorted(
    (ROOT / "apps").glob("*/frontend/src")
)
SERVERS = [ROOT / "processcraft", ROOT / "sdk" / "python" / "plantcraft_sdk"] + sorted(
    (ROOT / "apps").glob("*/src")
)
CONVERTER = ROOT / "ui" / "src" / "timeZone.ts"

ISO_CUT = re.compile(r"toISOString\(\)\s*\.\s*(slice|substring|substr|replace)\(")
UTC_OPTION = re.compile(r"timeZone:\s*[\"']UTC[\"']")
LOCALE_TIME = re.compile(r"\.toLocale(?:Time)?String\(([^;]*)")
TIME_PARTS = re.compile(r"\b(hour|minute|timeStyle)\b")
UTC_TEXT = re.compile(r"""(\bt\(\s*|strftime\()\s*f?["'][^"']*\bUTC\b""")


def _interface_files() -> list[Path]:
    found = []
    for folder in INTERFACES:
        for path in folder.rglob("*.ts*"):
            name = path.name
            if ".test." in name or name.endswith(".d.ts") or "node_modules" in path.parts:
                continue
            if path != CONVERTER:
                found.append(path)
    return found


def _lines(path: Path) -> list[tuple[int, str]]:
    return list(enumerate(path.read_text(encoding="utf-8").splitlines(), start=1))


def test_the_interfaces_never_show_utc_s_wall_clock():
    wrong = []
    for path in _interface_files():
        lines = _lines(path)
        for number, line in lines:
            where = f"{path.relative_to(ROOT)}:{number}"
            before = " ".join(text for _, text in lines[max(0, number - 4) : number - 1])
            if ISO_CUT.search(line) and "file name" not in line:
                wrong.append(
                    f"{where}: a time cut from toISOString() is UTC; use wallClock/localOf"
                )
            if UTC_OPTION.search(line) and "utc-day" not in line + before:
                wrong.append(f'{where}: timeZone "UTC"; use displayTimeZone() (or mark a utc-day)')
            for match in LOCALE_TIME.finditer(line):
                options = match.group(1)
                if TIME_PARTS.search(options) and "timeZone" not in options:
                    if "device clock" not in line + before:
                        wrong.append(f"{where}: a time of day without timeZone: displayTimeZone()")
    assert not wrong, "\n".join(wrong)


def test_the_servers_never_write_utc_into_what_people_read():
    wrong = []
    for folder in SERVERS:
        for path in folder.rglob("*.py"):
            if "tests" in path.parts:
                continue
            for number, line in _lines(path):
                if UTC_TEXT.search(line):
                    wrong.append(
                        f"{path.relative_to(ROOT)}:{number}: 'UTC' in a text for people; write the "
                        "time on the plant's clock (processcraft.config.plant_clock, "
                        "plantcraft_sdk.utc.local_text)"
                    )
    assert not wrong, "\n".join(wrong)


def test_the_checks_catch_what_they_look_for():
    assert ISO_CUT.search("date.toISOString().slice(0, 16)")
    assert UTC_OPTION.search('{ dateStyle: "medium", timeZone: "UTC" }')
    match = LOCALE_TIME.search('d.toLocaleTimeString(locale, { hour: "2-digit" })')
    assert match and TIME_PARTS.search(match.group(1))
    assert UTC_TEXT.search('t("no news since {time} UTC", time=since)')
    assert UTC_TEXT.search('now.strftime(f"{fmt} %H:%M UTC")')
