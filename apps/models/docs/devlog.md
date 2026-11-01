# Devlog

Notes on how the module changed and why, newest first: what a later contributor would need to
know that the code and `CHANGELOG.md` do not say. One short entry per change worth explaining.

## 0.5.1

- The repository's public history starts here; earlier releases are summarized in `CHANGELOG.md`.
- 2026-11-01: compiled models. The kept compiled version is the FMU, not the runner's program:
  build files never leave the sandbox (`runner.py` KEEP), and its build cache lives on a 512 MB
  tmpfs that a restart empties. A compilation is an `fmu` run with `options.compile` and
  `options.source` (the digest of the files with the shared blocks and the class, `source_of`);
  the state compares that digest with the current one, so a block library's change makes a
  model out of date too. Versions are matched by the same digest over each kept revision.
