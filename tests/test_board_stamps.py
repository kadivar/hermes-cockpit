# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The Board's reading of what Hermes keeps: a time in any of its shapes, and what a lane asked when it blocked."""

import sqlite3

from cockpitlib import board_view


def test_a_time_reads_the_same_whether_hermes_kept_seconds_milliseconds_or_text():
    assert board_view._iso(None) == "" and board_view._iso("") == ""
    assert board_view._iso("2026-03-10T12:00:00Z") == "2026-03-10T12:00:00Z"  # already text: left as it is
    assert (
        board_view._iso(1773144000)
        == board_view._iso("1773144000")
        == board_view._iso(1773144000000)
        == "2026-03-10T12:00:00Z"
    )
    assert board_view._epoch(None) == 0.0 and board_view._epoch("") == 0.0
    assert (
        board_view._epoch(1773144000000)
        == board_view._epoch("1773144000")
        == board_view._epoch("2026-03-10T12:00:00Z")
        == 1773144000.0
    )
    assert board_view._epoch("not a time") == 0.0


def test_the_question_of_a_blocked_card_is_the_first_telling_field_of_its_newest_block_event():
    payloads = [
        "not json",
        "[1, 2]",
        '{"question": ""}',
        {"reason": "Which base branch?", "message": "later"},
        '{"question": "an older one"}',
    ]
    assert board_view.block_question(payloads) == "Which base branch?"
    assert board_view.block_question([None, "{}"]) == ""
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    assert board_view._block_payloads(connection, "t_1", set()) == []  # an older Hermes: no events table
    connection.execute("create table task_events (task_id text, kind text, payload text, created_at real)")
    for at, kind, payload in (
        (1, "blocked", '{"question": "first"}'),
        (2, "comment", '{"question": "not a block"}'),
        (3, "block_loop_detected", '{"message": "newest"}'),
    ):
        connection.execute("insert into task_events values ('t_1', ?, ?, ?)", (kind, payload, at))
    found = board_view._block_payloads(connection, "t_1", board_view._tables(connection))
    assert found == ['{"message": "newest"}', '{"question": "first"}'] and board_view.block_question(found) == "newest"
    assert board_view._columns(connection, "task_events") == {"task_id", "kind", "payload", "created_at"}
