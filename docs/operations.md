# Operations: backup, updates and monitoring

How the suite keeps its data safe, updates without losing it, and watches itself. The design was
agreed with the owner on 2026-10-21;
this file is the contract the code follows. Everything here is offline: nothing downloads,
nothing reports out.

| Part | Where | Status |
|---|---|---|
| JSON logs, request ids, `/api/ops/metrics`, schema stamp, `[backup]` | `plantcraft-sdk` 0.10.0 | done |
| Backup, verification, restore, restore drill, retention, schedule | `plantcraft.ops.snapshot`, `plantcraft.apps.operations` (the driver) | done |
| Signed bundle, `release.json`, release notes, verified update, automatic rollback | `plantcraft.apps.release`, `deploy/install.sh`, `deploy/bundle.sh` | done |
| The Backups page (back up, check, restore with password and typed name, drill, schedule, history) and the Updates page (version, notes, update history) | `plantcraft.apps.operations_desk`, `/api/operations`, `OperationsPage.tsx` | done |
| Docker's view of every service (`metrics.json`), the suite watch, "System" messages, the Health panel and banner | `plantcraft.apps.installer`, `plantcraft.watch`, `/api/operations/health` | done |
| Diagnostic bundle (Health panel, `install.sh --diagnostics`) | `plantcraft.apps.installer` (`diagnostics`), `/api/operations/diagnostics` | done |
| The suite's health as signals of the Historian's `system` source | `plantcraft.watch.recorder`, Historian `POST /api/v1/data/system` | done |
| The "Suite health" dashboard | View | done |
| Maintenance page, update from the interface | platform, proxy | planned |

## 1. One engine: the operations driver

Backup, restore, the restore drill, update and rollback are one engine,
`plantcraft.apps.operations`, run by the **driver**: a one-off container of the installer
image named `processcraft-ops`, as root, with no network, the install folder at its own path and
the Docker socket. It is outside the Compose project, so it keeps running while it stops and
starts the suite; its name is the lock (Docker never runs two containers with one name). The
admin pages, `install.sh` (`--backup`, `--list-backups`, `--restore NAME`) and the schedule all
start the same driver, so each operation has one code path and one set of tests. PlantCraft
never talks to Docker: it writes a request to `data/app-requests` (`action` backup, verify,
restore, drill, prune) and reads the answer in `data/installer/status`, as for app installs
(`docs/app-package.md`). The `installer` service (uid 10005, no network) checks each request and
starts the driver; it also runs the schedule (`ops-settings.json` in `data/app-requests`).

Every operation writes its journal (`.ops/current.json` in the install folder, beside `data/`,
which a restore swaps) before each phase, and a copy for PlantCraft and the proxy in
`data/installer/status/operation.json`. When the server stops in the middle, the installer
starts the driver with `resume` on its next loop, which finishes or undoes the operation: an
interrupted restore returns to the state before it, an interrupted backup or drill is removed.
An update replaces every container, the installer included, so `install.sh` of the new bundle
drives it: the driver of the installed version takes the backup and, when the new version fails,
restores it (section 3).

## 2. Backup and restore

**What an app declares.** Each app lists its data in `app.toml` (checked by
`plantcraft_sdk.app_manifest`):

```toml
[backup]
sqlite = ["cpmcraft.sqlite3"]        # copied with SQLite's online backup, then checked
files = ["uploads/", "secret.key"]   # copied as they are
skip = ["cache/", "logs/"]           # left out
```

Anything in the app's data folder that none of the three names is copied as a file too: a new
file is never lost because nobody declared it. `plantcraft-app check` fails when a
`*.sqlite3` named in the code is missing from `sqlite`.

**Online, the suite at one instant.** The suite keeps running. Every app's SQLite file is held at the same moment first (a read snapshot each, opened together in a few milliseconds; in WAL mode the apps keep writing beside it), then each is copied from its snapshot in one step of the online backup API, so the backup never holds a run in one app that another app's copy is missing. A copy in steps started again at every commit of a busy app and did not finish in 16 minutes with the apps writing (storage test 2026-10-31, `ci/bench/storage/backup_bench.py`); the one-instant copy took 28 s for 1.5 GB of databases, the same as with the apps idle. A database not in WAL mode (a Docker Desktop bind mount, a share) is copied on its own, in one step, while its app waits. The Historian's
PostgreSQL goes just before, by blocks, at its own consistent point (below); settings (`.env`, `compose.yaml`, `bundle.env`, `release.json`,
`certs/`) as files. Each backup is `backups/<date>-<reason>/` with `manifest.json` (versions,
image ids, size and SHA-256 per file, rows per table), `data.tar.gz` and `histcraft-db/`; the
images get a `:rollback-<date>` tag.

**The Historian's database, by blocks** (`plantcraft.apps.historian_backup`). A historian grows
by hundreds of gigabytes a year, so a `pg_dump` of all of it every night does not scale: it
rewrites every row, takes hours and holds a transaction open meanwhile. PostgreSQL 17 backs
itself up by blocks instead, with the tools already in the `histcraft-db` image (nothing added to
the bundle, no network; pgBackRest was weighed and left out for that reason):

