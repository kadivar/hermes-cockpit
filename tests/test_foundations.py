# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Reference foundations: resume, lend, warm, gate, standup window, authenticator seed."""

import datetime
import json
import os
import time

import pytest

from cockpitlib.cli import main
from cockpitlib.errors import CockpitError
from cockpitlib.lend import approve, ask, deny, inbox_rows, note_block, take_back
from cockpitlib.resume import hook_installed, progress_note, unfinished
from cockpitlib.slots import data_ready, mark_ready, ready_answer, warm_slot
from cockpitlib.window import window_start


def test_resume_note_drops_tool_output_and_finished_runs(monkeypatch, env):
    assert (
        unfinished(
            [
                {"ended": True, "outcome": "crashed"},
                {"ended": True, "outcome": "done"},
                {"ended": False, "outcome": "crashed"},
            ]
        )
        == []
    )
    assert unfinished([{"ended": True, "outcome": "crashed"}])
    note = progress_note(
        [
            {"output": "secret page"},
            {"text": "read the plan"},
            {"command": "gate", "exit": 1},
            {"command": "status", "exit": 0},
            "nope",
        ]
    )
    assert "secret" not in note
    assert "read the plan" in note
    assert "gate exit 1" in note
    assert "status exit 0" in note
    assert progress_note([{"text": "hello world"}], max_chars=5).endswith("…")
    assert progress_note([{"text": "word " * 80}]).endswith("…")
    assert hook_installed()
    import io
    import sys

    monkeypatch.setattr(sys, "stdin", io.StringIO("{"))
    assert main(["resume-context"]) == 0
    monkeypatch.setattr(sys, "stdin", io.StringIO('{"events":[{"text":"kept"}]}'))
    assert main(["resume-context"]) == 0
    from cockpitlib.doctor import run as doctor_run
    from cockpitlib.pack import load

    monkeypatch.setattr("cockpitlib.resume.hook_installed", lambda: False)
    assert "resume hook missing" in doctor_run(load(os.environ["COCKPIT_PACK"]))


def test_window_starts_on_the_last_working_day():
    # moments on this machine's own wall clock, which is the clock the window is counted on: a moment given in a fixed
    # zone is another time of day on a machine elsewhere, and Friday noon was Friday morning on a UTC machine
    monday = datetime.datetime(2026, 10, 19, 9, 0)
    start = window_start(monday, hour=11)
    assert start.weekday() == 4
    assert start.hour == 11
    friday = datetime.datetime(2026, 10, 16, 12, 0)
    assert window_start(friday, hour=11).day == 16


def test_slot_warm_holds_the_lock_and_stores_must_be_present(bare):
    assert warm_slot(1, "TASK-100", "lane:worker-1") == "warming"
    assert warm_slot(1, "TASK-100", "lane:worker-1") == "warming"
    assert ready_answer(1) == "still warming"
    mark_ready(1, "ready")
    assert ready_answer(1) == "ready"
    mark_ready(1, "failed")
    assert ready_answer(1) not in ("ready", "still warming")
    assert data_ready({}) == "ready"
    assert data_ready({"stores": [{"name": "db", "present": False}]}).startswith("not ready")
    assert data_ready({"stores": [{"name": "db", "present": True}]}) == "ready"
    assert ready_answer(9) == "ready"
    assert warm_slot(2, "TASK-200", "lane:worker-1") == "warming"
    lock = os.path.join(os.environ["COCKPIT_VOLUMES"], "slot-2", "lock")
    os.utime(lock, (time.time() - 4000, time.time() - 4000))
    assert warm_slot(2, "TASK-200", "lane:worker-1") == "warming"


def test_gate_refuses_a_second_run_and_hides_known_failures(env, monkeypatch):
    import subprocess

    from cockpitlib import repo_gates as gate_mod
    from cockpitlib.repo_gates import gates_dir, run_gates

    monkeypatch.setenv("COCKPIT_TICKET", "TASK-80")
    pack = {
        "repos": {
            "repos": [{"name": "api", "gates": ["printf 'FAIL Known.one\\n'; exit 1"], "failures": ["^FAIL (\\S+)"]}]
        }
    }
    code, lines = run_gates(pack, "api", record_baseline=True)
    assert code == 1 and "baseline: 1 known failures" in lines
    code, lines = run_gates(pack, "api")
    assert (
        code == 1 and "only known failures (1)" in lines and not any(line.startswith("new failure") for line in lines)
    )
    holder = subprocess.Popen(["sleep", "30"])
    os.makedirs(gates_dir("TASK-80"), exist_ok=True)
    open(os.path.join(gates_dir("TASK-80"), "live.json"), "w", encoding="utf-8").write(
        json.dumps({"id": "live", "status": "running", "pid": holder.pid})
    )
    assert run_gates(pack, "api") == (1, ["gate already running (live)"])
    holder.kill()
    holder.wait()
    assert run_gates(pack, "api")[0] == 1
    monkeypatch.setattr(gate_mod.os, "kill", lambda *_a, **_k: (_ for _ in ()).throw(OSError("gone")))
    assert gate_mod._alive(5) is False


