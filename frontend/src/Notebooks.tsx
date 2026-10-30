/** Desk › Notebooks: JupyterLite (Python in the browser, offline) with the plant's data a call
 * away. Notebooks open in a tab of their own, where people work beside the suite (owner,
 * 2026-10-24): this page starts them, lists the person's notebooks and the examples. Arriving with
 * ``?signals=...&start=...&end=...`` (Historian, View) or ``?asset=...`` writes a notebook that
 * already loads them and opens it in this tab, which those pages open as a new one.
 * Administrators turn Notebooks on and off in Setup › Notebooks (``NotebookSettingsPage``). */
import { FormFooter, FormSection, Heading, PythonMark, useAssistantPage } from "@plantcraft/ui";
import { AlertTriangle, Copy, Download, ExternalLink, Gauge, Globe, KeyRound, LoaderCircle, Monitor, Power, Settings2 } from "lucide-react";
import { useCallback, useEffect, useRef, useState, type FormEvent, type MouseEvent, type ReactNode } from "react";
import { assistantApi } from "./AssistantAccess";
import { requestJson } from "./api";
import { t } from "./i18n";
import { navigate } from "./nav";
import { useIsAdmin } from "./session";
import { forget, install, installed, megabytes, type BrowserFiles } from "./notebookInstall";
import "./notebooks.css";

export type NotebookItem = { notebook_id: string; name: string; path: string; created_at: string; size: number; url: string };
export type NotebookExample = { id: string; title: string; summary: string };
export type UsageLimits = { per_minute: number; concurrent: number; default_per_minute: number; default_concurrent: number; updated_by: string | null; updated_at: string | null };
export type NotebooksOverview = {
  allowed: boolean; enabled: boolean; built: boolean; lab_url: string;
  package: { file: string; url: string } | null; notebooks: NotebookItem[]; examples?: NotebookExample[];
  limits?: UsageLimits; browser?: { build: string; bytes: number; files: number } | null;
  kit_enabled?: boolean; kits?: NotebookKits | null;
};
export type NotebookKit = { id: string; system: string; arch: string; bytes: number; sha256: string; url: string; installer?: { url: string; file: string; bytes: number; sha256: string } | null };
export type NotebookKits = { enabled: boolean; version: string; token_days: number; kits: NotebookKit[] };
export type KitToken = { token: string; expires_at: string; code?: string };
export type NotebookRequest = { kind: "series" | "asset" | "blank" | "example"; example?: string; signals?: string[]; start?: string; end?: string; step?: number; asset_id?: string; name?: string; origin?: string };

const json = (method: string, body?: unknown): RequestInit => ({ method, body: body === undefined ? undefined : JSON.stringify(body) });

export const notebooksApi = {
  overview: () => requestJson<NotebooksOverview>("/api/notebooks"),
  turn: (enabled: boolean) => requestJson<NotebooksOverview>("/api/notebooks/settings", json("PUT", { enabled })),
  turnKits: (kit_enabled: boolean) => requestJson<NotebooksOverview>("/api/notebooks/settings", json("PUT", { kit_enabled })),
  kitToken: () => requestJson<KitToken>("/api/notebooks/token", json("POST")),
  create: (request: NotebookRequest) => requestJson<NotebookItem>("/api/notebooks", json("POST", request)),
  files: () => requestJson<BrowserFiles>("/api/notebooks/files"),
  saveLimits: (limits: { per_minute: number; concurrent: number }) => requestJson<UsageLimits>("/api/notebooks/limits", json("PUT", limits)),
};

/** What the address asks for: a notebook of signals, of an asset, or nothing. */
export function requestFromQuery(search: string): NotebookRequest | null {
  const params = new URLSearchParams(search);
  const signals = params.getAll("signal").concat((params.get("signals") ?? "").split(",")).map((value) => value.trim()).filter(Boolean);
  const origin = params.get("origin") ?? undefined;
  if (signals.length) {
    const step = Number(params.get("step"));
    return { kind: "series", signals, start: params.get("start") || "-24h", end: params.get("end") || "now", step: Number.isFinite(step) && step > 0 ? step : undefined, origin };
  }
  const asset = params.get("asset");
  if (asset) return { kind: "asset", asset_id: asset, name: params.get("name") ?? undefined };
  return null;
}

