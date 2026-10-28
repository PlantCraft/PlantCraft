# Gaps

Known gaps, with the date they were found.

- 2026-10-26: files are read in the app's own thread, not yet on a compute worker's executor
  without network (plan D2). A malicious file is still bounded (zip-bomb check, 5,000 pages,
  200 MB) and runs as the app's unprivileged user in its read-only container.
- 2026-10-26: a scanned PDF without text is refused with the reason; OCR is not built in.
