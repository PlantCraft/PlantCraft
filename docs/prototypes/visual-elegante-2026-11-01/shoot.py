"""Capture the same pages with the current look and with prototype stylesheets injected."""
import json, sys, time
from pathlib import Path
from playwright.sync_api import sync_playwright

PAGES = [
    ("overview", "/link/"),
    ("malha", "/link/loops/fic-101"),
    ("malha-graficos", "/link/loops/fic-101#.loop-result-charts"),
    ("lista", "/link/results"),
    ("formulario", "/link/schedules/new"),
    ("lista-dica", "/link/results"),
]
variants = sys.argv[1].split(",")          # e.g. antes,refinado
themes = sys.argv[2].split(",") if len(sys.argv) > 2 else ["light"]
only = sys.argv[3].split(",") if len(sys.argv) > 3 else None
out = Path("/tmp/claude-0/proto/shots")
srv = json.loads(Path("/tmp/claude-0/proto/server.json").read_text())
with sync_playwright() as p:
    b = p.chromium.launch(executable_path="/opt/pw-browsers/chromium")
    for theme in themes:
        ctx = b.new_context(viewport={"width": 1440, "height": 900}, device_scale_factor=2, color_scheme=theme)
        ctx.add_cookies([{"name": "processcraft_token", "value": srv["token"], "url": srv["url"]}])
        ctx.add_init_script("try{localStorage.setItem(\"plantcraft-ui:tours-off\",\"1\")}catch(e){}")
        pg = ctx.new_page()
        for name, path in PAGES:
            if only and name not in only:
                continue
            sel = path.split("#")[1] if "#" in path else None
            pg.goto(srv["url"] + path.split("#")[0])
            pg.wait_for_load_state("networkidle")
            time.sleep(1.5)
            if sel:
                pg.evaluate("s => { const e=document.querySelector(s); if (e) window.scrollTo(0, e.getBoundingClientRect().top + window.scrollY - 24); }", sel)
                time.sleep(0.8)
            for v in variants:
                pg.evaluate("document.querySelectorAll('style[data-proto]').forEach(s=>s.remove())")
                if v != "antes":
                    css = Path(f"/tmp/claude-0/proto/{v}.css").read_text()
                    pg.evaluate("css => { const s=document.createElement('style'); s.dataset.proto='1'; s.textContent=css; document.head.appendChild(s); }", css)
                time.sleep(0.6)
                if name == "lista-dica":
                    pg.evaluate("""() => {
                      document.querySelectorAll('.proto-tip').forEach(n => n.remove());
                      const row = document.querySelectorAll('table.table tbody tr')[1]; if (!row) return;
                      const small = row.querySelector('small.clamp') || [...row.querySelectorAll('td small')].pop();
                      const cell = small.closest('td'); const title = cell.querySelector('strong, b, a')?.textContent || '';
                      row.querySelectorAll('td').forEach(td => td.style.background = 'color-mix(in srgb, var(--pc-primary) 4%, var(--pc-surface))');
                      const r = small.getBoundingClientRect(); const tip = document.createElement('div'); tip.className = 'proto-tip';
                      tip.style.cssText = 'position:fixed;z-index:1000;max-width:340px;padding:10px 12px;border-radius:10px;background:var(--pc-surface);box-shadow:0 10px 30px rgba(0,0,0,.18);border:1px solid var(--pc-border-subtle);font-size:13px;line-height:1.45;color:var(--pc-text-2)';
                      tip.style.left = (r.left) + 'px'; tip.style.top = (r.bottom + 8) + 'px';
                      tip.innerHTML = '<strong></strong><span></span>'; tip.querySelector('strong').textContent = title; tip.querySelector('span').textContent = small.textContent;
                      tip.querySelector('strong').style.cssText = 'display:block;margin-bottom:3px;color:var(--pc-text)';
                      document.body.appendChild(tip);
                    }""")
                    time.sleep(0.3)
                pg.screenshot(path=str(out / f"{name}-{v}-{theme}.png"))
        ctx.close()
    b.close()
