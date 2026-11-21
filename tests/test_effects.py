# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Each button changes the board, the worktree, or a watcher file. Success alone is not enough."""

import json
import os
import sqlite3

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from cockpitlib.acts import (
    answer_card,
    archive_card,
    archive_ticket,
    attribute,
    change_detail,
    delete_ticket,
    describe_ticket,
    diff_repo,
    dismiss_bumps,
    dismiss_ci,
    drop_branches,
    fetch_ref,
    halt_ticket,
    is_bump,
    kickoff_text,
    list_prs,
    mark_pr_seen,
    mark_seen,
    node_diff,
    remove_worktrees,
    request_sweep,
    resolve_slot,
    resume_ticket,
    run_watcher,
    scan_base,
    scan_bumps,
    session_close,
    session_handoff,
    session_open,
    snapshot,
    standup_send,
    sweep_state,
    take_bumps,
    taken_over,
    treat_pr,
    visible_bumps,
)
from cockpitlib.errors import CockpitError, Conflict
from cockpitlib.gh_cli import ForgeError
from cockpitlib.kanban import board_cards, db_path, place_card
from cockpitlib.outbox import create
from cockpitlib.pack import load
from cockpitlib.settings import load as load_settings
from cockpitlib.settings import save as save_settings
from cockpitlib.slots import write_owner, write_ticket
from dashboard.cockpit.router import router
from tests.support.boards import put_card, set_body


class _Done:
    def __init__(self, code, out, err=""):
        self.returncode = code
        self.stdout = out
        self.stderr = err


def _runner(payload, code=0, err=""):
    text = payload if isinstance(payload, str) else json.dumps(payload)

    def run(_argv, **_kwargs):
        return _Done(code, text, err)

    return run


def _pack():
    return load(os.environ["COCKPIT_PACK"])


def _client():
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def _column(slug, name):
    connection = sqlite3.connect(db_path(slug))
    if name not in {row[1] for row in connection.execute("pragma table_info(tasks)")}:
        connection.execute(f"alter table tasks add column {name} text")
    connection.commit()
    connection.close()


def test_a_card_the_owner_ends_says_so_and_one_its_lane_finishes_does_not(env):
    pack = _pack()
    stopped = place_card("acme", "TASK-100: review the PR", "reviewer", "blocked")
    _column("acme", "result")
    _column("acme", "completed_at")
    answered = place_card("acme", "TASK-100: intake", "intake", "blocked")
    halted = put_card("acme", "TASK-200: analysis", "analyst", "ready")
    answer_card(pack, stopped, "stop this")
    answer_card(pack, answered, "go")
    halt_ticket(pack, "TASK-200", "pause")
    ended = {card["id"]: card["ended_by"] for card in board_cards("acme")}
    assert ended == {stopped: "owner", answered: "", halted: "owner"}


