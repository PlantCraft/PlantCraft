# Disaster recovery

How much an installation can lose and how long it takes to come back, for each thing that can go
wrong. The mechanics (backups, the restore drill, updates and rollback) are in
[operations.md](operations.md); this page is the promise they add up to, and how it is checked.

**RPO** (recovery point): the data written since the last good backup, which a restore cannot
bring back. **RTO** (recovery time): from the decision to restore to the suite answering again.

## The numbers

| What happened | Recovery | RPO | RTO |
|---|---|---|---|
| A bad update | Automatic rollback to the `pre-update` backup, or `install.sh --rollback` | none (the backup is taken just before) | the rollback: minutes |
| A person deleted or broke something | Backups page › restore the backup from before it | up to 24 h (daily backup at 02:00), less with a backup taken by hand | minutes on a small plant; the Historian's size sets it on a large one (the restore stops the suite meanwhile) |
| A container or the server restarted | Nothing to do: Docker starts the suite again | none for the stores; the Historian has a gap for the time its collector was down | the start: about a minute |
| The server's disk is lost | A new server, the same bundle, `install.sh --restore` from a copy kept off the server | the age of the last copy off the server | install plus restore (estimate: under an hour on a small plant) |
| The Historian's database is damaged | Restore the latest good chain (full plus incrementals) | up to 24 h | proportional to the Historian's size |

Measured on the release battery of 0.4.0 (demo data, 4 CPUs, 16 GB): backup plus restore drill
in 31.5 s. On a large plant the Historian dominates: a full copy is about its database size on
disk, read back in full by `pg_verifybackup`; time a drill on your own data and write it here.

## What it rests on

- **A daily backup that is checked.** Each backup is verified when taken (SQLite integrity, every
  file's SHA-256, `pg_verifybackup` for the Historian) and a failed one is never counted as good.
  The signal `system:backup.age_h` and the suite watch tell the administrators when there has been
  no good backup for 26 h.
- **A weekly restore drill.** Every Sunday at 03:00 the installer restores the latest good backup
  into an isolated copy of the suite, waits for every app to answer and compares the rows with
  the manifest (`system:backup.drill_ok`; a failure becomes a message to the administrators). A
  backup that has never been restored is a hope, not a backup.
- **A copy off the server.** Backups on the server's disk do not survive that disk. Until the
  encrypted export ships ([operations.md](operations.md), "Off the server"), copy
  `backups/` to another machine or disk on a schedule of your own (`rsync` from the host, as
  root; the folder is `0700`).
- **The bundle and the settings.** Keep the bundle that is installed (`release.json` names it)
  and `.env`; a backup holds the settings and the image ids, but a new server needs the bundle
  to load them.

## On every release

The release battery runs a backup and a drill on the new version and an update from the version
before (`make e2e-upgrade`: nothing lost, rollback works). A release whose drill fails does not
ship. The numbers above are updated from it.

## When it happens

1. Pick the backup: the Backups page lists each with its date, reason, size and check result.
2. Restore with your password and the backup's name typed in. The suite sets its current state
   aside in `before-restore` first, so a wrong pick can be undone.
3. Check the Health page: every app answering, the collector running, no gap you did not expect.
