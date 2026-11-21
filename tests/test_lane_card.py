# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""A lane's own command knows its card from the board when Hermes has taken the card out of its environment."""

from cockpitlib import browser_card, kanban


def _board(monkeypatch, rows):
    monkeypatch.setattr(kanban, "board_cards", lambda slug, pack=None: rows)
    monkeypatch.setattr(kanban, "_index", lambda: {"acme": {"t_run": {"kind": "test", "ticket": "TASK-9"}}})
    monkeypatch.delenv("HERMES_KANBAN_TASK", raising=False)
    monkeypatch.delenv("HERMES_KANBAN_BOARD", raising=False)


def test_a_tester_whose_shell_was_not_told_its_card_is_on_the_card_the_board_says_it_runs(monkeypatch):
    rows = [
        {
            "id": "t_run",
            "title": "TASK-9: test",
            "status": "running",
            "assignee": "tester-3",
            "ticket": "TASK-9",
            "body": "",
        },
        {
            "id": "t_old",
            "title": "TASK-8: test",
            "status": "done",
            "assignee": "tester-3",
            "ticket": "TASK-8",
            "body": "",
        },
        {
            "id": "t_other",
            "title": "TASK-7: test",
            "status": "running",
            "assignee": "tester-1",
            "ticket": "TASK-7",
            "body": "",
        },
    ]
    _board(monkeypatch, rows)
    monkeypatch.setenv("COCKPIT_LANE", "tester-3")
    here = browser_card.current({"board": "acme"})
    assert here["card"] == "t_run" and here["test_kickoff"] and here["ticket"] == "TASK-9"
    monkeypatch.setenv("HERMES_KANBAN_TASK", "t_other")  # named by Hermes: that one, as before
    monkeypatch.setenv(
        "HERMES_KANBAN_BOARD", "acme"
    )  # Hermes names the board with the card; without it the bound pack is read
    assert browser_card.current({"board": "acme"})["card"] == "t_other"


def test_no_lane_no_running_card_or_two_of_them_name_no_card(monkeypatch):
    rows = [
        {
            "id": "t_a",
            "title": "TASK-9: test",
            "status": "running",
            "assignee": "tester-3",
            "ticket": "TASK-9",
            "body": "",
        },
        {
            "id": "t_b",
            "title": "TASK-8: test",
            "status": "claimed",
            "assignee": "tester-3",
            "ticket": "TASK-8",
            "body": "",
        },
    ]
    _board(monkeypatch, rows)
    monkeypatch.setenv("COCKPIT_LANE", "tester-3")
    assert browser_card.current({"board": "acme"}) == {}
    _board(monkeypatch, [{**rows[0], "status": "blocked"}])
    assert browser_card.current({"board": "acme"}) == {}
    monkeypatch.delenv("COCKPIT_LANE")
    _board(monkeypatch, rows[:1])
    assert browser_card.current({"board": "acme"}) == {} and browser_card._lane_card({}) == ""
