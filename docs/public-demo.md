# Public demo

An installation left open on the internet so anyone can see what the suite does in a few
minutes: `install.sh --public-demo` installs the demo plant, runs `plantcraft demo seed` (one
refinery story, already in use by its team: results, alarms, actions, conversations, assistant
chats, dashboards, notebooks) and sets `PLANTCRAFT_PUBLIC_DEMO=true`. Never turn it on for an
installation holding real plant data.

## A visit

The sign-in page of a public demo has one way in: the title **Demo**, one line saying what it is, **Enter the demo**, and a plain **Sign in**
button that opens the team's own sign-in form (and single sign-on), so a visitor sees there is a
sign-in without facing a form; `/?account` opens the form at once. Each visit
is the read-only visitor account `demo`, in one of a few places at once:

- a free place is taken at once; when every place is taken, the page shows the visitor's number
  in line and about how long until a place frees, and asks again every 5 s (a browser silent for
  30 s leaves the line; the first in line takes the next place);
- a visit lasts `PLANTCRAFT_PUBLIC_DEMO_MINUTES` (30) from the moment it starts, with its clock
  always on screen (bottom center, with **Leave**); the last 2 minutes say the visit is ending
  and its changes are discarded;
- a visit left unused (no click, key, scroll or touch, in the apps too) for
  `PLANTCRAFT_PUBLIC_DEMO_IDLE_MINUTES` (5) ends, someone waiting or not, so a tab forgotten for
  days never holds a place; its last minute asks "Still there?" with **Keep exploring**;
- no cap per address: behind the proxy and the tunnel every visitor can seem to come from one
  (the per-visit request limits still hold);
- from outside (through the proxy) the visitor account signs in only this way, never with its
  password; inside the network the password still works, and `plantcraft demo seed` uses it.
  `install.sh` keeps that password in `data/public-demo-password` (mode 600), never in `.env`:
  random on a new installation, and moved there from an older installation's `.env` unchanged.

When the visit ends, the browser is back on the sign-in page, which thanks the visitor and offers
to enter again. The places are in the database (`demo_visits`, `demo_line`), so every server
process sees the same ones (`plantcraft/auth/demo_visits.py`).

Each visit also leaves a line in `demo_visit_log` (when it started, how long it was used, how long
its visitor waited in line; no address) and the pages it had in front in `demo_visit_pages` (paths
only, an object's id as `:id`), kept 400 days. `GET /api/demo/stats` gives them, with the places
taken now, to whoever holds `PLANTCRAFT_PUBLIC_DEMO_STATS_KEY` as a bearer token (unset: a 404);
the site's private `/stats` page reads it (`site/README.md`).

## Updating the demo

An update stops the suite for a few minutes, and a visitor who meets an error page thinks the
product is broken. So the visits are told first:

- `plantcraft demo update-notice --in 2` (inside the PlantCraft container; `vm.sh demo` runs it
  before it updates, `UPDATE_NOTICE_MINUTES`) puts a strip across the top of every visit: "The
  demo will be updated to a new version in 1:59...". No new visit starts; the sign-in page says
  the demo is being updated and that nothing is broken.
- When the time comes every visit ends, and its browser goes to
  `PLANTCRAFT_PUBLIC_DEMO_UPDATING_URL` (the site's `/demo-updating`; without it, the sign-in
  page). The site does not restart with the demo: its page says the demo is being updated, asks
  the site's `/api/demo/ready` every 10 s (the demo's stats, with no update under way), and opens
  the demo again once it is back.
- `plantcraft demo update-notice --clear` (`vm.sh demo` runs it after the update) lets visits
  start again; a notice nobody cleared is forgotten 30 minutes after it was due.
- A page of PlantCraft asked for while it restarts gets the proxy's short "PlantCraft is
  restarting" page, which opens again by itself, instead of a bare 502 (any installation).

## Guides by role

