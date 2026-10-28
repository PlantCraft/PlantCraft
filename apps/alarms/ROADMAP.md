# PlantCraft Alarms roadmap

Readiness per area (0-100 %), updated with every change that moves one.

| Area | Ready | What is there, what is missing |
|---|---|---|
| Alarm evaluation | 85 % | Rules over a signal, assets or a branch (one alarm per asset); limits, deadband, on/off delays, no data, app verdicts, repeated events of the suite (N in a window, still open after a while); one judging path; missing rate of change and deviation from setpoint |
| Active and actions | 80 % | ISA-18.2 states, alarms and notices, acknowledge one or all, shelve with reason, out of service, owners, areas, disciplines and "My alarms"; missing per-console views and sound |
| Notifications | 95 % | Inside each rule (2026-10-24): the responsible (the schedule's owner), people and groups, Messages and email, gathered per rule, at most 6 an hour per person, inhibited by a failed schedule; by priority with a shift summary, flood as one message, chattering held, stale not reminded, inhibited while the data does not flow (2026-10-25, G9 closed); reminders, hours (shift and on call), escalation to group coordinators, silences, Sent; missing a calendar of on-call rotations |
| Incoming | 90 % | The suite's events read each cycle, kept 30 days, counted per rule, a rule started from an event; conditions (start/end by key) and what is open now; the suite's catalog with suggested rules (2026-10-25) |
| Journal and occurrences | 80 % | Every raise, clear and action with who and when; missing export |
| Performance | 80 % | ISA-18.2/EEMUA 191 figures against the installation's alarm philosophy (editable targets and statement, 2026-10-25), top 10, chattering, stale, priorities; missing per-console figures and a printable report |
| Rules | 75 % | One editor (When, Where, Notify, rationalization), try on history or on the events that came in, suggested limits for loops, migration of older alarms and policies; missing bulk import/export |
| Suite integration | 80 % | Results, events, runs, schedules, asset page, audit, shared frame and tour; compose, proxy and installer entry in PlantCraft (2026-10-21, G1 closed) |
| Packaging | 60 % | Dockerfile, SBOM, signed package target; image not yet built in CI |
