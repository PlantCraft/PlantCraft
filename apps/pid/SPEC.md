# SPEC: PlantCraft PID

What the app does and the public sources it relies on (AGENTS.md, "Clean room").

## Purpose

Read the plant's P&IDs into a plant map an engineer checks: what equipment and instruments are
drawn, what feeds, measures and controls what, the control loops, and the lines from one sheet to
another. Moved out of PlantCraft Documents on 2026-11-01 to be the suite's first closed app.

## Objects

| Object | Holds |
|---|---|
| Drawing | number, title, unit, its revisions (each a file kept by SHA-256), status of the reading |
| Diagram | one page of a drawing's current revision read as a P&ID: items, relations, notes |
| Review | Correct / Wrong on an item (by tag) or a relation (`from|type|to`), kept by name |

## Reading

PDF from CAD (pdfplumber), SVG, DEXPI / Proteus XML (its own reader; pyDEXPI is AGPL and not
used) and scans (tesseract OCR when the image has it). Each reader runs in a worker process with
time and memory limits (plantcraft_sdk.sandbox). Symbols follow ISA-5.1 tags and DIN/ISO 10628
shapes. A language model may read a scanned page again when an administrator gives the use
`diagram-read` a model (off by default).

## API

`/api/drawings` (list, send, read, change, delete), `/api/diagrams`, `/api/plant-map`
(map, reviews, lists as CSV, `asset-file`, `dexpi.xml`, `summary.md`), `/api/license`, and the
suite's search, references and widgets. Every route but meta, help, licence and health answers
402 when the licence is not usable.

## Licence

`plantcraft_sdk.licensing`: an Ed25519-signed `.pclicense` for app `pidcraft` and this
installation; limits: `sheets` (drawings held). The publisher's public key is compiled into
`pidcraft.licence`.

## Sources

ISA-5.1 (instrument symbols and identification), ISO 10628 (diagrams for the chemical and
petrochemical industry), the DEXPI specification and its public Training Test Cases (CC BY 4.0,
ATTRIBUTION.md).
