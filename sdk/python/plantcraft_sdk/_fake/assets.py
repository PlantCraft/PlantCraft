"""The fake PlantCraft's routes for assets, asset types, scopes and exploring."""

from typing import Any

from plantcraft_sdk import explore as _explore
from plantcraft_sdk._fake.wire import _Abort, _Request
from plantcraft_sdk.assets import (
    MAX_RESULT_ASSETS,
    RESULT_TYPE,
    parse_result_assets,
    resolve_types,
)
from plantcraft_sdk.contract import (
    ContractError,
)


class _AssetRoutes:
    """The fake's routes for assets and scopes (mixed into the fake)."""

    def _scope(self, claims: dict[str, Any]) -> tuple[set[str], set[str]] | None:
        """The assets and signals a token's ``assets`` claim lets it read, as PlantCraft
        applies it (docs/asset-scope.md); None for the whole plant."""

        from plantcraft_sdk.asset_scope import roots_of

        roots = roots_of(claims)
        if roots is None:
            return None
        children: dict[str | None, list[str]] = {}
        for item in self.assets:
            children.setdefault(item.get("parent_id"), []).append(item["id"])
        assets: set[str] = set()
        pending = [root for root in roots if any(item["id"] == root for item in self.assets)]
        while pending:
            current = pending.pop()
            if current not in assets:
                assets.add(current)
                pending.extend(children.get(current, []))
        signals = {
            str(signal)
            for item in self.assets
            if item["id"] in assets
            for signal in (item.get("signals") or {}).values()
        }
        for item in self.signals:
            subject = str(item.get("subject") or "")
            if subject.startswith("asset:") and subject[6:] in assets:
                signals.add(item["id"])
            if subject.startswith("signal:") and subject[7:] in signals:
                signals.add(item["id"])
        return assets, signals

    def _signal_in_scope(self, request: "_Request", signal_id: str) -> None:
        scope = self._scope(self._caller(request))
        if scope is None:
            return
        found = self._known(signal_id)
        if found is None or found["id"] not in scope[1]:
            raise _Abort(404, "Signal not found.")

    def _route_assets(self, request: "_Request") -> list[dict[str, Any]]:
        scope = self._scope(self._reader(request))
        kind, parent_id = request.query.get("kind"), request.query.get("parent_id")
        wanted = request.query.get("type")
        results = request.query.get("results") == "true" or RESULT_TYPE in (kind, wanted)
        return [
            item
            for item in self.assets
            if (results or not isinstance(item, dict) or item.get("kind") != RESULT_TYPE)
            and (kind is None or item["kind"] == kind)
            and (wanted is None or wanted in item["type_path"])
            and (parent_id is None or item["parent_id"] == parent_id)
            and (scope is None or item["id"] in scope[0])
        ]

    def _app_caller(self, request: "_Request", detail: str) -> str:
        subject = str(self._caller(request).get("sub") or "")
        if not subject.startswith("app:"):
            raise _Abort(403, detail)
        return subject[4:]

    def _route_put_result_assets(self, request: "_Request") -> dict[str, int]:
        app = self._app_caller(request, "Only an app's service token writes result assets.")
        origin = f"app:{app}"
        try:
            items = parse_result_assets(app, request.json())
        except ValueError as error:
            raise _Abort(422, str(error)) from error
        by_id = {item["id"]: item for item in self.assets}
        for index, item in enumerate(items):
            parent = by_id.get(item["parent_id"])
            if parent is None:
                raise _Abort(422, f"[{index}] parent_id {item['parent_id']} is not an asset.")
            if parent["kind"] == RESULT_TYPE:
                raise _Abort(
                    422,
                    f"[{index}] a result hangs under the asset it is about, not under another result.",
                )
            mine = by_id.get(item["id"])
            if mine is not None and mine["attributes"].get("origin") != origin:
                raise _Abort(422, f"[{index}] {item['id']} is an asset the app does not own.")
        listed = {item["id"] for item in items}
        ended = 0
        for asset in self.assets:
            stale = asset["kind"] == RESULT_TYPE and asset["id"] not in listed
            if stale and asset["attributes"].get("origin") == origin:
                ended += asset["attributes"].get("state") != "ended"
                asset["attributes"]["state"] = "ended"
        for item in items:
            row = {
                "id": item["id"],
                "name": item["name"],
                "kind": RESULT_TYPE,
                "type_path": [RESULT_TYPE],
                "parent_id": item["parent_id"],
                "attributes": {
                    "app": app,
                    "made_by": item["made_by"],
                    "state": "active",
                    "description": item["description"],
                    "kind_label": "Result",
                    "origin": origin,
                },
                "signals": {point["role"]: point["signal"] for point in item["points"]},
                "relations": [],
            }
            if item["id"] in by_id:
                by_id[item["id"]].clear()
                by_id[item["id"]].update(row)
            else:
                self.assets.append(row)
        return {"saved": len(items), "ended": ended}

    def _route_remove_result_assets(self, request: "_Request") -> dict[str, int]:
        app = self._app_caller(request, "Only an app's service token removes result assets.")
        body = request.json() or {}
        ids = body.get("ids") if isinstance(body, dict) else None
        if not isinstance(ids, list) or not 1 <= len(ids) <= MAX_RESULT_ASSETS:
            raise ContractError(f"Send 1 to {MAX_RESULT_ASSETS} ids to remove.")
        wanted = {str(item) for item in ids}
        kept = [
            item
            for item in self.assets
            if not (
                item["id"] in wanted
                and item["kind"] == RESULT_TYPE
                and item["attributes"].get("origin") == f"app:{app}"
            )
        ]
        removed = len(self.assets) - len(kept)
        self.assets[:] = kept
        return {"removed": removed}

    def _route_asset_types(self, request: "_Request") -> list[dict[str, Any]]:
        self._reader(request)
        return resolve_types(self.asset_types)

    def _route_explore(self, request: "_Request") -> dict[str, Any]:
        """The Explorer (``plantcraft_sdk.explore``), over the fake's assets, signals and the
        events written to it."""

        self._reader(request)
        assets = [
            item
            for item in self.assets
            if isinstance(item, dict) and item.get("kind") != RESULT_TYPE
        ]
        signals = [self._signal_payload(item) for item in self.signals]
        query, asset_id = request.query.get("q") or "", request.query.get("asset")
        if query.strip():
            return {"hits": _explore.search(assets, signals, query)}
        if not asset_id:
            return _explore.top(assets)
        found = next((item for item in assets if item["id"] == asset_id), None)
        if found is None:
            raise _Abort(404, "Asset not found.")
        ref = f"asset:{asset_id}"
        kinds: dict[str, dict[str, Any]] = {}
        last: dict[tuple[str, str], tuple[str, str]] = {}
        for event in self.links.events:
            if ref not in event["refs"]:
                continue
            item = kinds.setdefault(
                event["kind"],
                {"kind": event["kind"], "app": event["app"], "count": 0, "last_at": "",
                 "open": 0, "severity": "", "title": event["kind"]},
            )  # fmt: skip
            item.update(count=item["count"] + 1, last_at=event["at"], severity=event["severity"])
            if event.get("key") and event.get("phase") in ("start", "end"):
                last[(event["app"], event["key"])] = (event["phase"], event["kind"])
        for phase, kind in last.values():
            kinds[kind]["open"] += int(phase == "start")
        return _explore.asset_contents(found, assets, signals, events=list(kinds.values()))

    def _route_asset(self, request: "_Request", id: str) -> dict[str, Any]:
        scope = self._scope(self._reader(request))
        found = next((item for item in self.assets if item["id"] == id), None)
        if found is None or (scope is not None and id not in scope[0]):
            raise _Abort(404, "Asset not found.")
        return found
