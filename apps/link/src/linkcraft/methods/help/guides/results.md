# Results

What every algorithm of Analytics concluded, on every asset it runs on: one row per algorithm and
asset, worst first. Each row shows the asset, its type, the algorithm and its version, the
status in the suite's words (OK, Warning, Alarm, Unknown), the result's measure (quality,
health, score), the main finding, the algorithm's labels and when it ran.

Filter by **algorithm**, **label**, **asset type**, **group** (the algorithm's responsible group)
and **status**, or search by asset, finding, algorithm or label. Each choice shows how many
results it would keep. **Clear filters** shows every result again.

**Report** prints what the filter keeps as a PDF: the counts per status and per algorithm, then
every result worst first. A filter on the label *control loop* gives the loop portfolio report;
any other filter gives the report of what it keeps.

Open a row to see the result on its own page; open the asset to see every algorithm's result on
it. Assets, loops included, are registered on PlantCraft's Assets page: Analytics reads them and
never keeps its own list. The **Run history** tab lists every run of every algorithm.

## Multivariable controllers

The **Multivariable controllers** tab reads a third-party advanced controller (APC, MPC) from its
own signals and never writes to it. Register it in PlantCraft as an asset of type *Multivariable
controller* with its signal `on` (1 when on and in control), and inside it one *Manipulated
variable* or *Controlled variable* asset per MV and CV, each with `value` and, when the vendor
gives them, `lo`, `hi`, `target` (steady-state target), `status` (1 when in service) and
`shadow_price`. View's MV/CV widget reads the same assets.

For each controller, over the last day, week or month:

- **On**: the time it was on.
- **MVs in service**: the mean time its MVs were in service while it was on. An MV out of service
  is freedom the controller does not have.
- **CVs at a limit**: the mean time its CVs' targets (their values, without a target) sat within
  their band of a limit. The band is the variable's *At-limit band*, else 1% of its range. A CV at
  a limit is the controller pushing the plant against a constraint, not a fault.
- The state is *Alarm* when on, or MVs in service, less than 50% of the time and *Warning* under
  90%.

One controller's page ranks its **active limits by cost**: the hours each was active, the
controller's own shadow price (the mean while active) and the **worth of 1% more range**, the
shadow price times 1% of the variable's range: what moving that limit would be worth, in the
controller's cost unit. A limit with no shadow price is ranked by its hours. The weekly report
carries the same two tables, and the widget *Analytics: multivariable controllers* shows each
controller on the Overview and on Desk.
