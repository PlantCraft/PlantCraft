# Events

**Events** is what the other apps of the suite reported to PlantCraft. Apps report changes only:
an Analytics run that failed (one event per run, not one per asset), a Historian signal
that stopped sending and when it is back, a finding opened or closed. PlantCraft drops a start
that is already open and an end of nothing, and holds each app to 1000 events an hour, so a
broken app cannot flood the suite. Alarms reads them every cycle and keeps them 30 days.

Events never notify anyone. A rule decides when an event becomes an alarm.

## Open now and All

**Open now** (the default) lists the conditions started and not ended yet. An app reports a
condition as two events, its **start** and its **end**, with a **key** that names it (a service,
a signal, a loop's finding). A rule "open for at least 10 min" raises on such a condition and
clears by itself on its end.

**All** lists every event of the period (24 hours, 7 or 30 days), newest first. Filter by type,
app, asset, severity, state (open, ended, instant) or whether a rule counted it; **Rules** names
the rules that counted each event.

## Start a rule from an event

**Create a rule** on an event opens a new rule filled in from it: the event's type, the asset it
is about, open for at least or counted so many times. Choose the outputs, then **Test** it on
the last days.

When Alarms starts for the first time it shows the last day's events here, without counting them:
rules judge what happens from then on.

From Analytics, a monitor's **Create alarm rule** opens a new rule already filled in for it: each
asset it runs on found critical, one alarm per asset, cleared when the status is back to ok.
