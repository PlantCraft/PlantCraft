"""The operations driver: backup, restore and their way back, against a recorded Docker."""

import json
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from plantcraft.apps import operations as ops
from plantcraft.apps.installer import InstallError
from tests.test_ops_snapshot import _install, _rows

NOW = datetime(2026, 10, 21, 2, 0, 5, tzinfo=timezone.utc)


class FakeDocker:
    """Answers the calls the driver makes; ``fail`` names calls that fail (``up``, ``tag``)."""

    def __init__(self, histcraft: bool = False):
        self.calls: list[list[str]] = []
        self.images = {"processcraft:0.1.0": "sha256:aaa", "linkcraft:0.1.0": "sha256:bbb"}
        self.histcraft = histcraft
        self.fail: set[str] = set()
        self.containers = [
            {"ID": "c1", "Service": "processcraft", "State": "running", "Health": "healthy",
             "Image": "processcraft:0.1.0"},
            {"ID": "c2", "Service": "linkcraft", "State": "running", "Health": "healthy",
             "Image": "linkcraft:0.1.0"},
        ]  # fmt: skip

    def _done(self, args, code=0, out=""):
        return subprocess.CompletedProcess(args, code, out, "boom" if code else "")

    def image_id(self, ref):
        return self.images.get(ref)

    def run(self, *args, check=True, stdin=None, stdout=None, env=None, timeout=900):
        args = list(args)
        self.calls.append(args)
        verb = next((a for a in args if a in {"ps", "config", "exec", "up", "down", "rm"}), "")
        if args[0] == "compose" and env is not None:
            assert "PLANTCRAFT_VERSION" not in env  # Compose reads the current .env only
        if args[0] == "tag":
            if "tag" in self.fail:
                return self._done(args, 1)
            self.images[args[2]] = args[1]
            return self._done(args)
        if verb == "config" and "json" in args:
            services = {ref.split(":")[0]: {"image": ref} for ref in self.images_in_use()}
            return self._done(args, out=json.dumps({"services": services}))
        if verb == "config":
            return self._done(args, out="\n".join(self.images_in_use()))
        if verb == "ps" and "json" in args:
            return self._done(args, out="\n".join(json.dumps(c) for c in self.containers))
        if verb == "ps":
            return self._done(args, out="abc\n" if self.histcraft else "")
        if args[0] == "inspect":
            found = next((c for c in self.containers if c["ID"] == args[-1]), {})
            return self._done(args, out=self.images.get(found.get("Image", ""), ""))
        if verb == "exec" and "pg_dump" in args:
            Path(stdout).write_bytes(b"PGDMP fake dump")
            return self._done(args)
        if verb == "up" and "up" in self.fail:
            self.fail.discard("up")  # fails once: the way back comes up
            if check:
                raise InstallError("docker compose up failed: container unhealthy")
            return self._done(args, 1)
        return self._done(args)

    def images_in_use(self):
        return ["processcraft:0.1.0", "linkcraft:0.1.0"]

    def verbs(self):
        return [" ".join(a for a in call if not a.startswith(("/", "-f"))) for call in self.calls]


@pytest.fixture()
def driver(tmp_path):
    install = _install(tmp_path / "install")
    docker = FakeDocker()
    clock = iter(NOW + timedelta(seconds=i) for i in range(10_000))
    return ops.Driver(install, docker=docker, project="pc-test", clock=lambda: next(clock))


def test_a_backup_is_taken_verified_indexed_and_keeps_its_images(driver):
    outcome = driver.run("backup", request_id="r1", reason="manual")
    assert outcome["state"] == "ok" and outcome["name"].endswith("-manual")
    listed = json.loads((driver.state / "status" / "backups.json").read_text())["backups"]
    assert listed[0]["name"] == outcome["name"] and listed[0]["state"] == "ok"
    assert listed[0]["suite_version"] == "0.1.0"
    request = json.loads((driver.state / "status" / "requests" / "r1.json").read_text())
    assert request["state"] == "done" and request["name"] == outcome["name"]
    assert driver.docker.images["processcraft:rollback-20261021-020005"] == "sha256:aaa"
    assert not driver.journal.exists()
    history = (driver.install / ".ops" / "history.jsonl").read_text().splitlines()
    assert json.loads(history[-1])["action"] == "backup"
    shown = json.loads((driver.state / "status" / "operations.json").read_text())
    assert shown["operations"][0]["name"] == outcome["name"]
    assert not (driver.state / "status" / "operation.json").exists()


