/**
 * The frame's side (frame.ts): the apps' iframes beside the platform's sidebar. The visible one
 * follows the address; the last few apps opened stay loaded, hidden, so going back to one is
 * instant. What the visible app reports (its pages, where it is) goes to `onState`, and the
 * window's address follows it. An app that does not say it is ready in FRAME_READY_MS is opened
 * on its own page.
 */
import { useEffect, useRef, useState } from "react";
import { useOpenMessages, openMessages } from "./MessagesDrawer.js";
import { useQueuesOpen } from "./SuiteQueue.js";
import { claimPanel, setOutsidePanel } from "./SidePanel.js";
import { FRAME_ATTR, FRAME_READY_MS, frameOff, readToFrame, toApp, type FrameState } from "./frame.js";
import { t } from "./i18n.js";

/** How many apps stay loaded. */
export const KEEP_APPS = 3;

type Loaded = { prefix: string; src: string; used: number };

export type AppFramesProps = {
  /** False while the person is on a platform page: the apps stay loaded, hidden. */
  active?: boolean;
  /** The address to show: path, query and hash, under an app's prefix. */
  url: string;
  /** That app's prefix ("/link/"). */
  prefix: string;
  /** What the visible app reports; null while it loads. */
  onState: (state: FrameState | null) => void;
  /** The visible app went somewhere in itself: the window's address, replaced (no new history entry). */
  onAddress: (url: string) => void;
  /** A link out of the app (another app, a platform page): opened by the frame's own navigation. */
  onOpen: (url: string) => void;
  /** A shortcut pressed inside the app. */
  onKey: (key: "[" | "k") => void;
};

/** The address without the frame's own query (`pc-frame=...`). */
export function withoutFrameQuery(url: string): string {
  const [rest, hash] = url.split("#", 2);
  const [path, query = ""] = rest.split("?", 2);
  const kept = query.split("&").filter((part) => part && !part.startsWith("pc-frame="));
  return `${path}${kept.length ? `?${kept.join("&")}` : ""}${hash !== undefined ? `#${hash}` : ""}`;
}

