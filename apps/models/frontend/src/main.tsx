import { startApp } from "@plantcraft/ui";
import { App } from "./App";
import { t } from "./i18n";
import "./styles.css";

// The suite's theme before the first paint, the shared components' strings through t().
// This app's own status ids (the suite's are in the package).
startApp(App, { t, statusTones: {
  unknown: "inactive",
  "run-queued": "inactive", "run-running": "info", "run-done": "good", "run-failed": "problem", "run-cancelled": "inactive",
  "level-error": "problem", "level-warning": "attention", "level-info": "info",
} });
