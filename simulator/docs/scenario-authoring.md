# Scenario authoring and change control

The bundled scenario set is part of the benchmark identity. Scenario work is a
reviewed contract change, not a runtime configuration shortcut.

## Required separation

Every scenario belongs to exactly one injection layer:

```text
physical plant -> operating policy -> controller -> actuator
               -> sensor -> transport -> observation
```

A transport scenario may change delivery, quality, or source timing but must
not change physical state. A sensor scenario may change the published
measurement but must not change the controlled process. Controller and actuator
scenarios must preserve their separate internal states so that OP and MVFB can
distinguish command from response. Hidden active-scenario truth never appears
in the observation CSV or OPC UA namespace.

## Authoring checklist

1. Define the scenario identity, layer, Portuguese display text, primary loops,
   injection pattern, observable OPC UA effect, and analytical limitations in
   `scenarios.csv`.
2. Add all numerical parameters to the closed scenario parameterization in the
   benchmark manifest. Do not hide behavior in an undocumented default.
3. Implement the effect in its owning layer and define deterministic activation,
   recovery, overlap, and seed behavior.
4. Define an observation-independent minimum physical signature for scenario
   presence. Calibrate only with seed 0; never inspect validation or held-out
   results before freezing the rule.
5. Add focused invariants for inactive behavior, active behavior, recovery,
   timestamp/quality semantics, and forbidden cross-layer effects.
6. Run the 15/5/10 seed partition, the complete isolation matrix, deliberate
   connected overlap controls, and a byte-identical replay in the same recorded
   execution environment.
7. Regenerate the paper-cycle study whenever timing-dependent behavior or the
   benchmark-manifest digest changes.
8. Record negative results and changed identities; do not overwrite evidence
   from a prior parameterization.

## Acceptance questions

- Is the injected cause located in the declared layer?
- Is the effect measurable without reading hidden truth?
- Are inactive and recovery windows distinguishable from the active window?
- Does isolation avoid implicitly enabling unrelated scenarios?
- Are overlaps explicit, reproducible, and scientifically interpretable?
- Do cadence, quality, missingness, source time, and server time retain their
  documented meanings?
- Are claims limited to measured benchmark behavior rather than industrial
  prevalence, refinery fidelity, or diagnostic validity?

The executable commands and current results are in
[Scenario validation](scenario-validation.md). Contract identities are in
[Versioned contracts](contracts.md).
