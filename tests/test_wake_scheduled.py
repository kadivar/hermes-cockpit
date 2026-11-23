# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""A card a lane parked as scheduled itself (Hermes's schedule tool sets no timer) is ready again once the time in its
SCHEDULED_UNTIL marker has passed, and while it waits it is a row in the Inbox with a button that wakes it now. A card
parked with no time is a row that says only the human starts it. Cockpit's own quota parks and a plugin's cards are
left alone."""

import datetime
import sqlite3

import pytest

from cockpitlib import scheduled
from cockpitlib.errors import CockpitError
from cockpitlib.kanban import BoardWrites, db_path
from cockpitlib.pack import load
from cockpitlib.quota import MARK
from tests.support.boards import put_card
from tests.test_quota import PACKS, _rows, _status
from tests.test_row_actions import _press

NOW = 1_800_000_000.0  # mid-January 2027, after every due time below and before every later one


def _setup(monkeypatch, pack_file):
    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    monkeypatch.delenv("COCKPIT_LANE", raising=False)
    return load(pack_file)


def _park(pack, title, lane, reason) -> str:
    card = put_card(pack["board"], title, lane, "ready")
    writes = BoardWrites(pack["board"])
    writes.schedule(card, reason)
    writes.flush()
    assert _status(pack, card) == "scheduled"
    return card


def _comments(pack, card) -> list:
    connection = sqlite3.connect(db_path(pack["board"]))
    try:
        return [
            (a, b) for a, b in connection.execute("select author, body from task_comments where task_id = ?", (card,))
        ]
    finally:
        connection.close()


def test_the_wake_time_is_read_from_the_marker_in_any_iso_form():
    moment = datetime.datetime(2026, 11, 26, 12, 31, tzinfo=datetime.UTC).timestamp()
    assert scheduled.wake_at("SCHEDULED_UNTIL=2026-11-26T13:31:00+01:00 — row 8: read email") == moment
    assert scheduled.wake_at("until SCHEDULED_UNTIL=2026-11-26T12:31:00Z.") == moment
    assert scheduled.wake_at("SCHEDULED_UNTIL=2026-11-26T13:31") is not None  # no zone: this machine's
    for reason in ("", None, "waits for the invite", "SCHEDULED_UNTIL=soon", "SCHEDULED_UNTIL="):
        assert scheduled.wake_at(reason) is None


@pytest.mark.parametrize("pack_file", PACKS)
def test_a_card_whose_time_has_passed_is_ready_again_with_a_comment_and_no_row(env, pack_file, monkeypatch):
    pack = _setup(monkeypatch, pack_file)
    due = _park(pack, "TASK-5: test", "tester-1", "SCHEDULED_UNTIL=2027-01-15T07:00:00+00:00 read the postponed mail")
    assert scheduled.step(pack, now=NOW) == "1 woke, 0 waiting"
    assert _status(pack, due) == "ready"
    ((author, body),) = _comments(pack, due)
    assert author == "cockpit" and "has passed: it is ready again" in body and "read the postponed mail" in body
    assert not [ident for ident in _rows() if ident.startswith("scheduled-")]
    assert scheduled.step(pack, now=NOW + 60) == "0 woke, 0 waiting"  # once


@pytest.mark.parametrize("pack_file", PACKS)
def test_a_card_still_waiting_is_a_row_that_wakes_it_now(env, pack_file, monkeypatch):
    pack = _setup(monkeypatch, pack_file)
    later = _park(pack, "TASK-6: test", "tester-1", "SCHEDULED_UNTIL=2027-01-16T12:00:00+00:00 row 8")
    assert scheduled.step(pack, now=NOW) == "0 woke, 1 waiting"
    row = _rows()[f"scheduled-{later}"]
    assert row["tone"] == "info" and row["what"].startswith("TASK-6: test waits until 2027-01-16")
    assert [action["label"] for action in row["detail"]["actions"]] == ["Wake it now"]
    assert _status(pack, later) == "scheduled"
    done = _press(f"scheduled-{later}")
    assert done["ok"] and _status(pack, later) == "ready", done
    assert any(
        "woke this card before its scheduled time" in body and "row 8" in body for _a, body in _comments(pack, later)
    )
    assert f"scheduled-{later}" not in _rows()
    scheduled.step(pack, now=NOW)  # no longer parked: the row stays gone
    assert f"scheduled-{later}" not in _rows()


@pytest.mark.parametrize("pack_file", PACKS)
def test_a_card_parked_with_no_time_is_a_warning_row_and_never_woken_by_the_clock(env, pack_file, monkeypatch):
    pack = _setup(monkeypatch, pack_file)
    card = _park(pack, "TASK-7: worker", "worker-1", "waits for the vendor's answer")
    assert scheduled.step(pack, now=NOW + 10**8) == "0 woke, 1 waiting"
    row = _rows()[f"scheduled-{card}"]
    assert row["tone"] == "warn" and "nothing starts it again but you" in row["what"]
    assert _status(pack, card) == "scheduled"


@pytest.mark.parametrize("pack_file", PACKS)
def test_cockpits_quota_parks_and_a_plugins_cards_are_left_alone(env, pack_file, monkeypatch):
    pack = _setup(monkeypatch, pack_file)
    quota = _park(pack, "TASK-8: worker", "worker-1", MARK + "budget ceiling: SCHEDULED_UNTIL=2000-01-01T00:00:00Z")
    owned = _park(pack, "TASK-9: watch", "worker-1", "SCHEDULED_UNTIL=2000-01-01T00:00:00Z")
    monkeypatch.setattr("cockpitlib.housekeeping._owned_cards", lambda pack: {owned: "some-plugin"})
    assert scheduled.step(pack, now=NOW) == "0 woke, 0 waiting"
    assert _status(pack, quota) == "scheduled" and _status(pack, owned) == "scheduled"
    assert not [ident for ident in _rows() if ident.startswith("scheduled-")]
    with pytest.raises(CockpitError, match="not a card a lane parked"):
        scheduled.wake(pack, quota)


@pytest.mark.parametrize("pack_file", PACKS)
def test_wake_refuses_a_card_that_is_not_parked_and_the_step_runs_in_housekeeping(env, pack_file, monkeypatch):
    pack = _setup(monkeypatch, pack_file)
    ready = put_card(pack["board"], "TASK-10: test", "tester-1", "ready")
    with pytest.raises(CockpitError, match="not a card a lane parked"):
        scheduled.wake(pack, ready)
    from cockpitlib.housekeeping import STEPS

    names = [name for name, _ in STEPS]
    assert names.index("quota") < names.index("wake-scheduled")
    assert dict(STEPS)["wake-scheduled"](pack).endswith("waiting")


def test_a_board_that_is_not_there_or_keeps_no_reasons_wakes_nothing(monkeypatch):
    monkeypatch.setattr("cockpitlib.housekeeping._db", lambda pack: None)
    assert scheduled.step({"board": "nowhere"}) == "0 woke"
    with pytest.raises(CockpitError, match="no board"):
        scheduled.wake({"board": "nowhere"}, "t_1")

    class _Bare:
        def execute(self, sql, *args):
            return [] if "sqlite_master" in sql else [("t_1", "TASK-1: test", "tester-1")]

        def close(self):
            pass

    monkeypatch.setattr("cockpitlib.housekeeping._db", lambda pack: _Bare())
    assert scheduled.step({"board": "bare"}, now=NOW) == "0 woke"

    class _Broken(_Bare):
        def execute(self, sql, *args):
            raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr("cockpitlib.housekeeping._db", lambda pack: _Broken())
    assert scheduled.step({"board": "locked"}, now=NOW) == "0 woke"
