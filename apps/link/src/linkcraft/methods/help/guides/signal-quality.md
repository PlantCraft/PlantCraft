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
