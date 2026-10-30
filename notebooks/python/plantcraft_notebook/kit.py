"""The Notebooks app on a person's computer: ``python -m plantcraft_notebook.kit <command>``.

The installer (``notebooks/kit/build_kit.py``: a Windows setup, a macOS app, a Linux folder with
``install.sh``) puts a portable Python with JupyterLab on the computer and runs ``install``, which
registers the ``plantcraft-notebooks://`` link with the system and copies the examples.

The person connects it once with a connection code: Notebooks › Run on your
computer › Create a connection code gives one line with the server's address, a read-only token
of their own and the SHA-256 of the local certificate authority. Opened unconnected, the app asks
for it in a small window ("Configure token" asks in a terminal), fetches the CA and keeps it only
when it matches, keeps the token in the system's vault and remembers the server. PlantCraft's page
no longer opens the app by its link: browsers on some Windows computers ignore such links without
a word. The link still works for kits connected the old way (``connect``, ``open``).

A link only names a server and a notebook: the app connects only after the person says yes,
opens notebooks only for servers already connected, takes file names (never paths) and runs
nothing that came with it. JupyterLab listens on 127.0.0.1 only, with a password this app makes
at each start. A strip at the top of JupyterLab says it runs on this computer and reads which
PlantCraft as whom.

The access token is never in a file of the kit: it is in the system's vault (``keyring``:
Windows Credential Manager, macOS Keychain, Secret Service), or, where there is none, in a file of
this app's folder only its owner reads. The notebooks live in ``PlantCraft notebooks`` in the
person's Documents, so a new version keeps them. A kit unzipped from an older download still works
the old way: its ``plantcraft.json`` names the server, "Configure token" asks for a token.
"""

from __future__ import annotations

import base64
import binascii
import getpass
import hashlib
import json
import os
import secrets
import shutil
import socket
import ssl
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import warnings
import webbrowser
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SERVICE = "PlantCraft"
SCHEME = "plantcraft-notebooks"
APP = "PlantCraft Notebooks"
TOKEN_FILE = ".plantcraft-token"
WORK_FOLDER = "PlantCraft notebooks"
EXAMPLES = "Examples"
MINE = "My notebooks"
PORT = 8888
# The kit says a token is about to expire this many days before.
WARN_DAYS = 7
# How long to wait for a JupyterLab this app started to answer.
START_SECONDS = 60


def home() -> Path:
    """The kit's folder: where its Python is."""

    configured = os.environ.get("PLANTCRAFT_KIT", "").strip()
    return Path(configured) if configured else Path(sys.prefix).resolve().parent


def app_folder() -> Path:
    """This app's own settings on this computer: the servers it reads, JupyterLab's state."""

    configured = os.environ.get("PLANTCRAFT_APP_FOLDER", "").strip()
    if configured:
        folder = Path(configured)
    elif sys.platform == "win32":
        folder = Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming") / APP
    elif sys.platform == "darwin":
        folder = Path.home() / "Library" / "Application Support" / APP
    else:
        base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
        folder = Path(base) / "plantcraft-notebooks"
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def settings(root: Path | None = None) -> dict[str, Any]:
    """The kit's version (``kit.json``) and the server it reads by default with its certificate
    authority: the last one connected, else the one a zip kit's ``plantcraft.json`` names."""

    path = (root or home()) / "kit.json"
    found: dict[str, Any] = {}
    if path.is_file():
        found.update(json.loads(path.read_text(encoding="utf-8")))
    where = default_server()
    if where:
        found.update(url=where["url"], ca=where.get("ca") or None)
    return found


def workspace() -> Path:
    """Where the person's notebooks are: ``PlantCraft notebooks`` in Documents (else home)."""

    configured = os.environ.get("PLANTCRAFT_NOTEBOOK_FOLDER", "").strip()
    if configured:
        return Path(configured)
    documents = Path.home() / "Documents"
    return (documents if documents.is_dir() else Path.home()) / WORK_FOLDER


# The servers this computer is connected to ---------------------------------------------------


def servers() -> list[dict[str, Any]]:
    """Every PlantCraft connected from this computer, the last one connected last."""

    path = app_folder() / "servers.json"
    try:
        listed = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return [item for item in listed if isinstance(item, dict) and item.get("url")]


def server(url: str) -> dict[str, Any] | None:
    url = url.rstrip("/")
    known = next((item for item in servers() if item["url"] == url), None)
    if known is None and str(settings_of_kit().get("url") or "").rstrip("/") == url:
        found = settings_of_kit()
        return {"url": url, "ca": found.get("ca") or ""}
    return known


