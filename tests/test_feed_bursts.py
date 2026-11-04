"""Changes one person makes to an action in a row reach its owner as one notification."""

from plantcraft.api.feed import _bursts


def entry(actor: str, at: str, text: str) -> dict:
    return {"actor": actor, "created_at": at, "text": text}


def test_a_run_of_changes_by_one_person_is_one_notification():
    entries = [
        entry("ana", "2026-11-03T23:16:00Z", "Checklist, added: Book the thermometer"),
        entry("ana", "2026-11-03T23:16:01Z", "Checklist, added: Read the outlet"),
        entry("ana", "2026-11-03T23:17:00Z", "Checklist, done: Book the thermometer"),
        entry("marina", "2026-11-03T23:18:00Z", "Blocked"),
        entry("ana", "2026-11-04T01:00:00Z", "Comment"),
    ]
    found = _bursts(entries)
    assert [(item["text"], more) for item, more in found] == [
        ("Checklist, done: Book the thermometer", 2),
        ("Blocked", 0),
        ("Comment", 0),
    ]


def test_changes_far_apart_stay_apart_and_odd_times_never_join():
    far = [entry("ana", "2026-11-03T10:00:00Z", "a"), entry("ana", "2026-11-03T10:30:00Z", "b")]
    assert [more for _, more in _bursts(far)] == [0, 0]
    odd = [entry("ana", "yesterday", "a"), entry("ana", "today", "b")]
    assert [more for _, more in _bursts(odd)] == [0, 0]
    assert _bursts([]) == []
