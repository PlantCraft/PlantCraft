"""The signal pages' API (from DataCraft): signals, overview, the Signal quality protocol's
settings and runs, and who may do what."""

from __future__ import annotations

from urllib.parse import quote

from tests.conftest import client_for, make_signal_runtime
from tests.signal_plant import EXPECTED


def test_health_and_me(sq_client):
    assert sq_client.get("/healthz").json()["status"] == "ok"
    assert sq_client.get("/link/healthz").json()["status"] == "ok"
    me = sq_client.get("/link/api/me").json()
    assert me["username"] == "engineer"
    assert me["can_edit"] is True


def test_no_token_is_401_and_a_browser_goes_to_sign_in(sq_runtime, sq_fake):
    sq_client = client_for(sq_runtime, sq_fake)
    sq_client.headers.pop("Authorization")
    assert sq_client.get("/link/api/signals").status_code == 401
    page = sq_client.get(
        "/link/api/signals", headers={"accept": "text/html"}, follow_redirects=False
    )
    assert page.status_code == 303
    assert page.headers["location"].startswith("/login?next=")


def test_people_without_linkcraft_are_refused(sq_runtime, sq_fake):
    with client_for(sq_runtime, sq_fake, "outsider") as sq_client:
        assert sq_client.get("/link/api/signals").status_code == 403


def test_round_judges_every_signal_as_expected(checked, sq_client):
    items = {
        item["id"]: item for item in sq_client.get("/link/api/signals?limit=500").json()["items"]
    }
    for signal_id, (status, limiting) in EXPECTED.items():
        assert (items[signal_id]["status"], items[signal_id]["limiting"]) == (status, limiting), (
            signal_id,
            items[signal_id]["message"],
        )


def test_signals_are_listed_worst_first_and_filtered(checked, sq_client):
    items = sq_client.get("/link/api/signals").json()["items"]
    order = {"bad": 0, "suspect": 1, "unknown": 2, "good": 3}
    ranks = [order[item["status"]] for item in items]
    assert ranks == sorted(ranks)
    bad = sq_client.get("/link/api/signals?status=bad").json()["items"]
    assert bad and {item["status"] for item in bad} == {"bad"}
    found = sq_client.get("/link/api/signals?q=bed temperature").json()["items"]
    assert {item["id"] for item in found} == {"historian:TI-108A.PV", "historian:TI-108B.PV"}
    frozen = sq_client.get("/link/api/signals?check=sq_frozen").json()["items"]
    assert [item["id"] for item in frozen] == ["historian:TI-101.PV"]


def test_roles_come_from_processcraft_assets(checked, sq_client):
    signal = sq_client.get("/link/api/signals/historian:FIC-110.SP").json()
    assert signal["roles"] == ["sp"]
    assert signal["assets"] == ["FIC-110"]
    checks = [item["check"] for item in signal["verdict"]["checks"]]
    assert "sq_frozen" not in checks


def test_overview_counts_and_worst(checked, sq_client):
    overview = sq_client.get("/link/api/overview").json()["signals"]
    assert overview["signals"] == 14
    assert sum(overview["counts"].values()) == 14
    assert overview["counts"]["bad"] >= 4
    assert overview["worst"][0]["status"] == "bad"
    assert {item["check"] for item in overview["by_check"]} >= {"sq_frozen", "sq_spikes"}
    assert overview["last_run"]["status"] == "ok"


def test_signal_page_data_and_history(checked, sq_client):
    page = sq_client.get("/link/api/signals/historian:PI-102.PV").json()
    spikes = next(item for item in page["verdict"]["checks"] if item["check"] == "sq_spikes")
    assert len(spikes["events"]) == 5
    data = sq_client.get("/link/api/signals/historian:PI-102.PV/data").json()
    assert 1000 < len(data["series"]["t"]) <= 4100
    assert max(value for value in data["series"]["v"] if value is not None) > 80
    history = sq_client.get("/link/api/signals/historian:PI-102.PV/history").json()
    assert history and history[-1]["status"] == "suspect"


def test_unknown_signal_is_404(checked, sq_client):
    assert sq_client.get("/link/api/signals/NOPE").status_code == 404
    assert sq_client.patch("/link/api/signals/NOPE", json={"enabled": False}).status_code == 404