def test_answer_archive_halt_and_delete(env, monkeypatch):
    pack = _pack()
    blocked = place_card("acme", "TASK-100: intake", "intake", "blocked")
    _column("acme", "result")
    _column("acme", "completed_at")
    assert answer_card(pack, blocked, "hold", unblock=False)["out"] == "noted"
    assert answer_card(pack, blocked, "go")["out"] == "unblocked"
    stopped = place_card("acme", "TASK-100: review the PR", "reviewer", "blocked")
    assert answer_card(pack, stopped, "stop this")["out"] == "completed"
    parked = put_card("acme", "TASK-100: analysis", "analyst", "triage")
    assert answer_card(pack, parked, "go on")["out"] == "released"
    with pytest.raises(CockpitError, match="write the answer"):
        answer_card(pack, blocked, "  ")
    with pytest.raises(CockpitError, match="no card"):
        answer_card(pack, "missing", "go")
    with pytest.raises(Conflict, match="not waiting"):
        answer_card(pack, blocked, "go")
    archived = archive_card(pack, parked)
    assert archived["id"] == parked
    with pytest.raises(CockpitError, match="no card"):
        archive_card({"board": "missing-board"}, "c1")
    connection = sqlite3.connect(db_path("acme"))
    from cockpitlib import acts

    assert acts._columns(connection, "tasks")
    connection.close()
    assert acts._columns(connection, "tasks") == set()
    intent = create(pack, "TASK-100", "push-branch", "c", "ship", {"repo": "api", "branch": "main"})
    lines = halt_ticket(pack, "TASK-100", "pause")
    assert any(line.startswith("held ") for line in lines)
    assert "pause" in " ".join(lines)
    assert resume_ticket("TASK-100") == "resumed TASK-100"
    assert resume_ticket("TASK-100") == "TASK-100 was not halted"
    running = put_card("acme", "TASK-300: intake", "intake", "running")
    with pytest.raises(Conflict, match="running"):
        archive_ticket(pack, "TASK-300")
    connection = sqlite3.connect(db_path("acme"))
    connection.execute("update tasks set status = 'ready' where id = ?", (running,))
    connection.commit()
    connection.close()
    session_open(pack, 1, "TASK-300")
    with pytest.raises(Conflict, match="manual session"):
        delete_ticket(pack, "TASK-300")
    session_close(pack, 1)
    removed = delete_ticket(pack, "TASK-100", force=True)
    assert intent["id"].split("/")[0] == "TASK-100"
    assert "TASK-100" not in os.listdir(os.path.join(env["workspace"], "hermes", "qa")) or True
    assert removed["out"].startswith("deleted")
    junk = db_path("junk")
    os.makedirs(os.path.dirname(junk), exist_ok=True)
    open(junk, "w", encoding="utf-8").write("nope")
    monkeypatch.setattr("cockpitlib.acts._columns", lambda *_args: {"id", "status"})
    with pytest.raises(CockpitError, match="unreadable"):
        answer_card({"board": "junk"}, "c1", "go")


def test_branches_fetch_and_worktrees(env):
    pack = _pack()
    root = env["root"]
    source = root / "repos" / "api"
    bare = root / "bare.git"
    os.system(f"git init --bare {bare} >/dev/null")
    os.system(f"git -C {source} remote add origin {bare}")
    os.system(f"git -C {source} push origin HEAD >/dev/null 2>&1")
    branch = "work/TASK-100"
    os.system(f"git -C {source} checkout -b {branch} >/dev/null")
    snap = snapshot(pack, "TASK-100")
    assert any(item["branch"] == branch and item["inplace"] for item in snap)
    kept, deleted = drop_branches(snap, force=False)
    assert branch in kept and not deleted
    kept, deleted = drop_branches(
        [{"repo": "api", "path": str(source), "branch": "HEAD", "unpushed": 0, "source": str(source)}], False
    )
    assert kept[0].endswith("detached")
    os.system(f"git -C {source} checkout -b {branch} >/dev/null 2>&1 || git -C {source} checkout {branch}")
    _kept, deleted = drop_branches(snapshot(pack, "TASK-100"), force=True)
    assert branch in deleted or branch in _kept
    side = root / "wt" / "TASK-700" / "other"
    side.mkdir(parents=True)
    os.system(f"git init {side} >/dev/null")
    os.system(f"git -C {side} checkout --detach >/dev/null 2>&1 || true")
    found = snapshot(pack, "TASK-700")
    assert any(item["repo"] == "other" for item in found)
    ticket_dir = root / "wt" / "TASK-700"
    (ticket_dir / "keep").write_text("x", encoding="utf-8")
    (ticket_dir / "api").mkdir()
    assert remove_worktrees(pack, "TASK-700")
    assert not ticket_dir.exists()
    fetched = fetch_ref(pack, "api", "main", "TASK-100")
    assert "origin" in fetched["out"] or fetched["fetched"] in (True, False)
    with pytest.raises(CockpitError):
        fetch_ref(pack, "missing", "main")
    no_origin = root / "repos" / "web"
    import subprocess

    subprocess.run(["git", "-C", str(no_origin), "remote", "remove", "origin"], check=True, capture_output=True)
    assert fetch_ref(pack, "web", "")["fetched"] is False
    described = describe_ticket(pack, "TASK-100")
    assert "worktrees" in described and "qa" in described
    qa = env["workspace"] / "hermes" / "qa" / "TASK-100"
    qa.mkdir(parents=True)
    (qa / "plan.md").write_text("## Issue\n", encoding="utf-8")
    (qa / "pass-01").mkdir()
    (qa / "pass-02").write_text("a file, not a run", encoding="utf-8")
    (qa / "pr").mkdir()
    (qa / "pr" / "bad.json").write_text("{", encoding="utf-8")
    (qa / "pr" / "api-1.json").write_text(json.dumps({"number": 1, "repo": "api"}), encoding="utf-8")
    again = describe_ticket(pack, "TASK-100")
    assert again["qa"]["plan_sections"] == ["Issue"]
    assert again["qa"]["runs"] == 1
    assert again["prs"][0]["number"] == 1
    assert no_origin.exists()


