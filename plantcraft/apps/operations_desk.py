"""What PlantCraft shows and asks about backups, restores and updates (docs/operations.md).

PlantCraft never touches Docker or the install folder: it reads what the installer and its
driver write to ``data/installer/status`` (mounted read-only) and writes requests to
``data/app-requests``, as the Apps page does. The installer checks each request again.
"""

from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from plantcraft.apps.manager import AppError, AppSettings
from plantcraft.config import plant_timezone, valid_zone
from plantcraft.i18n import t

ACTIONS = ("backup", "verify", "restore", "drill", "prune")
NAME = re.compile(r"^\d{8}-\d{6}-[a-z][a-z0-9-]{1,30}$")
SETTINGS_FILE = "ops-settings.json"
TIME = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
# "local" is the installation's time zone (Setup › Installation), resolved for the installer
# into ``local_zone`` each time the schedule or that zone is saved.
DEFAULTS = {
    "enabled": True,
    "daily_at": "02:00",
    "timezone": "local",
    "drill": True,
    "drill_weekday": 6,
    "drill_at": "03:00",
}
STATUS_LIMIT = 4 * 1024 * 1024


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class OperationsDesk:
    def __init__(self, settings: AppSettings):
        self.settings = settings

    @property
    def status_dir(self) -> Path:
        return self.settings.installer_dir / "status"

    def read(self, name: str) -> Any:
        """A status file of the installer or its driver (JSON); None when absent or unreadable."""

        path = self.status_dir / name
        try:
            if path.stat().st_size > STATUS_LIMIT:
                return None
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None

    def overview(self) -> dict[str, Any]:
        backups = self.read("backups.json") or {}
        return {
            "running": self.read("operation.json"),
            "backups": backups.get("backups") or [],
            "free_bytes": backups.get("free_bytes"),
            "indexed_at": backups.get("at"),
            "history": (self.read("operations.json") or {}).get("operations") or [],
            "drill": self.read("drill.json"),
            "update": self.read("update.json"),
            "release": self.read("release.json"),
            "schedule": {**self.schedule(), "state": self.read("schedule.json") or {}},
        }

    def schedule(self) -> dict[str, Any]:
        try:
            stored = json.loads((self.settings.requests_dir / SETTINGS_FILE).read_text("utf-8"))
        except (OSError, ValueError):
            stored = {}
        stored = stored.get("backup") if isinstance(stored, dict) else {}
        stored = stored if isinstance(stored, dict) else {}
        return {key: stored.get(key, value) for key, value in DEFAULTS.items()}

    def set_schedule(self, changes: dict[str, Any]) -> dict[str, Any]:
        value = {**self.schedule(), **{k: v for k, v in changes.items() if k in DEFAULTS}}
        for key in ("enabled", "drill"):
            if not isinstance(value[key], bool):
                raise AppError(422, t("Invalid schedule."))
        for key in ("daily_at", "drill_at"):
            if not isinstance(value[key], str) or not TIME.match(value[key]):
                raise AppError(422, t("Times are written HH:MM, for example 02:00."))
        zone = value["timezone"]
        if not isinstance(zone, str) or not (zone == "local" or valid_zone(zone)):
            raise AppError(422, t("Unknown time zone."))
        weekday = value["drill_weekday"]
        if not isinstance(weekday, int) or isinstance(weekday, bool) or not 0 <= weekday <= 6:
            raise AppError(422, t("Invalid schedule."))
        # The installer has no database: it reads the zone "local" means from the file.
        stored = {**value, "local_zone": plant_timezone(fresh=True).key}
        self._write(self.settings.requests_dir / SETTINGS_FILE, {"backup": stored})
        return value

    def request(self, action: str, actor: str, *, name: str | None = None) -> dict[str, Any]:
        if action not in ACTIONS:
            raise AppError(404, t("Unknown operation."))
        if action in {"verify", "restore"} and (not name or not NAME.match(name)):
            raise AppError(422, t("Choose a backup."))
        if name is not None and action in {"verify", "restore", "drill"}:
            known = {b.get("name") for b in self.overview()["backups"]}
            if name not in known:
                raise AppError(404, t("Backup not found."))
        running = self.read("operation.json")
        if running:
            raise AppError(409, t("Another operation is running; try again when it ends."))
        request_id = uuid.uuid4().hex
        self._write(
            self.settings.requests_dir / f"{request_id}.json",
            {
                "request_id": request_id,
                "action": action,
                "name": name,
                "requested_by": actor,
                "requested_at": _now(),
            },
        )
        return {"request_id": request_id, "action": action, "name": name, "state": "queued"}

    def request_diagnostics(self, actor: str) -> dict[str, Any]:
        """Asks the installer for a diagnostic bundle (it runs beside any operation)."""

        request_id = uuid.uuid4().hex
        self._write(
            self.settings.requests_dir / f"{request_id}.json",
            {
                "request_id": request_id,
                "action": "diagnostics",
                "requested_by": actor,
                "requested_at": _now(),
            },
        )
        return {"request_id": request_id, "action": "diagnostics", "name": None, "state": "queued"}

    def diagnostics_file(self, request_id: str) -> Path:
        """The zip the installer wrote for that request; ``AppError(404)`` when there is none
        (not ready, failed, or older than 24 h)."""

        outcome = self.outcome(request_id)
        path = self.status_dir / "diagnostics" / f"{request_id}.zip"
        if outcome.get("action") != "diagnostics" or outcome.get("state") != "done":
            raise AppError(404, t("The diagnostic bundle is not ready."))
        if not path.is_file():
            raise AppError(404, t("The diagnostic bundle is no longer kept (24 h)."))
        return path

    def outcome(self, request_id: str) -> dict[str, Any]:
        if not re.fullmatch(r"[0-9a-f]{32}", request_id):
            raise AppError(404, t("Request not found."))
        found = self.read(f"requests/{request_id}.json")
        if found is None:
            if (self.settings.requests_dir / f"{request_id}.json").exists():
                return {"request_id": request_id, "state": "queued"}
            raise AppError(404, t("Request not found."))
        return found

    @staticmethod
    def _write(path: Path, value: Any) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        partial = path.with_name(f".{path.name}.partial")
        partial.write_text(json.dumps(value, indent=2), encoding="utf-8")
        partial.chmod(0o640)
        partial.replace(path)
