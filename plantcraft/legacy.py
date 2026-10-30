"""``processcraft``, the package's name until 0.5.0, as a door to ``plantcraft``.

The images copy this file to ``/app/processcraft/__init__.py``, so what was written for the old
name still runs: ``python -m processcraft.apps.operations`` from an older ``install.sh`` or an
older Backups page, and scripts an administrator kept. Its modules load from ``plantcraft``'s own
folder. New code imports ``plantcraft``.
"""

import plantcraft

__path__ = plantcraft.__path__
