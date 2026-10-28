# Security policy

## Reporting a vulnerability

Please report vulnerabilities privately. Do not open a public issue.

Use GitHub's private vulnerability reporting: go to the repository's
**Security** tab and choose **Report a vulnerability**
(https://github.com/PlantCraft/PlantCraft/security/advisories/new).

Include what you found, how to reproduce it, the affected version or commit
and the impact you expect. We will acknowledge the report, keep you informed
while we work on a fix and credit you in the advisory unless you prefer
otherwise.

## Supported versions

The latest release of the suite. Fixes ship in the next suite bundle.

## Scope and design notes

- **No plant connections, no plant writes.** PlantCraft Documents never talks to a DCS, PLC,
  historian or OPC UA server. Its only outbound connection is to the PlantCraft named by
  `PLANTCRAFT_URL` (`tests/test_suite_rules.py` fails on any other network module). The
  embedding model is in the image: nothing is downloaded at run time.
- **Sign-in is PlantCraft's.** Every route needs a PlantCraft token whose `apps` claim grants
  `doccraft`. Viewers read and search; editors send and change documents.
- **Folders decide who reads.** A folder lists its viewers and editors (people and PlantCraft
  groups). A document in a folder a person may not see answers 404 everywhere (page, file,
  passages, search, Ctrl+K, references, the assistant's tools). Search filters before ranking.
- **The assistant reads as the person.** PlantCraft calls the tools with the person's own
  token. A folder or a document marked "not for the assistant" is never returned to it. Text from
  a document is labelled as quoted material, never as an instruction (prompt injection inside a
  document is expected and contained by the platform's tool rules).
- **Untrusted files.** Files are parsed by pure-Python readers (pypdf, python-docx, openpyxl,
  python-pptx; no PyMuPDF, no macros run). Office files are checked against zip bombs (ratio
  100, 500 MB unpacked), PDFs above 5,000 pages are refused, a file is at most 200 MB and the
  library at most 20 GB. Parsing happens in a background thread, never in a request, as the
  app's unprivileged user in a read-only container. Moving it to a no-network compute executor
  is on the roadmap (`docs/gaps.md`).
- **Files are never shown as pages.** Originals are served as attachments with
  `Content-Security-Policy: default-src 'none'; sandbox` and `nosniff`; only a PDF may open
  inline, as `application/pdf` with `nosniff`, in the browser's own PDF viewer in a tab of its
  own (never inside the app's pages). HTML is served as text.
- **App key.** Read from `PLANTCRAFT_APP_KEY_FILE` (a Docker secret) or `PLANTCRAFT_APP_KEY`;
  used only to read the asset tree (tags) and groups. Never logged.
- **Audit.** Folder and document changes, downloads and every assistant call are recorded in
  PlantCraft's audit log (`doccraft.*`).
- **Container.** uid 10015, read-only root filesystem, state only in `/data`, scratch in `/tmp`;
  no build tools, not even pip. Dependencies from a hash-checked wheelhouse
  (`deploy/requirements.lock`); the model checked against `deploy/embedding-model.lock`.
