# syntax=docker/dockerfile:1.7
#
# The Modelica runner image (modelcraft-runner): OpenModelica's compiler omc, the Modelica
# Standard Library 4.0.0 and the runner (src/modelcraft/omc/runner.py, Python standard library
# only). It is the suite's sandbox for Modelica: compose runs it with no network at all
# (network_mode: none), no secret, a read-only root filesystem and CPU, memory and process
# limits. It runs as the suite's compute user (10020) on PlantCraft's compute workers
# (`modelcraft-executor`, PlantCraft docs/compute.md) and shares only its jobs folder with the
# worker's gateway.
#
# Build from the repository root: make runner-image. Behind a TLS-inspecting proxy pass its CA
# as a build secret (make runner-image BUILD_CA=/path/ca.pem).
#
# OpenModelica (OSMC-PL / GPL 3, used as a separate program, never linked into the app) and
# the Modelica Standard Library (BSD-3-Clause) are pinned by version and digest/commit.

ARG OPENMODELICA_IMAGE=openmodelica/openmodelica:v1.24.4-minimal@sha256:96c5d09d5d4701c2e667ccc6bf14e54ae58018e127d2f1761782ef9ecb0df379

FROM ${OPENMODELICA_IMAGE} AS runtime

ARG VERSION=0.1.0
ARG REVISION=unknown
ARG CREATED=unknown
# The Modelica Standard Library v4.0.0 tag, by commit.
ARG MSL_COMMIT=6626538a236a34a390655b55d5e8c906bfe31772

LABEL org.opencontainers.image.title="modelcraft-runner" \
      org.opencontainers.image.description="The Modelica runner of PlantCraft Models: OpenModelica and the Modelica Standard Library, without network." \
      org.opencontainers.image.version="${VERSION}" \
      org.opencontainers.image.revision="${REVISION}" \
      org.opencontainers.image.created="${CREATED}" \
      org.opencontainers.image.source="https://github.com/PlantCraft/PlantCraft" \
      org.opencontainers.image.base.name="openmodelica/openmodelica:v1.24.4-minimal" \
      org.processcraft.app.id="modelcraft" \
      org.processcraft.app.part="runner"

# Python 3 (the runner) and git (the library, then removed); OpenModelica's own apt source is
# dropped: its packages are already in the image.
RUN --mount=type=secret,id=build_ca,required=false,mode=0444 \
    set -eux; \
    rm -f /etc/apt/sources.list.d/*openmodelica* /etc/apt/sources.list.d/*.list; \
    if [ -s /run/secrets/build_ca ]; then CA="-o Acquire::https::CAInfo=/run/secrets/build_ca"; \
        sed -i 's#http://#https://#g' /etc/apt/sources.list; else CA=""; fi; \
    apt-get $CA update; \
    apt-get $CA install -y --no-install-recommends python3 git ca-certificates; \
    if [ -s /run/secrets/build_ca ]; then export GIT_SSL_CAINFO=/run/secrets/build_ca; fi; \
    git init -q /tmp/msl; \
    git -C /tmp/msl fetch -q --depth 1 https://github.com/modelica/ModelicaStandardLibrary.git "${MSL_COMMIT}"; \
    git -C /tmp/msl checkout -q FETCH_HEAD; \
    test "$(git -C /tmp/msl rev-parse HEAD)" = "${MSL_COMMIT}"; \
    mkdir -p /opt/modelica; \
    cp -r /tmp/msl/Modelica /tmp/msl/ModelicaServices /tmp/msl/Complex.mo /tmp/msl/LICENSE /opt/modelica/; \
    rm -rf /tmp/msl; \
    apt-get purge -y git; apt-get autoremove -y; rm -rf /var/lib/apt/lists/*; \
    groupadd --gid 10020 compute; \
    useradd --no-create-home --uid 10020 --gid 10020 --home-dir /tmp --shell /usr/sbin/nologin compute; \
    mkdir -p /jobs; chown 10020:10020 /jobs; chmod 0750 /jobs

COPY src/modelcraft/omc/runner.py /opt/runner/runner.py
COPY LICENSE ATTRIBUTION.md /opt/runner/

ENV HOME=/tmp \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    MODELCRAFT_JOBS_DIR=/jobs \
    MODELCRAFT_LIBRARIES=/opt/modelica

USER 10020:10020

HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=5 \
    CMD ["python3", "-c", "import json, time; s = json.load(open('/jobs/runner.json')); assert time.time() - s['at'] < 60"]

CMD ["python3", "/opt/runner/runner.py"]
