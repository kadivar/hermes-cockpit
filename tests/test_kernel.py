# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
import json
import os
import runpy
import sys

import pytest
import yaml
from fastapi.testclient import TestClient

from cockpitlib.activity import counts
from cockpitlib.advise import advise
from cockpitlib.capacity import compute, refusal
from cockpitlib.cli import main
from cockpitlib.doctor import run as doctor_run
from cockpitlib.egress import check
from cockpitlib.errors import PackError
from cockpitlib.fence import outside
from cockpitlib.gh_cli import ForgeError, run_json
from cockpitlib.halt import clear, describe, halted, write
from cockpitlib.health import reason, should_retry
from cockpitlib.intents import advance, can_move
from cockpitlib.kanban import card_flow, mentions, open_cards, open_same, ticket_of
from cockpitlib.local_refs import find_local_refs
from cockpitlib.migrate import discover, draft, rollback, secrets_scan
from cockpitlib.outbox import create, endorse, hold, verify
from cockpitlib.pack import load
from cockpitlib.patch_apply import actions, leave_open
from cockpitlib.plan import append, init, sections
from cockpitlib.publish import execute, forge_for, submit_review
from cockpitlib.refusals import record
from cockpitlib.settings import load as load_settings
from cockpitlib.settings import over_budget
from cockpitlib.setup import setup
from cockpitlib.slots import check_access, free_slots, provider_for, write_owner
from cockpitlib.store import log, read_json, write_json
from cockpitlib.test_flow import banner, unfinished
from cockpitlib.time_util import iso, quiet
from cockpitlib.worktree import add, list_worktrees, mode
from tests.support import fake_gh
from tests.support.boards import init_db, insert_card


def test_pack_and_relative_skills(tmp_path, env):
    data = load(os.environ["COCKPIT_PACK"])
    assert data["providers"]["judgment"]["hermes_provider"] != data["providers"]["worker"]["hermes_provider"]
    broken = tmp_path / "pack.yaml"
    raw = yaml.safe_load(open(os.environ["COCKPIT_PACK"], encoding="utf-8"))
    raw["skills_dir"] = ["skills"]
    broken.write_text(yaml.safe_dump(raw), encoding="utf-8")
    with pytest.raises(PackError, match="absolute"):
        load(str(broken))


def test_loose_pattern_and_unknown_key(tmp_path, env):
    raw = yaml.safe_load(open(os.environ["COCKPIT_PACK"], encoding="utf-8"))
    raw["ticket_pattern"] = ".*"
    path = tmp_path / "pack.yaml"
    path.write_text(yaml.safe_dump(raw), encoding="utf-8")
    with pytest.raises(PackError, match="looser"):
        load(str(path))
    raw = yaml.safe_load(open(os.environ["COCKPIT_PACK"], encoding="utf-8"))
    raw["extra"] = 1
    path.write_text(yaml.safe_dump(raw), encoding="utf-8")
    with pytest.raises(PackError, match="unknown key"):
        load(str(path))


def test_transitions_and_time(env):
    row = {"id": "TASK-1/001-push-branch", "status": "pending"}
    assert can_move("pending", "endorsed")
    advance(row, "nope", "test")
    assert row["status"] == "nope"
    assert iso().endswith("Z")
    assert quiet(-1, 10) is False
    assert quiet(0, 400) is True


def test_localrefs_egress_fence_halt(env, monkeypatch):
    assert find_local_refs("see qa/TASK-100/a")
    assert check("git push origin x") == "blocked"
    assert check("gh pr create -t x") == "blocked"
    assert check("git status") == ""
    assert check("rg TODO /") == "blocked"
    assert check("curl https://app.acme.example/x", production_hosts=[r"app\.acme\.example"]) == "blocked"
    assert check(None) == "unreadable tool call"
    monkeypatch.delenv("COCKPIT_HUMAN")
    monkeypatch.setenv("CURSOR_AGENT", "1")
    assert outside(cwd=str(env["root"])) is True
    monkeypatch.setenv("COCKPIT_HUMAN", "1")
    assert outside(cwd=str(env["root"])) is False
    write("TASK-100", "pause")
    assert "pause" in describe("TASK-100", halted("TASK-100"))
    clear("TASK-100")
    assert halted("TASK-100") is None


def test_capacity_patch_testflow_health_settings():
    caps = compute(0, {"intake": 1}, {"slots": 1, "intake": 1, "reviewer": 1, "analyst": 1}, True, "over budget")
    assert refusal("intake", caps) == "over budget"
    caps = compute(1, {}, {"slots": 1, "intake": 1, "reviewer": 1, "analyst": 1})
    assert refusal("review", caps) == ""
    assert refusal("test", compute(0, {}, {"slots": 1, "intake": 1, "reviewer": 1, "analyst": 1}))
    rows = actions(
        [
            {"type": "Code", "thread": "t1"},
            {"type": "Deferred", "thread": "t2", "reply": "later"},
            {"type": "Other", "thread": "t3"},
        ]
    )
    assert rows[0]["resolve"] and rows[1]["leave_open"] and not rows[2]["reply"]
    assert leave_open({"type": "Code"}, True) is True
    table = [{"n": 1, "result": "✅ Pass", "evidence": "evidence/1.png"}, {"n": 2, "result": "", "evidence": ""}]
    assert unfinished(table) == ["2·open"]
    assert banner([{"n": 1, "result": "❌ Fail", "evidence": "evidence/1.png"}]) == "Failed"
    assert banner([{"n": 1, "result": "✅ Pass", "evidence": "evidence/1.png"}]) == "Passed"
    assert reason(None) == "no successful run yet"
    assert reason({"ok": True}) == ""
    assert "timed out" in reason({"ok": False, "output": "timed out"})
    assert "token" in reason({"ok": False, "output": "401 token"})
    assert "crashed" in reason({"ok": False, "trace": "x"})
    assert reason({"ok": False, "summary": "disk"}) == "disk"
    assert should_retry("429", 0) is True
    assert should_retry("429", 1) is False
    assert (
        over_budget(10, 5, [{"provider": "other", "name": "week", "used": 99}], 90, {"fixture-a"})
        == "spent 10.00 of 5.00"
    )
    assert "window" in over_budget(0, 0, [{"provider": "fixture-a", "name": "week", "used": 95}], 90, {"fixture-a"})


def test_kanban_and_refusals(env):
    assert ticket_of("TASK-100 do") == "TASK-100"
    assert mentions("see TASK-1 end", "TASK-1")
    assert not mentions("see TASK-12", "TASK-1")
    assert not mentions("XTASK-1", "TASK-1")
    assert card_flow("TASK-100: intake — go") == "intake"
    assert card_flow("TASK-100: review the PR") == "review"
    assert card_flow("nothing") == "card"
    init_db("acme")
    insert_card("acme", "t1", "TASK-100: intake", "intake", "running")
    assert open_cards("acme")["intake"] == 1
    assert open_same("acme", "TASK-100: intake") == "t1"
    assert open_cards("missing") == {}
    record("TASK-100", "tracker-comment", "t1", "tester-1", "local reference")
    assert not counts("slot-assign")
    assert counts("comment")


def test_outbox_publish_and_walk(env):
    pack = load(os.environ["COCKPIT_PACK"])
    with pytest.raises(Exception, match="local reference"):
        create(pack, "TASK-100", "tracker-comment", "c1", "note", {"body": "see qa/TASK-100/a"})
    sha = fake_gh.commit("api", "work/TASK-100")
    intent = create(
        pack, "TASK-100", "push-branch", "c1", "push", {"repo": "api", "branch": "work/TASK-100"}, "worker-1"
    )
    assert (
        intent["payload"]["sha"] == sha
        and intent["payload"]["remote_sha"] == ""
        and intent["payload"]["publish_as"] == "work/TASK-100"
    )
    assert verify(intent["id"], head_sha="zzz")
    endorse(intent["id"], "low", "ok", "gatekeeper", "fixture-a", "fixture-large", pack=pack)
    from cockpitlib.intents import load as load_intent

    row = load_intent(intent["id"])
    os.environ["COCKPIT_LANE"] = "worker-1"
    with pytest.raises(Exception, match="lane"):
        execute(row, pack=pack)
    del os.environ["COCKPIT_LANE"]
    good = execute(row, pack=pack)
    assert good["ok"] and good["sha"] == sha and fake_gh.remote("api", "work/TASK-100") == sha
    fake_gh.pull("acme/api", 1, "work/TASK-100", sha)
    review = create(
        pack,
        "TASK-100",
        "pr-review-submit",
        "c2",
        "review",
        {"repo": "api", "number": 1, "sha": sha, "event": "APPROVE"},
    )
    endorse(review["id"], "high", "no", "gatekeeper", "fixture-a", "fixture-large")
    posted = load_intent(review["id"])
    assert execute(posted, pack=pack, explicit_approve=True)["stage"] == "pending" and posted["status"] == "posted"
    with pytest.raises(Exception, match="APPROVE waits for green checks"):
        submit_review(posted, forge_for(pack), pack=pack)
    assert advise(pack, "C0", "matches the outline", ticket="TASK-100")["verdict"] == "APPROVED"
    from cockpitlib.skill_log import names_in

    assert names_in(None) == [] and names_in("nothing\nskill: \nskill:a\nskill:a\n") == ["a"]
    held = create(pack, "TASK-100", "pr-comment", "c3", "comment", {"repo": "api", "number": 1, "body": "hi"})
    hold(held["id"], "rewrite", rework="shorter")
    assert load_intent(held["id"])["status"] == "pending"
    path = init("TASK-100", "body", "go")
    append("TASK-100", "Delivered", "sha abc")
    assert "Delivered" in sections("TASK-100")
    assert os.path.isfile(path)
    write_json(os.path.join(env["workspace"], "outbox", "extra.json"), {"a": 1})
    assert read_json(os.path.join(env["workspace"], "outbox", "extra.json"))["a"] == 1
    assert read_json(os.path.join(env["workspace"], "missing.json")) is None
    log("note")
    assert main(["help"]) == 0
    assert main([]) == 2
    assert main(["nope"]) == 2


