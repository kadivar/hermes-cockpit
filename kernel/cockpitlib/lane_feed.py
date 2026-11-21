# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""What the Live page streams: a card's details and conversation on the board, a ticket's job stream, and the tail of a
lane's run log. Read-only; a log outside the board's log folder is not read.

A job stream keeps the newest rows of each lane (PER_LANE), never the newest rows of all of them together: one busy lane
must not push the others out of view. A lane's session belongs to the card that started it, so a session that names
other cards along the way is shown once, not once per card it names.

Another plugin may show its own Hermes profile there (the supervisor's brain, say) by writing
<Hermes home>/cockpit/live/<plugin>.json = {"profile": "<profile>", "label": "<how Live names it>"}. Cockpit then reads
that profile's sessions and shows each under the ticket its first prompt names. Nothing else is learned about the plugin.
"""

import json
import os
import re
import sqlite3
import time

from .store import read_db

TAIL_BYTES = 64 * 1024
LIVE_SECONDS = 30
PER_LANE = 300  # the newest rows a job stream keeps of each lane
CARD_ID = re.compile(r"\bt_[0-9a-f]+\b")  # a Hermes board card id, as the Desktop reads it (t_<hex>)
NAME = re.compile(r"[A-Za-z0-9_.-]+")


def _connect(pack):
    from .kanban import db_path

    path = db_path((pack or {}).get("board") or "")
    if not os.path.isfile(path):
        return None
    return read_db(path)


def logs_dir(pack) -> str:
    from .kanban import db_path

    return os.path.join(os.path.dirname(db_path((pack or {}).get("board") or "")), "logs")


def card(pack, card_id: str) -> dict:
    """One card: its fields, comments, events and runs."""
    from .activity import _stamp
    from .render import markdown

    connection = _connect(pack)
    found = {"id": card_id, "comments": [], "events": [], "runs": []}
    if connection is None or not card_id:
        return found
    connection.row_factory = sqlite3.Row
    try:
        row = connection.execute("select * from tasks where id = ?", (card_id,)).fetchone()
        if row is None:
            return found
        task = dict(row)
        found.update({key: task.get(key) for key in ("title", "status", "assignee", "body", "result", "block_kind")})
        found["body_html"] = markdown(task.get("body") or "")
        found["result_html"] = markdown(task.get("result") or "")
        tables = {item[0] for item in connection.execute("select name from sqlite_master where type = 'table'")}
        if "task_comments" in tables:
            found["comments"] = [
                {
                    "author": item["author"],
                    "body": item["body"],
                    "html": markdown(item["body"]),
                    "ts": _stamp(item["created_at"]),
                }
                for item in connection.execute("select * from task_comments where task_id = ? order by id", (card_id,))
            ]
        if "task_events" in tables:
            found["events"] = [
                {"kind": item["kind"], "payload": item["payload"], "ts": _stamp(item["created_at"])}
                for item in connection.execute("select * from task_events where task_id = ? order by id", (card_id,))
            ]
        if "task_runs" in tables:
            found["runs"] = [
                {
                    key: item[key]
                    for key in item.keys()
                    if key in ("id", "profile", "status", "outcome", "summary", "error", "started_at", "ended_at")
                }
                for item in connection.execute("select * from task_runs where task_id = ? order by id", (card_id,))
            ]
    finally:
        connection.close()
    return found


def _epoch(text: str) -> float:
    import datetime

    try:
        return datetime.datetime.fromisoformat(str(text).replace("Z", "+00:00")).timestamp() if text else 0.0
    except ValueError:
        return 0.0


def jobs(pack) -> list:
    """Every ticket with cards or outbox items, the newest activity first: [{ticket, last}]."""
    from .activity import _stamp
    from .intents import all_intents
    from .kanban import ticket_of

    newest = {}
    connection = _connect(pack)
    if connection is not None:
        try:
            for title, last in connection.execute(
                "select t.title, max(e.created_at) from tasks t join task_events e on e.task_id = t.id group by t.id"
            ):
                ticket = ticket_of(title or "")
                if ticket:
                    newest[ticket] = max(newest.get(ticket, 0.0), float(last or 0))
        except sqlite3.Error:
            pass
        finally:
            connection.close()
    for row in all_intents():
        ticket = row.get("ticket") or ""
        if ticket:
            newest[ticket] = max(newest.get(ticket, 0.0), _epoch(row.get("created_at") or ""))
    ordered = sorted(newest.items(), key=lambda item: item[1], reverse=True)
    return [{"ticket": ticket, "last": _stamp(last) if last else ""} for ticket, last in ordered]


LANE_MESSAGES = 400


def _profile_db(profile: str) -> str:
    from .paths import hermes_home

    if not NAME.fullmatch(str(profile or "")):
        return ""
    path = os.path.join(hermes_home(), "profiles", profile, "state.db")
    return path if os.path.isfile(path) else ""


def _openers(connection) -> dict:
    """session -> its first prompt: what the session was started for."""
    firsts = [
        row[0] for row in connection.execute("select min(id) from messages where role = 'user' group by session_id")
    ]
    found = {}
    for start in range(0, len(firsts), 500):
        chunk = firsts[start : start + 500]
        marks = ",".join("?" * len(chunk))
        found.update(
            {
                session: str(content or "")
                for session, content in connection.execute(
                    f"select session_id, content from messages where id in ({marks})", tuple(chunk)
                )
            }
        )
    return found


class LaneIndex:
    """One profile's sessions, read once per stream: the card each belongs to, and which have news after `since`.
    A session belongs to the card its first prompt names; one whose first prompt names none belongs to every card
    its prompts name, as before."""

    def __init__(self, connection, since: str = ""):
        self.openers = _openers(connection)
        self.by_card = {}
        loose = []
        for session, opener in self.openers.items():
            owner = _owner(opener)
            if owner:
                self.by_card.setdefault(owner, []).append(session)
            else:
                loose.append(session)
        for start in range(0, len(loose), 500):
            chunk = loose[start : start + 500]
            marks = ",".join("?" * len(chunk))
            for session, content in connection.execute(
                f"select session_id, content from messages where role = 'user' and session_id in ({marks})",
                tuple(chunk),
            ):
                for card_id in set(CARD_ID.findall(str(content or ""))):
                    if session not in self.by_card.setdefault(card_id, []):
                        self.by_card[card_id].append(session)
        self.fresh = {
            row[0]
            for row in connection.execute(
                "select session_id from messages group by session_id having max(timestamp) > ?", (_epoch(since),)
            )
        }

    def sessions(self, card_id: str) -> list:
        return [session for session in self.by_card.get(card_id, []) if session in self.fresh]


def _owner(opener: str) -> str:
    """The card a session was started for: the first card its first prompt names, or none."""
    found = CARD_ID.search(opener or "")
    return found.group(0) if found else ""


def _entries(rows, base: dict) -> list:
    """Hermes messages (role, content, tool_calls, tool_name, timestamp) as Live entries."""
    from .activity import _stamp
    from .render import markdown

    found = []
    for role, content, calls, tool, stamp in rows:
        when = _stamp(stamp)
        text = str(content or "")
        if role == "tool":
            found.append({**base, "kind": "tool_result", "name": tool or "", "text": text[:3000], "ts": when})
            continue
        if text.strip():
            found.append(
                {
                    **base,
                    "kind": "prompt" if role == "user" else "text",
                    "text": text[:12000],
                    "html": markdown(text[:12000]),
                    "ts": when,
                }
            )
        try:
            listed = json.loads(calls) if calls else []
        except ValueError:
            listed = []
        for call in listed if isinstance(listed, list) else []:
            function = call.get("function") if isinstance(call, dict) and isinstance(call.get("function"), dict) else {}
            arguments = str(function.get("arguments") or "")
            found.append(
                {
                    **base,
                    "kind": "tool_use",
                    "name": str(function.get("name") or "tool"),
                    "summary": arguments[:240],
                    "input": arguments[:8000],
                    "text": "",
                    "ts": when,
                }
            )
    return found


def _messages(connection, sessions, since: str) -> list:
    marks = ",".join("?" * len(sessions))
    rows = connection.execute(
        f"select role, content, tool_calls, tool_name, timestamp from messages where session_id in ({marks}) "
        f"and timestamp > ? order by timestamp desc, id desc limit ?",
        (*sessions, _epoch(since), LANE_MESSAGES),
    ).fetchall()
    return list(reversed(rows))


def lane_messages(card: dict, since: str = "", indexes=None) -> list:
    """The lane's own conversation on this card, from the lane profile's state.db (Hermes writes it whatever coding tool the lane
    drives): the messages of the lane's sessions that belong to this card (LaneIndex). Read-only; no database, no table:
    none. `indexes` (profile path -> LaneIndex) lets a stream over many cards read each profile once."""
    lane = str(card.get("assignee") or "")
    card_id = str(card.get("id") or "")
    path = _profile_db(lane)
    if not card_id or not path:
        return []
    try:
        connection = read_db(path)
        try:
            index = (indexes or {}).get(path)
            if index is None:
                index = LaneIndex(connection, since)
                if indexes is not None:
                    indexes[path] = index
            sessions = index.sessions(card_id)
            rows = _messages(connection, sessions, since) if sessions else []
        finally:
            connection.close()
    except sqlite3.Error:
        return []
    return _entries(rows, {"src": "lane", "who": lane, "card": card_id, "ticket": card.get("ticket") or ""})


def live_sources() -> list:
    """The Hermes profiles other plugins asked Live to show: <Hermes home>/cockpit/live/<plugin>.json. A file that is not
    {profile, label?} with plain names is left out."""
    from .paths import hermes_home

    folder = os.path.join(hermes_home(), "cockpit", "live")
    found = []
    for name in sorted(os.listdir(folder)) if os.path.isdir(folder) else []:
        plugin = name[:-5]
        if not name.endswith(".json") or not NAME.fullmatch(plugin):
            continue
        try:
            data = json.load(open(os.path.join(folder, name), encoding="utf-8"))
        except (OSError, ValueError):
            continue
        profile = str((data or {}).get("profile") or "") if isinstance(data, dict) else ""
        label = str((data or {}).get("label") or plugin).strip()[:40] if isinstance(data, dict) else ""
        if NAME.fullmatch(profile) and label:
            found.append({"plugin": plugin, "profile": profile, "label": label})
    return found


def source_messages(source: dict, cards: list, tickets: list, since: str = "") -> list:
    """A plugin's profile in a job stream: each of its sessions under the ticket it was started for (the card its first
    prompt names, else the first of these tickets it names); a session about none of them is left out."""
    from .kanban import mentions

    path = _profile_db(source.get("profile") or "")
    if not path or not tickets:
        return []
    ticket_of_card = {item["id"]: item.get("ticket") or "" for item in cards}
    try:
        connection = read_db(path)
        try:
            index = LaneIndex(connection, since)
            found = []
            for session, opener in index.openers.items():
                if session not in index.fresh:
                    continue
                card_id = _owner(opener)
                ticket = ticket_of_card.get(card_id) or next((name for name in tickets if mentions(opener, name)), "")
                if ticket not in tickets:
                    continue
                found += _entries(
                    _messages(connection, [session], since),
                    {
                        "src": "lane",
                        "who": source["label"],
                        "card": card_id if card_id in ticket_of_card else "",
                        "ticket": ticket,
                    },
                )
        finally:
            connection.close()
    except sqlite3.Error:
        return []
    return found


def per_lane(entries: list, limit: int = PER_LANE) -> list:
    """The newest `limit` rows of each lane (a row without a lane counts as its own), oldest first; one row once."""
    seen, kept, counts = set(), [], {}
    for entry in sorted(entries, key=lambda row: row["ts"], reverse=True):
        key = (
            entry.get("src"),
            entry.get("who"),
            entry.get("card"),
            entry["ts"],
            entry.get("kind"),
            str(entry.get("text") or "")[:200],
        )
        if key in seen:
            continue
        seen.add(key)
        who = entry.get("who") or ""
        if counts.get(who, 0) >= limit:
            continue
        counts[who] = counts.get(who, 0) + 1
        kept.append(entry)
    return kept[::-1]


def lane_stream(pack, card_id: str, since: str = "") -> dict:
    """A card's conversation on the board (its comments and events) after `since`."""
    shown = card(pack, card_id)
    entries = [
        {
            "src": "hermes",
            "who": item["author"],
            "kind": "text",
            "text": item["body"],
            "html": item["html"],
            "ts": item["ts"],
        }
        for item in shown["comments"]
    ]
    from .activity import counts

    entries += [
        {
            "src": "hermes",
            "who": shown.get("assignee") or "",
            "kind": str(item["kind"]),
            "text": str(item["payload"] or ""),
            "ts": item["ts"],
        }
        for item in shown["events"]
        if counts(str(item["kind"]))
    ]
    entries += lane_messages({"id": card_id, "assignee": shown.get("assignee") or ""}, since)
    entries = sorted((entry for entry in entries if entry["ts"] > (since or "")), key=lambda entry: entry["ts"])
    return {
        "card": card_id,
        "since": since,
        "entries": entries,
        "last": entries[-1]["ts"] if entries else since,
        "running": shown.get("status") == "running",
    }


