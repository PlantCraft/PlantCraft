"""What an OPC UA StatusCode says beyond good, uncertain or bad (gap H6, OPC UA Part 4 §7.39).

The collector keeps the whole code with each change of quality: its sub-code
(``UncertainLastUsableValue``, ``BadCommunicationError``...) and its LimitBits, which say the
value is pinned at a low or high limit, or constant (it cannot move). Read back as ``status``
and ``limit`` beside ``quality``. The sub-code's name is taken where the code is read (the
collector's OPC UA reader) and kept beside it: nothing else here speaks OPC UA.
"""

from __future__ import annotations

# Severity and sub-code: the upper 16 bits; LimitBits: bits 8 and 9.
SUBCODE_MASK = 0xFFFF0000
LIMIT_MASK = 0x00000300
LIMITS = {0x100: "low", 0x200: "high", 0x300: "constant"}


def limit_of(code: int | None) -> str:
    """``low``, ``high``, ``constant``, or '' when the value is free to move (or no code)."""

    return "" if not code else LIMITS.get(int(code) & LIMIT_MASK, "")


def subcode(code: int | None) -> int:
    """The severity and sub-code bits of ``code`` (0: plain Good, or no code)."""

    return int(code) & SUBCODE_MASK if code else 0


def described(code: int | None, name: str | None = None) -> dict[str, str]:
    """The fields a quality change carries for ``code`` (none for plain Good): ``status``, the
    sub-code's name as the collector read it (its hex value when unnamed), and ``limit``."""

    out = {}
    named = name or (f"0x{subcode(code):08X}" if subcode(code) else "")
    name, limit = named if subcode(code) else "", limit_of(code)
    if name:
        out["status"] = name
    if limit:
        out["limit"] = limit
    return out