def test_publish_commands_and_chain(env, jira):
    pack = load(os.environ["COCKPIT_PACK"])
    sha = fake_gh.commit("api", "work/TASK-300")
    fake_gh.head("acme/api", "work/TASK-300", sha)
    first = create(pack, "TASK-300", "push-branch", "c", "push", {"repo": "api", "branch": "work/TASK-300"})
    second = create(
        pack,
        "TASK-300",
        "open-pr",
        "c",
        "open",
        {"repo": "api", "base": "main", "branch": "work/TASK-300", "title": "TASK-300"},
    )
    assert second["payload"]["after"] == first["id"] and second["payload"]["head"] == "work/TASK-300"
    endorse(first["id"], "low", "", "gatekeeper", "fixture-a", "fixture-large")
    endorse(second["id"], "low", "", "gatekeeper", "fixture-a", "fixture-large")
    from cockpitlib.intents import all_intents, save
    from cockpitlib.intents import load as load_intent

    by_id = {item["id"]: item for item in all_intents("TASK-300")}
    receipt = execute(by_id[second["id"]], by_id=by_id, pack=pack)
    assert receipt["ok"] and receipt["url"].endswith("/pull/1") and fake_gh.remote("api", "work/TASK-300") == sha
    save(by_id[first["id"]])
    save(by_id[second["id"]])
    assert main(["publish", "--id", second["id"], "--dry-run"]) == 1
    comment = create(pack, "TASK-300", "pr-comment", "c", "note", {"repo": "api", "number": 1, "body": "done"})
    endorse(comment["id"], "low", "", "gatekeeper", "fixture-a", "fixture-large")
    assert execute(load_intent(comment["id"]), pack=pack)["ok"]
    edit = create(pack, "TASK-300", "pr-edit", "c", "edit", {"repo": "api", "number": 1, "title": "x"})
    endorse(edit["id"], "low", "", "gatekeeper", "fixture-a", "fixture-large")
    assert execute(load_intent(edit["id"]), pack=pack)["ok"]
    rerun = create(pack, "TASK-300", "ci-rerun", "c", "rerun", {"repo": "api", "run_id": "1"})
    endorse(rerun["id"], "low", "", "gatekeeper", "fixture-a", "fixture-large")
    assert execute(load_intent(rerun["id"]), pack=pack)["ok"]
    assert fake_gh.state()["repos"]["acme/api"]["runs"]["1"]["reruns"] == 1
    ticket = create(pack, "TASK-300", "tracker-create", "c", "ticket", {"summary": "hello"})
    endorse(ticket["id"], "low", "", "gatekeeper", "fixture-a", "fixture-large")
    assert execute(load_intent(ticket["id"]), pack=pack)["ok"] and list(jira.issues) == ["TASK-101"]
    done = create(pack, "TASK-300", "ticket-done", "c", "done", {})
    from cockpitlib.outbox import ack, drop

    with pytest.raises(Exception, match="not executed"):
        execute(done, pack=pack)
    ack(done["id"])
    dropped = create(pack, "TASK-300", "infra-note", "c", "note", {"body": "later"})
    drop(dropped["id"], "no")
    assert load_intent(dropped["id"])["status"] == "dropped"


def test_setup_doctor_cli_and_slots(env, monkeypatch):
    pack = load(os.environ["COCKPIT_PACK"])
    setup(pack)
    assert doctor_run(pack) == []
    assert main(["doctor"]) == 0
    assert main(["status"]) == 0
    assert main(["down"]) == 0
    assert main(["up"]) == 0
    assert main(["pack", "check"]) == 0
    assert main(["advise", "C2", "a line", "--ticket", "TASK-100"]) == 0
    assert main(["plan", "init", "TASK-100", "outline", "go"]) == 0
    assert main(["plan", "sections", "TASK-100"]) == 0
    assert main(["outbox", "list"]) == 0
    assert main(["slot", "status"]) == 0
    assert main(["slot", "up", "1", "TASK-100"]) == 0
    assert free_slots(1) == []
    write_owner(1, "free")
    provider = provider_for("none", {**pack, "slots": {"provider": "none", "exec_refuse": ["\\bledger\\s+wipe\\b"]}})
    provider.up(1, "TASK-200")
    assert provider.down(1) is None and provider.reset(1) is None
    assert provider.exec(1, ["echo", "ok"])["argv"] == ["echo", "ok"]
    with pytest.raises(Exception, match="refused"):
        provider.exec(1, ["ledger", "wipe", "all"])
    monkeypatch.delenv("COCKPIT_HUMAN")
    monkeypatch.setenv("COCKPIT_LANE", "worker-1")
    write_owner(1, "human")
    with pytest.raises(Exception, match="manual"):
        check_access(1, "TASK-200")
    monkeypatch.delenv("COCKPIT_LANE")
    monkeypatch.setenv("COCKPIT_HUMAN", "1")
    write_owner(1, "lane:worker-1")
    with pytest.raises(Exception, match="pipeline"):
        check_access(1, "TASK-200")
    assert main(["migrate", "discover"]) == 0
    assert main(["help"]) == 0
    assert main([]) == 2
    assert main(["nope"]) == 2


def test_migrate_worktree_and_page(env):
    found = discover(str(env["workspace"]))
    assert found["skills_dir"] == [] or all(os.path.isabs(path) for path in found["skills_dir"])
    dest = env["workspace"] / "draft"
    draft({"name": "ws", "skills_dir": ["/tmp"], "repos": []}, str(dest))
    assert (dest / "pack.yaml").is_file()
    with pytest.raises(Exception, match="secret"):
        draft(
            {"name": "ws", "skills_dir": ["/tmp"], "repos": [], "token": "password=hunter2"},
            str(env["workspace"] / "bad"),
        )
    assert secrets_scan("safe") == ""
    home = str(env["home"])
    snap = env["root"] / "snap"
    (snap / "profiles" / "intake").mkdir(parents=True)
    (snap / "config.yaml").write_text("kanban:\n  auto_decompose: false\n", encoding="utf-8")
    (env["home"] / "cockpit.yaml").write_text("pack: x\n", encoding="utf-8")
    restored = rollback(str(snap), home)
    assert restored
    assert not (env["home"] / "cockpit.yaml").exists()
    with pytest.raises(Exception, match="snapshot"):
        rollback("", home)
    source = env["root"] / "repos" / "api"
    subprocess_ok = add("TASK-400", "api", "work", str(source))
    assert os.path.isdir(subprocess_ok) or subprocess_ok
    if os.path.isdir(os.path.join(os.environ["COCKPIT_WT"], "TASK-400", "api")):
        assert mode("TASK-400", "api", True) == "ALLOWED"
    assert isinstance(list_worktrees(), list)
    from fastapi import FastAPI

    from dashboard.cockpit.router import router

    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    assert client.get("/settings").status_code == 200
    body = client.get("/settings").json()
    assert body["display_name"] == "Chat"
    assert client.get("/list").status_code == 200
    assert client.get("/capacity").status_code == 200
    from cockpitlib.plan import init as init_plan

    init_plan("TASK-100", "body", "go")
    assert client.post("/kickoff", json={"ticket": "TASK-100", "mode": "review"}).status_code == 200
    assert client.get("/needs-you").status_code == 200
    missing = client.post("/publish", json={"id": "TASK-1/001-push-branch", "confirm": "no"})
    assert missing.status_code == 400


def test_bin_and_hook_and_forge(env, monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["cockpit", "status"])
    with pytest.raises(SystemExit) as caught:
        runpy.run_path(os.path.join(os.path.dirname(os.path.dirname(__file__)), "bin", "cockpit"), run_name="__main__")
    assert caught.value.code == 0
    import importlib.util
    import io

    hook_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "hooks", "egress.py")
    spec = importlib.util.spec_from_file_location("egress_hook", hook_path)
    egress = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(egress)
    monkeypatch.setattr(sys, "stdin", io.StringIO("{"))
    assert egress.main() == 2
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps({"tool_input": {"command": "git status"}})))
    assert egress.main() == 0
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps({"tool_input": {"command": "git push"}})))
    assert egress.main() == 2

    class Result:
        returncode = 0
        stdout = '{"ok": true}'
        stderr = ""

    assert run_json(["true"], runner=lambda argv: Result())["ok"] is True
    bad = Result()
    bad.returncode = 1
    bad.stdout = ""
    bad.stderr = "nope"
    with pytest.raises(ForgeError):
        run_json(["true"], runner=lambda argv: bad)
    with pytest.raises(
        ForgeError, match="no-such-forge-cli"
    ):  # a missing binary is a forge failure, not a crash (a cron's bare PATH)
        run_json(["no-such-forge-cli", "api"])
    settings = load_settings(load(os.environ["COCKPIT_PACK"]))
    assert settings["budget"]["monthly_usd"] == 0
    capsys.readouterr()


def test_plugin_register(env):  # the hook resolves the workspace: without the fixture it would lean on a real binding
    class Ctx:
        def __init__(self):
            self.skills = []
            self.hooks = {}

        def register_skill(self, name, path):
            self.skills.append(name)

        def register_hook(self, event, fn):
            self.hooks[event] = fn

    import importlib

    importlib.import_module("__init__") if False else None
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "cockpit_plugin", os.path.join(os.path.dirname(os.path.dirname(__file__)), "__init__.py")
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    ctx = Ctx()
    module.register(ctx)
    from cockpitlib.pack import BUNDLED

    assert sorted(ctx.skills) == sorted(BUNDLED)
    from tests.support.hermes_contract import block_message, call

    pushed = call(ctx.hooks["pre_tool_call"], "pre_tool_call", tool_name="terminal", args={"command": "git push"})
    assert block_message(pushed)
    assert (
        call(ctx.hooks["pre_tool_call"], "pre_tool_call", tool_name="terminal", args={"command": "git status"}) is None
    )


def test_store_write_failure(env, monkeypatch):
    from cockpitlib import store

    target = env["workspace"] / "hermes" / "outbox" / "boom.json"

    def explode(*_args, **_kwargs):
        raise OSError("disk")

    monkeypatch.setattr(store.os, "replace", explode)
    with pytest.raises(OSError):
        store.write_json(str(target), {"a": 1})


