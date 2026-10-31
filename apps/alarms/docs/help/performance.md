# Alarm performance

The Performance page measures the alarm load over a period (24 hours, 7 or 30 days) for one
operator position, against the public targets of ISA-18.2 and EEMUA 191. Shelved and
out-of-service alarms raise nothing and are not counted.

| Figure | Acceptable | Manageable |
|---|---|---|
| Alarms per hour | up to 6 | up to 12 |
| Alarms per 10 minutes | up to 1 | up to 2 |
| Time in flood (10-minute periods with more than 10 alarms) | under 1 % | under 5 % |
| Peak alarms in 10 minutes | up to 10 | up to 20 |
| Load from the 10 most frequent alarms | up to 5 % | up to 10 % |
| Chattering alarms (3 raises within a minute) | none | |
| Stale alarms (active for more than 24 hours) | fewer than 5 | fewer than 10 |

The priority distribution is compared with about 5 % high (critical and high), 15 % medium and
80 % low.

## Consoles (operator positions)

The targets are for one operator. When the plant has several boards, set the **consoles** in
Targets › Consoles. Each console lists:

- the **areas** it answers, at any level of the asset tree (a unit, a section, one equipment);
- who sits at it;
- its own alarms-an-hour target, if it differs from the load per person.

An alarm goes to the console that names the most specific of its areas. If two consoles name the
same area, it goes to the first one. An alarm no console covers is counted under **No console**.

Performance then shows a **Consoles** table with each console's load against its own target:
alarms an hour, the peak in 10 minutes and the EEMUA 191 level. The **Console** selector shows
every figure for one console. People who sit at a console see their own console first.

## What to do with it

Start with the **most frequent alarms**: a handful of bad actors usually make most of the load.
For each, check the limit, add a deadband or a delay, or ask whether it needs an alarm at all.
Chattering alarms almost always need a deadband. Stale alarms are either a real standing
problem or an alarm that should be out of service.
