# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Board states a card reaches only by running (running, review, done, todo, triage). Test setup only."""

import sqlite3

from cockpitlib.kanban import db_path, place_card


def put_card(slug: str, title: str, lane: str, status: str) -> str:
    """Create the card the way cockpit does, then move it to a state only a run would give it."""
    card = place_card(slug, title, lane, "blocked" if status == "blocked" else "ready")
    if status in ("ready", "blocked"):
        return card
    connection = sqlite3.connect(db_path(slug))
    connection.execute("update tasks set status = ? where id = ?", (status, card))
    connection.commit()
    connection.close()
    return card


def set_body(slug: str, card: str, body: str) -> None:
    """Edit a card's body through Hermes, as an editing human or lane would."""
    from cockpitlib.kanban import BoardWrites

    writes = BoardWrites(slug)
    writes.edit(card, body=body)
    writes.flush()


def raw(slug: str):
    """A writable connection for test setup only. Cockpit itself writes through Hermes."""
    return sqlite3.connect(db_path(slug))


def init_db(slug: str) -> str:
    """An older, smaller board table, for tests of cockpit's readers."""
    import os

    path = db_path(slug)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    connection = sqlite3.connect(path)
    connection.execute(
        "create table if not exists tasks (id text primary key, title text, assignee text, status text, created_at text)"
    )
    connection.commit()
    connection.close()
    return path


def insert_card(slug: str, card_id: str, title: str, assignee: str, status: str = "triage") -> None:
    """A row written straight into an older board, the way a pre-Hermes tool would have."""
    init_db(slug)
    connection = sqlite3.connect(db_path(slug))
    connection.execute(
        "insert or replace into tasks (id, title, assignee, status, created_at) values (?, ?, ?, ?, ?)",
        (card_id, title, assignee, status, ""),
    )
    connection.commit()
    connection.close()
