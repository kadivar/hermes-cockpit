# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The pack `cockpit init` writes is one that works: over seven workspace layouts and both answers about production,
with nothing but the binding file to find it, the pack loads, its repos resolve, Hermes knows its provider, setup passes,
doctor has no error, every warning names its fix, and a second init changes no byte."""

import hashlib
import os
import subprocess

import pytest

from cockpitlib import cli, doctor, scaffold
from cockpitlib.pack import check_known_providers, check_repos, load
from cockpitlib.paths import binding_file, hermes_home, load_binding, pack_path, root, workspace
from cockpitlib.setup import setup

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# The warnings a fresh scaffold may carry: each is a thing only the adopter can supply (a staging URL, a test command)
# or a tool this machine may lack. Anything else is a scaffold that is not finished.
ALLOWED = {"staging.missing", "repos.no-gates", "tools.video", "python.yaml-missing"}
CONFIG = "model:\n  provider: alpha\n  default: big-1\n"


def _repo(folder, origin="", files=()) -> None:
    folder.mkdir(parents=True)
    subprocess.run(["git", "init", "-q", str(folder)], check=True)
    if origin:
        subprocess.run(["git", "-C", str(folder), "remote", "add", "origin", origin], check=True)
    for name, text in files:
        (folder / name).write_text(text, encoding="utf-8")


def _single_repo_as_cwd(base):
    _repo(base / "app")
    return base / "app", "", ["app"]


def _child_repos(base):
    _repo(
        base / "ws" / "api",
        "https://github.com/example-org/api.git",
        [("package.json", '{"scripts": {"test": "node test.js"}}')],
    )
    _repo(base / "ws" / "web", "git@github.com:example-org/web.git")
    return base, "ws", ["api", "web"]


def _sibling_repos(base):
    (base / "ws").mkdir(parents=True)
    _repo(base / "api", files=[("go.mod", "module example.test/api\n")])
    _repo(base / "web")
    return base, "ws", ["api", "web"]


def _a_repo_with_no_remote(base):
    _repo(base / "ws" / "tool")
    return base, "ws", ["tool"]


def _a_remote_on_another_forge(base):
    _repo(base / "ws" / "api", "git@git.example.test:team/api.git")
    return base, "ws", ["api"]


def _no_project_markers(base):
    _repo(base / "ws" / "notes", files=[("README", "notes\n")])
    return base, "ws", ["notes"]


def _a_hermes_home_with_only_known_providers(base):
    _repo(base / "ws" / "api")
    return base, "ws", ["api"]


LAYOUTS = (
    _single_repo_as_cwd,
    _child_repos,
    _sibling_repos,
    _a_repo_with_no_remote,
    _a_remote_on_another_forge,
    _no_project_markers,
    _a_hermes_home_with_only_known_providers,
)
PRODUCTION = (
    ["--no-production"],
    ["--production-host", r"app\.example\.test", "--production-host", r"admin\.example\.test"],
)


@pytest.fixture
def machine(tmp_path, monkeypatch):
    """A machine with a Hermes and nothing bound: no workspace, pack or root is named in the environment."""
    home = tmp_path / "h"
    home.mkdir()
    monkeypatch.setenv("COCKPIT_HERMES_HOME", str(home))
    monkeypatch.setenv("COCKPIT_HUMAN", "1")
    monkeypatch.setenv("COCKPIT_CURSOR_HOOKS", str(tmp_path / "editor" / "hooks.json"))
    keys = tmp_path / "keys"
    keys.mkdir(mode=0o700)
    monkeypatch.setenv("GNUPGHOME", str(keys))
    monkeypatch.setenv("PATH", os.path.join(ROOT, "tests", "bin") + os.pathsep + os.environ.get("PATH", ""))
    monkeypatch.setattr(scaffold, "CODING_TOOLS", ("no-such-coding-tool",))
    for name in ("COCKPIT_WORKSPACE", "COCKPIT_PACK", "COCKPIT_ROOT", "COCKPIT_WT", "COCKPIT_VOLUMES"):
        monkeypatch.delenv(name, raising=False)
    return home


def _bytes(*folders) -> dict:
    found = {}
    for folder in folders:
        for base, dirs, names in os.walk(folder):
            dirs[:] = [name for name in dirs if name != ".git"]
            for name in names:
                path = os.path.join(base, name)
                found[path] = hashlib.sha256(open(path, "rb").read()).hexdigest()
    return found


def _tokens() -> list:
    """The words tests/guards/grep_tokens.py refuses in the product tree: a written pack holds none of them either."""
    words = []
    for name in ("forbidden-tokens.txt", "ui-vendor-names.txt"):
        words += [
            line.strip()
            for line in open(os.path.join(ROOT, "tests", "guards", name), encoding="utf-8")
            if line.strip() and not line.startswith("#")
        ]
    return words


@pytest.mark.parametrize("production", PRODUCTION, ids=("no-production", "production-hosts"))
@pytest.mark.parametrize("layout", LAYOUTS, ids=lambda layout: layout.__name__.strip("_"))
def test_the_pack_init_writes_loads_sets_up_and_leaves_doctor_without_an_error(
    machine, layout, production, tmp_path, monkeypatch, capsys
):
    base = tmp_path / "w"
    start, directory, names = layout(base)
    if layout is _a_hermes_home_with_only_known_providers:
        (machine / "known-providers").write_text("alpha\nbeta\n", encoding="utf-8")
    else:
        (machine / "config.yaml").write_text(CONFIG, encoding="utf-8")
    monkeypatch.chdir(start)
    argv = ["init", *([directory] if directory else []), *production, "--yes"]

    before = _bytes(str(base), str(machine))
    assert cli.main(argv) == 0, capsys.readouterr().err
    assert _bytes(str(base), str(machine)) == before and "nothing was written" in capsys.readouterr().out, (
        "a dry run writes nothing"
    )

    assert cli.main([*argv, "--write"]) == 0, capsys.readouterr().err
    assert "next: cockpit setup, then cockpit doctor" in capsys.readouterr().out
    bound = load_binding()
    assert sorted(bound) == ["pack", "workspace"] and os.path.isfile(binding_file())
    assert workspace() == os.path.realpath(bound["workspace"]) and pack_path() == os.path.join(
        workspace(), "cockpit-pack", "pack.yaml"
    )
    if layout is _single_repo_as_cwd:
        assert workspace() == os.path.realpath(str(base / "app")) + "-workspace"

    pack = load(pack_path())
    check_repos(pack, root())
    check_known_providers(pack, hermes_home())
    assert [repo["name"] for repo in pack["repos"]["repos"]] == names
    assert pack["seats"] == {"slots": 1, "intake": 1, "reviewer": 1, "analyst": 1}
    assert pack["providers"]["main"]["hermes_provider"] == "alpha" and set(pack["roles"].values()) == {"main"}
    assert pack["skills_dir"] == [os.path.join(os.path.dirname(pack_path()), "skills")]
    assert "skills_dir: ['{pack}/skills']" in open(pack_path(), encoding="utf-8").read(), (
        "no path of this machine is written"
    )
    assert str(tmp_path) not in "".join(
        open(os.path.join(pack["_dir"], name), encoding="utf-8").read()
        for name in ("pack.yaml", "repos.yaml", "skills.yaml", "egress.yaml")
    )

    setup(pack)
    found = doctor.findings(pack)
    assert [(item["id"], item["message"]) for item in found if item["severity"] == "error"] == []
    warnings = [item for item in found if item["severity"] == "warning"]
    assert [item["id"] for item in warnings if item["id"] not in ALLOWED] == []
    assert all(item["fix"] for item in warnings)
    assert cli.main(["doctor"]) == 0 and "doctor: OK" in capsys.readouterr().out

    written = _bytes(pack["_dir"])
    assert (
        written
        and [
            word
            for word in _tokens()
            for path in written
            if word in open(path, encoding="utf-8", errors="replace").read()
        ]
        == []
    )
    kept = _bytes(str(base), os.path.dirname(binding_file()))
    assert cli.main([*argv, "--write"]) == 2
    assert "is there and not empty: init never replaces a file" in capsys.readouterr().err
    assert _bytes(str(base), os.path.dirname(binding_file())) == kept, "a second init changes no byte"


def test_the_layouts_differ_where_the_matrix_says_they_do(machine, tmp_path):
    (machine / "config.yaml").write_text(CONFIG, encoding="utf-8")
    start, directory, _names = _child_repos(tmp_path / "kids")
    kids = scaffold.detect(str(start / directory))
    assert [(repo["path"], repo["base"], repo["host"], repo["org"]) for repo in kids["repos"]] == [
        ("ws/api", "main", "github.com", "example-org"),
        ("ws/web", "main", "github.com", "example-org"),
    ]
    assert kids["org"] == "example-org" and kids["repos"][0]["suggested"] == ["npm test"] and kids["model"] == "big-1"
    start, directory, _names = _sibling_repos(tmp_path / "sibs")
    sibs = scaffold.detect(str(start / directory))
    assert [(repo["path"], repo["suggested"]) for repo in sibs["repos"]] == [("api", ["go test ./..."]), ("web", [])]
    start, directory, _names = _a_remote_on_another_forge(tmp_path / "forge")
    other = scaffold.detect(str(start / directory))
    assert (other["host"], other["org"]) == ("git.example.test", "team")
    assert any(note.startswith("the repos' origin is git.example.test, not github.com") for note in other["notes"])
    assert "# Detected on git.example.test" in scaffold.files_for({**other, "no_production": True})["pack.yaml"]


@pytest.mark.parametrize("project", ("", "WEB"))
@pytest.mark.parametrize("production", PRODUCTION, ids=("no-production", "production-hosts"))
def test_the_pack_init_writes_for_a_project_whose_tickets_are_issues_loads_sets_up_and_leaves_doctor_without_an_error(
    machine, production, project, tmp_path, monkeypatch, capsys
):
    from cockpitlib import tracker
    from cockpitlib.trackers.github_issues import GitHubIssuesTracker

    base = tmp_path / "w"
    start, directory, names = _child_repos(base)
    (machine / "config.yaml").write_text(CONFIG, encoding="utf-8")
    monkeypatch.chdir(start)
    argv = [
        "init",
        directory,
        *production,
        "--yes",
        "--tracker",
        "github-issues",
        *(["--project", project] if project else []),
    ]
    before = _bytes(str(base), str(machine))
    assert cli.main(argv) == 0, capsys.readouterr().err
    said = capsys.readouterr().out
    assert (
        _bytes(str(base), str(machine)) == before
        and "nothing was written" in said
        and "tracker     github-issues" in said
    )
    assert cli.main([*argv, "--write"]) == 0, capsys.readouterr().err
    assert "next: cockpit setup, then cockpit doctor" in capsys.readouterr().out

    pack = load(pack_path())
    check_repos(pack, root())
    check_known_providers(pack, hermes_home())
    assert pack["tracker"] == {"kind": "github-issues", "project": project or "GH", "repo": names[0]}
    written = open(pack_path(), encoding="utf-8").read()
    assert "kind: github-issues" in written and "tracker.example.test" not in written, (
        "no tracker URL is asked for or written"
    )
    made = tracker.tracker_for(pack)
    key = f"{project or 'GH'}-12"
    assert type(made) is GitHubIssuesTracker and (made.repo, made.number(key)) == (names[0], 12)
    assert made.browse_url(key) == f"https://github.com/example-org/{names[0]}/issues/12" == tracker.browse(pack, key)

    setup(pack)
    found = doctor.findings(pack)
    assert [(item["id"], item["message"]) for item in found if item["severity"] == "error"] == []
    warnings = [item for item in found if item["severity"] == "warning"]
    assert [item["id"] for item in warnings if item["id"] not in ALLOWED] == [] and all(
        item["fix"] for item in warnings
    )
    assert cli.main(["doctor"]) == 0 and "doctor: OK" in capsys.readouterr().out
    kept = _bytes(pack["_dir"])
    assert (
        kept
        and [
            word for word in _tokens() for path in kept if word in open(path, encoding="utf-8", errors="replace").read()
        ]
        == []
    )


def test_init_names_no_repo_for_the_issues_when_it_found_none_and_takes_no_tracker_it_does_not_know(
    machine, tmp_path, capsys
):
    (machine / "config.yaml").write_text(CONFIG, encoding="utf-8")
    (tmp_path / "empty" / "ws").mkdir(parents=True)
    found = scaffold.detect(str(tmp_path / "empty" / "ws"), tracker="github-issues", project="OPS")
    assert found["repos"] == [] and any(
        note.startswith("tracker github-issues: no repo was found to hold the issues") for note in found["notes"]
    )
    block = scaffold.files_for({**found, "no_production": True})["pack.yaml"].split("tracker:")[1].split("\n\n")[0]
    assert "kind: github-issues" in block and "project: OPS" in block and "repo:" not in block and "url:" not in block
    assert scaffold.detect(str(tmp_path / "empty" / "ws"))["project"] == "TASK" and scaffold.TRACKERS == (
        "jira",
        "command",
        "github-issues",
    )
    assert cli.main(["init", str(tmp_path / "empty" / "ws"), "--no-production", "--tracker", "issues"]) == 2
    assert "invalid value" in capsys.readouterr().err
