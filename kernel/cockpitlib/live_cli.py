# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""`cockpit live` and `cockpit board`: what the agents are doing, in a terminal.

Read-only and straight from the board's database and the lanes' transcripts, so it works when the gateway or the
Desktop does not. `live` reads only the cards that are open, and each poll only what is newer than the last one.
"""

import calendar
import json
import os
import re
import shutil
import signal
import sqlite3
import sys
import time
from collections import deque

from .kanban import OPEN, db_path, ticket_of
from .lane_feed import _entries, _messages, _owner, _profile_db
from .lane_transcripts import job_rows
from .store import read_db

POLL_SECONDS = 2.0
BOARD_SECONDS = 3.0
HISTORY_MINUTES = 5
RECENT_CLOSED = 8
SEEN_ROWS = 6000
SESSION_REFRESH = 15  # seconds before a card's sessions are looked up again (a retry opens a new one)
TEXT_LINES = 4
EVENTS = {
    "created": "new",
    "claimed": "claimed",
    "spawned": "started",
    "completed": "done",
    "crashed": "crashed",
    "blocked": "blocked",
    "unblocked": "unblocked",
    "gave_up": "gave up",
    "worker_lost": "worker lost",
    "timed_out": "timed out",
}
BAD_EVENTS = {"crashed", "gave_up", "worker_lost", "timed_out", "blocked"}
GLYPHS = {
    "running": "●",
    "ready": "○",
    "claimed": "◐",
    "blocked": "⊘",
    "review": "◇",
    "triage": "◌",
    "scheduled": "◷",
    "todo": "○",
    "in_progress": "●",
    "done": "✓",
    "archived": "▪",
    "cancelled": "✗",
}
ORDER = ("running", "in_progress", "claimed", "ready", "todo", "blocked", "review", "triage", "scheduled")
STATUS_TONE = {
    "running": 42,
    "in_progress": 42,
    "claimed": 45,
    "ready": 75,
    "todo": 75,
    "blocked": 203,
    "review": 180,
    "triage": 180,
    "scheduled": 245,
    "done": 244,
    "archived": 240,
    "cancelled": 240,
}
LANE_TONES = (39, 208, 141, 44, 214, 170, 78, 111, 216, 147)
# Agent text is untrusted: an escape sequence in it must not reach the terminal.
CONTROL = re.compile("[\x00-\x08\x0b-\x1f\x7f-\x9f\ud800-\udfff]")


class Style:
    def __init__(self, on: bool):
        self.on = on

    def __call__(self, text: str, tone: int = 0, bold: bool = False) -> str:
        if not self.on or (not tone and not bold):
            return text
        codes = ("1;" if bold else "") + (f"38;5;{tone}" if tone else "")
        return f"\033[{codes.rstrip(';')}m{text}\033[0m"

    def lane(self, name: str) -> str:
        return self(name.ljust(10)[:10], LANE_TONES[sum(name.encode()) % len(LANE_TONES)], True)


def _clean(text) -> str:
    return CONTROL.sub("", str(text or "").replace("\t", "  "))


def _width() -> int:
    return max(60, shutil.get_terminal_size((120, 30)).columns)


def _clip(text: str, room: int) -> str:
    return text if len(text) <= room else text[: max(room - 1, 1)] + "…"


def _ago(seconds) -> str:
    seconds = max(int(seconds), 0)
    if seconds < 90:
        return f"{seconds}s"
    if seconds < 5400:
        return f"{seconds // 60}m"
    if seconds < 172800:
        return f"{seconds // 3600}h{(seconds % 3600) // 60:02d}"
    return f"{seconds // 86400}d"


def _local(stamp: str) -> str:
    try:
        return time.strftime("%H:%M:%S", time.localtime(calendar.timegm(time.strptime(stamp, "%Y-%m-%dT%H:%M:%SZ"))))
    except ValueError:
        return _clean(stamp[11:19])


def _connect(pack):
    path = db_path(str(pack.get("board") or ""))
    if not os.path.isfile(path):
        return None
    try:
        connection = read_db(path, timeout=2)
    except sqlite3.Error:
        return None
    connection.row_factory = sqlite3.Row
    return connection


def _field(row, name, default=None):
    """A column an older board may not have."""
    return row[name] if row is not None and name in row.keys() and row[name] is not None else default


def _open_cards(pack, also=()) -> list:
    """The open cards and `also`, by id: what the feed reads each poll, without loading the whole board's history."""
    connection = _connect(pack)
    if connection is None:
        return []
    marks = ",".join("?" * len(OPEN))
    extra = ",".join("?" * len(also))
    where = f"status in ({marks})" + (f" or id in ({extra})" if also else "")
    try:
        rows = connection.execute(
            f"select id, title, status, assignee, created_at from tasks where {where}", (*OPEN, *also)
        ).fetchall()
    except sqlite3.Error:
        return []
    finally:
        connection.close()
    return [{**dict(row), "ticket": ticket_of(row["title"] or "") or ""} for row in rows]


