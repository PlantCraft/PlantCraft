# Independent scientific reviewer guide

## Purpose and independence

This guide bounds the review needed before publication-grade claims. The
reviewer should have process-control, fault-diagnosis, or causal-inference
expertise and should not have authored the implementation being reviewed.
Passing software tests is necessary evidence, but it is not a substitute for
this independent judgment.

## Materials

Review the exact candidate commit and record its Git identifier. Use:

- [Scientific model](scientific-model.md);
- [Control structures](control-structures.md);
- [Versioned contracts](contracts.md);
- [Scenario validation](scenario-validation.md);
- [Research protocol](research-protocol.md);
- the generated benchmark manifest and the evidence artifacts whose digests
  are reported in the scenario-validation record.

Generated evidence under `var/` is not a release artifact until its file digest
matches the recorded value. The reviewer should regenerate at least one held-out
seed, one isolated scenario, one deliberate overlap, and one OPC UA history
journey from a clean installed wheel.

## Review questions

### Process and control plausibility

- Are loop directions, gains, time constants, delays, limits, cascade/ratio
  relationships, selectors, and shared disturbances plausible as a transparent
  grey-box benchmark?
- Do controller, actuator, sensor, process, and transport faults remain
  mechanistically distinguishable?
- Are stiction, backlash, saturation, manual mode, tuning, oscillation, and
  propagation represented without circular use of their evaluation rules?
- Are plant balances and graph propagation adequate for the stated scope and
  clearly limited where they are not first-principles?

### Experimental validity

- Are scenario rules frozen before held-out evaluation and independent of truth
  at inference time?
- Are seeds and complete cycles the experimental units?
- Do confidence intervals, failed-run reporting, baselines, and ablations
  support the written claims?
- Could loop identity, topology, timing, missingness, or scenario schedule leak
  labels into a baseline?
- Are negative results, high false-alarm rates, and mixed ablation outcomes
  reported without selective omission?

### OPC UA and data semantics

- Are value, unit, status, source timestamp, server timestamp, cadence, gap,
  communication loss, and history continuation semantics unambiguous?
- Does the server expose only observations and metadata, never hidden truth?
- Can an independent client reproduce current and historical reads without
  assuming a namespace index?

## Required disposition

The review result must record reviewer identity and relevant expertise, date,
candidate commit, package/container/manifest digests, materials examined,
commands independently reproduced, and findings classified as blocking,
non-blocking, or editorial. Each finding needs a disposition and evidence.

Acceptance authorizes only claims about reproducibility, declared scenario
coverage, measured grey-box behavior, and OPC UA delivery. It does not establish
operating-refinery fidelity, realistic fault prevalence, safety suitability,
causal identification performance, or industrial transfer.

Use this decision statement verbatim in the signed review record:

> I reviewed the identified candidate and evidence within the stated scope. I
> either found no unresolved blocking issue, or listed every unresolved
> blocking issue below. This disposition does not validate industrial fidelity
> or safety suitability.
