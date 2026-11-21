# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""A ticket's activity: what its intents went through, and what happened on its cards. Which board events count as the
ticket moving, and which are housekeeping."""

import datetime
import json
import os
import sqlite3

from .store import read_db

# A card's heartbeat is liveness, not a step: the board shows it ("alive · heartbeat N ago"). As activity it was one empty
# row a minute per running card, each counted against its lane's row limit in a job stream, so it pushed the lane's real
# messages out of Live.
HOUSEKEEPING = {"slot-assign", "unblock-login", "watcher", "sweep", "heartbeat"}


def counts(kind: str) -> bool:
    return kind not in HOUSEKEEPING


def _stamp(epoch) -> str:
    from .time_util import iso

    try:
        return iso(datetime.datetime.fromtimestamp(float(epoch), datetime.UTC))
    except (TypeError, ValueError, OverflowError, OSError):
        return ""


def lane_label(name) -> str:
    """A lane as the pages name it. An earlier watcher wrote its home folder's name (".hermes") where its lane goes;
    that was cockpit's own watcher, not a lane."""
    text = str(name or "")
    return "cockpit" if text.startswith(".") else text


def _intent_rows(ticket: str) -> list:
    from .intents import all_intents

    rows = []
    for intent in all_intents(ticket):
        what = f"{intent.get('type')} {intent.get('id')}"

        def add(ts, who, kind, text=""):
            if ts:
                rows.append(
                    {
                        "ts": ts,
                        "src": "outbox",
                        "who": lane_label(who),
                        "kind": kind,
                        "intent": intent.get("id"),
                        "text": f"{what}" + (f": {text}" if text else ""),
                    }
                )

        add(intent.get("created_at"), intent.get("created_by"), "written", intent.get("summary") or "")
        endorsement = intent.get("endorsement") or {}
        add(endorsement.get("time"), endorsement.get("by") or "gatekeeper", "endorsed", endorsement.get("risk") or "")
        hold = intent.get("hold") or {}
        add(hold.get("time"), hold.get("by") or "gatekeeper", "held", hold.get("reason") or "")
        returned = intent.get("returned") or {}
        add(returned.get("time"), returned.get("by"), "returned", returned.get("instruction") or "")
        human = intent.get("human") or {}
        add(human.get("time"), "human", human.get("decision") or "decided", human.get("note") or "")
        receipt = intent.get("receipt") or {}
        if receipt:
            add(
                receipt.get("time"),
                "cockpit",
                "published" if receipt.get("ok") else "refused",
                receipt.get("url") or receipt.get("error") or "",
            )
        for event in intent.get("history") or []:
            if isinstance(event, dict):
                add(event.get("time"), event.get("by") or "", "history", event.get("event") or "")
    return rows


def _board_rows(pack, ticket: str) -> list:
    from .kanban import db_path, ticket_of

    path = db_path((pack or {}).get("board") or "")
    if not os.path.isfile(path):
        return []
    rows = []
    connection = read_db(path)
    try:
        cards = {
            row[0]: (row[1] or "", row[2] or "")
            for row in connection.execute("select id, title, assignee from tasks")
            if ticket_of(row[1] or "") == ticket
        }
        tables = {row[0] for row in connection.execute("select name from sqlite_master where type = 'table'")}
        marks = ",".join("?" * len(cards))
        if cards and "task_events" in tables:
            for card, kind, payload, created in connection.execute(
                f"select task_id, kind, payload, created_at from task_events where task_id in ({marks})", tuple(cards)
            ):
                if not counts(str(kind)):
                    continue
                try:
                    detail = json.loads(payload) if payload else {}
                except ValueError:
                    detail = {}
                reason = (detail.get("reason") or detail.get("summary") or "") if isinstance(detail, dict) else ""
                rows.append(
                    {
                        "ts": _stamp(created),
                        "src": "board",
                        "who": cards[card][1],
                        "kind": str(kind),
                        "card": card,
                        "title": cards[card][0],
                        "text": str(reason or ""),
                    }
                )
        if cards and "task_comments" in tables:
            for card, author, body, created in connection.execute(
                f"select task_id, author, body, created_at from task_comments where task_id in ({marks})", tuple(cards)
            ):
                rows.append(
                    {
                        "ts": _stamp(created),
                        "src": "board",
                        "who": author or "",
                        "kind": "comment",
                        "card": card,
                        "title": cards[card][0],
                        "text": str(body or "")[:2000],
                    }
                )
    except sqlite3.Error:
        rows = []
    finally:
        connection.close()
    return rows


def ticket_activity(pack, ticket: str, since: str = "", limit: int = 500) -> list:
    """Every recorded step of the ticket, oldest first; `since` keeps only what came after that time."""
    rows = [row for row in _intent_rows(ticket) + _board_rows(pack, ticket) if row["ts"] and row["ts"] > (since or "")]
    rows.sort(key=lambda row: (row["ts"], row["src"]))
    return rows[-limit:]
