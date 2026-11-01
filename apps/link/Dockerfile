# syntax=docker/dockerfile:1.7
#
# PlantCraft Analytics image: built online once, then shipped offline in the PlantCraft suite bundle.
# Three stages:
#   1. frontend: builds the web interface with Node (never shipped).
#   2. wheels:   downloads every Python dependency as a wheel, checked against the hashes in
#                deploy/requirements.lock (binary wheels only: no compiler anywhere), plus the
#                PlantCraft Analytics wheel. plantcraft-sdk comes from vendor/, never from an index.
#   3. runtime:  Python slim, installs from that wheelhouse with --no-index (no network), runs
#                as an unprivileged user and holds no build tools, not even pip.
#
# Runs under the suite's deploy/compose.yaml: read-only root filesystem, state only in /data,
# scratch in the /tmp tmpfs, app key from the file PLANTCRAFT_APP_KEY_FILE names.
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
# @plantcraft/ui comes from vendor/ (file:../vendor/plantcraft-ui-<version>.tgz), checked
# against its SHA256 in vendor/README.md before npm installs it.
COPY vendor/README.md vendor/plantcraft-ui-*.tgz /build/vendor/
RUN cd /build/vendor && grep -o '[0-9a-f]\{64\}  plantcraft-ui-[^ ]*\.tgz' README.md | sha256sum -c -
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
    pip wheel --no-cache-dir --require-hashes --no-deps --only-binary=:all: \
        --wheel-dir /wheelhouse -r requirements.lock
COPY vendor ./vendor
COPY pyproject.toml README.md LICENSE app.toml ./
COPY src ./src
# The version is app.toml's (`make image` passes it): the label, the tag and /healthz agree.
ARG VERSION
RUN python -c "import sys, tomllib; \
want = tomllib.load(open('app.toml', 'rb'))['app']['version']; \
sys.exit(None if '${VERSION}' == want else \
f'--build-arg VERSION=${VERSION}, app.toml says {want}: build with make image')"
# plantcraft-sdk from vendor/ only, checked against the SHA256 in vendor/README.md; then the
# PlantCraft Analytics wheel (--no-deps: the index only provides its build backend, setuptools).
RUN --mount=type=secret,id=build_ca,required=false \
    if [ -s /run/secrets/build_ca ]; then export PIP_CERT=/run/secrets/build_ca; fi; \
    grep -o '[0-9a-f]\{64\}  plantcraft_sdk-0.102.0-py3-none-any.whl' vendor/README.md \
        | (cd vendor && sha256sum -c -) \
    && cp vendor/plantcraft_sdk-0.102.0-py3-none-any.whl /wheelhouse/ \
    && pip wheel --no-cache-dir --no-deps --wheel-dir /wheelhouse . \
    && rm -rf build

FROM ${PYTHON_IMAGE} AS runtime

# From app.toml (`make image` passes them; the defaults match it, tests/test_app_manifest.py).
ARG APP_ID=linkcraft
ARG APP_PREFIX=/link/
ARG APP_PORT=8140
ARG APP_UID=10012
ARG SUMMARY="Scheduled monitors, diagnostics and KPIs for signals and control loops: finds bad data, oscillation, sticking valves and manual mode, and says why."
ARG VERSION
ARG REVISION=unknown
ARG CREATED=unknown

LABEL org.opencontainers.image.title="${APP_ID}" \
      org.opencontainers.image.description="${SUMMARY}" \
      org.opencontainers.image.version="${VERSION}" \
      org.opencontainers.image.revision="${REVISION}" \
      org.opencontainers.image.created="${CREATED}" \
      org.opencontainers.image.licenses="Apache-2.0" \
      org.opencontainers.image.source="https://github.com/PlantCraft/PlantCraft" \
      org.opencontainers.image.base.name="python:3.13.16-slim-trixie" \
      org.processcraft.app.id="${APP_ID}" \
      org.processcraft.app.prefix="${APP_PREFIX}" \
      org.processcraft.app.port="${APP_PORT}"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HOME=/tmp \
    PLANTCRAFT_URL=http://processcraft:8060 \
    LINKCRAFT_ROOT_PATH=/link \
    LINKCRAFT_DATA_DIR=/data \
    LINKCRAFT_UI_DIR=/app/ui \
    LINKCRAFT_HOST=0.0.0.0 \
    LINKCRAFT_PORT=${APP_PORT} \
    LINKCRAFT_APP_TOML=/app/app.toml \
    LINKCRAFT_REVISION=${REVISION} \
    FORWARDED_ALLOW_IPS=127.0.0.1

WORKDIR /app
COPY --from=frontend /build/frontend/dist /app/ui
COPY LICENSE ATTRIBUTION.md CHANGELOG.md app.toml /app/
COPY fmus /app/fmus

# Dependencies from the hash-checked wheelhouse, without network; then the SDK and PlantCraft Analytics.
RUN --mount=type=bind,from=wheels,source=/wheelhouse,target=/wheelhouse \
    --mount=type=bind,source=deploy/requirements.lock,target=/tmp/requirements.lock \
    python -m pip install --no-cache-dir --root-user-action=ignore --no-index --find-links /wheelhouse \
        --require-hashes --no-deps -r /tmp/requirements.lock \
    && python -m pip install --no-cache-dir --root-user-action=ignore --no-index --no-deps \
        /wheelhouse/plantcraft_sdk-0.102.0-py3-none-any.whl /wheelhouse/linkcraft-*.whl \
    && { python -m pip check | grep -Ev '^fmpy [0-9.]+ requires (cmake|jinja2|nbformat),' || true; } \
        | { ! grep . ; } \
    && python -m compileall -q "$(python -c 'import sysconfig; print(sysconfig.get_paths()["purelib"])')/linkcraft" \
    && python -m pip uninstall -y --root-user-action=ignore pip \
    && SBOM_CREATED="${CREATED}" python -m plantcraft_sdk.sbom --here "${APP_ID}:${VERSION}" > /app/sbom.json \
    && rm -rf /root/.cache \
    && groupadd --gid ${APP_UID} ${APP_ID} \
    && useradd --no-create-home --uid ${APP_UID} --gid ${APP_UID} --home-dir /tmp --shell /usr/sbin/nologin ${APP_ID} \
    && mkdir -p /data \
    && chown ${APP_UID}:${APP_UID} /data \
    && chmod 0750 /data

USER ${APP_UID}:${APP_UID}

EXPOSE ${APP_PORT}

HEALTHCHECK --interval=20s --timeout=5s --start-period=60s --retries=5 \
    CMD ["python", "-c", "import os, urllib.request; urllib.request.urlopen('http://127.0.0.1:%s/healthz' % os.environ['LINKCRAFT_PORT'], timeout=4)"]

CMD ["linkcraft", "serve"]
