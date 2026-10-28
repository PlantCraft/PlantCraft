// Writes docs/images/apps/<id>.svg and family(-dark).svg from appMarks.ts.
// Run from ui/: node --experimental-strip-types src/appMarks.render.mjs
import { mkdirSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { APP_IDS, APP_NAMES, APP_COLORS, glyphMarkup, markSvg } from "./appMarks.ts";

const out = join(dirname(fileURLToPath(import.meta.url)), "../../docs/images/apps");
mkdirSync(out, { recursive: true });

for (const id of APP_IDS) writeFileSync(join(out, `${id}.svg`), `${markSvg(id, "light", 64)}\n`);

function family(theme) {
  const cell = 132;
  const tile = 72;
  const pad = 32;
  const width = pad * 2 + cell * APP_IDS.length;
  const height = 184;
  const bg = theme === "dark" ? "#000000" : "#f5f5f7";
  const ink = theme === "dark" ? "#f5f5f7" : "#1d1d1f";
  const sub = theme === "dark" ? "#98989d" : "#6e6e73";
  const font = "Inter, system-ui, -apple-system, Segoe UI, sans-serif";
  const items = APP_IDS.map((id, i) => {
    const x = pad + i * cell + (cell - tile) / 2;
    const cx = pad + i * cell + cell / 2;
    const scale = tile / 32;
    return `<g transform="translate(${x} 32) scale(${scale})"><rect width="32" height="32" rx="7" fill="${APP_COLORS[id][theme]}"/>${glyphMarkup(id, "#fff")}</g>`
      + `<text x="${cx}" y="134" text-anchor="middle" font-family="${font}" font-size="16" fill="${ink}"><tspan font-weight="600">${APP_NAMES[id]}</tspan></text>`
      + `<text x="${cx}" y="156" text-anchor="middle" font-family="${font}" font-size="11.5" fill="${sub}">${APP_COLORS[id].name}</text>`;
  }).join("");
  return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${width} ${height}" width="${width}" height="${height}" role="img" aria-label="PlantCraft app family"><title>PlantCraft app family</title><rect width="${width}" height="${height}" rx="12" fill="${bg}"/>${items}</svg>\n`;
}
writeFileSync(join(out, "family.svg"), family("light"));
writeFileSync(join(out, "family-dark.svg"), family("dark"));
console.log(`wrote ${APP_IDS.length + 2} files to ${out}`);
