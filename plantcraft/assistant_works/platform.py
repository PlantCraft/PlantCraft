"""PlantCraft's own works, page by page (docs/assistant.md, "Works"; plan "Assistant on every
page"). Each page names itself in ``useAssistantPage({page:
"processcraft:<id>"})``; the create routes are the pages' own.

each page offers what fits it, not the same questions everywhere. "Explain
this page" is the suite's own on every page (ui); a list page adds finding and creating its
objects, an object page explaining, changing or copying that object and its own questions
(docs/assistant.md, "Works on each page"). Each work keeps only the page's facts it needs
(``context``)."""

from __future__ import annotations

from typing import Any

from plantcraft_sdk.contributes import AssistantWork

_WORKS: list[dict[str, Any]] = [
    # 1. Actions: create an action with the assistant, or ask about the actions on the board. An app
    # may offer "new-action" on its own pages (an alarm's: [[contributes.assistant.offers]]).
    {
        "id": "new-action",
        "pages": ["actions", "action", "asset", "attention", "desk-today"],
        "kind": "create",
        "level": "editor",
        "title": "Help me create an action",
        "hint": "Say what has to be done; the assistant asks the rest and fills in the form",
        "instructions": (
            "Help the person write a new action: what must be done (a short title, starting with "
            "a verb), why and how (description), its priority and due date, and the assets or "
            "signals it is about (refs such as asset:FIC-101; find them with search_assets). Ask "
            "only for what is missing, one or two questions at a time; suggest a priority from "
            "what they say. When the page is about something (the subject section: an alarm, a "
            "signal, an asset), the action is about it: put its ref in About and start the "
            "description from what the page shows. Before proposing, check with list_actions "
            "that the same action is not already open, and say so if it is."
        ),
        "object": "action",
        "fields": [
            {"key": "title", "title": "Title", "required": True, "max_length": 200},
            {"key": "description", "title": "Description", "type": "long_text", "max_length": 4000},
            {
                "key": "priority",
                "title": "Priority",
                "type": "choice",
                "options": ["low", "medium", "high", "critical"],
            },
            {"key": "due_at", "title": "Due", "type": "date"},
            {
                "key": "refs",
                "title": "About",
                "type": "list",
                "help": "Assets or signals, e.g. asset:FIC-101",
                "max_length": 400,
            },
        ],
        "create": "/api/actions",
        "open": "/actions/{id}",
    },
    {
        "id": "about-actions",
        "pages": ["actions"],
        "title": "What should be done first?",
        "hint": "Late, due soon, without an owner, critical",
        "context": ["shown", "overdue", "unowned", "rows", "view", "scope", "statuses"],
        "instructions": (
            "Rank the actions on this page (the view section: the board's filters and the rows on "
            "screen; read more with list_actions, as the person: only what they may see). Point "
            "out what is late or due soon, what has no owner and what is critical, most urgent "
            "first, with each action's number and title and why it comes there."
        ),
    },
    {
        "id": "find-actions",
        "pages": ["actions"],
        "title": "Find actions",
        "hint": "About an asset, a person, a subject",
        "ask": "Which actions? (about FIC-101, João's, the valve ones…)",
        "context": ["search", "scope", "statuses"],
        "instructions": (
            "Find the actions the person describes with list_actions (and search_assets for the "
            "assets they name): list each with its number, title, status, owner and due date, "
            "and say how to filter the board to keep them on screen."
        ),
    },
    # 2. One action: its state, history and what to do next.
    {
        "id": "about-action",
        "pages": ["action"],
        "title": "Explain this action",
        "hint": "Where it stands, its history and what is left",
        "instructions": (
            "Explain this action (the subject section): read it with list_actions, and the "
            "assets it is about with get_asset and their latest results. Say where it stands, "
            "who has it, what changed lately and what is left on its checklist."
        ),
    },
    {
        "id": "action-next",
        "pages": ["action"],
        "title": "Suggest the next step",
        "hint": "From its checklist and the plant now",
        "instructions": (
            "Suggest the next step for this action (the subject section): read it with "
            "list_actions and, for the assets it is about, their signals now (signal_value) and "
            "latest results. Give one concrete next step and why; say when the plant shows the "
            "action may already be done. The person changes the action themselves."
        ),
    },
    # 3. Calendar: create an event, or ask about what is coming.
    {
        "id": "new-event",
        "pages": ["calendar"],
        "kind": "create",
        "level": "viewer",
        "title": "Help me add an event",
        "hint": "Say what and when; the assistant fills in the event",
        "instructions": (
            "Help the person add an event to their own calendar: its title, when it starts and "
            "ends (in their local time; write ISO 8601 with the offset), whether it lasts all day, "
            "whether it repeats and until when, and notes. 'Tomorrow at 9' is a date: work it out "
            "from now, and say the day you understood."
        ),
        "object": "event",
        "fields": [
            {"key": "title", "title": "Title", "required": True, "max_length": 200},
            {"key": "start", "title": "Starts", "type": "datetime", "required": True},
            {"key": "end", "title": "Ends", "type": "datetime"},
            {"key": "all_day", "title": "All day", "type": "boolean"},
            {
                "key": "repeat",
                "title": "Repeats",
                "type": "choice",
                "options": ["daily", "weekdays", "weekly", "monthly"],
            },
            {"key": "until", "title": "Until", "type": "date"},
            {"key": "notes", "title": "Notes", "type": "long_text", "max_length": 2000},
        ],
        "create": "/api/desk/events",
    },
    {
        "id": "about-calendar",
        "pages": ["calendar"],
        "title": "What is coming up?",
        "hint": "Clashes, what is due, what needs preparing",
        "instructions": (
            "Answer about the person's calendar from what the page shows (the view section: the "
            "period and the items on screen) and their actions (list_actions). Point out clashes, "
            "what is due and what needs preparing, soonest first."
        ),
    },
    # 4-6. Notes, To-do, Notebooks: ask only (owner: no work of their own for now).
    {
        "id": "about-notes",
        "pages": ["notes"],
        "title": "Summarize the open note",
        "hint": "Its points, and the assets and actions it names",
        "context": ["open"],
        "instructions": (
            "Summarize the note open on the page (the view section) in a few points, then read "
            "the assets, signals or actions it mentions with your tools and say what they show "
            "now. The notes are private: use only what the page gives. With no note open, say "
            "so and offer to find one."
        ),
    },
    {
        "id": "find-notes",
        "pages": ["notes"],
        "title": "Find in my notes",
        "hint": "Among the notes listed",
        "ask": "What are you looking for?",
        "context": ["search", "listed", "notes"],
        "instructions": (
            "Find what the person asks among the notes the page lists (the view section: their "
            "titles and the search). Name the notes that may hold it and say what to search for "
            "on the page to narrow them; you see only titles and the open note."
        ),
    },
    {
        "id": "about-todo",
        "pages": ["todo"],
        "title": "What should I do first?",
        "hint": "Today's to-dos, ranked, and what can wait",
        "instructions": (
            "From the to-dos on the page (the view section: the list open and its to-dos, with "
            "due dates), help the person choose what to do first and what can wait, in a short "
            "ranked list with the reason for each."
        ),
    },
    {
        "id": "todo-actions",
        "pages": ["todo"],
        "title": "Which of these should be actions?",
        "hint": "To-dos someone else should do, or the plant needs tracked",
        "context": ["items", "list"],
        "instructions": (
            "Point out which of the person's to-dos (the view section) should become actions: "
            "work for someone else, or about the plant and worth tracking. Check with "
            "list_actions that no action already covers them, and say the title each would have."
        ),
    },
    {
        "id": "about-notebooks",
        "pages": ["notebooks"],
        "title": "Help me start an analysis",
        "hint": "The first cells for what you want to study",
        "ask": "What do you want to analyse?",
        "instructions": (
            "Help the person start an analysis in the suite's notebooks (JupyterLite, in the "
            "browser): find the signals or assets they mean (search_signals, search_assets), "
            "then give the first short code cells to read them with the notebook kit and plot "
            "them (read_help for the kit's functions), and the next step of the analysis."
        ),
    },
    {
        "id": "notebook-kit",
        "pages": ["notebooks"],
        "title": "How do I read a signal in Python?",
        "hint": "The notebook kit, with a cell to paste",
        "instructions": (
            "Explain how to read the plant's signals and assets in a notebook with the suite's "
            "kit (read_help for its functions): a short code cell that reads one real signal of "
            "this plant (pick one with search_signals) over the last day and plots it."
        ),
    },
]


