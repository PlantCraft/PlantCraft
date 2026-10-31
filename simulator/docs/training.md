# Training on the loop portfolio

An instructor can make the 50-loop portfolio misbehave on a schedule, keep the answer key apart
from what trainees see, and save, restore, freeze or speed up the plant. Every command acts on
the server's state file (`--state-db`, `SIMCRAFT_STATE_DB`). None of them needs the network or a
writable OPC UA node.

## Fault schedule

```json
{"faults": [
  {"id": "F1", "loop": "FIC-1003", "fault": "valve_stuck", "start": "2026-11-02T13:30:00Z",
   "duration_minutes": 20, "note": "Before the shift change"},
  {"id": "F2", "loop": "TIC-1104", "fault": "sensor_bias", "start": "2026-11-02T14:00:00Z",
   "magnitude": 4.0}
]}
```

| Fault | What it does | What a trainee should notice |
|---|---|---|
| `sensor_bias` | the PV reads `magnitude` off the true value | OP moved with no load change; a redundant measurement disagrees |
| `sensor_frozen` | the PV holds its value from the start | the PV has no noise and no change while OP keeps moving |
| `bad_quality` | the PV is published with status `BadSensorFailure` | the value cannot be used; alarms on it say so |
| `valve_stuck` | the valve holds its position | OP keeps moving but the PV does not answer |
| `load_step` | the process takes a step of `magnitude` | the PV leaves SP at once and OP moves to bring it back |
| `manual` | the loop is left in manual and its output holds | MODE reads MAN and the PV drifts from SP |

Rules for the schedule:

- Times are UTC.
- Without `duration_minutes`, a fault lasts until the server stops.
- One loop can carry different faults at once, but the same fault twice only if the two do not
  overlap.

```sh
simcraft loops faults check faults.json              # checks every entry
simcraft loops serve --faults faults.json ...        # or SIMCRAFT_FAULTS=/data/faults.json
simcraft loops faults key faults.json                # the answer key, for the instructor only
```

Keep the schedule file and the answer key away from trainees. The server writes nothing about
faults to OPC UA. In its state file, it records when each fault began and what PV, SP, OP and
MODE were at that moment. The answer key shows these under "Fired".

## Snapshots, freeze and speed

```sh
simcraft loops snapshot save "Start of shift"     # every loop's state, under a name
simcraft loops snapshot list
simcraft loops snapshot restore "Start of shift"  # put back at the server's next step
simcraft loops freeze                             # nothing moves or publishes
simcraft loops resume
simcraft loops speed 4                            # the model runs 4 s per second (1 to 20)
simcraft loops status                             # controls, snapshots, faults fired
```

- **Speed** applies to the model only. Published timestamps stay the real time, so the historian
  never receives a point from the future.
- **Freeze** also stops the model's clock: on `resume`, the setpoint schedules carry on from
  where they stopped.
- **Fault times follow the wall clock**, so an instructor can schedule them by the time in the
  room.
