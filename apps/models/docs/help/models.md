# Models

Models draws process models as **block diagrams** and simulates them over time, like Simulink:
blocks with inputs and outputs are wired together, you choose the start, the stop, the solver and
its step, and **Run** integrates the diagram. Behind the diagram is Modelica, the open language for
models of physical systems, and OpenModelica computes it.

Models is for study: what a bigger tank or another tuning would do. It never runs on the plant;
algorithms that run on the plant's data belong to Analytics.

## The words Models uses

| Word | What it is |
|---|---|
| **Block** | A piece with inputs, outputs and parameters: a step, a gain, a transfer function, a PID, a tank, a scope. Blocks come in libraries (**Blocks** in the menu). |
| **Model** | Blocks wired into a diagram, with its simulation settings: a level loop, a heat exchanger. |
| **Simulation** | One run of a model: its settings, its results and its messages. |
| **Study** | A model run over a grid of parameter values, to compare the simulations and find the best. |
| **Simulations** (page) | Everything that ran: the studies and each model's single simulations, with the queue. |

## Where to start

1. **Models** lists the models. Three examples are there from the start: **TankLevelControl**
   (a PID holds a tank's level by its feed pump), **HeatExchangerOutlet** and
   **FirstOrderDeadTimeLoop**.
2. Open **TankLevelControl**. Its page has the tabs an algorithm has in Analytics: **Overview** (what
   it is), **Inputs and outputs** (what it reads, what its scopes show and every block's
   parameters: the block's default unless the model sets its own value), **Diagram** (the
   setpoint, the controller, the pump, the tank, the level transmitter and two scopes; **Open the
   editor** opens it in a window of its own), **Test**, **Used by** (the studies of the model),
   **Versions** and **Settings** (from when to when, with which solver and step, and where the
   model is kept). Saving a change makes a new version and asks what changed.
3. On **Test**, press **Run the test**: one simulation with its settings, a check. The results
   plot what the scopes show: the level following its setpoint.
4. A study is what runs a model for real: on **Studies**, press **New study**, choose the model,
   set `tank.A` to a range from 2 to 6 in 5 values and `tank.Cv` to the list 0.03, 0.05, 0.08:
   fifteen simulations start, and the study's page ranks them by the indicator you choose and can
   draw them side by side, one chart per tank size. A value the study does not set is the
   model's, and one the model does not set is the block's default.

Examples stay as Models ships them. **Duplicate** makes your own copy to change.

**Compile** on a model's page builds the model as it is now and keeps the compiled version with
it: an FMU (FMI 2.0, co-simulation), the form Analytics runs. Beside the button the page says
whether the model is **Compiled** (and from which version), **Out of date** (it, or a block it
uses, changed after the compilation), **Compile failed** or **Not compiled**. The Overview's
**Compiled version** says when and by whom, how long it took and what omc said, downloads the FMU
and lists the last three compilations. Test and the studies still compile in the runner as they
run; a study reuses the build its batches share.

A block's page has the tabs of a block in Analytics: **Overview** (how it is drawn, what it does,
how to read it and its formula), **Inputs and outputs** (its ports and parameters), **Code**,
**Used by** (the models that place it) and **Versions**. The blocks Models ships stay as they are;
**Duplicate** copies any of them into this site's own library, where its defaults change on
Inputs and outputs and each save is a new version that says what changed. A value set on a model
wins over the block's default, and one set by a study wins over the model's.

There is one kind of model: a diagram of blocks. A model written in Modelica code (the furnaces
Analytics learned from, say) is one block of its own diagram: its real inputs and outputs are the
block's ports and its parameters the block's settings. Its equations stay in the code, one click
away (**Modelica code**).

## Who can do what

| Role | Can |
|---|---|
| Viewer | Read the models, blocks, studies and simulations with their plots and messages |
| Editor | Everything else: draw and save models, run them, start and cancel studies, export FMUs, write block libraries |

## Where things are kept

Models, block libraries, simulations, their results and FMUs are kept by Models in the suite's data
folder. A simulation keeps a copy of the model as it was when it started, so its results always match
the diagram that made them. **Code** on a model's page shows its Modelica text.
