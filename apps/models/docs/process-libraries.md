# Open process libraries

Models runs any Modelica library that is in the runner image. Every job loads the Modelica
Standard Library 4.0.0. The libraries below are loaded only for a project whose files name them,
so they cost nothing to the projects that do not use them. This page records which libraries
ship, why, and how a model uses them.

## OMChemSim (shipped)

[OMChemSim](https://github.com/FOSSEE/OMChemSim), the OpenModelica Chemical Simulator, is a
library of chemical process models: about 450 components with their constants (the ChemSep
database), thermodynamic packages (Raoult's law, NRTL, UNIQUAC, Peng-Robinson, Grayson-Streed),
material and energy streams, and unit operations (mixer, splitter, heater, cooler, valve, pump,
compressor, flash, heat exchanger, reactors, shortcut and rigorous distillation, absorption).
FOSSEE (IIT Bombay) develops it under the **BSD-3-Clause** license.

- The runner image fetches it at a fixed commit (`deploy/runner/Dockerfile`,
  `OMCHEMSIM_COMMIT`) into `/opt/modelica/Simulator`, with its license beside it. None of its
  files are copied into this repository.
- Its package is called `Simulator`. The runner loads it when a project file uses `Simulator.`
  or names it in `uses(...)` (`modelcraft.omc.runner.named_libraries`). The Overview shows
  the runner's libraries and their versions.
- The example project **Process library examples** (`PlantCraftProcess`, our own model) is a
  flash drum: a methanol and water feed at 1 atm whose temperature rises from 355 K to 362 K over
  ten minutes, split into vapour and liquid by Raoult's law. Duplicate it to start a flowsheet of
  your own.

To use another component or thermodynamic package, extend a stream and a unit operation with the
package, as `PlantCraftProcess.Stream` and `PlantCraftProcess.FlashDrum` do:

```modelica
model Stream "Material stream with NRTL"
  extends Simulator.Streams.MaterialStream;
  extends Simulator.Files.ThermodynamicPackages.NRTL;
end Stream;
```

OMChemSim's models are steady state: time moves the inputs, and each instant is a new steady
state.

## ThermoSysPro (not shipped)

[ThermoSysPro](https://thermosyspro.com) (EDF and partners) models power and thermal-hydraulic
plants: water and steam, boilers, turbines, heat exchangers and their instrumentation. Its
releases on GitHub (up to 2025, before the project moved to its own GitLab) are licensed under
the **Modelica License 2**. That license lets anyone use and redistribute the library, but a
modified copy, and the executable built from it, must keep the Modelica License 2 and its
notices (section 2c and 2d). Models is Apache-2.0 and builds executables from every model it
runs, so it does not ship ThermoSysPro.

A site that accepts the Modelica License 2 can still use ThermoSysPro: build the runner image
with the library added to `/opt/modelica` and add it to `LIBRARY_VERSIONS` and
`OPTIONAL_LIBRARIES` in `src/modelcraft/omc/runner.py`. That makes a local image, which the
site maintains and whose license terms it accepts.

The license of the current GitLab releases could not be checked from the build machine. Check
it again before any change to this decision.
