/** The setup guide: a small robot in the corner of every screen that walks an administrator
 * through a new installation, one step at a time (docs/setup-guide.md; owner, 2026-11-03: "a
 * robot beside the screen; the person asks, it answers and configures").
 *
 * The robot shows the step that comes now in a bubble; a click opens its card with every step.
 * Each step offers "Do it with me", which opens the assistant beside the page with that step's
 * work (the model knows the step, asks what it needs and proposes the change as a card the
 * person applies with one click), and the step's own page for doing it by hand. The guide reads
 * the installation's state again every few seconds while its card is open, so a step done
 * anywhere (with the robot, on its page, by another administrator) is seen and celebrated,
 * and the next one comes. Before a language model is connected the robot cannot talk: its
 * first step points to Settings › Language models. */
import { forgetAssistantStatus, openAssistant, startTour } from "@plantcraft/ui";
import { ArrowRight, Check, ChevronDown, ChevronUp, CircleAlert, LoaderCircle, MessageCircle, Play, PlugZap, SkipForward, Undo2, X } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { language, setLanguage, t, type Language } from "./i18n";
import { guideApi, guideLine, OPEN_GUIDE_EVENT, stepFacts, type ConnectionTest, type Guide, type GuideStep, type StartStep } from "./setupGuideApi";

/** While the card is open: often enough to see a connection or an import as it happens. */
const OPEN_POLL_MS = 5000;
/** While it is closed: only to keep the bubble about the right step. */
const CLOSED_POLL_MS = 60000;
const CHEER_MS = 4000;

/** The robot itself: a round head with a screen for a face, eyes that blink and an antenna that
 * glows. ``mood`` changes the face: listening, cheering, sleeping. */
export function GuideRobot({ mood = "idle", size = 48 }: { mood?: "idle" | "cheer" | "talk" | "sleep"; size?: number }) {
  return <svg className={`guide-robot guide-robot-${mood}`} width={size} height={size} viewBox="0 0 64 64" aria-hidden="true">
    <line className="guide-robot-antenna" x1="32" y1="6" x2="32" y2="15" />
    <circle className="guide-robot-light" cx="32" cy="6" r="4" />
    <rect className="guide-robot-ear" x="4" y="26" width="6" height="14" rx="3" />
    <rect className="guide-robot-ear" x="54" y="26" width="6" height="14" rx="3" />
    <rect className="guide-robot-head" x="9" y="14" width="46" height="38" rx="15" />
    <rect className="guide-robot-face" x="15" y="21" width="34" height="23" rx="10" />
    {mood === "sleep"
      ? <g className="guide-robot-eyes"><path d="M22 33h7M35 33h7" /></g>
      : mood === "cheer"
        ? <g className="guide-robot-eyes"><path d="M21 34l4-4 4 4M35 34l4-4 4 4" /></g>
        : <g className="guide-robot-eyes guide-robot-blink"><ellipse cx="25.5" cy="32" rx="3.4" ry="4.2" /><ellipse cx="38.5" cy="32" rx="3.4" ry="4.2" /></g>}
    {mood === "talk" && <rect className="guide-robot-mouth" x="28" y="38.5" width="8" height="2.6" rx="1.3" />}
    <rect className="guide-robot-neck" x="26" y="52" width="12" height="5" rx="2" />
  </svg>;
}

/** Open the assistant beside the page with ``step``'s work. */
function talkAbout(guide: Guide, step: GuideStep, help = false) {
  // The model may have been connected a moment ago (the guide's first step).
  forgetAssistantStatus();
  openAssistant({
    page: "processcraft:setup-guide",
    work: help ? "processcraft:guide-help" : step.work,
    title: t("Getting started"),
    place: `${t("Getting started")} › ${step.title}`,
    subject: "",
    facts: stepFacts(guide, step),
  });
}

