# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""A pull request stacked on another PR's branch goes back for a rebase when that branch is gone from the remote."""

import pytest

from cockpitlib import gate, git_push
from cockpitlib.errors import CockpitError

PACK = {"base_branch": "rc", "repos": {"repos": [{"name": "api"}]}}


def _rows(base="work/TASK-8", push="held", pr="held"):
    return [
        {
            "id": "TASK-9/001-push-branch",
            "ticket": "TASK-9",
            "type": "push-branch",
            "status": push,
            "payload": {"repo": "api", "branch": "work/TASK-9"},
        },
        {
            "id": "TASK-9/002-open-pr",
            "ticket": "TASK-9",
            "type": "open-pr",
            "status": pr,
            "payload": {"repo": "api", "base": base, "head": "work/TASK-9", "after": "TASK-9/001-push-branch"},
        },
    ]


@pytest.fixture
def world(monkeypatch, tmp_path):
    from cockpitlib import paths

    state = {"rows": _rows(), "remote": set(), "returned": [], "lines": []}
    monkeypatch.setattr(paths, "watch_dir", lambda: str(tmp_path))
    monkeypatch.setattr(gate, "all_intents", lambda ticket=None: state["rows"])
    monkeypatch.setattr(gate, "load", lambda iid: next(row for row in state["rows"] if row["id"] == iid))
    monkeypatch.setattr(gate, "log", state["lines"].append)
    monkeypatch.setattr(git_push, "checkout", lambda pack, ticket, repo: f"/wt/{ticket}/{repo}")
    monkeypatch.setattr(git_push, "remote_tip", lambda folder, branch: "a" * 40 if branch in state["remote"] else "")
    monkeypatch.setattr(git_push, "publish_name", lambda pack, repo, branch: branch)

    def returned(pack, iid, instruction, chain=True, actor="human", **_more):
        state["returned"].append((iid, chain, actor, instruction))

    monkeypatch.setattr(gate, "return_intent", returned)
    return state


def test_the_push_of_a_pr_whose_base_left_the_remote_goes_back_once_with_the_rebase_to_do(world):
    assert gate.base_gone(PACK) == "1"
    iid, chain, actor, instruction = world["returned"][0]
    assert (iid, chain, actor) == ("TASK-9/001-push-branch", False, "cockpit")
    assert (
        "work/TASK-8 is no longer on the remote" in instruction
        and "Rebase work/TASK-9 onto origin/rc" in instruction
        and "base rc" in instruction
    )
    assert world["lines"] == ["BASE-GONE TASK-9/002-open-pr base work/TASK-8 → TASK-9/001-push-branch returned"]
    assert gate.base_gone(PACK) == "0" and len(world["returned"]) == 1  # told once for that base


def test_a_pr_with_no_open_push_before_it_goes_back_itself(world):
    world["rows"] = _rows(push="published")
    assert gate.base_gone(PACK) == "1" and world["returned"][0][0] == "TASK-9/002-open-pr"


def test_a_base_that_is_there_the_repos_own_or_still_to_be_pushed_is_left_alone(world):
    world["remote"] = {"work/TASK-8"}
    assert gate.base_gone(PACK) == "0"
    world["remote"] = set()
    world["rows"] = _rows(base="rc")
    assert gate.base_gone(PACK) == "0"
    world["rows"] = _rows() + [
        {
            "id": "TASK-8/001-push-branch",
            "ticket": "TASK-8",
            "type": "push-branch",
            "status": "endorsed",
            "payload": {"repo": "api", "branch": "work/TASK-8"},
        }
    ]
    assert gate.base_gone(PACK) == "0"  # the branch it stacks on has not gone out yet: not there is not gone
    world["rows"] = _rows(pr="published") + [
        {
            "id": "TASK-9/003-pr-comment",
            "ticket": "TASK-9",
            "type": "pr-comment",
            "status": "held",
            "payload": {"repo": "api"},
        }
    ]
    assert gate.base_gone(PACK) == "0" and world["returned"] == []


def test_a_push_already_back_with_a_lane_waits_and_a_refused_return_is_tried_again(world, monkeypatch):
    world["rows"] = _rows(push="returned")
    assert gate.base_gone(PACK) == "0" and world["returned"] == []
    world["rows"] = _rows()

    def refuse(*_args, **_more):
        raise CockpitError("TASK-9 is halted")

    monkeypatch.setattr(gate, "return_intent", refuse)
    assert gate.base_gone(PACK) == "0" and world["lines"] == ["BASE-GONE? TASK-9/002-open-pr :: TASK-9 is halted"]
    monkeypatch.setattr(gate, "return_intent", lambda pack, iid, instruction, **more: world["returned"].append(iid))
    assert gate.base_gone(PACK) == "1" and world["returned"] == ["TASK-9/001-push-branch"]
