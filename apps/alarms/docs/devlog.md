# Devlog

## 2026-10-24 (round 7: rules)

- Rules make the alarms (owner, 2026-10-24: "dentro do alarme seriam feitas essas
  configurações"): `alarms/rules.py` (RuleDraft, RuleStore), `engine/scope.py` (subjects under a
  branch, which events count), `monitor/sync.py` (one alarm per subject), `judge_events` and
  `replay_events` (N events in a window, still open after a while), Incoming (`/api/v1/events`
  read with a cursor, kept 30 days), Notify inside the rule with gathering, a limit of 6 messages
  an hour per person and inhibition by a failed schedule; older alarms and policies migrate into
  rules with the same ids. Five pages: Overview, Active, Incoming, Rules (with Silences), History
  (Journal, Sent, Performance); old paths redirect. The demo has five example rules instead of 26
  alarms. Browser journeys rewritten (closes G2).

## 2026-10-21

- First version: alarm contract and store (alarms, occurrences, journal), `engine.evaluate`
  (limits, deadband, delays, no data) and `engine.performance` (ISA-18.2/EEMUA 191 figures),
  the monitor (one batch read per cycle, results, events, runs, schedule), the API (configuration,
  try on history, suggested limits, summary, acknowledge, shelve, out of service, journal,
  performance, asset page), help pages and the interface (summary, journal, configuration,
  editor, alarm page, performance). Skeleton from ProcessCraft Twin (same app standard).

## 2026-10-21 (history replay and the way through)

