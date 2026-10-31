"""PlantCraft setup wizard (prototype, docs/installation-file.md): the installer's screens in a
browser, before the suite exists.

    sudo python3 wizard/wizard.py              # from the bundle folder, as root
    sudo python3 wizard/wizard.py --apply      # the last screen may also run install.sh

It listens on 127.0.0.1 only and prints an address with a one-time key; from another computer,
reach it through SSH (`ssh -L 8765:127.0.0.1:8765 server`). It runs preflight.sh, shows the
choices, writes /etc/plantcraft/installation.conf (root, 644) and, with --apply, runs
`install.sh --config` and shows its log. Standard library only: it runs on the server's own
Python 3.8+, with no network and nothing installed.
"""

from __future__ import annotations

import argparse
import hmac
import json
import os
import secrets
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

HERE = Path(__file__).resolve().parent
BUNDLE = HERE.parent
CONF_PATH = Path(
    os.environ.get("PLANTCRAFT_INSTALLATION_CONF", "/etc/plantcraft/installation.conf")
)
APPS = ("analytics", "historian", "view", "alarms", "models", "documents")
KEYS = {
    "APPS": r"^(all|[a-z]+(,[a-z]+)*)$",
    "WEB_APP_INSTALL": r"^(on|off)$",
    "DEMO": r"^(off|on|public)$",
    "MACHINE": r"^(auto|small|medium|large|xlarge|off)$",
    "MAX_CPUS": r"^([0-9]+(\.[0-9]+)?)?$",
    "MAX_MEMORY": r"^([0-9]+[mMgG]?)?$",
    "MAX_SIGNALS": r"^[0-9]*$",
    "MAX_PARALLEL_RUNS": r"^[0-9]*$",
    "MAX_SESSIONS": r"^[0-9]*$",
    "HOSTNAME": r"^[A-Za-z0-9. :_-]*$",
    "HTTPS_PORT": r"^[0-9]{2,5}$",
    "BIND_ADDRESS": r"^[0-9.:a-fA-F]+$",
    "NETWORK_BASE": r"^[0-9]{1,3}\.[0-9]{1,3}$",
    "LLM": r"^(on|off)$",
    "TIMEZONE": r"^[A-Za-z0-9/_+-]*$",
    "LOCK_TIMEZONE": r"^(yes|no)$",
}


def conf_text(values: dict[str, str]) -> str:
    """The installation file for these choices; raises ValueError for a value outside its rule."""

    import re

    lines = [
        "# PlantCraft installation file, written by the setup wizard.",
        "# Change it as root, then run install.sh again (docs/installation-file.md).",
    ]
    for key, rule in KEYS.items():
        value = str(values.get(key, "")).strip()
        if not re.fullmatch(rule, value):
            raise ValueError(f"{key}: '{value}' is not allowed")
        if key == "APPS" and value != "all":
            unknown = sorted(set(value.split(",")) - set(APPS))
            if unknown:
                raise ValueError(f"APPS: unknown {', '.join(unknown)}")
        lines.append(f"{key}={value}")
    return "\n".join(lines) + "\n"


class Wizard:
    def __init__(self, apply: bool, conf_path: Path) -> None:
        self.key = secrets.token_urlsafe(18)
        self.apply = apply
        self.conf_path = conf_path
        self.log: list[str] = []
        self.state = "idle"  # idle | running | done | failed

    def check(self, apps: str) -> dict:
        done = subprocess.run(
            [str(BUNDLE / "preflight.sh"), "--json", "--apps", apps or "all"],
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
        return json.loads(done.stdout or "{}")

    def write(self, text: str) -> None:
        self.conf_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.conf_path.with_suffix(".tmp")
        tmp.write_text(text, encoding="utf-8")
        os.chmod(tmp, 0o644)
        if os.geteuid() == 0:
            os.chown(tmp, 0, 0)
        tmp.replace(self.conf_path)

    def install(self) -> None:
        self.state, self.log = "running", []
        process = subprocess.Popen(
            [str(BUNDLE / "install.sh"), "--config", str(self.conf_path), "--yes"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        assert process.stdout is not None
        for line in process.stdout:
            self.log.append(line.rstrip())
        self.state = "done" if process.wait() == 0 else "failed"


def handler(wizard: Wizard) -> type[BaseHTTPRequestHandler]:
    page = (HERE / "index.html").read_bytes()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args) -> None:  # quiet
            pass

        def _authorised(self) -> bool:
            query = parse_qs(urlparse(self.path).query)
            given = self.headers.get("X-Wizard-Key") or (query.get("key") or [""])[0]
            return hmac.compare_digest(given, wizard.key)

        def _send(self, status: int, body: bytes, kind: str = "application/json") -> None:
            self.send_response(status)
            self.send_header("Content-Type", kind)
            self.send_header("Cache-Control", "no-store")
            self.send_header(
                "Content-Security-Policy",
                "default-src 'self'; style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'",
            )
            self.end_headers()
            self.wfile.write(body)

        def _json(self, status: int, data: object) -> None:
            self._send(status, json.dumps(data).encode())

        def do_GET(self) -> None:
            if not self._authorised():
                return self._send(
                    403, b"Open the address the wizard printed (it carries the key).", "text/plain"
                )
            route = urlparse(self.path).path
            if route == "/":
                return self._send(200, page, "text/html; charset=utf-8")
            if route == "/api/check":
                apps = (parse_qs(urlparse(self.path).query).get("apps") or ["all"])[0]
                return self._json(200, wizard.check(apps))
            if route == "/api/status":
                return self._json(
                    200,
                    {
                        "state": wizard.state,
                        "log": wizard.log[-400:],
                        "apply": wizard.apply,
                        "conf": str(wizard.conf_path),
                    },
                )
            return self._send(404, b"{}")

        def do_POST(self) -> None:
            if not self._authorised():
                return self._send(403, b"{}")
            length = min(int(self.headers.get("Content-Length") or 0), 16 * 1024)
            try:
                values = json.loads(self.rfile.read(length) or b"{}")
                text = conf_text(values)
            except (ValueError, json.JSONDecodeError) as error:
                return self._json(400, {"error": str(error)})
            route = urlparse(self.path).path
            if route == "/api/preview":
                return self._json(200, {"text": text, "path": str(wizard.conf_path)})
            if route == "/api/install":
                wizard.write(text)
                if not wizard.apply:
                    return self._json(200, {"written": str(wizard.conf_path), "installing": False})
                if wizard.state == "running":
                    return self._json(409, {"error": "already installing"})
                threading.Thread(target=wizard.install, daemon=True).start()
                return self._json(200, {"written": str(wizard.conf_path), "installing": True})
            return self._send(404, b"{}")

    return Handler


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--apply", action="store_true", help="the last screen also runs install.sh")
    parser.add_argument("--conf", default=str(CONF_PATH), help="where the installation file goes")
    args = parser.parse_args(argv)
    wizard = Wizard(args.apply, Path(args.conf))
    server = ThreadingHTTPServer(("127.0.0.1", args.port), handler(wizard))
    print(f"PlantCraft setup: open http://127.0.0.1:{args.port}/?key={wizard.key}", flush=True)
    print(
        "From another computer: ssh -L {0}:127.0.0.1:{0} <this server>, then the same address.".format(
            args.port
        )
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
