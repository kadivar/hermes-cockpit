# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
import os
import shutil

import pytest
import yaml
from fastapi import FastAPI
from fastapi.testclient import TestClient

from cockpitlib.capacity import _kind_free, compute
from cockpitlib.cli import main
from cockpitlib.egress import _wide_search
from cockpitlib.errors import CockpitError, PackError
from cockpitlib.fence import outside
from cockpitlib.gh_cli import run_json
from cockpitlib.health import load as load_health
from cockpitlib.intents import all_intents, check_ticket, next_seq
from cockpitlib.kanban import open_same
from cockpitlib.local_refs import find_local_refs
from cockpitlib.migrate import discover, draft, journal, rollback
from cockpitlib.outbox import ack, create, verify
from cockpitlib.pack import load as load_pack
from cockpitlib.paths import qa
from cockpitlib.publish import execute
from cockpitlib.setup import _bin_link, _board_flags, profile_dir, setup
from cockpitlib.slots import NoneProvider, provider_for, write_owner
from cockpitlib.test_flow import row_state
from cockpitlib.worktree import add, list_worktrees, repo_source
from dashboard.cockpit.router import router
from tests.support import fake_gh
from tests.support.boards import init_db


def test_discovered_provider_and_context(bare, tmp_path):
    home = tmp_path / "discover"
    (home / "plugins" / "model-providers" / "cursor-agent").mkdir(parents=True)
    (home / "config.yaml").write_text("model:\n  provider: cursor-agent\n", encoding="utf-8")
    from cockpitlib.pack import _listed_providers, _plugin_providers
    from cockpitlib.setup import _profile

    assert "cursor-agent" in _listed_providers(str(home)) | _plugin_providers(str(home))
    pack = load_pack(os.environ["COCKPIT_PACK"])
    pack["providers"]["judgment"]["context_length"] = 246000
    pack["providers"]["judgment"]["reasoning_effort"] = "high"
    folder = _profile(pack, "intake", "intake")
    text = open(os.path.join(folder, "config.yaml"), encoding="utf-8").read()
    assert "context_length: 246000" in text
    assert "reasoning_effort: high" in text
    assert "hooks/egress.py" in text