def settings_of_kit() -> dict[str, Any]:
    """Only the kit's own ``plantcraft.json`` (a kit downloaded as a zip names its server)."""

    path = home() / "plantcraft.json"
    try:
        found = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if found.get("ca"):
        found["ca"] = str(home() / str(found["ca"]))
    return found


def remember(url: str, *, ca: str = "", name: str = "", username: str = "") -> None:
    """Adds or moves ``url`` to the end of the servers (the default from now on)."""

    url = url.rstrip("/")
    listed = [item for item in servers() if item["url"] != url]
    listed.append({"url": url, "ca": ca, "name": name, "username": username})
    path = app_folder() / "servers.json"
    path.write_text(json.dumps(listed, indent=2) + "\n", encoding="utf-8")


def default_server() -> dict[str, Any] | None:
    known = servers()
    if known:
        return known[-1]
    found = settings_of_kit()
    return (
        {"url": str(found["url"]).rstrip("/"), "ca": found.get("ca") or ""}
        if found.get("url")
        else None
    )


# The token ---------------------------------------------------------------------------------


def _vault() -> Any:
    try:
        import keyring
        from keyring.backends import fail

        backend = keyring.get_keyring()
        if isinstance(backend, fail.Keyring):
            return None
        return keyring
    except Exception:  # no vault on this system (a server without a desktop session)
        return None


def stored_token(url: str, root: Path | None = None) -> str:
    """The token saved for ``url`` (empty when none)."""

    vault = _vault()
    if vault is not None:
        try:
            found = vault.get_password(SERVICE, url)
            if found:
                return found
        except Exception:
            pass
    for path in ((root or home()) / TOKEN_FILE, app_folder() / TOKEN_FILE):
        try:
            saved = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if saved.get(url):
            return str(saved[url])
    return ""


def save_token(url: str, token: str, root: Path | None = None) -> str:
    """Keeps ``token`` for ``url``: in the vault, else in a file only its owner reads. Says where."""

    vault = _vault()
    if vault is not None:
        try:
            vault.set_password(SERVICE, url, token)
            return "vault"
        except Exception:
            pass
    # A zip kit keeps it beside itself, as before; the installed app in its own folder.
    zipped = root is None and (home() / "plantcraft.json").is_file()
    path = (root or (home() if zipped else app_folder())) / TOKEN_FILE
    saved: dict[str, str] = {}
    try:
        saved = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        pass
    saved[url] = token
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        json.dump(saved, handle)
    os.chmod(path, 0o600)
    return "file"


def days_left(expires_at: str | None, now: datetime | None = None) -> float | None:
    if not expires_at:
        return None
    try:
        moment = datetime.fromisoformat(str(expires_at).replace("Z", "+00:00"))
    except ValueError:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return (moment - (now or datetime.now(timezone.utc))).total_seconds() / 86400


def expiry_notice(listing: dict[str, Any], now: datetime | None = None) -> str:
    """What to say about the token's end (``/api/v1/notebooks``): nothing until a week before."""

    left = days_left(listing.get("token_expires_at"), now)
    if left is None or left > WARN_DAYS:
        return ""
    days = max(0, int(left))
    return (
        f"Your PlantCraft token expires in {days} day{'s' if days != 1 else ''}: in PlantCraft, "
        "Notebooks > Run on your computer > Create a connection code, and paste it when "
        "PlantCraft Notebooks asks."
    )


def _client(token: str | None = None, url: str | None = None) -> Any:
    from plantcraft_notebook import connect

    found = server(url) if url else default_server()
    if not found:
        raise SystemExit(
            "This computer is not connected to a PlantCraft yet: open PlantCraft Notebooks and "
            "paste the connection code from Notebooks > Run on your computer."
        )
    address = found["url"]
    return connect(
        address, token=token or stored_token(address) or None, ca=found.get("ca") or None
    )


# A connection code (``plantcraft.notebooks.kits.connection_code``): this PlantCraft's address,
# the kit's token and the SHA-256 of its local certificate authority, as one line.
CODE_PREFIX = "pcnb1:"


def parse_code(text: str) -> dict[str, str] | None:
    """``{url, token, ca}`` from a connection code; None for anything else (a bare token)."""

    text = "".join(text.split())
    if not text.startswith(CODE_PREFIX):
        return None
    packed = text[len(CODE_PREFIX) :]
    try:
        found = json.loads(base64.urlsafe_b64decode(packed + "=" * (-len(packed) % 4)))
    except (ValueError, binascii.Error) as error:
        raise LinkError("the connection code is cut or changed: copy it again") from error
    url = str(found.get("url") or "") if isinstance(found, dict) else ""
    if not url.startswith(("https://", "http://")):
        raise LinkError("the connection code names no PlantCraft: copy it again")
    return {
        "url": url.rstrip("/"),
        "token": str(found.get("token") or ""),
        "ca": str(found.get("ca") or ""),
    }


