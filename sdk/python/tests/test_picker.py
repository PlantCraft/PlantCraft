from plantcraft_sdk.server.picker import rank_signals, signal_choices

FOUND = [
    {"id": "app-linkcraft:fic-101.out_health", "source": "app-linkcraft", "app": "linkcraft"},
    {"id": "fake:XFIC-101.PV", "source": "fake"},
    {"id": "fake:FIC-101.PV", "source": "fake", "unit": "m3/h"},
    {"id": "fake:FIC-101", "source": "fake"},
    {"id": "fake:FIC-101.MODE", "source": "fake", "kind": "text"},
    {"id": "app-histcraft:FIC-101", "source": "app-histcraft"},
]


def test_plant_signals_first_then_exact_prefix_and_other_matches():
    assert [item["id"] for item in rank_signals(FOUND, "FIC-101 ")] == [
        "fake:FIC-101",
        "fake:FIC-101.PV",
        "fake:FIC-101.MODE",
        "fake:XFIC-101.PV",
        "app-histcraft:FIC-101",
        "app-linkcraft:fic-101.out_health",
    ]


def test_choices_keep_the_picker_fields_numbers_only_and_the_limit():
    rows = signal_choices(FOUND, "fic-101", limit=2, numbers_only=True)
    assert [row["id"] for row in rows] == ["fake:FIC-101", "fake:FIC-101.PV"]
    assert (
        rows[0]["name"] == "fake:FIC-101" and rows[0]["unit"] == "" and rows[0]["description"] == ""
    )
    assert rows[1]["unit"] == "m3/h" and "app" not in rows[1]
    assert "fake:FIC-101.MODE" in {row["id"] for row in signal_choices(FOUND, "mode")}
    assert signal_choices([], "x") == []