def test_privileged_lend_and_authenticator_seed(env, monkeypatch):
    from cockpitlib.ops import vault_put
    from cockpitlib.pack import load
    from cockpitlib.vault import _items, login_metadata
    from tests.test_vault import seal_ephemeral

    with pytest.raises(CockpitError, match="not sealed"):
        approve("card-1", "tester-1")
    seal_ephemeral(monkeypatch, str(env["home"]))
    pack = load(os.environ["COCKPIT_PACK"])
    assert ask("nope") is None
    assert note_block("nope") == ""
    text = "PRIVILEGED LOGIN NEEDED · staging · open users, then undo · the row needs it"
    assert note_block(text, "card-1") == "asked"
    assert inbox_rows()[0]["options"] == ["Approve this step", "Deny"]
    with pytest.raises(CockpitError, match="no privileged"):
        approve("card-1", "tester-1")
    vault_put(pack, "https://app.acme.test", "admin@acme.test", "s3cret", otp="SEED")
    from cockpitlib.vault import store_login

    assert store_login("https://app.acme.test", "root@acme.test", "s3cret", privileged=True) == "vault stored"
    assert login_metadata()[-1]["two_factor"] is True
    assert "SEED" not in json.dumps(login_metadata())
    from cockpitlib import vault as vault_mod

    real_items = vault_mod._items
    monkeypatch.setattr(vault_mod, "_items", lambda: (_ for _ in ()).throw(CockpitError("unreadable")))
    assert vault_mod._previous("https://app.acme.test", "admin@acme.test") is None
    monkeypatch.setattr(vault_mod, "_items", real_items)
    assert (
        store_login("https://app.acme.test", "admin@acme.test", "")
        == "vault stored for the human: no lane owns this login"
    )
    vault_put(pack, "https://app.acme.test", "admin@acme.test", "next")
    assert _items()[-1]["otp"] == "SEED" or any(item.get("otp") == "SEED" for item in _items())
    assert approve("card-1", "tester-1") == "lent"
    assert inbox_rows() == []
    from cockpitlib.lane_vault import items

    assert [item["label"] for item in items("tester-1")] == ["cockpit lent card-1 root@acme.test"]
    returned = take_back(status_of=lambda _card: ("ready", 0))
    assert returned == []
    assert take_back(now=10**12, status_of=lambda _card: ("ready", 0))
    assert approve("card-1", "tester-1") == "lent"
    assert take_back(status_of=lambda _card: ("blocked", 10**12))
    assert items("tester-1") == []
    open(os.path.join(os.environ["COCKPIT_WORKSPACE"], "hermes", "watch", "blocks.json"), "w", encoding="utf-8").write(
        "{"
    )
    assert inbox_rows() == []
    open(os.path.join(os.environ["COCKPIT_WORKSPACE"], "hermes", "watch", "blocks.json"), "w", encoding="utf-8").write(
        "{}"
    )
    assert inbox_rows() == []
    assert deny("card-1") == "denied"