export function AppFrames({ active = true, url, prefix, onState, onAddress, onOpen, onKey }: AppFramesProps) {
  const [loaded, setLoaded] = useState<Loaded[]>(() => [{ prefix, src: url, used: Date.now() }]);
  const frames = useRef(new Map<string, HTMLIFrameElement>());
  const states = useRef(new Map<string, FrameState>());
  const ready = useRef(new Set<string>());
  // Bumped when an app says it is ready: it is shown from then on (never its own sidebar first).
  const [, setReadyTick] = useState(0);
  const handlers = useRef({ onState, onAddress, onOpen, onKey, prefix, url, active });
  handlers.current = { onState, onAddress, onOpen, onKey, prefix, url, active };

  // The address changed from outside the app (the sidebar of another app, Back, the search).
  useEffect(() => {
    if (!active) return;
    setLoaded((list) => {
      const found = list.find((item) => item.prefix === prefix);
      if (!found) {
        const next = [...list, { prefix, src: url, used: Date.now() }];
        // The oldest hidden app is dropped past KEEP_APPS.
        return next.length > KEEP_APPS ? next.sort((a, b) => b.used - a.used).slice(0, KEEP_APPS) : next;
      }
      return list.map((item) => (item.prefix === prefix ? { ...item, used: Date.now() } : item));
    });
    const state = states.current.get(prefix);
    onState(state ?? null);
    if (state && withoutFrameQuery(state.url) !== url) {
      const to = url.startsWith(state.base) ? `/${url.slice(state.base.length)}` : url;
      toApp(frames.current.get(prefix)?.contentWindow, { type: "pc-frame:go", to });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [active, prefix, url]);

  // A dropped app loads afresh (and says it is ready again) next time. Not in the iframe's ref:
  // React calls an inline ref again on every render.
  useEffect(() => {
    const kept = new Set(loaded.map((item) => item.prefix));
    for (const known of [...frames.current.keys()]) {
      if (!kept.has(known)) { frames.current.delete(known); states.current.delete(known); ready.current.delete(known); }
    }
  }, [loaded]);

  // A new app that never says it is ready (an older ui): its own page.
  useEffect(() => {
    if (!active || ready.current.has(prefix)) return;
    const timer = window.setTimeout(() => {
      const now = handlers.current;
      if (!ready.current.has(prefix) && now.active && now.prefix === prefix) window.location.replace(frameOff(now.url));
    }, FRAME_READY_MS);
    return () => window.clearTimeout(timer);
  }, [active, prefix]);

  // What the apps say.
  useEffect(() => {
    const heard = (event: MessageEvent) => {
      const message = readToFrame(event);
      if (!message) return;
      const from = [...frames.current.entries()].find(([, frame]) => frame.contentWindow === event.source)?.[0];
      if (!from) return;
      const now = handlers.current;
      const visible = now.active && from === now.prefix;
      const isReady = () => { if (!ready.current.has(from)) { ready.current.add(from); setReadyTick((tick) => tick + 1); } };
      if (message.type === "pc-frame:ready") { isReady(); return; }
      if (message.type === "pc-frame:state") {
        isReady();
        const opened = message.state.assistantOpen && !states.current.get(from)?.assistantOpen;
        states.current.set(from, message.state);
        if (!visible) return;
        now.onState(message.state);
        // The app's assistant just opened (from a page's own button): the frame's panels close.
        if (opened) claimPanel("assistant");
        setOutsidePanel("assistant", message.state.assistantOpen);
        const address = withoutFrameQuery(message.state.url);
        if (address !== now.url) now.onAddress(address);
        return;
      }
      if (!visible) return;
      if (message.type === "pc-frame:messages") openMessages(message.conversation);
      else if (message.type === "pc-frame:key") now.onKey(message.key);
      else if (message.type === "pc-frame:open") {
        // The platform answered inside the frame for this app's own address: the app is not
        // behind the proxy here. Open it on its own page rather than loop.
        if (message.url.startsWith(now.prefix)) window.location.replace(frameOff(message.url));
        else now.onOpen(message.url);
      }
    };
    window.addEventListener("message", heard);
    return () => window.removeEventListener("message", heard);
  }, []);

  // A panel of the frame opening closes the app's own (its assistant).
  const messages = useOpenMessages() !== null;
  const queues = useQueuesOpen();
  useEffect(() => {
    if (messages || queues) toApp(frames.current.get(handlers.current.prefix)?.contentWindow, { type: "pc-frame:close-panels", still: true });
  }, [messages, queues]);

  // Another app, or a platform page: the app left behind closes its panels (they would still be
  // open when the person comes back to it).
  const shownPrefix = active ? prefix : null;
  const lastShown = useRef(shownPrefix);
  useEffect(() => {
    const before = lastShown.current;
    lastShown.current = shownPrefix;
    if (before && before !== shownPrefix) toApp(frames.current.get(before)?.contentWindow, { type: "pc-frame:close-panels" });
    setOutsidePanel("assistant", Boolean(shownPrefix && states.current.get(shownPrefix)?.assistantOpen));
  }, [shownPrefix]);

  return (
    <div className="pcs-frames" hidden={!active}>
      {active && !ready.current.has(prefix) && <div className="pcs-frame-loading" role="status"><span className="pcs-spin-ring" aria-hidden="true" />{t("Loading…")}</div>}
      {loaded.map((item) => (
        <iframe
          key={item.prefix}
          ref={(node) => { if (node) frames.current.set(item.prefix, node); }}
          {...{ [FRAME_ATTR]: "" }}
          className="pcs-frame"
          src={item.src}
          title={t("App")}
          hidden={!active || item.prefix !== prefix}
          data-ready={ready.current.has(item.prefix) ? "" : undefined}
          allow="fullscreen; clipboard-write"
        />
      ))}
    </div>
  );
}
