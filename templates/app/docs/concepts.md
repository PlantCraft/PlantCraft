# Concepts

## PlantCraft and its apps

PlantCraft is the central app of an installation: it signs people in, keeps the asset tree, the
data sources and their signals, the audit log, messages, licences and backups, and shows the
launcher. Everything else is an **app**: its own folder, its own container, its own database,
its own version. Analytics, Historian, View, Alarms, Models and Documents are apps like the one
you are building, made from the same standard.

```text
            browser
               |
         PlantCraft proxy  ---- /            PlantCraft (sign-in, launcher, assets, signals)
               |          ---- /logbook/     your app
               |          ---- /hist/ ...    the other apps
               |
     your app --- API v1 (token) ---> PlantCraft
```

An app talks to PlantCraft only through **API v1**, with `plantcraft-sdk`. It never imports
another app's code and never calls another app: apps link through what they publish in
PlantCraft (results and events).

## What your app owns, and what it asks for

| Your app owns | PlantCraft owns (your app reads it through API v1) |
|---|---|
| Its object (a note, a logbook entry, a study) and the rules on it | People, sign-in, roles, groups |
| Its tables, in its own SQLite database | Assets, asset types, signals, data sources |
| Its pages, inside the suite's frame | Time series (through Historian when installed) |
| Its help pages | The audit log, messages, notifications |
| The methods that compute something from plant data | Licences, backups, the launcher |

When two apps would need the same thing, it belongs in PlantCraft, not in either app.

## Referring to things

An app never copies the asset tree or plant samples. It keeps ids and reads the rest when it
needs it:

| Reference | Means |
|---|---|
| `asset:<id>` | An asset of PlantCraft's asset tree |
| `signal:<source>:<tag>` | A signal of a data source |
| `run:<app>/<id>` | A run of an app |

Every app also answers `<prefix>assets/<id>`: the page of one asset inside the app. PlantCraft
links to it from the asset's page.

## Who may do what

Every request carries a PlantCraft token. PlantCraft says whether the person may open your app
and with which level: viewers read, editors change, admins also manage. Your routes check it
with one line (`CurrentUser`, `EditorUser`, see [backend.md](backend.md)). An app may also have
its own **app key**, for what it does on its own (background work, events); it gets exactly the
permissions `app.toml` declares and nothing else.

## The rules that never bend

- **Read-only on the plant.** No app writes to a DCS, PLC, historian or OPC UA server.
- **Bad data never crashes.** Wrong input gets a 422 with words a person can act on; never a 500.
- **No silent wrong answers.** A result the app cannot compute says so.
- **Offline.** No CDN, web font, telemetry or update check: plants run without the internet.
- **Every change is audited** in PlantCraft's audit log.

[`../AGENTS.md`](../AGENTS.md) has the full list, and the tests in `tests/` check most of them on
every `make ci`.

## The package

An installation gets your app as a signed `.pcapp` file: `app.toml`, the Docker image and its
SBOM, signed with your publisher key. The administrator sees the permissions before installing,
and PlantCraft refuses a package whose signature it does not trust. See
[packaging.md](packaging.md).