A demo convinces when it shows each visitor what matters to their job, in their words. The way in no longer asks for the role (2026-10-28, one button only): a visit opens
with the platform's tour (Desk, its quick buttons, then PlantCraft), whose last step points to
**Guided demo by role** in the menu under the visitor's name: control room operator, process
engineer, control and instrumentation engineer, maintenance and reliability, plant or area
manager, IT, OT and security. A role starts its guide: a card at the bottom right, above every
app, that walks the visitor through five to seven screens across the suite (the operator's
process displays, alarms and wall screen; the manager's dashboard, weekly reports and alarm
performance; IT's read-only sources, health and access...), each with a few lines on why it
matters to them. **Next** opens the stop's page; the visitor may wander from there, fold the
guide away, take **Another role**, or close it. While a guide is on, the apps' own tours wait.

- The guides are in `frontend/src/demoGuides.ts` (texts in English, through `t()`). A stop opens
  a fixed page (`/alarm/performance`) or an object of the story by name ("Plant overview",
  "DOC-MH-001"); `plantcraft demo seed` writes the page each name opens on this installation
  (`demo_guide_links`, read by `GET /api/demo/guides`), and a name not there opens its list.
- The role a visitor picked is in the visit's audit entry (`session.sign_in`, `guide`): which
  people the demo interests.
- On any installation where the demo story was seeded, the menu under the person's name has
  **Guided demo by role**, so the guides can be shown without a public demo.

## What a visitor may do

- **Look at everything and try the editors.** The apps show their editors to a visit
  (`/api/me` says `can_edit`), but the visitor is still a viewer: saving, running a test or any
  other change answers 403 "This is a public demo: you can try everything, but nothing is saved."
  In PlantCraft's own pages a visitor reads; they may only sign out and mark what they read.
- **Read the team's assistant chats**; by default never ask one: language models are only for the
  people an administrator created (editors and administrators). With the model off, the assistant's panel
  still lists the visitor's chats and those shared with them, and opens each one with its steps
  and sources: that is how a visitor learns what the assistant does.
- **Ask the assistant, when the owner turns it on** (`PLANTCRAFT_PUBLIC_DEMO_LLM=on`, off by
  default; `plantcraft/assistant_chat/demo.py`). Each visit then asks the installation's assistant
  model, in chats of its own (owned by `demo#visit:<id>`, never shown to another visit, deleted
  7 days after their last message), and it only asks: no card that creates, no specialists, no
  works that create, 4 rounds of tool calls and 200 signal reads per visit. The limits, each a
  `PLANTCRAFT_PUBLIC_DEMO_LLM_*` setting:

  | Setting | Default | What |
  |---|---|---|
  | `_QUESTIONS` | 10 | Questions per visit (`GET /api/assistant` says how many are left: `visit.left`) |
  | `_PER_MINUTE` | 6 | Questions per client address per minute |
  | `_PER_ADDRESS` | 30 | Questions per client address per plant day |
  | `_DAILY` | 600 | Questions of all visits per plant day |
  | `_MAX_TEXT` | 1200 | Characters of one question |
  | `_ROUNDS` | 4 | Rounds of tool calls before the model answers |
  | `_READS` | 200 | Signal reads per visit |
  | `_KEEP_DAYS` | 7 | Days a visit's chats are kept, to read what visitors asked |
  | `_HISTORY` | 12 | Last turns of the chat sent with a question |
  | `_TOOL_CALLS` | 16 | Tool calls in one answer |
  | `_MAX_ANSWER` | 4000 | Characters of one answer |

  A visit's answer never points outside the suite: images, raw HTML and links or addresses of
  other sites are taken out on the server, whatever the model was led to write.

  The counts are kept in `assistant_demo_questions`, with the tokens each answer spent, so a
  restart does not reset them; `GET /api/demo/stats` adds today's (`assistant`: questions,
  answered, failed, input, cached, output and reasoning tokens). Give the demo its own provider
  key with a monthly spending cap at the provider: it is the limit that holds whatever happens
  here. `PLANTCRAFT_PUBLIC_DEMO_LLM=off` and a restart turn it off.
- **Nothing a visitor does reaches another visitor**: no messages, no actions, no audit entries.

## Keeping the demo fast

A demo is only convincing when it answers quickly, so a visit is held to a share of the suite:

| Setting | Default | What it limits |
|---|---|---|
| `PLANTCRAFT_PUBLIC_DEMO_SEATS` | 30 | Visits at once |
| `PLANTCRAFT_PUBLIC_DEMO_MINUTES` | 30 | A visit lasts this long from its start (its clock) |
| `PLANTCRAFT_PUBLIC_DEMO_IDLE_MINUTES` | 5 | Unused this long, a visit ends |
| `PLANTCRAFT_PUBLIC_DEMO_QUERIES` | 4 | A visit's requests in flight in each app |
| `PLANTCRAFT_PUBLIC_DEMO_QUERIES_TOTAL` | 8 | All visits' requests in flight in each app (per process) |
| `PLANTCRAFT_PUBLIC_DEMO_RATE` | 600 | Requests a minute to PlantCraft, per visit (per address before a visit) |

The two query limits travel in the visit's token (`demo` claim) and are applied by every app
(`plantcraft_sdk.server.demo.DemoVisitLimit`, added by `web.mount`): a request over the limit
waits its turn, up to 30 s, then answers 429 "The demo is busy". A visit's tokens live two
minutes and the frame renews them every 30 s, so a visit that ended loses the apps within about
two minutes even in a tab left open. The series reads of a visit through API v1 count against
the visit's own budget (`plantcraft.api.usage`), not one shared by every visitor.

