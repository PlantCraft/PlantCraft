# Messages, specialists and actions

Decided by the owner on 2026-10-20 (post-MVP step 7): people and specialists talk in
**Messages**, follow-up **actions** live in PlantCraft, and **specialists** are robot users
configured in PlantCraft. Every app of the suite shows the same messages button in its sidebar
(`@plantcraft/ui`), which opens PlantCraft's Messages over the page, in a panel on the right,
without leaving the app; **Full page** opens `/messages`.

Since 2026-10-23 specialists answer in Desk's **Assistant** ([assistant.md](assistant.md)), where
each person keeps many chats with a language model; new conversations in Messages are between
people only. Older conversations with a specialist stay readable, and the specialist responder
below still answers the `/api/v1/assistant` routes of apps on `@plantcraft/ui` 0.26 or older.

## Concepts

- **Conversation**: two or more participants (people or specialists) and their messages. A
  conversation between two participants with no title is a *direct* one and is reused.
  A message can point at platform objects with references (`asset:FIC-101`,
  `signal:opc:FT-101.PV`, `action:12`, `run:linkcraft/abc`), written `#asset:FIC-101` in the
  text or picked in the composer; plain asset ids in the text become references too.
- **Specialist**: a workspace user of kind `specialist` with a profile: subject, instructions
  (its prompt), the apps whose published data it may read, and an optional language model
  (provider, model, endpoint, API key). It is **read-only**: it reads assets, the results,
  events and runs the apps publish in PlantCraft (API v1), and actions; it never writes
  anything but its own reply. It **answers only when messaged**: in a conversation with one
  person it answers every message; in a group only when mentioned (`@username`).