/** Where a page of the suite links to open signals in a notebook. */
export function notebookLink(signals: string[], start: string, end: string, origin = ""): string {
  const params = new URLSearchParams({ signals: signals.join(","), start, end });
  if (origin) params.set("origin", origin);
  return `/notebooks?${params.toString()}`;
}

/** The lines that connect a notebook on the person's computer. */
export function computerSnippet(origin: string, token: string, file: string): string {
  return [`# ${file} installed (step 2)`, "import plantcraft_notebook as pc", `pc.connect("${origin}", token="${token}")`, "pc.me()"].join("\n");
}


/** The kit for the computer this page runs on: Windows, a Mac, else Linux. */
export function ownKit(kits: NotebookKit[], platform: string): NotebookKit | undefined {
  const name = platform.toLowerCase();
  const id = name.includes("win") ? "windows" : name.includes("mac") ? "macos" : name.includes("linux") ? "linux" : "";
  return kits.find((kit) => kit.id.startsWith(id + "-")) ?? undefined;
}

function message(error: unknown) {
  return error instanceof Error ? error.message : t("Couldn't complete the operation.");
}

/** A notebook's size the way a file browser says it. */
export function sizeText(bytes: number): string {
  if (bytes < 1024) return t("{count} bytes", { count: bytes });
  return `${Math.max(1, Math.round(bytes / 1024))} KB`;
}

const setupLink = (event: MouseEvent) => { event.preventDefault(); navigate("/setup/notebooks"); };

export default function NotebooksPage() {
  const isAdmin = useIsAdmin();
  const [data, setData] = useState<NotebooksOverview | null>(null);
  const [error, setError] = useState("");
  const [opening, setOpening] = useState("");
  const asked = useRef(false);
  const [where, setWhere] = useState<NotebookPlace>(rememberedPlace);
  const choose = (place: NotebookPlace) => { setWhere(place); keepPlace(place); };

  const load = useCallback(() => notebooksApi.overview().then((value) => { setData(value); return value; }), []);
  useAssistantPage({ place: t("Desk › Notebooks"), page: "processcraft:notebooks" });
  useEffect(() => {
    load().then(async (value) => {
      const request = requestFromQuery(window.location.search);
      if (!request || asked.current || !value.enabled || !value.built) return;
      asked.current = true;
      setOpening(t("Writing the notebook…"));
      const created = await notebooksApi.create(request);
      // Historian and View open this page in a new tab: the notebook takes it over.
      window.location.replace(created.url);
    }).catch((err) => { setOpening(""); setError(message(err)); });
  }, [load]);

  const heading = <Heading eyebrow={<><PythonMark size={14} /> {t("Desk")}</>} title={t("Notebooks")}
    detail={t("Python with the plant's data: numpy, pandas, scipy and matplotlib, offline. A notebook runs in your browser, on your computer, and reads the plant with your own access.")} />;

  if (opening) return <>{heading}<div className="module-state"><LoaderCircle className="spin" /><span>{opening}</span></div></>;
  if (error && !data) return <>{heading}<div className="form-error" role="alert"><AlertTriangle size={15} /> {error}</div></>;
  if (!data) return <>{heading}<div className="module-state"><LoaderCircle className="spin" /><span>{t("Loading…")}</span></div></>;
  if (!data.built) return <>{heading}<div className="module-state"><AlertTriangle /><span>{t("This installation was built without notebooks (make notebooks builds them).")}</span></div></>;
  if (!data.enabled) return <>{heading}
    <section className="panel nb-off">
      <span className="nb-off-icon"><PythonMark /></span>
      <div>
        <h2>{t("Notebooks are off")}</h2>
        <p>{t("With notebooks on, each person can analyse the plant's signals in Python, in a tab of their own: charts, statistics, comparisons. The code runs in their browser with their own access, so whoever may read a signal may analyse it, and nothing is downloaded from the internet.")}</p>
        {!data.allowed ? <p className="muted">{t("This installation turned notebooks off (PLANTCRAFT_NOTEBOOKS=off).")}</p>
          : isAdmin ? <a className="button button-primary" href="/setup/notebooks" onClick={setupLink}><Settings2 /> {t("Turn on in Settings")}</a>
            : <p className="muted">{t("Ask an administrator to turn them on.")}</p>}
      </div>
    </section>
  </>;

  return <>
    <Heading eyebrow={<><PythonMark size={14} /> {t("Desk")}</>} title={t("Notebooks")}
      detail={t("Python with the plant's data, reading with your own access. Choose where it runs.")} />
    {error && <div className="form-error" role="alert"><AlertTriangle size={15} /> {error}</div>}
    <WhereChoice where={where} onChoose={choose} />
    <section className="panel nb-panel" role="tabpanel" id={`nb-${where}`} aria-labelledby={`nb-tab-${where}`}>
      {where === "browser" ? <BrowserPanel data={data} /> : <ComputerPanel data={data} onError={setError} />}
    </section>
  </>;
}

