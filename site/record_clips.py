"""Records the clips at the top of the site from a live demo suite (page/assets/clips/).

    PLANTCRAFT_SUITE_URL=https://vm python record_clips.py [desk analytics process dashboards]

Needs Playwright with Chromium and ffmpeg. Each clip enters the demo as a visitor, walks one part
of the suite with a drawn cursor (Playwright's video has none) and is saved as raw video under
dist/clips/ with when the walk started; encode() cuts it there, speeds it up (SPEED) and writes the .webm (VP9), the
.mp4 (H.264, for Safari) and the poster .jpg beside the page. Keep each file under 1 MB.
"""

import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

HERE = Path(__file__).resolve().parent
OUT = HERE / "dist/clips"
ASSETS = HERE / "page/assets/clips"
# The walks are recorded at a person's pace and played this many times faster.
SPEED = 1.6
URL = os.environ.get("PLANTCRAFT_SUITE_URL", "https://vm").rstrip("/")

CURSOR = """
(() => {
  if (window.__pcCursor) return; window.__pcCursor = 1;
  const add = () => {
    const d = document.createElement('div');
    d.style.cssText = 'position:fixed;left:-40px;top:-40px;width:22px;height:22px;z-index:2147483647;pointer-events:none;transition:transform .12s ease;';
    d.innerHTML = '<svg width="22" height="22" viewBox="0 0 22 22"><path d="M3 2l15 9-6.5 1.6L8 19z" fill="#fff" stroke="#111" stroke-width="1.4" stroke-linejoin="round"/></svg>';
    document.documentElement.appendChild(d);
    addEventListener('mousemove', e => { d.style.left = e.clientX - 3 + 'px'; d.style.top = e.clientY - 2 + 'px'; }, true);
    addEventListener('mouseout', e => { if (!e.relatedTarget || e.relatedTarget.tagName === 'IFRAME') d.style.left = '-40px'; }, true);
    addEventListener('mousedown', () => { d.style.transform = 'scale(.8)'; }, true);
    addEventListener('mouseup', () => { d.style.transform = ''; }, true);
  };
  if (document.documentElement) add(); else addEventListener('DOMContentLoaded', add);
})();
"""


