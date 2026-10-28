# Running the suite

What an administrator looks after once the suite is installed: its time zone, its health, its
backups and its updates. Every page named here is in PlantCraft, under **Administration**.

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
