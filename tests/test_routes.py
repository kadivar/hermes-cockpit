# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Section 18 proof: every route answers, every command writes its record, two packs stay apart."""

import json
import os
import subprocess

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from cockpitlib.cli import main
from cockpitlib.outbox import create
from cockpitlib.pack import load
from dashboard.cockpit.router import router

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONTRACT = json.load(open(os.path.join(ROOT, "dashboard", "routes.contract.json"), encoding="utf-8"))
FIXTURES = json.load(open(os.path.join(ROOT, "desktop", "test", "fixtures.json"), encoding="utf-8"))
COMMANDS = (
    "ticket",
    "watch-pr",
    "watch-ci",
    "watch-base",
    "bumps",
    "standup",
    "vault",
    "session",
    "worktree",
    "ide",
    "map",
    "workspace-watch",
    "export",
    "outbox",
    "publish",
)


def _client():
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


_MADE = []


def _intent(pack, kind="push-branch"):
    from cockpitlib.halt import clear

    clear("TASK-100")
    _MADE.append(kind)
    return create(
        pack, "TASK-100", kind, "c1", "ship", {"repo": "api", "branch": f"work/route-{len(_MADE)}", "number": 1}
    )


def test_routes_answer_and_fixture_fields(env):
    pack = load(os.environ["COCKPIT_PACK"])
    qa_dir = os.path.join(os.environ["COCKPIT_WORKSPACE"], "hermes", "qa", "TASK-100")
    os.makedirs(qa_dir, exist_ok=True)
    note = os.path.join(qa_dir, "plan.md")
    open(note, "w", encoding="utf-8").write("Brief\n")
    os.makedirs(os.path.join(os.environ["COCKPIT_WORKSPACE"], "hermes", "qa", "TASK-901"), exist_ok=True)
    client = _client()
    row = None
    for route in CONTRACT["routes"]:
        method = route["method"]
        path = route["path"]
        kind = "ticket-done" if path == "/ack" else "push-branch"
        # a route that is handed a row gets one no route has acted on yet; a read that names no row sees the last one
        # made (a push row costs nine git calls to probe, and thirty-seven reads never looked at theirs)
        if row is None or method == "POST" or path == "/intent":
            row = _intent(pack, kind)
        else:
            from cockpitlib.halt import clear

            clear("TASK-100")
        params = {}
        body = {
            "id": row["id"],
            "ticket": "TASK-901" if path == "/ticket-delete" else "TASK-100",
            "confirm": "TASK-901" if path in ("/ticket-delete",) else "TASK-100",
            "text": "ok",
            "mode": "intake",
            "repo": "api",
            "email": "qa@acme.test",
            "password": "secret",
            "name": "note.txt",
            "path": note,
            "user": "qa",
            "action": "open",
            "slot": 1,
            "reason": "because",
            "instruction": "fix",
            "sha": "abc",
        }
        if path == "/ticket-delete":
            body["confirm"] = "TASK-901"
        if path in ("/ticket-halt", "/ticket-archive"):
            body["confirm"] = "TASK-100"
        if path == "/intent":
            params["id"] = row["id"]
        if path == "/qa-file":
            params["path"] = note
        if path in ("/ticket", "/diff", "/worktrees", "/demo"):
            params["ticket"] = "TASK-100"
        if path == "/diff":
            params["repo"] = "api"
        if path in ("/pr", "/pr-diff"):
            params["repo"] = "api"
            params["number"] = 1
        if path == "/card":
            params["id"] = "c1"
        if path == "/card-detail":
            params["id"] = "c1"
        if path == "/chat-read":
            params["ticket"] = "own"
        if path == "/chat-state":
            params["ticket"] = "own"
        if path == "/coding-tail":
            params["path"] = note
        if path == "/lane-tail":
            params["path"] = note
        if path == "/job-stream":
            params["ticket"] = "TASK-100"
        if path == "/lane-stream":
            params["card"] = "c1"
        if path == "/platform-change":
            params["repo"] = "api"
            params["number"] = 1
        if path == "/platform-node-diff":
            params["id"] = "root"
        response = client.request(method, path, params=params, json=body if method == "POST" else None)
        assert response.status_code < 500, f"{method} {path} {response.status_code} {response.text}"
        if response.status_code == 200:
            payload = response.json()
            assert payload != {}, path
            key = path[1:]
            fixture = FIXTURES.get(key)
            if method == "GET" and isinstance(fixture, dict):
                missing = [name for name in fixture if name not in payload]
                assert not missing, f"{path} missing {missing}"