def test_pack_policy_plan_once_and_write_fence(env, monkeypatch):
    from cockpitlib.egress import check_bound
    from cockpitlib.errors import PackError
    from cockpitlib.pack import load, policy
    from cockpitlib.plan import init, require_decision

    pack = load(os.environ["COCKPIT_PACK"])
    assert policy(pack)["login_scope"] == "lane"
    with pytest.raises(PackError):
        policy({"working_days": ["no"]})
    path = init("TASK-100", "first", "go")
    again = init("TASK-100", "second", "go")
    assert "first" in open(path, encoding="utf-8").read()
    assert again == path
    require_decision("TASK-100")
    with pytest.raises(CockpitError, match="no decision"):
        require_decision("TASK-404")
    monkeypatch.setenv("COCKPIT_LANE", "intake")
    monkeypatch.setenv("COCKPIT_PACK", os.environ["COCKPIT_PACK"])
    assert check_bound("echo ok > /tmp/outside.txt") == "blocked"
    assert check_bound("echo ok") == ""
    from cockpitlib.lanes import profile_dir
    from cockpitlib.setup import seat_drift

    os.makedirs(profile_dir("intake"), exist_ok=True)
    open(os.path.join(profile_dir("intake"), "SOUL.md"), "w", encoding="utf-8").write("different\n")
    assert any(item.startswith("seat drift") for item in seat_drift(pack))
    changed = init("TASK-310", "body", "go with changes: add a row")
    assert "add a row" in open(changed, encoding="utf-8").read()
    with pytest.raises(PackError):
        policy({"refused": "no"})
    with pytest.raises(PackError):
        policy({"logins": "no"})
    with pytest.raises(PackError):
        policy({"stores": "no"})
    pack_stores = dict(pack)
    pack_stores["stores"] = [{"name": "db", "present": False}]
    from cockpitlib.acts import session_open

    with pytest.raises(CockpitError, match="not ready"):
        session_open(pack_stores, 1, "TASK-100")
    from cockpitlib import lanes

    real_seats = lanes.seats_from
    monkeypatch.setattr(lanes, "seats_from", lambda _pack: (_ for _ in ()).throw(RuntimeError("no seats")))
    assert seat_drift(pack)[0].startswith("seat render failed")
    monkeypatch.setattr(lanes, "seats_from", real_seats)
    monkeypatch.setattr("cockpitlib.setup._soul", lambda *_a, **_k: (_ for _ in ()).throw(OSError("disk")))
    assert any("seat render failed" in item for item in seat_drift(pack))
    scratch = str(env["workspace"] / "scratch")
    os.makedirs(scratch, exist_ok=True)
    real_policy = policy

    def with_scratch(loaded):
        parsed = real_policy(loaded)
        parsed["scratch"] = scratch
        parsed["reads"] = ["echo allowed"]
        parsed["hosts"] = ["secret.example"]
        return parsed

    monkeypatch.setattr("cockpitlib.pack.policy", with_scratch)
    monkeypatch.setenv("COCKPIT_LANE", "reviewer")
    assert check_bound(f"echo ok > {scratch}/note.txt") == ""
    assert check_bound("echo allowed stays") == ""
    assert check_bound("curl https://secret.example") == "blocked"
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from dashboard.cockpit.router import router

    app = FastAPI()
    app.include_router(router)
    refused = TestClient(app).post("/kickoff", json={"ticket": "TASK-500", "mode": "rework"})  # a rework needs a plan
    assert refused.status_code == 409 and "plan has no decision" in refused.text


def test_housekeeping_runs_every_step_and_bumps_do_not_double_start(env):
    import sqlite3

    from cockpitlib.acts import _noise_only, audit_bumps, release_bumps, take_bumps
    from cockpitlib.housekeeping import run
    from cockpitlib.kanban import db_path
    from cockpitlib.pack import load
    from cockpitlib.paths import qa

    pack = load(os.environ["COCKPIT_PACK"])
    path = db_path(pack["board"])
    os.makedirs(os.path.dirname(path), exist_ok=True)
    connection = sqlite3.connect(path)
    connection.execute("create table tasks (id text, title text, status text, result text, assignee text)")
    connection.execute("insert into tasks values ('1', 'TASK-100: review', 'review', 'report', 'reviewer')")
    connection.execute("insert into tasks values ('2', 'TASK-100: review', 'blocked', '', 'reviewer')")
    connection.execute("insert into tasks values ('3', 'TASK-100: work', 'ready', '', 'worker-1')")
    connection.commit()
    connection.close()
    folder = os.path.join(qa(), "TASK-100")
    os.makedirs(folder, exist_ok=True)
    open(os.path.join(folder, "test-results.md"), "w", encoding="utf-8").write("Not run\n")
    detail = run(pack)
    assert "settle-reviews: 1" in detail
    assert "unfinished-runs: 1" in detail
    connection = sqlite3.connect(path)
    returned = connection.execute("select assignee, status from tasks where id = '2'").fetchone()
    connection.close()
    assert returned == ("tester-1", "ready")
    assert "warm-waiting: 1" in detail
    assert _noise_only(["docs/readme.md"])
    assert not _noise_only(["src/app.ts"])
    from cockpitlib.acts import _write, bumps_path

    _write(bumps_path(), {"repos": {"api": [{"number": 4, "sha": "abc"}]}, "started": {}, "dismissed": {}})
    take_bumps(pack, "api", "card-a", [4])
    with pytest.raises(CockpitError, match="already started"):
        take_bumps(pack, "api", "card-b", [4])
    assert release_bumps("api", [4])["ok"]
    assert audit_bumps(pack)["missing"] == []