def test_a_backup_refuses_to_fill_the_disk(driver, monkeypatch):
    driver.run("backup", reason="manual")
    monkeypatch.setattr(driver, "free_bytes", lambda: 10)
    outcome = driver.run("backup", reason="manual")
    assert outcome["state"] == "failed" and "not enough free disk" in outcome["message"]


def test_restore_returns_the_data_and_keeps_what_it_replaced(driver):
    name = driver.run("backup", reason="manual")["name"]
    db = driver.install / "data" / "linkcraft" / "linkcraft.sqlite3"
    import sqlite3

    with sqlite3.connect(db) as connection:
        connection.execute("DELETE FROM items")
    outcome = driver.run("restore", request_id="r2", name=name)
    assert outcome["state"] == "ok", outcome
    assert _rows(db) == 50
    aside = driver.backups / outcome["aside"]
    assert _rows(aside / "data" / "linkcraft" / "linkcraft.sqlite3") == 0
    verbs = driver.docker.verbs()
    assert verbs.index(
        "compose --project-name pc-test --project-directory down --remove-orphans"
    ) < (len(verbs) - 1)
    assert any(" up -d --remove-orphans --wait" in verb for verb in verbs)
    listed = {b["name"]: b for b in driver.list_backups()}
    assert listed[outcome["aside"]]["state"] == "aside"
    # What the installer reports belongs to now: carried across the restore.
    request = json.loads((driver.state / "status" / "requests" / "r2.json").read_text())
    assert request["state"] == "done" and request["aside"] == outcome["aside"]


def test_a_restore_from_a_bigger_machine_fits_the_cpu_limits_to_this_host(driver, monkeypatch):
    # 31/10 test day: a backup from a 4-CPU server failed to start on a 2-CPU one
    # ("range of CPUs is from 0.01 to 2.00").
    (driver.install / "compose.yaml").write_text(
        'services:\n  a:\n    cpus: "${PLANTCRAFT_CPUS:-1}"\n'
        '  b:\n    cpus: "${LINKCRAFT_EXECUTOR_CPUS:-4}"\n  c:\n    cpus: "${HISTCRAFT_CPUS:-1.5}"\n'
    )
    env = driver.install / ".env"
    env.write_text(env.read_text() + "PLANTCRAFT_CPUS=4\nHISTCRAFT_CPUS=1\n")
    name = driver.run("backup", reason="manual")["name"]
    monkeypatch.setattr(ops, "host_cpus", lambda: 2)
    outcome = driver.run("restore", name=name)
    assert outcome["state"] == "ok", outcome
    values = ops.env_values(env)
    assert values["PLANTCRAFT_CPUS"] == "2"  # set above the host: capped
    assert values["LINKCRAFT_EXECUTOR_CPUS"] == "2"  # default above the host: written
    assert values["HISTCRAFT_CPUS"] == "1"  # fits: untouched
    assert env.read_text().count("PLANTCRAFT_CPUS=") == 1


def test_fit_cpu_limits_leaves_a_host_with_enough_cpus_alone(tmp_path):
    (tmp_path / "compose.yaml").write_text('x:\n  cpus: "${LINKCRAFT_EXECUTOR_CPUS:-4}"\n')
    (tmp_path / ".env").write_text("A=1\n")
    assert ops.fit_cpu_limits(tmp_path, 8) == {}
    assert (tmp_path / ".env").read_text() == "A=1\n"
    assert ops.fit_cpu_limits(tmp_path, 3) == {"LINKCRAFT_EXECUTOR_CPUS": "4"}
    assert (tmp_path / ".env").read_text() == "A=1\nLINKCRAFT_EXECUTOR_CPUS=3\n"


def test_a_restore_that_does_not_come_up_returns_by_itself(driver):
    name = driver.run("backup", reason="manual")["name"]
    db = driver.install / "data" / "linkcraft" / "linkcraft.sqlite3"
    import sqlite3

    with sqlite3.connect(db) as connection:
        connection.execute("DELETE FROM items WHERE id > 10")
    driver.docker.fail.add("up")
    outcome = driver.run("restore", name=name)
    assert outcome["state"] == "failed"
    assert "returned to its state before it" in outcome["message"]
    assert _rows(db) == 10  # the state before the restore, not the backup


