# The Assistant in Desk

Desk › **Assistant** is where each person talks with a language model. Each
person keeps many chats, each on its own subject: a question about the plant ("plot FIC-101
yesterday", "which loops need attention today?") or about how the platform works. Messages stay
between people.

**Platform use only**: the assistant helps with PlantCraft and the plant, in
Desk and in the side panel. It declines anything else (translating or writing general texts,
general knowledge) in one sentence and says what it can do instead; in the side panel it keeps to
the page and the task the person chose.

It is off until an administrator adds a provider in **Setup › Language models** and a default
model is chosen (the first model that answers its test becomes it); the Assistant's line in
**Models by use** may pick another model or turn it off. Until then its button is dimmed and
an administrator's click opens that page. Providers: the company's own
or a local one: any OpenAI-compatible server such as vLLM, Ollama or LM Studio, or Anthropic's
API). `PLANTCRAFT_LLM=off` forbids models in the whole installation, and a public demo never
uses one.

## Turn it on

The assistant is off in a new installation: nothing leaves the plant's network until an
administrator chooses a model. To turn it on:

1. Sign in as an administrator and open **Setup › Language models** (Desk › Assistant shows the
   button when it is off).
2. Add a provider: a model on your own machines (any OpenAI-compatible server such as Ollama,
   vLLM or LM Studio), the company's own endpoint, or Anthropic's API with a key.
