# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""What is already on a PR at the watch's first read is news when this pipeline opened the PR, and the baseline otherwise."""

from cockpitlib import pr_watch

IDS = ["inline:1", "inline:2", "issue:3"]
NOW = 1_800_000_000.0


def test_a_pr_this_pipeline_opened_has_no_baseline_and_one_it_did_not_open_keeps_what_was_there():
    assert pr_watch.first_baseline({}, IDS, True, NOW - 600, NOW) == set()
    assert pr_watch.first_baseline({}, IDS, False, NOW - 600, NOW) == set(IDS)


def test_a_record_written_by_the_old_first_read_is_read_once_more_while_the_pr_is_a_day_old():
    swallowed = {"ids": IDS, "new": []}
    assert pr_watch.first_baseline(swallowed, IDS, True, NOW - 3600, NOW) == set()
    assert pr_watch.first_baseline(
        {**swallowed, "first_sight": "2026-11-18T09:42:14Z"}, IDS, True, NOW - 3600, NOW
    ) == set(IDS)  # once
    assert pr_watch.first_baseline(swallowed, IDS, True, NOW - 2 * 86400, NOW) == set(
        IDS
    )  # an old PR's history stays history
    assert pr_watch.first_baseline(swallowed, IDS, True, 0.0, NOW) == set(IDS)  # no date to go by
    assert pr_watch.first_baseline(swallowed, IDS, False, NOW - 3600, NOW) == set(IDS)  # not opened here
    assert pr_watch.first_baseline({"ids": IDS[:1], "new": [{"id": "inline:2"}]}, IDS, True, NOW - 3600, NOW) == {
        "inline:1"
    }
    assert pr_watch.first_baseline({"baseline": ["1"]}, IDS, False, NOW - 3600, NOW) == pr_watch.known_ids(
        {"baseline": ["1"]}
    )


def test_a_pr_is_opened_here_when_a_published_open_pr_of_the_ticket_names_it(monkeypatch):
    from cockpitlib import intents

    rows = [
        {
            "type": "open-pr",
            "status": "published",
            "payload": {"repo": "api"},
            "receipt": {"url": "https://github.test/acme/api/pull/12"},
        },
        {
            "type": "open-pr",
            "status": "endorsed",
            "payload": {"repo": "web"},
            "receipt": {"url": "https://github.test/acme/web/pull/7"},
        },
        {
            "type": "push-branch",
            "status": "published",
            "payload": {"repo": "api"},
            "receipt": {"url": "https://github.test/acme/api/tree/x"},
        },
    ]
    monkeypatch.setattr(intents, "all_intents", lambda ticket=None: rows)
    assert pr_watch.opened_here("TASK-9", "api", 12) and pr_watch.opened_here("TASK-9", "api", "12")
    assert (
        not pr_watch.opened_here("TASK-9", "api", 2)
        and not pr_watch.opened_here("TASK-9", "web", 7)
        and not pr_watch.opened_here("TASK-9", "web", 12)
    )
