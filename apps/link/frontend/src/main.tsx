import { startApp } from "@plantcraft/ui";
import { App } from "./App";
import { t } from "./i18n";
import "./styles.css";

// The suite's theme before the first paint, the shared components' strings through t().
startApp(App, { t });
