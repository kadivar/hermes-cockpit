# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""`cockpit init` detects, says what it would write, and writes only with --write. It never replaces a file, never
guesses what production is, scans for a secret before its first write, takes back what it made when the pack does not
load, and writes the binding last."""

import json
import os
import subprocess

import pytest
import yaml

from cockpitlib import cli, migrate, pack_keys, scaffold
from cockpitlib.errors import CockpitError, PackError
from cockpitlib.pack import _skills, load
from cockpitlib.paths import binding_file, load_binding

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HOST = r"app\.example\.test"


@pytest.fixture
def machine(tmp_path, monkeypatch):
    """A Hermes home that names a provider and a model, a workspace folder with one repo in it, and nothing bound."""
    home = tmp_path / "h"
    home.mkdir()
    (home / "config.yaml").write_text("model:\n  provider: alpha\n  default: big-1\n", encoding="utf-8")
    monkeypatch.setenv("COCKPIT_HERMES_HOME", str(home))
    monkeypatch.setenv("COCKPIT_HUMAN", "1")
    monkeypatch.setattr(scaffold, "CODING_TOOLS", ("no-such-coding-tool",))
    for name in ("COCKPIT_WORKSPACE", "COCKPIT_PACK", "COCKPIT_ROOT"):
        monkeypatch.delenv(name, raising=False)
    workspace = tmp_path / "w" / "ws"
    (workspace / "api").mkdir(parents=True)
    subprocess.run(["git", "init", "-q", str(workspace / "api")], check=True)
    return {"home": home, "workspace": workspace, "pack": workspace / "cockpit-pack"}


def _tree(folder) -> list:
    return sorted(
        os.path.relpath(os.path.join(base, name), folder)
        for base, dirs, names in os.walk(folder)
        for name in [*names, *dirs]
        if ".git" not in os.path.join(base, name).split(os.sep)
    )


# ---------- nothing is written unless asked, and production is never guessed ----------


def test_without_write_init_prints_its_findings_and_makes_nothing(machine, tmp_path, capsys):
    before = _tree(tmp_path)
    assert cli.main(["init", str(machine["workspace"])]) == 0
    printed = capsys.readouterr()
    assert f"workspace   {machine['workspace']}" in printed.out and "provider    alpha, model big-1" in printed.out
    assert "production  NOT ANSWERED" in printed.out and "repo        api at ws/api, base main" in printed.out
    assert f"  {machine['pack']}/pack.yaml" in printed.out and "would write:" in printed.out
    assert "production is not answered, and init never guesses it: cockpit init --production-host" in printed.err
    assert cli.main(["init", str(machine["workspace"]), "--production-host", HOST]) == 0
    printed = capsys.readouterr()
    assert f"production  {HOST}" in printed.out
    assert (
        printed.out.splitlines()[-1]
        == f"nothing was written. To write it: cockpit init {machine['workspace']} --production-host '{HOST}' --write"
    )
    assert _tree(tmp_path) == before and not os.path.exists(binding_file())


@pytest.mark.parametrize("flags", (["--yes"], ["--write"], ["--write", "--yes"]))
def test_init_stops_with_an_example_when_production_is_not_answered(machine, tmp_path, capsys, flags):
    before = _tree(tmp_path)
    assert cli.main(["init", str(machine["workspace"]), *flags]) == 2
    assert "or cockpit init --no-production --write" in capsys.readouterr().err
    assert _tree(tmp_path) == before


@pytest.mark.parametrize(
    "argv",
    (
        ["--slots", "many"],
        ["--slots", "9"],
        ["--production-host", "("],
        ["--production-host", HOST, "--no-production"],
        ["--tracker", "mail"],
        ["one", "two"],
        ["--pack"],
        ["--pack", "--write"],
        ["--pack", "a", "--pack", "b"],
    ),
)
def test_a_wrong_argument_names_the_usage_and_runs_nothing(machine, tmp_path, capsys, argv):
    before = _tree(tmp_path)
    assert cli.main(["init", *argv]) == 2
    assert "Examples:" in capsys.readouterr().err and _tree(tmp_path) == before


def test_a_lane_may_look_and_may_not_write(machine, monkeypatch, capsys):
    monkeypatch.setenv("COCKPIT_LANE", "worker-1")
    assert cli.main(["init", str(machine["workspace"]), "--no-production"]) == 0
    assert cli.main(["init", str(machine["workspace"]), "--no-production", "--write"]) == 1
    assert "a new pack and the binding stay with the human" in capsys.readouterr().err and not machine["pack"].exists()


# ---------- what is written ----------


def test_write_makes_the_pack_then_the_binding_and_says_what_is_next(machine, capsys):
    assert (
        cli.main(
            [
                "init",
                str(machine["workspace"]),
                "--no-production",
                "--write",
                "--json",
                "--slots",
                "2",
                "--staging-origin",
                "https://staging.example.test",
                "--tracker-url",
                "https://tickets.example.test",
                "--project",
                "SHOP",
                "--no-starter",
            ]
        )
        == 0
    )
    told = json.loads(capsys.readouterr().out)
    assert sorted(told) == [
        "binding",
        "coding",
        "files",
        "model",
        "notes",
        "pack",
        "production",
        "provider",
        "refused",
        "repos",
        "tracker",
        "workspace",
        "written",
    ]
    assert (
        told["written"] is True and told["production"] == "none" and told["refused"] == "" and told["tracker"] == "jira"
    )
    assert sorted(os.path.relpath(path, told["pack"]) for path in told["files"]) == [
        ".gitignore",
        "egress.yaml",
        "pack.local.example.yaml",
        "pack.yaml",
        "repos.yaml",
        "skills.yaml",
        "skills/.gitkeep",
        "staging.yaml",
    ]
    assert sorted(_tree(machine["pack"])) == [
        ".gitignore",
        "egress.yaml",
        "pack.local.example.yaml",
        "pack.yaml",
        "repos.yaml",
        "skills",
        "skills.yaml",
        "skills/.gitkeep",
        "staging.yaml",
    ]
    assert load_binding() == {"workspace": str(machine["workspace"]), "pack": str(machine["pack"] / "pack.yaml")}
    pack = load(str(machine["pack"] / "pack.yaml"))
    assert (
        pack["seats"]["slots"] == 2
        and pack["tracker"]["url"] == "https://tickets.example.test"
        and pack["tracker"]["project"] == "SHOP"
    )
    written = yaml.safe_load((machine["pack"] / "pack.yaml").read_text(encoding="utf-8"))
    assert written["tracker"] == {"url": "https://tickets.example.test", "project": "SHOP"} and written["forge"] == {
        "org": pack["forge"]["org"]
    }
    assert pack["egress"]["no_production_hosts"] is True and pack["egress"]["production_hosts"] == []
    assert yaml.safe_load((machine["pack"] / "staging.yaml").read_text(encoding="utf-8")) == {
        "origins": {"app": "https://staging.example.test"}
    }
    assert (
        pack["providers"]["coding"]["command"] == ["true"]
        and "No known coding tool was found on PATH" in (machine["pack"] / "pack.yaml").read_text()
    )
    assert not [name for name in os.listdir(machine["workspace"]) if name.startswith(".cockpit-pack")], (
        "the folder it built in is gone"
    )


def test_every_comment_in_a_written_pack_is_the_registrys_sentence_for_that_key(machine):
    found = scaffold.detect(
        str(machine["workspace"]), production_hosts=[HOST], staging_origin="https://staging.example.test"
    )
    files = scaffold.files_for(found)
    docs = {entry["doc"] for entry in pack_keys.ENTRIES}
    for name, text in files.items():
        assert yaml.safe_load(text), name
        lines = text.split("\n\n", 1)[1].splitlines()  # under the file's own heading
        keys = [line for line in lines if line.strip() and not line.lstrip().startswith("#")]
        comments = [line.strip()[2:] for line in lines if line.lstrip().startswith("# ")]
        assert [
            comment
            for comment in comments
            if comment not in docs
            and not comment.startswith(("One provider serves", "none: the worker", "No known coding tool"))
        ] == [], name
        top = [line.split(":")[0] for line in keys if not line.startswith((" ", "-"))]
        for key in top:
            doc = f"# {pack_keys.find(key if name == 'pack.yaml' else f'{name}:{key}')['doc']}"
            between = lines[
                lines.index(doc) + 1 : [number for number, line in enumerate(lines) if line.startswith(f"{key}:")][0]
            ]
            assert all(line.startswith("# ") for line in between), (name, key)


def test_gates_are_suggested_from_project_files_and_written_only_when_accepted(machine, capsys):
    repo = machine["workspace"] / "api"
    (repo / "package.json").write_text('{"scripts": {"test": "node t.js"}}', encoding="utf-8")
    (repo / "pyproject.toml").write_text("[tool.pytest.ini_options]\n", encoding="utf-8")
    (repo / "composer.json").write_text('{"scripts": {"test": "phpunit"}}', encoding="utf-8")
    (repo / "go.mod").write_text("module x\n", encoding="utf-8")
    (repo / "Cargo.toml").write_text("[package]\n", encoding="utf-8")
    (repo / "Makefile").write_text("build:\n\ttrue\ntest:\n\ttrue\n", encoding="utf-8")
    every = ["npm test", "python -m pytest -q", "composer test", "go test ./...", "cargo test", "make test"]
    assert scaffold.suggested_gates(str(repo)) == every
    (repo / "composer.json").write_text("{}", encoding="utf-8")
    (repo / "package.json").write_text("not json", encoding="utf-8")
    assert scaffold.suggested_gates(str(repo))[:2] == ["python -m pytest -q", "vendor/bin/phpunit"]
    (repo / "Makefile").chmod(0)  # a project file that cannot be read suggests nothing and stops nothing
    assert "make test" not in scaffold.suggested_gates(str(repo)) or os.geteuid() == 0
    (repo / "Makefile").chmod(0o644)
    text = scaffold.files_for(scaffold.detect(str(machine["workspace"]), no_production=True))["repos.yaml"]
    assert (
        "    gates: []" in text
        and "# suggested from this repo's files (cockpit init --accept-gates writes it): [" in text
    )
    assert cli.main(["init", str(machine["workspace"]), "--no-production", "--accept-gates", "--write"]) == 0
    assert load(str(machine["pack"] / "pack.yaml"))["repos"]["repos"][0]["gates"] == scaffold.suggested_gates(str(repo))
    assert "suggested" not in (machine["pack"] / "repos.yaml").read_text(encoding="utf-8")


# ---------- it never replaces, and it takes back what it made ----------


def test_a_pack_folder_that_holds_anything_is_refused_and_an_empty_one_is_used(machine, tmp_path, capsys):
    machine["pack"].mkdir()
    (machine["pack"] / "notes.txt").write_text("mine\n", encoding="utf-8")
    before = _tree(tmp_path)
    assert cli.main(["init", str(machine["workspace"]), "--no-production", "--write"]) == 2
    assert (
        "is there and not empty: init never replaces a file (name another place with --pack DIR)"
        in capsys.readouterr().err
    )
    assert _tree(tmp_path) == before and (machine["pack"] / "notes.txt").read_text(encoding="utf-8") == "mine\n"
    elsewhere = tmp_path / "packs-here" / "first"
    assert (
        cli.main(
            ["init", str(machine["workspace"]), "--no-production", "--write", "--pack", str(elsewhere), "--no-bind"]
        )
        == 0
    )
    assert "binding     not written (--no-bind)" in capsys.readouterr().out
    assert (elsewhere / "pack.yaml").is_file() and not os.path.exists(binding_file())
    empty = tmp_path / "empty"
    empty.mkdir()
    assert cli.main(["init", str(machine["workspace"]), "--no-production", "--write", "--pack", str(empty)]) == 0
    assert load_binding()["pack"] == str(empty / "pack.yaml")
    a_file = tmp_path / "a-file"
    a_file.write_text("x", encoding="utf-8")
    assert cli.main(["init", str(machine["workspace"]), "--no-production", "--write", "--pack", str(a_file)]) == 2


def test_a_secret_stops_init_before_its_first_write(machine, tmp_path, monkeypatch, capsys):
    solo = tmp_path / "solo" / "app"
    solo.mkdir(parents=True)
    subprocess.run(["git", "init", "-q", str(solo)], check=True)
    before = _tree(tmp_path)
    monkeypatch.setattr(
        migrate, "secrets_scan", lambda text: "password=x" if "egress" in text or "lane may reach" in text else ""
    )
    assert cli.main(["init", str(solo), "--no-production", "--write"]) == 1
    assert "cockpit: secret in draft" in capsys.readouterr().err
    assert (
        _tree(tmp_path) == before
        and not os.path.exists(str(solo) + "-workspace")
        and not os.path.exists(binding_file())
    )


def test_a_pack_that_does_not_load_is_taken_back_and_nothing_is_bound(machine, tmp_path, monkeypatch, capsys):
    solo = tmp_path / "solo" / "app"
    solo.mkdir(parents=True)
    subprocess.run(["git", "init", "-q", str(solo)], check=True)
    before = _tree(tmp_path)
    (machine["home"] / "config.yaml").write_text("model:\n  provider: alpha\n", encoding="utf-8")
    real = scaffold.hermes_model
    monkeypatch.setattr(scaffold, "hermes_model", lambda home: {**real(home), "provider": "unheard-of"})
    assert cli.main(["init", str(solo), "--no-production", "--write"]) == 2
    assert "cockpit: provider unheard-of is not configured in Hermes" in capsys.readouterr().err
    assert _tree(tmp_path) == before and not os.path.exists(binding_file())
    monkeypatch.setattr(
        scaffold, "_check", lambda pack_file, workspace: (_ for _ in ()).throw(PackError("the pack does not load"))
    )
    assert cli.main(["init", str(machine["workspace"]), "--no-production", "--write"]) == 2
    assert _tree(tmp_path) == before


def test_a_machine_whose_hermes_names_no_provider_is_told_to_choose_one(machine, capsys):
    os.remove(machine["home"] / "config.yaml")
    assert scaffold.hermes_model(str(machine["home"])) == {"provider": "", "model": ""}
    assert cli.main(["init", str(machine["workspace"]), "--no-production", "--write"]) == 2
    assert (
        "known-providers: choose one in Hermes first (hermes model)" in capsys.readouterr().err
        and not machine["pack"].exists()
    )
    (machine["home"] / "config.yaml").write_text("- not\n- a mapping\n", encoding="utf-8")
    (machine["home"] / "known-providers").write_text("# ours\nbeta\nalpha\n", encoding="utf-8")
    assert scaffold.hermes_model(str(machine["home"])) == {"provider": "beta", "model": ""}
    found = scaffold.detect(str(machine["workspace"]), no_production=True)
    assert "providers.main.model is written as set-a-model; set it in pack.yaml" in "".join(found["notes"])
    assert "replace set-a-model before the first card" in scaffold.files_for(found)["pack.yaml"]


def test_the_command_tracker_needs_the_starters_script(machine, capsys):
    assert (
        cli.main(
            ["init", str(machine["workspace"]), "--no-production", "--write", "--no-starter", "--tracker", "command"]
        )
        == 2
    )
    assert (
        "--tracker command needs the starter's bin/tracker" in capsys.readouterr().err and not machine["pack"].exists()
    )


# ---------- the binding ----------


def test_a_binding_to_another_workspace_needs_rebind_and_is_kept_as_a_copy(machine, tmp_path, capsys):
    os.makedirs(os.path.dirname(binding_file()), exist_ok=True)
    old = "workspace: /srv/other\npack: /srv/other/cockpit-pack/pack.yaml\n"
    open(binding_file(), "w", encoding="utf-8").write(old)
    before = _tree(tmp_path)
    assert cli.main(["init", str(machine["workspace"]), "--no-production", "--write"]) == 2
    assert "binds another workspace (/srv/other): --rebind keeps a copy and binds this one" in capsys.readouterr().err
    assert _tree(tmp_path) == before and open(binding_file(), encoding="utf-8").read() == old
    assert cli.main(["init", str(machine["workspace"]), "--no-production", "--rebind"]) == 0
    assert "(replaces another workspace's; a copy is kept)" in capsys.readouterr().out
    assert cli.main(["init", str(machine["workspace"]), "--no-production", "--write", "--rebind"]) == 0
    copies = [name for name in os.listdir(os.path.dirname(binding_file())) if name.startswith("cockpit.yaml.")]
    assert (
        len(copies) == 1
        and open(os.path.join(os.path.dirname(binding_file()), copies[0]), encoding="utf-8").read() == old
    )
    assert (
        f"the binding that was there is kept as {os.path.join(os.path.dirname(binding_file()), copies[0])}"
        in capsys.readouterr().out
    )
    assert load_binding()["workspace"] == str(machine["workspace"])
    stamp = os.stat(binding_file()).st_mtime_ns
    second = tmp_path / "second-pack"
    planned = scaffold.plan(scaffold.detect(str(machine["workspace"]), no_production=True))
    assert planned["binding"]["kept"] is True and planned["binding"]["replaces"] is False
    assert cli.main(["init", str(machine["workspace"]), "--no-production", "--pack", str(second)]) == 2, (
        "another pack of the bound workspace is a rebind"
    )
    assert os.stat(binding_file()).st_mtime_ns == stamp
    assert "already this workspace" not in capsys.readouterr().out


# ---------- detection ----------


@pytest.mark.parametrize(
    "url, host, org",
    [
        ("git@github.com:example-org/api.git", "github.com", "example-org"),
        ("https://github.com/example-org/api", "github.com", "example-org"),
        ("ssh://git@git.example.test:2222/team/sub/api.git", "git.example.test", "team/sub"),
        ("https://user@Git.Example.Test/team/api.git/", "git.example.test", "team"),
        ("/srv/git/api.git", "", ""),
        ("../remotes/api.git", "", ""),
        ("file:///srv/git/api.git", "", ""),
        ("", "", ""),
    ],
)
def test_a_remote_gives_its_host_and_org_and_a_folder_on_this_machine_gives_neither(tmp_path, url, host, org):
    repo = tmp_path / "r"
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    if url:
        subprocess.run(["git", "-C", str(repo), "remote", "add", "origin", url], check=True)
    assert scaffold.repo_remote(str(repo)) == {"host": host, "org": org}


def test_a_repos_base_is_what_its_origin_calls_head_then_its_own_branch_then_main(tmp_path, monkeypatch):
    repo = tmp_path / "r"
    subprocess.run(["git", "init", "-q", "-b", "trunk", str(repo)], check=True)
    assert scaffold.repo_base(str(repo)) == "trunk"
    subprocess.run(
        ["git", "-C", str(repo), "symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/release/next"],
        check=True,
    )
    assert scaffold.repo_base(str(repo)) == "release/next"
    assert scaffold.repo_base(str(tmp_path / "not-a-repo")) == "main"
    monkeypatch.setattr(scaffold.subprocess, "run", lambda *a, **k: (_ for _ in ()).throw(OSError("no git")))
    assert scaffold._git(str(repo), "status") == ""


def test_repos_are_children_of_the_workspace_and_of_its_parent_and_the_workspace_child_wins_a_name(machine, tmp_path):
    parent = machine["workspace"].parent
    for folder in (parent / "api", parent / "web", parent / ".hidden", machine["workspace"] / "cockpit-pack"):
        folder.mkdir()
        subprocess.run(["git", "init", "-q", str(folder)], check=True)
    (parent / "plain").mkdir()
    found = scaffold.find_repos(str(machine["workspace"]), skip=(str(machine["workspace"] / "cockpit-pack"),))
    assert [(repo["name"], repo["path"]) for repo in found] == [("api", "ws/api"), ("web", "web")]
    assert scaffold.find_repos(str(tmp_path / "w" / "not-made-yet" / "deeper")) == []
    os.environ["COCKPIT_ROOT"] = str(tmp_path / "elsewhere")
    try:
        assert scaffold.find_repos(str(machine["workspace"]), skip=(str(machine["workspace"] / "cockpit-pack"),))[0][
            "path"
        ] == str(machine["workspace"] / "api")
    finally:
        del os.environ["COCKPIT_ROOT"]


def test_a_folder_that_is_a_repo_gets_a_sibling_workspace_and_a_router_file_is_found(machine, tmp_path, monkeypatch):
    repo = machine["workspace"] / "api"
    assert scaffold.place(str(repo)) == {"workspace": str(repo) + "-workspace", "moved_from": str(repo)}
    assert scaffold.place(str(repo), as_is=True) == {"workspace": str(repo), "moved_from": ""}
    monkeypatch.chdir(machine["workspace"])
    assert scaffold.place() == {"workspace": str(machine["workspace"]), "moved_from": ""}
    (machine["workspace"] / "AGENTS.md").write_text("router\n", encoding="utf-8")
    found = scaffold.detect("", no_production=True)
    assert found["router"] == "AGENTS.md" and "router: AGENTS.md" in scaffold.files_for(found)["skills.yaml"]
    moved = scaffold.detect(str(repo))
    assert moved["notes"][0].startswith(
        f"{repo} is a git repository, so it is a repo of the workspace and not the workspace"
    )
    empty = scaffold.detect(str(tmp_path / "nothing-here" / "ws"))
    assert any(note.startswith("no git repository is a child of") for note in empty["notes"]) and empty["name"] == "ws"


def test_the_first_known_coding_tool_on_path_starts_the_humans_sessions(machine, tmp_path, monkeypatch):
    assert scaffold.coding_command() == []
    tools = tmp_path / "tools"
    tools.mkdir()
    (tools / "second-tool").write_text("#!/bin/sh\n", encoding="utf-8")
    (tools / "second-tool").chmod(0o755)
    monkeypatch.setenv("PATH", str(tools) + os.pathsep + os.environ["PATH"])
    monkeypatch.setattr(scaffold, "CODING_TOOLS", ("first-tool", "second-tool"))
    assert scaffold.coding_command() == ["second-tool"]
    found = scaffold.detect(str(machine["workspace"]), no_production=True)
    assert "command: [second-tool]" in scaffold.files_for(found)["pack.yaml"] and not any(
        "coding tool" in note for note in found["notes"]
    )


# ---------- skills_dir may name a folder of the pack ----------


def test_skills_dir_takes_a_folder_inside_the_pack_and_refuses_one_that_leaves_it(tmp_path):
    (tmp_path / "skills" / "deep").mkdir(parents=True)
    data = {"_dir": str(tmp_path), "skills_dir": ["{pack}/skills", "{pack}/skills/deep", str(tmp_path / "skills")]}
    assert _skills(data) == [
        os.path.realpath(tmp_path / "skills"),
        os.path.realpath(tmp_path / "skills" / "deep"),
        os.path.realpath(tmp_path / "skills"),
    ]
    for bad in ("{pack}/", "{pack}/../skills", "{pack}//etc", "{pack}/skills/../../x"):
        with pytest.raises(PackError, match="names a folder inside the pack"):
            _skills({"_dir": str(tmp_path), "skills_dir": [bad]})
    os.symlink("/", tmp_path / "out")
    with pytest.raises(PackError, match="names a folder inside the pack"):
        _skills({"_dir": str(tmp_path), "skills_dir": ["{pack}/out"]})
    with pytest.raises(PackError, match="missing directory"):
        _skills({"_dir": str(tmp_path), "skills_dir": ["{pack}/absent"]})
    with pytest.raises(PackError, match="must be absolute"):
        _skills({"_dir": str(tmp_path), "skills_dir": ["skills"]})
    with pytest.raises(PackError, match="must be absolute"):
        _skills({"_dir": str(tmp_path), "skills_dir": ["@skills"]})  # the fixture anchor stays the fixtures' own


# ---------- the migration's verbs use the same detection and the same writer ----------


def test_discover_keeps_its_shape_and_writes_each_repo_where_the_kernel_resolves_it(machine):
    found = migrate.discover(str(machine["workspace"]))
    assert sorted(found) == ["agent", "name", "repos", "router", "skills_dir"]
    assert found["repos"] == [{"name": "api", "path": "ws/api", "base": "main", "gates": [], "suggested": []}]


def test_a_draft_replaces_no_file_and_a_worker_and_a_tester_seat_exist_in_it(machine, monkeypatch, capsys):
    monkeypatch.setenv("COCKPIT_WORKSPACE", str(machine["workspace"]))
    subprocess.run(
        ["git", "init", "-q", str(machine["workspace"])], check=True
    )  # a bound workspace that is a repo stays where it is
    assert cli.main(["migrate", "draft"]) == 0
    assert capsys.readouterr().out.splitlines()[0] == str(machine["pack"] / "pack.yaml")
    raw = yaml.safe_load((machine["pack"] / "pack.yaml").read_text(encoding="utf-8"))
    assert raw["seats"]["slots"] == 1 and raw["providers"]["main"] == {"hermes_provider": "alpha", "model": "big-1"}
    assert raw["agent"]["home"] == str(machine["workspace"]) and raw["skills_dir"] == ["{pack}/skills"]
    assert "Not answered yet. Doctor stays red until this lists production" in (
        machine["pack"] / "egress.yaml"
    ).read_text(encoding="utf-8")
    assert not os.path.exists(binding_file()), "the migration binds, not the draft"
    kept = (machine["pack"] / "pack.yaml").read_text(encoding="utf-8")
    assert cli.main(["migrate", "draft"]) == 2 and "init never replaces a file" in capsys.readouterr().err
    assert (machine["pack"] / "pack.yaml").read_text(encoding="utf-8") == kept
    with pytest.raises(CockpitError, match="secret in draft"):
        migrate.draft(
            {"name": "ws", "skills_dir": [], "repos": [], "note": "password=hunter2"},
            str(machine["workspace"] / "other"),
        )
    assert not (machine["workspace"] / "other").exists()