export function SetupGuide({ navigate, onGuiding }: { navigate: (to: string) => void; onGuiding?: (guiding: boolean) => void }) {
  const [guide, setGuide] = useState<Guide | null>(null);
  const [open, setOpen] = useState(false);
  const [bubble, setBubble] = useState(true);
  const [cheer, setCheer] = useState<string | null>(null);
  const [showAll, setShowAll] = useState(false);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const before = useRef<Guide | null>(null);

  const load = useCallback(async () => {
    try {
      const found = await guideApi.get();
      const last = before.current;
      // A step that became done since the last read: the robot cheers it.
      const newly = last ? found.steps.find((step) => step.state === "done" && last.steps.find((old) => old.id === step.id)?.state !== "done") : undefined;
      if (newly) { setCheer(newly.title); setBubble(true); window.setTimeout(() => setCheer(null), CHEER_MS); }
      before.current = found;
      setGuide(found);
      // The basics changed this person's language: this browser follows (it reloads).
      const chosen = found.steps.find((step) => step.id === "basics")?.facts.my_language;
      if (newly?.id === "basics" && typeof chosen === "string" && chosen && chosen !== language) window.setTimeout(() => setLanguage(chosen as Language), 1500);
      onGuiding?.(!found.hidden && !found.finished);
    } catch {
      // Not an administrator, or offline: the robot stays away.
      onGuiding?.(false);
    }
  }, [onGuiding]);

  useEffect(() => { void load(); }, [load]);
  useEffect(() => {
    const timer = window.setInterval(() => { if (document.visibilityState === "visible") void load(); }, open ? OPEN_POLL_MS : CLOSED_POLL_MS);
    return () => window.clearInterval(timer);
  }, [open, load]);
  useEffect(() => {
    const show = () => { void guideApi.hide(false).then((found) => { before.current = found; setGuide(found); onGuiding?.(!found.finished); setOpen(true); }).catch(() => undefined); };
    window.addEventListener(OPEN_GUIDE_EVENT, show);
    return () => window.removeEventListener(OPEN_GUIDE_EVENT, show);
  }, [onGuiding]);

  if (!guide || guide.hidden) return null;
  const current = guide.steps.find((step) => step.id === guide.current) ?? null;
  const percent = guide.total ? Math.round((guide.done / guide.total) * 100) : 0;

  async function act(key: string, run: () => Promise<Guide | void>) {
    setBusy(key); setError("");
    try {
      const found = await run();
      if (found) { setGuide(found); }
      await load();
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : String(exc));
    } finally {
      setBusy("");
    }
  }

  const mood = cheer ? "cheer" : open ? "talk" : guide.finished ? "sleep" : "idle";
  const line = cheer ? t("Done: {step}. On to the next one!", { step: cheer }) : guide.finished ? t("Your plant is set up. Open me any time from Settings.") : guideLine(guide);

  return <div className={["setup-guide", open ? "setup-guide-open" : ""].filter(Boolean).join(" ")}>
    {open && <section className="guide-card" role="dialog" aria-label={t("Getting started")}>
      <header className="guide-card-head">
        <GuideRobot mood={mood} size={40} />
        <div className="guide-card-title">
          <strong>{guide.finished ? t("All set") : t("Let's set up your plant")}</strong>
          <span>{t("{done} of {total} steps", { done: guide.done, total: guide.total })}</span>
        </div>
        <button type="button" className="guide-icon-button" onClick={() => setOpen(false)} title={t("Close")} aria-label={t("Close")}><X size={16} /></button>
      </header>
      <div className="guide-progress" aria-hidden="true"><span style={{ width: `${percent}%` }} /></div>
      {cheer && <p className="guide-cheer"><Check size={14} /> {t("Done: {step}. On to the next one!", { step: cheer })}</p>}
      {current && <CurrentStep key={current.id} guide={guide} step={current} busy={busy} navigate={(to) => { navigate(to); }} act={act} />}
      {guide.finished && <div className="guide-step-body">
        <p>{t("Every step is done or skipped. The apps are collecting, monitoring and drafting; their Overview pages show what they find.")}</p>
        <div className="guide-actions">
          <button type="button" className="button button-primary" onClick={() => { setOpen(false); startTour(); }}><Play size={14} /> {t("Take the tour")}</button>
          <button type="button" className="button button-secondary" onClick={() => navigate("/")}><ArrowRight size={14} /> {t("Go to the Overview")}</button>
        </div>
      </div>}
      {error && <p className="guide-error"><CircleAlert size={14} /> {error}</p>}
      <button type="button" className="guide-all-toggle" onClick={() => setShowAll((value) => !value)} aria-expanded={showAll}>
        {showAll ? <ChevronUp size={14} /> : <ChevronDown size={14} />} {t("All steps")}
      </button>
      {showAll && <ol className="guide-steps">
        {guide.steps.map((step, index) => <li key={step.id} className={`guide-step-row guide-step-${step.state}`}>
          <span className="guide-step-dot">{step.state === "done" ? <Check size={12} /> : step.state === "skipped" ? <SkipForward size={11} /> : index + 1}</span>
          <span className="guide-step-name">{step.title}{step.optional && <em> · {t("optional")}</em>}</span>
          {step.state !== "current" && step.marked && <button type="button" className="guide-link" disabled={busy !== ""} onClick={() => void act(`undo-${step.id}`, () => guideApi.mark(step.id, null))} title={t("Take the mark back")}><Undo2 size={12} /></button>}
          {step.state === "todo" && <button type="button" className="guide-link" onClick={() => talkAbout(guide, step)} disabled={!guide.ready}>{t("Ask")}</button>}
        </li>)}
      </ol>}
      <footer className="guide-card-foot">
        <button type="button" className="guide-link" disabled={!guide.ready || !current} onClick={() => current && talkAbout(guide, current, true)}><MessageCircle size={13} /> {t("Ask the guide anything")}</button>
        <button type="button" className="guide-link" onClick={() => void act("hide", async () => { const found = await guideApi.hide(true); onGuiding?.(false); return found; })}>{t("Hide the guide")}</button>
      </footer>
    </section>}
    {!open && bubble && line && <div className="guide-bubble" role="status">
      <button type="button" className="guide-bubble-text" onClick={() => setOpen(true)}>{line}</button>
      <button type="button" className="guide-icon-button" onClick={() => setBubble(false)} title={t("Close")} aria-label={t("Close")}><X size={13} /></button>
    </div>}
    <button type="button" className="guide-launcher" onClick={() => setOpen((value) => !value)} title={t("Getting started")} aria-label={t("Getting started")} aria-expanded={open}>
      <GuideRobot mood={mood} size={44} />
      {!guide.finished && <span className="guide-badge">{guide.done}/{guide.total}</span>}
    </button>
  </div>;
}

