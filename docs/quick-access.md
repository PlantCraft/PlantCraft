# The quick-access bar: what apps send to it

> **Added:** 2026-10-26 (owner decisions D1 to D8, thread "Notificações e Fila")

The four quick buttons at the bottom of every app's sidebar cross the whole suite. Each has one
job, and apps reach each one in one way only:

| Button | What it is for | Who sends | How |
|---|---|---|---|
| **Messages** | Conversations | People and specialists | Apps never write here |
| **Notifications** | Something that needs a person: an alarm, a failure of work they started, an action assigned | Any app, through PlantCraft | `client.notify(...)`, `client.resolve_notification(key)` ([notifications.md](notifications.md)) |
| **Assistant** | Ready questions and creations on each page | Each app, in `app.toml` | Works and tasks ([api-v1.md](api-v1.md), "Knowledge and the assistant") |
| **Queue** | Everything that processes in the background | Any app | Runs (`client.put_runs(...)`) or, for an app without an app key, its own `GET <app>/api/queue` |

## Notifications

- **One thread per key.** The same app and `key` is one entry with its history (an alarm fired,
  reminded, escalated). Use one key per occurrence (`alarm:12:3`).
- **Buttons.** Up to three beside **Open**. `{"label", "href"}` opens a page of the suite;
  `{"label", "href", "method": "POST"}` runs the call in the app that sent it, as the person who
  clicks, with their permissions (`/alarm/api/alarms/12/ack`). PlantCraft refuses a POST button
  outside the sending app's own prefix: a notification never makes a person act in another app.
  The app answers as it does to its own pages; a refusal (403) is shown to the person.
- **Settled for everyone.** When the thing is settled (acknowledged, here or in the app, or
  cleared), the app calls `POST /api/v1/notifications/resolve` with the key and a note
  ("Acknowledged by Ana"). The thread leaves the unread count of everyone who received it, loses
  its buttons and shows the note. A later notification under the same key opens it again, so send
  first and resolve after. Resolving is safe to repeat.
- **At once.** The newest unread critical or high notification of the last hour pops up in
  whatever app the person has open, with its buttons (`urgent_notification` of
  `GET /api/v1/inbox`, read every 15 s while the page is visible). Once closed, acted on or
  opened it does not pop up again in that tab.

## Queue

Anything that runs in the background or can take more than a few seconds goes to the Queue:
Analytics' monitors, Models' simulations, Historian's imports (a large file, a saved import that
runs every day), View's report exports, notebook runs asked of an app.

- **Apps with an app key** write each run (`PUT /api/v1/runs`) as it is queued, starts, moves on
  and ends. The fields the Queue uses beside `status`, `name` and `url`: `by` (the username who
  started it), `progress` (0 to 1, or null), `step` ("Writing 120 of 900 tags") and `cancel`
  (a path under the app's prefix the Queue POSTs as the person, only while it can be cancelled).
- **Apps without an app key** (Historian never calls the suite) answer the same fields in their
  own queue: `GET <app>/api/queue` (`plantcraft-queue/1`) with an optional `items` list
  `[{"id", "name", "by", "status", "progress", "step", "url", "started_at", "finished_at",
  "cancel"}]` (done and failed ones kept 24 hours) and an optional `url` for the app's own page of
  its queue (else `<app>/executions`).
- **The panel.** The Queue button opens each app's numbers first (running of its workers,
  waiting, the oldest wait, failures in the last hour), with a "mine" mark when the person has
  work waiting or running there (owner, 2026-10-26: the overview before the detail). Opening an
  app lists its work by name, newest first: what waits or runs, with its progress, step and
  Cancel, and what ended in the last day, then a link to the app's own page of its queue.
  Above its work, an app that sends tasks to the suite's compute workers (docs/compute.md) shows
  the workers that run them: name, online or paused, how many of its tasks each runs of its
  slots, the environments and the largest size its machine takes (`GET /api/compute/summary`,
  anyone signed in; no host, label or credential), or that none runs them.
  PlantCraft answers the runs part (`GET /api/v1/queue`); the panel adds the items of the apps'
  own queues, and reads them every 5 s while it is open.
- **When it ends.** When a run someone started (`by`, trigger `manual`) fails, or ends well
  after more than a minute, PlantCraft sends that person a notification (category `run`, key
  `run:<id>`). Apps never send it themselves. A short run only turns the Queue button green.

`tests/test_quick_access.py` holds the platform to this page.
