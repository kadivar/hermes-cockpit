# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""`cockpit live` and `cockpit board`: a terminal view of the board and the lanes, with no gateway."""

import io
import json
import sqlite3
import time

import pytest

from cockpitlib import cli
from cockpitlib import live_cli as L


@pytest.fixture
def world(tmp_path, monkeypatch):
    board = tmp_path / "kanban.db"
    lanes = tmp_path / "lane.db"
    db = sqlite3.connect(board)
    db.executescript("""create table tasks (id text, title text, status text, assignee text, created_at real, block_reason text);
        create table task_runs (id integer primary key, task_id text, status text, started_at real, ended_at real,
                                last_heartbeat_at real, error text, summary text);
        create table task_events (id integer primary key, task_id text, kind text, created_at real);""")
    db.close()
    db = sqlite3.connect(lanes)
    db.execute(
        "create table messages (id integer primary key, session_id text, role text, content text, tool_calls text, tool_name text, timestamp real)"
    )
    db.close()
    monkeypatch.setattr(L, "db_path", lambda slug: str(board))
    monkeypatch.setattr(L, "_profile_db", lambda lane: str(lanes) if lane == "tester-1" else "")
    monkeypatch.setattr(L, "job_rows", lambda cards, since: [])
    return {"board": str(board), "lanes": str(lanes), "pack": {"board": "demo"}}


def add_card(
    world,
    card,
    status,
    lane="tester-1",
    title="ACME-1: chrome-qa",
    started=None,
    ended=None,
    beat=None,
    run="running",
    error="",
    reason="",
    runs=1,
):
    now = time.time()
    db = sqlite3.connect(world["board"])
    db.execute("insert into tasks values (?,?,?,?,?,?)", (card, title, status, lane, now - 600, reason))
    for _ in range(runs):
        db.execute(
            "insert into task_runs (task_id,status,started_at,ended_at,last_heartbeat_at,error,summary) values (?,?,?,?,?,?,?)",
            (card, run, started or now - 120, ended, beat or now - 3, error, "the summary"),
        )
    db.commit()
    db.close()


def say(world, session, role, content, when=None, calls=None, tool=None):
    db = sqlite3.connect(world["lanes"])
    db.execute(
        "insert into messages (session_id,role,content,tool_calls,tool_name,timestamp) values (?,?,?,?,?,?)",
        (session, role, content, calls, tool, when if when is not None else time.time()),
    )
    db.commit()
    db.close()


def event(world, card, kind, when=None):
    db = sqlite3.connect(world["board"])
    db.execute("insert into task_events (task_id,kind,created_at) values (?,?,?)", (card, kind, when or time.time()))
    db.commit()
    db.close()


PLAIN = L.Style(False)


def test_the_board_groups_cards_by_status_with_age_heartbeat_and_crashes(world):
    add_card(world, "t_a", "running")
    add_card(world, "t_b", "blocked", reason="needs \x1b[31man answer")
    add_card(world, "t_c", "done", ended=time.time() - 30, run="crashed", error="worker lost", runs=2)
    rows = L.board_rows(world["pack"])
    by = {row["id"]: row for row in rows}
    assert by["t_a"]["ticket"] == "ACME-1" and by["t_a"]["step"] == "chrome-qa" and by["t_a"]["beat"] < 10
    assert "\x1b" not in by["t_b"]["note"] and by["t_c"]["crashes"] == 2 and by["t_c"]["beat"] is None
    text = "\n".join(L.render_board(world["pack"], rows, PLAIN, 140, clock="10:00:00"))
    assert "1 running" in text and "1 closed" in text and "RUNNING" in text and "BLOCKED" in text and "RECENT" in text
    assert "×2" in text and "!2" in text and "worker lost" in text
    assert "CLOSED" in "\n".join(L.render_board(world["pack"], rows, PLAIN, 140, everything=True))
    assert "nothing open" in "\n".join(L.render_board(world["pack"], [], PLAIN, 140))


