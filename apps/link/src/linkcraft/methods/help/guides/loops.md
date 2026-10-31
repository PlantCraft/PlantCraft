# Where loops and their settings come from

Loops come from PlantCraft's asset catalog: every asset of the control loop type, with its
signals by role (PV, SP, OP, mode, secondary) and its record (loop type, criticality, action,
controller, relations). The record is edited in PlantCraft.

The loop type and criticality give each loop its starting algorithm, parameters and ranking weight
(see Analysis defaults per loop type). A setting changed on the loop page is Analytics' from then
on: the page marks it "set here", and "Use the asset record" gives it back.

A loop asset with no signal for a role its type requires (PV and OP) is listed as an Incomplete
record and not analysed until the signals are bound on the asset's page in PlantCraft.

Criticality from the record (low, medium, high) weights the ranking: points lost from 100 times
0.6, 1.0 or 1.5; critical (2.0) is set here only.

## On the loop page

- **Where the output spent the window**: the share of the window in each 5% band of the output.
  A loop that lives near 0 or 100% is saturated; one squeezed into a few percent has little room
  left.
- **Setpoint steps** (read only): "Find steps" lists each setpoint change of the last window that
  stands clear of the PV's noise and was held at least ten samples, with how the PV answered it:
  overshoot past the new setpoint, rise time (10 to 90% of the step), settling time (until the PV
  stays within 5% of the step, wider when the PV is noisy) and IAE divided by the step's size, in
  seconds, so steps of different sizes compare. A short ramp of up to three samples counts as one
  step; steps taken in manual are left out. The medians sit above the table.
- **Suggest tuning** (read only): fits a first order plus dead time from the OP to the PV on the
  last window and gives PI settings by Lambda (IMC) rules for three speeds: tight (lambda = dead
  time), moderate (lambda = time constant) and robust (lambda = 3 time constants), with the
  controller action. Data taken in closed loop is a weak experiment, so take it as the starting
  point for a step test. The page says why a suggestion is not reliable: the fit explains under
  half of the PV, the OP barely moved, or the time constant is shorter than a sample. Nothing is
  sent to the controller.
- **Record as reference** (editors): keeps the loop's last run as the one to compare against,
  after commissioning or a retune. The page then shows health then and now and, for each method,
  its status, score change and the indicator that moved most. One reference per loop: recording
  again replaces it.
