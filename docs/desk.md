# Desk: each person's day

Desk is the suite's first screen (owner, 2026-10-23): each person's own workspace, with what
they have to do, what came to them and what they follow, arranged as they like. It is built
into the platform (same container, same database, served at `/`); PlantCraft's own pages
(Overview, Assets, Settings, People, Apps, System health, Backups, Updates) moved under `/admin` and the PlantCraft
entry is last in the list of apps. Actions, messages, groups and events stay platform data:
Desk reads them, it does not copy them.

## Pages

| Path | Page | What it holds |
| --- | --- | --- |
| `/` | Today | The greeting, the date and the time, then the person's widgets on the suite's card grid (below). |
| `/widgets` | Widgets | Every widget at every size it allows: the widget test page (not in the menu). |
| `/actions`, `/messages` | Actions, Messages | The platform's pages, now in Desk's menu. `/actions?view=mine` opens a quick filter. |
| `/calendar` | Calendar | FullCalendar (MIT) year, month, week, day and list; the title opens a month and year picker (round 8). A click or a drag on the calendar makes an event of the person's own (see Own events); dragging an action changes its due date. The apps' scheduled runs start hidden, an hour's runs as one entry; each feed an app keeps is a chip of its own (see What the apps put in Desk). `?date=2026-10-24` opens that day. |
| `/todo` | To-do | My day, Planned, All, Done, From apps and the person's lists and their groups' shared lists (see To-do). `/routines` leads here. `?view=planned`, `?view=apps`, `?list=3`, `?item=12` open a view, a list or a to-do. |
| `/notes` | Notes | The person's notes and those shared with them, pinned first, with a search (see Notes). `?note=4` opens one; `?event=event:12&title=…` opens a calendar event's note (made the first time). |
| `/team` | Team | How the person's groups are doing today and who can take what (see Team). `?group=all` shows every group at a glance (the default with more than one); `?group=u-100-operations` opens a group. |
| `/setup/calendars` | Settings › Calendars | Admins: calendar links on or off, and the servers allowed. |

## Today: the card grid

