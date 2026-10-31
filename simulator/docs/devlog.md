# Devlog

Notes on how the module changed and why, newest first: what a later contributor would need to
know that the code and `CHANGELOG.md` do not say. One short entry per change worth explaining.

## Unreleased

- **Training (S1, S2).**
  - **Controls go through the state file.** The instructor's commands write the state SQLite
    file the server reads every step. AGENTS.md keeps every OPC UA node read-only, and a
    writable node is a maintainer decision, so a control channel over OPC UA was ruled out.
  - **Faults follow the wall clock; the model has its own.** The model runs on the wall clock
    plus `offset_seconds`: speed N adds (N-1)·dt, and a freeze takes dt away. An instructor
    therefore schedules faults by the time on the wall, while the setpoint schedules and noise
    stay continuous.
  - **Published timestamps are always real.** The historian never sees future points.
  - **What a fault holds is kept in `LoopState.fault_holds`.** That covers the frozen PV, the
    stuck valve position and the output left in manual, so a restart keeps them.
    `LoopState.from_dict` ignores unknown keys, so an older state file still loads.

## 0.5.1

- The repository's public history starts here; earlier releases are summarized in `CHANGELOG.md`.