class Rec:
    def __init__(self, p, video_dir=None):
        self.b = p.chromium.launch(args=["--no-proxy-server"])
        opts = dict(
            ignore_https_errors=True,
            viewport={"width": 1440, "height": 900},
            color_scheme="dark",
            locale="en-US",
            timezone_id="America/Sao_Paulo",
        )
        if video_dir:
            opts.update(
                record_video_dir=video_dir, record_video_size={"width": 1440, "height": 900}
            )
        if os.path.exists("state.json"):
            opts["storage_state"] = "state.json"
        self.c = self.b.new_context(**opts)
        self.c.add_init_script(CURSOR)
        self.pg = self.c.new_page()
        self.pg.set_default_timeout(20000)
        self.x, self.y = 720, 450

    def app(self):
        return self.pg.frame_locator("iframe[data-pc-frame]:not([hidden])")

    def go(self, path, wait=1500):
        self.pg.goto(URL + path)
        self.pg.wait_for_load_state("networkidle")
        self.pg.wait_for_timeout(wait)
        self.not_now()

    def not_now(self):
        for loc in (
            self.pg.get_by_role("button", name="Not now"),
            self.app().get_by_role("button", name="Not now"),
        ):
            try:
                if loc.count() and loc.first.is_visible():
                    loc.first.click()
                    self.pg.wait_for_timeout(400)
            except Exception:
                pass

    def move(self, x, y, ms=700):
        steps = max(8, ms // 16)
        x0, y0 = self.x, self.y
        for i in range(1, steps + 1):
            t = i / steps
            e = t * t * (3 - 2 * t)
            self.pg.mouse.move(x0 + (x - x0) * e, y0 + (y - y0) * e)
            self.pg.wait_for_timeout(16)
        self.x, self.y = x, y

    def to(self, loc, ms=700, dx=0.5, dy=0.5):
        loc.scroll_into_view_if_needed()
        bb = loc.bounding_box()
        self.move(bb["x"] + bb["width"] * dx, bb["y"] + bb["height"] * dy, ms)

    def click(self, loc, ms=700, wait=1200):
        self.to(loc, ms)
        self.pg.wait_for_timeout(250)
        self.pg.mouse.down()
        self.pg.mouse.up()
        self.pg.wait_for_timeout(wait)

    def wheel(self, dy, n=10, pause=40):
        for _ in range(n):
            self.pg.mouse.wheel(0, dy / n)
            self.pg.wait_for_timeout(pause)

    def close(self):
        self.c.close()
        self.b.close()


def enter_demo(r):
    r.pg.goto(URL + "/")
    r.pg.wait_for_load_state("networkidle")
    r.pg.get_by_role("button", name=re.compile("Enter the demo")).click()
    r.pg.wait_for_timeout(4000)
    r.c.storage_state(path="state.json")


def desk(r):
    r.go("/", 2500)
    yield
    r.move(460, 360, 900)
    r.pg.wait_for_timeout(900)
    r.to(r.pg.get_by_text("FIC-1003 recycle valve").first, 900)
    r.pg.wait_for_timeout(500)
    r.click(r.pg.get_by_text("FIC-1003 recycle valve").first, 300, 3200)
    r.click(r.pg.get_by_role("link", name="Actions").first, 900, 2600)
    r.click(r.pg.get_by_role("link", name="Calendar").first, 700, 2600)


def analytics(r):
    r.go("/link/", 3000)
    yield
    r.move(450, 560, 900)
    r.move(560, 600, 700)
    r.pg.wait_for_timeout(600)
    r.to(r.app().get_by_text("FIC-1007").first, 800)
    r.pg.wait_for_timeout(700)
    r.click(r.pg.get_by_role("link", name="Algorithms").first, 900, 1800)
    r.click(r.app().get_by_text("Flow loop", exact=True).first, 800, 2000)
    r.click(r.app().get_by_text("Diagram", exact=True).first, 700, 2500)
    try:
        r.click(r.app().get_by_text("Values on wires").first, 800, 1200)
    except Exception as e:
        print("wires", e)
    zin = r.app().get_by_role("button", name=re.compile("zoom in", re.I)).first
    for _ in range(3):
        r.click(zin, 500, 500)
    r.move(800, 520, 900)
    r.pg.wait_for_timeout(800)
    try:
        r.click(r.app().get_by_text("SP activity", exact=True).first, 900, 2500)
    except Exception as e:
        print("block", e)


def process(r):
    r.go("/dash/diagrams", 2000)
    r.app().get_by_text("Riverbend plant", exact=True).first.click()
    r.pg.wait_for_timeout(5000)
    r.not_now()
    r.pg.wait_for_timeout(500)
    yield
    r.move(800, 360, 900)
    r.pg.wait_for_timeout(800)
    r.click(r.app().get_by_text("Column", exact=True).first, 900, 3000)
    r.move(760, 500, 900)
    r.pg.wait_for_timeout(1500)
    r.click(r.app().get_by_text("Reactor loop", exact=True).first, 900, 3000)
    r.move(820, 560, 900)
    r.pg.wait_for_timeout(1500)


def dashboards(r):
    r.go("/dash/dashboards", 2000)
    r.app().get_by_text("Plant overview", exact=True).first.click()
    r.pg.wait_for_timeout(6000)
    r.not_now()
    yield
    r.move(420, 440, 900)
    r.pg.wait_for_timeout(500)
    r.move(700, 440, 700)
    r.pg.wait_for_timeout(600)
    r.move(600, 640, 700)
    r.wheel(380, 30, 40)
    r.pg.wait_for_timeout(1500)
    r.move(900, 640, 800)
    r.pg.wait_for_timeout(1500)
    r.wheel(-380, 30, 40)
    r.pg.wait_for_timeout(1200)


def reports(r):
    r.go("/dash/reports", 2500)
    yield
    r.move(500, 300, 900)
    r.pg.wait_for_timeout(600)
    r.to(r.app().get_by_text("Alarm summary, weekly", exact=True).first, 800)
    r.pg.wait_for_timeout(500)
    r.click(r.app().get_by_text("U-100 daily report", exact=True).first, 800, 4000)
    r.not_now()
    r.move(800, 600, 900)
    r.wheel(500, 30, 40)
    r.pg.wait_for_timeout(1800)


def sources(r):
    r.go("/hist/sources", 2500)
    yield
    r.to(r.app().get_by_text("Simulator (OPC UA)", exact=True).first, 900)
    r.pg.wait_for_timeout(600)
    r.to(r.app().get_by_text("Laboratory (LIMS export)", exact=True).first, 700)
    r.pg.wait_for_timeout(600)
    r.click(r.pg.get_by_role("link", name="Signals").first, 900, 2500)
    r.move(700, 400, 900)
    r.pg.wait_for_timeout(800)
    r.click(r.pg.get_by_role("link", name="Overview").first, 900, 3000)


def alarms(r):
    r.go("/alarm/", 3000)
    yield
    r.move(600, 400, 900)
    r.pg.wait_for_timeout(800)
    r.click(r.pg.get_by_role("link", name="Alarms", exact=True).first, 900, 2500)
    r.move(700, 300, 700)
    try:
        r.click(r.app().locator("tbody tr").first, 700, 3000)
    except Exception as e:
        print("alarm row", e)
    r.pg.wait_for_timeout(1000)


def encode(name: str) -> None:
    j = json.loads((OUT / f"{name}.json").read_text())
    cut = ["-ss", str(j["start"]), "-t", str(j["dur"]), "-i", j["file"]]
    scale = ["-vf", f"setpts=PTS/{SPEED},fps=25,scale=1280:-2", "-an"]
    run = ["ffmpeg", "-loglevel", "error", "-y"]
    vp9 = ["-c:v", "libvpx-vp9", "-b:v", "0", "-crf", "36", "-row-mt", "1"]
    h264 = ["-c:v", "libx264", "-crf", "25", "-preset", "slow", "-pix_fmt", "yuv420p"]
    subprocess.run([*run, *cut, *scale, *vp9, str(ASSETS / f"{name}.webm")], check=True)
    subprocess.run(
        [*run, *cut, *scale, *h264, "-movflags", "+faststart", str(ASSETS / f"{name}.mp4")],
        check=True,
    )
    poster = [
        "-ss",
        str(j["start"] + 0.3),
        "-i",
        j["file"],
        "-frames:v",
        "1",
        "-vf",
        "scale=1280:-2",
    ]
    subprocess.run([*run, *poster, "-q:v", "4", str(ASSETS / f"{name}.jpg")], check=True)


CLIPS = {
    "dashboards": dashboards,
    "process": process,
    "reports": reports,
    "analytics": analytics,
    "alarms": alarms,
    "sources": sources,
    "desk": desk,
}


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    os.chdir(OUT)
    names = sys.argv[1:] or list(CLIPS)
    Path("state.json").unlink(missing_ok=True)
    with sync_playwright() as p:
        r = Rec(p)
        enter_demo(r)
        r.close()
        for name in names:
            vd = Path("raw") / name
            shutil.rmtree(vd, ignore_errors=True)
            r = Rec(p, str(vd))
            t0 = time.time()
            walk = CLIPS[name](r)
            next(walk)
            start = time.time() - t0
            for _ in walk:
                pass
            dur = time.time() - t0 - start
            video = r.pg.video.path()
            r.close()
            meta = {"start": start, "dur": dur, "file": str(video)}
            (OUT / f"{name}.json").write_text(json.dumps(meta))
            print(name, round(start, 1), round(dur, 1))
            encode(name)


if __name__ == "__main__":
    main()
