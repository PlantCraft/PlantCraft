"""A scripted OpenAI-compatible model for trying the setup guide without a real one
(``python dev/fake_llm.py --port 11999``; docs/setup-guide.md, "Try it").

It answers ``POST /v1/chat/completions`` the way a small model would for each step's work: it
asks one question first, then proposes the step's card from what the person answered. Never
for production: it only knows the guide's steps.
"""

from __future__ import annotations

import argparse
import json
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

ZONES = {
    "brazil": "America/Sao_Paulo",
    "brasil": "America/Sao_Paulo",
    "são paulo": "America/Sao_Paulo",
    "campinas": "America/Sao_Paulo",
    "germany": "Europe/Berlin",
    "india": "Asia/Kolkata",
    "texas": "America/Chicago",
}


def _text_of(message: dict[str, Any]) -> str:
    content = message.get("content")
    if isinstance(content, list):
        return " ".join(str(part.get("text") or "") for part in content if isinstance(part, dict))
    return str(content or "")


def _step(system: str) -> str:
    for step, marker in (
        ("basics", "the plant's time zone (an IANA name"),
        ("connection", "connect PlantCraft to the plant's data"),
        ("assets", "build the asset tree on Assets"),
        ("people", "add the people who will use PlantCraft"),
        ("documents", "add the plant's documents"),
        ("start", "each installed app takes its first step"),
    ):
        if marker in system:
            return step
    return "help"


def _reply(body: dict[str, Any]) -> dict[str, Any]:
    messages = body.get("messages") or []
    system = " ".join(_text_of(item) for item in messages if item.get("role") == "system")
    users = [_text_of(item) for item in messages if item.get("role") == "user"]
    last = messages[-1] if messages else {}
    tools = {tool.get("function", {}).get("name") for tool in body.get("tools") or []}
    step = _step(system)
    said = users[-1] if users else ""
    if last.get("role") == "tool":
        return _text(
            "Here it is. Check the card and click **Create**: I apply it as you, and the guide "
            "moves on as soon as it sees it."
        )
    if step == "basics":
        if len(users) < 2:
            return _text(
                "Let's start with the basics. **Where is the plant?** A city or a country is "
                "enough, and I will pick its time zone."
            )
        zone = next((value for key, value in ZONES.items() if key in said.lower()), "UTC")
        language = "pt-BR" if re.search(r"portugu|brasil|brazil", said, re.I) else "en"
        return _propose(tools, {"time_zone": zone, "language": language})
    if step == "connection":
        found = re.search(r"(opc\.tcp://\S+|https://\S+)", said)
        if not found:
            return _text(
                "Now the plant's data, read only. **What does the plant have?** An OPC UA server "
                "(its address, like `opc.tcp://192.168.0.10:4840`), a PI Web API "
                "(`https://server/piwebapi`) or a CSV file."
            )
        address = found.group(1).rstrip(".,)")
        kind = "opcua" if address.startswith("opc.tcp") else "pi_web_api"
        return _propose(
            tools,
            {
                "name": "Plant OPC UA" if kind == "opcua" else "Plant PI",
                "kind": kind,
                "endpoint": address,
            },
        )
    if step == "people":
        if len(users) < 2:
            return _text(
                "Who should I add first? Their **name**, the **user name** they sign in with, and what they do."
            )
        name = said.split(",")[0].strip() or "Ana Souza"
        username = re.sub(r"[^a-z0-9]+", ".", name.lower()).strip(".")[:60] or "ana"
        access = "editor" if re.search(r"engineer|engenh", said, re.I) else "viewer"
        return _propose(
            tools,
            {
                "display_name": name,
                "username": username,
                "role": "Process engineer" if access == "editor" else "Operator",
                "access_level": access,
            },
        )
    if step == "assets":
        return _text(
            "The quickest way: open **Assets › Import**, choose **Draft from tags** and pick the "
            "source you just connected. I read its tags as ISA-5.1, so `FIC-1003` becomes a flow "
            "loop with its PV, SP and OP, and the draft opens for review. Leave out what is "
            "wrong and click **Apply** (you can undo it)."
        )
    if step == "documents":
        return _text(
            "Start with the **P&IDs** and the **loop list**: with them each loop lands in its unit and area. Open Documents › Add and drop the files."
        )
    if step == "start":
        return _text(
            "Each app takes one first step: the Historian collects the signals, Analytics starts monitoring the loops, Alarms drafts rules that stay off, and View draws a dashboard per unit. Use **Run them all** in the guide."
        )
    return _text("I can help with every step of the setup. Which one would you like to do now?")


def _propose(tools: set[str | None], fields: dict[str, Any]) -> dict[str, Any]:
    name = (
        "propose"
        if "propose" in tools
        else next((tool for tool in tools if tool and tool.startswith("propose")), "propose")
    )
    call = {
        "id": "call_1",
        "type": "function",
        "function": {"name": name, "arguments": json.dumps({"fields": fields})},
    }
    return {"role": "assistant", "content": "", "tool_calls": [call]}, "tool_calls"


def _text(text: str) -> tuple[dict[str, Any], str]:
    return {"role": "assistant", "content": text}, "stop"


class Handler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:  # noqa: N802
        size = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(size) or b"{}")
        message, reason = _reply(body)
        answer = {
            "id": "fake",
            "object": "chat.completion",
            "model": body.get("model") or "fake",
            "choices": [{"index": 0, "message": message, "finish_reason": reason}],
            "usage": {"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120},
        }
        data = json.dumps(answer).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:  # noqa: N802
        data = json.dumps({"data": [{"id": "guide-fake"}]}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *_args: Any) -> None:
        pass


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=11999)
    args = parser.parse_args()
    ThreadingHTTPServer(("127.0.0.1", args.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
