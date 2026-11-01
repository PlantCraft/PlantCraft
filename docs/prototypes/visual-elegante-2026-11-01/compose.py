from PIL import Image, ImageDraw, ImageFont
from pathlib import Path
S = Path("shots"); O = Path("comparacoes"); O.mkdir(exist_ok=True)
try: F = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 34)
except Exception: F = ImageFont.load_default()
names = {"antes": "Antes (ui 0.99)", "refinado": "A · Refinado (só tokens)", "elegante": "B · Elegante (tokens + componentes)", "estudio": "C · Estúdio (B + barra lateral clara)"}
def tile(p, label, w=1440):
    im = Image.open(p).convert("RGB"); im = im.resize((w, int(im.height * w / im.width)), Image.LANCZOS)
    c = Image.new("RGB", (w, im.height + 64), "white"); d = ImageDraw.Draw(c)
    d.text((16, 14), label, fill=(29, 29, 31), font=F); c.paste(im, (0, 64)); return c
for page in ["overview", "malha", "malha-graficos", "lista", "formulario"]:
    for th in ["light", "dark"]:
        ts = [tile(S / f"{page}-{v}-{th}.png", names[v]) for v in names]
        w, h = ts[0].size; g = 16
        grid = Image.new("RGB", (2 * w + 3 * g, 2 * h + 3 * g), (200, 200, 205))
        for i, t in enumerate(ts): grid.paste(t, (g + (i % 2) * (w + g), g + (i // 2) * (h + g)))
        grid.save(O / f"{page}-{th}-4-versoes.png", optimize=True)
        pair = Image.new("RGB", (2 * w + 3 * g, h + 2 * g), (200, 200, 205))
        pair.paste(ts[0], (g, g)); pair.paste(ts[2], (2 * g + w, g))
        pair.save(O / f"{page}-{th}-antes-x-B.png", optimize=True)
