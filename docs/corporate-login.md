# Corporate sign-in

People sign in with their company account instead of an account created in PlantCraft one by
one: from **Active Directory or LDAP** (they type their company username and password on the usual
sign-in page) or through **single sign-on with OpenID Connect** (Keycloak, Microsoft Entra ID,
AD FS, Okta and others: a button on the sign-in page). Their groups in the directory decide their
access level, the apps they open with their role in each, and the groups they belong to here. The
account is created the first time they sign in, with their name, email, job title, sector, phone,
organization and unit read from the directory.

Set it up in **Settings › Corporate sign-in** (admins). Code: `processcraft/directory`, routes
`/api/directory` (admins) and `/api/sso/*` (the sign-in page).

## Safe by default

- **Off** until an admin turns a method on. `PLANTCRAFT_CORPORATE_LOGIN=off` forbids it in an
  installation whatever the settings say.
- It only applies with sign-in on. **The installation's admin account** (the one from the
  environment, `PLANTCRAFT_BASIC_AUTH_USERNAME`) always signs in with its own password, and a
  directory person can never take its name, so a directory that stops answering never locks the
  admins out.
- **LDAP never in clear**: LDAPS or StartTLS only, the server's certificate checked against the
  system's authorities or the company CA pasted in Settings (hostname included). Empty passwords are
  refused before the directory is asked (an "unauthenticated bind" many servers accept). The typed
  name is escaped in every filter. Nothing is ever written to the directory.
- **OIDC**: authorization code flow with PKCE (S256), a `state` against forged callbacks and a
  `nonce` against replayed tokens, kept in the signed session cookie for 10 minutes (any server
  process can finish the sign-in). The ID token's signature is checked against the provider's
  published keys (RS, PS, ES and EdDSA only: never `none` or HMAC), then `iss`, `aud`, `azp`,
  `exp`, `iat` and `nonce`. Claims missing from the ID token come from the user info endpoint, only
  when its `sub` is the same person. The provider's address must be `https://`. The sign-in page
  never shows text taken from the address: the reason of a failure stays in the session.
- **Secrets** (the LDAP service account's password, the OIDC client secret) live in
  `directory-secrets.json` beside the database, mode 600, never in it and never sent back to the
  browser (`PLANTCRAFT_DIRECTORY_SECRETS_FILE` moves it). A saved secret only goes to the server it was
  typed for: a new server address, bind account or provider needs it typed again.
- Wrong passwords count in the same sign-in throttle as local ones (10 failures, 5 minutes).
- Settings changes are in the audit log (`directory.settings`); so is each account the directory
  creates (`user.created`).
- Offline: PlantCraft talks only to the directory and the provider set in Settings.

## The directory is the source of truth

Each sign-in brings the person's access level, apps, app roles and the groups the rules name up
to date (a person in several groups gets the most of each). A change an admin makes by hand lasts
until their next sign-in. What stays in PlantCraft's hands:

- **Turned off here stays off**: a deactivated person is refused whatever the directory says.
- People from the directory **sign in again** after the hours set in Settings (12 by default), and
  their sessions end as soon as their method is turned off, so someone turned off in the
  directory loses access here within the day.
- **People in no mapped group** are refused by default (or get a level the admin chooses; never
  admin).
- An account that already exists here **with a password** is never taken over by a directory
  namesake; one an admin created without a password is adopted on the first sign-in.
- A directory person has no password here (resetting it is refused).
- With "People created here still sign in with their password" off, only company accounts and
  the installation's admin account sign in.

## Rules

A rule names a directory group by its name (CN, or the last part of a Keycloak group path) or by
its full DN (then only that DN matches), and gives: an access level, the apps (every app or a
list) with an optional role in each (viewer or editor), and the groups here its people belong to.
"Check the rules" on the page shows the access someone in given groups would get; the LDAP test
does the same for a real person.

## Testing

`tests/test_corporate_login.py` runs every journey against an in-memory directory (ldap3's mock)
and provider. `tests/test_corporate_login_live.py` runs them against OpenLDAP (LDAPS and StartTLS)
and Keycloak in containers: `dev/corporate-login/README.md`.

## Not yet

SAML 2.0 (most providers that offer SAML also offer OIDC); signing out of the provider when
signing out here (RP-initiated logout); groups synchronised without a sign-in (a scheduled
directory sync).