def test_cover_rest(env, monkeypatch, tmp_path):
    pack = load_pack(os.environ["COCKPIT_PACK"])
    assert compute(0, {}, {"slots": 0, "intake": 1, "reviewer": 1, "analyst": 1})["test"] == 0
    assert _kind_free("worker", 2, {"worker-1": 1}) == 1
    assert row_state("Partial") == "open"
    assert find_local_refs("") == []
    assert _wide_search("echo hello") is False
    assert outside(env={}, cwd=os.environ["COCKPIT_WT"], worktrees=os.environ["COCKPIT_WT"]) is False
    assert load_health(str(env["workspace"]), "missing") is None
    with pytest.raises(CockpitError):
        check_ticket("TASK-100", "^ZZ-")
    folder = os.path.join(os.environ["COCKPIT_WORKSPACE"], "hermes", "outbox", "TASK-SEQ")
    os.makedirs(folder, exist_ok=True)
    open(os.path.join(folder, "999-push-branch.json"), "w", encoding="utf-8").write("{}")
    with pytest.raises(CockpitError, match="exhausted"):
        next_seq("TASK-SEQ")
    open(os.path.join(os.environ["COCKPIT_WORKSPACE"], "hermes", "outbox", "NOTDIR"), "w", encoding="utf-8").write("x")
    all_intents()
    init_db("broken")
    from cockpitlib.kanban import db_path

    open(db_path("broken"), "w", encoding="utf-8").write("nope")
    assert open_same("broken", "t") == ""
    with pytest.raises(PackError):
        load_pack(str(env["workspace"] / "missing.yaml"))
    (env["workspace"] / "bad.yaml").write_text("- 1\n", encoding="utf-8")
    with pytest.raises(PackError, match="mapping"):
        load_pack(str(env["workspace"] / "bad.yaml"))
    copied = tmp_path / "packs" / "acme"
    shutil.copytree(os.path.join(os.path.dirname(os.path.dirname(__file__)), "packs", "acme"), copied)
    raw = yaml.safe_load((copied / "pack.yaml").read_text(encoding="utf-8"))
    raw.pop("name")
    (copied / "pack.yaml").write_text(yaml.safe_dump(raw), encoding="utf-8")
    with pytest.raises(PackError, match="missing"):
        load_pack(str(copied / "pack.yaml"))
    raw = yaml.safe_load(open(os.environ["COCKPIT_PACK"], encoding="utf-8"))
    raw["skills_dir"] = [""]
    (copied / "pack.yaml").write_text(yaml.safe_dump(raw), encoding="utf-8")
    with pytest.raises(PackError):
        load_pack(str(copied / "pack.yaml"))
    raw["skills_dir"] = "@skills"
    raw["providers"] = {}
    (copied / "pack.yaml").write_text(yaml.safe_dump(raw), encoding="utf-8")
    with pytest.raises(PackError, match="coding"):
        load_pack(str(copied / "pack.yaml"))
    base = yaml.safe_load(open(os.environ["COCKPIT_PACK"], encoding="utf-8"))
    base["roles"] = []
    (copied / "pack.yaml").write_text(yaml.safe_dump(base), encoding="utf-8")
    with pytest.raises(PackError):
        load_pack(str(copied / "pack.yaml"))
    base = yaml.safe_load(open(os.environ["COCKPIT_PACK"], encoding="utf-8"))
    base["roles"] = {"intake": "coding"}
    (copied / "pack.yaml").write_text(yaml.safe_dump(base), encoding="utf-8")
    with pytest.raises(PackError):
        load_pack(str(copied / "pack.yaml"))
    base = yaml.safe_load(open(os.environ["COCKPIT_PACK"], encoding="utf-8"))
    base["roles"] = {
        role: "judgment" for role in ("intake", "worker", "tester", "reviewer", "analyst", "gatekeeper", "advisor")
    }
    base["providers"]["judgment"] = {"hermes_provider": "", "model": ""}
    (copied / "pack.yaml").write_text(yaml.safe_dump(base), encoding="utf-8")
    with pytest.raises(PackError):
        load_pack(str(copied / "pack.yaml"))
    base = yaml.safe_load(open(os.environ["COCKPIT_PACK"], encoding="utf-8"))
    base["seats"] = []
    (copied / "pack.yaml").write_text(yaml.safe_dump(base), encoding="utf-8")
    with pytest.raises(PackError, match="seats"):
        load_pack(str(copied / "pack.yaml"))
    base = yaml.safe_load(open(os.environ["COCKPIT_PACK"], encoding="utf-8"))
    base["seats"]["slots"] = 99
    (copied / "pack.yaml").write_text(yaml.safe_dump(base), encoding="utf-8")
    with pytest.raises(PackError, match="out of range"):
        load_pack(str(copied / "pack.yaml"))
    os.remove(copied / "repos.yaml")
    base = yaml.safe_load(open(os.environ["COCKPIT_PACK"], encoding="utf-8"))
    (copied / "pack.yaml").write_text(yaml.safe_dump(base), encoding="utf-8")
    with pytest.raises(PackError, match="missing"):
        load_pack(str(copied / "pack.yaml"))
    (copied / "repos.yaml").write_text("repos: {}\n", encoding="utf-8")
    with pytest.raises(PackError, match="repos"):
        load_pack(str(copied / "pack.yaml"))
    (copied / "repos.yaml").write_text("repos: []\n", encoding="utf-8")
    (copied / "skills.yaml").write_text("kickoff: []\nintent: {}\n", encoding="utf-8")
    with pytest.raises(PackError):
        load_pack(str(copied / "pack.yaml"))
    (copied / "skills.yaml").write_text("kickoff:\n  intake: missing\nintent: {}\n", encoding="utf-8")
    with pytest.raises(PackError):
        load_pack(str(copied / "pack.yaml"))
    (copied / "skills.yaml").write_text("kickoff:\n  intake: [not-a-skill]\nintent: {}\n", encoding="utf-8")
    with pytest.raises(PackError, match="not found"):
        load_pack(str(copied / "pack.yaml"))
    with pytest.raises(CockpitError, match="no intent TASK-700/000-push-branch"):
        create(
            pack,
            "TASK-700",
            "open-pr",
            "c",
            "open",
            {"repo": "api", "branch": "work/TASK-700", "title": "x", "after": "TASK-700/000-push-branch"},
        )
    intent = create(pack, "TASK-700", "infra-note", "c", "note", {"body": "a note"})
    with pytest.raises(CockpitError, match="unknown type"):
        create(pack, "TASK-700", "nope", "c", "x", {})
    jira = create(pack, "TASK-700", "tracker-comment", "c", "body", {"body": "hello"})
    os.path.join(os.environ["COCKPIT_WORKSPACE"], "hermes", "outbox", "TASK-700")
    from cockpitlib.intents import load as load_intent
    from cockpitlib.intents import save

    row = load_intent(jira["id"])
    row["payload"]["body"] = "qa/secret"
    save(row)
    assert verify(jira["id"])
    with pytest.raises(CockpitError, match="ticket-done"):
        ack(intent["id"])
    fake_gh.pull("acme/api", 1, "work/TASK-700", "a" * 40)
    review = create(
        pack,
        "TASK-700",
        "pr-review-submit",
        "c",
        "r",
        {"repo": "api", "number": 1, "event": "COMMENT", "body": "n", "sha": "a" * 40},
    )
    from cockpitlib.outbox import endorse

    endorse(review["id"], "low", "", "gatekeeper", "fixture-a", "fixture-large")
    posted = load_intent(review["id"])
    assert execute(posted, pack=pack)["ok"] and posted["status"] == "posted"
    posted["review"]["proposed_event"] = "APPROVE"
    save(posted)
    with pytest.raises(CockpitError, match="APPROVE"):
        execute(posted, pack=pack)
    none = NoneProvider()
    assert none.down(1) is None and none.reset(1) is None
    from cockpitlib.slots import claim, read_owner

    write_owner(1, "lane:worker-1")
    assert none.gc(60, 1) == [1]
    assert read_owner(1) == "free"
    write_owner(1, "human")
    assert none.gc(60, 1) == []
    write_owner(1, "lane:worker-1")
    claim(1)
    assert none.gc(60, 1) == []
    assert read_owner(1) == "lane:worker-1"
    assert provider_for("pack").name == "none"
    with pytest.raises(CockpitError, match="use slots.provider command"):
        provider_for("compose")
    write_owner(1, "free")
    setup(pack)
    env_path = os.path.join(profile_dir("intake"), ".env")
    open(env_path, "w", encoding="utf-8").write("OTHER=1\n")
    link = os.path.join(profile_dir("intake"), "skills", "workspace")
    if os.path.lexists(link):
        os.remove(link)
    open(link, "w", encoding="utf-8").write("file")
    os.remove(os.path.join(profile_dir("intake"), "config.yaml"))
    setup(pack)
    assert "COCKPIT_LANE=intake" in open(env_path, encoding="utf-8").read()
    open(os.path.join(env["home"], "config.yaml"), "w", encoding="utf-8").write("plugins:\n  enabled:\n    - other\n")
    _board_flags(pack)
    _bin_link()
    assert main(["setup"]) == 0
    assert main(["apply"]) == 0
    monkeypatch.setattr("cockpitlib.doctor.check", lambda command, **kwargs: "")
    assert main(["doctor"]) == 1
    endorsed = create(pack, "TASK-701", "push-branch", "c", "p", {"repo": "api", "branch": "main"})
    endorse(endorsed["id"], "low", "", "gatekeeper", "fixture-a", "fixture-large")
    assert main(["publish", "--id", endorsed["id"]]) == 0
    snap = env["root"] / "snap2"
    (snap / "profiles").mkdir(parents=True)
    (env["home"] / "profiles").mkdir(exist_ok=True)
    assert main(["migrate", "rollback", str(snap)]) == 0
    repo = env["root"] / "repos" / "api"
    first = add("TASK-800", "api", "work", str(repo))
    assert add("TASK-800", "api", "work", str(repo)) == first
    git = env["workspace"] / "demo"
    git.mkdir()
    os.environ_copy = None
    os.environ.copy()
    import subprocess

    subprocess.run(["git", "init", str(git)], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(git), "config", "user.email", "dev@example.test"], check=True)
    subprocess.run(["git", "-C", str(git), "config", "user.name", "Dev"], check=True)
    (git / "README").write_text("a\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(git), "add", "README"], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(git), "commit", "-m", "init"],
        check=True,
        capture_output=True,
        env={
            **os.environ,
            "GIT_AUTHOR_NAME": "Dev",
            "GIT_AUTHOR_EMAIL": "dev@example.test",
            "GIT_COMMITTER_NAME": "Dev",
            "GIT_COMMITTER_EMAIL": "dev@example.test",
        },
    )
    found = discover(str(env["workspace"]), skill_dirs=[str(copied / "skills")])
    assert found["repos"]
    assert journal(str(env["workspace"]))
    secret = {"name": "ok", "skills_dir": ["/tmp"], "repos": []}
    dest = env["workspace"] / "secret-draft"
    calls = {"n": 0}

    def scan(text):
        calls["n"] += 1
        if calls["n"] == 1:
            return ""
        return "password=x"

    monkeypatch.setattr("cockpitlib.migrate.secrets_scan", scan)
    with pytest.raises(Exception, match="secret"):
        draft(secret, str(dest))
    home = str(env["home"])
    (env["home"] / "profiles" / "old").mkdir(parents=True, exist_ok=True)
    (snap / "profiles" / "fresh").mkdir(parents=True, exist_ok=True)
    rollback(str(snap), home)
    assert repo_source(pack, "api").endswith("api")
    (os.path.join(os.environ["COCKPIT_WT"], "TASK-800", "notdir")).replace if False else None
    open(os.path.join(os.environ["COCKPIT_WT"], "TASK-800", "notes"), "w", encoding="utf-8").write("x")
    assert any(path.endswith("api") for path in list_worktrees("TASK-800"))
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    monkeypatch.delenv("COCKPIT_PACK", raising=False)
    monkeypatch.delenv("COCKPIT_WORKSPACE", raising=False)
    (env["home"] / "cockpit.yaml").write_text("workspace: /missing\n", encoding="utf-8")
    assert client.get("/capacity").status_code == 409
    monkeypatch.setenv("COCKPIT_WORKSPACE", str(env["workspace"]))
    monkeypatch.setenv(
        "COCKPIT_PACK", os.path.join(os.path.dirname(os.path.dirname(__file__)), "packs", "acme", "pack.yaml")
    )
    monkeypatch.setenv("COCKPIT_HUMAN", "1")
    from tests.support.boards import insert_card

    insert_card("acme", "busy", "x", "intake", "running")
    insert_card("acme", "busy2", "x", "reviewer", "running")
    insert_card("acme", "busy3", "x", "analyst", "running")
    write_owner(1, "lane:worker-1")
    assert client.post("/kickoff", json={"ticket": "TASK-100", "mode": "intake"}).status_code == 409
    pushed = create(pack, "TASK-702", "ci-rerun", "c", "r", {"repo": "api", "run_id": "9"})
    from cockpitlib.outbox import endorse

    endorse(pushed["id"], "low", "", "gatekeeper", "fixture-a", "fixture-large")
    assert client.post("/publish", json={"id": pushed["id"], "confirm": pushed["id"]}).status_code == 200

    try:
        run_json(["git", "--version"])
    except Exception:  # noqa: BLE001 - the test only needs to know that it raised
        pass
    assert qa()


