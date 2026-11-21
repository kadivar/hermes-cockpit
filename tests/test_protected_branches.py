# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Two protected branches (an integration branch beside the release branch): what only the human writes, which base a
repo's work starts from, and which PR base a lane may not pick."""

import os
import shutil
import subprocess

import pytest
import yaml

from cockpitlib.errors import CockpitError, PackError
from cockpitlib.gate import _auto_refusal
from cockpitlib.git_push import protected, repo_branch
from cockpitlib.pack import load

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PACKS = (os.path.join(ROOT, "packs", "acme", "pack.yaml"), os.path.join(ROOT, "packs", "bravo", "pack.yaml"))

PACK = {
    "protected_branches": ["rc", "master"],
    "base_branch": "rc",
    "workspace_branch": "master",
    "repos": {"repos": [{"name": "core", "base": "rc"}, {"name": "tools", "base": "master"}, {"name": "bare"}]},
}


def test_each_repo_has_its_own_base_and_shares_the_protected_branches():
    assert repo_branch(PACK, "core") == "rc"
    assert repo_branch(PACK, "tools") == "master"
    assert repo_branch(PACK, "bare") == "rc"  # no base of its own: the pack's
    assert repo_branch(PACK, "unknown") == "rc"
    assert repo_branch({}, "core") == "main"
    assert protected(PACK, "core") == {"rc", "master"}
    assert protected(PACK, "tools") == {"rc", "master"}
    # a pack without the key keeps today's set: the repo's base, the pack's base, the workspace branch
    assert protected({"base_branch": "main", "repos": {"repos": [{"name": "a", "base": "dev"}]}}, "a") == {
        "dev",
        "main",
    }


@pytest.mark.parametrize("branch", ["rc", "master"])
def test_a_push_to_either_protected_branch_waits_for_the_human(branch):
    said = _auto_refusal(PACK, {"id": "i1", "type": "push-branch", "payload": {"repo": "core", "branch": branch}})
    assert said == f"{branch} is a protected branch: only the human pushes it"
    assert (
        _auto_refusal(PACK, {"id": "i2", "type": "push-branch", "payload": {"repo": "core", "branch": "feature/X-1"}})
        == ""
    )
    held = _auto_refusal(
        PACK, {"id": "i3", "type": "push-branch", "payload": {"repo": "core", "branch": "x", "publish_as": branch}}
    )
    assert "protected branch" in held


def test_a_pr_into_another_base_or_a_retarget_waits_for_the_human():
    release = _auto_refusal(
        PACK,
        {
            "id": "p1",
            "type": "open-pr",
            "payload": {"repo": "core", "title": "Release 1.0.0", "head": "rc", "base": "master"},
        },
    )
    assert release == "a PR into master is the human's: core works on rc"
    retarget = _auto_refusal(
        PACK, {"id": "p2", "type": "pr-edit", "payload": {"repo": "core", "number": 7, "base": "master"}}
    )
    assert retarget == "a PR into master is the human's: core works on rc"
    assert (
        _auto_refusal(
            PACK,
            {"id": "p3", "type": "open-pr", "payload": {"repo": "core", "title": "t", "branch": "b", "base": "rc"}},
        )
        == ""
    )
    assert (
        _auto_refusal(PACK, {"id": "p4", "type": "open-pr", "payload": {"repo": "core", "title": "t", "branch": "b"}})
        == ""
    )
    assert (
        _auto_refusal(PACK, {"id": "p5", "type": "pr-edit", "payload": {"repo": "core", "number": 7, "title": "t"}})
        == ""
    )
    # the hub works on master: a PR into master there is ordinary
    assert (
        _auto_refusal(
            PACK,
            {
                "id": "p6",
                "type": "open-pr",
                "payload": {"repo": "tools", "title": "t", "branch": "b", "base": "master"},
            },
        )
        == ""
    )


@pytest.mark.parametrize("pack_file", PACKS)
def test_the_pack_takes_a_list_of_protected_branches(tmp_path, pack_file):
    copied = tmp_path / "packs" / os.path.basename(os.path.dirname(pack_file))
    shutil.copytree(os.path.dirname(pack_file), copied)
    raw = yaml.safe_load((copied / "pack.yaml").read_text(encoding="utf-8"))
    for value, ok in ((["rc", "master"], True), ([], True), ("rc", False), ([""], False), ([3], False)):
        (copied / "pack.yaml").write_text(
            yaml.safe_dump({**raw, "protected_branches": value}, sort_keys=False), encoding="utf-8"
        )
        if ok:
            assert load(str(copied / "pack.yaml"))["protected_branches"] == value
            continue
        with pytest.raises(PackError, match="protected_branches"):
            load(str(copied / "pack.yaml"))
    (copied / "pack.yaml").write_text(
        yaml.safe_dump({k: v for k, v in raw.items() if k != "protected_branches"}, sort_keys=False), encoding="utf-8"
    )
    assert load(str(copied / "pack.yaml"))["protected_branches"] == []


def _git(folder, *args):
    return subprocess.run(["git", "-C", str(folder), *args], check=True, capture_output=True, text=True).stdout.strip()


def test_a_ticket_branch_starts_from_the_fetched_base_and_a_missing_base_is_refused(tmp_path, env):
    from cockpitlib.worktree import add

    origin = tmp_path / "origin.git"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "master", str(origin)], check=True)
    seed = tmp_path / "seed"
    subprocess.run(["git", "clone", "-q", str(origin), str(seed)], check=True, capture_output=True)
    _git(seed, "-c", "user.email=a@b", "-c", "user.name=a", "commit", "-q", "--allow-empty", "-m", "base")
    _git(seed, "push", "-q", "origin", "HEAD:master", "HEAD:rc")
    work = tmp_path / "work"
    subprocess.run(["git", "clone", "-q", str(origin), str(work)], check=True, capture_output=True)
    # the integration branch moves after the clone: the ticket must start from the fetched tip, not the stale local view
    _git(seed, "-c", "user.email=a@b", "-c", "user.name=a", "commit", "-q", "--allow-empty", "-m", "on rc")
    _git(seed, "push", "-q", "origin", "HEAD:rc")
    tip = _git(seed, "rev-parse", "HEAD")
    stale = _git(work, "rev-parse", "HEAD")
    first = add("TASK-1", "work", "work", str(work), base="rc")
    assert first == str(env["root"] / "wt" / "TASK-1" / "work")
    assert (
        _git(first, "rev-parse", "HEAD") == tip != stale
        and _git(first, "rev-parse", "--abbrev-ref", "HEAD") == "work/TASK-1"
    )
    assert _git(work, "rev-parse", "HEAD") == stale  # the repo's own checkout stays where it was
    with pytest.raises(CockpitError, match="no nope to branch from"):
        add("TASK-2", "work", "work", str(work), base="nope")
    # --from wins over the base
    third = add("TASK-3", "work", "work", str(work), base="master", branch_from="work/TASK-1")
    assert _git(third, "rev-parse", "HEAD") == tip
