# syntax=docker/dockerfile:1.7
#
# StarterCraft image: built online once, then shipped offline in the PlantCraft suite bundle.
# Three stages:
#   1. frontend: builds the web interface with Node (never shipped), with @plantcraft/ui
#                from vendor/.
#   2. wheels:   downloads every Python dependency as a wheel, checked against the hashes in
#                deploy/requirements.lock (binary wheels only: no compiler anywhere), plus the
#                StarterCraft wheel. plantcraft-sdk comes from vendor/, never from an index.
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
    pip wheel --no-cache-dir --require-hashes --no-deps --only-binary=:all: \
        --wheel-dir /wheelhouse -r requirements.lock
COPY vendor ./vendor
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
# plantcraft-sdk from vendor/ only, checked against the SHA256 in vendor/README.md; then the
# StarterCraft wheel (--no-deps: the index only provides its build backend, setuptools).
RUN --mount=type=secret,id=build_ca,required=false \
    if [ -s /run/secrets/build_ca ]; then export PIP_CERT=/run/secrets/build_ca; fi; \
    grep -o '[0-9a-f]\{64\}  plantcraft_sdk-0.98.0-py3-none-any.whl' vendor/README.md \
        | (cd vendor && sha256sum -c -) \
    && cp vendor/plantcraft_sdk-0.98.0-py3-none-any.whl /wheelhouse/ \
    && pip wheel --no-cache-dir --no-deps --wheel-dir /wheelhouse . \
    && rm -rf build

FROM ${PYTHON_IMAGE} AS runtime

ARG VERSION=0.1.0
ARG REVISION=unknown
ARG CREATED=unknown

LABEL org.opencontainers.image.title="starter" \
      org.opencontainers.image.description="The smallest app of the PlantCraft suite: a note on any asset of the plant." \
      org.opencontainers.image.version="${VERSION}" \
      org.opencontainers.image.revision="${REVISION}" \
      org.opencontainers.image.created="${CREATED}" \
      org.opencontainers.image.licenses="Apache-2.0" \
      org.opencontainers.image.base.name="python:3.13.16-slim-trixie" \
      org.processcraft.app.id="starter" \
      org.processcraft.app.prefix="/starter/" \
      org.processcraft.app.port="9100"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HOME=/tmp \
    PLANTCRAFT_URL=http://processcraft:8060 \
    STARTER_ROOT_PATH=/starter \
    STARTER_DATA_DIR=/data \
    STARTER_UI_DIR=/app/ui \
    STARTER_APP_DIR=/app \
    STARTER_REVISION=${REVISION} \
    STARTER_HOST=0.0.0.0 \
    STARTER_PORT=9100 \
    FORWARDED_ALLOW_IPS=127.0.0.1

WORKDIR /app
COPY --from=frontend /build/frontend/dist /app/ui
COPY LICENSE ATTRIBUTION.md CHANGELOG.md app.toml /app/
COPY docs/help /app/docs/help

# Dependencies from the hash-checked wheelhouse, without network; then the SDK and StarterCraft.
# --no-deps everywhere: the lock is complete.
RUN --mount=type=bind,from=wheels,source=/wheelhouse,target=/wheelhouse \
    --mount=type=bind,source=deploy/requirements.lock,target=/tmp/requirements.lock \
    python -m pip install --no-cache-dir --root-user-action=ignore --no-index --find-links /wheelhouse \
        --require-hashes --no-deps -r /tmp/requirements.lock \
    && python -m pip install --no-cache-dir --root-user-action=ignore --no-index --no-deps \
        /wheelhouse/plantcraft_sdk-0.98.0-py3-none-any.whl /wheelhouse/starter-*.whl \
    && python -m pip check \
    && python -m compileall -q "$(python -c 'import sysconfig; print(sysconfig.get_paths()["purelib"])')/starter" \
    && python -m pip uninstall -y --root-user-action=ignore pip \
    && SBOM_CREATED="${CREATED}" python -m plantcraft_sdk.sbom --here "starter:${VERSION}" > /app/sbom.json \
    && rm -rf /root/.cache \
    && groupadd --gid 20100 starter \
    && useradd --no-create-home --uid 20100 --gid 20100 --home-dir /tmp --shell /usr/sbin/nologin starter \
    && mkdir -p /data \
    && chown 20100:20100 /data \
    && chmod 0750 /data

USER 20100:20100

EXPOSE 9100

HEALTHCHECK --interval=20s --timeout=5s --start-period=60s --retries=5 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:9100/healthz', timeout=4)"]

CMD ["starter", "serve"]
