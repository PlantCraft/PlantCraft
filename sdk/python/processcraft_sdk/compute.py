"""``python -m processcraft_sdk.compute``, as compose files before 2026-10-27 start a compute
worker: runs ``plantcraft_sdk.compute``."""

import sys

from plantcraft_sdk.compute import *  # noqa: F403
from plantcraft_sdk.compute.__main__ import main

if __name__ == "__main__":
    sys.exit(main())
