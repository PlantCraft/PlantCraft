// Opens each case in Chromium, waits for its result, reads the JS heap and takes a screenshot.
// node run.mjs <out dir> <plan.json>   plan: [{ "case": "c1-uplot", "q": "n=200000", "w": 1280, "h": 800 }]
import { createRequire } from "node:module";
const { chromium } = createRequire(import.meta.url)(process.env.PLAYWRIGHT_MODULE ?? "playwright");
import http from "node:http";
import { readFileSync, writeFileSync, mkdirSync, existsSync } from "node:fs";
import path from "node:path";

const [out, planFile] = process.argv.slice(2);
mkdirSync(path.join(out, "prints"), { recursive: true });
const plan = JSON.parse(readFileSync(planFile, "utf8"));
const sizes = JSON.parse(readFileSync("dist/sizes.json", "utf8"));
const types = { ".html": "text/html", ".js": "text/javascript", ".css": "text/css", ".json": "application/json", ".ttf": "font/ttf", ".woff2": "font/woff2", ".woff": "font/woff" };
const server = http.createServer((req, res) => {
  const file = path.join(process.cwd(), decodeURIComponent(new URL(req.url, "http://x").pathname));
  if (!file.startsWith(process.cwd()) || !existsSync(file)) { res.writeHead(404).end(); return; }
  res.writeHead(200, { "content-type": types[path.extname(file)] ?? "application/octet-stream" }).end(readFileSync(file));
}).listen(0);
const port = server.address().port;
const browser = await chromium.launch({ args: ["--enable-precise-memory-info", "--js-flags=--expose-gc", "--enable-unsafe-swiftshader", "--ignore-gpu-blocklist"] });
const resultsFile = path.join(out, "results.json");
const results = existsSync(resultsFile) ? JSON.parse(readFileSync(resultsFile, "utf8")) : {};
for (const step of plan) {
  const key = `${step.case}${step.q ? "?" + step.q : ""}`;
  const context = await browser.newContext({ viewport: { width: step.w ?? 1280, height: step.h ?? 800 }, deviceScaleFactor: 1, isMobile: !!step.mobile, hasTouch: !!step.mobile });
  const page = await context.newPage();
  const errors = [];
  page.on("pageerror", (e) => errors.push(String(e)));
  const cdp = await context.newCDPSession(page);
  await cdp.send("Performance.enable");
  const t0 = Date.now();
  let result;
  try {
    await page.goto(`http://127.0.0.1:${port}/page.html?case=${step.case}&${step.q ?? ""}`);
    await page.waitForFunction(() => window.__result, null, { timeout: (step.timeout ?? 180) * 1000, polling: 200 });
    result = await page.evaluate(() => window.__result);
  } catch (e) { result = { error: `timeout or crash: ${String(e).slice(0, 200)}` }; }
  try {
    await page.evaluate(() => window.gc && window.gc());
    const metrics = Object.fromEntries((await cdp.send("Performance.getMetrics")).metrics.map((m) => [m.name, m.value]));
    result.heap_mb = Math.round(metrics.JSHeapUsedSize / 1048576);
    result.dom_nodes = metrics.Nodes;
    const shot = `${key.replace(/[?&=]/g, "_")}.png`;
    await page.screenshot({ path: path.join(out, "prints", shot), timeout: 60000 });
    result.print = `prints/${shot}`;
  } catch (e) { result.after_error = String(e).slice(0, 200); }
  result.wall_s = Math.round((Date.now() - t0) / 100) / 10;
  if (errors.length) result.page_errors = errors.slice(0, 3);
  result.bundle = sizes[step.case];
  results[key] = result;
  console.log(key, JSON.stringify(result));
  writeFileSync(resultsFile, JSON.stringify(results, null, 1));
  await context.close();
}
await browser.close();
server.close();
