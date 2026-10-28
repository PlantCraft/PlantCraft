"""An app keeps a person to their part of the plant (asset scope, decision D2, 2026-10-27)."""

from __future__ import annotations

import pytest

from plantcraft_sdk.asset_scope import EVERYTHING, NOTHING, forget, limited, roots_of, scope_of
from plantcraft_sdk.testing import FakePlantCraft


@pytest.fixture(autouse=True)
def _fresh():
    forget()
    yield
    forget()


def _user(fake, username="operator", **claims):
    verifier = fake.verifier("linkcraft")
    return verifier.user(fake.token(username, **claims))


def test_no_claim_an_admin_and_an_app_see_the_whole_plant():
    fake = FakePlantCraft()
    assert roots_of({"sub": "operator"}) is None
    assert roots_of({"sub": "admin", "level": "admin", "assets": ["x"]}) is None
    assert roots_of({"sub": "app:linkcraft", "assets": ["x"]}) is None
    assert scope_of(_user(fake), fake.client("admin")) is EVERYTHING


def test_a_limited_person_sees_their_assets_signals_and_tags():
    fake = FakePlantCraft()
    user = _user(fake, assets=["fic-101"])
    scope = scope_of(user, fake.client("admin"))
    assert scope.roots == ("fic-101",)
    assert scope.asset("fic-101") and not scope.asset("lic-102") and not scope.asset("unit-100")
    assert scope.signal("fake:FIC-101.PV") and scope.signal("FIC-101.PV")
    assert not scope.signal("fake:LIC-102.PV")
    assert scope.subject("asset:fic-101") and not scope.subject("signal:fake:LIC-102.PV")
    assert scope.subject("") and scope.subject("run:linkcraft/1")
    assert scope.refs(["user:ana"]) and scope.refs(["asset:lic-102", "asset:fic-101"])
    assert not scope.refs(["asset:lic-102"])
    assert scope.all_signals(["fake:FIC-101.PV", "FIC-101.SP"])
    assert not scope.all_signals(["fake:FIC-101.PV", "fake:LIC-102.PV"])

    # Kept a minute: the second ask costs no request.
    before = fake.requests
    assert scope_of(user, fake.client("admin")) is scope
    assert fake.requests == before


def test_when_plantcraft_cannot_say_nothing_of_the_plant_is_shown():
    fake = FakePlantCraft()
    user = _user(fake, assets=["fic-101"])

    class Down:
        def with_token(self, _token):
            raise ConnectionError("PlantCraft is down")

    assert scope_of(user, Down()) is NOTHING


def test_a_limited_person_sets_up_nothing_an_app_reads_with_its_own_token():
    fake = FakePlantCraft()
    assert limited(_user(fake, assets=["fic-101"]))
    assert not limited(_user(fake))
    assert not limited(_user(fake, "admin", level="admin", assets=["fic-101"]))