def test_signal_ids_with_slashes(sq_runtime, sq_fake):
    # A tag is everything after the source id: slashes, spaces and colons included.
    signal_id = "historian:AREA 1/TI-1:A"
    sq_fake.signals.append({**sq_fake.signals[0], "id": signal_id})
    sq_fake.series_data[signal_id] = sq_fake.series_data["TI-100.PV"]
    sq_runtime.run_signal_quality("manual")
    with client_for(sq_runtime, sq_fake) as sq_client:
        assert (
            sq_client.get(f"/link/api/signals/{quote(signal_id, safe='')}").json()["status"]
            == "good"
        )
        assert sq_client.get(f"/link/api/signals/{signal_id}/history").status_code == 200


def test_editor_sets_a_reference_and_drift_shows(checked, sq_client, sq_fake):
    answer = sq_client.patch(
        "/link/api/signals/historian:TI-108A.PV", json={"reference": "historian:TI-108B.PV"}
    )
    assert answer.status_code == 200, answer.text
    verdict = sq_client.post("/link/api/signals/historian:TI-108A.PV/check").json()
    assert verdict["status"] == "bad"
    assert verdict["limiting"] == "sq_drift"
    assert verdict["saved"] is True
    assert sq_client.get("/link/api/signals/historian:TI-108A.PV").json()["status"] == "bad"
    assert any(item["action"] == "linkcraft.signal.update" for item in sq_fake.audit_log)


def test_signal_settings_are_validated(checked, sq_client):
    assert (
        sq_client.patch(
            "/link/api/signals/historian:TI-100.PV", json={"low": 50, "high": 10}
        ).status_code
        == 422
    )
    assert (
        sq_client.patch(
            "/link/api/signals/historian:TI-100.PV", json={"reference": "historian:TI-100.PV"}
        ).status_code
        == 422
    )
    assert (
        sq_client.patch(
            "/link/api/signals/historian:TI-100.PV", json={"reference": "NOPE"}
        ).status_code
        == 422
    )
    assert (
        sq_client.patch(
            "/link/api/signals/historian:TI-100.PV", json={"checks_off": ["nope"]}
        ).status_code
        == 422
    )
    bad_param = {"parameters": {"sq_frozen": {"min_minutes": -1}}}
    assert (
        sq_client.patch("/link/api/signals/historian:TI-100.PV", json=bad_param).status_code == 422
    )
    unknown = {"parameters": {"sq_frozen": {"nope": 1}}}
    assert sq_client.patch("/link/api/signals/historian:TI-100.PV", json=unknown).status_code == 422


def test_limits_override_and_clear(checked, sq_client):
    answer = sq_client.patch("/link/api/signals/historian:PI-105.PV", json={"high": 150}).json()
    assert answer["high"] == 150
    assert sq_client.post("/link/api/signals/historian:PI-105.PV/check").json()["status"] == "good"
    cleared = sq_client.patch(
        "/link/api/signals/historian:PI-105.PV", json={"clear": ["high"]}
    ).json()
    assert cleared["high"] == 100


def test_disabled_signals_are_skipped_by_the_round(checked, sq_client):
    sq_client.patch("/link/api/signals/historian:TI-100.PV", json={"enabled": False})
    summary = checked.run_signal_quality("manual")
    assert summary["signals"] == 13
    assert sq_client.get("/link/api/signals/historian:TI-100.PV").json()["status"] == "off"


def test_custom_window_check_is_not_saved(checked, sq_client):
    before = sq_client.get("/link/api/signals/historian:LI-104.PV").json()["verdict"]["checked_at"]
    answer = sq_client.post(
        "/link/api/signals/historian:LI-104.PV/check",
        json={"start": "2026-10-18T12:00:00Z", "end": "2026-10-19T08:00:00Z"},
    ).json()
    assert answer["saved"] is False
    assert answer["status"] == "good"
    assert (
        sq_client.get("/link/api/signals/historian:LI-104.PV").json()["verdict"]["checked_at"]
        == before
    )


def test_viewers_read_but_do_not_change(checked, sq_runtime, sq_fake):
    with client_for(sq_runtime, sq_fake, "operator") as sq_client:
        assert sq_client.get("/link/api/signals").status_code == 200
        assert (
            sq_client.patch(
                "/link/api/signals/historian:TI-100.PV", json={"enabled": False}
            ).status_code
            == 403
        )
        assert sq_client.post("/link/api/signals/historian:TI-100.PV/check").status_code == 403
        assert sq_client.post("/link/api/signal-quality/run").status_code == 403
        assert sq_client.post("/link/api/signals/sync").status_code == 403


def _check(protocol: dict, check_id: str) -> dict:
    return next(item for item in protocol["checks"] if item["id"] == check_id)


