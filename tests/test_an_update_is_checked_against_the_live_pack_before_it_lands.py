# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The update's pre-flight: before the checkout moves, the incoming commit's own code is run against the live pack. A
commit the pack does not load under, or one that changes what the pack means without declaring it, is refused and the
checkout stays where it was; the exported tree is removed either way; nothing skips the check."""

import json
import os
import subprocess

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from cockpitlib import self_update
from cockpitlib.errors import CockpitError
from dashboard.cockpit.router import router


def _beside(name):
    """A helper module of tests/support, loaded by its path: the name `tests` may resolve to another folder on a machine
    whose checkout sits next to one."""
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        f"cockpit_tests_{name}", os.path.join(os.path.dirname(os.path.abspath(__file__)), "support", f"{name}.py")
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


git, install = _beside("update_kit").git, _beside("update_kit").install

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PACKS = (os.path.join(ROOT, "packs", "acme", "pack.yaml"), os.path.join(ROOT, "packs", "bravo", "pack.yaml"))


@pytest.fixture
def made(tmp_path, monkeypatch):
    """A stand-in install with the calls its pre-flight made (`log()`) and every folder a pre-flight exported into."""
    found = install(tmp_path)
    monkeypatch.setenv("COCKPIT_PLUGIN_ROOT", found["plugin"])
    monkeypatch.setenv("PREFLIGHT_LOG", str(tmp_path / "preflight.log"))
    monkeypatch.setattr(self_update, "_record_hermes_revision", lambda name, revision: "")
    folders = []
    real = self_update._scratch

    def scratch():
        folders.append(real())
        return folders[-1]

    monkeypatch.setattr(self_update, "_scratch", scratch)

    def log():
        path = tmp_path / "preflight.log"
        return [line.split("\t") for line in path.read_text(encoding="utf-8").splitlines()] if path.exists() else []

    return {**found, "folders": folders, "log": log}


def _head(made) -> str:
    return git(made["plugin"], "rev-parse", "HEAD")


def _client():
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def test_a_commit_the_live_pack_does_not_load_under_is_refused_and_the_checkout_stays(env, made):
    made["commit"]("breaks the pack", {"PACK-CHECK-FAILS": "PackError: unknown key shiny_new_thing\n"})
    with pytest.raises(CockpitError) as refused:
        self_update.apply(made["plugin"], restart=False)
    said = str(refused.value)
    assert said.startswith("update refused: the live pack (") and said.endswith(
        "stops every lane: PackError: unknown key shiny_new_thing"
    )
    assert _head(made) == made["first"] and not git(made["plugin"], "status", "--porcelain")
    assert len(made["folders"]) == 1 and not os.path.exists(made["folders"][0]), "the exported tree is removed"
    assert self_update._read_check().get("previous") is None
    # the page's button meets the same refusal
    answer = _client().post("/update-apply", json={"restart": False})
    assert answer.status_code == 400 and "update refused" in answer.text and _head(made) == made["first"]
    assert all(not os.path.exists(folder) for folder in made["folders"])
    # the next commit repairs it: the update lands, both commits with it
    newest = made["commit"]("repairs the pack", {"PACK-CHECK-FAILS": None})
    assert self_update.apply(made["plugin"], restart=False)["changed"] is True and _head(made) == newest


@pytest.mark.parametrize("pack_file", PACKS)
def test_a_clean_commit_is_run_from_its_own_exported_tree_against_the_bound_pack_and_lands(
    env, made, pack_file, monkeypatch
):
    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    newest = made["commit"]()
    done = self_update.apply(made["plugin"], restart=False)
    assert done["changed"] is True and _head(made) == newest
    assert done["preflight"] == {"ran": True, "checks": ["pack check"], "effective_changes": [], "notes": []}
    [folder] = made["folders"]
    assert not os.path.exists(folder), "the exported tree is removed"
    words, pack, tree = made["log"]()[0]
    assert words == "pack check" and pack == os.path.realpath(pack_file)
    assert tree == os.path.realpath(os.path.join(folder, "tree")) != os.path.realpath(made["plugin"]), (
        "the candidate's own code answered"
    )
    assert [line[0] for line in made["log"]()] == [
        "pack check",
        "pack effective --json",
    ]  # neither side prints effective values


def test_nothing_is_exported_when_the_checkout_would_not_move(env, made):
    done = self_update.apply(made["plugin"], restart=False)
    assert done["changed"] is False and done["preflight"] == {} and made["folders"] == [] and made["log"]() == []


def test_a_checkout_off_its_repositorys_line_is_refused_before_any_pre_flight(env, made):
    made["commit"]()
    open(os.path.join(made["plugin"], "local.txt"), "w", encoding="utf-8").write("here\n")
    git(made["plugin"], "add", "local.txt")
    git(made["plugin"], "commit", "-q", "-m", "a local commit")
    with pytest.raises(CockpitError, match="not a fast-forward"):
        self_update.apply(made["plugin"], restart=False)
    assert made["folders"] == [] and made["log"]() == []


def test_the_same_effective_values_on_both_sides_land(env, made):
    values = json.dumps({"hours": {"start": 9}, "capacity": {"dev": 2}})
    made["commit"]("prints effective values", {"EFFECTIVE.json": values})
    assert self_update.apply(made["plugin"], restart=False)["preflight"]["checks"] == [
        "pack check"
    ]  # the installed kernel cannot yet
    made["commit"]("another")
    done = self_update.apply(made["plugin"], restart=False)
    assert done["changed"] is True and done["preflight"] == {
        "ran": True,
        "checks": ["pack check", "pack effective"],
        "effective_changes": [],
        "notes": [],
    }
    trees = {line[2] for line in made["log"]() if line[0] == "pack effective --json"}
    assert os.path.realpath(made["plugin"]) in trees and len(trees) == 3, "the installed kernel answered for itself"


def test_the_first_commit_that_prints_effective_values_lands_with_a_note(env, made, capsys):
    from cockpitlib.cli import main

    made["commit"]("prints effective values", {"EFFECTIVE.json": "{}"})
    assert main(["update", "apply", "--no-restart"]) == 0
    printed = capsys.readouterr()
    [note] = json.loads(printed.out)["preflight"]["notes"]
    assert "the installed kernel does not" in note and printed.err.startswith(f"# {note}\n# after the update, run:\n")


def test_a_commit_that_no_longer_prints_effective_values_is_checked_by_its_pack_check_alone(env, made):
    made["commit"]("prints effective values", {"EFFECTIVE.json": "{}"})
    self_update.apply(made["plugin"], restart=False)
    made["commit"]("prints them no more", {"EFFECTIVE.json": None})
    assert self_update.apply(made["plugin"], restart=False)["preflight"] == {
        "ran": True,
        "checks": ["pack check"],
        "effective_changes": [],
        "notes": [],
    }


def test_a_changed_effective_value_the_commit_does_not_declare_is_refused(env, made):
    made["commit"](
        "prints effective values",
        {"EFFECTIVE.json": json.dumps({"hours": {"start": 9, "end": 17}, "capacity": {"dev": 2}})},
    )
    self_update.apply(made["plugin"], restart=False)
    here = _head(made)
    made["commit"](
        "moves a default",
        {"EFFECTIVE.json": json.dumps({"hours": {"start": 8, "end": 17}, "capacity": {"dev": 2}, "awake": True})},
    )
    with pytest.raises(CockpitError) as refused:
        self_update.apply(made["plugin"], restart=False)
    assert "changes what the live pack means without declaring it (awake, hours.start)" in str(refused.value)
    assert "effective_changes in UPDATE-CHANGES.json" in str(refused.value)
    assert _head(made) == here and not os.path.exists(made["folders"][-1])
    # declaring one of the two is not enough; a file that is not the declared shape declares nothing
    for text in (
        json.dumps({"effective_changes": ["awake"]}),
        "[1, 2]",
        "not json",
        json.dumps({"effective_changes": "hours"}),
    ):
        made["commit"]("declares too little", {"UPDATE-CHANGES.json": text})
        with pytest.raises(CockpitError, match="without declaring it"):
            self_update.apply(made["plugin"], restart=False)
        assert _head(made) == here


def test_a_changed_effective_value_the_commit_declares_lands_and_is_printed(env, made, capsys):
    from cockpitlib.cli import main

    made["commit"](
        "prints effective values", {"EFFECTIVE.json": json.dumps({"hours": {"start": 9, "end": 17}, "old": 1})}
    )
    self_update.apply(made["plugin"], restart=False)
    newest = made["commit"](
        "moves defaults on purpose",
        {
            "EFFECTIVE.json": json.dumps({"hours": {"start": 8, "end": 18}, "awake": True}),
            "UPDATE-CHANGES.json": json.dumps({"effective_changes": ["hours", "awake", "old", "", 7]}),
        },
    )  # a key covers what is under it
    capsys.readouterr()
    assert main(["update", "apply", "--no-restart"]) == 0 and _head(made) == newest
    printed = capsys.readouterr()
    done = json.loads(printed.out)["preflight"]
    assert done["effective_changes"] == ["awake", "hours.end", "hours.start", "old"] and done["checks"] == [
        "pack check",
        "pack effective",
    ]
    assert (
        "# pre-flight: the update changes these pack values, as it declares: awake, hours.end, hours.start, old\n"
        in printed.err
    )


def test_a_long_list_of_undeclared_changes_is_cut_with_its_count(env, made):
    made["commit"]("prints effective values", {"EFFECTIVE.json": "{}"})
    self_update.apply(made["plugin"], restart=False)
    made["commit"]("moves ten", {"EFFECTIVE.json": json.dumps({f"k{n}": n for n in range(10)})})
    with pytest.raises(CockpitError, match=r"\(k0, k1, k2, k3, k4, k5, k6, k7 and 2 more\)"):
        self_update.apply(made["plugin"], restart=False)


@pytest.mark.parametrize(
    "answer, said",
    [
        ("FAIL the registry is broken", "`pack effective` failed on {short}: FAIL the registry is broken"),
        ("not json", "`pack effective --json` on {short} answered no JSON object"),
        ("[1]", "`pack effective --json` on {short} answered no JSON object"),
    ],
)
def test_effective_values_that_cannot_be_read_refuse_the_update(env, made, answer, said):
    made["commit"]("prints effective values", {"EFFECTIVE.json": "{}"})
    self_update.apply(made["plugin"], restart=False)
    here = _head(made)
    newest = made["commit"]("prints them badly", {"EFFECTIVE.json": answer})
    with pytest.raises(CockpitError) as refused:
        self_update.apply(made["plugin"], restart=False)
    assert str(refused.value) == "update refused: " + said.format(short=newest[:7]) and _head(made) == here


def test_a_refused_commit_that_also_changes_the_dependencies_says_what_may_be_missing(env, made):
    made["commit"](
        "needs a new library",
        {
            "PACK-CHECK-FAILS": "ModuleNotFoundError: No module named 'shiny'\n",
            "pyproject.toml": "[project]\nname = 'x'\ndependencies = ['shiny']\n",
        },
    )
    with pytest.raises(
        CockpitError, match=r"No module named 'shiny' \(pyproject.toml changes with it: .*apply again\)$"
    ):
        self_update.apply(made["plugin"], restart=False)
    assert _head(made) == made["first"]


def test_a_pre_flight_that_does_not_answer_in_time_refuses_the_update(env, made, monkeypatch):
    made["commit"]()
    real = subprocess.run

    def run(argv, *args, **kwargs):
        if argv[-2:] == ["pack", "check"]:
            raise subprocess.TimeoutExpired(argv, kwargs.get("timeout"))
        return real(argv, *args, **kwargs)

    monkeypatch.setattr(self_update.subprocess, "run", run)
    with pytest.raises(CockpitError, match=f"stops every lane: no answer within {self_update.PREFLIGHT_TIMEOUT} s"):
        self_update.apply(made["plugin"], restart=False)
    assert _head(made) == made["first"] and not os.path.exists(made["folders"][0])


def test_a_tree_that_cannot_be_unpacked_refuses_the_update(env, made, monkeypatch):
    newest = made["commit"]()
    real = subprocess.run

    def run(argv, *args, **kwargs):
        if argv[0] == "tar":
            return subprocess.CompletedProcess(argv, 1, "tar: damaged archive\n", "")
        return real(argv, *args, **kwargs)

    monkeypatch.setattr(self_update.subprocess, "run", run)
    with pytest.raises(CockpitError, match=f"the tree of {newest[:7]} could not be unpacked: tar: damaged archive"):
        self_update.apply(made["plugin"], restart=False)
    assert _head(made) == made["first"] and not os.path.exists(made["folders"][0])


def test_an_installation_with_no_workspace_updates_with_a_note_and_no_pre_flight(made, capsys):
    from cockpitlib.cli import main

    newest = made["commit"]()
    assert self_update.status(made["plugin"])["remote"] == {}  # no workspace: no record to read, and no failure
    assert main(["update", "apply", "--no-restart"]) == 0 and _head(made) == newest
    printed = capsys.readouterr()
    assert json.loads(printed.out)["preflight"]["ran"] is False and made["folders"] == [] and made["log"]() == []
    assert printed.err.startswith("# pre-flight skipped: no workspace is bound")


def test_the_candidate_runs_on_the_plugins_own_interpreter_when_it_has_one(tmp_path):
    import sys

    assert self_update._python(str(tmp_path)) == sys.executable
    venv = tmp_path / ".venv" / "bin"
    venv.mkdir(parents=True)
    (venv / "python").write_text("", encoding="utf-8")
    assert self_update._python(str(tmp_path)) == str(venv / "python")


def test_a_failed_command_is_quoted_by_its_last_words():
    done = subprocess.CompletedProcess
    assert (
        self_update._last_line(done([], 2, "pack ok\n", "Traceback\n  File x\nPackError: bad key\n\n"))
        == "PackError: bad key"
    )
    assert self_update._last_line(done([], 1, "first\nlast on stdout\n", "")) == "last on stdout"
    assert self_update._last_line(done([], 3, "", None)) == "exit 3"


def test_nested_values_compare_key_by_key():
    assert self_update._flat({"a": {"b": 1, "c": {"d": [1, 2]}}, "e": {}, "f": None}) == {
        "a.b": 1,
        "a.c.d": [1, 2],
        "e": {},
        "f": None,
    }
    assert self_update._flat({}) == {}  # a description with no values has no keys


@pytest.mark.parametrize("pack_file", PACKS)
def test_the_kernels_own_exported_tree_checks_a_pack_with_no_environment_of_its_own(pack_file, tmp_path):
    """The real launcher, not the stand-in: a tree exported from this repository has no venv beside it and still answers."""
    import sys

    if not os.path.exists(os.path.join(ROOT, ".git")):
        pytest.skip("not a git checkout")
    tree = self_update._export(ROOT, git(ROOT, "rev-parse", "HEAD"), str(tmp_path))
    assert os.path.isfile(os.path.join(tree, "bin", "cockpit")) and not os.path.exists(os.path.join(tree, ".venv"))
    # the copy is not the code under test: a coverage run must not measure its files as a second, barely-run kernel
    env = {
        key: value for key, value in os.environ.items() if not key.startswith(("COCKPIT_", "COVERAGE_", "COV_CORE_"))
    }
    env.update(COCKPIT_PACK=pack_file, COCKPIT_HERMES_HOME=str(tmp_path / "home"), PYTHONDONTWRITEBYTECODE="1")
    done = self_update._cockpit(tree, sys.executable, env, "pack", "check")
    assert done.returncode == 0 and done.stdout.startswith("pack ok "), done.stderr
    absent = self_update._cockpit(tree, sys.executable, env, "pack", "no-such-word")
    assert absent.returncode == 2 and "Examples:" in absent.stderr, "a kernel without a sub-command refuses it as usage"
