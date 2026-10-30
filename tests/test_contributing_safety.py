"""What keeps an outside pull request from reaching the Mac mini, the release or the rules
(docs/contributing-safety.md).

- every path ``.github/CODEOWNERS`` names exists, so moving a guarded file without moving its
  owner line fails here;
- no workflow runs on ``pull_request_target`` or ``workflow_run`` (they run with the base
  repository's token and secrets on code a stranger wrote);
- every workflow's token is read-only by default;
- a job that may run on the self-hosted runner never runs a fork's pull request there, and the
  deploy jobs run only from main;
- every action is pinned to a full commit SHA (a moved tag never changes what CI runs).
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = sorted((ROOT / ".github" / "workflows").glob("*.yml"))
# Paths CODEOWNERS guards before they exist (a folder an agent tool may create).
MAY_BE_MISSING = {"/.claude/"}
FORK_GUARD = "github.event.pull_request.head.repo.fork && 'ubuntu-latest'"
PINNED = re.compile(r"^[\w.-]+/[\w./-]+@[0-9a-f]{40}$")


def _load(path: Path) -> dict:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    # YAML 1.1 reads the key "on" as True.
    if True in data:
        data["on"] = data.pop(True)
    return data


def _triggers(workflow: dict) -> set[str]:
    on = workflow.get("on") or {}
    if isinstance(on, str):
        return {on}
    if isinstance(on, list):
        return set(on)
    return set(on)


def test_there_are_workflows_to_check():
    assert len(WORKFLOWS) >= 5


def test_every_code_owner_path_exists():
    lines = (ROOT / ".github" / "CODEOWNERS").read_text(encoding="utf-8").splitlines()
    rules = [line.split() for line in lines if line.strip() and not line.startswith("#")]
    assert rules, "CODEOWNERS has no rules"
    missing = [
        rule[0]
        for rule in rules
        if "*" not in rule[0]
        and rule[0] not in MAY_BE_MISSING
        and not (ROOT / rule[0].lstrip("/")).exists()
    ]
    assert not missing, f"CODEOWNERS names paths that do not exist: {missing}"
    assert all(len(rule) >= 2 for rule in rules), "a CODEOWNERS rule without an owner"


@pytest.mark.parametrize("path", WORKFLOWS, ids=lambda path: path.name)
def test_no_workflow_runs_a_stranger_s_code_with_the_repository_s_token(path):
    assert not _triggers(_load(path)) & {"pull_request_target", "workflow_run"}


@pytest.mark.parametrize("path", WORKFLOWS, ids=lambda path: path.name)
def test_the_token_is_read_only(path):
    workflow = _load(path)
    assert workflow.get("permissions") == {"contents": "read"}, (
        f"{path.name}: set `permissions: contents: read` at the top"
    )
    for name, job in workflow["jobs"].items():
        granted = job.get("permissions") or {}
        writes = [scope for scope, level in dict(granted).items() if level == "write"]
        if path.name == "labels.yml":
            # Labels only, and never on a pull request: a stranger's code never holds the token.
            assert writes == ["issues"] and not _triggers(workflow) & {"pull_request"}, path.name
            continue
        assert not writes, f"{path.name} job {name} asks for write access: {writes}"


@pytest.mark.parametrize("path", WORKFLOWS, ids=lambda path: path.name)
def test_forks_never_reach_the_self_hosted_runner(path):
    workflow = _load(path)
    for name, job in workflow["jobs"].items():
        runs_on = str(job.get("runs-on", ""))
        condition = str(job.get("if", ""))
        if "self-hosted" in runs_on:
            assert "refs/heads/main" in condition and "pull_request" not in condition, (
                f"{path.name} job {name}: the self-hosted runner runs only pushes to main"
            )
        # Any runner picked by a repository variable (TEST_RUNNER, formerly CI_RUNNER) can be the
        # Mac mini, so a fork's pull request must be sent to GitHub's runners first.
        if "vars." in runs_on:
            assert FORK_GUARD in runs_on, (
                f"{path.name} job {name}: a fork's pull request must run on GitHub's runners"
            )


@pytest.mark.parametrize("path", WORKFLOWS, ids=lambda path: path.name)
def test_actions_are_pinned_to_a_commit(path):
    used = re.findall(r"uses:\s*([^\s#]+)", path.read_text(encoding="utf-8"))
    loose = [use for use in used if not PINNED.match(use)]
    assert not loose, f"{path.name}: pin these actions to a full commit SHA: {loose}"


HOOK = ROOT / "ci" / "macmini" / "ci-slot-acquire.sh"


@pytest.mark.parametrize(
    ("event", "ref", "repository"),
    [
        ("pull_request", "refs/pull/1/merge", "PlantCraft/PlantCraft"),
        ("pull_request_target", "refs/heads/main", "PlantCraft/PlantCraft"),
        ("push", "refs/heads/feature", "PlantCraft/PlantCraft"),
        ("push", "refs/heads/main", "someone/PlantCraft"),
        ("", "", ""),
    ],
)
def test_the_mac_mini_refuses_every_job_that_is_not_mains(event, ref, repository):
    # The repository is public: a fork's pull request can edit a workflow to ask for the Mac mini,
    # so its runners' job-started hook refuses anything but main's own jobs (ci/macmini/README.md).
    env = {
        "PATH": "/usr/bin:/bin",
        "REPO": "PlantCraft/PlantCraft",
        "GITHUB_EVENT_NAME": event,
        "GITHUB_REF": ref,
        "GITHUB_REPOSITORY": repository,
    }
    done = subprocess.run(["sh", str(HOOK)], env=env, capture_output=True, text=True, check=False)
    assert done.returncode != 0 and "takes only main's jobs" in done.stderr


@pytest.mark.parametrize("event", ["push", "schedule", "workflow_dispatch"])
def test_the_mac_mini_takes_mains_own_jobs(event):
    env = {
        "PATH": "/usr/bin:/bin",
        "REPO": "PlantCraft/PlantCraft",
        "GITHUB_EVENT_NAME": event,
        "GITHUB_REF": "refs/heads/main",
        "GITHUB_REPOSITORY": "plantcraft/plantcraft",
    }
    done = subprocess.run(["sh", str(HOOK)], env=env, capture_output=True, text=True, check=False)
    # Past the guard it waits for a CI slot (ci-slot, only inside the runner's image).
    assert "takes only main's jobs" not in done.stderr