def test_restore_refuses_a_damaged_backup_without_stopping_anything(driver):
    name = driver.run("backup", reason="manual")["name"]
    archive = driver.backups / name / "data.tar.gz"
    archive.write_bytes(archive.read_bytes()[:-10])
    outcome = driver.run("restore", name=name)
    assert outcome["state"] == "failed" and "nothing changed" in outcome["message"]
    assert not any(" down " in f" {verb} " for verb in driver.docker.verbs())


def test_unknown_names_are_refused(driver):
    assert "no backup named" in driver.run("restore", name="../../etc")["message"]
    assert "no backup named" in driver.run("verify", name="20261021-020000-nope")["message"]


def test_an_interrupted_restore_is_undone_on_the_next_run(driver):
    name = driver.run("backup", reason="manual")["name"]
    folder = driver._folder(name)
    driver.operation = {"action": "restore", "name": name}
    aside = driver.backups / "20261021-030000-before-restore"
    driver.phase("stopping the suite", aside=aside.name, images=driver.images())
    ops.snapshot.restore(folder, driver.install, aside)  # the driver died after this
    (driver.install / "data" / "linkcraft" / "half.txt").write_text("half")
    outcome = driver.resume()
    assert outcome["state"] == "failed" and "interrupted" in outcome["message"]
    assert not (driver.install / "data" / "linkcraft" / "half.txt").exists()
    assert not driver.journal.exists()


def _backup(name, state="ok"):
    return {"name": name, "state": state, "reason": name[16:]}


def test_retention_keeps_the_newest_of_each_kind():
    now = datetime(2026, 10, 21, 3, 0, tzinfo=timezone.utc)
    daily = [
        _backup((now - timedelta(days=day)).strftime("%Y%m%d-020000") + "-daily")
        for day in range(0, 120)
    ]
    others = [
        _backup("20260901-100000-pre-update"),
        _backup("20261001-100000-pre-update"),
        _backup("20261020-100000-manual", state="failed"),
        _backup("20261001-100000-manual", state="failed"),
        _backup("20261019-100000-before-restore", state="aside"),
        _backup("20261018-100000-before-restore", state="aside"),
        _backup("20261017-100000-before-restore", state="aside"),
    ]
    removed = set(ops.to_delete(daily + others, now))
    kept_daily = [b["name"] for b in daily if b["name"] not in removed]
    assert all(b["name"] not in removed for b in daily[:7])
    assert 7 <= len(kept_daily) <= 7 + 4 + 3
    assert "20261001-100000-pre-update" not in removed
    assert "20260901-100000-pre-update" not in removed  # removed only with its update
    assert "20261020-100000-manual" not in removed  # a failed one stays a week to be read
    assert "20261001-100000-manual" in removed
    assert "20261017-100000-before-restore" in removed
    assert "20261018-100000-before-restore" not in removed


def test_retention_never_removes_the_only_good_backup():
    now = datetime(2027, 1, 1, tzinfo=timezone.utc)
    assert ops.to_delete([_backup("20261001-100000-manual")], now) == []


def test_the_daily_backup_is_due_once_a_day_after_its_hour(tmp_path):
    settings = ops.schedule_settings(tmp_path / "missing.json")
    assert settings == ops.DEFAULT_SCHEDULE
    early = datetime(2026, 10, 21, 1, 59, tzinfo=timezone.utc)
    late = datetime(2026, 10, 21, 2, 1, tzinfo=timezone.utc)
    assert not ops.due(settings, None, early)
    assert ops.due(settings, None, late)
    assert not ops.due(settings, "2026-10-21", late)
    path = tmp_path / "ops-settings.json"
    path.write_text(json.dumps({"backup": {"enabled": False, "daily_at": "25:00", "timezone": 3}}))
    assert ops.schedule_settings(path) == {**ops.DEFAULT_SCHEDULE, "enabled": False}
    assert not ops.due(ops.schedule_settings(path), None, late)


def test_the_driver_runs_without_network_as_root_with_the_install_folder(tmp_path):
    command = ops.driver_command(tmp_path, "processcraft-installer:0.2.0", ["drive", "backup"],
                                 detach=True, project="processcraft")  # fmt: skip
    text = " ".join(command)
    assert "--network none" in text and "--name processcraft-ops" in text
    assert f"-v {tmp_path}:{tmp_path}" in text and "--cap-drop ALL" in text
    assert "--read-only" in text and "no-new-privileges:true" in text


