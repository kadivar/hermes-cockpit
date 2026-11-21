# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""An amend that asks to pair a staged intent says why it is not taken, instead of answering "amended"."""

from cockpitlib import outbox


def _intent(monkeypatch, waits_for=""):
    monkeypatch.setattr(outbox, "load", lambda iid: {"id": iid, "payload": {"waits_for": waits_for, "after": ""}})


def test_pairing_a_stage_is_refused_with_the_way_to_do_it(monkeypatch):
    _intent(monkeypatch, "TASK-9/002-open-pr")
    said = outbox.staged_pair_refusal("TASK-9/004-open-pr", {"after": "TASK-9/003-push-branch"})
    assert (
        "is a stage: it waits for TASK-9/002-open-pr" in said
        and "--waits-for '' --after TASK-9/003-push-branch" in said
    )
    assert "nothing to change" not in said
    _intent(monkeypatch, "TASK-9/003-push-branch")
    assert "That is the order asked for: nothing to change." in outbox.staged_pair_refusal(
        "TASK-9/004-open-pr", {"after": "TASK-9/003-push-branch"}
    )


def test_an_amend_without_after_or_one_that_leaves_the_stage_is_taken(monkeypatch):
    _intent(monkeypatch, "TASK-9/002-open-pr")
    assert outbox.staged_pair_refusal("TASK-9/004-open-pr", {"body_file": "b.md"}) == ""
    assert outbox.staged_pair_refusal("TASK-9/004-open-pr", {"after": "TASK-9/003-push-branch", "waits_for": ""}) == ""
    _intent(monkeypatch, "")
    assert outbox.staged_pair_refusal("TASK-9/004-open-pr", {"after": "TASK-9/003-push-branch"}) == ""
    assert "waits for TASK-9/001-tracker-create" in outbox.staged_pair_refusal(
        "TASK-9/004-open-pr", {"after": "x", "waits_for": "TASK-9/001-tracker-create"}
    )

    def gone(_iid):
        raise FileNotFoundError

    monkeypatch.setattr(outbox, "load", gone)
    assert (
        outbox.staged_pair_refusal("TASK-9/404-open-pr", {"after": "x"}) == ""
    )  # the amend itself says it is not there
