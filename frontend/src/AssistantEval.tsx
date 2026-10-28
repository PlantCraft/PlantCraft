/** Setup › Language models › Evaluation (docs/assistant.md): questions whose right answer is
 * known, read from this plant's data at each run, asked to a model with the assistant's tools;
 * or each of the assistant's works asked as its page asks it, with the context PlantCraft builds
 * (Evaluate works). Each case shows the question, the expected answer, the model's answer and why
 * it passed; a work's case also the context sent and the card proposed. */
import { useEffect, useState } from "react";
import { CheckCircle2, ChevronDown, ChevronRight, LoaderCircle, Play, Target, XCircle } from "lucide-react";
import { FormSection, formatDate } from "@plantcraft/ui";
import { assistantApi, type AssistantProfile, type EvalRun, type EvalSuite } from "./assistantApi";
import { errorText } from "./collab";
import { t } from "./i18n";
import "./assistant.css";

const POLL_MS = 2_000;

/** "5 of 7" and the share, for a run's heading. */
export function evalScore(run: Pick<EvalRun, "passed" | "total">): string {
  if (!run.total) return "–";
  return `${run.passed}/${run.total} · ${Math.round((100 * run.passed) / run.total)} %`;
}

export function AssistantEvaluation({ allowed }: { allowed: boolean }) {
  const [runs, setRuns] = useState<EvalRun[] | null>(null);
  const [profiles, setProfiles] = useState<AssistantProfile[]>([]);
  const [profile, setProfile] = useState("");
  const [shown, setShown] = useState<number | null>(null);
  const [error, setError] = useState("");
  const running = runs?.some((item) => item.state === "running") ?? false;

  useEffect(() => {
    let alive = true;
    const load = () => assistantApi.evals().then((value) => { if (!alive) return; setRuns(value.runs); setProfiles(value.profiles.filter((item) => item.ready)); }).catch((err) => alive && setError(errorText(err)));
    void load();
    if (!running) return () => { alive = false; };
    const timer = window.setInterval(load, POLL_MS);
    return () => { alive = false; window.clearInterval(timer); };
  }, [running]);

  async function start(suite: EvalSuite) {
    setError("");
    try { const run = await assistantApi.startEval(profile, suite); setRuns((current) => [run, ...(current ?? [])]); setShown(run.run_id); }
    catch (err) { setError(errorText(err)); }
  }

  const open = runs?.find((item) => item.run_id === shown) ?? runs?.[0] ?? null;
  return <FormSection id="asst-eval" icon={<Target size={16} />} title={t("Evaluation")} detail={t("Questions whose right answer is known, read from this plant's data at each run: a signal's mean and maximum over a day, a chart, how many assets of a type, a tag that does not exist, an app the person may not open, a request outside the platform (declined). Evaluate tasks asks each of the assistant's tasks the way its page asks it, with the same context, and checks that the model reads it: an answer that reads the plant and names the page's subject, or a card with the object's fields. Run them after changing the model, a specialist's instructions or a task.")}>
    <div className="heading-actions">
      {profiles.length > 1 && <select value={profile} onChange={(event) => setProfile(event.target.value)} aria-label={t("Answer as")}>{profiles.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select>}
      <button type="button" className="button button-secondary" onClick={() => void start("questions")} disabled={!allowed || running || !profiles.length}>{running ? <LoaderCircle className="spin" /> : <Play />} {running ? t("Evaluating…") : t("Evaluate")}</button>
      <button type="button" className="button button-secondary" onClick={() => void start("works")} disabled={!allowed || running || !profiles.length}><Play /> {t("Evaluate tasks")}</button>
    </div>
    {error && <div className="form-error">{error}</div>}
    {runs && !runs.length && <p className="muted">{profiles.length ? t("No evaluation yet.") : t("Set up a model first.")}</p>}
    {open && <EvalRunView run={open} />}
    {runs && runs.length > 1 && <details className="asst-eval-older"><summary>{t("Earlier runs")}</summary>
      <ul>{runs.map((item) => <li key={item.run_id}><button type="button" className={item.run_id === open?.run_id ? "active" : ""} onClick={() => setShown(item.run_id)}>{formatDate(item.created_at)} · {item.suite === "works" ? t("Tasks") : t("Questions")} · {item.model || t("Assistant")} · {evalScore(item)}</button></li>)}</ul>
    </details>}
  </FormSection>;
}

function EvalRunView({ run }: { run: EvalRun }) {
  const [open, setOpen] = useState<string | null>(null);
  return <div className="asst-eval-run">
    <p className="asst-eval-summary"><strong>{evalScore(run)}</strong> <span className="muted">{run.suite === "works" ? `${t("Tasks")} · ` : ""}{run.model} · {formatDate(run.created_at)}{run.state === "running" ? ` · ${t("running")}` : ""}{run.state === "failed" ? ` · ${t("stopped: {error}", { error: run.error })}` : ""}</span></p>
    <ul className="asst-eval-cases">
      {run.results.map((item) => <li key={item.id} className={item.passed ? "ok" : "bad"}>
        <button type="button" className="asst-eval-case" aria-expanded={open === item.id} onClick={() => setOpen(open === item.id ? null : item.id)}>
          {item.passed ? <CheckCircle2 size={15} aria-label={t("Passed")} /> : <XCircle size={15} aria-label={t("Failed")} />}
          <span>{t(item.title)}</span><small className="muted">{item.why}</small>
          {open === item.id ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
        </button>
        {open === item.id && <dl className="asst-eval-detail">
          <div><dt>{t("Question")}</dt><dd>{item.question}</dd></div>
          <div><dt>{item.work ? t("Expected") : t("Golden answer")}</dt><dd>{item.golden}</dd></div>
          <div><dt>{t("The model's answer")}</dt><dd className="asst-eval-answer">{item.error || item.answer || "–"}</dd></div>
          {item.work && <div><dt>{t("Task")}</dt><dd><code>{item.work}</code> · <code>{item.page}</code>{item.subject ? <> · <code>{item.subject}</code></> : null}</dd></div>}
          {item.proposal && <div><dt>{t("Card proposed")}</dt><dd><pre className="asst-eval-context">{JSON.stringify(item.proposal, null, 2)}</pre></dd></div>}
          {item.context && <div><dt>{t("Context sent")}</dt><dd><details><summary>{t("{count} characters", { count: item.context.length })}</summary><pre className="asst-eval-context">{item.context}</pre></details></dd></div>}
          <div><dt>{t("Reads")}</dt><dd>{item.tools.length ? item.tools.join(", ") : t("none")}{item.charts ? ` · ${t("{count} chart(s)", { count: item.charts })}` : ""} · {item.seconds} s</dd></div>
        </dl>}
      </li>)}
      {run.skipped && run.skipped.length > 0 && <li className="muted asst-eval-skipped">{t("Left out, no such object here to ask about: {tasks}", { tasks: run.skipped.join(", ") })}</li>}
      {run.state === "running" && run.results.length < run.total && <li className="asst-eval-pending"><LoaderCircle className="spin" size={15} /> {t("Case {number} of {total}…", { number: run.results.length + 1, total: run.total })}</li>}
    </ul>
  </div>;
}
