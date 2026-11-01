# syntax=docker/dockerfile:1.7
#
# PlantCraft PID image: a CLOSED app (PlantCraft docs/app-package.md, section 8). It ships
# in its own signed package (dist/pidcraft-<version>.pcapp), never in the open suite bundle, and
# carries no Python source of the app: only one compiled module.
# Four stages:
#   1. frontend: builds the web interface with Node (never shipped), with @plantcraft/ui
#                from vendor/; minified, no source maps.
#   2. wheels:   downloads every Python dependency as a wheel, checked against the hashes in
#                deploy/requirements.lock (binary wheels only). plantcraft-sdk comes from
#                vendor/, never from an index.
#   3. compiled: Nuitka (deploy/build-requirements.lock, hash-checked) turns the whole pidcraft
#                package into one C extension module, pidcraft.<abi>.so, without docstrings.
#                The compiler and the source stay in this stage.
#   4. runtime:  Python slim, installs from that wheelhouse with --no-index (no network), adds
#                the compiled module, checks that no pidcraft .py or .pyc is left, runs as an
#                unprivileged user and holds no build tools, not even pip.
#
# What compiling protects, plainly: the code is machine code, not readable Python; names,
# messages and constants can still be read from the binary, and a skilled person with time can
# take it apart or patch out the licence check. The licence contract is the real protection.
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
# plantcraft-sdk from vendor/ only, checked against the SHA256 in vendor/README.md.
RUN grep -o '[0-9a-f]\{64\}  plantcraft_sdk-0.102.0-py3-none-any.whl' vendor/README.md \
        | (cd vendor && sha256sum -c -) \
    && cp vendor/plantcraft_sdk-0.102.0-py3-none-any.whl /wheelhouse/

FROM ${PYTHON_IMAGE} AS compiled
WORKDIR /build
RUN apt-get update \
    && apt-get install -y --no-install-recommends gcc libc6-dev \
    && rm -rf /var/lib/apt/lists/*
COPY deploy/build-requirements.lock ./
RUN --mount=type=secret,id=build_ca,required=false \
    if [ -s /run/secrets/build_ca ]; then export PIP_CERT=/run/secrets/build_ca; fi; \
    pip install --no-cache-dir --root-user-action=ignore --require-hashes -r build-requirements.lock
COPY src ./src
# One module for the whole package; the package's data files (not code) beside it.
RUN cd src \
    && python -m nuitka --mode=module pidcraft --include-package=pidcraft \
        --output-dir=/compiled --remove-output --no-pyi-file --python-flag=no_docstrings \
        --quiet \
    && find pidcraft -type f ! -name '*.py' ! -path '*__pycache__*' -exec cp --parents {} /compiled/ \; \
    && ls /compiled/pidcraft.*.so

FROM ${PYTHON_IMAGE} AS runtime

ARG VERSION=0.1.0
ARG REVISION=unknown
ARG CREATED=unknown

LABEL org.opencontainers.image.title="pidcraft" \
      org.opencontainers.image.description="The plant's P&IDs read into a plant map: units, equipment, lines and control loops." \
      org.opencontainers.image.version="${VERSION}" \
      org.opencontainers.image.revision="${REVISION}" \
      org.opencontainers.image.created="${CREATED}" \
      org.opencontainers.image.licenses="LicenseRef-PlantCraft-EULA" \
      org.opencontainers.image.base.name="python:3.13.16-slim-trixie" \
      org.processcraft.app.id="pidcraft" \
      org.processcraft.app.prefix="/pid/" \
      org.processcraft.app.port="8160"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HOME=/tmp \
    PLANTCRAFT_URL=http://processcraft:8060 \
    PIDCRAFT_ROOT_PATH=/pid \
    PIDCRAFT_DATA_DIR=/data \
    PIDCRAFT_UI_DIR=/app/ui \
    PIDCRAFT_APP_DIR=/app \
    PIDCRAFT_REVISION=${REVISION} \
    PIDCRAFT_HOST=0.0.0.0 \
    PIDCRAFT_PORT=8160 \
    FORWARDED_ALLOW_IPS=127.0.0.1

# OCR for scanned drawings (the plant map reads tags on scans with it): tesseract with its
# English data, from Debian, nothing else. Without it scans are skipped, never an error.
RUN apt-get update \
    && apt-get install -y --no-install-recommends tesseract-ocr tesseract-ocr-eng \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY --from=frontend /build/frontend/dist /app/ui
COPY LICENSE ATTRIBUTION.md CHANGELOG.md app.toml /app/
COPY docs/help /app/docs/help

# Dependencies from the hash-checked wheelhouse, without network; then the SDK; then the
# compiled module of PlantCraft PID and its launcher. --no-deps everywhere: the lock is
# complete. The build fails if any pidcraft source or bytecode reached the image.
RUN --mount=type=bind,from=wheels,source=/wheelhouse,target=/wheelhouse \
    --mount=type=bind,source=deploy/requirements.lock,target=/tmp/requirements.lock \
    --mount=type=bind,from=compiled,source=/compiled,target=/compiled \
    python -m pip install --no-cache-dir --root-user-action=ignore --no-index --find-links /wheelhouse \
        --require-hashes --no-deps -r /tmp/requirements.lock \
    && python -m pip install --no-cache-dir --root-user-action=ignore --no-index --no-deps \
        /wheelhouse/plantcraft_sdk-0.102.0-py3-none-any.whl \
    && python -m pip check \
    && site="$(python -c 'import sysconfig; print(sysconfig.get_paths()["purelib"])')" \
    && cp -r /compiled/. "$site/" \
    && printf '#!/usr/local/bin/python\nfrom pidcraft.cli import main\nraise SystemExit(main())\n' \
        > /usr/local/bin/pidcraft \
    && chmod 0755 /usr/local/bin/pidcraft \
    && if find / -xdev \( -path /proc -o -path /sys \) -prune -o \
        \( -path '*pidcraft*' \( -name '*.py' -o -name '*.pyc' \) \) -print | grep .; then \
        echo "pidcraft source in the image" >&2; exit 1; fi \
    && python -c "import pidcraft; assert hasattr(pidcraft, '__compiled__'), 'not compiled'" \
    && python -m pip uninstall -y --root-user-action=ignore pip \
    && SBOM_CREATED="${CREATED}" python -m plantcraft_sdk.sbom --here "pidcraft:${VERSION}" > /app/sbom.json \
    && rm -rf /root/.cache \
    && groupadd --gid 10016 pidcraft \
    && useradd --no-create-home --uid 10016 --gid 10016 --home-dir /tmp --shell /usr/sbin/nologin pidcraft \
    && mkdir -p /data \
    && chown 10016:10016 /data \
    && chmod 0750 /data

USER 10016:10016

EXPOSE 8160

HEALTHCHECK --interval=20s --timeout=5s --start-period=60s --retries=5 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8160/healthz', timeout=4)"]

CMD ["pidcraft", "serve"]
