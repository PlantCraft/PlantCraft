"""Every method has a help page with its parameters' real defaults (catalog/help.py)."""

from __future__ import annotations

import pytest

from linkcraft.catalog.help import (
    HELP_DIR,
    SECTIONS,
    documented_parameters,
    format_default,
    method_help,
    parse,
)
from linkcraft.catalog.registry import METHOD_SPECS


@pytest.mark.parametrize("method_id", sorted(METHOD_SPECS))
def test_every_method_has_a_complete_help_page(method_id):
    path = HELP_DIR / f"{method_id}.md"
    assert path.is_file(), f"no help page for {method_id}: add {path.name}"
    page = parse(path.read_text(encoding="utf-8"))
    assert page["title"]
    assert [section["title"] for section in page["sections"]] == [name for _, name in SECTIONS]
    for section in page["sections"]:
        assert section["blocks"], f"{method_id}: empty section {section['title']}"

    fields = METHOD_SPECS[method_id].parameter_schema.model_fields
    documented = documented_parameters(page)
    assert set(documented) == set(fields), method_id
    for key, field in fields.items():
        real = format_default(field.get_default(call_default_factory=True))
        assert documented[key]["default"] == real, f"{method_id}.{key}: page says "
        f"{documented[key]['default']}, the method {real}"
        assert len(documented[key]["meaning"]) > 20


@pytest.mark.parametrize("method_id", sorted(METHOD_SPECS))
def test_the_reference_section_names_each_reference_of_the_method(method_id):
    page = method_help(method_id)
    text = " ".join(
        str(block.get("text") or " ".join(block.get("items", [])))
        for section in page["sections"]
        if section["id"] == "reference"
        for block in section["blocks"]
    )
    for reference in METHOD_SPECS[method_id].metadata.references:
        surname = reference.authors[0].split()[-1].replace("Hagglund", "Hägglund")
        assert surname in text and str(reference.year) in text, (method_id, surname)


def test_help_is_served_with_the_configured_defaults(client):
    index = client.get("/link/api/help/methods").json()
    assert {item["method_id"] for item in index} == set(METHOD_SPECS)
    assert all(item["summary"] for item in index)
    page = client.get("/link/api/help/methods/oscillation_autocorrelation").json()
    assert [section["id"] for section in page["sections"]] == [
        "detects",
        "reference",
        "reading",
        "limits",
    ]
    lag = next(item for item in page["parameters"] if item["key"] == "min_lag_samples")
    assert lag["default"] == "3" and lag["configured"] is None and "lag" in lag["meaning"]
    assert client.get("/link/api/help/methods/nope").status_code == 404


def test_the_loop_type_table_is_served(client):
    rows = client.get("/link/api/help/loop-types").json()
    assert [row["loop_type"] for row in rows] == [
        "flow",
        "level",
        "pressure",
        "temperature",
        "composition",
        None,
    ]
    flow = rows[0]
    assert flow["profile_name"] == "Flow loop" and flow["parameters"][0]["values"]
