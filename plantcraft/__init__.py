"""PlantCraft: industrial process analysis platform."""

import os as _os

# Settings an older compose file or .env still passes under the former names (renamed 2026-10-27).
try:
    from plantcraft_sdk import settings_compat as _settings_compat
except ImportError:
    # The installer image carries no SDK: the same copy as plantcraft_sdk.settings_compat.adopt.
    _former = "PROCESS" + "CRAFT_"
    for _key in [key for key in _os.environ if key.startswith(_former)]:
        _os.environ["PLANTCRAFT_" + _key[len(_former) :]] = _os.environ[_key]
else:
    _settings_compat.adopt()
