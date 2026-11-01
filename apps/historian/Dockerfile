# syntax=docker/dockerfile:1.7
#
# PlantCraft Historian image: built online once, then shipped offline in the PlantCraft suite bundle.
# Three stages:
#   1. frontend: builds the web interface with Node (never shipped), with @plantcraft/ui
#                from vendor/.
#   2. wheels:   downloads every Python dependency as a wheel, checked against the hashes in
#                deploy/requirements.lock (binary wheels only: no compiler anywhere), plus the
#                PlantCraft Historian wheel. plantcraft-sdk comes from vendor/, never from an index.
#   3. runtime:  Python slim, installs from that wheelhouse with --no-index (no network), runs
#                as an unprivileged user and holds no build tools, not even pip.
#
# One image, two services (deploy/compose.histcraft.yaml): `histcraft serve` (pages and API, apps
# network) and `histcraft collect` (the collector, plant network only, no port). Both run with a
# read-only root filesystem, state only in /data (shared), scratch in the /tmp tmpfs.
#
# Base images are pinned by version and digest (the same ones PlantCraft uses). Override them
# with --build-arg NODE_IMAGE=... / PYTHON_IMAGE=... (for example a registry mirror holding the
# same digests). Behind a TLS-inspecting proxy pass its CA as a build secret:
#   docker build --secret id=build_ca,src=/path/to/ca.pem ...   (make image BUILD_CA=...)

ARG NODE_IMAGE=node:22.23.3-slim@sha256:c3de60bf2f9dd0ac6370e6117950ff62d6e339527e7472301c9c78a017978392
ARG PYTHON_IMAGE=python:3.13.16-slim-trixie@sha256:70729b46c69b4f1e97c4822c1af3df53a1476cf5ddc6c087c0c10bc3a5678c2f

# On the build machine's own processor: the web interface is the same for amd64 and arm64.
FROM --platform=$BUILDPLATFORM ${NODE_IMAGE} AS frontend
WORKDIR /build/frontend
# @plantcraft/ui comes from vendor/ (package.json: file:../vendor/...), checked against the
# SHA-256 in vendor/README.md before npm ci (which checks it again against package-lock.json).
COPY vendor/README.md vendor/plantcraft-ui-*.tgz /build/vendor/
RUN grep -o '[0-9a-f]\{64\}  plantcraft-ui-[0-9.]*\.tgz' /build/vendor/README.md \
        | (cd /build/vendor && sha256sum -c -)
COPY frontend/package.json frontend/package-lock.json ./
RUN --mount=type=secret,id=build_ca,required=false \
    if [ -s /run/secrets/build_ca ]; then export NODE_EXTRA_CA_CERTS=/run/secrets/build_ca; fi; \
    npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

FROM ${PYTHON_IMAGE} AS wheels
WORKDIR /build
COPY deploy/requirements.lock ./
RUN --mount=type=secret,id=build_ca,required=false \
    if [ -s /run/secrets/build_ca ]; then export PIP_CERT=/run/secrets/build_ca; fi; \
    pip wheel --no-cache-dir --require-hashes --only-binary=:all: \
        --wheel-dir /wheelhouse -r requirements.lock
COPY vendor ./vendor
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
# plantcraft-sdk from vendor/ only, checked against the SHA256 in vendor/README.md; then the
# PlantCraft Historian wheel (--no-deps: the index only provides its build backend, setuptools).
RUN --mount=type=secret,id=build_ca,required=false \
    if [ -s /run/secrets/build_ca ]; then export PIP_CERT=/run/secrets/build_ca; fi; \
    grep -o '[0-9a-f]\{64\}  plantcraft_sdk-0.97.0-py3-none-any.whl' vendor/README.md \
        | (cd vendor && sha256sum -c -) \
    && cp vendor/plantcraft_sdk-0.97.0-py3-none-any.whl /wheelhouse/ \
    && pip wheel --no-cache-dir --no-deps --wheel-dir /wheelhouse . \
    && rm -rf build