/** The step that comes now: what and why, "Do it with me", its page, and its own tools (the
 * sources to test, the apps' first steps). */
function CurrentStep({ guide, step, busy, navigate, act }: { guide: Guide; step: GuideStep; busy: string; navigate: (to: string) => void; act: (key: string, run: () => Promise<Guide | void>) => Promise<void> }) {
  return <div className="guide-step-body">
    <h3>{step.title}{step.optional && <em> · {t("optional")}</em>}</h3>
    <p>{step.summary}</p>
    <p className="guide-why">{step.why}</p>
    {step.id === "connection" && <Sources step={step} busy={busy} act={act} />}
    {step.id === "start" && <StartSteps act={act} />}
    <div className="guide-actions">
      {step.id === "model"
        ? <button type="button" className="button button-primary" onClick={() => navigate(step.page)}><PlugZap size={14} /> {t("Open {page}", { page: step.page_label })}</button>
        : <button type="button" className="button button-primary" onClick={() => talkAbout(guide, step)}><MessageCircle size={14} /> {t("Do it with me")}</button>}
      {step.id !== "model" && <button type="button" className="button button-secondary" onClick={() => navigate(step.page)}>{t("Open {page}", { page: step.page_label })}</button>}
    </div>
    <div className="guide-actions guide-actions-quiet">
      {!step.seen && <button type="button" className="guide-link" disabled={busy !== ""} onClick={() => void act(`done-${step.id}`, () => guideApi.mark(step.id, "done"))}><Check size={13} /> {t("It is done")}</button>}
      <button type="button" className="guide-link" disabled={busy !== ""} onClick={() => void act(`skip-${step.id}`, () => guideApi.mark(step.id, "skipped"))}><SkipForward size={13} /> {t("Skip for now")}</button>
    </div>
    {step.id === "model" && <p className="guide-note">{t("After the model answers its Test, come back here: I will talk you through the rest.")}</p>}
  </div>;
}

