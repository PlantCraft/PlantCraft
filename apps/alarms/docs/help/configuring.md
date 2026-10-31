# Rules

A rule says **where** it applies, **when** it raises, **what it makes**, where its alarms go
(**outputs**) and **why**. Each rule reads as a sentence on its page and in the list.

## Where

- **Assets** named, every asset **under** a branch of the plant map, or every asset of a
  **type**, today's and those added later.
- The assets of a **Analytics monitor** (what it runs on).
- **Anywhere**: any asset the rule's events name.
- **Nothing**: a rule on named values or events only, with one alarm.

**One alarm per** asset (the default), per monitor, or one for the whole rule.

## When: Simple or Python

- **Simple**: up to three conditions joined by **and** or **or**. A condition reads a **value**
  (above, below, between, outside, changed, or **did not change**: a frozen measurement) with a
  **deadband**, or an **event** (open for at least so long, or counted so many times in a
  window). It may have to hold **for at least** so many minutes or values, and the alarm clears
  **after** so long back to normal.
- **Python**: for any other logic. Pick a few values as inputs; `check(inputs)` reads each one's
  last reading (`inputs.flow`, None when there is no data) and answers `True, "sentence"` to raise
  or `False, ""` not to. The editor starts from a commented example for the inputs, shows what
  comes in and goes out beside the code, and opens full screen with **Expand**. Only
  administrators write code; it runs in PlantCraft's isolated area (no network, no files, limited
  time and memory), at most once a minute.

A rule drawn in the former Blocks editor keeps running as drawn (those that fit were rewritten as
Simple or Python); to change its logic, write it again in Simple or Python.

Values and events are picked in the **Explorer**: the plant map with each asset's signals, the
series the apps computed about it and the events that named it. A value picked for **each
asset** is read on every asset of the rule.

### Only while: alarms that depend on the plant's state

**Only while…** in the Simple form adds a permissive: a value condition that must hold for the
alarm to be judged at all (state-based alarming, ISA-18.2 designed suppression). A low flow alarm
**only while P-101 running ≥ 1**, with **Enabled after** 30 s so the flow can settle after a
start. While the permissive does not hold, the alarm is suppressed by design: it is not raised,
it clears if it was raised, and its page says so. A permissive that cannot be judged (no data)
leaves the alarm enabled, so a bad signal never hides an alarm. In Blocks it is the **Enabled
when** input of Raise an alarm.

## What it makes

- **An alarm**: needs an acknowledgement, shows in Alarms and counts in Performance (ISA-18.2).
- **An alert**: shows in Alarms and is sent, but needs no acknowledgement and stays out of
  Performance. Good for what the apps report about themselves, such as a failed run.

**Priority** is critical, high, medium or low; keep most rules low. **Owner**, **area** and
**discipline** say who answers for it and where it is; the area comes from the asset tree when
left empty. **Rationalization** is the cause, the consequence of not acting and the corrective
action: an alarm without an action for the operator should not be an alarm.

## Outputs

- **Alarms**: always; the alarm is listed to acknowledge, shelve and comment.
- **Dashboards** (on): its alarms colour their assets and show in the Active alarms widgets of
  View and the Overview.
- **Messages** (on, to the responsible): in PlantCraft's Messages, gathered, with reminders,
  hours and escalation. See **Notifications**.
- **Email**: shows once an administrator set up PlantCraft's email server (Settings, Email); it goes
  to the people who allow it in their profile.

## Test before saving

**Test** runs the rule, as written, over the last days of values and events and says how many
alarms it would have made, on how many targets, and about how many messages it would have sent
once gathered. If a rule would fire dozens of times a day in normal operation, its limit,
deadband, delay or count needs work.

## Turning a rule off

**Turn off** on the rule's page stops it: its alarms are out of service until it is turned on.
Deleting a rule ends its alarms; their journal stays. Changing a rule's logic ends its active
alarms and judges again from then on.

## Import the DCS alarm list

**Import alarm list** on Rules reads the alarm list exported from the DCS (the master alarm
database): a CSV file, or Excel saved as .xlsx. **Template** gives a file with the columns Alarms
reads. Each row is one alarm on one signal:

- **tag** (the signal, by its id or its name in the DCS, like `FIC-1001.PV`) and **type**: HH,
  HI, LO or LL (PVHI, HIHI, LOLO and the like are read too);
- **limit**, and optionally unit, **priority** (critical, high, medium, low, or 1 the most
  urgent to 4), deadband, on-delay (seconds, `2 min` or `00:00:10`), description, cause,
  consequence, action and enabled.

Reading the file changes nothing. The review lists what an apply would do: **new** rules,
**changed** ones (field by field, before and after), **removed** ones (alarms an earlier import
made that the list no longer has) and rows that could not be read, with their line. Untick what
should not change and **Apply**. A removed alarm's rule is turned off, never deleted. What
people set in Alarms itself (where, who is notified, owner, area) stays. A rule someone changed
after the file was read is left as it is and listed: read the file again to see it. Rules
written by hand are never touched. Each import is matched alarm by alarm by its tag and type.
