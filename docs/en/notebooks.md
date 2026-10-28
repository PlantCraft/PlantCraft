# Notebooks

**Notebooks** (in Desk's menu, after Calendar) is Jupyter inside PlantCraft: Python with numpy, pandas,
scipy and matplotlib, and the plant's data a call away. It runs in your browser, on your own
computer (JupyterLite on Pyodide, built into PlantCraft: nothing is downloaded from the internet),
and reads the plant through API v1 with **your own access**: a notebook never sees more than you
may.

## Run in the browser

Desk › Notebooks has two ways to run Python: **in the browser** and **on your computer**.

- **Install Python in this browser** (once, about 130 MB, with its progress): the page fetches
  Python, numpy, pandas, scipy, matplotlib and JupyterLab into this browser. On the plant's
  network it takes seconds (about 15 s measured); afterwards the page checks they are still
  there and offers **Open JupyterLab** at once. A new PlantCraft version asks to install again.
- **Open JupyterLab** opens a new tab with two folders: **Examples** (ready notebooks that find
  their own signals and assets, so they run on any installation, one folder per app:
  `PlantCraft` for the plant's data, `Link` for running Analytics' blocks and algorithms, and one
  for every other app that brings examples) and **My notebooks** (what PlantCraft wrote for
  you). While Python starts, the page says
  "Starting Python on your computer…" (about 10 s once installed).
- From the Historian (a point, an export): **Open in a notebook**. PlantCraft writes a notebook
  whose first cells already load those signals over that period, and opens it in a new tab.
- From any page, `/notebooks?signals=<id>,<id>&start=<time>&end=<time>` does the same, and
  `/notebooks?asset=<id>` opens an asset with its signals.

Limits of the browser: the memory one tab may use (about 2 to 4 GB), only the packages that come
with it (no `pip install` of others), slower than Python on your computer for heavy work, and
what you change (an example too) is kept by this browser only: **File › Download** saves the
notebook as an `.ipynb`, and the upload button brings one back. "In this browser", at the top
right of JupyterLab, says so. For more, run on your computer.

## Reading the plant

```python
import plantcraft_notebook as pc

pc.me()  # who the notebook reads as
pc.signals("FIC")  # signals whose id, name or description holds FIC
data = pc.series(["plant:FIC-101.PV", "plant:FIC-101.SP"], "-7d", "now", step=60)
data.plot(subplots=True)  # one column per signal, a UTC time index
pc.value("plant:FIC-101.PV", agg="mean", window="24h")
pc.assets(type="loop")  # the plant tree
pc.asset("FIC-101")["signals"]  # an asset's signals by role
pc.results(subject="asset:FIC-101")  # what the apps published (loop health, quality...)
pc.events(ref="asset:FIC-101")  # findings, alarms raised and cleared
```

Every time is UTC: a time without an offset is taken as UTC, and `"now"`, `"-24h"` or `"-7d"`
count back from now. `step` (seconds) gives one mean per step; without it, the values as
recorded. Long periods and many signals are read in parts.

## The apps' objects

Every app reads the same way in a notebook (owner, 2026-10-26): `pc.app(...)` with the app's
name, and its objects by kind. What each app offers is in `pc.apps()`.

```python
link = pc.app("link")
link.kinds()  # block, algorithm
link.blocks()  # a table: the same as link.list("block")
spikes = link.get("block", "dq.spikes")  # one object, whole: its ports and parameters
run = spikes.run(asset="FIC-101", start="-24h")  # on the loop's PV, here
run.values()  # each output: a verdict, a number, a series
link.get("block", "transform.moving_average").run(x=my_series, window_samples=30)
link.get("algorithm", "flow").run(asset="FIC-101")  # a whole algorithm on one loop
link.runtime().test_block(block_file, x=my_series)  # a block you write, tested as Link tests it
```

Models' models run in Models (OpenModelica), not in the notebook: `.run()` queues a simulation
in its queue, as its Simulate button does, and `.wait()` reads the run again until it ends. An
administrator allows it in Settings › Apps › Models (**Simulations from notebooks**, off by
default), and only Models' editors may. Alarms' rules and alarms are read only: an alarm comes
with its occurrences of the last 30 days, which is where an alarm performance study starts.
View's dashboards and reports are read only too, each with its panels or sections and the
signals they show (`pc.app("view").list("dashboard")`); the assistant lists them the same way.
Each app's examples show the rest: `Examples/Analytics`, `Examples/Models`, `Examples/Historian`,
`Examples/Alarms`.

```python
models = pc.app("models")
models.models()  # every model, the examples first
model = models.get("model", models.models().index[0])
run = model.run(stop=600).wait()  # in Models' queue, when allowed
run["results"]  # each variable: its time and values (thinned to 2000 points)
```

A block or an algorithm runs **in the notebook**, on your computer or in this browser, with the
code Analytics runs: the first `.run` brings Analytics' runtime (its Python code, under 1 MB, kept per
version). Its data is read with your access, as `pc.series` reads it. Nothing runs on the server
and nothing is written there: to keep a block, save its file and import it in Analytics. A model's
blocks (an FMU) run only in Analytics.

## Run on your computer

For more memory, packages of your own, big files or long calculations, run the same notebooks in
JupyterLab on your own computer with **PlantCraft Notebooks**, an app for Windows (x64), macOS
(Apple silicon) and Linux (x64) that Notebooks › Run on your computer offers while Notebooks are
on and the installation has it. No administrator rights, nothing from the internet, no command.

1. **Install it once.** The button names your system: a setup for Windows (for you only, with a
   Start menu entry and an uninstaller in Settings › Apps), an app for macOS (drag it to
   Applications), a folder with `Install.sh` for Linux. It holds Python 3.12, JupyterLab, numpy,
   pandas, scipy and matplotlib (the versions of the browser), `plantcraft-notebook` and the
   examples. A portable zip that needs no installation at all is there too.
