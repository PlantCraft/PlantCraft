# Glossary

> **Updated:** 2026-10-26 · decided by the owner (thread "Repensar os nomes da suíte", every
> recommendation accepted) · checked by `tests/test_glossary.py`

One word, one meaning, across the whole suite. A name says what the thing is for, in the words a
process engineer already uses (ISA-18.2, PI, Simulink, Grafana), never the word of the code. A
page is named after what a person finds on it, in the plural of its object, and the same
function has the same name in every app.

This page names what people **see**: menus, headings, buttons, help and documents. Ids, routes,
API fields, database columns and package names keep their old words until the platform's final
brand name (BACKLOG D5b); then they change once, with redirects from the old addresses.

## Apps

| Name | What it is for | Was |
|---|---|---|
| **PlantCraft** | The platform: people, assets, settings, results and events, the launcher. Its entry in the app menu holds Assets, System health and the administration | |
| **Desk** | Each person's day: Today, Actions, Calendar, Notebooks, To-do, Notes, Team | |
| **Analytics** | Algorithms of blocks that run on the plant's assets and signals and publish results (signal quality, loop performance, equipment, process models) | Link |
| **Historian** | The data layer: sources, collection, compression, archive | |
| **View** | Dashboards, reports and trends | Dashboards |
| **Alarms** | Rules that raise ISA-18.2 alarms, the Active list, history and performance | |
| **Models** | Block-diagram models simulated over time (Modelica underneath) | |
| **Notebooks** | Jupyter with the plant's data, in the browser or on the person's computer | |
| **Simulator** | The simulated plant behind the demo and the benchmarks | id `simcraft` (was `plantcraft` until 2026-10-27) |
| **App template** | The starting point of a new app | StarterCraft (pending) |

## Words of the whole suite

| Word | Meaning | Not |
|---|---|---|
| **Signal** | One tag of a source, with its name and unit; what every app reads | point, variable, series (in text) |
| **Tag** | Only the signal's address in its source (`FIC-101.PV`) | an organizing keyword |
| **Label** | A free keyword that organizes objects (algorithms, blocks, dashboards) | tag |
| **Derived signal** | A signal an app calculates and writes to the Historian | derived series, output series, recorded output |
| **Asset**, **Type**, **Role** | A place of the plant; what each type of asset records; what a signal is for in its asset | kind (in text) |
| **Target** | What a result, an event or a run is about: an asset or a signal | subject |
| **Result** | What an app concluded about a target: a level, a score from 0 to 100 and a sentence | verdict |
| **OK, Warning, Critical, Unknown** | The levels of a result (stored as `ok`, `warning`, `alarm`, `unknown`) | Alarm, Bad, Attention as a level |
| **Event** | Something that happened, published by an app; also an appointment, inside the Calendar only | incoming |
| **Run** | One pass of something an app runs (in Models, a run of a model is a **Simulation**) | execution, round, job, work |
| **Queue** | What waits to run | work queue |
| **Compute**, **Worker**, **Compute task** | Settings › Compute: the machines that run the apps' calculations away from the apps; a worker is one of them; a compute task is one piece of a run that a worker takes | lambda, processing container, job |
| **Folder** | Organizes objects in any app | group (for objects) |
| **Group** | People only | |
| **Library** | A collection of blocks | |
| **Overview** | The first page of every app: a board of widgets | |
| **Widget** | A piece an app offers for the Overview and Today boards | card |
| **Panel** | One element of a dashboard or a report (stat, gauge, trend, bar chart, table, scatter, text) | card |
| **Settings** | The installation's and each app's configuration | Setup |
| **Preferences** | Each person's own choices | |
| **People** | The people of the installation, their groups and the specialists | Users |
| **System health** | The installation's services, disk and queues | Health |
| **Assistant**, **Specialist**, **Task** | The AI chat on every page; a robot colleague people message; a ready question or creation the assistant offers on a page | works |
| **Alarm**, **Alert** | An alarm needs an acknowledgement and counts in performance; an alert (ISA-18.2) does not | notice |

## Words of each app

| App | Words |
|---|---|
| PlantCraft | Overview, Assets (Asset types), System health, Preferences, People (Groups, Specialists), Apps (App keys), Backups, Updates, Settings, Runs and schedules (`/executions`, off the menu), Audit log |
| Desk | Today, Actions, Calendar, Notebooks, To-do, Notes, Team, Messages (Chats, Notifications) |
| Analytics | Blocks, Algorithms, **Monitors** (an algorithm on its targets, with its cadence, recorded outputs and alarm rule; was Schedules), **Results** (by monitor, then target, then history, with the Queue; was Executions), Finding, Check, Loop health, Labels |
| Historian | Sources, **Signals** (was Points), **Calculated signals** (was Calculated points), Derived signals, Imports, Exports, Settings; scan, deviation, max interval, retention, step, archive, backfill |
| View | Overview, Dashboards (**Panels**, Variables, Folders, Public links), Reports, Trends |
| Alarms | Overview, Alarms, **Events** (was Incoming; Received, Open now, Catalog), Rules (Simple, Blocks or Python; Rules, Silences), History (Journal, Sent, Performance, Targets); alarm and **alert** (was notice); acknowledge, shelve, out of service; priority and severity; values in a row (was points) |
| Models | Blocks, Models, Studies, **Simulations** (was Executions; every simulation and the queue), indicators, **simulation settings** and **solver** (not experiment, integrator), **category** of a model or block (was group; folders organize them) |

## Retired words

A retired word never comes back to the interface. `tests/test_glossary.py` reads the interface
text (the `t()` and `tt()` strings, menu labels, titles and help props) of every area already
renamed and fails on a retired word; an area joins its list when its renaming is merged.

| Area | Renamed | Retired in its interface |
|---|---|---|
| PlantCraft and Desk (`frontend/src`) | 2026-10-26 | Setup, Users (as a page), Health (as a page), Executions, Alarm (as a level), Works and Work (the assistant's tasks) |
| Historian (`apps/historian/frontend/src`) | 2026-10-26 | point, points, calculated point |
| View (`apps/view/frontend/src`) | 2026-10-26 | card, cards, Tags, Alarm and Attention (as levels) |
| Alarms (`apps/alarms/frontend/src`) | 2026-10-26 | notice, notices, subject, Setup, Incoming, points in a row, Kind (of an event), verdict |
| Analytics (`apps/link/frontend/src`) | 2026-10-26 | Link, schedule, execution, subject, Tags, Attention and Alarm (as levels), verdict, Setup, output and input series |
| Models (`apps/models/frontend/src`) | 2026-10-26 | Executions, execution, Experiment, Integrator, Runs (as the page), Group (of a model or block), Link |
