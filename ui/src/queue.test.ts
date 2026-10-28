import { describe, expect, it } from "vitest";
import { queueChart, queueTiles, type QueueNow, type QueuePoint } from "./Queue.js";

const now: QueueNow = {
  at: "2026-10-23T12:00:00Z", queued: 1000, running: 8, workers: 8, busy: 8, done: 40, failed: 1, cancelled: 0,
  done_hour: 400, failed_hour: 2, cancelled_hour: 1, skipped_hour: 3, delay_seconds: 600, average_seconds: 2.5, cpu_percent: 380, memory_mb: 1200,
};

describe("the queue", () => {
  it("says what waits, what runs and what failed", () => {
    const tiles = queueTiles(now);
    expect(tiles.map((tile) => tile.id)).toEqual(["queued", "running", "done", "failed"]);
    expect(tiles[0].detail).toContain("10 min");
    expect(tiles[1].detail).toBe("8 of 8 workers busy");
    expect(tiles[3].tone).toBe("problem");
    expect(tiles[3].detail).toBe("3 skipped · 1 cancelled");
    expect(queueTiles({ ...now, queued: 0, failed_hour: 0, skipped_hour: 0, cancelled_hour: 0 })[0].detail).toBe("nothing waiting");
  });

  it("draws the queue, running and the wait in minutes on its own axis", () => {
    const history: QueuePoint[] = [
      { at: "2026-10-23T00:00:00Z", queued: 1000, running: 8, workers: 8, done: 0, failed: 0, cancelled: 0, delay_seconds: 0, average_seconds: null },
      { at: "2026-10-23T00:10:00Z", queued: 0, running: 2, workers: 8, done: 1000, failed: 0, cancelled: 0, delay_seconds: 540, average_seconds: 2 },
    ];
    const { data, layout } = queueChart(history, { theme: "light" });
    expect(data).toHaveLength(3);
    expect((data[2] as { y: number[] }).y).toEqual([0, 9]);
    expect(layout).toHaveProperty("yaxis2");
    expect(queueChart(history, { theme: "dark", delay: false }).data).toHaveLength(2);
  });

  it("spans the whole window ending now, even with one sample", () => {
    const history: QueuePoint[] = [{ at: "2026-10-23T11:59:50Z", queued: 3, running: 1, workers: 8, done: 0, failed: 0, cancelled: 0, delay_seconds: 0, average_seconds: null }];
    const { layout } = queueChart(history, { theme: "light", window: "24h", end: "2026-10-23T12:00:00Z" });
    expect((layout.xaxis as { range: string[] }).range).toEqual(["2026-10-22T12:00:00.000Z", "2026-10-23T12:00:00.000Z"]);
    expect(queueChart(history, { theme: "light" }).layout.xaxis).not.toHaveProperty("range");
  });
});
