# Public demo

An installation left open on the internet so anyone can see what the suite does in a few
minutes: `install.sh --public-demo` installs the demo plant, runs `plantcraft demo seed` (one
refinery story, already in use by its team: results, alarms, actions, conversations, assistant
chats, dashboards, notebooks) and sets `PLANTCRAFT_PUBLIC_DEMO=true`. Never turn it on for an
installation holding real plant data.

## A visit

The sign-in page of a public demo has one way in (owner, 2026-10-28: more than one scares a
visitor): the title **Demo**, one line saying what it is, **Enter the demo**, and a plain **Sign in**
button that opens the team's own sign-in form (and single sign-on), so a visitor sees there is a
sign-in without facing a form; `/?account` opens the form at once. Each visit
is the read-only visitor account `demo`, in one of a few places at once:

- a free place is taken at once; when every place is taken, the page shows the visitor's number
  in line and about how long until a place frees, and asks again every 5 s (a browser silent for
  30 s leaves the line; the first in line takes the next place);
- a visit lasts while it is used, with no clock on screen: it ends `PLANTCRAFT_PUBLIC_DEMO_MINUTES`
  (30) after its last use (a click, a key, a scroll, in the apps too), so a tab forgotten for days
  does not hold a place. Only the last 5 minutes show a note, with **Keep exploring** and
  **Leave** (which frees the place);
- a visitor who has not used the page for `PLANTCRAFT_PUBLIC_DEMO_IDLE_MINUTES` (5) gives up
  their place, but only to someone waiting;
- no cap per address: behind the proxy and the tunnel every visitor can seem to come from one
  (the per-visit request limits still hold);
- from outside (through the proxy) the visitor account signs in only this way, never with its
  password; inside the network the password still works, and `plantcraft demo seed` uses it.

When the visit ends, the browser is back on the sign-in page, which thanks the visitor and offers
to enter again. The places are in the database (`demo_visits`, `demo_line`), so every server
process sees the same ones (`processcraft/auth/demo_visits.py`).

Each visit also leaves a line in `demo_visit_log` (when it started, how long it was used, how long
its visitor waited in line; no address) and the pages it had in front in `demo_visit_pages` (paths
only, an object's id as `:id`), kept 400 days. `GET /api/demo/stats` gives them, with the places
taken now, to whoever holds `PLANTCRAFT_PUBLIC_DEMO_STATS_KEY` as a bearer token (unset: a 404);
the site's private `/stats` page reads it (`site/README.md`).

## Guides by role

A demo convinces when it shows each visitor what matters to their job, in their words (owner,
2026-10-27). The way in no longer asks for the role (2026-10-28, one button only): a visit opens
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
- **Read the team's assistant chats**, never ask one: language models are only for the people an
  administrator created (editors and administrators). With the model off, the assistant's panel
  still lists the visitor's chats and those shared with them, and opens each one with its steps
  and sources: that is how a visitor learns what the assistant does.
- **Nothing a visitor does reaches another visitor**: no messages, no actions, no audit entries.

## Keeping the demo fast

A demo is only convincing when it answers quickly, so a visit is held to a share of the suite:

| Setting | Default | What it limits |
|---|---|---|
| `PLANTCRAFT_PUBLIC_DEMO_SEATS` | 10 | Visits at once |
| `PLANTCRAFT_PUBLIC_DEMO_MINUTES` | 30 | A visit ends this long after it was last used |
| `PLANTCRAFT_PUBLIC_DEMO_IDLE_MINUTES` | 5 | Unused this long, a visit gives way to someone waiting |
| `PLANTCRAFT_PUBLIC_DEMO_QUERIES` | 4 | A visit's requests in flight in each app |
| `PLANTCRAFT_PUBLIC_DEMO_QUERIES_TOTAL` | 8 | All visits' requests in flight in each app (per process) |
| `PLANTCRAFT_PUBLIC_DEMO_RATE` | 600 | Requests a minute to PlantCraft, per visit (per address before a visit) |

The two query limits travel in the visit's token (`demo` claim) and are applied by every app
(`plantcraft_sdk.server.demo.DemoVisitLimit`, added by `web.mount`): a request over the limit
waits its turn, up to 30 s, then answers 429 "The demo is busy". A visit's tokens live two
minutes and the frame renews them every 30 s, so a visit that ended loses the apps within about
two minutes even in a tab left open. The series reads of a visit through API v1 count against
the visit's own budget (`processcraft.api.usage`), not one shared by every visitor.

The defaults come from the multi-user load test (`ci/bench/load_users.py`, 2026-10-27, 4 vCPU and
16 GB, the whole suite, with that day's speed fixes): 10 people kept a screen's p95 at 1.0 s and 50 at 1.6 s, so 10 places are
comfortably safe on such a machine. A screen fires about 15 calls at once, so 4 in flight per
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
