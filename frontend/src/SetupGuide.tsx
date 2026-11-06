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
import { ArrowRight, Check, Trophy, ChevronDown, ChevronUp, CircleAlert, LoaderCircle, MessageCircle, Play, PlugZap, SkipForward, Undo2, X } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { language, setLanguage, t, type Language } from "./i18n";
import { GuideRobot } from "./GuideRobot";
import { guideApi, guideLine, nextMission, OPEN_GUIDE_EVENT, stepFacts, type ConnectionTest, type Guide, type GuideMission, type GuideStep, type StartStep } from "./setupGuideApi";

/** While the card is open: often enough to see a connection or an import as it happens. */
const OPEN_POLL_MS = 5000;
/** While it is closed: only to keep the bubble about the right step. */
const CLOSED_POLL_MS = 60000;
/** After "Do it with me" or "Open <page>" the card is closed but the person is doing a step: look
 * as often as with the card open, for this long, so the guide moves on right after "Create". */
const TALKING_MS = 15 * 60_000;
let talkingSince = 0;
const CHEER_MS = 4000;

/** The bubble sits over the page's corner: it speaks on the Overview only (and to cheer a step
 * just done), so it never covers a field, a button or a chart on the other pages (owner,
 * 2026-11-06). The robot itself stays in the corner of every page. */
function onHome(): boolean {
  const path = window.location.pathname.replace(/\/+$/, "");
  return path === "" || path === "/desk";
}

/** Open the assistant beside the page with a mission's work. */
function talkMission(guide: Guide, mission: GuideMission) {
  talkingSince = Date.now();
  forgetAssistantStatus();
  openAssistant({
    page: "processcraft:setup-guide",
    work: mission.work,
    title: "Heron",
    place: `${t("First missions")} › ${mission.title}`,
    subject: "",
    facts: { mission: mission.id, mission_title: mission.title, mission_page: `${mission.page_label} (${mission.page})`, missions: guide.missions.map((item) => `${item.title}: ${item.done ? "done" : "to do"}`).join("; ") },
  });
}