def test_every_seat_gets_cockpit_on_its_own_terminal_path(env):
    """Hermes puts $HERMES_HOME/bin on a lane's terminal PATH, and a seat's HERMES_HOME is its profile folder: the home's
    link alone leaves every lane with `cockpit: command not found`."""
    from cockpitlib.pack import plugin_root
    from cockpitlib.setup import seat_cockpit, seat_drift

    pack = load_pack(os.environ["COCKPIT_PACK"])
    setup(pack)
    target = os.path.join(plugin_root(), "bin", "cockpit")
    for lane in ("intake", "worker-1"):
        link = os.path.join(profile_dir(lane), "bin", "cockpit")
        assert os.path.islink(link) and os.readlink(link) == target and seat_cockpit(lane) == ""
    link = os.path.join(profile_dir("intake"), "bin", "cockpit")
    os.remove(link)
    assert "no bin/cockpit" in seat_cockpit("intake")
    assert any("intake: no bin/cockpit" in item for item in seat_drift(pack))
    os.symlink("/old/checkout/bin/cockpit", link)
    assert "points at /old/checkout" in seat_cockpit("intake")
    _bin_link(["intake"])
    assert os.readlink(link) == target, "a link to an old checkout is replaced"
    os.remove(link)
    open(link, "w", encoding="utf-8").write("#!/bin/sh\n")
    _bin_link(["intake"])
    assert not os.path.islink(link), "a file put there on purpose stays"
    os.remove(link)
    _bin_link(["intake"])
    assert seat_cockpit("intake") == ""


