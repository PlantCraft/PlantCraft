# Blocks and algorithms

`plantcraft_sdk.blocks` (0.11.1) is the suite's dataflow contract. PlantCraft Analytics builds its
monitoring algorithms with it; PlantCraft Models will use the same blocks, diagrams and editor
for orchestration. An app owns its catalog of blocks, where its diagrams are stored and what its
output blocks do; the contract, the checks, the run and the descriptions are shared.

## A block

A block is one calculation with typed, described ports (`BlockSpec`, `Block`):

| Type | On the wire | Example |
|---|---|---|
| `series` | numeric values in time (`pandas.Series`), with a unit | PV, filtered PV, SP − PV |
| `state` | text or discrete values in time | controller mode |
| `number` | one value per run (`float`) | stiction index |
| `result` | status, score 0-100 (100 is best), one sentence (`Result`) | a block's verdict |
| `intervals` | parts of the window (boolean `pandas.Series`) | time in manual |

- A wire joins an output to an input that accepts its type; the one conversion on the wire is
  `result` to `number` (the score). An input may accept several types and, when `multiple`,
  any number of wires (it receives a list).
- `required` inputs must be wired. An output with `record` is written to the historian by
  default; a diagram node switches recording per output (`"record": ["index"]`).
- Parameters are a Pydantic model: every field has a description and, where it has one, a unit
  (`Field(json_schema_extra={"unit": "s"})`).
- `run(inputs, parameters, context)` returns a dict of outputs. `context` has the window, the
  asset, the app's `extra` and the node's own `state` between runs.

## Descriptions, one format

People read them in the editor and the help; the suite's assistants answer from them. Each
block has a name, a one-sentence `summary`, a `description` of how it works, `reading` (what ok,
warning and bad mean), `assumptions`, `limitations`, `formula` and `references`; every port and
parameter is described. An algorithm has `purpose`, `assets`, `when`, `reading` and
`assistant` (`AlgorithmDocs`). `check_block`, `check_algorithm` and `check_catalog` hold them to
the format (an app's tests fail on any problem); `block_markdown` and `algorithm_markdown` write
them with the same headings in the same order.

## A diagram

```json
{"version": 2,
 "nodes": [{"id": "pv", "block": "input.signal", "parameters": {"role": "pv"}, "x": 40, "y": 60},
           {"id": "st", "block": "cpm.stiction", "record": ["index"]}],
 "edges": [{"source": "pv", "source_port": "value", "target": "st", "target_port": "pv"}]}
```

`compile_diagram(diagram, catalog)` checks it: known blocks, valid parameters, wires between
ports of matching types, one wire per input unless `multiple`, required inputs wired, no loops,
at least one output (a block without outputs, or what the app's `sinks` says). Errors and
warnings come back in words, also per node (`node_errors`, `node_warnings`) for the editor.
`execute(plan, catalog, context)` runs the blocks in `graphlib` order. A block that raises, or
whose required input carries `NoData`, gives `NoData` with the reason on every output, so only
the blocks after it go without a value. An optional input carrying `NoData` counts as not wired
(the block gets `None` there and runs on what it has), unless none of the block's wired inputs
has a value. `runs_on_missing` blocks (a "worst of", an output) get every value as it is,
`NoData` included, and decide.

No graph library is used: the engine is the standard library's `graphlib` plus Pydantic
(evaluated on 2026-10-22 against pipefunc, Hamilton, Kedro, pydra, PathSim and TensorFlow; see
PlantCraft Analytics's `docs/blocks-and-algorithms.md`).
