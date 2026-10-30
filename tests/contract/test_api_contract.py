"""API v1 as published (scale review E3, ``plantcraft.api.contract``).

The API v1 this commit serves is ``docs/api/v1/openapi.json`` (``make api-contract`` writes it,
so every change to API v1 shows in a review), and no release's API v1 is broken by it.
"""

from __future__ import annotations

import copy
import json

import pytest

from plantcraft.api import contract

RELEASES = sorted(contract.RELEASES.glob("*.json"))


@pytest.fixture(scope="module")
def served() -> dict:
    return contract.served()


def test_the_api_v1_served_is_the_one_in_the_repository(served):
    kept = json.loads(contract.CURRENT.read_text())
    assert contract.dumps(served) == contract.dumps(kept), (
        "API v1 changed: run `make api-contract` and commit docs/api/v1/openapi.json"
    )
    assert contract.REFERENCE.read_text() == contract.reference(kept), "run `make api-contract`"


def test_a_published_release_is_kept():
    assert "0.4.0" in [path.stem for path in RELEASES]


@pytest.mark.parametrize("release", RELEASES, ids=[path.stem for path in RELEASES])
def test_no_release_api_v1_is_broken(release, served):
    assert contract.breaking(json.loads(release.read_text()), served) == []


# What counts as breaking ---------------------------------------------------------------------


def _api() -> dict:
    return {
        "paths": {
            "/api/v1/things": {
                "get": {
                    "parameters": [
                        {"in": "query", "name": "kind", "schema": {"type": "string"}},
                    ],
                    "responses": {
                        "200": {
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "array",
                                        "items": {"$ref": "#/components/schemas/Thing"},
                                    }
                                }
                            }
                        }
                    },
                },
                "put": {
                    "requestBody": {
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "properties": {
                                        "name": {"type": "string"},
                                        "mode": {"type": "string", "enum": ["a", "b"]},
                                    },
                                    "required": ["name"],
                                }
                            }
                        }
                    },
                    "responses": {"200": {"description": "ok"}},
                },
            }
        },
        "components": {
            "schemas": {
                "Thing": {
                    "type": "object",
                    "properties": {"id": {"type": "string"}, "value": {"type": "number"}},
                }
            }
        },
    }


def test_adding_routes_fields_and_optional_parameters_breaks_nothing():
    old, new = _api(), _api()
    new["paths"]["/api/v1/other"] = {"get": {"responses": {}}}
    new["components"]["schemas"]["Thing"]["properties"]["unit"] = {"type": "string"}
    get = new["paths"]["/api/v1/things"]["get"]
    get["parameters"].append({"in": "query", "name": "limit", "schema": {"type": "integer"}})
    body = new["paths"]["/api/v1/things"]["put"]["requestBody"]["content"]["application/json"]
    body["schema"]["properties"]["mode"]["enum"].append("c")
    body["schema"]["properties"]["note"] = {"type": "string"}
    assert contract.breaking(old, new) == []


@pytest.mark.parametrize(
    ("change", "problem"),
    [
        (lambda api: api["paths"]["/api/v1/things"].pop("put"), "PUT /api/v1/things: removed"),
        (
            lambda api: api["paths"]["/api/v1/things"]["get"]["parameters"][0].update(
                required=True
            ),
            "GET /api/v1/things: query parameter kind is required now",
        ),
        (
            lambda api: api["components"]["schemas"]["Thing"]["properties"].pop("value"),
            "GET /api/v1/things answer[].value: is no longer answered",
        ),
        (
            lambda api: api["components"]["schemas"]["Thing"]["properties"]["id"].update(
                type="integer"
            ),
            "GET /api/v1/things answer[].id: is ['integer'], was ['string']",
        ),
        (
            lambda api: api["paths"]["/api/v1/things"]["put"]["requestBody"]["content"][
                "application/json"
            ]["schema"]["required"].append("mode"),
            "PUT /api/v1/things body.mode: is required now",
        ),
        (
            lambda api: api["paths"]["/api/v1/things"]["put"]["requestBody"]["content"][
                "application/json"
            ]["schema"]["properties"]["mode"].update(enum=["a"]),
            "PUT /api/v1/things body.mode: no longer accepts ['b']",
        ),
    ],
)
def test_what_breaks_a_client_is_named(change, problem):
    old = _api()
    new = copy.deepcopy(old)
    change(new)
    assert problem in contract.breaking(old, new)
