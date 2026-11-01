# User guide

PlantCraft is where you sign in to the suite. It keeps what every app
shares: the people, their groups and what each one may open, the asset tree,
actions and messages. The apps of the suite (the Historian for the plant's
data, Analytics, Alarms, Models, Dashboards) open from the menu. Nothing in the
suite changes the process: it only reads the plant's systems.

## Sign in

With sign-in on, enter your username and password (ask the admin, who creates
them in **People**). An app of the suite that needs you
to sign in sends you here and, once you are in, takes you back to where you
were. The demo has no password: the profile menu, at the bottom left, switches
between people.

## Access

What you can do depends on your access level and on the apps enabled for you:

- **Admin**: everything, including people, groups, apps and Settings.
- **Editor**: changes the asset tree and edits in the apps.
- **Viewer**: sees the assets and opens their apps read-only; changes nothing,
  and the create and edit buttons do not appear.
- **Dashboards only**: for control-room screens.

An administrator may also limit you to part of the plant (a unit, an area): then the asset tree
starts at those assets, and you see only their signals, what the apps say about them and the
actions about them.

## Desk: your day

After signing in you land on **Desk**, your own workspace. **Today** is a page of
widgets you arrange: **Coming days** (what has a date, like a phone's calendar
widget), **My actions** (yours, your groups' or the ones you created),
**Notifications** (the unread ones: alarms, runs and changes to your actions), **My
day** (today's to-dos), **Suggestions for today** (each with its reason; take it, snooze it or
dismiss it), **Assets I follow** and **My team** (your group: who is away or has late work). Each
installed app adds its own widgets. **Customize**, at the top right, lets you drag a
widget by its title, pull its corner to resize it, set it up (the gear) and add the
same widget twice with other settings; each person keeps their own arrangement.

Desk's other pages: **Actions**, **Calendar** (month, week, day or list; click or drag to add an event of your own;
drag an action to change its due date; **Add a calendar** imports an Outlook or Google `.ics` file,
or reads it by link when an administrator allowed it in Settings › Calendars),
**To-do** (My day, Planned, your lists and your groups' shared lists; a to-do has a
date, a repeat, steps and notes, and turns into an action when it needs someone else),
**Notes** (private until you share them with people or groups; headings, lists, a checklist,
`#` to mention an asset or an action, and a line that becomes a to-do or an action; an event of
yours on the Calendar has its own note) and **Team** (how your group is doing today: who is
away or busy, the group's actions on a board, the week ahead and the day's shift handover note). **Follow** on
an asset's page brings its alarms and results to your Desk.

**Messages** and the **Assistant** are at the bottom of the menu, above your name, in
every app: each opens over the page you are on and closing it brings you back. Messages
has two sections: **Chats** with people and groups, and **Notifications**, read like an
email inbox (alarms, runs and changes others made to your actions; open one to read it,
archive it when it is handled).

## PlantCraft and the apps

**PlantCraft**, last in the list of apps, is the suite's setup: its **Overview** answers
"is the installation healthy?", as widgets you arrange: **Apps online**, **Data connections**
(each Historian connection), **System** (problems open, free disk, last backup, version, who
signed in today) and, for administrators, **Recent changes** from the audit log. **Customize**
adds the others back: **Needs attention**, **Open actions**, **Worst first**, **Your apps** and
the widgets each installed app publishes (an app that is not installed adds none). A board you
arranged stays as you left it; **Restore the default** brings this one. Assets, Settings, People, Apps, System health, Backups and Updates are PlantCraft's pages.

## Moving around

Every app of the suite has the same menu on the left: the app's own pages, then
**Apps** (every app you may open: Desk first, then in the order data flows:
Historian, Analytics, Models, Alarms, View, and PlantCraft last; one click switches app). Your name at the bottom opens
the user menu: light, dark or the system's theme (one choice for every app), the
language, **Help**, **Take the tour**, **About** (the version) and **Sign out**; a
click anywhere else closes it.
**Collapse** folds the menu to icons.

## Sources and signals

The plant's sources (OPC UA, PI Web API or CSV), its signals and their history
live in the **Historian** app: add and test a source, browse its tags, choose
the signals to keep and for how long. A signal on an asset's page opens there.

## Assets

**Assets** shows the plant in folders: site, units, areas, equipment and loops,
each with its signals. The tree opens to level 2; **Open to level** 1, 2, 3 or
All above it opens it as deep as you need (the choice is kept in your browser),
and **Collapse all** closes it. **Import** and **Export** (at the top of the page) move
the tree alone: assets, their records, the signals they reference and their
relations, in PlantCraft's JSON, Excel, CSV, ISA-95 B2MML or PI AF XML. An
import opens a review page first: the file as a tree, each asset marked new,
changed, unchanged or with an error, where you correct a name, a type or a
place, or leave a row out, before applying. **Copy as prompt** on the import
page explains the file to your AI assistant, so it can build the tree from the
plant's documents or another system's export. **Last import** on the import
page shows who imported what and when, and **Undo last import** takes it back
once: the assets it created are removed and the records it changed return to how
they were.

**Draft a new plant** (on the import page, administrators) writes the first tree
for you when there is no asset file yet. Choose a source (its tags, as the
Historian browses them) or a tag list (`.csv` or `.xlsx` with a tag column and,
if you have them, description and engineering units). The ISA-5.1 names give
each loop (`FIC-1003`), its signals by role (`.PV`, `.SP`, `.OP`, `.MODE`), its
type and its transmitter and valve (`FT-1003`, `FV-1003`). With **Documents**
installed, the plant's control narratives, P&ID index, datasheets and manuals
place each loop in its unit and area, on its equipment, with the equipment's
type and record; each row shows where it comes from (document, revision, page
and the passage). With a language model chosen for **Plant draft** (Settings ›
Language models), the loops still unsure are placed by the model from the same
passages; anything it names that the sources do not is left out. The draft opens
on the same review page: **To check** filters the rows that are not sure, and
leaving out a unit or an area leaves out what the draft put in it. Nothing is
written until you apply, and the import can be undone.

