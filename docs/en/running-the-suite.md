# Running the suite

What an administrator looks after once the suite is installed: its time zone, its health, its
backups, its updates and the Operations app. Every page named here is in PlantCraft, under
**Administration**, or in Operations.

## Time zone

The suite stores and computes every time in UTC. Screens show them in **Local time**: the
installation's time zone, the same for everyone.

- **Settings › Installation** sets that zone, picked from a list. `install.sh` starts it at the
  server's own zone. Change it when the server keeps another time (a server in UTC at a plant in
  Brazil, for example). Stored times never change, only how they are shown and when the schedules
  saved at local time run.
- Wherever a form asks for a time zone (the backup schedule, a Analytics monitor, the hours an alarm
  may notify, a CSV import), it offers **Local time** first, then **UTC**, then fixed offsets
  (UTC−1 … UTC−12, UTC+1 … UTC+14), and last the cities, for zones with daylight saving.
  A schedule saved at **Local time** follows the installation if its zone changes later.
- Each person chooses in **Preferences** (their menu, at the bottom of the sidebar) whether they
  see Local time, UTC or, when they are elsewhere, their own device's time. That choice is saved
  for their account and is the first one their forms offer.

## System health

**System health** shows every service of the suite with its state, CPU, memory and restarts. The suite
checks itself every 30 seconds; when a part stops, every administrator gets a message in
**Messages** (from "System") and a banner at the top of PlantCraft's pages, and another when it is
back. **Download diagnostic bundle** saves what support needs: versions, each service's state and the
end of its log, and the settings without any secret. Never databases, plant data or keys.

### Certificates

**System health › Certificates** lists the certificates the suite uses, with the date each expires: the
HTTPS one and the Historian's OPC UA connections. Every administrator gets a message 30 days before
one expires and another 7 days before. **Renew** makes a new certificate for the Historian's OPC UA
client; download it and have each OPC UA server trust it, or its connection stops. A server's
certificate is renewed on the server, then accepted again in its source; the HTTPS certificate is
replaced in the `certs/` folder of the installation.

## Backups

The suite backs itself up while it runs, every day at the time in **Schedule** (02:00 Local time
by default), and checks every backup before it counts. It keeps 7 daily, 4 weekly and 3 monthly
backups, and the one taken before the last update.

- **Back up now** takes one at once. **Check again** (the shield in the list) checks one again.
- Once a week (Sunday 03:00 by default) the **restore drill** restores the latest good backup
  into a separate copy of the suite, with no network and no port, starts it, checks it and removes
  it. The running suite is not touched. **Test a restore now** runs it at once.
- **Restore** puts every database, setting and image back as they were in that backup. Type the
  backup's name and your password to confirm. The suite stops for a few minutes; what was there is
  set aside, not deleted, and the suite returns to it by itself if the restore does not come up
  healthy.

From the server, `sudo ./install.sh --backup`, `--list-backups` and `--restore NAME` do the same.

## Updates

An update comes as a signed bundle. On the server, from the new bundle's folder:

```bash
sudo ./install.sh
```

It checks the signature, backs up, updates and checks the new version. When the new version is
not healthy it returns to the previous one by itself. **Updates** shows the installed version, its
release notes and every update with its result.

## Operations

**Operations** sits beside Desk in the app switcher, for administrators and for people with the
**Operations** role (IT, or an integrator's team, without making them administrators).

- **Status**: every app's CPU and memory against its own limit ("86 %, 3.4 of 4 CPUs"), the
  machine's CPU, memory, load and free disk, and the incidents. Each app's **uptime** over 24
  hours, 7 and 30 days leaves out planned maintenance. An administrator plans a **maintenance
  window** (now or later, every app or some, up to 72 hours); while it lasts the watch keeps
  quiet about those apps.
- **The machine and its profile**: suite health names the machine as Docker sees it, the
  **machine profile** that sized the suite (small, medium, large or xlarge) and each service's
  CPU limit beside its use. When the machine fits another profile (more memory added, a profile
  pinned by hand), it names it with the command to apply it on the server, `sudo ./install.sh
  --machine auto`. Nothing is changed from the web.
- **Logs**: every server's log in one list, with period, level, text, request and app filters,
  the most frequent warnings and errors, "Same request in every app" and CSV export.
- **Load alerts**: tells the administrators when an app or the machine stays above a level (CPU
  or memory at 80 % warning and 95 % critical, or errors logged a minute) for 5 minutes. The
  levels are changed on the page.
- **Requests**: anyone asks for help with **Ask for help** in their menu, in every app, with the
  app and page already filled in; a log record and an open incident have **Open a request**.
  Each queue can have working hours, and each priority a first-answer and a resolution target;
  the clocks run only in working hours and stop while a request is Blocked. Requests shows the
  time left or how late. Time is logged on any request or action, billable or not.
- **Partners**: the companies working at the plant (groups of kind **Company**), each with its
  coordinator, teams, a sponsor at the plant and a last day of access, after which nobody in it
  signs in. Partners shows each company's people, access, open requests and the month's hours.
  After a month ends, an administrator or the sponsor approves its hours, and the month is
  closed. A sponsor without the Operations role sees only Requests and Partners, for their own
  companies.
- **Temporary support access**: an administrator gives a person Operations for up to 72 hours,
  for a reason. It ends by itself or with **End now**, the person is told, and both are in the
  audit log.

## From the server

These run on the server, from the install folder, as root:

- `./install.sh --security-check`: 36 checks of the installation, with a score; `--format json`,
  `junit`, `sarif` or an evidence report for an audit. Exceptions can be recorded with an end
  date.
- `./install.sh --rotate-admin-password`: a new password for the emergency administrator, shown
  once. The security check fails when that password is older than 90 days.
- `./install.sh --machine small|medium|large|xlarge|auto`: sizes every container from one choice.
- `./install.sh --show-config`: the installation file (`/etc/plantcraft/installation.conf`) and
  whether it is applied. Its values win over the command line and `.env`.

The bundle also carries a Zabbix template (`monitoring/plantcraft_zabbix_agent.yaml`, Zabbix 7.0
and later) that watches the machine, the free disk and every service with the same levels as
the load alerts.
