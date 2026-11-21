# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""A request that arrives twice starts its work once: the look for an open card and the making of one are one step."""

import threading
import time

import pytest

from cockpitlib import kanban
from cockpitlib.errors import Conflict
from tests.test_refused_shapes_in_commands_and_routes import _pack


def test_what_looks_for_a_card_and_then_makes_one_runs_alone(bare):
    inside, overlaps, order = [], [], []

    @kanban.one_at_a_time
    def look_and_make(name):
        """Its own words are kept."""
        if inside:
            overlaps.append(name)
        inside.append(name)
        time.sleep(0.05)
        inside.remove(name)
        order.append(name)
        return name.upper()

    answers = []
    threads = [threading.Thread(target=lambda n=n: answers.append(look_and_make(n))) for n in ("a", "b", "c")]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert overlaps == [] and sorted(order) == ["a", "b", "c"] and sorted(answers) == ["A", "B", "C"]
    assert look_and_make.__name__ == "look_and_make" and look_and_make.__doc__ == "Its own words are kept."

    @kanban.one_at_a_time
    def outer():
        return look_and_make("nested")  # the same thread takes it again freely

    assert outer() == "NESTED"


def test_a_caller_that_waits_too_long_is_told_who_holds_it(bare, monkeypatch):
    monkeypatch.setattr(kanban, "PLACE_WAIT", 0.05)
    started, release = threading.Event(), threading.Event()

    @kanban.one_at_a_time
    def held():
        started.set()
        release.wait(5)

    @kanban.one_at_a_time
    def second():
        return "ran"

    thread = threading.Thread(target=held)
    thread.start()
    assert started.wait(5)
    try:
        with pytest.raises(Conflict):
            second()
    finally:
        release.set()
        thread.join()
    assert second() == "ran"


def test_the_same_kickoff_sent_twice_at_once_makes_one_card(bare, monkeypatch):
    from cockpitlib import kickoff

    pack = _pack()
    real = kanban.place_card

    def slow(*args, **kwargs):
        time.sleep(0.2)  # long enough for the second request to have looked, were the two not one step
        return real(*args, **kwargs)

    monkeypatch.setattr(kanban, "place_card", slow)
    results = []

    def go():
        try:
            results.append(("made", kickoff.start(pack, "intake", ticket="TASK-640", prompt="look into it")["card_id"]))
        except Conflict as exc:
            results.append(("refused", str(exc)))

    threads = [threading.Thread(target=go) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert sorted(kind for kind, _ in results) == ["made", "refused"], results
    made = next(value for kind, value in results if kind == "made")
    assert next(value for kind, value in results if kind == "refused") == f"already open: card {made}"
    assert [card["id"] for card in kanban.board_cards(pack["board"]) if card["ticket"] == "TASK-640"] == [made]


def test_the_same_rework_asked_twice_is_one_card_and_another_instruction_is_another(bare):
    from cockpitlib import acts

    pack = _pack()
    repo = pack["repos"]["repos"][0]["name"]
    first = acts._rework_per_repo(pack, "TASK-641", "TASK-641: rework", "fix it", "fix it", [repo])
    count = len(kanban.board_cards(pack["board"]))
    again = acts._rework_per_repo(pack, "TASK-641", "TASK-641: rework", "fix it", "fix it", [repo])
    assert again[0]["card"] == first[0]["card"] and again[0]["chain"] == first[0]["chain"]
    assert len(kanban.board_cards(pack["board"])) == count  # no second worker, tester or reviewer
    other = acts._rework_per_repo(pack, "TASK-641", "TASK-641: rework", "and this too", "and this too", [repo])
    assert other[0]["card"] != first[0]["card"]  # a lane's rework beside a CI rework stays possible


def test_a_reopen_sent_twice_makes_one_card(bare):
    from cockpitlib import acts

    pack = _pack()
    card = acts._reopen_card(pack, "TASK-644", "TASK-644: reopened", "intake", "ready", "what changed")
    with pytest.raises(Conflict, match=f"already open: card {card}"):
        acts._reopen_card(pack, "TASK-644", "TASK-644: reopened", "intake", "ready", "what changed")
    assert [c["id"] for c in kanban.board_cards(pack["board"]) if c["ticket"] == "TASK-644"] == [card]


def test_a_refusal_sent_back_twice_goes_back_on_one_card(bare):
    from cockpitlib import gate

    pack = _pack()
    card, there = gate.send_back(
        pack, "rework", "TASK-645", "worker-1", "fix what it names", refusal="TASK-645|push-branch|t_1|"
    )
    again, there_again = gate.send_back(
        pack, "rework", "TASK-645", "worker-1", "fix what it names", refusal="TASK-645|push-branch|t_1|"
    )
    assert (there, there_again) == (False, False) and again == card
    assert [c["id"] for c in kanban.board_cards(pack["board"]) if c["ticket"] == "TASK-645"] == [card]
    other, _ = gate.send_back(
        pack, "rework", "TASK-645", "worker-1", "another refusal", refusal="TASK-645|open-pr|t_2|"
    )
    assert other != card
    plain, _ = gate.send_back(pack, "tester", "TASK-646", "tester-1", "no refusal row behind it")
    assert plain not in (card, other)
