"""Desk's Assistant in a real browser, answered by a stand-in for a local model (an
OpenAI-compatible server on this machine): a question, the reads it made, a chart drawn from the
plant's history and a second chat beside the first."""

from __future__ import annotations

import json
import os
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
from playwright.sync_api import expect

SHOTS = os.environ.get("PLANTCRAFT_E2E_SHOTS")


def _reply(body: dict) -> dict:
    """What a model with tools does: find signals, draw them, then answer from the chart."""

    messages = body["messages"]
    question = next(item["content"] for item in reversed(messages) if item["role"] == "user")
    results = [item for item in messages if item["role"] == "tool"]
    if "Translate" in question or "Traduza" in question:
        return {"content": "The control valve is stuck at 40 % open."}
    if not results:
        call = ("search_signals", {"query": "PV", "limit": 4})
    elif len(results) == 1:
        found = json.loads(results[0]["content"])
        # The demo plant is a recorded day of January 2026.
        call = (
            "show_chart",
            {
                "signal_ids": [item["id"] for item in found[:2]],
                "start": "2026-01-01T00:00:00Z",
                "end": "2026-01-02T00:00:00Z",
                "title": "1 January 2026",
            },
        )
    else:
        chart = json.loads(results[-1]["content"])
        rows = "\n".join(
            f"| `{item['signal']}` | {item.get('min', 0):.2f} | {item.get('mean', 0):.2f} | {item.get('max', 0):.2f} |"
            for item in chart["signals"]
        )
        return {
            "content": "Both signals stayed inside their usual band on 1 January 2026.\n\n"
            f"| Signal | Min | Mean | Max |\n|---|---|---|---|\n{rows}\n\n"
            "No step or oscillation stands out in the chart."
        }
    name, arguments = call
    return {
        "content": None,
        "tool_calls": [
            {"id": f"call-{len(results)}", "type": "function",
             "function": {"name": name, "arguments": json.dumps(arguments)}}
        ],
    }  # fmt: skip


class _Model(BaseHTTPRequestHandler):
    def do_POST(self):  # noqa: N802 (the standard library's name)
        body = json.loads(self.rfile.read(int(self.headers["content-length"])))
        message = {"role": "assistant", **_reply(body)}
        reason = "tool_calls" if message.get("tool_calls") else "stop"
        data = json.dumps({"choices": [{"message": message, "finish_reason": reason}]}).encode()
        self.send_response(200)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *_args):
        pass


@pytest.fixture(scope="module")
def local_model():
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Model)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_address[1]}/v1"
    server.shutdown()


def _shot(page, name: str) -> None:
    if SHOTS:
        Path(SHOTS).mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(Path(SHOTS) / name), full_page=False)


def test_the_assistant_reads_the_plant_and_draws_a_chart(page, local_model):
    page.goto("/assistant")
    expect(page.get_by_role("heading", name="The assistant is off")).to_be_visible()
    saved = page.request.put(
        "/api/language-model",
        data={
            "enabled": True,
            "provider": "openai",
            "name": "local-model",
            "endpoint": local_model,
        },
    )
    assert saved.ok, saved.text()
    page.goto("/assistant/new")
    expect(page.get_by_role("heading", name="How can I help?")).to_be_visible()
    _shot(page, "assistant-new.png")
    page.get_by_label("Your question").fill("Plot the PV signals on 1 January 2026")
    page.get_by_label("Your question").press("Enter")
    expect(page).to_have_url(re.compile(r"/assistant/\d+$"))
    answer = page.locator(".asst-answer")
    expect(answer.get_by_text("Both signals stayed inside their usual band")).to_be_visible(
        timeout=20_000
    )
    expect(answer.locator(".pc-answer-chart .main-svg").first).to_be_visible()
    expect(answer.get_by_role("button", name=re.compile("2 reads of the plant"))).to_be_visible()
    page.wait_for_load_state("networkidle")
    _shot(page, "assistant-chart.png")
    answer.get_by_role("button", name=re.compile("2 reads of the plant")).click()
    expect(answer.get_by_text("Search signals")).to_be_visible()
    _shot(page, "assistant-steps.png")
    # A second chat, on another subject, beside the first.
    page.get_by_role("button", name="New chat").click()
    page.get_by_label("Your question").fill("Translate: a válvula está travada em 40 %")
    page.get_by_label("Your question").press("Enter")
    expect(page.locator(".asst-answer", has_text="stuck at 40 %")).to_be_visible(timeout=20_000)
    chats = page.locator(".asst-list li")
    expect(chats).to_have_count(2)
    _shot(page, "assistant-two-chats.png")
