# PlantCraft Models roadmap

Readiness per area (0-100 %, estimated), updated with every change that moves one. Last review
2026-10-24.

| Area | Ready | What is there, what is missing |
|---|---|---|
| Block diagram models | 70 % | Simulink-like diagrams in the suite's editor, simulation settings, read-only examples with Duplicate, text kept as Modelica; missing subsystems (a diagram as a block) and line routing |
| Files | 75 % | Packages as folders, `package.order`, versions, Code view; missing git |
| Text editor | 75 % | Highlighting, class completion, errors on lines, conflict-safe saves; missing member completion and go to definition |
| Diagram | 65 % | Icons and connections from annotations, add, move, rotate, delete, connect, parameters; missing line routing, icon editing, dialog tabs and groups |
| Library | 60 % | MSL 4.0.0 browser, search, class view; missing other libraries and library upload |
| Simulation and plots | 85 % | Solvers, overrides, plots, compare runs, CSV, plant inputs and comparison; persistent queue with progress and cancel; missing optimisation |
| Studies | 80 % | Grids over ranges and lists built once per batch, ranking with overshoot, settling time and IAE, overlay coloured by a parameter, envelope, statistics, export for Jupyter; optimization studies (SciPy, one simulation at a time, resumed after a restart); missing a fit to plant data and an embedded notebook |
| Blocks | 75 % | Six shipped libraries (28 blocks) in the suite's block editor, a page per block, libraries of the site's own in code; missing a form to write a block |
| FMU export | 80 % | FMI 2.0/3.0, CS/ME, Linux 64-bit; missing one-click hand-off to Twin |
| Sandbox | 80 % | Runner container without network or secrets, limits, policy checked twice; missing seccomp profile |
| Suite integration | 70 % | Runs on PlantCraft, asset page, audit, frame, help, tour; compose/proxy entry in PlantCraft |
| Packaging | 60 % | App and runner Dockerfiles, SBOM, signed package target; runner image not yet in the bundle CI |