def _check(url: str, token: str, ca: str) -> tuple[dict[str, Any], dict[str, Any]]:
    """Who the token reads as, and the notebooks listing (it says when the token ends)."""

    from plantcraft_notebook import connect

    client = connect(url, token=token, ca=ca or None)
    return client.get("/api/v1/me"), client.get("/api/v1/notebooks")


def connect_with(text: str) -> str:
    """Connects this computer with a connection code (or, in a zip kit that names its server, a
    bare token): checks it with PlantCraft, keeps the token in the vault and the server as the
    default. Says what it did; raises LinkError, PlantCraftError or OSError."""

    found = parse_code(text)
    if found:
        url, token = found["url"], found["token"]
        ca = _fetch_ca(url, found["ca"]) if found["ca"] else ""
    else:
        token = "".join(text.split())
        where = default_server() or {}
        url, ca = str(where.get("url") or ""), str(where.get("ca") or "")
        if not url:
            raise LinkError("paste the connection code from PlantCraft (it starts with pcnb1:)")
    if not token.startswith("pcat_"):
        raise LinkError("that is not a PlantCraft connection code (they start with pcnb1:)")
    me, listing = _check(url, token, ca)
    where = save_token(url, token, root=app_folder())
    remember(url, ca=ca, name=str(me.get("name") or ""), username=str(me.get("username") or ""))
    copy_examples()
    place = "this computer's vault" if where == "vault" else "a file only you can read"
    said = (
        f"Connected to {url} as {me.get('name') or me.get('username')}, read-only. "
        f"The token is kept in {place}."
    )
    notice = expiry_notice(listing)
    return f"{said}\n\n{notice}" if notice else said


def ask_code() -> str:
    """The connection code, asked in a small window (in a terminal where there is none; from
    ``PLANTCRAFT_CODE`` when set, for scripted installs). Empty when the person cancels."""

    question = (
        "Paste the connection code from PlantCraft (Notebooks > Run on your computer > "
        "Create a connection code):"
    )
    if os.environ.get("PLANTCRAFT_CODE"):
        return os.environ.pop("PLANTCRAFT_CODE")  # once: a wrong one is not asked forever
    try:
        import tkinter
        from tkinter import simpledialog

        root = tkinter.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        try:
            answer = simpledialog.askstring(APP, question, parent=root, show="*")
        finally:
            root.destroy()
        return (answer or "").strip()
    except Exception:  # no display or no Tk: a terminal, when there is one
        if sys.stdin and sys.stdin.isatty():
            return getpass.getpass(question + " ").strip()
        return ""


def connect_interactive() -> bool:
    """Asks for a connection code until one works or the person cancels."""

    from plantcraft_notebook import PlantCraftError

    while True:
        text = ask_code()
        if not text:
            return False
        try:
            tell(connect_with(text))
            return True
        except LinkError as error:
            tell(f"This computer was not connected: {error}.")
        except PlantCraftError as error:
            tell(f"PlantCraft did not accept the code: {error}. Create a new one and paste it.")
        except OSError as error:
            tell(f"PlantCraft could not be reached: {error}.")


def configure_token() -> bool:
    """Configure token (``kit token``): connects with a code pasted in a terminal. True when it
    connected."""

    from plantcraft_notebook import PlantCraftError

    print("Create a connection code in PlantCraft: Notebooks > Run on your computer.")
    text = getpass.getpass("Paste it here and press Enter (it is not shown): ")
    try:
        print(connect_with(text))
        return True
    except (LinkError, PlantCraftError, OSError) as error:
        print(f"This computer was not connected: {error}")
        return False


# Notebooks ---------------------------------------------------------------------------------


def _safe(name: str) -> str:
    """A file name from the server, without folders."""

    return Path(str(name).replace("\\", "/")).name


def _example_place(item: dict[str, Any]) -> Path:
    """Where an example goes under ``Examples``: its app's folder and its name, never a path the
    server could steer elsewhere (``Examples/Analytics/Run a block.ipynb`` -> ``Analytics/Run a block.ipynb``)."""

    parts = str(item.get("path") or "").replace("\\", "/").split("/")
    folder = _safe(parts[1]) if len(parts) == 3 and parts[1] not in ("", ".", "..") else ""
    name = _safe(item["name"])
    return Path(folder, name) if folder else Path(name)


