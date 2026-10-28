// @vitest-environment jsdom
import { describe, expect, it, vi } from "vitest";
import { ApiError, createApiClient, errorDetail, jsonBody, query } from "./api.js";

const json = (status: number, body: unknown) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

describe("errorDetail", () => {
  it("reads every FastAPI error shape", () => {
    expect(errorDetail({ detail: "Twin not found." })).toBe("Twin not found.");
    expect(errorDetail({ detail: [{ msg: "Value error, name is empty" }, { msg: "bad step" }] })).toBe("Invalid data: name is empty; bad step");
    expect(errorDetail({ detail: { message: "Runner busy" } })).toBe("Runner busy");
    expect(errorDetail(null)).toBe("Couldn't complete the operation.");
  });
});

describe("request helpers", () => {
  it("leaves empty values out of a query and writes JSON bodies", () => {
    expect(query({ q: "fic", empty: "", none: null })).toBe("?q=fic");
    expect(query({})).toBe("");
    expect(jsonBody("POST", { a: 1 })).toEqual({ method: "POST", body: '{"a":1}' });
  });
});

describe("createApiClient", () => {
  it("calls under the base path and renews an expired token once", async () => {
    const fetcher = vi.fn()
      .mockResolvedValueOnce(json(401, { detail: "expired" }))
      .mockResolvedValueOnce(json(200, { ok: true }));
    const renew = vi.fn().mockResolvedValue(true);
    const client = createApiClient({ app: "demo", href: (path) => `/demo${path}`, fetcher, renew });
    await expect(client.request("/api/me")).resolves.toEqual({ ok: true });
    expect(fetcher.mock.calls[0][0]).toBe("/demo/api/me");
    expect(renew).toHaveBeenCalledTimes(1);
  });

  it("reports a second 401 to the app and turns errors into ApiError", async () => {
    const fetcher = vi.fn().mockResolvedValue(json(401, { detail: "signed out" }));
    const client = createApiClient({ app: "demo", href: (path) => path, fetcher, renew: async () => false });
    const heard = vi.fn();
    window.addEventListener(client.UNAUTHORIZED_EVENT, heard);
    const failed = await client.request("/api/x").catch((error: unknown) => error);
    expect(failed).toBeInstanceOf(ApiError);
    expect((failed as ApiError).status).toBe(401);
    expect(heard).toHaveBeenCalledTimes(1);
    expect(client.UNAUTHORIZED_EVENT).toBe("demo:unauthorized");
  });

  it("does not renew or report on a public page", async () => {
    const fetcher = vi.fn().mockResolvedValue(json(401, { detail: "link expired" }));
    const renew = vi.fn().mockResolvedValue(true);
    const client = createApiClient({ app: "demo", href: (path) => path, fetcher, renew });
    await expect(client.request("/api/public/x", undefined, { signedIn: false })).rejects.toThrow("link expired");
    expect(renew).not.toHaveBeenCalled();
  });

  it("answers undefined for 204 and a clear error when offline", async () => {
    const client = createApiClient({ app: "demo", href: (path) => path, fetcher: vi.fn().mockResolvedValue(new Response(null, { status: 204 })) });
    await expect(client.request("/api/x", { method: "DELETE" })).resolves.toBeUndefined();
    const offline = createApiClient({ app: "demo", href: (path) => path, fetcher: vi.fn().mockRejectedValue(new TypeError("network")) });
    await expect(offline.request("/api/x")).rejects.toThrow("Couldn't connect to the server.");
  });
});