def _step(title: str, ticket: str) -> str:
    head = title.split(":", 1)
    return head[1].strip() if len(head) == 2 and head[0].strip() == ticket else title


def board_rows(pack, now=None) -> list:
    """Every card with its newest run: id, status, lane, ticket, step, age, beat (seconds since a heartbeat, open cards
    only), runs, crashes and the last error or summary."""
    now = time.time() if now is None else now
    connection = _connect(pack)
    if connection is None:
        return []
    try:
        tasks = connection.execute("select * from tasks").fetchall()
    except sqlite3.Error:
        connection.close()
        return []
    runs = {}
    try:
        for row in connection.execute("select * from task_runs order by id"):
            runs.setdefault(row["task_id"], []).append(row)
    except sqlite3.Error:  # a board from before runs were kept
        runs = {}
    finally:
        connection.close()
    rows = []
    for task in tasks:
        title = _clean(_field(task, "title", "")).replace("\n", " ")
        ticket = ticket_of(title) or ""
        mine = runs.get(task["id"], [])
        last = mine[-1] if mine else None
        status = _clean(_field(task, "status", ""))
        start = _field(last, "started_at", 0) or _field(task, "created_at", 0) or now
        end = _field(last, "ended_at", 0)
        beat = _field(last, "last_heartbeat_at", 0)
        note = _field(last, "error", "") or _field(last, "summary", "")
        reason = _field(task, "block_reason", "")
        rows.append(
            {
                "id": _clean(task["id"]),
                "status": status,
                "lane": _clean(_field(task, "assignee", "")).replace("\n", " "),
                "ticket": ticket,
                "step": _step(title, ticket),
                "age": (end if status not in OPEN and end else now) - start,
                "closed": end or start,
                "beat": now - beat if beat and status in OPEN else None,
                "runs": len(mine),
                "crashes": sum(1 for run in mine if _field(run, "status") in ("crashed", "timed_out", "failed")),
                "note": _clean(reason or note).replace("\n", " "),
            }
        )
    return rows


def _filtered(rows, ticket="", lane="", status="") -> list:
    return [
        row
        for row in rows
        if (not ticket or row["ticket"] == ticket)
        and (not lane or row["lane"] == lane)
        and (not status or row["status"] == status)
    ]


def _row_line(row, style, width) -> str:
    tone = STATUS_TONE.get(row["status"], 250)
    beat = f"♥{_ago(row['beat'])}" if row["beat"] is not None else ""
    runs = f"×{row['runs']}" if row["runs"] > 1 else ""
    if row["crashes"]:
        runs += style(f" !{row['crashes']}", 203)
    fixed = f"{row['id']:<11}{row['ticket']:<14}{_clip(row['step'], 16):<17}{_ago(row['age']):>6} {beat:<7}"
    head = (
        f" {style(GLYPHS.get(row['status'], '·'), tone)} {style(fixed[:11], 244)}{style.lane(row['lane'])} {fixed[11:]}"
    )
    room = width - 64 - len(re.sub(r"\033\[[0-9;]*m", "", runs))
    return f"{head}{runs} {style(_clip(row['note'], room), 245)}" if room > 8 and row["note"] else f"{head}{runs}"