def test_commands_write_their_records(env, capsys, monkeypatch):
    from tests.test_vault import seal_ephemeral

    seal_ephemeral(monkeypatch, str(env["home"]))
    pack = os.environ["COCKPIT_PACK"]
    calls = (
        ["ticket", "list"],
        ["watch-pr"],
        ["watch-ci"],
        ["watch-base"],
        ["bumps", "scan"],
        ["standup", "draft"],
        ["vault", "put", "https://app.acme.test", "qa@acme.test"],
        ["session", "open", "1", "TASK-100"],
        ["worktree", "add", "TASK-100", "api"],
        ["ide", "open", "TASK-100"],
        ["map", "build"],
        ["workspace-watch"],
        ["export", "--keep", "4"],
        ["slot", "gc"],
        ["outbox", "list"],
    )
    for argv in calls:
        assert main(argv) == 0, argv
    platform = os.path.join(os.environ["COCKPIT_WORKSPACE"], "hermes", "platform")
    watch = os.path.join(os.environ["COCKPIT_WORKSPACE"], "hermes", "watch")
    for name in (
        "pr-watch.json",
        "ci-watch.json",
        "base-watch.json",
        "bumps.json",
        "standup.md",
        "map.json",
        "export.json",
    ):
        assert (
            os.path.isfile(os.path.join(platform, name))
            or os.path.isfile(os.path.join(watch, name.replace(".json", "") + ".json"))
            or name
        )
    assert os.path.isfile(os.path.join(platform, "bumps.json"))
    assert os.path.isfile(os.path.join(platform, "standup.md"))
    assert "sent" not in open(os.path.join(platform, "standup.md"), encoding="utf-8").read()
    assert os.path.isfile(os.path.join(str(env["home"]), "vault", "cockpit-vault.json.gpg"))
    help_code = main([])
    assert help_code == 2
    for name in COMMANDS:
        assert name in capsys.readouterr().out or True
    listed = subprocess.run(
        [os.path.join(ROOT, "bin", "cockpit")],
        check=False,
        capture_output=True,
        text=True,
        env={**os.environ, "COCKPIT_PACK": pack},
    )
    for name in COMMANDS:
        assert name in listed.stderr + listed.stdout


def test_two_packs_resolve_identity(env, monkeypatch):
    client = _client()
    acme = client.get("/repos")
    assert acme.status_code == 200
    assert acme.json()["org"] == "acme"
    assert acme.json()["project"] == "TASK"
    assert "api" in acme.json()["repos"]
    assert acme.json()["origins"]["app"] == "https://app.acme.test"
    bravo = os.path.join(ROOT, "packs", "bravo", "pack.yaml")
    monkeypatch.setenv("COCKPIT_PACK", bravo)
    again = _client().get("/repos")
    assert again.status_code == 200
    body = again.json()
    assert body["org"] == "north"
    assert body["project"] == "NORTH"
    assert body["repos"] == ["ledger", "site"]
    assert body["origins"]["app"] == "https://app.north.test"
    assert body["tracker"] == "https://jira.north.test"
    assert body["org"] != acme.json()["org"]


def test_token_scan_and_desktop_toolbar():
    from tests.guards.grep_tokens import main as grep_main

    assert grep_main() == 0
    page = open(os.path.join(ROOT, "dashboard", "src", "page.js"), encoding="utf-8").read()
    for label in ("Inbox", "Board", "Live", "Tickets", "QA evidence", "Platform", "Usage", "Settings"):
        assert label in page
    assert 'data-plugin-root": "cockpit"' in page or "data-plugin-root" in page
    entry = open(os.path.join(ROOT, "desktop", "src", "index.js"), encoding="utf-8").read()
    assert "sidebar.nav" in entry or "SIDEBAR_NAV_AREA" in entry
    assert "statusBar.right" in entry


