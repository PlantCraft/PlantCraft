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


def platform_works() -> list[AssistantWork]:
    return [AssistantWork.model_validate(item) for item in _WORKS]
