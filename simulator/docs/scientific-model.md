# Scientific model

## 1. Intended use and epistemic status

The simulator is a synthetic benchmark for methods that consume industrial
time series. It is designed to be structurally credible, reproducible, and
inspectable. It is not calibrated to a named physical refinery, does not solve
material/energy balances at design accuracy, and must not be used for safety,
equipment sizing, operating limits, or operator training.

“Grey-box” means that the topology, controller equations, process response,
couplings, fault layers, and parameters are explicit, while detailed fluid
properties and equipment geometries are intentionally abstracted.

## 2. State-space formulation

Each control loop has a dimensionless physical state $x_i$, manipulated state
$m_i$, setpoint $r_i$, measured value $y_i$, controller output $u_i$, integral
state $I_i$, process gain $K_i$, time constant $\tau_i$, and dead time
$\theta_i$.

The continuous process approximation is:

$$
\frac{dx_i}{dt} = \frac{1}{\tau_i}\left[
0.55 + K_i(m_i(t-\theta_i)-0.50) + d_i(t)
+ \sum_{j \in \mathcal{N}_i} a_{ji}(x_j(t)-0.55) - x_i(t)
\right].
$$

The sparse matrix $A=[a_{ji}]$ contains within-area edges and ten declared
cross-area mechanisms. Every edge uses its declared transport delay against
retained source-state history. The numerical integrator uses fixed-step forward
Euler with a default one-second step. All couplings use completed integration
states, so loop iteration order does not define instantaneous causality.

The PI controller is:

$$
e_i(t)=r_i(t)-y_i(t), \qquad
u_i^*(t)=0.50+K_{c,i}e_i(t)+I_i(t),
$$

$$
\frac{dI_i}{dt}=\frac{K_{c,i}}{T_{I,i}}e_i(t).
$$

$u_i=\mathrm{clip}(u_i^*,0,1)$. Conditional integration implements a simple
anti-windup rule: the integral update is accepted only when the unsaturated
controller output lies inside its limits. Manual mode replaces this law with
an explicit operating schedule.

The nominal actuator is first order and subject to a per-second travel limit:

$$
\frac{dm_i}{dt}=\frac{u_i-m_i}{\tau_{a,i}}.
$$

Manual output continuously tracks the PI integral term, allowing a bounded
bumpless return to AUTO, CAS, or REMOTE. Backlash retains direction and
remaining reversal travel; stiction and capacity restriction have separate
explicit parameters. Structure-specific policies are documented in
[Control structures](control-structures.md).

Every normalized numeric state is mapped linearly into the engineering range
declared by its Signal catalog entry. This scaling supports mixed units but is
not a claim of unit-specific thermodynamic calibration.

## 3. Parameterization

The seven loop classes have declared base parameter sets in `model.py`:
flow, pressure, temperature, level, analyzer, ratio, and speed. A stable hash of
the loop identifier introduces bounded heterogeneity in process time constant
and gain. The hash is not random at runtime and is part of the deterministic
contract. All 50 resolved definitions are serialized into the benchmark
manifest.

Aggressive, sluggish, and oscillatory tuning scenarios modify controller gain
and integral time. Other scenarios leave nominal controller parameters intact
and act in the appropriate layer.

This initial parameterization is hypothesis-generating. A future calibrated
release should publish parameter provenance, uncertainty intervals, and
validation against appropriately licensed experimental or industrial data.

## 4. Fault and observation layers

Scenario effects are applied in this order:

1. process load, disturbance, and cross-loop coupling;
2. setpoint and operating-mode schedule;
3. PI controller and saturation;
4. actuator lag, stiction, backlash, and capacity restriction;
5. measurement noise, bias drift, and frozen sensor;
6. publication cadence, timestamp jitter, quality, gap, and communication loss.

This order defines counterfactual truth. For example, during a data gap the
physical and control states continue evolving, but observations are absent.
During a frozen sensor event the controller sees the frozen measurement while
the physical state continues evolving.

The current stiction implementation is a one-parameter stick-band
approximation inspired by the input-output distinction in Choudhury et al.
(2005); it is not an implementation of their full two-parameter model.

## 5. Noise and determinism

Measurement innovations are deterministic standard-normal values obtained by
Box–Muller transformation of SHA-256-derived uniform variates. The function is
indexed by seed, integration step, loop identifier, and channel. It does not
depend on Python hash randomization or global pseudorandom state.

Reproducibility requires reporting:

- software version and Git commit;
- catalog SHA-256 digest;
- simulation seed;
- UTC start timestamp;
- integration and observation steps;
- scenario-cycle duration;
- observation and truth artifact digests.

## 6. Signal and topology model

The benchmark exposes exactly 500 temporal Signals:

- 50 × PV, SP, OP, MODE, and final-element feedback = 250 loop Signals;
- five contextual Signals for each of 50 process/equipment objects = 250
  context Signals.

Context values are deterministic functions of related hidden process states
with small channel-specific variation. They provide multivariate evidence but
must not be interpreted as independently calibrated equipment models.

The address space separates `Plant.ControlLoops` from
`Plant.Areas.<AREA>.Equipment`. The truth model is never mounted in this OPC UA
address space.

## 7. Numerical and scientific validation

Each release should report:

- catalog cardinality, uniqueness, type, and reference validation;
- deterministic replay at byte and state-digest level;
- invariants for controller output, actuator position, finite values, and
  bounded normalized state;
- step-response gain, settling time, overshoot, and dead-time estimates;
- fault-effect checks at the correct layer;
- missingness, quality-code, and timestamp-jitter checks;
- coupling impulse-response direction, sign, gain, and delay;
- OPC UA browse, current-read, Historical Access, status, and timestamp tests;
- runtime, memory, database size, and query latency by profile.

## 8. Known limitations

- No thermodynamic property package or rigorous mass/energy balance.
- No hydraulics, reaction kinetics, phase equilibrium, or equipment geometry.
- Sparse linear coupling around one operating region.
- Simplified PI, actuator, stiction, backlash, and sensor models.
- Context Signals are state-derived proxies.
- No current calibration against licensed real plant data.
- Anonymous OPC UA is local-development only.
- Scenario prevalence is designed, not an estimate of industrial prevalence.

Claims in a paper must remain within these limits unless new validation is
added and released with evidence.
