from PIL import Image, ImageDraw, ImageFont
from pathlib import Path
S = Path("rodadaG"); O = Path("rodadaG-folhas"); O.mkdir(exist_ok=True)
F = ImageFont.truetype("inter.ttf", 36)
try: F.set_variation_by_axes([32, 600])
except Exception: pass
names = {"antes": "Antes (hoje)", "f1": "F1 (escolhida)", "g2": "G · F1 + abas de hoje + espaçamento padronizado"}
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
    ts = [tile(S / f"{p}-{v}-{th}.png", f"{names[v]} · {'claro' if th=='light' else 'escuro'}") for th in ["light", "dark"] for v in names]
    sheet(ts, 3, O / f"{p}.png")
