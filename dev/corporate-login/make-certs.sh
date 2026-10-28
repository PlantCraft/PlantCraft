#!/bin/sh
# A throwaway certificate authority and one server certificate for the test directory
# (ldap.plant.test) and the test sign-in provider (sso.plant.test). For tests only.
set -eu
cd "$(dirname "$0")"
mkdir -p certs
cd certs
[ -f ca.crt ] && [ -f server.crt ] && exit 0
# Python 3.13 checks certificates strictly (X.509 key usage and key identifiers), as it should.
openssl req -x509 -newkey rsa:2048 -nodes -days 30 -subj "/CN=PlantCraft test CA" \
  -addext "basicConstraints=critical,CA:TRUE" -addext "keyUsage=critical,keyCertSign,cRLSign" \
  -addext "subjectKeyIdentifier=hash" -keyout ca.key -out ca.crt 2>/dev/null
openssl req -newkey rsa:2048 -nodes -subj "/CN=ldap.plant.test" \
  -keyout server.key -out server.csr 2>/dev/null
printf 'subjectAltName=DNS:ldap.plant.test,DNS:sso.plant.test,DNS:localhost,IP:127.0.0.1\nextendedKeyUsage=serverAuth\nkeyUsage=critical,digitalSignature,keyEncipherment\nauthorityKeyIdentifier=keyid\nsubjectKeyIdentifier=hash\n' > san.ext
openssl x509 -req -in server.csr -CA ca.crt -CAkey ca.key -CAcreateserial -days 30 \
  -extfile san.ext -out server.crt 2>/dev/null
# The containers run as unprivileged users: they must read the key.
chmod 644 server.key server.crt ca.crt
