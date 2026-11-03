"""What the queue and the schedules share: statuses, works, priorities, kinds, cadences,
the default retry, a schedule's output key and the summary kept with an execution."""

from __future__ import annotations

import re
import unicodedata
from typing import Any

# English labels; whoever serves them translates them with t().
JOB_STATUSES = {
    "scheduled": "Scheduled",
    "waiting_data": "Waiting for data",
    "queued": "Queued",
    "running": "Running",
    "completed": "Completed",
    "failed": "Failed",
    "cancelled": "Cancelled",
    "skipped": "Skipped",
}

# What an execution runs: one loop's algorithm, a whole round (every loop, or Signal quality on
# every signal), an algorithm on one asset, or the archive replayed.
WORKS = {
    "loop": "Algorithm on a loop",
    "round": "Every target in turn",
    "asset": "Algorithm on an asset",
    "replay": "Replay of the past",
}

# The queue's order: what a person asked for first, then the schedules,
# then the past replayed. Higher runs first; equal priorities run in the order they were due.
PRIORITIES = {"manual": 100, "test": 100, "baseline": 60, "scheduled": 50, "replay": 10}
OPEN_STATUSES = ("scheduled", "waiting_data", "queued", "running")

# Names the loops' round had before; it is renamed at start (``ensure_round_schedule``).
RENAMED_ROUNDS = frozenset({"Loop monitor", "Monitoring round", "Loop monitoring round"})

JOB_KINDS = {
    "baseline": "Initial",
    "manual": "Manual analysis",
    "test": "Manual test",
    "scheduled": "Scheduled",
}

SCHEDULE_CADENCES = {
    "interval": "Every N minutes",
    "once": "Once",
    "hourly": "Hourly",
    "daily": "Daily",
    "weekly": "Weekly",
    # A calendar rule (``recurrence``): every N minutes on some days, several times a day, chosen
    # weekdays, a day of the month.
    "calendar": "Calendar",
}

# What a schedule does when an execution cannot read the plant or finds no data (owner,
# 2026-10-25, as Elipse EPM's scheduled calculations): try again, a few times, a few minutes
# apart, and give up when the next occurrence comes first.
DEFAULT_RETRY = {"enabled": True, "count": 2, "wait_minutes": 5.0, "abort_on_next": True}
# A schedule's part in the ids of the points it records (``<asset>.<key>.<output>``).
OUTPUT_KEY_LENGTH = 40


def output_key_of(name: str, taken: set[str]) -> str:
    """A short stable key from a schedule's name ("Revisão diária" → ``revisao-diaria``),
    unique among ``taken``; kept when the schedule is renamed."""

    plain = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii")
    base = re.sub(r"[^a-z0-9]+", "-", plain.lower()).strip("-")[:OUTPUT_KEY_LENGTH].strip("-")
    base = base or "schedule"
    key, number = base, 2
    while key in taken:
        suffix = f"-{number}"
        key = f"{base[: OUTPUT_KEY_LENGTH - len(suffix)]}{suffix}"
        number += 1
    return key


def lean_summary(summary: dict[str, Any]) -> dict[str, Any]:
    """A summary as kept with its execution: each recorded series without its points, and
    without the wires' samples (``engine.samples`` keeps those of the last runs).

    An algorithm on an asset records its series over the whole window (hundreds of points
    each, tens of kB per execution); the Historian keeps the points, the execution each
    series' last value."""

    if not isinstance(summary, dict):
        return summary
    # The wires' samples are kept apart, for the last runs only (``engine.samples``).
    summary = {key: value for key, value in summary.items() if key != "samples"}
    recorded = summary.get("recorded")
    if not recorded:
        return summary
    return {
        **summary,
        "recorded": [
            {key: value for key, value in entry.items() if key != "points"}
            if isinstance(entry, dict)
            else entry
            for entry in recorded
        ],
    }
