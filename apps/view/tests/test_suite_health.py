"""The dashboard "Suite health" over the Historian's source "System", kept by View."""

from __future__ import annotations

from dashcraft.dashboards.suite_health import BUILTIN, build


def _system(fake, *names):
    for name in names:
        fake.signals.append(
            {"id": f"system:{name}", "name": name, "source": "system", "unit": "",
             "description": "The suite's own health", "low": None, "high": None,
             "source_kind": "system"}
        )  # fmt: skip


SIGNALS = (
    "processcraft.up", "processcraft.latency_ms", "processcraft.errors", "processcraft.cpu_pct",
    "linkcraft.up", "linkcraft.latency_ms", "proxy.up", "histcraft-db.up",
    "host.disk_free_pct", "host.disk_free_gb", "backup.age_h", "backup.ok",
)  # fmt: skip


def test_nothing_without_the_system_source(runtime, client):
    assert build({"fake:FIC-101.PV"}) is None
    assert runtime.ensure_suite_health(force=True) is None
    assert client.get("/dash/api/dashboards").json() == []


def test_the_suite_keeps_one_read_only_dashboard(runtime, client, fake):
    _system(fake, *SIGNALS)
    made = runtime.ensure_suite_health(force=True)
    assert made["name"] == "Suite health" and made["builtin"] == BUILTIN
    cards = {card["card_id"]: card for card in made["cards"]}
    assert cards["disk"]["kind"] == "gauge"
    up = cards["table-up"]["items"]
    # PlantCraft first, the apps, then the containers that serve no page
    assert [item["label"] for item in up] == ["processcraft", "linkcraft", "histcraft-db", "proxy"]
    assert [i["signal_id"] for i in cards["trend-latency-ms"]["items"]] == [
        "system:processcraft.latency_ms",
        "system:linkcraft.latency_ms",
    ]
    assert "trend-mem-mb" not in cards  # no memory signal yet
    listed = client.get("/dash/api/dashboards").json()
    assert [item["name"] for item in listed] == ["Suite health"]
    dashboard_id = made["dashboard_id"]
    # nobody edits or deletes it; a copy is an ordinary dashboard
    body = {"name": "Mine", "cards": made["cards"]}
    assert client.put(f"/dash/api/dashboards/{dashboard_id}", json=body).status_code == 409
    assert client.delete(f"/dash/api/dashboards/{dashboard_id}").status_code == 409
    copy = client.post(f"/dash/api/dashboards/{dashboard_id}/copy").json()
    assert copy["builtin"] == "" and copy["name"] == "Suite health (copy)"
    assert client.put(f"/dash/api/dashboards/{copy['dashboard_id']}", json=body).status_code == 200
    # its cards read the signals like any other
    data = client.get(f"/dash/api/dashboards/{dashboard_id}/cards/table-up")
    assert data.status_code == 200
    # a new service: the cards are redrawn, the dashboard stays the same one
    _system(fake, "alarmcraft.up", "alarmcraft.mem_mb")
    again = runtime.ensure_suite_health(force=True)
    assert again["dashboard_id"] == dashboard_id
    labels = [i["label"] for c in again["cards"] if c["card_id"] == "table-up" for i in c["items"]]
    assert "alarmcraft" in labels
    assert any(card["card_id"] == "trend-mem-mb" for card in again["cards"])
    assert len([d for d in runtime.dashboards.list() if d["builtin"]]) == 1


def test_it_lives_in_the_platform_folder(runtime, client, fake):
    """Owner, 2026-10-25: the suite's own dashboards in a folder of their own, "Platform"."""

    _system(fake, *SIGNALS)
    made = runtime.ensure_suite_health(force=True)
    folder = runtime.folders.by_name("Platform")
    assert folder is not None and made["folder_id"] == folder["folder_id"]
    # renamed by an administrator: it stays there, no second folder
    runtime.folders.update(folder["folder_id"], {**folder, "name": "Suite"}, "admin")
    _system(fake, "alarmcraft.up")
    again = runtime.ensure_suite_health(force=True)
    assert again["folder_id"] == folder["folder_id"] and runtime.folders.by_name("Platform") is None


def test_processcraft_down_keeps_the_dashboard(runtime, fake):
    _system(fake, *SIGNALS)
    made = runtime.ensure_suite_health(force=True)

    class Down:
        def signals(self, *_args, **_kwargs):
            raise RuntimeError("down")

    runtime.service_client = Down()
    assert runtime.ensure_suite_health(force=True)["dashboard_id"] == made["dashboard_id"]


def test_it_looks_at_most_every_ten_minutes(runtime, fake):
    _system(fake, *SIGNALS)
    assert runtime.ensure_suite_health(force=True) is not None
    assert runtime.ensure_suite_health() is None  # too soon: not looked again
