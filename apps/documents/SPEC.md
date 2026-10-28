# SPEC: PlantCraft Documents

What the app does, the choices behind it and the public sources it relies on.

## Purpose

Give the suite's assistant, and the people using the suite, the plant's own documents as
context: a loop that performs badly is explained by its control narrative, the troubleshooting
guide, the valve's maintenance history and the last incident report, each cited by page.

## Objects

| Object | What it holds |
|---|---|
| Folder | Name, description, `viewers` and `editors` (`user:<name>`, `group:<id>`; empty means everyone, as View's folders), `assistant` (may the assistant read it). General holds what is in no folder. |
| Document | Number (`DOC-U200-OM-001`), title, kind, unit, language, folder, `assistant`, the assets it is about (`manual` by a person, `suggested` by the tags found). |
| Revision | One file of a document: revision, issued, file name, SHA-256, size, format, pages, status (`queued`, `indexing`, `indexed`, `failed`, `superseded`), the reason it failed. A new file with the same number is a new revision; the older one is superseded once the new one is read. |
| Passage | About 350 words of one revision (50 words of overlap, never across a heading) with its pages, section path, the assets its tags name and its vector. |

The original files are kept once per SHA-256 under `files/` in the data folder; the database is
`doccraft.sqlite3`. Defaults: 200 MB per file, 20 GB in all (`DOCCRAFT_MAX_FILE_MB`,
`DOCCRAFT_QUOTA_GB`).

## Reading

PDF (pypdf; headings from font size and bold, page by page), Word (heading styles and tables),
Excel (one section per sheet, each row as "column: value"), PowerPoint (one section per slide),
text, Markdown, CSV and HTML. A zip bomb and a PDF over 5,000 pages are refused. A scanned PDF
without text fails with the reason (text recognition, OCR, is a later option). Reading runs in
the app's own thread, never in the request; moving it to a compute worker's executor (no network)
is planned.

## Search

Both run on every question and are fused by reciprocal rank fusion (k = 60, 60 candidates each):

- **Words**: SQLite FTS5 (BM25, `unicode61` without diacritics), each word and tag of the
  question quoted and joined by OR, so tags such as `FV-1003` and numbers match exactly.
- **Meaning**: `intfloat/multilingual-e5-small` (384 dimensions, Portuguese and English in one
  space) in ONNX with 8-bit weights, through onnxruntime; exact cosine search with numpy (enough
  for hundreds of thousands of passages). Without the model files a hashed stand-in keeps every
  path working.

A passage naming the asset asked about scores ×1.5, a passage of a document linked to it ×1.2.
Folders the person may not see are filtered before ranking, never after.

## The assistant

Documents declares three tools (`[[contributes.assistant.tools]]`, SDK 0.61.0), which PlantCraft
calls as the person who asks:

| Tool | Answer |
|---|---|
| `search_documents(query, asset?, kind?, limit?)` | Numbered passages with document, revision, page, section and link, to cite as [n]. |
| `read_document(document, page?, section?)` | Up to about 12,000 characters of one document, by page or section. |
| `find_tags(tags)` | For each tag, up to 5 passages that name it: its own section first, then the text around each mention. PlantCraft's plant draft reads it. |

Text from a document is data: every answer says so, and documents or folders marked "not for the
assistant" are never returned. Each call is audited (`doccraft.assistant.search`,
`doccraft.assistant.read`, `doccraft.assistant.find_tags`).

## API

`GET /api/kinds`; `GET|POST /api/folders`, `PUT|DELETE /api/folders/{id}`;
`GET /api/documents` (`folder`, `asset`, `kind`), `POST /api/documents` (the body is the file,
the fields in the query), `GET|PATCH|DELETE /api/documents/{id}`, `PUT /api/documents/{id}/assets`,
`POST /api/documents/{id}/reindex`, `GET /api/documents/{id}/file` (`revision`, `inline` for a
PDF), `GET /api/documents/{id}/passages` (`page`); `GET /api/documents/{id}/view` (a Word file as a
page); `POST /api/search`; `GET /api/queue` (the suite's `plantcraft-queue/1`);
`POST /api/assistant/tools/{search_documents,read_document,find_tags}`; the suite's `GET /api/search`,
`/api/refs/doc/{id}`, `/api/widgets`, `/healthz`, `/api/meta`, `/api/help`.

## Sources

- ISA-5.1, Instrumentation symbols and identification (tag letters): the tag pattern.
- Wang et al., "Multilingual E5 Text Embeddings: A Technical Report" (2024), and the model card
  of `intfloat/multilingual-e5-small` (MIT): the "query: " and "passage: " prefixes, mean pooling.
- Cormack, Clarke and Büttcher, "Reciprocal Rank Fusion outperforms Condorcet and individual rank
  learning methods" (SIGIR 2009): k = 60.
- SQLite FTS5 documentation (BM25, the `unicode61` tokenizer).
- The demo documents in PlantCraft's `deploy/demo/documents/` were written for the Simulator's
  invented refinery from public engineering knowledge (valve stiction, PID tuning, alarm limits).