- `pg_basebackup` takes a **full** copy of the database files and the WAL that makes them
  consistent, or an **incremental** one (`--incremental`) holding only the blocks changed since
  the backup it names, which the server knows from its WAL summaries (`summarize_wal = on` in
  `deploy/compose.yaml`). It runs inside `histcraft-db`, as its user, over its local socket,
  into `data/histcraft-db/.ops-staging/`, and the driver moves it into the backup folder.
- A **chain** is a full backup and the incrementals after it, each naming the one before
  (`histcraft_db` in `manifest.json`: `kind`, `base`, `chain`). A chain is at most a full backup
  and 6 incrementals: with daily backups, a full copy a week and six small ones. An incremental
  the server refuses (its WAL summaries are gone, after 10 days without a backup) becomes full.
- A chain belongs to one **lineage** of the database (a random id in
  `data/histcraft-db/backup-lineage`). A restored database starts in a fresh `data/histcraft-db`
  without that file and ends its recovery on a new timeline (`recovery.signal`,
  `restore_command=false`), so the next backup is full. An incremental against a backup of
  another history would hold wrong blocks without any error: both guards stop it (PostgreSQL's
  own, by timeline, and ours, by lineage), and a chain is built on only when every backup in it
  is `ok` and its `backup_manifest` is unchanged.
- `pg_verifybackup` and `pg_combinebackup` run in a throwaway container of the same image
  (`processcraft-ops-pg`): no network, read-only, the Historian's uid, the backups mounted read-only.

- The Historian's archive is **partitioned by month** (histcraft, after 0.3.0): retention drops a
  past month as one table instead of deleting its rows, so it changes no block of the other
  months and the next incremental stays small. Each month is its own table in
  `pg_stat_user_tables`, so the restore drill reads it like any other. Nothing here changes for
  it: a backup taken before the migration restores the old layout, which the Historian migrates
  again on start.

Older backups hold a `pg_dump` (`extra/histcraft-db.dump`); they still restore.

**Verified.** A backup is `ok` only after: every SHA-256 matches the manifest, every SQLite copy
passes `PRAGMA integrity_check`, `pg_verifybackup` reads the new Historian backup in full (every
file's SHA-256 and its WAL), and every backup it builds on is still there, file by file at its
size, with its manifest unchanged. "Check again" reads the whole chain in full. Otherwise it is
`failed`, never counted as good by retention, and the admins get a message.

**Restore drill.** Weekly (Sunday 03:00) and on demand, the installer restores the latest good
backup into a scratch folder (the Historian's chain joined by `pg_combinebackup` and the result
read in full by `pg_verifybackup`), starts the same images as a separate Compose project
(`processcraft-drill`) with no published port and no route out, waits for every `/healthz`,
checks the rows of each SQLite table against the manifest and reads every table the Historian
database had, and removes everything. It checks free disk and
memory first and does not run without them. The result goes to the backup history, to the signal
`system:backup.drill_ok` and, on failure, to a message.

**Schedule and retention.** Daily at 02:00; keep 7 daily, 4 weekly, 3 monthly; the pre-update
backup stays until the next update succeeds. A backup stays while a kept one builds on it (the
Backups page says so), and a week or month is kept by its full backup when it has one, so old
periods hold no chain of incrementals. Disk: about one full copy of the Historian per kept week
or month, plus the small daily ones. The schedule lives in the installer, so backups run while
PlantCraft is down. A backup does not start with less free space than twice the last archive
plus the Historian's part (its database size for a full copy, a twentieth of it for an
incremental).

**Off the server.** A copy on the same disk does not survive the disk. `install.sh
--export-backup <name> --passphrase-file FILE [--out PATH]` writes one backup encrypted (AES-256,
key from the passphrase with PBKDF2, 600,000 rounds; the passphrase is never stored). Local copies
stay unencrypted, root only (`0700`): they hold `.env`, the app keys, the initial admin password,
the database password and the local certificate authority's private key, so a plain copy of
`backups/` must not leave the server. Planned: export to `PLANTCRAFT_BACKUP_EXPORT_DIR` and through
the Download button.

**Restore.** On the Backups page (`/backups`; `/operations` and `/setup/backups` lead there since 2026-10-24) the admin picks a backup, confirms with their password
and types its name. The driver checks it (the Historian's chain too) before anything stops, sets the current state aside (`before-restore`), stops the suite, restores images, settings and data,
rebuilds the Historian's database from its chain (`pg_combinebackup`, then `pg_verifybackup` of
the result), starts it, and waits for every service to be healthy; if one is not, it returns to
`before-restore` by itself and says why. Meanwhile the proxy shows a maintenance page with the
progress. Command line: `install.sh --backup`, `--list-backups`, `--restore <name>`, `--drill`.

