# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""What waits outside the lanes: a hold the pack has since answered, and a Board card for a ticket's outbox items."""

from cockpitlib import board_view, gate

REASON = "the pushed range has commits by bot@users.noreply.example: confirm they belong in this push"


def _held(**over):
    intent = {
        "id": "BATCH-1/003-push-branch",
        "ticket": "BATCH-1",
        "type": "push-branch",
        "status": "held",
        "payload": {"foreign": ["bot@users.noreply.example"]},
        "hold": {"waits": "human", "ask": "", "reason": REASON},
    }
    intent.update(over)
    return intent


def test_a_foreign_commit_hold_is_answered_only_when_the_pack_names_every_author():
    named = {"forge": {"human_emails": ["bot@users.noreply.example"]}}
    assert gate._foreign_declared(named, _held())
    assert not gate._foreign_declared({"forge": {}}, _held())
    assert not gate._foreign_declared(
        named, _held(payload={"foreign": ["bot@users.noreply.example", "someone@else.example"]})
    )
    assert not gate._foreign_declared(named, _held(hold={"waits": "human", "ask": "Which base?", "reason": REASON}))
    assert not gate._foreign_declared(named, _held(hold={"waits": "human", "ask": "", "reason": "a product call"}))
    assert not gate._foreign_declared(named, _held(type="pr-comment"))


def test_the_resweep_hands_an_answered_hold_back_to_the_gatekeeper(monkeypatch):
    intent = _held()
    saved, swept = [], []
    monkeypatch.setattr(gate, "all_intents", lambda: [intent])
    monkeypatch.setattr(gate, "save", saved.append)
    monkeypatch.setattr(gate, "advance", lambda row, status, _by: row.update(status=status))
    monkeypatch.setattr(gate, "request_sweep", lambda: swept.append(1))
    monkeypatch.setattr(gate, "log", lambda _line: None)
    gate.resweep_held({"forge": {"human_emails": ["bot@users.noreply.example"]}})
    assert intent["status"] == "pending" and "hold" not in intent and intent["payload"]["foreign"] == []
    assert intent["history"][-1]["previous_hold"]["reason"] == REASON and saved == [intent] and swept == [1]


def test_the_board_has_a_card_for_a_ticket_whose_outbox_waits_and_no_lane_works_on(monkeypatch):
    from cockpitlib import intents, sequence

    rows = [
        {
            "id": "BATCH-1/001-tracker-create",
            "ticket": "BATCH-1",
            "type": "tracker-create",
            "status": "endorsed",
            "created_at": "2026-01-02T00:00:00Z",
        },
        {
            "id": "BATCH-1/002-pr-edit",
            "ticket": "BATCH-1",
            "type": "pr-edit",
            "status": "endorsed",
            "created_at": "2026-01-01T00:00:00Z",
        },
        {
            "id": "BATCH-1/003-push-branch",
            "ticket": "BATCH-1",
            "type": "push-branch",
            "status": "pending",
            "created_at": "2026-01-03T00:00:00Z",
        },
        {
            "id": "TASK-7/001-push-branch",
            "ticket": "TASK-7",
            "type": "push-branch",
            "status": "endorsed",
            "created_at": "2026-01-01T00:00:00Z",
        },
        {
            "id": "TASK-8/001-push-branch",
            "ticket": "TASK-8",
            "type": "push-branch",
            "status": "published",
            "created_at": "2026-01-01T00:00:00Z",
        },
    ]
    monkeypatch.setattr(intents, "all_intents", lambda: rows)
    monkeypatch.setattr(
        sequence, "waits", lambda item, _pack=None: {"id": "x"} if item["id"].endswith("002-pr-edit") else None
    )
    monkeypatch.setattr(board_view.time, "time", lambda: board_view._epoch("2026-01-03T06:00:00Z"))
    made = board_view.waiting_cards(
        {}, [{"ticket": "TASK-7", "status": "running"}, {"ticket": "BATCH-1", "status": "done"}]
    )
    assert [card["id"] for card in made] == ["yours:BATCH-1"]  # TASK-7 has a lane at work, TASK-8 has nothing open
    card = made[0]
    assert (
        card["status"] == "review"
        and card["lane"] == "you"
        and card["yours"]
        and card["created"] == "2026-01-01T00:00:00Z"
    )
    assert card["question"] == "1 for you now · 1 later stage(s) · 1 with the gatekeeper"
    assert [(item["id"].split("/", 1)[1], item["when"]) for item in card["items"]] == [
        ("001-tracker-create", "now"),
        ("002-pr-edit", "later"),
        ("003-push-branch", "gate"),
    ]