The defaults come from the multi-user load test (`ci/bench/load_users.py`, 2026-10-27, 4 vCPU and
16 GB, the whole suite, with that day's speed fixes): 10 people kept a screen's p95 at 1.0 s and 50 at 1.6 s, so 10 places were
comfortably safe on such a machine; 30 (the default since 2026-11-01) stay well under the 50
measured. A screen fires about 15 calls at once, so 4 in flight per
visit keeps it quick; with 10 places, 8 per app process holds the heaviest reads (dashboards and
reports over 30 days) from piling up. Details in [requirements.md](requirements.md).

## On a cloud VM

PlantCraft's own public demo, with the site and its chat, runs on one small cloud VM that holds
simulated data only; no plant installation ever connects to it. `deploy/cloud/` sets it up:

```bash
# From a clone (once the VM exists, Ubuntu 22.04 or 24.04, amd64 or arm64, 4 vCPU and 16 GB or more):
deploy/cloud/push-to-vm.sh ubuntu@<vm address> -i <ssh key>   # copies main, runs vm.sh all
# On the VM, once:
sudo /opt/plantcraft-src/deploy/cloud/vm.sh tunnel     # the Cloudflare Tunnel's token
#   or: vm.sh tunnel-login   one Cloudflare sign-in link; makes the tunnel, DNS names and routes below
sudo /opt/plantcraft-src/deploy/cloud/vm.sh chat-key   # the site chat's model key
```

The VM builds the bundle itself, natively for its processor, and installs it with
`--public-demo`. Nothing on it listens on the internet: the suite is published on `127.0.0.1:443`
only (`PLANTCRAFT_BIND_ADDRESS`), the site on `127.0.0.1:8090`, and a Cloudflare Tunnel
(`cloudflared`, an outbound connection) brings visitors in. In the tunnel's public hostnames:

| Hostname | Service | |
|---|---|---|
| `plantcraft.io` | `http://127.0.0.1:8090` | the site and its chat |
| `demo.plantcraft.io` | `https://127.0.0.1:443` | TLS: *No TLS Verify* on, *Origin Server Name* `demo.plantcraft.io` (the suite's local CA) |

**The visitor's address.** Through a tunnel every request reaches the proxy from the same Docker
gateway, so every visitor would share one address: two places in the demo for everyone, one rate
limit. `PLANTCRAFT_TRUSTED_PROXIES` (CIDR, comma separated; `vm.sh demo` sets it to the
gateways of the proxy's networks) makes the proxy read the visitor's address from
`CF-Connecting-IP` (or `X-Forwarded-For`) when, and only when, the request comes from those
addresses. Leave it empty on a plant's network, and set it only with
`PLANTCRAFT_BIND_ADDRESS=127.0.0.1`, so that nothing but the tunnel on the same host can send
those headers. The site's chat reads the same header with `SITE_TRUST_PROXY=cloudflare`.

`vm.sh site` builds the site with `--noindex` (search engines kept away) until `LAUNCHED=1` is
set in `/etc/plantcraft-site/vm.env`; `vm.sh demo` again updates the suite from a newer push;
`vm.sh status` shows what runs. Contact requests: `/var/lib/plantcraft-site/contacts.jsonl` and
`SITE_CONTACT_WEBHOOK` in `/etc/plantcraft-site/site.env`. Visits, chat questions and contacts:
`https://plantcraft.io/stats`, with the password `vm.sh stats-password` prints (`vm.sh site` and
`vm.sh demo` share the demo's stats key through `/etc/plantcraft-site/demo-stats-key`).

**Watching it live.** `vm.sh site` also starts `plantcraft-watch` (`site/sitechat/health.py`, root,
every 30 s): the machine's CPU, memory, disk and load, every container (running, healthy,
restarts, its CPU and memory), `cloudflared` and the site, the answer of the site and of the
demo from the VM and through Cloudflare (code and time), and the tunnel's requests and 5xx
answers (cloudflared's own metrics). `/stats` shows it on top as *Server now*, with the last two
hours and the last alerts; `/stats/now.json` gives the same to a script. When something stays
wrong (a page not answering, a container down, unhealthy or restarted, a unit stopped, under 10%
of the disk or 8% of the memory free, the CPU over 90% for 5 minutes, over 5% of answers 5xx)
it pushes once to an [ntfy](https://ntfy.sh) topic, and once more when it is back:
`vm.sh alerts` prints the topic to subscribe to in the ntfy app and sends a test
(`WATCH_EMAIL` in `/etc/plantcraft-site/watch.env` also mails each alert). The alerts hold
service names and numbers only, never a visitor's data. A VM that is gone cannot say so: run
`deploy/cloud/outside-watch.sh install <topic url>` on another machine (the Mac mini), which
opens both pages every minute and pushes to the same topic after 3 misses in a row.