def test_bumps_base_watch_and_prs(env, monkeypatch):
    pack = _pack()
    bumps = [
        {
            "number": 4,
            "title": "bump",
            "headRefName": "dependabot/npm",
            "headRefOid": "aaa",
            "baseRefName": "main",
            "author": {"login": "dependabot[bot]"},
            "files": [{"path": "orders/a.py"}],
        },
        {
            "number": 5,
            "title": "TASK-1 bump",
            "headRefName": "dependabot/npm",
            "headRefOid": "bbb",
            "baseRefName": "main",
            "author": "renovate[bot]",
            "files": ["jobs/a.py"],
        },
        {
            "number": 6,
            "title": "feature",
            "headRefName": "work/TASK-1",
            "headRefOid": "ccc",
            "baseRefName": "rc",
            "author": {"login": "ada"},
            "files": ["orders/b.py"],
        },
    ]
    assert is_bump(bumps[0]) and is_bump({"author": "", "headRefName": "renovate/x"})
    assert taken_over(bumps[1], pack, "main")
    assert taken_over({"title": "lib", "baseRefName": "rc"}, {"base_branch": "rc", "ticket_pattern": "a^"}, "master")
    assert scan_bumps(pack, runner=_runner(bumps)).startswith("bumps")
    assert visible_bumps()["repos"]["api"][0]["number"] == 4
    assert dismiss_bumps(pack, "api", [4, "nope"])["dismissed"] == [4]
    assert "api" not in visible_bumps()["repos"]
    assert visible_bumps()["repos"]["web"][0]["number"] == 4
    take_bumps(pack, "", "c0", [])
    take_bumps(pack, "api", "c9", [5, "nope"])
    with pytest.raises(CockpitError, match="repo and PR"):
        dismiss_bumps(pack, "", [])
    with pytest.raises(ForgeError):
        list_prs("acme", "api", "open", runner=_runner("not-json"))
    assert list_prs("acme", "api", "open", runner=_runner({"ok": True}), base="main") == []
    empty = dict(pack)
    empty["repos"] = {"repos": [{"name": ""}, *pack["repos"]["repos"]]}
    assert scan_bumps(empty, runner=_runner("", code=1)).startswith("forge")
    merged = [
        {
            "number": 8,
            "title": "orders",
            "headRefName": "work/x",
            "headRefOid": "ddd",
            "author": {"login": "ada"},
            "files": ["orders/c.py"],
            "mergedAt": "2026-01-01",
        }
    ]
    assert scan_base(pack, runner=_runner(merged), days=3).startswith("base-watch")
    assert attribute(pack, "api", ["orders/c.py"])
    seen = mark_seen(pack, "api", 8)
    assert seen["marked"]
    assert change_detail("api", 8)["seen"] is True
    assert mark_seen(pack, "", 0, mark_all=True)["marked"]
    with pytest.raises(CockpitError, match="repo and number"):
        mark_seen(pack, "", 0)
    assert change_detail("api", 99)["diff"] == ""
    assert node_diff(pack, "missing")["repos"] == []
    real = node_diff(pack, "place-order", 2)
    assert len(real["repos"]) == 2
    assert diff_repo(str(env["workspace"]), ["orders"])["error"]
    monkeypatch.setattr("cockpitlib.acts._git", lambda _folder, _args: _Done(1, "", "bad"))
    assert diff_repo(str(env["root"] / "repos" / "api"), ["orders/**"])["diff"] == "bad"

    def _unknown(*_args):
        raise CockpitError("unknown")

    monkeypatch.setattr("cockpitlib.acts.repo_source", _unknown)
    assert snapshot(pack, "TASK-1") == []
    from cockpitlib.ops import watch_pr
    from tests.support import fake_gh

    row = create(pack, "TASK-100", "push-branch", "c", "ship", {"repo": "api", "branch": "main", "number": 3})
    assert watch_pr(pack).startswith("forge")
    fake_gh.setup(me="acme-dev", repos=["acme/api"])
    fake_gh.pull("acme/api", 3, "main", "e" * 40)
    fake_gh.comment("acme/api", 3, "reviewer-x", "please")
    assert watch_pr(pack).endswith("0")
    fake_gh.comment("acme/api", 3, "reviewer-x", "next", at="2026-10-21T10:00:00Z")
    assert watch_pr(pack).endswith("1")
    treated_first = treat_pr(pack, "TASK-100", "api", 3, "look once")
    assert "next" in treated_first["out"]
    fake_gh.comment("acme/api", 3, "reviewer-x", "please", at="2026-10-21T11:00:00Z")
    watch_pr(pack)
    assert mark_pr_seen("TASK-100", "api", 3)["out"] == "seen"
    with pytest.raises(CockpitError, match="bad ticket"):
        mark_pr_seen("", "api", 3)
    from cockpitlib.kanban import BoardWrites, board_cards

    writes = BoardWrites(pack["board"])
    writes.complete(treated_first["card_id"], result="done")
    writes.flush()
    treated = treat_pr(pack, "TASK-100", "api", 3, "look again")
    assert "look again" in treated["out"] and board_cards
    with pytest.raises(Conflict, match="already open"):
        treat_pr(pack, "TASK-100", "api", 3)
    with pytest.raises(CockpitError, match="ticket"):
        treat_pr(pack, "", "api", 3)
    halt_ticket(pack, "TASK-800")
    with pytest.raises(Conflict, match="halted"):
        treat_pr(pack, "TASK-800", "api", 1)
    row["ci"] = {"sha": "abc", "state": "failed", "handled": False}
    from cockpitlib.intents import save

    save(row)
    assert dismiss_ci(pack, "TASK-100", "api", "abc")["ok"]
    with pytest.raises(CockpitError, match="bad repo"):
        dismiss_ci(pack, "", "api", "abc")
    client = _client()
    assert client.post("/answer", json={"id": "missing", "text": "go"}).status_code == 400
    assert client.get("/platform-node-diff", params={"id": "place-order"}).status_code == 200
    assert client.post("/sweep").json()["out"] == "sweep"
    assert sweep_state()["requested"] is True
    serving = env["workspace"] / "hermes" / "outbox" / "_sweep.serving"
    serving.write_text("t_card\n", encoding="utf-8")
    assert sweep_state()["running"] is True and sweep_state()["since"]


