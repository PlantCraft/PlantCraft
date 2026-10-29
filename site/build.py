"""Builds PlantCraft's site into dist/: the page, its assets and fonts, and the chat's knowledge.

    python build.py [--owner PlantCraft] [--bundle processcraft-0.5.0-linux-amd64-bundle] [--draft]
                    [--demo-url https://demo.example] [--contact team@example] [--security sec@example] [--noindex]

The page is page/template.html with the app cards, links and bundle name filled in; the app
marks come from docs/images/apps and the fonts from ui/src/fonts, so the site uses the suite's
own. knowledge.json is the public documentation listed in knowledge/sources.toml, cut into
passages, which the chat answers from. Nothing in dist/ is secret: it is all served as it is.
Beside the page: privacy.html (what the site and the demo keep), robots.txt and
.well-known/security.txt (RFC 9116). --noindex keeps search engines away (a site online for tests
before its launch); --demo-url adds the live demo's button.
"""

from __future__ import annotations

import argparse
import hashlib
import re
import shutil
import sys
from datetime import datetime, timedelta, timezone
from html import escape
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))

from sitechat.knowledge import Knowledge  # noqa: E402

MARKS = ROOT / "docs/images/apps"
FONTS = ROOT / "ui/src/fonts"

# (mark, name, category, what it does): the names people see (docs/glossary.md).
APPS = [
    (
        "desk",
        "Desk",
        "Your day",
        "What needs you, actions, calendar, to-do, notes and the team on shift.",
    ),
    (
        "histcraft",
        "Historian",
        "Data",
        "Collects and archives the plant's signals from OPC UA, PI Web API, MQTT, Modbus TCP, SQL and CSV, read-only to the plant.",
    ),
    (
        "linkcraft",
        "Analytics",
        "Signals and assets",
        "Algorithms of blocks that watch every signal and asset and say what is wrong and why.",
    ),
    (
        "alarmcraft",
        "Alarms",
        "Operations",
        "Alarms and alerts, shelving, history and alarm performance.",
    ),
    (
        "dashcraft",
        "View",
        "Dashboards and diagrams",
        "Dashboards, process diagrams, trends and scheduled reports, shared with the shift.",
    ),
    (
        "modelcraft",
        "Models",
        "Modelling",
        "Block-diagram models with Modelica underneath: simulations, studies, optimization and FMUs.",
    ),
    (
        "doccraft",
        "Documents",
        "Plant knowledge",
        "Manuals, control narratives and datasheets, searched offline and cited by the assistant.",
    ),
]

# The clips at the top of the page (page/assets/clips/<name>.webm, .mp4 and .jpg, recorded from
# the demo by record_clips.py): name, tab label, what it shows.
CLIPS = [
    ("dashboards", "Dashboards", "View: a dashboard of the unit, shared with the shift."),
    ("process", "Process", "View: the plant's process diagram with live values."),
    ("reports", "Reports", "View: a scheduled report of the unit, as it is sent by e-mail."),
    (
        "analytics",
        "Analytics",
        "Analytics: an algorithm's block diagram and the results on every asset.",
    ),
    ("alarms", "Alarms", "Alarms: the alarms of the plant, their history and performance."),
    ("sources", "Sources", "PlantCraft: the plant's data sources, read-only, and their signals."),
    ("desk", "Desk", "Desk: messages, actions, calendar and what needs you today."),
]


def mark(app: str, size: int = 44) -> str:
    svg = (MARKS / f"{app}.svg").read_text()
    svg = re.sub(r"<title>.*?</title>", "", svg)
    svg = re.sub(r' width="64" height="64"', f' width="{size}" height="{size}"', svg)
    svg = re.sub(r' aria-label="[^"]*"', "", svg).replace(' role="img"', "")
    return svg.replace("<svg ", '<svg aria-hidden="true" focusable="false" ', 1)


def cards() -> str:
    return "\n".join(
        f'      <article class="app"><div class="app-head">{mark(app)}<div><h3>{name}</h3>'
        f'<p class="cat">{cat}</p></div></div><p>{text}</p></article>'
        for app, name, cat, text in APPS
    )


def showcase() -> str:
    """One video and one button per clip under it; showcase.js swaps the video's sources (a
    single video element, so speed-control browser add-ons draw one control, not seven)."""
    n, _, alt = CLIPS[0]
    tabs = "".join(
        f'<button type="button" aria-pressed="{"true" if i == 0 else "false"}" '
        f'data-webm="assets/clips/{name}.webm" data-mp4="assets/clips/{name}.mp4" '
        f'data-poster="assets/clips/{name}.jpg" data-label="{escape(text)}">'
        f'<span class="clip-name">{label}</span><span class="clip-fill"></span></button>'
        for i, (name, label, text) in enumerate(CLIPS)
    )
    return (
        '    <figure class="showcase" aria-label="PlantCraft at work">\n'
        '      <div class="shot"><video muted playsinline preload="auto" '
        f'poster="assets/clips/{n}.jpg" aria-label="{escape(alt)}" width="1440" height="900">'
        f'<source src="assets/clips/{n}.webm" type="video/webm">'
        f'<source src="assets/clips/{n}.mp4" type="video/mp4"></video></div>\n'
        '      <div class="clip-bar">'
        '<button type="button" class="clip-play" aria-label="Pause">'
        '<svg aria-hidden="true" viewBox="0 0 16 16" width="16" height="16">'
        '<path class="i-pause" d="M4 3h3v10H4zM9 3h3v10H9z"/>'
        '<path class="i-play" d="M4 2.5v11l9.5-5.5z"/></svg></button>'
        '<input class="clip-seek" type="range" min="0" max="1000" value="0" step="1" '
        'aria-label="Position in the clip"></div>\n'
        f'      <div class="clip-tabs" aria-label="Parts of the suite">{tabs}</div>\n'
        "    </figure>"
    )


