# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
import json
import os
import shutil

import pytest
import yaml
from fastapi import FastAPI
from fastapi.testclient import TestClient

from cockpitlib.cli import main
from cockpitlib.errors import CockpitError, NeedMigrate, PackError
from cockpitlib.fence import markers, outside
from cockpitlib.gh_cli import run_json
from cockpitlib.health import load as load_health
from cockpitlib.health import save as save_health
from cockpitlib.intents import check_ticket, load, next_seq
from cockpitlib.kanban import db_path, open_cards, ticket_of
from cockpitlib.lanes import free_lane, lanes_of
from cockpitlib.migrate import discover
from cockpitlib.outbox import amend, create, endorse, hold, verify
from cockpitlib.pack import check_known_providers, check_repos, find_skill
from cockpitlib.pack import load as load_pack
from cockpitlib.patch_apply import leave_open
from cockpitlib.paths import binding_file, load_binding, pack_path, root, workspace
from cockpitlib.plan import show
from cockpitlib.setup import _soul, gateway_down, setup
from cockpitlib.slots import claim, claimed_recently, provider_for, read_owner, write_owner, write_ticket
from cockpitlib.store import read_json
from cockpitlib.test_flow import banner, row_state, unfinished
from cockpitlib.time_util import iso
from cockpitlib.worktree import add, list_worktrees, mode, repo_source
from dashboard.cockpit.router import router


def _copy_pack(tmp_path):
    dest = tmp_path / "packs" / "acme"
    shutil.copytree(os.path.join(os.path.dirname(os.path.dirname(__file__)), "packs", "acme"), dest)
    return dest / "pack.yaml"


def test_pack_errors(tmp_path, env):
    path = _copy_pack(tmp_path)
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    raw["skills_dir"] = "/no/such/cockpit/skills"
    path.write_text(yaml.safe_dump(raw), encoding="utf-8")
    with pytest.raises(PackError, match="missing directory"):
        load_pack(str(path))
    raw["skills_dir"] = ["@bad name"]
    path.write_text(yaml.safe_dump(raw), encoding="utf-8")
    with pytest.raises(PackError, match="absolute"):
        load_pack(str(path))
    raw["skills_dir"] = []
    path.write_text(yaml.safe_dump(raw), encoding="utf-8")
    with pytest.raises(PackError, match="absolute"):
        load_pack(str(path))
    raw["skills_dir"] = "@skills"
    raw["ticket_pattern"] = "["
    path.write_text(yaml.safe_dump(raw), encoding="utf-8")
    with pytest.raises(PackError, match="ticket_pattern"):
        load_pack(str(path))
    raw["ticket_pattern"] = "NOPE"
    path.write_text(yaml.safe_dump(raw), encoding="utf-8")
    with pytest.raises(PackError, match="TASK-100"):
        load_pack(str(path))
    raw["ticket_pattern"] = "^[A-Z][A-Z0-9]*(?:-[A-Z0-9]+)+$"
    raw["providers"] = {"coding": {"command": []}}
    path.write_text(yaml.safe_dump(raw), encoding="utf-8")
    with pytest.raises(PackError, match="command"):
        load_pack(str(path))
    raw = yaml.safe_load(open(os.environ["COCKPIT_PACK"], encoding="utf-8"))
    data = load_pack(os.environ["COCKPIT_PACK"])
    assert find_skill(data, "missing-skill") is None
    with pytest.raises(PackError):
        check_repos(data, str(tmp_path))
    with pytest.raises(PackError, match="not configured"):
        check_known_providers(data, str(tmp_path))
    assert isinstance(raw, dict)


def test_paths_binding(env, monkeypatch):
    monkeypatch.delenv("COCKPIT_WORKSPACE")
    monkeypatch.delenv("COCKPIT_PACK")
    monkeypatch.delenv("COCKPIT_ROOT")
    with pytest.raises(NeedMigrate):
        workspace()
    home = env["home"]
    (home / "cockpit.yaml").write_text(
        "workspace: " + str(env["workspace"]) + "\npack: " + os.environ.get("COCKPIT_PACK", "") + "\n", encoding="utf-8"
    )
    monkeypatch.setenv("COCKPIT_HERMES_HOME", str(home))
    # binding pack path was empty because env was deleted before write. Rewrite.
    (home / "cockpit.yaml").write_text(
        f"workspace: {env['workspace']}\npack: {os.path.join(os.path.dirname(os.path.dirname(__file__)), 'packs', 'acme', 'pack.yaml')}\n",
        encoding="utf-8",
    )
    assert workspace() == str(env["workspace"])
    assert pack_path().endswith("pack.yaml")
    assert root() == os.path.dirname(str(env["workspace"]))
    assert binding_file().endswith("cockpit.yaml")
    assert load_binding()["workspace"]
    (home / "cockpit.yaml").write_text("- not-a-map\n", encoding="utf-8")
    assert load_binding() == {}


