"""PlantCraft SDK: what an app of the suite needs to talk to PlantCraft.

- ``plantcraft_sdk.jwt``: Ed25519 JSON Web Tokens and JWK helpers.
- ``plantcraft_sdk.auth``: verify the user's token on every request (FastAPI/Starlette).
- ``plantcraft_sdk.client``: typed client for every endpoint of API v1.
- ``plantcraft_sdk.assets``: the asset model (types, attributes, roles, relations, starter types).
- ``plantcraft_sdk.asset_scope``: the part of the plant a person sees (token claim ``assets``),
  for an app that answers people from its own store.
- ``plantcraft_sdk.refs``: ``parse_ref``/``format_ref`` for asset, signal, person and run references.
- ``plantcraft_sdk.links``: shapes and rules of results, events, runs and schedules.
- ``plantcraft_sdk.app_manifest``: the ``app.toml`` model; ``plantcraft-app check`` runs it.
- ``plantcraft_sdk.methods``: the ``@method`` decorator and the method contracts.
- ``plantcraft_sdk.blocks``: blocks with typed, described ports and algorithms as diagrams of
  them: the contract, the diagram checks and runs, and the one format of their descriptions.
- ``plantcraft_sdk.prompts``: prompts for an AI assistant (the "Copy as prompt" buttons), with
  no secret or endpoint in them.
- ``plantcraft_sdk.testing``: ``FakePlantCraft``, an in-process API v1 for app tests.
- ``plantcraft_sdk.server``: what every app server has in common (its SQLite store, ``app.toml``
  and help pages, access checks and the web application under its prefix).
- ``plantcraft_sdk.sbom``: the SPDX SBOM of an app's image (``plantcraft-app sbom``).
- For app tests (``docs/testing.md``): ``apptest`` (the suite's rules as checks), ``testplant``
  (the Simulator's loops served by a fake), ``e2e`` (browser journeys), ``pytest_budget`` (the
  test time budget, a pytest plugin).
"""

from plantcraft_sdk import settings_compat as _settings_compat

# Settings an older compose file still passes under the former names (renamed 2026-10-27).
_settings_compat.adopt()

__version__ = "0.89.0"
