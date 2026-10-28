/**
 * How an app of the suite starts (scale review A2): its main.tsx is one call, startApp(App), and
 * its App one hook, useSuiteSession(), instead of the same lines copied in every app.
 */
import { StrictMode, useEffect, type ComponentType } from "react";
import { createRoot } from "react-dom/client";
import { addStatusTones, type StatusTone } from "./brandTheme.js";
import { configureUi } from "./i18n.js";
import { RENEW_EVERY_MS, renewToken, signInAgain } from "./session.js";
import { initTheme } from "./theme.js";

export type StartAppOptions = {
  /** The app's translator: the shared components' strings go through it too. */
  t?: (text: string, values?: Record<string, string | number>) => string;
  /** The app's own status ids and the tone each is drawn in (the suite's are in the package). */
  statusTones?: Record<string, StatusTone>;
  /** The element the app is drawn in; `#root` when left out. */
  root?: string;
};

/**
 * Apply the theme chosen in any app of the suite before the first paint, hand the app's `t` and
 * status tones to the shared components, and draw `App` in `#root`.
 */
export function startApp(App: ComponentType, options: StartAppOptions = {}) {
  initTheme();
  if (options.t) configureUi({ t: options.t });
  if (options.statusTones) addStatusTones(options.statusTones);
  const element = document.querySelector(options.root ?? "#root");
  if (!element) throw new Error(`startApp: no ${options.root ?? "#root"} in the page`);
  createRoot(element).render(<StrictMode><App /></StrictMode>);
}

/**
 * Keep the suite session alive while the app is open: PlantCraft's token is renewed every
 * RENEW_EVERY_MS, and the page signs in again when the app's API answers 401 twice
 * (`unauthorizedEvent`, from createApiClient).
 */
export function useSuiteSession(unauthorizedEvent: string) {
  useEffect(() => {
    window.addEventListener(unauthorizedEvent, signInAgain);
    const timer = window.setInterval(() => void renewToken(), RENEW_EVERY_MS);
    return () => {
      window.removeEventListener(unauthorizedEvent, signInAgain);
      window.clearInterval(timer);
    };
  }, [unauthorizedEvent]);
}
