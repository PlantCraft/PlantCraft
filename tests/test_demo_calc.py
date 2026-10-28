"""The demo's calculated signals (``demo_seed.CALC_SIGNALS``) read signals the demo really has.

Historian checks each input of a formula and skips a calculated signal whose input it does not
archive, so a name that drifts from the plant map's tags silently leaves the demo without them.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from processcraft.demo_seed import CALC_SIGNALS

MAP = Path(__file__).resolve().parents[1] / "deploy" / "demo" / "plantcraft-50-loops-map.json"


def test_every_input_of_the_calculated_signals_is_a_signal_of_the_demo():
    plant = json.loads(MAP.read_text(encoding="utf-8"))
    signals = {f"{item['source_id']}:{item['tag']}" for item in plant["signals"]}
    for tag, formula, _unit, _description in CALC_SIGNALS:
        inputs = re.findall(r"\[([^\]]+)\]", formula)
        assert inputs, tag
        assert set(inputs) <= signals, (tag, sorted(set(inputs) - signals))