_WORKS += [
    # 7. Assets: create an asset with the assistant, or ask about the tree and how it is organized.
    {
        "id": "new-asset",
        "pages": ["assets"],
        "kind": "create",
        "level": "admin",
        "title": "Help me create an asset",
        "hint": "Say what it is and where it sits; the assistant fills in the record",
        "instructions": (
            "Help an admin add an asset to the plant's tree: its tag as people write it (FV-2001), "
            "a name if it differs, its type (an id from list_asset_types, such as unit, area or "
            "equipment), the asset it sits inside (its id; find it with search_assets) and a short "
            "description. Before proposing, check with search_assets that it is not already in "
            "the tree, and say so if it is. The types the parent's type usually holds come first."
        ),
        "object": "asset",
        "fields": [
            {"key": "asset_id", "title": "Tag", "max_length": 128, "help": "e.g. FV-2001"},
            {"key": "name", "title": "Name", "required": True, "max_length": 120},
            {
                "key": "kind",
                "title": "Type",
                "required": True,
                "max_length": 64,
                "help": "A type id: unit, area, equipment, or one created in Types",
            },
            {
                "key": "parent_id",
                "title": "Inside",
                "max_length": 128,
                "help": "The id of the asset it sits inside; empty puts it at the top",
            },
            {"key": "description", "title": "Description", "type": "long_text", "max_length": 600},
        ],
        "create": "/api/assets",
        "open": "/assets/{id}",
    },
    {
        "id": "about-assets",
        "pages": ["assets"],
        "title": "What is missing in the tree?",
        "hint": "Assets without signals, records missing attributes",
        "instructions": (
            "Answer about the plant's asset tree: the filters on screen are in the view section. "
            "Read it with search_assets, get_asset and list_asset_types. Say how it is organized "
            "(sites, units, areas, equipment), what looks out of place or incomplete (assets with "
            "no signals, records missing attributes), and suggest how to improve it."
        ),
    },
    {
        "id": "find-assets",
        "pages": ["assets"],
        "title": "Find an asset",
        "hint": "By tag, name or what it does",
        "ask": "Which asset? (a tag, a name, what it does)",
        "context": ["search", "type"],
        "instructions": (
            "Find the assets the person describes with search_assets (and get_asset for the best "
            "matches): list them with tag, name, type and where they sit in the tree, best match "
            "first."
        ),
    },
    # 8. One asset: how it is now, its main signals, what the apps concluded.
    {
        "id": "asset-now",
        "pages": ["asset"],
        "title": "How is this asset doing now?",
        "hint": "Its signals now and the apps' latest results",
        "instructions": (
            "Read this asset (the subject section) with get_asset, its signals now with "
            "signal_value and the apps' latest results about it with latest_results, and say how "
            "it is doing, most important first."
        ),
    },
    {
        "id": "asset-plot",
        "pages": ["asset"],
        "title": "Plot its main signals",
        "hint": "The last day, process signals first",
        "instructions": (
            "Draw this asset's main signals (up to 6, the process ones first) over the last 24 "
            "hours: read them with read_series, show them with show_chart, and describe what "
            "they show. If the person names another period or signals, use those."
        ),
    },
    {
        "id": "asset-signal",
        "pages": ["asset"],
        "title": "Explain one of its signals",
        "hint": "Its behaviour over the last day",
        "ask": "Which signal?",
        "instructions": (
            "Read the signal of this asset the person names (get_asset lists its signals by role) "
            "over the last 24 hours with read_series, show it with show_chart and explain its "
            "behaviour: its level, how it moved, anything unusual and when."
        ),
    },
    {
        "id": "asset-conclusions",
        "pages": ["asset"],
        "title": "What did the apps conclude about it?",
        "hint": "Each app's latest result and since when",
        "instructions": (
            "Read the apps' latest results (latest_results, result_history) and recent events "
            "(recent_events) about this asset, and summarize what each app concluded and since "
            "when, pointing out where they agree or disagree."
        ),
    },
]


