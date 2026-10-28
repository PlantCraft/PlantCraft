"""Builds PlantCraft's site into dist/: the page, its assets and fonts, and the chat's knowledge.

    python build.py [--owner PlantCraft] [--bundle processcraft-0.5.0-linux-amd64-bundle] [--draft]
                    [--demo-url https://demo.example] [--contact team@example] [--noindex]

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
        "Signals and loops",
        "Algorithms of blocks that watch every signal and control loop and say what is wrong and why.",
    ),
    (
        "alarmcraft",
        "Alarms",
        "Operations",
        "ISA-18.2 alarms and alerts, shelving, history and alarm performance.",
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
    (
        "notebooks",
        "Notebooks",
        "Your own analysis",
        "JupyterLab with the plant's data, in the browser or on your computer.",
    ),
    (
        "simcraft",
        "Simulator",
        "Try it",
        "An OPC UA plant of 50 control loops with faults on purpose, to try everything safely.",
    ),
]

# Notebooks has no mark of its own in docs/images/apps: a page with a code bracket, same style.
NOTEBOOKS = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32" width="64" height="64">'
    '<rect width="32" height="32" rx="7" fill="#b45309"/>'
    '<rect x="8" y="5" width="16" height="22" rx="2.5" stroke-width="2.2" fill="none" stroke="#fff"/>'
    '<path d="M14 12l-3 4 3 4M18 12l3 4-3 4" stroke-width="2" fill="none" stroke="#fff" '
    'stroke-linecap="round" stroke-linejoin="round"/></svg>'
)


def mark(app: str, size: int = 44) -> str:
    svg = NOTEBOOKS if app == "notebooks" else (MARKS / f"{app}.svg").read_text()
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
) -> Path:
    gh = f"https://github.com/{owner}/PlantCraft"
    banner = '<p class="draft">Draft: not published yet</p>' if draft else ""
    demo = f'<a class="btn" href="{escape(demo_url)}">Try the live demo</a>' if demo_url else ""
    if contact:
        write = f'write to <a href="mailto:{escape(contact)}">{escape(contact)}</a>'
    else:
        write = "write to us with <b>Talk to us</b> on the site"
    values = {
        "%%CARDS%%": cards(),
        "%%LOGO%%": mark("processcraft", 28),
        "%%GH%%": gh,
        "%%DOCS%%": f"{gh}/blob/main",
        "%%BUNDLE%%": bundle,
        "%%DRAFT%%": banner,
        "%%ROBOTS%%": '<meta name="robots" content="noindex, nofollow">' if noindex else "",
        "%%DEMO%%": demo,
        "%%WRITE%%": write,
    }
    html = _fill((HERE / "page/template.html").read_text(encoding="utf-8"), values)
    privacy = _fill((HERE / "page/privacy.html").read_text(encoding="utf-8"), values)
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
    contacts = ([f"Contact: mailto:{contact}"] if contact else []) + [
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
    parser.add_argument("--demo-url", default="", help="the public demo, for its button")
    parser.add_argument("--contact", default="", help="the team's e-mail (privacy, security.txt)")
    parser.add_argument("--noindex", action="store_true", help="ask search engines to stay away")
    args = parser.parse_args()
    out = build(
        args.out, args.owner, args.bundle, args.draft, args.demo_url, args.contact, args.noindex
    )
    print(f"built {out}")


if __name__ == "__main__":
    main()