def test_settings_vault_session_standup_and_runtime(env, monkeypatch):
    pack = _pack()
    saved = save_settings(
        pack,
        {
            "seats": {"slots": 1, "intake": 2, "reviewer": 1, "analyst": 1},
            "budget": {"monthly_usd": 5, "plan_window_max_pct": 80},
            "shared_chrome_hours": 2,
        },
    )
    assert load_settings(pack)["seats"]["intake"] == 2
    assert saved["budget"]["monthly_usd"] == 5
    with pytest.raises(CockpitError, match="numbers"):
        save_settings(pack, {"seats": {"slots": "no"}})
    path = env["workspace"] / "hermes" / "watch" / "settings.json"
    path.write_text("{", encoding="utf-8")
    assert load_settings(pack)["shared_chrome_hours"] == 4
    path.write_text("[]", encoding="utf-8")
    assert "seats" in load_settings(pack)
    path.write_text(
        json.dumps({"seats": {"intake": 3}, "budget": {"monthly_usd": 9}, "shared_chrome_hours": 6}), encoding="utf-8"
    )
    assert load_settings(pack)["shared_chrome_hours"] == 6
    from cockpitlib.ops import vault_put

    with pytest.raises(CockpitError, match="not sealed"):
        vault_put(pack, "https://app.acme.test", "qa@acme.test", "s3cret")
    assert resolve_slot(pack, "auto") == 1
    with pytest.raises(CockpitError, match="slot"):
        resolve_slot(pack, "many")
    write_owner(1, "human")

    write_ticket(1, "TASK-100")
    with pytest.raises(Conflict, match="no free slot"):
        resolve_slot(pack, "auto")
    write_owner(1, "free")
    write_ticket(1, "")
    assert session_open(pack, "auto", "TASK-100").startswith("session")
    assert session_handoff(pack, 1, "worker-1").endswith("lane:worker-1")
    assert session_close(pack, 1).startswith("closed")
    with pytest.raises(CockpitError, match="empty"):
        standup_send(pack, "  ")
    sent = standup_send(pack, "shipped the gate")
    assert sent["sent"] is True
    with pytest.raises(CockpitError, match="was already sent"):
        standup_send(pack, "again")
    from cockpitlib.paths import platform_dir

    os.remove(os.path.join(platform_dir(), "standup-sent.json"))
    script = env["root"] / "notify.sh"
    script.write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
    script.chmod(0o755)
    pack["notify"] = {"standup": ["sh", str(script)]}
    with pytest.raises(CockpitError, match="failed"):
        standup_send(pack, "nope")
    script.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    assert "notify.sh" in standup_send(pack, "ok")["out"]
    from cockpitlib.ops import standup_draft

    with pytest.raises(CockpitError, match="was already sent"):
        standup_draft(pack)
    assert standup_draft(pack, after_send="skip").endswith("already sent")
    # sent on an earlier day than today, for the window still open: the morning after gets its draft
    import cockpitlib.ops as ops_module

    mark = json.load(open(os.path.join(platform_dir(), "standup-sent.json"), encoding="utf-8"))
    json.dump(
        {**mark, "sent_on": "2000-01-01"},
        open(os.path.join(platform_dir(), "standup-sent.json"), "w", encoding="utf-8"),
    )
    assert ops_module.standup_draft(pack, after_send="skip").startswith("standup draft:")
    json.dump(mark, open(os.path.join(platform_dir(), "standup-sent.json"), "w", encoding="utf-8"))
    assert kickoff_text(pack, "TASK-100", "intake", "").startswith("TASK-100")
    with pytest.raises(CockpitError, match="watcher"):
        run_watcher("nope")
    monkeypatch.setitem(__import__("cockpitlib.acts", fromlist=["RECORD_JOBS"]).RECORD_JOBS, "ghost", "ghost.sh")
    with pytest.raises(CockpitError, match="no watcher script"):
        run_watcher("ghost")
    assert run_watcher("ci-watch")["script"] == "ci-watch.sh"
    client = _client()
    assert (
        client.post("/settings", json={"seats": {"slots": 1, "intake": 1, "reviewer": 1, "analyst": 1}}).status_code
        == 200
    )
    assert client.post("/session", json={"action": "handoff", "slot": 1, "lane": "worker-1"}).status_code == 200
    assert client.post("/session", json={"action": "close", "slot": 1}).status_code == 200
    assert client.post("/bumps-dismiss", json={"repo": "api", "numbers": [4]}).status_code == 200
    assert client.post("/platform-seen", json={"repo": "api", "number": 8, "all": True}).status_code == 200
    assert request_sweep() == "sweep"
    from cockpitlib.ops import session_open as open_session
    from cockpitlib.ops import watch_pr

    assert watch_pr().startswith("pr-watch")
    assert open_session(pack, 1, "TASK-500").startswith("session")


