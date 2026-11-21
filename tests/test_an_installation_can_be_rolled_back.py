# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""`cockpit update rollback [--to <commit>]`: the checkout goes back to the commit its last update came from, or to a named
commit behind it, never below the floor, never with local edits, and only to code the live pack loads under; what follows
an update follows it; and the next check says that what it counts as ahead was rolled back."""

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
    recorded, launched = [], []
    monkeypatch.setattr(
        self_update, "_record_hermes_revision", lambda name, revision: recorded.append((name, revision)) or ""
    )
    monkeypatch.setattr(self_update, "_spawn", lambda argv, wait=0.0: launched.append(list(argv)) or "")
    monkeypatch.setattr(self_update.shutil, "which", lambda name: "/usr/bin/hermes" if name == "hermes" else None)
    return {
        **found,
        "recorded": recorded,
        "launched": launched,
        "log": lambda: (
            [line.split("\t")[0] for line in (tmp_path / "preflight.log").read_text(encoding="utf-8").splitlines()]
            if (tmp_path / "preflight.log").exists()
            else []
        ),
    }


def _head(made) -> str:
    return git(made["plugin"], "rev-parse", "HEAD")


def test_a_rollback_returns_to_the_commit_the_last_update_came_from_and_the_next_check_says_so(env, made):
    plugin = made["plugin"]
    made["commit"]("second")
    newest = made["commit"]("third", {"desktop/plugin.js": "export const v = 3\n"})
    self_update.apply(plugin, restart=False, now=100.0)
    assert (
        self_update.status(plugin)["remote"]["previous"] == made["first"]
        and "rolled_back_from" not in self_update.status(plugin)["remote"]
    )
    os.makedirs(os.path.join(plugin, "kernel", "cockpitlib", "__pycache__"))
    made["recorded"].clear()
    seen_before = len(made["log"]())

    done = self_update.rollback(plugin, restart=True, now=200.0)

    assert (
        _head(made) == made["first"]
        and done["changed"] is True
        and done["from"] == newest[:7]
        and done["to"] == made["first"][:7]
    )
    assert done["out"].startswith(
        f"rolled back {newest[:7]} → {made['first'][:7]}: 2 commit(s) left; gateway restart requested"
    )
    assert [line.split(" ", 1)[1] for line in done["commits"]] == ["third", "second"]
    assert (
        git(plugin, "rev-parse", "--abbrev-ref", "HEAD") == "master" and self_update.remote_branch(plugin) == "master"
    )
    assert (
        not git(plugin, "status", "--porcelain")
        and "x = 0" in open(os.path.join(plugin, "kernel", "cockpitlib", "a.py")).read()
    )
    # what follows an update follows a rollback: bytecode, the Desktop, Hermes's record, the gateway, the line left to the human
    assert done["bytecode_cleared"] == 1 and not os.path.isdir(
        os.path.join(plugin, "kernel", "cockpitlib", "__pycache__")
    )
    assert done["desktop"] is True and made["recorded"] == [(os.path.basename(plugin), made["first"])]
    assert made["launched"] == [["/usr/bin/hermes", "gateway", "restart"]] and done["restart"] == "requested"
    assert " setup --rerender && " in done["next"]["line"] and done["next"]["line"].count(" doctor") == 1
    # the older code met the live pack first: its own pack check, and no comparison of values
    assert made["log"]()[seen_before:] == ["pack check"] and done["preflight"]["checks"] == ["pack check"]
    # the record: what was left, no second step back, and how far behind the checkout now is
    remote = self_update.status(plugin)["remote"]
    assert (
        remote["rolled_back_from"] == newest
        and "previous" not in remote
        and remote["behind"] == 2
        and remote["sha"] == newest
    )
    row = self_update.inbox_row()
    assert (
        f"2 commit(s) behind its repository ({newest[:7]}), after a rollback from {newest[:7]} (an update brings those commits back)"
        in row["reason"]
    )
    # a check keeps saying so, for as long as the checkout is behind what it left
    assert (
        self_update.check(plugin, now=300.0)["remote"]["rolled_back_from"] == newest
        and "after a rollback" in self_update.inbox_row()["reason"]
    )
    with pytest.raises(CockpitError, match="nothing to roll back to: .*rollback --to <commit>"):
        self_update.rollback(plugin, restart=False)
    # an update forward again clears it and records where it came from
    self_update.apply(plugin, restart=False, now=400.0)
    remote = self_update.status(plugin)["remote"]
    assert (
        _head(made) == newest
        and remote["previous"] == made["first"]
        and "rolled_back_from" not in remote
        and self_update.inbox_row() == {}
    )


def test_an_apply_that_moves_nothing_keeps_what_the_record_knew(env, made):
    newest = made["commit"]()
    self_update.apply(made["plugin"], restart=False)
    self_update.apply(made["plugin"], restart=False)
    assert self_update.status(made["plugin"])["remote"]["previous"] == made["first"]
    self_update.rollback(made["plugin"], restart=False)
    assert self_update.rollback(made["plugin"], restart=False, to="HEAD")["out"] == f"already at {made['first'][:7]}"
    assert self_update.status(made["plugin"])["remote"]["rolled_back_from"] == newest


def test_a_checkout_brought_forward_by_hand_no_longer_says_it_was_rolled_back(env, made):
    made["commit"]()
    self_update.apply(made["plugin"], restart=False)
    self_update.rollback(made["plugin"], restart=False)
    git(made["plugin"], "merge", "-q", "--ff-only", "origin/master")
    remote = self_update.check(made["plugin"], now=500.0)["remote"]
    assert "rolled_back_from" not in remote and remote["behind"] == 0


def test_a_rollback_to_a_named_commit_goes_only_back_along_the_checkouts_history(env, made):
    plugin = made["plugin"]
    second, third = made["commit"]("second"), made["commit"]("third")
    self_update.apply(plugin, restart=False, to=second)
    with pytest.raises(
        CockpitError, match=f"{third[:7]} is not behind the installed {second[:7]}: a rollback only goes back"
    ):
        self_update.rollback(plugin, restart=False, to=third)
    for name in ("no-such-commit", "--force"):
        with pytest.raises(CockpitError, match="is not a commit of this checkout"):
            self_update.rollback(plugin, restart=False, to=name)
    assert _head(made) == second
    seen = len(made["log"]())
    same = self_update.rollback(plugin, restart=False, to=second)
    assert (
        same["changed"] is False
        and same["preflight"] == {}
        and len(made["log"]()) == seen
        and same["next"] == {"steps": [], "line": ""}
    )
    self_update.apply(plugin, restart=False)
    done = self_update.rollback(
        plugin, restart=False, to=made["first"][:12]
    )  # further back than the last update came from
    assert _head(made) == made["first"] and done["restart"] == "skipped" and len(done["commits"]) == 2


def test_a_checkout_with_local_edits_is_not_rolled_back(env, made):
    made["commit"]()
    self_update.apply(made["plugin"], restart=False)
    here = _head(made)
    open(os.path.join(made["plugin"], "kernel", "cockpitlib", "a.py"), "a", encoding="utf-8").write("# edited here\n")
    with pytest.raises(CockpitError, match="local changes: commit or stash them before rolling back"):
        self_update.rollback(made["plugin"], restart=False)
    assert _head(made) == here


def test_a_folder_that_is_no_checkout_is_not_rolled_back(env, tmp_path):
    with pytest.raises(CockpitError, match="is not a git checkout"):
        self_update.rollback(str(tmp_path))


def test_a_rollback_never_goes_below_the_floor_the_installed_commit_names(env, made):
    plugin = made["plugin"]
    second = made["commit"]("second")
    third = made["commit"](
        "third: nothing older than second reads these records", {"UPDATE-FLOOR": second + "\nwhy: the record format\n"}
    )
    self_update.apply(plugin, restart=False)
    with pytest.raises(
        CockpitError, match=f"rollback refused: {made['first'][:7]} is below the floor {second[:7]} .UPDATE-FLOOR."
    ):
        self_update.rollback(plugin, restart=False)  # the recorded previous commit is below it too
    with pytest.raises(CockpitError, match="below the floor"):
        self_update.rollback(plugin, restart=False, to=made["first"])
    assert _head(made) == third
    assert (
        self_update.rollback(plugin, restart=False, to=second)["changed"] is True and _head(made) == second
    )  # the floor itself is allowed
    # second's own tree names no floor: the file that counts is the installed commit's
    assert self_update.rollback(plugin, restart=False, to=made["first"])["changed"] is True


@pytest.mark.parametrize("text", ["0000000000000000000000000000000000000000\n", "not-a-commit\n", "\n", "", "--all\n"])
def test_a_floor_that_names_no_commit_refuses_every_rollback(env, made, text):
    made["commit"]("a damaged floor", {"UPDATE-FLOOR": text})
    self_update.apply(made["plugin"], restart=False)
    here = _head(made)
    with pytest.raises(CockpitError, match="rollback refused: UPDATE-FLOOR names no commit of this checkout"):
        self_update.rollback(made["plugin"], restart=False)
    assert _head(made) == here


def test_a_floor_file_the_installed_commit_does_not_track_is_no_floor(env, made):
    made["commit"]()
    self_update.apply(made["plugin"], restart=False)
    open(os.path.join(made["plugin"], "UPDATE-FLOOR"), "w", encoding="utf-8").write(
        "not-a-commit\n"
    )  # untracked: not the release's word
    assert self_update.rollback(made["plugin"], restart=False)["changed"] is True and _head(made) == made["first"]


def test_a_rollback_to_code_the_live_pack_does_not_load_under_is_refused(env, made):
    plugin = made["plugin"]
    second = made["commit"]("cannot read this pack", {"PACK-CHECK-FAILS": "PackError: unknown key newer_key\n"})
    third = made["commit"]("can", {"PACK-CHECK-FAILS": None})
    self_update.apply(plugin, restart=False)  # the head loads the pack: the update lands
    assert _head(made) == third
    with pytest.raises(
        CockpitError,
        match=f"does not load under {second[:7]}, and a pack that does not load stops every lane: PackError: unknown key newer_key",
    ):
        self_update.rollback(plugin, restart=False, to=second)
    assert _head(made) == third and "rolled_back_from" not in self_update.status(plugin)["remote"]
    assert self_update.rollback(plugin, restart=False, to=made["first"])["changed"] is True


def test_a_checkout_on_no_branch_is_rolled_back_where_it_stands(env, made):
    made["commit"]()
    self_update.apply(made["plugin"], restart=False)
    git(made["plugin"], "checkout", "-q", "--detach")
    master = git(made["plugin"], "rev-parse", "master")
    assert self_update.rollback(made["plugin"], restart=False, to=made["first"])["changed"] is True
    assert _head(made) == made["first"] and git(made["plugin"], "rev-parse", "--abbrev-ref", "HEAD") == "HEAD"
    assert git(made["plugin"], "rev-parse", "master") == master, "the branch it was not on stays where it was"


def test_a_checkout_git_refuses_to_move_reports_the_refusal(env, made, monkeypatch):
    made["commit"]()
    self_update.apply(made["plugin"], restart=False)
    here = _head(made)
    real = self_update._git

    def refuse_checkout(root, *args, **kwargs):
        if args[0] == "checkout":
            import subprocess

            return subprocess.CompletedProcess(args, 1, "", "error: unable to create file\n")
        return real(root, *args, **kwargs)

    monkeypatch.setattr(self_update, "_git", refuse_checkout)
    with pytest.raises(CockpitError, match="rollback failed: error: unable to create file"):
        self_update.rollback(made["plugin"], restart=False)
    assert _head(made) == here


def test_a_rollback_with_no_origin_branch_to_count_against_records_no_count(env, made):
    made["commit"]()
    self_update.apply(made["plugin"], restart=False)
    git(made["plugin"], "update-ref", "-d", "refs/remotes/origin/master")
    assert self_update.rollback(made["plugin"], restart=False)["changed"] is True
    remote = self_update.status(made["plugin"])["remote"]
    assert remote["behind"] is None and remote["sha"] == "" and self_update.inbox_row() == {}


def test_the_command_rolls_back_and_prints_what_is_left_to_the_human(env, made, capsys):
    made["commit"]()
    assert main(["update", "apply", "--no-restart"]) == 0
    capsys.readouterr()
    assert main(["update", "rollback", "--no-restart"]) == 0
    printed = capsys.readouterr()
    assert (
        json.loads(printed.out)["out"].startswith("rolled back ")
        and _head(made) == made["first"]
        and made["launched"] == []
    )
    assert printed.err.startswith("# after the rollback, run:\n") and " setup --rerender && " in printed.err
    assert main(["update", "rollback"]) == 1 and "nothing to roll back to" in capsys.readouterr().err
    assert (
        main(["update", "rollback", "--to"]) == 2
        and "cockpit update rollback [--to <commit>]" in capsys.readouterr().err
    )
    assert main(["update", "rollback", "--hard"]) == 2 and "unknown option --hard" in capsys.readouterr().err
    assert main(["update", "apply", "--no-restart"]) == 0
    capsys.readouterr()
    assert main(["update", "rollback", "--to", made["first"], "--no-restart"]) == 0 and _head(made) == made["first"]


def test_an_installation_with_no_workspace_rolls_back_to_a_named_commit_with_a_note(made, capsys):
    made["commit"]()
    assert main(["update", "apply", "--no-restart"]) == 0
    capsys.readouterr()
    assert main(["update", "rollback", "--no-restart"]) == 1  # no workspace, no record of where it came from
    assert "nothing to roll back to" in capsys.readouterr().err
    assert main(["update", "rollback", "--to", made["first"], "--no-restart"]) == 0 and _head(made) == made["first"]
    assert capsys.readouterr().err.startswith("# pre-flight skipped: no workspace is bound")
