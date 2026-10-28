# Security policy

## Reporting a vulnerability

Please report vulnerabilities privately. Do not open a public issue.

Use GitHub's private vulnerability reporting: go to the repository's
**Security** tab and choose **Report a vulnerability**
(https://github.com/PlantCraft/PlantCraft/security/advisories/new).

Include what you found, how to reproduce it, the affected version or commit
and the impact you expect. We will acknowledge the report, keep you informed
while we work on a fix and credit you in the advisory unless you prefer
otherwise.

## Supported versions

PlantCraft View is in alpha. Security fixes go to the `main` branch and the latest
release.

## Scope and design notes

- **No plant connections.** PlantCraft View never talks to a DCS, PLC, historian or
  OPC UA server. Its only outbound connection is to the PlantCraft named by
  `PLANTCRAFT_URL`, through `plantcraft_sdk.client` (`tests/test_suite_rules.py`
  fails on any other network module). It writes nothing to the plant, and
  never writes assets or signals: those live only in PlantCraft.
- **Sign-in is PlantCraft's.** Every API route and page needs a PlantCraft
  token whose `apps` claim grants `dashcraft`, except public links (below);
  tokens are verified offline with PlantCraft's published keys. Viewers read
  dashboards; editors (PlantCraft role editor or admin, with PlantCraft View
  editor access) create, change, copy, delete and share them.
- **Two readers.** A saved dashboard reads plant data with PlantCraft View's
  service token: it is a published report, so viewers and public links see
  what an editor chose to publish. The asset and signal pickers and the card
  preview read with the editor's own token, so an editor cannot browse what
  PlantCraft does not show them. The asset picked on a dashboard must be of
  the dashboard's kind, so a viewer cannot point a published card at another
  part of the plant.
- **Public links.** An editor can create a read-only link to one dashboard.
  The token (32 random bytes) is shown once and stored only as its SHA-256; a
  link reads that dashboard's cards and nothing else, and stops at once when
  revoked or when its dashboard is deleted. Link pages are served with
  `Cache-Control: no-store` and `Referrer-Policy: no-referrer`.
  `DASHCRAFT_PUBLIC_LINKS=false` turns links off (existing links answer 404),
  and links need an app key. Creating and revoking a link is audited.
- **App key.** The service token comes from an app key an admin creates in
  PlantCraft. Give it as a file (`PLANTCRAFT_APP_KEY_FILE`, a Docker secret
  in the suite's compose file) or `PLANTCRAFT_APP_KEY`; it is never logged or
  stored by PlantCraft View. Revoking it in PlantCraft stops published dashboards
  and public links at once (they answer 503 with the reason).
- **Audit.** Every change a person makes (dashboards created, changed, copied,
  deleted; links created and revoked) is recorded in PlantCraft's audit log
  (`POST /api/v1/audit`, action `dashcraft.*`). A failed audit write is
  logged and does not block the change (see `docs/gaps.md`).
- **Limits.** At most 30 cards per dashboard, 12 items per card, windows up to
  366 days and about 600 points per trend line, so a dashboard cannot ask
  PlantCraft for unbounded data. `tests/test_suite_rules.py` sends
  malformed input to every API operation.
- **Container.** The image runs as uid 10006 with a read-only root filesystem;
  state lives only in `/data`, scratch in the `/tmp` tmpfs. It holds no build
  tools, not even pip. Dependencies are installed offline from a hash-checked
  wheelhouse (`deploy/requirements.lock`); `plantcraft-sdk` comes from
  `vendor/` with its SHA-256 in `vendor/README.md`.
- **No code execution.** Cards are data (kind, items, limits); there are no
  formulas, scripts or HTML in a dashboard.
