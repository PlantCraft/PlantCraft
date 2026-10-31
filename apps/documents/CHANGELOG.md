# Changelog

All notable changes to this app are recorded here ([Keep a Changelog](https://keepachangelog.com)).

## [Unreleased]

### Added

- **Diagrams and the plant map, read from the P&IDs in the library.** P&IDs sent as PDF, SVG or
  an image (PNG, JPEG, TIFF) are read offline, with no language model: ISA-5.1 tags, symbols,
  lines, flow arrows and off-page connectors, each finding with how sure it is and why. Every
  diagram page is in **Diagrams**; **Plant map** joins the sheets into one plant (units,
  equipment in flow order, control loops, lines across sheets), with a summary and what to check.
  Editors mark an item or a line Correct or Wrong (with Undo); the map exports its equipment,
  instrument, line and loop lists as CSV and an asset file for PlantCraft's Assets › Import, and
  is compared with the plant's own tag list in the browser. Each diagram is also a passage in
  words, so search and the assistant find what it shows ("P-1001 feeds E-1009"). Scans are read
  with Tesseract OCR (now in the image), within a time budget. New dependencies: pdfplumber,
  pypdfium2, pillow. A DEXPI example P&ID (CC BY 4.0) is a test file.
- **Real P&IDs from CAD tools read better.** An equipment tag written beside its outline finds
  that outline (not the gap between the pipes around it); valves drawn as four loose strokes
  are valves; arrows drawn along a line, away from any symbol, give the line's direction; a
  pump drawn small to scale is still a pump. On the DEXPI example the reader finds 4 of its 6
  equipment feeds with none wrong (3, one of them reversed, before).
- **The plant map in DEXPI.** **DEXPI (XML)** under Lists downloads the map in the open P&ID
  exchange format (Proteus XML): equipment with its class and tag, each process line between
  two pieces of equipment with a nozzle at each end, and each instrument loop with its valves
  and the equipment it measures. No graphics; what was marked Wrong is left out. The help page
  now explains Diagrams and the plant map.
- **From the map to the plant.** An item PlantCraft already has opens its asset, its signals
  (the Historian's) and what the suite's apps say about it, from the item's card on the map.
- `tools/llm_vision_eval.py --dexpi DIR --xml DIR` scores a vision model on public P&IDs against
  their DEXPI XML (`tools/dexpi_truth.py`), next to the classical reader on the same files.

### Security

- Drawings are read in the same worker process as the text of the file, with the same limits:
  120 s, a memory budget, no network and no file writes.

## [0.5.1] - 2026-10-30

- Suite 0.5.1: `plantcraft-sdk` 0.79.0 and `@plantcraft/ui` 0.89.0, with the new look (the PC valve logo, Steel Blue and the new app marks).

### Changed

- **The library's table on one line (fine pass 2026-10-28).** Number, unit and when it was sent
  no longer wrap; Assets names the first asset and how many more (all on hover); the description
  never widens the title; the Rev. column left the list (the document's page has its revisions).
  On a phone the list shows the title and its reading state.

## [0.5.0] - 2026-10-27

### Changed

- **Final review round.** The Overview has no buttons at the top (the
  library and **Send files** are on Library, in the menu); the latest documents say when each was
  sent or changed. The library shows its folders in the column on the left, as Analytics and
  Models do (All, each folder with its count, General, New folder), and says under its title which
  files are read and how large. The **Reading queue** page left the menu: `GET /api/queue`
  answers in the suite's format (`plantcraft-queue/1`, `[contributes] queue = true`), so the
  files waiting, being read and read in the last day are in the Queue of the side bar.

### Added

- A document's **description** (up to 1,000 characters): sent with the file, changed on its page,
  shown under its title in the library, searched (its words count as the title's) and read by the
  assistant (`read_document`).
- **Citations open the passage.** Each result of Search shows the part of the passage around the
  words, with the words in bold, and opens the document at that passage with the words marked
  (`?passage=&q=`); a PDF opens at the passage's page. Every passage the assistant's search gives
  carries that link, and PlantCraft turns each [n] of the answer into it.
- **A Word file as a page** (`GET /api/documents/<id>/view`, `library/preview.py`): headings,
  paragraphs, lists and tables from the file's text, every piece escaped, in a fixed set of tags.

### Security

- **Asset scope (decision D2).** A person who sees only part of the plant (PlantCraft's token claim
  `assets`) finds a document about assets only when one of them is theirs: list, page, search and
  the assistant's tools. `processcraft-sdk` 0.66.0.

### Added

- **Searched with each question.** `search_documents` declares `prefetch = "query"`
  (`processcraft-sdk` 0.73.0): PlantCraft searches the documents with the person's question
  before the model answers, so the assistant reads them even when the model would not pick the
  tool (it did on 20 of 40 questions in the evaluation of 2026-10-27). Folders, asset scope and
  "not for the assistant" decide what is found, as before.
- The assistant's tool `find_tags` (owner decision D5, 2026-10-27): for each tag, up to five
  passages that name it, its own section first, then one passage per document, with the text
  around the mention ("FIC- 1003", where a PDF broke the line, counts). PlantCraft's plant draft
  (Assets › Import) reads it to place loops and equipment. `tests/write_demo_tags.py` writes
  PlantCraft's fixture of its answers on the demo documents.
- **Overview** (Overviews redesign, 2026-10-27): Documents opens on its Overview, like every app
  (`AppOverview`): a search box that opens Search with the words or the question, the count (how
  many documents are ready for search and being read), the latest documents and those not linked
  to assets, and a line on how many are being read, to the Reading queue. **Send files** and
  **Open the library** at the top. The library moved to `/documents` (Library in the menu); the
  reading widget stays in the catalog. Widgets declare their sizes; `processcraft-sdk` 0.69.0,
  `@processcraft/ui` 0.72.0.

### Security

- A folder that no longer exists keeps its documents for administrators only, as in View (platform
  review I1, 2026-10-27).
- The "Reading" widget and the reading queue count only the documents of the folders the person
  sees; they counted every folder's passages and failures (platform review S2, 2026-10-27).

## [0.4.0] - 2026-10-26

- First version (plan "Documents" D1 to D8): a library of the plant's
  documents in folders with access, revisions by document number, the original files kept by
  SHA-256; PDF, Word, Excel, PowerPoint, text, Markdown, CSV and HTML read into passages with
  page and section; the plant's tags linked to its assets; search by words (FTS5) and by meaning
  (multilingual-e5-small, ONNX, bundled) fused by rank; the assistant's tools
  `search_documents` and `read_document` (processcraft-sdk 0.61.0) and four works; Ctrl+K,
  `#doc:` references and four widgets.
- The meaning model is pinned (`deploy/embedding-model.lock`, Xenova/multilingual-e5-small at
  761b726). A build machine that cannot reach it builds the image without the model: the search
  then matches words only and says so; a file with another hash still stops the build. Changing the model queues every indexed
  document to be read again, so search never mixes two models' vectors.
