# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Hermes's databases (a board's kanban.db, a seat's state.db) are opened through one helper that can only read.

Cockpit reads them with SQL and writes them only through Hermes's own functions. store.read_db is the one place a
connection is made: read-only, with a busy timeout, and told not to write. The only other connect in the kernel is the
migration's snapshot, which copies a board with sqlite's own backup.
"""

import glob
import os
import re
import sqlite3

import pytest

from cockpitlib import store

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# file -> how many connects it may make itself, and why
OWN_CONNECTS = {
    "kernel/cockpitlib/store.py": 1,  # read_db itself
    "kernel/cockpitlib/pack_migration.py": 2,  # the snapshot: sqlite's backup from the board into a new file
}


def _board(tmp_path) -> str:
    path = str(tmp_path / "kanban.db")
    made = sqlite3.connect(path)
    made.execute("create table tasks (id text, status text)")
    made.execute("insert into tasks values ('t_1', 'ready')")
    made.commit()
    made.close()
    return path


def test_a_board_is_read_and_cannot_be_written_through_the_helper(tmp_path):
    connection = store.read_db(_board(tmp_path))
    try:
        assert connection.execute("select id, status from tasks").fetchall() == [("t_1", "ready")]
        assert connection.execute("PRAGMA query_only").fetchone() == (1,)
        for statement in (
            "update tasks set status = 'done'",
            "insert into tasks values ('t_2', 'ready')",
            "create table more (id text)",
        ):
            with pytest.raises(sqlite3.OperationalError):
                connection.execute(statement)
    finally:
        connection.close()
    with pytest.raises(sqlite3.OperationalError):
        store.read_db(str(tmp_path / "missing.db"))  # reading never makes a database


def test_the_wait_for_a_writer_is_the_callers_or_sqlites_own(tmp_path, monkeypatch):
    path, asked = _board(tmp_path), []
    real = sqlite3.connect

    class _Plain:
        """A stand-in that knows no pragma: the helper still hands it over."""

        def execute(self, *_args):
            raise RuntimeError("no pragma here")

    def connect(*args, **kwargs):
        asked.append((args, kwargs))
        return real(*args, **kwargs) if len(asked) < 3 else _Plain()

    monkeypatch.setattr(sqlite3, "connect", connect)
    store.read_db(path).close()
    store.read_db(path, timeout=2).close()
    assert asked == [
        ((f"file:{path}?mode=ro",), {"uri": True}),
        ((f"file:{path}?mode=ro",), {"uri": True, "timeout": 2}),
    ]
    assert isinstance(store.read_db(path), _Plain)


def test_no_module_connects_to_a_database_by_itself():
    found = {}
    for tree in ("kernel/cockpitlib", "dashboard/cockpit"):
        for path in glob.glob(os.path.join(ROOT, tree, "**", "*.py"), recursive=True):
            with open(path, encoding="utf-8") as handle:
                count = len(re.findall(r"\bsqlite3\.connect\(", handle.read()))
            if count:
                found[os.path.relpath(path, ROOT)] = count
    assert found == OWN_CONNECTS, "open Hermes's databases with store.read_db(path): read-only, with a busy timeout"
