import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App, { AppErrorBoundary } from "./App";
import "./styles.css";
import { initTheme } from "@plantcraft/ui";
// The interface language first: the shared components take its translator (i18n.ts).
import "./i18n";

initTheme();

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <AppErrorBoundary>
      <App />
    </AppErrorBoundary>
  </StrictMode>,
);
