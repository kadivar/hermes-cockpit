# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""A slot's runtime: its verbs, its lock, its helpers, and when a ticket's copy is warmed or stopped."""

import json
import os
import re

import pytest

from cockpitlib.cli import main
from cockpitlib.errors import CockpitError
from cockpitlib.pack import load
from tests.support.boards import put_card
from tests.support.both_packs import PACKS, _client


@pytest.mark.parametrize("pack_file", PACKS)
def test_a_ticket_that_has_a_slot_is_not_warmed_again(env, pack_file, monkeypatch):
    import time

    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    pack = load(pack_file)
    other = load(PACKS[0] if pack["name"] == "bravo" else PACKS[1])
    store = pack["stores"][0]["name"]
    assert store != other["stores"][0]["name"]
    from cockpitlib.housekeeping import _has_slot, warm_waiting

    assert _has_slot("", 2) is False
    from cockpitlib.kanban import place_card
    from cockpitlib.slots import read_owner, read_ticket, write_owner, write_ticket

    shaped = dict(pack)
    shaped["seats"] = dict(pack["seats"])
    shaped["seats"]["slots"] = 2
    shaped["stores"] = [
        dict(
            pack["stores"][0],
            present=True,
            capacity=pack["stores"][0]["capacity"],
            have=list(pack["stores"][0].get("names") or pack["stores"][0].get("have") or ["app"]),
        )
    ]
    place_card(shaped["board"], "TASK-8870: work", "worker-1", "ready")
    time.sleep(0.01)
    place_card(shaped["board"], "TASK-8871: test", "tester-1", "ready")
    time.sleep(0.01)
    place_card(shaped["board"], "TASK-8872: review", "reviewer", "ready")
    write_owner(1, "lane:worker-1")
    write_ticket(1, "TASK-8870")
    write_owner(2, "free")
    write_ticket(2, "TASK-8869")
    assert warm_waiting(shaped) == "0"
    assert read_ticket(1) == "TASK-8870"
    assert read_ticket(2) == "TASK-8869"
    write_ticket(2, "")
    assert warm_waiting(shaped) == "1"
    assert read_ticket(1) == "TASK-8870"
    assert read_ticket(2) == "TASK-8871"
    assert read_owner(2) == "lane:tester-1"
    assert read_owner(1) == "lane:worker-1"
    from cockpitlib.slots import check_access, provider_for

    with pytest.raises(CockpitError, match="pipeline"):
        check_access(2, "TASK-8871")
    assert 2 not in provider_for(pack.get("slot_provider") or "none").gc(60, 2)
    assert read_owner(2) == "lane:tester-1"
    assert other["stores"][0]["name"] not in read_owner(2)
    shaped["seats"]["slots"] = 3
    write_owner(1, "free")
    write_ticket(1, "")
    write_owner(3, "free")
    write_ticket(3, "")
    place_card(shaped["board"], "TASK-8875: work", "worker-2", "ready")
    time.sleep(0.01)
    place_card(shaped["board"], "TASK-8876: test", "tester-2", "ready")
    assert warm_waiting(shaped) == "2"
    taken = {read_ticket(1), read_ticket(3)}
    assert "" not in taken and len(taken) == 2
    assert read_ticket(2) == "TASK-8871"
    assert other["name"] not in read_owner(1) and other["name"] not in read_owner(3)
    shaped["seats"]["slots"] = 4
    write_owner(4, "free")
    write_ticket(4, "")
    import sqlite3

    class _Boom:
        def execute(self, *_args, **_kwargs):
            raise sqlite3.Error("down")

        def close(self):
            return None

    monkeypatch.setattr("cockpitlib.housekeeping._db", lambda _pack: _Boom())
    with pytest.raises(RuntimeError, match="down"):
        warm_waiting(shaped)


@pytest.mark.parametrize("pack_file", PACKS)
def test_a_person_row_is_handed_over_last(env, pack_file):
    pack = load(pack_file)
    other = load(PACKS[0] if pack["name"] == "bravo" else PACKS[1])
    assert pack["name"] != other["name"]
    from cockpitlib.acts import post_test_plan
    from cockpitlib.paths import qa
    from cockpitlib.slots import state_dir, write_ticket

    ticket = "TASK-1025"
    write_ticket(1, ticket)
    login = os.path.join(state_dir(1), "login.json")
    os.makedirs(os.path.dirname(login), exist_ok=True)
    open(login, "w", encoding="utf-8").write(f"session {pack['name']}\n")
    link = f"https://{pack['name']}.test/row"
    posted = post_test_plan(pack, ticket, f"lane checks {pack['name']}\n\n👤 sign in {link}\n")
    assert posted["blocked"] is True
    handed = json.loads(open(os.path.join(qa(), ticket, "human-rows.json"), encoding="utf-8").read())
    assert handed[0]["human"] is False
    assert handed[-1]["human"] is True and handed[-1]["logged_out"] is True
    assert handed[-1]["links"] == [link]
    assert handed[-1]["steps"] == [f"👤 sign in {link}"]
    assert other["name"] not in json.dumps(handed)
    assert not os.path.isfile(login)
    quiet = post_test_plan(pack, "TASK-1026", f"only the lane {pack['name']}\n")
    assert quiet["blocked"] is True
    assert not os.path.isfile(os.path.join(qa(), "TASK-1026", "human-rows.json"))


@pytest.mark.parametrize("pack_file", PACKS)
def test_an_empty_copy_is_not_warmed(env, pack_file):
    pack = load(pack_file)
    other = load(PACKS[0] if pack["name"] == "bravo" else PACKS[1])
    assert pack["stores"][0]["name"] != other["stores"][0]["name"]
    from cockpitlib.acts import begin_change
    from cockpitlib.housekeeping import warm_waiting
    from cockpitlib.kanban import place_card
    from cockpitlib.slots import _stores_path, read_ticket, write_owner, write_ticket

    shaped = dict(pack)
    shaped["seats"] = dict(pack["seats"])
    shaped["seats"]["slots"] = 1
    place_card(shaped["board"], "TASK-8873: work", "worker-1", "ready")
    path = _stores_path(1)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    json.dump([], open(path, "w", encoding="utf-8"))
    write_owner(1, "free")
    write_ticket(1, "")
    assert warm_waiting(shaped) == "0"
    assert read_ticket(1) == ""
    with pytest.raises(CockpitError, match="not ready empty copy"):
        begin_change(shaped, "TASK-8874", "read the ticket", "lane:intake")
    assert read_ticket(1) == ""
    shaped["seats"]["slots"] = 2
    write_owner(2, "free")
    write_ticket(2, "")
    assert warm_waiting(shaped) == "1"
    assert read_ticket(1) == ""
    assert read_ticket(2) == "TASK-8873"


@pytest.mark.parametrize("pack_file", PACKS)
def test_session_open_stays_unmarked_when_the_copy_is_empty(env, pack_file, monkeypatch):
    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    pack = load(pack_file)
    other = load(PACKS[0] if pack["name"] == "bravo" else PACKS[1])
    assert pack["stores"][0]["name"] != other["stores"][0]["name"]
    from cockpitlib.acts import session_open
    from cockpitlib.paths import qa
    from cockpitlib.slots import _stores_path, read_ticket

    monkeypatch.setattr("cockpitlib.ops.worktree_add", lambda *_args, **_kwargs: [])
    quiet = dict(pack)
    quiet["slot_browser"] = []
    quiet["dev_servers"] = []
    path = _stores_path(1)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    json.dump([], open(path, "w", encoding="utf-8"))
    with pytest.raises(CockpitError, match="not ready empty copy"):
        session_open(quiet, 1, "TASK-886")
    assert not os.path.isfile(os.path.join(qa(), "TASK-886", "session.json"))
    assert read_ticket(1) in ("",)
    json.dump([dict(pack["stores"][0])], open(path, "w", encoding="utf-8"))
    assert session_open(quiet, 1, "TASK-886").startswith("session")
    assert read_ticket(1) == "TASK-886"