2. **Connect it once.** Notebooks › Run on your computer › **Create a connection code** gives one
   line (shown once): this PlantCraft's address, a token of your own (read-only, as you, for 90
   days) and the fingerprint of the installation's certificate authority. Open PlantCraft
   Notebooks (Start menu, Applications, your Linux menu) and paste it when it asks; in the
   portable zip, double-click Configure token. The app checks the certificate authority against
   the fingerprint, and keeps the token in the system's vault (Windows Credential Manager, the
   macOS Keychain, the Secret Service on Linux; where there is none, a file only you read). The
   app says when the token ends within a week: create a new code then.
3. **Open notebooks.** Open PlantCraft Notebooks: JupyterLab opens in your browser, with
   `Examples` and `My notebooks`. A strip at the top of JupyterLab says it runs on your computer
   and reads which PlantCraft as whom. "Open in a notebook" (Historian, View, an asset) opens in
   the browser; open the app to have the notebooks PlantCraft wrote for you on your computer.

JupyterLab listens on `127.0.0.1` only, with a password the app makes each time it starts, and
keeps running in the background (the app reuses it; Start menu or the app open it again). The
notebooks live in `PlantCraft notebooks` in your Documents, outside the app, so a new version keeps
them; the browser does not see them, nor the other way round. Each opening refreshes `Examples`
and copies the notebooks PlantCraft wrote for you into `My notebooks`, never over one you edited;
in a notebook, `pc.sync()` does the same. `%pip install <name>` adds any package, when your
computer reaches a package index.

The first time, Windows may say "Windows protected your PC" (choose More info, then Run anyway)
and macOS that it cannot check the app (System Settings › Privacy & Security › Open Anyway): the
app is not signed yet. A link only names a server and a notebook: the app connects only after you
confirm, opens notebooks only for servers already connected and runs nothing that came with the
link.

**Without the kit** (or in a Python of your own: "Use my own Python instead"): **download** the
`plantcraft-notebook` wheel there and keep its name (pip refuses a file the browser renamed, such as
`...-2.whl`), install it in an environment of its own (macOS and most Linux refuse a `pip install`
outside one, PEP 668), **create an access token**, and connect:

```sh
python3 -m venv ~/plantcraft-env            # Windows: py -m venv plantcraft-env
source ~/plantcraft-env/bin/activate         # Windows: plantcraft-env\Scripts\activate
pip install jupyterlab matplotlib ~/Downloads/plantcraft_notebook-<version>-py3-none-any.whl
jupyter lab
```

```python
import plantcraft_notebook as pc

pc.connect("https://<server>", token="pcat_...")  # or PLANTCRAFT_URL and PLANTCRAFT_TOKEN
```

If your computer does not trust the server's certificate, pass `ca="company-ca.pem"`. The
notebook's other cells run unchanged; the `%pip install` line of the first cell is for the
browser.

## For administrators

- **Off by default.** An administrator turns Notebooks on (PlantCraft › Settings › Notebooks), and every
  change is in the audit log (`notebooks.settings`, and `notebooks.create` for each notebook
  PlantCraft writes). `PLANTCRAFT_NOTEBOOKS=off` in the installation's settings keeps them off
  for good.
- **What runs where.** The Python code runs in each person's browser, not on the server: the
  server only serves the files and answers API v1 as that person. A heavy notebook slows that
  person's computer, never the plant's server.
- **Limits for each person.** What a notebook asks the server for (series, signals, events) is
  limited per person in Settings › Notebooks: 120 requests a minute and 2 reads at once by default.
  They count every API v1 request made with an access token (a notebook or script on a computer,
  one budget per token) and the series reads a person's browser sends through the proxy. Past a
  limit that person alone gets `429` with `Retry-After`, and `plantcraft-notebook` waits and asks
  again by itself (up to 4 times, 30 s at most each). The apps' own reads (Analytics, Alarms, View),
  inside the internal network, never count, so a heavy notebook never slows them down. The first
  refusal of each minute for each person is in the audit log (`usage.limited`).
- **What a notebook may do.** Exactly what its person may do in PlantCraft through API v1,
  through their own session: read signals, series, assets, results and events. Turn Notebooks on
  when people are trusted to run code they write or are given, like any analysis tool on their
  computer.
- **Security.** The notebook pages (`/notebooks/lite/`) need the browser to run WebAssembly and
  code JupyterLab generates, so the proxy's Content-Security-Policy for those pages alone also
  allows `'unsafe-eval' 'wasm-unsafe-eval'`. They still load nothing from outside the server.
  Access tokens read API v1 only while Notebooks are on, and only read (`GET`, and the series
  read `POST /api/v1/series`).
- The image carries JupyterLite and a pruned Pyodide (about 130 MB), built by
  `notebooks/build.py` with versions and SHA-256 pinned in `notebooks/pins.json`.
- **The kit** is an optional part of the offline bundle (`notebook-kits/`, about 450 MB for the
  three systems), built by `make notebook-kits` (`make bundle` builds them too; on the Mac mini, every deploy that changes them) (`notebooks/kit/build_kit.py`: python-build-standalone
  and every wheel pinned by SHA-256 in `notebooks/kit/pins.json` and `requirements.txt`). It is
  offered whenever Notebooks are on and the installation has it (owner, 2026-10-26: one switch);
  an administrator may take it away in Settings › Notebooks › Kit for people's computers. PlantCraft adds the server's address and, with the local certificate authority,
  its root certificate to each zip as it sends it; never a token. Each download is in the audit
  log (`notebooks.kit_download`), each kit token too (`assistant_token.create`). A kit runs on
  the person's computer and reads only through API v1, within the limits above.