export type NotebookPlace = "browser" | "computer";
const WHERE_KEY = "plantcraft.notebooks.where";

/** The place the person chose last on this browser; the browser the first time. */
export function rememberedPlace(): NotebookPlace {
  try { return window.localStorage.getItem(WHERE_KEY) === "computer" ? "computer" : "browser"; } catch { return "browser"; }
}

function keepPlace(where: NotebookPlace) {
  try { window.localStorage.setItem(WHERE_KEY, where); } catch { /* private window: the choice lasts this visit */ }
}

/** Two cards side by side, one line each; the chosen one opens its panel below (owner, 2026-10-27:
 * the page was too long and too much to read before starting). */
function WhereChoice({ where, onChoose }: { where: NotebookPlace; onChoose: (where: NotebookPlace) => void }) {
  const cards: { id: NotebookPlace; icon: ReactNode; title: string; line: string }[] = [
    { id: "browser", icon: <Globe />, title: t("Run in the browser"), line: t("Nothing to install: it opens in seconds.") },
    { id: "computer", icon: <Monitor />, title: t("Run on your computer"), line: t("Any package, all your computer's memory.") },
  ];
  return <div className="nb-choice" role="tablist" aria-label={t("Where notebooks run")}>
    {cards.map((card) => <button key={card.id} id={`nb-tab-${card.id}`} type="button" role="tab" aria-selected={where === card.id} aria-controls={`nb-${card.id}`}
      className={`nb-choice-card${where === card.id ? " on" : ""}`} onClick={() => onChoose(card.id)}>
      <span className="nb-choice-icon">{card.icon}</span>
      <span><strong>{card.title}</strong><small>{card.line}</small></span>
    </button>)}
  </div>;
}

type BrowserState = "checking" | "missing" | "installing" | "ready" | "failed";

/** In this browser: Python installed once into this browser, then JupyterLab in a new tab with the
 * examples and the person's notebooks as folders. */
function BrowserPanel({ data }: { data: NotebooksOverview }) {
  const [listing, setListing] = useState<BrowserFiles | null>(null);
  const [state, setState] = useState<BrowserState>("checking");
  const [done, setDone] = useState(0);
  const [problem, setProblem] = useState("");
  const abort = useRef<AbortController | null>(null);

  useEffect(() => {
    let live = true;
    notebooksApi.files().then(async (value) => {
      const here = await installed(value);
      if (live) { setListing(value); setState(here ? "ready" : "missing"); }
    }).catch((err) => { if (live) { setProblem(message(err)); setState("failed"); } });
    return () => { live = false; abort.current?.abort(); };
  }, []);

  async function start() {
    if (!listing) return;
    const controller = new AbortController();
    abort.current = controller;
    setState("installing"); setDone(0); setProblem("");
    try {
      await install(listing, setDone, controller.signal);
      setState("ready");
    } catch (err) {
      setState("missing");
      if (!controller.signal.aborted) setProblem(message(err));
    }
  }

  const size = megabytes(listing?.bytes ?? data.browser?.bytes ?? 0);
  const percent = listing?.bytes ? Math.min(100, Math.round((done / listing.bytes) * 100)) : 0;
  return <div className="nb-run">
    {state === "checking" && <p className="module-state"><LoaderCircle className="spin" /><span>{t("Checking whether Python is in this browser…")}</span></p>}
    {state === "failed" && <p className="form-error" role="alert"><AlertTriangle size={15} /> {problem}</p>}
    {state === "missing" && <>
      {problem && <p className="form-error" role="alert"><AlertTriangle size={15} /> {problem}</p>}
      <p>{t("Python downloads once into this browser ({size}); then JupyterLab opens in seconds. Nothing runs on the server.", { size })}</p>
      <div><button type="button" className="button button-primary" onClick={() => void start()}><Download /> {t("Install Python in this browser ({size}, once)", { size })}</button></div>
    </>}
    {state === "installing" && <>
      <p>{t("Downloading Python into this browser: {done} of {size}.", { done: megabytes(done), size })}</p>
      <div className="nb-progress" role="progressbar" aria-label={t("Downloading Python")} aria-valuemin={0} aria-valuemax={100} aria-valuenow={percent}><span style={{ width: `${percent}%` }} /></div>
      <div><button type="button" className="button button-secondary" onClick={() => abort.current?.abort()}>{t("Cancel")}</button></div>
    </>}
    {state === "ready" && <>
      <p>{t("Python is installed in this browser. JupyterLab opens in a new tab, with the Examples and My notebooks folders.")}</p>
      <div className="nb-run-actions">
        <a className="button button-primary" href={data.lab_url} target="_blank" rel="noreferrer"><ExternalLink /> {t("Open JupyterLab")}</a>
        <button type="button" className="button button-ghost" onClick={() => { forget(); setState("missing"); }}>{t("Install again")}</button>
      </div>
    </>}
    <details className="nb-more">
      <summary>{t("Limits of the browser")}</summary>
      <ul>
        <li>{t("Memory: what one browser tab may use, about 2 to 4 GB.")}</li>
        <li>{t("Only the packages that come with it (numpy, pandas, scipy, matplotlib): no pip install of others.")}</li>
        <li>{t("Slower than Python on your computer for heavy calculations.")}</li>
        <li>{t("What you change is kept in this browser only: File › Download keeps a copy.")}</li>
      </ul>
    </details>
  </div>;
}