3. Press **Test**. The first model that answers becomes the default.
4. Optionally, in **Models by use**, pick another model per use (the Assistant, the Help, the
   apps' own uses) or turn one off.

The assistant then answers in Desk › Assistant and in the side panel of every page, as the
person who asks, reading only what that person may open. `PLANTCRAFT_LLM=off` in `.env` keeps
models off in the whole installation, whatever Setup says. The public demo shows recorded chats
only: its visitors never reach a model.

## What the model can read

The model has no database access. It reads the plant through the same read-only tools as the
MCP server (`plantcraft/assistant_access/mcp.py`, [assistant-access.md](assistant-access.md)):
search and read assets, asset types, signals, values and history, the apps' latest results and
their history, events, runs, follow-up actions and the texts the apps wrote for assistants.

- **As the person who asks.** Each tool call is a request to API v1 inside the process
  (`httpx.ASGITransport`, never the network), with a token issued for that person at that moment.
  A person who lost access, or was turned off, stops at once.
- **Only the apps the person may open.** Results, events, runs and texts published by an app the
  person may not open are taken out of every tool answer (`mcp.only_apps`). The MCP server does
  the same since 2026-10-23.
- **Nothing writes.** The tools only read; the only thing written is the chat itself.
- **Audited.** Each tool call is in the audit log (`assistant.tool`, with the chat and the
  arguments), as the MCP server's are (`mcp.tool`).

## Tools the apps add

An app gives the assistant a read-only tool of its own
without a change to PlantCraft. It declares the tool in its `app.toml` and serves it under its
prefix; PlantCraft lists it to the model as `<app id>_<id>` beside its own tools, in Desk's
assistant, the side panel and the MCP server (`plantcraft/assistant_access/app_tools.py`).
Desk's assistant also names the offered app tools in its instructions and tells the model to
search them before it answers "there is none" or gives general advice: in the first evaluation
(2026-10-27, 40 questions on the demo plant's documents, gpt-5-nano) the model called the
documents' tool on only 13 questions, though it cited the right document every time it did.
Write the tool's description as when to use it (which questions), not only what it holds.

```toml
[[contributes.assistant.tools]]      # plantcraft-sdk 0.61.0
id = "search_documents"              # the model sees doccraft_search_documents
title = "Search the plant documents" # the step the person reads
description = "The plant's manuals and guides: causes, procedures, limits. Cite what you use."
reads = "Passages of the documents the person may open."
prefetch = "query"                   # plantcraft-sdk 0.73.0: called with each question
[[contributes.assistant.tools.args]] # text, integer, boolean or ref (asset:<id>, doc:<id>)
key = "query"
title = "What to find"
required = true
```

- **Read with each question (`prefetch`).** A tool whose `prefetch` names one of its text
  arguments is called by PlantCraft with the person's question in it, as the person, before the
  model answers (not in a work that creates an object, nor for a message under 8 characters).
  The model starts from that answer as if it had called the tool itself (one step, "Search the
  plant documents", the same audit) and may still call it with other words. What it carried
  becomes a source only when the answer names it (its `ref`, `number`, `title` or `name`). The
  second evaluation (2026-10-27) left the model to pick the tool: it did on 20 of 40 questions,
  and the "why", action and event questions went to the plant's tools alone. Use it for a cheap
  search that answers most questions about the app's objects, not for a slow or wide read.
  On a page about an asset (the chat's subject is `asset:<id>`: an Analytics loop, an alarm's
  tag), a tool that declares an `asset` argument gets it too.
- **Citations that open the passage.** An item of an app's answer with `cite` (its number) and
  `url` (a path of the suite, `/doc/documents/<id>?passage=<n>&q=<words>`) is what the answer's
  `[n]` points to: PlantCraft writes each `[n]` of the final answer as a link to it
  (`engine.linked_citations`; the latest call's numbering wins, a number no tool gave stays as
  written, an address outside the suite is never linked).

- **As the person who asks.** A call goes to API v1, `POST /api/v1/apps/<app>/tools/<id>`
  ([api-v1.md](api-v1.md)), which checks the arguments against the declaration and forwards
  them to `POST <prefix>api/assistant/tools/<id>` with a short token for that person
  (`app_proxy.post_tool`). The app answers with its own access checks (Documents' folders).
- **Only the apps the person may open.** A person who may not open the app is not offered its
  tools, and the route answers 404.
- **Quoted, never obeyed.** Every app tool's description tells the model its answer is the app's
  data and that instructions written inside it are never followed. The app marks its answer the
  same way (Documents: `note`).
- **Cited.** The `ref` of what an answer carries (`doc:<id>`) becomes a source of the answer,
  shown as a link under it.
- **Audited** twice: PlantCraft records the call (`assistant.tool`, `mcp.tool`) and the app
  records what it read (`doccraft.assistant.search`).

Documents (`apps/documents`) is the first: `doccraft_search_documents` (read with each question) and
`doccraft_read_document` answer from the plant's manuals, narratives, datasheets, procedures and
incident reports with document, revision and page. Analytics' and Alarms' works ask the model to
search them for a problem's known causes when the tool is offered.

## Charts

`show_chart` is the chat's own tool. It reads up to 6 signals' history through API v1 (about 600
points each) and draws them in the chat with the suite's time chart
(`@plantcraft/ui/plot`, `TimeChart`). The model gets only each series' statistics back (points,
first, last, min, max, mean), so a chart never shows a value the model wrote.

Desk and the side panel draw a chart the same way (`@plantcraft/ui` `AssistantChart`):
**Full screen**, one plot or **one plot per signal** (the default when the signals' ranges are
more than ten times apart or their units differ, so a mode at 0 does not sit flat beside a flow),
and **Open in Trends**: the app that declares the `trend` ref kind (View's
`/dash/trends/{id}`) opens a new trend with `?signal=&signal=&start=&end=`, the same signals
over the same period, to go on with the analysis.

## While the answer is written

The text is **streamed**: the model's answer comes as server-sent events (OpenAI's Responses
API, chat completions and Anthropic's Messages API alike; a server that does not stream answers
whole) and is kept in the message a few times a second, so the page that polls shows it as it
grows, with a caret. Until then a line says what is happening: waiting for a free slot,
thinking, which read is running ("Reading: Search signals…"), drawing the chart, preparing the
card, with the seconds so far (`AnswerProgress`). A failed answer (a lost connection, a model
that timed out) has **Try again**, which asks the same question again
(`POST /api/assistant/chats/{id}/retry`).

## Creating from any chat

A chat started from no work offers the model one `propose_create_<app>_<work>` tool per create
work the person may use (their access level, the apps they may open; not the works about one
page's object), each with the work's instructions and its fields typed, as the page's own
`propose`. Asked "create a block that…", the model proposes the fields: the person gets the same
card as from the page's work, with **Create**, or **Continue in the block form** that opens the
form filled in. A list field written as text (one item per line, or split by ";") or as an object
of name to description is read as a list. A proposal the check refuses shows as a failed
**Prepare the card** step with why. The model never writes the object as text to copy.

## What a person sees

- The list of their chats: their own groups first (by name), then today, the last 7 days and
  older, a **New chat** button and three views: **Chats**, **Archived** and **Shared with me**.
- Each chat's menu: rename, put in a group (or move it to another), share, copy its link, copy
  its reference, archive (or bring it back) and delete. Groups and the archive are the person's
  own; nobody else sees them.
- **Share** works like a dashboard's: everyone in the workspace, or chosen people and groups.
  Whoever it is shared with reads the chat (read-only, with its owner's name) and can
  **Continue in a copy**, a chat of their own with the same messages. Sharing is audited
  (`assistant.chat_shared`).
- A chat is a ref (`chat:<id>`, "Assistant chat"): its reference `#[title](chat:12)` pasted in an
  action's About or in a message links to it, like a dashboard or a report, for whoever may
  read it.
- In each answer: the reads the model made (one line per tool call, open while it works), the
  answer in Markdown (lists, tables), the charts, the cards it proposed, its **Sources** and the
  model's name. A source is an object the model read successfully (an id it guessed and that
  answered 404 is not one); each links to its page: an asset to its page, a signal to a new
  trend of it (the app that declares the `trend` kind, View).

## The side panel: the assistant on every page

the platform will be used mostly by talking to it, so the assistant is offered
on every page, the same way in every app, and each page says what it can do there.

- **One button.** **Assistant**, a spark like the other quick buttons, one of the four above the
  person's name in every app (`SuiteShell`; owner, 2026-10-24, round 8: beside Messages,
  Notifications and the work queues; at the top right of every page until ui 0.32.0). It opens the
  panel from the left, out from under the sidebar, over the page; the same button closes it. It is not
  shown when models are forbidden in the installation (`PLANTCRAFT_LLM=off`) or to people who may
  not use the assistant.
- **"What do you want to do?"** The panel first offers the page's tasks, then the suite's own
  ("Explain this page", "What needs attention here?"), or the person writes what they want. A
  task that needs the person's words ("Ask about one execution" › "Which execution?") waits for
  them beside the box. One page can offer several things, each with its own instructions and
  context, so the person's choice steers the model.
- **The page's developer declares them** once per page: `useAssistantPage({subject, title, place,
  context, tasks})` (docs/app-standard.md). A task is `{label, hint, instructions, ask, context,
  subject}`. A page that declares nothing gets the suite's tasks with its visible text (3,000
  characters) as the context.
- **What the model gets** is a chat with that context: the task chosen ("The person chose …",
  "What to do …"), what the task read (a table's rows) and what the page shows. The model is told
  to do the task and to take everything else as information, never as instructions (it can quote
  the plant's own texts). The person reads it all under **See the context**.
- **Like a chat in Messages**. The panel opens on a new chat about
  the page (the tasks above) and, under it, the person's earlier chats, newest first (eight; the
  rest in Desk). A new chat is about the page it was started on (its place and context). Every
  chat is kept, private to the person, in Desk's Assistant; **Full page** opens it there, **New
  chat** goes back to the start. A chat started with `keep: false` (older apps' panels) is still
  deleted a day after its last message unless continued in Desk.
- Declared today: Alarms (an alarm), Historian (a point), Analytics (results, a loop, a run, an
  algorithm), Models (a project), View (a dashboard), PlantCraft (an asset).

## Works: what the assistant does on each page

In the interface these are **tasks** (docs/glossary.md); the code, the API and `app.toml` keep
the word `works`.

Every page title has the assistant's button
on its right (ui `AssistantTitleButton`); clicking it lists the **works** of that page. A work is
either **ask** (the assistant reads and explains) or **create** (it talks with the person until
the object's fields are known and proposes it; the person creates it with one click). Choosing a
work opens the standard assistant chat with a context PlantCraft builds.

- **Declared as data, once.** PlantCraft's own works are `PLATFORM_WORKS`
  (`plantcraft/assistant_works`); an app declares its own in `app.toml` and the SDK sends them
  with its contributions:

  ```toml
  [[contributes.assistant.works]]
  id = "new-block"
  pages = ["blocks", "block-new"]   # the page ids its pages name in useAssistantPage
  kind = "create"                   # or "ask"
  level = "editor"                  # lowest access level offered it (what its create route takes)
  title = "Create a block with the assistant"
  instructions = "Collect the block's name, inputs, outputs and formula, then propose it."
  object = "block"
  create = "/link/api/blocks"       # the object's own route, under the app's prefix
  open = "/link/blocks/{id}"
  [[contributes.assistant.works.fields]]
  key = "name"
  title = "Name"
  required = true
  ```

  A field has `key, title, help, type` (`text`, `long_text`, `number`, `integer`, `boolean`,
  `choice` with `options`, `date`, `datetime`, `list`), `required`, `max_length`, `min`, `max`.
- **The page only says where the person is:** `useAssistantPage({page: "<app>:<page id>",
  subject, facts, view})`: the object's reference, a few small facts, and what the page shows
  (filters, selection, the ids of the rows on screen), never whole tables. Facts and view weigh 8,000
  characters at most; beyond that the longest list is cut by halves, so a long table never
  refuses the chat.
- **The context (`assistant-context/1`)** is built by PlantCraft in fixed sections, each with a
  limit: `work` (what was chosen and its instructions, 2,000 characters), `place` (300),
  `subject` (the reference as the suite resolves it, and the facts, 3,000), `view` (2,000),
  `fields` (create works, 4,000), `person` (name and access level, 300). A cut says so and
  names the tool that reads the rest. The person reads it under **See the context**.
- **A create work never writes.** The model gets a `propose` tool with the work's fields;
  PlantCraft checks the proposal (`plantcraft_sdk.contributes.check_fields`) and answers the
  problems to the model, which asks the person. A sound proposal is shown as a card with the
  fields and **Create**; the click calls the work's `create` route with the person's session
  (same checks as the form), then `POST /api/assistant/chats/{id}/proposals` keeps the card's
  state. Audit: `assistant.proposed`, `assistant.proposal_created`,
  `assistant.proposal_discarded`.
- **Or it continues in the object's own form.** An object a person finishes where it is made (a
  block's code to test, an algorithm's diagram) names `form` instead of `create` (and no `open`).
  The card's button reads **Continue in the … form**: it keeps the fields for that page
  (session storage, ten minutes) and opens it; the page calls `takeAssistantDraft("<app>:<id>")`
  once, fills itself in and the person saves there, with the page's own checks. The card's state
  becomes `opened`.
- **Or an app offers one of PlantCraft's works on its pages** (SDK 0.39.0): creating an action
  from an alarm is PlantCraft's work, with PlantCraft's route; the app only names its pages.

  ```toml
  [[contributes.assistant.offers]]
  work = "new-action"     # a work of PlantCraft's (the table below)
  pages = ["alarm"]       # the app's page ids
  ```

  The work keeps its key (`processcraft:new-action`), level and route; the page's subject (an
  alarm, a signal) tells the model what the new object is about.
- **Each work its own context** (SDK 0.47.0): `context = ["code", "summary"]` keeps only those
  keys of the page's facts and view (empty: all of them); the place, the subject's reference and
  the person always go. A page may send more facts (a block's code, its inputs) than any one work
  needs: "Explain this block" takes the code, "Where is it used?" the uses and versions.
- **Works on the object on screen.** `create`, `open` and `form` may hold `{subject}`, the id of
  the chat's object (the last part of its reference: `block:linkcraft/rate` gives `rate`):
  "Help me change this block" continues in `form = "/link/blocks/{subject}/edit"`. With no object
  the proposal is refused.
- **What each page offers.** The menu
  never repeats the same questions everywhere. Every page has the suite's **Explain this page**
  (ui); the rest are the page's own works, in this pattern, so the apps read as one suite:

  | Page | Works |
  |---|---|
  | A list of objects (blocks, assets, actions) | **Find …** (the person says what) · **Help me create a new …** (where the person may create) · at most one judgement where the page is about one ("What should be done first?") |
  | One object (a block, an asset, an alarm) | **Explain this …** · **Help me change this …** (where it can be changed: its form, a new version) · **Make a new … from this one** · the object's own questions (plot it, why it is so, what to check) · **Help me create an action** where it is about the plant |
  | A result or a run | **Explain this result** · **Why did it come out so?** · **What should we verify?** |

  Titles start with a verb and say exactly what the answer is about; every question a page offers
  is a work (declared and evaluated), not a task in the page's code.
- **Who sees what.** `GET /api/assistant/works?page=` lists only the works of the person's level
  (a create work declares the level its route takes: an editor for shared objects, a viewer for
  their own); in a public demo visitors get none.
- **PlantCraft's works** (`plantcraft/assistant_works/platform.py`), page by page:

  | Page | Works |
  |---|---|
  | `processcraft:actions` | Help me create an action (editor) · What should be done first? · Find actions |
  | `processcraft:action` | Help me create an action · Explain this action · Suggest the next step |
  | `processcraft:calendar` | Help me add an event (anyone, to their own calendar) · What is coming up? |
  | `processcraft:notes` | Summarize the open note · Find in my notes (the open note's start and the titles listed only) |
  | `processcraft:todo` | What should I do first? · Which of these should be actions? |
  | `processcraft:notebooks` | Help me start an analysis · How do I read a signal in Python? |
  | `processcraft:assets` | Help me create an asset (admin) · What is missing in the tree? · Find an asset |
  | `processcraft:asset` | Help me create an action · How is this asset doing now? · Plot its main signals · Explain one of its signals · What did the apps conclude about it? |
  | `processcraft:desk-today` | Help me create an action · What needs my attention today? · Plan my day |
  | `processcraft:attention` | Help me create an action · What should I look at first? |
  | `processcraft:asset-types` | Which signal roles do the apps read? · Which type fits my equipment? |
  | `processcraft:help` | Find it in the help |
  | `processcraft:executions` | Which runs failed, and why? · Did every schedule run on time? |

  The apps' (each `app.toml`, 2026-10-26):

  | App | Pages and works |
  |---|---|
  | Analytics | `blocks`, `block-new`: Help me create a new block (its form) · Which block computes what I need? — `block`: Explain this block · Help me change this block (its next version, `{subject}`) · Make a new block from this one · Where is it used? — `algorithms`, `algorithm-new`: Help me design a new algorithm · Which algorithm judges what I need? — `algorithm`: Explain this algorithm · How do I read its result? · Which assets does it fit? · Design a new algorithm from this one — `schedules`: Which schedules found problems? · What is not monitored yet? — `schedule`: Explain this schedule · What did its last runs find? — `executions`: Which runs failed, and why? · What did the latest runs find? — `execution-group`: Explain this monitoring round · What changed since the last round? — `subject-history`: Explain this result · Why did it come out so? · How has it changed over time? — `run`: Explain this run · Why did it fail? · What should engineering verify? · Explain one of its methods — `loop`: its health · Plot its PV, SP and OP · What to check in the field · Explain one of its methods — `results`: Which need attention first? · What do the worst have in common? · Explain one result — `signal-quality`: Which signals have problems? · Explain one signal's quality. Offers Help me create an action on `loop`, `results`, `signal-quality`, `run` and `subject-history`. |
  | Historian | `points`: Which points need attention? · Find a signal — `point`: Explain this signal's behaviour · What was its average yesterday? · When was it last out of range? · Compare with another signal · Check its quality (and Help me create an action) — `sources`: Are all sources connected? · What does each source provide? |
  | Alarms | Help me create an alarm (a rule on one signal, `POST /alarm/api/rules`) on `rules`, `active`, `alarm` and `rule` — `active`: Which alarms first? · Are these one upset? — `alarm`: Why did it fire? · Plot its signal · What should the operator do? · Is it well set? · Explain one occurrence — `performance`: the load against the targets · Which alarms should we fix first? — `journal`: What happened in this period? · Find in the journal — `rules`: What is not alarmed yet? — `rule`: Explain this rule · Is it well set? Offers Help me create an action on `alarm` and `active`. |
  | View | `dashboards`: Which dashboard shows what I need? · Plan a new dashboard — `dashboard`: Explain this dashboard · What changed in the period? · Explain one card · What should it also show? — `reports`: Which reports are due next? · Plan a new report — `report`: Summarize it for the shift · What should it also show? — `trends`: Explain this trend · Which signals relate to these? |
  | Models | `models`, `model-new`: Help me design a new model · Which model fits my question? — `model`: Explain this model · Suggest a study · Help me change this model — `studies`: Which study answers my question? — `study`: What did this study find? · What should I try next? |

  No page keeps a task in its code: every question is a work, so Evaluate works asks each one.
- **In the interface (ui 0.48.0).** The button beside the title opens a menu: the page's works
  (create works marked **Creates**), then the page's tasks and the suite's, then **Ask something
  else**. A choice opens the side panel and starts the chat on it (`openPageAssistant({work})`).
  The card (`ProposalCard`) shows each field as an input of its type, editable; **Create** stays
  off until the required fields are filled, dates go out in UTC, and **Put aside** keeps the
  proposal unused. The proposal carries its card (`card`: fields and routes), so it draws itself
  wherever the chat is read again. After a creation the page hears `pc-assistant-created` (a window
  event with the work, object and id) and shows the new object.

## The Help

The model reads PlantCraft's guides (the user guide, how the suite works, concepts, setup) with
`read_help`: the list, the guides that mention some words with the lines around them, or one
guide. The person reads the same Help from their menu, one for the whole suite, with each app's
guides at the top. The apps' own guides reach the model through what the apps write for assistants
(`/api/v1/knowledge`).

## Evaluation: questions whose answer is known

Setup › Language models › **Evaluate** asks a fixed set of questions to the installation's model
(or a specialist's) with the assistant's own tools and permissions, as the administrator who runs
it, and checks each answer against a golden answer (`plantcraft/assistant_chat/evals.py`). The
golden answers are not written by hand: each run reads them from this installation's data, so
the cases fit the demo plant and a real one.

| Case | Golden answer | Passes when |
|---|---|---|
| Mean of a signal over a day | The mean of the recorded values of the first numeric signal on its newest day with data | A number in the answer is within 2 % of the day's range |
| Maximum of a signal over a day | The maximum recorded value | Within 10 % of the range (the model reads about 600 averaged points) |
| Chart of a signal | That signal, that day | A chart of that signal was drawn |
| Yesterday's average of a signal | The mean of the first numeric signal's values over yesterday (UTC), asked as "yesterday" | Within 2 % of that day's range |
| A time series of the last 24 hours | That signal, asked in words ("how it moved over the last 24 hours") | A chart of that signal was drawn |
| Counting assets of a type | The number of assets of the type that has the most, subtypes included | The answer has that number |
| The platform's installed apps | The names of the apps installed here | Every name is in the answer |
| An Analytics block, identified | A block from Analytics' explanations, by its title | The model read the apps' explanations and named the block or its id |
| An app's results in alarm | How many results of one app and kind are in alarm now (1 to 20) | The answer has that number |
| A tag that does not exist | `XQ-4242.PV` does not exist | The answer says it found no such signal and draws nothing |
| Results of an app the person may not open | Nothing of the app with the most results | None of its result summaries appears, and the answer says it found nothing |
| A request outside the platform | A translation is declined | The answer does not translate, says it helps with the platform and draws nothing |

Each case shows the question, the golden answer, the model's answer, the reads it made and why
it passed or failed; the last 50 runs are kept (`assistant_evals`). Checks read the text and what
the model did; no second model judges the first. Run it after changing the model, its provider
or a specialist's instructions.

### Evaluate works: each work as its page asks it

"run the model with the context the application adds from the person's
choice, and see whether it can read that context and whether the context is enough".
**Evaluate works** (`plantcraft/assistant_chat/work_evals.py`) makes one case per work offered
to an administrator, PlantCraft's and the installed apps':

- **The same start as the button beside the title.** The question is the work's title, as the
  menu sends it (a work that first asks something gets a short answer: "A water tank whose level
  is controlled by an inlet valve"). The chat carries the work, the page's id and a subject read
  from this installation (an asset with signals, a loop, a signal, an alarm's signal, a run, an
  action), and PlantCraft builds the context exactly as for a person (`_page_context`).
- **A create work's question gives the fields** ("Title: Check the valve stiction of FIC-101.
  Priority: high...") and asks to propose at once, so one answer is enough.
- **Simple checks, for a modest model.** An ask work passes when the answer has some sentences,
  read the plant with at least one tool, names the page's subject and does not say it could not
  find it. A create work passes when the model called `propose` with fields PlantCraft accepts
  and the card carries what was asked (the title's key word, the priority).
- **What a person judges.** Each case keeps the context sent, the reads, the answer and the card
  proposed, so whether the context was enough can be read case by case. A work whose page is
  about an app's own object the platform does not list (a block, a dashboard, a report) is left
  out, and the run names it.

## Limits

| Setting | Default | What it does |
|---|---|---|
| `PLANTCRAFT_ASSISTANT_WORKERS` | 4 | Answers written at once in a server process; more wait in a queue ("Waiting for a free slot") |
| `PLANTCRAFT_ASSISTANT_DAILY` | 300 | Answers a person gets per day |
| One at a time | | A person has one answer being written at a time |
| Tool rounds | 8 | Rounds of tool calls before the model answers with what it read |

The limit that matters most is the model server itself: each answer takes from seconds to tens of
seconds, whatever the number of workers.

## Profiles

A chat answers as **Assistant** (the installation's default model) or as an active specialist
with a model (Users › Specialists): its subject and instructions are added to the model's
instructions. Specialists no longer answer in Messages' new conversations; their older
conversations stay, and the `/api/v1/assistant` routes stay for apps that still vendor
`@plantcraft/ui` 0.26 or older.

## API

Session routes, each person's own chats only (`plantcraft/api/routers/assistant_chat.py`):

| Route | What |
|---|---|
| `GET /api/assistant` | `{available, allowed, reason, can_set_up, profiles, daily_limit, chats, archived, shared}` (`chats`: not archived; `shared`: others' chats shared with the person) (`can_set_up`: the person is an administrator) |
| `GET /api/assistant/works?page=` | `{page, works}`: the works offered this person on `<app>:<page id>`, create works first (`{key, kind, title, hint, ask}`, and for create `{object, fields, create, open}`) |
| `POST /api/assistant/chats` | `{text, profile?, ref?, place?, context?, keep?, work?, page?}`: a new chat and its first question; with `work` (`<app>:<id>`) and `page` (`{page, subject, facts, view}`) PlantCraft builds the context (404: work not offered to the person; 422: not on this page); 409 without a model or while an answer is being written, 429 past the daily limit |
| `POST /api/assistant/chats/{id}/proposals` | `{message_id, index, state: created\|discarded, ref?, href?}`: what the person did with a proposal's card |
| `GET /api/assistant/chats/{id}?after=` | The chat and its messages after `after`, plus any still being written; also for a person it is shared with (read-only) |
| `POST /api/assistant/chats/{id}/messages` | `{text}`: the next question |
| `PATCH /api/assistant/chats/{id}` | `{title?, folder?, archived?}`: rename, put in one of the person's groups (`""` takes it out), archive or bring back |
| `PUT /api/assistant/chats/{id}/sharing` | `{grants}`: `everyone`, `user:<name>`, `group:<id>` (at most 50; `[]` stops sharing); owner only |
| `POST /api/assistant/chats/{id}/copy` | A chat shared with the person continued as their own copy |
| `POST /api/assistant/chats/{id}/retry` | The last question asked again after its answer failed (409 otherwise) |
| `DELETE /api/assistant/chats/{id}` | Deletes the chat and its messages |
| `POST /api/assistant/chats/{id}/keep` | A side panel's chat continued in Desk |
| `GET /api/assistant/evals` | The latest evaluation runs (administrators) |
| `POST /api/assistant/evals` | `{profile?}`: a new run, in the background (202; 409 while one runs) |
| `GET /api/assistant/evals/{id}` | One run with each case's result |

Tables: `assistant_chats`, `assistant_chat_messages`, `assistant_evals` (`plantcraft/assistant_chat`, layer 2).
