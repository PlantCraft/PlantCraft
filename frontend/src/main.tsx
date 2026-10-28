import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App, { AppErrorBoundary } from "./App";
import "./styles.css";
import { configureUi, initTheme } from "@plantcraft/ui";
import { TRANSLATIONS, locale, t } from "./i18n";

initTheme();
configureUi({ t, locale, translations: TRANSLATIONS });

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <AppErrorBoundary>
      <App />
    </AppErrorBoundary>
  </StrictMode>,
);
