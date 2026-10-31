# Signals

A signal is one tag of a source that Historian reads or archives. Its signal id, `<source id>:<tag>`, is the
name apps see.

| Setting | Meaning |
|---|---|
| Scan | Seconds between two reads |
| Deviation | Compression tolerance in engineering units: the rebuilt trend never strays further from a value read. 0 keeps every change |
| Max interval | A value is archived at least this often, even on a flat signal |
| Retention | Days the archive keeps its values |
| Step | On/off states and setpoints moved by hand: kept until the next change, never interpolated |
| Kind | Number or text |

Scan, deviation, max interval and retention can be left empty: the signal then takes its
source's value, else the general settings. Under each field the page shows the value in effect
and where it comes from ("set on this signal", "from the source", "from general settings").

The installation can cap how many signals Historian records (`MAX_SIGNALS` in PlantCraft's
installation file). Signals added past the cap are skipped, and the answer says why. The series
apps write do not count.

The signal page shows its trend for any range and the bytes it takes on disk. Deleting a signal
removes its archive too (admins only).

The table's **Type** filter (on the Scan and deviation column) shows one kind of signal: read
from the plant, calculated, imported, written by an app or by PlantCraft.

## Notes

A signal's page lists the notes written on it in the period shown: what happened that the values
do not say ("analyser recalibrated", "pump B on manual from 14:00 to 15:30"). Editors add one at an
instant or over an interval, and remove their own (administrators any). Each note is also told to
PlantCraft as an event (*Note on a signal*), so Events, Alarms and the assistant see it.
Scripts and other apps read and write them with `GET` and `POST /api/v1/annotations`.

## Edited values

An editor can insert a value where there was none, change one or delete one (a reading taken
while the sensor was being calibrated, a value typed in by hand), always with a reason. The
value read then carries its mark (*inserted*, *edited* or *deleted*), the value it replaced is
kept with who changed it, when and why (the list under **Edited values**, or
`GET /api/v1/edits/{signal}`), and each edit is in PlantCraft's audit log. Signals an app writes
are changed in that app. Scripts use `POST /api/v1/edits`.

## The signal list in a spreadsheet

**Export signal list**, on the Exports page, writes every signal with its own
configuration: `source_id`, `tag`, `address`, `name`, `description`, `unit`, `kind`, `step`,
`low`, `high`, `mode`, `scan_seconds`, `deviation`, `max_seconds`, `retention_days`, `enabled`.
An empty setting cell means "inherit" from the source or the general settings.

**Import signal list** (editors), on the Imports page, reads such a file, separated by commas, semicolons or tabs. Only
`source_id` and `tag` are required; columns left out keep what the signals have. A row whose
source and tag exist changes that signal; any other row adds one. Historian first shows what
the file adds and changes and lists each line with a problem; nothing is imported until every
line is right. An address or a kind cannot change: remove the signal and add it again.

## Calculated signals

**Add calculated signal** makes a signal from others with a formula: a unit conversion, a sum
of flows, a condition, a totalizer. Its signal is `calc:<tag>` and it is archived, compressed
and trended like any signal; apps and exports read it the same way.

- Signals are written `[source:tag]`, e.g. `[plant:FI-100.PV] * 3.6`. A formula may use
  numbers, `+ - * / ** %`, comparisons (`< <= > >= == !=`, true is 1), `and`, `or`, `not` and
  the functions abs, min, max, sqrt, exp, log, log10, round, clip and if:
  `if([plant:XV-1.PV] > 0.5, [plant:FI-1.PV], 0)`.
- A **totalizer** is the whole formula: `total([plant:FI-100.PV], per="h", reset="day")`
  integrates a rate given per second, minute, hour or day (`per` = s, min, h, d) and restarts
  each hour, day or month in UTC, or never (`reset` = hour, day, month, none). Time while an
  input has no value adds nothing; after a restart of the collector the total continues from
  its last archived value in the same period.
- Inputs are signals archived here: OPC UA signals in mode archive or both, or other calculated
  signals (one scan later). PI Web API and CSV signals are read on request only, so a formula
  cannot follow them. A formula never reads itself, directly or through others.
- The collector evaluates each formula on the signal's scan with the latest values of its
  inputs. Any input bad, disconnected or missing makes a gap; any input uncertain makes the
  result uncertain. Sources that report no quality count as good.
- The formula can change on the signal's page or in the signal list CSV (column `address`).
