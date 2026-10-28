# Simulating

**Run** on a model's page saves the diagram and simulates it with its **Simulation settings**:

| Setting | Meaning |
|---|---|
| Start, Stop | The simulated period, in seconds of model time |
| Solver | How the equations are integrated in time (below) |
| Step | With a fixed-step solver, the integration step; with a variable-step one, the output step (one result point per step) |
| Tolerance | The relative tolerance of a variable-step solver |

| Solver | When |
|---|---|
| DASSL (the default), IDA | Variable step BDF: stiff systems and most process models |
| CVODE | Variable step: smooth systems |
| Euler, Heun, Runge-Kutta | Fixed step, explicit: non-stiff systems |
| Implicit Euler, Trapezoid | Fixed step, implicit: stiff systems at a fixed step |

A simulation holds at most 200 000 steps. The settings are saved with the model (its `experiment`
annotation), so every simulation and study starts from them.

A model runs once every input of every block has a wire; the diagram marks what is missing.
Feedback loops (a controller reading the level it moves) are allowed.

## The results

The results below the diagram plot what the model's **scopes** show. Open the simulation for its own
page:

- the variables picked on the left (up to 12); **Main** hides derivatives and protected
  variables, **All** shows every one; each shows its final value;
- **Compare with** draws the same variables of another simulation of the same model, dashed;
- **Results as CSV** downloads every variable at every point;
- **Messages** lists what OpenModelica and the solver said.

A simulation that fails is marked **Failed** and its messages say why: an equation that could not be
solved, a division by zero, a step too large for the solver.

## Simulations and the queue

**Simulations** is laid out as Analytics' Results, with the study in the monitor's place and the simulation
in the asset's. **By study** lists each study (and each model's **single simulations**, what Run
starts) with what it varies and how its simulations ended; open one for a summary and its
simulations, and a simulation for its results. **Queue** shows what runs and what waits, now
and over time (the same panel as every app of the suite), then every simulation. Two simulations run at the same time by default (an administrator sets
`MODELCRAFT_RUN_WORKERS`); single simulations go ahead of studies, so a long study never blocks a quick
check. A simulation stops after its time limit (at most 6 hours, `MODELCRAFT_MAX_RUN_SECONDS`).