def job_stream(pack, ticket: str = "", since: str = "") -> dict:
    """A ticket's steps (every ticket's when none is named), as board rows."""
    from .activity import ticket_activity
    from .kanban import board_cards
    from .render import markdown

    cards = board_cards((pack or {}).get("board") or "")
    tickets = (
        [ticket] if ticket and ticket != "all" else sorted({item["ticket"] for item in cards if item.get("ticket")})
    )
    limit = ((pack or {}).get("desktop") or {}).get("live_jobs")
    if ticket in ("", "all") and limit:  # the pack's newest jobs only
        tickets = [row["ticket"] for row in jobs(pack)][: int(limit)]
    entries = []
    for name in tickets:
        for row in ticket_activity(pack, name, since):
            entries.append(
                {
                    **row,
                    "src": "board",
                    "ticket": name,
                    "title": row.get("title") or row.get("text") or "",
                    "html": markdown(row.get("text") or "") if row.get("kind") == "comment" else "",
                }
            )
    from .lane_transcripts import job_rows

    shown = [item for item in cards if item.get("ticket") in tickets]
    entries += job_rows(shown, since)
    indexes = {}
    for item in shown:
        entries += lane_messages(item, since, indexes)
    sources = live_sources()
    for source in sources:
        entries += source_messages(source, cards, tickets, since)
    entries = per_lane(entries)
    running = any(item.get("status") == "running" and item.get("ticket") in tickets for item in cards)
    lanes = sorted({item.get("assignee") for item in shown if item.get("assignee")}) + [
        source["label"] for source in sources
    ]
    from .lanes import live_order

    return {
        "ticket": ticket,
        "since": since,
        "entries": entries,
        "last": entries[-1]["ts"] if entries else since,
        "running": running,
        "lanes": lanes,
        "per_lane": PER_LANE,
        "lane_order": live_order(pack),
    }


def lane_tail(pack, path: str, offset: int = -1) -> dict:
    """New text of a lane's run log from `offset` (-1: the last 64 KB). A path outside the board's logs is refused."""
    from .errors import CockpitError

    folder = os.path.realpath(logs_dir(pack))
    real = os.path.realpath(path or "")
    if not real.startswith(folder + os.sep) or not os.path.isfile(real):
        raise CockpitError("not a lane run log")
    size = os.path.getsize(real)
    start = max(0, size - TAIL_BYTES) if offset is None or offset < 0 or offset > size else offset
    with open(real, "rb") as handle:
        handle.seek(start)
        text = handle.read(size - start).decode("utf-8", "replace")
    running = time.time() - os.path.getmtime(real) < LIVE_SECONDS
    return {"path": path, "offset": size, "text": text, "running": running}