def test_the_board_filters_and_prints_json(world, capsys):
    add_card(world, "t_a", "running")
    add_card(world, "t_b", "ready", lane="worker-1", title="ACME-2: dev")
    assert L.run_board(world["pack"], ["ACME-2", "--json"]) == 0
    assert [row["id"] for row in json.loads(capsys.readouterr().out)] == ["t_b"]
    assert L.run_board(world["pack"], ["--lane", "tester-1", "--status", "running"]) == 0
    out = capsys.readouterr().out
    assert "t_a" in out and "t_b" not in out and "\033" not in out
    with pytest.raises(ValueError, match="stray"):
        L.run_board(world["pack"], ["A", "B"])
    with pytest.raises(ValueError, match="needs a value"):
        L.run_board(world["pack"], ["--lane"])


def test_a_card_with_no_run_and_a_missing_or_broken_board_read_as_nothing(world, tmp_path, monkeypatch):
    db = sqlite3.connect(world["board"])
    db.execute("insert into tasks values ('t_x','no ticket here','ready',null,1,'')")
    db.commit()
    db.close()
    [row] = L.board_rows(world["pack"])
    assert row["ticket"] == "" and row["step"] == "no ticket here" and row["runs"] == 0 and row["note"] == ""
    broken = tmp_path / "broken.db"
    sqlite3.connect(broken).close()
    monkeypatch.setattr(L, "db_path", lambda slug: str(broken))
    assert L.board_rows(world["pack"]) == [] and L._open_cards(world["pack"]) == []
    feed = L.Feed(world["pack"])
    assert feed._events() == []
    monkeypatch.setattr(L, "db_path", lambda slug: str(tmp_path / "gone.db"))
    assert (
        L.board_rows(world["pack"]) == []
        and L._open_cards(world["pack"]) == []
        and L.Feed(world["pack"])._events() == []
    )


def test_the_feed_reads_new_rows_once_and_a_closed_card_one_last_time(world):
    add_card(world, "t_a", "running")
    say(world, "s1", "user", "work on card t_a")
    say(
        world,
        "s1",
        "assistant",
        "looking",
        calls=json.dumps([{"function": {"name": "terminal", "arguments": '{"command": "ls"}'}}]),
    )
    event(world, "t_a", "claimed")
    feed = L.Feed(world["pack"], minutes=5)
    rows = feed.poll()
    assert {row["kind"] for row in rows} >= {"prompt", "text", "tool_use", "event"}
    assert feed.poll() == []
    say(world, "s1", "assistant", "finished it")
    db = sqlite3.connect(world["board"])
    db.execute("update tasks set status = 'done' where id = 't_a'")
    db.commit()
    db.close()
    event(world, "t_a", "completed")
    rows = feed.poll()
    assert [row["text"] for row in rows if row["kind"] == "text"] == ["finished it"]
    assert any(row["kind"] == "event" and row["text"].startswith("done") for row in rows)
    assert feed.poll() == [] and feed.watching == {}


def test_the_feed_filters_and_forgets_old_keys(world, monkeypatch):
    add_card(world, "t_a", "running")
    add_card(world, "t_b", "running", lane="worker-1", title="ACME-2: dev")
    say(world, "s1", "user", "card t_a")
    event(world, "t_a", "claimed")
    event(world, "t_b", "crashed")
    assert L.Feed(world["pack"], ticket="ACME-2").poll()[0]["bad"] is True
    assert all(row["who"] == "tester-1" for row in L.Feed(world["pack"], lane="tester-1").poll())
    monkeypatch.setattr(L, "SEEN_ROWS", 1)
    feed = L.Feed(world["pack"])
    assert feed._remember("a") and feed._remember("b") and "a" not in feed.seen and not feed._remember("b")


def test_a_lane_lookup_is_cached_and_survives_a_broken_database(world, monkeypatch, tmp_path):
    add_card(world, "t_a", "running")
    feed = L.Feed(world["pack"])
    card = L._open_cards(world["pack"])[0]
    say(world, "s1", "user", "card t_a")
    assert len(feed._lane(card, "")) == 1
    say(world, "s2", "user", "card t_a again")
    assert len(feed._lane(card, "")) == 1, "the sessions are cached for a moment"
    monkeypatch.setattr(L, "SESSION_REFRESH", 0)
    assert len(feed._lane(card, "")) == 2
    bad = tmp_path / "bad.db"
    bad.write_text("not a database")
    monkeypatch.setattr(L, "_profile_db", lambda lane: str(bad))
    assert feed._lane(card, "") == []
    assert feed._lane({**card, "assignee": "nobody"}, "") == []
    monkeypatch.setattr(L, "_profile_db", lambda lane: "")
    assert feed._lane(card, "") == []