**Restore on another server.** Copy the whole chain to the new server's `backups/` (an incremental
needs every backup it names in `needed_by`; `--list-backups` shows them), install the same version
there, then `--restore <name>`. CPU limits above the new host's CPU count are lowered to it before
the suite starts (a 4-CPU server's backup restores on a 2-CPU one). The backup brings the old
server's name (`PLANTCRAFT_HOSTNAME`), certificates and `installation_id`: set
`PLANTCRAFT_HOSTNAME` in `.env` to the new server's names and run `install.sh` again (it applies
the settings and issues the certificates), and retire the old server, which now shares the
installation's identity.

## 3. Updates

**Versions.** The suite has one SemVer version (the bundle's name); each module keeps its own.
The bundle carries `release.json` (suite version, each module's version, every image and its id,
`upgrade_from`, date; `plantcraft.apps.release`) and `RELEASE-NOTES.md`, joined by `bundle.sh`
from each module's `CHANGELOG.md` entry for its version (PlantCraft's from the repository, every
app's from `/app/CHANGELOG.md` in its image; [Keep a Changelog](https://keepachangelog.com/en/1.1.0/):
Added, Changed, Fixed, Security). `plantcraft-app check` fails when the version has no entry.
`UPGRADE_FROM` (bundle.sh) is the oldest installed version the bundle updates.

**Signed.** `bundle.sh` signs `SHA256SUMS` with Ed25519 (`RELEASE_KEY`, the publisher's private
key, never committed; `SHA256SUMS.sig`) with the same keys as `.pcapp` packages, and the hash of
the archive in OpenSSH's format (`<bundle>.tar.gz.sha256.sig`), which an administrator checks
with `ssh-keygen -Y verify` before unpacking (install-offline.md, section 2). Every install checks
`SHA256SUMS.sig`: a first one with the installer image of the bundle, against the key the bundle
carries (it prints the key id to compare with the published one) or `--publisher-key FILE`; an
update with the installer image **already installed**, against the publisher keys the
installation already trusts (`trusted-publishers/`), never by the bundle that asks to replace
it. An unsigned bundle needs `--allow-unsigned` (development). An installation that trusts no
publisher yet (installed from an unsigned bundle) checks its first signed update against the
bundle's key and says so. The bundle's keys join the trusted ones once it is installed.

**Signing on an offline machine.** The release key can live on a machine that never builds
anything: only two small files are signed there, so the images never travel to it.

```bash
# Build machine: the bundle, unsigned.
make bundle ARCH=arm64 DOCKER_BUILD_FLAGS="--platform linux/arm64"
B=dist/plantcraft-<version>-linux-arm64-bundle
# Key machine (python3 with cryptography, plantcraft/apps/{release,package}.py copied over):
python -m plantcraft.apps.release sign <folder holding SHA256SUMS> --key processcraft.key --publisher processcraft
# Build machine: SHA256SUMS.sig into $B, pack again, hash the archive.
tar -C dist -czf $B.tar.gz $(basename $B) && (cd dist && sha256sum $(basename $B).tar.gz > $(basename $B).tar.gz.sha256)
# Key machine: the archive's hash.
python -m plantcraft.apps.release sign-file <name>.tar.gz.sha256 --key processcraft.key
```

`SHA256SUMS.sig` is not listed in `SHA256SUMS`, so adding it changes no hash inside the bundle.

**Before.** Refused, with nothing changed, when a checksum or the signature fails, the installed
version is below `upgrade_from`, the bundle is older than what runs (going back is a rollback),
the disk lacks room for the new images and twice the data, or another operation is running.
Then the driver of the installed version takes a `pre-update` backup while the suite runs.

**After.** The new version stays only when every service of its profiles is running, `healthy`
(their health checks call `/healthz`) and on the image the new settings name (`operations
health`), within `PLANTCRAFT_WAIT_SECONDS`. Otherwise, and when anything fails or the script is
interrupted after the backup, `install.sh` saves the state of the attempt
(`update-<date>-<version>-failed.log`: `docker compose ps` and the last 200 log lines, 0600) and
restores the `pre-update` backup with the driver of the old version: the old version runs again
with its data, healthy. Each outcome (`ok`, `returned`, `rolled-back`) is recorded in the
operations history and in `data/installer/status/update.json`.

**Rollback.** Until the backups are pruned, the previous version stays on the host (images tagged
`:rollback-<date>`, the `pre-update` backup). `install.sh --rollback` restores the newest good
`pre-update` backup of an older version; data written since is set aside in `before-restore`.
An installation from before the driver (0.1.0) keeps its stop-and-copy backup and rollback.

**Tested before every release.** `make e2e-upgrade FROM_BUNDLE=<the released bundle>`
(`ci/e2e-upgrade.sh`, on a machine with Docker, never in GitHub CI) does what a client does:
it installs the released bundle in an empty folder with the demo, adds marked records (an asset,
an action with a checklist item, a group), takes a fingerprint through the APIs
(`ci/upgrade/fingerprint.py`: the ids of every list PlantCraft and the apps serve, the exact
values of a few signals over a closed past hour, the results the apps published, the audit
log's size), updates with the bundle built from the checkouts (`TO_VERSION`, the next patch by
default), checks that every id, value and result is still there and that PlantCraft runs the new
version, walks the demo story (`tests/e2e_suite`), then rolls back and checks again. Logs and
both fingerprints are in `dist/e2e-upgrade/logs/`.