@pytest.mark.parametrize("pack_file", PACKS)
def test_halt_reclaims_the_slot_and_archive_removes_the_checkout(env, pack_file, monkeypatch):
    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    from cockpitlib.acts import archive_ticket, halt_ticket, resume_ticket
    from cockpitlib.intents import path_of
    from cockpitlib.kanban import board_cards
    from cockpitlib.outbox import create
    from cockpitlib.paths import qa
    from cockpitlib.slots import read_owner, read_ticket, write_owner, write_ticket
    from cockpitlib.worktree import dest

    pack = load(pack_file)
    other = load(PACKS[0] if pack["name"] == "bravo" else PACKS[1])
    ticket = "TASK-970"
    card = put_card(pack["board"], f"{ticket}: worker", "worker-1", "running")
    write_owner(1, "lane:worker-1")
    write_ticket(1, ticket)
    from cockpitlib.slots import start_slot_runtime

    seconds = str(int(pack["hours"]["standup"]))
    assert seconds != str(int(other["hours"]["standup"]))
    pack["slot_browser"] = ["sleep", seconds]
    pack["dev_servers"] = [
        ["python3", "-c", "import signal,time; signal.signal(signal.SIGTERM, signal.SIG_IGN); time.sleep(30)"]
    ]
    started = start_slot_runtime(pack, 1)
    assert started["browser_command"] == ["sleep", seconds]
    checkout = dest(ticket, "api")
    os.makedirs(checkout, exist_ok=True)
    open(os.path.join(checkout, "README"), "w", encoding="utf-8").write("kept\n")
    intent = create(
        pack, ticket, "push-branch", card, "ship", {"repo": pack["repos"]["repos"][0]["name"], "branch": "main"}
    )
    evidence = os.path.join(qa(), ticket, "note.txt")
    os.makedirs(os.path.dirname(evidence), exist_ok=True)
    open(evidence, "w", encoding="utf-8").write("evidence\n")
    import time

    time.sleep(0.01)
    intake = put_card(pack["board"], f"{ticket}: intake", "intake", "running")
    try:
        lines = halt_ticket(pack, ticket, "pause")
        assert "reclaimed slot 1" in lines
        assert any(line.startswith("held ") for line in lines)
        assert read_owner(1) == "free" and read_ticket(1) == ""
        with pytest.raises(OSError):
            os.kill(started["browser"], 0)
        with pytest.raises(OSError):
            os.kill(started["servers"][0], 0)
    finally:
        import signal

        for pid in [started["browser"], *started["servers"]]:
            try:
                os.kill(pid, signal.SIGKILL)
            except OSError:
                pass
    assert os.path.isfile(os.path.join(checkout, "README"))
    assert any(item["id"] == card and item["status"] == "done" for item in board_cards(pack["board"]))
    import sqlite3

    from cockpitlib.intents import load as load_held
    from cockpitlib.kanban import db_path

    connection = sqlite3.connect(db_path(pack["board"]))
    kinds = [
        row[0] for row in connection.execute("select kind from task_events where task_id = ? order by id", (card,))
    ]
    connection.close()
    assert "reclaimed" in kinds and kinds.index("reclaimed") < kinds.index(
        "completed"
    )  # the running worker is stopped first
    assert load_held(intent["id"])["status"] == "held" and load_held(intent["id"])["hold"]["waits"] == "human"
    from cockpitlib.acts import finish_intake
    from cockpitlib.errors import Conflict

    with pytest.raises(Conflict, match="halted"):
        finish_intake(pack, intake, f"proposal {pack['name']}")
    assert any(item["id"] == intake and item["status"] == "done" for item in board_cards(pack["board"]))
    assert not os.path.isfile(os.path.join(qa(), ticket, "proposal.md"))
    blocked = _client().post("/kickoff", json={"ticket": ticket, "mode": "intake"})
    assert blocked.status_code == 409 and "halted" in blocked.text
    from cockpitlib.errors import Conflict

    repo = pack["repos"]["repos"][0]["name"]
    other_repo = other["repos"]["repos"][0]["name"]
    assert repo != other_repo
    with pytest.raises(Conflict, match="halted"):
        create(pack, ticket, "push-branch", "c", "ship", {"repo": repo, "branch": "main"})
    from cockpitlib.ops import worktree_add as add_checkout
    from cockpitlib.slots import slot_up

    with pytest.raises(Conflict, match="halted"):
        add_checkout(pack, ticket, repo)
    with pytest.raises(Conflict, match="halted"):
        slot_up(1, ticket, pack)
    assert read_owner(1) == "free" and read_ticket(1) == ""
    client = _client()
    sent = client.post("/refusal-send-back", json={"ticket": ticket})
    assert sent.status_code == 409 and "halted" in sent.text
    returned = client.post("/return", json={"id": intent["id"], "instruction": "fix"})
    assert returned.status_code == 400 and "halted" in returned.text
    assert all(": rework" not in (item.get("title") or "") for item in board_cards(pack["board"]))
    other_ticket = f"{pack['tracker']['project']}-971"
    kept = create(pack, other_ticket, "push-branch", "c", "ship", {"repo": repo, "branch": "main"})
    assert kept["ticket"] == other_ticket and kept["status"] == "pending"
    assert other_repo not in kept["payload"]["repo"]
    from cockpitlib.acts import begin_change, post_test_plan, session_handoff, session_open

    with pytest.raises(Conflict, match="halted"):
        begin_change(pack, ticket, f"read {pack['name']}", "intake")
    assert not os.path.isfile(os.path.join(qa(), ticket, "ticket.md"))
    with pytest.raises(Conflict, match="halted"):
        post_test_plan(pack, ticket, f"plan {pack['name']}")
    assert not os.path.isfile(os.path.join(qa(), ticket, "test-kickoff.md"))
    assert all(": test kickoff" not in (item.get("title") or "") for item in board_cards(pack["board"]))
    write_owner(1, "human")
    write_ticket(1, ticket)
    with pytest.raises(Conflict, match="halted"):
        session_handoff(pack, 1, "worker-1")
    assert read_owner(1) == "human"
    assert all(item.get("title") != f"{ticket}: work" for item in board_cards(pack["board"]))
    with pytest.raises(Conflict, match="halted"):
        session_open(pack, 1, ticket)
    assert read_owner(1) == "human" and read_ticket(1) == ticket
    assert not os.path.isfile(os.path.join(qa(), ticket, "session.json"))
    from cockpitlib.acts import mark_ci, open_analyst

    before_cards = len(board_cards(pack["board"]))
    assert open_analyst(pack, "ci", ticket, sha="abc") == ""
    assert len(board_cards(pack["board"])) == before_cards
    with pytest.raises(Conflict, match="halted"):
        mark_ci(pack, ticket, "abc", "real", repo)
    titles = [item.get("title") for item in board_cards(pack["board"])]
    assert titles.count(f"{ticket}: intake") == 1
    diagnosed = open_analyst(pack, "ci", other_ticket, sha="abc")
    assert diagnosed
    assert any(item["id"] == diagnosed and item["ticket"] == other_ticket for item in board_cards(pack["board"]))
    write_owner(1, "free")
    write_ticket(1, "")
    assert resume_ticket(ticket).startswith("resumed")
    released = create(pack, ticket, "push-branch", "c", "ship", {"repo": repo, "branch": f"work/{ticket}"})
    assert released["status"] == "pending" and released["payload"]["repo"] == repo
    assert any(item["id"] == card and item["status"] == "done" for item in board_cards(pack["board"]))
    opened = _client().post("/kickoff", json={"ticket": ticket, "mode": "intake"})
    assert opened.status_code == 200
    assert any(item["id"] == card and item["status"] == "done" for item in board_cards(pack["board"]))
    archive_ticket(pack, ticket)
    assert not os.path.isdir(checkout)
    assert os.path.isfile(path_of(intent["id"]))
    assert os.path.isfile(evidence)


