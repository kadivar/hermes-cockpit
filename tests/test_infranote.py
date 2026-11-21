# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""A lane may not write an infrastructure path: it leaves a patch in a note, and the human applies that one diff."""

import os
import subprocess

import pytest

from cockpitlib import infra_note
from cockpitlib.errors import CockpitError


def _git(folder, *args):
    return subprocess.run(["git", "-C", str(folder), *args], capture_output=True, text=True, check=True).stdout.strip()


@pytest.fixture
def note(tmp_path, monkeypatch):
    repo = tmp_path / "wt" / "api"
    repo.mkdir(parents=True)
    _git(repo, "init", "-q", "-b", "bump/x")
    _git(repo, "config", "user.email", "me@example.test")
    _git(repo, "config", "user.name", "Me")
    (repo / ".ci").mkdir()
    (repo / ".ci" / "run.yml").write_text("node: 18\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "base")
    patch = tmp_path / "ws" / "records" / "qa" / "BATCH-1" / "node.patch"
    patch.parent.mkdir(parents=True)
    patch.write_text("--- a/.ci/run.yml\n+++ b/.ci/run.yml\n@@ -1 +1 @@\n-node: 18\n+node: 22\n", encoding="utf-8")
    intent = {
        "id": "BATCH-1/009-infra-note",
        "ticket": "BATCH-1",
        "type": "infra-note",
        "status": "pending",
        "created_by": "reviewer-2",
        "card_id": "c-9",
        "agent_summary": "Run the e2e job on Node 22",
        "payload": {"repo": "api", "branch": "bump/x", "patch_file": str(patch), "waits_for": "BATCH-1/002-pr-edit"},
    }
    made = []
    from cockpitlib import outbox, paths, worktree

    monkeypatch.setattr(infra_note, "load", lambda _id: intent)
    monkeypatch.setattr(infra_note, "save", lambda _row: None)
    monkeypatch.setattr(infra_note, "log", lambda _line: None)
    monkeypatch.setattr(paths, "workspace", lambda: str(tmp_path / "ws"))
    monkeypatch.setattr(worktree, "_checkout", lambda _ticket, _repo, _pack=None: str(repo))
    monkeypatch.setattr(
        outbox,
        "create",
        lambda _pack, ticket, kind, card, summary, payload, created_by="human", **_more: (
            made.append((ticket, kind, card, payload, created_by)) or {"id": "BATCH-1/010-push-branch"}
        ),
    )
    return {"repo": repo, "intent": intent, "made": made, "patch": patch}


def test_the_human_applies_the_patch_as_their_commit_and_its_push_is_filed(note):
    done = infra_note.apply({}, "BATCH-1/009-infra-note")
    assert done["files"] == [".ci/run.yml"] and done["push"] == "BATCH-1/010-push-branch"
    assert (note["repo"] / ".ci" / "run.yml").read_text(encoding="utf-8") == "node: 22\n"
    assert _git(note["repo"], "log", "-1", "--format=%an|%s") == "Me|Run the e2e job on Node 22"
    assert "reviewer-2 wrote the patch" in _git(note["repo"], "log", "-1", "--format=%b")
    assert note["made"] == [
        (
            "BATCH-1",
            "push-branch",
            "c-9",
            {"repo": "api", "branch": "bump/x", "waits_for": "BATCH-1/002-pr-edit"},
            "human",
        )
    ]
    assert (
        note["intent"]["status"] == "published-manually" and note["intent"]["history"][-1]["commit"] == done["commit"]
    )


def test_a_lane_never_applies_it_and_a_note_without_a_patch_is_not_applied(note, monkeypatch):
    monkeypatch.setenv("COCKPIT_LANE", "worker-1")
    with pytest.raises(CockpitError, match="stay with the human"):
        infra_note.apply({}, "BATCH-1/009-infra-note")
    monkeypatch.delenv("COCKPIT_LANE")
    note["intent"]["payload"].pop("patch_file")
    with pytest.raises(CockpitError, match="carries no patch"):
        infra_note.apply({}, "BATCH-1/009-infra-note")
    assert infra_note.patch_of(note["intent"]) == {}


def test_a_patch_that_does_not_apply_or_a_dirty_checkout_leaves_the_checkout_as_it_was(note):
    head = _git(note["repo"], "rev-parse", "HEAD")
    note["patch"].write_text(
        "--- a/.ci/run.yml\n+++ b/.ci/run.yml\n@@ -1 +1 @@\n-node: 16\n+node: 22\n", encoding="utf-8"
    )
    with pytest.raises(CockpitError, match="does not apply"):
        infra_note.apply({}, "BATCH-1/009-infra-note")
    assert (
        _git(note["repo"], "rev-parse", "HEAD") == head
        and _git(note["repo"], "status", "--porcelain") == ""
        and note["made"] == []
    )
    (note["repo"] / "left.txt").write_text("someone's work\n", encoding="utf-8")
    with pytest.raises(CockpitError, match="not committed"):
        infra_note.apply({}, "BATCH-1/009-infra-note")
    assert os.path.isfile(note["repo"] / "left.txt")
    note["intent"]["status"] = "dropped"
    os.remove(note["repo"] / "left.txt")
    with pytest.raises(CockpitError, match="only an open note"):
        infra_note.apply({}, "BATCH-1/009-infra-note")


def test_a_send_back_that_needs_code_goes_to_a_worker_with_its_own_instruction():
    from cockpitlib import gate

    said = gate.CODE_BODY.format(
        id="BATCH-1/054-pr-review-submit",
        type="pr-review-submit",
        instruction="add the workflow fix",
        evidence="",
        writer="reviewer-2",
    )
    assert (
        "You did not write BATCH-1/054-pr-review-submit" in said
        and "infra-note" in said
        and "reviewer-2 then redoes" in said
    )