def _push(number, status, card=""):
    row = {
        "id": f"BATCH-1/{number:03d}-push-branch",
        "ticket": "BATCH-1",
        "type": "push-branch",
        "status": status,
        "payload": {"repo": "api"},
    }
    if card:
        row["returned"] = {"card": card}
    return row


def test_a_rework_card_of_a_returned_push_waits_for_the_pushes_filed_before_it_on_its_repo():
    rows = [
        _push(1, "published"),
        _push(2, "endorsed"),
        _push(3, "returned", "c-3"),
        _push(4, "returned", "c-4"),
        {**_push(5, "endorsed"), "payload": {"repo": "web"}},
        {**_push(0, "dropped")},
    ]
    said = "Waiting for the human to publish the push before mine."
    assert gate.publish_wait(said, "c-3", rows) == {
        "open": ["BATCH-1/002-push-branch"],
        "out": ["BATCH-1/001-push-branch"],
    }
    assert gate.publish_wait(said, "c-4", rows)["open"] == [
        "BATCH-1/003-push-branch",
        "BATCH-1/002-push-branch",
    ]  # nearest first
    assert gate.publish_wait("Which base branch do you want?", "c-3", rows) == {
        "open": [],
        "out": [],
    }  # another question is the human's
    assert gate.publish_wait(said, "c-9", rows) == {"open": [], "out": []}  # not a returned push's card
    rows[1]["status"] = "published"
    assert gate.publish_wait(said, "c-3", rows) == {
        "open": [],
        "out": ["BATCH-1/002-push-branch", "BATCH-1/001-push-branch"],
    }


def test_the_desktops_publish_of_one_review_carries_the_humans_approval_only_when_it_says_so(monkeypatch):
    """A lane proposes APPROVE on a bump; the human approves by publishing that one review (`approve`), as naming its
    number does in a digest reply. Without it the publish is as before: an APPROVE is refused."""
    from cockpitlib import intents, publish
    from dashboard.cockpit import router as web

    seen = []
    monkeypatch.setattr(web, "_guard", lambda: {"name": "acme"})
    monkeypatch.setattr(
        intents,
        "load",
        lambda _id: {"id": "BATCH-1/005-pr-review-submit", "type": "pr-review-submit", "status": "endorsed"},
    )
    monkeypatch.setattr(intents, "save", lambda _row: None)
    monkeypatch.setattr(publish, "forge_for", lambda _pack, _dry: None)
    monkeypatch.setattr(
        publish, "execute", lambda _row, _forge, **kwargs: seen.append(kwargs["explicit_approve"]) or {"ok": True}
    )
    web.publish({"id": "BATCH-1/005-pr-review-submit", "confirm": "BATCH-1/005-pr-review-submit", "approve": True})
    web.publish({"id": "BATCH-1/005-pr-review-submit", "confirm": "BATCH-1/005-pr-review-submit"})
    assert seen == [True, False]


def test_a_card_note_that_cannot_be_written_never_fails_the_act_it_reports(monkeypatch):
    """Hermes refuses a board write from a lane's own command. The note comes after the act is recorded: it is skipped."""
    from cockpitlib import acts
    from cockpitlib.errors import CockpitError

    class Refusing:
        closed = False

        def commit(self):
            raise CockpitError(
                "hermes board helper failed: PermissionError: delegate_task child contexts cannot mutate Kanban tasks or boards"
            )

        def close(self):
            self.closed = True

    board = Refusing()
    monkeypatch.setattr(acts, "_open", lambda _slug: board)
    monkeypatch.setattr(acts, "_task", lambda _connection, _card: {"id": "c-1"})
    monkeypatch.setattr(acts, "_comment", lambda *_args: None)
    from cockpitlib import store

    lines = []
    monkeypatch.setattr(store, "log", lines.append)
    assert acts.note_card({"board": "b"}, "c-1", "cockpit", "sent back") is False
    assert board.closed and lines and lines[0].startswith("NOTE? c-1")