**From the interface (planned).** The Updates page shows the version, its notes and the update
history; uploading a bundle there to update is the next step, through the same driver.

**Schemas only go forward.** Going back restores data; it never undoes a migration. The SDK's
`Database(path, version=...)` stamps the file with the app's version (`PRAGMA user_version`,
`0.10.3` -> `10003`) and refuses, with `SchemaTooNew`, a file stamped by a later version.

## 4. Monitoring

**Metrics.** The installer writes Docker's view every 30 s to `data/installer/status/metrics.json`
(`plantcraft.apps.installer.Installer.metrics`): for each container its state, health, exit
code, restarts, start time, CPU and memory (`docker compose ps`, `inspect`, `stats`), and the
free disk of the install folder. Docker's CPU is a percentage of one core (`cpu_pct`, 344 for
3.4 cores), so each service also carries `cpus` (its limit, `HostConfig.NanoCpus`, else the
machine's) and `cpu_load_pct`, the share of that limit (0 to 100). `host` is the machine itself,
read from `/proc` (`plantcraft.apps.host_usage`): `cpus`, `cpu_pct` (between two reads),
`mem_pct`, `mem_total_bytes`, `mem_used_bytes`, `load_1m`. Docker runs every service's health check, which calls its
`/healthz`, so `health` is each server's own answer seen from outside it. Every server also
answers `GET /api/ops/metrics` (SDK, `plantcraft_sdk.server.ops`) to an admin or a token with the
`ops` scope: version, uptime, warnings and errors logged, requests, server errors, p95 latency.

**The `system` source.** Every 60 s PlantCraft (`plantcraft.watch.recorder.HealthRecorder`)
writes the suite's health to the Historian's reserved source `system`, shown as "System"
("Sistema"), which only PlantCraft writes (`POST /api/v1/data/system`; the Historian's
`docs/data-layer.md`), kept 90 days. Signals: `system:<service>.up` (1 running and healthy),
`.cpu_pct` (share of its CPU limit when the installer gives it), `.mem_mb`, `.mem_pct`,
`.restarts` for every container in `metrics.json`; `system:host.cpu_pct`, `.mem_pct`;
`.latency_ms` (p95), `.errors`, `.warnings` (logged per minute) for every server that answers
`GET /api/ops/metrics` (PlantCraft's own in-process; the others at their Compose service with a
two-minute token of the `ops` scope: `histcraft`, `linkcraft`, `dashcraft`, `alarmcraft`,
`modelcraft`, and `PLANTCRAFT_OPS_URLS`, `service=url` pairs, adds, replaces or, with an
empty url, drops one; an app installed from a package has Docker's view only);
`.queue_items` and `.queue_wait_min` (how long the oldest item has waited) for every server
that reports a work queue (`ops.report_queue`: Analytics' executions, Models' simulations);
`system:host.disk_free_gb`, `.disk_free_pct`; `system:backup.age_h`, `.ok`, `.drill_ok`.
Metrics that carry `conditions` (an app without an app key, the Historian: `ops.report_conditions`)
are handed each minute to `plantcraft.events.conditions`, which writes them as that app's
events, start and end (`docs/api-v1.md`, Conditions of an app without an app key).
A minute with nothing known (the installer silent) writes nothing for that signal: a gap, never
a made-up value. While the Historian is down the values wait in memory, up to 24 h per signal,
and go on the next write. It runs in the leader process only (`ApiRuntime._lead`), with the watch. Only with the Historian as the data layer;
`PLANTCRAFT_HEALTH_SIGNALS=false` turns it off. View creates the read-only dashboard
"Suite health" ("Saúde da suíte") when the source exists.

**The watch** (`plantcraft.watch`). A thread inside PlantCraft, using neither the Historian nor
View, reads `metrics.json`, the backups, the last drill and the last update every 30 s, and
the work queues the servers reported to the recorder's last sample.
A check that fails 3 times in a row (90 s) opens an incident: a message from the robot user
`system` ("System", kind `system`: no password, no sign-in, not in any list of people) in the
conversation "Suite health" with every administrator (new admins join it), and a banner above
every page for them. When the check passes it says so, with how long it lasted. At most one
message per subject every 10 minutes: an incident opened sooner is stored without a message, and
so is its recovery. Incidents and what was told are stored (`watch_incidents`, `watch_state`),
so a restart neither repeats nor forgets them. Every incident is also an event of the platform
(`processcraft.service.down`, `queue.stuck`, `disk.low`, `disk.filling`, `backup.missing`,
`drill.failed`, `installer.silent`, `docker.down`, `certificate.expiring`: `start` with the check as its `key` when it
opens, `end` when it closes; `processcraft.update.finished` after an update), written whether or
not a message went out, so Alarms sees the suite's health with every other event
(`docs/api-v1.md`, Catalogs). Their suggested rules in Alarms are off: the message above already
reaches the administrators.

| Check | Bad when | After |
|---|---|---|
| `service:<name>` | not running (exit code), health check failing, restarted since the last look | 3 ticks |
| `service:<name>` | still `starting`, or `created` and not started | 10 ticks |
| `installer` | `metrics.json` older than 3 minutes | 3 ticks |
| `docker` | Docker does not answer the installer | 3 ticks |
| `disk` | under 10 % free (back above 12 %) | 1 tick |
| `backup` | no good backup for 26 h (from the first look when there is none), daily backups on | 1 tick |
| `drill` | the last restore drill failed | 1 tick |
| `queue:<service>` | items waiting and the oldest has waited over 30 minutes: the queue does not drain | 2 ticks |
| `cert:<id>` | a certificate expires in under 30 days or has expired (one reminder under 7 days) | 1 tick |
| `load:<service>`, `load:host` | CPU (of its limit) or memory over the warning level (80 %) | 5 minutes |
| `load_critical:<service>`, `load_critical:host` | the same over the critical level (95 %) | 5 minutes |
| `errors:<service>`, `errors_critical:<service>` | errors logged a minute over 2 (critical 5) | 5 minutes |

**Load alerts** (`plantcraft.watch.load`). The levels above are stored in `watch_state`
(`load_limits`) and changed on Operations › Load alerts (`GET`/`PUT /api/operations/limits`,
changes by admins only, audited `operations.limits`): on or off, warning and critical for CPU,
memory and errors a minute, and the minutes a level must hold (1 to 120; a short peak, a report
or a backup, says nothing). An incident ends once the value is 5 points under its level (errors:
a fifth of it), so a value on the line does not flap. Warnings are posted with 🟠, critical ones
with 🔴, and are events `processcraft.load.high`, `load.critical`, `errors.high`,
`errors.critical`. Errors a minute come from each server's `GET /api/ops/metrics`, read by the
recorder. Load checks hold still like the services' during an operation.

While the driver runs an operation (at most 6 h) or the installer is silent, the services'
and queues' checks hold still: neither opened nor closed. A service or queue that leaves the
suite (an app removed) ends its incident without a message. An update (done, returned, rolled back) is announced once,
when less than 24 h old. `PLANTCRAFT_WATCH=false` turns the watch off.

**Operations, the built-in app** (2026-10-31). Like Desk, Operations is part of PlantCraft and
sits in the app switcher, for administrators and for people given the **Operations** role
(Users, a checkbox beside the apps; stored as the app role `operations`, `Access.can_operate`;
IT or an integrator's team that keeps the suite running without being an administrator). Pages:
**Status** (`/health`: the last check, open and recent incidents, the machine's CPU, memory, load
and free disk, every service's state, CPU and memory against its limit with the levels' colours,
restarts; `GET /api/operations/health`, which carries the `limits`), **Logs** (`/ops/logs`, below),
**Requests**, **Partners** and **Support access** (below), **Load alerts** (`/ops/alerts`); Backups and Updates stay
for administrators. The Operations
role reads; installing, updating, restoring and changing levels stay with administrators.

**Requests** (`/ops/requests`, Operations › Requests). What the people of the suite ask of IT or
an integrator: an action of kind `request` (`plantcraft.actions`), with a category (something
not working, slow, access, data, a change, other), a queue (the group that answers it: IT, a
company) and `first_response_at`, set the first time someone other than who asked comments,
changes it or logs time. A new request reaches who answers it: its queue's members (the
administrators when it has none) get a notification from "Operations" in Messages, and an email
when they asked for email. Anyone who signs in asks, a viewer too (`POST /api/requests`): "Ask for
help" in the person's menu of every app (`@plantcraft/ui` SuiteShell) opens the form with the app
and page filled in; a log record and an open incident have "Open a request". Who asked follows
theirs; the Operations role sees and answers every request (status and edit too, whatever its
access level: `Visibility.requests`); each request is an action on its own page, with its
comments, checklist and **time**: hours on a day, a note, billable or not
(`POST /api/actions/{id}/hours`, by whoever sees it; removed by who logged it or an admin).

**Partners** (`/ops/partners`, `GET /api/operations/partners?month=`,
`GET /api/operations/hours?month=&company=`, audited `operations.hours.read`). The companies
working at the plant: a group of kind `company` (docs/groups.md) with its teams (groups under it),
people, coordinator on its side, sponsor at the plant, last day of access (no end, active, ending in
30 days, ended: from the next day nobody in it signs in, and the sign-in says why) and open
requests; the hours its people logged in the month (an entry counts for the company of who logged
it; the plant's own people are "Plant"), with the month's report exported as CSV.

**Targets** (`plantcraft.actions.sla`; `GET`/`PUT /api/operations/targets`, the change audited
`operations.targets`). Each priority has a first answer target and a resolution target, in hours
on the clock, day and night (defaults: critical 1 h and 8 h, high 4 h and 24 h, medium 8 h and
72 h, low 24 h and 168 h); an administrator changes them on Requests › Targets. The first answer
runs from the request to `first_response_at`; the resolution from the request to Done, **without
the time it spent Blocked** (waiting for who asked, or a third party: the request's status
history says when). Every request carries `sla` (`response`, `resolution`: target, minutes used,
`running`, `at_risk` from 75 %, `met` or `breached`, the due time while it runs, `paused`). The
Requests list shows the target that matters now (the first answer until there is one) and counts
the late ones; the request's page shows both. An archived request has none. A target changed
applies to the open requests at once.

**Working hours** (`PUT /api/operations/service-hours` `{queue, hours}`, administrators, audited
`operations.service_hours`; read in `GET /api/operations/targets`). A queue may work only some
days and hours (`{"days": ["mon", ...], "start": "08:00", "end": "17:00"}` on the plant's clock);
its requests' clocks then run only inside them, due times land on the next working minute, and
the request's page says so. The default calendar (`queue` null) covers requests without a queue
and queues without their own; with none set, every clock runs day and night. Holidays are not
modelled. Set on Requests › Targets.

**The month's approval** (`POST /api/operations/hours/approve` `{month, company}`, audited
`operations.hours.approved`; `POST /api/operations/hours/reopen`, administrators, audited
`operations.hours.reopened`). Once a month has ended, a company's hours are approved by an
administrator or by the company's sponsor at the plant (the plant's own people's hours by an
administrator), on its Partners card; the approval keeps who, when and the total. From then on no
entry of that month is added or removed for that company's people (409: an administrator reopens
the month first), and the request's page shows those entries locked. A sponsor who is not in
Operations still opens it with Requests and Partners only, and Partners shows only the companies
they sponsor (the session's `access.sponsor_of`); status, logs and the rest stay closed.

**Uptime and maintenance windows** (`plantcraft.watch.uptime`; `GET /api/operations/uptime`,
`POST /api/operations/maintenance/windows` `{starts_at, hours, services, reason}` and `DELETE
.../windows/{id}`, administrators, audited `operations.maintenance.planned` and `.ended`). Status
shows each app's uptime over 24 hours, 7 and 30 days: the share of the watched time (from the
watch's first run) it had no `service:` incident open (stopped, unhealthy, restarting; load is
not downtime), leaving out planned maintenance. A maintenance window (up to 72 hours, now or
later, every app or a few, with a reason) keeps the watch quiet about the apps it covers while it
lasts: no incident opens and nobody is told, as during the watch's own backups and updates. A
window in force is ended with "End now"; a planned one is cancelled. Holidays and partial
degradation are not counted.

**Support access** (`/ops/support`, `plantcraft.auth.support_access`; `GET
/api/operations/support-access`, `POST /api/operations/support-access/grants`
`{username, hours, reason, action_id}`, `DELETE .../grants/{id}`; audited
`operations.support_access.granted` and `.ended`). An administrator lets a person into Operations
for up to 72 hours, for a reason and often a request (its page links here with the request
filled in): while it lasts the person has the Operations role (status, load, logs, every
request) and nothing else changes; they are told in Messages and by email, and Status says until
when. It ends by itself, or earlier with "End now". It cannot be given to someone whose company's
access ended.

The public demo's visitor opens Operations read-only, without Logs (a public server's logs name
its visitors).

