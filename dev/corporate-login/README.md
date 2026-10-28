# A test company directory and sign-in provider

For the live tests of corporate sign-in (`docs/corporate-login.md`): OpenLDAP, reached over LDAPS
and StartTLS, and Keycloak (OpenID Connect), both with certificates from a throwaway test CA.
Everything runs on this machine; nothing reaches the internet once the two images are pulled.

```sh
dev/corporate-login/make-certs.sh                  # the test CA and the server certificate
echo "127.0.0.1 ldap.plant.test sso.plant.test" | sudo tee -a /etc/hosts
docker compose -f dev/corporate-login/compose.yaml up -d
PLANTCRAFT_LIVE_DIRECTORY=1 python -m pytest tests/test_corporate_login_live.py
docker compose -f dev/corporate-login/compose.yaml down
```

Behind a proxy, set `NO_PROXY=plant.test` so the test traffic stays local. Where Docker Hub or
Quay are out of reach, point `OPENLDAP_IMAGE` and `KEYCLOAK_IMAGE` at a mirror of the same images.

| Who | Where | Password | Groups |
|---|---|---|---|
| ana.lima | OpenLDAP | `ana-directory-pass` | pc-engineers, pc-admins |
| carlos.menezes | OpenLDAP | `carlos-directory-pass` | pc-operators |
| outsider | OpenLDAP and Keycloak | `outsider-directory-pass`, `outsider-sso-pass` | none |
| uid=reader (service account) | OpenLDAP | `reader-service-pass` | reads the directory |
| marina.costa | Keycloak realm `plant` | `marina-sso-pass` | pc-engineers |
| rafael.souza | Keycloak realm `plant` | `rafael-sso-pass` | pc-operators |

Keycloak's client is `processcraft`, secret `processcraft-test-secret`, with a `groups` claim.
To try it in the browser, run PlantCraft with sign-in on at `http://127.0.0.1:8000`, and in
Setup › Corporate sign-in paste `certs/ca.crt` as the CA certificate of both.
