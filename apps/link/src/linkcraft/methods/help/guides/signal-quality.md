# Signal quality algorithm

A system algorithm: it reads every enabled signal over a window (24 hours by default) and runs the
Data quality methods on it, on a cadence (every 15 minutes by default). Each run is a run,
listed on Results > Run history with its counts and duration, and on PlantCraft's Results page.

Admins change the window, the monitor, which checks run by default and their default parameters
on the algorithm's page; a signal's own settings still win.

Runs use Analytics' app key, created by an admin in PlantCraft. After each run Analytics
publishes its results in PlantCraft: `linkcraft.signal_quality` on every signal, and on every
asset (the worst of its signals), and the derived series `app-linkcraft:<signal>.quality`.

The loop methods read these results: a loop whose PV or OP is bad is not analysed (it is
reported as blocked by Signal quality), and a suspect signal is noted on the loop's finding.

## The checks

- **Availability and gaps**, **Freshness**: the source sends values, and recently.
- **Source quality**: how much of the window the source itself marked bad, substituted or
  uncertain (OPC UA, PI and Canary keep a quality with every value). Bad or substituted time over
  1% is a warning, over 5% makes the data unusable; uncertain time is a warning at most. On a
  source without quality it does not apply.
- **Frozen value**, **Spikes**, **Noise**, **Resolution and compression**, **Drift**.
- **Out of range**: values outside the signal's limits.
- **Rate of change**: changes, measured over at least a minute, faster than the process can move.
  The limit is the signal's own (per minute), or half of its range per minute by default.
- **Transmitter fault levels (NE 43)**: a 4-20 mA signal read on its range as NAMUR NE 43 does.
  3.8 to 20.5 mA is measurement; 3.6 mA or less, or 21 mA or more, is the transmitter reporting
  its own fault. Any fault level is a warning and over 1% of the values is bad.

Out of range, Rate of change and NE 43 need the signal's limits (the rate can have a limit of
its own); without them they do not apply.