**Reading the logs** (`GET /api/operations/logs`, audited `operations.logs.read`). One list of
every server's records, newest first: PlantCraft reads its own file, and asks every running
server's `GET /api/ops/logs` (SDK, `plantcraft_sdk.server.logread`, with a two-minute token of
the `ops` scope, in parallel, 8 s each). Filters, applied by each server on its own file:
`services`, a period (`hours`, default 6, at most 31 days, or `since`/`until`), the lowest
`level`, `text` (in the message, the logger or the error), `request_id`, `logger`, `limit` (at most
1000). Each server reads its rotated files newest first and stops at the first record older than
the period, at most 64 MB scanned. The answer has `records` (each with its `service`),
`truncated`, `services` (the running ones), `missing` (a server down or older than this endpoint:
its logs stay on its disk and in the diagnostic bundle), and `top`, the most frequent warnings and
errors with numbers and ids folded (`#`). The page shows it as a table, opens a record whole,
follows one request through every app ("Same request in every app") and exports CSV.

**Certificates** (`plantcraft.certificates`, B17, 2026-10-25). A certificate that expires stops
a connection without a word on any screen, so Health lists every one the suite uses, read once an
hour: the suite's HTTPS certificate (`certs/cert.pem`, mounted read-only at `/certs`, where `key.pem` stays readable by the proxy only; with
none the proxy's local authority issues and renews its own, shown as "renews by itself") and the
Historian's secure OPC UA connections, its client certificate and the servers' certificates it
pinned (the Historian's `GET /api/v1/certificates`, read with PlantCraft's service token:
`[{"id", "name", "use": "opcua-client" | "opcua-server-pinned", "source_id", "not_after",
"fingerprint_sha256"}]`; ids `opcua-client` and `server-<source id>`; a pinned server's
`not_after` is `null`, "not seen yet", until the Historian has seen its certificate once). Each has a state: ok,
expiring (under 30 days), expired, auto or unknown. An expiring one opens the `cert:<id>` incident
30 days before, with one reminder in the same conversation 7 days before. **Renew** (admins,
audited, `POST /api/operations/certificates/{id}/renew`, which calls the Historian's
`POST /api/v1/certificates/{id}/renew` with the administrator's own token, since the service
token never writes there; the answer is the new item with its `pem`) is offered for the Historian's client certificate only:
the OPC UA servers must then trust the new one, which the page offers to download. A pinned
server certificate is pinned again in its source; the HTTPS one is replaced in `certs/`.