- `POST /api/history/replay {hours, acknowledged_by}` (editors; `GET` for progress): every enabled
  alarm judged over the archive before it was created (`monitor/history.py`, same judge as "Try
  it"), occurrences and journal lines at their own moments, optionally acknowledged by a person;
  run again, it changes nothing. The demo seed uses it so the journal and Performance have days
  of history on a fresh install.
- Summary page opens with "Where to start" (configure, answer, review, improve); the alarm page
  ends with the asset's follow-up (ProcessCraft actions) and next steps.

## 2026-10-21: on the suite's shared server and test kit (processcraft-sdk 0.9.0, @processcraft/ui 0.7.0)

- Server: the SQLite store, `app.toml` and help, access checks and the web application come from
  `processcraft_sdk.server`; `db.py` and `deploy/sbom.py` are gone, `meta.py`, `api/deps.py` and
  `api/app.py` keep only the parts that are Alarms' own. The image writes its SBOM with the SDK.
- Interface: the API client, the Help page, the source picker and the segmented control come
  from `@processcraft/ui` (`al-segmented`, `al-source` and `al-search` styles are gone).
- Tests: `tests/test_suite_rules.py` (offline, layers, image, API floor, hostile inputs, on
  `processcraft_sdk.apptest`) replaces four files; the test plant is `processcraft_sdk.testplant`;
  e2e fixtures use `processcraft_sdk.e2e`; time budget in `pyproject.toml` (`make test-fast`).
- Docs: `AGENTS.md` is the short module file (the suite's rules live once, in ProcessCraft's
  `AGENTS.md`); the README says how the module is built (with Claude Code, in the open); `make
  test-fast` in Develop.
- `docs/gaps.md` in the suite's format (Id, Gap, Impact, B); G1 (the suite entry) closed.

## 2026-10-22: owners, areas, notification policies and silences (processcraft-sdk 0.12.0, @processcraft/ui 0.16.0)

- `AlarmDraft`: `owner` (`user:`/`group:`, the creator when empty; older alarms read their
  `created_by`), `area` (an asset; else the top of the alarm's branch of the asset tree, below a
  site root), `discipline`, `notify`.
- `alarms/notices.py`: `policies` (the built-in `default`, to the owner, high and up, sends only
  when no other policy matches), `silences`, `outbox` (kept 30 days). `engine/routing.py`: pure
  matching (an area matches anywhere in the alarm's chain of assets), silences, recipients.
- `monitor/notifier.py`: raises and clears are queued per routed policy in the cycle; reminders
  for active unacknowledged alarms every `repeat_minutes`; a batch per policy and recipients goes
  out once its oldest row is `group_seconds` old (`POST /api/v1/notifications`); refused sends
  wait, rows older than a day are dropped; shelved or silenced alarms send nothing.
- `monitor/reader.py`: `AssetTree` and `Directory` (people and groups), each read once a minute
  with the app's key; an older ProcessCraft without them leaves both empty.
- API: `/api/directory`, `/api/notifications`, `/api/policies[/{id}[/alarms]]`, `/api/silences`,
  `/api/silences/{id}/end`; `mine`, `owner`, `area_*` and `discipline_label` on every alarm row,
  `counts.mine` on the summary, owners on Performance's lists.
- Interface: the Overview's JourneyPath is gone (as on every page of the suite); My alarms and All
  alarms; area, discipline and owner columns with filters; the editor's "Owner and
  notifications" section (`RecipientPicker`) and a priority-share hint; the Notifications page
  (policies, the alarms each sends, silences, what was sent).

## 2026-10-22 (app verdict alarms)

- A source can name another app's result on an asset (`result: "<app>:<kind>"`, kind
  `verdict`); `engine.evaluate.judge_verdict` raises at `alarm` (or `warning` and worse) with
  the delays, keeps the state while the result is stale or unknown. The monitor reads every
  verdict once a cycle (`ApiReader.verdicts`, `GET /api/v1/results`); history replay skips them.
- `GET /api/verdicts?asset=` for the editor's verdict picker; the alarm page shows the latest
  verdict. Closes G9 without touching Link: any app that publishes results can raise an alarm.

## 2026-10-22 (hours and escalation on notification policies)

- `PolicyDraft` gains `hours_mode` (always, inside, outside), `hours` (windows: days, start, end;
  past midnight when the end is before the start; `24:00` ends a whole day), `timezone` (IANA,
  checked) and `escalations` (up to five steps: minutes, recipients incl. `coordinator`, email).
- `engine.routing.in_hours` reads the policy's wall clock; `routes(..., now)` leaves out a policy
  outside its hours, `now=None` (counts, "My alarms") ignores hours. `record` routes at the
  cycle's time, not the sample's.
- `Notifier.remind` hands an unacknowledged alarm over when a policy's hours begin and queues due
  escalation steps from when the policy announced the occurrence (`NoticeStore.announced`);
  outbox rows carry `step` (column added in place on older databases). Escalations skip
  gathering; reminders and escalations still waiting drop once the alarm is acknowledged.
- Fix: the recipient picker sent `group:owner`; `owner` and `coordinator` now travel as words.

## 2026-10-25: Alarms round 8 (events as conditions, catalog, philosophy, anti-flood)

- `IncomingStore`: columns `phase`, `event_key`, `category` (added in place) and table
  `conditions` (open start/end pairs by app and key). `scope.counts` ignores an end;
  `scope.clears` clears on the end of a counted kind; `event_subject` keys an app-wide event by
  its condition key.
- `alarms.philosophy` (`PhilosophyDraft`, one row) read by `Notifier` each cycle: outbox status
  `digest` (shift summary, `Notifier.summarize`, mark `summary_at` in `rule_meta`), `chatter`
  (from occurrences in the last minute and hour), flood per recipient (`NoticeStore.raised_for`),
  stale alarms skip reminders, `data_down` from the open conditions. `performance` takes the
  targets.
- `monitor.suggest`: the catalog from PlantCraft, the editor's prefill, suggested rules marked
  enabled created once (`rule_meta` `suggested:<kind>`), read every 10 minutes.

## 2026-10-25 (the Historian's conditions)

- `data_down(alarm)`: `histcraft.collector.stalled` inhibits like the Historian down;
  `histcraft.source.disconnected` (key `source:<id>`) only the alarms whose `signal_id` is of
  that source. SDK 0.28.

## 2026-10-27 (a focused Overview)

- Default board: by priority (4x2) and the rate (8x2), the summary and the most frequent (6x3),
  the ISA-18.2 indicators (12x2). `rate` is `columns` (per hour, stacked by priority, target
  line at the philosophy's `per_person_hour`), `bad-actors` is `bars` coloured by priority,
  `performance` gives each figure its state, the ones out of target first. `performance()`
  answers `hourly` and each top alarm's `priority`. SDK 0.69.0, ui 0.72.0.
