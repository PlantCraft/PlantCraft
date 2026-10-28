"""Installing apps from PlantCraft: what the Apps page does, without touching Docker.

PlantCraft verifies a package (upload or catalog), shows it to the
administrator and, once confirmed, hands it to the installer service through a
folder (``<requests>/<id>.json`` plus ``<id>.pcapp``). The installer verifies it
again, runs it and writes its outcome to its own folder, which
:meth:`AppManager.sync` reads back. See docs/app-package.md.
"""

from __future__ import annotations

import json
import os
import re
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from processcraft.files import write_atomic
from processcraft.apps import package as pkg
from processcraft.apps import remote
from processcraft.apps.store import LAUNCHABLE, PENDING, InstalledAppStore
from processcraft.i18n import t
from processcraft.ops.workers import first_only

HEARTBEAT_SECONDS = 30
UPLOAD_HOURS = 24
SYNC_SECONDS = 1.0
EXTERNAL_URL_LIMIT = 300


class AppError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


@dataclass(frozen=True)
class AppSettings:
    install_enabled: bool
    requests_dir: Path
    installer_dir: Path
    trusted_dir: Path
    catalog_url: str | None
    max_bytes: int

    @classmethod
    def from_environment(cls, beside: str | Path) -> AppSettings:
        """Paths default to folders beside the database (local use without Docker)."""

        base = Path(beside).expanduser().resolve().parent
        root = Path(__file__).resolve().parents[2]
        max_mb = os.environ.get("PLANTCRAFT_APP_MAX_MB", "").strip()
        install = os.environ.get("PLANTCRAFT_APP_INSTALL", "on").strip().lower()
        return cls(
            install_enabled=install not in {"off", "false", "0", "no"},
            requests_dir=Path(os.environ.get("PLANTCRAFT_APP_REQUESTS") or base / "app-requests"),
            installer_dir=Path(
                os.environ.get("PLANTCRAFT_INSTALLER_STATE") or base / "installer"
            ),
            trusted_dir=Path(
                os.environ.get("PLANTCRAFT_TRUSTED_PUBLISHERS")
                or root / "deploy" / "trusted-publishers"
            ),
            catalog_url=(os.environ.get("PLANTCRAFT_APP_CATALOG_URL") or "").strip() or None,
            max_bytes=(int(max_mb) if max_mb.isdigit() else 4096) * pkg.MiB,
        )


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _prefix_of(url: str) -> str | None:
    """The proxy prefix of a configured app URL (``/cpm/``), or None for another server."""

    if not url.startswith("/"):
        return None
    first = url.strip("/").split("/", 1)[0]
    return f"/{first}/" if first else None


# What an external app's token may do unless the administrator says otherwise.
EXTERNAL_PERMISSIONS = ["read.assets", "read.signals", "read.series", "write.audit"]


