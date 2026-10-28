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

PlantCraft Historian is in alpha. Security fixes go to the `main` branch and the latest
release.

## Scope and design notes

- **No route to the plant by default.** PlantCraft Historian runs on the internal apps
  network and collects through PlantCraft (`POST /api/v1/values/current`, its
  service token from the app key): only PlantCraft reaches plant systems, as
  the suite's app standard requires. Direct OPC UA sources are refused while
  `HISTCRAFT_OPCUA=off`, the image default.
- **Read-only on the plant.** Where the owner allows a direct collector
  (`histcraft collect`, profile `histcraft-collector`), it uses OPC UA Read and
  Browse only; no write service appears in the code (`tests/test_read_only.py`).
  It runs in its own container (uid 10013) on the plant network only, with no
  published port and no route to the apps. The server files browse and test
  requests the collector answers; the two share only the data folder and the
  database, and each set of tables has one writer.
- **The database stays inside.** PlantCraft Historian's PostgreSQL (`histcraft-db`) sits on
  the internal apps network with no published port, runs as PlantCraft Historian's uid with
  a read-only root filesystem and no capabilities, and uses SCRAM passwords. Its
  password is a Docker secret read from a file (`HISTCRAFT_DATABASE_PASSWORD_FILE`),
  never put in the URL, an environment variable or a log; pages show the URL with
  `***` for a password.
- **Sign-in is PlantCraft's.** Every API route and page needs a PlantCraft
  token whose `apps` claim grants `histcraft`; tokens are verified offline with
  PlantCraft's published keys. Viewers read; editors add and change points;
  admins manage sources, settings and deleting archived data. PlantCraft
  reads the data API with a token it signs for audience `histcraft`.
- **No stored secrets.** An OPC UA password is never stored: a source names an
  environment variable `HISTCRAFT_SECRET_<NAME>` of the collector that holds it.
  The app key is read from `PLANTCRAFT_APP_KEY_FILE` when a token is needed
  and is never logged or stored by PlantCraft Historian.
  OPC UA message security (Sign, SignAndEncrypt with certificates) is not
  supported yet (`docs/gaps.md`): use it on a segregated network only.
- **Audit.** Every change a person makes (sources, points, settings) is
  recorded in PlantCraft's audit log (`POST /api/v1/audit`, tagged
  `app: histcraft`). A failed audit write is logged and does not block the change.
- **Container.** The image runs as uid 10008 with a read-only root filesystem;
  state lives only in `/data`, scratch in the `/tmp` tmpfs. It holds no build
  tools, not even pip. Dependencies are installed offline from a hash-checked
  wheelhouse (`deploy/requirements.lock`); `plantcraft-sdk` comes from
  `vendor/` with its SHA-256 in `vendor/README.md`.
