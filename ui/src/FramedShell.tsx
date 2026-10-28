/**
 * An app inside the platform's frame (frame.ts): the frame draws the sidebar, its panels and the
 * search; the app draws only its pages. It tells the frame its pages (the sidebar's entries, with
 * their icons as SVG markup), where it is and the page's title, and does what the frame asks: go
 * to a page, open its assistant (the page's own tasks live here), start its tour. Links that leave
 * the app, and the shortcuts the frame answers, go to the frame.
 */
import { useCallback, useEffect, useLayoutEffect, useRef, type ReactNode } from "react";
import { appDisplayName, type AnyAppId } from "./appMarks.js";
import { AssistantHost, closeAssistant, openAssistant, pageContext, useAssistantPlaceValue, useOpenAssistant } from "./AssistantDrawer.js";
import { headingText } from "./tabTitle.js";
import { readToApp, toFrame, type FrameNavItem, type FrameState } from "./frame.js";
import { markPanelSwap, useClosePanelsOnMove } from "./SidePanel.js";
import { GuidedTour, useTour, type TourStep } from "./Tour.js";

export type FramedShellProps = {
  app: AnyAppId;
  appName?: string;
  subtitle?: string;
  home: string;
  tourId?: string;
  nav: Array<{ to: string; label: string; icon: ReactNode; match?: (path: string) => boolean; section?: string; children?: Array<{ to: string; label: string; match?: (path: string) => boolean }> }>;
  path: string;
  href: (to: string) => string;
  navigate: (to: string) => void;
  version?: string | null;
  assistant: boolean;
  tour?: TourStep[];
  isActive: (item: { to: string; match?: (path: string) => boolean }, path: string) => boolean;
  children: ReactNode;
};

/** The app's base path from its `href` ("/link/" for href("/") = "/link/"). */
function baseOf(href: (to: string) => string): string {
  const root = href("/");
  return root.endsWith("/") ? root : `${root}/`;
}

export function FramedShell({ app, appName, subtitle, home, tourId, nav, path, href, navigate, version, assistant, tour: tourSteps, isActive, children }: FramedShellProps) {
  const tour = useTour(tourId ?? app, tourSteps);
  const content = useRef<HTMLElement | null>(null);
  const icons = useRef<HTMLDivElement | null>(null);
  const sent = useRef("");
  const assistantOpen = useOpenAssistant() !== null;
  const described = useAssistantPlaceValue();
  const base = baseOf(href);
  // Another page of the app closes its assistant, as the frame closes its own panels.
  useClosePanelsOnMove(path);

  const page = useCallback(() => {
    const heading = content.current?.querySelector("h1");
    const where = (heading?.textContent ?? "").trim();
    return { place: [appDisplayName(app, appName), where].filter(Boolean).join(" › "), context: pageContext(content.current) };
  }, [app, appName]);

  // Tell the frame where the app is, after every render that may have changed it.
  const report = useCallback(() => {
    const markup = new Map<string, string>();
    icons.current?.querySelectorAll<HTMLElement>("[data-to]").forEach((node) => markup.set(node.dataset.to ?? "", node.querySelector("svg")?.outerHTML ?? ""));
    const items: FrameNavItem[] = nav.map((item) => ({
      to: item.to,
      href: href(item.to),
      label: item.label,
      icon: markup.get(item.to) ?? "",
      section: item.section,
      active: isActive(item, path),
      children: item.children?.map((child) => ({ to: child.to, href: href(child.to), label: child.label, active: isActive(child, path) })),
    }));
    const heading = content.current?.querySelector("h1");
    const state: FrameState = {
      app, appName, subtitle, base, home, path,
      url: `${window.location.pathname}${window.location.search}${window.location.hash}`,
      nav: items,
      heading: heading ? headingText(heading) : "",
      version: version ?? null,
      tour: Boolean(tourSteps?.length),
      assistant,
      assistantOpen,
    };
    const text = JSON.stringify(state);
    if (text === sent.current) return;
    sent.current = text;
    toFrame({ type: "pc-frame:state", state });
  }, [app, appName, subtitle, base, home, path, nav, href, isActive, version, tourSteps, assistant, assistantOpen]);
  useLayoutEffect(report);
  useEffect(() => { toFrame({ type: "pc-frame:ready" }); }, []);
  // A detail page fills its title after it loads: report again when the heading changes.
  useEffect(() => {
    const root = content.current;
    if (!root || typeof MutationObserver === "undefined") return;
    let pending = 0;
    const observer = new MutationObserver(() => { if (!pending) pending = window.setTimeout(() => { pending = 0; report(); }, 80); });
    observer.observe(root, { childList: true, subtree: true, characterData: true });
    return () => { observer.disconnect(); if (pending) window.clearTimeout(pending); };
  }, [report]);

  // What the frame asks.
  const latest = useRef({ navigate, page, described, tourStart: tour.start, assistant, assistantOpen });
  latest.current = { navigate, page, described, tourStart: tour.start, assistant, assistantOpen };
  useEffect(() => {
    const heard = (event: MessageEvent) => {
      const message = readToApp(event);
      if (!message) return;
      const now = latest.current;
      if (message.type === "pc-frame:go") now.navigate(message.to);
      else if (message.type === "pc-frame:tour") now.tourStart();
      else if (message.type === "pc-frame:close-panels") {
        if (message.still) markPanelSwap();
        closeAssistant();
      } else if (message.type === "pc-frame:assistant" && now.assistant) {
        if (now.assistantOpen) { closeAssistant(); return; }
        if (message.still) markPanelSwap();
        const seen = now.page();
        openAssistant({ ...seen, ...now.described, context: now.described?.context ?? seen.context });
      }
    };
    window.addEventListener("message", heard);
    return () => window.removeEventListener("message", heard);
  }, []);

  // Shortcuts the frame answers, and links that leave the app.
  useEffect(() => {
    const press = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null;
      const typing = Boolean(target && (target.isContentEditable || /^(input|textarea|select)$/i.test(target.tagName)));
      if (event.key === "[" && !typing && !event.metaKey && !event.ctrlKey && !event.altKey) { event.preventDefault(); toFrame({ type: "pc-frame:key", key: "[" }); }
      else if ((event.key === "k" || event.key === "K") && (event.ctrlKey || event.metaKey)) { event.preventDefault(); toFrame({ type: "pc-frame:key", key: "k" }); }
    };
    const click = (event: MouseEvent) => {
      if (event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
      const link = (event.target as Element | null)?.closest?.("a[href]") as HTMLAnchorElement | null;
      if (!link || (link.target && link.target !== "_self") || link.hasAttribute("download")) return;
      const url = new URL(link.href, window.location.href);
      if (url.origin !== window.location.origin || url.pathname.startsWith(base) || `${url.pathname}/` === base) return;
      event.preventDefault();
      toFrame({ type: "pc-frame:open", url: `${url.pathname}${url.search}${url.hash}` });
    };
    window.addEventListener("keydown", press);
    document.addEventListener("click", click);
    return () => { window.removeEventListener("keydown", press); document.removeEventListener("click", click); };
  }, [base]);

  return (
    <div className="pcs-framed">
      <div hidden ref={icons} className="pcs-frame-icons">{nav.map((item) => <span key={item.to} data-to={item.to}>{item.icon}</span>)}</div>
      <main className="pcs-content" ref={content}>{children}</main>
      {assistant && <AssistantHost page={page} />}
      {tour.open && tourSteps && <GuidedTour app={app} steps={tourSteps} path={path} navigate={navigate} onClose={tour.close} />}
    </div>
  );
}

