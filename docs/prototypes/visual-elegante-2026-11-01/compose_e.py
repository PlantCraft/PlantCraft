from PIL import Image, ImageDraw, ImageFont
from pathlib import Path
S = Path("rodadaE"); O = Path("rodadaE-folhas"); O.mkdir(exist_ok=True)
F = ImageFont.truetype("inter.ttf", 36)
try: F.set_variation_by_axes([32, 600])
except Exception: pass
names = {"antes": "Antes (hoje)", "r3-d3": "D3 (modelo final)", "e1": "E1 · D3 + espaço (fundo preto, cartão #161618)",
         "e2": "E2 · Invertido (fundo cinza, cartão quase preto)", "e3": "E3 · Degraus maiores (fundo preto, cartão #1F1F22)",
         "e4": "E4 · Grafite (fundo #121214, cartão #232326)"}
def tile(p, label, w=1440):
    im = Image.open(p).convert("RGB"); im = im.resize((w, int(im.height * w / im.width)), Image.LANCZOS)
    c = Image.new("RGB", (w, im.height + 68), "white"); ImageDraw.Draw(c).text((18, 14), label, fill=(29, 29, 31), font=F); c.paste(im, (0, 68)); return c
def sheet(ts, cols, path):
    w, h = ts[0].size; g = 16; rows = -(-len(ts) // cols)
    s = Image.new("RGB", (cols * w + (cols + 1) * g, rows * h + (rows + 1) * g), (200, 200, 205))
    for i, t in enumerate(ts): s.paste(t, (g + (i % cols) * (w + g), g + (i // cols) * (h + g)))
    s.save(path, optimize=True)
pages = sorted({f.name.split("-antes-")[0] for f in S.glob("*-antes-dark.png")})
for p in pages:
    sheet([tile(S / f"{p}-{v}-dark.png", names[v]) for v in names], 3, O / f"{p}-escuro.png")
    sheet([tile(S / f"{p}-{v}-light.png", names[v].split(" (")[0] if v == "e1" else names[v]) for v in ["antes", "r3-d3", "e1"]], 3, O / f"{p}-claro-espaco.png")
