# Research protocol and paper outline

## Proposed paper

**Working title:** *An open, deterministic, plant-wide OPC UA benchmark for
control-loop performance, fault diagnosis, and industrial data quality*

## Research gap

Process-control benchmarks commonly emphasize either plant dynamics, a narrow
fault family, or static downloadable datasets. This project tests whether an
open benchmark can combine plant-wide propagation, control-loop internals,
sensor/transport failures, reproducible hidden truth, and standards-based live
and historical OPC UA access without coupling evaluation methods to the
generator.

## Research questions

1. How accurately can methods distinguish controller, actuator, sensor,
   process, and transport causes when their observed symptoms overlap?
2. How much do missingness, bad quality, and irregular cadence degrade methods
   trained only on good regular samples?
3. Can a method trained on some areas, seeds, and operating cycles generalize
   to unseen areas and seeds?
4. Can algorithms identify the originating loop of a propagated oscillation
   rather than merely flag all affected Signals?
5. Does preserving OPC UA status and timestamps improve detection and reduce
   false positives relative to value-only ingestion?

## Falsifiable hypotheses

- H1: methods using OP and final-element feedback will distinguish actuator
  faults from controller oscillation more accurately than PV/SP-only methods.
- H2: models that consume quality and timestamp features will produce fewer
  false process-fault alarms during transport failures.
- H3: graph-aware methods using the declared coupling topology will localize
  propagated disturbances earlier than independent univariate detectors.
- H4: random row splitting will overestimate generalization relative to splits
  by seed and complete scenario cycle.

## Experimental design

Generate at least 30 independent seeds. Reserve complete seeds and cycles:

- development: 15 seeds;
- validation: 5 seeds;
- held-out test: 10 seeds.

Do not mix adjacent timestamps from one cycle across partitions. Report results
for normal operation and for every scenario individually, then for approved
scenario overlaps. Pre-register scenario parameters and metrics before
examining held-out results.

The current executable accelerated qualification, its frozen seed partitions,
and the remaining paper gate are recorded in
[Scenario validation](scenario-validation.md).

Recommended operating profiles:

| Profile | History | Integration | Published cadence | Purpose |
| --- | ---: | ---: | ---: | --- |
| smoke | 15 min | 1 s | 30 s | CI and compatibility |
| development | 6 h | 1 s | 30 s | method iteration |
| paper | 24 h | 1 s | 5 s | 72 h/seed main experiments |
| stress | 24 h | 5 s | 30 s | 30 d storage and performance |

These values are executable definitions bundled with the package. See
[Versioned contracts](contracts.md) for scenario-cycle and historian response
limits and for the compatibility rules.

## Metrics

- event detection: AUROC, AUPRC, macro-F1, false alarms/day;
- timing: detection delay and recovery delay with censored-event reporting;
- diagnosis: scenario macro-F1 and confusion matrix;
- localization: source-loop top-1/top-3 accuracy and mean reciprocal rank;
- calibration: Brier score and expected calibration error;
- data quality: gap/status/timestamp classification precision and recall;
- systems: generation throughput, peak RSS, storage per signal-day, OPC UA
  read latency, and Historical Access continuation behavior.

Report confidence intervals across seeds, effect sizes, failed runs, and the
complete environment. Avoid treating highly correlated samples as independent
replicates; the seed/cycle is the experimental unit.

## Baselines

At minimum compare:

- rule-based control-performance indicators;
- robust univariate residual thresholds;
- multivariate PCA residual statistics;
- a temporal sequence model;
- a graph-aware temporal model for source localization.

Hyperparameter budgets and input Signal sets must be identical or explicitly
reported. A method must not receive truth files, scenario identifiers, or
future observations at inference time.

## Ablations

- PV/SP only versus PV/SP/OP/MVFB/MODE;
- values only versus values plus quality/timestamps;
- no coupling graph versus declared graph;
- one area versus full plant context;
- regularized observations versus native missing/irregular observations;
- random-row split versus seed/cycle split.

## Reproducibility package

A paper release should archive:

- exact Git tag and container digest;
- catalog, observation, and truth digests;
- seeds and UTC intervals;
- experiment configurations;
- raw per-seed predictions and metrics;
- figure/table generation code;
- software and hardware environment;
- a machine-readable limitations and ethical-use statement.

Use Zenodo or an equivalent archival repository to mint a DOI for the exact
release. The GitHub `CITATION.cff` gives citation metadata but is not itself an
archival DOI.

## Responsible claims

The first paper may claim reproducibility, scenario coverage, standards-based
delivery, and measured benchmark behavior. It may not claim fidelity to an
operating refinery, validated fault prevalence, safety suitability, or direct
industrial transfer until those claims are supported by independently
licensed empirical validation.
