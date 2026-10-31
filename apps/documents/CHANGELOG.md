# Changelog

All notable changes to this app are recorded here ([Keep a Changelog](https://keepachangelog.com)).

## [Unreleased]

### Added

- **P&IDs saved as DEXPI (XML) go straight into the plant map.** Send the `.xml` a P&ID tool
  (AVEVA, Hexagon Smart P&ID, Siemens COMOS...) exports as DEXPI (Proteus XML) and Documents reads
  it with its own reader (pyDEXPI is AGPL and is not used): equipment, instruments and their
  valves, and what feeds, measures, controls or sits on what, all certain since the tool says
  so. The page is drawn from the file's data for the review page, and it is a diagram like any
  other: in Diagrams, on the map, in search. On the 79 public DEXPI test files it reads 65 of 67
  equipment-to-equipment feeds, none wrong; the example C01 gives all 12 tags and 6 feeds. A file
  with a DOCTYPE or entities is refused.
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
- **Links to check: a queue for the assets found in documents.** The library's **Links to
  check** lists the links between documents and the assets named in their text that wait for a
  person, in the folders you change. Pick several and mark them **Correct**, which links them,
  or **Wrong**. A link marked Wrong is not suggested again when the document is read again.
  `DOCCRAFT_ASSET_AUTO_MENTIONS` sets a threshold: an asset named that many times in a document
  is linked at once (source `auto`), and removing it on the document's page rejects it. The
  default 0 sends every link to the queue, as before.
- **Tags on a P&ID open the plant.** On a diagram's page, the box of a tag that PlantCraft
  has opens the asset, its signals and what the apps say about it. A sheet linked from the
  plant map opens with the item already picked.
- **The plant map as a document the assistant cites.** **Write the plant summary** on the
  plant map writes the map of a folder's P&IDs out as a document in that same folder:
  - each unit, with its equipment in flow order and what feeds what;
  - the control loops and the instruments;
  - the sheets each item is drawn on.

  It is indexed like any other document, so search and the assistant cite it. It is made with no
  language model, and making it again adds a revision. Only that folder's drawings go into it,
  so it has the same readers as they do.
- **Hand valves drawn with no tag are followed.** A small circle in a gap of the line (a
  ball or hand valve as DIN/ISO 10628 tools draw it) is a valve the line runs through. A valve
  between two lines with arrows takes its direction from the line where it is alone. On the
  DEXPI example the reader now finds all 6 equipment feeds, with none wrong (4 before). The
  demo P&IDs are still read completely.
- **The plant map in DEXPI.** **DEXPI (XML)** under Lists downloads the map in the open P&ID
  exchange format (Proteus XML): equipment with its class and tag, each process line between
  two pieces of equipment with a nozzle at each end, and each instrument loop with its valves
  and the equipment it measures. No graphics; what was marked Wrong is left out. The help page
  now explains Diagrams and the plant map.
- **A scan read again by the language model.** On a scanned diagram an editor may ask
  **Read again with the language model**: the page's image and what the drawing reader found go
  to the model an administrator gives the new use `diagram-read` (Setup › Language models; off
  until then, and the app now asks for `write.llm`). The tags and lines it adds are kept with
  medium certainty and "read by the language model; check it", to be checked on the map. On the
  demo scans gpt-5-mini read the lines with precision 0.93 and recall 0.97, where OCR reads none.
- **From the map to the plant.** An item PlantCraft already has opens its asset, its signals
  (the Historian's) and what the suite's apps say about it, from the item's card on the map.
- `tools/llm_vision_eval.py --dexpi DIR --xml DIR` scores a vision model on public P&IDs against
  their DEXPI XML (`tools/dexpi_truth.py`), next to the classical reader on the same files.

### Fixed

- A diagram's page no longer shows the library's top buttons.

### Security

- **A document that looks confidential is kept from the assistant** (security test D11). When
  its first revision is read, a document that says it is not for the assistant, is marked
  confidential, or holds what looks like a password, PIN or key has its assistant switch turned
  off. A line inside the text was only text before, and answers quoted the secret it held. The
  editor turns the switch back on in the document's settings when that was wrong.
- Drawings are read in the same worker process as the text of the file, with the same limits:
  120 s, a memory budget, no network and no file writes.
- Files are read in a worker process with a time limit (120 s) and a memory limit, no network
  and no file writes, and a refused query value answers 422.
- `pypdf` 6.21.4 (7 CVEs: crafted PDFs that loop or eat memory).

## [0.5.1] - 2026-10-30

- Suite 0.5.1: `plantcraft-sdk` 0.79.0 and `@plantcraft/ui` 0.89.0, with the new look (the PC valve logo, Steel Blue and the new app marks).

### Changed

- **Search is faster for people who see some folders and for the assistant.** The search no
  longer reads the id of every passage the person may see. It checks only its best few hundred
  passages by meaning. With 100,000 passages, a search with specific words takes 16 ms instead
  of 191 ms, and a search with common words takes 190 ms instead of 360 ms. The results are
  the same.
- **Scans are read three times faster.** The search for instrument bubbles counts each ring of
  points as whole shifted copies of the page instead of letting every dark pixel vote: the same
  bubbles, found in 0.46 s instead of 5.2 s on a demo sheet. A scanned demo P&ID is now read in
  2.3 s instead of 6.8 s, with the same tags on all 14 sheets.
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
