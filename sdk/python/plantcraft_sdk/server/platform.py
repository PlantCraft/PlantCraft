"""An app server's connection to PlantCraft, written once: the HTTP client, the token verifier,
the service client (the app's key) and a client acting as each person.

An app's ``Runtime`` extends ``PlatformRuntime`` and connects in its ``__init__``::

    class Runtime(PlatformRuntime):
        def __init__(self, settings, *, verifier=None, service_client=None, http_client=None):
            self.settings = settings
            self.connect("alarmcraft", settings, verifier=verifier,
                         service_client=service_client, http_client=http_client)

Needs the ``server`` extra (``plantcraft_sdk.auth``).
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Mapping
from typing import Any

import httpx

from plantcraft_sdk.asset_scope import EVERYTHING, AssetScope, roots_of, scope_for
from plantcraft_sdk.auth import TokenVerifier, User
from plantcraft_sdk.client import PlantCraftClient, PlantCraftError
from plantcraft_sdk.contributes import contributions
from plantcraft_sdk.server import ops

LOGGER = logging.getLogger(__name__)


class PlatformRuntime:
    """``http``, ``verifier`` and ``service_client`` (``None`` without an app key), plus
    ``user_client``, ``asset_scope``, ``audit`` and ``close_platform``."""

    app_id: str
    settings: Any
    http: httpx.Client
    verifier: TokenVerifier
    service_client: Any
    # Changes made with a service token are the app's own work, not a person's: set False to
    # leave them out of the audit log.
    audit_service_users = True

    def connect(
        self,
        app_id: str,
        settings: Any,
        *,
        verifier: TokenVerifier | None = None,
        service_client: PlantCraftClient | None = None,
        http_client: httpx.Client | None = None,
        service: bool = True,
    ) -> None:
        """Open the connection; ``service=False`` for an app that has no service token."""

        self.app_id = app_id
        self._own_http = http_client is None
        self.http = http_client or httpx.Client(timeout=30.0)
        self.verifier = verifier or TokenVerifier(
            settings.processcraft_url, app_id, http_client=self.http, login_url=settings.login_url
        )
        if service and service_client is None and settings.app_key:
            service_client = PlantCraftClient(
                settings.processcraft_url, app=app_id, key=settings.app_key, http_client=self.http
            )
        self.service_client = service_client

    @property
    def has_service_key(self) -> bool:
        return self.service_client is not None

    def user_client(self, user: User) -> PlantCraftClient:
        """A client acting as ``user``; its audit records carry ``app: <app id>``."""

        return PlantCraftClient(
            self.settings.processcraft_url, user.token, app=self.app_id, http_client=self.http
        )

    def asset_scope(self, user: User) -> AssetScope:
        """The part of the plant ``user`` sees (token claim ``assets``), for what this app answers
        from its own store: ``scope.subject(...)``, ``scope.signal(...)``, ``scope.asset(...)``."""

        return self.claims_scope(user.claims, user.token)

    def claims_scope(self, claims: Mapping[str, Any], token: str) -> AssetScope:
        """``asset_scope`` from a token's verified claims and the token itself."""

        if roots_of(dict(claims)) is None:
            return EVERYTHING
        client = PlantCraftClient(
            self.settings.processcraft_url, token, app=self.app_id, http_client=self.http
        )
        return scope_for(dict(claims), token, client)

    def audit(self, user: User, action: str, subject: str, detail: Any = None) -> None:
        """Record a person's change in PlantCraft's audit log (never blocks the change)."""

        if user.is_service and not self.audit_service_users:
            return
        try:
            self.user_client(user).audit(f"{self.app_id}.{action}", subject, detail)
        except PlantCraftError as exc:
            LOGGER.warning("Audit of %s %s not recorded: %s", action, subject, exc)

    def send_contributions(
        self, manifest: Mapping[str, Any], *, wait: bool = False, tries: int = 6
    ) -> threading.Thread | None:
        """Tell PlantCraft what the app adds (``[contributes]``, ``[[publishes.series]]`` and
        ``[[publishes.events]]``, ``plantcraft_sdk.contributes``).

        Sent when the app starts (``server.web.mount``), in the background and retried while
        PlantCraft is not up yet; never stops the app. A PlantCraft older than SDK 0.30.0 gets
        the event catalog alone. ``wait`` sends it now (tests). An app with no app key carries
        both in ``GET /api/ops/metrics`` instead (``ops.report_contributions``).
        """

        try:
            body = contributions(manifest)
        except ValueError as exc:  # app.toml is checked in CI; a broken one only logs here
            LOGGER.warning("Contributions not sent: %s", exc)
            return None
        if self.app_id:
            body["app"] = self.app_id  # the app the runtime serves, as its token says
        events = [
            {key: value for key, value in spec.items() if value is not None}
            for spec in body.get("events", [])
        ]
        if self.service_client is None:
            # No app key: PlantCraft's monitor reads them with the metrics instead.
            ops.report_catalog(events)
            ops.report_contributions(body)
            return None
        client = self.service_client

        def send() -> None:
            for attempt in range(tries):
                try:
                    try:
                        client.put_contributions(body)
                    except PlantCraftError as exc:
                        if exc.status_code not in (404, 405):
                            raise
                        client.put_event_catalog(events)  # a PlantCraft before SDK 0.30.0
                    return
                except Exception as exc:  # PlantCraft starting
                    if attempt == tries - 1:
                        LOGGER.warning("Contributions not sent to PlantCraft: %s", exc)
                        return
                    time.sleep(min(60, 2**attempt))

        if wait:
            send()
            return None
        thread = threading.Thread(target=send, name="contributions", daemon=True)
        thread.start()
        return thread

    def send_event_catalog(
        self, manifest: Mapping[str, Any], *, wait: bool = False, tries: int = 6
    ) -> threading.Thread | None:
        """``send_contributions``, by its name before SDK 0.30.0 (the events go with the rest)."""

        return self.send_contributions(manifest, wait=wait, tries=tries)

    def close_platform(self) -> None:
        """Close the HTTP client if the runtime opened it."""

        if self._own_http:
            self.http.close()
