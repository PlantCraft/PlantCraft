# Documents

Documents keeps the plant's documents in one place: operating manuals, control narratives, P&IDs,
datasheets, procedures, troubleshooting guides, maintenance records and incident reports. It
reads each file, so you and the assistant can find the passage that answers a question, with its
page.

## Overview

Documents opens on its **Overview**: a search box (words or a question; it opens **Search** with
what you typed), how many documents are ready for search and how many are being read, the latest
documents (with when each was sent or changed) and those no one has linked to the plant's assets
yet. While files are read, a line above the widgets says how many. **Customize** arranges the
widgets; **Library** in the menu opens the folders and every document.

## Send a document

In the **Library**, pick a folder in the column on the left and choose **Send files** (or drop
files on the page). The line under the title says what is read: PDF, Word (.docx), Excel (.xlsx),
PowerPoint (.pptx), text, Markdown, CSV and HTML, up to 200 MB a file. Older .doc, .xls and .ppt
files are not read: save them in the new format first.

- Give the document its **number** (DOC-U200-OM-001), **title**, a **description** (what it
  covers, for whom; the search and the assistant read it too), **kind** and **unit**. A file
  sent with a number that already exists becomes its **new revision**; the older revision stays
  in the document's history and is no longer searched.
- The file is read in the background, from a few seconds to a few minutes: the **Queue** of the
  side bar lists the files waiting, being read and read in the last day. A file that cannot
  be read says why (for example a scanned PDF with no text).
- The tags found in the text (FIC-1003, FV-1003, P-1003) that exist in PlantCraft's asset tree
  are **suggested** as the document's assets. Confirm them on the document's page: the
  assistant ranks a document linked to an asset first when you ask about that asset.
- **Links to check** (in the Library, if you can edit) lists the assets found in the text of
  every document you can change. Pick several and mark them **Correct**, to link them, or
  **Wrong**, so they are not suggested again. An administrator can set a number of mentions
  from which an asset is linked at once (`DOCCRAFT_ASSET_AUTO_MENTIONS`, off by default).

## Find something

**Search** finds passages by their words and by their meaning, in English and Portuguese: "why
does the recycle flow jump?" finds the passage on valve stiction even when it never says "jump".
Filter by kind or asset. Each result shows the part of the passage around your words, with the
words in bold, and opens the document at that passage, marked, with your words in bold again. A
PDF's **Open the PDF** opens at that page; a Word file's **Open the document** shows it as a page
(its text, headings and tables). Ctrl+K, anywhere in the
suite, finds documents by number or title and the best passages.

## Diagrams and the plant map (beta)

P&IDs sent to the library are also read as drawings, offline and with no language model. This
works for PDF from a CAD tool, SVG, and scans or images (PNG, JPEG, TIFF). Every page that is a
diagram is listed in **Diagrams**. Each page opens with boxes over what was found and a list
of what to check first. Each finding says how sure the reader is and why.
Pick a box: if PlantCraft has that tag, the asset, its signals and what the apps say about it
are one click away.

**Plant map** joins all the sheets into one plant:

- the units, with the equipment in flow order and the control loops on each piece;
- the lines from one sheet to another, through the off-page connectors;
- a summary and the list **To check**.

On the map you can work with what was read:

- Pick an item to see its lines and the sheets it is drawn on. If PlantCraft already has it, its
  card opens the asset, its signals and what the suite's apps say about it.
- **Correct** or **Wrong** on any item or line, if you can edit. Wrong takes it off the map and
  out of every export. **Undo** brings it back.
- **Lists** downloads the equipment, instrument, line and loop lists as CSV.
- **DEXPI (XML)** downloads the map in the open P&ID exchange format, for tools such as AVEVA,
  Hexagon Smart P&ID or COMOS. It holds equipment, lines and instrument loops, with no drawing.
- **Asset file** goes to PlantCraft's Assets › Import, where you review it before anything
  changes.
- **Write the plant summary** (if you can edit) writes the map out as a document of the
  library, in the folder that holds most of the P&IDs. It covers each unit, the equipment in flow
  order with what feeds what, the control loops, and the sheets each item is drawn on. It is
  made from the drawings with no language model. Search and the assistant find it and cite it
  like any other document. Make it again after a change: it becomes a new revision.
- **Check against a tag list**: pick your plant's tag list (CSV or text, the tag in the first
  column) to see which tags are on both, and which are only on one. The file stays in your
  browser.

On a scan, an editor can also choose **Read again with the language model** on the diagram's
page. The page's image and what was found on it go to the model an administrator chose for
"Read a scanned diagram again" in Setup › Language models (off until then). What the model adds
is marked as the model's, with medium certainty: check it on the map.

How well it reads depends on the drawing:

- A clean vector P&ID is read almost completely.
- On a scan, the tags are read, but the lines are not.
- On a P&ID from a commercial tool, the tags are read well, but only part of the lines.

So check the lines before you use them.

## Ask the assistant

The assistant searches and reads the documents you may open, and cites each fact as [n] with the
document, revision and page; each [n] opens the document at that passage. It searches the
documents with every question, in every app: on a page about an asset (a loop in Analytics, an
alarm's tag) it searches about that asset too. On a document's page it can summarize it or answer from it alone; on
an asset's page it lists the documents about it. Analytics and Alarms ask it to check the
documents when they look for the cause of a problem.

## Folders and who reads

A folder lists who **sees** it and who **changes** it (people and groups); empty means everyone
with access to Documents. A document in a folder you may not see does not exist for you: not in
lists, search, the assistant or links. Uncheck **The assistant may read it** on a folder or a
document to keep it from the assistant while people still find it.

Every document sent, changed, downloaded or deleted, and every search the assistant makes, is
recorded in PlantCraft's audit log.
