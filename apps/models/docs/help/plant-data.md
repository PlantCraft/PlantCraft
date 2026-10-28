# Simulating with plant data

A simulation can take its inputs from the plant's history, and be drawn against the plant's own
signals: is the model right, and what would the plant have done with another tuning?

In the **Simulate** dialog of the code editor (**Code** on a model's page), tick **Use plant data**:

1. **From** and **To**: the period of the plant's history. The simulation covers it, starting at
   model time 0.
2. **Sample step**: how often the signals are read (in seconds). A period may hold up to 100,000
   samples.
3. **Inputs from the plant**: each top-level input of the model (a `RealInput` connector, or an
   `input Real` variable) can follow a signal. Between two samples the last value is held, as the
   plant recorded it.
4. **Compare with the plant**: a model variable (`tank.level`) and the signal it should match.
   The simulation's plot draws the signal's samples next to the variable.

Signals are read through PlantCraft with your own access: you see the signals PlantCraft
shows you. The plot of such a simulation is in plant time.

To drive a model from the plant, give it inputs. In the example `TankLevelControl`, the tank's
feed comes from a pump; a copy with a `Modelica.Blocks.Interfaces.RealInput qin` connected to the
tank's `qIn` can be fed with a flow signal instead.

An asset's page in Models (open from the asset in PlantCraft) lists the simulations that used
its signals.