FROM ${PYTHON_IMAGE} AS runtime

ARG VERSION=0.1.0
ARG REVISION=unknown
ARG CREATED=unknown

LABEL org.opencontainers.image.title="histcraft" \
      org.opencontainers.image.description="The suite's data layer: every plant connection and every history, read-only toward the plant." \
      org.opencontainers.image.version="${VERSION}" \
      org.opencontainers.image.revision="${REVISION}" \
      org.opencontainers.image.created="${CREATED}" \
      org.opencontainers.image.licenses="Apache-2.0" \
      org.opencontainers.image.source="https://github.com/PlantCraft/PlantCraft" \
      org.opencontainers.image.base.name="python:3.13.16-slim-trixie" \
      org.processcraft.app.id="histcraft" \
      org.processcraft.app.prefix="/hist/" \
      org.processcraft.app.port="8100"

# MALLOC_ARENA_MAX: two malloc arenas, not one per thread: the memory long reads used goes
# back to the system instead of staying with the process (16 long reads at once kept 1.4 GiB
# after they ended; 0.8 GiB with two arenas, load test 2026-10-27).
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    MALLOC_ARENA_MAX=2 \
    HOME=/tmp \
    PLANTCRAFT_URL=http://processcraft:8060 \
    HISTCRAFT_ROOT_PATH=/hist \
    HISTCRAFT_COLLECTOR=embedded \
    HISTCRAFT_OPCUA=off \
    HISTCRAFT_DATA_DIR=/data \
    HISTCRAFT_UI_DIR=/app/ui \
    HISTCRAFT_APP_DIR=/app \
    HISTCRAFT_REVISION=${REVISION} \
    HISTCRAFT_HOST=0.0.0.0 \
    HISTCRAFT_PORT=8100 \
    FORWARDED_ALLOW_IPS=127.0.0.1

WORKDIR /app
COPY --from=frontend /build/frontend/dist /app/ui
COPY LICENSE ATTRIBUTION.md CHANGELOG.md app.toml /app/
COPY docs/help /app/docs/help

# Dependencies from the hash-checked wheelhouse, without network; then the SDK and PlantCraft Historian.
RUN --mount=type=bind,from=wheels,source=/wheelhouse,target=/wheelhouse \
    --mount=type=bind,source=deploy/requirements.lock,target=/tmp/requirements.lock \
    --mount=type=bind,source=deploy/sbom.py,target=/tmp/sbom.py \
    --mount=type=bind,source=frontend/package-lock.json,target=/tmp/package-lock.json \
    python -m pip install --no-cache-dir --root-user-action=ignore --no-index --find-links /wheelhouse \
        --require-hashes -r /tmp/requirements.lock \
    && python -m pip install --no-cache-dir --root-user-action=ignore --no-index --no-deps \
        /wheelhouse/plantcraft_sdk-0.97.0-py3-none-any.whl /wheelhouse/histcraft-*.whl \
    && python -m pip check \
    && python -m compileall -q "$(python -c 'import sysconfig; print(sysconfig.get_paths()["purelib"])')/histcraft" \
    && python -m pip uninstall -y --root-user-action=ignore pip \
    && python /tmp/sbom.py /tmp/package-lock.json > /app/sbom.json \
    && rm -rf /root/.cache \
    && groupadd --gid 10008 histcraft \
    && useradd --no-create-home --uid 10008 --gid 10008 --home-dir /tmp --shell /usr/sbin/nologin histcraft \
    && mkdir -p /data \
    && chown 10008:10008 /data \
    && chmod 0770 /data

USER 10008:10008

EXPOSE 8100

HEALTHCHECK --interval=20s --timeout=5s --start-period=60s --retries=5 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8100/healthz', timeout=4)"]

CMD ["histcraft", "serve"]