@pytest.mark.parametrize("pack_file", PACKS)
def test_open_starts_the_pack_browser(env, pack_file):
    import signal
    import subprocess

    pack = load(pack_file)
    other = load(PACKS[0] if pack["name"] == "bravo" else PACKS[1])
    assert pack["slot_browser"] != other["slot_browser"]
    assert pack["dev_servers"] != other["dev_servers"]
    git_env = os.environ.copy()
    git_env.update(
        {
            "GIT_AUTHOR_NAME": "Dev",
            "GIT_AUTHOR_EMAIL": "dev@example.test",
            "GIT_COMMITTER_NAME": "Dev",
            "GIT_COMMITTER_EMAIL": "dev@example.test",
        }
    )
    for repo in pack["repos"]["repos"]:
        source = env["root"] / "repos" / repo["name"]
        source.mkdir(parents=True, exist_ok=True)
        if (source / ".git").exists():
            continue
        subprocess.run(["git", "init", str(source)], check=True, capture_output=True)
        (source / "README").write_text(f"{pack['name']}\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(source), "add", "README"], check=True, capture_output=True)
        subprocess.run(["git", "-C", str(source), "commit", "-m", "init"], check=True, capture_output=True, env=git_env)
    from cockpitlib.acts import session_close, session_open
    from cockpitlib.slots import _read_runtime, _runtime_path

    pids = []
    try:
        assert session_open(pack, 1, "TASK-9964").startswith("session")
        from cockpitlib.slots import bringup

        assert bringup(1, pack) == "ready"
        record = _read_runtime(1)
        assert record["browser_command"] == [str(part) for part in pack["slot_browser"]]
        assert record["server_commands"] == [[str(part) for part in command] for command in pack["dev_servers"]]
        assert (
            other["slot_browser"][0] not in record["browser_command"] or pack["slot_browser"] == other["slot_browser"]
        )
        assert other["name"] not in " ".join(record["browser_command"])
        pids = [record.get("browser"), *(record.get("servers") or [])]
        assert session_close(pack, 1).startswith("closed")
        assert not os.path.isfile(_runtime_path(1))
    finally:
        for pid in pids:
            if not pid:
                continue
            try:
                os.kill(int(pid), signal.SIGKILL)
            except OSError:
                pass


@pytest.mark.parametrize("pack_file", PACKS)
def test_change_kickoff_warms_after_the_read_and_before_the_trace(env, pack_file, monkeypatch):
    from cockpitlib.acts import begin_change
    from cockpitlib.paths import qa
    from cockpitlib.slots import warm_slot, write_owner

    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    pack = load(pack_file)
    ticket = "TASK-991"
    seen = []

    def spy(slot, bound, owner, pack=None):
        folder = os.path.join(qa(), bound)
        assert os.path.isfile(os.path.join(folder, "ticket.md"))
        assert not os.path.isfile(os.path.join(folder, "trace.md"))
        seen.append(slot)
        return warm_slot(slot, bound, owner, pack)

    monkeypatch.setattr("cockpitlib.slots.warm_slot", spy)
    blank = _client().post("/kickoff", json={"mode": "intake"})
    assert blank.status_code == 409 and "no ticket" in blank.text
    with pytest.raises(CockpitError, match="no ticket"):
        begin_change(pack, "  ", "text", "intake")
    with pytest.raises(CockpitError, match="no free slot"):
        begin_change({"seats": {"slots": 0}}, ticket, "text", "intake")
    opened = _client().post("/kickoff", json={"ticket": ticket, "mode": "intake", "prompt": "the report is wrong"})
    assert opened.status_code == 200
    assert seen == [1]
    folder = os.path.join(qa(), ticket)
    assert open(os.path.join(folder, "ticket.md"), encoding="utf-8").read() == "the report is wrong\n"
    assert open(os.path.join(folder, "trace.md"), encoding="utf-8").read() == "trace after slot 1\n"
    write_owner(1, "human")
    with pytest.raises(CockpitError, match="no free slot"):
        begin_change(pack, "TASK-992", "again", "intake")
    assert os.path.isfile(os.path.join(qa(), "TASK-992", "ticket.md"))
    assert not os.path.isfile(os.path.join(qa(), "TASK-992", "trace.md"))


def test_stop_clears_a_bad_runtime_record(env, monkeypatch):
    from cockpitlib.slots import _stop_pid, state_dir, stop_slot_runtime

    folder = state_dir(2)
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, "runtime.json")
    open(path, "w", encoding="utf-8").write("{")
    assert stop_slot_runtime(2) == {"browser": None, "servers": []}
    open(path, "w", encoding="utf-8").write("[]")
    assert stop_slot_runtime(2)["servers"] == []
    _stop_pid(None)
    _stop_pid(999999)
    monkeypatch.setattr("cockpitlib.slots.os.kill", lambda *_args, **_kwargs: None)

    def _gone(*_args, **_kwargs):
        raise OSError("gone")

    monkeypatch.setattr("cockpitlib.slots.os.waitpid", _gone)
    _stop_pid(1)


@pytest.mark.parametrize("pack_file", PACKS)
def test_garbage_collection_stops_an_idle_slot_runtime(env, pack_file):
    import signal

    from cockpitlib.slots import claim, provider_for, read_owner, start_slot_runtime, state_dir, write_owner

    pack = load(pack_file)
    seconds = str(int(pack["hours"]["standup"]))
    pack["slot_browser"] = ["sleep", seconds]
    write_owner(1, "human")
    human = start_slot_runtime(pack, 1)
    write_owner(2, "lane:worker-1")
    claim(2)
    fresh = start_slot_runtime(pack, 2)
    write_owner(3, "lane:worker-1")
    idle = start_slot_runtime(pack, 3)
    pids = [human["browser"], fresh["browser"], idle["browser"]]
    try:
        assert human["browser_command"] == ["sleep", seconds]
        collected = provider_for(pack.get("slot_provider") or "none").gc(60, 3)
        assert collected == [3]
        assert read_owner(1) == "human"
        assert read_owner(2).startswith("lane:")
        assert read_owner(3) == "free"
        assert not os.path.isfile(os.path.join(state_dir(3), "runtime.json"))
        os.kill(human["browser"], 0)
        os.kill(fresh["browser"], 0)
        with pytest.raises(OSError):
            os.kill(idle["browser"], 0)
    finally:
        for pid in pids:
            try:
                os.kill(pid, signal.SIGTERM)
                os.waitpid(pid, 0)
            except OSError:
                pass


@pytest.mark.parametrize("pack_file", PACKS)
def test_the_next_up_applies_the_pack_store_rules(env, pack_file, monkeypatch):
    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    monkeypatch.delenv("COCKPIT_LANE", raising=False)
    pack = load(pack_file)
    other = load(PACKS[0] if pack["name"] == "bravo" else PACKS[1])
    store = pack["stores"][0]
    assert store["name"] != other["stores"][0]["name"]
    from cockpitlib.slots import _stores_path, data_ready, slot_up, state_dir

    folder = state_dir(1)
    os.makedirs(folder, exist_ok=True)
    have = [str(label) for label in (store.get("have") or [])]
    have.append(f"kept-{pack['name']}")
    json.dump(
        [
            {
                "name": store["name"],
                "present": True,
                "capacity": 0,
                "minimum": 99,
                "names": ["stale"],
                "have": have,
            }
        ],
        open(_stores_path(1), "w", encoding="utf-8"),
    )
    ticket = f"{pack['tracker']['project']}-1046"
    slot_up(1, ticket, pack)
    written = json.load(open(_stores_path(1), encoding="utf-8"))
    assert written[0]["capacity"] == store["capacity"]
    assert written[0]["minimum"] == int(store.get("minimum") or 0)
    assert written[0]["names"] == [str(label) for label in (store.get("names") or [])]
    assert f"kept-{pack['name']}" in written[0]["have"]
    assert "stale" not in written[0]["names"]
    assert all(row["name"] != other["stores"][0]["name"] for row in written)
    assert data_ready(pack, 1) == "ready"


@pytest.mark.parametrize("pack_file", PACKS)
def test_reset_restores_the_provider_baseline(env, pack_file, monkeypatch):
    import signal

    from cockpitlib.acts import cleanup_settings, session_open
    from cockpitlib.paths import qa
    from cockpitlib.slots import NoneProvider, start_slot_runtime, state_dir, write_ticket

    pack = load(pack_file)
    monkeypatch.setattr("cockpitlib.ops.worktree_add", lambda *_args, **_kwargs: [])
    session_open(pack, 1, "TASK-994")
    stores_path = os.path.join(state_dir(1), "stores.json")
    stores = json.load(open(stores_path, encoding="utf-8"))
    assert stores[0]["name"] == pack["stores"][0]["name"]
    stores[0]["present"] = False
    stores[0]["capacity"] = 0
    json.dump(stores, open(stores_path, "w", encoding="utf-8"))
    open(os.path.join(state_dir(1), "state"), "w", encoding="utf-8").write("failed\n")
    seconds = str(int(pack["hours"]["standup"]))
    pack["slot_browser"] = ["sleep", seconds]
    started = start_slot_runtime(pack, 1)
    try:
        assert NoneProvider().reset(1) is None
    finally:
        try:
            os.kill(started["browser"], signal.SIGTERM)
            os.waitpid(started["browser"], 0)
        except OSError:
            pass
    restored = json.load(open(stores_path, encoding="utf-8"))
    assert restored[0]["name"] == pack["stores"][0]["name"]
    assert restored[0]["present"] is True
    assert restored[0]["capacity"] == pack["stores"][0]["capacity"]
    assert restored[0]["minimum"] == int(pack["stores"][0].get("minimum") or 0)
    assert restored[0]["names"] == [str(label) for label in (pack["stores"][0].get("names") or [])]
    assert restored[0]["have"] == [str(label) for label in (pack["stores"][0].get("have") or [])]
    from cockpitlib.slots import data_ready

    assert data_ready(pack, 1) == "ready"
    assert open(os.path.join(state_dir(1), "state"), encoding="utf-8").read().strip() == "ready"
    log = os.path.join(qa(), "TASK-994", "reset.log")
    text = open(log, encoding="utf-8").read()
    assert "reset slot 1" in text
    with pytest.raises(OSError):
        os.kill(started["browser"], 0)
    cleanup_settings("TASK-994")
    assert open(log, encoding="utf-8").read() == text
    write_ticket(4, "TASK-994")
    os.makedirs(state_dir(4), exist_ok=True)
    open(os.path.join(state_dir(4), "baseline.json"), "w", encoding="utf-8").write("{")
    NoneProvider().reset(4)
    open(os.path.join(state_dir(4), "baseline.json"), "w", encoding="utf-8").write("[]")
    NoneProvider().reset(4)
    write_ticket(5, "TASK-994")
    NoneProvider().reset(5)
    assert open(log, encoding="utf-8").read().count("reset slot") >= 3