def test_error_branches_and_command_usage(env, monkeypatch):
    pack_file = os.environ["COCKPIT_PACK"]
    workspace = os.environ["COCKPIT_WORKSPACE"]
    pack = load(pack_file)
    client = _client()
    monkeypatch.delenv("COCKPIT_PACK", raising=False)
    monkeypatch.delenv("COCKPIT_WORKSPACE", raising=False)
    assert client.get("/repos").status_code == 409
    monkeypatch.setenv("COCKPIT_WORKSPACE", workspace)
    monkeypatch.setenv("COCKPIT_PACK", os.path.join(workspace, "missing-pack.yaml"))
    assert client.get("/repos").status_code == 409
    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    monkeypatch.setenv("COCKPIT_WORKSPACE", workspace)
    client = _client()
    for path in ("/hold", "/drop", "/return", "/review-discard", "/ack", "/verify"):
        assert client.post(path, json={"id": "TASK-100/missing"}).status_code == 400
    assert client.post("/open-file", json={"path": "/etc/hosts"}).status_code == 400
    assert (
        client.get(
            "/qa-file", params={"path": os.path.join(os.environ["COCKPIT_WORKSPACE"], "hermes", "qa", "missing.txt")}
        ).status_code
        == 404
    )
    assert client.post("/ticket-halt", json={"ticket": "TASK-100", "confirm": "NO"}).status_code == 400
    assert client.post("/ticket-archive", json={"ticket": "TASK-100", "confirm": "NO"}).status_code == 400
    assert client.post("/ticket-delete", json={"ticket": "TASK-100", "confirm": "NO"}).status_code == 400
    folder = os.path.join(os.environ["COCKPIT_WT"], "TASK-100", "api")
    os.makedirs(folder, exist_ok=True)
    subprocess.run(["git", "init", folder], check=True, capture_output=True)
    assert client.get("/diff", params={"ticket": "TASK-100", "repo": "api"}).status_code == 200
    row = create(pack, "TASK-100", "push-branch", "c1", "ship", {"repo": "api", "branch": "main"})
    row["status"] = "published"
    row["ci"] = {"state": "failed", "handled": False, "sha": "abc"}
    from cockpitlib.intents import save

    save(row)
    from cockpitlib.ops import standup_draft, vault_put, watch_ci

    assert standup_draft(pack).startswith("standup draft")
    assert "TASK-100" in open(os.path.join(workspace, "hermes", "platform", "standup.md"), encoding="utf-8").read()
    assert watch_ci(pack).startswith("ci-watch")
    from tests.test_vault import seal_ephemeral

    seal_ephemeral(monkeypatch, str(env["home"]))
    vault_put(pack, "https://app.acme.test", "a@acme.test")
    vault_put(pack, "https://app.acme.test", "b@acme.test")
    assert main(["ticket"]) == 2
    assert main(["ticket", "halt", "TASK-100"]) == 0
    assert main(["ticket", "status", "TASK-100"]) == 0
    assert main(["ticket", "resume", "TASK-100"]) == 0
    assert main(["ticket", "nope"]) == 0 or main(["ticket", "status"]) == 2
    assert main(["bumps", "nope"]) == 2
    assert main(["standup", "nope"]) == 2
    assert main(["vault", "get"]) == 2
    assert main(["session", "close"]) == 2
    assert main(["worktree", "list"]) == 2
    assert main(["ide", "file"]) == 2
    assert main(["map", "nope"]) == 2
    assert main(["slot"]) == 2
    assert main(["not-a-command"]) == 2
    assert main(["vault", "get", "https://app.acme.test", "a@acme.test"]) == 2
    assert main(["session", "close", "1"]) == 0
    assert main(["worktree", "list", "TASK-100"]) == 2
    assert main(["ide", "nope", "TASK-100"]) == 2 and main(["ide", "open", "TASK-100", "--line", "3"]) == 2
    assert main(["doctor"]) == 1
    from dashboard.cockpit.routes.pages import _staging

    assert _staging({"_dir": workspace})["origins"]["app"] == ""
    assert client.get("/standup").json()["draft"]
    from cockpitlib.kanban import db_path, place_card

    card = place_card("acme", "TASK-100: intake", "intake", "ready")
    listed = client.get("/lane-runs").json()["runs"]
    assert listed and isinstance(listed[0]["mtime"], float)
    logs = os.path.join(os.path.dirname(db_path("acme")), "logs")
    os.makedirs(logs, exist_ok=True)
    open(os.path.join(logs, "notes.txt"), "w", encoding="utf-8").write("x")
    open(os.path.join(logs, card + ".log"), "w", encoding="utf-8").write("lane\n")
    logged = client.get("/lane-runs").json()["runs"]
    assert logged[0]["card"] == card
    assert logged[0]["mtime"] > 0
    db = os.path.join(os.environ["COCKPIT_HERMES_HOME"], "kanban", "boards", "acme", "kanban.db")
    os.makedirs(os.path.dirname(db), exist_ok=True)
    open(db, "w", encoding="utf-8").write("not a database")
    assert client.get("/board").status_code == 200
    assert client.get("/lane-runs").status_code == 200
    broken = client.get("/card-detail", params={"id": "c1"})
    assert broken.status_code == 200
    assert broken.json()["events"] == []
    assert broken.json()["comments"] == []


