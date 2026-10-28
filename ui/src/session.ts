/**
 * The suite session seen from an app: PlantCraft's token lives in a cookie it sets on the shared
 * host. It lasts 15 minutes; the browser renews it with PlantCraft's session cookie.
 */
export const RENEW_URL = "/api/v1/auth/token";
export const RENEW_EVERY_MS = 10 * 60 * 1000;
/** PlantCraft's sign-out (same host). */
export const LOGOUT_URL = "/api/logout";

let pending: Promise<boolean> | null = null;

/** Ask PlantCraft for a fresh token (one request at a time). */
export function renewToken(fetcher: typeof fetch = fetch): Promise<boolean> {
  pending ??= fetcher(RENEW_URL, { method: "POST", credentials: "same-origin" })
    .then((response) => response.ok)
    .catch(() => false)
    .finally(() => {
      pending = null;
    });
  return pending;
}

/** Sign in again at PlantCraft: reloading lets the server redirect to its login page. */
export function signInAgain() {
  window.location.reload();
}

/** Sign out at PlantCraft, then its home page, which asks to sign in again. */
export async function signOut(fetcher: typeof fetch = fetch, go: (url: string) => void = (url) => window.location.assign(url)) {
  try {
    await fetcher(LOGOUT_URL, { method: "POST", credentials: "same-origin" });
  } catch {
    // Signed out or not, the home page shows where the session stands.
  }
  go("/");
}