/** On your computer: the PlantCraft Notebooks app when an administrator offers the kit, else the
 * package for a Python of the person's own. */
function ComputerPanel({ data, onError }: { data: NotebooksOverview; onError: (text: string) => void }) {
  const kits = data.kits?.enabled ? data.kits : null;
  if (!kits) return <div className="nb-run">
    <p>{t("Python on your computer, with every package you need and as much memory as it has. The notebook reads the plant as you, read-only, with an access token. Revoke the token on your profile when you stop using it.")}</p>
    <PackageSteps data={data} onError={onError} />
  </div>;
  return <div className="nb-run">
    <KitSteps kits={kits} onError={onError} />
    {data.package && <details className="nb-more"><summary>{t("Use my own Python instead")}</summary><PackageSteps data={data} onError={onError} /></details>}
  </div>;
}

/** The Notebooks app in three steps side by side: install it once, paste a connection code into it
 * once (one line with this PlantCraft's address, a read-only token of the person's own and the
 * fingerprint of its certificate authority, ``plantcraft_notebook.kit``), then open it. No link to
 * the app: browsers on some Windows computers ignore it without a word (#370). */
function KitSteps({ kits, onError }: { kits: NotebookKits; onError: (text: string) => void }) {
  const [token, setToken] = useState<KitToken | null>(null);
  const [copied, setCopied] = useState(false);
  const mine = ownKit(kits.kits, navigator.platform || navigator.userAgent);
  const others = kits.kits.filter((kit) => kit !== mine);
  async function createCode() {
    onError("");
    setCopied(false);
    try { setToken(await notebooksApi.kitToken()); } catch (err) { onError(message(err)); }
  }
  const code = token ? token.code ?? token.token : "";
  const name = (kit: NotebookKit) => `${kit.system} (${kit.arch})`;
  const download = (kit: NotebookKit) => kit.installer ?? { url: kit.url, bytes: kit.bytes };
  const system = mine?.id.split("-")[0] ?? "";
  // Without makensis where the kits were built, Windows gets the portable zip: no setup to double-click.
  const windowsSetup = !!kits.kits.find((kit) => kit.id.startsWith("windows"))?.installer;
  const howTo: Record<string, string> = {
    windows: windowsSetup
      ? t("Windows: double-click the file. The first time, if it says \"Windows protected your PC\", choose More info, then Run anyway: it is not signed yet.")
      : t("Windows: right-click the zip, Extract All (it takes a few minutes), then double-click Install in the folder. The first time, if it says \"Windows protected your PC\", choose More info, then Run anyway: it is not signed yet."),
    macos: t("macOS: open the zip and drag PlantCraft Notebooks to Applications, then open it. The first time macOS says it cannot check it: in System Settings › Privacy & Security, choose Open Anyway. It is not signed yet."),
    linux: t("Linux: unzip it where it should stay and run Install.sh."),
  };
  const opening: Record<string, string> = {
    windows: t("Open PlantCraft Notebooks from the Start menu."),
    macos: t("Open PlantCraft Notebooks from Applications."),
    linux: t("Open PlantCraft Notebooks from your applications."),
  };
  return <ol className="nb-kit">
    <li>
      <strong>{t("Install the app")}</strong>
      <p>{t("Python {python}, JupyterLab and the examples, for you only: no administrator needed.", { python: "3.12" })}</p>
      <div className="nb-run-actions">
        {(mine ? [mine] : kits.kits).map((kit) => <a key={kit.id} className="button button-primary" href={download(kit).url} download><Download /> {t("Download for {system}", { system: name(kit) })} · {megabytes(download(kit).bytes)}</a>)}
      </div>
      <details className="nb-more">
        <summary>{t("How to install")}</summary>
        {(system ? [system] : Object.keys(howTo)).map((id) => <p key={id}>{howTo[id]}</p>)}
        <p>
          {mine && others.length > 0 && <>{t("Other systems:")} {others.map((kit, index) => <span key={kit.id}>{index > 0 && " · "}<a className="text-link" href={download(kit).url} download>{name(kit)}</a></span>)}. </>}
          {mine?.installer && <>{t("Without installing:")} <a className="text-link" href={mine.url} download>{t("portable zip")}</a>.</>}
        </p>
      </details>
    </li>
    <li>
      <strong>{t("Connect it")}</strong>
      {token ? <>
        <span className="nb-token"><KeyRound size={14} /> {t("Copy it now: it will not be shown again.")}</span>
        <pre className="nb-code">{code}</pre>
        <div className="nb-run-actions"><button type="button" className="button button-primary button-small" onClick={() => void navigator.clipboard?.writeText(code).then(() => setCopied(true), () => setCopied(false))}><Copy /> {copied ? t("Copied") : t("Copy")}</button></div>
        <p>{t("Paste it into PlantCraft Notebooks when it asks (portable kit: Configure token).")}</p>
      </> : <>
        <p>{t("A one-line code connects the app to this PlantCraft as you, read-only, for {days} days.", { days: kits.token_days })}</p>
        <div className="nb-run-actions"><button type="button" className="button button-secondary" onClick={() => void createCode()}><KeyRound /> {t("Create a connection code")}</button></div>
      </>}
    </li>
    <li>
      <strong>{t("Open it")}</strong>
      <p>{opening[system] ?? t("Open PlantCraft Notebooks on your computer.")} {t("Your notebooks and the examples are in Documents › PlantCraft notebooks.")}</p>
    </li>
  </ol>;
}

