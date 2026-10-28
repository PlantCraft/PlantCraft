# Studies

A **study** runs one model over a grid of parameter values and compares the simulations: which tank
size holds the level best, how much heat exchanger area is enough. Start one with **New study**
on the Studies page and choose any model, or with **New study** on a model's page, which opens
the same page with that model chosen (`/studies/new`).

## Setting it up

| Field | Meaning |
|---|---|
| Parameters | Each parameter of the diagram's blocks keeps the **Model's value**, takes a **Fixed** one, or varies over a **Range** (from, to, how many values, evenly spaced) or a **List** of values |
| Indicators | Variables measured in every simulation; the scopes' signals come first |
| Simulation settings | Start, stop, intervals, tolerance and solver, from the model's simulation settings |
| Time limit per simulation | Optional, in minutes: a simulation that takes longer is stopped |

Every combination of the varied values is one simulation: 5 values of `tank.A` and 3 of `tank.Cv` make
15. The **Preview** beside the form says how many before you start, what varies, and about how long they take
(from this model's last simulations and the number of workers). Above 100 it warns; a study
holds at most 500 simulations unless an administrator changes `MODELCRAFT_STUDY_MAX_RUNS`.

OpenModelica builds the model once and then only changes the parameters (the runner keeps the
built model for the study's next batches of up to 10), so a sweep costs far less than as many
separate simulations.

## Optimization: find the best values

On the new-study page, **Find the best values** turns the study into an optimization: instead of
every combination, it looks for the values of a few inputs or parameters that make one indicator
best, one simulation at a time, each chosen from the results of those before.

| Field | Meaning |
|---|---|
| Optimize | In the parameters table, an input or parameter set to **Optimize** gets its **smallest** and **largest** value and, optionally, where the optimizer **starts** (the middle of the bounds when empty). Up to 10 |
| Objective | A variable and one of its indicators (final value, overshoot, settling time, IAE, ...), to **Minimize**, **Maximize** or **Reach a value** (the squared distance to the target is minimized) |
| Constraints | Optional: other indicators kept below or above a limit (`tank.level` largest ≤ 2.5). Up to 10 |
| Method | **Automatic** takes Nelder-Mead, or COBYLA when there are constraints. **Nelder-Mead** (no derivatives, no constraints), **COBYLA** (no derivatives, with constraints), **SLSQP** (gradients by finite differences, with constraints; fewer simulations on smooth problems, but each step costs one simulation per value) |
| Most simulations | The optimizer stops when the best values change no more, or here (60 by default) |

The methods are SciPy's (`scipy.optimize.minimize`). The values are scaled to 0..1 between their
bounds, so the first steps (a quarter of each range) suit every unit. A simulation that fails costs
the optimizer a very large value, so it moves away from it. The best simulation is the one with
the best objective among those that meet every constraint; when none does, the one closest to
meeting them, said so on the page.

The study's page opens with the **Optimization** panel: how it goes, the best values beside their
start and bounds, a link to the best simulation, and a chart of the objective of every simulation
(those that miss a constraint in another colour) with the best so far. The rest of the page reads
as any study's: every simulation the optimizer asked for is in **Simulations**, with its values.

Optimizations are sequential (each point depends on the last): about 20 to 60 simulations for two
or three values. The runner builds the model at the first one and keeps it, so every next step
only runs it (about a second each for the examples). If PlantCraft restarts during one,
it goes on by itself at the next start: the optimizer asks for the same points again and the
simulations it already has answer at once. **Cancel the rest** stops it.

## Reading a study

- **Ranking** orders the simulations by an indicator and a statistic: final value, smallest, largest,
  mean, integral, **overshoot** (how far past its final value it went, in %), **settling time**
  (when it last entered the 2 % band around its final value) and **IAE** (the integral of the
  absolute error from the final value). **Best is** says whether smaller or larger wins; the best
  simulation is highlighted and named above the table. Click a simulation to open it.
- **Results** overlays one variable of every finished simulation. **Colour by** a varied parameter
  shades the lines from light (smallest value) to deep (largest); **Envelope** draws the band
  where 90 % of the simulations fall and their median. **Indicator against a parameter** plots one
  indicator of each simulation against a varied parameter.
- **Simulations** lists the simulations with the values each used. Tick some and press **Compare
  these** to overlay only those.
- **Statistics over the simulations** gives, for every indicator, the mean, standard deviation and
  percentiles over the simulations.
- **Side by side** draws one small chart per value of a varied parameter, all on the same
  vertical scale, so the outputs of each choice sit next to each other; within each chart the
  lines are shaded by the other varied parameter.
- **Run again with changes** opens the new-study page with the same settings.

**Cancel the rest** stops the study's running simulations and takes its waiting ones out of the
queue. A simulation that fails (a parameter value the model cannot take) is marked failed; the
others go on.

## Export for Jupyter

**Export for Jupyter** downloads a .zip with:

| File | What |
|---|---|
| `parameters.csv` | One row per simulation: its id, its values and its indicators |
| `results.csv` | Every point of every finished simulation: `run_id`, `time` and the variables |
| `study.ipynb` | A notebook that reads both with pandas and plots the indicators |
| `study.json` | The study's settings |
| `model/` | The model's Modelica files as they were |

Open it in Jupyter, JupyterLab or VS Code. The notebook only needs pandas and matplotlib.