def test_origin_probe_reports_up_and_down(monkeypatch):
    from cockpitlib.acts import _origin_probe, origins_up

    assert _origin_probe("") is False
    assert _origin_probe("not-a-url") is False

    class Sock:
        def close(self):
            return None

    monkeypatch.setattr("socket.create_connection", lambda *_args, **_kwargs: Sock())
    assert _origin_probe("https://app.example/path") is True

    def down(*_args, **_kwargs):
        raise OSError("down")

    monkeypatch.setattr("socket.create_connection", down)
    assert _origin_probe("http://down.example") is False
    assert origins_up(
        {"app": "https://app.example", "portal": ""}, probe=lambda url: url.startswith("https://app.")
    ) == {"app": True, "portal": False}


# Each fixture's runtime: its log, how slot 1's line reads, its status fields, its refused pattern, its own verb.
RUNTIMES = {
    "acme": {
        "log": "acme-slot.log",
        "up": "up slot=1 env=1 ticket={ticket} owner={owner} lane={lane} args={ticket} 8101",
        "status": {"db": "up", "app_port": 8101},
        "refused": ["ledger", "wipe", "all"],
        "verb": "ledger-check",
        "verb_out": "ledger ok in {root}/acme-data/1",
        "verb_who": "lane",
        "toggle": "mail",
        "password": "demo-acme-1",
        "marker": "acme-slot",
        "probe": ["bin/slot", "probe", "{slot}"],
        "capacity": ["bin/slot", "capacity", "{slot}"],
        "has": "app",
    },
    "bravo": {
        "log": "north-runtime.log",
        "up": "start slot=1 env=1 ticket={ticket} owner={owner} lane={lane} port=7201 args=",
        "status": {"web": "up", "web_port": 7201},
        "refused": ["site", "--purge"],
        "verb": "cache-warm",
        "verb_out": "cache warm on 9401",
        "verb_who": "both",
        "toggle": "cdn",
        "password": "demo-north-1",
        "marker": "north",
        "probe": ["bin/runtime", "--slot", "{slot}", "--do", "probe"],
        "capacity": ["bin/runtime", "--slot", "{slot}", "--do", "capacity"],
        "has": "site",
    },
}


@pytest.mark.parametrize("pack_file", PACKS)
def test_the_packs_commands_run_each_slot_verb_with_its_ports_and_variables(env, pack_file, monkeypatch, capsys):
    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    pack = load(pack_file)
    own = RUNTIMES[pack["name"]]
    other = RUNTIMES["bravo" if pack["name"] == "acme" else "acme"]
    from cockpitlib.cli import main
    from cockpitlib.paths import qa
    from cockpitlib.slots import (
        CommandProvider,
        data_ready,
        provider_for,
        start_slot_runtime,
        stop_slot_runtime,
        write_owner,
    )

    root = str(env["root"])
    log = env["root"] / own["log"]
    provider = provider_for(pack.get("slot_provider"), pack)
    assert isinstance(provider, CommandProvider)
    ticket = f"{pack['tracker']['project']}-120"
    monkeypatch.setenv("COCKPIT_LANE", "worker-1")
    provider.up(1, ticket)
    assert log.read_text(encoding="utf-8").splitlines()[-1] == own["up"].format(
        ticket=ticket, owner="lane:worker-1", lane="worker-1"
    )
    assert provider.ready(1)["state"] == "ok"
    (env["root"] / f"{own['marker']}-1.warming").write_text("", encoding="utf-8")
    assert provider.ready(1)["state"] == "working" and main(["slot", "ready", "1"]) == 2
    os.remove(env["root"] / f"{own['marker']}-1.warming")
    (env["root"] / f"{own['marker']}-1.dependency").write_text("", encoding="utf-8")
    assert provider.ready(1)["state"] == "dependency down" and main(["slot", "ready", "1"]) == 3
    os.remove(env["root"] / f"{own['marker']}-1.dependency")
    assert main(["slot", "ready", "1"]) == 0
    row = provider.status(count=1)[0]
    assert {key: row[key] for key in own["status"]} == own["status"] and row["ticket"] == ticket
    assert all(key not in row for key in other["status"])

    # exec passes its arguments through and refuses the pack's own patterns, not the other pack's.
    assert provider.exec(1, ["echo", "hi"])["out"] == "ran: echo hi"
    with pytest.raises(CockpitError, match="slot exec refused"):
        provider.exec(1, own["refused"])
    assert provider.exec(1, other["refused"])["state"] == "ok"
    assert main(["slot", "exec", "1", "--", "echo", "-n", "x"]) == 0 and "ran: echo -n x" in capsys.readouterr().out

    # The pack's own verb, with who may run it; the human's login and toggle.
    assert provider.run(own["verb"], 1)["out"] == own["verb_out"].format(root=root)
    assert main(["slot", "run", own["verb"], "1"]) == 0
    with pytest.raises(CockpitError, match="takes no arguments"):
        provider.run(own["verb"], 1, args=["x"])
    with pytest.raises(CockpitError, match="the pack names no slot nope"):
        provider.run("nope", 1)
    with pytest.raises(CockpitError, match="slot login is the human's"):
        provider.login(ticket, "qa@x.test")
    with pytest.raises(CockpitError, match="slot toggles are the human's"):
        provider.toggle(own["toggle"], "on", 1)
    monkeypatch.delenv("COCKPIT_LANE")
    if own["verb_who"] == "lane":
        with pytest.raises(CockpitError, match="is a lane's"):
            provider.run(own["verb"], 1)
    assert provider.login(ticket, "qa@x.test")["password"] == own["password"]
    assert (
        provider.toggle(own["toggle"], "on", 1)["out"] == "on"
        and main(["slot", "toggle", own["toggle"], "status", "1"]) == 0
    )
    with pytest.raises(CockpitError, match="no slot toggle"):
        provider.toggle(own["toggle"], "sideways", 1)

    # A reset runs the pack's command and leaves a line in the ticket's reset log.
    write_owner(1, "human")
    provider.reset(1)
    assert "reset slot 1" in open(os.path.join(qa(), ticket, "reset.log"), encoding="utf-8").read()
    assert log.read_text(encoding="utf-8").splitlines()[-1].startswith(("reset", "wipe"))

    # A failed up names the runtime's own words.
    (env["root"] / f"{own['marker']}-2.fail").write_text("", encoding="utf-8")
    with pytest.raises(CockpitError, match="slot up failed: .* would not start"):
        provider.up(2, f"{pack['tracker']['project']}-121")

    # Stores answer through the pack's probes on a slot; an empty copy is not ready.
    store = {"name": "data", "probe": own["probe"], "capacity": own["capacity"], "minimum": 1, "names": [own["has"]]}
    probed = {**pack, "slots": {**pack["slots"], "stores": [store]}}
    assert data_ready(probed, 1) == "ready"
    (env["root"] / f"{own['marker']}-1.empty").write_text("", encoding="utf-8")
    assert data_ready(probed, 1) == "not ready data"

    # The slot browser and dev servers get this slot's ports and folder.
    shaped = {
        **pack,
        "slot_browser": [
            "sh",
            "-c",
            "echo {slot}:{port." + next(iter(pack["slots"]["ports"])) + "} > {state_dir}.browser",
        ],
    }
    os.makedirs(CommandProvider(pack).values(2)["state_dir"].rsplit("/", 1)[0], exist_ok=True)
    started = start_slot_runtime(shaped, 2)
    import time

    for _ in range(100):
        if os.path.isfile(CommandProvider(pack).values(2)["state_dir"] + ".browser"):
            break
        time.sleep(0.05)
    base = next(iter(pack["slots"]["ports"].values()))
    assert (
        open(CommandProvider(pack).values(2)["state_dir"] + ".browser", encoding="utf-8").read().strip()
        == f"2:{base + 2}"
    )
    stop_slot_runtime(2)
    assert started["browser"]