def test_the_drill_is_due_weekly_after_its_hour():
    settings = dict(ops.DEFAULT_SCHEDULE)
    sunday = datetime(2026, 10, 25, 3, 30, tzinfo=timezone.utc)
    assert ops.drill_due(settings, None, sunday)
    assert not ops.drill_due(settings, ops.local_week(settings, sunday), sunday)
    assert not ops.drill_due(settings, None, sunday.replace(hour=2))
    assert not ops.drill_due(settings, None, sunday - timedelta(days=1))
    assert not ops.drill_due({**settings, "drill": False}, None, sunday)


def test_the_drill_guard_finds_anything_that_reaches_the_live_suite(driver, tmp_path):
    target = driver.backups / ".drill-x" / "install"
    config = {
        "services": {
            "ok": {
                "volumes": [{"source": f"{target}/data/ok"}],
                "ports": [{"host_ip": "127.0.0.1", "published": "0"}],
            },
            "live": {"volumes": [{"source": f"{driver.install}/data/linkcraft"}]},
            "socket": {"volumes": [{"source": "/var/run/docker.sock"}]},
            # The installer holds the socket too, but the drill never starts it.
            "installer": {"volumes": [{"source": "/var/run/docker.sock"}]},
            "open": {"ports": [{"host_ip": "0.0.0.0", "published": "443"}]},
        },
        "networks": {"apps": {"internal": True}, "plant": {}},
    }
    problems = driver.drill_guard(config, target)
    assert any("live mounts the live folder" in p for p in problems)
    assert any("socket mounts the Docker socket" in p for p in problems)
    assert any("open publishes a port on 0.0.0.0" in p for p in problems)
    assert "network plant is not internal" in problems
    assert not any(p.startswith(("ok ", "installer ")) for p in problems)


def test_the_drill_refuses_when_memory_is_short(driver, monkeypatch):
    driver.run("backup", reason="manual")
    monkeypatch.setattr(ops.Driver, "available_memory", staticmethod(lambda: 2**20))
    outcome = driver.run("drill")
    assert outcome["state"] == "failed" and "not enough free memory" in outcome["message"]


def test_health_wants_every_service_running_healthy_and_on_its_image(driver):
    assert driver.health() == []
    driver.docker.containers[1]["Health"] = "unhealthy"
    driver.docker.images["processcraft:0.1.0"] = "sha256:new"  # the settings name a new image
    driver.docker.images["old"] = "sha256:aaa"
    driver.docker.containers[0]["Image"] = "old"
    assert driver.health() == [
        "linkcraft: unhealthy",
        "processcraft: runs another image than processcraft:0.1.0",
    ]
    driver.docker.containers.pop()
    assert "linkcraft: no container" in driver.health()


def test_an_update_is_recorded_for_the_updates_page_and_the_history(driver):
    outcome = driver.note_update(**{"from": "0.1.0", "to": "0.2.0", "state": "returned",
                                    "message": "unhealthy", "backup": "b1"})  # fmt: skip
    assert outcome["state"] == "returned"
    shown = json.loads((driver.state / "status" / "update.json").read_text())
    assert shown["from"] == "0.1.0" and shown["to"] == "0.2.0" and shown["backup"] == "b1"
    history = json.loads((driver.state / "status" / "operations.json").read_text())["operations"]
    assert history[0]["action"] == "update" and history[0]["message"] == "unhealthy"


def test_latest_names_the_newest_good_backup_of_a_reason(driver, monkeypatch, capsys):
    first = driver.run("backup", reason="pre-update")["name"]
    driver.run("backup", reason="manual")
    monkeypatch.setenv("PLANTCRAFT_INSTALL_DIR", str(driver.install))
    capsys.readouterr()
    assert ops.main(["latest", "--reason", "pre-update"]) == 0
    assert capsys.readouterr().out.strip() == first
    assert ops.main(["latest", "--reason", "daily"]) == 1
    assert ops.main(["latest", "--reason", "pre-update", "--before", "0.1.0"]) == 1  # same version
    assert ops.main(["latest", "--reason", "pre-update", "--before", "0.2.0"]) == 0


def test_the_installed_release_is_published_for_the_updates_page(driver):
    (driver.install / "release.json").write_text(json.dumps({"version": "0.2.0"}))
    (driver.install / "RELEASE-NOTES.md").write_text("# PlantCraft 0.2.0\n")
    driver.index()
    shown = json.loads((driver.state / "status" / "release.json").read_text())
    assert shown["release"] == {"version": "0.2.0"} and shown["notes"].startswith("# PlantCraft")
    assert shown["version"] == "0.1.0"  # what .env runs