def test_cli_and_api(env):
    pack = load_pack(os.environ["COCKPIT_PACK"])
    setup(pack)
    assert main(["outbox"]) == 2
    assert (
        main(
            [
                "outbox",
                "new",
                "TASK-100",
                "push-branch",
                "--card",
                "card",
                "--summary",
                "summary",
                "--repo",
                "api",
                "--branch",
                "main",
            ]
        )
        == 0
    )
    assert main(["outbox", "list", "TASK-100"]) == 0
    ident = json.loads(os.popen("true").read() or "[]")
    from cockpitlib.intents import all_intents

    ident = all_intents("TASK-100")[0]["id"]
    assert main(["outbox", "endorse", ident, "low", "ok"]) == 0
    assert main(["outbox", "verify", ident]) == 0
    assert main(["publish", "--id", ident, "--dry-run"]) == 0
    assert main(["outbox", "hold", ident, "wait"]) == 0
    assert main(["outbox", "drop", ident, "no"]) == 0
    assert main(["outbox", "nope"]) == 2
    assert main(["plan", "show", "TASK-100"]) == 0
    assert main(["plan", "init", "TASK-100", "plan", "go"]) == 0
    assert main(["plan", "append", "TASK-100", "Reviewed", "clean"]) == 0
    assert main(["plan", "nope"]) == 2
    assert main(["slot", "free"]) == 0
    assert main(["slot", "nope"]) == 2
    assert main(["migrate", "draft"]) == 0
    assert main(["migrate", "nope"]) == 2
    assert main(["advise", "C1"]) == 1
    assert main(["pack"]) == 2
    done = create(pack, "TASK-100", "ticket-done", "c", "done", {})
    assert main(["outbox", "ack", done["id"]]) == 0
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    from cockpitlib.halt import write

    write("TASK-100", "stop")
    assert client.post("/kickoff", json={"ticket": "TASK-100", "mode": "intake"}).status_code == 409
    from cockpitlib.halt import clear

    clear("TASK-100")
    from tests.support.boards import insert_card

    insert_card("acme", "t9", "TASK-100: intake", "intake", "triage")
    assert client.post("/kickoff", json={"ticket": "TASK-100", "mode": "intake"}).status_code == 409
    pushed = create(pack, "TASK-500", "push-branch", "c", "push", {"repo": "api", "branch": "main"})
    endorse(pushed["id"], "low", "", "gatekeeper", "fixture-a", "fixture-large")
    assert (
        client.post("/publish", json={"id": pushed["id"], "confirm": pushed["id"], "dry_run": True}).status_code == 200
    )
    assert client.get("/intent", params={"id": pushed["id"]}).status_code == 200
    folder = env["workspace"] / "hermes" / "watch"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "ci-watch.json").write_text(json.dumps({"ok": False, "output": "timeout"}), encoding="utf-8")
    assert client.get("/needs-you").json()["rows"]
    os.environ.pop("COCKPIT_PACK")
    os.environ.pop("COCKPIT_WORKSPACE")
    assert client.get("/list").status_code == 409