@pytest.mark.parametrize("pack_file", PACKS)
def test_a_slot_comes_up_detached_under_one_lock_for_one_ticket_and_stays_while_used(env, pack_file, monkeypatch):
    import threading
    import time

    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    pack = load(pack_file)
    own = RUNTIMES[pack["name"]]
    from cockpitlib import slots
    from cockpitlib.egress import check_tool
    from cockpitlib.kanban import place_card
    from cockpitlib.slots import (
        _acquire,
        bringup,
        lock_busy,
        provider_for,
        read_owner,
        ready_answer,
        slot_up,
        state_dir,
        warm_slot,
        write_owner,
    )

    project = pack["tracker"]["project"]
    marker = lambda slot, kind: env["root"] / f"{own['marker']}-{slot}.{kind}"

    # A real detached bring-up outlives the process that asked, and lands ready.
    monkeypatch.delenv("PYTEST_CURRENT_TEST")
    assert warm_slot(1, f"{project}-130", "lane:worker-1", pack) == "warming"
    for _ in range(200):
        if ready_answer(1) != "still warming":
            break
        time.sleep(0.05)
    assert ready_answer(1) == "ready" and not lock_busy(1)
    assert own["up"].split()[0] in open(env["root"] / own["log"], encoding="utf-8").read()
    monkeypatch.setenv("PYTEST_CURRENT_TEST", "1")

    # A slow ready stays warming until it answers; a failed up is failed with the runtime's words.
    monkeypatch.setattr(slots, "READY_POLL_SECONDS", 0.01)
    monkeypatch.setattr(slots, "READY_LIMIT_SECONDS", 0.1)
    marker(2, "warming").write_text("", encoding="utf-8")
    warm_slot(2, f"{project}-131", "lane:worker-1", pack)
    assert ready_answer(2) == "still warming"
    assert bringup(2, pack) == "failed" and "ready: working" in ready_answer(2)
    marker(2, "warming").unlink()
    marker(3, "fail").write_text("", encoding="utf-8")
    warm_slot(3, f"{project}-132", "lane:worker-1", pack)
    assert bringup(3, pack) == "failed" and "would not start" in ready_answer(3)
    # A down during bring-up wins.
    warm_slot(4, f"{project}-133", "lane:worker-1", pack)
    open(os.path.join(state_dir(4), "lock"), "w", encoding="utf-8").write(f"{os.getpid()}:0")
    assert provider_for("command", pack).down(4) == "down held"
    assert bringup(4, pack) == "down" and read_owner(4) == "free"

    # One ticket, one slot.
    with pytest.raises(CockpitError, match=f"{project}-130 is already on slot 1"):
        warm_slot(5, f"{project}-130", "lane:worker-2", pack)
    with pytest.raises(CockpitError, match=f"{project}-130 is already on slot 1"):
        slot_up(5, f"{project}-130", pack)

    # Two ups on one slot take turns; a dead holder's lock is cleared.
    released = threading.Event()

    def hold():
        _acquire(6)
        released.wait(5)
        os.remove(os.path.join(state_dir(6), "lock"))

    holder = threading.Thread(target=hold)
    holder.start()
    for _ in range(100):
        if lock_busy(6):
            break
        time.sleep(0.01)
    threading.Timer(0.2, released.set).start()
    started = time.time()
    slot_up(6, f"{project}-134", pack)
    assert 0.15 < time.time() - started < pack["slots"]["lock_wait_seconds"]
    holder.join()
    open(os.path.join(state_dir(6), "lock"), "w", encoding="utf-8").write("999999:0")
    assert lock_busy(6) is False and not os.path.exists(os.path.join(state_dir(6), "lock"))
    monkeypatch.setitem(pack["slots"], "lock_wait_seconds", 0)
    _acquire(6)
    for_other = threading.Thread(target=lambda: results.append(_try_up(6)))
    results = []

    def _try_up(slot):
        try:
            slot_up(slot, f"{project}-135", pack)
            return "up"
        except CockpitError as exc:
            return str(exc)

    for_other.start()
    for_other.join()
    assert results == ["slot 6 lock is held"]
    os.remove(os.path.join(state_dir(6), "lock"))

    # An idle lane slot is collected; one whose ticket still has an open card, or that a tool call just used, stays.
    for slot, ticket in ((1, f"{project}-130"), (6, f"{project}-134"), (7, f"{project}-136")):
        write_owner(slot, "lane:worker-1")
        open(os.path.join(state_dir(slot), "ticket"), "w", encoding="utf-8").write(ticket + "\n")
        open(os.path.join(state_dir(slot), "last_activity"), "w", encoding="utf-8").write(str(time.time() - 7200))
    place_card(pack["board"], f"{project}-130: work", "worker-1", "ready")
    card = place_card(pack["board"], f"{project}-136: test", "tester-1", "ready")
    from tests.support.boards import raw

    connection = raw(pack["board"])
    connection.execute("update tasks set status = 'done' where id = ?", (card,))
    connection.commit()
    connection.close()
    monkeypatch.setenv("COCKPIT_LANE", "worker-1")
    monkeypatch.setenv("COCKPIT_TICKET", f"{project}-134")
    assert check_tool("terminal", {"command": "git status"}) == ""
    monkeypatch.delenv("COCKPIT_LANE")
    collected = provider_for("command", pack).gc(pack["slots"]["idle_minutes"], 7)
    assert collected == [7]
    assert read_owner(1) == "lane:worker-1" and read_owner(6) == "lane:worker-1" and read_owner(7) == "free"


@pytest.mark.parametrize("pack_file", PACKS)
def test_a_waiting_card_hears_once_and_a_session_hands_over_and_closes_cleanly(env, pack_file, monkeypatch):
    import subprocess

    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    pack = load(pack_file)
    own = RUNTIMES[pack["name"]]
    from cockpitlib.acts import session_close, session_handoff, session_open
    from cockpitlib.housekeeping import slot_assign
    from cockpitlib.kanban import board_cards, place_card
    from cockpitlib.slots import read_owner, write_owner, write_ticket
    from tests.support.boards import raw

    project = pack["tracker"]["project"]
    slots = pack["seats"]["slots"]

    # Every slot taken: a ready card hears it waits, once; a ticket on the human's slot hears that, once.
    for number in range(1, slots + 1):
        write_owner(number, "lane:worker-9")
        write_ticket(number, f"{project}-14{number}")
    waiting = place_card(pack["board"], f"{project}-150: work", "worker-1", "ready")
    write_owner(1, "human")
    write_ticket(1, f"{project}-151")
    human = place_card(pack["board"], f"{project}-151: test", "tester-1", "ready")
    assert slot_assign(pack) == "2" and slot_assign(pack) == "0"
    connection = raw(pack["board"])
    said = dict(connection.execute("select task_id, body from task_comments").fetchall())
    connection.close()
    assert said[waiting] == "waiting for a slot: every slot is taken"
    assert said[human] == "waiting for a slot: slot 1 is the human's session"

    # The human's session: its open extras run, the handoff makes linked worker, tester and reviewer cards and stops
    # the browser; a slot that is a lane's is not the human's to hand off.
    for number in range(1, slots + 1):
        write_owner(number, "free")
        write_ticket(number, "")
    for repo in pack["repos"]["repos"]:
        source = env["root"] / "repos" / repo["name"]
        if not (source / ".git").exists():
            source.mkdir(parents=True, exist_ok=True)
            subprocess.run(["git", "init", "-q", str(source)], check=True)
            (source / "README").write_text("x\n", encoding="utf-8")
            subprocess.run(["git", "-C", str(source), "add", "README"], check=True)
            subprocess.run(
                ["git", "-C", str(source), "-c", "user.name=Dev", "-c", "user.email=d@x.test", "commit", "-qm", "init"],
                check=True,
            )
    ticket = f"{project}-160"
    session_open(pack, 1, ticket)
    log = env["root"] / own["log"]
    assert log.read_text(encoding="utf-8").splitlines()[-1].startswith("session-open slot=1")
    handed = session_handoff(pack, 1, "worker-1")
    assert handed == "handoff 1 lane:worker-1" and read_owner(1) == "lane:worker-1"
    made = [card for card in board_cards(pack["board"]) if card["ticket"] == ticket]
    assert sorted(card["status"] for card in made) == ["ready", "todo", "todo"]
    with pytest.raises(CockpitError, match="not the human's to hand off"):
        session_handoff(pack, 1, "worker-2")
    # Closing runs the pack's close and puts the checkouts back in lane mode, which cannot push.
    pushed = []
    monkeypatch.setattr("cockpitlib.worktree.mode", lambda t, repo, human: pushed.append((t, repo, human)))
    assert session_close(pack, 1).startswith("closed 1")
    assert log.read_text(encoding="utf-8").splitlines()[-1].startswith("session-close slot=1")
    assert pushed and all(human is False for _t, _repo, human in pushed)


