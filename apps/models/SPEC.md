# PlantCraft Models spec

Category: equation-based modelling and simulation of physical systems in the Modelica language:
writing models as text and as diagrams from component libraries, checking, simulating and
plotting them, and exporting them as FMUs for other tools. Tools studied (research only, public
behaviour): OpenModelica (OMEdit, its graphical editor), Dymola (Dassault Systèmes), Wolfram
System Modeler, Modelon Impact (browser based), Altair Activate, Claytex/Modelon libraries, and
the FMI tool list. Sources are public only (clean room, see AGENTS.md); no code of these tools is
used. OpenModelica's compiler (omc) is used as a separate program in its own container, never
linked into this code.

## Sources

| Source | Link | Read on |
|---|---|---|
| Modelica Language Specification 3.6 (graphical annotations: section 18; packages, `package.order`: section 13) | https://specification.modelica.org/maint/3.6/MLS.html | 2026-10-21 |
| Modelica Standard Library 4.0.0 (BSD-3-Clause) | https://github.com/modelica/ModelicaStandardLibrary/releases/tag/v4.0.0 | 2026-10-21 |
| OpenModelica User's Guide: scripting API (`checkModel`, `simulate`, `buildModelFMU`, `getModelInstance`), simulation flags (`-override`, `-csvInput`), OMEdit | https://openmodelica.org/doc/OpenModelicaUsersGuide/1.24/ | 2026-10-21 |
| Functional Mock-up Interface 2.0.4 and 3.0 specifications | https://fmi-standard.org/downloads/ | 2026-10-21 |
| Dymola, Wolfram System Modeler and Modelon Impact public product pages and manuals (features only) | https://www.3ds.com/products/catia/dymola, https://www.wolfram.com/system-modeler/, https://modelon.com/modelon-impact/ | 2026-10-21 |
| Vendor research of the suite (thread "Pesquisa de apps de fornecedores", 2026-10-20) | Claude Doc in the project | 2026-10-20 |
| PlantCraft API v1 and the app standard (`docs/api-v1.md`, `docs/app-standard.md`) | PlantCraft repository | 2026-10-21 |

## Features of the category

| Feature | Status | Notes |
|---|---|---|
| Block diagram models (Simulink-like): palette, wires, feedback loops, simulation settings beside the diagram | done | Suite's `BlockEditor`; written as Modelica declarations and `connect()`; six libraries, 28 blocks |
| Models as Modelica packages, folders, `package.order` | done | Code view per model; 50 versions per file |
| Text editor: highlighting, completion, errors on lines | done | CodeMirror 6; completion of library and project class names (no completion of component members yet) |
| Check model (equations and variables, errors with lines) | done | omc `checkModel` |
| Diagram view from annotations (icons, placements, connections) | done | Line, Polygon, Rectangle, Ellipse, Text; Bitmap drawn as a frame |
| Diagram editing: add from library or project, move, rotate, delete, connect, disconnect | done | Every edit is a text edit; connection routing is a simple elbow, no manual line points yet |
| Parameter dialog of a component | partial | Flat list with units and descriptions; no `Dialog(tab, group)` layout, no choices for enumerations or `replaceable` |
| Library browser with search, icons, documentation, text | done | MSL 4.0.0; other libraries (Buildings, ThermoSysPro...) not shipped |
| Documentation view | done | Shown sandboxed, no scripts |
| Simulation: solver (variable or fixed step), start, stop, step, tolerance saved with the model; parameter overrides | done | `experiment` and `__OpenModelica_simulationFlags`; omc `simulate` with `-override`; at most 200 000 steps |
| Plot results, several variables, compare runs, CSV | done | Thinning keeps min and max per bucket |
| Plant data as inputs and comparison | done | Signals through PlantCraft, last value held |
| FMU export, FMI 2.0 and 3.0, CS and ME | done | Linux 64-bit, CVODE inside for CS |
| FMU import (use an FMU inside a model) | missing | |
| Studies: one simulation or a parameter sweep (ranges and lists, every combination), indicators per simulation | done | Built once per batch of 10 (`buildModel`, then the executable with `-override` per variant); 500 per study by default |
| Compare simulations: ranking by indicator (final, extremes, mean, integral, overshoot, settling time, IAE) with the best highlighted, overlay coloured by a parameter, envelope (P5–P95, median), indicator against a parameter, statistics | done | Study page; ticked simulations compared alone |
| Simulation queue: progress, cancel, priority, survives restarts, the suite's queue numbers | done | Queue in SQLite; single runs ahead of studies; `plantcraft-queue/1` on Executions |
| Export a study for Jupyter (CSV + notebook) | done | `parameters.csv`, `results.csv`, `study.ipynb`, `study.json`, model files; an embedded notebook (JupyterLite) later |
| Shared block libraries in groups | done | Global Modelica packages (`kind = library`), merged into every project's jobs; a project's own package wins |
| Optimization studies (SciPy Nelder-Mead, COBYLA, SLSQP on study indicators) | done | `docs/help/studies.md` |
| Fit to plant data, linearisation | missing | `docs/gaps.md` |
| Component templates (signal block, thermal, electrical) and systems built from project components | done | New class dialog; the project tree drags into a diagram |
| Icon editor, drawing graphical primitives | missing | Icons come from the text |
| Version control (git) of projects | missing | Versions per file only |
| Multi-user editing | partial | Saves are refused on conflict; no live co-editing |

## Decisions

1. **The text is the one source.** The diagram is drawn from omc's instance of the class
   (`getModelInstance`) and every diagram change is a small, local text edit
   (`modelica/edit.py`), so a project stays plain Modelica any tool can open.
2. **omc runs in its own container**, with no network, no secret, a read-only root filesystem,
   CPU, memory, process and time limits, sharing only a jobs folder with the app. The app never
   runs omc itself in the suite.
3. **Defense in depth on what a model may run.** `external` functions and
   `Modelica.Utilities.System/Files/Internal` (however aliased) are refused by the app before a
   job leaves and by the runner again; the administrator may allow `external` code.
4. **Runs keep the model's files** as they were, so results always match a model.
7. **Blocks are shared** (owner, 2026-10-23): block libraries are global and grouped, like
   Link's algorithms. Every simulation belongs to a study (quick, single or sweep); FMU exports
   are listed apart. Projects are no longer shown (2026-10-24): each model is stored as one
   package, the person sees models.
8. **The queue is the database**: runs wait as rows (`status = 'queued'`, a priority), a
   dispatcher thread hands batches to the runner, and a restart requeues what was running. Path
   A for blocks: Modelica stays underneath; the suite's block editor goes on top once Link's
   editor settles.
5. **Plant data only through PlantCraft**, read with the person's own token; nothing is
   written to the plant.
6. **The Twin hand-off is a file**: the FMU is downloaded and uploaded in Twin (apps never call
   each other); a file exchange through PlantCraft would make it one click (`docs/gaps.md`).
9. **Models is Simulink-like and for study only** (owner, 2026-10-24): a model is a block
   diagram integrated over time with its own solver and step; it never runs on the plant. Link
   runs algorithms at an instant over a data window. Nothing is published to Link for now; a
   later "Publish to Link" would be a form mapping inputs to asset roles.

## Not yet (see docs/gaps.md)

Parameter dialog tabs and groups, more libraries, optimisation,
linearisation, FMU import, icon editing, git, a Portuguese catalog.
