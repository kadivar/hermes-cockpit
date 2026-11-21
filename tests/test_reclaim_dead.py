# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""A card the board calls running whose worker is gone is handed back, so it and the cards behind it move again."""

import os
import sqlite3

from cockpitlib import housekeeping

NOW = 1_800_000_000.0


def _board(
    tmp_path, rows, columns="id text, status text, claim_expires real, worker_pid integer, last_heartbeat_at real"
):
    path = tmp_path / "board.db"
    connection = sqlite3.connect(path)
    connection.execute(f"create table tasks ({columns})")
    connection.executemany(f"insert into tasks values ({', '.join('?' * len(rows[0]))})", rows) if rows else None
    connection.commit()
    connection.close()
    return str(path)


def _world(monkeypatch, path, owned=None):
    done, lines, woken = [], [], []

    class Writes:
        def __init__(self, slug):
            self.ops = []

        def reclaim(self, card, reason=None):
            self.ops.append((card, reason))

        def flush(self):
            done.extend(self.ops)

    from cockpitlib import store

    monkeypatch.setattr(housekeeping, "_db", lambda pack: sqlite3.connect(path) if path else None)
    monkeypatch.setattr(housekeeping, "BoardWrites", Writes)
    monkeypatch.setattr(housekeeping, "_owned_cards", lambda pack: owned or {})
    monkeypatch.setattr("cockpitlib.inbox.wake", lambda plugin, card: woken.append((plugin, card)))
    monkeypatch.setattr(store, "log", lines.append)
    return done, lines, woken


def test_a_running_card_whose_worker_is_gone_and_whose_claim_ran_out_is_handed_back(monkeypatch, tmp_path):
    gone = 2**22 + 12345  # no such process
    # fmt: off
    rows = [("t_dead", "running", NOW - 3600, gone, NOW - 3700),          # the interrupted worker
            ("t_nopid", "running", NOW - 3600, None, None),               # claimed, never bound
            ("t_alive", "running", NOW - 3600, os.getpid(), NOW - 3700),   # slow, but there
            ("t_fresh", "running", NOW - 60, gone, NOW - 3700),            # the claim has only just run out
            ("t_beat", "running", NOW - 3600, gone, NOW - 30),             # a heartbeat a moment ago
            ("t_claim", "running", NOW + 600, gone, NOW - 3700),           # the claim still holds
            ("t_plugin", "running", NOW - 3600, gone, NOW - 3700),         # another plugin's card
            ("t_block", "blocked", NOW - 3600, gone, NOW - 3700),
            ("t_odd", "running", "soon", gone, None)]
    # fmt: on
    done, lines, woken = _world(monkeypatch, _board(tmp_path, rows), owned={"t_plugin": "supervisor"})
    assert housekeeping.reclaim_dead({"board": "acme"}, now=NOW) == "2"
    assert [card for card, _reason in done] == ["t_dead", "t_nopid"] and "the worker is gone" in done[0][1]
    assert lines == ["RECLAIM-DEAD t_dead t_nopid"] and woken == [("supervisor", "t_plugin")]


def test_nothing_to_hand_back_no_board_or_an_older_board_writes_nothing(monkeypatch, tmp_path):
    done, lines, _woken = _world(monkeypatch, _board(tmp_path, [("t_ok", "running", NOW + 600, os.getpid(), NOW)]))
    assert housekeeping.reclaim_dead({"board": "acme"}, now=NOW) == "0" and done == [] and lines == []
    done, _lines, _woken = _world(monkeypatch, "")
    assert housekeeping.reclaim_dead({"board": "acme"}, now=NOW) == "0"
    old = tmp_path / "old"
    old.mkdir()
    done, _lines, _woken = _world(monkeypatch, _board(old, [("t_1", "running")], columns="id text, status text"))
    assert housekeeping.reclaim_dead({"board": "acme"}) == "0" and done == []
    assert housekeeping._alive("not a pid") is False and housekeeping._alive(os.getpid()) is True


def test_a_board_without_a_heartbeat_column_goes_by_the_claim_and_the_process(monkeypatch, tmp_path):
    path = _board(
        tmp_path,
        [("t_dead", "running", NOW - 3600, 2**22 + 999)],
        columns="id text, status text, claim_expires real, worker_pid integer",
    )
    done, _lines, _woken = _world(monkeypatch, path)
    assert housekeeping.reclaim_dead({"board": "acme"}, now=NOW) == "1" and done[0][0] == "t_dead"
