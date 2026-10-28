"""Platform users shared by every application."""

from __future__ import annotations

import hashlib
import hmac
import json
import re
import time
from typing import Any

from argon2 import PasswordHasher
from argon2 import exceptions as argon2_exceptions

from processcraft.auth.access import Access, check_level
from processcraft.config import env_flag
from processcraft.db import Database, Migration, Store, add_columns
from processcraft.i18n import t

# Argon2id with argon2-cffi's defaults (RFC 9106, the low-memory profile: 64 MiB, 3 passes).
# Hashes from before 0.3.x are PBKDF2-SHA256; they still check, and the next sign-in stores the
# password again as Argon2id (``UserStore.verify_password``).
_HASHER = PasswordHasher()
PBKDF2_PREFIX = "pbkdf2_sha256$"


def hash_password(password: str) -> str:
    return _HASHER.hash(password)


def _check_pbkdf2(password: str, encoded: str) -> bool:
    try:
        algorithm, iterations, salt, expected = encoded.split("$")
    except ValueError:
        return False
    if algorithm != "pbkdf2_sha256":
        return False
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt.encode("ascii"), int(iterations)
    )
    return hmac.compare_digest(digest.hex(), expected)


def check_password(password: str, encoded: str | None) -> bool:
    encoded = encoded or ""
    if encoded.startswith(PBKDF2_PREFIX):
        return _check_pbkdf2(password, encoded)
    try:
        return _HASHER.verify(encoded, password)
    except (argon2_exceptions.VerificationError, argon2_exceptions.InvalidHashError):
        return False


def needs_rehash(encoded: str) -> bool:
    """True for a PBKDF2 hash, or an Argon2 hash made with other parameters than today's."""

    if encoded.startswith(PBKDF2_PREFIX):
        return True
    try:
        return _HASHER.check_needs_rehash(encoded)
    except argon2_exceptions.InvalidHashError:
        return True


# The demonstration team. Real installations turn these off with
# PLANTCRAFT_DEMO_USERS=false and create people with ``processcraft users``.
DEMO_USERS = (
    {"username": "ana.lima", "display_name": "Ana Lima", "role": "Control engineering"},
    {"username": "marina.costa", "display_name": "Marina Costa", "role": "Control engineering"},
    {"username": "rafael.souza", "display_name": "Rafael Souza", "role": "Control engineering"},
    {"username": "carlos.menezes", "display_name": "Carlos Menezes", "role": "Operations"},
    {"username": "julia.prado", "display_name": "Júlia Prado", "role": "Engineering lead"},
)
_ORDER = " ".join(
    f"WHEN '{user['username']}' THEN {index}" for index, user in enumerate(DEMO_USERS)
)


def demo_users_enabled() -> bool:
    return env_flag("PLANTCRAFT_DEMO_USERS", True)


_COLUMNS = (
    "username, display_name, role, active, kind, is_admin, access_level, applications_json, "
    "profile_json, app_roles_json, auth_source, asset_scope_json"
)
# Where a person signs in: a password kept here, or the company directory (LDAP or OIDC,
# ``processcraft.directory``), which then owns their access.
AUTH_SOURCES = ("local", "ldap", "oidc")

# What a person says about themselves (the profile page), with each field's longest length.
# ``role`` (a column of its own, older) is the sector or team: "Process engineering".
PROFILE_FIELDS = {
    "job_title": 120,
    "affiliation": 10,
    "organization": 120,
    "email": 200,
    "phone": 40,
    "unit": 120,
}
AFFILIATIONS = ("internal", "external")
APP_ROLES = ("viewer", "editor")


def _loads(raw: str | None, empty: Any) -> Any:
    """JSON of the expected kind (that of ``empty``), else ``empty``."""

    try:
        value = json.loads(raw) if raw else empty
    except ValueError:
        return empty
    return value if isinstance(value, type(empty)) else empty


