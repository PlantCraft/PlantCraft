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
| Retention | 400 days | Values older than this are deleted, hourly (in PostgreSQL a past month whose values are all past retention is dropped at once) |
| Scan | 1 s | Seconds between two reads |
| Deviation | 0.1 % | Of the signal's range when the range is known, else of the value (each archived value starts a segment kept within that share of it; near 0 nearly every change is kept). A signal sets it in engineering units |
| Max interval | 3600 s | A value is archived at least this often, even on a flat signal |

A signal's page says what is in effect and where it comes from, for example "400 days, from
general settings". A change at any level reaches the collector within seconds; signals that set
their own value do not change. Every change is written to PlantCraft's audit log.