/** Open the assistant beside the page with ``step``'s work. */
function talkAbout(guide: Guide, step: GuideStep, help = false) {
  talkingSince = Date.now();
  // The model may have been connected a moment ago (the guide's first step).
  forgetAssistantStatus();
  openAssistant({
    page: "processcraft:setup-guide",
    work: help ? "processcraft:guide-help" : step.work,
    title: "Heron",
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
      const mission = last ? found.missions.find((item) => item.done && !last.missions.find((old) => old.id === item.id)?.done) : undefined;
      const won = newly?.title ?? (mission ? t("Mission complete: {mission}", { mission: mission.title }) : null);
      if (won) { setCheer(won); setBubble(true); window.setTimeout(() => setCheer(null), CHEER_MS); }
      before.current = found;
      setGuide(found);
      // The basics changed this person's language: this browser follows (it reloads).
      const chosen = found.steps.find((step) => step.id === "basics")?.facts.my_language;
      if (newly?.id === "basics" && typeof chosen === "string" && chosen && chosen !== language) window.setTimeout(() => setLanguage(chosen as Language), 1500);
      onGuiding?.(!found.hidden && !(found.finished && found.missions_done >= found.missions.length));
    } catch {
      // Not an administrator, or offline: the robot stays away.
      onGuiding?.(false);
    }
  }, [onGuiding]);

  useEffect(() => { void load(); }, [load]);
  useEffect(() => {
    let last = Date.now();
    const timer = window.setInterval(() => {
      if (document.visibilityState !== "visible") return;
      const fast = open || Date.now() - talkingSince < TALKING_MS;
      if (!fast && Date.now() - last < CLOSED_POLL_MS) return;
      last = Date.now();
      void load();
    }, OPEN_POLL_MS);
    return () => window.clearInterval(timer);
  }, [open, load]);
  useEffect(() => {
    const show = () => { void guideApi.hide(false).then((found) => { before.current = found; setGuide(found); onGuiding?.(!(found.finished && found.missions_done >= found.missions.length)); setOpen(true); }).catch(() => undefined); };
    window.addEventListener(OPEN_GUIDE_EVENT, show);
    return () => window.removeEventListener(OPEN_GUIDE_EVENT, show);
  }, [onGuiding]);

  if (!guide || guide.hidden) return null;
  const current = guide.steps.find((step) => step.id === guide.current) ?? null;
  const missionsLeft = guide.missions.length - guide.missions_done;
  const percent = guide.finished
    ? (guide.missions.length ? Math.round((guide.missions_done / guide.missions.length) * 100) : 100)
    : guide.total ? Math.round((guide.done / guide.total) * 100) : 0;
  const upNext = nextMission(guide);

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

  const allDone = guide.finished && missionsLeft === 0;
  const mood = cheer ? "cheer" : busy ? "load" : error ? "error" : open ? "talk" : allDone ? "sleep" : "idle";
  const line = cheer ? t("Done: {step}. On to the next one!", { step: cheer })
    : allDone ? t("Your plant is set up. Open me any time from Settings.")
      : upNext ? t("Next mission: {mission}", { mission: upNext.title }) : guideLine(guide);

  return <div className={["setup-guide", open ? "setup-guide-open" : ""].filter(Boolean).join(" ")}>
    {open && <section className="guide-card" role="dialog" aria-label={t("Heron, your setup guide")}>
      <header className="guide-card-head">
        <GuideRobot mood={mood} size={56} />
        <div className="guide-card-title">
          <strong>{allDone ? t("All set") : guide.finished ? t("First missions") : t("Let's set up your plant")}</strong>
          <span>{guide.finished ? t("{done} of {total} missions", { done: guide.missions_done, total: guide.missions.length }) : t("{done} of {total} steps", { done: guide.done, total: guide.total })}</span>
        </div>
        <button type="button" className="guide-icon-button" onClick={() => setOpen(false)} title={t("Close")} aria-label={t("Close")}><X size={16} /></button>
      </header>
      <div className="guide-progress" aria-hidden="true"><span style={{ width: `${percent}%` }} /></div>
      {cheer && <p className="guide-cheer"><Check size={14} /> {t("Done: {step}. On to the next one!", { step: cheer })}</p>}
      {current && <CurrentStep key={current.id} guide={guide} step={current} busy={busy} navigate={(to) => { talkingSince = Date.now(); navigate(to); }} act={act} />}
      {guide.finished && !allDone && <Missions guide={guide} navigate={(to) => { talkingSince = Date.now(); navigate(to); }} />}
      {allDone && <div className="guide-step-body">
        <p>{guide.steps.some((step) => step.id === "start" && step.facts.no_app_steps) ? t("Every step and mission is done. Install apps from Settings › Apps to collect, monitor and draft from the plant's data.") : t("Every step and mission is done. The apps are collecting, monitoring and drafting; their Overview pages show what they find.")}</p>
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
        {guide.missions.length > 0 && <li className="guide-steps-heading">{t("Then, the first missions")}</li>}
        {guide.missions.map((mission) => <li key={mission.id} className={`guide-step-row guide-step-${mission.done ? "done" : "todo"}`}>
          <span className={mission.done ? "guide-step-dot guide-trophy-won" : "guide-step-dot"}><Trophy size={11} /></span>
          <span className="guide-step-name">{mission.title}</span>
        </li>)}
      </ol>}
      <footer className="guide-card-foot">
        <button type="button" className="guide-link" disabled={!guide.ready || (!current && !guide.steps.length)} onClick={() => talkAbout(guide, current ?? guide.steps[guide.steps.length - 1], true)}><MessageCircle size={13} /> {t("Ask the guide anything")}</button>
        <button type="button" className="guide-link" onClick={() => void act("hide", async () => { const found = await guideApi.hide(true); onGuiding?.(false); return found; })}>{t("Hide the guide")}</button>
      </footer>
    </section>}
    {!open && bubble && line && (cheer || onHome()) && <div className="guide-bubble" role="status">
      <button type="button" className="guide-bubble-text" onClick={() => setOpen(true)}>{line}</button>
      <button type="button" className="guide-icon-button" onClick={() => setBubble(false)} title={t("Close")} aria-label={t("Close")}><X size={13} /></button>
    </div>}
    <button type="button" className="guide-launcher" onClick={() => setOpen((value) => !value)} title={t("Heron, your setup guide")} aria-label={t("Heron, your setup guide")} aria-expanded={open}>
      <GuideRobot mood={mood} size={44} view="head" />
      {!guide.finished && <span className="guide-badge">{guide.done}/{guide.total}</span>}
      {guide.finished && !allDone && <span className="guide-badge guide-badge-trophy"><Trophy size={10} /> {guide.missions_done}/{guide.missions.length}</span>}
    </button>
  </div>;
}

/** The first missions, once the setup is done: each one a thing that shows what the suite does,
 * with the robot beside the person ("Do it with me") or straight on its page. */
function Missions({ guide, navigate }: { guide: Guide; navigate: (to: string) => void }) {
  const next = nextMission(guide);
  return <div className="guide-step-body">
    <p className="guide-why">{t("Your plant is set up. Now try what PlantCraft is for: each mission takes a few minutes.")}</p>
    <ul className="guide-missions">
      {guide.missions.map((mission) => <li key={mission.id} className={["guide-mission", mission.done ? "guide-mission-done" : "", mission.id === next?.id ? "guide-mission-next" : ""].filter(Boolean).join(" ")}>
        <span className="guide-mission-trophy"><Trophy size={16} /></span>
        <div className="guide-mission-text">
          <strong>{mission.title}</strong>
          <span>{mission.done ? t("Done") : mission.summary}</span>
          {!mission.done && mission.id === next?.id && <div className="guide-actions">
            <button type="button" className="button button-primary" disabled={!guide.ready} onClick={() => talkMission(guide, mission)}><MessageCircle size={14} /> {t("Do it with me")}</button>
            <button type="button" className="button button-secondary" onClick={() => navigate(mission.page)}>{t("Open {page}", { page: mission.page_label })}</button>
          </div>}
          {!mission.done && mission.id !== next?.id && <button type="button" className="guide-link" onClick={() => navigate(mission.page)}>{t("Open {page}", { page: mission.page_label })}</button>}
        </div>
      </li>)}
    </ul>
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