@pytest.mark.parametrize(
    "entry,expected",
    [
        ({"kind": "text", "text": "hello\nthere"}, "hello"),
        ({"kind": "tool_use", "name": "terminal", "summary": json.dumps({"command": "ls -la"})}, "ls -la"),
        ({"kind": "tool_use", "name": "x", "summary": "not json"}, "not json"),
        ({"kind": "tool_use", "name": "x", "summary": json.dumps({"other": 1})}, "other"),
        ({"kind": "tool_use", "name": "x", "summary": "[1]"}, "[1]"),
        ({"kind": "tool_result", "text": "\n  first\nsecond"}, "first"),
        ({"kind": "prompt", "text": "\ndo it"}, "do it"),
        ({"kind": "event", "text": "done", "bad": False}, "◆ done"),
    ],
)
def test_each_kind_of_row_prints(entry, expected):
    lines = L.format_entry({"who": "tester-1", "ticket": "ACME-1", "ts": "2026-01-01T10:00:00Z", **entry}, PLAIN, 120)
    assert expected in lines[0] and "tester-1" in lines[0]


def test_rows_are_clean_short_and_optional():
    long = "\n".join(f"line {index}" for index in range(9))
    lines = L.format_entry({"kind": "text", "who": "a", "ts": "bad", "text": long}, PLAIN, 80)
    assert len(lines) == 5 and "5 more lines" in lines[-1]
    assert L.format_entry({"kind": "text", "text": "  \n "}, PLAIN, 80) == []
    assert L.format_entry({"kind": "tool_result", "text": "x"}, PLAIN, 80, tools=False) == []
    hostile = L.format_entry({"kind": "text", "text": "a\x1b]0;owned\x07b"}, PLAIN, 80)
    assert "\x1b" not in hostile[0] and "\x07" not in hostile[0]
    wide = L.format_entry({"kind": "text", "text": "x" * 500}, PLAIN, 80)[0]
    assert wide.endswith("…") and len(wide) < 100
    assert L._ago(5) == "5s" and L._ago(120) == "2m" and L._ago(7200) == "2h00" and L._ago(200000) == "2d"


def test_no_control_sequence_from_a_title_lane_or_transcript_reaches_the_terminal(world):
    add_card(world, "t_a", "running", title="ACME-1: \x1b[2Jevil", lane="bad\x1b]0;x\x07lane")
    event(world, "t_a", "crashed")
    [row] = L.board_rows(world["pack"])
    assert "\x1b" not in row["step"] + row["lane"]
    assert "\x1b" not in "\n".join(L.render_board(world["pack"], [row], PLAIN, 140))
    lines = L.format_entry(
        {"kind": "text", "who": "a\x1b[2J", "ticket": "b\x1b[2J", "ts": "2026-01-01\x1b[2JT10", "text": "\ud800ok"},
        PLAIN,
        120,
    )
    assert "\x1b" not in lines[0] and "\ud800" not in lines[0]
    lines[0].encode("utf-8")
    assert len(L.format_entry({"kind": "event", "text": "two\nlines"}, PLAIN, 120)) == 1


def test_an_older_board_without_runs_or_columns_still_lists_its_cards(world, tmp_path, monkeypatch):
    old = tmp_path / "old.db"
    db = sqlite3.connect(old)
    db.execute("create table tasks (id text, title text)")
    db.execute("insert into tasks values ('t_o', 'ACME-9: dev')")
    db.commit()
    db.close()
    monkeypatch.setattr(L, "db_path", lambda slug: str(old))
    [row] = L.board_rows(world["pack"])
    assert row["id"] == "t_o" and row["runs"] == 0 and row["lane"] == "" and row["status"] == ""
    monkeypatch.setattr(L, "db_path", lambda slug: str(tmp_path))  # a folder cannot be opened
    assert L._connect(world["pack"]) is None
    monkeypatch.setattr(L.os.path, "isfile", lambda path: True)
    assert L._connect(world["pack"]) is None


