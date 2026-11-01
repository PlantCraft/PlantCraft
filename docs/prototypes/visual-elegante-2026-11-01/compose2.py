"""Side-by-side sheets: python compose2.py OUTDIR var1,var2,... (labels in Inter)."""
import sys
from PIL import Image, ImageDraw, ImageFont
from pathlib import Path
S = Path("shots"); O = Path(sys.argv[1]); O.mkdir(exist_ok=True)
variants = sys.argv[2].split(",")
F = ImageFont.truetype("inter.ttf", 36)
try: F.set_variation_by_axes([32, 600])
except Exception:
    try: F.set_variation_by_name("SemiBold")
    except Exception: pass
names = {"antes": "Antes (hoje)", "estudio": "C da rodada 1", "r2-c1": "C1 · Tom (barra um tom abaixo da página)",
         "r2-c2": "C2 · Flutuante (escolhida na rodada 2)", "r2-c3": "C3 · Branca (barra branca, página cinza)",
         "r3-d1": "D1 · Painel único (página também flutua)", "r3-d2": "D2 · Acento azul (onde você está)",
         "r3-d3": "D3 · Denso (sala de controle)", "r3-d4": "D4 · Barra de título translúcida"}
def tile(p, label, w=1440):
    im = Image.open(p).convert("RGB"); im = im.resize((w, int(im.height * w / im.width)), Image.LANCZOS)
    c = Image.new("RGB", (w, im.height + 68), "white"); d = ImageDraw.Draw(c)
    d.text((18, 14), label, fill=(29, 29, 31), font=F); c.paste(im, (0, 68)); return c
for page in ["overview", "malha", "malha-graficos", "lista", "lista-dica", "formulario"]:
    for th in ["light", "dark"]:
        ts = [tile(S / f"{page}-{v}-{th}.png", names[v]) for v in variants]
        w, h = ts[0].size; g = 16; cols = 3 if len(ts) > 4 else 2; rows = -(-len(ts) // cols)
        grid = Image.new("RGB", (cols * w + (cols + 1) * g, rows * h + (rows + 1) * g), (200, 200, 205))
        for i, t in enumerate(ts): grid.paste(t, (g + (i % cols) * (w + g), g + (i // cols) * (h + g)))
        grid.save(O / f"{page}-{th}.png", optimize=True)
