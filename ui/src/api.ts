/**
 * The HTTP client every app's interface uses for its own API (under its base path): one copy for
 * the suite. Each app makes its own with `createApiClient({ app: "twincraft", href })` and keeps
 * only its endpoint list.
 */
import { t } from "./i18n.js";
import { renewToken } from "./session.js";

export class ApiError extends Error {
  constructor(public status: number, message: string, public payload?: unknown) {
    super(message);
  }
}

/** A FastAPI error body as one line: a string, Pydantic's list of problems, or `{message}`. */
export function errorDetail(payload: unknown): string {
  const detail = (payload as { detail?: unknown } | null)?.detail;
  if (typeof detail === "string" && detail) return detail;
  if (detail && typeof detail === "object" && typeof (detail as { message?: unknown }).message === "string") return (detail as { message: string }).message;
  if (Array.isArray(detail)) {
    const messages = detail.map((item) => (item as { msg?: unknown })?.msg).filter((msg): msg is string => typeof msg === "string" && msg !== "");
    return messages.length ? t("Invalid data: {details}", { details: messages.map((msg) => msg.replace(/^Value error, /, "")).join("; ") }) : t("Invalid data.");
  }
  return t("Couldn't complete the operation.");
}

/** An error as the line a person reads. */
export function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : t("Couldn't complete the operation.");
}

/** A request body: `jsonBody("POST", value)`. */
export function jsonBody(method: string, value: unknown): RequestInit {
  return { method, body: JSON.stringify(value) };
}

/** `?a=1&b=2` from the values that are set (empty ones are left out). */
export function query(values: Record<string, string | null | undefined>): string {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(values)) if (value) params.set(key, value);
  const text = params.toString();
  return text ? `?${text}` : "";
}

export interface ApiClientOptions {
  /** The app id: the unauthorized event is `<app>:unauthorized`. */
  app: string;
  /** The browser path of an app path (the app's `createNav(...).href`). */
  href: (path: string) => string;
  fetcher?: typeof fetch;
  renew?: () => Promise<boolean>;
}

export interface RequestOptions {
  /** false for pages anyone may open (a public link): a 401 is not renewed or reported. */
  signedIn?: boolean;
}

export function createApiClient({ app, href, fetcher, renew = renewToken }: ApiClientOptions) {
  const UNAUTHORIZED_EVENT = `${app}:unauthorized`;

  /** fetch under the base path; PlantCraft's cookie carries the token. An expired token is
   * renewed at PlantCraft once; a second 401 tells the app (UNAUTHORIZED_EVENT). */
  async function send(path: string, init?: RequestInit, options: RequestOptions = {}, retry = true): Promise<Response> {
    const signedIn = options.signedIn ?? true;
    let response: Response;
    try {
      response = await (fetcher ?? fetch)(href(path), {
        credentials: "same-origin",
        ...init,
        headers: { "Content-Type": "application/json", ...init?.headers },
      });
    } catch {
      throw new ApiError(0, t("Couldn't connect to the server."));
    }
    if (signedIn) {
      if (response.status === 401 && retry && (await renew())) return send(path, init, options, false);
      if (response.status === 401) window.dispatchEvent(new CustomEvent(UNAUTHORIZED_EVENT));
    }
    if (!response.ok) {
      const payload = await response.json().catch(() => null);
      throw new ApiError(response.status, errorDetail(payload), payload);
    }
    return response;
  }

  /** The answer's JSON (undefined for 204). */
  async function request<T>(path: string, init?: RequestInit, options: RequestOptions = {}): Promise<T> {
    const response = await send(path, init, options);
    if (response.status === 204) return undefined as T;
    try {
      return (await response.json()) as T;
    } catch {
      throw new ApiError(0, t("Couldn't connect to the server."));
    }
  }

  return { UNAUTHORIZED_EVENT, send, request };
}

/** The help pages every app serves (`/api/help`, `/api/help/<id>`; the app standard, section 7). */
export interface HelpEntry { id: string; title: string; category?: string | null }
export interface HelpPage { id: string; title: string; markdown: string }