def _notebook(client: Any, path: str) -> Any:
    return client.get("/api/v1/notebooks/file?" + urllib.parse.urlencode({"path": path}))


def sync(target: Path | None = None, url: str | None = None) -> dict[str, Any]:
    """Refreshes ``Examples`` and copies the notebooks PlantCraft wrote for the person into
    ``My notebooks``, never over a notebook already here. Says what it did."""

    folder = target or workspace()
    client = _client(url=url)
    listing = client.get("/api/v1/notebooks")
    done = {"examples": 0, "added": 0, "kept": 0, "folder": str(folder)}
    written: set[Path] = set()
    for item in listing.get("examples") or []:
        content = _notebook(client, item["path"])
        path = folder / EXAMPLES / _example_place(item)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(content, indent=1), encoding="utf-8")
        written.add(path)
        done["examples"] += 1
    if written:
        # Examples is PlantCraft's (read-only: File › Save As keeps a copy in My notebooks): an
        # example the server no longer has goes, as do the flat ones of kits before 2026-10-26.
        for path in (folder / EXAMPLES).glob("**/*.ipynb"):
            if path not in written and ".ipynb_checkpoints" not in path.parts:
                path.unlink()
    for item in listing.get("mine") or []:
        path = folder / MINE / _safe(item["name"])
        if path.exists():
            done["kept"] += 1
            continue
        content = _notebook(client, item["path"])
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(content, indent=1), encoding="utf-8")
        done["added"] += 1
    (folder / MINE).mkdir(parents=True, exist_ok=True)
    newer = listing.get("kit_version")
    mine = settings().get("version")
    done["newer_kit"] = bool(newer and mine and newer != mine)
    done["token_expires_at"] = listing.get("token_expires_at")
    return done


def copy_examples(target: Path | None = None) -> int:
    """The examples that came with the installer, into ``Examples`` (never over a newer copy
    a sync wrote): JupyterLab has them before the computer is connected."""

    source = home() / "examples"
    folder = (target or workspace()) / EXAMPLES
    copied = 0
    for path in sorted(source.glob("**/*.ipynb")) if source.is_dir() else []:
        destination = folder / path.relative_to(source)
        if destination.exists():
            continue
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, destination)
        copied += 1
    (folder.parent / MINE).mkdir(parents=True, exist_ok=True)
    return copied


# Talking to the person without a terminal ----------------------------------------------------


def _osascript(script: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["osascript", "-e", script], capture_output=True, text=True, check=False)


def _quoted(text: str) -> str:
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


def ask(question: str) -> bool:
    """Yes or no, in the system's own dialog (a terminal where there is none)."""

    if os.environ.get("PLANTCRAFT_ASSUME_YES") == "1":
        return True
    if sys.platform == "win32":
        import ctypes

        # MB_YESNO | MB_ICONQUESTION | MB_SETFOREGROUND; IDYES is 6.
        return ctypes.windll.user32.MessageBoxW(None, question, APP, 0x4 | 0x20 | 0x10000) == 6
    if sys.platform == "darwin":
        answer = _osascript(
            f"display dialog {_quoted(question)} with title {_quoted(APP)} "
            'buttons {"Cancel", "Connect"} default button "Connect" with icon note'
        )
        return answer.returncode == 0 and "Connect" in answer.stdout
    for tool in (
        ["zenity", "--question", "--title", APP, "--text"],
        ["kdialog", "--title", APP, "--yesno"],
    ):
        if shutil.which(tool[0]):
            return subprocess.run([*tool, question], check=False).returncode == 0
    if sys.stdin and sys.stdin.isatty():
        return input(f"{question} [y/N] ").strip().lower() in ("y", "yes")
    return False


def tell(message: str) -> None:
    """Says ``message`` in the system's own dialog, or prints it."""

    print(message)
    if os.environ.get("PLANTCRAFT_ASSUME_YES") == "1" or (sys.stdout and sys.stdout.isatty()):
        return
    try:
        if sys.platform == "win32":
            import ctypes

            ctypes.windll.user32.MessageBoxW(None, message, APP, 0x40 | 0x10000)
        elif sys.platform == "darwin":
            _osascript(
                f"display dialog {_quoted(message)} with title {_quoted(APP)} "
                'buttons {"OK"} default button "OK" with icon note'
            )
        elif shutil.which("zenity"):
            subprocess.run(["zenity", "--info", "--title", APP, "--text", message], check=False)
        elif shutil.which("notify-send"):
            subprocess.run(["notify-send", APP, message], check=False)
    except Exception:  # a message the person does not see is not worth a crash
        pass


