"""Source passwords: encrypted at rest, the key in its own file, never in the database."""

from __future__ import annotations

import stat

import pytest

from histcraft.vault import Vault


def test_passwords_round_trip_and_the_key_is_private(tmp_path):
    vault = Vault(tmp_path / "keys" / "secret.key")
    token = vault.encrypt("s3cret")
    assert "s3cret" not in token and vault.decrypt(token) == "s3cret"
    assert vault.encrypt("") == "" and vault.decrypt("") == ""
    assert stat.S_IMODE((tmp_path / "keys" / "secret.key").stat().st_mode) == 0o600
    # the same key file opens the same tokens later
    assert Vault(tmp_path / "keys" / "secret.key").decrypt(token) == "s3cret"


def test_a_changed_key_is_reported_not_guessed(tmp_path):
    token = Vault(tmp_path / "a.key").encrypt("s3cret")
    with pytest.raises(RuntimeError, match="secret key file changed"):
        Vault(tmp_path / "b.key").decrypt(token)
