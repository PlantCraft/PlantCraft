import { describe, expect, it } from "vitest";
import { QUEUE_FORMAT, type QueueNow } from "./Queue.js";
import { fetchAppQueue, fetchComputeSummary, jobsByApp, queueJob, queueLine, queueTotals, type AppQueue } from "./SuiteQueue.js";
import type { SuiteApp } from "./SuiteShell.js";

const link: SuiteApp = { id: "linkcraft", name: "PlantCraft Analytics", url: "/link/" };

const idle: QueueNow = {
  at: "2026-10-23T12:00:00Z", queued: 0, running: 0, workers: 4, busy: 0, done: 0, failed: 0, cancelled: 0,
  done_hour: 0, failed_hour: 0, cancelled_hour: 0, skipped_hour: 0, delay_seconds: 0, average_seconds: null, cpu_percent: null, memory_mb: null,
};

function queue(app: string, now: Partial<QueueNow>): AppQueue {
  return { app, appName: app, url: `/${app}/executions`, now: { ...idle, ...now } };
}

describe("the suite's work queues", () => {
  it("sums what runs and waits across the apps, with the longest wait", () => {
    const totals = queueTotals([queue("link", { running: 4, queued: 12, delay_seconds: 2400 }), queue("model", { running: 1, failed_hour: 2, delay_seconds: 9999 })]);
    expect(totals).toMatchObject({ running: 5, queued: 12, workers: 8, failedHour: 2, delaySeconds: 2400, late: true });
    expect(queueLine(totals)).toBe("5 running · 12 waiting");
    expect(queueLine(queueTotals([queue("link", { running: 2 })]))).toBe("2 running");
    expect(queueLine(queueTotals([queue("link", {})]))).toBe("Queue idle");
    expect(queueTotals([queue("link", { queued: 3, delay_seconds: 60 })]).late).toBe(false);
  });

  it("asks an app once when it has no queue of this format", async () => {
    const reply = (status: number, body: unknown) => (async () => new Response(JSON.stringify(body), { status })) as typeof fetch;
    expect(await fetchAppQueue(link, reply(404, {}))).toBe("none");
    expect(await fetchAppQueue(link, reply(200, { format: "other", now: idle }))).toBe("none");
    expect(await fetchAppQueue(link, reply(502, {}))).toBeNull();
    expect(await fetchAppQueue(link, (async () => { throw new Error("down"); }) as typeof fetch)).toBeNull();
    const found = await fetchAppQueue(link, (async (url: string) => {
      expect(url).toBe("/link/api/queue?window=1h");
      return new Response(JSON.stringify({ format: QUEUE_FORMAT, now: { ...idle, running: 3 }, history: [] }));
    }) as unknown as typeof fetch);
    expect(found).toMatchObject({ app: "linkcraft", appName: "Analytics", url: "/link/executions", now: { running: 3 } });
  });
});

describe("the Queue panel's work (docs/quick-access.md)", () => {
  const hist: SuiteApp = { id: "histcraft", name: "PlantCraft Historian", url: "/hist/" };
  const historian = {
    format: QUEUE_FORMAT,
    url: "imports",
    now: { ...idle, running: 1 },
    items: [
      { id: 7, name: "Import load-2025.csv", by: "ana", status: "running", progress: 0.62, step: "Writing 560 of 900 tags", url: "/hist/sources/3", started_at: "2026-10-26T12:00:00Z" },
      { id: 8, file_name: "other.csv", by: "rui", status: "queued", progress: null, url: "https://elsewhere.test/", cancel: { label: "Cancel", method: "POST", href: "/hist/api/imports/8/cancel" } },
      { id: 9, name: "Old", by: "ana", status: "error" },
    ],
  };
  const answer = (body: unknown) => (async () => new Response(JSON.stringify(body), { status: 200 })) as unknown as typeof fetch;

  it("reads an app's own items and the page of its queue", async () => {
    const found = await fetchAppQueue(hist, answer(historian));
    if (!found || found === "none") throw new Error("no queue");
    expect(found.url).toBe("/hist/imports");
    expect(found.items?.map((item) => [item.id, item.name, item.status])).toEqual([["7", "Import load-2025.csv", "running"], ["8", "other.csv", "queued"], ["9", "Old", "failed"]]);
    expect(found.items?.[1]).toMatchObject({ url: null, cancel: { label: "Cancel", href: "/hist/api/imports/8/cancel" } });
  });

  it("lists each app with its own work, the platform's runs joined with the apps' items", async () => {
    const found = await fetchAppQueue(hist, answer(historian));
    if (!found || found === "none") throw new Error("no queue");
    const run = queueJob({ app: "linkcraft", app_name: "Analytics", id: "r-1", name: "Loop health", status: "running", by: "rui", progress: 0.4, cancel: "/link/api/runs/r-1/cancel", started_at: "2026-10-26T12:05:00Z" }, "", "");
    const apps = jobsByApp({ me: "ana", mine: [], running: run ? [run] : [] }, [found]);
    // The apps with a queue first, then those only the platform's runs name.
    expect(apps.map((item) => [item.app, item.url, item.now !== null])).toEqual([["histcraft", "/hist/imports", true], ["linkcraft", null, false]]);
    expect(apps[0].jobs.map((job) => job.id)).toEqual(["7", "8", "9"]);
    expect(apps[0].mineActive).toBe(1);
    expect(apps[1].jobs[0].cancel).toEqual({ label: "Cancel", href: "/link/api/runs/r-1/cancel" });
    expect(apps[1].mineActive).toBe(0);
    // A finished one offers no Cancel.
    expect(queueJob({ id: "x", status: "done", cancel: "/link/api/x" }, "linkcraft", "Analytics")?.cancel).toBeNull();
    // A run reads by the suite's name of its app, not the manifest's (the Queue said
    // "PlantCraft Models" beside "Analytics").
    expect(queueJob({ app: "modelcraft", app_name: "PlantCraft Models", id: "s", status: "done" }, "", "")?.appName).toBe("Models");
    expect(queueJob({ app: "linkcraft", app_name: "PlantCraft Analytics", id: "s", status: "done" }, "", "")?.appName).toBe("Analytics");
  });
});

describe("the compute workers under an app of the Queue panel", () => {
  const answer = (status: number, body: unknown) => (async () => new Response(JSON.stringify(body), { status })) as unknown as typeof fetch;
  it("reads each app's workers, keeping only what it shows", async () => {
    const found = await fetchComputeSummary(answer(200, { apps: { linkcraft: { queued: 2, running: 1, workers: [{ name: "local", status: "active", environments: ["standard", "ml"], slots: 3, running: 1, largest_size: "medium", host: "box" }, { status: "active" }] } } }));
    expect(found).toEqual({ linkcraft: { queued: 2, running: 1, workers: [{ name: "local", status: "active", environments: ["standard", "ml"], slots: 3, running: 1, largestSize: "medium" }] } });
  });
  it("is null where PlantCraft has no summary or does not answer", async () => {
    expect(await fetchComputeSummary(answer(404, {}))).toBeNull();
    expect(await fetchComputeSummary((async () => { throw new Error("down"); }) as unknown as typeof fetch)).toBeNull();
  });
});
