# syntax=docker/dockerfile:1.7
#
# PlantCraft proxy: Caddy with the suite's configuration baked in (deploy/compose.yaml,
# service `proxy`). Built by `make image` from the deploy/proxy folder.
#
# The upstream binary carries a file capability (cap_net_bind_service) so that it may bind
# port 443; a process with no capabilities and no-new-privileges cannot even start it. The
# copy below drops that attribute: the proxy listens on 8443 and needs no capability at all.

ARG CADDY_IMAGE=caddy:2.11.6-alpine@sha256:d44355d3c2149dc580ce2cac735955d1c08d3d00882c30489c241aa51a5c10d9

FROM ${CADDY_IMAGE}

# apk upgrade: the base image's Alpine packages (curl, brotli) get their fixes at build (trivy, D13).
RUN apk upgrade --no-cache \
    && cp /usr/bin/caddy /tmp/caddy \
    && mv /tmp/caddy /usr/bin/caddy \
    && chmod 0755 /usr/bin/caddy \
    && addgroup -S -g 10003 proxy \
    && adduser -S -D -H -u 10003 -G proxy -h /data -s /sbin/nologin proxy \
    && mkdir -p /data /config /certs \
    && chown 10003:10003 /data /config

COPY --chmod=0644 Caddyfile /etc/caddy/Caddyfile
COPY --chmod=0755 entrypoint.sh /usr/local/bin/processcraft-proxy

# No PLANTCRAFT_HOSTNAME default here: the entrypoint falls back to the name before the rename,
# then to localhost.
ENV XDG_DATA_HOME=/data \
    XDG_CONFIG_HOME=/config

USER 10003:10003

EXPOSE 8443

HEALTHCHECK --interval=15s --timeout=5s --start-period=20s --retries=5 \
    CMD ["wget", "-q", "-O", "/dev/null", "http://127.0.0.1:8081/healthz"]

ENTRYPOINT ["/usr/local/bin/processcraft-proxy"]

# Last, so a new commit or build time changes only the labels: the layers stay cached and
# identical, and suite-deploy (ci/macmini) leaves a container whose content did not change.
ARG VERSION=0.0.0
ARG REVISION=unknown
ARG CREATED=unknown

LABEL org.opencontainers.image.title="processcraft-proxy" \
      org.opencontainers.image.description="PlantCraft suite HTTPS entry point (Caddy)" \
      org.opencontainers.image.version="${VERSION}" \
      org.opencontainers.image.revision="${REVISION}" \
      org.opencontainers.image.created="${CREATED}" \
      org.opencontainers.image.licenses="Apache-2.0" \
      org.opencontainers.image.source="https://github.com/PlantCraft/PlantCraft" \
      org.opencontainers.image.base.name="caddy:2.11.2-alpine"
