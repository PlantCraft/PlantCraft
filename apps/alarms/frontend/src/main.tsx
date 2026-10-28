import { startApp } from "@plantcraft/ui";
import { App } from "./App";
import { t } from "./i18n";
import "./styles.css";

// The suite's theme before the first paint, the shared components' strings through t().
// This app's own status ids (the suite's are in the package).
startApp(App, { t, statusTones: {
  unknown: "inactive",
  "alarm-unacked": "problem", "alarm-acked": "attention", "alarm-rtn_unacked": "info",
  "alarm-shelved": "inactive", "alarm-out_of_service": "inactive", "alarm-normal": "good",
  "priority-critical": "problem", "priority-high": "serious", "priority-medium": "attention", "priority-low": "info",
} });