**Logs.** Every server logs through `plantcraft_sdk.server.logs.configure_logging`: one JSON
object per line (time, level, app, version, logger, message, request id, error) to standard error
and to `data/<app>/logs/<app>.jsonl` (10 MB, 4 old files), which survives a replaced container.
The proxy's `X-Request-ID` is logged by every server (`plantcraft_sdk.server.ops.RequestLog`).
Passwords, tokens, keys, cookies and `Authorization` values are replaced by `***` before writing.
Servers run uvicorn with `log_config=None` and no access log of its own.

**Diagnostic bundle.** "Download diagnostic bundle" (Health panel; `install.sh --diagnostics`
writes it to the current folder) asks the installer for a zip (`plantcraft.apps.installer`,
action `diagnostics`; it runs beside any operation): the installer's status files
(`release.json`, health and metrics, backups, the last drill, the operation running and the
operations journal, the last update, installed apps), `docker compose ps` and `images`, the last
200,000 lines (at most 20 MB) of each service's log (`docker compose logs`), the suite's settings
as the installer sees them (its `env_file` is `.env`) with every password, key, token and secret
replaced by `***`, the disk, Docker's `version` and `info`, host facts, and a `README.txt` of what
is inside. Every text is passed through the same redaction (bearer and basic credentials,
`password=`, `token:`, URL passwords). Never databases, plant data, certificates or keys.
Admins only (`POST /api/operations/diagnostics`, then `GET /api/operations/diagnostics/{id}`),
kept 24 h in `data/installer/status/diagnostics/`, both steps audited.

