# Devlog

Notes on how the module changed and why, newest first: what a later contributor would need to
know that the code and `CHANGELOG.md` do not say. One short entry per change worth explaining.

## 0.5.1

- The repository's public history starts here; earlier releases are summarized in `CHANGELOG.md`.
- 2026-10-31: loop-hours lost by cause, by area and period, and effective control per loop (engine/losses.py, LACUNAS A13 and A7).
- 2026-10-31: days until a falling loop health reaches its alarm limit (engine/days_to_limit.py, LACUNAS A18).
- 2026-10-31: a new action from a loop's verdict with its charts attached (loopResult.ts, verdict reference; LACUNAS A19).
- 2026-11-09: health methods and likely causes checked against the Simulator's 100 known loops (0 of 100 wrong live, 2 on the 30 s backfill): setpoint transients, oscillation amplitude and pattern, robust noise, hysteresis reversals, new output_drift, cause on the loop row.
