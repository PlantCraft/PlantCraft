# Imports

**Imports** loads CSV and Excel files into the archive: lab analyses, an export from another
system, a spreadsheet. An import reads its next files the same way, and can **repeat from a
folder**: each new file there is read every day, or more often, into the same signals.

## Import a file

1. Press **Import CSV** and choose the file (up to 200 MB). Historian checks it at once and
   writes nothing yet.
2. Set the **time zone** of times written without an offset. Times with an offset or `Z` are read
   as written. Everything is stored in UTC.
3. Read the check: layout, period, lines, values and signals, then any **errors** (the file
   cannot be imported) and **notes** (it can, but look first). Each problem lists its lines.
4. Name the import and press **Import**. The collector writes the values, one file at a time;
   the status shows **Waiting** while the file is in the queue, then **Writing values** with a
   progress bar. The suite's **Queue** shows the same. The uploaded file is then deleted: the
   values stay in the archive. A file still waiting can be cancelled (**Cancel the waiting
   file**); one being written is not stopped.

## The next file, and repeating from a folder

**Import the next file** reads a new file the way the import's last file was read (separator,
columns, time format, time zone) into the same import: new tags become signals, and values at a
time already imported are replaced.

**Repeat from a folder** does that by itself. Give a file, or a pattern such as
`/csv/lab/*.csv`, inside the folders the administrator opened to CSV sources
(`HISTCRAFT_CSV_DIRS`), and how often to check it (every 15 minutes to every day). Each file
there that is new or changed is read and written, and shows in the queue while it is; a file
that has not changed is not read again, and a file with errors is skipped and named under the
import's status. The files are only read, never moved or changed. The signals keep their names
(`import-3:LAB-101.DENSITY`), so charts and algorithms that use them go on working. A repeating
import is listed under Sources too. **Stop repeating** keeps every value written.

## Layouts

| Layout | Columns |
| --- | --- |
| Wide | The time, then one column per tag. |
| Long | The time, the tag, the value and, optionally, the quality (`good`, `uncertain`, `substituted`, `bad`). |

The separator (`,` `;` tab `|`) and a decimal comma are found from the file. Times may be ISO
8601, `dd/mm/yyyy hh:mm` (`mm/dd` when a first part is above 12) or Unix epoch in seconds or
milliseconds. Empty cells and markers such as `NA`, `#N/A`, `null` or `-` are gaps. A column that
is mostly text becomes a text signal.

**Errors** block the import: unreadable times, text in a number column, lines without a tag,
unknown qualities, duplicate or unnamed columns. **Notes** do not: repeated times (the last value
wins), times more than a day ahead, how a day/month date was read, a file imported before.

## Signals and keeping

Each import is a source of its own (`import-1`, `import-2`, ...) with one signal per tag, mode
archive. Its values are kept until the import is deleted, unless a signal is given its own
retention. The list keeps every import with who loaded it and when.

**Delete** removes the import, its signals and every value it brought, after you type its id. It
cannot be undone. Only editors import and delete.
