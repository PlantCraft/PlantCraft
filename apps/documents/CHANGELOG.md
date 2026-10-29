# Changelog

All notable changes to this app are recorded here ([Keep a Changelog](https://keepachangelog.com)).

## [Unreleased]

### Changed

- **The library's table on one line (fine pass 2026-10-28).** Number, unit and when it was sent
  no longer wrap; Assets names the first asset and how many more (all on hover); the description
  never widens the title; the Rev. column left the list (the document's page has its revisions).
  On a phone the list shows the title and its reading state.

## [0.5.0] - 2026-10-27

### Changed

- **Final review round (owner, 2026-10-27).** The Overview has no buttons at the top (the
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

- First version (owner, 2026-10-26, plan "Documents" D1 to D8): a library of the plant's
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