def _versioned(html: str) -> str:
    """Each stylesheet, script, clip and poster with ?v=<its hash>: a cache in front of the site
    (Cloudflare keeps them for hours) never serves a new page with an old file."""

    def stamp(match: re.Match) -> str:
        digest = hashlib.sha256((HERE / "page" / match[1]).read_bytes()).hexdigest()[:10]
        return f'"{match[1]}?v={digest}"'

    return re.sub(r'"(assets/[\w./-]+\.(?:css|js|webm|mp4|jpg))"', stamp, html)


def _fill(html: str, values: dict[str, str]) -> str:
    for key, value in values.items():
        html = html.replace(key, value)
    assert "%%" not in html, "a placeholder is left in the page"
    return html


def build(
    out: Path,
    owner: str,
    bundle: str,
    draft: bool,
    demo_url: str = "",
    contact: str = "",
    noindex: bool = False,
    security: str = "",
) -> Path:
    gh = f"https://github.com/{owner}/PlantCraft"
    banner = '<p class="draft">Draft: not published yet</p>' if draft else ""
    demo = (
        f'<a class="btn primary" href="{escape(demo_url)}">Try the live demo</a>'
        if demo_url
        else ""
    )
    demo_float = (
        f'<a class="demo-launch" href="{escape(demo_url)}"><svg aria-hidden="true" viewBox="0 0 20 20"'
        ' width="16" height="16"><path d="M6 4v12l10-6z" fill="currentColor"/></svg>Live demo</a>'
        if demo_url
        else ""
    )
    if contact:
        write = f'write to <a href="mailto:{escape(contact)}">{escape(contact)}</a>'
    else:
        write = "write to us with <b>Talk to us</b> on the site"
    values = {
        "%%CARDS%%": cards(),
        "%%SHOWCASE%%": showcase(),
        "%%LOGO%%": mark("processcraft", 28),
        "%%GH%%": gh,
        "%%DOCS%%": f"{gh}/blob/main",
        "%%BUNDLE%%": bundle,
        "%%DRAFT%%": banner,
        "%%ROBOTS%%": '<meta name="robots" content="noindex, nofollow">' if noindex else "",
        "%%DEMO%%": demo,
        "%%DEMO_FLOAT%%": demo_float,
        "%%INSTALL_PRIMARY%%": "" if demo_url else " primary",
        "%%WRITE%%": write,
        "%%MAIL%%": f'<a href="mailto:{escape(contact)}">{escape(contact)}</a>' if contact else "",
    }
    html = _versioned(_fill((HERE / "page/template.html").read_text(encoding="utf-8"), values))
    privacy = _versioned(_fill((HERE / "page/privacy.html").read_text(encoding="utf-8"), values))
    if out.exists():
        shutil.rmtree(out)
    shutil.copytree(HERE / "page/assets", out / "assets")
    (out / "assets/fonts").mkdir()
    for font in FONTS.glob("*.woff2"):
        if "italic" not in font.name:
            shutil.copy(font, out / "assets/fonts" / font.name)
    for licence in FONTS.glob("OFL-*.txt"):
        shutil.copy(licence, out / "assets/fonts" / licence.name)
    (out / "assets/plantcraft.svg").write_text(mark("processcraft", 64))
    (out / "index.html").write_text(html, encoding="utf-8")
    (out / "privacy.html").write_text(privacy, encoding="utf-8")
    (out / "robots.txt").write_text(
        "User-agent: *\nDisallow: /\n" if noindex else "User-agent: *\nAllow: /\n"
    )
    (out / ".well-known").mkdir()
    expires = (datetime.now(timezone.utc) + timedelta(days=365)).strftime("%Y-%m-%dT00:00:00Z")
    reports = security or contact
    contacts = ([f"Contact: mailto:{reports}"] if reports else []) + [
        f"Contact: {gh}/security/advisories/new"
    ]
    (out / ".well-known/security.txt").write_text(
        "\n".join([*contacts, f"Expires: {expires}", f"Policy: {gh}/blob/main/SECURITY.md", ""])
    )
    Knowledge.from_repository(ROOT).dump(out / "knowledge.json")
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=HERE / "dist")
    parser.add_argument("--owner", default="PlantCraft", help="the GitHub organization")
    parser.add_argument("--bundle", default="processcraft-0.5.0-linux-amd64-bundle")
    parser.add_argument("--draft", action="store_true", help="show a 'not published' banner")
    parser.add_argument(
        "--demo-url", default="https://demo.plantcraft.io", help="the public demo, for its button"
    )
    parser.add_argument("--contact", default="info@plantcraft.io", help="the team's e-mail")
    parser.add_argument(
        "--security", default="security@plantcraft.io", help="where security reports go"
    )
    parser.add_argument("--noindex", action="store_true", help="ask search engines to stay away")
    args = parser.parse_args()
    out = build(
        args.out,
        args.owner,
        args.bundle,
        args.draft,
        args.demo_url,
        args.contact,
        args.noindex,
        args.security,
    )
    print(f"built {out}")


if __name__ == "__main__":
    main()