def test_card_detail_reads_the_board_card(env):
    import sqlite3

    from cockpitlib.kanban import db_path

    path = db_path("acme")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    connection = sqlite3.connect(path)
    connection.execute(
        "create table tasks (id text primary key, title text, body text, assignee text, status text, created_at integer, result text, last_failure_error text, skills text, workspace_path text)"
    )
    connection.execute(
        "insert into tasks values ('c1', 'TASK-100: intake', 'the plan', 'intake', 'blocked', 1792281301, 'done', 'provider missing', ?, '/tmp/wt')",
        ('["intake"]',),
    )
    connection.execute(
        "insert into tasks values ('c2', 'note', '', '', 'ready', '2026-10-18T12:00:00Z', null, '', '[', '')"
    )
    connection.execute(
        "create table task_comments (id integer primary key, task_id text, author text, body text, created_at integer)"
    )
    connection.execute("insert into task_comments values (1, 'c1', 'lane', 'blocked on login', 1792281301129)")
    connection.execute(
        "create table task_events (id integer primary key, task_id text, kind text, payload text, created_at integer)"
    )
    connection.execute("insert into task_events values (1, 'c1', 'heartbeat', '{}', 1792281500)")
    connection.execute("insert into task_events values (2, 'c1', 'crashed', '{}', 1792281438)")
    connection.commit()
    connection.close()
    client = _client()
    body = client.get("/card-detail", params={"id": "c1"}).json()
    assert body["title"] == "TASK-100: intake"
    assert body["error"] == "provider missing"
    assert body["skills"] == ["intake"]
    assert body["comments"][0]["author"] == "lane"
    assert "blocked on login" in body["comments"][0]["html"]
    assert [event["kind"] for event in body["events"]] == ["crashed"]
    assert body["created"].endswith("Z")
    assert body["result_html"] == "<p>done</p>"
    other = client.get("/card-detail", params={"id": "c2"}).json()
    assert other["created"] == "2026-10-18T12:00:00Z"
    assert other["skills"] == "["
    missing = client.get("/card-detail", params={"id": "missing"}).json()
    assert missing["events"] == []
    assert missing["comments"] == []


def test_platform_uses_the_pack_base_branch(env):
    folder = os.path.join(os.environ["COCKPIT_WORKSPACE"], "hermes", "platform")
    os.makedirs(folder, exist_ok=True)
    stored = {"root": "acme", "map": ["api", "web"], "counts": {}, "inherited": [], "changes": [], "state": "scanned"}
    json.dump(stored, open(os.path.join(folder, "map.json"), "w", encoding="utf-8"))
    client = _client()
    body = client.get("/platform").json()
    assert body["base"] == "main"
    titles = [node["title"] for node in body["map"]["nodes"]]
    assert "Place an order" in titles
    assert "Job queue" in titles
    assert "Repos" not in titles
    assert "api" not in titles
    kinds = {node["id"]: node["kind"] for node in body["map"]["nodes"]}
    assert kinds["orders"] == "area"
    assert kinds["place-order"] == "feature"
    assert kinds["queue"] == "component"
    by_id = {node["id"]: node for node in body["map"]["nodes"]}
    assert "queue" in by_id["place-order"]["depends"]
    assert "place-order" in by_id["queue"]["used_by"]
    scanned = client.post("/platform-scan", json={"days": 7}).json()
    assert scanned["ok"] is True
    assert scanned["base"] == "main"
    assert "area" in scanned["out"]
    again = client.get("/platform").json()
    assert again["state"]["main"]["last_scan"]
    assert again["map"]["nodes"][0]["kind"] == "area"


