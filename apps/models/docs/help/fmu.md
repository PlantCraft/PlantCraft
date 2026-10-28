# Exporting FMUs

An FMU (Functional Mock-up Unit) is a model packed as a standard file (FMI, the Functional
Mock-up Interface) that other tools can run: PlantCraft Analytics, and most simulation tools.

**Export FMU** (the package button on a model's page, or on the code editor's toolbar) builds one
from the model:

| Choice | Meaning |
|---|---|
| FMI version | 2.0 (read by the most tools) or 3.0 |
| Type | **Co-simulation**: the FMU carries its own solver (CVODE) and steps itself; this is what PlantCraft Analytics runs. **Model exchange**: the tool running it brings the solver. **Both** |

The FMU is built for Linux (64-bit), with its libraries inside, so it runs without OpenModelica.
The export runs in the queue: its page shows the FMI version, the platform, the inputs, outputs and the
number of parameters, and **Download the FMU**.

## Using it elsewhere

**Download the FMU** and use it in any tool that runs FMUs. Exports are listed under
**Simulations › Queue**, with every simulation.

Models does not send FMUs to Analytics: models are for study and never run on the plant. A model
meant for a tool that runs it against the plant has top-level inputs (what the plant gives it:
flows, openings, setpoints) and outputs (what it predicts: levels, temperatures). The **Analytics
models** examples hold the models Analytics ships for the Simulator's loops.