def test_remaining_branches(env, monkeypatch):
    pack = load_pack(os.environ["COCKPIT_PACK"])
    assert row_state("Not run") == "open"
    assert row_state("Blocked") == "open"
    assert "screenshot" in unfinished([{"n": 3, "result": "✅ Pass", "evidence": "note.txt"}])[0]
    assert banner([{"n": 1, "result": "⚠️ Blocked", "evidence": ""}]) == "In progress"
    assert leave_open({"type": "Deferred"}, False) is True
    assert iso(None).endswith("Z")
    from datetime import datetime

    assert iso(datetime(2026, 1, 1)).endswith("Z")
    assert lanes_of("reviewer", 3, False) == ["reviewer", "reviewer-2", "reviewer-3"]
    assert free_lane("worker", pack, {"worker-1": 2}) == "worker-1"
    assert ticket_of("") == ""
    assert ticket_of("nope") == ""
    open_cards("acme")
    path = db_path("acme")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    open(path, "w", encoding="utf-8").write("not a database")
    assert open_cards("acme") == {}
    with pytest.raises(Exception):
        check_ticket("nope", pack["ticket_pattern"])
    assert next_seq("TASK-900") == "001"
    with pytest.raises(FileNotFoundError):
        load("TASK-900/001-push-branch")
    intent = create(pack, "TASK-900", "push-branch", "c", "p", {"repo": "api", "branch": "main"})
    assert verify(intent["id"], remote_tip="c") == ["lease moved"]
    with pytest.raises(CockpitError, match="a lane pushes a feature branch"):
        amend(intent["id"], summary="again", payload={"base": "origin/main"}, pack=pack)  # a lane may not take it over
    amend(intent["id"], summary="again", payload={"base": "origin/main"}, pack=pack, created_by="human")
    hold(intent["id"], "ask", ask="which?", options=["a", "b"])
    assert _soul(None, "lane", "missing").startswith("You are") or "lane" in _soul(None, "lane", "missing")
    claim(1)
    assert claimed_recently(1) is True
    open(os.path.join(os.environ["COCKPIT_VOLUMES"], "slot-1", "claim"), "w", encoding="utf-8").write("nope")
    assert claimed_recently(1) is False
    assert provider_for("none").login("TASK-1", "ada")["user"] == "ada"
    with pytest.raises(Exception, match="unknown slot"):
        provider_for("nope")
    write_owner(2, "")
    assert read_owner(2) == "free"
    write_ticket(2, "TASK-1")
    monkeypatch.setenv("COCKPIT_LANE", "worker-1")
    monkeypatch.delenv("COCKPIT_HUMAN")
    write_owner(2, "lane:worker-1")
    from cockpitlib.slots import check_access

    check_access(2, "TASK-1")
    with pytest.raises(Exception, match="bound"):
        check_access(2, "TASK-2")
    monkeypatch.delenv("COCKPIT_LANE")
    monkeypatch.delenv("COCKPIT_HUMAN", raising=False)
    monkeypatch.setenv("CURSOR_AGENT", "1")
    with pytest.raises(Exception, match="outside"):
        check_access(3, "TASK-1")
    skills = env["workspace"] / "skills" / "demo"
    skills.mkdir(parents=True)
    (skills / "SKILL.md").write_text("# demo\n", encoding="utf-8")
    found = discover(str(env["workspace"]))
    assert any(path.endswith("skills") or "skills" in path for path in found["skills_dir"]) or found["repos"] == []
    save_health(str(env["workspace"] / "hermes" / "watch"), "ci-watch", {"ok": False, "output": "timeout"})
    assert load_health(str(env["workspace"] / "hermes" / "watch"), "ci-watch")["ok"] is False
    save_health(str(env["workspace"] / "hermes" / "watch"), "empty", {"ok": True})
    with pytest.raises(Exception, match="no repo"):
        add("TASK-1", "api", "work", str(env["workspace"]))
    with pytest.raises(Exception, match="no worktree"):
        mode("TASK-1", "missing", False)
    with pytest.raises(Exception, match="unknown repo"):
        repo_source(pack, "nope")
    assert list_worktrees("missing-ticket") == []
    assert show("TASK-404") == ""

    class Result:
        returncode = 0
        stdout = ""
        stderr = ""

    assert run_json(["true"], runner=lambda argv: Result()) is None
    assert markers()
    monkeypatch.setattr("cockpitlib.fence.MARKER_FILE", str(env["workspace"] / "no-markers"))
    assert markers() == []
    assert outside(env={"COCKPIT_LANE": "worker-1", "CURSOR_AGENT": "1"}, cwd="/", worktrees="/wt") is False
    read_json(str(env["workspace"] / "not-json"))
    open(env["workspace"] / "not-json", "w", encoding="utf-8").write("{")
    assert read_json(str(env["workspace"] / "not-json")) is None
    gateway_down()
    from cockpitlib.capacity import compute, refusal

    caps = compute(1, {"tester-1": 1, "reviewer": 1}, {"slots": 1, "intake": 2, "reviewer": 2, "analyst": 1})
    assert caps["test"] == 0
    assert refusal("analyst", {"question": 0, "dev": 1, "review": 1, "why": ""})
    from cockpitlib.egress import _wide_search

    assert _wide_search("grep -r TODO /") is True
    from cockpitlib.doctor import run as doctor_run

    (env["home"] / "config.yaml").write_text("kanban:\n  auto_decompose: true\n", encoding="utf-8")
    assert doctor_run(pack)
    from cockpitlib.intents import is_intent_file

    assert is_intent_file("notes.json") is False
