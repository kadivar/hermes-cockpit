# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The pack names the coding-tool home, its arguments, and an optional skill router."""

import os
import shutil

import pytest
import yaml

from cockpitlib.acts import kickoff_text
from cockpitlib.doctor import run as doctor_run
from cockpitlib.errors import PackError
from cockpitlib.migrate import discover, draft
from cockpitlib.pack import _agent, _router, agent_launch, load
from cockpitlib.setup import profile_dir, setup


def test_agent_launch_router_and_seat_env(env):
    pack = load(os.environ["COCKPIT_PACK"])
    assert agent_launch(pack)["router"].endswith("router.md")
    assert agent_launch(pack)["home"].endswith(os.path.join("homes", "acme"))
    assert "--workspace" in agent_launch(pack)["args"]
    home = env["workspace"] / "agent-home"
    (home / "extra").mkdir(parents=True)
    (home / "AGENTS.md").write_text("lookup\n", encoding="utf-8")
    pack["agent"] = {"home": "agent-home", "add_dirs": ["extra"], "args": ["--approve-mcps"]}
    pack["skills"] = {**pack["skills"], "router": "AGENTS.md"}
    launch = agent_launch(pack)
    assert launch["home"] == str(home.resolve())
    assert "--approve-mcps" in launch["args"]
    assert launch["args"][launch["args"].index("--workspace") + 1] == str(home.resolve())
    assert str((home / "extra").resolve()) in launch["args"]
    assert launch["router"].endswith("AGENTS.md")
    text = kickoff_text(pack, "TASK-100", "intake", "")
    assert "skill router" in text and "Coding tool home" in text
    assert "Ticket checkout" not in text
    checkout = env["root"] / "wt" / "TASK-100"
    checkout.mkdir(parents=True)
    assert "Ticket checkout" in kickoff_text(pack, "TASK-100", "intake", "")
    setup(pack)
    env_file = open(os.path.join(profile_dir("intake"), ".env"), encoding="utf-8").read()
    assert "COCKPIT_LANE=intake" in env_file
    assert "--approve-mcps" in env_file and "agent-home" in env_file
    pack["skills"]["router"] = "missing.md"
    assert "skill router missing" in doctor_run(pack)


def test_a_missing_agent_home_uses_the_ticket_folder(env, monkeypatch):
    from cockpitlib import chat

    monkeypatch.setattr("cockpitlib.pack.load", lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("down")))
    assert chat._agent_home() == ""
    monkeypatch.setattr("cockpitlib.pack.load", lambda *_a, **_k: {})
    monkeypatch.setattr(
        "cockpitlib.pack.agent_launch", lambda _pack: {"home": os.path.join(str(env["workspace"]), "missing-home")}
    )
    assert chat._agent_home() == ""
    monkeypatch.setattr(chat, "_agent_home", lambda: "")
    folder = os.path.join(os.environ["COCKPIT_WT"], "TASK-9")
    os.makedirs(folder, exist_ok=True)
    assert chat.chat_cwd("TASK-9") == folder
    assert chat.chat_cwd("missing-ticket") == os.environ["COCKPIT_ROOT"]
    pack = load(os.environ["COCKPIT_PACK"])
    pack["skills"] = {**pack["skills"], "router": "/tmp/cockpit-router-absent.md"}
    assert agent_launch(pack)["router"] == os.path.realpath("/tmp/cockpit-router-absent.md")


def test_bad_agent_and_migrate_draft(env):
    source = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "packs", "acme")
    dest = env["root"] / "packs" / "acme"
    shutil.copytree(source, dest)
    raw = yaml.safe_load(open(dest / "pack.yaml", encoding="utf-8"))
    raw["agent"] = {"args": [1]}
    open(dest / "pack.yaml", "w", encoding="utf-8").write(yaml.safe_dump(raw))
    with pytest.raises(PackError, match="agent.args"):
        load(str(dest / "pack.yaml"))
    with pytest.raises(PackError, match="mapping"):
        _agent({"agent": "no"})
    with pytest.raises(PackError, match="add_dirs"):
        _agent({"agent": {"add_dirs": "no"}})
    with pytest.raises(PackError, match="home"):
        _agent({"agent": {"home": 1}})
    with pytest.raises(PackError, match="router"):
        _router({"skills": {"router": 1}})
    workspace = env["root"] / "adopt"
    (workspace / ".cursor" / "skills" / "demo").mkdir(parents=True)
    (workspace / ".cursor" / "skills" / "demo" / "SKILL.md").write_text("# demo\n", encoding="utf-8")
    (workspace / ".cursor" / "mcp.json").write_text("{}\n", encoding="utf-8")
    (workspace / "AGENTS.md").write_text("router\n", encoding="utf-8")
    found = discover(str(workspace))
    assert found["router"] == "AGENTS.md"
    assert found["agent"]["args"] == ["--approve-mcps"]
    assert found["agent"]["home"] == str(workspace.resolve())
    written = draft(found, str(env["workspace"] / "cockpit-pack"))
    pack_text = open(os.path.join(env["workspace"], "cockpit-pack", "pack.yaml"), encoding="utf-8").read()
    skills_text = open(os.path.join(env["workspace"], "cockpit-pack", "skills.yaml"), encoding="utf-8").read()
    assert "approve-mcps" in pack_text and "router: AGENTS.md" in skills_text
    assert "outbox" not in skills_text
    repos_text = open(os.path.join(env["workspace"], "cockpit-pack", "repos.yaml"), encoding="utf-8").read()
    assert "demo" not in repos_text
    assert "repos: []" in repos_text
    assert "  project: PROJECT\n" in pack_text  # a draft names its tracker project in the tracker block
    assert (
        "hermes_provider: fixture-a" in pack_text and "fixture-b" not in pack_text
    )  # the Hermes home's own first provider
    assert "fixture-large" not in pack_text and "fixture-fast" not in pack_text
    assert "project: TASK" not in pack_text
    assert "project: NORTH" not in pack_text
    assert written
    root = os.path.dirname(os.path.dirname(__file__))
    for pack_file in ("packs/acme/pack.yaml", "packs/bravo/pack.yaml"):
        pack = load(os.path.join(root, pack_file))
        named = env["workspace"] / f"draft-{pack['name']}"
        draft({**found, "project": pack["tracker"]["project"], "org": pack["forge"]["org"]}, str(named))
        text = open(named / "pack.yaml", encoding="utf-8").read()
        assert f"  project: {pack['tracker']['project']}\n" in text
        assert f"  org: {pack['forge']['org']}\n" in text
        assert "fixture-b" not in text and pack["providers"]["judgment"]["model"] not in text
        other = "NORTH" if pack["tracker"]["project"] == "TASK" else "TASK"
        assert f"project: {other}" not in text
        skilled = env["workspace"] / f"skills-{pack['name']}"
        draft({**found, "skills": pack["skills"]}, str(skilled))
        skill_body = open(skilled / "skills.yaml", encoding="utf-8").read()
        assert "analyze-ticket" in skill_body
        with_repos = env["workspace"] / f"repos-{pack['name']}"
        draft({**found, "repos": pack["repos"]["repos"]}, str(with_repos))
        repo_body = open(with_repos / "repos.yaml", encoding="utf-8").read()
        assert pack["repos"]["repos"][0]["name"] in repo_body
        other_file = "packs/bravo/pack.yaml" if pack["name"] == "acme" else "packs/acme/pack.yaml"
        other_repo = load(os.path.join(root, other_file))["repos"]["repos"][0]["name"]
        assert other_repo not in repo_body
        assert pack["skills"]["router"] in skill_body or "router: AGENTS.md" in skill_body
