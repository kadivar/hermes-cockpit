# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""A pull request is not offered while the push of its own branch is still to go out."""

from cockpitlib import sequence


def _pr(**over):
    payload = {"repo": "api", "head": "work/TASK-9", "branch": "work/TASK-9", "base": "main", "after": ""}
    payload.update(over)
    return {"id": "TASK-9/002-open-pr", "ticket": "TASK-9", "type": "open-pr", "status": "endorsed", "payload": payload}


def _push(status="pending", repo="api", branch="work/TASK-9", number=3, **more):
    return {
        "id": f"TASK-9/00{number}-push-branch",
        "ticket": "TASK-9",
        "type": "push-branch",
        "status": status,
        "payload": {"repo": repo, "branch": branch, **more},
    }


def _world(monkeypatch, rows):
    monkeypatch.setattr(sequence, "all_intents", lambda ticket=None: rows)


def test_a_pr_waits_for_the_open_push_of_its_branch_however_they_were_linked(monkeypatch):
    pr = _pr()
    _world(monkeypatch, [pr, _push("pending")])
    assert sequence._own_push(pr) == {"id": "TASK-9/003-push-branch", "type": "push-branch", "status": "pending"}
    assert sequence.waits(pr, {})["id"] == "TASK-9/003-push-branch"
    assert "waits for TASK-9/003-push-branch" in sequence.said(pr, sequence.waits(pr, {}))
    _world(monkeypatch, [pr, _push("endorsed", branch="local-name", publish_as="work/TASK-9")])
    assert sequence._own_push(pr)["status"] == "endorsed"  # the branch it publishes as is the one the PR names


def test_a_pr_whose_push_is_out_paired_or_of_another_branch_does_not_wait(monkeypatch):
    pr = _pr()
    for rows in (
        [pr, _push("published")],
        [pr, _push("dropped")],
        [pr, _push("pending", repo="web")],
        [pr, _push("pending", branch="work/TASK-8")],
        [pr],
    ):
        _world(monkeypatch, rows)
        assert sequence._own_push(pr) == {}
    _world(monkeypatch, [_push("pending")])
    assert sequence._own_push(_pr(after="TASK-9/003-push-branch")) == {}  # a pair: its Publish sends the push first
    assert sequence._own_push(_pr(head="", branch="", publish_as="")) == {} and sequence._own_push(_pr(repo="")) == {}
    assert (
        sequence._own_push(
            {"type": "pr-comment", "ticket": "TASK-9", "payload": {"repo": "api", "head": "work/TASK-9"}}
        )
        == {}
    )