def test_a_blocked_sweep_is_run_again_once_and_a_second_block_is_the_humans(monkeypatch, tmp_path):
    import sqlite3

    from cockpitlib import housekeeping, kanban, paths

    db = tmp_path / "kanban.db"
    connection = sqlite3.connect(db)
    connection.execute("create table tasks (id text, status text)")
    connection.executemany(
        "insert into tasks values (?, ?)", [("s-1", "blocked"), ("w-1", "blocked"), ("s-2", "ready")]
    )
    connection.commit()
    connection.close()
    done = []

    class Writes:
        def __init__(self, _slug):
            pass

        def comment(self, card, author, _body):
            done.append(("comment", card, author))

        def unblock(self, card):
            done.append(("unblock", card))

        def flush(self):
            return []

    monkeypatch.setattr(housekeeping, "_db", lambda _pack: sqlite3.connect(db))
    monkeypatch.setattr(housekeeping, "BoardWrites", Writes)
    monkeypatch.setattr(
        kanban, "_index", lambda: {"b": {"s-1": {"kind": "sweep"}, "s-2": {"kind": "sweep"}, "w-1": {"kind": "work"}}}
    )
    monkeypatch.setattr(paths, "watch_dir", lambda: str(tmp_path))
    assert housekeeping.retry_sweeps({"board": "b"}) == "1"
    assert done == [("comment", "s-1", "cockpit"), ("unblock", "s-1")]  # the worker's block is a question, not a sweep
    assert housekeeping.retry_sweeps({"board": "b"}) == "0" and len(done) == 2  # blocked again: left for the human


def test_a_rework_a_lane_asks_for_while_the_board_is_closed_is_queued_and_made_by_the_housekeeping(
    monkeypatch, tmp_path
):
    from cockpitlib import acts, paths
    from cockpitlib.errors import CockpitError

    monkeypatch.setattr(paths, "watch_dir", lambda: str(tmp_path))
    request = {
        "ticket": "TASK-9",
        "title": "TASK-9: rework",
        "body": "b",
        "instruction": "fix it",
        "repos": ["api"],
        "chain": True,
    }
    acts._queue_rework(request)
    calls, retired, lines = [], [], []
    closed = {"refuse": True}

    def per_repo(_pack, ticket, title, body, instruction, repos, chain):
        calls.append((ticket, title, body, instruction, repos, chain))
        if closed["refuse"]:
            raise CockpitError("hermes board helper failed: PermissionError")
        return [{"repo": "api", "card": "c-1", "lane": "worker-1", "chain": []}]

    monkeypatch.setattr(acts, "_rework_per_repo", per_repo)
    monkeypatch.setattr(
        acts, "_retire_done_rows", lambda _pack, ticket, card, mode: retired.append((ticket, card, mode)) or []
    )
    from cockpitlib import store

    monkeypatch.setattr(store, "log", lines.append)
    assert acts.rework_queued({}) == "0"  # still refused: it stays queued with what the board said
    from cockpitlib.store import read_json

    assert read_json(acts._rework_queue_path())[0]["error"].startswith("hermes board helper failed")
    closed["refuse"] = False
    assert acts.rework_queued({}) == "1" and retired == [("TASK-9", "c-1", "rework")]
    assert calls[-1] == ("TASK-9", "TASK-9: rework", "b", "fix it", ["api"], True)
    assert (
        read_json(acts._rework_queue_path()) == []
        and acts.rework_queued({}) == "0"
        and lines == ["REWORK-QUEUED TASK-9 → c-1"]
    )


def test_a_fail_mark_in_the_counts_line_is_no_failed_row():
    from cockpitlib.test_flow import rows_failed

    table = "| # | Scenario | Result |\n|---|---|---|\n| 1 | a | ✅ Pass |\n| 2 | b | ✅ Pass |\n"
    assert rows_failed(table + "\n**Counts**: 2 rows — 2 ✅ Pass, 0 ❌ Fail. Failures: none.\n") is False
    assert rows_failed(table + "| 3 | c | ❌ Fail |\n") is True
    assert rows_failed("| AC | Verdict |\n|---|---|\n| AC1 | ❌ |\n") is True
    assert rows_failed("Row 2 failed ❌: the button stays hidden.") is True  # results without a table: read whole
    assert rows_failed("All good ✅") is False and rows_failed("") is False


# ---------- who an outbox item waits on ----------

import os  # noqa: E402 - two test files joined: the second half keeps its own header

import pytest  # noqa: E402 - two test files joined: the second half keeps its own header

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PACKS = (os.path.join(ROOT, "packs", "acme", "pack.yaml"), os.path.join(ROOT, "packs", "bravo", "pack.yaml"))
NOW = "2026-03-10T12:00:00Z"


