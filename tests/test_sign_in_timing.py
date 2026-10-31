"""A wrong username costs a password check too, so timing does not reveal who has an account
(security test 2026-10-31, D3: 15 ms for an unknown name against 200 ms for a known one)."""

from __future__ import annotations

from plantcraft.auth import users as users_module
from plantcraft.auth.users import UserStore
from plantcraft.db import Database


def test_unknown_and_known_names_both_check_a_hash(tmp_path, monkeypatch):
    store = UserStore(Database(tmp_path / "w.db"))
    store.upsert_user("ana.real", "Ana", "")
    store.set_password("ana.real", "a-long-password")
    checked: list[str] = []
    real = users_module.check_password

    def counting(password: str, encoded: str | None) -> bool:
        checked.append(encoded or "")
        return real(password, encoded)

    monkeypatch.setattr(users_module, "check_password", counting)
    assert store.verify_password("nobody-here", "a-long-password") is False
    assert store.verify_password("ana.real", "wrong-password") is False
    assert store.verify_password("ana.real", "a-long-password") is True
    assert len(checked) == 3