@pytest.mark.parametrize("pack_file", PACKS)
def test_the_tester_uses_the_slot_that_holds_the_ticket(env, pack_file, monkeypatch):
    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    pack = load(pack_file)
    other = load(PACKS[0] if pack["name"] == "bravo" else PACKS[1])
    from cockpitlib.acts import start_manual_plan
    from cockpitlib.paths import qa
    from cockpitlib.slots import _slot_count, _tester_slot_for, state_dir, tester_slot, write_owner, write_ticket

    assert _slot_count({"seats": {"slots": 0}}) == 1
    shaped = dict(pack)
    shaped["seats"] = dict(pack["seats"], slots=2)
    assert _tester_slot_for(shaped, "") == 1
    write_owner(1, "free")
    write_ticket(1, "")
    write_owner(2, "lane:tester-1")
    write_ticket(2, "TASK-996")
    stores = os.path.join(state_dir(2), "stores.json")
    open(stores, "w", encoding="utf-8").write("[]")
    with pytest.raises(CockpitError, match="not ready empty copy"):
        tester_slot(shaped, "TASK-996")
    assert not os.path.isfile(os.path.join(qa(), "TASK-996", "manual-plan.md"))
    os.remove(stores)
    write_owner(2, "human")
    with pytest.raises(CockpitError, match="manual session"):
        start_manual_plan(shaped, "TASK-996")
    assert not os.path.isfile(os.path.join(qa(), "TASK-996", "manual-plan.md"))
    write_owner(2, "lane:tester-1")
    started = start_manual_plan(shaped, "TASK-996")
    assert os.path.isfile(started["path"])
    assert pack["stores"][0]["name"] != other["stores"][0]["name"]
    write_owner(1, "lane:worker-1")
    write_ticket(1, "TASK-1")
    write_owner(2, "free")
    write_ticket(2, "")
    tester_slot(shaped, "TASK-997", 2)
    write_owner(2, "lane:worker-2")
    write_ticket(2, "TASK-2")
    with pytest.raises(CockpitError, match="bound to"):
        tester_slot(shaped, "TASK-997")


@pytest.mark.parametrize("pack_file", PACKS)
def test_up_reset_and_down_share_the_slot_lock(env, pack_file, monkeypatch):
    import subprocess
    import threading

    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    load(pack_file)
    from cockpitlib.slots import NoneProvider, lock_busy, read_owner, state_dir

    provider = NoneProvider()
    folder = state_dir(1)
    os.makedirs(folder, exist_ok=True)
    lock = os.path.join(folder, "lock")
    open(lock, "w", encoding="utf-8").write("nope")
    assert lock_busy(1) is False
    sleeper = subprocess.Popen(["sleep", "30"])
    open(lock, "w", encoding="utf-8").write(str(sleeper.pid))
    try:
        assert lock_busy(1) is True
        assert provider.down(1) == "down held"
        assert os.path.isfile(os.path.join(folder, "down"))
        with pytest.raises(CockpitError, match="lock is held"):
            provider.up(1, "TASK-999")
        with pytest.raises(CockpitError, match="lock is held"):
            provider.reset(1)
        assert read_owner(1) == "free"
    finally:
        sleeper.kill()
        sleeper.wait(timeout=5)
    os.remove(lock)
    open(lock, "w", encoding="utf-8").write(f"{sleeper.pid}:1")
    assert lock_busy(1) is False
    os.remove(os.path.join(folder, "down"))
    open(lock, "w", encoding="utf-8").write(str(os.getpid()))
    assert lock_busy(1) is True
    open(lock, "w", encoding="utf-8").write(f"{os.getpid()}:{threading.get_ident()}")
    assert lock_busy(1) is False
    open(lock, "w", encoding="utf-8").write(f"{os.getpid()}:0")
    assert lock_busy(1) is True
    assert provider.down(1) == "down held"
    with pytest.raises(CockpitError, match="lock is held"):
        provider.up(1, "TASK-999")
    os.remove(lock)
    os.remove(os.path.join(folder, "down"))
    from cockpitlib.slots import _finish, ready_answer

    open(os.path.join(folder, "state"), "w", encoding="utf-8").write("warming\n")
    open(os.path.join(folder, "down"), "w", encoding="utf-8").write("1\n")
    assert _finish(1, "ready") == "down"
    assert ready_answer(1) == "down"
    assert read_owner(1) == "free"
    provider.up(1, "TASK-999")
    assert read_owner(1) != "free"
    assert ready_answer(1) == "ready"
    assert not os.path.isfile(lock)
    assert provider.reset(1) is None


@pytest.mark.parametrize("pack_file", PACKS)
def test_ready_answers_the_log_tail_when_bringup_failed(env, pack_file, monkeypatch):
    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    pack = load(pack_file)
    other = load(PACKS[0] if pack["name"] == "bravo" else PACKS[1])
    store = pack["stores"][0]["name"]
    assert store != other["stores"][0]["name"]
    from cockpitlib.slots import _stores_path, ready_answer, state_dir

    folder = state_dir(1)
    os.makedirs(folder, exist_ok=True)
    stores = _stores_path(1)
    open(os.path.join(folder, "state"), "w", encoding="utf-8").write("warming\n")
    open(stores, "w", encoding="utf-8").write("{")
    assert ready_answer(1) == "still warming"
    json.dump([], open(stores, "w", encoding="utf-8"))
    assert ready_answer(1) == "not ready empty copy"
    os.remove(stores)
    open(os.path.join(folder, "state"), "w", encoding="utf-8").write("warming\n")
    assert ready_answer(1) == "still warming"
    open(os.path.join(folder, "state"), "w", encoding="utf-8").write("failed\n")
    assert ready_answer(1) == "failed"
    lines = [f"line {index}" for index in range(1, 7)]
    lines.append(f"store {store} missing")
    open(os.path.join(folder, "bringup.log"), "w", encoding="utf-8").write("\n".join(lines) + "\n")
    answer = ready_answer(1)
    assert f"store {store} missing" in answer
    assert "line 1" not in answer
    assert "line 3" in answer
    client = _client()
    body = client.get("/slots").json()["slots"]
    assert body[0]["ready"] == answer


@pytest.mark.parametrize("pack_file", PACKS)
def test_a_capacity_change_applies_on_the_next_up(env, pack_file, monkeypatch):
    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    pack = load(pack_file)
    other = load(PACKS[0] if pack["name"] == "bravo" else PACKS[1])
    store = pack["stores"][0]
    assert store["name"] != other["stores"][0]["name"]
    assert store["capacity"] != other["stores"][0]["capacity"]
    from cockpitlib.slots import NoneProvider, _stores_path, data_ready

    path = _stores_path(4)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    json.dump([], open(path, "w", encoding="utf-8"))
    assert data_ready(pack, 4) == "not ready empty copy"
    provider = NoneProvider(pack)
    provider.up(4, "TASK-100")
    copied = json.load(open(path, encoding="utf-8"))
    assert copied[0]["name"] == store["name"] and copied[0]["capacity"] == store["capacity"]
    copied[0]["capacity"] = 0
    copied[0]["minimum"] = 1
    json.dump(copied, open(path, "w", encoding="utf-8"))
    assert data_ready(pack, 4).startswith("not ready")
    provider.up(4, "TASK-100")
    assert json.load(open(path, encoding="utf-8"))[0]["capacity"] == store["capacity"]
    assert data_ready(pack, 4) == "ready"
    open(path, "w", encoding="utf-8").write("{")
    assert data_ready(pack, 4) == "ready"
    from cockpitlib.slots import apply_capacity, ready_answer

    apply_capacity(pack, 4)
    state = os.path.join(os.path.dirname(path), "state")
    log = os.path.join(os.path.dirname(path), "bringup.log")
    open(state, "w", encoding="utf-8").write("failed\n")
    open(log, "w", encoding="utf-8").write("\n")
    assert ready_answer(4) == "failed"


