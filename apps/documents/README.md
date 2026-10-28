<p align="center"><img src="docs/images/logo.svg" width="72" height="72" alt="PlantCraft Documents"></p>

# PlantCraft Documents

The plant's documents in one library: operating manuals, control narratives, P&IDs, datasheets,
procedures, troubleshooting guides, maintenance records and incident reports. Each file is read
into passages that keep their page and section, the plant's tags found in them link them to the
assets, and a search by words and by meaning finds them. The suite's assistant searches and reads
them as the person who asks and cites the document, revision and page of each fact, so a question
such as "why does FIC-1003 cycle?" is answered from the plant's own troubleshooting guide and
maintenance history.

Everything runs offline, inside the suite: the reading (pypdf, python-docx, openpyxl,
python-pptx), the word index (SQLite FTS5), the meaning model (multilingual-e5-small in ONNX,
bundled in the image) and the search. The original files stay in the app's own data folder.

The suite was built with Claude Code; it is meant to be used with an assistant.

## Run it

```sh
make ci       # app standard, lint, interface build and tests, pytest
make dev      # the Simulator, PlantCraft on :8060 and Documents on :8150
```

In the suite it is the `doccraft` profile of PlantCraft's `deploy/compose.yaml`
(`install.sh --with-doccraft`). The demo seed (`processcraft demo seed`) sends the Simulator
plant's twelve demo documents (`deploy/demo/documents/` in PlantCraft).

## What each part does

| Path | What it is |
|---|---|
| [`app.toml`](app.toml) | The manifest: id `doccraft`, prefix `/doc/`, port 8150, uid 10015, permissions, and what it adds to PlantCraft (Ctrl+K, `#doc:` references, widgets, the assistant's tools and works). |
| `src/doccraft/library/` | The app's object. `extract.py` reads each kind of file into sections (page, headings); `passages.py` cuts them; `tags.py` finds the plant's tags; `embed.py` turns passages into vectors; `store.py` keeps folders, documents, revisions and passages (SQLite, FTS5, vectors); `search.py` fuses words and meaning; `indexer.py` reads one file; `service.py` the rules and the reading thread; `access.py` who sees which folder. |
| `src/doccraft/api/` | `runtime.py`, `deps.py`, `routers/` (`library.py` the pages' API, `tools.py` the assistant's tools, `search.py` Ctrl+K, `refs.py`, `widgets.py`). |
| `frontend/src/` | The pages: Overview, Library (folders, upload), a document (passages, assets, revisions, a Word file as a page), Search. The files being read are in the suite's Queue. All on `@plantcraft/ui`. |
| `tests/` | pytest against `FakePlantCraft`; `tests/files/` a small PDF of the demo plant. |
| `Dockerfile`, `deploy/` | The image: hashed dependencies, the embedding model checked against `deploy/embedding-model.lock`, non-root, read-only root. |

## The rules

[`AGENTS.md`](AGENTS.md) lists the rules of this app and points to the suite's standard
(PlantCraft `docs/app-standard.md`). [`SPEC.md`](SPEC.md) says what it does and why.

## License

Apache-2.0 ([LICENSE](LICENSE)). Third-party libraries and the model: [ATTRIBUTION.md](ATTRIBUTION.md).