# The plantcraft-notebooks:// link --------------------------------------------------------------


class LinkError(ValueError):
    pass


def parse_link(link: str) -> tuple[str, dict[str, str]]:
    """``plantcraft-notebooks://connect?...`` or ``://open?...``: the action and its values,
    checked. Anything else is refused."""

    parts = urllib.parse.urlsplit(link.strip())
    if parts.scheme != SCHEME:
        raise LinkError("not a PlantCraft Notebooks link")
    action = (parts.netloc or parts.path.strip("/")).lower()
    values = {key: value for key, value in urllib.parse.parse_qsl(parts.query)}
    address = urllib.parse.urlsplit(values.get("server", ""))
    if address.scheme not in ("http", "https") or not address.hostname or address.username:
        raise LinkError("the link does not name a PlantCraft server")
    values["server"] = f"{address.scheme}://{address.netloc}".rstrip("/")
    if action == "connect":
        code = values.get("code", "")
        if not (16 <= len(code) <= 64) or not code.replace("-", "").replace("_", "").isalnum():
            raise LinkError("the link has no connection code")
        ca = values.get("ca", "")
        if ca and (len(ca) != 64 or any(char not in "0123456789abcdef" for char in ca)):
            raise LinkError("the link's certificate fingerprint is not valid")
        return action, {"server": values["server"], "code": code, "ca": ca}
    if action == "open":
        notebook = _safe(values.get("notebook", ""))
        if notebook and not notebook.endswith(".ipynb"):
            raise LinkError("the link does not name a notebook")
        return action, {"server": values["server"], "notebook": notebook}
    raise LinkError(f"unknown action {action!r}")


def _unverified() -> ssl.SSLContext:
    context = ssl.create_default_context()
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    return context


def _fetch_ca(url: str, fingerprint: str) -> str:
    """The server's local certificate authority, kept only when it is the one the signed-in page
    named (its SHA-256 in the link). Its path."""

    request = urllib.request.Request(url + "/api/notebooks/pair/ca")
    with urllib.request.urlopen(request, timeout=30, context=_unverified()) as answer:
        data = answer.read(65536)
    if hashlib.sha256(data).hexdigest() != fingerprint:
        raise LinkError("the server's certificate is not the one PlantCraft's page named")
    host = urllib.parse.urlsplit(url).netloc.replace(":", "_")
    path = app_folder() / f"ca-{host}.pem"
    path.write_bytes(data)
    return str(path)


def _context(ca: str) -> ssl.SSLContext | None:
    from plantcraft_notebook import Client

    return Client("http://unused", token="unused", ca=ca or None)._context()


