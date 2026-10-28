/**
 * Client-side navigation under the base path an app is served from (`/link/`, `/hist/`):
 * one copy for every app. Each app makes its own with `createNav(import.meta.env.BASE_URL)`.
 */
import { createElement, useEffect, useState, type MouseEvent, type ReactNode } from "react";

export type AppNav = ReturnType<typeof createNav>;

type Click = { preventDefault: () => void; metaKey?: boolean; ctrlKey?: boolean; shiftKey?: boolean; button?: number };

export function createNav(baseUrl: string = "/") {
  const BASE = baseUrl.replace(/\/$/, "");

  /** The browser path for an app path: "/loops/x" -> "/link/loops/x". */
  function href(path: string): string {
    return `${BASE}${path.startsWith("/") ? path : `/${path}`}`;
  }

  /** The app path for a browser path: "/link/loops/x" -> "/loops/x". */
  function appPath(pathname: string): string {
    const inside = BASE && pathname.startsWith(BASE) ? pathname.slice(BASE.length) : pathname;
    return inside.startsWith("/") ? inside : `/${inside}`;
  }

  /** Push an app path and let the shell re-render the route. */
  function navigate(to: string) {
    window.history.pushState({}, "", href(to));
    window.dispatchEvent(new PopStateEvent("popstate"));
    if (!to.includes("#")) window.scrollTo(0, 0);
  }

  /** onClick for an <a href={href(path)}>: client navigation, middle-click still opens a tab. */
  function follow(path: string) {
    return (event: Click) => {
      if (event.metaKey || event.ctrlKey || event.shiftKey || (event.button ?? 0) !== 0) return;
      event.preventDefault();
      navigate(path);
    };
  }

  /** The current app path, updated on navigation. */
  function usePath(): string {
    const [path, setPath] = useState(() => appPath(window.location.pathname));
    useEffect(() => {
      const update = () => setPath(appPath(window.location.pathname));
      window.addEventListener("popstate", update);
      return () => window.removeEventListener("popstate", update);
    }, []);
    return path;
  }

  /** A link to an app path that navigates without reloading. */
  function Link({ to, children, className, title }: { to: string; children: ReactNode; className?: string; title?: string }) {
    return createElement("a", { href: href(to), onClick: (event: MouseEvent) => follow(to)(event), className, title }, children);
  }

  return { BASE, href, appPath, navigate, follow, usePath, Link };
}
