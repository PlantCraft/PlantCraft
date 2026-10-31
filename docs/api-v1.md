# PlantCraft API v1

The contract between PlantCraft (the central app) and every app of the suite.
It is public API: add fields, never remove or rename one inside v1. Contract tests live in
`tests/contract/` here and in each app (against `plantcraft_sdk.testing.FakePlantCraft`).

**Kept as published (scale review E3).** `docs/api/v1/openapi.json` is API v1 as the code serves
it, and `docs/api/v1/releases/<version>.json` as each release served it; every route with its
parameters and the permission an app needs is in the [API v1 reference](api-v1-reference.md),
written from the same file. CI refuses a change to API v1 that `make api-contract` did not write
into `openapi.json` (so every change shows in a review) and any change that breaks a release:
a route removed, a parameter or body field newly required, a response field removed, a type
changed, a request value no longer accepted. `tests/contract/test_sdk_previous.py` runs the SDK
of the last release (`tests/contract/previous-sdk/`, replaced at each release) against this
PlantCraft. In an app's tests, `FakePlantCraft` holds the app's token to its `[permissions]`
as PlantCraft does, and `apptest.permission_problems` (each app's `pytest_sessionfinish`)
fails the run when the app used a permission its `app.toml` does not declare (SDK 0.43.0).

## Topology

One HTTPS origin served by the proxy (Caddy). PlantCraft is mounted at `/`, each app under its
own prefix: Analytics at `/link/`. The proxy is the only published port. PlantCraft is the only
container that reaches plant systems (PI Web API, OPC UA, CSV folders); apps reach PlantCraft
only, at `PLANTCRAFT_URL` (inside Docker: `http://processcraft:8060`). Signal and series reads may also
go straight to the Historian ("Direct reads from the Historian", below).

## Identity

PlantCraft signs short-lived JSON Web Tokens with Ed25519 (`alg: EdDSA`); apps verify them
offline with the public keys from `GET /api/v1/auth/keys` (cached; refreshed on an unknown `kid`).

| Claim | Meaning |
|---|---|
| `iss` | `processcraft` |
| `sub` | user name (or `app:<id>` for a service token) |
| `name` | display name |
| `level` | `admin`, `editor`, `viewer` or `dashboards` (platform-wide access level) |
| `apps` | `{ "<app id>": "editor" \| "viewer" }`: apps this user may open, and how |
| `assets` | Only when the person sees part of the plant: the ids of the roots of the asset tree they see (each root and everything under it). Absent: the whole plant. API v1 already answers a person only about those assets; an app that answers people from its own store keeps the same ones ([asset-scope.md](asset-scope.md), added 2026-10-27) |
| `aud` | `processcraft` or an app id; apps accept their own id and `processcraft` |
| `iat`, `exp` | issued at, expiry (user tokens 15 minutes, service tokens 60 minutes) |
| `kid` (header) | key id, matches an entry of `/api/v1/auth/keys` |

How a token reaches an app:

- **Browser.** After sign-in PlantCraft sets the session cookie and a `processcraft_token` cookie
  (path `/`, `HttpOnly`, `SameSite=Lax`, `Secure` behind HTTPS) holding a user token. The browser
  renews it with `POST /api/v1/auth/token` (session cookie required). An app without a valid token
  redirects the browser to `/login?next=<app url>`. A write (`POST`, `PUT`, `PATCH`, `DELETE`)
  that rides the cookies is refused with 403 when the browser says it comes from another origin
  (`Sec-Fetch-Site` other than `same-origin` or `none`; 2026-10-27): a sibling server of the
  company's domain counts as the same site for `SameSite=Lax`. A request with its own
  `Authorization` header is not checked.
- **App to PlantCraft.** For a user request the app forwards the user's token as
  `Authorization: Bearer <token>`. For background work (rounds, schedules) the app asks for a
  service token with `POST /api/v1/auth/service-token` and its app key (`PLANTCRAFT_APP_KEY`,
  issued by an admin in PlantCraft, stored hashed); service tokens carry `level: viewer`.

- **A person's notebook on their computer** (`docs/en/notebooks.md`). While Notebooks are on,
  API v1 also accepts a person's access token (`Authorization: Bearer pcat_...`, the tokens of
  [assistant-access.md](assistant-access.md)) and answers as that person with their current
  access, for reads only: `GET`, and `POST /api/v1/series`. Any other write answers 403.
  Requests with an access token, and the series reads a person's browser sends through the
  proxy, are limited per person (Settings › Notebooks, `plantcraft/api/usage.py`): past the
  limit the answer is `429` with `Retry-After` and `reason` (`rate` or `busy`). Apps' requests
  (service tokens, and a person's token forwarded by an app inside the network) never count.

When sign-in is off (local single-user mode on 127.0.0.1) PlantCraft still issues tokens, for the
session's current user (the one the demo switched to, else the default user), so apps never need
a second code path and their audit rows name the same person as PlantCraft's own.

## Endpoints

All responses are JSON, UTF-8. Errors: `{"detail": "<message>"}` with 4xx; never a 500 for bad
input. Times are ISO 8601 with offset; series timestamps are UTC.

| Method and path | Purpose |
|---|---|
| `GET /api/v1/auth/keys` | `{"keys": [{"kid", "kty": "OKP", "crv": "Ed25519", "x"}]}` (JWK, public) |
| `GET /api/v1/auth/revoked` | Tokens ended before they expire (public): `{"users": [{"sub_sha256", "not_before"}], "keys": [{"key_id", "revoked_at"}], "sessions": [{"sid_sha256", "ended_at"}]}`; see "Ending tokens early" below |
| `POST /api/v1/auth/token` | Renew the browser token from the session cookie: `{"token", "expires_at"}` |
| `POST /api/v1/auth/service-token` | Body `{"app", "key"}`: `{"token", "expires_at"}` |
| `GET /api/v1/me` | `{"username", "name", "level", "apps": {...}, "notebooks_url"}` from the bearer token; `notebooks_url` is `/notebooks` when the person may open data in a notebook (Notebooks on, viewer and up; added 2026-10-23), else `null` |
| `GET /api/v1/apps` | Installed apps the caller may open: `[{"id", "name", "url", "access", "version"}]` |
| `GET /api/v1/installation` | `{"id", "time_zone", "features"}`: `id` (added 2026-10-25, SDK 0.42.0 `client.installation_id()`) is this installation's UUID, the same for good (`PLANTCRAFT_INSTALLATION_ID`, written once by `install.sh`); apps put it in what they export; `features` (added 2026-10-25, SDK 0.31.0 `client.features()`) lists the tables of `[contributes]` this PlantCraft draws; the installation's IANA zone (Settings › Installation, else `PLANTCRAFT_TIMEZONE`, else `UTC`), what `local` means in an app's schedule (added 2026-10-25; SDK `installation_time_zone()`) |
| `GET /api/v1/inbox` | A person's unread chat messages, unread notifications and open actions, for the badge of the suite's messages button (it shows the two unread counts together): `{"unread_messages", "unread_notifications", "urgent_notification", "open_actions", "messages_url", "actions_url"}` (`urgent_notification`, since SDK 0.53.0: the newest unread critical or high notification of the last hour, `{"key", "title", "detail", "priority", "priority_label", "from", "at", "href", "actions"}`, or `null`; every app pops it up, [quick-access.md](quick-access.md)); `unread_messages` leaves out what apps' robots post since 2026-10-24; 403 for service tokens and dashboards-only accounts ([collaboration.md](collaboration.md)). Browser only: `FakePlantCraft` does not serve it |
| `GET /api/v1/actions` | Follow-up actions, newest decisions first by status and priority: `{"items": [{"action_id", "title", "status", "status_label", "priority", "priority_label", "owner", "owner_name", "due_at", "overdue", "refs", "created_at", "updated_at", "completed_at"}], "actions_url"}`; filters `ref` (`asset:<id>`: the actions about that asset), `status` (repeatable), `limit` (1 to 500, default 100). Read only; for people (viewers and up) and service tokens. The suite frame's follow-up panel reads it ([collaboration.md](collaboration.md)). Browser only: `FakePlantCraft` does not serve it |
| `GET /api/v1/assets` | Asset tree: `[{"id", "name", "kind", "type_path", "parent_id", "attributes", "signals": {"<role>": "<signal id>"}, "relations": [{"type", "to"}]}]`; filters `kind` (exact type), `type` (the type and its subtypes), `parent_id`; result assets (type `result`) only with `results=true` or `kind=result` / `type=result` |
| `GET /api/v1/assets/{id}` | One asset, same shape |
| `PUT /api/v1/assets/results` | Result assets, an app's service token only. Body `{"assets": [{"id": "<app id>.<name>", "parent_id", "name", "description", "made_by", "points": [{"role", "signal": "app-<app id>:<name>", "name", "unit"}]}]}`, the app's whole set (2,000 at most): `{"saved", "ended"}` (see "Result assets") |
| `POST /api/v1/assets/results/remove` | An app's service token only. Body `{"ids": [...]}`: removes its own result assets, `{"removed"}` |
| `GET /api/v1/asset-types` | Type catalog: `[{"id", "name", "description", "icon", "parent", "path", "attributes": [{"key", "name", "data_type", "unit", "required", "default", "options"}], "roles": [{"key", "name", "unit", "required"}], "children"}]` |
| `GET /api/v1/signals` | `[{"id", "name", "source", "unit", "description", "low", "high", "kind", "source_kind"}]`; `source_kind` is the source's type (`opcua`, `pi_web_api`, `csv`, `derived`; `null` when unknown): a `csv` signal is sampled (laboratory analyses) and judged by its own rules; filter `q`; derived signals add `app`, `subject`, `result` and filter by them |
| `GET /api/v1/signals/{id}` | One signal, same shape |
| `GET /api/v1/signals/{id}/series?start&end&step` | `{"signal", "kind", "t": [iso...], "v": [number \| string \| null...]}` (typed by the point's kind); `step` in seconds (optional: recorded values); at most 200,000 points. A runs point answers `{"signal", "kind": "runs", "runs": [{"run_at", "t", "v"}]}` (`run`, `runs`) |
| `POST /api/v1/series` | Body `{"signals": [id...], "start", "end", "step", "quality"}` (1 to 500 ids; `quality` optional): `{"series": [{"signal", "kind", "t", "v"}...], "errors": [{"signal", "status", "detail"}...]}` |
| `GET /api/v1/signals/{id}/value?agg&window` | `{"signal", "agg", "window", "value", "at"}`; `agg` one of `last, mean, min, max, std`; `window` like `1h`, `24h`, `7d` |
| `PUT /api/v1/series` | Derived series, an app's service token only. Body: up to 500 items `[{"signal": "app-<app id>:<name>", "t": [iso...], "v": [...], "name", "unit", "kind", "subject", "result"}]`: `{"written", "errors"}` |
| `PUT /api/v1/series/runs` | Runs points, an app's service token only. Body: up to 500 runs `[{"signal": "app-<app id>:<name>", "run_at", "t": [iso...], "v": [number...], "keep_runs", "keep_days", ...}]`: `{"written", "errors"}` (see "Value kinds, retention and runs") |
| `GET /api/v1/signals/{id}/runs?limit` | A runs point's executions, newest first: `{"signal", "runs": [{"run_at", "start", "end", "n"}]}` |
| `POST /api/v1/series/retire` | An app's service token only. Body `{"signals": ["app-<app id>:<name>"...]}` (1 to 500, its own source only, else 403 and nothing retired): the series it no longer writes stop being listed and read, `{"retired": [ids], "errors"}` |
| `POST /api/v1/audit` | Body `{"action", "subject", "detail"}`; the user comes from the token: `{"id"}` |

Signal ids are `<source id>:<tag>` (`docs/app-standard.md`):
`scenario:FIC-101.PV` for the scenario's own source, `pi:FIC1001.PV` for an added source with
id `pi`. Clients URL-encode the id in a path (`quote(id, safe="")`); `:` needs no encoding, `/`,
spaces and `\` do. See "Signal ids" below.

## Lists in pages, and unchanged answers (added 2026-10-25, `plantcraft-sdk` 0.42.0)

A plant holds tens of thousands of signals (the target is 50,000 per installation), so the long
lists of API v1 answer in pages and say when nothing changed (`plantcraft_sdk.server.paging`):

- **Pages.** `GET /api/v1/signals` and `GET /api/v1/assets` take `limit` (1 to 5,000) and
  `cursor`. The answer is the first `limit` items in id order, `X-Total-Count` (the whole list)
  and, when items are left, `X-Next-Cursor`: send it as `cursor` for the next page. Without
  `limit` and `cursor` the whole list comes in one answer, as before; that form stays for
  clients before SDK 0.42 and is limited at the freeze of v1.
- **Not modified.** Every answer of those lists carries an `ETag`; the same request with
  `If-None-Match: <that ETag>` is a `304` with no body when the list did not change.
- **The SDK does both.** `client.signals()` and `client.assets()` read page by page and keep
  each page with its ETag: asking again for a list that did not change moves only headers.

## Rules for apps

- Read plant data only through these endpoints; never open PI or OPC UA connections.
- Verify every request's token (`plantcraft_sdk.auth`), check `apps[<own id>]`, and record user
  changes with `POST /api/v1/audit`.
- Keep your own database; never read PlantCraft's.
- **Ask in `[permissions]` for what your token does** (added 2026-10-25, scale review E4). An
  app's own service token is held to its permissions on every route (`plantcraft_sdk.scopes`
  names the one each route needs); a route it did not ask for answers `403`. A packaged app is
  held to its signed manifest, an external app to what the administrator granted when
  registering it (by default `read.assets`, `read.signals`, `read.series`, `write.audit`), a
  suite app to what it declares at start (`PUT /api/v1/contributions` `permissions`, sent by
  SDK 0.42 from `app.toml`). An app that declared nothing yet is not held (until the freeze of
  v1). A person's token keeps the person's access. Your identity, the installation and what
  `[contributes]` declares (language model uses, calendar feeds, to-dos, settings) need no
  permission. `PLANTCRAFT_APP_PERMISSIONS=audit` only logs what would be refused.

## Details settled by the first implementation (2026-10-19)

These complete the table above; `tests/contract/test_api_v1.py` checks them.

- **Times (changed 2026-10-23).** Every time PlantCraft stores or answers is UTC in one fixed
  form, `2026-10-23T14:05:09.123Z` (`plantcraft_sdk.utc.utc_iso`), so two of them compare as
  text in their time order. A time sent without an offset is taken as UTC. Rows written before in
  the server's local offset are rewritten once at start (`normalize_times`, in PlantCraft's
  database and in every app database opened through `plantcraft_sdk.server.store`). Each
  person's browser shows them in its own time zone; the plant's time zone
  (`PLANTCRAFT_TIMEZONE`) only says where a day begins (due dates). Series keep their `t`
  lists as they are (UTC with an offset).
- **Configuration.** `PLANTCRAFT_APPS` lists the installed apps as `id=url` pairs separated by
  commas, optionally with a version: `linkcraft=/link/@0.2.0,dashcraft=/dash/`. `name` comes from
  the family names (`CPMCraft`...); `version` is `null` when not given. Apps installed from the
  Apps page ([app-package.md](app-package.md)) are listed after them, while running; a token's
  `apps` claim is fixed when it is issued, so a newly installed app appears once the token is
  renewed (at most 15 minutes, or at the next sign-in). The key pair lives beside
  the database (`tokens.key`, mode 0600) or at `PLANTCRAFT_TOKEN_KEY_FILE`; rotated public keys
  stay listed in `/api/v1/auth/keys` (current key first, up to 5 retired ones) so issued tokens
  keep verifying.
- **Tokens PlantCraft accepts** have `aud: processcraft`. A token reaches it as
  `Authorization: Bearer` or the `processcraft_token` cookie. A deactivated person's tokens and the
  service tokens of a revoked app key stop working at once (service tokens carry a `key_id` claim).
- **Ending tokens early (since SDK 0.8.4).** Disabling a person, a new password and a change of
  their level or applications end every token they hold: PlantCraft refuses it at once, and
  apps, which verify offline, within 10 seconds. `GET /api/v1/auth/revoked` lists, for each such
  person, the SHA-256 of their username (`sub_sha256`, hex) and `not_before` (Unix seconds): a
  token whose `iat` is before it is refused with 401. It also lists the app keys revoked in the
  last hour (`key_id`, `revoked_at`), whose service tokens are refused. Entries stay only as long
  as a token from before them could still be alive (15 minutes for people, an hour for keys).
  A token issued after the change (signing in again) gets `iat` at least `not_before`.
  Signing out ends that browser session's tokens the same way (since SDK 0.84.0): the browser's
  token carries the SHA-256 of its session id (`sid` claim), and the list gives the sessions signed
  out in the last 15 minutes (`sid_sha256`, `ended_at`). The person's other sessions keep working.
  `plantcraft_sdk.auth.TokenVerifier` reads the list at most every 10 seconds; when it cannot
  (PlantCraft down, or older than this list), the last list read stays in force.
- **`apps` claim.** Editors and admins get `editor`, viewers `viewer`, `dashboards` people no app.
  A person's applications list may name an app by its id or by the PlantCraft module it grew
  from (`cpm` and `data_quality` grant `linkcraft`).
- **Cookie.** Set at sign-in and renewed by every `GET /api/session` (page load) and
  `POST /api/v1/auth/token`, also in local mode; cleared at sign-out. `Secure` when the request
  is HTTPS or `PLANTCRAFT_SESSION_HTTPS_ONLY` is on. Local mode tokens are for the session's
  current user with that person's level (`admin` when none is set); `POST /api/session/switch`
  renews the cookie for the person switched to. (Before 2026-10-19 they were always for `admin`.)
- **Status codes.** 401 (no, expired or refused token; with `WWW-Authenticate: Bearer`),
  403 (a `dashboards` person reading plant data; in an app, `apps[<app id>]` missing),
  404 (unknown asset or signal), 422 (a value outside the contract), 502 (the data source failed;
  `detail` says why). `POST /api/v1/audit` answers 201.
- **Assets.** `attributes` holds `description`, `kind_label` and `origin` (more may be added).
  `signals` lists the signals bound with a role; a signal placed on an asset without a role is
  not in it.

## Asset model (added 2026-10-20)

Additive to v1; `plantcraft-sdk` 0.3.0 (`plantcraft_sdk.assets`, `client.asset_types()`,
`client.assets(type=...)`, and `FakePlantCraft(asset_types=...)`). `tests/contract` checks it.

- **Types.** Every asset is an instance of a type; its `kind` is the type id. Type ids are
  `snake_case` (types made before 2026-10-20 from a name keep the id they had). A type has one
  parent (single inheritance): it gets the parent's attributes and roles and adds its own, and
  a change to the parent reaches every child type. `GET /api/v1/asset-types` lists every type with
  inheritance resolved: `path` is root type first and the type itself last, `attributes` and
  `roles` hold the inherited ones first (the root's first), and `children` the types that may sit
  inside it (each allowed type and its subtypes; PlantCraft's interface offers them first, the
  tree does not enforce them). Only admins edit types, in PlantCraft; apps read them.
- **Starter types** (an installation starts with them; the admin may edit any and add others):
  `site` ("Plant"), `unit`, `area`, `equipment`, `loop` ("Control loop"), `pump`, `valve` (both
  under `equipment`), `control_valve` (under `valve`) and `instrument`. Kinds added by hand before
  2026-10-20 became types under `equipment`. The five kinds the platform always had keep no parent.
- **Control loop** (`loop`). Attributes: `loop_type` (choice: `flow`, `level`, `pressure`,
  `temperature`, `composition`), `criticality` (`low`, `medium`, `high`), `action` (`direct`,
  `reverse`), `controller` (`DCS`, `SLC`). Roles: `pv` and `op` (required), `sp`, `mode`,
  `secondary`. An app that works on loops takes every asset whose `type_path` contains `loop`
  (`GET /api/v1/assets?type=loop`); a loop without a signal for a required role is an incomplete
  record, to be shown as such, not hidden.
- **Attributes.** `data_type` is `text`, `number` (with `unit`), `choice` (one of `options`),
  `date` (`YYYY-MM-DD`) or `asset` (the id of another asset). An asset's `attributes` carries,
  beside `description`, `kind_label` and `origin`, the value of every attribute of its type that
  has one, by key: the stored value, else the attribute's `default`; an attribute without either
  is left out. Values are JSON numbers for `number`, strings otherwise. Attribute keys never take
  the names `description`, `kind_label` or `origin`.
- **`type_path`** of an asset is the `path` of its type (`["equipment", "valve",
  "control_valve"]`); for a kind without a type it is `[kind]`.
- **Relations** are typed links outside the tree: `controls`, `measures`, `feeds`,
  `downstream_of`. An asset lists the ones that start from it (`relations: [{"type": "controls",
  "to": "FV-2001"}]`); incoming ones are the other assets' outgoing ones.
- **Filters.** `kind` matches the type exactly (as before); `type` matches the type and every
  subtype (`type=valve` lists valves and control valves); an unknown `type` lists nothing.
- **Signals.** `source` is the id of the source the signal is read from (`scenario` for the
  scenario's own source). `low` and `high` are `null` until PlantCraft keeps engineering limits.
  `kind` is `"number"` or `"text"`: text signals record labels, such as controller modes
  (`"AUTO"`, `"MAN"`); the kind comes from the source (CSV column type, OPC UA `String`
  variables, PI digital and string points). Added 2026-10-19; apps treat a missing `kind` as
  `"number"`.
- **Series.** `start` and `end` are optional: `end` defaults to now (for a recorded file, its last
  sample) and `start` to 24 hours before `end`; a time without offset is UTC; the span is at most
  366 days. Without `step`: the recorded numeric values in `[start, end]` (nulls left out). With
  `step`: a regular grid from `start` (points `t` in `[start, end)`), each point the mean of the
  values in `[t, t + step)`. More than 200,000 points is a 422 (ask with a larger `step`). Every
  series carries the signal's `kind`. A **text series** has strings in `v`: without `step`,
  every recorded label in `[start, end]`; with `step`, the last label of each `[t, t + step)`.
  Numbers recorded on a text signal are written without a needless `.0` (`1.0` becomes `"1"`);
  blank labels are left out of recorded values.
- **Step-hold on a grid** (since 2026-10-20, `plantcraft-sdk` 0.7.1). A step with no sample
  holds the signal's last value before it (numbers: the last recorded value, not a mean; text:
  the last label), as a historian's interpolated grid does for a setpoint or mode recorded on
  change, or a signal scanned slower than `step`. It is `null` instead when:
  - no sample came before it: nothing is filled before the first sample. The value just before
    `start` counts when the source supplies it (PlantCraft asks its readers for that
    look-back value on a grid read: PI's last value before `start`, the OPC UA source's within
    `history_boundary_minutes`, the history cache's last earlier sample);
  - the sample it would hold is null: a source or app that writes `null` (or, for a number,
    something that is not one, such as a PI digital state) says "no value", and that ends the hold;
  - the sample is more than the **hold limit** older than the point: 10 (`HOLD_STEPS`) times the
    larger of `step` and the signal's median spacing between samples in the read. A signal with
    fewer than three samples has no spacing to judge by and is held to `end` (a setpoint left
    alone). So a source outage longer than ten usual spacings stays a gap, not a flat line.
    **Signals recorded on change have no hold limit** (since `plantcraft-sdk` 0.8.3): text
    signals (modes) and signals whose tag ends in the word `SP`, `SETPOINT` or `MODE` (any case,
    after the last `.`, `/`, `\`, `:`, `_`, space or `-`: `FIC-101.SP`, `scenario:mode`;
    `plantcraft_sdk.contract.recorded_on_change`). A source writes them only when they change,
    so their spacing measures how often an operator moves them, not whether the source is alive:
    a setpoint written every 30 s by a demo's pre-written history and then left alone used to go
    null ten spacings later. They hold until their next sample, a null sample, `end` or now. An
    outage still shows: as gaps on the source's sampled signals (PV, OP), as a null sample where
    the source records one (bad quality, a PI digital state), and as a 502 when the source cannot
    be read;
  - the point is after now: nothing is held into the future.
  Steps with samples keep their mean (numbers) or last label (text). The server and
  `FakePlantCraft` shape grids with the same function (`plantcraft_sdk.contract.shape_values`).
- **Batch read** (`POST /api/v1/series`). The same series as the one-signal route, for many
  signals in one request and one read of the data source. `signals` holds 1 to 500 ids
  (each 1 to 300 characters; repeats are answered once, in the order first asked); `start`,
  `end` and `step` are shared and follow the rules above. A body outside these rules is a 422
  for the whole request. Otherwise the answer is 200, `series` in the order asked, and every
  signal that could not be answered is in `errors` instead, with its own `status` and `detail`:
  404 unknown signal, 422 more than 200,000 points for it, 502 the data source failed, 413 the
  request reached its budget of **2,000,000 points** across its series (the first series always
  fits; that signal and every one after it are postponed: ask for them again in another
  request). The SDK's `series_many` does that on its own. It is a POST because the id list can
  be long; it reads only, like every other v1 data route.
  With `"quality": true` (since 2026-10-31, SDK 0.84.0) each series also lists where the
  source's quality was not good: `"quality": [{"t": iso, "quality": "uncertain" | "substituted" |
  "bad" | "good"}]`, oldest first, each change holding until the next one (the first may be the
  state at `start`, then its `t` is at or before `start`; an empty list: good all along). A bad
  sample is still a null value, and an uncertain or substituted one keeps its value, so this is
  the only place they show. A source that keeps no quality leaves the list out.
  A client may also ask for the binary answer (`Accept: application/x-plantcraft-series`, when
  `GET /api/v1/reads` lists `pcs1` in `formats`; `plantcraft_sdk.wire`): the same series, with
  times and values as arrays.
- **Value.** Defaults `agg=last`, `window=1h`; `window` is a number and one of `s, m, h, d`, at most
  366 days, ending now (or at a recorded file's last sample). `value` is `null` without data;
  `std` is the sample standard deviation (0 for one sample). `at` is the time of the last sample
  for `last`, otherwise the end of the window. A text signal has only `agg=last`, whose `value`
  is its newest label (a string); other aggregations are a 422.
- **Audit.** `detail` is any JSON value. The body may add `"app": "<app id>"`; a service token
  always records its own app.

## Result assets (added 2026-10-25)

What an app records about an asset gets an asset of its own, of type `result`, under that asset:
Analytics gives each asset of a schedule one (`FIC-1003 · Daily review`), whose signals are the
points that schedule writes for it (`health`, `verdict`, ...). People find a schedule's outputs
where they look for everything else, in the plant tree, and the Historian points keep their
own retention.

- **Only the app makes them.** `PUT /api/v1/assets/results` carries the app's whole set; the
  service token names the app. Ids are `<app id>.<name>` (letters, digits, `.`, `_`, `-`),
  the parent must be an existing asset that is not itself a result, points are the app's own
  derived signals (`app-<app id>:<name>`) by `role` (lower case, digits and `_`). The first
  broken item makes the request a 422 naming it (`[3] parent_id x is not an asset.`) and
  nothing is written. An id an asset of someone else already has is a 422.
- **Record.** Each result asset's attributes are `app`, `made_by` (what made it, such as
  `schedule:daily-review`) and `state` (`active`, `ended`); `origin` is `app:<app id>`.
- **Ended, not removed.** A result the app no longer lists turns `ended` and keeps its points,
  which stay readable until their retention ends; listed again, it is `active`.
  `POST /api/v1/assets/results/remove` removes them for good (other ids are skipped).
- **Hidden unless asked.** `GET /api/v1/assets` leaves them out unless `results=true` or the
  `result` type is asked for, so apps that walk the tree see the plant only; PlantCraft's tree
  has a "Show app results" switch. An asset's own page lists them among its children.
- SDK: `PlantCraftClient.sync_result_assets`, `remove_result_assets`, `assets(results=True)`;
  the rules are `plantcraft_sdk.assets.parse_result_assets`, shared with `FakePlantCraft`.

## Signal ids (changed 2026-10-20)

The one change inside v1 that is not additive (D2), made once before v1 is frozen.
`plantcraft-sdk` 0.5.0; `tests/contract` checks it.

- **Form.** A signal's `id` is `<source id>:<tag>`; `source` is the same source id. Asset
  `signals` map each role to such an id. A reference to a signal is `signal:<id>`
  (`signal:scenario:FIC-101.PV`); `plantcraft_sdk.refs` parses and builds them
  (`parse_ref(...).signal_id`, `split_signal_id`, `signal_ref`). Source ids are lower-case
  letters, digits, `_` and `-`; the tag is everything after the first `:`, as the source names
  it (spaces, `/`, `\` and `:` included, never percent-encoded).
- **One source per tag today.** PlantCraft reads each tag from one source (its route, else the
  scenario's); moving a tag to another source (a map import, "Use" on the Sources page) changes
  its id, and the role maps follow.
- **Transition (deprecated, dropped when v1 is frozen).** Every read and write that takes a
  signal id also takes a bare tag that exactly one source has: `GET /api/v1/signals/{id}`,
  `/series`, `/value`, `POST /api/v1/series`, result, event and run subjects (`signal:<tag>`)
  and the `subject`/`ref` filters. The answer names the signal as asked (`signal` in series and
  values, the batch's `signal`); `GET /api/v1/signals/{tag}` answers the signal with its new
  `id`. Subjects and event refs are stored by the new id. A bare tag two sources have is a 404
  whose `detail` names both ids.
- **Stored data.** At its first start after the change PlantCraft renames, once, the
  `signal:<tag>` subjects and references it stored (results and their history, run subjects,
  events) to `signal:<source id>:<tag>`.
- **Apps.** Re-read assets and signals (ids are opaque: never build one from a tag), migrate
  any setting keyed by a bare tag to the new id (a bare tag still reads until the freeze), and
  pin `plantcraft-sdk` 0.5.0, whose `FakePlantCraft` serves `fake:FIC-101.PV`... (its
  `series=` and `broken=` may still be keyed by bare tag).

## Results, events, runs and schedules (added 2026-10-20)

How the apps of the suite link (`docs/app-standard.md`, section 6): an app publishes what it
found about an asset or a signal (**results**) and what happened (**events**), and reports its
executions (**runs**) and **schedules** for PlantCraft's read-only Executions page. Apps never
call each other; they read what the others published here. The shapes and rules are shared with
the SDK (`plantcraft_sdk.links`, the client and `FakePlantCraft`);
`tests/contract/test_api_v1_links.py` checks them. `plantcraft-sdk` 0.6.0 adds lists of
events (`client.post_events`) and sends `subject` filters as repeated parameters.

**Who reads them (2026-10-27).** A person reads the results, result history, events, runs,
schedules and knowledge texts of the apps they may open (and the platform's own); an
administrator reads all of them, and an app's service token reads every app's. The same rule
holds on the asset's page, Desk, Home and the assistant, so having an app means reading what it
publishes, wherever it shows. A saved View dashboard reads with View's service token: sharing
it shares what its panels show.

| Method and path | Purpose |
|---|---|
| `PUT /api/v1/results` | Body: up to 500 results `[{"subject", "kind", "status", "score", "usable", "value", "summary", "detail", "at", "expires_at"}]`: `{"saved", "errors"}` |
| `GET /api/v1/results?subject&app&kind&under&group&limit&cursor` | Latest results, in pages by subject, app and kind (`X-Next-Cursor` while more are left; added 2026-10-27, before that a silent cut at 5,000): `[{"app", "subject", "kind", "status", "score", "usable", "value", "summary", "detail", "at", "expires_at", "updated_at", "stale"}]`. `under=<asset id>` keeps the results about that asset and the assets under it; `group=<asset type>` (e.g. `unit`) adds each result's ancestor of that type, `"group": {"id", "name"}` or `null` |
| `GET /api/v1/results/history?subject&app&kind&after&limit` | Status changes about one subject, oldest first: `[{"app", "subject", "kind", "status", "score", "usable", "value", "summary", "at"}]` |
| `POST /api/v1/events` | Body `{"kind", "subject", "summary", "refs", "payload", "severity", "key", "phase", "category"}`: 201 with the event `{"id", "at", "app", "kind", "subject", "actor", "summary", "refs", "payload", "severity", "key", "phase", "category"}`. Body a list of up to 1,000 such objects: 201 with `{"saved", "ids", "errors", "repeated"}` |
| `GET /api/v1/events?ref&kind&after&limit&key` | Events, oldest first: `[event...]`; a person's token leaves out the events of actions they do not see (docs/collaboration.md) |
| `PUT /api/v1/events/catalog` | Body `{"events": [spec...]}`, the app's declared events (`plantcraft_sdk.events.EventSpec`, up to 100), replaced: `{"app", "events"}` |
| `PUT /api/v1/contributions` | Body `{"app"?, "version", "format": 1, "contributes": {...}, "series": [...], "events": [spec...]}`: what the app adds to PlantCraft (`plantcraft_sdk.contributes.ContributionsIn`, [app-standard.md](app-standard.md) section 4b), replaced whole; the events go to the catalog as with `PUT /events/catalog`. A table PlantCraft does not know is kept aside, never refused: `{"app", "events", "unknown"}`. Added 2026-10-25, SDK 0.31.0 |
| `GET /api/v1/contributions` | What every installed app adds, in the suite's order: `{"features", "apps": [{"app", "name", "version", "format", "contributes", "series", "unknown", "updated_at"}]}` |
| `GET /api/v1/contributions/settings` | The calling app's installation settings (`[[contributes.settings]]`) as an administrator set them in Settings › Apps, else their defaults, secrets included: `{"app", "values": {key: value}}`. An app's service token only (403 otherwise). Added 2026-10-25, SDK 0.33.0 `client.app_settings()` |
| `GET /api/v1/events/catalog` | Every declared event, PlantCraft's first: `[{"app", "name", "events": [{"kind", "name", "title", "description", "severity", "category", "phase", "payload", "rule"}], "undeclared", "updated_at"}]` |
| `PUT /api/v1/runs` | Body: up to 500 runs `[{"id", "name", "status", "trigger", "started_at", "finished_at", "subjects", "summary", "url", "by", "progress", "step", "cancel"}]`: `{"saved", "errors"}` (`by`, `progress`, `step`, `cancel` since SDK 0.53.0, for the suite's Queue: [quick-access.md](quick-access.md)) |
| `GET /api/v1/runs?app&status&subject&by&limit` | Runs, newest first: `[{"app", "id", "name", "status", "trigger", "started_at", "finished_at", "subjects", "summary", "url", "by", "progress", "step", "cancel", "updated_at"}]` |
| `GET /api/v1/queue` | A person only (403 for service tokens; SDK 0.54.0): what the suite's Queue panel lists, from the runs apps write: `{"me", "mine", "running"}`, `mine` the runs this person started (`by`) still waiting or running or written in the last 24 hours (up to 20), `running` every run waiting or running in the apps they may open (up to 30); each run as `GET /api/v1/runs` gives it, with `app_name` ([quick-access.md](quick-access.md)). Browser only: `FakePlantCraft` does not serve it |
| `PUT /api/v1/schedules?app` | Body: the app's whole list `[{"id", "name", "cadence", "next_run", "enabled", "url", "subjects"}]` (up to 500; `[]` clears it; `subjects`: what the schedule runs on, `asset:<id>` or `signal:<id>`, up to 2000, since `plantcraft-sdk` 0.51.0): `{"saved", "errors"}` |
| `GET /api/v1/schedules?app` | Schedules: `[{"app", "id", "name", "cadence", "next_run", "enabled", "url", "subjects", "updated_at"}]` |

- **Who writes.** A service token writes for its own app; an `app` that names another app is a
  403 for that item. With a person's token each item names its `app` (`PUT /api/v1/schedules`
  takes `?app=`), and the person needs `editor` access to that app (`apps[<app id>]`); a missing
  `app` is a 422, an app they do not edit a 403.
- **Who reads.** The same rule as plant data: viewers, editors, admins and service tokens;
  `dashboards` people get a 403.
- **Subjects** are `asset:<asset id>` or `signal:<signal id>` (`signal:<source id>:<tag>`;
  a bare `signal:<tag>` of one source is stored under its signal's id, see "Signal ids"). A
  subject PlantCraft does not know is a 404 for that item.
- **Whole request or per item.** A body outside the shapes and limits below is a 422 for the
  whole request, naming the first problem as `[<index>] <field>: <message>`. Otherwise the
  answer is 200: the items that pass are saved, and each item that fails a rule depending on the
  caller or the plant (unknown subject 404, app not allowed 403, missing `app` or a bad `url` or
  `kind` 422) is listed in `errors` as `{"index", "id", "status", "detail"}` (`id` is the
  result's subject, or the run's or schedule's id) and is not saved.
- **Results.** One row per (app, subject, kind); a PUT replaces it. `status` is `ok`,
  `warning`, `alarm` or `unknown`; `score` a number from 0 to 100 (100 = best) or `null`;
  `usable` `true`, `false` or `null` ("other apps may trust this subject's data", `null` = don't
  know); `value` a finite number or `null` (NaN and infinities are a 422, everywhere in the body);
  `summary` at most 300 characters; `detail` a JSON object of at most 16 KB (default `{}`); `at`
  (default: now) and `expires_at` (optional) ISO 8601 times, stored and answered as UTC
  (`2026-10-20T06:00:00+00:00`, whole seconds). `kind` is the producer's bare name
  (`loop_health`, lower case, digits and `_`); a kind written with the app's own prefix
  (`linkcraft.loop_health`) is stored bare.
- **Reading results.** `subject` is repeated, one subject per parameter
  (`?subject=asset:a&subject=signal:pi:Unit 2,FIC 101.PV`, up to 500), or left out for every
  subject. A value is never split: ids may hold commas and spaces (changed 2026-10-20, G41; a
  comma no longer separates subjects; until v1 is frozen, a single value with commas that
  matches no subject is still read as a comma-joined list, for clients before SDK 0.6); `kind=<app id>.<kind>` (`datacraft.signal_quality`) is the same as `app` plus
  `kind`. After `expires_at` a result is answered with `status: "unknown"` and `"stale": true`
  (the stored score, value and summary stay); every result carries `stale`.
- **History.** Every change of a result's `status` (and its first write) is kept for 90 days.
  `subject` is required; `after` is an ISO time (changes whose `at` is later), `limit` 1 to 500
  (default 100).
- **Events.** `kind` is `<app id>.<noun>.<verb>` for the caller's app (`linkcraft.finding.opened`,
  lower case, up to four parts after the app id); another app's prefix is a 422. `subject` must
  exist (404); `refs` holds up to 50 references of the suite (`asset:`, `signal:`, `user:`,
  `run:<app id>/<run id>`, read with `plantcraft_sdk.refs`), anything else is a 422. The event's
  `refs` lists its subject first, then the others without repeats; `actor` is the token's `sub`.
  `summary` at most 300 characters, `payload` a JSON object of at most 16 KB. Reading: `ref`
  (events about or mentioning it), `kind` (exact), `after` (an event `id`: the next `limit`
  events after it, to page forward; without it, the latest `limit`), `limit` 1 to 500 (default
  100); always oldest first. Events PlantCraft records itself (`app` = its module) are listed
  too. An app may also write about itself with the subject `app:<its app id>` (its collector,
  its runs as a whole); any other `app:` subject is a 422.
- **The event's own fields** (added 2026-10-25, Alarms round 8). `severity` is `info`, `ok`,
  `warning` or `critical`: how bad the app thinks it is (the priority of an alarm is Alarms'
  rule's, never the app's). `phase` is `instant` (the default), or `start` and `end` of a
  condition named by `key` (1 to 200 visible characters, like `FIC-101/oscillation`): events
  with one `key` are one condition happening, and a `start` without `key` is a 422. `category`
  is `process`, `equipment`, `data`, `run`, `system` or `user`. Left out, they come from the
  app's catalog; `severity` then from `payload.severity` (how apps wrote it before), else
  `info`. Reading `key=` keeps one condition's events. Every event read carries the four
  fields (`""` for a key or category never given).
- **Only changes are written** (added 2026-10-26, Alarms round 11). A `start` of a condition the
  same app has open with the same `severity`, or an `end` of a condition it has not open, is not
  written again: the answer is the event already saying it with `"repeated": true` (an `end`
  never opened: what was sent, `id` null), 201 as usual; a list's answer counts them in
  `repeated` (`ids[i]` is the existing event's id) and not in `saved`. A `start` with another
  severity (warning to critical) is a change and is written. Apps publish when something
  changes, never to repeat that it is still the same.
- **An hourly budget per app** (added 2026-10-26). An app may write
  `PLANTCRAFT_EVENT_HOURLY_LIMIT` events an hour (1,000 by default, `0` for none); the `end`
  of a condition always passes. Past it, a one-object post is a 429 and a list's items are 429
  errors, and PlantCraft writes `processcraft.events.flood` (about `app:<app id>`, payload
  `{"app", "limit"}`) at most once an hour.
- **Catalogs** (added 2026-10-25). Every app declares the events it writes in
  `[[publishes.events]]` of its `app.toml` (`docs/app-standard.md`, section 6), and the SDK's
  server sends it with `PUT /api/v1/contributions` when the app starts (a PlantCraft before
  SDK 0.31.0: `PUT /api/v1/events/catalog`). A declared `interval`
  event must say `start` or `end`, a declared `instant` one neither (422). A kind the app
  writes without declaring it is still recorded, logged once, and listed in its catalog's
  `undeclared`; from the next major SDK it will be a 422 (`FakePlantCraft` refuses it
  already, so a typo fails in the app's own tests). An app that never sent a catalog writes as
  before. `GET /api/v1/events/catalog` lists PlantCraft's own events first (asset and action
  activity under their bare names, `processcraft.*` about the installation's health), then each
  app's with its full `kind`; Alarms' rule editor reads it.
- **Conditions of an app without an app key** (added 2026-10-25, SDK 0.28). Such an app (the
  Historian) cannot post. It names the conditions it has open now with
  `plantcraft_sdk.server.ops.report_conditions` (`Condition`: `name` of a declared `interval`
  event, `key`, `summary`, `subject`, optional `severity`, `refs`, `payload`, up to 200), and
  its `GET /api/ops/metrics` carries them as `conditions` with its catalog as `events`.
  PlantCraft's health recorder reads them every minute and writes, in the app's name
  (`source` the app, actor `system`), a `start` for each new key and an `end` (severity `ok`)
  for each key gone (`plantcraft.events.conditions`). An app that did not answer, or whose
  metrics lack `conditions`, keeps its conditions open; open ones are stored
  (`relayed_conditions`). A name the app does not declare as `interval` is left out, logged
  once; a `subject` that is not a reference becomes `app:<id>`.
- **Many events at once** (added 2026-10-20, G39). The body may be a JSON list of 1 to 1,000
  event objects, each with the rules above. A list outside the shapes (empty, over 1,000, an
  item that is not an object, a bad `refs`, `summary` or `payload`) is a 422 for the whole
  request and nothing is saved. Otherwise the answer is 201 `{"saved", "ids", "errors"}`: the
  items that pass are recorded in order in one transaction; each one that fails a rule
  depending on the caller or the plant (unknown subject 404, app not allowed 403, missing `app`
  or another app's `kind` 422) is in `errors` as `{"index", "id", "status", "detail"}` (`id` is
  its subject as sent). `ids` has one entry per item: the new event's `id`, or `null` for an
  item in `errors`. The one-object form is unchanged (an item error is the request's status).
  The SDK's `post_events` sends lists of 1,000.
- **Runs.** One row per (app, `id`), replaced on PUT; a run not written for 90 days is dropped.
  `id` is 1 to 128 letters, digits and `_ . : -` (it goes into `run:<app id>/<run id>`); `status`
  `queued`, `running`, `done`, `failed` or `cancelled`; `trigger` (required) `manual`,
  `schedule` or `api`; `subjects` up to 500 subjects, each one must exist. Reading: newest first
  by `started_at` (else the last write), `status` one of the five, `subject` the runs that list
  it, `limit` 1 to 500 (default 100).
- **Queue fields** (SDK 0.53.0). `by` is the username who started the run (1 to 80
  characters); `progress` 0 to 1 or `null`; `step` at most 200 characters; `cancel` a path under
  the app's prefix (an absolute URL or another app's path is a 422 for that item), POSTed by the
  Queue as the person. When a run with `by` first turns `failed`, or `done` more than 60 s after
  `started_at`, PlantCraft notifies that person (category `run`, key `run:<id>`).
- **Schedules.** A PUT replaces the app's whole list, kept in the order sent; `id` as for runs
  and unique in the list (a repeat is a 422); `cadence` is people's words (`every day at 06:00`,
  at most 200 characters); `next_run` an ISO time or `null`; `enabled` `true` (default) or
  `false`.
- **`url`** (runs and schedules) is optional: a path under the app's prefix from
  `PLANTCRAFT_APPS` (`/link/runs/42` for `linkcraft=/link/`), or an absolute `http://` or
  `https://` URL. `//host`, `..` segments, backslashes, spaces, control characters and other
  schemes (`javascript:`) are a 422 for that item; an app not in `PLANTCRAFT_APPS` has no
  prefix, so only absolute URLs.

## Knowledge and the assistant (added 2026-10-21)

An app explains its own objects in plain text, so every specialist of the platform can answer
about them: what a protocol evaluates, what its inputs and outputs mean and how to read them
(with the instructions the app wants an assistant to follow), what a run did and found. The
texts are context, never data: nothing reads a number out of them.

| Method and path | Purpose |
|---|---|
| `PUT /api/v1/knowledge` | Body: up to 500 texts `[{"ref", "kind", "title", "text", "subjects", "url", "transient"}]`: `{"saved", "errors"}` |
| `POST /api/v1/knowledge/delete` | Body `{"refs": [...], "app"?}`: the app's texts about these refs are removed, `{"deleted"}` |
| `GET /api/v1/knowledge?ref&q&app&limit` | Texts written for `ref` or naming it among their `subjects` (its own first), else those holding every word of `q`: `[{"app", "ref", "kind", "title", "text", "subjects", "url", "transient", "updated_at"}]` |
| `GET /api/v1/assistant?ref` | A person's token: `{"ref", "specialists", "suggested", "model_allowed", "conversations", "messages_url", "specialists_url"}` |
| `POST /api/v1/assistant/conversations` | Body `{"specialist", "ref", "text"}`: 201 `{"conversation", "message"}`, a new conversation about `ref` |
| `GET /api/v1/assistant/conversations/{id}?after` | `{"conversation", "messages"}` (messages after the id `after`; read up to the last one) |
| `POST /api/v1/assistant/conversations/{id}/messages` | Body `{"text"}`: 201 with the message |

- **Knowledge.** One row per (app, `ref`), replaced on PUT. `ref` is any reference of the
  suite (`protocol:linkcraft/flow`, `run:linkcraft/42`, `asset:FIC-101`); `subjects` up to 50
  more references the text is also about (a run report names its protocol and loops); `kind` a
  bare name (`protocol`, `run_report`, `note`); `title` at most 200 characters; `text` at most
  20,000; `url` as for runs. A `transient` text (a run's report) is dropped 90 days after its last
  write, the others stay until the app deletes them. Who writes and reads: as for runs.
- **References.** `run:<app>/<run id>` resolves to the run (its name, status and `url`); a
  reference of a kind no module owns resolves to the newest text written for it, so
  `#protocol:linkcraft/flow` becomes a link with the protocol's title wherever it is cited.
- **Assistant.** The routes an app's page uses, through `AssistantPanel` of `@plantcraft/ui`,
  to talk with a specialist about one of its objects (`docs/collaboration.md`). People only (a
  service token or a `dashboards` account gets 403). `specialists` are the active ones,
  `suggested` those reading an app that owns `ref` (`run:` and `protocol:` name it) or published a
  result or a text about it; `conversations` are the caller's conversations citing `ref`. A
  conversation starts with the person's question, cites `ref` and is titled after it; it is an
  ordinary conversation of Messages. `ref` must resolve (422 otherwise), `specialist` must be an
  active specialist (422).

## People, groups and notifications (added 2026-10-22)

Groups of people live in PlantCraft once ([groups.md](groups.md)); apps read them to fill their
pickers and send notifications to a person or a whole group ([notifications.md](notifications.md)).
People are listed without their email or phone: delivering is the platform's job.

| Endpoint | Shape |
|---|---|
| `GET /api/v1/people` | The active people: `[{"username", "name", "role", "job_title", "unit", "groups": [group id...]}]` |
| `GET /api/v1/groups` | `[{"id", "name", "kind", "description", "asset_id", "coordinator", "parent_id", "members": [username...]}]`; `kind` one of `department, area, discipline, team`; `parent_id` the group it sits under, or `null` (added 2026-10-23) |
| `GET /api/v1/notifications` | What a notification can reach now: `{"email": bool}`, true when an administrator set up the email server (Setup, Email), so an app offers email only then (added 2026-10-26, SDK 0.51.0 `client.notification_settings()`) |
| `POST /api/v1/notifications` | An app's service token only (403 otherwise). Body `{"recipients": ["user:<username>" \| "group:<id>"...], "title", "text", "priority", "url", "email", "refs", "key", "category", "actions"}` (1 to 50 recipients; `key` makes one thread in Messages' Notifications per app and key; `category` one of `alarm, run, action, info`; `actions` up to 3 `{"label", "href", "method"}` buttons, each `href` a path of the suite (added 2026-10-24, SDK 0.25.0); `method` `GET` (default: opens the page) or `POST` (SDK 0.53.0: runs the call in the sending app as the person who clicks; the `href` must be under that app's own prefix, else 422); `priority` one of `critical, high, medium, low`; `url` a path of the suite such as `/alarm/alarms/12`; `email: true` also queues an email when the administrator set up a server and the person allows it): `{"delivered": [username...], "email_queued", "unknown": [recipient...]}` |
| `POST /api/v1/notifications/resolve` | An app's service token only (403 otherwise; SDK 0.53.0). Body `{"key", "note"}` (`key` 1 to 200, `note` at most 200 characters, "Acknowledged by Ana"): the app's thread with that key is settled for everyone who received it (it leaves their unread count, loses its buttons and shows the note); a later notification with the key opens it again. Safe to repeat: `{"key", "resolved_at", "note"}` ([quick-access.md](quick-access.md)) |

Each person receives the message in their conversation with the app (its robot user carries the
app's name), so the suite's messages button counts it; the message's `meta` holds
`{"kind": "notification", "app", "priority", "url", "key", "category", "actions"}`. `FakePlantCraft` serves the four
routes and keeps what apps sent in `fake.notifications` (`fake.email_ready` sets the email answer).

## Calendar feeds and to-dos in Desk (added 2026-10-25, `plantcraft-sdk` 0.33.0)

What an app puts in a person's Desk. Desk owns the format (`plantcraft_sdk.desk`); the app
declares its feeds in `[[contributes.calendar]]` and its to-do kinds in `[[contributes.todo]]`
([app-standard.md](app-standard.md) section 4b), and a feed or a kind it did not declare is
refused (422), so what an app may put in anyone's Desk is what the administrator saw on the Apps
page. Who an item is for is its `audience`: `user:<username>`, `group:<id>` or `everyone`. The
app's service token writes for its own app; a person's token writes with `?app=<id>` and editor
access to it.

| Endpoint | Shape |
|---|---|
| `PUT /api/v1/calendar/{feed}` | The feed's whole list, replaced: `[{"id", "title", "start", "end"?, "all_day", "audience", "ref"?, "url"?, "detail"?}]`, at most 2,000 (422 over it). `start`/`end` are days (`all_day: true`) or instants with their offset; `url` a path under the app's prefix or an http(s) URL: `{"app", "feed", "items"}`. In Desk › Calendar each feed is one chip (`visible: false` starts it off); a person sees the items for them of the apps they open |
| `POST /api/v1/todos` | `{"key", "kind", "title", "for", "due"?, "ref"?, "url"?, "detail"?}`, made or changed by `key` (a done one stays done); `for` is `user:<username>` or `group:<id>` that exists, `due` a day. At most 200 open per app and per person or group (429 for a new one over it). Answers the to-do |
| `GET /api/v1/todos` | The app's own to-dos, newest change first; `?state=open\|done\|all`. Each `{"app", "key", "kind", "title", "for", "due", "ref", "url", "detail", "done", "done_at", "done_by", "created_at", "updated_at"}` |
| `POST /api/v1/todos/close` | `{"keys": [key...]}` (1 to 500): the app closes those to-dos, gone from every Desk: `{"app", "closed"}`, how many there were |

The person sees the apps' to-dos in Desk › To-do › From apps (and those due in My day) and ticks
them there; the app reads who ticked it in `GET /api/v1/todos`. A to-do is work the app asks of
a person; a problem is an event, never a to-do. `FakePlantCraft` serves the four routes and
keeps them in `fake.links.calendar` and `fake.links.todos` (`fake.tick_todo` ticks one).

## Language models (added 2026-10-25)

An app writes with a language model only through PlantCraft, which keeps the keys and addresses
and picks the model. Each use is declared in `[[contributes.llm]]`
([app-standard.md](app-standard.md) section 4b) and listed in Settings › Language models as
`<app id>:<id>`, where an administrator gives it the default model, another provider's model or
none; a use declared `default = "off"` has no model until one is chosen. Since the security
audit of 2026-10-26 the app also needs `write.llm` in its `[permissions]` (the administrator sees
it before the install), and a use of an app outside the suite's own bundle (`PLANTCRAFT_APPS`)
starts off whatever it declares, until an administrator gives it a model.

| Endpoint | Shape |
|---|---|
| `POST /api/v1/llm/{use}` | An app's service token only, with `write.llm` (403 otherwise); `use` is `<id>` or `<app id>:<id>` of one of its own uses. Body `{"system"?: text, "messages": [{"role": "user" \| "assistant", "content"}]}`, the last message the user's, at most 200,000 characters in all: `{"use": "<app>:<id>", "model", "text"}`. 404 for a use the app did not declare, 409 when the use has no model now (off, nothing set up, or models forbidden in the installation), 429 past `PLANTCRAFT_LLM_APP_DAILY` calls of the app per plant day (500), 502 when the model's server did not answer. Each call is audited (`language_model.used`: provider, model, characters sent and received). Added 2026-10-25, SDK 0.32.0 |

`client.llm(use, messages, system=...)` sends it (a question or the turns of a chat; 120 s
timeout). `FakePlantCraft` answers it for the uses the app sent in its contributions, keeps
`fake.links.llm_calls` and answers `fake.links.llm_answer` (a text, a function of the call, or
None for 409). The model only reads what the app sends: it never acts on the plant or the suite.

## Compute (added 2026-10-26)

An app never runs the code people write in its own container: it hands a **task** to the
suite's compute workers ([compute.md](compute.md)). A task is a job folder (`job.json` and the
files the app's executor reads) sent as a tar archive; its answer is `result.json` and the files
under `out/`, the same way. An app's service token only (403 for a person's), with
`write.compute` in its `[permissions]`; an app sees only its own tasks. PlantCraft never opens an
archive. A task's fields: `{"id", "app", "version", "kind", "priority", "labels", "run",
"status", "attempts", "worker", "timeout_seconds", "memory_mb", "input_bytes", "output_bytes",
"error", "created_at", "started_at", "finished_at", "seconds"}`; `status` is `queued`,
`running`, `done` (the executor answered: read `result.json` for how it went), `failed` (no
answer, after up to three workers) or `cancelled`.

| Endpoint | Shape |
|---|---|
| `POST /api/v1/compute/tasks` | Body: the archive (`application/octet-stream`, at most 64 MB, `PLANTCRAFT_COMPUTE_MAX_MB`). Query: `kind`, `priority` (`interactive`, `run`, `backfill`), `version` (only an executor of this version runs it), `labels` (comma separated; a worker must have them all), `run` (the app's run id), `timeout_seconds`, `memory_mb` (capped by the app's limits in Settings › Compute): 201, the task. 413 too big, 429 past 20,000 waiting tasks of the app |
| `GET /api/v1/compute/tasks/{id}` | The task |
| `POST /api/v1/compute/wait` | Body `{"ids": [...] (1 to 500), "seconds": 0 to 25}`: `{"tasks": [...], "unknown": [ids]}` as soon as one of them has finished, or after `seconds` |
| `GET /api/v1/compute/tasks/{id}/output` | The answer's archive (`done` only, else 409; 410 once collected or an hour after) |
| `DELETE /api/v1/compute/tasks/{id}` | The app has read the answer: its bytes go now: `{"collected": true}` |
| `POST /api/v1/compute/tasks/{id}/cancel` | Stops a task that waits or runs: the task |
| `POST /api/v1/compute/runs/{run}/cancel` | Every task of the app's run that waits or runs: `{"cancelled": n}` |
| `GET /api/v1/compute/capacity?version` | `{"workers", "slots", "queued", "running", "oldest_queued_at"}`: workers online that run the app's tasks (of that version), so an app can say "waiting for a compute worker" |

`plantcraft_sdk.compute.client.ComputeClient` sends them (`submit`, `wait`, `answers`, `run`,
`cancel`, `cancel_run`, `capacity`). The workers' own routes (`/api/compute-worker/...`) and the
administrators' (`/api/compute/...`) are not API v1: [compute.md](compute.md).

## Notebooks (added 2026-10-25)

The Notebooks kit on a person's computer ([en/notebooks.md](en/notebooks.md)) reads these with
the person's access token when it opens and on `pc.sync()`: the same two folders the browser's
JupyterLab shows. A person's own token or session only (an app's service token gets 403), and
404 while Notebooks is off.

| Endpoint | Shape |
|---|---|
| `GET /api/v1/notebooks` | `{"examples": [{"app", "name", "path"}], "mine": [{"name", "path", "created_at"}], "kit_version", "token_expires_at"}`: the examples, the notebooks PlantCraft wrote for the person ("Open in a notebook"), the kits' version on this server (`null` without kits) and when the access token ends (`null` for a session) |
| `GET /api/v1/notebooks/file?path=...` | One notebook (`.ipynb` JSON) by its `path` from the list: `Examples/<folder>/<name>` or `My notebooks/<name>`; 404 for any other |

FakePlantCraft does not serve them: no app reads them.

### Apps' objects (added 2026-10-26, `plantcraft-sdk` 0.48.0)

A notebook reads every app's objects in one format (`pc.app("link").list("block")`). An app
declares its kinds in `[[contributes.objects]]` and serves them under its prefix
(`plantcraft_sdk.server.objects`, `docs/app-standard.md` section 4b); PlantCraft lists what
each app offers and forwards the reads to the app inside the suite's network with a signed
identity of the person (`plantcraft.api.app_proxy`), so the app applies its own access checks and
never sees an access token. A person's own token or session only (an app's token gets 403);
only the apps the person may open. Reads, and one request to run (below).

| Endpoint | Shape |
|---|---|
| `GET /api/v1/objects` | `{"apps": [{"app", "name", "prefix", "version", "kinds": [{"kind", "title", "description", "run"}], "examples", "runtime"}]}`: `run` is `none`, `local` (it runs in the notebook) or `app` |
| `GET /api/v1/apps/{app}/objects/{kind}` | The app's answer to `<prefix>api/objects/<kind>`: `{"format": "plantcraft-objects/1", "kind", "items": [{"id", "name", ...}]}` |
| `GET /api/v1/apps/{app}/objects/{kind}/{id}` | One object, whole: `{"id", "name", "kind", ...}` as the app describes it |
| `POST /api/v1/apps/{app}/objects/{kind}/run` | `{"id", "options"}` (options at most 16 KB): ask the app to run one object of a kind it runs itself (`run` is `app`: a Models simulation in its queue). The app answers `201 {"format", "kind", "id", "started": {"kind", "id"}}`, the object to read back (a run), or refuses: 403 while its administrator has not switched notebook runs on, or for a person who is not its editor. The one write a person's access token may send; audited as `notebooks.app_run` |
| `GET /api/v1/apps/{app}/notebooks/runtime` | The app's runtime, a zip of its Python packages with `plantcraft-runtime.json` (`entry`); `ETag` and `X-Runtime-Sha256`. The notebook imports `<entry>.run(kind, item, plant, app, **options)` |

404 for an app that offers nothing or that the person may not open, or a kind it does not
declare; 503 when the app does not answer; 502 when it fails. An app's examples
(`[contributes.notebooks] examples`, served at `<prefix>api/notebooks/examples`) appear in the
`examples` of `GET /api/v1/notebooks` with their `app` and the path `Examples/<app>/<name>`.

### Apps' assistant tools (added 2026-10-26, `plantcraft-sdk` 0.61.0)

The read-only tools an app adds to the assistant (`[[contributes.assistant.tools]]`,
[assistant.md](assistant.md), "Tools the apps add"). Forwarded as the person, like the objects
above; a person's own token, session or access token (an access token may send this POST, a read).

| Endpoint | Shape |
|---|---|
| `GET /api/v1/tools` | `{"tools": [{"name", "app", "id", "title", "description", "reads", "input_schema"}]}`: the tools of the installed apps the person may open; `name` is `<app>_<id>` |
| `POST /api/v1/apps/{app}/tools/{id}` | The arguments (at most 16 KB), checked against the declaration (422 for an unknown or missing one); the app's answer to `<prefix>api/assistant/tools/<id>` as it is |

404 for a tool the app does not declare or an app the person may not open; 503 when the app does
not answer; 502 when it fails.

## The Explorer (added 2026-10-26, `plantcraft-sdk` 0.51.0)

One way to find any value or event of the suite, drawn by every app's pickers with
`@plantcraft/ui` `Explorer` (Alarms round 11). Read with a person's or an app's token
(`V1Reader`); nothing here reads a series (a value's preview is `GET /signals/{id}/value`).
The answers are `plantcraft_sdk.explore`'s, shared with `FakePlantCraft`;
`tests/contract/test_api_v1_explore.py` checks them.

| Endpoint | Shape |
|---|---|
| `GET /api/v1/explore` | `{"asset": null, "path": [], "children": [...]}`: the plant's top assets, each `{"id", "name", "kind", "children", "roles"}` |
| `GET /api/v1/explore?asset=<id>` | That asset opened: `asset`, `path` (`[{"id", "name"}]` from the top), `children`, `signals` (`[{"role", "id", "name", "unit", "kind"}]`), `outputs` (the series apps computed about it: `{"id", "name", "unit", "app", "app_name", "result", "kind"}`) and `events` (kinds that named it in 30 days: `{"kind", "app", "title", "count", "last_at", "open", "severity"}`, open conditions first); 404 for an unknown asset |
| `GET /api/v1/explore?q=<words>` | `{"hits": [...]}`: assets, then plant signals, then computed series whose id, name, role and path hold every word, each with its `path`; at most 40 |

Result assets are left out of the tree.

## Derived series (added 2026-10-20)

Series an app computed, published as signals of the app's own source, `app-<app id>` (a source
id cannot hold `:`, hence the hyphen). Additive to v1; `plantcraft-sdk` 0.7.0
(`plantcraft_sdk.derived`, `client.put_series`, `client.signals(app=, subject=, result=)` and
`FakePlantCraft`). `tests/contract/test_api_v1_derived.py` checks it.

- **Who writes.** Only a service token (`sub: app:<app id>`); a person's token is a 403. Every
  `signal` must be `app-<the token's app id>:<name>`; an item naming another app's source makes
  the whole request a 403 and nothing is written.
- **Body.** A JSON list of 1 to 500 items, at most 100,000 values across them:
  `signal` (`app-<app id>:<name>`, the name 1 to 200 characters without control characters or
  outer spaces), `t` (ISO 8601 times; without offset UTC) and `v` (same length: finite numbers
  or `null`, or labels for a text series), and optionally `name` (shown to people, up to 200),
  `unit` (up to 40; a score from 0 to 100 uses `/100`), `kind` (`number`, `integer`,
  `boolean`, `text`, `instant` or `structured`, below; default `text` when a value is a
  string, else `number`), `retention_days` and `managed_by` (below), `subject` (`asset:<id>` or `signal:<id>`, what
  the series is about) and `result` (the result kind it comes from, such as `loop_health`). A
  body outside these rules (NaN and infinities included) is a 422 for the whole request.
- **Answer.** 200 `{"written", "errors"}`: `written` counts the items stored; each item that
  could not be stored is in `errors` as `{"index", "signal", "status", "detail"}` (a series
  written before with the other `kind` is a 422 for that item).
- **Values.** A value written at an instant already stored replaces it; the others stay, so
  sending a series again is safe. `name`, `unit`, `subject` and `result` left out keep the
  stored ones.
- **Reading.** A derived signal is a signal: `GET /api/v1/signals` lists it with `source`
  `app-<app id>` and three more fields, `app`, `subject` and `result` (`null` when not given);
  `?app=`, `?subject=` and `?result=` keep the signals that have exactly those values (plant
  signals have none, so any of these filters leaves them out). Its series, batch reads and
  values follow the rules above; a value window ends at the series' last write when that is
  later than the data's end (a recorded file), never after now. A derived signal can be a
  result or event subject (`signal:app-linkcraft:health.fic-101`).
- **Where it is kept.** Without Historian, in PlantCraft's `derived_series` table. With
  Historian (next section), the write is forwarded there and nothing is kept in PlantCraft.

### Value kinds, retention and runs (added 2026-10-25, `plantcraft-sdk` 0.30.0)

What each execution of an app records (Analytics review round 8, D6, agreed with the Historian). Checked
by `plantcraft_sdk.derived` (`typed_value`, `RunIn`); `tests/contract/test_api_v1_typed.py`.

- **Kinds.** `kind` is one of `number` (finite number), `integer` (whole number; `2.0` is `2`,
  `2.5` a 422), `boolean` (`true` or `false`), `text` (up to 1,000 characters, longer ones
  cut), `instant` (ISO 8601, read back in UTC) and `structured` (a JSON object or list, 64 kB
  at most); `null` is a gap in every kind. A point's kind never changes. Reads answer the
  values typed; `integer`, `boolean`, `instant` and `structured` points are read as recorded
  (`step` is ignored) and their value route takes only `agg=last`.
- **Retention and lock.** `retention_days` (0 keeps the values forever, `null` leaves the
  point's) and `managed_by` (up to 100 characters, such as `link:<schedule id>`; `""` clears
  it, `null` leaves it) are written with the values. A point with `managed_by` has its
  retention and compression set only by its app: people get a 409 in the Historian. Derived
  signals list both (`managed_by` `""` for none, `retention_days` `null` for the default).
- **Runs points.** `PUT /api/v1/series/runs` takes 1 to 500 runs `[{"signal", "run_at", "t",
  "v", "keep_runs", "keep_days", "name", "unit", "description", "subject", "result",
  "managed_by"}]`, checked and owned as `PUT /api/v1/series` is: each is one execution's whole
  series (numbers, 20,000 at most), the point keeps the newest `keep_runs` (1 to 1,000, default
  10) and none older than `keep_days`; a run sent again at the same `run_at` replaces it; a
  point of another kind is a 409 for that item. `{"written", "errors"}`.
  `GET /api/v1/signals/{id}/series` on a runs point answers `{"signal", "kind": "runs", "runs":
  [{"run_at", "t", "v"}]}`, newest first: `run=latest` (default), `run=<ISO run time>` or
  `runs=N` (1 to 50); `start` and `end` do not apply. `GET /api/v1/signals/{id}/runs?limit=`
  (1 to 200, default 50) lists `{"run_at", "start", "end", "n"}`, newest first (422 for another
  kind). The batch read answers a runs point's latest run with `run_at` added; its value
  route is a 422. SDK: `put_series_runs`, `series_runs(signal, run=, last=)`,
  `series_run_list`.

## Data layer: Historian (added 2026-10-20)

Historian is the suite's data layer: when PlantCraft has `HISTCRAFT_URL` (for example
`http://histcraft:8100/hist`), Historian is the only component that reaches plant data sources,
and PlantCraft forwards. API v1 is unchanged for the apps: PlantCraft checks the caller
exactly as before (401, 403), then forwards the request and answers Historian's answer.
Without `HISTCRAFT_URL`, PlantCraft reads its own sources through its history cache, as
before (`plantcraft/platform/datalayer/local.py`). `tests/contract/test_api_v1_histcraft.py`
checks the forwarding against a stub.

| API v1 (and the interface) | Historian |
|---|---|
| `GET /api/v1/signals?q&app&subject&result` | `GET {HISTCRAFT_URL}/api/v1/data/signals` (same query) |
| `GET /api/v1/signals/{id}` (also result and event subjects) | `GET .../api/v1/data/signals/{id}` |
| `GET /api/v1/signals/{id}/series?start&end&step` (also the asset page and history charts) | `GET .../api/v1/data/signals/{id}/series` |
| `POST /api/v1/series` | `POST .../api/v1/data/series` (same body) |
| `GET /api/v1/signals/{id}/value?agg&window` | `GET .../api/v1/data/signals/{id}/value` |
| `PUT /api/v1/series` (derived) | `POST .../api/v1/data/derived` with `{"app", "series": [item + "app"]}`, answering `{"written", "errors": [{"signal", "status", "detail"}]}` (PlantCraft adds each error's `index`) |
| `PUT /api/v1/series/runs` | `POST .../api/v1/data/derived/runs` with `{"app", "series": [run...]}`, answering as `/derived` |
| `GET /api/v1/signals/{id}/series?run&runs`, `GET /api/v1/signals/{id}/runs?limit` | `GET .../api/v1/data/signals/{id}/series` and `.../runs` (same query) |
| `POST /api/v1/series/retire` | `DELETE .../api/v1/data/signals/{id}` for each (the Historian keeps the archive for its retired days) |
| Sources page and plant map: list, add, edit, remove | `GET`, `POST .../api/v1/data/sources`; `PUT`, `DELETE .../sources/{id}` |
| Sources page: "Use" on a source's signals | `POST .../sources/{id}/signals` `{"signals": [tag...]}`, answering `{"added": [ids], "skipped"}` |
| Sources page: status and test, a source's signals | `POST .../sources/{id}/test`, `POST .../sources/{id}/browse` `{"root", "limit"}` |
| Sources page: test settings before saving | `POST .../sources/test` (the body of `PUT .../sources/{id}`) |
| Sources page: "Stop using" a source's signals | `PATCH .../signals/{source id}:{tag}` `{"enabled": false}` per signal |

- **Shapes** are API v1's. With Historian every signal carries `mode` (`source`, `archive` or
  `both`: read from the plant source, from Historian's archive, or both) and `app`, `subject`,
  `result` (`null` for plant signals), passed through to the apps.
- **Sources** are Historian's (its `docs/data-layer.md`): PlantCraft checks the settings a
  person typed as it checks its own (422), then sends `{"id", "name", "kind", "endpoint",
  "namespace_uri", "username", "password", "password_env", "options": {...}, "signals": [tag...]}`:
  `endpoint` is the OPC UA `endpoint_url`, the PI Web API `base_url` or the CSV `path`;
  `options` holds `server`, `auth_type`, `verify_ssl`, `ca_bundle`, `read_mode`, `max_workers`,
  `retries`, `page_size`, `timeout_seconds`, `timezone` and `history_boundary_minutes` (the
  history cache setting stays out). An edit (`PUT`) sends no `signals`, and `password: null`
  keeps the stored one. Historian never returns passwords (`has_password`). Removing a source
  that still has signals is Historian's 409. A source's status and "Test" are Historian's
  `POST .../sources/{id}/test` (`{"ok", "detail"}`; its 502 becomes `ok: false` with the
  source's message). Testing settings before saving is `POST .../sources/test` with the body of
  an edit (`id` is the source being edited, or `unsaved`); without a password Historian uses
  `password_env` or the stored password of that id (a source not saved yet sends `""`), and its
  502 is `ok: false` the same way. A source's signal list is `POST .../sources/{id}/browse` `{"root": <the search text>,
  "limit": offset + limit (at most 20,000)}`, whose `variables` PlantCraft pages. "Stop using"
  a signal is `PATCH .../signals/{source id}:{tag}` `{"enabled": false}`: Historian stops
  collecting it and keeps its history; a tag Historian does not have is skipped, and a derived
  signal is Historian's 422, passed on. Binding a signal to an asset stays in PlantCraft and records the source
  it came from. `plantcraft/platform/datalayer/histcraft.py` is the one place that maps them.
- **Bare tags.** Historian's `/signals/{id}` routes take a bare tag that exactly one source has
  (404 otherwise) and answer with the canonical id, which PlantCraft keeps (a result subject
  `signal:FIC-101.PV` is stored as `signal:plc:FIC-101.PV`); PlantCraft adds no resolution of
  its own.
- **Identity.** PlantCraft calls Historian with a token it issues to itself:
  `sub: app:processcraft`, `aud: histcraft`, `apps: {"histcraft": "editor"}`, signed with
  PlantCraft's key (Historian verifies it with `/api/v1/auth/keys` like any token), valid 5
  minutes and renewed a minute before it expires (and once on a 401).
- **Errors.** Historian's 400, 404, 409, 413 and 422 reach the caller with their `detail`, and so
  does its 504 for a read past its time limit (`HISTCRAFT_QUERY_TIMEOUT`, "ask for a shorter
  period or a larger step"); any other answer (401, 403, 5xx, not JSON) or an unreachable
  Historian is a 502, and no answer within `HISTCRAFT_TIMEOUT_SECONDS` (default 75: a read may
  wait 30 s for its turn in the Historian's read budget, then run 30 s) a 504. The SDK's client
  waits 90 s for a series read (`SERIES_TIMEOUT`), so it never asks again while its read runs.
- **Long series pass through.** A series and a batch are Historian's JSON bytes as it wrote them:
  PlantCraft checks the caller, then passes the answer on without parsing it and writing it
  again.

## Direct reads from the Historian (added 2026-10-23)

The Historian serves API v1's reads itself, at the same paths under its own root
(`{HISTCRAFT_URL}/api/v1/...`), with the same shapes, limits and errors, so an app can read
series without the hop through PlantCraft (PlantCraft keeps people, assets, results,
derived writes and everything else):

| Route on the Historian | Answer |
|---|---|
| `GET {HISTCRAFT_URL}/api/v1/reads` | `{"api": 1}`: this Historian serves the reads below |
| `GET {HISTCRAFT_URL}/api/v1/signals?q&app&subject&result`, `.../signals/{id}` | as API v1 |
| `GET {HISTCRAFT_URL}/api/v1/signals/{id}/series?start&end&step`, `POST .../series` | as API v1 |
| `GET {HISTCRAFT_URL}/api/v1/signals/{id}/value?agg&window` | as API v1 |

- **Who reads.** The rule of API v1's reads: a token PlantCraft signed (a person's, or an
  app's service token), checked against `/api/v1/auth/keys` and the tokens ended early
  (`/api/v1/auth/revoked`, read again every 10 s), at level viewer, editor or admin
  (dashboards-only people get 403). Access to the Historian app is not needed. Nothing there
  writes: derived series still go through `PUT /api/v1/series` on PlantCraft.
- **Apps.** `plantcraft-sdk` 0.13.0 reads `signals`, `signal`, `series`, `series_many` (and
  what is built on them) and `value` there when the client has `historian_url` or
  `PLANTCRAFT_HISTORIAN_URL` is set; the suite's compose file and the app installer set it to
  `HISTCRAFT_URL`. The client asks `GET /api/v1/reads` once; a Historian that does not serve
  the reads, or cannot be reached, leaves them to PlantCraft (asked again a minute later).
  The Historian's own answers (404 unknown signal, 422, 502 a plant source that failed) are the
  answer, as PlantCraft would forward them.