def render_board(pack, rows, style, width, everything=False, clock=None) -> list:
    tally = {}
    for row in rows:
        tally[row["status"]] = tally.get(row["status"], 0) + 1
    shown = [f"{style(str(tally[name]), STATUS_TONE.get(name, 250), True)} {name}" for name in ORDER if tally.get(name)]
    closed = sum(count for name, count in tally.items() if name not in OPEN)
    head = f"{style(str(pack.get('board') or 'board'), bold=True)}  " + "  ".join(shown or ["nothing open"])
    lines = [f"{head}  {style(f'{closed} closed', 244)}  {style(clock or time.strftime('%H:%M:%S'), 244)}", ""]
    for name in ORDER:
        group = sorted((row for row in rows if row["status"] == name), key=lambda row: -row["age"])
        if group:
            lines.append(style(name.upper(), STATUS_TONE.get(name, 250), True))
            lines += [_row_line(row, style, width) for row in group] + [""]
    past = sorted((row for row in rows if row["status"] not in OPEN), key=lambda row: -row["closed"])
    past = past if everything else past[:RECENT_CLOSED]
    if past:
        lines.append(style("RECENT" if not everything else "CLOSED", 244, True))
        lines += [_row_line(row, style, width) for row in past]
    return lines


def _plain_args(summary: str) -> str:
    try:
        data = json.loads(summary)
    except ValueError:
        return summary
    if isinstance(data, dict):
        for key in ("command", "code", "path", "expression", "query", "pattern", "url"):
            if data.get(key):
                return str(data[key])
    return summary


def format_entry(entry, style, width, tools=True) -> list:
    """An entry as terminal lines: a time and lane gutter, then what happened."""
    kind = entry.get("kind")
    if kind == "tool_result" and not tools:
        return []
    stamp = _local(str(entry.get("ts") or ""))
    gutter = f"{style(stamp, 240)} {style.lane(_clean(entry.get('who') or '-').replace(chr(10), ' '))} {style(_clip(_clean(entry.get('ticket')).replace(chr(10), ' '), 9).ljust(9), 244)} "
    room = max(width - 32, 24)
    text = _clean(entry.get("text"))
    if kind == "event":
        tone = 203 if entry.get("bad") else 78
        return [f"{gutter}{style('◆ ' + _clip(text.replace(chr(10), ' '), room - 2), tone, True)}"]
    if kind == "tool_use":
        name = _clean(entry.get("name") or "tool")
        body = _clean(_plain_args(str(entry.get("summary") or ""))).replace("\n", " ⏎ ")
        return [f"{gutter}{style('⚙', 111)} {style(name, 111)} {style(_clip(body, room - len(name) - 3), 250)}"]
    if kind == "tool_result":
        first = next((line.strip() for line in text.splitlines() if line.strip()), "")
        return [f"{gutter}{style('↳ ' + _clip(first, room - 2), 241)}"]
    if kind == "prompt":
        first = next((line.strip() for line in text.splitlines() if line.strip()), "")
        return [f"{gutter}{style('▸ ' + _clip(first, room - 2), 244)}"]
    lines = [line.rstrip() for line in text.splitlines() if line.strip()]
    if not lines:
        return []
    pad = " " * 30
    shown = [_clip(line, room) for line in lines[:TEXT_LINES]]
    if len(lines) > TEXT_LINES:
        shown.append(style(f"… {len(lines) - TEXT_LINES} more lines", 241))
    return [gutter + shown[0]] + [pad + line for line in shown[1:]]


