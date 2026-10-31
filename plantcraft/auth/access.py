"""Access profiles: what a person may do (level) and where (applications).

Levels, from least to most:

- ``dashboards``: only the dashboards and the queries behind their panels.
- ``viewer``: reads everything it has access to; writes only conversations
  (comments, messages, marking notifications read). No analyses, no edits.
- ``editor``: engineering work: runs analyses, edits protocols, actions and
  dashboards.
- ``admin``: everything, including users, specialists, rounds and method code.

Applications: ``None`` means every installed application; otherwise only the
listed ``application_id`` values. Administrators always see every application.

App roles: a person may have another role in a given app than their level gives
(``viewer`` or ``editor``: an engineer who only reads the Historian, an operator
who edits in Alarms). Administrators edit everywhere.

Operations: an app role on ``operations`` (Desk-like built-in app, docs/operations.md section 4)
lets someone who is not an administrator open Operations: the suite's status, load and logs
(the plant's IT, an integrator's support). It changes nothing else: backups, updates and the
load limits stay with the administrators.
"""

from __future__ import annotations

from dataclasses import dataclass

from plantcraft.i18n import t

ACCESS_LEVELS = ("dashboards", "viewer", "editor", "admin")
LEVEL_LABELS = {
    "admin": "Admin",
    "editor": "Editor",
    "viewer": "Viewer",
    "dashboards": "Dashboards only",
}
_RANK = {level: index for index, level in enumerate(ACCESS_LEVELS)}
# The built-in Operations app (status, load, logs): its id in a person's app roles.
OPERATIONS_APP = "operations"


def level_label(level: str) -> str:
    """The access level's name in the current language."""

    return t(LEVEL_LABELS[level])


def check_level(level: str) -> str:
    if level not in _RANK:
        raise ValueError(
            t(
                "Invalid access level: {level}. Use {levels}.",
                level=level,
                levels=", ".join(ACCESS_LEVELS),
            )
        )
    return level


@dataclass(frozen=True)
class Access:
    level: str = "admin"
    applications: tuple[str, ...] | None = None
    # ((app id, "viewer" | "editor"), ...): the role in those apps instead of the level's.
    app_roles: tuple[tuple[str, str], ...] = ()

    def app_role(self, application_id: str) -> str:
        """ "editor" or "viewer" in that app (whether the person may open it is ``allows``)."""

        if not self.is_admin:
            for app_id, role in self.app_roles:
                if app_id == application_id:
                    return role
        return "editor" if self.can_edit else "viewer"

    def at_least(self, level: str) -> bool:
        return _RANK[self.level] >= _RANK[level]

    @property
    def is_admin(self) -> bool:
        return self.level == "admin"

    @property
    def can_operate(self) -> bool:
        """May open Operations (status, load, logs): an administrator, or an Operations role."""

        return self.is_admin or any(app_id == OPERATIONS_APP for app_id, _ in self.app_roles)

    @property
    def can_edit(self) -> bool:
        return self.at_least("editor")

    def allows(self, application_id: str | None) -> bool:
        if not application_id or self.is_admin or self.applications is None:
            return True
        return application_id in self.applications

    def as_dict(self) -> dict[str, object]:
        return {
            "level": self.level,
            "label": level_label(self.level),
            "applications": list(self.applications) if self.applications is not None else None,
            "app_roles": dict(self.app_roles),
            "can_edit": self.can_edit,
            "can_operate": self.can_operate,
            "is_admin": self.is_admin,
        }
