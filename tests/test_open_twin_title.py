# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""A card with the same title under another key is another card: the title finds only a card made before the index."""

from cockpitlib import kanban

TITLE = "TASK-9: review the PR"


def _world(monkeypatch, index):
    monkeypatch.setattr(
        kanban,
        "board_cards",
        lambda slug, pack=None: [{"id": "t_web", "status": "blocked"}, {"id": "t_old", "status": "running"}],
    )
    monkeypatch.setattr(kanban, "_index", lambda: {"acme": index})


def test_the_second_pr_of_a_ticket_is_not_taken_for_the_first_ones_open_card(monkeypatch):
    _world(monkeypatch, {"t_web": {"kind": "pr-treat", "ticket": "TASK-9", "key": "web#7"}})
    monkeypatch.setattr(kanban, "open_same", lambda slug, title: "t_web")
    assert kanban.open_twin("acme", "pr-treat", "TASK-9", "web#7", TITLE) == "t_web"  # its own PR: found by the index
    assert kanban.open_twin("acme", "pr-treat", "TASK-9", "api#4", TITLE) == ""  # the other PR: no card of its own yet


def test_a_card_made_before_the_index_is_still_found_by_its_title(monkeypatch):
    _world(monkeypatch, {"t_web": {"kind": "pr-treat", "ticket": "TASK-9", "key": "web#7"}})
    monkeypatch.setattr(kanban, "open_same", lambda slug, title: "t_old")
    assert kanban.open_twin("acme", "pr-treat", "TASK-9", "api#4", TITLE) == "t_old"
    monkeypatch.setattr(kanban, "open_same", lambda slug, title: "")
    assert (
        kanban.open_twin("acme", "pr-treat", "TASK-9", "api#4", TITLE) == ""
        and kanban.open_twin("acme", "pr-treat", "TASK-9", "api#4") == ""
    )
