/** A long Python file: `lines` lines of a method module. */
export function pythonSource(lines = 5000) {
  const out = ["import numpy as np", "import pandas as pd", "from plantcraft_sdk import method", ""];
  for (let i = 0; out.length < lines; i++) out.push(`@method(name="check_${i}")`, `def check_${i}(signal: pd.Series, window: int = ${10 + (i % 50)}) -> dict:`, `    """Rolling check number ${i}."""`, `    mean = signal.rolling(window).mean()`, `    spread = (signal - mean).abs().max()`, `    return {"value": float(spread), "ok": spread < ${i % 7 + 1}.5}`, "");
  return out.join("\n");
}
export const TYPED = "    result = np.percentile(signal.to_numpy(), [5, 50, 95])  # added while typing\n".repeat(3);
