Put the client's HTTPS certificate here, in PEM format:

- `cert.pem`: the server certificate followed by any intermediate certificates;
- `key.pem`: its private key (not encrypted).

Then run `./install.sh` again: it sets the owner and permissions the proxy needs and restarts it.
Without these files the proxy uses its own local certificate authority
(`data/proxy/caddy/pki/authorities/local/root.crt`). See `docs/install-offline.md`, section 6.