def test_checks_catalog_and_admin_defaults(sq_runtime, sq_fake):
    with client_for(sq_runtime, sq_fake, "admin") as sq_client:
        protocol = sq_client.get("/link/api/signal-quality").json()
        assert len(protocol["checks"]) == 8 and protocol["system"] is True
        frozen = _check(protocol, "sq_frozen")
        assert frozen["parameters"][0]["name"] == "min_minutes"
        assert frozen["action"]
        saved = sq_client.put(
            "/link/api/signal-quality",
            json={"window_hours": 12, "check_parameters": {"sq_frozen": {"min_minutes": 30}}},
        )
        assert saved.status_code == 200, saved.text
        assert _check(saved.json(), "sq_frozen")["parameters"][0]["value"] == 30
        assert saved.json()["settings"]["window_hours"] == 12
        assert (
            sq_client.put("/link/api/signal-quality", json={"interval_minutes": 0}).status_code
            == 422
        )
        assert (
            sq_client.put("/link/api/signal-quality", json={"enabled_checks": ["x"]}).status_code
            == 422
        )
        # The Methods page saves a check's defaults into the protocol.
        methods = {item["method_id"]: item for item in sq_client.get("/link/api/methods").json()}
        assert methods["sq_frozen"]["configured_defaults"] == {"min_minutes": 30}
        answer = sq_client.put(
            "/link/api/methods/sq_spikes/defaults",
            json={"parameters": {"n_sigma": 7}, "description": "Fewer spikes flagged"},
        )
        assert answer.status_code == 200, answer.text
        assert (
            sq_client.get("/link/api/signal-quality").json()["settings"]["check_parameters"][
                "sq_spikes"
            ]["n_sigma"]
            == 7
        )
        assert "def spikes" in sq_client.get("/link/api/methods/sq_spikes/source").json()["source"]
        timed = sq_client.put(
            "/link/api/signal-quality", json={"interval_minutes": 30, "enabled": False}
        ).json()
        assert timed["schedule"]["interval_minutes"] == 30 and not timed["schedule"]["enabled"]
    with client_for(sq_runtime, sq_fake, "engineer") as sq_client:
        assert (
            sq_client.put("/link/api/signal-quality", json={"window_hours": 2}).status_code == 403
        )


def test_status_and_sync(sq_runtime, sq_client):
    status = sq_client.get("/link/api/status").json()
    assert status["service_key"] is True
    assert status["signal_quality"]["running"] is False
    synced = sq_client.post("/link/api/signals/sync").json()
    assert synced["added"] == 14


def test_runs_need_an_app_key(tmp_path, sq_fake):
    sq_runtime = make_signal_runtime(tmp_path, sq_fake, app_key=False)
    try:
        with client_for(sq_runtime, sq_fake) as sq_client:
            assert sq_client.post("/link/api/signal-quality/run").status_code == 409
            assert sq_client.get("/link/api/status").json()["service_key"] is False
    finally:
        sq_runtime.shutdown()


def test_runs_are_listed_with_their_counts(checked, sq_client):
    (run,) = sq_client.get("/link/api/signal-quality/runs").json()
    assert run["status"] == "ok" and run["signals"] == 14
    assert sum(run["counts"].values()) == 14
    one = sq_client.get(f"/link/api/signal-quality/runs/{run['id']}").json()
    assert one["id"] == run["id"]
    # Its page lists the signals it judged, worst first, each named for people.
    judged = one["results"]
    assert len(judged) == 14 and all(row["name"] and row["signal_id"] for row in judged)
    order = {"bad": 0, "suspect": 1, "unknown": 2, "good": 3}
    assert [order[row["status"]] for row in judged] == sorted(
        order[row["status"]] for row in judged
    )
    assert sq_client.get("/link/api/signal-quality/runs/999").status_code == 404
    week = sq_client.get("/link/api/overview").json()["week"]["signals"]
    assert len(week) == 7 and week[-1]["signals"] == 14


def test_a_dead_source_marks_signals_unknown(sq_runtime, sq_fake):
    sq_fake.broken["historian:TI-100.PV"] = "historian offline"
    sq_runtime.run_signal_quality("manual")
    verdict = sq_runtime.quality_results.latest("historian:TI-100.PV")
    assert verdict["status"] == "unknown"
    assert "historian offline" in verdict["message"]
    assert sq_runtime.quality_results.latest("historian:TI-101.PV")["status"] == "suspect"


