# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""`cockpit update apply --to <commit>`: the checkout fast-forwards to a commit between itself and its repository's head,
through the same pre-flight; a commit off that line, behind the checkout, or unknown is refused with the reason."""

import json
import os

import pytest

from cockpitlib import self_update
from cockpitlib.cli import main
from cockpitlib.errors import CockpitError


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


@pytest.fixture
def made(tmp_path, monkeypatch):
    found = install(tmp_path)
    monkeypatch.setenv("COCKPIT_PLUGIN_ROOT", found["plugin"])
    monkeypatch.setenv("PREFLIGHT_LOG", str(tmp_path / "preflight.log"))
    monkeypatch.setattr(self_update, "_record_hermes_revision", lambda name, revision: "")
    return {
        **found,
        "log": lambda: (
            (tmp_path / "preflight.log").read_text(encoding="utf-8").splitlines()
            if (tmp_path / "preflight.log").exists()
            else []
        ),
    }


def _head(made) -> str:
    return git(made["plugin"], "rev-parse", "HEAD")


def test_the_checkout_stops_at_the_commit_named_and_knows_how_far_behind_it_stays(env, made, capsys):
    second, third, fourth = made["commit"]("second"), made["commit"]("third"), made["commit"]("fourth")
    assert main(["update", "apply", "--to", third[:10], "--no-restart"]) == 0
    done = json.loads(capsys.readouterr().out)
    assert (
        _head(made) == third
        and done["to"] == third[:7]
        and [line.split(" ", 1)[1] for line in done["commits"]] == ["third", "second"]
    )
    assert done["preflight"]["ran"] is True and made["log"]()[0].startswith("pack check\t")
    seen = self_update.status(made["plugin"])
    assert (
        seen["remote"]["behind"] == 1
        and seen["remote"]["sha"] == fourth
        and "1 commit(s) behind" in self_update.inbox_row()["reason"]
    )
    assert git(made["plugin"], "rev-parse", "--abbrev-ref", "HEAD") == "master"
    # the head itself, named: the same as no name, and nothing is left behind
    assert self_update.apply(made["plugin"], restart=False, to=fourth)["changed"] is True and _head(made) == fourth
    assert self_update.status(made["plugin"])["remote"]["behind"] == 0 and self_update.inbox_row() == {}
    # the installed commit, named: nothing moves and nothing is checked
    before = len(made["log"]())
    again = self_update.apply(made["plugin"], restart=False, to=fourth)
    assert again["changed"] is False and again["preflight"] == {} and len(made["log"]()) == before
    assert second != third


def test_a_named_commit_goes_through_the_same_pre_flight(env, made):
    made["commit"]("fine")
    bad = made["commit"]("breaks the pack", {"PACK-CHECK-FAILS": "PackError: bad\n"})
    with pytest.raises(CockpitError, match="update refused: the live pack .* stops every lane: PackError: bad"):
        self_update.apply(made["plugin"], restart=False, to=bad)
    assert _head(made) == made["first"]


def test_a_named_commit_off_the_repositorys_line_or_behind_the_checkout_is_refused_with_the_reason(env, made):
    second = made["commit"]("second")
    third = made["commit"]("third")
    # a commit only this checkout has
    git(made["plugin"], "checkout", "-q", "-b", "side")
    open(os.path.join(made["plugin"], "side.txt"), "w", encoding="utf-8").write("x\n")
    git(made["plugin"], "add", "side.txt")
    git(made["plugin"], "commit", "-q", "-m", "side")
    side = _head(made)
    git(made["plugin"], "checkout", "-q", "master")
    git(made["plugin"], "branch", "-q", "-D", "side")
    with pytest.raises(CockpitError, match=f"--to {side}: {side[:7]} is not on origin/master"):
        self_update.apply(made["plugin"], restart=False, to=side)
    # a commit behind the installed one
    self_update.apply(made["plugin"], restart=False, to=third)
    with pytest.raises(
        CockpitError,
        match=f"--to {second}: {second[:7]} is not ahead of the installed {third[:7]}: `update rollback --to` goes back",
    ):
        self_update.apply(made["plugin"], restart=False, to=second)
    # a name that is no commit, and one git would read as an option
    for name in ("no-such-commit", "--upload-pack=x", "-n"):
        with pytest.raises(CockpitError, match="is not a commit of this checkout"):
            self_update.apply(made["plugin"], restart=False, to=name)
    assert _head(made) == third


def test_the_command_refuses_a_to_without_a_commit_twice_or_on_another_verb(env, made, capsys):
    for words in (
        ["update", "apply", "--to"],
        ["update", "apply", "--to", " "],
        ["update", "apply", "--to", "a", "--to", "b"],
        ["update", "check", "--to", "a"],
        ["update", "--to", "a"],
    ):
        assert main(words) == 2, words
        assert "cockpit update apply [--to <commit>]" in capsys.readouterr().err
    assert _head(made) == made["first"]