def test_config_merge_and_symlink(env, monkeypatch):
    from cockpitlib.setup import _board_flags, _ensure_plugin, _init_board_db

    pack = load(os.environ["COCKPIT_PACK"])
    config = env["home"] / "config.yaml"
    config.write_text(
        "plugins:\n  clone_timeout_seconds: 300\n"
        "# note\n"
        "  enabled:\n"
        "    - other\n"
        "kanban:\n"
        "  review_dispatch: true\n"
        "  failure_limit: 2\n"
        "model:\n"
        "  default: demo\n"
        "kanban:\n"
        "  auto_decompose: false\n"
        "  review_dispatch: false\n"
        "  failure_limit: 9\n"
        "  extra_limit: 3\n",
        encoding="utf-8",
    )
    _board_flags(pack)
    text = config.read_text(encoding="utf-8")
    assert [line for line in text.splitlines() if line.startswith("kanban:")] == ["kanban:"]
    assert "  review_dispatch: true" not in text
    assert "  review_dispatch: false" in text
    assert "  auto_decompose: false" in text
    assert "  failure_limit: 2" in text
    assert "  extra_limit: 3" in text
    assert "  default: demo" in text
    assert text.count("    - cockpit") == 1
    assert "    - other" in text
    marker = env["home"] / "kanban" / "boards" / pack["board"] / "board.json"
    assert json.loads(marker.read_text(encoding="utf-8"))["slug"] == pack["board"]
    _board_flags(pack)
    again = config.read_text(encoding="utf-8")
    assert again.splitlines().count("kanban:") == 1
    assert again.count("    - cockpit") == 1
    bare = _ensure_plugin("plugins:\n  clone_timeout_seconds: 1\n")
    assert "    - cockpit" in bare
    from cockpitlib.setup import _merge_kanban

    assert _merge_kanban("model: demo").splitlines()[0] == "model: demo"
    assert _ensure_plugin("model: demo").endswith("    - cockpit\n")
    commented = _ensure_plugin("plugins:\n  enabled:\n    - other\n\n    # keep\nmodel:\n  default: x\n")
    assert "    - cockpit" in commented
    assert "# keep" in commented
    calls = []
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.setattr("cockpitlib.setup.shutil.which", lambda _name: None)
    _init_board_db(pack["board"])
    monkeypatch.setattr("cockpitlib.setup.shutil.which", lambda _name: "/usr/bin/hermes")
    monkeypatch.setattr("cockpitlib.setup.subprocess.run", lambda argv, **kwargs: calls.append((argv, kwargs)))
    _init_board_db(pack["board"])
    assert calls[0][0][-1] == pack["board"]
    assert calls[0][1]["env"]["HERMES_HOME"] == str(env["home"])
    db = env["home"] / "kanban" / "boards" / pack["board"] / "kanban.db"
    db.write_text("", encoding="utf-8")
    _init_board_db(pack["board"])
    assert len(calls) == 1
    link_dir = env["root"] / "linked-bin"
    link_dir.mkdir()
    target = os.path.join(os.path.dirname(os.path.dirname(__file__)), "bin", "cockpit")
    os.symlink(target, link_dir / "cockpit")
    monkeypatch.setattr(sys, "argv", ["cockpit", "status"])
    with pytest.raises(SystemExit) as caught:
        runpy.run_path(str(link_dir / "cockpit"), run_name="__main__")
    assert caught.value.code == 0


def test_hook_allowlist(env):
    from cockpitlib.lanes import profile_dir
    from cockpitlib.setup import _allow_hook

    pack = load(os.environ["COCKPIT_PACK"])
    path = _allow_hook(pack)
    seat = os.path.join(profile_dir("intake"), "shell-hooks-allowlist.json")
    seat_cmd = json.loads(open(seat, encoding="utf-8").read())["approvals"][0]["command"]
    root_cmd = json.loads(open(path, encoding="utf-8").read())["approvals"][0]["command"]
    assert seat_cmd == root_cmd
    data = json.loads(open(path, encoding="utf-8").read())
    hook = next(item["command"] for item in data["approvals"] if item["event"] == "pre_tool_call")
    assert hook.endswith("hooks/egress.py")
    data["approvals"].append({"event": "pre_tool_call", "command": "other"})
    open(path, "w", encoding="utf-8").write(json.dumps(data))
    _allow_hook()
    again = json.loads(open(path, encoding="utf-8").read())
    commands = [item["command"] for item in again["approvals"]]
    assert commands.count(hook) == 1
    assert "other" in commands
    open(path, "w", encoding="utf-8").write("{")
    healed = json.loads(open(_allow_hook(), encoding="utf-8").read())
    assert [item["command"] for item in healed["approvals"]] == [hook]
    assert oct(os.stat(path).st_mode & 0o777) == "0o600"


def test_reload_gateway_skips_foreign_home(env, monkeypatch):
    from cockpitlib.setup import _reload_gateway

    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.setattr("cockpitlib.setup.hermes_home", lambda: "/tmp/other-home")
    monkeypatch.setattr("cockpitlib.setup.os.path.realpath", lambda path: path)
    monkeypatch.setattr("cockpitlib.setup.os.path.expanduser", lambda path: "/home/owner/.hermes")
    calls = []
    monkeypatch.setattr("cockpitlib.setup.subprocess.run", lambda *args, **kwargs: calls.append(args))
    _reload_gateway()
    monkeypatch.setattr("cockpitlib.setup.hermes_home", lambda: "/home/owner/.hermes")
    monkeypatch.setattr("cockpitlib.setup.shutil.which", lambda _name: None)
    _reload_gateway()
    monkeypatch.setattr("cockpitlib.setup.shutil.which", lambda _name: "/usr/bin/hermes")

    def run(argv, **kwargs):
        calls.append(argv)

        class Result:
            stdout = "inactive"
            stderr = ""

        return Result()

    monkeypatch.setattr("cockpitlib.setup.subprocess.run", run)
    _reload_gateway()
    assert calls == [["/usr/bin/hermes", "gateway", "status"]]

    def running(argv, **kwargs):
        calls.append(argv)

        class Result:
            stdout = "Active: active (running)"
            stderr = ""

        return Result()

    monkeypatch.setattr("cockpitlib.setup.subprocess.run", running)
    _reload_gateway()
    assert calls[-1] == ["/usr/bin/hermes", "gateway", "restart"]


def test_cron_registration_is_idempotent(env, monkeypatch):
    from cockpitlib.errors import CockpitError
    from cockpitlib.setup import CRON_JOBS, _register_crons, registered_jobs

    pack = load(os.environ["COCKPIT_PACK"])

    def names():
        return {job.get("name") for job in registered_jobs(pack) if isinstance(job, dict) and job.get("name")}

    assert names() == set()
    folder = env["home"] / "cron"
    folder.mkdir()
    (folder / "jobs.json").write_text("{", encoding="utf-8")
    assert names() == set()
    (folder / "jobs.json").write_text('{"jobs": {}}', encoding="utf-8")
    assert names() == set()
    (folder / "jobs.json").write_text(
        json.dumps({"jobs": [{"name": "pr-watch"}, "nope", {"id": "x"}, {"name": "morning-digest"}]}),
        encoding="utf-8",
    )
    assert names() == {"pr-watch"}
    calls = []

    def run(argv, **kwargs):
        calls.append(argv)

        class Result:
            returncode = 0
            stdout = ""
            stderr = ""

        return Result()

    monkeypatch.setattr("cockpitlib.setup.shutil.which", lambda _name: "/usr/bin/hermes")
    monkeypatch.setattr("cockpitlib.setup.subprocess.run", run)
    _register_crons()
    created = [argv[argv.index("--name") + 1] for argv in calls]
    assert "pr-watch" not in created
    assert created == [name for name, _schedule, _script in CRON_JOBS if name != "pr-watch"]
    assert calls[0][1] == "cron"
    assert "--no-agent" in calls[0]
    monkeypatch.setattr("cockpitlib.setup.shutil.which", lambda _name: None)
    with pytest.raises(CockpitError, match="hermes not found"):
        _register_crons()
    assert len(calls) == len(created)

    def fail(argv, **kwargs):
        class Result:
            returncode = 1
            stdout = ""
            stderr = "bad schedule"

        return Result()

    (folder / "jobs.json").write_text('{"jobs": []}', encoding="utf-8")
    monkeypatch.setattr("cockpitlib.setup.shutil.which", lambda _name: "/usr/bin/hermes")
    monkeypatch.setattr("cockpitlib.setup.subprocess.run", fail)
    with pytest.raises(CockpitError, match="bad schedule"):
        _register_crons()
    from cockpitlib.doctor import run as doctor_run

    found = doctor_run(load(os.environ["COCKPIT_PACK"]))
    assert any(item.endswith("cron not registered") for item in found)
    names = [name for name, _schedule, _script in CRON_JOBS]
    (folder / "jobs.json").write_text(json.dumps({"jobs": [{"name": name} for name in names]}), encoding="utf-8")
    again = doctor_run(load(os.environ["COCKPIT_PACK"]))
    assert [item for item in again if item.endswith("cron not registered")] == ["morning-digest cron not registered"]
    from cockpitlib.lanes import profile_dir

    seat = os.path.join(profile_dir("analyst"), "cron")
    os.makedirs(seat)
    open(os.path.join(seat, "jobs.json"), "w", encoding="utf-8").write(
        json.dumps({"jobs": [{"name": "morning-digest"}]})
    )
    assert not any(item.endswith("cron not registered") for item in doctor_run(load(os.environ["COCKPIT_PACK"])))


def test_screen_panes(env):
    pack = load(os.environ["COCKPIT_PACK"])
    from cockpitlib.health import save
    from cockpitlib.intents import load as load_intent
    from cockpitlib.intents import save as save_intent
    from cockpitlib.outbox import create, endorse
    from cockpitlib.paths import watch_dir
    from cockpitlib.plan import init
    from dashboard.cockpit.payload import _chat_sessions, _platform, _qa_files, _watcher_rows

    assert _platform()["hidden"] is True
    assert _watcher_rows(pack) == []
    assert _qa_files() == []
    assert _chat_sessions() == []
    intent = create(pack, "TASK-100", "push-branch", "card", "ship it", {"repo": "api", "branch": "main"})
    endorse(intent["id"], "low", "", "gatekeeper", "fixture-a", "fixture-large")
    held = create(pack, "TASK-100", "infra-note", "card", "wait", {})
    row = load_intent(held["id"])
    row["status"] = "held"
    row["payload"]["ask"] = "which?"
    row["payload"]["options"] = ["a", "b"]
    save_intent(row)
    posted = create(pack, "TASK-100", "pr-comment", "card", "note", {"repo": "api", "number": 1, "body": "x"})
    posted_row = load_intent(posted["id"])
    posted_row["status"] = "posted"
    posted_row["payload"]["after"] = ""
    save_intent(posted_row)
    create(pack, "TASK-100", "ticket-done", "card", "done", {})
    later = create(pack, "TASK-100", "pr-comment", "card", "later", {"repo": "api", "number": 1, "body": "later"})
    later_row = load_intent(later["id"])
    later_row["payload"]["after"] = ""
    save_intent(later_row)
    plain = create(pack, "TASK-100", "infra-note", "card", "hold", {})
    plain_row = load_intent(plain["id"])
    plain_row["status"] = "held"
    save_intent(plain_row)
    init("TASK-100", "# Plan\n\n## Brief\nship", "go")
    save(watch_dir(), "ci-watch", {"ok": False, "output": "timeout", "summary": "failed"})
    save(watch_dir(), "pr-watch", {"ok": True, "output": "", "summary": "ok"})
    hidden = env["workspace"] / "hermes" / "qa" / ".hidden"
    hidden.parent.mkdir(parents=True, exist_ok=True)
    hidden.write_text("x\n", encoding="utf-8")
    import sqlite3

    from cockpitlib.kanban import db_path

    board = db_path(pack["board"])
    os.makedirs(os.path.dirname(board), exist_ok=True)
    connection = sqlite3.connect(board)
    connection.execute("create table tasks (id text, title text, assignee text, status text)")
    connection.execute("insert into tasks values ('1', 'TASK-100: intake', 'intake', 'ready')")
    connection.execute("insert into tasks values ('2', null, '', 'done')")
    connection.execute("insert into tasks values ('3', 'old', 'worker-1', 'archived')")
    connection.commit()
    connection.close()
    (env["workspace"] / "map.yaml").write_text("repos: api\n", encoding="utf-8")
    (env["workspace"] / "hermes" / "qa" / "TASK-100" / "chat.json").write_text("{}\n", encoding="utf-8")
    from fastapi import FastAPI

    from dashboard.cockpit.router import router

    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    body = client.get("/screen").json()
    kinds = {item["kind"] for item in body["inbox"]}
    assert {"publish", "decide", "publish review", "confirm done", "fix watcher"} <= kinds
    assert body["outbox"]
    assert any(item["lane"] == "intake" for item in body["live"])
    assert body["tickets"][0]["plan"]
    assert any(name.endswith("plan.md") for name in body["qa"])
    assert body["platform"]["hidden"] is False
    assert body["settings"]["seats"]["intake"] == 1
    assert body["chat"]["sessions"] == ["TASK-100"]
    assert "resolve hold" in kinds
    assert any(card["lane"] == "intake" for card in body["board_cards"])
    from cockpitlib.plan import init as init_plan

    init_plan("TASK-200", "body", "go")
    kicked = client.post("/kickoff", json={"ticket": "TASK-200", "mode": "review"}).json()
    assert kicked["ok"] is True
    assert any(card["title"] == "TASK-200: review" for card in client.get("/screen").json()["board_cards"])
    from cockpitlib.kanban import db_path, place_card

    shaped = db_path("shaped")
    os.makedirs(os.path.dirname(shaped), exist_ok=True)
    shaped_db = sqlite3.connect(shaped)
    shaped_db.execute(
        "create table tasks (id text primary key, title text not null, status text not null, assignee text, created_at integer not null, created_by text, workspace_kind text not null default 'scratch')"
    )
    shaped_db.commit()
    shaped_db.close()
    assert place_card("shaped", "TASK-9: intake", "intake")
    assert place_card("fresh", "TASK-8: intake", "intake")
    assert body["need_you"] == len(body["inbox"])
    assert client.post("/setup").status_code == 200
    from dashboard.cockpit.payload import _cards, _qa_files

    bulk = env["workspace"] / "hermes" / "qa" / "bulk"
    bulk.mkdir()
    for index in range(200):
        (bulk / f"f{index}.txt").write_text("a", encoding="utf-8")
    assert len(_qa_files()) == 200
    open(board, "w", encoding="utf-8").write("nope")
    assert _cards(pack["board"]) == []