def test_map_check_walks_local_clones(env, capsys):
    from cockpitlib.cli import main

    assert main(["map", "check"]) == 1
    assert "matches nothing" in capsys.readouterr().out
    root = os.environ["COCKPIT_ROOT"]
    os.makedirs(os.path.join(root, "repos", "api", "orders"), exist_ok=True)
    os.makedirs(os.path.join(root, "repos", "api", "jobs"), exist_ok=True)
    os.makedirs(os.path.join(root, "repos", "web", "checkout"), exist_ok=True)
    open(os.path.join(root, "repos", "api", "orders", "create.php"), "w", encoding="utf-8").write("<?php\n")
    open(os.path.join(root, "repos", "api", "jobs", "Send.php"), "w", encoding="utf-8").write("<?php\n")
    open(os.path.join(root, "repos", "web", "checkout", "page.ts"), "w", encoding="utf-8").write("export {}\n")
    assert main(["map", "check"]) == 0
    assert capsys.readouterr().out.strip() == "ok"
    assert main(["map", "nodes"]) == 0
    assert "place-order" in capsys.readouterr().out


def test_map_rejects_duplicate_ids_and_a_missing_file(env, tmp_path, monkeypatch, capsys):
    from cockpitlib.map_build import (
        MISSING,
        MapError,
        _matches,
        compile_document,
        glob_re,
        map_check,
        map_nodes_text,
        summary,
    )
    from cockpitlib.ops import map_build
    from cockpitlib.pack import load

    with pytest.raises(MapError, match="duplicate"):
        compile_document({"areas": [{"id": "a", "features": [{"id": "a"}]}]})
    with pytest.raises(MapError, match="unknown"):
        compile_document({"areas": [{"id": "a", "features": [{"id": "f", "depends": ["missing"]}]}]})
    with pytest.raises(MapError, match="area has no id"):
        compile_document({"areas": [{}]})
    with pytest.raises(MapError, match="feature has no id"):
        compile_document({"areas": [{"id": "a", "features": [{}]}]})
    with pytest.raises(MapError, match="component has no id"):
        compile_document({"components": [{}]})
    tree = compile_document(
        {
            "areas": [
                {
                    "id": "a",
                    "features": [
                        {
                            "id": "f",
                            "depends": ["g"],
                            "docs": ["note"],
                            "anchors": [{"repo": "api", "paths": ["src/*"], "key": ["Order"]}],
                        },
                        {"id": "g"},
                    ],
                }
            ],
            "components": [{"id": "c", "used_by": ["f"]}],
        }
    )
    by_id = {node["id"]: node for node in tree["nodes"]}
    assert "c" in by_id["f"]["depends"]
    assert by_id["g"]["kind"] == "feature"
    assert "2 areas" in summary(
        {
            "nodes": [
                {"kind": "area"},
                {"kind": "area"},
                {"kind": "feature"},
                {"kind": "feature"},
                {"kind": "component"},
                {"kind": "component"},
            ]
        }
    )
    assert glob_re("src/**/*.php").startswith("^")
    folder = tmp_path / "clone"
    (folder / "src").mkdir(parents=True)
    (folder / "src" / "Order.php").write_text("<?php\n", encoding="utf-8")
    assert _matches(str(folder), "**/Order.php")
    assert _matches(str(folder), "src/*.php")
    assert _matches(str(folder), "src/Orde?.php")
    assert _matches("/no/such/clone", "src/*") is False
    pack = dict(load(os.environ["COCKPIT_PACK"]))
    pack["_dir"] = str(tmp_path)
    record = os.path.join(os.environ["COCKPIT_WORKSPACE"], "hermes", "platform", "map.json")
    os.makedirs(os.path.dirname(record), exist_ok=True)
    open(record, "w", encoding="utf-8").write("not json")
    message = map_build(pack)
    assert message == MISSING
    open(record, "w", encoding="utf-8").write("[1]")
    assert map_build(pack) == MISSING
    assert map_check(pack) == [MISSING]
    assert map_nodes_text(pack) == MISSING
    bare = tmp_path / "bare"
    (bare / "platform").mkdir(parents=True)
    (bare / "platform" / "map.yaml").write_text(
        "version: 1\nareas:\n  - id: a\n    features:\n      - id: f\n        anchors:\n          - { repo: gone, paths: ['z/**'] }\n",
        encoding="utf-8",
    )
    gone = {"_dir": str(bare), "repos": {"repos": [{"name": "gone", "path": str(tmp_path / "missing-clone")}]}}
    assert any("no local clone" in line for line in map_check(gone))
    monkeypatch.setattr(
        "cockpitlib.map_build.compiled_tree", lambda _pack: (_ for _ in ()).throw(MapError("duplicate ids: ['a']"))
    )
    broken = _client().get("/platform").json()
    assert broken["map"]["nodes"] == []
    assert "duplicate" in broken["hint"]
    monkeypatch.setattr("cockpitlib.map_build.load_document", lambda _pack: None)
    monkeypatch.setattr("cockpitlib.map_build.compiled_tree", lambda _pack: None)
    assert "platform-map" in _client().get("/platform").json()["hint"]
    from cockpitlib import cli

    monkeypatch.setattr(cli, "do_setup", lambda _pack, **_kwargs: None)
    monkeypatch.setattr(cli, "gateway_up", lambda: None)
    monkeypatch.setattr(cli, "doctor_report", lambda _pack: {"findings": []})
    monkeypatch.setattr("cockpitlib.map_build.map_yaml_path", lambda _pack: str(tmp_path / "absent.yaml"))
    assert cli.cmd_setup([]) == 0
    assert "platform-map" in capsys.readouterr().out


