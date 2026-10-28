import { describe, expect, it } from "vitest";
import { calibrationLine, withCalibration } from "./Calibrate";

const DIAGRAM = {
  version: 2,
  nodes: [
    { id: "model", block: "model.fmu_x", parameters: { step_seconds: 5 }, x: 0, y: 0 },
    { id: "deviation", block: "model.deviation", parameters: { persistence: 2 }, x: 300, y: 0 },
  ],
  edges: [],
};
const CALIBRATION = { outputs: ["y"], mean: [0.01], cov: [[0.04]], std: [0.2], samples: 480, asset: "furnace", start: "2026-10-01T10:00:00Z", end: "2026-10-01T11:00:00Z" };

describe("Calibrate", () => {
  it("puts the calibration in the deviation block's parameters only", () => {
    const next = withCalibration(DIAGRAM, "deviation", CALIBRATION);
    expect(next.nodes[1].parameters).toEqual({ persistence: 2, calibration: CALIBRATION });
    expect(next.nodes[0]).toBe(DIAGRAM.nodes[0]);
    expect(DIAGRAM.nodes[1].parameters).toEqual({ persistence: 2 });
  });

  it("says what the block is calibrated on, or that it is not", () => {
    expect(calibrationLine(null)).toContain("Not calibrated yet");
    const line = calibrationLine(CALIBRATION, "Furnace");
    expect(line).toContain("480 samples");
    expect(line).toContain("Furnace");
  });
});