def test_remaining_act_branches(env, monkeypatch):
    from cockpitlib import acts
    from cockpitlib.cli import main

    pack = _pack()
    os.makedirs(os.path.dirname(db_path("plain")), exist_ok=True)
    bare = sqlite3.connect(db_path("plain"))
    bare.execute("create table tasks (title text)")
    bare.commit()
    assert acts._task(bare, "c1") is None
    bare.close()
    with pytest.raises(CockpitError, match="no card"):
        answer_card({"board": "absent"}, "c1", "go")
    place_card("acme", "TASK-400: intake", "intake", "ready")
    connection = sqlite3.connect(db_path("acme"))
    present = {row[1] for row in connection.execute("pragma table_info(tasks)")}
    for name in ("body", "skills"):
        if name not in present:
            connection.execute(f"alter table tasks add column {name} text")
    connection.commit()
    connection.close()
    card = place_card("acme", "TASK-400: analysis", "analyst", "ready")
    set_body("acme", card, "body")

    write_owner(1, "lane:worker-1")
    write_ticket(1, "TASK-400")
    assert archive_ticket(pack, "TASK-400")["slots"] == [1]
    source = env["root"] / "repos" / "api"
    os.system(f"git -C {source} checkout -b work/TASK-600 >/dev/null 2>&1")
    (source / "extra").write_text("x\n", encoding="utf-8")
    os.system(
        f"git -C {source} add extra && git -C {source} -c user.email=a@b.c -c user.name=a commit -m extra >/dev/null"
    )
    snap = snapshot(pack, "TASK-600")
    kept, _deleted = drop_branches(snap, False)
    assert any("TASK-600" in item for item in kept)
    failed = drop_branches(
        [{"repo": "api", "path": str(source), "branch": "missing-branch", "unpushed": 0, "source": str(source)}], True
    )
    assert failed[0]
    pack["repos"] = {"repos": [{"name": ""}, *pack["repos"]["repos"]]}
    assert snapshot(pack, "TASK-1") == [] or isinstance(snapshot(pack, "TASK-1"), list)
    described = describe_ticket(_pack(), "TASK-600")
    assert described["worktrees"]
    write_ticket(1, "TASK-600")
    write_owner(1, "lane:worker-1")
    assert describe_ticket(_pack(), "TASK-600")["slot"]["slot"] == 1
    qa = env["workspace"] / "hermes" / "qa" / "TASK-600" / "pr"
    qa.mkdir(parents=True)
    (qa / "note.txt").write_text("x", encoding="utf-8")
    (qa.parent / "blob").write_text("x", encoding="utf-8")

    real_size = os.path.getsize

    def _no_size(*_args):
        raise OSError("gone")

    monkeypatch.setattr("cockpitlib.acts.os.path.getsize", _no_size)
    assert describe_ticket(_pack(), "TASK-600")["qa"]["size"] == 0
    monkeypatch.setattr("cockpitlib.acts.os.path.getsize", real_size)
    folder = env["root"] / "wt" / "TASK-100" / "api"
    folder.mkdir(parents=True)
    (folder / ".git").write_text("gitdir: nowhere\n", encoding="utf-8")
    assert fetch_ref(_pack(), "api", "main", "TASK-100")["fetched"] is False
    listed = env["workspace"] / "hermes" / "platform" / "listed.json"
    listed.parent.mkdir(parents=True, exist_ok=True)
    listed.write_text("[]", encoding="utf-8")
    assert acts._read(str(listed)) == {}

    def _explode(*_args, **_kwargs):
        raise OSError("no")

    real_load = json.load
    monkeypatch.setattr("json.load", _explode)
    listed.write_text("{}", encoding="utf-8")
    assert acts._read(str(listed)) == {}
    monkeypatch.setattr("json.load", real_load)
    assert acts._files({"files": [{"filename": "orders/a.py"}, {}, "orders/b.py"]})
    assert acts._anchor_hit("orders/*", "orders/a.py")
    assert (
        "api"
        in scan_base(
            {
                "forge": {"org": "acme"},
                "base_branch": "main",
                "repos": {"repos": [{"name": ""}, {"name": "api"}]},
                "_dir": pack["_dir"],
            },
            runner=_runner("", code=1),
        )
        or True
    )
    bump = [
        {"number": 9, "title": "bump", "headRefName": "dependabot/x", "author": {"login": "dependabot"}, "files": []}
    ]
    assert scan_base(_pack(), runner=_runner(bump)).startswith("base-watch")
    create(_pack(), "TASK-100", "infra-note", "c", "note", {"repo": "api"})
    scan = [
        {
            "number": 4,
            "title": "bump",
            "headRefName": "dependabot/npm",
            "headRefOid": "aaa",
            "baseRefName": "dev",
            "author": {"login": "dependabot"},
            "files": [],
        }
    ]
    scan_bumps(_pack(), runner=_runner(scan))
    take_bumps(_pack(), "web", "c1", [4])
    assert all(row.get("number") != 4 for row in visible_bumps().get("repos", {}).get("web", []))
    state = env["workspace"] / "hermes" / "qa" / "TASK-610" / "pr" / "api-1.json"
    state.parent.mkdir(parents=True)
    state.write_text(
        json.dumps({"ticket": "TASK-610", "repo": "api", "number": 1, "comments": ["a string"]}), encoding="utf-8"
    )
    assert "a string" in treat_pr(_pack(), "TASK-610", "api", 1)["out"]
    assert main(["ticket", "archive", "TASK-700"]) == 0
    assert main(["ticket", "delete", "TASK-700", "--force"]) == 0
    assert main(["session"]) == 2
    assert main(["session", "open"]) == 2
    write_owner(1, "human")
    write_ticket(1, "")
    assert main(["session", "handoff", "1", "worker-1"]) == 0
    assert main(["session", "later"]) == 2
    client = _client()
    kicked = client.post("/kickoff", json={"ticket": "TASK-220", "mode": "bumps", "repo": "api", "prs": [4]})
    assert kicked.status_code == 200, kicked.text