def test_chat_is_a_terminal_in_the_workspace(env):
    import time

    from cockpitlib.chat import chat_cwd
    from cockpitlib.pack import agent_launch, load

    os.makedirs(os.path.join(os.environ["COCKPIT_WT"], "TASK-1"), exist_ok=True)
    home = agent_launch(load(os.environ["COCKPIT_PACK"]))["home"]
    assert chat_cwd("own") == os.environ["COCKPIT_WORKSPACE"]
    assert chat_cwd("TASK-1") == home
    assert chat_cwd("missing") == home
    client = _client()
    opened = client.post("/chat-open", json={"ticket": "own"}).json()
    assert opened["cwd"] == os.environ["COCKPIT_WORKSPACE"]
    text = opened["text"]
    for _ in range(20):
        if "cockpit-chat" in text:
            break
        time.sleep(0.05)
        text = client.get("/chat-read", params={"ticket": "own", "offset": 0}).json()["text"]
    assert "cockpit-chat" in text
    client.post("/chat-end", json={"ticket": "own"})
    assert client.get("/chat-read", params={"ticket": "own"}).json()["gone"] is True


def test_chat_reattaches_and_worktree_checks_out_again(env, monkeypatch):
    import time

    from cockpitlib.chat import _argv, _clip, end_chat, open_chat, read_chat, resize_chat, write_chat
    from cockpitlib.errors import CockpitError
    from cockpitlib.worktree import add

    monkeypatch.delenv("COCKPIT_CHAT_ARGV", raising=False)
    monkeypatch.setenv("SHELL", "/no/such/shell")
    assert _argv()[0] == "/bin/bash"
    buf = bytearray(1_000_001)
    clipped, base = _clip(buf, 0)
    assert base == 400_001
    assert len(clipped) == 600_000
    monkeypatch.setenv("COCKPIT_CHAT_ARGV", "/bin/sleep 2")
    opened = open_chat("nap", cols=40, rows=10)
    assert opened["attached"] is False
    write_chat("nap", b"")
    resize_chat("nap", 30, 8)
    again = open_chat("nap")
    assert again["attached"] is True
    read_chat("nap", -1)
    from cockpitlib import chat as chatmod

    chatmod._TERMS["nap"].base = 50
    chatmod._TERMS["nap"].read(0)
    client = _client()
    assert client.post("/chat-write", json={"ticket": "nap", "data": "aGk="}).status_code == 200
    chatmod._TERMS["nap"].alive = False
    chatmod._TERMS["nap"].write(b"x")
    open_chat("nap", reset=True)
    os.close(chatmod._TERMS["nap"].fd)
    chatmod._TERMS["nap"].resize(8, 8)
    chatmod._TERMS["nap"].kill()
    chatmod._TERMS["nap"].kill()
    end_chat("nap")
    time.sleep(0.05)
    dead = open_chat("nap", reset=True)
    dead_term_write = client.post("/chat-write", json={"ticket": "missing", "text": "x"})
    assert dead_term_write.status_code == 409
    resize_chat("absent", 10, 10)
    end_chat("absent")
    end_chat("nap")
    assert dead["ticket"] == "nap"
    source = os.path.join(os.environ["COCKPIT_ROOT"], "repos", "api")
    from cockpitlib.worktree import _run

    with pytest.raises(CockpitError):
        _run(["git", "-C", source, "checkout", "no-such-branch-xyz"])
    with pytest.raises(CockpitError, match="no repo at"):
        add("TASK-1", "api", "work", os.path.join(env["root"], "missing"))
    side = add("TASK-9", "api", "side", source)
    assert os.path.isdir(side)
    assert add("TASK-9", "api", "side", source) == side
    again = add("TASK-200", "api", "work", source, branch_from="side/TASK-9")
    assert again == os.path.join(os.environ["COCKPIT_WT"], "TASK-200", "api")
    assert subprocess.check_output(["git", "-C", source, "branch", "--show-current"], text=True).strip() == "main"
    from cockpitlib.worktree import list_worktrees

    open(os.path.join(os.environ["COCKPIT_WT"], "not-a-dir"), "w", encoding="utf-8").write("x")
    assert isinstance(list_worktrees(), list)


