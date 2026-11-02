"""Builds PlantCraft's site into dist/: its pages, their assets and fonts, and the chat's knowledge.

    python build.py [--owner PlantCraft] [--bundle plantcraft-0.5.1-linux-amd64-bundle] [--draft]
                    [--demo-url https://demo.example] [--contact team@example] [--security sec@example] [--noindex]

Each page (index, pricing, partners, install; pages.py) and privacy.html is put in
page/template.html with the links filled in; the logo and app marks come from docs/images and the
fonts from ui/src/fonts, so the site uses the suite's own. knowledge.json is the public documentation listed in knowledge/sources.toml, cut into
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

import pages  # noqa: E402
from sitechat.knowledge import Knowledge  # noqa: E402

IMAGES = ROOT / "docs/images"
MARKS = IMAGES / "apps"
FONTS = ROOT / "ui/src/fonts"

# The clips at the top of the page (page/assets/clips/<name>.webm, .mp4 and .jpg, recorded from
# the demo by record_clips.py): name, tab label, what it shows.
CLIPS = [
    ("dashboards", "Monitor your KPIs", "View: a dashboard of the unit, shared with the shift."),
    ("process", "See your plant", "View: the plant's process diagram with live values."),
    (
        "analytics",
        "Find the problems",
        "Analytics: an algorithm's block diagram and the results on every asset.",
    ),
    ("alarms", "Handle alarms", "Alarms: the alarms of the plant, their history and performance."),
    ("reports", "Share reports", "View: a scheduled report of the unit, as it is sent by e-mail."),
    (
        "sources",
        "Collect the data",
        "Historian: the plant's data sources, read-only, and their signals.",
    ),
    ("desk", "Manage your day", "Desk: messages, actions, calendar and what needs you today."),
]

# The pages beside index.html: file, title, description (the nav shows the first three).
NAV = [("./", "Home"), ("pricing.html", "Pricing"), ("partners.html", "Partners")]
DESCRIPTIONS = {
    "index.html": "The open suite for industrial plants: historian, analytics, alarms, dashboards, models and documents on your own servers, with an AI assistant that checks the results with you.",
    "pricing.html": "PlantCraft is free and open source. Pay only for help: installation, monitoring, diagnosis, custom apps, support and training, per plant.",
    "partners.html": "Integrators, consultants and app builders: deliver PlantCraft straight to the plant, and keep your own apps open or closed.",
    "install.html": "Install PlantCraft in about 10 minutes: one signed offline bundle with the whole suite and a demo plant.",
    "privacy.html": "What PlantCraft's site and public demo keep about visitors, and what PlantCraft installed at a plant sends out: nothing.",
}


def mark(app: str, size: int = 44) -> str:
    svg = (MARKS / f"{app}.svg").read_text()
    svg = re.sub(r"<title>.*?</title>", "", svg)
    svg = re.sub(r' width="64" height="64"', f' width="{size}" height="{size}"', svg)
    svg = re.sub(r' aria-label="[^"]*"', "", svg).replace(' role="img"', "")
    return svg.replace("<svg ", '<svg aria-hidden="true" focusable="false" ', 1)


def showcase() -> str:
    """The clips at the top: one video, then one button per clip and a pause button with a bar
    under it; on a phone, the clip's name between back and next. showcase.js swaps the video's sources
    (a single video element, so speed-control browser add-ons draw one control, not seven)."""
    n, _, alt = CLIPS[0]
    tabs = "".join(
        f'<button type="button" class="tab" aria-pressed="{"true" if i == 0 else "false"}" '
        f'data-webm="assets/clips/{name}.webm" data-mp4="assets/clips/{name}.mp4" '
        f'data-poster="assets/clips/{name}.jpg" data-label="{escape(text)}">'
        f'{label}<span class="f"></span></button>'
        for i, (name, label, text) in enumerate(CLIPS)
    )
    return (
        '<figure class="showcase" aria-label="PlantCraft at work">'
        '<div class="show"><video muted playsinline preload="auto" '
        f'poster="assets/clips/{n}.jpg" aria-label="{escape(alt)}" width="1440" height="900">'
        f'<source src="assets/clips/{n}.webm" type="video/webm">'
        f'<source src="assets/clips/{n}.mp4" type="video/mp4"></video></div>'
        f'<div class="tabs clip-tabs" aria-label="Parts of the suite">{tabs}</div>'
        '<div class="clip-nav"><button type="button" class="clip-prev" aria-label="Previous">‹</button>'
        f'<span class="clip-name">{CLIPS[0][1]}</span>'
        '<button type="button" class="clip-next" aria-label="Next">›</button></div>'
        '<div class="clip-bar">'
        '<button type="button" class="clip-play" aria-label="Pause">'
        '<svg aria-hidden="true" viewBox="0 0 16 16" width="16" height="16">'
        '<path class="i-pause" d="M4 3h3v10H4zM9 3h3v10H9z"/>'
        '<path class="i-play" d="M4 2.5v11l9.5-5.5z"/></svg></button>'
        '<input class="clip-seek" type="range" min="0" max="1000" value="0" step="1" '
        'aria-label="Position in the clip"></div>'
        "</figure>"
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
    if contact:
        write = f'write to <a href="mailto:{escape(contact)}">{escape(contact)}</a>'
    else:
        write = "write to us with <b>Talk to us</b> on the site"
    shell = (HERE / "page/template.html").read_text(encoding="utf-8")
    bodies = {fn: (title, body) for fn, (title, body) in pages.PAGES.items()}
    bodies["privacy.html"] = (
        "Privacy · PlantCraft",
        (HERE / "page/privacy.html").read_text(encoding="utf-8"),
    )
    built = {}
    for fn, (title, body) in bodies.items():
        nav = "".join(
            f'<a href="{href}"{" class=cur" if href == fn or (href == "./" and fn == "index.html") else ""}>{name}</a>'
            for href, name in NAV
        )
        scripts = (
            '<script src="assets/showcase.js" defer></script>\n'
            '<script src="assets/home.js" defer></script>\n'
            if fn == "index.html"
            else ""
        )
        values = {
            "%%BODY%%": body.replace("%%SHOWCASE%%", showcase()),
            "%%TITLE%%": title,
            "%%DESCRIPTION%%": DESCRIPTIONS[fn],
            "%%SCRIPTS%%": scripts,
            "%%NAV%%": nav,
            "%%INSTALL_CUR%%": " cur" if fn == "install.html" else "",
            "%%GH%%": gh,
            "%%DOCS%%": f"{gh}/blob/main",
            "%%BUNDLE%%": bundle,
            "%%DRAFT%%": banner,
            "%%ROBOTS%%": '<meta name="robots" content="noindex, nofollow">' if noindex else "",
            "%%DEMO_URL%%": escape(demo_url or "https://demo.plantcraft.io"),
            "%%WRITE%%": write,
            "%%MAIL%%": f'<a href="mailto:{escape(contact)}">{escape(contact)}</a>'
            if contact
            else "",
        }
        built[fn] = _versioned(_fill(shell, values))
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
    for fn, html in built.items():
        (out / fn).write_text(html, encoding="utf-8")
    (out / "assets/img/apps").mkdir(parents=True)
    for name in ("logo.svg", "logo-mark.svg"):
        shutil.copy(IMAGES / name, out / "assets/img" / name)
    for svg in MARKS.glob("*.svg"):
        shutil.copy(svg, out / "assets/img/apps" / svg.name)
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
    parser.add_argument("--bundle", default="plantcraft-0.5.1-linux-amd64-bundle")
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
