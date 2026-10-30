# Notifications

> **Added:** 2026-10-22

Apps tell people about something that needs them (an alarm raised, later an action assigned)
through the platform, never on their own: PlantCraft knows who is in which group, how to reach
them and what they allow.

## Delivery

1. An app's service token calls `POST /api/v1/notifications` with recipients (`user:<username>`,
   `group:<id>`), a title, a text, a priority (`critical`, `high`, `medium`, `low`), a link back
   (a path of the suite, `/alarm/...`) and whether email is wanted ([api-v1.md](api-v1.md)).
2. Groups are expanded to their active members; each person receives one message in their
   conversation with the app (its robot user carries the app's name, "Alarms"). Messages lists it
   under **Notifications**, beside the chats, and the suite's messages button
   counts it.
   - **One thread per key.** The same app and `key` (`alarm:12:3`: fired, reminded, escalated,
     cleared) is one entry with its history, unread again on each new send.
   - **Read like an email inbox.** Unread in bold; filters All, Unread, Favorites, Alarms,
     Actions, Runs and Done, and a search; opening an entry marks it seen. Each row and the open
     entry carry the person's own buttons: one that turns seen into not seen
     and back, a star (a favorite keeps its star when the thread gets a new event) and the
     **check**, which marks it done: out of the list until something new happens to it. **Open**
     leaves a small bar on the page it opens (an action, an alarm) with the same check, so it is
     marked done where it is handled. Read and done marks are kept 45 days; the list shows 30.
   - **The person's own marks.** `PUT /api/me/marks` with `{"key", "mark": "star" | "unread",
     "on"}`: a notification's key, `conversation:<id>` or `chat:<id>` (an assistant chat) as a
     favorite, and a conversation or an assistant chat unread again until it is opened. On a public
     demo each visit keeps its own marks (`demo#visit:<id>`, gone a day later), what it read in a
     conversation too (`conversation:<id>@<message id>`, never the shared account's read mark):
     the next visitor starts from the demo as seeded. A visit starts with the newest 20
     notifications unread (`DEMO_UNREAD`) and the rest read; the seed leaves the newest message
     of 4 conversations unread (`VISITOR_UNREAD`).
   - **Category and buttons.** `category` (`alarm`, `run`, `action`, `info`) chooses the icon and
     the filter; `actions` adds up to three buttons beside **Open**: `{"label": "Open the rule",
     "href": "/alarm/rules/4"}` opens a page, `{"label": "Acknowledge", "href":
     "/alarm/api/alarms/12/ack", "method": "POST"}` runs the call in the app as the person
     (under the app's own prefix; 2026-10-26).
   - **Settled for everyone.** `POST /api/v1/notifications/resolve` with the key (an alarm
     acknowledged or cleared) takes the thread off everyone's count and shows who settled it.
   - **At once.** A critical or high one pops up in any app the person has open, with its buttons.
     The rules of all four quick buttons: [quick-access.md](quick-access.md).
   - **Also listed:** changes other people made to the person's actions and their groups', and
     alarms and warnings on the assets they follow (`GET /api/notifications`,
     `POST /api/notifications/marks` with `{"keys", "state": "read" | "archived" | null}`, null
     being not seen again).
3. When email is wanted, the administrator set up a mail server and the person allows it, an
   email is queued.

## Email (optional)

- **Settings › Email** (`/setup/email`): server, port, security (STARTTLS, TLS or none), user,
  password and sender, with a test email. Off by default: the suite installs offline and the
  messages always arrive. It points at the company's own relay; PlantCraft connects to nothing
  else.
- The password is kept in `mail-secret.json` beside the database (mode 600,
  `PLANTCRAFT_MAIL_SECRET_FILE` to move it), never returned by the API, never logged.
- The outbox is sent every 20 s by a background worker (`PLANTCRAFT_MAIL_OUTBOX=false` turns
  it off); a failing server keeps the email waiting and retries up to six times. Settings shows the
  counts and the last error.
- At most 20 emails an hour reach one person; what waits beyond leaves in one digest, the most
  urgent first. Several notifications waiting for the same person always go as one digest.
- Each person chooses in their profile (`/people/me`): email on or off, and from which priority
  (high and above by default). The address is the profile's email.

The code is `plantcraft/notify` (layer 2); `tests/test_groups_and_notifications.py` holds it.
