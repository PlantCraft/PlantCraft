"""What a project holds and its rules without the database: paths, names, limits and the
errors the store raises (``ProjectError``, ``Conflict``, ``ReadOnly``)."""

from __future__ import annotations

import re

from modelcraft.i18n import t

# A Modelica file (``Package/Model.mo``) or a package's class order (``Package/package.order``).
PATH = re.compile(
    r"^(?:[A-Za-z_][A-Za-z0-9_]{0,63}(/[A-Za-z_][A-Za-z0-9_]{0,63}){0,5}\.mo"
    r"|([A-Za-z_][A-Za-z0-9_]{0,63}/){1,6}package\.order)$"
)
MAX_FILES = 200
MAX_FILE_BYTES = 1_000_000
MAX_PROJECT_BYTES = 8_000_000
MAX_NAME = 120
MAX_DESCRIPTION = 2000
KEEP_REVISIONS = 50
# A version's name and what changed in it (as Link's algorithms).
MAX_VERSION_NAME = 120
MAX_VERSION_NOTE = 2000
KINDS = ("project", "library")
MAX_GROUP = 60


class ProjectError(ValueError):
    """A change the store refuses, with words a person can act on."""


class Conflict(ProjectError):
    """The file changed since the person opened it."""


class ReadOnly(ProjectError):
    """An example: Models keeps it as it ships it (a person duplicates it to change it)."""


SYSTEM = "modelcraft"  # who seeds and updates the examples


def check_path(path: str) -> str:
    path = (path or "").strip().replace("\\", "/")
    if not PATH.match(path):
        raise ProjectError(
            t(
                "A file is a Modelica name ending in .mo, in up to five folders "
                "(letters, digits and _): {path}",
                path=path[:80],
            )
        )
    return path


def check_name(name: str) -> str:
    name = " ".join((name or "").split())
    if not name or len(name) > MAX_NAME:
        raise ProjectError(t("A project needs a name of up to {n} characters.", n=MAX_NAME))
    return name
