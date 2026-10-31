"""Tags on a drawing, read with ISA-5.1 (instruments) and the usual equipment letters.

Public conventions only: the ISA-5.1 letter table (first letter = what is measured, the letters
after = what the instrument does) and the equipment prefixes engineering contractors commonly
use (P pump, E exchanger, V vessel...). A text is a tag only when the whole word is one, so a
line number (``8"-P-1001-A1``) or a drawing number (``PID-U-100-01``) never counts as one.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# ISA-5.1 first letters: the measured or initiating variable.
MEASURED = {
    "A": "analysis",
    "B": "burner",
    "C": "conductivity",
    "D": "density",
    "E": "voltage",
    "F": "flow",
    "H": "hand",
    "I": "current",
    "J": "power",
    "K": "time",
    "L": "level",
    "M": "moisture",
    "P": "pressure",
    "Q": "quantity",
    "R": "radiation",
    "S": "speed",
    "T": "temperature",
    "U": "multivariable",
    "V": "vibration",
    "W": "weight",
    "Y": "event",
    "Z": "position",
}
# What the equipment letters mean; two-letter ones are checked first.
EQUIPMENT = {
    "TK": "tank",
    "AC": "air_cooler",
    "CT": "cooling_tower",
    "FL": "flare",
    "ME": "mixer",
    "P": "pump",
    "E": "heat_exchanger",
    "V": "vessel",
    "D": "vessel",
    "C": "column",
    "T": "column",
    "R": "reactor",
    "F": "furnace",
    "H": "furnace",
    "K": "compressor",
    "B": "blower",
    "M": "mixer",
    "X": "equipment",
    "S": "separator",
    "G": "generator",
}
# Two-letter equipment prefixes that ISA-5.1 does not use for instruments outside a circle.
EQUIPMENT_PAIRS = {"TK", "AC", "CT", "FL", "ME"}
# The words after which an instrument's role is plain.
INSTRUMENT_CLASSES = (
    "controller",
    "valve",
    "transmitter",
    "element",
    "indicator",
    "switch",
    "relay",
    "alarm",
    "instrument",
)

FULL = re.compile(r"^([A-Z]{1,5})[-_ ]?(\d{2,6})([A-Z]{0,2}(?:/[A-Z])?)$")
LETTERS = re.compile(r"^[A-Z]{1,5}$")
NUMBER = re.compile(r"^\d{2,6}[A-Z]?$")
LINE_NUMBER = re.compile(r"^\d+(?:[.,/]\d+)?(?:\"|”|''|IN)?-[A-Z]{1,4}-\d{2,6}(?:-[A-Z0-9]+)*$")
SHEET = re.compile(r"^(?:P&?ID|PFD|DWG|PID)[-_ ]?[A-Z0-9][A-Z0-9-]*$")


@dataclass(frozen=True)
class Tag:
    tag: str  # normalised: letters, a dash, the number (FIC-1003, P-1001A)
    letters: str
    number: str
    family: str  # "instrument" or "equipment"
    cls: str  # controller, valve, transmitter... or pump, vessel...
    measured: str = ""  # instruments: flow, level...


def parse(text: str, *, in_bubble: bool = False) -> Tag | None:
    """The tag a whole word is, or None. ``in_bubble``: the word sits in an instrument circle."""

    word = text.strip().upper().replace("–", "-").replace("—", "-")
    if not word or len(word) > 20 or LINE_NUMBER.match(word) or SHEET.match(word):
        return None
    match = FULL.match(word)
    if not match:
        return None
    letters, number, suffix = match.groups()
    tag = f"{letters}-{number}{suffix}"
    if letters == "U" and not in_bubble:
        return None  # a unit code (U-100), not a thing on the drawing
    if not in_bubble and letters in EQUIPMENT and (len(letters) == 1 or letters in EQUIPMENT_PAIRS):
        return Tag(tag, letters, number + suffix, "equipment", EQUIPMENT[letters])
    cls = instrument_class(letters)
    if cls is None:
        return None
    return Tag(tag, letters, number + suffix, "instrument", cls, MEASURED.get(letters[0], ""))


def instrument_class(letters: str) -> str | None:
    """What an ISA-5.1 instrument does, from its letters; None when they are not ISA."""

    if not letters or letters[0] not in MEASURED or len(letters) < 2:
        return None
    rest = letters[1:]
    # Modifiers right after the first letter: differential, ratio, scan, rate, integrate, safety.
    while rest and rest[0] in "DFJKQS" and len(rest) > 1:
        rest = rest[1:]
    if rest.endswith("V") or rest.endswith("CV") or rest == "Z":
        return "valve"
    if "C" in rest:
        return "controller"
    if rest.endswith("T"):
        return "transmitter"
    if rest.startswith("E"):
        return "element"
    if rest[0] in "IGR":
        return "indicator"
    if rest[0] == "S":
        return "switch"
    if rest[0] == "Y":
        return "relay"
    if rest[0] == "A":
        return "alarm"
    if set(rest) <= set("AHLIRTCVEYSGZOPW"):
        return "instrument"
    return None


def loop_number(tag: Tag) -> str:
    """The number instruments of one loop share (FT-1003, FIC-1003, FV-1003 -> F1003)."""

    return f"{tag.letters[0]}{tag.number}"