class Feed:
    """The rows newer than the last poll: lanes' messages and transcripts of the open cards, and the board's events."""

    def __init__(self, pack, ticket="", lane="", minutes=HISTORY_MINUTES, now=None):
        self.pack, self.ticket, self.lane = pack, ticket, lane
        now = time.time() if now is None else now
        self.start = now - minutes * 60
        self.since = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(self.start))
        self.seen, self.order = set(), deque(maxlen=SEEN_ROWS)
        self.event_id = None
        self.watching = {}
        self.sessions = {}

    def _remember(self, key) -> bool:
        if key in self.seen:
            return False
        if len(self.order) == self.order.maxlen:
            self.seen.discard(self.order[0])
        self.order.append(key)
        self.seen.add(key)
        return True

    def _events(self) -> list:
        connection = _connect(self.pack)
        if connection is None:
            return []
        marks = ",".join("?" * len(EVENTS))
        try:
            if self.event_id is None:
                rows = connection.execute(
                    f"select e.*, t.title, t.assignee from task_events e join tasks t on t.id = e.task_id "
                    f"where e.kind in ({marks}) and e.created_at > ? order by e.id",
                    (*EVENTS, self.start),
                ).fetchall()
                self.event_id = (
                    rows[-1]["id"]
                    if rows
                    else connection.execute("select coalesce(max(id), 0) from task_events").fetchone()[0]
                )
            else:
                rows = connection.execute(
                    f"select e.*, t.title, t.assignee from task_events e join tasks t on t.id = e.task_id "
                    f"where e.kind in ({marks}) and e.id > ? order by e.id",
                    (*EVENTS, self.event_id),
                ).fetchall()
                self.event_id = rows[-1]["id"] if rows else self.event_id
        except sqlite3.Error:
            return []
        finally:
            connection.close()
        found = []
        for row in rows:
            ticket = ticket_of(row["title"] or "") or ""
            found.append(
                {
                    "kind": "event",
                    "who": row["assignee"] or "board",
                    "ticket": ticket,
                    "card": row["task_id"],
                    "bad": row["kind"] in BAD_EVENTS,
                    "text": f"{EVENTS[row['kind']]} · {_step(row['title'] or '', ticket)}",
                    "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(row["created_at"])),
                }
            )
        return found

    def _sessions(self, connection, card) -> list:
        known = self.sessions.get(card["id"])
        if known and time.time() - known[0] < SESSION_REFRESH:
            return known[1]
        named = "%" + card["id"].replace("\\", "\\\\").replace("_", "\\_").replace("%", "\\%") + "%"
        candidates = [
            row[0]
            for row in connection.execute(
                "select distinct session_id from messages where role = 'user' and timestamp >= ? "
                "and content like ? escape '\\'",
                (float(card.get("created_at") or 0) - 60, named),
            )
        ]
        found = []
        for session in candidates:  # a session belongs to the card its first prompt names, as on the Live page
            opener = connection.execute(
                "select content from messages where session_id = ? and role = 'user' order by id limit 1", (session,)
            ).fetchone()
            if _owner(str(opener[0] or "")) in ("", card["id"]):
                found.append(session)
        self.sessions[card["id"]] = (time.time(), found)
        return found

    def _lane(self, card, since: str) -> list:
        path = _profile_db(str(card.get("assignee") or ""))
        if not path:
            return []
        try:
            connection = read_db(path, timeout=2)
            try:
                sessions = self._sessions(connection, card)
                rows = _messages(connection, sessions, since) if sessions else []
            finally:
                connection.close()
        except sqlite3.Error:
            return []
        return _entries(rows, {"src": "lane", "who": card["assignee"], "card": card["id"], "ticket": card["ticket"]})

    def poll(self) -> list:
        # one last read of a card that has just closed, for what it said at the end
        cards = _open_cards(self.pack, tuple(self.watching))
        cards = [
            card
            for card in cards
            if (not self.ticket or card["ticket"] == self.ticket) and (not self.lane or card["assignee"] == self.lane)
        ]
        self.watching = {card["id"]: card for card in cards if card["status"] in OPEN}
        shown = cards
        since = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(max(self.start, time.time() - 30)))
        since = self.since if self.since < since else since
        entries = list(job_rows(shown, since)) if shown else []
        for card in shown:
            entries += self._lane(card, since)
        for event in self._events():
            if (not self.ticket or event["ticket"] == self.ticket) and (not self.lane or event["who"] == self.lane):
                entries.append(event)
        fresh = []
        for entry in sorted(entries, key=lambda row: str(row.get("ts") or "")):
            key = (
                entry.get("card"),
                entry.get("ts"),
                entry.get("kind"),
                str(entry.get("name") or ""),
                str(entry.get("text") or "")[:120],
                str(entry.get("summary") or "")[:120],
            )
            if self._remember(key):
                fresh.append(entry)
        self.since = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - 30))
        return fresh


def _status_line(rows, style, width, ticket="") -> str:
    running = [row for row in rows if row["status"] in ("running", "in_progress")]
    waiting = sum(1 for row in rows if row["status"] in ("ready", "todo", "claimed"))
    blocked = sum(1 for row in rows if row["status"] == "blocked")
    parts = [f"{style.lane(row['lane']).rstrip()} {row['ticket']} {row['step']} {_ago(row['age'])}" for row in running]
    left = f" {style('●', 42 if running else 244)} {len(running)} running · {waiting} waiting · {blocked} blocked" + (
        f" · {ticket}" if ticket else ""
    )
    tail = "   ".join(parts) or style("no card running", 244)
    used = len(re.sub(r"\033\[[0-9;]*m", "", left)) + 14
    plain = re.sub(r"\033\[[0-9;]*m", "", tail)
    tail = tail if len(plain) <= width - used else style(_clip(plain, width - used), 250)
    return f"{left}   {tail}   {style(time.strftime('%H:%M:%S'), 244)}"


