import { createContext, useContext } from "react";
import { t } from "./i18n";
import type { AccessInfo } from "./types";

/** What everyone may do when the session says nothing (older servers): edit everything. */
export const FULL_ACCESS: AccessInfo = { level: "admin", label: t("Admin"), applications: null, can_edit: true, is_admin: true };

/** What components need to know about the signed-in person. */
export const SessionContext = createContext<{ isAdmin: boolean; access?: AccessInfo }>({ isAdmin: false });

export function useIsAdmin() {
  return useContext(SessionContext).isAdmin;
}

/** Reads the administration pages: an administrator, or a public demo's visitor (read-only). */
export function useAdminView() {
  const { access, isAdmin } = useContext(SessionContext);
  return isAdmin || Boolean(access?.admin_view);
}

export function useAccess(): AccessInfo {
  const { access, isAdmin } = useContext(SessionContext);
  return access ?? { ...FULL_ACCESS, is_admin: isAdmin };
}

/** Editors and administrators: run analyses, edit protocols, actions and dashboards. */
export function useCanEdit() {
  return useAccess().can_edit;
}

/** Whether a menu section is for this person. The API enforces the same rules. */
export type Section = "settings" | "users" | "engineering" | "operation" | "plant" | "dashboards" | "administration";
export function canSee(access: AccessInfo, section: Section, applicationId?: string) {
  if (access.level === "dashboards") return section === "dashboards";
  if (applicationId && !access.is_admin && access.applications && !access.applications.includes(applicationId)) return false;
  if (section === "users") return access.is_admin;
  if (section === "administration") return access.is_admin || Boolean(access.admin_view);
  if (section === "settings") return access.can_edit;
  return true;
}

export const ADMIN_ONLY = t("Admins only");
export const READ_ONLY = t("Your access is read-only");

/**
 * Where to go after signing in when an app sent the browser to /login?next=...:
 * only a path on this origin ("/cpm/loops"), never another site ("//evil", "https://...").
 */
export function safeNext(search: string, origin: string): string | null {
  const next = new URLSearchParams(search).get("next");
  if (!next || !next.startsWith("/") || next.startsWith("//") || next.startsWith("/\\")) return null;
  try {
    const url = new URL(next, origin);
    return url.origin === origin ? `${url.pathname}${url.search}${url.hash}` : null;
  } catch {
    return null;
  }
}