def _user(row: Any) -> dict[str, Any]:
    user = dict(row)
    # None: every application; a list: only those.
    applications = _loads(user.pop("applications_json", None), [None])
    user["applications"] = None if applications == [None] else applications
    profile = _loads(user.pop("profile_json", None), {}) or {}
    user["profile"] = {key: str(profile.get(key) or "") for key in PROFILE_FIELDS}
    roles = _loads(user.pop("app_roles_json", None), {}) or {}
    user["app_roles"] = {str(key): value for key, value in roles.items() if value in APP_ROLES}
    user["auth_source"] = user.get("auth_source") or "local"
    # None: the whole plant; a list: only those assets and everything under them.
    scope = _loads(user.pop("asset_scope_json", None), [None])
    user["asset_scope"] = None if scope == [None] else [str(item) for item in scope]
    return user


# One plain address: no spaces, line breaks or the separators of an address list, so it is
# safe in an email header (a line break there would stop the whole outbox).
_ADDRESS_PART = r"[^\s@,;:<>()\[\]\\\"]+"
EMAIL = re.compile(rf"{_ADDRESS_PART}@{_ADDRESS_PART}\.{_ADDRESS_PART}")


def is_email(text: str) -> bool:
    """Whether ``text`` is one plain address (``name@host.domain``)."""

    return bool(EMAIL.fullmatch(text)) and text.isprintable()


def check_profile(profile: dict[str, Any]) -> dict[str, str]:
    """The profile's known fields, trimmed and checked (an empty string clears a field)."""

    cleaned: dict[str, str] = {}
    for key, limit in PROFILE_FIELDS.items():
        value = str(profile.get(key) or "").strip()
        if len(value) > limit:
            raise ValueError(
                t("{field} is longer than {count} characters.", field=key, count=limit)
            )
        cleaned[key] = value
    if cleaned["affiliation"] and cleaned["affiliation"] not in AFFILIATIONS:
        raise ValueError(t("Choose internal or external."))
    email = cleaned["email"]
    if email and not is_email(email):
        raise ValueError(t("Enter a valid email address."))
    return cleaned