# Each fixture's helpers: the one with the longest chain, its start and stop verbs, the dependency that fails,
# the composite, the helper that takes a choice (verb, choices, who), the status group and its rows.
HELPER_CASES = {
    "acme": {
        "target": "web",
        "up": "start",
        "down": "stop",
        "chain": ["queue", "ledger-db", "web"],
        "failing": "ledger-db",
        "fail": "acme-helper-ledger-db.fail",
        "composite": "everything",
        "members": ["queue", "ledger-db", "web"],
        "choice": ("model", "use", ["small", "large"], "both"),
        "group": "stack",
        "confirm": "everything",
        "rows": [
            ("queue", "running", "pid 41", "queue"),
            ("ledger-db", "stopped", "", "ledger-db"),
            ("web local", "skipped", "ledger-db is stopped", "web"),
        ],
    },
    "bravo": {
        "target": "tunnel",
        "up": "up",
        "down": "down",
        "chain": ["cache", "api", "tunnel"],
        "failing": "api",
        "fail": "bravo-svc-api.fail",
        "composite": "fleet",
        "members": ["cache", "api", "tunnel"],
        "choice": ("profile", "switch", ["quarter", "full"], "lane"),
        "group": "services",
        "confirm": "tunnel",
        "rows": [
            ("cache", "running", "hit rate 0.9", "cache"),
            ("api", "failed", "port 7200 busy", "api"),
            ("tunnel", "skipped", "", "tunnel"),
        ],
    },
}


