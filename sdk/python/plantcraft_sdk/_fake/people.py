"""The fake PlantCraft's routes for keys, sessions, the caller, apps, people, groups and notifications."""

import copy
import hmac
from typing import Any

import pandas as pd

from plantcraft_sdk import contributes as _contributes
from plantcraft_sdk import links as _links
from plantcraft_sdk._fake.defaults import SESSION_COOKIE
from plantcraft_sdk._fake.wire import FakeResponse, _Abort, _Request
from plantcraft_sdk.contract import (
    SERVICE_TOKEN_SECONDS,
    TOKEN_COOKIE,
    USER_TOKEN_SECONDS,
    ContractError,
    iso,
    subject_digest,
)
from plantcraft_sdk.people import check_notification, check_resolution


class _PeopleRoutes:
    """The fake's routes for keys, sessions, people and notifications (mixed into the fake)."""

    def _route_keys(self, request: "_Request") -> dict[str, Any]:
        return self.jwks

    def _route_revoked(self, request: "_Request") -> dict[str, Any]:
        return {
            "users": [
                {"sub_sha256": subject_digest(name), "not_before": stamp}
                for name, stamp in self.revoked_users.items()
            ],
            "keys": [{"key_id": key_id, "revoked_at": 0} for key_id in sorted(self.revoked_keys)],
            "sessions": [{"sid_sha256": sid, "ended_at": 0} for sid in sorted(self.ended_sessions)],
        }

    def _route_renew(self, request: "_Request") -> FakeResponse:
        username = request.cookies.get(SESSION_COOKIE)
        if not username or username not in self.users:
            raise _Abort(401, "Session expired. Sign in again.")
        grant = self._grant(self.token(username))
        return FakeResponse(
            200, grant, cookies=[(TOKEN_COOKIE, grant["token"], USER_TOKEN_SECONDS)]
        )

    def _route_service_token(self, request: "_Request") -> dict[str, str]:
        payload = request.json()
        if not isinstance(payload, dict):
            raise _Abort(422, "Send a JSON object with app and key.")
        app_id, key = str(payload.get("app") or ""), str(payload.get("key") or "")
        expected = self.app_keys.get(app_id)
        if not expected or not hmac.compare_digest(expected, key):
            raise _Abort(401, "Unknown app or key.")
        token = self.token(
            f"app:{app_id}",
            ttl=SERVICE_TOKEN_SECONDS,
            name=app_id,
            level="viewer",
            apps={app_id: "viewer"},
        )
        return self._grant(token)

    def _route_me(self, request: "_Request") -> dict[str, Any]:
        claims = self._caller(request)
        return {
            "username": claims.get("sub"),
            "name": claims.get("name"),
            "level": claims.get("level"),
            "apps": claims.get("apps") or {},
            "notebooks_url": None,  # Notebooks: off in the fake
        }

    def _route_installation(self, request: "_Request") -> dict[str, Any]:
        self._caller(request)
        return {"time_zone": self.time_zone, "features": list(_contributes.FEATURES)}

    def _route_apps(self, request: "_Request") -> list[dict[str, Any]]:
        allowed = self._caller(request).get("apps") or {}
        return [
            {
                "id": item["id"],
                "name": item["name"],
                "url": item["url"],
                "access": allowed[item["id"]],
                "version": item.get("version"),
            }
            for item in self.apps_installed
            if item["id"] in allowed
        ]

    def _route_audit(self, request: "_Request") -> dict[str, int]:
        claims = self._caller(request)
        payload = request.json()
        if not isinstance(payload, dict):
            raise _Abort(422, "Send a JSON object with action, subject and detail.")
        action = payload.get("action")
        if not isinstance(action, str) or not action.strip():
            raise _Abort(422, "action is required.")
        subject = str(claims.get("sub") or "")
        # A service token always records its own app, as PlantCraft does.
        app_id = subject[4:] if subject.startswith("app:") else payload.get("app")
        entry = {
            "id": len(self.audit_log) + 1,
            "username": subject,
            "app": app_id,
            "action": action,
            "subject": str(payload.get("subject") or ""),
            "detail": payload.get("detail"),
            "at": iso(pd.Timestamp.now(tz="UTC")),
        }
        self.audit_log.append(entry)
        return {"id": entry["id"]}

    def _route_people(self, request: "_Request") -> list[dict[str, Any]]:
        self._reader(request)
        return [
            {
                "username": username,
                "name": user.get("name") or username,
                "role": user.get("role") or "",
                "job_title": user.get("job_title") or "",
                "unit": user.get("unit") or "",
                "groups": [group["id"] for group in self.groups if username in group["members"]],
            }
            for username, user in self.users.items()
        ]

    def _route_groups(self, request: "_Request") -> list[dict[str, Any]]:
        self._reader(request)
        return copy.deepcopy(self.groups)

    def _route_notification_settings(self, request: "_Request") -> dict[str, bool]:
        self._reader(request)
        return {"email": bool(self.email_ready)}

    def _route_notify(self, request: "_Request") -> dict[str, Any]:
        claims = self._caller(request)
        subject = str(claims.get("sub") or "")
        if not subject.startswith("app:"):
            raise _Abort(403, "Only an app's service token sends notifications.")
        try:
            body = check_notification(request.json())
        except ContractError as exc:
            raise _Abort(422, str(exc)) from exc
        delivered: list[str] = []
        unknown: list[str] = []
        for ref in body["recipients"]:
            kind, _, name = ref.partition(":")
            group = next((item for item in self.groups if item["id"] == name), None)
            if kind == "user" and name in self.users:
                delivered.append(name)
            elif kind == "group" and group is not None:
                delivered.extend(group["members"])
            else:
                unknown.append(ref)
        delivered = list(dict.fromkeys(delivered))
        self.notifications.append({**body, "app": subject[4:], "delivered": delivered})
        return {"delivered": delivered, "email_queued": 0, "unknown": unknown}

    def _route_resolve_notification(self, request: "_Request") -> dict[str, Any]:
        claims = self._caller(request)
        subject = str(claims.get("sub") or "")
        if not subject.startswith("app:"):
            raise _Abort(403, "Only an app's service token resolves notifications.")
        try:
            body = check_resolution(request.json())
        except ContractError as exc:
            raise _Abort(422, str(exc)) from exc
        self.resolved_notifications[(subject[4:], body["key"])] = body["note"]
        return {**body, "resolved_at": _links.now_text()}
