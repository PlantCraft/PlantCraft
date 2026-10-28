import { describe, expect, it, vi } from "vitest";
import { LOGOUT_URL, RENEW_URL, renewToken, signOut } from "./session";

describe("token renewal", () => {
  it("posts to PlantCraft once even when asked twice at the same time", async () => {
    const fetcher = vi.fn(async (_url: string, _init?: RequestInit) => new Response("{}", { status: 200 }));
    const [first, second] = await Promise.all([renewToken(fetcher as unknown as typeof fetch), renewToken(fetcher as unknown as typeof fetch)]);
    expect(first && second).toBe(true);
    expect(fetcher).toHaveBeenCalledTimes(1);
    expect(fetcher.mock.calls[0][0]).toBe(RENEW_URL);
  });
  it("reports an expired session", async () => {
    const fetcher = vi.fn(async () => new Response("{}", { status: 401 }));
    expect(await renewToken(fetcher as unknown as typeof fetch)).toBe(false);
  });
});

describe("sign out", () => {
  it("posts to PlantCraft's /api/logout on the same host, then goes home", async () => {
    const fetcher = vi.fn(async (_url: string, _init?: RequestInit) => new Response(null, { status: 204 }));
    const go = vi.fn();
    await signOut(fetcher as unknown as typeof fetch, go);
    expect(LOGOUT_URL).toBe("/api/logout");
    expect(fetcher.mock.calls[0][0]).toBe("/api/logout");
    expect(fetcher.mock.calls[0][1]).toMatchObject({ method: "POST", credentials: "same-origin" });
    expect(go).toHaveBeenCalledWith("/");
  });
  it("goes home even when PlantCraft does not answer", async () => {
    const fetcher = vi.fn(async () => { throw new Error("offline"); });
    const go = vi.fn();
    await signOut(fetcher as unknown as typeof fetch, go);
    expect(go).toHaveBeenCalledWith("/");
  });
});