def test_a_session_counts_only_for_the_card_its_first_prompt_names(world):
    add_card(world, "t_a1", "running")
    add_card(world, "t_b2", "running")
    say(world, "own", "user", "card t_a1")
    say(world, "other", "user", "card t_b2 mentions t_a1")
    feed = L.Feed(world["pack"])
    cards = {card["id"]: card for card in L._open_cards(world["pack"])}
    assert [row["text"] for row in feed._lane(cards["t_a1"], "")] == ["card t_a1"]


def test_colour_is_on_only_when_asked():
    assert L.Style(False)("x", 12, True) == "x"
    on = L.Style(True)
    assert on("x") == "x" and on("x", 12) == "\033[38;5;12mx\033[0m" and on("x", bold=True) == "\033[1mx\033[0m"
    assert "\033" in on.lane("tester-1")


def test_live_once_prints_and_json_keeps_the_rows(world, capsys):
    add_card(world, "t_a", "running")
    say(world, "s1", "user", "card t_a")
    say(world, "s1", "tool", "output", tool="terminal")
    assert L.run_live(world["pack"], ["--once"]) == 0
    assert "card t_a" in capsys.readouterr().out
    assert L.run_live(world["pack"], ["--once", "--no-tools"]) == 0
    assert "output" not in capsys.readouterr().out
    assert L.run_live(world["pack"], ["ACME-1", "--once", "--json", "--minutes", "2"]) == 0
    rows = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert rows and all("html" not in row for row in rows)
    with pytest.raises(ValueError, match="number"):
        L.run_live(world["pack"], ["--minutes", "x"])
    with pytest.raises(ValueError, match="stray"):
        L.run_live(world["pack"], ["A", "B"])


class Screen(io.StringIO):
    def isatty(self):
        return True


def test_watching_redraws_and_gives_the_terminal_back(world, monkeypatch):
    add_card(world, "t_a", "running")
    screen = Screen()
    monkeypatch.setattr(L.sys, "stdout", screen)
    monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.setattr(L.time, "sleep", lambda seconds: (_ for _ in ()).throw(KeyboardInterrupt()))
    with pytest.raises(KeyboardInterrupt):
        L._quit()
    assert L.run_board(world["pack"], ["--watch"]) == 0
    out = screen.getvalue()
    assert out.startswith("\033[?1049h") and "RUNNING" in out and out.endswith("\033[?25h\033[?1049l")


def test_live_pins_a_status_line_and_gives_the_terminal_back(world, monkeypatch):
    add_card(world, "t_a", "running")
    add_card(world, "t_w", "ready", lane="worker-1", title="ACME-2: dev")
    add_card(world, "t_z", "blocked", lane="worker-1", title="ACME-3: dev")
    say(world, "s1", "user", "card t_a")
    screen = Screen()
    handlers = []
    monkeypatch.setattr(L.sys, "stdout", screen)
    monkeypatch.setattr(L.signal, "signal", lambda sig, handler: handlers.append(handler))
    monkeypatch.setattr(L.time, "sleep", lambda seconds: (_ for _ in ()).throw(KeyboardInterrupt()))
    assert L.run_live(world["pack"], []) == 0
    handlers[0]()
    out = screen.getvalue()
    assert (
        "\033[1;" in out
        and "1 running" in out
        and "1 waiting" in out
        and "1 blocked" in out
        and "ACME-1 chrome-qa" in out
    )
    assert out.rstrip("\n").endswith("\033[2K")
    assert "no card running" in L._status_line([], PLAIN, 120)
    busy = L.board_rows(world["pack"])
    assert "…" in L._status_line(busy, PLAIN, 60, ticket="ACME-1")


def test_the_cli_runs_them_and_a_wrong_argument_prints_the_usage(world, monkeypatch, capsys):
    monkeypatch.setattr(cli, "_pack", lambda: world["pack"])
    add_card(world, "t_a", "running")
    assert cli.main(["board"]) == 0 and "t_a" in capsys.readouterr().out
    assert cli.main(["live", "--once"]) == 0
    capsys.readouterr()
    assert cli.main(["board", "--lane"]) == 2 and "cockpit board --watch" in (lambda c: c.out + c.err)(  # noqa: PLC3002 - one read of the captured output, used twice
        capsys.readouterr()
    )
    assert cli.main(["live", "--bad"]) == 2
