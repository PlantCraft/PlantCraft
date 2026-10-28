# Blocks

**Blocks** are what a model's diagram is drawn with: each has inputs, outputs and parameters.
**Blocks** in the menu lists them by library. A block's page has tabs, like a block's in Analytics:
**Overview** (what it does, its inputs and outputs), **Code** (its Modelica text), **Inputs and
parameters** (one table, so the columns line up) and **Used by** (the models that place it).

| Library | Blocks |
|---|---|
| Sources | Step, ramp, constant, sine, pulse, a table of values in time |
| Math | Gain, add, multiply, divide, saturation, rate limiter |
| Continuous | Integrator, derivative, first order, transfer function, state space, dead time |
| Control | PID with anti-windup, on/off |
| Process equipment | Tank, pump, control valve, heat exchanger, CSTR, measurement lag |
| Sinks | Scopes (one or two signals): what a simulation's results plot first |

## Using a block

In a model's editor (**Diagram**, then **Open the editor**), drag a block from the palette onto
the diagram, or press **+ Block**, and wire an output to an input. Select a block to set its parameters in the inspector; **Arrange** lays the diagram out
from left to right.

## Writing blocks

The shipped libraries are read-only. **New block library** creates an empty Modelica package of
the site's own, with a name and a category, and opens it in the code editor. A block's real inputs
and outputs (`RealInput`, `RealOutput`) become its ports in the diagram; its parameters, its
settings.

Changing a block changes every model that uses it, from its next simulation on. Simulations already made keep
the files they ran with.