/** The commands that install the package in a Python of the person's own: in a virtual
 * environment, since macOS and most Linux refuse a pip install outside one (PEP 668). */
export function ownPythonCommands(file: string, platform: string): string {
  const windows = platform.toLowerCase().includes("win");
  // A "~" in quotes stays a "~" in a Unix shell; the wheel's name has no spaces.
  const wheel = windows ? `"%USERPROFILE%\\Downloads\\${file}"` : `~/Downloads/${file}`;
  return (windows
    ? ["py -m venv plantcraft-env", "plantcraft-env\\Scripts\\activate"]
    : ["python3 -m venv ~/plantcraft-env", "source ~/plantcraft-env/bin/activate"]
  ).concat([`pip install jupyterlab matplotlib ${wheel}`, "jupyter lab"]).join("\n");
}

/** A Python the person has already: the package, a token and the lines that connect. */
function PackageSteps({ data, onError }: { data: NotebooksOverview; onError: (text: string) => void }) {
  const [token, setToken] = useState("");
  const [copied, setCopied] = useState("");
  async function createToken() {
    onError("");
    try { setToken((await assistantApi.create(t("Notebook on my computer"))).token); } catch (err) { onError(message(err)); }
  }
  if (!data.package) return <p className="muted">{t("The package is missing from this build.")}</p>;
  const file = data.package.file;
  const commands = ownPythonCommands(file, navigator.platform || navigator.userAgent);
  const snippet = computerSnippet(window.location.origin, token, file);
  const copy = (text: string, which: string) => void navigator.clipboard?.writeText(text).then(() => setCopied(which), () => setCopied(""));
  return <ol className="nb-steps">
    <li><a className="text-link" href={data.package.url} download={file}><Download size={13} /> {t("Download {file}", { file })}</a>
      <p className="muted">{t("Keep its name: pip refuses the file if the browser renamed it (\"(1)\" or \"-2\" at the end).")}</p></li>
    <li>{t("In a terminal, create a Python environment of its own, install the package with JupyterLab and start it (Python 3.11 or newer):")}
      <pre className="nb-code">{commands}</pre>
      <button type="button" className="button button-secondary button-small" onClick={() => copy(commands, "commands")}><Copy /> {copied === "commands" ? t("Copied") : t("Copy")}</button></li>
    <li>{token ? <span className="nb-token"><KeyRound size={14} /> <strong>{t("Copy it now: it will not be shown again.")}</strong></span>
      : <button type="button" className="button button-secondary button-small" onClick={() => void createToken()}><KeyRound /> {t("Create an access token")}</button>}</li>
    {token && <li>{t("In a notebook, connect:")}<pre className="nb-code">{snippet}</pre>
      <button type="button" className="button button-secondary button-small" onClick={() => copy(snippet, "snippet")}><Copy /> {copied === "snippet" ? t("Copied") : t("Copy")}</button></li>}
  </ol>;
}