def _redeem(url: str, code: str, ca: str) -> dict[str, Any]:
    """Trades the one-time code for the kit's token: ``{token, expires_at, username, name}``."""

    body = json.dumps({"code": code, "computer": socket.gethostname()[:60]}).encode()
    request = urllib.request.Request(
        url + "/api/notebooks/pair/redeem",
        data=body,
        method="POST",
        headers={"Content-Type": "application/json", "Accept": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=30, context=_context(ca)) as answer:
        return json.loads(answer.read().decode("utf-8"))


def connect_link(values: dict[str, str]) -> bool:
    """Connects this computer to ``server`` with a one-time code, once the person said yes."""

    url = values["server"]
    if not ask(
        f"Connect PlantCraft Notebooks on this computer to {url}?\n\n"
        "Your notebooks will read that PlantCraft with your access, read-only. Say no if you "
        "did not just click Connect this computer there."
    ):
        return False
    ca = _fetch_ca(url, values["ca"]) if values.get("ca") else ""
    try:
        given = _redeem(url, values["code"], ca)
    except urllib.error.HTTPError as error:
        from plantcraft_notebook import _detail

        reason = _detail(error.read().decode("utf-8", "replace"))
        tell(f"PlantCraft did not connect this computer: {reason}")
        return False
    save_token(url, str(given["token"]), root=app_folder())
    remember(
        url, ca=ca, name=str(given.get("name") or ""), username=str(given.get("username") or "")
    )
    copy_examples()
    tell(
        f"Connected to {url} as {given.get('name') or given.get('username')}.\n\n"
        "In PlantCraft, open any notebook On my computer, or open PlantCraft Notebooks here."
    )
    return True


def open_link(values: dict[str, str]) -> int:
    url = values["server"]
    if server(url) is None or not stored_token(url):
        tell(
            f"This computer is not connected to {url} yet: in PlantCraft, Notebooks > "
            "Run on your computer > Connect this computer."
        )
        return 1
    return open_lab(url=url, notebook=values.get("notebook") or "")


def handle_link(link: str) -> int:
    try:
        action, values = parse_link(link)
        if action == "connect":
            return 0 if connect_link(values) else 1
        return open_link(values)
    except LinkError as error:
        tell(f"This link cannot be opened: {error}.")
        return 2
    except OSError as error:
        tell(f"PlantCraft could not be reached: {error}.")
        return 1


# JupyterLab ----------------------------------------------------------------------------------


def _state_path() -> Path:
    return app_folder() / "jupyterlab.json"


def _running() -> dict[str, Any] | None:
    """The JupyterLab this app started, when it still answers."""

    try:
        state = json.loads(_state_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    probe = f"http://127.0.0.1:{int(state['port'])}/api/status?token={state['token']}"
    try:
        with urllib.request.urlopen(probe, timeout=3) as answer:
            return state if answer.status == 200 else None
    except (OSError, ValueError, KeyError):
        return None


def _free_port() -> int:
    for port in [PORT, *range(PORT + 1, PORT + 20)]:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            if probe.connect_ex(("127.0.0.1", port)) != 0:
                return port
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def strip_css(where: dict[str, Any], expires_at: str | None) -> str:
    """The strip at the top of JupyterLab: this computer, which PlantCraft, as whom, until when."""

    who = where.get("name") or where.get("username") or "you"
    text = f"On your computer · reads {where.get('url', 'PlantCraft')} as {who}"
    if expires_at:
        text += f" · token until {str(expires_at)[:10]}"
    text += " · notebooks in Documents/PlantCraft notebooks"
    escaped = text.replace("\\", "\\\\").replace('"', '\\"')
    return (
        "/* PlantCraft Notebooks: where these notebooks run (plantcraft_notebook.kit). */\n"
        'body::before { content: "' + escaped + '"; position: fixed; top: 4px; right: 12px;'
        " z-index: 9999; padding: 2px 10px; border-radius: 999px; font: 12px system-ui, sans-serif;"
        " background: rgba(21, 128, 61, .12); border: 1px solid rgba(21, 128, 61, .4);"
        " pointer-events: none; white-space: nowrap; }\n"
    )


def _start(folder: Path, where: dict[str, Any], expires_at: str | None) -> dict[str, Any]:
    """JupyterLab on 127.0.0.1, in the background, with a password only this app knows."""

    config = app_folder() / "jupyter"
    (config / "custom").mkdir(parents=True, exist_ok=True)
    (config / "custom" / "custom.css").write_text(strip_css(where, expires_at), encoding="utf-8")
    port = _free_port()
    token = secrets.token_urlsafe(24)
    environment = dict(
        os.environ,
        PLANTCRAFT_URL=str(where.get("url") or ""),
        PLANTCRAFT_KIT=str(home()),
        JUPYTER_CONFIG_DIR=str(config),
    )
    if where.get("ca"):
        environment["PLANTCRAFT_CA"] = str(where["ca"])
    command = [
        _python(console=True),
        "-m",
        "jupyterlab",
        "--ServerApp.ip=127.0.0.1",
        f"--ServerApp.port={port}",
        "--ServerApp.port_retries=0",
        f"--IdentityProvider.token={token}",
        f"--ServerApp.root_dir={folder}",
        "--ServerApp.open_browser=False",
        "--LabApp.custom_css=True",
        # JupyterLab's own announcements and update checks call the internet: never here.
        "--LabApp.news_url=",
        "--LabApp.check_for_updates_class=jupyterlab.NeverCheckForUpdate",
        "--LabApp.extension_manager=readonly",
    ]
    if hasattr(os, "geteuid") and os.geteuid() == 0:
        command.append("--allow-root")  # a container's only user
    log = (app_folder() / "jupyterlab.log").open("ab")
    options: dict[str, Any] = {"cwd": folder, "env": environment, "stdout": log, "stderr": log}
    if sys.platform == "win32":
        # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP | CREATE_NO_WINDOW
        options["creationflags"] = 0x8 | 0x200 | 0x08000000
    else:
        options["start_new_session"] = True
    process = subprocess.Popen(command, stdin=subprocess.DEVNULL, **options)  # noqa: S603
    state = {"port": port, "token": token, "pid": process.pid, "url": where.get("url")}
    _state_path().write_text(json.dumps(state), encoding="utf-8")
    deadline = time.monotonic() + START_SECONDS
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise OSError(
                f"JupyterLab stopped as it started (see {app_folder() / 'jupyterlab.log'})"
            )
        if _running():
            return state
        time.sleep(0.5)
    raise OSError("JupyterLab did not start within a minute")


def _python(console: bool = False) -> str:
    """This Python; on Windows its windowless twin (pythonw.exe) unless a console is wanted."""

    if sys.platform == "win32" and not console:
        quiet = Path(sys.executable).with_name("pythonw.exe")
        if quiet.is_file():
            return str(quiet)
    return sys.executable


def open_lab(url: str | None = None, notebook: str = "") -> int:
    """Brings the notebooks up to date and opens JupyterLab (the one running, else a new one),
    at ``notebook`` in My notebooks when one is named."""

    from plantcraft_notebook import PlantCraftError

    where = (server(url) if url else default_server()) or {}
    if not where.get("url") or not stored_token(where["url"]):
        # Not connected yet: the connection code, once.
        if not connect_interactive():
            return 1
        where = (server(url) if url else default_server()) or {}
    folder = workspace()
    folder.mkdir(parents=True, exist_ok=True)
    copy_examples(folder)
    expires_at = None
    if where.get("url"):
        try:
            done = sync(folder, url=where["url"])
            expires_at = done.get("token_expires_at")
            notice = expiry_notice(done)
            if notice:
                tell(notice)
            print(f"Examples refreshed; {done['added']} new notebook(s) from PlantCraft in {MINE}.")
            if done["newer_kit"]:
                print("A newer version is in PlantCraft (Notebooks > Run on your computer).")
        except PlantCraftError as error:
            print(f"PlantCraft could not be read ({error}): your notebooks open as they are.")
            if error.status == 401:
                tell(
                    "Your token was not accepted: in PlantCraft, create a new connection code "
                    "(Notebooks > Run on your computer) and paste it next."
                )
                if connect_interactive():
                    return open_lab(url, notebook)
        except OSError as error:
            print(f"PlantCraft could not be reached ({error}): your notebooks open as they are.")
    state = _running()
    if state is None or state.get("url") != where.get("url"):
        stop()
        state = _start(folder, where, expires_at)
    page = f"lab/tree/{urllib.parse.quote(MINE + '/' + _safe(notebook))}" if notebook else "lab"
    address = f"http://127.0.0.1:{state['port']}/{page}?token={state['token']}"
    print(f"JupyterLab: http://127.0.0.1:{state['port']}/lab")
    webbrowser.open(address)
    return 0


def stop() -> bool:
    """Stops the JupyterLab this app started. True when one was running."""

    state = _running()
    _state_path().unlink(missing_ok=True)
    if state is None:
        return False
    try:
        if sys.platform == "win32":
            subprocess.run(
                ["taskkill", "/PID", str(state["pid"]), "/T", "/F"],
                capture_output=True,
                check=False,
            )
        else:
            os.kill(int(state["pid"]), 15)
    except OSError:
        return False
    return True


# Installing --------------------------------------------------------------------------------


def _desktop_entry(name: str, command: str, extra: str = "") -> str:
    return (
        "[Desktop Entry]\nType=Application\n"
        f"Name={name}\nExec={command}\nTerminal=false\nCategories=Development;Science;\n{extra}"
    )


def install() -> str:
    """Registers the ``plantcraft-notebooks://`` link with this system and copies the examples.
    The Windows setup and the macOS app call it; on Linux, ``install.sh``. Says what it did."""

    copy_examples()
    python = _python()
    if sys.platform == "win32":
        import winreg

        command = f'"{python}" -m plantcraft_notebook.kit link "%1"'
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, rf"Software\Classes\{SCHEME}") as key:
            winreg.SetValueEx(key, "", 0, winreg.REG_SZ, f"URL:{APP}")
            winreg.SetValueEx(key, "URL Protocol", 0, winreg.REG_SZ, "")
        # Chrome and Edge open a link only when Windows names its app: without this name they
        # do nothing at all, not even ask (pythonw.exe has none Windows can find).
        with winreg.CreateKey(
            winreg.HKEY_CURRENT_USER, rf"Software\Classes\{SCHEME}\shell\open"
        ) as key:
            winreg.SetValueEx(key, "FriendlyAppName", 0, winreg.REG_SZ, APP)
        path = rf"Software\Classes\{SCHEME}\shell\open\command"
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, path) as key:
            winreg.SetValueEx(key, "", 0, winreg.REG_SZ, command)
        return "link registered for this Windows user"
    if sys.platform == "darwin":
        # The app's Info.plist declares the link; macOS registers it when the app is opened.
        return "link declared by the app"
    applications = (
        Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share") / "applications"
    )
    applications.mkdir(parents=True, exist_ok=True)
    quoted = '"' + python.replace('"', '\\"') + '"'
    handler = _desktop_entry(
        f"{APP} (links)",
        f"{quoted} -m plantcraft_notebook.kit link %u",
        f"NoDisplay=true\nMimeType=x-scheme-handler/{SCHEME};\n",
    )
    (applications / "plantcraft-notebooks-link.desktop").write_text(handler, encoding="utf-8")
    launcher = _desktop_entry(APP, f"{quoted} -m plantcraft_notebook.kit open")
    (applications / "plantcraft-notebooks.desktop").write_text(launcher, encoding="utf-8")
    if shutil.which("xdg-mime"):
        subprocess.run(
            [
                "xdg-mime",
                "default",
                "plantcraft-notebooks-link.desktop",
                f"x-scheme-handler/{SCHEME}",
            ],
            check=False,
        )
    if shutil.which("update-desktop-database"):
        subprocess.run(
            ["update-desktop-database", str(applications)], check=False, capture_output=True
        )
    return f"link registered in {applications}"


