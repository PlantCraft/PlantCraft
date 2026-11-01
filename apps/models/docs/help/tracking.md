# Tracking a model against the plant

A tracking keeps checking a model against the plant on its own. On a schedule it simulates the
model over the last window of plant data (as **Use plant data** does in the Simulate dialog),
writes **model minus plant** for each compared variable as a signal in PlantCraft, and, when a
limit is set, raises **Model off the plant** while the error stays above it.

Open **Tracking** and press **New tracking**:

1. **Model**: the model to run. Its settings (solver, parameters) are the ones it has when each run
   starts.
2. **Window** and **Every**: each run covers the last *window* minutes up to now, and a run starts
   every *every* minutes (5 minutes at least for both).
3. **Compare with the plant**: one line per variable, `variable = signal`, for example
   `tank.level = plant:LT-101`. Each one gets an error signal,
   `app-modelcraft:tracking-<id>.<variable>.error`, written at the plant's sample times inside the
   window. Trend it in View, use it in Analytics, or alarm on it like any signal.
4. **Inputs from the plant** (optional): `input = signal` lines feed the model's inputs from the
   plant, holding the last value between samples.
5. **Alarm limits** (optional): `variable = number`, the mean absolute error above which the
   variable is off the plant. The event opens when a run ends above the limit and closes when one
   ends below it; it goes to the tracking's owner when it stays open for 30 minutes.

Each run is an ordinary simulation in the model's quick simulations, labelled with the tracking's
name; the last 20 of each tracking are kept. The table shows each variable's mean absolute error
and bias from the last run, the run itself, and why it failed when it did (a signal that could not
be read, a model that does not build). **Run now** starts one at once; untick a tracking to pause it.

Trackings read the plant through Models's own access (the suite's service account), not the
person who made them: they keep running when nobody is signed in.
