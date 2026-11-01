# Devlog

Notes on how the module changed and why, newest first: what a later contributor would need to
know that the code and `CHANGELOG.md` do not say. One short entry per change worth explaining.

## 0.1.0 (2026-11-01)

- Made from the app template and the plant map of PlantCraft Documents. Apps do not call each
  other, so PID keeps its own drawings instead of reading Documents' files; the summary that
  Documents wrote as a library document is now a Markdown download.
- Closed: Nuitka `--mode=module` (one `.so`, about 4 MB, 45 s); data files are copied beside it.
  Compiled modules have `__compiled__`, and their `__file__` still ends in `__init__.py`.

## 0.5.1

- The repository's public history starts here; earlier releases are summarized in `CHANGELOG.md`.
