# PlantCraft spec

Category: the central app of an industrial software suite, what the platform layer of vendor
suites for process plants does: one sign-in and user directory, licences or access per app, the
connections to historians, the plant's asset model with its tags, and a launcher for the apps.
Tools studied (research only): the platform layers of commercial historian and APM suites. Sources
are public only (clean room, see AGENTS.md).

## Sources

| Source | Link | Read on |
|---|---|---|
| OPC UA Part 11, Historical Access | https://reference.opcfoundation.org/Core/Part11/ | 2026-10-19 |
| PI Web API reference (public) | https://docs.aveva.com/bundle/pi-web-api-reference/ | 2026-10-19 |
| RFC 8037, EdDSA for JOSE | https://www.rfc-editor.org/rfc/rfc8037 | 2026-10-19 |

## Features

| Area | Feature in the target tool | Source | Ours | Test or oracle |
|---|---|---|---|---|
| People | User directory with individual passwords | | done | `tests/test_access.py`, `tests/test_security.py` |
| People | Access levels and access per app | | done | `tests/test_access.py`, e2e `test_admin_creates_a_person_and_an_app_key` |
| People | Single sign-on into the apps (short-lived signed tokens) | RFC 8037 | done | `tests/contract/test_api_v1.py` |
| People | Directory integration (LDAP, Active Directory, OIDC single sign-on; SAML not yet) | RFC 4511, RFC 4513, OpenID Connect Core 1.0, RFC 7636 | partial | `tests/test_corporate_login.py`, `tests/test_corporate_login_live.py` |
| Apps | Launcher of the installed apps | | done | `tests/test_access.py`, e2e `test_launcher_lists_the_installed_apps` |
| Apps | Service credentials for background work (app keys) | | done | `tests/contract/test_api_v1.py` |
| Apps | Installing apps from the interface | | done; licence check and permission scopes open (G16) | `tests/test_apps_api.py`, `tests/test_app_installer.py`, `tests/test_installer_live.py`, e2e `test_admin_installs_an_app_from_a_signed_package` |
| Audit | Central audit log of changes by people and apps | | partial (app keys, API v1 writes) | `tests/contract/test_api_v1.py` |
| Data | OPC UA Historical Access source | OPC UA Part 11 | done | `tests/test_opcua_demo.py` (test server; the Simulator when installed) |
| Data | PI Web API source | PI Web API reference | partial (never run on a real server, G2) | `tests/test_pi_web_api.py` |
| Data | CSV source | | done | `tests/test_sources_and_map.py` |
| Data | Local history cache | | done | `tests/test_history_cache.py` |
| Assets | Asset hierarchy with kinds and tags by role | | done | `tests/test_platform_core.py` |
| Assets | Bulk import and export of the asset model (Excel, JSON) | | done | `tests/test_sources_and_map.py`, e2e `test_import_page_previews_and_applies_a_small_map` |
| Assets | Asset templates (attributes per kind) | | missing | |
| Platform | Works offline, on premises, isolated network | | done | `tests/test_offline.py`, `tests/test_isolation.py` |
