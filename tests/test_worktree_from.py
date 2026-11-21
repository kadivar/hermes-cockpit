# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""`cockpit worktree add <ticket> <repo> --from <ref>` on a checkout that is already there.

It used to return the folder as it stood and say nothing: a reviewer told to refresh to the PR head (the re-review
card's first line; a reviewer reusing one batch folder per pull request) kept reading the old head. Now the checkout is
fetched and, when it is clean and holds no commit of its own, moved to the ref; a checkout with changes or unpushed
commits is left alone and the command says so. Without --from nothing changed."""

import os
import subprocess

import pytest

from cockpitlib.errors import CockpitError
from cockpitlib.ops import worktree_add
from cockpitlib.pack import load

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PACKS = (os.path.join(ROOT, "packs", "acme", "pack.yaml"), os.path.join(ROOT, "packs", "bravo", "pack.yaml"))


def _git(folder, *args) -> str:
    return subprocess.run(["git", "-C", str(folder), *args], check=True, capture_output=True, text=True).stdout.strip()


def _author_pushes(env, name, branch, file) -> str:
    """Someone else pushes a commit to the PR's branch on the forge."""
    theirs = env["root"] / "theirs" / name
    if not theirs.is_dir():
        subprocess.run(
            ["git", "clone", "-q", str(env["root"] / "remotes" / f"{name}.git"), str(theirs)],
            check=True,
            capture_output=True,
        )
        _git(theirs, "config", "user.email", "author@example.test")
        _git(theirs, "config", "user.name", "Author")
    _git(theirs, "checkout", "-q", "-B", branch)
    (theirs / file).write_text(file + "\n", encoding="utf-8")
    _git(theirs, "add", ".")
    _git(theirs, "commit", "-q", "-m", file)
    _git(theirs, "push", "-q", "origin", branch)
    return _git(theirs, "rev-parse", "HEAD")


def _setup(env, monkeypatch, pack_file, number):
    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    monkeypatch.delenv("COCKPIT_LANE", raising=False)
    pack = load(pack_file)
    name = pack["repos"]["repos"][0]["name"]
    ticket = f"{pack['tracker']['project']}-{number}"
    source = env["root"] / "repos" / name
    first = _author_pushes(env, name, "feature/pr", "one.txt")
    _git(source, "fetch", "-q", "origin")
    made = worktree_add(pack, ticket, name, branch_from="origin/feature/pr")
    folder = env["root"] / "wt" / ticket / name
    assert made == [str(folder)] and _git(folder, "rev-parse", "HEAD") == first
    return pack, name, ticket, folder, first


@pytest.mark.parametrize("pack_file", PACKS)
def test_from_moves_a_clean_checkout_to_the_new_head(env, pack_file, monkeypatch):
    pack, name, ticket, folder, first = _setup(env, monkeypatch, pack_file, 3301)
    branch = _git(folder, "branch", "--show-current")
    assert branch == f"{pack['branch_prefix']}/{ticket}"
    assert (
        worktree_add(pack, ticket, name) == [str(folder)] and _git(folder, "rev-parse", "HEAD") == first
    )  # no --from: as it was
    second = _author_pushes(env, name, "feature/pr", "two.txt")
    assert worktree_add(pack, ticket, name, branch_from="origin/feature/pr") == [str(folder)]  # fetched, then moved
    assert _git(folder, "rev-parse", "HEAD") == second and _git(folder, "branch", "--show-current") == branch
    assert worktree_add(pack, ticket, name, branch_from="origin/feature/pr") == [
        str(folder)
    ]  # already there: nothing to do
    assert _git(folder, "rev-parse", "HEAD") == second
    (folder / "scratch.txt").write_text(
        "untracked\n", encoding="utf-8"
    )  # a file git does not track is no change of ours
    third = _author_pushes(env, name, "feature/pr", "three.txt")
    worktree_add(pack, ticket, name, branch_from="origin/feature/pr")
    assert _git(folder, "rev-parse", "HEAD") == third and (folder / "scratch.txt").is_file()
    with pytest.raises(CockpitError, match="no ref origin/nowhere"):
        worktree_add(pack, ticket, name, branch_from="origin/nowhere")
    assert _git(folder, "rev-parse", "HEAD") == third


@pytest.mark.parametrize("pack_file", PACKS)
def test_from_refuses_a_checkout_with_work_of_its_own_and_says_where_it_stands(env, pack_file, monkeypatch):
    pack, name, ticket, folder, first = _setup(env, monkeypatch, pack_file, 3302)
    _author_pushes(env, name, "feature/pr", "two.txt")
    (folder / "one.txt").write_text("changed here\n", encoding="utf-8")
    with pytest.raises(CockpitError, match=rf"{first[:10]}.*1 changed file.*--from origin/feature/pr was not applied"):
        worktree_add(pack, ticket, name, branch_from="origin/feature/pr")
    assert (
        _git(folder, "rev-parse", "HEAD") == first
        and (folder / "one.txt").read_text(encoding="utf-8") == "changed here\n"
    )
    _git(folder, "-c", "user.email=dev@example.test", "-c", "user.name=Dev", "commit", "-q", "-am", "mine")
    mine = _git(folder, "rev-parse", "HEAD")
    with pytest.raises(
        CockpitError, match=rf"{mine[:10]}.*1 unpushed commit.*--from origin/feature/pr was not applied"
    ):
        worktree_add(pack, ticket, name, branch_from="origin/feature/pr")
    assert _git(folder, "rev-parse", "HEAD") == mine


def test_a_checkout_on_no_branch_stays_on_no_branch(env, monkeypatch):
    pack, name, ticket, folder, first = _setup(env, monkeypatch, PACKS[1], 3303)
    _git(folder, "checkout", "-q", "--detach")
    second = _author_pushes(env, name, "feature/pr", "two.txt")
    worktree_add(pack, ticket, name, branch_from="origin/feature/pr")
    assert _git(folder, "rev-parse", "HEAD") == second and _git(folder, "branch", "--show-current") == ""