@pytest.mark.parametrize("pack_file", PACKS)
def test_helpers_start_in_dependency_order_and_a_failed_dependency_stops_its_dependents(
    env, pack_file, monkeypatch, capsys
):
    import time

    from cockpitlib import helpers, plugin_api

    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    monkeypatch.delenv("COCKPIT_LANE", raising=False)
    pack = load(pack_file)
    case = HELPER_CASES[pack["name"]]
    other = HELPER_CASES["bravo" if pack["name"] == "acme" else "acme"]
    assert case["target"] not in load(PACKS[0] if pack["name"] == "bravo" else PACKS[1])["_helpers"]["helpers"]
    done = helpers.run(pack, case["target"], case["up"])
    assert done["code"] == 0 and [step["helper"] for step in done["steps"]] == case["chain"]
    assert all(step["state"] == "ok" for step in done["steps"])
    root = os.environ["COCKPIT_ROOT"]
    open(os.path.join(root, case["fail"]), "w").write("")
    failed = helpers.run(pack, case["target"], case["up"])
    states = {step["helper"]: (step["code"], step["state"]) for step in failed["steps"]}
    assert failed["code"] == 3 and failed["state"] == "dependency down"
    assert states[case["failing"]] == (1, "failed") and states[case["target"]] == (3, "skipped")
    assert any(f"dependency down: {case['failing']}" in str(step["out"]) for step in failed["steps"])
    composite = helpers.run(pack, case["composite"], case["up"])
    assert [step["helper"] for step in composite["steps"]] == case["members"] and composite["code"] == 1
    os.remove(os.path.join(root, case["fail"]))
    assert helpers.run(pack, case["composite"], case["up"])["code"] == 0
    stopped = helpers.run(pack, case["composite"], case["down"])
    assert [step["helper"] for step in stopped["steps"]] == list(reversed(case["members"])) and stopped["code"] == 0
    assert [step["helper"] for step in helpers.run(pack, case["target"], case["down"])["steps"]] == [case["target"]]

    name, verb, choices, who = case["choice"]
    if who == "lane":
        with pytest.raises(CockpitError, match=f"helper {name} is a lane's"):
            helpers.run(pack, name, verb, choices[0])
        monkeypatch.setenv("COCKPIT_LANE", "worker-1")
    assert helpers.options(pack, name) == choices
    with pytest.raises(CockpitError, match=f"helper {name}: pick one of {', '.join(choices)}"):
        helpers.run(pack, name, verb, "huge")
    assert helpers.run(pack, name, verb, choices[1])["code"] == 0
    monkeypatch.setenv("COCKPIT_LANE", "worker-1")
    with pytest.raises(CockpitError, match=f"helper {case['target']} is the human's"):
        helpers.run(pack, case["target"], case["up"])
    monkeypatch.delenv("COCKPIT_LANE")
    for bad, message in (
        ((case["target"], "explode"), f"helper {case['target']} takes"),
        (("absent", case["up"]), "no helper absent"),
        ((case["target"], case["up"], "small"), f"helper {case['target']} takes no choice"),
        ((other["target"], other["up"]), f"no helper {other['target']}"),
    ):
        with pytest.raises(CockpitError, match=message):
            helpers.run(pack, *bad)

    from cockpitlib.helpers import _record_path, _write

    _write(_record_path(case["target"]), {"id": "busy", "pid": os.getpid(), "status": "running"})
    again = helpers.run(pack, case["target"], case["up"])
    assert again["already"] and again["run"] == "busy" and again["code"] == 2
    _write(_record_path(case["target"]), {"id": "gone", "pid": 2**22 + 7, "status": "running"})
    stale = {row["name"]: row for row in helpers.status(pack)["helpers"]}[case["target"]]["last"]
    assert stale["status"] == "ended" and stale["code"] == 1
    started = plugin_api.helper_run(case["target"], case["up"], pack=pack)
    assert started["code"] == 2 and started["state"] == "working"
    deadline = time.time() + 20
    while time.time() < deadline:
        last = {row["name"]: row for row in plugin_api.helper_status(pack=pack)["helpers"]}[case["target"]]["last"]
        if last and last["id"] == started["run"] and last["status"] == "done":
            break
        time.sleep(0.1)
    assert last["status"] == "done" and last["code"] == 0 and last["tail"]

    found = helpers.status(pack, case["group"])
    [group] = found["groups"]
    assert [(row["name"], row["state"], row["detail"], row["helper"]) for row in group["rows"]] == case["rows"]
    assert {row["name"] for row in found["helpers"]} >= set(case["chain"]) and group["error"] == ""
    with pytest.raises(CockpitError, match="no helper group nope"):
        helpers.status(pack, "nope")

    assert main(["helper", "list"]) == 0
    listed = capsys.readouterr().out
    assert f"{case['composite']}: " in listed and " = " in listed and "(needs " in listed
    assert main(["helper", "status"]) == 0 and f"{case['rows'][0][0]}: {case['rows'][0][1]}" in capsys.readouterr().out
    assert main(["helper", "status", "--group", case["group"], "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["groups"][0]["name"] == case["group"]
    if who == "lane":
        monkeypatch.setenv("COCKPIT_LANE", "worker-1")
    assert main(["helper", "options", name]) == 0 and capsys.readouterr().out.split() == choices
    assert main(["helper", "run", name, verb, "--choice", choices[0]]) == 0
    monkeypatch.delenv("COCKPIT_LANE", raising=False)
    open(os.path.join(root, case["fail"]), "w").write("")
    assert main(["helper", "run", case["target"], case["up"]]) == 3
    assert f"{case['target']}: skipped" in capsys.readouterr().out
    os.remove(os.path.join(root, case["fail"]))
    assert main(["helper", "run", case["composite"], case["up"], "--background"]) == 2
    assert "started" in capsys.readouterr().out
    assert main(["helper", "run", case["composite"]]) == 2 and main(["helper", "run", "--choice"]) == 2
    assert main(["helper", "status", "--group"]) == 2

    client = _client()
    page = client.get("/helpers").json()
    assert {row["name"]: row["options"] for row in page["helpers"]}[name] == choices
    assert client.get("/helpers", params={"group": "nope"}).status_code == 404
    refused = client.post("/helper", json={"name": case["confirm"], "verb": case["up"]})
    assert refused.status_code == 400 and f"confirm={case['confirm']} required" in refused.json()["detail"]
    assert (
        client.post("/helper", json={"name": case["confirm"], "verb": case["up"], "confirm": case["confirm"]}).json()[
            "code"
        ]
        == 2
    )
    assert client.post("/helper", json={"name": "absent", "verb": "x"}).status_code == 409


@pytest.mark.parametrize("pack_file", PACKS)
def test_a_helpers_file_that_cannot_run_is_refused_at_load(env, pack_file, tmp_path):
    import shutil

    import yaml

    from cockpitlib.errors import PackError

    name = os.path.basename(os.path.dirname(pack_file))
    copied = tmp_path / "packs" / name
    shutil.copytree(os.path.dirname(pack_file), copied)
    raw = yaml.safe_load((copied / "helpers.yaml").read_text(encoding="utf-8"))
    case = HELPER_CASES[name]
    first, second = case["chain"][0], case["chain"][1]

    def broken(change, message, file_key="helpers.yaml"):
        data = json.loads(json.dumps(raw))
        change(data)
        (copied / "helpers.yaml").write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
        with pytest.raises(PackError, match=re.escape(message)):
            load(str(copied / "pack.yaml"))

    broken(lambda d: d["helpers"][first].update(depends_on=[case["target"]]), "is a cycle")
    broken(lambda d: d["helpers"][first].update(depends_on=["ghost"]), f"helpers.{first}: no helper ghost")
    broken(lambda d: d["helpers"][first].update(composite=[second]), "an argv or a composite, not both")
    broken(lambda d: d["helpers"][first].update(argv=["run", "{choice}"]), "an argv with {choice} needs options")
    broken(lambda d: d["helpers"][first].update(argv=["run", "{slot}"]), "unknown field {slot}")
    broken(lambda d: d["helpers"][first].update(who="anyone"), ".who is one of human, lane, both")
    broken(lambda d: d["helpers"][first].update(group="ghost"), "no group ghost")
    broken(lambda d: d["helpers"][first].update(verbs=[]), "names at least one verb")
    broken(lambda d: d["helpers"][first].update(depends_on="queue"), ".depends_on is a list of names")
    broken(lambda d: d["helpers"][first].update(color="red"), f"helpers.{first} takes")
    broken(lambda d: d["helpers"][first].update(argv={"argv": []}), f"helpers.{first}.argv is a list of words")
    broken(lambda d: d["helpers"][first].update(options={"argv": ["x"], "parse": "xml"}), ".parse is lines or json")
    broken(lambda d: d["helpers"][first].update(options={"argv": ["x"], "sort": True}), ": {argv, parse}")
    broken(lambda d: d["groups"][case["group"]].update(icon="x"), "takes label and status")
    broken(lambda d: d.update(extra={}), "helpers.yaml takes groups and helpers")
    pack_raw = yaml.safe_load((copied / "pack.yaml").read_text(encoding="utf-8"))
    for value, message in (
        ("/abs/helpers.yaml", "helpers is a file beside pack.yaml"),
        ("absent.yaml", "helpers: missing absent.yaml"),
    ):
        (copied / "pack.yaml").write_text(
            yaml.safe_dump({**pack_raw, "helpers": value}, sort_keys=False, allow_unicode=True), encoding="utf-8"
        )
        with pytest.raises(PackError, match=re.escape(message)):
            load(str(copied / "pack.yaml"))
    from cockpitlib.helpers import problems

    assert problems(load(pack_file)) == []
    (copied / "pack.yaml").write_text(yaml.safe_dump(pack_raw, sort_keys=False, allow_unicode=True), encoding="utf-8")
    data = json.loads(json.dumps(raw))
    data["helpers"][first]["argv"] = ["{pack}/bin/absent", "{verb}"]
    data["helpers"][second]["argv"] = ["no-such-program-anywhere", "{verb}"]
    data["groups"][case["group"]]["status"] = {"argv": ["{pack}/helpers.yaml"]}
    (copied / "helpers.yaml").write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    found = problems(load(str(copied / "pack.yaml")))
    assert f"helper {first}: {copied}/bin/absent is not an executable file" in found
    assert f"helper {second}: no-such-program-anywhere is not on PATH" in found
    assert f"helper group {case['group']}: {copied}/helpers.yaml is not an executable file" in found
    del pack_raw["helpers"]
    (copied / "pack.yaml").write_text(yaml.safe_dump(pack_raw, sort_keys=False, allow_unicode=True), encoding="utf-8")
    assert load(str(copied / "pack.yaml"))["_helpers"] == {"groups": {}, "helpers": {}}


@pytest.mark.parametrize("pack_file", PACKS)
def test_a_helper_command_that_misbehaves_reads_as_failed_not_as_a_crash(env, pack_file, monkeypatch, tmp_path, capsys):
    import time

    from cockpitlib import helpers

    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    monkeypatch.delenv("COCKPIT_LANE", raising=False)
    pack = load(pack_file)
    script = tmp_path / f"odd-{pack['name']}"
    script.write_text(
        "#!/bin/sh\ncase \"$1\" in\n  seven) exit 7;;\n  brace) echo '{not json'; exit 0;;\n"
        "  slow) sleep 2;;\n  nonzero) exit 1;;\n  badjson) echo '[oops';;\n  list) printf 'one\\n\\ntwo\\n';;\n"
        "  report) echo 'nope: running'; echo 'wrong' >&2; exit 1;;\nesac\n",
        encoding="utf-8",
    )
    script.chmod(0o755)
    odd = str(script)

    def helper(name, argv, **extra):
        return {
            "name": name,
            "label": name,
            "group": extra.get("group", ""),
            "who": "human",
            "warn": "",
            "self": False,
            "verbs": ["go"],
            "depends_on": [],
            "composite": [],
            "status_names": [name],
            "argv": argv,
            "options": extra.get("options"),
        }

    pack["_helpers"] = {
        "groups": {
            "first": {"name": "first", "label": "First", "status": {"argv": [odd, "report"], "parse": "lines"}},
            "second": {"name": "second", "label": "Second", "status": {"argv": [odd, "badjson"], "parse": "json"}},
            "third": {
                "name": "third",
                "label": "Third",
                "status": {"argv": [str(tmp_path / "absent")], "parse": "lines"},
            },
        },
        "helpers": {
            "seven": helper("seven", [odd, "seven"]),
            "brace": helper("brace", [odd, "brace"]),
            "missing": helper("missing", [str(tmp_path / "absent")]),
            "plain": helper("plain", [odd, "{verb}"], options=None),
            "listed": helper("listed", [odd, "slow", "{choice}"], options={"argv": [odd, "list"], "parse": "lines"}),
            "refusing": helper("refusing", [odd, "{choice}"], options={"argv": [odd, "nonzero"], "parse": "lines"}),
            "garbled": helper("garbled", [odd, "{choice}"], options={"argv": [odd, "badjson"], "parse": "json"}),
            "gone": helper("gone", [odd, "{choice}"], options={"argv": [str(tmp_path / "absent")], "parse": "lines"}),
        },
    }
    assert helpers.run(pack, "seven", "go")["code"] == 1
    assert helpers.run(pack, "brace", "go")["steps"][0]["out"] == "{not json"
    assert helpers.run(pack, "missing", "go")["state"] == "failed"
    assert helpers.options(pack, "plain") == [] and helpers.options(pack, "listed") == ["one", "two"]
    assert helpers.options(pack, "refusing") == helpers.options(pack, "garbled") == helpers.options(pack, "gone") == []
    started = helpers.run(pack, "listed", "go", "two", background=True)
    assert started["code"] == 2
    deadline = time.time() + 5
    while not helpers._live("listed") and time.time() < deadline:
        time.sleep(0.05)
    assert helpers.run(pack, "listed", "go", "two")["already"]
    target = HELPER_CASES[load(pack_file)["name"]]
    helpers._write(helpers._record_path(target["target"]), {"id": "busy", "pid": os.getpid(), "status": "running"})
    assert main(["helper", "run", target["target"], target["up"]]) == 2
    assert f"{target['target']} already running (busy)" in capsys.readouterr().out
    found = {group["name"]: group for group in helpers.status(pack)["groups"]}
    assert found["first"]["rows"] == [{"name": "nope", "state": "running", "detail": "", "helper": ""}]
    assert found["first"]["error"] == "wrong" and found["second"]["rows"] == [] and found["third"]["error"]
    assert [group["name"] for group in helpers.status(pack, "second")["groups"]] == ["second"]
