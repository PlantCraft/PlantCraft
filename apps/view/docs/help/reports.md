# Reports

A **report** is a document over one period, written like a notebook: cells of text in Markdown,
the same panels as a dashboard (KPIs, dials, trends, bars, tables, scatter) and the events the apps
wrote (alarms, Analytics' findings). View makes it into a **PDF** on a schedule and sends it to people
and groups in **Messages › Notifications**, with the PDF one click away. Every PDF made is kept,
so what was sent can be read again as it was. It also downloads as **Word**, a **web page** and
**Markdown**, and opens by a **public link**.

Each dashboard can have its report beside it, in the same folder: **New report › Start from a
dashboard** turns its pages into headings and its panels into cells.

## The period

Every section of a report reads the report's period, which ends when the report is made: a
report made every day at 06:00 over **the last 24 hours** covers 06:00 the day before to 06:00
(the shift's day). Panels have no window of their own in a report.

A scheduled report can instead cover **whole calendar periods**: yesterday from midnight to
midnight, last week from Monday to Sunday, the two weeks before Monday, last month or last quarter,
on the installation's clock. Every panel then reads the period that closed, whenever the report is
made: a monthly report sent on day 3 still covers the first to the last day of the month before.

## Schedule and recipients

**Settings** sets:

- **Repeat**: every day, every week or every other week (on a weekday), every month or every
  quarter (on day 1 to 28), at a time of the installation's time zone. *Not scheduled* reports are
  made only when someone asks.
- **Covers**: the period, from 1 hour to a year. Changing the repeat suggests a matching period
  (a day, 7, 14, 30 or 90 days). **Whole calendar periods** covers the last closed day, week, two
  weeks, month or quarter instead.
- **Sent to**: people and groups of the platform. They get one notification per send; only
  those who may see the report's folder open it. **Also by email** adds an email where PlantCraft
  sends email and the person allows it.

The coming sends show on Desk's calendar, and PlantCraft lists the schedule with the other apps'.

## Building a report

**Edit** opens the editor on the page itself. Add cells at the bottom, or under any cell with its
**+**:

- **Text**: Markdown, written in place with its preview beside it (double-click a text to write
  in it; Shift+Enter finishes). `#` to `####` are headings of four levels, then paragraphs,
  **bold**, *italic*, lists (`-`, `1.`), tables (`| a | b |`), quotes (`>`) and links. The
  headings are the report's **sections**: the navigation at the side of the page, the PDF's
  bookmarks, Word's navigation pane and the web page's side menu.
- **Panel**: a chart, KPIs or a table, built in the same editor as a dashboard's panels. A report
  names its signals and assets (no variables, no repeated panels).
- **Events**: up to 10 kinds of events of the installed apps; the section counts each kind in
  the period and lists the latest (up to 100).
- **Page break**: the PDF starts a new page there.

Move sections up and down; panels and events can be **half width**, and two half sections in a
row sit side by side. While you edit, the panels read with your own access; the PDF reads with
View's, like a published dashboard.

## Making, downloading and sending

- **Download** reads the report now and saves it on your computer; nobody else gets it:
  - **PDF**: to print and keep; it is kept in **Sent** too.
  - **Word (.docx)**: to change and pass on. Headings are Word's own Heading 1 to 4, tables are
    Word tables, charts are pictures. Opens in Word, LibreOffice and Google Docs.
  - **Web page (.html)**: one file that opens anywhere, offline: the sections at the side, and
    charts that show every line's value under the pointer (as Grafana does); click a line in
    the legend to hide it.
  - **Markdown (.md)**: plain text for a wiki, a notebook or a ticket: the text as written and
    each panel as its values.
- **Send now** makes it and sends it to its recipients, as the schedule would.
- **Sent** lists every PDF made: when, what it covered, how (scheduled, sent, downloaded), how
  many people it reached, and whether a section could not be read. A section that cannot be
  read says why in the PDF and the rest of the report is still made; a report that cannot be
  made at all is a failed send, and the platform's administrators are told.

## Public links

**Share** makes a link that opens the report as its web page, read again each time it is opened,
without signing in: for a colleague without an account or a screen. A link opens that report
only and stops working when it is revoked or the report deleted (see *Public links*).

## Folders

Reports and dashboards share the same folders, which say who sees and who edits what they hold;
**New folder** is on both pages. **General** is not a folder: it holds what is outside every
folder, open to everyone, so it has no settings and no folder takes its name. A copy of a report
starts unscheduled, so it never sends twice what the original sends.
