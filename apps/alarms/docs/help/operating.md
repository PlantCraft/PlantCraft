# Operating alarms

**Alarms** lists every alarm and alert in one table, most urgent first: unacknowledged alarms,
then alarms that returned to normal without an acknowledgement, then active acknowledged ones,
then shelved ones. **Needs attention** (the default) keeps those; **Unacknowledged** only those
still to acknowledge; **All** every alarm the rules made, normal ones too. **Only mine** keeps
those you or your groups answer for, and those a rule notifies you about. Filter by priority,
state or area above the table, and tick rows to acknowledge them together.

A row opens the alarm: its state, what it is about, its rule and corrective action, its value
with the limit, its **History** (every raise, clear, acknowledgement, shelve and change) and the
**Messages sent** about it.

An **alert** (a rule can make alerts instead of alarms, for example "Analytics run failed")
shows here too but needs no acknowledgement and does not count in Performance.

## States

| State | Meaning |
|---|---|
| Unacknowledged | Active, and no one has acknowledged it yet |
| Acknowledged | Active, and an operator has seen it |
| Returned, unacknowledged | Back to normal before anyone acknowledged it |
| Shelved | Raises nothing until the shelve ends (an operator decision, with a reason) |
| Out of service | Not evaluated at all (an engineering decision, or its rule is off) |
| Normal | Inactive and acknowledged |

These are the states of ISA-18.2.

## Acknowledge

**Acknowledge** says "I have seen it". An acknowledged alarm stays in the list while it is
active. **Acknowledge all** acknowledges every alarm in the list. The message in PlantCraft's
Messages has an **Acknowledge** button too: it opens the alarm and acknowledges it. Who
acknowledged and when is kept in the journal and counts in the time-to-acknowledge figure.

## Shelve

Shelve a nuisance alarm for a fixed time (from 15 minutes to 7 days) and say why. While shelved
it is still evaluated but raises nothing. When the shelve ends, or someone unshelves it, an alarm
that is still active is announced again and needs a new acknowledgement.

## One alarm's page

An alarm's page shows its state, its signal with the limit and each occurrence, or, for an alarm
of a repeated event, the events that counted and the one that cleared it. **Change the rule**
opens the rule it comes from; **Take out of service** stops this one alarm only.

Viewers see everything; acknowledging and shelving need editor access to Alarms.
