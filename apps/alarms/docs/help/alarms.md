# Alarms

Alarms tells the right person when something needs action. **Rules** read two things and decide:

- **Values**: the plant's signals and what the apps compute and keep as series, such as a loop's
  health from Analytics (one value per run).
- **Events**: what the apps of the suite report, only when something changes: an Analytics run
  that failed, a Historian signal without data, a finding opened.

A rule that holds raises an **alarm**; nothing becomes an alarm by itself.

## Where to start

The menu follows the order things happen: events come in, rules read them, alarms are raised.

1. **Overview** shows the alarms at a glance, in widgets each person arranges; hover a widget's
   title for what it shows and in which order. The performance widget opens **Performance**,
   which compares the alarm load with the ISA-18.2 and EEMUA 191 **Targets**.
2. **Events** lists what the other apps reported: **Open now** (started and not ended) or **All**
   in a period, filtered by type, app, asset, severity or state. Events notify nobody. A row opens
   the event: where it came from (a link to the Analytics execution or run behind it), what the
   app sent, the same condition's earlier starts and ends, and the rules that read it; **Create a
   rule from it** starts a rule there.
3. **Rules** lists every rule as a sentence, each switched on or off from the list. **New rule**
   writes one in the Simple form or in Python. The **Silences** tab holds messages back during a
   planned shutdown.
4. **Alarms** is every alarm in one table, most urgent first: **Needs attention** (the default),
   **Unacknowledged** or **All**, and **Only mine**. A row opens the alarm: its value, its
   history (every raise, clear, acknowledgement and change) and the messages sent about it.

## One rule, many alarms

A rule covers named assets, every asset under a branch, every asset of a type, the assets of a
Analytics monitor, or any asset its events name, and makes **one alarm per asset** by default: "PV
above 50 under Unit 100" is one rule and a dozen alarms. Each alarm keeps its own ISA-18.2 life
(raised, acknowledged, shelved), while the messages of the whole rule are gathered, so fifty
loops do not become fifty messages. See **Rules** and **Notifications**.

## Where the data comes from

Alarms reads values and the suite's events only through PlantCraft, with its own app key, every
few seconds. It never connects to the control system and never writes to it: it informs, the
operator acts. A rule over assets reads each asset's own value (its `pv` role, or an app's
series about it), so when the plant map moves a role to another signal, the alarm follows.

Every raise and clear is also sent to PlantCraft as an event, and each asset shows its alarm
state in the other apps (unless the rule's **Dashboards** output is off).