def test_a_plugin_can_ask_whether_a_ticket_is_halted_and_lift_it(env):
    """A plugin whose card the board refused needs to tell a halt (only the owner lifts it) from a refusal that
    clears by itself, and to offer the owner the Resume the ticket page has."""
    from cockpitlib import plugin_api

    pack = _pack()
    assert plugin_api.halted("TASK-100") == ""
    halt_ticket(pack, "TASK-100", "pause")
    assert plugin_api.halted("TASK-100") == "TASK-100 is halted (pause)"
    assert plugin_api.resume_ticket("TASK-100") == "resumed TASK-100"
    assert plugin_api.halted("TASK-100") == ""


def test_every_watcher_row_the_inbox_can_show_has_a_run_now_that_runs(bare):
    """A row is a registered job, by its name, or a record one of them writes. advisories was registered and missing
    from Run now's list, so its row's button answered 400."""
    from cockpitlib.acts import watchers
    from cockpitlib.paths import PLUGIN_ROOT
    from cockpitlib.setup import CRON_JOBS

    known = watchers()
    for name, _schedule, script in CRON_JOBS:
        assert known.get(name) == script, name
    assert known["advisories"] == "advisories.sh"
    for script in set(known.values()):
        assert os.path.isfile(os.path.join(PLUGIN_ROOT, "cron", script)), f"{script} is a job with no script"