**First steps in the apps.** Once an import is applied, the page lists what each
installed app can start on the assets it wrote: the Historian collects their
signals, Analytics monitors their loops (its first round starts each loop's
baseline), Alarms drafts two rules per unit (a loop in poor shape, a signal
without data) switched off for you to review, and View draws one overview
dashboard per unit. Tick the ones you want and take them; each is done as you,
with your access in that app, and says what it did with a link to it. Taken
again after a later import, a step skips what it did already.

Sources and signals come in through the Historian. A signal may be referenced by several assets (a
loop's PV is also its transmitter's measurement); each asset's **Signals** tab
says where else its signals are used. Search by name or code, filter by kind, create an asset
(admins), move it under another one, or add a kind of your own. A loop is an
asset whose signals have the roles `pv`, `sp`, `op`, `mode` and `secondary`;
the apps that analyse loops read them from here. An asset you edited by hand is
never changed again by the scenario file or by a map.

An asset's page is at `/assets/<id>` (for example `/assets/FIC-101`); copy the
address to share it. Old `/plant/<id>` links still open it. Its tabs: **Overview**
(the record beside the main signals and what is inside), **Signals** (one table:
each role of its type and the signal that fills it, or the gap to bind, then the
other signals, with the last value), **Inside** (everything under it), **Relations**,
**Actions** and **History**. The tab is in the address (`?tab=signals`).

## Actions

**Actions** is a board with a column per status (open, in progress, blocked,
done); each card says how long it has been there and when it is due. Editors
drag a card to another column to move it; finished work that should leave the
board is **Archived**. A card shows the title, the start of the description and
the checklist's progress. **List** shows the same actions as a table. A card
opens the action's own page: description, a **checklist** (items ticked one by
one, each with who and by when), what it is about, history and comments, and
its facts beside them. Write `#` (or use **Mention**) to point at an asset, a
person or a run: it becomes a link. A person's name opens their page.

An action goes to a person, to a group, or to both. Each person sees the
actions they own, created or are mentioned in, those of their groups, and, when
they lead a group, those of the groups below it; an admin sees all. **Show**
picks what the board lists: **All I can see**, **Assigned to me**, **My
groups** or **Created by me**; filter by group, person, status or text on top.

## Messages

**Messages** holds conversations between people and with specialists. **New
conversation** picks people one by one, or a whole group at once. Every group
also has its own conversation (**Group conversation** on the group's page): its
members are the group's, and they follow the group as people join or leave it.

Every name opens the person's page: job title, sector, unit, how to reach them
and the actions they own. **My profile**, in the user menu, is where each person
keeps their own.

**Asset types**, a tab of **Assets**, says what each kind of asset records:
attributes, signal roles and what may sit inside it (admins edit it).

## People and groups (admins)

**People › Groups** keeps the organization as a tree: departments, areas,
disciplines and teams, each under another. A group's coordinator is its leader
and sees the actions of every group below it. A person may be in several groups;
choose them on the group's page or in the person's account.

## People and app keys (admins)

In **People** and **Apps › App keys**:

- create a person with a username, a starting password, an access level and
  the apps they may open (or all apps, including those installed later);
- give a person another role in a given app (only read in Historian, edit in
  Alarms) than their level gives, and fill in their profile;
- limit a person, or every member of a group, to part of the plant: in **Assets they see**
  (or the group's **Assets members see**) choose the units or areas; they see those assets,
  everything under them, their signals and what the apps say about them;
- change a person's level or apps (it takes effect at once), reset their
  password (their open sessions end) or deactivate them (their history stays);
- issue an **app key** for each app of the suite. The app uses it for its
  background work, such as Analytics' rounds. The key is shown once: copy it
  into the app's `PLANTCRAFT_APP_KEY` setting. Revoke a key when it leaks or
  the app moves.

## Settings (admins)

**Settings** keeps what has no other place: **Corporate sign-in**, the **Audit
log**, **Language models**, assistant access (MCP), notebooks, calendars and
email. **System health**, **Backups** (with their schedule) and **Updates** have their
own pages under Administration. People, groups and
specialists are under **People**; apps and app keys under **Apps**; asset types
under **Assets**.

## Language models and specialists (admins)

Specialists are robot users people message; they answer from what the apps published. With
no language model they answer from scripts. In **Settings › Language models** an admin adds the
servers the models run on: a name, the format (OpenAI-compatible for Ollama, vLLM, LM Studio,
Azure and most gateways, or Anthropic), the address, the key if the server needs one and the
list of models it serves. Each model has a **Test** button. One provider and model is the
installation's default, and nothing is sent anywhere until "Use language models" is on. In
**People › Specialists** each specialist answers with the default, with a provider and model
chosen for it, or from scripts only.

## Demo

An installation made with `install.sh --demo` (or `--public-demo`, which also
opens a read-only `demo` account on the sign-in page) runs the Simulator, a
simulated plant of 50 loops read over OPC UA, and a demo story across the apps:
loops with a sticky valve, an oscillation and a drifting sensor in Analytics, alarms,
dashboards, twins, models, actions and conversations. To write the story again
(it never duplicates anything), run in the installation folder:

```bash
docker compose exec processcraft plantcraft demo seed
```

From a source checkout, `python run_opcua_demo.py` starts the same demo for
development (see the README).