def test_signals_that_leave_processcraft_are_kept_as_missing(checked, sq_fake):
    sq_fake.signals = [item for item in sq_fake.signals if item["id"] != "historian:TI-100.PV"]
    checked.run_signal_quality("manual")
    assert checked.signal_store.get("historian:TI-100.PV")["missing"] is True


def test_round_in_worker_processes_gives_the_same_verdicts(tmp_path, sq_fake):
    sq_runtime = make_signal_runtime(tmp_path, sq_fake, processes=2)
    try:
        assert sq_runtime.run_signal_quality("manual")["status"] == "ok"
        for signal_id, (status, _limiting) in EXPECTED.items():
            assert sq_runtime.quality_results.latest(signal_id)["status"] == status
    finally:
        sq_runtime.shutdown()


def test_settings_merge_parameters_per_check_and_reset_to_all_checks(sq_runtime, sq_fake):
    url = "/link/api/signal-quality"
    with client_for(sq_runtime, sq_fake, "admin") as sq_client:
        sq_client.put(url, json={"check_parameters": {"sq_frozen": {"min_minutes": 30}}})
        sq_client.put(url, json={"check_parameters": {"sq_spikes": {"n_sigma": 8}}})
        saved = sq_client.put(url, json={"enabled_checks": ["sq_frozen"]}).json()["settings"]
        assert saved["check_parameters"] == {
            "sq_frozen": {"min_minutes": 30},
            "sq_spikes": {"n_sigma": 8},
        }
        reset = sq_client.put(
            url,
            json={"all_checks": True, "check_parameters": {"sq_frozen": {"min_minutes": None}}},
        ).json()["settings"]
        assert reset["enabled_checks"] is None
        assert reset["check_parameters"] == {"sq_spikes": {"n_sigma": 8}}


def test_check_filter_matches_any_flagged_check(checked, sq_client):
    sq_client.patch("/link/api/signals/historian:TI-100.PV", json={"high": 52})
    sq_client.post("/link/api/signals/historian:TI-100.PV/check")
    noisy = sq_client.get("/link/api/signals?check=sq_range").json()["items"]
    assert {"historian:PI-105.PV", "historian:TI-100.PV"} <= {item["id"] for item in noisy}


def test_signals_renamed_by_processcraft_keep_their_settings_and_history(
    sq_runtime, sq_fake, sq_client
):
    """Before D2 PlantCraft named signals by bare tag; DataCraft moves those rows once."""

    renamed = {item["id"]: item["id"].partition(":")[2] for item in sq_fake.signals}
    old_ids = list(sq_fake.signals)
    sq_fake.signals[:] = [{**item, "id": renamed[item["id"]]} for item in old_ids]
    sq_runtime.run_signal_quality("manual")
    sq_client.patch("/link/api/signals/TI-108A.PV", json={"reference": "TI-108B.PV", "high": 90})
    assert sq_runtime.quality_results.latest("TI-108A.PV") is not None
    sq_fake.signals[:] = old_ids  # PlantCraft now answers historian:<tag>
    synced = sq_client.post("/link/api/signals/sync").json()
    assert synced["renamed"] == len(old_ids) and synced["missing"] == 0
    signal = sq_client.get("/link/api/signals/historian:TI-108A.PV").json()
    assert signal["settings"] == {"reference": "historian:TI-108B.PV", "high": 90}
    assert signal["verdict"] is not None
    assert sq_client.get("/link/api/signals/historian:TI-108A.PV/history").json()
    assert sq_client.get("/link/api/signals/TI-108A.PV").status_code == 404
    assert sq_client.post("/link/api/signals/sync").json()["renamed"] == 0


def test_a_signal_can_be_marked_as_laboratory_samples(checked, sq_client):
    url = "/link/api/signals/historian:TI-100.PV"
    assert sq_client.get(url).json()["sampled"] is False
    marked = sq_client.patch(url, json={"sampling": "lab", "sample_interval_minutes": 240}).json()
    assert marked["sampled"] is True
    assert marked["settings"]["sample_interval_minutes"] == 240
    checks = [item["check"] for item in sq_client.post(f"{url}/check").json()["checks"]]
    assert "sq_frozen" not in checks and "sq_noise" not in checks
    assert sq_client.patch(url, json={"sampling": "weekly"}).status_code == 422
    assert sq_client.patch(url, json={"sample_interval_minutes": 0}).status_code == 422
    cleared = sq_client.patch(url, json={"clear": ["sampling", "sample_interval_minutes"]}).json()
    assert cleared["sampled"] is False and "sampling" not in cleared["settings"]
