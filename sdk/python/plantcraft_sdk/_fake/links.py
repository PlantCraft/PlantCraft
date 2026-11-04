"""The fake PlantCraft's results, events, runs, schedules, knowledge, contributions and desk routes."""

from dataclasses import dataclass, field
from datetime import timezone
from functools import cached_property
from typing import Any
from urllib.parse import unquote

from pydantic import ValidationError

from plantcraft_sdk import contributes as _contributes
from plantcraft_sdk import desk as _desk
from plantcraft_sdk import events as _events
from plantcraft_sdk import links as _links
from plantcraft_sdk import llm as _llm
from plantcraft_sdk._fake.wire import FakeResponse, _Abort, _Request
from plantcraft_sdk.contract import (
    ContractError,
)

# Rows a read answers when it gives no ``limit`` (as PlantCraft).
_SHORT = 100


@dataclass
class FakeLinks:
    """What apps published to the fake: inspect it in tests (``fake.links.results``...)."""

    # (app, subject, kind) -> stored result
    results: dict[tuple[str, str, str], dict[str, Any]] = field(default_factory=dict)
    history: list[dict[str, Any]] = field(default_factory=list)
    events: list[dict[str, Any]] = field(default_factory=list)
    # (app, run id) -> run
    runs: dict[tuple[str, str], dict[str, Any]] = field(default_factory=dict)
    # app -> its schedules, in order
    schedules: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    # (app, ref) -> text
    knowledge: dict[tuple[str, str], dict[str, Any]] = field(default_factory=dict)
    # app -> its declared events (PUT /api/v1/events/catalog, or ``fake.declare_events``).
    # An app with a catalog here may post only the events it declares: the fake answers 422
    # where PlantCraft only logs a warning, so a typo fails in the app's own tests.
    catalogs: dict[str, _events.EventCatalog] = field(default_factory=dict)
    # app -> what it adds to PlantCraft (PUT /api/v1/contributions), as PlantCraft stores it.
    contributions: dict[str, dict[str, Any]] = field(default_factory=dict)
    # What POST /api/v1/llm/{use} received: {"app", "use", "system", "messages"}.
    llm_calls: list[dict[str, Any]] = field(default_factory=list)
    # The model's answer: a text, or a function of the call; None answers as if the use had
    # no model (409), as PlantCraft does until an administrator sets one up.
    llm_answer: Any = "A model's answer."
    # (app, feed) -> its items (PUT /api/v1/calendar/<feed>)
    calendar: dict[tuple[str, str], list[dict[str, Any]]] = field(default_factory=dict)
    # (app, key) -> to-do (POST /api/v1/todos); tick one in a test with ``fake.tick_todo``.
    todos: dict[tuple[str, str], dict[str, Any]] = field(default_factory=dict)
    # app -> {key: value} an administrator chose in Setup › Apps; set them in a test.
    settings: dict[str, dict[str, Any]] = field(default_factory=dict)