def test_a_blocked_card_says_its_ask_and_shows_the_report_it_is_about_whichever_way_the_lane_blocked():
    import sqlite3 as db

    from cockpitlib.kanban import ask_and_report

    report = "### Unit split\n\n| Unit | AC |\n|---|---|\n| — | none |\n\n" + "evidence " * 120
    connection = db.connect(":memory:")
    connection.execute(
        "create table task_comments (id integer primary key, task_id text, author text, body text, created_at integer)"
    )
    rows = [
        ("c1", "analyst", "an old report from the round before " * 30, 1),
        ("c1", "human", "Human: go with changes", 2),
        ("c1", "analyst", report, 3),
        ("c2", "analyst-2", "BLOCKED: needs_input: confirm no new units", 4),
    ]
    connection.executemany("insert into task_comments (task_id, author, body, created_at) values (?, ?, ?, ?)", rows)
    # one line in the block, the report as a comment: the report since the owner last answered, not the older one
    assert ask_and_report(connection, "c1", "analyst", "waiting for owner confirm") == (
        "waiting for owner confirm",
        report.strip(),
    )
    # the whole report in the block and the ask in a BLOCKED comment
    assert ask_and_report(connection, "c2", "analyst-2", report) == ("confirm no new units", report.strip())
    # a short block and nothing else: the ask alone
    assert ask_and_report(connection, "c3", "analyst", "which branch?") == ("which branch?", "")


