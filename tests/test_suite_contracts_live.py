"""What the end-to-end test of the live suite found where PlantCraft speaks to an app (2026-10-22)."""

from plantcraft import demo_seed


def test_the_demo_keeps_three_monitors():
    """Control loop performance, Signal quality and the model beside the plant (owner,
    2026-10-27): the seed makes no algorithm or monitor of its own in Analytics."""

    assert not hasattr(demo_seed, "VALVE_PROTOCOL")
    assert not hasattr(demo_seed, "valve_algorithm")


def test_dials_are_two_rows_high():
    assert demo_seed._kpi("k", "FIC-1003", "FIC-1003")["height"] >= 2


def test_a_historian_source_keeps_its_connection_state():
    """Historian's data API answers the collector's view as ``status`` (live: every source
    showed "No news" on the Overview while the Historian said Connected)."""

    from plantcraft.platform.datalayer.histcraft import source_item

    connected = {"status": "connected", "detail": "", "since": 1}
    assert source_item({"id": "plant", "kind": "opcua", "status": connected})["state"] == connected
    assert source_item({"id": "plant", "kind": "opcua", "state": connected})["state"] == connected
    assert source_item({"id": "lab", "kind": "csv", "status": None})["state"] is None
    answered = source_item({"id": "pi", "kind": "pi", "status": {"ok": False, "message": "down"}})
    assert answered["state"]["status"] == "disconnected"
    assert answered["state"]["detail"] == "down"
