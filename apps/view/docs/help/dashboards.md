# Dashboards

A dashboard is a screen of panels over the plant's signals and assets, read from PlantCraft.
Dashboards live in folders; a folder says who sees and who edits its dashboards.

- **New dashboard** asks for a name, a folder and what to start from: an empty grid, a template
  built from the plant's assets (a loop detail, a unit overview) or a file exported from View.
  The editor opens with it; nothing is saved until you press **Save** (Cancel leaves no trace).
- **Edit** opens the dashboard for changes: add, change, drag, resize and remove panels, then **Save**. If
  someone else saved it meanwhile, Dashboards asks before replacing their version.
- **Refresh** reads the panels again every 15 s to 5 min, or only when you ask.
- **Full screen** hides everything but the panels, for a control room wall.
- **Time** sets one window for every panel (or each panel keeps its own). The address in the
  browser keeps the page, the variables (`?var-loop=fic-101`), the window and full screen, so a
  bookmark opens the same view.

## Variables

Variables are the pickers at the top of a dashboard (Config › Variables), as in Grafana. One
dashboard then serves every asset of a kind:

| Type | Offers |
|---|---|
| Asset | The assets of a kind (every loop, every pump); under a **parent** variable, only the assets under the ones picked there |
| Custom | A list you write (`PV, SP, OP` or `north, south`) |
| Interval | Time windows (`1h, 8h, 24h`), for panels that use `${period}` as their window |

A variable can take **several values** and offer **All**. Panels use it as `${name}` in a signal
line (Variable mode, or inside a signal name: `FIC-${unit}.PV`), a title, a note or a window. A panel with **Repeat** is drawn once per value
picked, side by side or one under another; while editing it shows once. A picker with no
options says so instead of showing empty panels. Dashboards made with the old **Asset** picker
open with it as their first variable.

## Pages

A dashboard can have up to 10 pages, shown as tabs at the top (a dashboard with one page shows
no tabs). While editing, **Add page** adds one; the page's name, the arrows and the bin next to it
rename, move and remove the page shown (removing a page removes its panels). A panel's **Page**, in
the panel editor, moves it to another page. The asset, the time window and the refresh are the
dashboard's: they stay when you change page. Only the page shown reads data.

**Turn pages in full screen** (Config › Time, with two or more pages) shows the next page every 30 s,
1 min or 5 min in full screen and on public links: a control room screen goes through every page.

## Folders

The list shows the dashboards by folder; **General** holds those outside any folder, and
everyone with access to View sees them. **New folder** (editors) names a folder and who may use it:

- **Who sees its dashboards**: everyone with access to View, or only some people and groups of
  the platform (Settings › People › Groups in PlantCraft). The others do not see the folder or its
  dashboards anywhere: not in the list, the asset pages, the Overview widgets or the API.
- **Who edits its dashboards**: every editor of View, or only some people and groups. Only View
  editors among them change, share, add or delete its dashboards; they always see the folder.

Administrators see and change every folder. A folder is deleted once it is empty. A public link
keeps showing its dashboard to whoever holds it, whatever the folder.

## Share, Config, Edit

Next to the time picker: **Share** (public links), **Config** and **Edit**. Config saves at once,
without entering the editor; inside the editor it changes what **Save** saves.

| Section | What it holds |
|---|---|
| General | Name, folder, description, labels (the list's search finds them) |
| Time | The window it opens with, the refresh, the page turn in full screen |
| Display | **Shared cursor**: hovering a trend marks the same moment on the others. **Kiosk**: full screen and public links show the panels only (Esc leaves) |
| Variables | The pickers at the top: asset, custom and interval variables, their defaults, several values, All, a parent |
| Versions | The last 30 saves, who and when; **Restore** saves an old one again as the newest |
| JSON | The dashboard as a file, to start a dashboard from it elsewhere |

A saved dashboard reads plant data with the Dashboards app key, so every viewer sees the same numbers, and one
read is shared by all viewers for a few seconds.
