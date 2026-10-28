# Export

Export takes the history out in open files, for a consultant, a colleague or your own
analysis in any tool. One ZIP holds the series and the plant's metadata.

## Choose what to export

1. **Search** assets and tags in one box: by name, tag, description or path. **Kind** narrows it
   to tags or to one or more kinds of asset (units, equipment, loops and any other kind in
   PlantCraft's asset tree); a kind alone lists every asset of it.
2. **Tick** what you want and press **Add**. A tag goes in as itself; an asset adds every tag
   under it, each with the asset and role it came from.
3. Repeat as often as you like. The list below holds the package. It sorts by any column, pages
   long lists and has its own **filter**. Remove one tag with its **×**, or tick several (the
   box in the header ticks the page; **Select all** ticks every tag the filter shows) and press
   **Remove selected**. **Clear** starts again.

Tags an asset names but the Historian does not archive show as *not archived* and are listed in
the manifest, never silently dropped.

## Save an export

Give the choice a name and press **Save export**. Saved exports are listed on the left; open one
and download again. A relative period ("last 24 hours") reads up to the moment you download, so
"Unit 100, last day" gives the latest day each time. **Save** changes it, **Save as new** keeps
the old one. Anyone who exports may save; the author or an editor changes or deletes it.

## Period and resolution

A relative period (last 2 hours to last 30 days) ends now; **From – to** takes any window.
**As recorded** gives every archived value (up to 7 days). A step of 1 minute, 10 minutes, 1 hour
or 1 day gives one value per step on a fixed grid (up to 31 days), and **Each step keeps** says
which: the **mean** (time-weighted), the **first** or **last** value recorded in the step, or the
**lowest** or **highest**. A step with no recorded value is left out (the mean holds the last
value across it). A text signal (a mode, a state) keeps the step's last value for lowest and
highest. `manifest.json` names the step and the aggregate. A package holds up to 500 tags.

## Privacy

**Replace tags and asset names by aliases** turns every tag into `S001`, `S002`… and every asset
into `A001`… and leaves names and descriptions out. **Download key** saves the table that turns
the aliases back: keep it apart; it never travels in the package.

## What is inside

| File | What it holds |
|---|---|
| `series.csv` | The time (UTC), then one column per signal, named by its tag (by `source:tag` when two sources share the tag); empty cells mean no value at that time |
| `signals.csv` | Every signal: tag, name, unit, limits, the asset and role it serves |
| `assets.csv` | The assets the signals came from, with their signals by role |
| `plant-map.json` | The assets and signals as a PlantCraft plant map |
| `manifest.json` | Period, choices, what could not be read and a SHA-256 of every file |

To open it in another PlantCraft, import `series.csv` in its Historian (Imports), then
import `plant-map.json` in Administration > Setup. Every export is recorded in PlantCraft's
audit log.
