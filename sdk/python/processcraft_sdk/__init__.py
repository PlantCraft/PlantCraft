"""The SDK's name before the rename to PlantCraft (2026-10-27): ``import processcraft_sdk.x``
gives ``plantcraft_sdk.x``, so code and compose files written before it keep working.

New code imports ``plantcraft_sdk``. This package goes away in a later release.
"""

from __future__ import annotations

import importlib
import importlib.abc
import importlib.util
import sys

import plantcraft_sdk

FORMER, CURRENT = "processcraft_sdk", "plantcraft_sdk"


class _Former(importlib.abc.MetaPathFinder, importlib.abc.Loader):
    """``processcraft_sdk.<name>`` is the module ``plantcraft_sdk.<name>`` itself."""

    def find_spec(self, fullname, path=None, target=None):
        if not fullname.startswith(FORMER + ".") or fullname == FORMER + ".compute":
            return None
        current = CURRENT + fullname[len(FORMER) :]
        if importlib.util.find_spec(current) is None:
            return None
        return importlib.util.spec_from_loader(fullname, self)

    def create_module(self, spec):
        return importlib.import_module(CURRENT + spec.name[len(FORMER) :])

    def exec_module(self, module):
        pass


if not any(isinstance(finder, _Former) for finder in sys.meta_path):
    sys.meta_path.insert(0, _Former())

__version__ = plantcraft_sdk.__version__
