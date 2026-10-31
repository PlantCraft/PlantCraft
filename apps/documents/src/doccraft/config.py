"""Settings, all from the environment, each with a safe default.

Secrets (the app key) are never logged or stored by PlantCraft Documents.

| Variable | Default | Meaning |
|---|---|---|
| ``PLANTCRAFT_URL`` | ``http://127.0.0.1:8060`` | PlantCraft API v1, as this server reaches it |
| ``PLANTCRAFT_PUBLIC_URL`` | empty (same origin) | PlantCraft as the browser reaches it (sign-in page) |
| ``PLANTCRAFT_APP_KEY`` | empty | App key: what the app reads and publishes on its own |
| ``PLANTCRAFT_APP_KEY_FILE`` | empty | File holding the app key (a Docker secret) |
| ``DOCCRAFT_DATA_DIR`` | ``var`` | Folder of the SQLite database and of ``files/``, the original files |
| ``DOCCRAFT_ROOT_PATH`` | ``/doc`` | Path prefix of the interface and API |
| ``DOCCRAFT_EMBEDDING_DIR`` | ``/app/models/multilingual-e5-small`` | The bundled embedding model (``model.onnx``, ``tokenizer.json``); without it, a hashed stand-in |
| ``DOCCRAFT_MAX_FILE_MB`` | ``200`` | The largest file a person may send |
| ``DOCCRAFT_QUOTA_GB`` | ``20`` | The most the original files may take on disk |
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from plantcraft_sdk.server.settings import AppSettings, env_text

from doccraft import APP_ID

DEFAULT_EMBEDDING_DIR = "/app/models/multilingual-e5-small"


@dataclass
class Settings(AppSettings):
    APP_ID = APP_ID

    root_path: str = "/doc"
    embedding_dir: str = DEFAULT_EMBEDDING_DIR
    max_file_mb: int = 200
    quota_gb: float = 20.0
    # A tag found this many times links its asset with no one checking it (0: every link waits).
    asset_auto_mentions: int = 0

    @property
    def files_dir(self) -> Path:
        return self.data_dir / "files"

    @classmethod
    def from_environment(cls) -> Settings:
        return cls(
            **cls.common(APP_ID, "/doc"),
            embedding_dir=env_text("DOCCRAFT_EMBEDDING_DIR", DEFAULT_EMBEDDING_DIR),
            max_file_mb=int(env_text("DOCCRAFT_MAX_FILE_MB", "200") or 200),
            quota_gb=float(env_text("DOCCRAFT_QUOTA_GB", "20") or 20),
            asset_auto_mentions=int(env_text("DOCCRAFT_ASSET_AUTO_MENTIONS", "0") or 0),
        )
