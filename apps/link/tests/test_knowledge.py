"""What Link explains to the suite's assistants (``linkcraft.knowledge``) and the Ask the
assistant button's preparation (``POST /api/assistant/prepare``)."""

from __future__ import annotations

from plantcraft_sdk.client import NotFound

from linkcraft.blocks.convert import from_methods
from tests.conftest import client_for

TRACKING = from_methods(["error_metrics_basic", "oscillation_autocorrelation"])
HEADINGS = (
    "Purpose",
    "Assets and signals it reads",
    "When to use it",
    "How to read the verdict",
    "Instructions for the assistant",
    "Blocks, in the order they run",
)


def _captured(runtime) -> list[dict]:
    """What the publisher sends to PlantCraft's /knowledge."""

    sent: list[dict] = []
    suite = runtime.monitor.publisher.suite
    suite.put_knowledge = lambda items: sent.extend(items) or True
    return sent


def test_a_shipped_algorithm_is_explained_from_its_docs_and_blocks(runtime):
    item = runtime.explain("algorithm:linkcraft/level_loop")
    assert item["ref"] == "algorithm:linkcraft/level_loop" and item["kind"] == "algorithm"
    assert item["url"] == "/link/algorithms/level_loop"
    text = item["text"]
    for heading in HEADINGS:
        assert f"## {heading}" in text
    assert "`cpm.stiction_screening`" in text
    assert "Recorded in the historian" in runtime.explain("algorithm:linkcraft/unit_twin")["text"]
    # A protocol of 0.2 is explained by the algorithm that replaced it.
    assert runtime.explain("algorithm:linkcraft/level_control")["ref"] == item["ref"]


def test_every_block_is_explained_with_the_same_headings(runtime):
    item = runtime.explain("block:linkcraft/dq.frozen")
    assert item["kind"] == "block" and item["url"] == "/link/blocks/dq.frozen"
    for heading in ("What it does", "How to read it", "Inputs", "Outputs", "Parameters"):
        assert f"### {heading}" in item["text"]
    assert runtime.explain("block:linkcraft/nope") is None


def test_written_documentation_wins_and_the_rest_comes_from_the_diagram(client, runtime):
    docs = {"purpose": "Does the loop track its setpoint?", "assistant": "Answer in Portuguese."}
    body = {"algorithm_id": "tracking_check", "name": "Tracking", "diagram": TRACKING}
    sent = _captured(runtime)
    saved = client.put("/link/api/algorithms/tracking_check", json={**body, "docs": docs}).json()
    assert saved["docs"]["purpose"] == docs["purpose"] and saved["docs"]["assets"] == ""
    assert "PV" in saved["docs_generated"]["assets"]
    # What the docs still lack is said, never refused.
    assert any("assets" in problem for problem in saved["docs_problems"])
    # Saving tells the suite at once.
    assert [item["ref"] for item in sent] == ["algorithm:linkcraft/tracking_check"]
    text = sent[0]["text"]
    assert docs["purpose"] in text and "Answer in Portuguese." in text
    assert "`cpm.oscillation_autocorrelation`" in text  # the blocks, from the diagram
    generated = client.post(
        "/link/api/algorithms/docs", json={"diagram": TRACKING, "name": "X", "description": "Y"}
    ).json()
    assert generated["purpose"].startswith("Y") and set(generated) == {
        "purpose", "assets", "when", "reading", "assistant"
    }  # fmt: skip


def test_a_run_report_says_what_the_run_found(client, analysed):
    job = client.post(
        "/link/api/jobs", json={"loop_id": "lic-102", "name": "Check", "lookback_minutes": 120}
    ).json()
    analysed.monitor.execute_job(job["job_id"])
    item = analysed.explain(f"run:linkcraft/{job['job_id']}")
    assert item["kind"] == "run_report" and item["transient"] is True
    assert item["url"] == f"/link/runs/{job['job_id']}"
    assert "lic-102" in item["text"] and "## Methods" in item["text"]
    # About its algorithm and its loop's asset: the assistant finds it from either.
    assert item["subjects"] == ["algorithm:linkcraft/flow_loop", "asset:lic-102"]
    assert "#algorithm:linkcraft/flow_loop" in item["text"]


def test_prepare_publishes_link_objects_and_ignores_the_rest(client, analysed):
    sent = _captured(analysed)
    ref = "algorithm:linkcraft/flow_loop"
    answer = client.post("/link/api/assistant/prepare", json={"ref": ref})
    assert answer.json() == {"ref": ref, "published": True}
    assert sent[-1]["ref"] == ref
    signal = client.post(
        "/link/api/assistant/prepare", json={"ref": "algorithm:linkcraft/signal_quality"}
    )
    assert signal.json()["published"] and "Signal quality" in sent[-1]["title"]
    for ref in ("algorithm:linkcraft/nope", "run:linkcraft/nope", "asset:lic-102", "run:other/1"):
        assert (
            client.post("/link/api/assistant/prepare", json={"ref": ref}).json()["published"]
            is False
        )


def test_without_knowledge_in_processcraft_nothing_fails(client, runtime, fake):
    # An older PlantCraft has no /api/v1/knowledge: the text waits, the page works.
    def no_route(items):
        raise NotFound("Not Found", status_code=404)

    runtime.monitor.publisher.suite.client.put_knowledge = no_route
    answer = client.post(
        "/link/api/assistant/prepare", json={"ref": "algorithm:linkcraft/level_loop"}
    )
    assert answer.status_code == 200 and answer.json()["published"] is False
    assert runtime.publish_algorithms() is False
    with client_for(runtime, fake, "operator") as viewer:
        assert (
            viewer.post(
                "/link/api/assistant/prepare", json={"ref": "algorithm:linkcraft/level_loop"}
            ).status_code
            == 200
        )


def test_a_signal_quality_run_is_explained(checked):
    run = checked.quality_results.rounds(1)[0]
    item = checked.explain(f"run:linkcraft/signal-quality-{run['id']}")
    assert item["ref"] == f"run:linkcraft/signal-quality-{run['id']}"
    assert "signals:" in item["text"] and item["subjects"] == ["algorithm:linkcraft/signal_quality"]
    assert item["url"] == f"/link/runs/signal-quality-{run['id']}"


def test_the_assistant_page_reads_everything_link_judged(client, analysed):
    sent = _captured(analysed)
    answer = client.post("/link/api/assistant/prepare", json={"ref": "app:linkcraft"}).json()
    assert answer == {"ref": "app:linkcraft", "published": True}
    item = sent[-1]
    assert item["ref"] == "app:linkcraft" and item["kind"] == "overview"
    assert item["url"] == "/link/results"
    text = item["text"]
    assert "## Worst first" in text and "## Algorithms" in text
    assert "#algorithm:linkcraft/" in text
    # Worst first: the first line under the heading is an alarm or a warning.
    first = text.split("## Worst first\n", 1)[1].splitlines()[0]
    assert "alarm" in first or "warning" in first
    assert (
        client.post("/link/api/assistant/prepare", json={"ref": "app:other"}).json()["published"]
        is False
    )
