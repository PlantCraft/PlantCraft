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

## P&IDs

P&IDs and the plant map are in **PlantCraft PID**, a separate app an administrator installs
with its licence. Documents keeps P&IDs sent as PDF like any other document, read for their text;
drawings sent as SVG, DEXPI or scans go to PlantCraft PID.

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