class UserStore(Store):
    """Users that can own actions, comment and run analyses."""

    SCHEMA = """
    CREATE TABLE IF NOT EXISTS workspace_users (
        username TEXT PRIMARY KEY,
        display_name TEXT NOT NULL,
        role TEXT NOT NULL,
        active INTEGER NOT NULL DEFAULT 1,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );
    """
    MIGRATIONS = (
        Migration(
            "columns-before-0.5",
            add_columns(
                "workspace_users",
                {
                    "password_hash": "TEXT",
                    "kind": "TEXT NOT NULL DEFAULT 'person'",
                    "is_admin": "INTEGER NOT NULL DEFAULT 0",
                    # NULL: the default of the installation (see ``access``).
                    "access_level": "TEXT",
                    # NULL: every application.
                    "applications_json": "TEXT",
                    "profile_json": "TEXT",
                    # {app id: "viewer" | "editor"}: the role in that app instead of the level's.
                    "app_roles_json": "TEXT",
                    # Unix seconds; tokens issued before it are refused (``revoke_tokens``).
                    "tokens_valid_after": "INTEGER",
                    "auth_source": "TEXT NOT NULL DEFAULT 'local'",
                    # The directory's own id of the person (LDAP DN or GUID, OIDC ``sub``).
                    "external_id": "TEXT",
                },
            ),
        ),
        # The roots of the asset tree the person sees (docs/asset-scope.md); NULL: all of it.
        Migration("asset-scope", add_columns("workspace_users", {"asset_scope_json": "TEXT"})),
    )

    def __init__(self, db: Database):
        super().__init__(db)
        with self._lock, self._write() as connection:
            # The old placeholder account gives way to the demonstration team.
            connection.execute(
                "UPDATE workspace_users SET active = 0 WHERE username = 'test_user' AND display_name = 'Test User'"
            )
        if demo_users_enabled():
            self._seed_demo_users()

    def _seed_demo_users(self) -> None:
        now = self._now()
        with self._lock, self._write() as connection:
            for user in DEMO_USERS:
                connection.execute(
                    """
                    INSERT INTO workspace_users
                    (username, display_name, role, active, created_at, updated_at)
                    VALUES (?, ?, ?, 1, ?, ?)
                    ON CONFLICT(username) DO UPDATE SET
                        display_name = excluded.display_name,
                        role = excluded.role,
                        active = 1,
                        updated_at = excluded.updated_at
                    """,
                    (
                        user["username"],
                        user["display_name"],
                        user["role"],
                        now,
                        now,
                    ),
                )

    def list_users(
        self, *, active_only: bool = True, kind: str | None = None
    ) -> list[dict[str, Any]]:
        """Users in display order; ``kind="person"`` leaves out the specialist bots."""

        clauses = (["active = 1"] if active_only else []) + (["kind = ?"] if kind else [])
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                f"""
                SELECT {_COLUMNS}
                FROM workspace_users{where}
                ORDER BY CASE username {_ORDER} ELSE 99 END, display_name
                """,
                [kind] if kind else [],
            ).fetchall()
        return [_user(row) for row in rows]

    def get_user(self, username: str | None) -> dict[str, Any] | None:
        if not username:
            return None
        with self._lock, self._connect() as connection:
            row = connection.execute(
                f"SELECT {_COLUMNS} FROM workspace_users WHERE username = ?",
                (username,),
            ).fetchone()
        return _user(row) if row else None

    def upsert_user(
        self, username: str, display_name: str, role: str, *, kind: str = "person"
    ) -> dict[str, Any]:
        username = username.strip().lower()
        # ":" is reserved: ``app:<id>`` is the subject of an app's service token, which the apps
        # trust offline (a person named ``app:histcraft`` would act as that app); "/" ends a path.
        if not username or any(char.isspace() or char in "@#:/\\" for char in username):
            raise ValueError(t("Invalid username: use letters, digits, dot or hyphen."))
        now = self._now()
        with self._lock, self._write() as connection:
            connection.execute(
                """
                INSERT INTO workspace_users
                (username, display_name, role, active, kind, created_at, updated_at)
                VALUES (?, ?, ?, 1, ?, ?, ?)
                ON CONFLICT(username) DO UPDATE SET
                    display_name = excluded.display_name,
                    role = excluded.role,
                    kind = excluded.kind,
                    active = 1,
                    updated_at = excluded.updated_at
                """,
                (username, display_name.strip() or username, role.strip(), kind, now, now),
            )
        return self.get_user(username) or {}

    def set_password(self, username: str, password: str) -> None:
        if len(password) < 8:
            raise ValueError(t("The password must have at least 8 characters."))
        if self.identity(username)[0] != "local":
            raise ValueError(
                t("This person signs in with the company directory: their password is kept there.")
            )
        with self._lock, self._write() as connection:
            cursor = connection.execute(
                "UPDATE workspace_users SET password_hash = ?, updated_at = ? WHERE username = ?",
                (hash_password(password), self._now(), username),
            )
        if cursor.rowcount == 0:
            raise ValueError(t("User not found: {username}.", username=username))
        self.revoke_tokens(username)

    def _password_hash(self, username: str) -> str | None:
        """The active user's stored hash; None for an unknown or inactive user."""

        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT password_hash FROM workspace_users WHERE username = ? AND active = 1",
                (username,),
            ).fetchone()
        return (row["password_hash"] or "") if row else None

    def verify_password(self, username: str, password: str, *, rehash: bool = False) -> bool:
        """The password checks. ``rehash`` (sign-in only): store an old hash again as Argon2id.

        The session fingerprint comes from the stored hash, so rehashing ends the person's other
        sessions once; a password check inside a session (an admin confirming an action) never
        rehashes, or it would end the very session it confirms.
        """

        stored = self._password_hash(username)
        if stored is None or not self.is_person(username) or not check_password(password, stored):
            return False
        if rehash and needs_rehash(stored):
            with self._lock, self._write() as connection:
                connection.execute(
                    "UPDATE workspace_users SET password_hash = ? WHERE username = ? AND password_hash = ?",
                    (hash_password(password), username, stored),
                )
        return True

    def deactivate(self, username: str) -> None:
        with self._lock, self._write() as connection:
            connection.execute(
                "UPDATE workspace_users SET active = 0, updated_at = ? WHERE username = ?",
                (self._now(), username),
            )
        self.revoke_tokens(username)

    def activate(self, username: str) -> None:
        with self._lock, self._write() as connection:
            connection.execute(
                "UPDATE workspace_users SET active = 1, updated_at = ? WHERE username = ?",
                (self._now(), username),
            )

    def update_profile(self, username: str, display_name: str, role: str) -> None:
        """Name and function text of an existing person (``upsert_user`` also reactivates)."""

        with self._lock, self._write() as connection:
            cursor = connection.execute(
                "UPDATE workspace_users SET display_name = ?, role = ?, updated_at = ? WHERE username = ?",
                (display_name.strip() or username, role.strip(), self._now(), username),
            )
        if cursor.rowcount == 0:
            raise ValueError(t("User not found: {username}.", username=username))

    def set_profile(self, username: str, profile: dict[str, Any]) -> dict[str, str]:
        """Job title, internal or external, organization, email, phone and unit."""

        cleaned = check_profile(profile)
        with self._lock, self._write() as connection:
            cursor = connection.execute(
                "UPDATE workspace_users SET profile_json = ?, updated_at = ? WHERE username = ?",
                (json.dumps(cleaned, ensure_ascii=False), self._now(), username),
            )
        if cursor.rowcount == 0:
            raise ValueError(t("User not found: {username}.", username=username))
        return cleaned

    def set_app_roles(self, username: str, roles: dict[str, str]) -> None:
        """The person's role in given apps ("viewer" or "editor"), instead of their level's."""

        bad = sorted(value for value in roles.values() if value not in APP_ROLES)
        if bad:
            raise ValueError(t("An app role is viewer or editor."))
        before = self.get_user(username)
        if before is None:
            raise ValueError(t("User not found: {username}.", username=username))
        cleaned = {key: roles[key] for key in sorted(roles)}
        if cleaned == before.get("app_roles"):
            return
        with self._lock, self._write() as connection:
            connection.execute(
                "UPDATE workspace_users SET app_roles_json = ?, updated_at = ? WHERE username = ?",
                (json.dumps(cleaned) if cleaned else None, self._now(), username),
            )
        # Tokens carry each app's role: the ones issued before the change must go.
        self.revoke_tokens(username)

    def set_asset_scope(self, username: str, roots: list[str] | None) -> None:
        """The assets the person sees: those ``roots`` and everything under them (``None``: the
        whole plant). The roots are checked by the caller, which knows the tree."""

        before = self.get_user(username)
        if before is None:
            raise ValueError(t("User not found: {username}.", username=username))
        cleaned = None if roots is None else sorted(set(roots))
        if cleaned == before.get("asset_scope"):
            return
        with self._lock, self._write() as connection:
            connection.execute(
                "UPDATE workspace_users SET asset_scope_json = ?, updated_at = ? WHERE username = ?",
                (None if cleaned is None else json.dumps(cleaned), self._now(), username),
            )
        # Tokens carry the scope: the ones issued before the change must go.
        self.revoke_tokens(username)

    def set_admin(self, username: str, admin: bool = True) -> None:
        """Administrators change the platform: specialists, rounds, method code.

        ``is_admin`` stays as the compatibility alias of the ``admin`` level.
        """

        user = self.get_user(username)
        if user is None:
            raise ValueError(t("User not found: {username}.", username=username))
        if admin:
            self.set_access(username, "admin", user.get("applications"))
        elif user.get("is_admin") or user.get("access_level") == "admin":
            self.set_access(username, "editor", user.get("applications"))

    def set_access(self, username: str, level: str, applications: list[str] | None = None) -> None:
        """The person's access level and applications (``None``: all of them)."""

        check_level(level)
        apps = None if applications is None else json.dumps(sorted(set(applications)))
        before = self.get_user(username)
        with self._lock, self._write() as connection:
            cursor = connection.execute(
                """
                UPDATE workspace_users SET access_level = ?, applications_json = ?, is_admin = ?, updated_at = ?
                WHERE username = ?
                """,
                (level, apps, int(level == "admin"), self._now(), username),
            )
        if cursor.rowcount == 0:
            raise ValueError(t("User not found: {username}.", username=username))
        old_apps = before.get("applications") if before else None
        if before and (
            before.get("access_level") != level
            or (None if old_apps is None else sorted(set(old_apps)))
            != (None if applications is None else sorted(set(applications)))
        ):
            # Tokens carry the level and the apps: the ones issued before the change must go.
            self.revoke_tokens(username)

    def revoke_tokens(self, username: str) -> int:
        """End every token ``username`` holds now; returns the new ``tokens_valid_after``.

        One second ahead, so a token issued in this same second is refused too (``iat`` is in
        whole seconds) and the next one issued (``iat`` at least this) is accepted; and always
        past the previous one, so a second change in the same second still ends the tokens
        issued after the first.
        """

        with self._lock, self._write() as connection:
            row = connection.execute(
                "SELECT tokens_valid_after FROM workspace_users WHERE username = ?", (username,)
            ).fetchone()
            previous = int(row["tokens_valid_after"] or 0) if row else 0
            stamp = max(int(time.time()) + 1, previous + 1)
            connection.execute(
                "UPDATE workspace_users SET tokens_valid_after = ? WHERE username = ?",
                (stamp, username),
            )
        return stamp

    def tokens_valid_after(self, username: str) -> int:
        """Unix seconds before which ``username``'s tokens are refused (0: none)."""

        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT tokens_valid_after FROM workspace_users WHERE username = ?", (username,)
            ).fetchone()
        return int(row["tokens_valid_after"] or 0) if row else 0

    def revoked_since(self, moment: int) -> list[tuple[str, int]]:
        """``(username, tokens_valid_after)`` of people whose tokens were ended after ``moment``."""

        with self._lock, self._connect() as connection:
            rows = connection.execute(
                """
                SELECT username, tokens_valid_after FROM workspace_users
                WHERE tokens_valid_after > ? ORDER BY username
                """,
                (int(moment),),
            ).fetchall()
        return [(row["username"], int(row["tokens_valid_after"])) for row in rows]

    def access(self, username: str | None, *, default: str = "editor") -> Access | None:
        """What an active person may do; ``default`` for people with no level set yet."""

        user = self.get_user(username)
        if not user or not user.get("active"):
            return None
        level = user.get("access_level") or ("admin" if user.get("is_admin") else default)
        apps = user.get("applications")
        if level == "admin":
            return Access(level, None)
        roles = tuple(sorted((user.get("app_roles") or {}).items()))
        return Access(level, None if apps is None else tuple(apps), roles)

    def is_admin(self, username: str | None) -> bool:
        user = self.get_user(username)
        return bool(user and user.get("active") and user.get("is_admin"))

    def password_fingerprint(self, username: str) -> str:
        """Changes whenever the password does, so old sessions stop working.

        A person from the company directory has no password here: their fingerprint is their
        directory identity, so a new password set here (they become local) ends the session.
        """

        encoded = self._password_hash(username) or ""
        if not encoded:
            source, external_id = self.identity(username)
            if source != "local" and external_id:
                encoded = f"directory:{source}:{external_id}"
        return hashlib.sha256(encoded.encode()).hexdigest()[:16]

    # The company directory (``processcraft.directory``) ----------------------------------

    def identity(self, username: str) -> tuple[str, str | None]:
        """``(auth_source, external_id)`` of a person; ``("local", None)`` when unknown."""

        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT auth_source, external_id FROM workspace_users WHERE username = ?",
                (username,),
            ).fetchone()
        if not row:
            return "local", None
        return row["auth_source"] or "local", row["external_id"]

    def find_external(self, source: str, external_id: str) -> str | None:
        """The username the directory's person ``external_id`` signed in as before."""

        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT username FROM workspace_users WHERE auth_source = ? AND external_id = ?",
                (source, external_id),
            ).fetchone()
        return row["username"] if row else None

    def set_identity(self, username: str, source: str, external_id: str | None) -> None:
        """Where the person signs in; a directory person keeps no password here."""

        if source not in AUTH_SOURCES:
            raise ValueError(source)
        with self._lock, self._write() as connection:
            cursor = connection.execute(
                """
                UPDATE workspace_users SET auth_source = ?, external_id = ?,
                    password_hash = CASE WHEN ? = 'local' THEN password_hash ELSE NULL END,
                    updated_at = ?
                WHERE username = ?
                """,
                (source, external_id, source, self._now(), username),
            )
        if cursor.rowcount == 0:
            raise ValueError(t("User not found: {username}.", username=username))

    def is_active_person(self, username: str | None) -> bool:
        user = self.get_user(username)
        return bool(user and user.get("active") and user.get("kind", "person") == "person")

    def is_person(self, username: str | None) -> bool:
        user = self.get_user(username)
        return bool(user) and user.get("kind", "person") == "person"

    def has_password(self, username: str) -> bool:
        return bool(self._password_hash(username))
