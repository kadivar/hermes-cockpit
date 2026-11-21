# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The plan gate on a worker card. `Plan gate: human` in the card body (or an advisor verdict at C0 other than the
checkpoint's first answer) means the worker blocks for "plan ok" after C0, and its pushes wait until the human said it."""

import re
import sqlite3

from .store import read_db

GATE_LINE = re.compile(r"^\s*Plan gate:\s*(auto|human)\s*$", re.M | re.I)
PLAN_OK = re.compile(
    r"^human:\s*(?:plan ok|go)\b", re.I
)  # the Inbox's answer to a blocked card is "go" (or "go with changes: ...")


def _card(pack, card: str) -> dict:
    from .skill_log import card_of

    return card_of((pack or {}).get("board") or "", card)


def declared(body: str) -> str:
    found = GATE_LINE.search(body or "")
    return found.group(1).lower() if found else "auto"


def _deviated(pack, ticket: str, card: str) -> bool:
    """An advisor answer at C0 that holds the worker: one the pack lists in C0's block_on, else any but the first. An answer
    that could not be read (the card's newest C0 row has no verdict, only a reason) holds too, until a later one reads."""
    from .advise import calls, config

    entry = (config(pack).get("checkpoints") or {}).get("C0") or {}
    first = (entry.get("answers") or [""])[0]
    block_on = entry.get("block_on")

    def holds(verdict):
        return verdict in block_on if isinstance(block_on, list) else verdict != first

    rows = [row for row in calls(ticket) if row.get("card") == card and row.get("checkpoint") == "C0"]
    unread = bool(rows) and not rows[-1].get("verdict") and bool(rows[-1].get("reason"))
    return unread or any(row.get("verdict") and holds(row["verdict"]) for row in rows)


def gate(pack, card: str) -> str:
    """human or auto, for this card."""
    found = _card(pack, card)
    if not found:
        return "auto"
    if declared(found.get("body") or "") == "human" or _deviated(pack, found.get("ticket") or "", card):
        return "human"
    return "auto"


def _plan_asked_at(pack, connection, card: str) -> float:
    """When the card stopped at its plan: the earliest of its first C0 advisor call and its first block that names the plan,
    else 0. The earliest, because an in-tool advisor's line may be recorded after the human already answered the plan."""
    found = _card(pack, card)
    from datetime import datetime

    from .advise import calls

    times = []
    for row in calls((found or {}).get("ticket") or ""):
        if row.get("card") == card and row.get("checkpoint") == "C0" and row.get("time"):
            try:
                times.append(datetime.fromisoformat(str(row["time"]).replace("Z", "+00:00")).timestamp())
            except ValueError:
                continue
    try:
        blocks = connection.execute(
            "select payload, created_at from task_events where task_id = ? and kind = 'blocked' order by id", (card,)
        ).fetchall()
    except sqlite3.Error:
        blocks = []
    times.extend(float(at or 0) for payload, at in blocks if re.search(r"plan|\bC0\b", str(payload or ""), re.I))
    return min(times) if times else 0.0


def said_ok(pack, card: str) -> bool:
    """The human said "plan ok" (or the Inbox's "go") on this card after it stopped at its plan. A comment a lane writes
    (any author but `human`) never counts, nor a "go" that answered an earlier, unrelated question."""
    from .kanban import db_path

    try:
        connection = read_db(db_path(pack["board"]))
    except sqlite3.Error:
        return False
    try:
        rows = connection.execute(
            "select author, body, created_at from task_comments where task_id = ?", (card,)
        ).fetchall()
        since = _plan_asked_at(pack, connection, card)
    except sqlite3.Error:
        rows, since = [], 0.0
    finally:
        connection.close()
    return any(
        author == "human" and PLAN_OK.match(str(body or "")) and float(at or 0) >= since for author, body, at in rows
    )


def waits(pack, card: str) -> str:
    """Why a push from this card waits, or empty."""
    if not card or gate(pack, card) != "human" or said_ok(pack, card):
        return ""
    return f"plan gate: card {card} waits for the human's plan ok"
