"""``python -m plantcraft.api.serve``: the image's server, in ``PLANTCRAFT_WORKERS`` processes.

The container's command (``Dockerfile``). Each worker builds the app from the environment
(``plantcraft.api.app:app``); uvicorn's supervisor starts a new worker when one dies.
How many: ``plantcraft.ops.workers.worker_count`` (docs/operations.md).
"""

from __future__ import annotations

import os

from plantcraft.ops.workers import worker_count


def main() -> None:
    import uvicorn

    uvicorn.run(
        "plantcraft.api.app:app",
        host=os.environ.get("PLANTCRAFT_HOST", "0.0.0.0"),
        port=int(os.environ.get("PLANTCRAFT_PORT", "8060")),
        workers=worker_count(),
        proxy_headers=True,
        # The suite's JSON logs (plantcraft_sdk.server.logs); requests are logged by the app.
        log_config=None,
        access_log=False,
        timeout_graceful_shutdown=20,
    )


if __name__ == "__main__":
    main()
