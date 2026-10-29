# The GitHub Actions runner the suite's repository uses on the Mac mini (README.md). Up to
# three containers, all from this image: Ubuntu like GitHub's own runners, with the
# Docker CLI to build images and redeploy the local suite through Docker Desktop's socket.
FROM ubuntu:24.04

ARG RUNNER_VERSION
ARG RUNNER_SHA256
ARG TARGETARCH

ENV DEBIAN_FRONTEND=noninteractive RUNNER_ALLOW_RUNASROOT=1 RUNNER_MANUALLY_TRAP_SIG=1
RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates curl git git-lfs gnupg jq lsb-release make build-essential unzip xz-utils \
        zstd python3 python3-venv python-is-python3 tzdata sudo \
    && install -m 0755 -d /etc/apt/keyrings \
    && curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc \
    && echo "deb [signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu noble stable" \
        > /etc/apt/sources.list.d/docker.list \
    && apt-get update && apt-get install -y --no-install-recommends \
        docker-ce-cli docker-buildx-plugin docker-compose-plugin \
    && rm -rf /var/lib/apt/lists/*

# The runner's own libraries (what its bin/installdependencies.sh would add on Ubuntu 24.04).
RUN apt-get update && apt-get install -y --no-install-recommends \
        libicu74 libkrb5-3 liblttng-ust1t64 libssl3t64 zlib1g \
    && rm -rf /var/lib/apt/lists/*

# The runner itself, checked against the SHA-256 GitHub publishes for it (setup.sh passes both).
WORKDIR /opt/runner
RUN test -n "$RUNNER_VERSION" && test -n "$RUNNER_SHA256" \
    && arch="$(case "$TARGETARCH" in arm64) echo arm64 ;; *) echo x64 ;; esac)" \
    && url="https://github.com/actions/runner/releases/download/v${RUNNER_VERSION}/actions-runner-linux-${arch}-${RUNNER_VERSION}.tar.gz" \
    && echo "downloading $url" && curl -fSL --retry 3 -o runner.tgz "$url"
RUN echo "${RUNNER_SHA256}  runner.tgz" | sha256sum -c - \
    && tar -xzf runner.tgz && rm runner.tgz && test -x ./run.sh

COPY entrypoint.sh /usr/local/bin/runner-entrypoint
COPY suite-deploy ci-slot ci-slot-acquire.sh ci-slot-release.sh /usr/local/bin/
ENTRYPOINT ["/usr/local/bin/runner-entrypoint"]
