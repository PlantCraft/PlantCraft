# Control structures and dynamic policies

This document maps every catalog control structure to executable behavior. The
model definitions are also embedded in the canonical benchmark manifest, so a
consumer can inspect gains, time constants, dead times, controller settings,
actuator limits, and failure bands without importing Python internals.

## Common loop model

All 50 loops use a deterministic fixed-step, normalized FOPDT approximation
with a reverse-acting PI controller: when measured PV falls below SP, controller
output increases, and the declared positive process gain raises PV. Conditional
integration prevents windup at output limits. The integral state is bounded and
tracks manual output, providing a bumpless return from MAN to the structure's
normal mode.

The final element is first order and rate limited. Dead time uses retained
actuator history. Stiction holds the actuator inside a declared stick band;
backlash consumes a declared amount of travel after each direction reversal;
capacity restriction clamps the actuator target. These mechanisms alter the
final element while leaving the requested controller output observable.

## Structure policies

| Catalog structure | Normal mode | Setpoint policy | Final element behavior |
| --- | --- | --- | --- |
| `feedback_pid` | AUTO | local | single |
| `inventory_control` | AUTO | inventory | single |
| `cascade_primary` | CAS | cascade bias | single |
| `cascade_secondary` | CAS | cascade bias | single |
| `supervisory_bias` | REMOTE | supervisory bias | single |
| `split_range` | AUTO | local | two-range aggregate with neutral crossover |
| `ratio_control` | CAS | ratio bias | single |
| `override_selector` | AUTO | protective minimum selector | single |
| `plant_master` | REMOTE | plant-master bias | single |
| `three_element` | CAS | three-element feedforward bias | single |

The current cascade, ratio, supervisory, and master policies are bounded
deterministic biases around the local setpoint. They exercise mode, hierarchy,
and interaction semantics; they are not a claim that the unnamed synthetic
plant duplicates one particular DCS configuration. The split-range value is an
aggregate final-element position rather than two separately published valves.

## Plant coupling and delay

Each coupling contribution is

$$c_{ji}(t)=a_{ji}[x_j(t-\delta_{ji})-0.55].$$

The simulator retains source-state history and evaluates the declared delay
before applying the signed gain. All target loops use values from completed
integration steps, so catalog iteration order cannot create instantaneous
causality. Within-area edges represent process sequence; the ten named
cross-area edges represent feed, hydrogen, fuel, steam, cooling water,
instrument air, wastewater, and flare mechanisms.

`balance_residual` in hidden truth compares realized normalized accumulation
with the model-predicted derivative. It is a numerical grey-box balance check,
not a physical mass or energy balance in engineering units.

## Testable invariants

The automated model suite checks that:

- every catalog loop has exactly one inspectable model definition;
- all ten control structures map to their declared normal modes;
- actuator travel never exceeds its per-second rate limit;
- integral state stays within anti-windup bounds;
- normalized balance residual is finite and near zero away from clipping;
- coupling remains unchanged before its delay and follows the gain sign after it;
- return from a manual scenario is bumpless;
- stiction and actuator capacity restrictions appear in hidden state; and
- sensor bias decays after the drift window ends.

Scenario labels and these hidden diagnostic states are never published as
ordinary OPC UA Signals.
