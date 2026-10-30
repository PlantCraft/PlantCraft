"""One run of an algorithm on one asset.

A schedule chooses the algorithm and the assets it runs on (schedules and
algorithms are independent; the algorithm's own assets are only where it is tested), and every
run is an execution of the queue
(``engine.service``), like any other. A run reads its window, runs the diagram with the blocks'
memory of the previous run, keeps its summary and publishes its outputs: results on the asset,
what its schedule records (``assets.outputs``) and messages.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any

import pandas as pd
from plantcraft_sdk.utc import utc_iso

from linkcraft.assets.outputs import recorded_points
from linkcraft.assets.run import failed_summary, run_on_asset, timing_of, window_end
from linkcraft.assets.store import AssetRunStore
from linkcraft.blocks.convert import diagram_of, with_node_parameters
from linkcraft.engine.suite_compute import placement

LOGGER = logging.getLogger(__name__)
SUBJECT_KIND = "asset"


def asset_algorithms(profiles: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The algorithms that run on assets, with at least one asset."""

    found = []
    for profile in profiles:
        config = profile.get("method_config") or {}
        if config.get("subject_kind") == SUBJECT_KIND and config.get("assets"):
            found.append(profile)
    return found


class AssetService:
    """Runs every algorithm on assets when due, keeps the runs and publishes them."""

    def __init__(
        self,
        presets: Any,
        store: AssetRunStore,
        *,
        client: Callable[[], Any],
        models: Any = None,
        publish: Callable[[dict[str, Any], datetime, float], Any] | None = None,
    ):
        self.presets = presets
        self.store = store
        self.client = client
        self.models = models
        self.publish = publish

    # One run -------------------------------------------------------------------------------

    def run_one(
        self,
        profile: dict[str, Any],
        asset_id: str,
        *,
        now: datetime | None = None,
        publish: bool = True,
        interval_minutes: float | None = None,
        schedule: dict[str, Any] | None = None,
        node_parameters: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Run ``profile`` on ``asset_id`` over the window ending now; keep and publish it.

        ``interval_minutes``: how often its schedule runs it (its results expire after two).
        ``schedule``: what the schedule records (``assets.outputs.recording``); without one the
        run's recorded ports are kept in Link only.
        ``node_parameters``: the monitor's own parameter values, on top of the algorithm's.
        """

        algorithm_id = profile["profile_id"]
        config = with_node_parameters(profile.get("method_config"), node_parameters)
        timing = timing_of(config)
        moment = now or datetime.now(timezone.utc)
        end = window_end(pd.Timestamp(moment), timing.step_seconds)
        start = end - pd.Timedelta(seconds=timing.window_seconds)
        before = self.store.get(algorithm_id, asset_id) or {}
        try:
            # Its blocks' code runs on the compute workers its algorithm asks for.
            with placement(config.get("compute")):
                payload = run_on_asset(
                    diagram_of(config),
                    asset_id,
                    client=self.client(),
                    start=start,
                    end=end,
                    step=timing.step_seconds,
                    models=self.models,
                    states=before.get("states") or {},
                    algorithm_id=algorithm_id,
                )
        except Exception as exc:  # one asset that cannot run never stops the others
            LOGGER.warning("Algorithm %s on asset %s did not run: %s", algorithm_id, asset_id, exc)
            reason = str(exc) or type(exc).__name__
            self.store.save(
                algorithm_id,
                asset_id,
                asset_name=str(before.get("asset_name") or asset_id),
                summary=failed_summary(algorithm_id, reason),
                states=before.get("states") or {},
                written=before.get("written") or {},
                window_end=end.isoformat(),
                error=reason,
            )
            return self.store.get(algorithm_id, asset_id) or {}
        summary = payload["summary"]
        # The version that ran, kept with the run (Executions marks where a version started).
        summary["algorithm_version"] = int(profile.get("version") or 1)
        # What the run records goes to the Historian only as its schedule says (round 8, D6):
        # a run without a schedule (Run now on the algorithm's page) writes none of it.
        recorded = summary.get("recorded") or [] if schedule else []
        if publish and self.publish is not None:
            try:
                self.publish(
                    {
                        **payload,
                        "summary": {**summary, "recorded": recorded},
                        **(
                            {
                                "schedule": schedule,
                                "recorded_points": recorded_points(
                                    {**payload, "summary": summary}, schedule, utc_iso(moment)
                                ),
                            }
                            if schedule
                            else {}
                        ),
                    },
                    moment,
                    interval_minutes or timing.cycle_seconds / 60.0,
                )
            except Exception:
                LOGGER.exception("Publishing %s on asset %s failed", algorithm_id, asset_id)
        self.store.save(
            algorithm_id,
            asset_id,
            asset_name=str(payload["asset"]["name"]),
            summary=summary,
            states=payload.get("states") or {},
            written=before.get("written") or {},
            window_end=end.isoformat(),
        )
        return self.store.get(algorithm_id, asset_id) or {}


__all__ = ["SUBJECT_KIND", "AssetService", "asset_algorithms"]