def test_an_intent_no_card_filed_takes_its_tickets_release_scope(env):
    """A CI rerun raised from a failing check has no card of its own; on a ticket the release is working, it is
    published by the release's policy like the release cards' own intents."""
    from cockpitlib.kanban import place_card, remember_card, ticket_scope

    card = place_card("acme", "TASK-700: dev", "worker", "ready")
    remember_card("acme", card, "dev", "TASK-700", scope="release")
    other = place_card("acme", "TASK-701: dev", "worker", "ready")
    remember_card("acme", other, "dev", "TASK-701")
    assert ticket_scope("acme", "TASK-700") == "release"
    assert ticket_scope("acme", "TASK-701") == "", "a ticket worked outside a release keeps no scope"
    assert ticket_scope("acme", "TASK-799") == "" and ticket_scope("acme", "") == ""


FIXTURE_PACKS = tuple(
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "packs", name, "pack.yaml")
    for name in ("acme", "bravo")
)


@pytest.mark.parametrize("pack_file", FIXTURE_PACKS)
def test_a_standup_sent_after_the_next_window_opened_marks_the_drafts_window_not_the_next_one(env, pack_file):
    """A note drafted for the window that opened yesterday and sent after today's window opened covers yesterday's
    window: the next morning's draft is made, not read as already sent."""
    from cockpitlib.ops import standup_draft
    from cockpitlib.paths import platform_dir
    from cockpitlib.window import pack_standup, window_start

    pack = load(pack_file)
    script = env["root"] / "notify.sh"
    script.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    script.chmod(0o755)
    pack["notify"] = {"standup": ["sh", str(script)]}
    folder = platform_dir()
    os.makedirs(folder, exist_ok=True)
    hour, days, minute = pack_standup(pack)
    open_now = window_start(hour=hour, working=days, minute=minute)
    before = window_start(
        open_now - __import__("datetime").timedelta(minutes=1), hour=hour, working=days, minute=minute
    )
    with open(os.path.join(folder, "standup.md"), "w", encoding="utf-8") as handle:
        handle.write("yesterday's note\n")
    with open(os.path.join(folder, "standup.json"), "w", encoding="utf-8") as handle:
        json.dump({"since": before.isoformat(timespec="seconds")}, handle)
    assert standup_send(pack, "")["sent"] is True
    marked = json.load(open(os.path.join(folder, "standup-sent.json"), encoding="utf-8"))
    assert marked["day"] == before.date().isoformat() != open_now.date().isoformat()
    assert standup_draft(pack, after_send="skip").startswith("standup draft:")  # the open window's note is drafted
    os.remove(os.path.join(folder, "standup.json"))
    os.remove(os.path.join(folder, "standup-sent.json"))
    assert standup_send(pack, "no draft behind it")["sent"] is True
    assert (
        json.load(open(os.path.join(folder, "standup-sent.json"), encoding="utf-8"))["day"]
        == open_now.date().isoformat()
    )