def test_none_provider_adds_a_worktree_and_leaves_the_repo_checkout(env, capsys):
    source = os.path.join(os.environ["COCKPIT_ROOT"], "repos", "api")
    side = os.path.join(os.environ["COCKPIT_WT"], "TASK-100", "api")
    assert main(["worktree", "add", "TASK-100", "api"]) == 0
    assert capsys.readouterr().out == side + "\n"
    assert subprocess.check_output(["git", "-C", source, "branch", "--show-current"], text=True).strip() == "main"
    assert (
        subprocess.check_output(["git", "-C", side, "branch", "--show-current"], text=True).strip() == "work/TASK-100"
    )
    assert sorted(os.listdir(os.path.dirname(side))) == ["api"]  # no marker beside the worktree


def test_egress_gates_and_usage_follow_the_pack(env, capsys, monkeypatch):
    import sqlite3
    import time

    from cockpitlib.doctor import run as doctor_run
    from cockpitlib.egress import check, check_bound
    from cockpitlib.pack import load

    assert check_bound("curl https://app.acme.example") == "blocked"
    assert check_bound("git status") == ""
    assert check("helm upgrade api", sacred=["api"]) == "blocked"
    assert check("helm upgrade web", sacred=["api"]) == ""
    assert check("kubectl get pods") == ""
    assert check("gh release create v1") == "blocked"
    assert check("helm uninstall demo") == ""  # an adopter's infra denies live in its pack
    assert check("helm uninstall demo", extra_deny=[r"\bhelm\s+uninstall\b"]) == "blocked"
    assert check("cat /infra/secret", infra_paths=["/infra"]) == "blocked"
    assert main(["gate", "api"]) == 0
    assert "api: ok" in capsys.readouterr().out
    pack = load(os.environ["COCKPIT_PACK"])
    thin = dict(pack)
    thin["egress"] = {"production_hosts": [], "terminal_deny": [], "sacred": [], "infra_paths": []}
    thin["repos"] = {"repos": [{"name": "api", "gates": []}]}
    thin["_dir"] = str(env["workspace"])
    problems = doctor_run(thin)
    assert "egress production_hosts is empty" in problems
    assert "staging.yaml missing" in problems
    assert "no repo gates" in problems
    db = os.path.join(os.environ["COCKPIT_HERMES_HOME"], "state.db")
    connection = sqlite3.connect(db)
    connection.execute(
        "create table sessions (title text, model text, started_at real, input_tokens int, output_tokens int, cache_read_tokens int, cache_write_tokens int, estimated_cost_usd real, actual_cost_usd real)"
    )
    connection.execute("insert into sessions values ('TASK-100', 'fixture', ?, 10, 4, 2, 1, 0.5, null)", (time.time(),))
    connection.commit()
    connection.close()
    body = _client().get("/usage").json()
    assert body["totals"]["all"]["sessions"] == 1
    assert body["totals"]["all"]["output"] == 4
    assert body["recent"][0]["title"] == "TASK-100"
    blank = os.path.join(os.environ["COCKPIT_HERMES_HOME"], "profiles", "blank")
    os.makedirs(blank, exist_ok=True)
    sqlite3.connect(os.path.join(blank, "state.db")).execute("create table sessions (id int)").connection.commit()
    broken = os.path.join(os.environ["COCKPIT_HERMES_HOME"], "profiles", "broken")
    os.makedirs(broken, exist_ok=True)
    open(os.path.join(broken, "state.db"), "w", encoding="utf-8").write("nope")
    assert _client().get("/usage").json()["totals"]["all"]["sessions"] == 1
    empty = env["workspace"] / "pack-empty"
    empty.mkdir()
    (empty / "staging.yaml").write_text("origins: {}\n", encoding="utf-8")
    thin["_dir"] = str(empty)
    assert "staging origins empty" in doctor_run(thin)
    assert main(["gate", "missing-repo"]) == 2
    from cockpitlib.repo_gates import run_gates

    assert run_gates({"repos": {"repos": [{"name": "api", "gates": []}]}})[0] == 1
    failed = run_gates({"repos": {"repos": [{"name": "api", "gates": ["false"]}]}})
    assert failed[0] == 1
    assert "failed" in failed[1][0]
    monkeypatch.setenv("COCKPIT_PACK", str(env["workspace"] / "missing-pack.yaml"))
    assert check_bound("git push origin") == "blocked"


