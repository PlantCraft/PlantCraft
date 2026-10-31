"""Writes the bench's report page: one section per item, a table of numbers and the screenshots.

python report.py <results dir> <notes.json> <out.html> [<gpu results dir>]
notes.json: {"title": ..., "intro": [html...], "items": {"c1": {"title", "today", "verdict", "text": [html...]}}}
"""

import html
import json
import sys
from pathlib import Path

out_dir, notes_file, out_file = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])
gpu_dir = Path(sys.argv[4]) if len(sys.argv) > 4 else None
results = json.loads((out_dir / "results.json").read_text())
gpu = (
    json.loads((gpu_dir / "results.json").read_text())
    if gpu_dir and (gpu_dir / "results.json").exists()
    else {}
)
notes = json.loads(notes_file.read_text())
react = (results.get("c0-react") or {}).get("bundle", {}).get("kb_gzip", 0)

SKIP = {"print", "bundle", "wall_s", "dom_nodes", "page_errors", "after_error", "note"}
LABEL = {
    "render": "1ª imagem (ms)",
    "zoom": "zoom (ms)",
    "unzoom": "voltar (ms)",
    "update_ms": "atualizar 24 (ms)",
    "one_update_ms": "atualizar 300 (ms)",
    "fps": "quadros/s",
    "frame_ms": "quadro (ms)",
    "p95_ms": "quadro p95 (ms)",
    "add_node": "novo bloco (ms)",
    "pan_fps": "arrastar (q/s)",
    "pan_p95_ms": "arrastar p95 (ms)",
    "sort_number": "ordenar número (ms)",
    "sort_text": "ordenar texto (ms)",
    "scroll_fps": "rolar (q/s)",
    "scroll_p95_ms": "rolar p95 (ms)",
    "scroll": "rolagem",
    "move_card": "mover cartão (ms)",
    "relayout_900px": "relayout 900 px (ms)",
    "open": "abrir (ms)",
    "per_key_ms_over_frame": "por tecla além do quadro (ms)",
    "jump_to_end": "ir ao fim (ms)",
    "heap_mb": "heap JS (MB)",
    "error": "erro",
}


def esc(value):
    return html.escape(str(value))


def table(keys):
    cols = []
    for key in keys:
        for name in results[key]:
            if name not in SKIP and name not in cols:
                cols.append(name)
    head = "".join(f"<th>{esc(LABEL.get(c, c))}</th>" for c in cols)
    rows = []
    for key in keys:
        r = results[key]
        lib, _, query = key.partition("?")
        b = r.get("bundle") or {}
        size = b.get("kb_gzip", "")
        cells = "".join(f"<td>{esc(r.get(c, ''))}</td>" for c in cols)
        g = gpu.get(key)
        gpu_cell = f"<td>{esc(g.get('render', g.get('error', '')))}</td>" if gpu else ""
        rows.append(
            f"<tr><td><b>{esc(lib.split('-', 1)[1])}</b><br><small>{esc(query.replace('&', ' '))}</small></td><td>{esc(size)}</td>{cells}{gpu_cell}<td><small>{esc(r.get('note', ''))}</small></td></tr>"
        )
    gpu_head = "<th>1ª imagem com GPU (ms)</th>" if gpu else ""
    return f"<div class=scroll><table><thead><tr><th>caso</th><th>tamanho gzip (KB)</th>{head}{gpu_head}<th>nota</th></tr></thead><tbody>{''.join(rows)}</tbody></table></div>"


def prints(keys):
    seen, figs = set(), []
    for key in keys:
        lib = key.split("?")[0]
        if lib in seen and "phone" not in key:
            continue
        seen.add(lib)
        p = results[key].get("print")
        if p:
            figs.append(
                f"<figure><a href='{esc(p)}'><img loading=lazy src='{esc(p)}' alt='{esc(key)}'></a><figcaption>{esc(key)}</figcaption></figure>"
            )
    return f"<div class=prints>{''.join(figs)}</div>"


sections = []
for item, note in notes["items"].items():
    keys = [k for k in results if k.split("-")[0] == item]
    if not keys:
        continue
    text = "".join(f"<p>{t}</p>" for t in note.get("text", []))
    sections.append(f"""<section id="{item}"><h3>{item.upper()} · {esc(note["title"])}</h3>
<p class=verdict><b>Recomendação:</b> {note["verdict"]}</p><p class=today>Hoje: {esc(note.get("today", ""))}</p>{text}
{table(keys)}{prints(keys)}</section>""")

decisions = "".join(
    f"<li><p><b>{d['q']}</b></p><p>Recomendo: {d['rec']}</p></li>"
    for d in notes.get("decisions", [])
)
summary_rows = "".join(
    f"<tr><td><a href='#{i}'>{i.upper()}</a></td><td>{esc(n['title'])}</td><td>{esc(n.get('today', ''))}</td><td>{n['verdict']}</td></tr>"
    for i, n in notes["items"].items()
)
intro = "".join(f"<p>{t}</p>" for t in notes.get("intro", []))
out_file.write_text(f"""<!doctype html><html lang=pt-BR><head><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1">
<title>Bibliotecas de visualização</title><style>
:root{{--bg:#fff;--fg:#0f172a;--muted:#64748b;--line:#e2e8f0;--accent:#2563eb;--soft:#f1f5f9}}
@media (prefers-color-scheme:dark){{:root{{--bg:#0b1220;--fg:#e2e8f0;--muted:#94a3b8;--line:#1e293b;--accent:#60a5fa;--soft:#111a2e}}}}
body{{margin:0;background:var(--bg);color:var(--fg);font:15px/1.5 system-ui,sans-serif}}main{{max-width:1180px;margin:0 auto;padding:24px 16px}}
h1{{font-size:26px;margin:0 0 4px}}h2{{font-size:20px;margin:40px 0 8px;border-top:1px solid var(--line);padding-top:24px}}
.verdict{{background:var(--soft);border-left:4px solid var(--accent);padding:10px 12px;border-radius:6px}}.today{{color:var(--muted)}}
.scroll{{overflow-x:auto}}table{{border-collapse:collapse;font-size:13px;margin:12px 0;min-width:100%}}th,td{{border-bottom:1px solid var(--line);padding:6px 8px;text-align:left;vertical-align:top;white-space:nowrap}}td small{{white-space:normal;color:var(--muted)}}
.prints{{display:grid;grid-template-columns:repeat(auto-fill,minmax(260px,1fr));gap:12px}}figure{{margin:0}}img{{width:100%;border:1px solid var(--line);border-radius:6px;background:#fff}}figcaption{{font-size:12px;color:var(--muted)}}
li{{margin:4px 0}}h3{{font-size:18px;margin:32px 0 8px}}table.summary td{{white-space:normal}}</style></head><body><main><h1>{esc(notes["title"])}</h1>{intro}<h2>1. Decisões para você</h2><ol>{decisions}</ol><h2>2. Resumo por ponto da plataforma</h2><div class=scroll><table class=summary><thead><tr><th></th><th>ponto</th><th>hoje</th><th>recomendação</th></tr></thead><tbody>{summary_rows}</tbody></table></div><h2>3. Evidências</h2>{"".join(sections)}</main></body></html>""")
print("wrote", out_file)
