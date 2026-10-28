# PlantCraft Alarms spec

Category: alarm management for process plants: rules that turn plant values and the suite's
events into alarms, with their rationalization (the master alarm database), who hears and how
often, the operator's Active list (acknowledge, shelve), the alarm journal, and alarm
performance monitoring against the industry targets. Tools studied (research
only, public behaviour): AVEVA (Alarm Adviser), Honeywell (Dynamo Alarm Suite), Emerson (DeltaV
Analyze), Siemens (Alarm Management in PCS 7/neo), Yokogawa (Exaquantum/AMD, CAMS), ABB (Alarm
Management in 800xA), Rockwell (FactoryTalk Alarms and Events). Sources are public only (clean
room, see AGENTS.md); no code of these tools is used.

## Sources

| Source | Link | Read on |
|---|---|---|
| ANSI/ISA-18.2-2016, Management of Alarm Systems for the Process Industries (public summaries, the alarm states and the performance metrics table) | https://www.isa.org/standards-and-publications/isa-standards/isa-18-standards | 2026-10-21 |
| IEC 62682:2022, Management of alarm systems for the process industries (international edition of ISA-18.2) | https://webstore.iec.ch/publication/62743 | 2026-10-21 |
| EEMUA Publication 191, Alarm systems: a guide to design, management and procurement (public summaries of its targets) | https://www.eemua.org/Products/Publications/Print/EEMUA-Publication-191.aspx | 2026-10-21 |
| Hollifield, B. and Habibi, E. (2010), The Alarm Management Handbook, 2nd ed., PAS | ISBN 978-0-9778969-8-9 | 2026-10-21 |
| Vendor research of the suite (thread "Pesquisa de apps de fornecedores", 2026-10-20) | Claude Doc in the project | 2026-10-20 |
| Grafana Alerting: alert rules, multi-dimensional rules (one instance per series), pending period, contact points | https://grafana.com/docs/grafana/latest/alerting/fundamentals/alert-rules/ | 2026-10-24 |
| Prometheus Alertmanager: grouping (group_wait, group_interval, repeat_interval), inhibition, silences | https://prometheus.io/docs/alerting/latest/alertmanager/ | 2026-10-24 |
| PlantCraft API v1 and the app standard (`docs/api-v1.md`, `docs/app-standard.md`) | PlantCraft repository | 2026-10-21 |

## Decisions

1. **Read only.** Alarms evaluates plant data read through PlantCraft API v1 and informs; it
   never writes to a control system. It complements the DCS's own alarms (a second, engineering
   view and the performance metrics), it does not replace them.
2. **Rules make the alarms** (owner, 2026-10-24): a rule has one condition (high-high, high,
   low, low-low, no data, an app's verdict, or a repeated event of the suite) over one signal or a
   signal role on assets and on every asset under some branches, resolved every cycle, so the
   plant map moves alarms with it. It makes one alarm per subject (asset, signal or Link
   schedule), each with its own ISA-18.2 life. Deadband and on/off delays are the ISA-18.2 tools
   against chattering and fleeting alarms; a repeated event needs N hits within a window.
   An alarm or a notice: notices need no acknowledgement and stay out of performance.
9. **Apps report, Alarms decides**: the apps publish events (`/api/v1/events`); Alarms reads them
   with a cursor each cycle, keeps them 30 days (Incoming) and counts them for the rules. Nothing
   that comes in notifies anyone by itself.
10. **Who hears is in the rule**, with three guards against a flood: one message per rule per
   gathering window (5 minutes by default), at most 6 messages an hour per person (escalations
   always go; a note says more are waiting), and a failed or stalled Link schedule holds back the
   other alarms of that schedule. Each occurrence is one thread in Messages (key
   `alarm:<id>:<occurrence>`, `rule:<id>:<hour>` when gathered).
3. **One judging path**: the monitor and "Try it" both run `engine.evaluate`. What an engineer
   tries on history is exactly what the plant will raise.
4. **States as in ISA-18.2**: unacknowledged, acknowledged, returned unacknowledged, shelved
   (operator, time-limited, with a reason; still evaluated but raises nothing; announced again
   if still active when it ends), out of service (engineering; not evaluated), normal.
5. **The monitor owns the evaluation state, people own acknowledgement and shelving**: separate
   columns, so an acknowledgement during a cycle is never lost.
6. **Performance for one operator position** (the whole installation) against the ISA-18.2 table:
   ≤ 6 alarms per hour acceptable (≤ 12 manageable), ≤ 1 per 10 minutes (≤ 2), flood above 10
   per 10 minutes under 1 % of the time, top 10 under 5 % of the load, no chattering (3 raises
   within a minute), fewer than 5 stale (active over 24 h), priorities about 5/15/80 %.
7. **Suggested limits** from data (median ± 4 robust standard deviations of the last 6 hours)
   are a starting point for rationalization, never a substitute for it.
8. **Suite links**: `alarm_state` results on the alarm's asset (else its signal), expiring after
   15 minutes; events `alarmcraft.alarm.raised|cleared`; one daily run and one schedule.

## Not yet (see docs/gaps.md)

Per-console operator positions, rate-of-change and deviation-from-setpoint alarms, alarm
suppression by plant state (state-based alarming), flood suppression, a printable alarm
rationalization report, and alarm import from a DCS export.