def _waiting(monkeypatch, pack_file, rows, cards=()):
    import cockpitlib.sequence  # noqa: F401  loaded before the stub below, or it would keep the stub as its own all_intents
    from cockpitlib import intents
    from cockpitlib.pack import load

    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    monkeypatch.setattr(intents, "all_intents", lambda ticket=None: rows)
    monkeypatch.setattr(board_view.time, "time", lambda: board_view._epoch(NOW))
    return board_view.waiting_cards(load(pack_file), list(cards))


@pytest.mark.parametrize("pack_file", PACKS)
def test_a_returned_push_whose_rework_card_is_done_is_the_lanes_and_never_for_you_now(env, pack_file, monkeypatch):
    returned = {
        "id": "REL-1/001-push-branch",
        "ticket": "REL-1",
        "type": "push-branch",
        "status": "returned",
        "created_at": "2026-03-10T09:00:00Z",
        "payload": {"repo": "api"},
        "returned": {"card": "t_done", "instruction": "rebase it"},
    }
    done = [{"id": "t_done", "ticket": "REL-1", "status": "done"}]
    assert (
        _waiting(monkeypatch, pack_file, [returned], done) == []
    )  # nothing of it is the human's: no card says "yours"
    held_for_lanes = {
        "id": "REL-1/002-pr-comment",
        "ticket": "REL-1",
        "type": "pr-comment",
        "status": "held",
        "created_at": "2026-03-10T09:00:00Z",
        "payload": {"repo": "api"},
        "hold": {"waits": "lane", "reason": "the tester is still running"},
    }
    assert _waiting(monkeypatch, pack_file, [returned, held_for_lanes], done) == []
    endorsed = {
        "id": "REL-1/003-pr-comment",
        "ticket": "REL-1",
        "type": "pr-comment",
        "status": "endorsed",
        "created_at": "2026-03-10T10:00:00Z",
        "payload": {"repo": "api"},
    }
    card = _waiting(monkeypatch, pack_file, [returned, held_for_lanes, endorsed], done)[0]
    assert card["question"] == "1 for you now · 2 back with a lane"
    assert [item["when"] for item in card["items"]] == ["lane", "lane", "now"]


@pytest.mark.parametrize("pack_file", PACKS)
def test_an_old_pending_ticket_done_makes_no_board_card_and_a_stale_pending_item_is_named_stale(
    env, pack_file, monkeypatch
):
    done_row = {
        "id": "REL-2/004-ticket-done",
        "ticket": "REL-2",
        "type": "ticket-done",
        "status": "pending",
        "created_at": "2026-01-05T09:00:00Z",
        "payload": {},
    }
    assert _waiting(monkeypatch, pack_file, [done_row]) == []
    fresh_done = {**done_row, "created_at": "2026-03-10T11:00:00Z"}
    assert (
        _waiting(monkeypatch, pack_file, [fresh_done]) == []
    )  # a confirmation of finished work is the Inbox's row, not a card
    old = {
        "id": "REL-3/001-pr-comment",
        "ticket": "REL-3",
        "type": "pr-comment",
        "status": "pending",
        "created_at": "2026-03-01T09:00:00Z",
        "payload": {"repo": "api"},
    }
    assert (
        board_view.stale_days(old, board_view._epoch(NOW)) == 9
        and board_view.stale_days(done_row, board_view._epoch(NOW)) == 64
    )
    assert _waiting(monkeypatch, pack_file, [old]) == []
    touched = {**old, "history": [{"time": "2026-03-09T12:00:01Z", "event": "git read again (re-probe)"}, "not a row"]}
    card = _waiting(monkeypatch, pack_file, [old, {**touched, "id": "REL-3/002-pr-comment"}])[0]
    assert card["question"] == "1 with the gatekeeper · 1 stale" and [item["when"] for item in card["items"]] == [
        "stale",
        "gate",
    ]


def test_only_a_pending_intent_untouched_for_days_is_stale():
    now = board_view._epoch(NOW)
    assert board_view.stale_days({"status": "endorsed", "created_at": "2026-01-01T00:00:00Z"}, now) == 0
    assert (
        board_view.stale_days({"status": "pending", "created_at": "2026-03-08T12:00:01Z"}, now) == 0
    )  # a second short of two days
    assert board_view.stale_days({"status": "pending", "created_at": "2026-03-08T12:00:00Z"}, now) == 2
    assert board_view.stale_days({"status": "pending"}, now) == 0  # no date to go by: not called stale
    assert board_view.stale_days(
        {"status": "pending", "created_at": "2020-01-01T00:00:00Z", "history": [{"time": NOW}]}
    ) == board_view.stale_days({"status": "pending", "created_at": NOW})
