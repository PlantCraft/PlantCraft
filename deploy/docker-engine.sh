#!/usr/bin/env bash
# Docker Engine for a Linux server that has none, offline, from the release bundle.
#
#   deploy/docker-engine.sh fetch DIR ARCH   (bundle.sh, on a machine with internet) download the
#                                            pinned static Docker Engine and Compose plugin for ARCH
#                                            (amd64 or arm64) into DIR, checked against the hashes below
#   ./docker-engine.sh install DIR           (install.sh --install-docker, as root, offline) check
#                                            DIR again, install the binaries in /usr/local, the
#                                            systemd units and the docker group, start Docker
#
# Docker Engine (moby) and Compose are Apache 2.0 and may be shipped with the suite; Docker
# Desktop is not used (it needs a paid subscription in companies of 250+ people or US$10M+
# revenue). The static binaries are Docker's own (docs.docker.com/engine/install/binaries); the
# server still needs iptables and a kernel with overlayfs and cgroups, as for any Docker. It runs
# the suite's images and builds none (no buildx): release bundles are built by CI.
set -Eeuo pipefail

DOCKER_VERSION=29.9.2
COMPOSE_VERSION=5.6.1
# sha256 of docker-<version>.tgz (download.docker.com/linux/static/stable/<arch>/) and of
# docker-compose-linux-<arch> (the .sha256 files of the Compose release), checked 2026-10-31.
declare -A SUMS=(
    [docker-amd64]=9ac225999fd5e863f7694c728ef23d480616b1e5639328fa309befd4243d69eb
    [docker-arm64]=873b3e0207857c3b2f28392fb922f3ea6efe37620c16d4d4aaf2fef409c90b73
    [compose-amd64]=47737f4236e6d3ccea7291995203f8f018058783b4c3a9469119811a0b5db8c0
    [compose-arm64]=42cfa75f51ad0ccf290bad37899e0038a8c10a0069e85233ecc1d53e3ff1347d
)

log() { printf '[%s] %s\n' "$(date +%H:%M:%S)" "$*"; }
die() {
    printf '[%s] ERROR: %s\n' "$(date +%H:%M:%S)" "$*" >&2
    exit 1
}
machine() { case "$1" in amd64) echo x86_64 ;; arm64) echo aarch64 ;; *) die "unknown architecture $1" ;; esac; }
check() { # check FILE KEY
    [ -f "$1" ] || die "missing $1"
    [ "$(sha256sum "$1" | cut -c 1-64)" = "${SUMS[$2]}" ] || die "$1 does not match its pinned hash: not installing it."
}

fetch() { # fetch DIR ARCH
    local dir="$1" arch="$2" m
    m="$(machine "$arch")"
    mkdir -p "$dir"
    curl -fsSLo "$dir/docker-$arch.tgz" "https://download.docker.com/linux/static/stable/$m/docker-$DOCKER_VERSION.tgz"
    curl -fsSLo "$dir/docker-compose-$arch" "https://github.com/docker/compose/releases/download/v$COMPOSE_VERSION/docker-compose-linux-$m"
    check "$dir/docker-$arch.tgz" "docker-$arch"
    check "$dir/docker-compose-$arch" "compose-$arch"
    cp "${BASH_SOURCE[0]}" "$dir/docker-engine.sh"
    printf 'DOCKER_VERSION=%s\nCOMPOSE_VERSION=%s\nARCH=%s\n' "$DOCKER_VERSION" "$COMPOSE_VERSION" "$arch" >"$dir/versions.env"
    log "Docker Engine $DOCKER_VERSION and Compose $COMPOSE_VERSION for $arch in $dir"
}

units() { # the systemd units of Docker's own packages, for binaries in /usr/local/bin
    cat >/etc/systemd/system/containerd.service <<'EOF'
[Unit]
Description=containerd container runtime (PlantCraft's offline Docker Engine)
After=network.target local-fs.target
[Service]
ExecStartPre=-/sbin/modprobe overlay
ExecStart=/usr/local/bin/containerd
Type=notify
Delegate=yes
KillMode=process
Restart=always
RestartSec=5
LimitNPROC=infinity
LimitCORE=infinity
TasksMax=infinity
OOMScoreAdjust=-999
[Install]
WantedBy=multi-user.target
EOF
    cat >/etc/systemd/system/docker.socket <<'EOF'
[Unit]
Description=Docker Socket for the API
[Socket]
ListenStream=/run/docker.sock
SocketMode=0660
SocketUser=root
SocketGroup=docker
[Install]
WantedBy=sockets.target
EOF
    cat >/etc/systemd/system/docker.service <<'EOF'
[Unit]
Description=Docker Application Container Engine (PlantCraft's offline Docker Engine)
After=network-online.target containerd.service docker.socket
Wants=network-online.target containerd.service
Requires=docker.socket
[Service]
Type=notify
ExecStart=/usr/local/bin/dockerd -H fd:// --containerd=/run/containerd/containerd.sock
ExecReload=/bin/kill -s HUP $MAINPID
TimeoutStartSec=0
RestartSec=2
Restart=always
LimitNOFILE=infinity
LimitNPROC=infinity
LimitCORE=infinity
TasksMax=infinity
Delegate=yes
KillMode=process
OOMScoreAdjust=-500
[Install]
WantedBy=multi-user.target
EOF
}

install_engine() { # install DIR
    local dir="$1" arch m
    [ "$(id -u)" = 0 ] || die "installing Docker needs root (sudo)."
    if command -v docker >/dev/null 2>&1; then
        log "Docker is already installed ($(docker --version)): nothing to do."
        return 0
    fi
    m="$(uname -m)"
    case "$m" in x86_64 | amd64) arch=amd64 ;; aarch64 | arm64) arch=arm64 ;; *) die "no Docker Engine for $m in this bundle" ;; esac
    check "$dir/docker-$arch.tgz" "docker-$arch"
    check "$dir/docker-compose-$arch" "compose-$arch"
    command -v iptables >/dev/null 2>&1 || die "Docker needs iptables: install the distribution's iptables package first."
    log "Installing Docker Engine $DOCKER_VERSION and Compose $COMPOSE_VERSION in /usr/local"
    tar -xzf "$dir/docker-$arch.tgz" -C /usr/local/bin --strip-components=1
    install -D -m 0755 "$dir/docker-compose-$arch" /usr/local/lib/docker/cli-plugins/docker-compose
    getent group docker >/dev/null || groupadd --system docker
    # The person who ran sudo may use docker without sudo after signing in again.
    if [ -n "${SUDO_USER:-}" ] && [ "$SUDO_USER" != root ] && id "$SUDO_USER" >/dev/null 2>&1; then
        usermod -aG docker "$SUDO_USER"
        log "$SUDO_USER is in the docker group: sign out and in again to use docker without sudo."
    fi
    if command -v systemctl >/dev/null 2>&1 && [ -d /run/systemd/system ]; then
        units
        systemctl daemon-reload
        systemctl enable --now containerd.service docker.socket docker.service
        log "Docker is running and starts with the server (systemctl status docker)."
    else
        log "No systemd here: start Docker with  sudo dockerd &  (and from the server's own start-up scripts)."
    fi
}

case "${1:-}" in
    fetch) [ $# -eq 3 ] || die "usage: $0 fetch DIR ARCH"; fetch "$2" "$3" ;;
    install) [ $# -eq 2 ] || die "usage: $0 install DIR"; install_engine "$2" ;;
    *) sed -n '2,13p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit 2 ;;
esac
