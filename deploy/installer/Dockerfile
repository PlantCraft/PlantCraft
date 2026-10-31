# syntax=docker/dockerfile:1.7
#
# PlantCraft installer: the only container of the suite with access to the Docker socket
# (compose service `installer`, docs/app-package.md, docs/security-guide.md). Built by
# `make image` from the repository root:  docker build -f deploy/installer/Dockerfile .
#
# It holds Python with `cryptography` (hash-checked wheels from deploy/requirements.lock), the
# static Docker CLI and Compose plugin, and two files of PlantCraft: plantcraft/apps/package.py
# (verification) and plantcraft/apps/installer.py. Nothing else of the application is in it.
# It runs with no network at all (`network_mode: none`).

ARG PYTHON_IMAGE=python:3.13.16-slim-trixie@sha256:70729b46c69b4f1e97c4822c1af3df53a1476cf5ddc6c087c0c10bc3a5678c2f
ARG DOCKER_CLI_IMAGE=docker:29.9.2-cli@sha256:5e6baf67325a79f64ed3bed6863954d5e05d0f3d4e57cbdb14809346814bbfdb

FROM ${DOCKER_CLI_IMAGE} AS cli

FROM ${PYTHON_IMAGE} AS wheels
WORKDIR /build
COPY deploy/requirements.lock ./
# Only cryptography and what it needs, with the hashes of the main lock file.
RUN python - <<'EOF'
import re
blocks = re.split(r"^(?=[A-Za-z0-9_.-]+==)", open("requirements.lock").read(), flags=re.M)
wanted = {"cryptography", "cffi", "pycparser"}
keep = [b for b in blocks if b.split("==", 1)[0].strip().lower() in wanted]
assert len(keep) == len(wanted), keep
open("installer.lock", "w").write("".join(keep))
EOF
RUN --mount=type=secret,id=build_ca,required=false \
    if [ -s /run/secrets/build_ca ]; then export PIP_CERT=/run/secrets/build_ca; fi; \
    pip wheel --no-cache-dir --require-hashes --only-binary=:all: --no-deps \
        --wheel-dir /wheelhouse -r installer.lock

FROM ${PYTHON_IMAGE} AS runtime

ARG VERSION=0.0.0
ARG REVISION=unknown
ARG CREATED=unknown

LABEL org.opencontainers.image.title="processcraft-installer" \
      org.opencontainers.image.description="PlantCraft installer: verifies signed app packages and runs them (the only part with Docker access)" \
      org.opencontainers.image.version="${VERSION}" \
      org.opencontainers.image.revision="${REVISION}" \
      org.opencontainers.image.created="${CREATED}" \
      org.opencontainers.image.licenses="Apache-2.0" \
      org.opencontainers.image.source="https://github.com/PlantCraft/PlantCraft" \
      org.opencontainers.image.base.name="python:3.13.16-slim-trixie"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app \
    HOME=/tmp \
    DOCKER_CONFIG=/tmp/.docker

COPY --from=cli /usr/local/bin/docker /usr/local/bin/docker
COPY --from=cli /usr/local/libexec/docker/cli-plugins/docker-compose /usr/local/libexec/docker/cli-plugins/docker-compose

RUN --mount=type=bind,from=wheels,source=/wheelhouse,target=/wheelhouse \
    --mount=type=bind,from=wheels,source=/build/installer.lock,target=/tmp/installer.lock \
    python -m pip install --no-cache-dir --root-user-action=ignore --no-index \
        --find-links /wheelhouse --require-hashes -r /tmp/installer.lock \
    && python -m pip uninstall -y --root-user-action=ignore pip \
    && rm -rf /root/.cache \
    && groupadd --gid 10005 installer \
    && useradd --no-create-home --uid 10005 --gid 10005 --home-dir /tmp --shell /usr/sbin/nologin installer

COPY plantcraft/__init__.py /app/plantcraft/__init__.py
# The package's name until 0.5.0: `python -m processcraft.apps.<module>` still runs on this image
# (plantcraft/legacy.py), so an older install.sh or Backups page can drive it.
COPY plantcraft/legacy.py /app/processcraft/__init__.py
COPY plantcraft/apps/__init__.py plantcraft/apps/package.py plantcraft/apps/installer.py plantcraft/apps/operations.py plantcraft/apps/historian_backup.py plantcraft/apps/release.py /app/plantcraft/apps/
# Backup, restore and updates (docs/operations.md), run by the operations driver: this image as root.
COPY plantcraft/ops/__init__.py plantcraft/ops/snapshot.py /app/plantcraft/ops/
RUN python -m compileall -q /app/plantcraft /app/processcraft \
    && chmod -R u=rwX,go=rX /app \
    && su -s /bin/sh installer -c 'python -c "import plantcraft.apps.installer, plantcraft.apps.operations, plantcraft.apps.historian_backup, plantcraft.apps.release, processcraft.apps.release"'

USER 10005:10005

HEALTHCHECK --interval=15s --timeout=5s --start-period=20s --retries=5 \
    CMD ["python", "-m", "plantcraft.apps.installer", "health"]

ENTRYPOINT ["python", "-m", "plantcraft.apps.installer"]
CMD ["serve"]
