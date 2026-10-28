"""Source passwords, encrypted at rest.

A password typed on the Sources page (or sent by PlantCraft when it hands its sources
over) is stored encrypted with Fernet (AES-128-CBC and HMAC-SHA256). The key lives in a
file of its own, never in the database: ``HISTCRAFT_SECRET_KEY_FILE``, else
``secret.key`` in the data folder, created with mode 0600 on first use. A database dump
alone therefore holds no usable password. Passwords are never logged or sent back to
pages.
"""

from __future__ import annotations

import os
import threading
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

from histcraft.i18n import t


class Vault:
    def __init__(self, key_file: str | Path):
        self.key_file = Path(key_file)
        self._fernet: Fernet | None = None
        self._lock = threading.Lock()

    def _key(self) -> Fernet:
        with self._lock:
            if self._fernet is None:
                if not self.key_file.exists():
                    self.key_file.parent.mkdir(parents=True, exist_ok=True)
                    fd = os.open(self.key_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                    with os.fdopen(fd, "wb") as handle:
                        handle.write(Fernet.generate_key())
                self._fernet = Fernet(self.key_file.read_bytes().strip())
            return self._fernet

    def encrypt(self, secret: str) -> str:
        return self._key().encrypt(secret.encode("utf-8")).decode("ascii") if secret else ""

    def decrypt(self, token: str) -> str:
        if not token:
            return ""
        try:
            return self._key().decrypt(token.encode("ascii")).decode("utf-8")
        except (InvalidToken, ValueError) as exc:
            raise RuntimeError(
                t("A stored password cannot be read: the secret key file changed.")
            ) from exc