class AppManager:
    def __init__(self, store: InstalledAppStore, settings: AppSettings):
        self.store = store
        self.settings = settings
        self._synced = 0.0
        self.uploads_dir = settings.requests_dir / "uploads"

    # What the page shows -------------------------------------------------------------------

    def installer(self) -> dict[str, Any]:
        path = self.settings.installer_dir / "status" / "heartbeat.json"
        beat = self._read(path) or {}
        try:
            seen = datetime.fromisoformat(str(beat.get("at")))
        except ValueError:
            seen = None
        online = seen is not None and (_now() - seen).total_seconds() < HEARTBEAT_SECONDS
        return {"online": online, "last_seen": seen.isoformat() if seen else None}

    def catalog_switch(self) -> bool:
        """The administrator's switch for the online catalog: off until someone turns it on."""

        return self.store.setting("catalog", "off") == "on"

    def catalog_enabled(self) -> bool:
        return bool(self.settings.catalog_url) and self.catalog_switch()

    def set_catalog(self, enabled: bool, actor: str) -> dict[str, Any]:
        if enabled and not self.settings.catalog_url:
            raise AppError(
                409,
                t(
                    "No catalog address is set on this server (PLANTCRAFT_APP_CATALOG_URL): "
                    "the catalog cannot be turned on."
                ),
            )
        self.store.set_setting("catalog", "on" if enabled else "off", actor)
        return self.settings_view()["catalog"]

    def settings_view(self) -> dict[str, Any]:
        catalog = self.settings.catalog_url
        safe = None
        if catalog:
            parts = urlsplit(catalog)
            safe = f"{parts.scheme}://{parts.hostname or ''}{f':{parts.port}' if parts.port else ''}{parts.path}"
        return {
            "install_enabled": self.settings.install_enabled,
            "installer": self.installer(),
            "catalog": {
                "enabled": self.catalog_enabled(),
                "configured": bool(catalog),
                "switch": self.catalog_switch(),
                "url": safe,
            },
            "trusted_publishers": sorted(pkg.load_trusted(self.settings.trusted_dir)),
            "max_mb": self.settings.max_bytes // pkg.MiB,
        }

    def launchable(self) -> list[dict[str, Any]]:
        return [row for row in self.store.list() if row["status"] in LAUNCHABLE]

    def public(self, row: dict[str, Any]) -> dict[str, Any]:
        manifest = row.get("manifest") or {}
        return {
            "id": row["app_id"],
            "name": row["name"],
            "version": row.get("version"),
            "url": row["url"],
            "origin": row["origin"],
            "status": row["status"],
            "summary": manifest.get("summary") or "",
            "message": row.get("message") or "",
            "publisher": row.get("publisher") or {},
            "permissions": [
                {"id": item, "label": t(pkg.PERMISSIONS.get(item, item))}
                for item in row.get("permissions") or []
            ],
            "previous_version": row.get("previous_version"),
            "has_sbom": bool(row.get("version") and self.sbom(row["app_id"], row["version"])),
            "needs_key": row["origin"] in {"package", "catalog"} and not row.get("key_id"),
            "health": row.get("health"),
            "installed_by": row.get("installed_by"),
            "installed_at": row.get("installed_at"),
            "updated_at": row.get("updated_at"),
        }

    def sbom(self, app_id: str, version: str) -> str | None:
        stored = self.store.sbom(app_id, version)
        if stored:
            return stored
        if not pkg.APP_ID.match(app_id) or not pkg.VERSION.match(version):
            return None
        path = self.settings.installer_dir / "apps" / app_id / "versions" / version / pkg.SBOM
        try:
            if path.stat().st_size <= pkg.LIMITS[pkg.SBOM]:
                return path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return None
        return None

    # Checks shared by every way in ---------------------------------------------------------

    def _guard_install(self) -> None:
        if not self.settings.install_enabled:
            raise AppError(
                409,
                t("App installs are switched off on this server (PLANTCRAFT_APP_INSTALL=off)."),
            )

    def _check_free(
        self,
        app_id: str,
        prefix: str | None,
        configured: list[tuple[str, str]],
        *,
        package: bool,
        summary: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        """Refuses ids, prefixes, ports and uids that are taken; returns the app's current row."""

        for other_id, url in configured:
            if other_id == app_id:
                raise AppError(
                    409,
                    t(
                        "{app} is already configured in PLANTCRAFT_APPS on this server. "
                        "Remove it there first.",
                        app=app_id,
                    ),
                )
        current = self.store.get(app_id)
        if current is not None:
            if current["status"] in PENDING:
                raise AppError(409, t("A request for {app} is still in progress.", app=app_id))
            if package and current["origin"] == "external":
                raise AppError(
                    409,
                    t("{app} is registered as an external app. Remove it first.", app=app_id),
                )
            if not package:
                raise AppError(409, t("{app} is already installed.", app=app_id))
        if prefix:
            taken = {p: other for other, url in configured if (p := _prefix_of(url)) is not None}
            for row in self.store.list():
                if row["app_id"] != app_id and (p := _prefix_of(row["url"])):
                    taken[p] = row["app_id"]
            owner = pkg.prefix_owner(app_id, prefix, taken)
            if owner:
                raise AppError(
                    409, t("{prefix} is already used by {app}.", prefix=prefix, app=owner)
                )
        if summary is not None:
            for row in self.store.list():
                runtime = row.get("manifest") or {}
                if row["app_id"] == app_id:
                    continue
                for key, what in (("port", t("Port")), ("uid", t("User id"))):
                    if runtime.get(key) is not None and runtime.get(key) == summary.get(key):
                        raise AppError(
                            409,
                            t(
                                "{what} {value} is already used by {app}.",
                                what=what,
                                value=summary[key],
                                app=row["app_id"],
                            ),
                        )
        return current

    # Packages ------------------------------------------------------------------------------

    def new_upload_path(self) -> tuple[str, Path]:
        self._guard_install()
        self.uploads_dir.mkdir(parents=True, exist_ok=True)
        self._clean_uploads()
        upload_id = uuid.uuid4().hex
        return upload_id, self.uploads_dir / f"{upload_id}.pcapp"

    def stage(
        self,
        upload_id: str,
        path: Path,
        actor: str,
        configured: list[tuple[str, str]],
        *,
        origin: str = "package",
    ) -> dict[str, Any]:
        """Verifies an uploaded or downloaded package and keeps it for the confirmation."""

        try:
            verified = pkg.verify_package(
                path,
                pkg.load_trusted(self.settings.trusted_dir),
                max_image_bytes=self.settings.max_bytes,
            )
        except pkg.PackageError as exc:
            path.unlink(missing_ok=True)
            raise AppError(422, t("The package was refused: {reason}", reason=str(exc))) from exc
        summary = verified.summary()
        try:
            current = self._check_free(
                summary["id"], summary["prefix"], configured, package=True, summary=summary
            )
        except AppError:
            path.unlink(missing_ok=True)
            raise
        self.store.add_upload(
            upload_id,
            origin=origin,
            summary=summary,
            sbom=verified.sbom_raw.decode("utf-8", "replace"),
            sbom_summary=verified.sbom,
            created_by=actor,
        )
        return self.preview(upload_id, current=current)

    def preview(self, upload_id: str, *, current: dict[str, Any] | None = None) -> dict[str, Any]:
        upload = self._upload(upload_id)
        summary = upload["summary"]
        current = current if current is not None else self.store.get(summary["id"])
        warnings = []
        replaces = current.get("version") if current else None
        if replaces and replaces == summary["version"]:
            warnings.append(
                t(
                    "Version {version} is already installed: it is installed again.",
                    version=replaces,
                )
            )
        elif replaces:
            warnings.append(
                t("This replaces version {old}; you can roll back to it later.", old=replaces)
            )
        if not (current and current.get("key_id")):
            warnings.append(t("An app key is issued for this app when you confirm."))
        return {
            "upload_id": upload_id,
            "origin": upload["origin"],
            "app": {
                **summary,
                "permissions": [
                    {"id": item["id"], "label": t(item["label"])} for item in summary["permissions"]
                ],
            },
            "sbom": upload["sbom_summary"],
            "replaces": replaces,
            "warnings": warnings,
            "installer": self.installer(),
            "uploaded_by": upload.get("created_by"),
            "uploaded_at": upload.get("created_at"),
        }

    def _upload(self, upload_id: str) -> dict[str, Any]:
        upload = self.store.upload(upload_id) if re.fullmatch(r"[0-9a-f]{32}", upload_id) else None
        if upload is None or not (self.uploads_dir / f"{upload_id}.pcapp").is_file():
            raise AppError(404, t("This package is no longer waiting; upload it again."))
        return upload

    def upload_sbom(self, upload_id: str) -> str:
        return self._upload(upload_id)["sbom_json"]

    def discard(self, upload_id: str) -> None:
        self._upload(upload_id)
        (self.uploads_dir / f"{upload_id}.pcapp").unlink(missing_ok=True)
        self.store.delete_upload(upload_id)

    def _clean_uploads(self) -> None:
        cutoff = _now() - timedelta(hours=UPLOAD_HOURS)
        for upload in self.store.uploads():
            try:
                created = datetime.fromisoformat(upload["created_at"])
            except ValueError:
                created = None
            if created is None or created < cutoff:
                (self.uploads_dir / f"{upload['upload_id']}.pcapp").unlink(missing_ok=True)
                self.store.delete_upload(upload["upload_id"])

    def confirm(
        self,
        upload_id: str,
        actor: str,
        configured: list[tuple[str, str]],
        issue_key: Callable[[str], tuple[str, str]],
    ) -> dict[str, Any]:
        """Hands the verified package to the installer. ``issue_key(app_id)`` -> (key id, key)."""

        self._guard_install()
        upload = self._upload(upload_id)
        summary = upload["summary"]
        app_id = summary["id"]
        current = self._check_free(
            app_id, summary["prefix"], configured, package=True, summary=summary
        )
        permissions = [item["id"] for item in summary["permissions"]]
        key_id = current.get("key_id") if current else None
        key = None
        if not key_id:
            key_id, key = issue_key(app_id)
        request_id = self._request(
            "install", app_id, actor, key=key, package=self.uploads_dir / f"{upload_id}.pcapp"
        )
        self.store.save_sbom(app_id, summary["version"], upload["sbom_json"])
        self.store.delete_upload(upload_id)
        row = self.store.save(
            app_id,
            name=summary["name"],
            version=current.get("version") if current else summary["version"],
            url=current["url"] if current else summary["prefix"],
            origin=upload["origin"],
            status="updating" if current else "installing",
            prior_status=current["status"] if current else None,
            message=t("Waiting for the installer: version {version}.", version=summary["version"]),
            publisher=summary["publisher"],
            permissions=permissions,
            manifest={
                "version": summary["version"],
                "summary": summary["summary"],
                "permissions": permissions,
                "image": summary["image"],
                "port": summary["port"],
                "uid": summary["uid"],
                "package_sha256": summary["sha256"],
                "asset_types": list((summary.get("requires") or {}).get("asset_types") or []),
            },
            request_id=request_id,
            request_action="install",
            key_id=key_id,
            installed_by=actor,
        )
        return {**self.public(row), "request_id": request_id, "key_issued": key is not None}

    def _request(
        self,
        action: str,
        app_id: str,
        actor: str,
        *,
        key: str | None = None,
        package: Path | None = None,
    ) -> str:
        request_id = uuid.uuid4().hex
        folder = self.settings.requests_dir
        folder.mkdir(parents=True, exist_ok=True)
        if package is not None:
            package.replace(folder / f"{request_id}.pcapp")
        body = {
            "request_id": request_id,
            "action": action,
            "app_id": app_id,
            "requested_by": actor,
            "requested_at": _now().isoformat(timespec="seconds"),
            "app_key": key,
        }
        write_atomic(folder / f"{request_id}.json", json.dumps(body), mode=0o640)
        return request_id

    def _installed_row(self, app_id: str) -> dict[str, Any]:
        row = self.store.get(app_id) if pkg.APP_ID.match(app_id) else None
        if row is None:
            raise AppError(404, t("App not found."))
        if row["status"] in PENDING:
            raise AppError(409, t("A request for {app} is still in progress.", app=app_id))
        return row

    def uninstall(self, app_id: str, actor: str) -> dict[str, Any]:
        row = self._installed_row(app_id)
        if row["origin"] == "external":
            self.store.delete(app_id)
            return {**self.public(row), "status": "removed"}
        self._guard_install()
        request_id = self._request("uninstall", app_id, actor)
        row = self.store.save(
            app_id,
            status="removing",
            prior_status=row["status"],
            request_id=request_id,
            request_action="uninstall",
            message=t("Waiting for the installer to remove it."),
        )
        return {**self.public(row), "request_id": request_id}

    def rollback(self, app_id: str, actor: str) -> dict[str, Any]:
        row = self._installed_row(app_id)
        if row["origin"] == "external":
            raise AppError(409, t("An external app has no versions here."))
        if not row.get("previous_version"):
            raise AppError(409, t("{app} has no previous version to return to.", app=app_id))
        self._guard_install()
        request_id = self._request("rollback", app_id, actor)
        row = self.store.save(
            app_id,
            status="rolling_back",
            prior_status=row["status"],
            request_id=request_id,
            request_action="rollback",
            message=t(
                "Waiting for the installer: back to {version}.", version=row["previous_version"]
            ),
        )
        return {**self.public(row), "request_id": request_id}

    def set_key(
        self, app_id: str, actor: str, issue_key: Callable[[str], tuple[str, str]]
    ) -> dict[str, Any]:
        row = self._installed_row(app_id)
        if row["origin"] == "external":
            raise AppError(
                409, t("An external app's key is managed under Users and app keys.", app=app_id)
            )
        self._guard_install()
        key_id, key = issue_key(app_id)
        request_id = self._request("set_key", app_id, actor, key=key)
        row = self.store.save(
            app_id,
            status="key",
            prior_status=row["status"],
            request_id=request_id,
            request_action="set_key",
            key_id=key_id,
            message=t("Waiting for the installer to give the app its key."),
        )
        return {**self.public(row), "request_id": request_id}

    # External apps -------------------------------------------------------------------------

    def register_external(
        self,
        app_id: str,
        name: str,
        url: str,
        version: str | None,
        actor: str,
        configured: list[tuple[str, str]],
        issue_key: Callable[[str], tuple[str, str]],
        *,
        permissions: list[str] | None = None,
    ) -> dict[str, Any]:
        """Lists an app that runs elsewhere and gives it an app key (shown once to the admin).

        ``permissions`` is what its token may do in API v1 (``processcraft.apps.scopes``); by
        default it reads the plant and writes to the audit log."""

        granted = EXTERNAL_PERMISSIONS if permissions is None else list(dict.fromkeys(permissions))
        unknown = sorted(set(granted) - set(pkg.PERMISSIONS))
        if unknown:
            raise AppError(422, t("Unknown permissions: {names}.", names=", ".join(unknown)))

        app_id = (app_id or "").strip().lower()
        if not pkg.APP_ID.match(app_id) or app_id in pkg.RESERVED_IDS:
            raise AppError(
                422,
                t("Invalid app id: 3 to 31 lower-case letters or digits, starting with a letter."),
            )
        name = (name or "").strip()
        if not name or len(name) > 60 or any(ord(char) < 32 for char in name):
            raise AppError(422, t("Give the app a name of 1 to 60 characters."))
        url = (url or "").strip()
        prefix = None
        if url.startswith("/"):
            if not pkg.PREFIX.match(url) or url.strip("/") in pkg.RESERVED_SEGMENTS:
                raise AppError(
                    422, t("A path on this server is one segment between slashes, like /myapp/.")
                )
            prefix = url
        else:
            parts = urlsplit(url)
            if (
                parts.scheme not in {"http", "https"}
                or not parts.hostname
                or parts.username
                or parts.password
                or len(url) > EXTERNAL_URL_LIMIT
                or any(ord(char) <= 32 for char in url)
            ):
                raise AppError(
                    422,
                    t(
                        "The address must be http(s)://host/path or a path like /myapp/, without a user or password."
                    ),
                )
        version = (version or "").strip() or None
        if version is not None and not pkg.VERSION.match(version):
            raise AppError(422, t("Version: numbers separated by dots, like 1.2.0."))
        self._check_free(app_id, prefix, configured, package=False)
        health = remote.check_health(url)
        key_id, key = issue_key(app_id)
        row = self.store.save(
            app_id,
            name=name,
            version=version,
            url=url,
            origin="external",
            status="external",
            message="",
            publisher={},
            permissions=granted,
            # What the administrator granted holds, even nothing (processcraft.apps.scopes).
            manifest={"permissions_granted": True},
            health=health,
            key_id=key_id,
            installed_by=actor,
        )
        return {**self.public(row), "app_key": key}

    def check(self, app_id: str) -> dict[str, Any]:
        row = self.store.get(app_id) if pkg.APP_ID.match(app_id) else None
        if row is None:
            raise AppError(404, t("App not found."))
        health = remote.check_health(row["url"])
        return self.public(self.store.save(app_id, health=health))

    # Catalog -------------------------------------------------------------------------------

    def catalog(self) -> list[dict[str, Any]]:
        if not self.catalog_enabled():
            raise AppError(409, t("The online catalog is off on this server."))
        try:
            entries = remote.fetch_index(
                self.settings.catalog_url, pkg.load_trusted(self.settings.trusted_dir)
            )
        except remote.RemoteError as exc:
            raise AppError(502, t("The catalog cannot be used: {reason}", reason=str(exc))) from exc
        installed = {row["app_id"]: row for row in self.store.list()}
        return [
            {
                **entry,
                "installed_version": (installed.get(entry["id"]) or {}).get("version"),
            }
            for entry in entries
        ]

    def download(
        self,
        app_id: str,
        version: str | None,
        actor: str,
        configured: list[tuple[str, str]],
    ) -> dict[str, Any]:
        self._guard_install()
        entries = [entry for entry in self.catalog() if entry["id"] == app_id]
        if version:
            entries = [entry for entry in entries if entry["version"] == version]
        if not entries:
            raise AppError(404, t("The catalog does not list {app}.", app=app_id))
        entry = sorted(entries, key=lambda item: _version_key(item["version"]))[-1]
        upload_id, path = self.new_upload_path()
        try:
            remote.download(self.settings.catalog_url or "", entry, path, self.settings.max_bytes)
        except remote.RemoteError as exc:
            path.unlink(missing_ok=True)
            raise AppError(502, t("The download failed: {reason}", reason=str(exc))) from exc
        return self.stage(upload_id, path, actor, configured, origin="catalog")

    # The installer's answers ---------------------------------------------------------------

    @staticmethod
    def _read(path: Path) -> Any:
        try:
            if path.stat().st_size > 4 * pkg.MiB:
                return None
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None

    def sync(self, *, force: bool = False) -> list[dict[str, Any]]:
        """Applies the installer's outcomes; returns audit events (who, action, app, detail)."""

        if not force and time.monotonic() - self._synced < SYNC_SECONDS:
            return []
        self._synced = time.monotonic()
        # One server process applies an outcome (PLANTCRAFT_WORKERS): never two audit rows.
        with first_only(self.store.path.with_name("apps-sync.lock")) as mine:
            return self._sync() if mine else []

    def _sync(self) -> list[dict[str, Any]]:
        events: list[dict[str, Any]] = []
        status_dir = self.settings.installer_dir / "status"
        installed_doc = self._read(status_dir / "installed.json")
        installed = {}
        if isinstance(installed_doc, dict) and isinstance(installed_doc.get("apps"), list):
            for item in installed_doc["apps"]:
                if isinstance(item, dict) and pkg.APP_ID.match(str(item.get("app_id"))):
                    installed[item["app_id"]] = item
        for row in self.store.list():
            request_id = row.get("request_id")
            if row["status"] not in PENDING or not request_id:
                continue
            outcome = self._read(status_dir / "requests" / f"{request_id}.json")
            if not isinstance(outcome, dict) or outcome.get("state") not in {"done", "failed"}:
                continue
            events.append(self._apply(row, outcome, installed.get(row["app_id"])))
            for suffix in (".json", ".pcapp"):
                (self.settings.requests_dir / f"{request_id}{suffix}").unlink(missing_ok=True)
        if installed_doc is not None:
            events.extend(self._adopt(installed))
        return events

    def _apply(
        self, row: dict[str, Any], outcome: dict[str, Any], running: dict[str, Any] | None
    ) -> dict[str, Any]:
        app_id, action = row["app_id"], row.get("request_action") or "install"
        message = str(outcome.get("message") or "")[:2000]
        event = {
            "username": row.get("installed_by") or "installer",
            "action": f"app.{action}",
            "app_id": app_id,
            "detail": {
                "result": outcome["state"],
                "message": message,
                "version": outcome.get("version"),
            },
        }
        if outcome["state"] == "failed":
            prior = row.get("prior_status")
            self.store.save(
                app_id,
                status=prior if prior and prior not in PENDING else "failed",
                message=message,
                request_id=None,
                request_action=None,
            )
            return event
        if action == "uninstall":
            self.store.delete(app_id)
            if row.get("key_id") and row["key_id"] != "installer":
                event["revoke_key"] = row["key_id"]
            return event
        fields: dict[str, Any] = {
            "status": "running",
            "message": "",
            "request_id": None,
            "request_action": None,
        }
        if running:
            fields.update(
                version=running.get("version"),
                url=running.get("prefix") or row["url"],
                name=running.get("name") or row["name"],
                previous_version=running.get("previous_version"),
            )
            if isinstance(running.get("publisher"), dict):
                fields["publisher"] = running["publisher"]
            if isinstance(running.get("permissions"), list):
                fields["permissions"] = running["permissions"]
            fields["manifest"] = {
                **(row.get("manifest") or {}),
                **{k: running[k] for k in ("version", "summary", "port", "uid") if k in running},
                **_asset_types(running),
            }
        self.store.save(app_id, **fields)
        return event

    def _adopt(self, installed: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
        """Apps installed or removed from the command line (``install.sh --add`` / ``--remove``)."""

        events = []
        rows = {row["app_id"]: row for row in self.store.list()}
        for app_id, item in installed.items():
            row = rows.get(app_id)
            if row is not None and (row["status"] in PENDING or row["origin"] == "external"):
                continue
            prefix = item.get("prefix")
            if not isinstance(prefix, str) or not pkg.PREFIX.match(prefix):
                continue
            version = str(item.get("version") or "")
            if row is not None and row.get("version") == version and row["status"] == "running":
                continue
            permissions = [p for p in item.get("permissions") or [] if p in pkg.PERMISSIONS]
            runtime = {
                key: item[key]
                for key in ("port", "uid")
                if isinstance(item.get(key), int) and not isinstance(item.get(key), bool)
            }
            self.store.save(
                app_id,
                name=str(item.get("name") or app_id)[:60],
                version=version,
                url=prefix,
                origin=row["origin"] if row else "package",
                status="running",
                message="",
                publisher=item.get("publisher") if isinstance(item.get("publisher"), dict) else {},
                permissions=permissions,
                manifest={
                    "version": version,
                    "summary": str(item.get("summary") or "")[:200],
                    "permissions": permissions,
                    **runtime,
                    **_asset_types(item),
                },
                previous_version=item.get("previous_version"),
                key_id=(row or {}).get("key_id") or ("installer" if item.get("has_key") else None),
                installed_by=str(item.get("requested_by") or "cli")[:120],
            )
            events.append(
                {
                    "username": str(item.get("requested_by") or "cli")[:120],
                    "action": "app.install",
                    "app_id": app_id,
                    "detail": {"result": "done", "version": version, "via": "command line"},
                }
            )
        for app_id, row in rows.items():
            if row["origin"] in {"package", "catalog"} and row["status"] in {"running", "failed"}:
                if app_id not in installed and row["status"] == "running":
                    self.store.delete(app_id)
                    events.append(
                        {
                            "username": "cli",
                            "action": "app.uninstall",
                            "app_id": app_id,
                            "detail": {"result": "done", "via": "command line"},
                        }
                    )
        return events


def _asset_types(item: dict[str, Any]) -> dict[str, list[str]]:
    """``{"asset_types": [...]}`` from the installer's record of an app, or {} when it has none.

    The asset page links an app for the types it lists (docs/app-standard.md, section 2).
    """

    value = item.get("asset_types")
    if not isinstance(value, list):
        return {}
    return {
        "asset_types": [kind for kind in value if isinstance(kind, str) and pkg.WORD.match(kind)][
            :50
        ]
    }


def _version_key(version: str) -> tuple:
    main, _, suffix = version.partition("-")
    return (tuple(int(part) for part in main.split(".")), suffix == "", suffix)
