from PIL import Image, ImageDraw, ImageFont
from pathlib import Path
S = Path("final"); O = Path("final-folhas"); O.mkdir(exist_ok=True)
F = ImageFont.truetype("inter.ttf", 36)
try: F.set_variation_by_axes([32, 600])
except Exception: pass
pages = [("1-algoritmo", "Analytics · diagrama do algoritmo"), ("2-blocos", "Analytics · catálogo de blocos"), ("3-sinal", "Analytics · sinal com gráfico"),
         ("4-ajuda", "Analytics · ajuda"), ("5-dashboard", "View · dashboard"), ("6-processo", "View · desenho Process")]
def tile(p, label, w=1440):
    im = Image.open(p).convert("RGB"); im = im.resize((w, int(im.height * w / im.width)), Image.LANCZOS)
    c = Image.new("RGB", (w, im.height + 68), "white"); ImageDraw.Draw(c).text((18, 14), label, fill=(29, 29, 31), font=F); c.paste(im, (0, 68)); return c
def sheet(ts, cols, path):
    w, h = ts[0].size; g = 16; rows = -(-len(ts) // cols)
    s = Image.new("RGB", (cols * w + (cols + 1) * g, rows * h + (rows + 1) * g), (200, 200, 205))
    for i, t in enumerate(ts): s.paste(t, (g + (i % cols) * (w + g), g + (i // cols) * (h + g)))
    s.save(path, optimize=True)
for th, nome in [("light", "claro"), ("dark", "escuro")]:
    sheet([tile(S / f"{p}-r3-d3-{th}.png", l) for p, l in pages], 3, O / f"modelo-final-{nome}.png")
    for p, l in pages:
        sheet([tile(S / f"{p}-antes-{th}.png", f"Antes · {l}"), tile(S / f"{p}-r3-d3-{th}.png", f"Final (D3) · {l}")], 2, O / f"{p}-{nome}-antes-x-final.png")