- **Language model off by default.** Until an administrator sets one up, every specialist
  answers from a script with what the apps published (status, summary and the method that
  limits each subject). An administrator saves **providers** in Settings > Language models
  (2026-10-22): each has a name, a format, an address, a key and the list of models it serves,
  and each model is tested when the provider is saved, and can be tested again from there. The
  same vendor may come more than once (two OpenAI keys, a local server beside a gateway). Two formats: the OpenAI chat completions API, which
  vLLM, Ollama, LM Studio, Azure OpenAI and most gateways speak (address with its `/v1`, e.g.
  `http://llm.company.local:8000/v1`; a key only if the server asks for one), and Anthropic's
  Messages API. One provider and model is the **installation's default**, and choosing it is
  what turns models on (no separate switch since 2026-10-25; with no default yet, the first model
  that answers its test becomes it). **Models by use**: each part of the suite that writes with a
  model (`assistant` today; apps will declare theirs) uses the default, a provider's model or
  nothing (`uses.<use>.source`: `default`, `provider`, `off`). Each specialist
  answers with the default, with a provider and model chosen for it, or from scripts
  (`model.source`: `installation`, `provider`, `off`; `own`, a model typed in the profile, is
  kept for profiles from before). The one connection of before becomes the provider `default`
  the first time the new version starts. `PLANTCRAFT_LLM=off` forbids models in the whole
  installation (the switch wins over every setting). Keys are stored in `specialist-keys.json`
  beside the database (mode 600; a provider's under `@provider:<id>`), never in the database
  and never returned by the API (only `api_key_set` and the last four characters).
- **Action**: a follow-up task: title, description, priority, owner (a person), due date,
  status (`open`, `in_progress`, `blocked`, `done`, `cancelled`, shown as **Archived**),
  references to what it is about and a checklist (items with their own owner and due date),
  with a history (created, changed, commented, checklist). `#asset:FIC-101` or `#user:ana` in
  the description or a comment comes back resolved in `mentions`; `user:` references open the
  person's page (`/people/<username>`). Creating an action or changing its
  status publishes an event (`action.created`, `action.status_changed`) with its references, so
  it shows in the asset's timeline. Apps open the form with a link:
  `/actions?new=1&ref=asset:FIC-101&title=...`.

## Interface API (session cookie)

Everyone signed in except dashboards-only accounts reads and writes messages. Actions: viewers
read and comment, editors create and change. Specialists: admins only.

### Who sees an action

Added 2026-10-23 (owner), modelled on Jira's assignee and team: an action goes to a person
(`owner`), a group (`group_id`) or both. A person sees the actions they own, the ones they
created, the ones assigned to one of their groups, and, when they lead a group (its
coordinator), everything owned by or assigned to the people and groups below it in the group
tree ([groups.md](groups.md)). An administrator sees every action, and so does the public demo's read-only visitor
(`PLANTCRAFT_PUBLIC_DEMO_USER`, the demo shows the team's follow-up). An action out of sight
answers 404 on every route; the home page counts, a person's page, the reference picker and
`GET /api/v1/actions` with a person's token follow the same rule (an app's service token reads
them all). The list's quick filters are `view=visible` (default), `mine`, `groups` and
`created`; `group=<id>` (repeatable) narrows to groups. Since the security review of
2026-10-26 the rule holds everywhere an action's title or state could show: a link to it
(`#action:42`, `GET /api/refs`) reads only "Action 42" for anyone else, and its events leave a
person's `GET /api/v1/events`, the asset's history and the assistant's `recent_events`. A
specialist in Messages answers the people of the conversation, so it reads only the actions they
all see and only the apps of its profile they all open.

### Messages

A group of people has its own conversation (2026-10-23, owner): its participants follow the group
(whoever joins the group finds it in Messages with the history read, whoever leaves stops
receiving it); deleting the group leaves it as an ordinary conversation. Starting a conversation,
a person can also choose a group, which chooses its people. `contacts` lists the groups with
their members.

| Route | Body | Answer |
|---|---|---|
| `GET /api/messages/contacts?ref=` | | `{people: Contact[], specialists: Contact[], suggested: string[], model_allowed: bool}` |
| `GET /api/messages/conversations` | | `{unread: int, items: Conversation[]}` |
| `POST /api/messages/conversations` | `{members: string[], title?, text?, ref?}` | `{conversation, message \| null}` (201) |
| `GET /api/messages/conversations/{id}?after=<message_id>` | | `{conversation, messages: Message[]}` |
| `POST /api/messages/conversations/{id}/messages` | `{text, ref?}` | `Message` (201) |
| `POST /api/messages/conversations/{id}/read` | `{message_id?}` | `{unread}` |
| `POST /api/messages/conversations/{id}/members` | `{members}` | `Conversation` (422 for a group's conversation) |
| `POST /api/messages/groups/{group_id}` | | the group's own `Conversation`, created the first time (members of the group only) |
| `GET /api/messages/references?q=` | | `RefOption[]` (assets, actions) |

```text
Contact      {username, display_name, role, kind: "person"|"specialist", subject?, model_on?}
ContactGroup {group_id, name, kind_label, members: string[] (without you), mine}
Conversation {conversation_id, title, display_title, is_group, group_id, has_specialist, unread,
              busy: string[]  (specialists writing a reply now),
              members: [{username, display_name, role, kind, busy}],
              last_message: {message_id, author, author_name, text, created_at} | null,
              created_at, updated_at}
Message      {message_id, conversation_id, author, author_name, author_kind, text,
              refs: [{ref, kind, id, kind_label, title, href, exists}],
              meta: {writer?: "script" | "<model label>" | "error", fallback?: bool},
              created_at}
RefOption    {ref, kind, kind_label, title, detail}
```

### Actions

| Route | Body | Answer |
|---|---|---|
| `GET /api/actions?status=&owner=&ref=&q=&view=&group=` | | `{items: Action[], statuses, priorities, people, groups, views, everything}` |
| `POST /api/actions` | `ActionDraft` | `Action` (201) |
| `GET /api/actions/{id}` | | `Action` with `history` |
| `PUT /api/actions/{id}` | `ActionDraft` + `status` | `Action` |
| `POST /api/actions/{id}/comments` | `{text}` | `Action` with `history` |
| `POST /api/actions/{id}/items` | `{text, owner?, due_at?}` | `Action` with `items` (201) |
| `PATCH /api/actions/{id}/items/{item}` | any of `{text, owner, due_at, done}` | `Action` with `items` |
| `DELETE /api/actions/{id}/items/{item}` | | `Action` with `items` |
| `GET /api/people/{username}` | | a person's profile and open actions; access for themselves and admins |
| `GET`, `PUT /api/me/profile` | `{display_name, role, profile}` | the signed-in person's own page |

```text
ActionDraft {title, description="", priority="medium", owner=null, group_id=null,
             due_at=null (YYYY-MM-DD), refs: string[] = []}
Action      {action_id, title, description, status, status_label, priority, priority_label,
             owner, owner_name, group_id, group_name, due_at, overdue, refs: [resolved ref as in Message],
             created_by, created_by_name, created_at, updated_at, completed_at,
             history?: [{kind: "created"|"changed"|"status"|"comment", text, actor,
                         actor_name, created_at}]}
statuses / priorities: [{id, label}];  people: [{username, display_name}]
```

### Specialists (admins)

| Route | Body | Answer |
|---|---|---|
| `GET /api/specialists` | | `{items: Specialist[], apps: [{application_id, name}], model_allowed, defaults: {provider, model}}` |
| `POST /api/specialists` | `SpecialistDraft` + `username` | `Specialist` (201) |
| `PUT /api/specialists/{username}` | `SpecialistDraft` | `Specialist` |
| `DELETE /api/specialists/{username}` | | `{removed}` (the account is deactivated; its messages stay) |
| `POST /api/specialists/{username}/test` | | `{ok, writer, text}` (one short model call, or why not) |
| `GET /api/language-models` | | `LanguageModels` |
| `POST /api/language-models/providers` | `ProviderDraft` | `LanguageModels` + `saved` + `tests` (201; each model tested; audited `language_model.provider_added`) |
| `PUT /api/language-models/providers/{id}` | `ProviderDraft` | `LanguageModels` + `saved` + `tests` (audited `language_model.provider_changed`) |
| `DELETE /api/language-models/providers/{id}` | | `LanguageModels` + `orphans` (the specialists that used it; audited) |
| `POST /api/language-models/providers/{id}/test` | `{model}` | `{ok, writer, text}` (one short call to that model; with no default yet, it becomes the default when it answers) |
| `PUT /api/language-models/settings` | `{provider_id, model, uses?}` | `LanguageModels` (empty provider_id: models off; audited `language_model.changed`) |
| `GET /api/language-model` | | `LanguageModel` (the default, in the shape of before) + `providers` |
| `PUT /api/language-model` | `{enabled, provider, name, endpoint, api_key?}` | `LanguageModel` (writes the provider `default`; kept for older clients) |
| `POST /api/language-model/test` | | `{ok, writer, text}` |

```text
SpecialistDraft {display_name, subject, instructions, apps: string[], active=true,
                 model: {source="installation"|"provider"|"own"|"off", provider_id="",
                         provider="anthropic"|"openai", name="", endpoint="",
                         api_key?: string|null}}
                 source "provider": provider_id of a saved provider, name one of its models
                 api_key: null keeps, "" clears, text sets (also for the language model)
Specialist      {username, display_name, subject, instructions, apps, active,
                 model: {source, enabled, ready, provider, provider_id, name, endpoint,
                         api_key_set, api_key_hint},
                 answers (replies written), last_answer_at, updated_at, updated_by}
LanguageModel   {enabled, provider, provider_id, provider_name, name, endpoint, api_key_set,
                 api_key_hint, ready, allowed (PLANTCRAFT_LLM), updated_at, updated_by}
ProviderDraft   {name, kind="openai"|"anthropic", endpoint="", models: string[] (1 to 30),
                 api_key?: string|null}
LanguageModels  {providers: [{provider_id, name, kind, kind_label, endpoint, models,
                 api_key_set, api_key_hint, ready, used_by: string[], updated_at, updated_by}],
                 settings: {enabled (a default is chosen), provider_id, model,
                 uses: {<use>: UseChoice}, allowed, updated_at, updated_by},
                 uses: [{use, label, description, app, choice: UseChoice, ready}],
                 kinds: [{id, label}], max_providers, tests?: {<model>: {ok, writer, text}}}
UseChoice       {source="default"|"off"|"provider", provider_id?, model?}
```

Profiles saved before `source` existed read as `own` when they had a model on and a key,
otherwise `installation`.

## API v1

`GET /api/v1/inbox` (a person's token, the cookie the apps already send):
`{unread_messages, open_actions, messages_url: "/messages", actions_url: "/actions"}`.
`open_actions` counts actions owned by the caller that are open, in progress or blocked. A
service token gets 403. The suite frame polls it for the badge of the messages button.

`GET /api/v1/actions?ref=asset:<id>` (people and service tokens; dashboards-only accounts get
403): the actions about an asset, open ones first, without their description and history. The
suite frame's follow-up panel (`FollowUp` in `@plantcraft/ui`) shows them on the asset's page
in every app (a loop in Analytics, a signal, the asset itself here), each linking to
`/actions/<id>`, with a **New action** button that opens `/actions?new=1&ref=…&title=…`.

## The assistant of an app (added 2026-10-21)

An app's page offers **Ask the assistant** beside its objects: a run that failed, a protocol, a
loop. The button (`AssistantButton` of `@plantcraft/ui`) opens a panel that lists the
specialists who can talk about the object (those reading its app first), the person's earlier
conversations about it, and starts a new one with the person's question (`/api/v1/assistant`,
`docs/api-v1.md`). Without any specialist the panel says so and links administrators to
People > Specialists.

The specialist answers from everything the platform knows about the object: its results, events
and actions, and what the app explained about it (`/api/v1/knowledge`: a protocol's meaning,
inputs, outputs and the instructions it gives an assistant; a run's report). Without a model the
scripted answer describes the object (status, summary and the opening of its explanation);
with a model the specialist also searches the explanations (`search_knowledge`) and the latest
runs (`recent_runs`). The conversation stays in Messages like any other.

An app can also give the assistant **a page of its own**, about everything it holds: the
subject is `app:<app id>` (`AssistantPanel` with `inline`), the specialists reading that app
are offered first and answer questions across its objects ("which loops are worst?") with
`list_attention`, `search_assets` and the other tools.