/** Setup › Notebooks (administrators): the one switch. Off by default; when on, Notebooks is in
 * every person's Desk. */
export function NotebookSettingsPage() {
  const isAdmin = useIsAdmin();
  const [data, setData] = useState<NotebooksOverview | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => { notebooksApi.overview().then(setData).catch((err) => setError(message(err))); }, []);
  if (!isAdmin) return <div className="module-state module-error"><AlertTriangle /><span>{t("Only admins turn notebooks on or off.")}</span></div>;
  async function turn(enabled: boolean) {
    setBusy(true); setError("");
    try { await notebooksApi.turn(enabled); setData(await notebooksApi.overview()); } catch (err) { setError(message(err)); }
    setBusy(false);
  }
  const canTurn = Boolean(data?.built && data.allowed);
  return <>
    <Heading eyebrow={<><PythonMark size={14} /> {t("Administration")} · <a href="/setup" onClick={(event) => { event.preventDefault(); navigate("/setup"); }}>{t("Settings")}</a></>} title={t("Notebooks")}
      detail={t("Python notebooks with the plant's data, for everyone who may read it. They open from Desk, in a tab of their own.")}
      actions={data && <button type="button" className={`button ${data.enabled ? "button-secondary" : "button-primary"}`} disabled={busy || !canTurn} onClick={() => void turn(!data.enabled)}>{busy ? <LoaderCircle className="spin" /> : <Power />} {data.enabled ? t("Turn off") : t("Turn on")}</button>} />
    {error && <div className="form-error" role="alert"><AlertTriangle size={15} /> {error}</div>}
    {!data && !error && <div className="module-state"><LoaderCircle className="spin" /><span>{t("Loading…")}</span></div>}
    {data && <section className="panel form-panel">
      <FormSection id="nb-state" title={data.enabled ? t("On") : t("Off")} detail={!data.built ? t("This installation was built without notebooks (make notebooks builds them).")
        : !data.allowed ? t("This installation turned notebooks off (PLANTCRAFT_NOTEBOOKS=off).")
          : data.enabled ? t("Notebooks is in every person's Desk. Turning it off hides it and stops every notebook from reading the plant; what people wrote stays in their browsers.")
            : t("Turn it on when people may analyse the plant's data in Python. Nothing runs on this server: each notebook runs in its person's browser, with that person's access, and nothing is downloaded from the internet.")}>
        <ul className="nb-facts">
          <li>{t("Reads only: a notebook never changes anything in the plant or the suite.")}</li>
          <li>{t("Each person sees only their own notebooks; edits stay in their browser.")}</li>
          <li>{t("Turning it off takes effect at once: open notebooks can no longer read.")}</li>
        </ul>
      </FormSection>
    </section>}
    {data?.enabled && <NotebookKitSwitch data={data} onChanged={setData} onError={setError} />}
    {data?.limits && <NotebookLimits limits={data.limits} onSaved={(limits) => setData({ ...data, limits })} />}
  </>;
}

