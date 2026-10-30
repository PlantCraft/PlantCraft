#!/bin/sh
# Starts Caddy with the client's certificate when certs/cert.pem and certs/key.pem exist,
# otherwise with Caddy's local certificate authority. Names come from PLANTCRAFT_HOSTNAME
# (separated by spaces or commas), for example "plantcraft.plant.example 10.0.0.5".
# The names before the rename to PlantCraft (PROCESSCRAFT_HOSTNAME)
# are still read: a compose file written by an older release passes them.
set -eu
PLANTCRAFT_HOSTNAME="${PLANTCRAFT_HOSTNAME:-${PROCESSCRAFT_HOSTNAME:-localhost}}"
PLANTCRAFT_TRUSTED_PROXIES="${PLANTCRAFT_TRUSTED_PROXIES:-${PROCESSCRAFT_TRUSTED_PROXIES:-}}"

names=$(printf '%s' "$PLANTCRAFT_HOSTNAME" | tr ',' ' ')
sites=""
first=""
address=""
for name in $names; do
    sites="${sites:+$sites, }https://${name}:8443"
    first="${first:-$name}"
    # Browsers send no SNI for an IP address, and behind Docker's published port Caddy sees the
    # container's own address, not the one typed: the default SNI picks the IP's certificate.
    case "$name" in
        *[!0-9.]* | "") ;;
        *) address="${address:-$name}" ;;
    esac
done
export PLANTCRAFT_SITES="$sites"
export PLANTCRAFT_DEFAULT_SNI="${address:-$first}"

# PLANTCRAFT_TRUSTED_PROXIES: the addresses (CIDR, separated by spaces or commas) of a tunnel or
# CDN in front of the proxy, for example the Docker gateway that cloudflared on the host connects
# through. From them alone the visitor's address is read from CF-Connecting-IP or X-Forwarded-For;
# without it every visitor of a public demo behind a tunnel would share one address (one place
# limit, one rate limit). Only addresses: anything else stops the proxy instead of reaching Caddy.
trusted=$(printf '%s' "$PLANTCRAFT_TRUSTED_PROXIES" | tr ',' ' ')
export PLANTCRAFT_TRUSTED_PROXIES_LINE=""
export PLANTCRAFT_CLIENT_IP_HEADERS_LINE=""
if [ -n "$(printf '%s' "$trusted" | tr -d ' ')" ]; then
    case "$trusted" in
        *[!0-9A-Fa-f.:/\ ]*)
            echo "proxy: PLANTCRAFT_TRUSTED_PROXIES must list addresses or CIDR ranges only: $trusted" >&2
            exit 1
            ;;
    esac
    export PLANTCRAFT_TRUSTED_PROXIES_LINE="trusted_proxies static $trusted"
    export PLANTCRAFT_CLIENT_IP_HEADERS_LINE="client_ip_headers CF-Connecting-IP X-Forwarded-For"
    echo "proxy: visitors' addresses come from CF-Connecting-IP or X-Forwarded-For when sent by: $trusted"
fi

if [ -r /certs/cert.pem ] && [ -r /certs/key.pem ]; then
    export PLANTCRAFT_TLS="/certs/cert.pem /certs/key.pem"
    echo "proxy: HTTPS with the certificate in certs/cert.pem for: $names"
else
    if [ -e /certs/cert.pem ] || [ -e /certs/key.pem ]; then
        echo "proxy: certs/cert.pem or certs/key.pem is missing or unreadable (uid $(id -u)); falling back to the local CA" >&2
    fi
    export PLANTCRAFT_TLS="internal"
    echo "proxy: HTTPS with the local CA for: $names (root certificate: data/proxy/caddy/pki/authorities/local/root.crt)"
fi

exec caddy run --config /etc/caddy/Caddyfile --adapter caddyfile
