# Notifications

Alarms tells people about alarms in PlantCraft's **Messages** and, when PlantCraft has its email
set up (Settings › Email) and the person allows it in their profile, by **email**. Each rule says
who hears about its alarms, in the **Messages** part of its **Outputs**. Email shows there once
PlantCraft can send it.

## Who

- **The responsible**: for an alarm on events, the owner the app names in its events (in Analytics,
  the monitor's owner); else the rule's owner. It is the default.
- People and groups of PlantCraft (such as "U-100 operations").
- Off: the rule's alarms show in Alarms only.

## How much, and when

| Part | Meaning |
|---|---|
| Gather for | Every alarm of the rule raised within this time (5 minutes by default) goes out as **one** message: "Loop critical 3 times in 1 h: 12 loops in Unit 100" |
| Remind every | While an alarm stays active and unacknowledged, it is sent again; acknowledging stops it. 0 never reminds |
| Also when it clears | A message when the alarm returns to normal too |
| Hours | Always, **only inside** some hours (a day shift), or **only outside** them (on call), on the rule's time zone. When the hours begin on an alarm still waiting, it is handed over once |
| If nobody acknowledges | Escalation steps: after so many minutes, tell more people, such as **the coordinator** of the groups notified (set in PlantCraft, People › Groups) |

## What reaches people: the alarm philosophy

Overview › Performance › **Targets** holds the installation's targets. Alarms measures them
(**Performance**, with the ten most frequent alarms) and uses them to keep messages few. The defaults
are the public ISA-18.2 and EEMUA 191 targets; an editor changes them, and every change is in
PlantCraft's audit.

| Guard | What it does |
|---|---|
| By priority | **Critical** goes at once, one by one, past gathering and the limit. **High** goes as its rule gathers it. **Medium**, **low** and every alert wait for the **shift summary** (07:00 and 19:00 by default, in the philosophy's time zone): one message a person with what waited. A rule can still ask for **Always at once** in its outputs |
| Gathering | One message per rule and gathering window, not one per alarm |
| A limit per person | Nobody gets more than 6 messages an hour from Alarms. Past that, one note says more are waiting in Alarms. Critical alarms and escalations always go out |
| Flood | More than 10 alarms for one person or group within 10 minutes: they get **one** flood message ("Alarm flood: 23 alarms in 10 min") instead of each, every 10 minutes while it lasts; critical alarms still come one by one. Alarms writes the event `alarmcraft.flood.started` |
| Chattering | An alarm raised 3 times within a minute, or 10 within an hour, stops sending; the summary lists it with what to change (a deadband, an on-delay) |
| Stale | An alarm active for more than 24 hours is no longer reminded; the summary lists it for review |
| Inhibition | While an Analytics monitor's "failed" or "stalled" alarm is active, the other alarms of that monitor are not announced. While the suite watch reports the Historian or its collector down (or the installer silent, or Docker down), "no data" alarms and failed runs are not announced either: that is their cause, already told to the administrators. The same while the Historian reports its collector stalled; while it reports one source disconnected, only the "no data" alarms of that source's signals wait |

## In Messages

Every occurrence of an alarm is one conversation in Messages: the raise, the reminders, the
escalations and the clear arrive in the same thread, which turns unread again with each one. The
message has **Acknowledge** and **Open the rule** buttons beside Open, and the "Alarms" filter
finds them. **Acknowledge** acknowledges the alarm at once, as you, without opening Alarms (a
read-only access is refused). Critical and high alarms also pop up in whichever app you have open,
with the same buttons. An alert needs no acknowledgement: its message has only **Open the rule**.
Messages gathered from several alarms open Alarms, filtered to their rule.

Once the alarm is acknowledged (here, in Alarms or by someone else), cleared or taken out of
service, its conversation is **settled for everyone** who received it: it leaves their unread
count, loses its buttons and says what settled it ("Acknowledged by ana", "Cleared"). A message
gathered from several alarms settles when all of them are. A new raise of the alarm is a new
conversation.

## Silences

A **silence** (Rules › Silences) holds back the messages of some alarms (areas, disciplines or
chosen alarms) for a while, with a reason: a planned shutdown, a turnaround. The alarms are still
raised, shown and recorded. To stop an alarm itself while its instrument is repaired, **shelve**
it instead (Operating alarms).

## What was sent

Each alarm's page lists its **Messages sent**: when, to whom, and whether it was sent. When PlantCraft cannot take a message (it is restarting, for example), it waits and is
tried again every cycle for a day.

The design follows public descriptions of alerting tools (Grafana Alerting's rules and
notification grouping; Prometheus Alertmanager's grouping, inhibition and silences) and
ISA-18.2's line between suppressing an alarm (shelving) and not paging about it.
