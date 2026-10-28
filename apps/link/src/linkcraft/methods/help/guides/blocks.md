# Blocks

Every block an algorithm can use, in seven libraries: pick a library on the left to see its
blocks.

- **Inputs**: the asset's signals by role (PV, SP, OP, mode…), and the results Signal quality
  already gave them.
- **Data quality**: the loop data check (run first on every loop; the methods after it do not
  run on data it rejects) and the checks Signal quality runs on every signal.
- **Transforms**: error, filters, detrend, difference, clip, delay.
- **Control loop performance**: tracking, oscillation, valve, saturation, noise and operating
  mode; each gives a result and its key numbers.
- **Models**: one block per published process model (FMU), which runs it on the asset's signals
  and gives what it predicts and the residual against the plant; the deviation block (T²) that
  says how far the plant is from the model; and when the unit is in operation.
- **Logic**: worst of, average, rule, limits.
- **Outputs**: loop health, a result on the asset, a message, a signal's result.

A site adds its own libraries with **New library**, under the libraries or beside a block's
Library in its form; they are listed after Analytics' own.

Open a block for what it does, how to read it, its inputs and outputs, its parameters and their
defaults on this site, its assumptions, limits and references, and its source code. Admins
change a method's default parameters on its page; a loop type, an algorithm or a loop can
still override them.

**Duplicate**, beside Download the file, starts a new block from it, in the library you choose.
A block of this site gets its next version with **New version**, on its Versions tab; a block
PlantCraft ships shows a closed lock there instead: it changes with PlantCraft, so duplicate it
to make your own.
