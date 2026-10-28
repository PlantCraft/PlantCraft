# Algorithms

An algorithm is a diagram of blocks: signals go in on the left, flow through data quality
checks, transforms and methods, are combined, and come out as outputs on the right. Every wire
joins two ports of the same type, and the algorithm is checked before it runs or is saved: a
block with an input not wired, a wire between ports that do not match, or a loop in the wiring
is marked on the block, in words.

PlantCraft ships six algorithms, read-only, with **PlantCraft** as their author:

- **Flow loop**: the default of flow loops and of loops of an unknown kind. PV–SP error,
  output saturation and sampling quality make the health (0 to 100); valve travel and stiction
  are judged with them; oscillation and noise are flagged beside it; manual mode, setpoint moves
  and interventions are context.
- **Level loop**: the default of level loops, for levels held tight at their setpoint: error,
  output and valve travel make the health; oscillation and stiction are flagged beside it.
- **Surge level**: for levels that should absorb upsets inside a band.
- **Temperature or pressure loop**: the default of temperature, pressure and composition loops:
  slow loops judged by the Harris index (variance against minimum-variance control) beside the
  error and the output.
- **Signal quality**: the data quality checks on every signal, on its own monitor.
- **Unit twin**: a process model runs beside a unit on its own signals, and the difference
  between what it predicts and what the plant measures is judged against normal operation. It
  runs on assets.

On the Simulator demo plant, Analytics adds its twins (the furnaces and the process models of two
loops) by itself the first time it finds the plant: calibrated on the last hours and scheduled on
their assets, so the models run from the start. A twin deleted stays deleted (**Add the plant's
model examples** brings it back). The valve and oscillation checks are blocks
of the *Control loop performance* library: draw them into any algorithm.

Every algorithm has **labels** (control loop, data quality, digital twin, or your own), an
**owner**, a **version** (each save adds one) and, when it is set, a **responsible group**: the
group's members and coordinators edit it, the others read it. The list says how many assets use
each one.

To change one, **Duplicate** it and edit the copy; a loop or a monitor then uses the copy.

## Drawing an algorithm

Open an algorithm and the editor opens in its own window. Drag blocks from the palette on the
left (search by name), wire an output to an input (compatible inputs light up), and set a
block's parameters in the panel on the right, where every port and parameter is described.

- **Wire colours** say what flows: blue a signal over time, violet the mode, amber a number,
  green a result (ok, warning, bad or unknown, with a 0-100 score and a sentence), grey a
  condition (parts of the window).
- **The loop data check** sits after the signals: it passes PV, SP, OP and mode on when the
  data is usable, and nothing (with the reason) when it is not, so the methods after it do not
  judge bad data.
- **Transforms** prepare signals: arithmetic (*Expression* such as `a * b / c`, *Engineering
  unit*), filters (*Moving average*, *Low-pass filter*, *Derivative*, *Resample*, *Detrend*,
  *Delay*), *Select by condition* and *Only in operation*, which keeps steady operation and
  leaves out start-ups and shutdowns.
- **Statistics** summarise a signal over the window, or only where a condition holds: *Mean*,
  *Standard deviation*, *Percentile*, *Histogram*, *Correlation* (with the best lag), *Step
  changes* and *Time outside limits*.
- **Equipment**: *Heat exchanger UA* (follows fouling against the clean UA) and *Pump
  efficiency* (against the manufacturer's curve).
- **Conditions** (grey wires) mark parts of the window: *Compare with a limit* (a feed flow above
  its minimum: the unit runs) and *AND / OR / NOT* to combine them.
- **Logic**: *Worst of* keeps the worst result; *Average* scores the mean against two limits;
  *Rule* replaces a result when a test is bad ("if the PV data is bad, the valve result is not
  trustworthy"); *Limits* turns a number into a result.
- **Outputs**: *Loop health* (the loop's health and findings), *Result on the asset* (a named
  result every app reads), *Message* (an event when its input turns bad, closed when it
  recovers). Any number, result or series can also be **recorded in Historian** with the toggle
  on its port: Trends, Dashboards and the assistant then read it. On assets, each monitor says
  in its **Recorded outputs** which of them it keeps and for how long (a result forever, other
  values 400 days, a series its last 10 runs, by default), with what that costs; the
  Historian shows a series' runs one over the other.

**Test** runs the diagram on one loop's recent data without saving anything and shows on each
wire what it carried. After saving, **Monitor** runs it every N minutes on all loops or chosen
ones; each run appears in **Results > Run history**. The panel beside the diagram says **where
it is used**: the loops that use the algorithm and its monitors.

Each algorithm has its documentation in the same five parts (what it is for, the assets it
reads, when to use it, how to read its result, instructions for the assistant). What is left
empty is written from the diagram, and the assistant reads it when someone asks about the
algorithm.

## Algorithms on assets and process models

An algorithm can also work on **assets**: a unit, a furnace, any asset of PlantCraft. Choose
*Assets* under *Works on*, then name the assets and set how often it runs (from every 10
seconds), how far back each run reads and the step it reads on. Its Signal blocks read a role of
the asset, a role of another asset (a loop of the unit) or a signal by its id. **Test** runs it
on one asset's window, ending now or at a moment you choose; the algorithm's page shows its
latest run on each asset, and an asset's page lists the algorithms that run on it.

The **Models** library holds a block per published process model (an FMU): its inputs are the
model's inputs, plus the measured value of each output, and it gives what the model predicts
and the residual (measured minus predicted). Wire the residuals to a **Deviation (T²)** block,
which judges them against normal operation.

A model comes from PlantCraft Models: on an exported FMU's run, an administrator presses
**Publish to Analytics**, and the model is a block of the library at once. **Build an algorithm with
it** there (or **New algorithm with this model** on the block's page) opens the editor on a new
algorithm on assets around the model: a Signal block on each input and output, the model,
Deviation, a result and a message. Choose the role behind each Signal block, calibrate, pick the
assets and save.

**Calibrate** teaches the Deviation block what normal looks like. Select the block, choose an
asset and a period when the unit ran normally, and press *Calibrate*: the algorithm runs over the
period as it would have, run after run, and the residuals' mean and spread become the block's
calibration. It says how many runs it used, which it left out and why, and warns when a residual
sits far from zero (the model or a sensor offset). Save the algorithm to keep it; until a block
is calibrated it judges nothing and says so.