_WORKS += [
    # Owner, 2026-10-25 (evening): the assistant on more pages. Ask works, each about what its
    # page shows.
    {
        "id": "today",
        "pages": ["desk-today"],
        "title": "What needs my attention today?",
        "hint": "Alarms, late actions and what the apps flag",
        "instructions": (
            "Say what needs this person's attention today, most urgent first: their actions that "
            "are late or due today (list_actions), what the apps flag as warning or alarm "
            "(latest_results) and the alarms and events of the last hours (recent_events). Keep "
            "it to a short list, each item with what to open next."
        ),
    },
    {
        "id": "about-attention",
        "pages": ["attention"],
        "title": "What should I look at first?",
        "hint": "The items on screen, ranked, with the reason",
        "instructions": (
            "Rank the items that need attention (the view section lists the ones on screen; read "
            "more with latest_results and recent_events): what to look at first and why, and the "
            "check to make for each. Say plainly when they look like one problem seen by several "
            "apps."
        ),
    },
    {
        "id": "about-types",
        "pages": ["asset-types"],
        "title": "Which signal roles do the apps read?",
        "hint": "By type, and the roles often missing",
        "instructions": (
            "Explain the plant's asset type catalog (list_asset_types; the subject section names "
            "the type open on screen, if any): what each type is for, how they inherit, and which "
            "signal roles the apps read from them. Point out types with no assets "
            "(search_assets) and roles that are often missing."
        ),
    },
    {
        "id": "type-choose",
        "pages": ["asset-types"],
        "title": "Which type fits my equipment?",
        "hint": "Or what a new type should hold",
        "ask": "What is the equipment?",
        "instructions": (
            "Say which type of the catalog (list_asset_types) fits the equipment the person "
            "describes, and which signal roles to fill so the apps read it. If none fits, say "
            "which type to inherit from and the attributes and roles the new type should add."
        ),
    },
    {
        "id": "today-plan",
        "pages": ["desk-today"],
        "title": "Plan my day",
        "hint": "Calendar, actions and to-dos in one order",
        "instructions": (
            "Plan the person's day: their actions due or late (list_actions), what the apps flag "
            "(latest_results) and the alarms of the last hours (recent_events). Give a short "
            "ordered plan for the morning and the afternoon, each item with what to open."
        ),
    },
    {
        "id": "about-help",
        "pages": ["help"],
        "title": "Find it in the help",
        "hint": "How a page or a concept of the suite works",
        "ask": "What do you want to know?",
        "instructions": (
            "Answer the person's question from the suite's Help (read_help; the view section says "
            "which app's help is open): a short answer, then the help page to read for more."
        ),
    },
    {
        "id": "about-executions",
        "pages": ["executions"],
        "title": "Which runs failed, and why?",
        "hint": "The latest problems first",
        "instructions": (
            "Find the apps' runs that failed or ended with warnings (list_runs; the view section "
            "lists what is on screen): for each, the app, when, and why it failed as its "
            "messages say, and what to do about it. Most recent first; say plainly when none did."
        ),
    },
    {
        "id": "executions-late",
        "pages": ["executions"],
        "title": "Did every schedule run on time?",
        "hint": "Schedules that missed a run",
        "context": ["runs", "schedules"],
        "instructions": (
            "Check the apps' schedules against their runs (list_runs): which did not run when "
            "expected, since when, and the likely reason (an app down, a failed run)."
        ),
    },
]