Today uses `WidgetBoard` from `@plantcraft/ui`, the board every Overview uses, on the shared
`CardGrid` (12 columns, the same row height and gap as View's dashboards, react-grid-layout).
**Customize** is a discreet text button; in edit mode a widget moves by its title, has a gear
for its settings (title, size, the widget's own fields, with a preview) and an X. Sizes are
fixed (owner, 2026-10-24): each widget has one to three, 1 to 3 rows high, and draws what fits.
"Add a widget" opens a window with the apps at the left and their widgets, previewed, at the
right. A widget marked `multiple` can be added more than once with other settings (two "My
actions": mine and my groups'). See [widgets.md](widgets.md).

Desk's widgets: `desk:clocks` (up to six time zones), `desk:month` (the month, a dot on each
busy day; a day opens the calendar on it), `desk:agenda` (today hour by hour with a line at
now), `desk:calendar` (coming days, 3/7/14 days), `desk:actions` (mine, my groups', created by
me), `desk:kanban` (open, in progress and blocked as columns; dragging a card moves it),
`desk:inbox` (Messages' unread notifications; it opens Messages over Desk), `desk:chats`
(unread chat messages: a count, or the conversations), `desk:checklist` (My day's to-dos; its id is the old checklist's, so boards keep it), `desk:note` (a quick
note kept with the card, saved as the person types), `desk:suggestions`, `desk:followed`,
`desk:team`; plus PlantCraft's "Worst first" and "Your apps", and every widget the installed
apps publish. A new person starts with the clocks; the coming days, their actions and the
month; notifications, My day and unread chats; suggestions and what they follow.

## Suggestions

Plain rules, no model, each with its reason: an action of the person past its due date or due
today, a followed asset in alarm with no open action, a conversation waiting for the person's
answer, an action of theirs with no change for 14 days. Taken, snoozed (until tomorrow) or
dismissed per person (`desk_triage`).

## To-do

To-do (owner, round 7, 2026-10-24) has the shape of Microsoft To Do and the Mac's Reminders. A
one-line box adds a to-do (to My day, to the list open, or due today in Planned). A to-do has a
date, a repeat (every day, Monday to Friday, or on some days of the week), up to 30 steps, notes
and a list; **My day** holds what is due by today (late ones too), what the person picked for
today and, beside them, their actions due and the day's events. A repeated to-do done moves to
its next day (its steps unchecked) and leaves a done copy, so Done keeps what was done and when.
Rows change order by dragging, or with Alt and an arrow key.

The left column keeps the four fixed views (My day, Planned, All, Done), which gather to-dos from
every list and are never renamed or deleted, apart from **My lists** (the person's own) and
**Shared with my groups** (round 8). With no to-do anywhere yet, a few examples are offered, each
added with a click.

Lists are a person's own, or a group's: a group's leader (or an admin) makes a list the group
shares, everyone in the group sees its to-dos and ticks them, and only leaders rename or delete
it. **Turn into an action** makes the to-do an action (its notes and steps in the description,
its date as the due date, owned by the person or, from a group's list, by the group) when it
needs someone else; the to-do is done and points to the action.

The day's checklists and the routines of before became to-dos once, with nothing lost
(`DeskStore.migrate_routines`): a routine became a list of its own (a group's routine, a list of
the group) whose items repeat as it did, and a checklist item a to-do on its day, done or not.
The items a routine had put on past days, left undone, went: the repeated to-do stands for them.

## Notes

Notes (owner, round 7, 2026-10-24) have the shape of Apple Notes and OneNote, in an editor of
their own (Tiptap, MIT; loaded only on this page). A note has a title and a body with headings,
bulleted and numbered lists, a **checklist**, quotes and code, and `#` mentions: typing `#` lists
the assets and actions the person can see (the same list as Messages' references), and a
mention clicked opens what it names. Notes save as one types.

A note is **private** to whoever made it until they share it with people or groups; whoever it
is shared with reads it and writes in it, and only its owner shares it, pins it, ties it to an
event or deletes it. **Line to to-do** makes the line under the cursor a to-do of the person's;
**Line to action** makes it an action, with the line's `#` mentions as its references. A calendar
event of the person's own has an **Event note** button: the event's note (the agenda, what was
said, what comes next), made the first time it is opened.

A person keeps 2000 notes, each up to 200 KB, shared with 50 people or groups at most. The
server keeps the body as Tiptap's JSON and its plain text (for search and the list's snippet).

## Team

Team is **hidden** until an administrator shows it in Settings › Desk (owner, 2026-10-25: its use is
not clear yet); the page still opens at `/team`. `GET /api/desk/team-page` says whether Desk lists
it, `PUT` (administrators) changes it.

Team (owner, round 7, 2026-10-24) answers "how is my group today, and who can take this?". Every
member sees their groups, a leader also the groups under the ones they lead, and an administrator
every group (round 8), with the same rights as a leader; a picker at the top changes group.
**All groups** (the default with more than one group) puts every group side by side: its open and
late actions and each person's state today (away, busy, open and late work), a group's name
opening its page. The demo has an **IT and automation** team led by the administrator. On a
group's page:

- **People**: each member with the leader marked, **Away today** (an all-day event of theirs
  today) or **Busy now** (one of theirs going on now), their open and late actions, and a button
  that opens a chat with them. The event itself stays private: Team says only away or busy.
- **Group board**: the group's open actions (and those of its people that belong to no group),
  by status or by person. A leader drags a card to another column: to hand it to someone in the
  group (or to the group, with no owner) or to change its status.
- **The week**: the group's actions and shared to-dos due in the next seven days, and who is away.
- **Shift handover**: one note a day, shared with the group (Notes), made by the first who opens
  it and read by whoever comes in; the last seven days' notes below it.
- **Assets in alarm**: what the group's people follow that is in alarm or warning, and who
  follows it. **Shared lists**: the group's to-do lists with their open to-dos.

## Mentions of Desk's things

`#note:4`, `#todo:12` and `#event:7` work in messages, actions and notes like every other
reference. What they are is their owner's, so a mention says only its kind and number to
whoever reads it (`Note 4`) unless it carries a label, and opening it shows the item only to
whoever may see it. The `#` picker offers a person their own notes and open to-dos beside the
assets and actions. The apps' own kinds (a saved trend, an alarm, a model) come with each app.

## Own events

Each person keeps their own events on the calendar (2000 at most): a click on a day of the
month makes an all-day event, a drag over the hours makes one for those hours, **New event**
opens the same window. An event repeats every day, Monday to Friday, every week or every month
(until a day, or with no end); its first day always counts, as in iCalendar. Repeats are laid out
in the plant's time zone (`PLANTCRAFT_TIMEZONE`), so a 09:00 meeting stays at 09:00 across a
change of summer time; a monthly repeat on the 31st skips the shorter months. Times are stored in
UTC, an all-day event as its days (the end not included). Dragging or stretching one time of a
repeat moves or stretches the whole series. Nobody else sees a person's events.

The apps' scheduled runs start hidden (the **Scheduled runs** chip shows them); runs due in the
same hour come as one entry ("6 scheduled runs") that opens the list.

## Calendars from elsewhere

- **Import an `.ics` file** (Outlook: File › Save calendar; Google: Settings › Import and
  export): always available, copied once, at most 2 MB.
- **Calendar link** (Outlook "Publish a calendar" ICS link, Google "Secret address in iCal
  format", any `https://` or `webcal://` address): **off by default**, since the suite may run
  with no internet. An administrator turns it on in Settings › Calendars and names the servers
  allowed (exact host names). Links carrying a user name or password are refused, addresses
  that resolve inside the network are refused, the answer is capped at 2 MB, and each link is
  read again every 15 minutes. The change is audited (`desk.calendar_links`).

Events are read for the past quarter and the coming year (`icalendar` and `dateutil` expand
repeating events), at most 3000 per calendar, read only.

## What the apps put in Desk

An app puts dated items in **calendar feeds** and gives **to-dos** through API v1
(`docs/api-v1.md`, "Calendar feeds and to-dos in Desk"); it declares each feed in
`[[contributes.calendar]]` and each kind of to-do in `[[contributes.todo]]`
(`docs/app-standard.md`, section 4b), and Desk refuses what it did not declare. Desk owns the
format (`plantcraft_sdk.desk`), and `plantcraft.desk.app_items` keeps the items.

- **Calendar.** Each feed is one chip beside "Scheduled runs", named after the app and the feed;
  a feed declared `visible = false` starts off. A person sees the items for them (`user:`, one of
  their `group:`s, or `everyone`) of the apps they open; a click opens the item's page in the
  app. The app sends a feed's whole list each time (2,000 items at most).
- **To-do.** The apps' to-dos for the person or their groups are in **From apps** (the view shows
  once there is one), and those due by today in My day. Ticked here, the app reads who ticked it
  (`GET /api/v1/todos`) and may close it itself. At most 200 open per app and per person or
  group. A to-do is work the app asks for; a problem is an event for Alarms, never a to-do.

## API (`/api/desk`, every signed-in person, viewers included: it is their own data)

| Method | Path | |
| --- | --- | --- |
| GET | `/today` | My day's to-dos, action counts, followed assets, suggestions, unread messages. |
| GET, POST, PATCH, DELETE | `/todos?view=today\|planned\|all\|done\|list&list_id`, `/todos/{id}` | To-dos (3000 each); PATCH changes only the fields sent, `done` on a repeat moves it on. |
| POST | `/todos/{id}/action` | Turns a to-do into an action (not for readers). |
| POST, PATCH, DELETE | `/todo-lists`, `/todo-lists/{id}` | Lists (30 each); a group's by its leaders. |
| GET, PUT, DELETE | `/follows` | Assets followed (`asset:<id>`, 200 at most). |
| GET, POST, DELETE | `/calendars`, `/calendars/{id}`, `/calendars/{id}/refresh` | Calendars added (10 at most). |
| GET, POST, PATCH, DELETE | `/events`, `/events/{id}` | Own events (PATCH changes only the fields sent; `until: null` lets a repeat go on). |
| GET, POST, PATCH, DELETE | `/notes?q&event`, `/notes/{id}` | Notes (the list without bodies); a note comes with its `#` mentions resolved (`refs`). Sharing (`user:ana`, `group:x`), pinning and the event only by the owner. |
| GET | `/calendar?start&end` | Every dated thing in a range of 62 days at most, own events' repeats laid out. |
| POST | `/triage` | Done, snoozed or back, for a suggestion (Messages' Notifications keep their read and archived marks here too). |
| GET | `/team?group` | One of the person's groups (the first without `group`): people, board, week, handovers, assets in alarm, shared lists. |
| POST | `/team/{group}/assign` | A leader moves a card: `owner` (one of the group's people, or `null` for the group) and/or `status`. |
| POST | `/team/{group}/handover?day` | The group's handover note of the day, made by the first who opens it. |
| GET, PUT | `/settings` | Admins: calendar links and allowed servers. |

Tables (layer 2, `plantcraft/desk`): `desk_todos`, `desk_todo_lists`, `desk_follows`,
`desk_events`, `desk_notes`, `desk_calendars`, `desk_triage`, `desk_settings`.
