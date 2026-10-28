# Overview widgets

Every app's first page is its **Overview**. PlantCraft's Overview is a page of widgets
each person arranges (Customize: add, move, pick a size, remove; saved per person by
`GET/PUT/DELETE /api/home/layout`). The catalog is PlantCraft's own widgets plus those
each installed app publishes, so the Overview never depends on a given app: an app that is
not installed, or does not publish widgets, adds nothing (owner, 2026-10-21).

## Every app's Overview

Each app's first page is an Overview too, built with `AppOverview` from `@plantcraft/ui`
([app-standard.md](app-standard.md), section 10): the widgets it publishes below, plus any the
page draws itself, arranged by each person and kept per app (`GET/PUT/DELETE
/api/home/layout?page=<app id>`; no `page`, or `processcraft`, is PlantCraft's own). A new
person sees every widget of the app, the page's own first, unless the app names a default.

```tsx
<AppOverview app="linkcraft" name="Link" url={BASE_URL} intro={t("What Link judged, and what needs a look first.")}
  actions={<button className="button button-secondary">…</button>}
  widgets={[{ id: "kinds", title: t("Signals and loops"), size: "l", render: () => <KindCards /> }]} />
```

## The card grid

Every board (each Overview, Desk's Today) draws on `CardGrid` from `@plantcraft/ui`: 12
columns, rows of 91 px and a 14 px gap, the sizes of View's dashboards, on react-grid-layout
(owner, 2026-10-23: one grid for every page of cards). A saved layout is a list of placements:

```json
{"widgets": [{"i": "desk:actions", "widget": "desk:actions", "x": 0, "y": 0, "w": 4, "h": 3,
  "title": "My actions", "config": {"view": "mine"}}, "linkcraft:worst-assets"]}
```

A plain widget id (the old form) is still read and placed by its `size`. `i` is the card's id
on the page (`desk:actions~2` for a second copy of a `multiple` widget), `config` the widget's
own settings (4000 characters at most). Below 720 px the cards stack in reading order.

### Fixed sizes

Widgets have fixed sizes (owner, 2026-10-24): each declares one to three sizes, small to large,
1 to 3 rows high, and draws what fits each one. Dragging a card only moves it; its gear picks
the size, with a preview. A size saved before (or one the widget no longer allows) becomes the
closest allowed. A widget that declares only `size` gets the standard ones:

| `size` | Small | Large | New card |
| --- | --- | --- | --- |
| `s` (a count) | 3 × 1 | 3 × 2 | 3 × 2 |
| `m` (a list) | 4 × 2 | 6 × 3 | 6 × 3 |
| `l` (wide) | 6 × 3 | 12 × 3 | 12 × 3 |

A widget defined in code may set `sizes` (`[{w, h}]`, smallest first), `w` and `h` (a new
card's size, one of `sizes`), `multiple`, `defaultConfig`, `settings` (its fields in the gear's
dialog) and `render({config, w, h, rows, editing, setConfig})`: `rows` is how many list rows
fit (`listRows(h)`), `setConfig` keeps new settings from the card itself (a quick note's text).
`bodyPixels(h)` is the height a widget draws in.

"Add a widget" opens a window with the apps at the left and their widgets at the right, each
previewed at the size picked for it.

### The widget test page

Desk's `/widgets` (`WidgetGallery`) draws every widget of Desk and of the installed apps at
every size it allows, on the page's real width. Its browser test (`tests/e2e/test_widgets.py`)
fills the lists, then fails when a widget's content is taller or wider than its card, in the
light and the dark theme; it also writes how much of each card is left empty
(`widgets-spare.json` with `PLANTCRAFT_E2E_SHOTS`). Check a new widget there.

## Publishing widgets from an app

An app declares its widgets once, in `app.toml` (`[[contributes.widgets]]`, see
[app-standard.md](app-standard.md) section 4b): PlantCraft keeps them in its registry and the
app serves them, read-only, under its prefix, answered with the person's own access (the browser
calls them with the suite's token cookie). `plantcraft_sdk.widgets` builds every answer, so all
apps answer the same; `plantcraft-app check` fails when the app serves widgets it does not
declare, or a widget with `pick` has no options route.

```toml
[[contributes.widgets]]
id = "schedule"
title = "Link: schedule"              # "Link: " is dropped on Link's own Overview
description = "One schedule: its last execution and what it found."
size = "m"
kind = "facts"                        # number, list, split, series, facts, bars, columns or tiles
sizes = [{ w = 4, h = 2 }, { w = 6, h = 3 }]
pick = "Schedule"                     # about one thing the person picks in the gear's dialog
default = false
```

```
GET <prefix>/api/widgets                  widgets.catalog(manifest, t)
{"version": 1, "widgets": [{"id", "title", "description", "size", "sizes", "kind", "default", "pick", "multiple"}]}

GET <prefix>/api/widgets/<id>             one widget's data, in one of the eight shapes
GET <prefix>/api/widgets/<id>?item=<v>    a widget with `pick`: the thing picked (without one, the first)
GET <prefix>/api/widgets/<id>/options     a widget with `pick`: {"options": [{"value", "label", "detail"}]}
```

The eight shapes (`plantcraft_sdk.widgets` builds each; `WidgetKinds.tsx` draws each):

| `kind` | Draws | Built with |
| --- | --- | --- |
| `number` | one figure, its unit and a line below it | `number(3, label="in alarm", state="alarm", href=…)` |
| `list` | rows: a name, a line below it, a value and a status dot | `items([item("FIC-101", detail=…, value=…, state=…, href=…)], href=…, empty=…)` |
| `split` | a total split by status: one bar and its parts, each a link | `split([part("Alarm", 2, "alarm", href)], label="results")` |
| `series` | a figure and its recent history as a small area chart | `series([(ms, value), …], value=41.2, unit="°C", label="last hour")` |
| `facts` | one thing (a run, a schedule, the collector): its status and labelled values | `facts("Night round", [fact("Assets", 12)], status="Done", state="ok")` |
| `bars` | a ranking: a bar per row, as given, against the longest (or `max`, or `target`, drawn dashed) | `bars([bar("PIC-1202 high", 50, detail="98 % of the load", state="alarm")], target=…)` |
| `columns` | a count per hour or day, each column stacked by status, with a dashed target line | `columns([(ms, [3, 1]), …], stacks=[stack("High", "alarm"), stack("Low", "warning")], step="hour", target=6)` |
| `tiles` | a status map: one small square per thing, in groups, each square a link | `tiles([group("Area 100", [tile("FIC-101", "alarm", href=…)])], label="loops")` |

A list row says what its time is: the time goes in the line below the name with its word
("Updated 5 h ago", "Started 2 min ago", "Next: Mon 08:00"), never as a bare "5 h ago" in the
value, where nobody can tell what happened then (owner, 2026-10-27). The value is for a figure
that reads on its own ("Health 30 %", "3 of 8"). `apptest.widget_problems` fails a bare time.

Every mark says what it is on hover and on keyboard focus (owner, 2026-10-27), drawn by the
ui from the data alone, nothing to add: a square of `tiles` its label, its group and each part
of its `detail` (split on " · ", so "Collecting · Feed flow" is two lines); a column of
`columns` its hour or day and each stack's count; a bar its label, detail and value; a part of
`split` its count and share; a point of `series` its value and time; a list row or a fact its
full text when an ellipsis cuts it. Put what the mark is in `detail`: it is what the note shows.

```
{"kind": "number", "value": 3, "unit": null, "label": "in alarm", "state": "alarm", "href": "/link/results"}
{"kind": "list", "items": [{"label": "FIC-101", "detail": "Oscillating", "value": 42, "state": "alarm",
  "href": "/link/assets/FIC-101"}], "href": "/link/results", "empty": "Nothing in alarm."}
{"kind": "split", "total": 42, "label": "results", "parts": [{"label": "Alarm", "value": 2, "state": "alarm", "href": "…"}]}
{"kind": "series", "value": 41.2, "unit": "°C", "label": "last hour", "points": [[1761400000000, 40.9], [1761400060000, null]]}
{"kind": "facts", "title": "Night round", "status": "Done", "detail": "2 h ago", "state": "ok",
  "facts": [{"label": "Assets", "value": 12}, {"label": "In alarm", "value": 1, "state": "alarm"}]}
{"kind": "bars", "unit": null, "target": 6, "target_label": "ISA-18.2 target",
 "bars": [{"label": "PIC-1202 pressure high", "value": 50, "detail": "98 % of the load", "state": "alarm", "href": "…"}]}
{"kind": "columns", "value": 35, "label": "raised in 24 h", "step": "hour", "target": 6, "target_label": "6 an hour",
 "stacks": [{"label": "High", "state": "alarm"}, {"label": "Low", "state": "warning"}], "buckets": [[1761400800000, [3, 1]]]}
{"kind": "tiles", "value": 264, "label": "loops", "more": null,
 "groups": [{"label": "Area 100", "href": "…", "tiles": [{"label": "FIC-101", "state": "alarm", "detail": "Oscillating", "href": "…"}]}]}
```

- `id`: `[a-z0-9-]`, at most 41 characters; the catalog names it `<app id>:<id>`.
- `size`: `s` (a count), `m` (a list), `l` (wide); its standard sizes are above.
- `sizes` (optional): up to three `{"w", "h"}`, `w` 1 to 12 columns, `h` 1 to 3 rows.
- `default`: on Desk's Today for a new person until they arrange their own. Keep it to one
  widget per app; an app's own Overview names its default board itself (`AppOverview defaultLayout`).
- `pick`: the widget is about one thing; its gear's dialog lists the options, the card is titled
  by the one picked, and it may be placed more than once (a card per schedule).
- `state`: a status of the suite (`alarm`, `warning`, `ok`, `unknown`), drawn in its colour.
- `href`: a path on the same host; anything else is not drawn as a link.
- Hover: a card's title shows the manifest's `description`; a fact's optional `detail`
  (`fact("Chattering", 2, detail="Alarms raised 3 times in a minute")`) says what it means.
- Each shape draws what fits its card: a list as many rows as fit (two in two rows, four in
  three), facts two to eight values, a split its parts from two rows, bars one, three or five
  bars (1, 2, 3 rows), columns their dates and key from two rows; tiles shrink their squares as
  there are more of them (1500 at most, `more` counts the rest). The data is read again every minute.

Another `version`, an error or a 404 hides the app's widgets; the Overview still draws. A shape
this PlantCraft does not know says "needs a newer PlantCraft" in its card.
Nothing of the app runs inside the platform: the page draws the eight shapes above.