/** Setup › Notebooks › Kits: whether people download the kit for their own computer. */
function NotebookKitSwitch({ data, onChanged, onError }: { data: NotebooksOverview; onChanged: (data: NotebooksOverview) => void; onError: (text: string) => void }) {
  const [busy, setBusy] = useState(false);
  const kits = data.kits;
  async function turn(enabled: boolean) {
    setBusy(true); onError("");
    try { await notebooksApi.turnKits(enabled); onChanged(await notebooksApi.overview()); } catch (err) { onError(message(err)); }
    setBusy(false);
  }
  return <section className="panel form-panel">
    <FormSection id="nb-kits" icon={<Monitor size={16} />} title={t("Kit for people's computers")} detail={!kits
      ? t("This installation has no kits: they are an optional part of the offline bundle (make notebook-kits builds them). People can still install the package in a Python of their own.")
      : kits.enabled ? t("People download Python and JupyterLab for Windows, macOS and Linux from Notebooks, set to this server. Their notebooks run on their computers and read the plant with their own token, within the limits below.")
        : t("Off: people see the package for a Python of their own. Turn it on to offer the kit ({count} systems, version {version}). It runs on their computers, never on this server.", { count: kits.kits.length, version: kits.version })}>
      {kits && <div className="nb-run-actions"><button type="button" className={`button ${kits.enabled ? "button-secondary" : "button-primary"}`} disabled={busy} onClick={() => void turn(!kits.enabled)}>{busy ? <LoaderCircle className="spin" /> : <Power />} {kits.enabled ? t("Turn off the kit") : t("Turn on the kit")}</button></div>}
    </FormSection>
  </section>;
}

/** How much one person may ask the plant for: a heavy notebook or script slows down its owner
 * alone, never the apps (``plantcraft/api/usage.py``). */
function NotebookLimits({ limits, onSaved }: { limits: UsageLimits; onSaved: (limits: UsageLimits) => void }) {
  const [perMinute, setPerMinute] = useState(String(limits.per_minute));
  const [concurrent, setConcurrent] = useState(String(limits.concurrent));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const changed = perMinute !== String(limits.per_minute) || concurrent !== String(limits.concurrent);
  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true); setError(""); setNotice("");
    try {
      onSaved(await notebooksApi.saveLimits({ per_minute: Number(perMinute), concurrent: Number(concurrent) }));
      setNotice(t("Saved. Every server process follows within 10 seconds."));
    } catch (err) { setError(message(err)); }
    setBusy(false);
  }
  return <form className="panel form-panel" onSubmit={(event) => void submit(event)}>
    {error && <div className="form-error" role="alert"><AlertTriangle size={15} /> {error}</div>}
    {notice && <div className="ac-notice" role="status">{notice}</div>}
    <FormSection id="nb-limits" icon={<Gauge size={16} />} title={t("Limits for each person")} detail={<>
      <p>{t("How much one person's notebooks, scripts and assistants may ask the plant for. Past a limit only that person waits: the notebook package waits and asks again by itself. The apps' own reads (Analytics, Alarms, View) never count.")}</p>
      <p>{limits.updated_by ? t("Set by {who}.", { who: limits.updated_by }) : t("The defaults: {perMinute} a minute, {concurrent} at once.", { perMinute: limits.default_per_minute, concurrent: limits.default_concurrent })}</p>
    </>}>
      <div className="form-grid">
        <label>{t("Requests a minute")}<input type="number" min={10} max={6000} required value={perMinute} onChange={(event) => setPerMinute(event.target.value)} /></label>
        <label>{t("Reads at once")}<input type="number" min={1} max={32} required value={concurrent} onChange={(event) => setConcurrent(event.target.value)} /></label>
      </div>
    </FormSection>
    <FormFooter note={t("Every refusal is in the audit log, once a minute for each person.")}>
      {changed && <button type="button" className="button button-secondary" onClick={() => { setPerMinute(String(limits.per_minute)); setConcurrent(String(limits.concurrent)); }}>{t("Cancel")}</button>}
      <button className="button button-primary" disabled={busy || !changed}>{busy && <LoaderCircle className="spin" />} {t("Save")}</button>
    </FormFooter>
  </form>;
}