# The setup guide (owner, 2026-11-03: "a robot beside the screen that helps with the
# configuration; the person asks, it answers and configures"): one work per step of
# plantcraft/setup_guide.py on the guide's own page. The page's facts carry the step's state
# (what is set, what failed); a step that writes ends in a card the person applies.
_GUIDE = (
    "You are PlantCraft's setup guide: a friendly robot beside the screen that walks an "
    "administrator through setting up a new installation, one step at a time. Be brief and "
    "warm, one or two short paragraphs, and ask one question at a time. Use the facts of this "
    "page (the step's state: what is set already, what failed) and never ask what they show. "
    "Say exactly what to click when the person has to do something on a page (the step's page "
    "is in the facts). When the step is done, say so in one line and that the guide moves on. "
)
_WORKS += [
    {
        "id": "guide-basics",
        "pages": ["setup-guide"],
        "kind": "create",
        "level": "admin",
        "title": "Set the basics with me",
        "hint": "The plant's time zone and your language",
        "instructions": _GUIDE
        + (
            "This step: the plant's time zone (an IANA name such as America/Sao_Paulo, "
            "Europe/Berlin or Asia/Kolkata) and the language the person reads PlantCraft in. "
            "Ask where the plant is (a city or country is enough) unless the facts already show a "
            "chosen zone; when the facts say the installer fixed it, say it is changed on the "
            "server and the step is done. Offer only the languages in the facts. Then propose "
            "the basics; the person applies them with one click."
        ),
        "object": "basics",
        "fields": [
            {
                "key": "time_zone",
                "title": "Time zone",
                "required": True,
                "max_length": 64,
                "help": "An IANA zone, e.g. America/Sao_Paulo",
            },
            {
                "key": "language",
                "title": "Language",
                "type": "choice",
                "options": ["en", "pt-BR", "es"],
            },
        ],
        "create": "/api/setup-guide/basics",
    },
    {
        "id": "guide-connection",
        "pages": ["setup-guide"],
        "kind": "create",
        "level": "admin",
        "title": "Connect the plant with me",
        "hint": "OPC UA, PI Web API or a file; read only",
        "instructions": _GUIDE
        + (
            "This step: connect PlantCraft to the plant's data, read only. Ask what the plant has: "
            "an OPC UA server (its address, opc.tcp://host:4840, and whether it needs a user), a "
            "PI Web API (https://server/piwebapi) or a CSV file on the server. When the facts list "
            "a source that failed, explain the likely cause from its detail (a wrong address, a "
            "firewall, a certificate to trust on Sources) before proposing another. Then propose "
            "the source with a short name; once applied, the guide tries the connection. A "
            "password is never written in the chat: the person types it on Sources › Edit."
        ),
        "object": "source",
        "fields": [
            {"key": "name", "title": "Name", "required": True, "max_length": 120},
            {
                "key": "kind",
                "title": "Kind",
                "type": "choice",
                "required": True,
                "options": ["opcua", "pi_web_api", "csv"],
            },
            {
                "key": "endpoint",
                "title": "Address",
                "required": True,
                "max_length": 500,
                "help": "opc.tcp://host:4840, https://server/piwebapi or a file path",
            },
            {"key": "username", "title": "User", "max_length": 200},
        ],
        "create": "/api/setup-guide/connection",
    },
    {
        "id": "guide-documents",
        "pages": ["setup-guide"],
        "title": "Which documents should I add?",
        "hint": "P&IDs, loop lists, data sheets, manuals",
        "instructions": _GUIDE
        + (
            "This step: add the plant's documents to PlantCraft Documents. Explain which help the "
            "most (the P&IDs and the loop or instrument list first, then data sheets and "
            "operating manuals), that scanned drawings are read too, and how: Documents › Add, "
            "drop the files, and file each one under its unit. Say that confidential documents "
            "keep their own access. Use search_documents to say what is there already."
        ),
    },
    {
        "id": "guide-assets",
        "pages": ["setup-guide"],
        "title": "Build the asset tree with me",
        "hint": "From the source's tags and the documents",
        "instructions": _GUIDE
        + (
            "This step: build the asset tree on Assets › Import. Explain the way that takes "
            "minutes: Draft from tags, pick the source just connected, and PlantCraft reads its "
            "tags as ISA-5.1 (FIC-101 is a flow loop with its PV, SP and OP), places each loop in "
            "its unit with the documents when there are any, and opens the draft for review; "
            "the person leaves out what is wrong and clicks Apply (an import can be undone). A "
            "spreadsheet of tags works the same. Use search_signals to say how many tags look "
            "like loops."
        ),
    },
    {
        "id": "guide-start",
        "pages": ["setup-guide"],
        "title": "What will each app do?",
        "hint": "Collect, monitor, draft alarms and dashboards",
        "instructions": _GUIDE
        + (
            "This step: each installed app takes its first step on the imported assets (the facts "
            "list the steps left). Explain in one line each what they do: the Historian collects "
            "the signals, Analytics starts monitoring the loops (its first round sets each loop's "
            "baseline), Alarms drafts rules that stay off until reviewed, View draws a dashboard "
            "per unit. The person runs them with the buttons in the guide."
        ),
    },
    {
        "id": "guide-people",
        "pages": ["setup-guide"],
        "kind": "create",
        "level": "admin",
        "title": "Invite someone with me",
        "hint": "Name, user name and access",
        "instructions": _GUIDE
        + (
            "This step: add the people who will use PlantCraft. Ask who (their name and the user "
            "name they sign in with) and what they do, and suggest the access: viewer for "
            "operators and managers who look, editor for engineers who change rules and "
            "dashboards, admin only for who runs the installation. Propose one person at a "
            "time; their password is set on Users after creating them. Say that the company's "
            "sign-in (Settings › Corporate sign-in) can replace passwords later."
        ),
        "object": "person",
        "fields": [
            {"key": "display_name", "title": "Name", "required": True, "max_length": 120},
            {"key": "username", "title": "User name", "required": True, "max_length": 60},
            {"key": "role", "title": "Role", "max_length": 120},
            {
                "key": "access_level",
                "title": "Access",
                "type": "choice",
                "required": True,
                "options": ["viewer", "editor", "admin"],
            },
        ],
        "create": "/api/users",
    },
    {
        "id": "guide-email",
        "pages": ["setup-guide"],
        "title": "How do I set up email?",
        "hint": "The mail server for notifications",
        "instructions": _GUIDE
        + (
            "This step, optional: the company's mail server, so notifications also go by email. "
            "Say what IT gives for it (the SMTP server, its port, 587 with STARTTLS usually, a "
            "user and password and the sender address) and where: Settings › Email, then Send a "
            "test. Notifications always reach Messages anyway."
        ),
    },
    {
        "id": "guide-help",
        "pages": ["setup-guide"],
        "title": "Ask the guide",
        "hint": "Anything about setting up the plant",
        "ask": "What would you like to know?",
        "instructions": _GUIDE
        + (
            "Answer the person's question about setting up PlantCraft (read_help for how a page "
            "works), and bring them back to the step that comes now (in the facts)."
        ),
    },
]


def platform_works() -> list[AssistantWork]:
    return [AssistantWork.model_validate(item) for item in _WORKS]
