# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""One payload for the Cockpit page. Each pane reads this. Nothing is invented."""

import os
import sqlite3

from cockpitlib.intents import all_intents
from cockpitlib.kanban import OPEN, db_path
from cockpitlib.lanes import seats_from
from cockpitlib.paths import qa, qa_of, watch_dir, workspace
from cockpitlib.plan import sections
from cockpitlib.settings import load as load_settings
from cockpitlib.setup import gateway_status
from cockpitlib.store import read_db

PANES = ("inbox", "outbox", "board", "live", "tickets", "qa", "platform", "usage", "settings", "chat")


def _chain_hidden(rows) -> set:
    """A chain's first step stays hidden until the following intent is endorsed."""
    shown = {"endorsed", "posted", "published", "published-manually"}
    hidden = set()
    for row in rows:
        parent = (row.get("payload") or {}).get("after") or ""
        if parent and row.get("status") not in shown:
            hidden.add(parent)
    return hidden


def build(pack, capacity) -> dict:
    raw = all_intents()
    hidden = _chain_hidden(raw)
    intents = [_public(row) for row in raw]
    counts = _card_counts(pack["board"])
    inbox = _inbox([row for row in intents if row["id"] not in hidden]) + _watcher_rows(pack) + _comment_rows()
    return {
        "name": pack["name"],
        "display_name": pack["providers"]["coding"].get("display_name") or "Chat",
        "board": pack["board"],
        "gateway": gateway_status(),
        "need_you": len(inbox),
        "capacity": capacity,
        "inbox": inbox,
        "outbox": intents,
        "board_cards": _cards(pack["board"]),
        "live": _live(pack, counts),
        "tickets": _tickets(intents, _cards(pack["board"])),
        "qa": _qa_files(),
        "platform": _platform(),
        "usage": load_settings(pack),
        "settings": load_settings(pack),
        "chat": {
            "display_name": pack["providers"]["coding"].get("display_name") or "Chat",
            "sessions": _chat_sessions(),
        },
        "panes": list(PANES),
    }


def _public(row) -> dict:
    payload = row.get("payload") or {}
    return {
        "id": row.get("id") or "",
        "type": row.get("type") or "",
        "status": row.get("status") or "",
        "ticket": row.get("ticket") or "",
        "lane": row.get("created_by") or "",
        "summary": row.get("agent_summary") or "",
        "leaves": row.get("agent_summary") or "",
        "repo": payload.get("repo") or "",
        "ask": payload.get("ask") or "",
        "options": payload.get("options") or [],
    }


def _inbox(intents) -> list:
    rows = []
    for row in intents:
        kind = _inbox_kind(row)
        if not kind:
            continue
        rows.append(
            {
                "kind": kind,
                "id": row["id"],
                "ticket": row["ticket"],
                "lane": row["lane"],
                "summary": row["summary"],
                "ask": row["ask"],
                "options": row["options"],
            }
        )
    return rows


def _inbox_kind(row) -> str:
    status = row["status"]
    if row["type"] == "ticket-done" and status in ("pending", "endorsed"):
        return "confirm done"
    if status == "endorsed":
        return "publish"
    if status == "posted":
        return "publish review"
    if status == "held" and row["ask"]:
        return "decide"
    if status == "held":
        return "resolve hold"
    return ""


def _comment_rows() -> list:
    """New comments are one inbox row per pull request. A scan with none adds nothing."""
    from cockpitlib.pr_watch import inbox_rows

    rows = []
    for item in inbox_rows():
        count = len(item.get("new") or [])
        rows.append(
            {
                "kind": "new comments",
                "id": f"{item['repo']}#{item['number']}",
                "ticket": item.get("ticket") or "",
                "lane": "",
                "summary": f"{count} new comments on {item['repo']}#{item['number']}",
                "ask": "",
                "options": [],
            }
        )
    return rows


def _watcher_rows(pack) -> list:
    from cockpitlib.health import watcher_rows

    rows = []
    for item in watcher_rows(pack, watch_dir()):
        record = item["record"]
        rows.append(
            {
                "kind": "fix watcher",
                "id": item["name"],
                "ticket": "",
                "lane": "",
                "summary": item["reason"],
                "output": record.get("output") or "",
                "ask": "",
                "options": [],
            }
        )
    return rows


def _cards(slug) -> list:
    path = db_path(slug)
    if not os.path.isfile(path):
        return []
    connection = read_db(path)
    try:
        rows = connection.execute("select id, title, assignee, status from tasks").fetchall()
    except sqlite3.Error:
        return []
    finally:
        connection.close()
    return [{"id": row[0], "title": row[1] or "", "lane": row[2] or "", "status": row[3] or ""} for row in rows]


def _card_counts(slug) -> dict:
    counts = {}
    for card in _cards(slug):
        if card["status"] not in OPEN:
            continue
        if not card["lane"]:
            continue
        counts[card["lane"]] = counts.get(card["lane"], 0) + 1
    return counts


def _live(pack, counts) -> list:
    rows = []
    for kind, names in seats_from(pack).items():
        for lane in names:
            rows.append({"lane": lane, "kind": kind, "open": counts.get(lane, 0)})
    return rows


def _tickets(intents, cards=None) -> list:
    from cockpitlib.kanban import ticket_of

    grouped = {}
    for row in intents:
        bucket = grouped.setdefault(row["ticket"], {"ticket": row["ticket"], "intents": [], "plan": [], "cards": []})
        bucket["intents"].append(row["id"])
    for card in cards or []:
        ticket = ticket_of(card.get("title") or "")
        if not ticket:
            continue
        bucket = grouped.setdefault(ticket, {"ticket": ticket, "intents": [], "plan": [], "cards": []})
        bucket.setdefault("cards", [])
        bucket["cards"].append(card.get("title") or "")
    root = qa()
    if os.path.isdir(root):
        for name in sorted(os.listdir(root)):
            if name.startswith("_") or not os.path.isdir(qa_of(name)):
                continue
            grouped.setdefault(name, {"ticket": name, "intents": [], "plan": []})
    for ticket, bucket in grouped.items():
        bucket["plan"] = sections(ticket)
    return [grouped[key] for key in sorted(grouped)]


def _qa_files() -> list:
    root = qa()
    found = []
    if not os.path.isdir(root):
        return found
    for dirpath, dirs, files in os.walk(root):
        dirs[:] = [name for name in dirs if not name.startswith(".")]
        for name in sorted(files):
            if name.startswith("."):
                continue
            found.append(os.path.relpath(os.path.join(dirpath, name), root))
            if len(found) >= 200:
                return found
    return found


def _platform() -> dict:
    path = os.path.join(workspace(), "map.yaml")
    if not os.path.isfile(path):
        return {"hidden": True, "text": ""}
    return {"hidden": False, "text": open(path, encoding="utf-8").read()[:8000]}


def _chat_sessions() -> list:
    root = qa()
    found = []
    if not os.path.isdir(root):
        return found
    for name in sorted(os.listdir(root)):
        if os.path.isfile(qa_of(name, "chat.json")):
            found.append(name)
    return found