def test_loader_serves_screen_without_preset_path(env):
    import importlib.util

    from fastapi import FastAPI

    plugin = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    saved = list(sys.path)
    # the dashboard modules the other tests hold are set aside and put back: a test that later patched one by name
    # would otherwise patch a second copy, and the routes it calls would not see the patch
    held = {
        name: module for name, module in sys.modules.items() if name == "dashboard" or name.startswith("dashboard.")
    }
    sys.path[:] = [entry for entry in sys.path if os.path.realpath(entry) != os.path.realpath(plugin)]
    for name in held:
        del sys.modules[name]
    try:
        path = os.path.join(plugin, "dashboard", "plugin_api.py")
        spec = importlib.util.spec_from_file_location("hermes_dashboard_plugin_cockpit_test", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        app = FastAPI()
        app.include_router(module.router, prefix="/api/plugins/cockpit")
        assert TestClient(app).get("/api/plugins/cockpit/screen").status_code == 200
    finally:
        sys.path[:] = saved
        for name in [name for name in sys.modules if name == "dashboard" or name.startswith("dashboard.")]:
            del sys.modules[name]
        sys.modules.update(held)


def test_a_helper_runs_inside_hermes_and_answers_json(env, monkeypatch):
    import sqlite3

    from cockpitlib import hermes_runtime
    from cockpitlib.errors import CockpitError

    monkeypatch.setattr(hermes_runtime, "_published", {})
    out = hermes_runtime.run_helper(
        "board",
        {
            "board": "acme",
            "ops": [
                {"op": "create", "title": "TASK-100: intake", "assignee": "intake", "skills": ["outbox"]},
                {"op": "create", "title": "TASK-100: work", "assignee": "worker-1", "initial_status": "blocked"},
            ],
        },
    )
    first, second = out["results"]
    assert first.startswith("t_") and second.startswith("t_")
    done = hermes_runtime.run_helper(
        "board",
        {
            "board": "acme",
            "ops": [
                {"op": "link", "parent": first, "child": second},
                {"op": "unblock", "id": second},
                {"op": "comment", "id": first, "author": "cockpit", "body": "note"},
                {"op": "block", "id": first, "reason": "waiting for go"},
                {"op": "reclaim", "id": first, "reason": "halt"},
                {"op": "complete", "id": first, "result": "ok"},
            ],
        },
    )
    assert done["results"] == [True, True, 1, True, False, True]
    db = sqlite3.connect(str(env["home"] / "kanban" / "boards" / "acme" / "kanban.db"))
    statuses = dict(db.execute("select id, status from tasks").fetchall())
    assert statuses == {first: "done", second: "todo"}
    db.close()
    with pytest.raises(CockpitError, match="helper failed"):
        hermes_runtime.run_helper("board", {"board": "acme", "ops": [{"op": "nope"}]})
    real_run = hermes_runtime.subprocess.run

    def no_json(argv, **kwargs):
        if kwargs.get("input") is not None:

            class Answer:
                returncode = 0
                stdout = "not json"
                stderr = ""

            return Answer()
        return real_run(argv, **kwargs)

    monkeypatch.setattr(hermes_runtime.subprocess, "run", no_json)
    with pytest.raises(CockpitError, match="answered no JSON"):
        hermes_runtime.run_helper("board", {"board": "acme", "ops": []})
    monkeypatch.setattr(hermes_runtime.subprocess, "run", real_run)
    monkeypatch.setattr(hermes_runtime, "_published", {})
    monkeypatch.setenv("COCKPIT_STUB_NO_RUNTIME", "1")
    with pytest.raises(CockpitError, match="did not publish a runtime command"):
        hermes_runtime.run_helper("board", {"board": "acme", "ops": []})
    monkeypatch.delenv("COCKPIT_STUB_NO_RUNTIME")
    monkeypatch.setenv("PATH", "/nonexistent")
    with pytest.raises(CockpitError, match="hermes not found"):
        hermes_runtime.runtime_argv("x.py")


def test_older_board_shapes_and_every_board_write(env):
    import sqlite3

    from cockpitlib.housekeeping import _credential_cards, _save_rates, settle_reviews, unstrand
    from cockpitlib.kanban import BoardWrites, block_reason, db_path, place_card

    pack = load(os.environ["COCKPIT_PACK"])
    bare = sqlite3.connect(":memory:")
    bare.execute("create table tasks (id text, status text, result text)")
    bare.execute("insert into tasks values ('a', 'blocked', 'CREDENTIALS NEEDED · lab')")
    assert _credential_cards(bare, {"id", "status", "result"}) == ["a"]
    bare.execute("create table task_comments (id integer primary key, task_id text, body text)")
    bare.execute("insert into tasks values ('b', 'blocked', '')")
    bare.execute("insert into task_comments (task_id, body) values ('b', 'CREDENTIALS NEEDED · lab')")
    assert _credential_cards(bare, {"id", "status", "result"}) == ["a", "b"]
    bare.execute("create table task_events (id integer primary key, task_id text, kind text, payload text)")
    bare.execute("insert into task_events (task_id, kind, payload) values ('a', 'blocked', 'not json')")
    assert block_reason(bare, "a") == "CREDENTIALS NEEDED · lab"
    bare.close()

    path = db_path(pack["board"])
    os.makedirs(os.path.dirname(path), exist_ok=True)
    thin = sqlite3.connect(path)
    thin.execute("create table tasks (id text, status text)")
    thin.commit()
    thin.close()
    assert settle_reviews(pack) == "0"
    os.remove(path)

    ready = place_card(pack["board"], "TASK-100: work", "worker-1")
    _save_rates({ready: {"ticket": "TASK-100", "at": 0}})
    assert unstrand(pack, now=10**6) == "1"

    parked = place_card(pack["board"], "TASK-100: wait", "intake", "blocked")
    writes = BoardWrites(pack["board"])
    writes.comment(parked, "cockpit", "why it waits")
    writes.edit(parked, body="the new body")
    writes.promote(parked, reason="go")
    writes.archive(ready)
    assert writes.flush() == [1, True, True, True]
    assert writes.flush() == []
    db = sqlite3.connect(path)
    rows = dict((row[0], row[1:]) for row in db.execute("select id, status, body from tasks"))
    db.close()
    assert rows[parked] == ("ready", "the new body") and rows[ready][0] == "archived"


def test_a_card_moves_only_the_ways_hermes_moves_it(env):
    from cockpitlib.acts import _open, _status
    from cockpitlib.errors import CockpitError
    from cockpitlib.kanban import place_card

    card = place_card("acme", "TASK-100: work", "worker-1")
    board = _open("acme")
    with pytest.raises(CockpitError, match="no board move to review"):
        _status(board, card, "review")
    board.close()


def test_doctor_names_a_hermes_this_plugin_was_not_checked_against(env, monkeypatch):
    from cockpitlib.doctor import hermes_version_problem

    assert hermes_version_problem() == ""
    monkeypatch.setenv("COCKPIT_STUB_VERSION", "0.23.0")
    assert hermes_version_problem() == ""
    monkeypatch.setenv("COCKPIT_STUB_VERSION", "0.24.0")
    monkeypatch.setenv(
        "COCKPIT_STUB_HOOKS", "no-block"
    )  # a newer Hermes whose hooks no longer answer the recorded shapes
    assert hermes_version_problem() == "hermes 0.24.0 is not a version this plugin was checked against (0.22, 0.23)"
    monkeypatch.setenv("COCKPIT_STUB_VERSION", "nope")
    assert hermes_version_problem() == "hermes version unreadable"
    from cockpitlib import doctor

    monkeypatch.setattr(doctor, "VERSION_TIMEOUT", 0.2)
    monkeypatch.setenv("COCKPIT_STUB_VERSION_SLEEP", "2")
    assert hermes_version_problem() == "hermes --version did not answer within 0.2 s"
    monkeypatch.setenv("PATH", "/nonexistent")
    assert hermes_version_problem() == "hermes not found"


def test_a_damaged_card_index_falls_back_to_titles(env):
    from cockpitlib.kanban import _index, _index_path, board_cards, open_twin, place_card, remember_card

    card = place_card("acme", "TASK-100: intake", "intake")
    os.makedirs(os.path.dirname(_index_path()), exist_ok=True)
    open(_index_path(), "w", encoding="utf-8").write("not json")
    assert _index() == {}
    open(_index_path(), "w", encoding="utf-8").write(json.dumps({"acme": {card: "loose", "other": {"kind": "intake"}}}))
    assert open_twin("acme", "intake", "TASK-100") == ""
    assert open_twin("acme", "intake", "TASK-100", title="TASK-100: intake") == card
    assert {item["id"]: item["flow"] for item in board_cards("acme")}[card] == "intake"
    open(_index_path(), "w", encoding="utf-8").write(json.dumps({"acme": "loose"}))
    remember_card("acme", card, "intake", "TASK-100")
    assert open_twin("acme", "intake", "TASK-100") == card


def test_records_live_where_the_pack_says(env, monkeypatch, tmp_path):
    import shutil

    from cockpitlib.errors import PackError
    from cockpitlib.paths import DEFAULT_RECORDS, records, records_name

    assert records_name() == "hermes" and records().endswith(os.path.join("ws", "hermes"))
    copied = tmp_path / "packs" / "acme"
    shutil.copytree(os.path.join(os.path.dirname(os.path.dirname(__file__)), "packs", "acme"), copied)
    pack_file = copied / "pack.yaml"
    text = pack_file.read_text(encoding="utf-8")
    monkeypatch.setenv("COCKPIT_PACK", str(pack_file))
    for bad in ("/abs/path", "../outside", "''"):
        pack_file.write_text(text.replace("records_dir: hermes", f"records_dir: {bad}"), encoding="utf-8")
        with pytest.raises(PackError, match="records_dir"):
            load(str(pack_file))
        assert records_name() == DEFAULT_RECORDS
    pack_file.write_text(text.replace("records_dir: hermes", "records_dir: work/records"), encoding="utf-8")
    assert load(str(pack_file))["records_dir"] == os.path.join("work", "records")
    assert records_name() == os.path.join("work", "records")
    pack_file.write_text(text.replace("records_dir: hermes\n", ""), encoding="utf-8")
    assert "records_dir" not in load(str(pack_file)) and records_name() == DEFAULT_RECORDS
    monkeypatch.setenv("COCKPIT_PACK", str(tmp_path / "missing.yaml"))
    assert records_name() == DEFAULT_RECORDS
    monkeypatch.delenv("COCKPIT_PACK")
    monkeypatch.delenv("COCKPIT_WORKSPACE")
    monkeypatch.setattr("cockpitlib.paths.load_binding", lambda: {})
    assert records_name() == DEFAULT_RECORDS


def test_only_paths_under_the_records_folder_are_a_concern(env):
    from cockpitlib.state_commit import _concern

    assert _concern("elsewhere/qa/TASK-1/plan.md") == ""
    assert _concern("hermes/qa") == ""
    assert _concern("hermes/qa/TASK-1/plan.md") == "ticket:TASK-1"
    assert _concern("hermes/outbox/_published.log") == "receipts"


def test_a_seat_file_cockpit_cannot_read_is_still_given_the_plugin(env, tmp_path):
    import shutil

    from cockpitlib.lanes import profile_dir
    from cockpitlib.setup import _seat_plugin, _settings_of

    folder = profile_dir("intake")
    os.makedirs(folder)
    path = os.path.join(folder, "config.yaml")
    open(path, "w", encoding="utf-8").write("model: [unclosed\n")
    _seat_plugin("intake")
    assert "    - cockpit" in open(path, encoding="utf-8").read()
    assert _settings_of("a: [unclosed") == "a: [unclosed"
    assert _settings_of("- one\n- two\n") == ["one", "two"]
    copied = tmp_path / "packs" / "acme"
    shutil.copytree(os.path.join(os.path.dirname(os.path.dirname(__file__)), "packs", "acme"), copied)
    raw = yaml.safe_load((copied / "pack.yaml").read_text(encoding="utf-8"))
    raw.pop("seat_config")
    (copied / "pack.yaml").write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")
    assert "seat_config" not in load(str(copied / "pack.yaml"))


def test_a_pack_soul_must_be_a_file_and_root_takes_only_a_soul(env, tmp_path):
    import shutil

    from cockpitlib.errors import PackError

    copied = tmp_path / "packs" / "acme"
    shutil.copytree(os.path.join(os.path.dirname(os.path.dirname(__file__)), "packs", "acme"), copied)
    text = (copied / "pack.yaml").read_text(encoding="utf-8")
    for old, new, message in (
        ("    soul: souls/reviewer.md\n", "    soul: 3\n", "seat_config reviewer.soul must be a path"),
        ("    soul: souls/reviewer.md\n", "    soul: souls/missing.md\n", "seat_config reviewer.soul: missing"),
        (
            "  root:\n    soul: souls/root.md\n",
            "  root:\n    hermes: {}\n",
            "seat_config root: hermes is not a seat field",
        ),
    ):
        (copied / "pack.yaml").write_text(text.replace(old, new), encoding="utf-8")
        with pytest.raises(PackError, match=message):
            load(str(copied / "pack.yaml"))
    (copied / "pack.yaml").write_text(
        text.replace("    soul: souls/reviewer.md\n", f"    soul: {copied / 'souls' / 'reviewer.md'}\n"),
        encoding="utf-8",
    )
    assert load(str(copied / "pack.yaml"))["seat_config"]["reviewer"]["soul"] == str(
        (copied / "souls" / "reviewer.md").resolve()
    )


def test_an_extra_plugin_and_a_seat_skill_must_name_a_real_folder(env, tmp_path):
    import re
    import shutil

    from cockpitlib.errors import PackError

    copied = tmp_path / "packs" / "acme"
    shutil.copytree(os.path.join(os.path.dirname(os.path.dirname(__file__)), "packs", "acme"), copied)
    (copied / "plugins" / "bare").mkdir()
    (copied / "seat-skills" / "bare").mkdir()
    text = (copied / "pack.yaml").read_text(encoding="utf-8")
    plugin = "  - name: ledger-view\n    path: plugins/ledger-view\n    where: root\n"
    skill = "      - name: house-style\n        path: seat-skills/house-style\n"
    for old, new, message in (
        ("extra_plugins:\n" + plugin, "extra_plugins: {}\n", "extra_plugins must be a list"),
        (plugin, "  - name: ledger-view\n", "each entry is {name, path, where}"),
        (plugin, plugin.replace("ledger-view\n    path", "cockpit\n    path"), "cockpit is not a new plugin name"),
        (plugin, plugin + plugin, "ledger-view is not a new plugin name"),
        (plugin, plugin.replace("name: ledger-view", "name: Ledger"), "Ledger is not a new plugin name"),
        (plugin, plugin.replace("path: plugins/ledger-view", "path: 3"), "extra_plugins ledger-view must be a path"),
        (plugin, plugin.replace("plugins/ledger-view", "plugins/missing"), "extra_plugins ledger-view: missing"),
        (plugin, plugin.replace("plugins/ledger-view", "plugins/bare"), "has no plugin.yaml"),
        (
            plugin,
            plugin.replace("where: root", "where: [root, nowhere]"),
            "where is root, seats, or a list of seat kinds",
        ),
        (plugin, plugin.replace("where: root", "where: []"), "where is root, seats, or a list of seat kinds"),
        (skill, "      - house-style\n", "each entry is {name, path}"),
        (skill, skill + skill, "house-style is not a new skill name"),
        (skill, skill.replace("seat-skills/house-style", "seat-skills/bare"), "has no SKILL.md"),
        ("    skills:\n" + skill, "    skills: house-style\n", "seat_config _common.skills must be a list"),
    ):
        assert old in text
        (copied / "pack.yaml").write_text(text.replace(old, new), encoding="utf-8")
        with pytest.raises(PackError, match=re.escape(message)):
            load(str(copied / "pack.yaml"))
    (copied / "pack.yaml").write_text(text.replace("where: root", "where: seats"), encoding="utf-8")
    from cockpitlib.pack import extra_plugins_for

    seated = load(str(copied / "pack.yaml"))
    assert [plugin["name"] for plugin in extra_plugins_for(seated, "gatekeeper")] == ["ledger-view"]
    assert extra_plugins_for(seated, "root") == []


def test_a_skill_list_holds_names_and_a_card_skill_column_may_be_junk(env, tmp_path, monkeypatch):
    import shutil

    from cockpitlib.errors import PackError
    from cockpitlib.kanban import skills_of
    from cockpitlib.skill_log import current_ticket

    assert skills_of("not json") == [] and skills_of('{"a": 1}') == [] and skills_of('["a", 2]') == ["a", "2"]
    assert current_ticket({"COCKPIT_TICKET": "TASK-7"}) == "TASK-7"
    assert current_ticket({}) == ""
    copied = tmp_path / "packs" / "acme"
    shutil.copytree(os.path.join(os.path.dirname(os.path.dirname(__file__)), "packs", "acme"), copied)
    text = (copied / "skills.yaml").read_text(encoding="utf-8")
    for bad in ("  worker: [[cockpit:outbox]]\n", "  worker: [3]\n"):
        (copied / "skills.yaml").write_text(text.replace("  worker: [cockpit:outbox]\n", bad), encoding="utf-8")
        with pytest.raises(PackError, match="skills.yaml kickoff: .* is not a skill name"):
            load(str(copied / "pack.yaml"))


def test_card_skills_and_titles_must_be_shaped_and_start_with_the_ticket(env, tmp_path):
    import re
    import shutil

    from cockpitlib.errors import PackError

    copied = tmp_path / "packs" / "acme"
    shutil.copytree(os.path.join(os.path.dirname(os.path.dirname(__file__)), "packs", "acme"), copied)
    skills = (copied / "skills.yaml").read_text(encoding="utf-8")
    cards = (
        "cards:\n  body: cards/body.md\n  decompose: [work, test, review]\n  skills:\n    rework: [local-review]\n    ci: [analyze-ticket]\n"
        '  titles:\n    analyst: "{ticket}: analysis"\n'
    )
    assert cards in skills
    for new, message in (
        ("cards: []\n", "skills.yaml cards takes skills, titles, body and decompose"),
        ("cards:\n  owner: x\n", "skills.yaml cards takes skills, titles, body and decompose"),
        ("cards:\n  skills: []\n", "skills.yaml cards.skills must be a mapping"),
        ("cards:\n  skills:\n    planning: [test]\n", "skills.yaml cards.skills: planning is not a card kind"),
        ("cards:\n  skills:\n    rework: test\n", "skills.yaml cards.skills.rework must be a list"),
        ("cards:\n  skills:\n    rework: [3]\n", "skills.yaml cards.skills.rework must be a list"),
        ("cards:\n  skills:\n    rework: [missing-skill]\n", "skill missing-skill not found"),
        ("cards:\n  titles:\n    rework: [x]\n", "skills.yaml cards.titles.rework must be a str"),
        ('cards:\n  titles:\n    rework: "{ticket}: {mood}"\n', "skills.yaml cards.titles.rework: 'mood'"),
        (
            'cards:\n  titles:\n    rework: "rework {ticket}"\n',
            "skills.yaml cards.titles.rework must start with {ticket}",
        ),
        (
            'cards:\n  titles:\n    base: "{change}: analysis"\n',
            "skills.yaml cards.titles.base must start with {ticket}",
        ),
    ):
        (copied / "skills.yaml").write_text(skills.replace(cards, new), encoding="utf-8")
        with pytest.raises(PackError, match=re.escape(message)):
            load(str(copied / "pack.yaml"))
    (copied / "skills.yaml").write_text(skills, encoding="utf-8")
    repos = (copied / "repos.yaml").read_text(encoding="utf-8")
    for new, message in (
        ("    skills: pr-review\n", "repos.yaml api: skills must be a list of names"),
        ("    skills: [missing-skill]\n", "skill missing-skill not found"),
    ):
        (copied / "repos.yaml").write_text(repos.replace("    skills: [pr-review]\n", new), encoding="utf-8")
        with pytest.raises(PackError, match=re.escape(message)):
            load(str(copied / "pack.yaml"))
    (copied / "repos.yaml").write_text(repos.replace("    skills: [pr-review]\n", ""), encoding="utf-8")
    (copied / "skills.yaml").write_text(skills.replace(cards, ""), encoding="utf-8")
    from cockpitlib.kanban import card_skills, card_title

    bare = load(str(copied / "pack.yaml"))
    assert card_skills(bare, "rework", ["api", "nope"], base=["test", "test"]) == ["test"]
    assert card_title("analyst", "TASK-1", pack=bare) == "TASK-1: analyst"


def test_a_notify_command_that_cannot_run_or_hangs_is_a_failed_send(env, tmp_path, monkeypatch):
    import re
    import shutil

    from cockpitlib import notify as bus
    from cockpitlib.errors import PackError

    missing = {"notify": {"ping": [str(tmp_path / "nope")]}}
    sent, detail = bus.run(missing, "ping", "x")
    assert sent is False and detail.startswith("notify ping failed:")
    monkeypatch.setattr(bus, "TIMEOUT", 0.2)
    assert bus.run({"notify": {"ping": ["sleep", "5"]}}, "ping", "x")[0] is False
    assert bus.run({"notify": {"ping": ["sh", "-c", "exit 4"]}}, "ping", "x") == (False, "notify ping failed: exit 4")
    assert bus.command({"notify": {"ping": "true"}}, "ping") == []
    assert bus.run({}, "ping", "x") == (False, "")
    copied = tmp_path / "packs" / "acme"
    shutil.copytree(os.path.join(os.path.dirname(os.path.dirname(__file__)), "packs", "acme"), copied)
    text = (copied / "pack.yaml").read_text(encoding="utf-8")
    line = '  ci_green: ["bin/notify", "{event}", "{key}"]\n'
    for new, message in (
        ('  CI Green: ["true"]\n', "notify CI Green: an event name is lowercase words"),
        ('  ci_green: "true"\n', "notify.ci_green must be a command: a list of words"),
        ('  ci_green: ["true", ""]\n', "notify.ci_green must be a command: a list of words"),
    ):
        (copied / "pack.yaml").write_text(text.replace(line, new), encoding="utf-8")
        with pytest.raises(PackError, match=re.escape(message)):
            load(str(copied / "pack.yaml"))


def test_a_board_workdir_starts_at_the_workspace_or_the_root(env, tmp_path):
    import re
    import shutil

    from cockpitlib.errors import PackError

    copied = tmp_path / "packs" / "acme"
    shutil.copytree(os.path.join(os.path.dirname(os.path.dirname(__file__)), "packs", "acme"), copied)
    text = (copied / "pack.yaml").read_text(encoding="utf-8")
    for new, message in (
        ('board_workdir: "/abs"\n', "board_workdir must start with {workspace} or {root}"),
        ("board_workdir: 3\n", "board_workdir must start with {workspace} or {root}"),
        ('board_workdir: "{workspace}/{repo}"\n', "board_workdir: 'repo'"),
    ):
        (copied / "pack.yaml").write_text(text.replace('board_workdir: "{workspace}"\n', new), encoding="utf-8")
        with pytest.raises(PackError, match=re.escape(message)):
            load(str(copied / "pack.yaml"))
    (copied / "pack.yaml").write_text(text.replace('board_workdir: "{workspace}"\n', ""), encoding="utf-8")
    from cockpitlib.pack import board_workdir

    assert board_workdir(load(str(copied / "pack.yaml"))) == ""


def test_guard_edges_parse_what_a_shell_would(env, monkeypatch):
    from cockpitlib import egress

    assert egress._wide_search("ls -la ; ; find / -name x")
    assert egress._http_write("curl -X POST https://x.test", []) is False
    assert egress._http_write("curl https://x.test && ; curl -d a https://x.test", ["x.test"])
    assert egress._commit_skips_hooks("git commit -m 'unclosed -n") is True
    assert egress._commit_skips_hooks("git commit --author 'A <a@b>' --amend -m x") is False
    assert egress._commit_skips_hooks("git commit --fixup -n") is False
    assert egress.protected(os.path.realpath(os.path.join(str(env["home"]), "profiles"))) is False
    assert egress.protected(os.path.realpath(str(env["home"]))) is False
    assert egress._leaves(3) == [] and egress._leaves(("a", {"b": ["c", 1]})) == ["a", "c"]
    assert egress._refused_host(["https://secret.acme.test"], {}) == ""
    assert egress.wide_root("/home") and not egress.wide_root("/tmp")
    assert egress.protected(os.path.realpath(os.path.join(str(env["home"]), "profiles", "worker-1"))) is False
    monkeypatch.setattr(egress, "pack_rules", lambda: ([], [], [], ["deploy/secrets"]))
    assert egress.check_tool("write_file", {"path": "/srv/deploy/secrets/a.yaml", "content": "x"}) == "blocked"


def test_egress_seat_keys_are_shaped(env, tmp_path):
    import re
    import shutil

    from cockpitlib.errors import PackError

    copied = tmp_path / "packs" / "acme"
    shutil.copytree(os.path.join(os.path.dirname(os.path.dirname(__file__)), "packs", "acme"), copied)
    text = (copied / "egress.yaml").read_text(encoding="utf-8")
    deny_line = next(line for line in text.splitlines() if "vaultctl" in line and "tester" in line)
    root_line = next(line for line in text.splitlines() if "acme-evidence" in line)
    for new, message in (
        ("[]\n", "egress.yaml must be a mapping"),
        (text + "mcp_allow: [tracker_create]\n", "egress.yaml mcp_allow must list MCP tool names"),
        (
            text.replace("role_deny:\n  tester:", "role_deny:\n  planner:"),
            "egress.yaml role_deny is keyed by seat kind",
        ),
        (text.replace(deny_line, '  tester: ["("]'), "egress.yaml role_deny.tester:"),
        (text.replace(deny_line, "  tester: x"), "egress.yaml role_deny.tester must be a list of patterns"),
        (text.replace(root_line, '  tester: ["evidence"]'), "egress.yaml write_roots.tester: each is absolute"),
        (text + "git_deny:\n  planner: [commit]\n", "egress.yaml git_deny is keyed by seat kind"),
        (text + "git_deny:\n  tester: commit\n", "egress.yaml git_deny.tester lists git verbs"),
        (text + 'git_deny:\n  tester: ["Commit!"]\n', "egress.yaml git_deny.tester lists git verbs"),
    ):
        (copied / "egress.yaml").write_text(new, encoding="utf-8")
        with pytest.raises(PackError, match=re.escape(message)):
            load(str(copied / "pack.yaml"))


def test_staging_write_parsing_and_testflow_shape(env, tmp_path, monkeypatch):
    import re
    import shutil

    from cockpitlib import egress
    from cockpitlib.errors import PackError
    from cockpitlib.local_refs import find_local_refs

    assert egress.http_writes("; wget --method=patch https://s.test/a") == [("PATCH", "https://s.test/a")]
    assert egress.http_writes("wget --post-file=x https://s.test/a") == [("POST", "https://s.test/a")]
    assert egress.http_writes("http PUT https://s.test/a") == [("PUT", "https://s.test/a")]
    assert egress.http_writes("http https://s.test/a name=x") == [("POST", "https://s.test/a")]
    assert egress.http_writes("fetch('https://s.test/a', {method: 'PATCH'})") == [("PATCH", "https://s.test/a")]
    assert egress.http_writes("curl https://s.test/a") == []
    monkeypatch.setenv("COCKPIT_PACK", str(tmp_path / "missing" / "pack.yaml"))
    assert find_local_refs("built on box.acme.internal") == []
    copied = tmp_path / "packs" / "acme"
    shutil.copytree(os.path.join(os.path.dirname(os.path.dirname(__file__)), "packs", "acme"), copied)
    text = (copied / "pack.yaml").read_text(encoding="utf-8")
    line = re.search(r"^testflow:\n(?:  .*\n)+", text, re.M).group(0)  # the whole block, whatever keys it has
    assert line.startswith('testflow:\n  never_write: ["/billing/"]\n  run_dir: "pass-{n:02d}"\n')
    for new, message in (
        ("testflow: []\n", "testflow takes never_write, run_dir and review_mark"),
        ("testflow:\n  mood: x\n", "testflow takes never_write, run_dir and review_mark"),
        ("testflow:\n  run_dir: runs\n", "testflow.run_dir is a folder name with {n}"),
        ("testflow:\n  never_write: x\n", "testflow.never_write must be a list of patterns"),
        ('testflow:\n  never_write: ["("]\n', "testflow.never_write:"),
    ):
        (copied / "pack.yaml").write_text(text.replace(line, new), encoding="utf-8")
        with pytest.raises(PackError, match=re.escape(message)):
            load(str(copied / "pack.yaml"))


def test_seat_vault_edges(env, monkeypatch, capsys, tmp_path):
    from cockpitlib import lane_vault, lend, scrub, vault
    from cockpitlib.cli import main
    from cockpitlib.errors import CockpitError
    from cockpitlib.lanes import profile_dir
    from tests.test_vault import seal_ephemeral

    pack = load(os.environ["COCKPIT_PACK"])
    # Unsealed and empty: nothing to index.
    assert scrub.current() == {}
    assert scrub.rebuild()["sources"][-1] == {"source": "gpg", "mtime": 0.0, "entries": [], "locked": False}
    assert scrub.spans("anything", {"salt": "s", "sources": []}) == [] and scrub._codes() == []
    assert vault.normalize_otp("") == "" and vault.totp("!!!!") == ""
    monkeypatch.setenv("COCKPIT_PACK", str(tmp_path / "none" / "pack.yaml"))
    assert vault._bound_pack() == {}
    monkeypatch.setenv("COCKPIT_PACK", pack["_path"])
    seal_ephemeral(monkeypatch, str(env["home"]))
    with pytest.raises(CockpitError, match="vault: "):
        lane_vault.place("tester-1", "nope", "a@b.test", "pw-123456")
    with pytest.raises(CockpitError, match="needs its password"):
        lane_vault.place("tester-1", "https://app.acme.test", "a@b.test", "")
    assert lane_vault.identifier_type("+1 555 0100") == "phone" and lane_vault.identifier_type("qa") == "username"
    assert "https://env.acme.test" in lane_vault.accepted_origins(
        {**pack, "environments": [{"name": "e", "origins": {"x": "https://env.acme.test"}}]}
    )
    assert lane_vault._origin_of("not a url") == "" and lane_vault.origin_accepted(pack, "not a url") is False
    # The command line.
    assert (
        main(["vault", "audit", "--nope"]) == 2
        and main(["vault", "audit", "extra"]) == 2
        and main(["vault", "index", "x"]) == 2
    )
    assert main(["vault", "put", "https://app.acme.test", "x@acme.test", "--lane"]) == 2
    assert main(["vault", "put", "https://app.acme.test"]) == 2
    from cockpitlib import ops

    called = {}
    real_put = ops.vault_put
    monkeypatch.setattr(
        ops, "vault_put", lambda pack_, origin, email, lane="": called.update(lane=lane) or "vault stored"
    )
    assert (
        main(["vault", "put", "https://app.acme.test", "x@acme.test", "--lane", "tester-1"]) == 0
        and called["lane"] == "tester-1"
    )
    monkeypatch.setattr(ops, "vault_put", real_put)
    vault.store_login("https://app.acme.test", "qa@acme.test", "pw-qa-123", lane="tester-1", pack=pack)
    assert main(["vault", "index"]) == 0 and "scrub index: " in capsys.readouterr().out
    # A lend cockpit no longer records, and a placed login that went missing: the audit names and fixes both.
    lane_vault.place("tester-1", "https://app.acme.test", "root@acme.test", "pw-root-1", kind="lent", card="gone-card")
    placed = next(item for item in lane_vault.items("tester-1") if item["identifier"] == "qa@acme.test")
    lane_vault.remove("tester-1", placed["id"])
    found = lane_vault.audit(pack)
    assert "lend with no record: tester-1 https://app.acme.test root@acme.test" in found
    assert "missing: tester-1 https://app.acme.test qa@acme.test" in found
    assert lane_vault.audit(pack, fix=True) == []
    assert [item["identifier"] for item in lane_vault.items("tester-1")] == ["qa@acme.test"]
    # Legacy lent copies in cockpit's own vault go with their lend.
    vault.store_login(
        "https://app.acme.test", "root@acme.test", "pw-root-1", lane="tester-1", lent="old-card", pack=pack
    )
    lane_vault.place("tester-1", "https://app.acme.test", "root@acme.test", "pw-root-1", kind="lent", card="old-card")
    lend._drop_previous_lend("old-card")
    assert not any(item.get("lent") == "old-card" for item, _path in vault.entry_records())
    vault.store_login(
        "https://app.acme.test", "root@acme.test", "pw-root-1", lane="tester-1", lent="old-card", pack=pack
    )
    lane_vault.place("tester-1", "https://app.acme.test", "root@acme.test", "pw-root-1", kind="lent", card="stray-card")
    returned = lend.take_back(status_of=lambda _card: ("ready", 0))
    assert ("stray-card", "tester-1", "no lend record") in returned
    assert not any(item.get("lent") for item, _path in vault.entry_records())
    with pytest.raises(CockpitError, match="no lane holds this card"):
        vault.store_login(
            "https://app.acme.test", "boss@acme.test", "pw-boss-1", privileged=True, pack=pack
        ) and lend.approve("nobody-card", "", pack=pack)
    # The scrub index notices a store that went away, and a lock that hid a change.
    os.remove(os.path.join(profile_dir("tester-1"), "vault", "vault.json.enc"))
    assert scrub._stale(scrub.load()) is True
    index = scrub.load()
    index["sources"] = [{"source": "gpg", "locked": True, "mtime": 1, "mtime_now": 2, "entries": []}]
    open(scrub.index_path(), "w", encoding="utf-8").write(json.dumps(index))
    assert scrub.locked() is True
    # A seat backed up without its key restores as ciphertext only; one whose key cannot unwrap says so.
    vault.store_login("https://app.acme.test", "qa@acme.test", "pw-qa-123", lane="tester-1", pack=pack)
    os.remove(os.path.join(profile_dir("tester-1"), "vault", "vault.key"))
    vault.backup_vault(1)
    assert vault.restore_vault().startswith("vault restore")
    vault.store_login("https://app.acme.test", "qa@acme.test", "pw-qa-124", lane="tester-1", pack=pack)
    vault.backup_vault(1)
    monkeypatch.setattr(vault, "_decrypt", lambda path="": (_ for _ in ()).throw(CockpitError("no private key")))
    assert "private key required" in vault.restore_vault()


def test_an_accounts_manifest_is_shaped(env, tmp_path):
    import re
    import shutil

    from cockpitlib.accounts import manifest
    from cockpitlib.errors import PackError

    copied = tmp_path / "packs" / "acme"
    shutil.copytree(os.path.join(os.path.dirname(os.path.dirname(__file__)), "packs", "acme"), copied)
    good = (copied / "accounts.yaml").read_text(encoding="utf-8")
    for text, message in (
        ("command: x\n", "command must be a list of words"),
        ("accounts: {}\n", "accounts must be a list"),
        ("accounts: [{origin: https://a.test}]\n", "each account has origin and identifier"),
        ("accounts: [{origin: https://a.test, identifier: a@b.test}]\n", "has an owner or readers, not both"),
        (
            "accounts: [{origin: https://a.test, identifier: a@b.test, owner: x}, {origin: https://a.test, identifier: a@b.test, owner: y}]\n",
            "listed twice",
        ),
    ):
        (copied / "accounts.yaml").write_text(text, encoding="utf-8")
        with pytest.raises(PackError, match=re.escape(message)):
            load(str(copied / "pack.yaml"))
    os.remove(copied / "accounts.yaml")
    with pytest.raises(PackError, match="logins.accounts: missing"):
        load(str(copied / "pack.yaml"))
    (copied / "accounts.yaml").write_text(good, encoding="utf-8")
    assert manifest({"logins": {}}) == {"command": [], "accounts": []}


def test_mcp_servers_and_seat_env_are_shaped(env, tmp_path):
    import re
    import shutil

    from cockpitlib.errors import PackError

    copied = tmp_path / "packs" / "acme"
    shutil.copytree(os.path.join(os.path.dirname(os.path.dirname(__file__)), "packs", "acme"), copied)
    text = (copied / "pack.yaml").read_text(encoding="utf-8")
    block = "mcp_servers:\n  docs:\n    command: [fixture-docs-mcp, --stdio]\n    env_keys: [DOCS_TOKEN]\n    include_tools: [search, get_page]\n"
    assert block in text
    for new, message in (
        ("mcp_servers: []\n", "mcp_servers must be a mapping"),
        ("mcp_servers:\n  docs: {command: [x], mood: calm}\n", "a name and {command | url"),
        ("mcp_servers:\n  docs: {}\n", "a command or a url, not both"),
        ("mcp_servers:\n  docs: {command: x}\n", "docs.command must be a list of words"),
        ("mcp_servers:\n  docs: {command: [x], env_keys: DOCS}\n", "docs.env_keys must be a list"),
        ("mcp_servers:\n  docs: {command: [x], env_keys: [docs-token]}\n", "env_keys are environment names"),
        (
            "mcp_servers:\n  docs: {url: https://x.test, headers_env: {Authorization: bad-name}}\n",
            "headers_env maps a header",
        ),
        ("", "seat_config reviewer.mcp names servers from mcp_servers"),
    ):
        (copied / "pack.yaml").write_text(text.replace(block, new), encoding="utf-8")
        with pytest.raises(PackError, match=re.escape(message)):
            load(str(copied / "pack.yaml"))
    for new, message in (
        ("    env:\n      ACME_REGION: [x]\n", "_common.env maps environment names to plain values"),
        ("    env_files: [relative.env]\n", "_common.env_files lists absolute paths"),
    ):
        (copied / "pack.yaml").write_text(text.replace("    env:\n      ACME_REGION: eu-1\n", new), encoding="utf-8")
        with pytest.raises(PackError, match=re.escape(message)):
            load(str(copied / "pack.yaml"))


def test_a_slots_block_is_shaped(env, tmp_path):
    import re
    import shutil

    import yaml

    from cockpitlib.errors import PackError

    copied = tmp_path / "packs" / "acme"
    shutil.copytree(os.path.join(os.path.dirname(os.path.dirname(__file__)), "packs", "acme"), copied)
    raw = yaml.safe_load((copied / "pack.yaml").read_text(encoding="utf-8"))
    good = raw["slots"]
    cases = (
        ({"mood": 1}, "slots takes"),
        ({"provider": "compose"}, "slots.provider is none or command"),
        ({"ports": {"app": "x"}}, "slots.ports maps a name to a base port"),
        ({"max": -1}, "slots.max must be a whole number"),
        ({"state_dir": "/tmp/x"}, "slots.state_dir must name {slot}"),
        ({"commands": []}, "slots.commands maps a verb"),
        ({"commands": {"up": {"argv": ["x"], "mood": 1}}}, "slots.commands.up is {argv, who, passthrough}"),
        ({"commands": {"up": {"argv": "x"}}}, "slots.commands.up.argv must be a command"),
        ({"commands": {"up": {"argv": ["x"], "who": "anyone"}}}, "slots.commands.up.who is human, lane, or both"),
        ({"commands": {"exec": {"argv": ["x", "{args...}"]}}}, "{args...} needs passthrough: true"),
        ({"exec_refuse": ["("]}, "slots.exec_refuse:"),
        ({"toggles": []}, "slots.toggles maps a name"),
        ({"toggles": {"t": {"on": ["x"]}}}, "slots.toggles.t is {on, off, status}"),
        ({"session": {"later": ["x"]}}, "slots.session takes open and close"),
        ({"session": {"open": "x"}}, "slots.session.open must be a command"),
        ({"stores": {}}, "slots.stores is a list"),
        ({"stores": [{"name": "db"}]}, "slots.stores db.probe must be a command"),
        ({"stores": [{"name": "db", "probe": ["x"], "capacity": "y"}]}, "slots.stores db.capacity must be a command"),
        ({"stores": [{"probe": ["x"]}]}, "slots.stores entries are"),
    )
    for change, message in cases:
        raw["slots"] = {**({"provider": "command"} if "provider" not in change else {}), **change}
        (copied / "pack.yaml").write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")
        with pytest.raises(PackError, match=re.escape(message)):
            load(str(copied / "pack.yaml"))
    raw["slots"] = {**good, "provider": "none", "session": {"open": ["x"], "close": ["y"]}}
    (copied / "pack.yaml").write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")
    from cockpitlib.slots import NoneProvider, provider_for

    assert isinstance(provider_for("none", load(str(copied / "pack.yaml"))), NoneProvider)


def test_a_command_provider_without_a_verb_keeps_the_kernel_bookkeeping(env, monkeypatch, capsys):
    from cockpitlib.cli import main
    from cockpitlib.errors import CockpitError
    from cockpitlib.slots import CommandProvider, write_owner

    pack = load(os.environ["COCKPIT_PACK"])
    bare = CommandProvider(
        {
            **pack,
            "slots": {
                "provider": "command",
                "commands": {
                    "broken": {"argv": ["/no/such/program"]},
                    "noisy": {"argv": ["sh", "-c", "echo '{not json'"]},
                },
            },
        }
    )
    assert bare.up(1, "TASK-1") is None and bare.reset(1) is None
    write_owner(1, "free")
    assert bare.down(1) is None
    assert bare.ready(1)["state"] == "ok"
    assert bare.status(count=1)[0]["slot"] == 1
    assert bare.exec(1, ["echo"])["argv"] == ["echo"]
    assert bare.login("TASK-1", "ada")["password"] == "slot-local"
    assert bare.run("broken", 1)["state"] == "failed" and "No such file" in bare.run("broken", 1)["tail"]
    assert bare.run("noisy", 1)["out"] == "{not json"
    assert main(["slot", "down", "1"]) == 0 and main(["slot", "reset", "1"]) == 0
    monkeypatch.setenv("COCKPIT_PACK", os.environ["COCKPIT_PACK"])
    from cockpitlib import cli

    monkeypatch.setattr(cli, "_pack", lambda: {**pack, "slots": None, "slot_provider": "none"})
    with pytest.raises(CockpitError, match="run no commands"):
        cli.cmd_slot(["run", "x", "1"])
    assert main(["slot", "status", "--json"]) == 0 and main(["slot", "status", "--nope"]) == 2
    assert (
        main(["slot", "up", "x", "TASK-1"]) == 2
        and main(["slot", "down", "1", "--", "x"]) == 2
        and main(["slot", "wave"]) == 2
    )


def test_a_repos_worktree_setup_is_shaped(env, tmp_path):
    import re
    import shutil

    import yaml

    from cockpitlib.errors import PackError

    copied = tmp_path / "packs" / "acme"
    shutil.copytree(os.path.join(os.path.dirname(os.path.dirname(__file__)), "packs", "acme"), copied)
    raw = yaml.safe_load((copied / "repos.yaml").read_text(encoding="utf-8"))
    good = dict(raw["repos"][0])
    for change, message in (
        ({"copy": ["/abs"]}, "copy lists paths inside the repo"),
        ({"hooks_path": ""}, "hooks_path is a folder"),
        ({"branch_suffix_when_held": 3}, "branch_suffix_when_held is a suffix"),
        ({"worktree_files": {}}, "worktree_files lists {source, target}"),
        ({"worktree_files": [{"source": "files/api.env", "target": "/abs"}]}, "worktree_files lists {source, target}"),
        ({"worktree_files": [{"source": "files/missing", "target": "x"}]}, "worktree_files: missing"),
        ({"after_add": "x"}, "after_add lists commands"),
        ({"after_add": [["x", ""]]}, "after_add must be a command"),
    ):
        raw["repos"][0] = {**good, **change}
        (copied / "repos.yaml").write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")
        with pytest.raises(PackError, match=re.escape(message)):
            load(str(copied / "pack.yaml"))


def test_worktree_add_takes_a_start_ref_from_the_command_line(env, monkeypatch):
    from cockpitlib import ops
    from cockpitlib.cli import main

    seen = {}
    monkeypatch.setattr(
        ops,
        "worktree_add",
        lambda pack, ticket, repo, branch_from="": seen.update(ticket=ticket, repo=repo, start=branch_from) or ["/x"],
    )
    assert main(["worktree", "add", "TASK-1", "api", "--from", "abc123"]) == 0 and seen == {
        "ticket": "TASK-1",
        "repo": "api",
        "start": "abc123",
    }
    assert main(["worktree", "add", "TASK-1", "--from"]) == 2


def test_a_chat_terminal_ends_a_shell_that_ignores_term(env, tmp_path):
    """end_chat on a personal shell: an interactive bash ignores SIGTERM, so kill() hangs the terminal up first and only then
    closes the master (closing it while the reader waits in read() blocks for good on macOS); one that ignores HUP too is killed."""
    import time

    from cockpitlib.chat import Term

    for script in ("trap '' TERM; while :; do sleep 1; done", "trap '' HUP TERM; while :; do sleep 1; done"):
        term = Term(["sh", "-c", script], str(tmp_path), 80, 24)
        time.sleep(0.2)
        started = time.time()
        term.kill()
        assert time.time() - started < 5 and term.alive is False
        try:
            os.kill(term.pid, 0)
            deadline = time.time() + 2
            while time.time() < deadline and term._still_running():
                time.sleep(0.02)
        except OSError:
            pass
        assert term._still_running() is False


def test_gate_scan_finds_a_running_gate_without_proc(env, monkeypatch, tmp_path):
    """macOS has no /proc: the running-gate check reads `ps` for the command lines and `lsof` for one process's folder.
    The same code is exercised here on every platform."""
    import subprocess
    import time

    from cockpitlib import repo_gates

    inside = tmp_path / "inside"
    inside.mkdir()
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    script = "sleep 20; echo gate-scan-probe"
    held = subprocess.Popen(["bash", "-c", script], cwd=str(inside))
    try:
        deadline = time.time() + 3
        while time.time() < deadline and not any(pid == held.pid for pid, _argv in repo_gates._ps_processes()):
            time.sleep(0.05)
        rows = dict(repo_gates._ps_processes())
        assert rows[held.pid] == ["bash", "-c", script]  # the script stays one argv word
        assert os.path.realpath(repo_gates._cwd_of(held.pid)) == os.path.realpath(str(inside))
        real_isdir = os.path.isdir  # gates.os.path is os.path: a stand-in that asked os.path.isdir would ask itself
        monkeypatch.setattr(repo_gates.os.path, "isdir", lambda path: False if path == "/proc" else real_isdir(path))
        assert os.path.isdir(str(inside)) and not os.path.isdir("/proc")  # any other folder is still answered
        assert repo_gates._outside(script, [str(inside)]) is True
        assert repo_gates._outside(script, [str(elsewhere)]) is False  # the same command elsewhere does not count
        assert repo_gates._outside("", [str(inside)]) is False
    finally:
        held.kill()
        held.wait()
    assert repo_gates._cwd_of(2**22 + 1) == ""  # no such process: lsof answers nothing
    monkeypatch.setattr(repo_gates.subprocess, "run", lambda *a, **k: (_ for _ in ()).throw(OSError("no ps")))
    assert repo_gates._ps_processes() == [] and repo_gates._cwd_of(1) == ""
    monkeypatch.setattr(
        repo_gates.subprocess, "run", lambda *a, **k: (_ for _ in ()).throw(subprocess.TimeoutExpired("ps", 5))
    )
    assert repo_gates._ps_processes() == [] and repo_gates._cwd_of(1) == ""


def test_gate_runner_edges(env, monkeypatch):
    import subprocess

    from cockpitlib import repo_gates

    assert repo_gates._alive(0) is False
    assert repo_gates._is_gate([], "x") is False and repo_gates._is_gate(["make", "check"], "make check") is True
    assert repo_gates._is_gate(["make"], "make") is True and repo_gates._is_gate(["sh", "-c", "other"], "make") is False
    assert repo_gates._outside("", ["/tmp"]) is False
    pack = load(os.environ["COCKPIT_PACK"])
    source = env["root"] / "repos" / "api"
    subprocess.run(["git", "-C", str(source), "checkout", "-qb", f"{pack['branch_prefix']}/TASK-90"], check=True)
    # a ticket branch in the repo's own checkout is not the ticket's checkout: the gate runs in the worktree or the workspace
    assert repo_gates._gate_folder(pack, {"name": "api", "path": "repos/api"}, "TASK-90") == repo_gates.workspace()
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("COCKPIT_PACK", pack["_path"])
        mp.setenv("COCKPIT_TICKET", "TASK-91")
        mp.setattr(repo_gates, "_run", lambda *a, **k: (_ for _ in ()).throw(KeyboardInterrupt()))
        with pytest.raises(KeyboardInterrupt):
            repo_gates.run_gates({"repos": {"repos": [{"name": "api", "gates": ["true"]}]}})
        assert all(
            repo_gates._read(os.path.join(repo_gates.gates_dir("TASK-91"), name)).get("status") == "done"
            for name in os.listdir(repo_gates.gates_dir("TASK-91"))
            if name.endswith(".json")
        )
    monkeypatch.setenv("COCKPIT_PACK", pack["_path"])
    monkeypatch.setenv("COCKPIT_TICKET", "TASK-92")
    started = []
    monkeypatch.setattr(
        repo_gates.subprocess, "Popen", lambda argv, **k: started.append(argv) or type("P", (), {"pid": 999999})()
    )
    run_id = repo_gates.start_background(pack, "api", True)
    assert started[0][-3:] == ["--repo", "api", "--baseline"]
    assert repo_gates.wait(run_id) == (1, [f"gate run {run_id} ended without a result"])
    repo_gates._write(
        repo_gates._record_path("TASK-92", "slow"), {"id": "slow", "status": "running", "pid": os.getpid()}
    )
    assert repo_gates.wait("slow", timeout=0) == (2, ["gate run slow still running"])


def test_a_bad_skills_group_names_the_file_read(env, tmp_path):
    import shutil

    from cockpitlib.errors import PackError

    copied = tmp_path / "packs" / "acme"
    shutil.copytree(os.path.join(os.path.dirname(os.path.dirname(__file__)), "packs", "acme"), copied)
    (copied / "skills.yaml").write_text("kickoff: []\nintent: {}\n", encoding="utf-8")
    with pytest.raises(PackError, match=r"skills.yaml kickoff must be a mapping \(read .*skills.yaml: 'kickoff: \[\]"):
        load(str(copied / "pack.yaml"))


def test_the_standup_window_starts_at_its_wall_clock_hour_across_a_daylight_saving_change(monkeypatch):
    import datetime
    import time

    from cockpitlib.window import window_start

    monkeypatch.setenv("TZ", "Europe/Amsterdam")
    time.tzset()
    try:
        # Sunday after the October change (CEST to CET): the window opens Friday 10:30 summer time, not 11:30
        moment = datetime.datetime(2026, 10, 25, 17, 0).astimezone()
        start = window_start(moment, hour=10, minute=30)
        assert (start.date().isoformat(), start.hour, start.minute) == ("2026-10-23", 10, 30)
        assert start.utcoffset() == datetime.timedelta(hours=2) and moment.utcoffset() == datetime.timedelta(hours=1)
        # and back in spring (CET to CEST)
        start = window_start(datetime.datetime(2026, 3, 30, 9, 0).astimezone(), hour=10)
        assert (start.date().isoformat(), start.hour, start.utcoffset()) == (
            "2026-03-27",
            10,
            datetime.timedelta(hours=1),
        )
    finally:
        monkeypatch.delenv("TZ")
        time.tzset()