**Zabbix.** `deploy/monitoring/zabbix/plantcraft_zabbix_agent.yaml` (in the bundle at
`monitoring/`) is PlantCraft's official template for Zabbix 7.0 and later, "PlantCraft by Zabbix
agent". A Zabbix agent on the PlantCraft machine reads `metrics.json` once a minute
(`vfs.file.contents`, no token and no PlantCraft account: the install folder and `data/` can be
crossed by others (0711),
`data/installer/status/` 0755, the file 0644), and dependent items take from it the machine's CPU,
memory, load and free disk, the age of the file and, by low-level discovery of `services`, each
service's state, health, restarts, killed-for-memory, CPU and memory as a share of its own limit.
Triggers: the installer silent (the file older than 180 s), nothing read for 5 minutes, a service
not running, unhealthy, restarted or killed for memory, CPU or memory above 80 % (warning) or 95 %
(critical) for 5 minutes, the machine's and each service's, and free disk below 10 %: the same
levels as the load alerts above, as macros (`{$PLANTCRAFT.CPU.WARN}`, `.CPU.CRIT`, `.MEM.WARN`,
`.MEM.CRIT`, `.DISK.FREE.MIN`, `.METRICS.AGE.MAX`). Import it (Data collection, Templates,
Import), link it to the host and set `{$PLANTCRAFT.DIR}` to the install folder (default
`/opt/plantcraft`). `tests/test_zabbix_template.py` checks that every field it reads is one the
installer writes.

**Analytics history and its file.** Analytics keeps loop health and signal checks
`LINKCRAFT_HISTORY_DAYS` (90 by default); past `LINKCRAFT_HISTORY_FULL_DAYS` (14) it keeps the
last point of each hour, and every signal problem. The hourly upkeep thins a day per pass, so the
file stops growing, but SQLite only reuses the freed pages: a file that grew before (2050 loops
and 8214 signals reached 18.5 GB) keeps its size until it is compacted. In a quiet hour:
`docker compose exec linkcraft linkcraft compact --dry-run`, then without `--dry-run`. It runs
only when at least 20 % of the file is free (`--min-free`) and the disk can hold the copy, and it
holds the database while it writes (about 16 s for 1.9 GB).

## 5. Tests

| Promise | Test |
|---|---|
| Online backup is consistent | Writes during the backup; the copy passes `integrity_check` and holds every committed row |
| The Historian is backed up by blocks | Full, then incremental; refused or out of lineage becomes full; a damaged base is never built on; retention keeps every base (`tests/test_historian_backup.py`); live: a restore of an incremental brings every row back on a new timeline and the next backup is full (`tests/test_ops_live.py`) |
| A damaged backup never counts | One changed byte: `failed` and a message |
| Restore works | Install with the demo, back up, delete data, restore, compare rows and read a signal |
| A failed restore undoes itself | A backup naming a missing image: the suite returns to its state, healthy |
| The drill is isolated | No new host port, no network with a route out, no file changed outside its folder |
| A good update stays; a bad one returns | A bundle whose PlantCraft is never healthy: automatic return, old version healthy, data written after the update kept, record and log (`tests/test_update_live.py`) |
| A crash mid-update | The driver killed in each phase; on start the installer finishes or undoes |
| Unsigned or altered bundle | Refused, nothing changed (`tests/test_release.py`, `tests/test_update_live.py`) |
| An older app never opens a newer database | `SchemaTooNew` (SDK `tests/test_ops.py`) |
| Logs and the diagnostic bundle hold no secret | Planted secrets never appear (SDK `tests/test_ops.py`) |
| Every app follows the rules | `plantcraft-app check`: `[backup]`, `configure_logging`, `CHANGELOG.md` |

