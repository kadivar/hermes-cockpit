# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""A ticket's cards sit on the stack the ticket holds; a stack reserved in error can be given back; down says what it left."""

import pytest

from cockpitlib import decompose as plan_cards
from cockpitlib import slots
from cockpitlib.errors import CockpitError

BREAKDOWN = {"repos": [{"repo": "api", "slot": 3}]}


@pytest.fixture
def watch(monkeypatch, tmp_path):
    from cockpitlib import paths

    monkeypatch.setattr(paths, "watch_dir", lambda: str(tmp_path))
    monkeypatch.setattr(plan_cards, "check", lambda pack, ticket, breakdown: [{"repo": "api", "slot": "3"}])
    return tmp_path


def _closed(*_a, **_k):
    raise CockpitError(
        "hermes board helper failed: PermissionError: delegate_task child contexts cannot mutate Kanban tasks or boards"
    )


def test_a_breakdown_a_lane_files_while_the_board_is_closed_is_queued_and_made_by_the_housekeeping(watch, monkeypatch):
    from cockpitlib import browser_card

    monkeypatch.setenv("COCKPIT_LANE", "intake")
    monkeypatch.setattr(browser_card, "_lane_card", lambda pack: "t_intake")
    monkeypatch.setattr(plan_cards, "decompose", _closed)
    said = plan_cards.decompose_or_queue({"board": "acme"}, "TASK-9", BREAKDOWN)
    assert said["queued"] and said["cards"] == [] and "Do not make them by hand" in said["out"]
    plan_cards.decompose_or_queue({"board": "acme"}, "TASK-9", BREAKDOWN)  # asked twice: still one request
    calls, lines = [], []
    from cockpitlib import store

    monkeypatch.setattr(store, "log", lines.append)
    assert plan_cards.decompose_queued({}) == "0"  # still closed: kept, with what the board said
    assert store.read_json(plan_cards._queue_path())[0]["error"].startswith("hermes board helper failed")

    def made(pack, ticket, breakdown, parent_card=None):
        calls.append((ticket, breakdown, parent_card))
        return {"ok": True, "cards": [{"card": "t_w"}, {"card": "t_t"}]}

    monkeypatch.setattr(plan_cards, "decompose", made)
    assert plan_cards.decompose_queued({}) == "1" and calls == [("TASK-9", BREAKDOWN, "t_intake")]
    assert lines == ["DECOMPOSE-QUEUED TASK-9 → t_w t_t"] and plan_cards.decompose_queued({}) == "0"
    assert store.read_json(plan_cards._queue_path()) == []


def test_a_refusal_that_is_not_the_closed_board_or_not_a_lanes_is_said_as_it_is(watch, monkeypatch):
    monkeypatch.setattr(plan_cards, "decompose", _closed)
    monkeypatch.delenv("COCKPIT_LANE", raising=False)
    with pytest.raises(CockpitError, match="helper failed"):
        plan_cards.decompose_or_queue({}, "TASK-9", BREAKDOWN)
    monkeypatch.setenv("COCKPIT_LANE", "intake")

    def other(*_a, **_k):
        raise CockpitError("TASK-9 is halted")

    monkeypatch.setattr(plan_cards, "decompose", other)
    with pytest.raises(CockpitError, match="halted"):
        plan_cards.decompose_or_queue({}, "TASK-9", BREAKDOWN)
    monkeypatch.setattr(plan_cards, "decompose", lambda pack, ticket, breakdown: {"ok": True, "cards": [1]})
    assert plan_cards.decompose_or_queue({}, "TASK-9", BREAKDOWN) == {"ok": True, "cards": [1]}


def test_a_card_is_told_the_stack_the_ticket_holds_whatever_the_breakdown_asked(monkeypatch):
    monkeypatch.setattr(slots, "slot_of", lambda ticket, count=8, but=0: 1 if ticket == "TASK-9" else 0)
    assert plan_cards._stack_of({"seats": {"slots": 3}}, "TASK-9", "3") == "1"
    assert (
        plan_cards._stack_of({"seats": {"slots": 3}}, "TASK-8", "3") == "3"
        and plan_cards._stack_of({}, "TASK-8", "auto") == "auto"
    )


class _Provider:
    def __init__(self):
        self.freed = []

    def free(self, slot):
        self.freed.append(slot)


@pytest.fixture
def bound(monkeypatch, tmp_path):
    monkeypatch.setenv("COCKPIT_VOLUMES", str(tmp_path / "volumes"))  # a slot's lock, never this machine's own
    state = {"ticket": "TASK-9", "owner": "intake", "busy": False, "cards": [], "who": "human", "lines": []}
    from cockpitlib import kanban, store

    monkeypatch.setattr(slots, "read_ticket", lambda slot: state["ticket"])
    monkeypatch.setattr(slots, "read_owner", lambda slot: state["owner"])
    monkeypatch.setattr(slots, "lock_busy", lambda slot: state["busy"])
    monkeypatch.setattr(slots, "caller", lambda: state["who"])
    monkeypatch.setattr(slots, "_acquire", lambda slot, wait=0.0: True)
    monkeypatch.setattr(slots, "_release", lambda slot: None, raising=False)
    monkeypatch.setattr(kanban, "board_cards", lambda slug, pack=None: state["cards"])
    monkeypatch.setattr(store, "log", state["lines"].append)
    return state


def test_the_human_gives_back_a_slot_reserved_in_error(bound):
    provider = _Provider()
    assert slots.release(1, {"board": "acme"}, provider) == "released slot 1 (was TASK-9, intake)"
    assert provider.freed == [1] and bound["lines"] == ["SLOT-RELEASE 1 was TASK-9 (intake)"]
    bound.update(ticket="", owner="free")
    assert slots.release(1, {"board": "acme"}, provider) == "slot 1 is free" and provider.freed == [1]


def test_a_release_is_refused_to_a_lane_during_a_bring_up_and_under_a_running_card(bound):
    provider = _Provider()
    bound["who"] = "lane:worker-3"
    with pytest.raises(CockpitError, match="the human's"):
        slots.release(1, {"board": "acme"}, provider)
    bound.update(who="human", busy=True)
    with pytest.raises(CockpitError, match="a bring-up holds it"):
        slots.release(1, {"board": "acme"}, provider)
    bound.update(
        busy=False,
        cards=[
            {"id": "t_w", "ticket": "TASK-9", "status": "running"},
            {"id": "t_x", "ticket": "TASK-8", "status": "running"},
        ],
    )
    with pytest.raises(CockpitError, match=r"TASK-9 has a card running \(t_w\)"):
        slots.release(1, {"board": "acme"}, provider)
    bound["cards"] = [{"id": "t_w", "ticket": "TASK-9", "status": "blocked"}]
    assert slots.release(1, {"board": "acme"}, provider).startswith("released slot 1") and provider.freed == [1]


def test_down_says_that_the_slot_is_still_bound_or_that_it_only_waits(bound):
    assert (
        slots.down_said(1, None)
        == "down: slot 1 is stopped and still bound to TASK-9 (intake); `cockpit slot release 1` gives it back"
    )
    assert slots.down_said(1, "down held") == "down held: a bring-up holds slot 1; it goes down when that ends"
    bound.update(ticket="", owner="free")
    assert slots.down_said(1, None) == "down"