def _quit(*_):
    raise KeyboardInterrupt


def _options(args, *values):
    found, rest, index = {}, [], 0
    while index < len(args):
        token = args[index]
        if token in values:
            if index + 1 >= len(args):
                raise ValueError(f"{token} needs a value")
            found[token] = args[index + 1]
            index += 2
            continue
        rest.append(token)
        index += 1
    return found, rest


def run_board(pack, argv) -> int:
    """cockpit board [TICKET] [--status NAME] [--lane NAME] [--all] [--watch] [--json]"""
    found, rest = _options(argv, "--status", "--lane")
    flags = {item for item in rest if item.startswith("--")}
    words = [item for item in rest if not item.startswith("--")]
    if len(words) > 1:
        raise ValueError("stray argument")
    ticket = words[0] if words else ""
    pick = lambda: _filtered(board_rows(pack), ticket, found.get("--lane", ""), found.get("--status", ""))  # noqa: E731
    if "--json" in flags:
        print(json.dumps(pick(), indent=1))
        return 0
    tty = sys.stdout.isatty()
    style = Style(tty and not os.environ.get("NO_COLOR"))
    if "--watch" not in flags or not tty:
        print("\n".join(render_board(pack, pick(), style, _width(), "--all" in flags)))
        return 0
    signal.signal(signal.SIGTERM, _quit)  # the terminal comes back however it ends
    sys.stdout.write("\033[?1049h\033[?25l")
    try:
        while True:
            size = shutil.get_terminal_size((120, 30))
            lines = render_board(pack, pick(), style, _width(), "--all" in flags)[: size.lines - 1]
            sys.stdout.write("\033[H\033[J" + "\n".join(lines))
            sys.stdout.flush()
            time.sleep(BOARD_SECONDS)
    except KeyboardInterrupt:
        return 0
    finally:
        sys.stdout.write("\033[?25h\033[?1049l")
        sys.stdout.flush()


def run_live(pack, argv) -> int:
    """cockpit live [TICKET] [--lane NAME] [--minutes N] [--no-tools] [--once] [--json]"""
    found, rest = _options(argv, "--lane", "--minutes")
    flags = {item for item in rest if item.startswith("--")}
    words = [item for item in rest if not item.startswith("--")]
    if len(words) > 1:
        raise ValueError("stray argument")
    try:
        minutes = float(found.get("--minutes", HISTORY_MINUTES))
    except ValueError as exc:
        raise ValueError("--minutes needs a number") from exc
    ticket = words[0] if words else ""
    feed = Feed(pack, ticket, found.get("--lane", ""), minutes)
    tty = sys.stdout.isatty()
    style = Style(tty and not os.environ.get("NO_COLOR"))
    tools = "--no-tools" not in flags
    pinned = tty and "--once" not in flags and "--json" not in flags
    resized = [True]
    if pinned:
        signal.signal(signal.SIGWINCH, lambda *_: resized.__setitem__(0, True))
        signal.signal(signal.SIGTERM, _quit)

    def show(entries):
        for entry in entries:
            if "--json" in flags:
                print(json.dumps({key: value for key, value in entry.items() if key != "html"}))
                continue
            for line in format_entry(entry, style, _width(), tools):
                print(line)
        sys.stdout.flush()

    try:
        while True:
            entries = feed.poll()
            if pinned and resized[0]:
                resized[0] = False
                rows_on_screen = shutil.get_terminal_size((120, 30)).lines
                sys.stdout.write(f"\033[1;{rows_on_screen - 1}r\033[{rows_on_screen - 1};1H")
            show(entries)
            if "--once" in flags:
                return 0
            if pinned:
                rows_on_screen = shutil.get_terminal_size((120, 30)).lines
                line = _status_line(
                    _filtered(board_rows(pack), ticket, found.get("--lane", "")), style, _width(), ticket
                )
                sys.stdout.write(f"\0337\033[{rows_on_screen};1H\033[2K{line}\0338")
                sys.stdout.flush()
            time.sleep(POLL_SECONDS)
    except KeyboardInterrupt:
        return 0
    finally:
        if pinned:
            rows_on_screen = shutil.get_terminal_size((120, 30)).lines
            sys.stdout.write(f"\033[r\033[{rows_on_screen};1H\033[2K\n")
            sys.stdout.flush()