Unit tests run in `make ci`. Tests that need Docker run on the Mac mini runner nightly and before
each release, not on every pull request.

## 6. Server processes and the Historian's collector

**PlantCraft in several processes** (2026-10-22). One Python process runs Python code for one
request at a time (the GIL), so with many people at once requests wait in line; removing the
database lock inside one process made it worse (3 s, a GIL convoy, measured in the architecture
review). PlantCraft therefore starts `PLANTCRAFT_WORKERS` processes (`python -m
plantcraft.api.serve`, the image's command; `plantcraft --workers N` locally). `auto`, the
default, is 2 to 4 (the CPUs, at most 4) when Historian is the data layer (`HISTCRAFT_URL`), and 1
while PlantCraft reads plant sources itself, because that history cache lives in the process.
Always 1 when the data folder is where SQLite cannot use WAL (a Docker Desktop bind mount on
macOS or Windows, a network share, FUSE), whatever `PLANTCRAFT_WORKERS` says: file locks there do
not hold between processes, and several of them writing a new database corrupted it.
What the processes share, and how (`plantcraft.ops.workers`):

| Shared | How |
|---|---|
| The database | WAL: readers never wait. Blocks that write open with `BEGIN IMMEDIATE` (`Store._write`), so a read-then-write is one step against every process; busy waits up to 30 s |
| Sign-in | The session is a signed cookie; `session.secret` and `tokens.key` are created once (`O_EXCL`); the login throttle is a table |
| First start | `startup.lock`: one process at a time builds its runtime (schemas, starter types, the administrator) |
| Once-only duties | `leader.lock`: the suite watch, the email outbox and clearing stale "writing" marks run in one process; another takes over within 5 s when it ends |
| Caches | Asset types carry a version row (`asset_type_version`); the Apps page applies the installer's answers in one process at a time (`apps-sync.lock`) |
| Shared | The public demo's places and line are tables (`demo_visits`, `demo_line`, [public-demo.md](public-demo.md)) |
| Not shared | The public demo's per-visit request limit is per process (the limit is `PLANTCRAFT_PUBLIC_DEMO_RATE` times the processes), and so is each app's limit on visits' requests in flight |

A new background duty that must run once per installation goes in `ApiRuntime._lead`; state that
must be the same in every process goes in the database, never in a module variable.

**The Historian in several processes** (0.6.0 load tests, 2026-10-31). Analytics' rounds and
methods read hours of raw values at once, and turning them into answers is Python work: in one
process the Historian answered them on one core while the others waited (50 s stalls on the
public demo). `histcraft serve` starts `HISTCRAFT_WORKERS` processes; `auto`, the default, is the
CPUs its container may use (the cgroup limit `HISTCRAFT_CPUS`, at most 4). Always 1 where SQLite
cannot use WAL in its data folder (as for PlantCraft) and when the collector runs inside the
server (`HISTCRAFT_COLLECTOR=embedded`, a one-laptop install). The archive is PostgreSQL; each
process holds `HISTCRAFT_READ_VALUES` divided by the processes, so the memory bound stays the
same; `startup.lock` and `leader.lock` (`plantcraft_sdk.server.workers`, the same locks as
PlantCraft's) keep the first start and the work queue's sampler to one process.

**Historian's collector on its own.** `histcraft-collector` (`histcraft collect`, the Historian
image, no port, healthy while its heartbeat is fresh) collects and archives; `histcraft` serves
the pages and the API with `HISTCRAFT_COLLECTOR=off`. Restarting or updating the server, or a
heavy query, no longer stops the recording. A collector holds a PostgreSQL advisory lock while it
writes, so a second one (left on by mistake) waits as a standby (`apps/historian/docs/boundary.md`).
An update needs nothing by hand: `install.sh` stops the services for the backup and `compose up`
starts the new service from the same image.

**Historian's gateway.** `histcraft-gateway` is Telegraf (pinned by digest, bundled like
`histcraft-db`). It reads the MQTT, Modbus TCP and SQL sources an admin adds on Historian's
Sources page and pushes their values to the collector (port 8186 inside the plant network,
`HISTCRAFT_INGEST_PORT`). Its configuration is written by the collector into
`data/histcraft/gateway/` and reloaded by Telegraf when it changes; nothing is edited by hand.
A source that sends nothing for 60 s shows Disconnected in Historian. Limits:
`HISTCRAFT_GATEWAY_CPUS`, `HISTCRAFT_GATEWAY_MEMORY`.
