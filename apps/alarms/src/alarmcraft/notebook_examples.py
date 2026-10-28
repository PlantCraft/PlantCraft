"""Alarms' examples in Notebooks (``Examples/Alarms``): its rules and alarms read with
``pc.app("alarms")``, an alarm performance study in the terms of ISA-18.2 and EEMUA 191, and one
alarm set against its signal.

They find their own alarms, so they run on any installation with Alarms, the demo included, and
say so when there is nothing to study yet. Every one is run by the tests against the test plant.
"""

from __future__ import annotations

from typing import Any

from plantcraft_sdk.notebooks import Example, cell

_OCCURRENCES = """
import pandas as pd

alarms = pc.app("alarms")
listed = alarms.alarms()


def occurrences_of(alarm_ids):
    \"\"\"Every occurrence of the last 30 days of these alarms: one row each, when it started
    and ended (an open one ends now).\"\"\"
    rows, now = [], pd.Timestamp.now(tz="UTC")
    for alarm_id in alarm_ids:
        alarm = alarms.get("alarm", alarm_id)
        now = pd.Timestamp(alarm["at"])
        for found in alarm.get("occurrences") or []:
            rows.append({"alarm": alarm["name"], "priority": found["priority"],
                         "start": found["started_at"], "end": found["ended_at"],
                         "limit": found.get("limit"), "value": found.get("start_value")})
    frame = pd.DataFrame(rows, columns=["alarm", "priority", "start", "end", "limit", "value"])
    frame["start"] = pd.to_datetime(frame["start"], utc=True, format="ISO8601")
    frame["end"] = pd.to_datetime(frame["end"], utc=True, format="ISO8601").fillna(now)
    return frame.sort_values("start")
"""


def _rules_and_alarms() -> list[dict[str, Any]]:
    return [
        cell(
            "markdown",
            '`pc.app("alarms")` reads Alarms with your access: its rules (each in one sentence, '
            "as the Rules page writes it) and its alarms with their state. Nothing here changes "
            "a rule: rules are written on the Rules page.",
        ),
        cell(
            "code",
            """
import pandas as pd

alarms = pc.app("alarms")
rules = alarms.rules()
print(len(rules), "rules")
rules[["name", "priority", "editor", "enabled", "alarms"]].head(15) if len(rules) else rules
""",
        ),
        cell(
            "code",
            """
if len(rules):
    rule = alarms.get("rule", rules.index[0])
    print(rule["name"], "-", rule["sentence"])
    print("where:", rule["where_words"], "| alarms:", rule["alarms"], "| active:", rule["active"])
""",
        ),
        cell(
            "markdown",
            "The alarms, one row each with their ISA-18.2 status (normal, unacked, acked, "
            "rtn_unacked, shelved, out_of_service), and how many are in each status by area.",
        ),
        cell(
            "code",
            """
listed = alarms.alarms()
print(len(listed), "alarms,", int(listed["active"].sum()) if len(listed) else 0, "active")
if len(listed):
    print(pd.crosstab(listed["area"].replace("", "(no area)"), listed["status"]))
""",
        ),
    ]


def _alarm_performance() -> list[dict[str, Any]]:
    return [
        cell(
            "markdown",
            "An alarm performance study of the last 30 days, with the measures of ISA-18.2 and "
            "EEMUA 191: alarms per 10 minutes (about 1 is manageable, over 10 is a flood), the "
            "most frequent alarms (bad actors), chattering (back within a minute) and standing "
            "alarms (active for over a day).",
        ),
        cell("code", _OCCURRENCES),
        cell(
            "code",
            """
occurrences = occurrences_of(listed.index[:300])
print(len(occurrences), "occurrences of", occurrences["alarm"].nunique(), "alarms")
if len(occurrences):
    per_10 = occurrences.set_index("start").resample("10min").size()
    print(f"alarms per 10 min: median {per_10.median():.1f}, max {per_10.max()}, "
          f"{(per_10 > 10).mean():.1%} of the periods in flood")
    per_10.plot(figsize=(10, 3), title="Alarms per 10 minutes");
""",
        ),
        cell(
            "code",
            """
if len(occurrences):
    bad_actors = occurrences.groupby("alarm").size().sort_values(ascending=False)
    share = bad_actors.cumsum() / bad_actors.sum()
    print(f"the top 10 alarms are {share.iloc[min(9, len(share) - 1)]:.0%} of all occurrences")
    print(bad_actors.head(10).rename("occurrences").to_frame())
""",
        ),
        cell(
            "code",
            """
if len(occurrences):
    occurrences["gap"] = occurrences.groupby("alarm")["start"].diff().dt.total_seconds()
    chattering = occurrences[occurrences["gap"] < 60].groupby("alarm").size()
    duration = (occurrences["end"] - occurrences["start"]).dt.total_seconds() / 3600
    standing = occurrences[duration > 24].groupby("alarm").size()
    print("chattering (back within 60 s):", {name: int(n) for name, n in chattering.sort_values(ascending=False).head(5).items()} or "none")
    print("standing (over 24 h):", {name: int(n) for name, n in standing.head(5).items()} or "none")
    print(occurrences.groupby("priority").size().rename("occurrences by priority"))
""",
        ),
    ]


