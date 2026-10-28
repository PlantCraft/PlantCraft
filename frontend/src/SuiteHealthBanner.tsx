/** For administrators: a line above every page while the suite watch has an open incident. */
import { AlertTriangle } from "lucide-react";
import { useEffect, useState } from "react";
import { t } from "./i18n";
import { navigate } from "./nav";
import { operationsApi, type Incident } from "./operationsApi";

const EVERY_MS = 60_000;

export default function SuiteHealthBanner() {
  const [open, setOpen] = useState<Incident[]>([]);
  useEffect(() => {
    let alive = true;
    const load = () => operationsApi.health().then((value) => { if (alive) setOpen(value.open); }).catch(() => undefined);
    void load();
    const timer = window.setInterval(load, EVERY_MS);
    return () => { alive = false; window.clearInterval(timer); };
  }, []);
  if (!open.length) return null;
  const first = open[0];
  return <div className="form-error ops-banner" role="status">
    <AlertTriangle size={15} />
    <span>{open.length === 1 ? t("{subject}: {detail}", { subject: first.subject, detail: first.detail }) : t("{count} problems in the suite, the first: {subject}", { count: open.length, subject: first.subject })}</span>
    <button className="button button-secondary" onClick={() => navigate("/health")}>{t("See the suite's health")}</button>
  </div>;
}
