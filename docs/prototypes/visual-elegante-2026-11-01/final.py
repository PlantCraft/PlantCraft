"""Final look (D3) on six different pages of two apps, before and after, light and dark."""
import json, re, sys, time
from pathlib import Path
from playwright.sync_api import sync_playwright

link = json.loads(Path("server.json").read_text())
view = json.loads(Path("server-view.json").read_text())
PLANT = Path("/home/user/plantcraft/deploy/demo/diagrams/riverbend-plant.json")
variants = sys.argv[1].split(",")
out = Path(sys.argv[3] if len(sys.argv) > 3 else "final"); out.mkdir(exist_ok=True)

def assistant(route):
    if route.request.url.rstrip("/").endswith("/api/assistant"):
        route.fulfill(json={"allowed": True, "available": True, "can_set_up": False})
    else:
        route.fulfill(json={"works": []})

def prepare_view(pg):
    """A dashboard from the first template and the demo plant's Process drawing."""
    pg.goto(view["url"] + "/dash/dashboards"); pg.wait_for_load_state("networkidle")
    pg.get_by_role("button", name="New dashboard").first.click()
    dialog = pg.get_by_role("dialog", name="New dashboard")
    radios = dialog.get_by_role("radio")
    print("templates:", [radios.nth(i).get_attribute("aria-label") or radios.nth(i).evaluate("e=>e.closest('label')?.textContent") for i in range(radios.count())])
    pick = int(sys.argv[2]) if len(sys.argv) > 2 else 1
    radios.nth(pick).check()
    dialog.get_by_role("button", name="Open the editor").click()
    time.sleep(1.5)
    pg.get_by_role("button", name="Save").click()
    pg.wait_for_url(re.compile(r"/dash/d/[0-9a-f]{12}"))
    dash = pg.url
    made = pg.request.post(view["url"] + "/dash/api/diagrams", data=json.loads(PLANT.read_text())).json()
    return dash, view["url"] + f"/dash/diagrams/{made['diagram_id']}"

with sync_playwright() as p:
    b = p.chromium.launch(executable_path="/opt/pw-browsers/chromium")
    setup = b.new_context(viewport={"width": 1440, "height": 900})
    setup.add_cookies([{"name": "processcraft_token", "value": view["token"], "url": view["url"]}])
    setup.add_init_script("try{localStorage.setItem('plantcraft-ui:tours-off','1')}catch(e){}")
    dash, diagram = prepare_view(setup.new_page()); setup.close()
    pages = [
        ("0-overview", link, link["url"] + "/link/"),
        ("0-lista", link, link["url"] + "/link/results"),
        ("0-malha", link, link["url"] + "/link/loops/fic-101"),
        ("1-algoritmo", link, link["url"] + "/link/algorithms/flow_loop/diagram"),
        ("2-blocos", link, link["url"] + "/link/blocks"),
        ("3-sinal", link, link["url"] + "/link/signals/fake%3ATIC-104.PV"),
        ("4-ajuda", link, link["url"] + "/link/help"),
        ("5-dashboard", view, dash),
        ("6-processo", view, diagram),
    ]
    for theme in ["light", "dark"]:
        ctx = b.new_context(viewport={"width": 1440, "height": 900}, device_scale_factor=2, color_scheme=theme)
        ctx.add_init_script("try{localStorage.setItem('plantcraft-ui:tours-off','1')}catch(e){}")
        ctx.route(re.compile(r".*/api/assistant(/works.*)?$"), assistant)
        pg = ctx.new_page(); current = None
        for name, srv, url in pages:
            if srv is not current:  # one cookie per host: ports share it, so switch per app
                ctx.clear_cookies(); ctx.add_cookies([{"name": "processcraft_token", "value": srv["token"], "url": srv["url"]}]); current = srv
            pg.goto(url); pg.wait_for_load_state("networkidle"); time.sleep(2.5)
            for v in variants:
                pg.evaluate("document.querySelectorAll('style[data-proto]').forEach(s=>s.remove())")
                if v != "antes":
                    pg.evaluate("css => { const s=document.createElement('style'); s.dataset.proto='1'; s.textContent=css; document.head.appendChild(s); }", Path(f"{v}.css").read_text())
                time.sleep(0.8)
                pg.screenshot(path=str(out / f"{name}-{v}-{theme}.png"))
        ctx.close()
    b.close()
