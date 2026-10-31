# Settings

Admins set how signals are read, compressed and kept. Settings come in three levels, and the
most specific one wins:

1. **General** (this page): every signal of every source.
2. **Source**: a source may set its own value for its signals (Sources, Edit, "Settings of this
   source's signals"). Empty fields take the general value.
3. **Signal**: a signal may set its own value (its page, "Collection and compression"). Empty
   fields take the source's value, else the general one.

| Setting | General default | Meaning |
|---|---|---|
| Retention (raw values) | 400 days | Values older than this are deleted, hourly (in PostgreSQL a past month whose values are all past retention is dropped at once) |
| Hourly rollups | 1825 days (5 years) | Each hour's mean, lowest and highest value, kept after the raw values are gone; general only |
| Daily rollups | forever (0) | Each UTC day's, from the hourly rollups; general only |
| Monthly rollups | forever (0) | Each UTC month's, from the daily rollups; general only |
| Scan | 1 s | Seconds between two reads |
| Deviation | 0.1 % | Of the signal's range when the range is known, else of the value (each archived value starts a segment kept within that share of it; near 0 nearly every change is kept). A signal sets it in engineering units |
| Max interval | 3600 s | A value is archived at least this often, even on a flat signal |

A signal's page says what is in effect and where it comes from, for example "400 days, from
general settings". A change at any level reaches the collector within seconds; signals that set
their own value do not change. Every change is written to PlantCraft's audit log.

## Rollups and the disk

Trends of whole hours, days or longer, and a window's mean, lowest and highest value, read the
rollups instead of every archived value: a year as a daily trend reads 365 daily rows. The
rollups keep their own retention, so the raw values can be kept a few months and the plant's
years still trend, with their means and extremes. A level is always kept at least as long as the
raw values and the finer levels (a shorter one would only be summed again from them), and a
signal kept forever keeps its rollups forever.

**Disk by retention**, on the Retention and collection page, shows what each level holds now and
what it will hold once every signal keeps its full retention, at the values archived in the last
24 h (per year for what is kept forever). An hourly rollup row takes about 125 bytes on disk and
a daily or monthly one 150: a signal's year of hourly rollups is about 1.1 MB, of daily ones 55 KB.