def uninstall() -> None:
    """Stops JupyterLab and forgets the link (the Windows setup's uninstaller; Linux)."""

    stop()
    if sys.platform == "win32":
        import winreg

        for path in (
            rf"Software\Classes\{SCHEME}\shell\open\command",
            rf"Software\Classes\{SCHEME}\shell\open",
            rf"Software\Classes\{SCHEME}\shell",
            rf"Software\Classes\{SCHEME}",
        ):
            try:
                winreg.DeleteKey(winreg.HKEY_CURRENT_USER, path)
            except OSError:
                pass
    elif sys.platform != "darwin":
        applications = (
            Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")
            / "applications"
        )
        for name in ("plantcraft-notebooks-link.desktop", "plantcraft-notebooks.desktop"):
            (applications / name).unlink(missing_ok=True)


def mac_app() -> int:
    """The macOS app's start: a link arrives as an Apple event, not as an argument, so the app
    listens for one for a moment; opened with a double click, it opens JupyterLab."""

    links: list[str] = []
    try:
        from rubicon.objc import NSObject, ObjCClass, objc_method
        from rubicon.objc.runtime import SEL

        NSApplication = ObjCClass("NSApplication")
        NSAppleEventManager = ObjCClass("NSAppleEventManager")
        NSRunLoop = ObjCClass("NSRunLoop")
        NSDate = ObjCClass("NSDate")

        class LinkHandler(NSObject):  # type: ignore[misc, valid-type]
            @objc_method
            def handleLink_withReply_(self, event, reply) -> None:  # noqa: N802
                # keyDirectObject ('----') holds the link.
                found = event.paramDescriptorForKeyword_(0x2D2D2D2D)
                if found is not None:
                    links.append(str(found.stringValue))

        application = NSApplication.sharedApplication
        handler = LinkHandler.alloc().init()
        # kInternetEventClass and kAEGetURL are both 'GURL'.
        NSAppleEventManager.sharedAppleEventManager.setEventHandler_andSelector_forEventClass_andEventID_(
            handler, SEL("handleLink:withReply:"), 0x4755524C, 0x4755524C
        )
        application.finishLaunching()
        deadline = time.monotonic() + 1.5
        while not links and time.monotonic() < deadline:
            NSRunLoop.currentRunLoop.runUntilDate_(NSDate.dateWithTimeIntervalSinceNow_(0.1))
    except Exception as error:  # without the bridge, a double click still opens JupyterLab
        warnings.warn(f"links are not received on this Mac: {error}", stacklevel=1)
    if links:
        return handle_link(links[0])
    return open_lab()


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    command = args[0] if args else "open"
    warnings.simplefilter("default")
    if command == "token":
        ok = configure_token()
        if sys.stdin.isatty():
            input("Press Enter to close.")
        return 0 if ok else 1
    if command == "sync":
        print(json.dumps(sync(), indent=2))
        return 0
    if command == "open":
        try:
            return open_lab()
        except OSError as error:
            tell(f"JupyterLab could not start: {error}")
            return 1
    if command == "link" and len(args) == 2:
        return handle_link(args[1])
    if command == "install":
        print(install())
        return 0
    if command == "uninstall":
        uninstall()
        return 0
    if command == "stop":
        print("stopped" if stop() else "JupyterLab was not running")
        return 0
    if command == "mac":
        return mac_app()
    print(
        "usage: python -m plantcraft_notebook.kit open|link <url>|install|uninstall|stop|sync|token"
    )
    return 2


if __name__ == "__main__":
    sys.exit(main())
