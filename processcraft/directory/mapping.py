"""From a person the company directory vouched for to a person here: their account (created on
the first sign-in), their profile (from the directory's attributes) and their access (from the
directory's groups, through the rules set in Settings). The directory is the source of truth: each
sign-in brings the access and the mapped groups up to date.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from processcraft.auth.access import ACCESS_LEVELS
from processcraft.auth.users import PROFILE_FIELDS
from processcraft.directory.settings import DirectorySettings, GroupRule
from processcraft.i18n import t

_RANK = {level: index for index, level in enumerate(ACCESS_LEVELS)}
_ROLE_RANK = {"viewer": 0, "editor": 1}


class DirectoryRefused(Exception):
    """The directory or the rules said no; the message is for the person signing in."""


class WrongCredentials(DirectoryRefused):
    """A wrong name or password (said the same way as for a password kept here)."""


class DirectoryUnavailable(Exception):
    """The directory or the provider did not answer (or answered something unusable)."""


@dataclass(frozen=True)
class DirectoryPerson:
    """What the directory says about a person who just proved who they are."""

    source: str  # "ldap" or "oidc"
    external_id: str
    username: str
    display_name: str = ""
    groups: tuple[str, ...] = ()
    # The directory's values for the profile fields here (job_title, email, ...) and "role".
    profile: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class MappedAccess:
    level: str
    apps: tuple[str, ...] | None
    app_roles: dict[str, str]
    groups: tuple[str, ...]
    matched: tuple[str, ...]  # the rules' ``match`` that applied

    def as_dict(self) -> dict[str, Any]:
        return {
            "level": self.level,
            "apps": None if self.apps is None else list(self.apps),
            "app_roles": self.app_roles,
            "groups": list(self.groups),
            "matched": list(self.matched),
        }


def _group_keys(name: str) -> set[str]:
    """The ways a rule may name a group: its full name or DN, its CN, its last path part."""

    text = name.strip().lower()
    keys = {text, text.strip("/")}
    first = text.split(",", 1)[0]
    if first.startswith("cn="):
        keys.add(first[3:].strip())
    if "/" in text:
        keys.add(text.rstrip("/").rsplit("/", 1)[-1])
    return {key for key in keys if key}


def rule_matches(rule: GroupRule, groups: tuple[str, ...]) -> bool:
    wanted = _group_keys(rule.match) if "=" not in rule.match else {rule.match.strip().lower()}
    return any(wanted & _group_keys(group) for group in groups)


def map_access(settings: DirectorySettings, groups: tuple[str, ...]) -> MappedAccess | None:
    """The access the rules give someone in ``groups``; None when they may not sign in."""

    matched = [rule for rule in settings.rules if rule_matches(rule, groups)]
    if not matched:
        if settings.unmatched == "deny":
            return None
        return MappedAccess(settings.unmatched, None, {}, (), ())
    level = max((rule.level for rule in matched), key=_RANK.__getitem__)
    if any(rule.apps is None for rule in matched):
        apps = None
    else:
        apps = tuple(sorted({app for rule in matched for app in rule.apps or ()}))
    roles: dict[str, str] = {}
    for rule in matched:
        for app, role in rule.app_roles:
            roles[app] = max(roles.get(app, role), role, key=_ROLE_RANK.__getitem__)
    member_of = tuple(dict.fromkeys(group for rule in matched for group in rule.groups))
    return MappedAccess(
        level, apps, dict(sorted(roles.items())), member_of, tuple(rule.match for rule in matched)
    )


_USERNAME_BAD = re.compile(r"[\s@#:/\\]+")


def local_username(value: str) -> str:
    """The name here for a directory login: "DOMAIN\\Ana.Lima" or "ana.lima@company" -> "ana.lima"."""

    text = value.strip()
    if "\\" in text:
        text = text.rsplit("\\", 1)[-1]
    if "@" in text:
        text = text.split("@", 1)[0]
    return _USERNAME_BAD.sub(".", text).strip(".").lower()[:120]


class Provisioner:
    """Creates and updates the people the directory signs in (users and groups stores)."""

    def __init__(self, users: Any, groups: Any, audit: Any | None = None):
        self.users = users
        self.groups = groups
        self.audit = audit

    def _account(self, person: DirectoryPerson, reserved: set[str]) -> tuple[str, bool]:
        """``(username, created)``: the account this person had, or a new one."""

        known = self.users.find_external(person.source, person.external_id)
        if known:
            return known, False
        username = local_username(person.username)
        if not username:
            raise DirectoryRefused(t("The directory gave no usable username for this person."))
        if username in reserved:
            raise DirectoryRefused(
                t(
                    "{username} is the installation's own admin account: it signs in with its password here.",
                    username=username,
                )
            )
        existing = self.users.get_user(username)
        if existing is None:
            return username, True
        source, external_id = self.users.identity(username)
        adoptable = (
            existing.get("kind", "person") == "person"
            and not external_id
            and (
                source == person.source
                or (source == "local" and not self.users.has_password(username))
            )
        )
        if not adoptable:
            raise DirectoryRefused(
                t(
                    "An account named {username} already exists in PlantCraft and signs in another way. Ask an admin to rename it.",
                    username=username,
                )
            )
        return username, False

    def sign_in(
        self, person: DirectoryPerson, settings: DirectorySettings, *, reserved: set[str]
    ) -> str:
        """The username to open a session for; raises ``DirectoryRefused`` with the reason."""

        access = map_access(settings, person.groups)
        if access is None:
            raise DirectoryRefused(
                t(
                    "Your company account is not in any group that has access to PlantCraft. Ask your admin."
                )
            )
        username, created = self._account(person, reserved)
        existing = self.users.get_user(username)
        if existing is not None and not existing.get("active"):
            raise DirectoryRefused(t("This account is turned off in PlantCraft. Ask your admin."))
        profile = person.profile
        name = person.display_name.strip() or (existing or {}).get("display_name") or username
        role = profile.get("role") or (existing or {}).get("role") or ""
        if created:
            self.users.upsert_user(username, name, role)
        else:
            self.users.update_profile(username, name, role)
        self.users.set_identity(username, person.source, person.external_id)
        before = (self.users.get_user(username) or {}).get("profile") or {}
        merged = {key: (profile.get(key) or before.get(key) or "") for key in PROFILE_FIELDS}
        try:
            self.users.set_profile(username, merged)
        except ValueError:
            # A value the profile refuses (an odd email): keep what was there.
            pass
        self.users.set_access(
            username, access.level, None if access.apps is None else list(access.apps)
        )
        self.users.set_app_roles(username, access.app_roles)
        self._sync_groups(username, settings, access)
        if created and self.audit is not None:
            self.audit.record(
                username,
                "user.created",
                f"user:{username}",
                {"source": person.source, "level": access.level},
                app_id="processcraft",
            )
        return username

    def _sync_groups(
        self, username: str, settings: DirectorySettings, access: MappedAccess
    ) -> None:
        """Membership of the groups the rules name: in the matched ones, out of the others."""

        managed = {group for rule in settings.rules for group in rule.groups}
        current = {group["group_id"] for group in self.groups.of(username)}
        for group_id in sorted(managed):
            if group_id in access.groups and group_id not in current:
                self.groups.add_member(group_id, username)
            elif group_id not in access.groups and group_id in current:
                self.groups.remove_member(group_id, username)
