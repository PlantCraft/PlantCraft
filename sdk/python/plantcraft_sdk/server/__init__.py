"""What every app server of the suite has in common, written once.

- ``plantcraft_sdk.server.store``: the app's own SQLite file and the ``Store`` base class.
- ``plantcraft_sdk.server.files``: ``app.toml`` and the help pages (``/api/meta``, ``/api/help``).
- ``plantcraft_sdk.server.access``: the request dependencies (runtime, signed-in person, editor)
  and ``guarded`` reads of PlantCraft.
- ``plantcraft_sdk.server.web``: the web application under the app's prefix: the endpoints every
  app serves (``docs/app-standard.md``, section 7), the built interface and sign-in redirects.
- ``plantcraft_sdk.server.logs``: JSON logs to the console and a rotating file, secrets redacted.
- ``plantcraft_sdk.server.ops``: request ids, one log line per request, ``/api/ops/metrics``.
- ``plantcraft_sdk.server.settings``: the settings every app reads (PlantCraft's URLs, the app
  key, the data folder, the prefix) and the ``env_*`` readers for its own.
- ``plantcraft_sdk.server.lease``: one process at a time on a file (an engine, a collector).
- ``plantcraft_sdk.server.memory``: freed memory given back to the system (``malloc_trim``),
  every minute in every server ``web.mount`` starts.
- ``plantcraft_sdk.server.platform``: the connection to PlantCraft (HTTP client, token
  verifier, service client, a client per person, the audit log), as a runtime base class.

An app keeps only what is its own: its stores, routers, runtime and settings. ``store``,
``files``, ``logs`` and ``settings`` need only the standard library; ``access``, ``web`` and
``platform`` need the ``server`` extra.
"""