def _alarm_and_signal() -> list[dict[str, Any]]:
    return [
        cell(
            "markdown",
            "One alarm against its signal: the last 7 days of the signal with each occurrence "
            "shaded and the limit drawn, then how many occurrences a wider deadband would have "
            "left, worked out here on your computer (the rule is not changed).",
        ),
        cell("code", _OCCURRENCES),
        cell(
            "code",
            """
with_signal = listed[listed["signal"].fillna("") != ""] if len(listed) else listed
if len(with_signal) == 0:
    print("No alarm watches a signal yet: create a Simple rule on a signal in Alarms.")
else:
    alarm_id = with_signal.index[0]
    signal = with_signal.loc[alarm_id, "signal"]
    occurrences = occurrences_of([alarm_id])
    at = pd.Timestamp(alarms.get("alarm", alarm_id)["at"])  # Alarms' clock
    values = pc.series(signal, at - pd.Timedelta(days=7), at, step=60)[signal].dropna()
    ax = values.plot(figsize=(10, 3.5), title=f"{with_signal.loc[alarm_id, 'name']} ({signal})")
    for _, found in occurrences.iterrows():
        ax.axvspan(found["start"], found["end"], color="tab:red", alpha=0.2)
    # The limit the occurrences were raised at, else the one of the rule's Simple condition.
    limits = occurrences["limit"].dropna()
    limit = float(limits.iloc[-1]) if len(limits) else None
    if limit is None and with_signal.loc[alarm_id, "rule"]:
        rule = alarms.get("rule", with_signal.loc[alarm_id, "rule"])
        conditions = (rule.get("simple") or {}).get("conditions") or []
        limit = next((float(c["limit"]) for c in conditions if c.get("limit") is not None), None)
    if limit is not None:
        ax.axhline(limit, color="tab:red", linestyle="--")
    print(len(occurrences), "occurrences in 30 days; limit", limit)
""",
        ),
        cell(
            "markdown",
            "With a deadband, an alarm raised above the limit clears only once the value falls "
            "below the limit minus the deadband, so a value that hovers at the limit raises it "
            "once instead of many times.",
        ),
        cell(
            "code",
            """
def raised(values, limit, deadband):
    active, count = False, 0
    for value in values:
        if not active and value >= limit:
            active, count = True, count + 1
        elif active and value < limit - deadband:
            active = False
    return count


if len(with_signal) and limit is not None and len(values):
    span = float(values.max() - values.min()) or 1.0
    for share in (0.0, 0.01, 0.02, 0.05):
        print(f"deadband {share * span:8.3g}: raised {raised(values, limit, share * span)} times in 7 days")
""",
        ),
    ]


EXAMPLES = [
    Example(
        "rules-and-alarms",
        "Rules and alarms",
        "List Alarms' rules, each in one sentence, and its alarms with their status by area.",
        _rules_and_alarms,
    ),
    Example(
        "alarm-performance",
        "Alarm performance",
        "Alarms per 10 minutes, bad actors, chattering and standing alarms of the last 30 days "
        "(ISA-18.2, EEMUA 191).",
        _alarm_performance,
    ),
    Example(
        "alarm-and-signal",
        "An alarm and its signal",
        "One alarm's occurrences over its signal, and how many a wider deadband would have left.",
        _alarm_and_signal,
    ),
]

__all__ = ["EXAMPLES"]
