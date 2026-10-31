# Panels

| Kind | Shows | Signals |
|---|---|---|
| Stat | One value (last, mean, min, max, ...) per signal over a window, coloured by its thresholds, with its line underneath if you want | up to 24 |
| Gauge | One value on a dial (or a bar gauge), with the threshold bands; one dial per signal. Style **Analog indicator (ISA-101)**: a grey bar with the normal range, the LL, L, H and HH limits from the thresholds and the setpoint (a signal of role SP of the same asset); the pointer takes a colour only out of normal | up to 24 |
| Trend | Lines over a window; two units get two axes; thresholds as lines or areas | up to 24 |
| Bar chart | One value per signal, vertical or horizontal, coloured by the thresholds | up to 24 |
| Table | Last, mean, min and max per signal, cells coloured by the thresholds | up to 24 |
| Scatter (X-Y) | One signal against another, on the same time grid: the first is x, the second y (PV against OP shows a sticky valve) | 2 |
| Text | A note: what the dashboard is for, what to watch, who to call | none |
| Multivariable controller | A third-party APC, read only: each manipulated (MV) and controlled (CV) variable with its value, low and high limits, steady-state target, status and shadow price now, a bar of its range (value as a pointer, target as a hollow mark) and its value and target over the time span (the horizon). A variable whose target (else its value) is within its band of a limit is marked **At high limit** or **At low limit** | none: the controller |

The controller is an asset of kind `apc` (roles `on`, `mode`; attributes `vendor`, `cost_unit`)
with assets of kind `apc_mv` and `apc_cv` under it (roles `value`, `lo`, `hi`, `target`, `status`,
`shadow_price`; attribute `limit_band`, 1 % of high minus low when empty). Analytics reads the same
names. View never writes to the controller.

Panels saved before round 7 open as before: a KPI or a "value and line" panel is now a Stat (the
second with its line on), and its limits are now thresholds.

## The panel editor

**Add panel** opens the editor full screen. First pick the **panel type**; the preview fills the
left and the options sit in groups on the right, with a search box that keeps only the options
whose name matches. **Visualization** at the top changes the type later: the signals, the
thresholds, the mappings and the overrides stay. **Apply** puts the panel on the dashboard (the
dashboard is saved with **Save**), **Discard** leaves it as it was.

**Signals.** Each line of a panel is one of:

- **Signal**: one PlantCraft signal, by name or description.
- **Asset**: one asset and a signal role, or **every signal of the asset**; the role buttons
  under it keep only some roles (PV, SP, OP, ...).
- **Variable**: the asset picked in a dashboard variable (`${loop}`), with a role or every role.
  The panel follows the picker; see [Dashboards](dashboards.md#variables).

A panel has up to 12 lines, which stand for at most 24 signals (a note says when more were cut).
A new trend, bar or table panel starts with every signal of the asset; a stat or a gauge with one.

## Options

| Group | What it sets |
|---|---|
| Panel | Title, description, page, time window of its own |
| Stat, Gauge, Bar chart, Table, Graph, Scatter | What the kind draws: the value (last, mean, ...), the line under a stat, the dial or the bar gauge, bar direction, line style and points, the table's columns |
| Legend, Axis | Legend place and table (with last, mean, min, max), axis labels, scale, soft min and max |
| Standard options | Unit, decimals, min and max, the normal range (a stat's line and the analog indicator shade it; empty: between the thresholds' normal step and the next), colour of the values |
| Thresholds | Steps from a base colour up: each step has a value and a colour; **absolute** or **percent** of min to max; on trends and bars shown as lines, areas, both or not at all, with their labels |
| Value mappings | A value or a range shown as a word and a colour (0 as "Stopped", 1 as "Running") |
| Overrides | Other options for some lines only, matched by role, signal or name (the SP dashed, OP on the right axis) |
| Layout | Width and height in grid cells |
| Repeat options | Repeat the panel for every value of a variable, side by side or one under another |

Colours stay readable in light and dark themes: a colour too close to the background is
darkened or lightened until it reads, and text on a filled cell is white or black, whichever
reads.

## Size and place

The grid has 12 columns; one row is about 90 pixels. In **Edit**, drag a panel by its title bar
and resize it from its lower right corner; the other panels move out of the way. **Duplicate**
puts a copy under it. Panels with a chart, a dial or a table take at least 2 rows. On narrower
screens panels take half the width or all of it, and on a phone every panel takes the whole width
at its own height.

**Full screen.** Trend, bar and scatter panels have a full-screen button in their corner: the panel
fills the window, with zoom, pan, reset and a picture download. Esc closes it. The Trends page has
its own **Full screen** button above the chart.

**Results of other apps.** Stat, bar and table panels can also show what another installed app
published about an asset or signal, such as Analytics' loop health or signal quality: pick the asset, then the
result under "Shows". The colour is the app's own status (OK, Warning, Critical), not the panel's
thresholds; the value is its score out of 100. A result its app has not refreshed in time shows as
stale and unknown. On a trend panel the same choice draws the result's history, when its app
archives it (Analytics keeps each loop's health over time).

**Windows** go from seconds to 366 days. A trend draws at most about 600 points per line, each
the mean of its step. When a window holds no samples, a trend shows the newest data it finds and
says so under the chart.
