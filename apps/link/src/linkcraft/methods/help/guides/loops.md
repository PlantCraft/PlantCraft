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