function Sources({ step, busy, act }: { step: GuideStep; busy: string; act: (key: string, run: () => Promise<Guide | void>) => Promise<void> }) {
  const [tests, setTests] = useState<Record<string, ConnectionTest>>({});
  const sources = step.sources ?? [];
  if (!sources.length) return null;
  return <ul className="guide-sources">
    {sources.map((source) => {
      const tested = tests[source.source_id];
      const connected = source.state?.status === "connected" || tested?.ok;
      return <li key={source.source_id}>
        <span className={connected ? "guide-dot guide-dot-good" : "guide-dot"} />
        <span className="guide-source-name"><strong>{source.name}</strong> <span>{source.endpoint}</span>
          {tested && !tested.ok && <span className="guide-source-fail">{tested.message}</span>}
          {!tested && source.state?.detail && !connected && <span className="guide-source-fail">{source.state.detail}</span>}
        </span>
        <button type="button" className="guide-link" disabled={busy !== ""} onClick={() => void act(`test-${source.source_id}`, async () => { const answer = await guideApi.test(source.source_id); setTests((now) => ({ ...now, [source.source_id]: answer.test })); return answer.guide; })}>
          {busy === `test-${source.source_id}` ? <LoaderCircle className="spin" size={13} /> : <PlugZap size={13} />} {t("Test")}
        </button>
      </li>;
    })}
  </ul>;
}

function StartSteps({ act }: { act: (key: string, run: () => Promise<Guide | void>) => Promise<void> }) {
  const [steps, setSteps] = useState<StartStep[] | null>(null);
  const [done, setDone] = useState<Record<string, string>>({});
  const [running, setRunning] = useState("");
  useEffect(() => { guideApi.startSteps().then((found) => setSteps(found.steps)).catch(() => setSteps([])); }, []);
  if (steps === null) return <p className="guide-note"><LoaderCircle className="spin" size={13} /> {t("Working…")}</p>;
  if (!steps.length) return <p className="guide-note">{t("The apps start from an import: build the asset tree on Assets › Import first, or skip this step if you built it by hand.")}</p>;
  async function run(step: StartStep) {
    const key = `${step.app}:${step.id}`;
    setRunning(key);
    await act(`start-${key}`, async () => { const answer = await guideApi.takeStart(step); setDone((now) => ({ ...now, [key]: answer.summary })); });
    setRunning("");
  }
  return <ul className="guide-starts">
    {steps.map((step) => {
      const key = `${step.app}:${step.id}`;
      return <li key={key}>
        <span className="guide-source-name"><strong>{step.title}</strong> <span>{done[key] ?? `${step.app_name} · ${step.description}`}</span></span>
        {done[key] ? <Check size={14} className="guide-good" /> : <button type="button" className="guide-link" disabled={running !== ""} onClick={() => void run(step)}>{running === key ? <LoaderCircle className="spin" size={13} /> : <Play size={13} />} {t("Run it")}</button>}
      </li>;
    })}
    <li className="guide-starts-all"><button type="button" className="button button-secondary" disabled={running !== ""} onClick={() => void (async () => { for (const step of steps) if (!done[`${step.app}:${step.id}`]) await run(step); })()}><Play size={14} /> {t("Run them all")}</button></li>
  </ul>;
}
