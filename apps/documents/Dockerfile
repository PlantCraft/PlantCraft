# syntax=docker/dockerfile:1.7
#
# PlantCraft Documents image: built online once, then shipped offline in the PlantCraft suite bundle.
# Four stages:
#   1. frontend: builds the web interface with Node (never shipped), with @plantcraft/ui
#                from the repository's ui/.
#   model:       downloads the embedding model named in deploy/embedding-model.lock, each file
#                checked against its SHA-256 (the app never downloads anything at run time).
#   2. wheels:   downloads every Python dependency as a wheel, checked against the hashes in
#                deploy/requirements.lock (binary wheels only: no compiler anywhere), plus the
#                PlantCraft Documents wheel. plantcraft-sdk is built from the repository's
#                sdk/python, never fetched from an index.
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
# The repository's layout, so frontend/package.json's file:../../../ui is /build/ui.
WORKDIR /build/apps/app/frontend
# @plantcraft/ui comes from this repository's ui/ (the build context named ui: make image passes
# --build-context ui=../../ui), built first with its own locked dependencies.
COPY --from=ui package.json package-lock.json tsconfig.json vite.mjs vite.d.mts /build/ui/
RUN --mount=type=secret,id=build_ca,required=false \
    if [ -s /run/secrets/build_ca ]; then export NODE_EXTRA_CA_CERTS=/run/secrets/build_ca; fi; \
    cd /build/ui && npm ci --no-audit --no-fund
COPY --from=ui src /build/ui/src
RUN cd /build/ui && npm run build
COPY frontend/package.json frontend/package-lock.json ./
RUN --mount=type=secret,id=build_ca,required=false \
    if [ -s /run/secrets/build_ca ]; then export NODE_EXTRA_CA_CERTS=/run/secrets/build_ca; fi; \
    npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# The embedding model (multilingual-e5-small, ONNX, 8-bit weights), the same for amd64 and arm64.
FROM --platform=$BUILDPLATFORM ${PYTHON_IMAGE} AS model
COPY deploy/embedding-model.lock deploy/fetch_model.py /build/
RUN --mount=type=secret,id=build_ca,required=false \
    if [ -s /run/secrets/build_ca ]; then export SSL_CERT_FILE=/run/secrets/build_ca; fi; \
    python /build/fetch_model.py /build/embedding-model.lock /models/multilingual-e5-small

FROM ${PYTHON_IMAGE} AS wheels
WORKDIR /build
COPY deploy/requirements.lock ./
RUN --mount=type=secret,id=build_ca,required=false \
    if [ -s /run/secrets/build_ca ]; then export PIP_CERT=/run/secrets/build_ca; fi; \
    pip wheel --no-cache-dir --require-hashes --no-deps --only-binary=:all: \
        --wheel-dir /wheelhouse -r requirements.lock
# plantcraft-sdk comes from this repository's sdk/python (the build context named sdk), without
# its tests or any local bytecode.
COPY --from=sdk pyproject.toml ./sdk/
COPY --from=sdk plantcraft_sdk ./sdk/plantcraft_sdk
COPY --from=sdk processcraft_sdk ./sdk/processcraft_sdk
RUN find ./sdk -name __pycache__ -prune -exec rm -rf {} +
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
# The plantcraft-sdk wheel from the tree, then the
# PlantCraft Documents wheel (--no-deps: the index only provides its build backend, setuptools).
RUN --mount=type=secret,id=build_ca,required=false \
    if [ -s /run/secrets/build_ca ]; then export PIP_CERT=/run/secrets/build_ca; fi; \
    pip wheel --no-cache-dir --no-deps --wheel-dir /wheelhouse ./sdk . \
    && rm -rf build

FROM ${PYTHON_IMAGE} AS runtime

ARG VERSION=0.1.0
ARG REVISION=unknown
ARG CREATED=unknown

LABEL org.opencontainers.image.title="doccraft" \
      org.opencontainers.image.description="The plant's manuals, narratives, datasheets and guides, searched offline and cited by the assistant." \
      org.opencontainers.image.version="${VERSION}" \
      org.opencontainers.image.revision="${REVISION}" \
      org.opencontainers.image.created="${CREATED}" \
      org.opencontainers.image.licenses="Apache-2.0" \
      org.opencontainers.image.base.name="python:3.13.16-slim-trixie" \
      org.processcraft.app.id="doccraft" \
      org.processcraft.app.prefix="/doc/" \
      org.processcraft.app.port="8150"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HOME=/tmp \
    PLANTCRAFT_URL=http://processcraft:8060 \
    DOCCRAFT_ROOT_PATH=/doc \
    DOCCRAFT_EMBEDDING_DIR=/app/models/multilingual-e5-small \
    DOCCRAFT_DATA_DIR=/data \
    DOCCRAFT_UI_DIR=/app/ui \
    DOCCRAFT_APP_DIR=/app \
    DOCCRAFT_REVISION=${REVISION} \
    DOCCRAFT_HOST=0.0.0.0 \
    DOCCRAFT_PORT=8150 \
    FORWARDED_ALLOW_IPS=127.0.0.1

WORKDIR /app
COPY --from=frontend /build/apps/app/frontend/dist /app/ui
COPY LICENSE ATTRIBUTION.md CHANGELOG.md app.toml /app/
COPY docs/help /app/docs/help
COPY --from=model /models /app/models

# Dependencies from the hash-checked wheelhouse, without network; then the SDK and PlantCraft Documents.
# --no-deps everywhere: the lock is complete.
RUN --mount=type=bind,from=wheels,source=/wheelhouse,target=/wheelhouse \
    --mount=type=bind,source=deploy/requirements.lock,target=/tmp/requirements.lock \
    python -m pip install --no-cache-dir --root-user-action=ignore --no-index --find-links /wheelhouse \
        --require-hashes --no-deps -r /tmp/requirements.lock \
    && python -m pip install --no-cache-dir --root-user-action=ignore --no-index --no-deps \
        /wheelhouse/plantcraft_sdk-*-py3-none-any.whl /wheelhouse/doccraft-*.whl \
    && python -m pip check \
    && python -m compileall -q "$(python -c 'import sysconfig; print(sysconfig.get_paths()["purelib"])')/doccraft" \
    && python -m pip uninstall -y --root-user-action=ignore pip \
    && SBOM_CREATED="${CREATED}" python -m plantcraft_sdk.sbom --here "doccraft:${VERSION}" > /app/sbom.json \
    && rm -rf /root/.cache \
    && groupadd --gid 10015 doccraft \
    && useradd --no-create-home --uid 10015 --gid 10015 --home-dir /tmp --shell /usr/sbin/nologin doccraft \
    && mkdir -p /data \
    && chown 10015:10015 /data \
    && chmod 0750 /data

USER 10015:10015

EXPOSE 8150

HEALTHCHECK --interval=20s --timeout=5s --start-period=60s --retries=5 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8150/healthz', timeout=4)"]

CMD ["doccraft", "serve"]