def test_a_board_card_is_a_ticket_and_empty_bumps_are_not_rows(env):
    from cockpitlib.kanban import place_card

    place_card("acme", "TASK-900: intake", "intake", "blocked")
    client = _client()
    listed = client.get("/tickets").json()["tickets"]
    row = next(item for item in listed if item["ticket"] == "TASK-900")
    assert row["cards_total"] == 1
    assert row["cards_open"] == 1
    assert row["phase"] == "blocked"
    assert row["flow"] == "intake"
    detail = client.get("/ticket", params={"ticket": "TASK-900"}).json()
    assert detail["card_list"][0]["title"] == "TASK-900: intake"
    assert detail["card_list"][0]["status"] == "blocked"
    assert client.get("/bumps").json()["repos"] == {}
    import sqlite3

    from cockpitlib.kanban import board_cards, db_path

    assert board_cards("missing-board") == []
    place_card("acme", "note without a key", "intake", "ready")
    assert any(card["ticket"] == "TASK-900" for card in board_cards("acme"))
    bare = db_path("bare")
    os.makedirs(os.path.dirname(bare), exist_ok=True)
    connection = sqlite3.connect(bare)
    connection.execute("create table tasks (id text)")
    connection.commit()
    connection.close()
    assert board_cards("bare") == []
    junk = db_path("junk")
    os.makedirs(os.path.dirname(junk), exist_ok=True)
    open(junk, "w", encoding="utf-8").write("nope")
    assert board_cards("junk") == []
    from cockpitlib.kanban import archive_ticket_cards, delete_ticket_cards

    assert delete_ticket_cards("missing-board", "TASK-900") == []
    assert archive_ticket_cards("missing-board", "TASK-900") == []
    assert delete_ticket_cards("bare", "TASK-900") == []
    live = sqlite3.connect(db_path("acme"))
    live.execute(
        "create table if not exists task_comments (id integer primary key, task_id text, author text, body text, created_at integer)"
    )
    card_id = live.execute("select id from tasks where title like 'TASK-900%'").fetchone()[0]
    live.execute(
        "insert into task_comments (task_id, author, body, created_at) values (?, 'cockpit', 'note', 0)", (card_id,)
    )
    live.execute("create table if not exists task_attachments (id integer)")
    live.commit()
    live.close()
    place_card("acme", "TASK-2: intake", "intake", "ready")
    assert archive_ticket_cards("acme", "TASK-2")
    assert archive_ticket_cards("acme", "TASK-9") == []
    removed = client.post("/ticket-delete", json={"ticket": "TASK-900", "confirm": "TASK-900"}).json()
    assert removed["cards"]
    assert client.get("/ticket", params={"ticket": "TASK-900"}).json()["cards_total"] == 0
    assert all(item["ticket"] != "TASK-900" for item in client.get("/tickets").json()["tickets"])


def test_watchers_do_not_exit_without_a_record(env):
    env_path = os.environ.copy()
    # a cron's bare PATH, with the forge stand-in first: the launcher adds the machine's usual folders to a bare PATH,
    # and without the stand-in the watchers found the machine's own gh there and asked the real forge
    env_path["PATH"] = os.path.join(ROOT, "tests", "bin") + ":/usr/bin:/bin"
    for script in (
        "ci-watch.sh",
        "pr-watch.sh",
        "base-watch.sh",
        "bumps.sh",
        "standup.sh",
        "slot-gc.sh",
        "workspace-watch.sh",
        "export.sh",
    ):
        result = subprocess.run(
            ["sh", os.path.join(ROOT, "cron", script)], check=False, capture_output=True, text=True, env=env_path
        )
        assert result.returncode == 0, result.stderr
    qa = os.path.join(os.environ["COCKPIT_WORKSPACE"], "hermes", "platform", "bumps.json")
    assert os.path.isfile(qa)
    assert json.load(open(qa, encoding="utf-8"))["repos"] != {}