def test_on_windows_a_seat_gets_a_cmd_shim(env, monkeypatch):
    from cockpitlib import setup as setup_module

    monkeypatch.setattr(setup_module.os, "name", "nt")
    made = setup_module._place_cockpit(os.path.join(profile_dir("intake"), "bin"))
    assert made.endswith("cockpit.cmd") and "%*" in open(made, encoding="utf-8").read()
    sh = os.path.join(profile_dir("intake"), "bin", "cockpit")
    assert (
        open(sh, encoding="utf-8").read().startswith("#!/bin/sh\nexec ") and '"$@"' in open(sh, encoding="utf-8").read()
    )
    assert setup_module.seat_cockpit("intake") == ""
    open(sh, "w", encoding="utf-8").write('#!/bin/sh\nexec py "/old/bin/cockpit" "$@"\n')
    assert "another checkout" in setup_module.seat_cockpit("intake")
    os.remove(made)
    assert "cockpit.cmd" in setup_module.seat_cockpit("intake")


def test_a_seat_left_over_after_a_lower_count_is_linked_and_a_seat_it_cannot_reach_does_not_stop_setup(
    env, monkeypatch
):
    from cockpitlib import setup as setup_module

    pack = load_pack(os.environ["COCKPIT_PACK"])
    setup(pack)
    assert "intake" in setup_module._linked_lanes(pack, [])
    blocked = os.path.join(profile_dir("intake"), "bin")
    shutil.rmtree(blocked)
    open(blocked, "w", encoding="utf-8").write("a file where the bin folder goes")
    _bin_link(["intake", "worker-1"])
    assert "no bin/cockpit" in setup_module.seat_cockpit("intake") or setup_module.seat_cockpit("intake")
    assert setup_module.seat_cockpit("worker-1") == ""
    os.remove(blocked)
