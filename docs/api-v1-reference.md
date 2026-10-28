# API v1 reference

Written by `python -m processcraft.api.contract write` from `docs/api/v1/openapi.json`;
never edited by hand. The rules, the shapes and examples are in `docs/api-v1.md`.
**Permission** is what an app's own token needs (its `app.toml` `[permissions]`):
*any app* for every app, *people only* for a route no app's token may use.

| Method | Route | Permission | Parameters | Summary |
|---|---|---|---|---|
| GET | `/api/v1/actions` | people only | `ref`, `status`, `limit` | Actions |
| GET | `/api/v1/apps` | any app |  | Apps |
| GET | `/api/v1/apps/{app}/notebooks/runtime` | people only | `app`* | Runtime File |
| GET | `/api/v1/apps/{app}/objects/{kind}` | people only | `app`*, `kind`* | Objects |
| POST | `/api/v1/apps/{app}/objects/{kind}/run` | people only | `app`*, `kind`*, JSON body | Run Object |
| GET | `/api/v1/apps/{app}/objects/{kind}/{object_id}` | people only | `app`*, `kind`*, `object_id`* | One Object |
| POST | `/api/v1/apps/{app}/tools/{tool_id}` | people only | `app`*, `tool_id`* | Call Tool |
| GET | `/api/v1/asset-types` | `read.assets` |  | Asset Types |
| GET | `/api/v1/assets` | `read.assets` | `kind`, `type`, `parent_id`, `results`, `limit`, `cursor` | Assets |
| PUT | `/api/v1/assets/results` | `write.results` | JSON body | Put Result Assets |
| POST | `/api/v1/assets/results/remove` | `write.results` | JSON body | Remove Result Assets |
| GET | `/api/v1/assets/{asset_id}` | `read.assets` | `asset_id`* | Asset |
| GET | `/api/v1/assistant` | people only | `ref`* | Assistant |
| POST | `/api/v1/assistant/conversations` | people only | JSON body | Start |
| GET | `/api/v1/assistant/conversations/{conversation_id}` | people only | `conversation_id`*, `after` | Conversation |
| POST | `/api/v1/assistant/conversations/{conversation_id}/messages` | people only | `conversation_id`*, JSON body | Send |
| POST | `/api/v1/audit` | `write.audit` | JSON body | Audit |
| GET | `/api/v1/auth/keys` | any app |  | Keys |
| GET | `/api/v1/auth/revoked` | any app |  | Revoked |
| POST | `/api/v1/auth/service-token` | any app | JSON body | Service Token |
| POST | `/api/v1/auth/token` | any app |  | Renew Token |
| PUT | `/api/v1/calendar/{feed}` | any app | `feed`*, `app`, JSON body | Put Calendar |
| GET | `/api/v1/compute/capacity` | `write.compute` | `version`, `environment`, `size` | Capacity |
| POST | `/api/v1/compute/runs/{run_id}/cancel` | `write.compute` | `run_id`* | Cancel Run |
| POST | `/api/v1/compute/tasks` | `write.compute` | `kind`, `priority`, `version`, `labels`, `run`, `timeout_seconds`, `memory_mb`, `environment`, `size` | Submit |
| DELETE | `/api/v1/compute/tasks/{task_id}` | `write.compute` | `task_id`* | Collected |
| GET | `/api/v1/compute/tasks/{task_id}` | `write.compute` | `task_id`* | Task |
| POST | `/api/v1/compute/tasks/{task_id}/cancel` | `write.compute` | `task_id`* | Cancel |
| GET | `/api/v1/compute/tasks/{task_id}/output` | `write.compute` | `task_id`* | Output |
| POST | `/api/v1/compute/wait` | `write.compute` | JSON body | Wait |
| GET | `/api/v1/contributions` | any app |  | Contributions |
| PUT | `/api/v1/contributions` | any app | JSON body | Put Contributions |
| GET | `/api/v1/contributions/settings` | any app |  | Contribution Settings |
| GET | `/api/v1/events` | `read.events` | `ref`, `kind`, `after`, `limit`, `key` | Events |
| POST | `/api/v1/events` | `write.events` | JSON body | Post Event |
| GET | `/api/v1/events/catalog` | any app |  | Event Catalog |
| PUT | `/api/v1/events/catalog` | any app | JSON body | Put Event Catalog |
| GET | `/api/v1/explore` | `read.assets` | `asset`, `q` | Explore |
| GET | `/api/v1/groups` | `read.people` |  | Groups |
| GET | `/api/v1/inbox` | people only |  | Inbox |
| GET | `/api/v1/installation` | any app |  | Installation |
| GET | `/api/v1/knowledge` | `read.knowledge` | `ref`, `q`, `app`, `limit` | Knowledge |
| PUT | `/api/v1/knowledge` | `write.knowledge` | JSON body | Put Knowledge |
| POST | `/api/v1/knowledge/delete` | `write.knowledge` | JSON body | Delete Knowledge |
| POST | `/api/v1/llm/{use}` | `write.llm` | `use`*, JSON body | Llm |
| GET | `/api/v1/me` | any app |  | Me |
| GET | `/api/v1/notebooks` | people only |  | Notebooks |
| GET | `/api/v1/notebooks/file` | people only | `path`* | Notebook File |
| GET | `/api/v1/notifications` | `write.notifications` |  | Notification Settings |
| POST | `/api/v1/notifications` | `write.notifications` | JSON body | Notify |
| POST | `/api/v1/notifications/resolve` | `write.notifications` | JSON body | Resolve |
| GET | `/api/v1/objects` | people only |  | Offered |
| GET | `/api/v1/people` | `read.people` |  | People |
| GET | `/api/v1/queue` | people only |  | Queue |
| GET | `/api/v1/results` | `read.results` | `subject`, `app`, `kind`, `under`, `group`, `limit`, `cursor` | Results |
| PUT | `/api/v1/results` | `write.results` | JSON body | Put Results |
| GET | `/api/v1/results/history` | `read.results` | `subject`*, `app`, `kind`, `after`, `limit` | Result History |
| GET | `/api/v1/runs` | `read.runs` | `app`, `status`, `subject`, `by`, `limit` | Runs |
| PUT | `/api/v1/runs` | `write.runs` | JSON body | Put Runs |
| GET | `/api/v1/schedules` | `read.schedules` | `app` | Schedules |
| PUT | `/api/v1/schedules` | `write.schedules` | `app`, JSON body | Put Schedules |
| POST | `/api/v1/series` | `read.series` | JSON body | Series Batch |
| PUT | `/api/v1/series` | `write.series` | JSON body | Put Series |
| POST | `/api/v1/series/retire` | `write.series` | JSON body | Retire Series |
| PUT | `/api/v1/series/runs` | `write.series` | JSON body | Put Series Runs |
| GET | `/api/v1/signals` | `read.signals` | `q`, `app`, `subject`, `result`, `limit`, `cursor` | Signals |
| GET | `/api/v1/signals/{signal_id}` | `read.signals` | `signal_id`* | Signal |
| GET | `/api/v1/signals/{signal_id}/runs` | `read.series` | `signal_id`*, `limit` | Run List |
| GET | `/api/v1/signals/{signal_id}/series` | `read.series` | `signal_id`*, `start`, `end`, `step`, `run`, `runs` | Series |
| GET | `/api/v1/signals/{signal_id}/value` | `read.series` | `signal_id`*, `agg`, `window` | Value |
| GET | `/api/v1/todos` | any app | `app`, `state` | App Todos |
| POST | `/api/v1/todos` | any app | `app`, JSON body | Put Todo |
| POST | `/api/v1/todos/close` | any app | `app`, JSON body | Close Todos |
| GET | `/api/v1/tools` | people only |  | Tools |

`*` marks a required parameter.