class _LinksRoutes:
    """The fake's routes for results, events, runs and schedules (mixed into the fake)."""

    @cached_property
    def links(self) -> FakeLinks:
        return FakeLinks()

    def _links_now(self) -> str:
        return self.now.astimezone(timezone.utc).isoformat(timespec="seconds")  # type: ignore[attr-defined]

    def _links_app(self, claims: dict[str, Any], given: Any) -> str:
        subject = str(claims.get("sub") or "")
        if subject.startswith("app:"):
            own = subject[4:]
            if given and str(given).strip().lower() != own:
                raise _links.LinkError(403, "A service token writes only for its own app.")
            return own
        if not given:
            raise _links.LinkError(422, "app is required with a person's token.")
        app = str(given).strip().lower()
        if (claims.get("apps") or {}).get(app) != "editor":
            raise _links.LinkError(403, f"You need editor access to {app} to write for it.")
        return app

    def _links_prefix(self, app: str) -> str | None:
        installed = self.apps_installed  # type: ignore[attr-defined]
        return next((item["url"] for item in installed if item["id"] == app), None)

    def _links_subject(self, subject: str) -> str:
        """The subject as stored (a bare signal tag by its signal's id); 404 when unknown."""

        kind, item = _links.split_subject(subject)
        if kind == "asset":
            if not any(asset["id"] == item for asset in self.assets):  # type: ignore[attr-defined]
                raise _links.LinkError(404, f"Asset not found. ({subject})")
            return subject
        try:
            found = self._known(item)  # type: ignore[attr-defined]
        except _Abort as abort:
            raise _links.LinkError(404, f"{abort.detail} ({subject})") from abort
        if found is None:
            raise _links.LinkError(404, f"Signal not found. ({subject})")
        return f"signal:{found['id']}"

    def _links_named(self, ref: str | None) -> str | None:
        """A ``signal:`` reference by its signal's id when it names a known one."""

        if ref is None or not ref.startswith("signal:"):
            return ref
        try:
            found = self._known(ref[len("signal:") :])  # type: ignore[attr-defined]
        except _Abort:
            return ref
        return f"signal:{found['id']}" if found else ref

    @staticmethod
    def _links_limit(query: dict[str, str], default: int = _SHORT) -> int:
        raw = query.get("limit")
        try:
            limit = default if raw in (None, "") else int(raw)
        except ValueError as exc:
            raise ContractError("limit is a whole number from 1 to 500.") from exc
        if not 1 <= limit <= _links.MAX_READ:
            raise ContractError("limit is a whole number from 1 to 500.")
        return limit

    @staticmethod
    def _links_kind(app: str | None, kind: str | None) -> tuple[str | None, str | None]:
        if kind and "." in kind:
            owner, _, name = kind.partition(".")
            return (app, "\0") if app and app != owner else (owner, name)
        return app, kind

    def _route_put_results(self, request: "_Request") -> dict[str, Any]:
        claims = self._caller(request)  # type: ignore[attr-defined]
        items = _links.parse_body(_links.ResultIn, request.json(), many=True)
        now = self._links_now()
        errors = []
        saved = 0
        for index, item in enumerate(items):
            try:
                app = self._links_app(claims, item.app)
                subject = self._links_subject(item.subject)
                kind = _links.result_kind(item.kind, app)
            except _links.LinkError as error:
                errors.append(_links.item_error(index, item.subject, error.status, error.detail))
                continue
            row = {
                **item.model_dump(exclude={"app", "kind"}),
                "subject": subject,
                "app": app,
                "kind": kind,
                "at": item.at or now,
                "updated_at": now,
            }
            key = (app, subject, kind)
            previous = self.links.results.get(key)
            if previous is None or previous["status"] != row["status"]:
                change = {name: row[name] for name in _CHANGE_FIELDS}
                self.links.history.append({**change, "recorded_at": now})
            self.links.results[key] = row
            saved += 1
        cutoff = _links.cutoff_text(self.now)  # type: ignore[attr-defined]
        self.links.history = [row for row in self.links.history if row["recorded_at"] >= cutoff]
        return {"saved": saved, "errors": errors}

    def _route_results(self, request: "_Request") -> list[dict[str, Any]]:
        self._reader(request)  # type: ignore[attr-defined]
        wanted = _links.subjects_param(request.lists.get("subject"))
        if len(wanted) > _links.MAX_SUBJECTS:
            raise ContractError(f"Ask for at most {_links.MAX_SUBJECTS} subjects at once.")
        wanted = [str(self._links_named(item)) for item in wanted]
        app, kind = self._links_kind(request.query.get("app"), request.query.get("kind"))
        now = self._links_now()
        rows = sorted(
            self.links.results.values(), key=lambda r: (r["subject"], r["app"], r["kind"])
        )
        return [
            _links.stale_view(row, now)
            for row in rows
            if (not wanted or row["subject"] in wanted)
            and (app is None or row["app"] == app)
            and (kind is None or row["kind"] == kind)
        ]

    def _route_result_history(self, request: "_Request") -> list[dict[str, Any]]:
        self._reader(request)  # type: ignore[attr-defined]
        subject = request.query.get("subject")
        if not subject:
            raise ContractError("subject is required.")
        subject = self._links_named(subject)
        app, kind = self._links_kind(request.query.get("app"), request.query.get("kind"))
        after = _links.utc_text(request.query.get("after"), "after")
        rows = [
            {name: row[name] for name in _CHANGE_FIELDS}
            for row in sorted(self.links.history, key=lambda r: r["at"])
            if row["subject"] == subject
            and (app is None or row["app"] == app)
            and (kind is None or row["kind"] == kind)
            and (after is None or row["at"] > after)
        ]
        return rows[: self._links_limit(request.query)]

    def _route_post_event(self, request: "_Request") -> "FakeResponse":
        claims = self._caller(request)  # type: ignore[attr-defined]
        items, many = _links.parse_events(request.json())
        ids: list[int | None] = []
        errors = []
        repeated = 0
        for index, item in enumerate(items):
            try:
                app = self._links_app(claims, item.app)
                kind = _links.event_kind(item.kind, app)
                if _links.own_app_subject(item.subject, app):
                    subject = item.subject
                else:
                    subject = self._links_subject(item.subject)
                catalog = self.links.catalogs.get(app)
                spec = catalog.spec(kind) if catalog is not None else None
                if catalog is not None and spec is None:
                    raise _links.LinkError(
                        422, f"{kind} is not in the event catalog of {app} (app.toml)."
                    )
                fields = _events.event_fields(item, spec)
            except _links.LinkError as error:
                if not many:
                    raise _Abort(error.status, error.detail) from error
                errors.append(_links.item_error(index, item.subject, error.status, error.detail))
                ids.append(None)
                continue
            refs = [subject]
            for ref in item.refs:
                ref = str(self._links_named(ref))
                if ref not in refs:
                    refs.append(ref)
            same = self._links_repeated(app, fields)
            if same is not None:
                echo = {**(same or {}), "repeated": True}
                if not many:
                    return FakeResponse(
                        201, echo if same else {"id": None, **fields, "repeated": True}
                    )
                ids.append(same["id"] if same else None)
                repeated += 1
                continue
            event = {
                "id": len(self.links.events) + 1,
                "at": self._links_now(),
                "app": app,
                "kind": kind,
                "subject": subject,
                "actor": str(claims.get("sub") or ""),
                "summary": item.summary,
                "refs": refs,
                "payload": item.payload,
                **fields,
            }
            self.links.events.append(event)
            if not many:
                return FakeResponse(201, event)
            ids.append(event["id"])
        saved = sum(1 for item in ids if item is not None) - repeated
        return FakeResponse(
            201, {"saved": saved, "ids": ids, "errors": errors, "repeated": repeated}
        )

    def _links_repeated(self, app: str, fields: dict[str, Any]) -> dict[str, Any] | None:
        """PlantCraft keeps only changes: the event already saying this start (same severity)
        or end, ``{}`` for an end of a condition never opened, None for a change."""

        key, phase = fields.get("key"), fields.get("phase")
        if not key or phase not in ("start", "end"):
            return None
        before = next(
            (
                event
                for event in reversed(self.links.events)
                if event["app"] == app
                and event.get("key") == key
                and event.get("phase") in ("start", "end")
            ),
            None,
        )
        if phase == "end":
            if before is None:
                return {}
            return before if before["phase"] == "end" else None
        if before and before["phase"] == "start" and before["severity"] == fields["severity"]:
            return before
        return None

    def _route_events(self, request: "_Request") -> list[dict[str, Any]]:
        self._reader(request)  # type: ignore[attr-defined]
        query = request.query
        ref, kind, key = self._links_named(query.get("ref")), query.get("kind"), query.get("key")
        try:
            after = None if query.get("after") in (None, "") else int(query["after"])
        except ValueError as exc:
            raise ContractError("after is the id of an event.") from exc
        limit = self._links_limit(query)
        found = [
            event
            for event in self.links.events
            if (ref is None or ref in event["refs"])
            and (kind is None or event["kind"] == kind)
            and (key is None or event.get("key") == key)
        ]
        if after is not None:
            return [event for event in found if event["id"] > after][:limit]
        return found[-limit:]

    def declare_events(self, manifest: Any, app: str | None = None) -> _events.EventCatalog:
        """Hold the app to the events its manifest declares (``app.toml`` dict or AppManifest)."""

        catalog = _events.EventCatalog.from_manifest(manifest, app=app)
        self.links.catalogs[catalog.app] = catalog
        return catalog

    def _route_put_event_catalog(self, request: "_Request") -> dict[str, Any]:
        claims = self._caller(request)  # type: ignore[attr-defined]
        try:
            body = _events.CatalogIn.model_validate(request.json())
        except ValidationError as exc:
            raise ContractError(str(exc.errors(include_url=False)[0].get("msg"))) from exc
        try:
            app = self._links_app(claims, body.app)
        except _links.LinkError as error:
            raise _Abort(error.status, error.detail) from error
        self.links.catalogs[app] = _events.EventCatalog(app, body.events)
        return {"app": app, "events": len(body.events)}

    def _route_put_contributions(self, request: "_Request") -> dict[str, Any]:
        claims = self._caller(request)  # type: ignore[attr-defined]
        try:
            body = _contributes.ContributionsIn.model_validate(request.json() or {})
        except ValidationError as exc:
            raise ContractError(str(exc.errors(include_url=False)[0].get("msg"))) from exc
        try:
            app = self._links_app(claims, body.app)
        except _links.LinkError as error:
            raise _Abort(error.status, error.detail) from error
        self.links.contributions[app] = {
            "app": app,
            **body.model_dump(mode="json", exclude_none=True, exclude={"app", "events"}),
            "updated_at": self._links_now(),
        }
        self.links.catalogs[app] = _events.EventCatalog(app, body.events)
        return {"app": app, "events": len(body.events), "unknown": body.unknown}

    def _route_contributions(self, request: "_Request") -> dict[str, Any]:
        self._reader(request)  # type: ignore[attr-defined]
        return {
            "features": list(_contributes.FEATURES),
            "apps": [
                {**item, "name": app} for app, item in sorted(self.links.contributions.items())
            ],
        }

    def _route_llm(self, request: "_Request", use: str) -> dict[str, Any]:
        claims = self._caller(request)  # type: ignore[attr-defined]
        subject = str(claims.get("sub") or "")
        if not subject.startswith("app:"):
            raise _Abort(403, "Only an app writes with its own uses of a model.")
        app = subject[4:]
        try:
            name = _llm.split_use(app, unquote(use))
        except ValueError as exc:
            raise _Abort(403, str(exc)) from exc
        declared = (self.links.contributions.get(app) or {}).get("contributes", {}).get("llm", [])
        if name not in {item["id"] for item in declared}:
            raise _Abort(404, f"{app} declares no use {name!r} in [[contributes.llm]].")
        body = request.json() or {}
        try:
            sent = _llm.messages_body(body.get("messages") or [], system=body.get("system") or "")
        except ValueError as exc:
            raise ContractError(str(exc)) from exc
        call = {"app": app, "use": name, **sent}
        self.links.llm_calls.append(call)
        answer = (
            self.links.llm_answer(call)
            if callable(self.links.llm_answer)
            else self.links.llm_answer
        )
        if answer is None:
            raise _Abort(409, "This use has no language model now.")
        return {"use": f"{app}:{name}", "model": "fake", "text": str(answer)}

    def _route_contribution_settings(self, request: "_Request") -> dict[str, Any]:
        claims = self._caller(request)  # type: ignore[attr-defined]
        app = str(claims.get("sub", ""))
        if not app.startswith("app:"):
            raise _Abort(403, "Only an app reads its settings.")
        app = app[4:]
        row = self.links.contributions.get(app) or {}
        specs = (row.get("contributes") or {}).get("settings", [])
        chosen = self.links.settings.get(app, {})
        for key, value in chosen.items():
            spec = next((item for item in specs if item["key"] == key), None)
            if spec is None:
                raise ContractError(f"{app} declares no setting {key}.")
            _contributes.setting_value(spec, value)
        return {
            "app": app,
            "values": {spec["key"]: chosen.get(spec["key"], spec.get("default")) for spec in specs},
        }

    # Desk: calendar feeds and to-dos (plantcraft_sdk.desk) ------------------------------

    def _declared(self, app: str, table: str) -> set[str]:
        row = self.links.contributions.get(app) or {}
        return {item["id"] for item in (row.get("contributes") or {}).get(table, [])}

    def _desk_app(self, request: "_Request") -> str:
        claims = self._caller(request)  # type: ignore[attr-defined]
        try:
            return self._links_app(claims, request.query.get("app"))
        except _links.LinkError as error:
            raise _Abort(error.status, error.detail) from error

    def _route_put_calendar(self, request: "_Request", feed: str) -> dict[str, Any]:
        app = self._desk_app(request)
        feed = unquote(feed)
        if feed not in self._declared(app, "calendar"):
            raise _Abort(
                422, f"{app} has no calendar feed {feed}: declare it in [[contributes.calendar]]."
            )
        body = request.json()
        try:
            given = _desk.FeedIn.model_validate({"items": body if isinstance(body, list) else None})
        except ValidationError as exc:
            raise ContractError(str(exc.errors(include_url=False)[0].get("msg"))) from exc
        self.links.calendar[(app, feed)] = [item.model_dump(mode="json") for item in given.items]
        return {"app": app, "feed": feed, "items": len(given.items)}

    def _route_put_todo(self, request: "_Request") -> dict[str, Any]:
        app = self._desk_app(request)
        try:
            given = _desk.TodoIn.model_validate(request.json() or {})
        except ValidationError as exc:
            raise ContractError(str(exc.errors(include_url=False)[0].get("msg"))) from exc
        if given.kind not in self._declared(app, "todo"):
            raise _Abort(
                422, f"{app} has no to-do kind {given.kind}: declare it in [[contributes.todo]]."
            )
        known = self.links.todos.get((app, given.key))
        if known is None:
            open_ = sum(
                1
                for (owner, _), item in self.links.todos.items()
                if owner == app and item["for"] == given.for_ and not item["done"]
            )
            if open_ >= _desk.MAX_OPEN_TODOS:
                raise _Abort(429, f"{given.for_} already has {_desk.MAX_OPEN_TODOS} open to-dos.")
        now = self._links_now()
        item = {
            "app": app,
            "detail": "",
            **given.as_body(),
            "done": bool(known and known["done"]),
            "done_at": known["done_at"] if known else None,
            "done_by": known["done_by"] if known else None,
            "created_at": known["created_at"] if known else now,
            "updated_at": now,
        }
        self.links.todos[(app, given.key)] = item
        return item

    def tick_todo(self, app: str, key: str, by: str, done: bool = True) -> dict[str, Any]:
        """A person ticks (or unticks) the app's to-do in Desk."""

        item = self.links.todos[(app, key)]
        item.update(
            done=done, done_at=self._links_now() if done else None, done_by=by if done else None
        )
        return item

    def _route_todos(self, request: "_Request") -> list[dict[str, Any]]:
        app = self._desk_app(request)
        state = request.query.get("state", "all")
        items = [item for (owner, _), item in self.links.todos.items() if owner == app]
        if state != "all":
            items = [item for item in items if item["done"] == (state == "done")]
        return sorted(items, key=lambda item: item["updated_at"], reverse=True)

    def _route_close_todos(self, request: "_Request") -> dict[str, Any]:
        app = self._desk_app(request)
        keys = (request.json() or {}).get("keys")
        if not isinstance(keys, list) or not 1 <= len(keys) <= 500:
            raise ContractError("keys is a list of 1 to 500 keys.")
        closed = sum(1 for key in dict.fromkeys(keys) if self.links.todos.pop((app, key), None))
        return {"app": app, "closed": closed}

    def _route_event_catalog(self, request: "_Request") -> list[dict[str, Any]]:
        self._reader(request)  # type: ignore[attr-defined]
        return [
            {
                "app": app,
                "name": app,
                "updated_at": None,
                "events": [{"kind": f"{app}.{spec['name']}", **spec} for spec in catalog.to_json()],
                "undeclared": [],
            }
            for app, catalog in sorted(self.links.catalogs.items())
        ]

    def _route_put_runs(self, request: "_Request") -> dict[str, Any]:
        claims = self._caller(request)  # type: ignore[attr-defined]
        items = _links.parse_body(_links.RunIn, request.json(), many=True)
        now = self._links_now()
        errors, saved = [], 0
        for index, item in enumerate(items):
            try:
                app = self._links_app(claims, item.app)
                url = _links.check_url(item.url, self._links_prefix(app))
                cancel = _links.check_url(item.cancel, self._links_prefix(app))
                if cancel and not cancel.startswith("/"):
                    raise _links.LinkError(422, "cancel is a path under the app's prefix.")
                subjects = list(
                    dict.fromkeys(self._links_subject(subject) for subject in item.subjects)
                )
            except _links.LinkError as error:
                errors.append(_links.item_error(index, item.id, error.status, error.detail))
                continue
            row = item.model_dump(exclude={"app"})
            self.links.runs[(app, item.id)] = {
                **row,
                "app": app,
                "url": url,
                "cancel": cancel,
                "subjects": subjects,
                "updated_at": now,
            }
            saved += 1
        cutoff = _links.cutoff_text(self.now)  # type: ignore[attr-defined]
        self.links.runs = {
            key: run for key, run in self.links.runs.items() if run["updated_at"] >= cutoff
        }
        return {"saved": saved, "errors": errors}

    def _route_runs(self, request: "_Request") -> list[dict[str, Any]]:
        self._reader(request)  # type: ignore[attr-defined]
        query = request.query
        status, app, by = query.get("status"), query.get("app"), query.get("by")
        subject = self._links_named(query.get("subject"))
        if status is not None and status not in _links.RUN_STATUSES:
            raise ContractError(f"Invalid status: use one of {', '.join(_links.RUN_STATUSES)}.")
        rows = sorted(
            self.links.runs.values(),
            key=lambda run: run["started_at"] or run["updated_at"],
            reverse=True,
        )
        return [
            run
            for run in rows
            if (app is None or run["app"] == app)
            and (status is None or run["status"] == status)
            and (subject is None or subject in run["subjects"])
            and (by is None or run.get("by") == by)
        ][: self._links_limit(query)]

    def _route_put_knowledge(self, request: "_Request") -> dict[str, Any]:
        claims = self._caller(request)  # type: ignore[attr-defined]
        items = _links.parse_body(_links.KnowledgeIn, request.json(), many=True)
        now = self._links_now()
        errors, saved = [], 0
        for index, item in enumerate(items):
            try:
                app = self._links_app(claims, item.app)
                url = _links.check_url(item.url, self._links_prefix(app))
            except _links.LinkError as error:
                errors.append(_links.item_error(index, item.ref, error.status, error.detail))
                continue
            row = item.model_dump(exclude={"app"})
            self.links.knowledge[(app, item.ref)] = {
                **row,
                "app": app,
                "url": url,
                "updated_at": now,
            }
            saved += 1
        return {"saved": saved, "errors": errors}

    def _route_delete_knowledge(self, request: "_Request") -> dict[str, Any]:
        claims = self._caller(request)  # type: ignore[attr-defined]
        try:
            app = self._links_app(claims, request.query.get("app"))
        except _links.LinkError as error:
            raise ContractError(error.detail) from error
        refs = set((request.json() or {}).get("refs") or [])
        before = len(self.links.knowledge)
        self.links.knowledge = {
            key: item
            for key, item in self.links.knowledge.items()
            if not (key[0] == app and key[1] in refs)
        }
        return {"deleted": before - len(self.links.knowledge)}

    def _route_knowledge(self, request: "_Request") -> list[dict[str, Any]]:
        self._reader(request)  # type: ignore[attr-defined]
        query = request.query
        ref, app, words = query.get("ref"), query.get("app"), (query.get("q") or "").lower()
        rows = sorted(self.links.knowledge.values(), key=lambda item: item["updated_at"])
        return [
            item
            for item in reversed(rows)
            if (ref is None or item["ref"] == ref or ref in item["subjects"])
            and (app is None or item["app"] == app)
            and all(word in f"{item['title']} {item['text']}".lower() for word in words.split())
        ][: self._links_limit(query)]

    def _route_put_schedules(self, request: "_Request") -> dict[str, Any]:
        claims = self._caller(request)  # type: ignore[attr-defined]
        try:
            app = self._links_app(claims, request.query.get("app"))
        except _links.LinkError as error:
            raise _Abort(error.status, error.detail) from error
        items = _links.parse_body(_links.ScheduleIn, request.json(), many=True)
        ids = [item.id for item in items]
        if len(set(ids)) != len(ids):
            raise ContractError("Each schedule id appears once.")
        now, prefix = self._links_now(), self._links_prefix(app)
        kept, errors = [], []
        for index, item in enumerate(items):
            try:
                url = _links.check_url(item.url, prefix)
                for subject in item.subjects:
                    _links.split_subject(subject)
            except _links.LinkError as error:
                errors.append(_links.item_error(index, item.id, error.status, error.detail))
                continue
            subjects = list(dict.fromkeys(item.subjects))
            kept.append(
                {
                    **item.model_dump(),
                    "app": app,
                    "url": url,
                    "subjects": subjects,
                    "updated_at": now,
                }
            )
        self.links.schedules[app] = kept
        return {"saved": len(kept), "errors": errors}

    def _route_schedules(self, request: "_Request") -> list[dict[str, Any]]:
        self._reader(request)  # type: ignore[attr-defined]
        app = request.query.get("app")
        return [
            schedule
            for owner in sorted(self.links.schedules)
            if app is None or owner == app
            for schedule in self.links.schedules[owner]
        ]


_CHANGE_FIELDS = ("app", "subject", "kind", "status", "score", "usable", "value", "summary", "at")
