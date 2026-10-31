# Devlog

Notes on how the module changed and why, newest first: what a later contributor would need to
know that the code and `CHANGELOG.md` do not say. One short entry per change worth explaining.

## Unreleased

- DCS alarm list import (L1): an imported rule carries `external_id` (`<tag>/<type>`) so the next
  export matches it alarm by alarm; the editors do not send it, so `PUT /rules` keeps the stored
  one. The .xlsx reader is the standard library's (zipfile and ElementTree, size-capped) to avoid
  a new dependency in the image; a removed alarm is turned off, not deleted, so its journal and
  any manual settings survive a mistaken export. Apply claims the draft first (one apply only)
  and updates each rule against the `updated_at` read with the file.

## 0.5.1

- The repository's public history starts here; earlier releases are summarized in `CHANGELOG.md`.
