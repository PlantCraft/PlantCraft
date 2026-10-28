# Output saturation

## What it detects

The share of the window in which the controller output sat at (or near) one of its limits. A
saturated output means the controller has run out of authority: the valve is fully open or
closed and the loop is effectively open.

## Reference

- Bauer, Horch, Xie, Jelali and Thornhill (2016), The current state of control loop performance
  monitoring: a survey of application in industry, Journal of Process Control. Saturation is one
  of the basic indicators the survey lists; the scoring is an engineering heuristic.

## Parameters

- `lower_limit` (default 0): the output's lower limit, in its unit (0 for an output in %).
- `upper_limit` (default 100): the output's upper limit (100 for an output in %).
- `margin` (default 1): how close to a limit a sample must be to count as saturated.
- `warning_fraction` (default 0.05): the saturated share at which the score reaches 100; the
  score is the saturated share divided by it.

## How to read the finding

"The controller output was at its limits 93% of the time." The performance (100% minus the
saturated share) multiplies into the loop's health. A saturated output with the PV away from the
setpoint means the valve, the pump or the setpoint is wrong for the duty (undersized valve,
fouled exchanger, a setpoint the process cannot reach). Stiction cannot be screened while the
output sits at a limit.

## Limits

- Saturation can be a process constraint (a selector, a design limit) rather than a fault.
- Output limits other than 0–100 must be configured.
