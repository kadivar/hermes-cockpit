# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The board as the page reads it: every open card and the done ones of the last days, each with its ticket, lane, run
state, the question when blocked and the last comment line; a card's Brief and the records it mentions. Read-only."""

import html
import json
import os
import re
import sqlite3
import time
from datetime import UTC

from .store import read_db

COLUMNS = [
    "triage",
    "todo",
    "ready",
    "claimed",
    "in_progress",
    "running",
    "review",
    "blocked",
    "done",
    "archived",
    "cancelled",
]
CLOSED = ("done", "archived", "cancelled")
ALIVE_SECONDS = 180
BLOCK_KEYS = ("question", "reason", "message", "summary_preview", "result_preview")


def _connect(pack):
    from .kanban import db_path

    path = db_path((pack or {}).get("board") or "")
    if not os.path.isfile(path):
        return None
    connection = read_db(path)
    connection.row_factory = sqlite3.Row
    return connection


def _tables(connection) -> set:
    return {row[0] for row in connection.execute("select name from sqlite_master where type = 'table'")}


def _columns(connection, table) -> set:
    return {row[1] for row in connection.execute(f"pragma table_info({table})")}


def _iso(value) -> str:
    if value in (None, ""):
        return ""
    if isinstance(value, str) and not value.replace(".", "", 1).isdigit():
        return value
    stamp = float(value)
    if stamp > 1e12:
        stamp = stamp / 1000
    from datetime import datetime

    return datetime.fromtimestamp(stamp, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _epoch(value) -> float:
    if value in (None, ""):
        return 0.0
    try:
        stamp = float(value)
        return stamp / 1000 if stamp > 1e12 else stamp
    except (TypeError, ValueError):
        pass
    from datetime import datetime

    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return 0.0


def block_question(payloads) -> str:
    """What the lane asked when it blocked: the first telling field of the newest block event."""
    for payload in payloads:
        try:
            data = json.loads(payload or "{}") if isinstance(payload, str) else (payload or {})
        except ValueError:
            data = {}
        if not isinstance(data, dict):
            continue
        found = next((str(data[key]) for key in BLOCK_KEYS if data.get(key)), "")
        if found:
            return found
    return ""


def _block_payloads(connection, card_id: str, tables) -> list:
    if "task_events" not in tables:
        return []
    return [
        row["payload"]
        for row in connection.execute(
            "select payload from task_events where task_id = ? and kind like '%block%' order by created_at desc limit 3",
            (card_id,),
        )
    ]


DONE_DAYS = 2
# A tracker ticket ends in its number (ACME-930). A key that does not (ACME-PLATFORM, REL-2-0-0) groups cockpit's or a
# plugin's own work: it keeps the days window, or one open item would bring back all of its history.
TRACKER_TICKET = re.compile(r"-\d+$")


def done_days(pack) -> int:
    """How many days a finished ticket's done cards stay on the Board: the pack's board_done_days, else two."""
    value = (pack or {}).get("board_done_days")
    return DONE_DAYS if value is None else int(value)


def live_tickets(pack, open_tickets=()) -> dict:
    """Tracker tickets whose lifecycle is not over, and what each waits for: work (an open card), publish (an open
    outbox item), merge (a PR of it the watch still sees open), confirm (its ticket-done waiting for the human's ack),
    release (a plugin's running release owns it).
    A live ticket keeps every card on the Board, whatever its age."""
    from .intents import OPEN_STATUSES, all_intents
    from .pr_watch import open_pr_tickets

    live = {}

    def add(ticket, why):
        if ticket and TRACKER_TICKET.search(ticket) and why not in live.setdefault(ticket, []):
            live[ticket].append(why)

    for ticket in open_tickets:
        add(ticket, "work")
    for intent in all_intents():
        if intent.get("status") in OPEN_STATUSES:
            add(intent.get("ticket") or "", "confirm" if intent.get("type") == "ticket-done" else "publish")
    for ticket in open_pr_tickets():
        add(ticket, "merge")
    from .owners import owned

    for ticket in owned():
        add(ticket, "release")  # a running release's ticket: it lands with the release
    return live


STALE_GATE_DAYS = 2  # a pending intent nothing has touched for this long is not work in hand: it is stale


def stale_days(intent, now=None) -> int:
    """Whole days a pending intent has sat with nothing touching it (its newest history line, else when it was made),
    once that is STALE_GATE_DAYS or more; 0 for any other intent. The Outbox marks such a row stale and the Board gives
    it no card: a pile of them, each "with the gatekeeper", read as open work nobody would ever do."""
    if intent.get("status") != "pending":
        return 0
    stamps = [intent.get("created_at")] + [
        row.get("time") for row in intent.get("history") or [] if isinstance(row, dict)
    ]
    touched = max((_epoch(stamp) for stamp in stamps), default=0.0)
    days = int(((time.time() if now is None else now) - touched) // 86400) if touched else 0
    return days if days >= STALE_GATE_DAYS else 0


def waiting_on(intent, pack) -> str:
    """Who an open outbox item waits on: `gate` (pending, the gatekeeper), `stale` (pending and untouched for days),
    `lane` (returned to its writer, or held until the lanes deliver), `later` (the human's, at a stage whose turn has
    not come) or `now` (the human can act on it)."""
    from .sequence import waits

    status = intent.get("status")
    if status == "pending":
        return "stale" if stale_days(intent) else "gate"
    if status == "returned" or (status == "held" and (intent.get("hold") or {}).get("waits") == "lane"):
        return "lane"
    return "later" if waits(intent, pack) else "now"


def waiting_cards(pack, cards) -> list:
    """One Review card per ticket whose work is not over although no lane holds a card of it: its outbox items wait for
    the gatekeeper or for the human (a bump batch after its lanes filed every stage had nothing on the Board at all).
    The card is not in Hermes's database: its id starts with `yours:` and it carries the items it stands for.

    It says who each item waits on (waiting_on). An item back with a lane is named as the lane's, never as the
    human's, and neither it nor a stale pending one makes a card by itself; a ticket-done is the Inbox's confirmation
    of finished work, not work, and is left out."""
    from .intents import OPEN_STATUSES, all_intents

    busy = {card["ticket"] for card in cards if card["status"] not in CLOSED and card["ticket"]}
    found = {}
    for intent in all_intents():
        ticket = intent.get("ticket") or ""
        if (
            intent.get("status") in OPEN_STATUSES
            and intent.get("type") != "ticket-done"
            and ticket
            and ticket not in busy
        ):
            found.setdefault(ticket, []).append(intent)
    made = []
    for ticket, items in sorted(found.items()):
        when = {item["id"]: waiting_on(item, pack) for item in items}
        count = {
            name: sum(1 for value in when.values() if value == name)
            for name in ("now", "later", "gate", "lane", "stale")
        }
        if not (count["now"] or count["later"] or count["gate"]):
            continue
        parts = [
            f"{count['now']} for you now" if count["now"] else "",
            f"{count['later']} later stage(s)" if count["later"] else "",
            f"{count['gate']} with the gatekeeper" if count["gate"] else "",
            f"{count['lane']} back with a lane" if count["lane"] else "",
            f"{count['stale']} stale" if count["stale"] else "",
        ]
        made.append(
            {
                "id": f"yours:{ticket}",
                "title": f"{ticket}: outbox",
                "status": "review",
                "lane": "you",
                "ticket": ticket,
                "flow": "",
                "created": min(str(item.get("created_at") or "") for item in items),
                "started": "",
                "completed": "",
                "heartbeat": "",
                "alive": False,
                "question": " · ".join(part for part in parts if part),
                "error": "",
                "last_comment": None,
                "runs": 0,
                "skills": [],
                "result": "",
                "yours": True,
                "items": [
                    {"id": item["id"], "type": item.get("type"), "status": item.get("status"), "when": when[item["id"]]}
                    for item in sorted(items, key=lambda item: item["id"])
                ],
            }
        )
    return made


def board(pack, include_done_days=None) -> dict:
    """Open cards, every card of a live ticket, and the other done ones of the last days; counts by status; the lanes;
    when each done card's ticket was last active and its tracker title, so the page can keep a recently active ticket's
    cards in view; the live tickets and what each waits for."""
    from .kanban import block_reason, board_cards, card_flow, completion_summary, skills_of, ticket_of

    flows = {card["id"]: card["flow"] for card in board_cards((pack or {}).get("board") or "", pack)}
    days = done_days(pack) if include_done_days is None else int(include_done_days)
    connection = _connect(pack)
    cards = []
    live = {}
    if connection is not None:
        try:
            tables = _tables(connection)
            columns = _columns(connection, "tasks")
            cut = time.time() - days * 86400
            rows = [dict(row) for row in connection.execute("select * from tasks order by created_at desc")]
            live = live_tickets(
                pack, {ticket_of(task.get("title") or "") for task in rows if (task.get("status") or "") not in CLOSED}
            )
            for task in rows:
                status = task.get("status") or ""
                if (
                    status in CLOSED
                    and _epoch(task.get("completed_at") or task.get("created_at")) < cut
                    and ticket_of(task.get("title") or "") not in live
                ):
                    continue
                card_id = task["id"]
                question = block_reason(connection, card_id) if status == "blocked" else ""
                last = None
                if "task_comments" in tables:
                    comment = connection.execute(
                        "select author, body, created_at from task_comments where task_id = ? order by created_at desc limit 1",
                        (card_id,),
                    ).fetchone()
                    if comment is not None:
                        last = {
                            "author": comment["author"] or "",
                            "text": (comment["body"] or "")[:200],
                            "at": _iso(comment["created_at"]),
                        }
                runs = 0
                if "task_runs" in tables:
                    runs = connection.execute(
                        "select count(*) from task_runs where task_id = ?", (card_id,)
                    ).fetchone()[0]
                heartbeat = task.get("last_heartbeat_at") if "last_heartbeat_at" in columns else None
                title = task.get("title") or ""
                ticket = ticket_of(title)
                # a done card's verdict: Hermes keeps the lane's complete summary on the event, not in result
                result = task.get("result") or (completion_summary(connection, card_id) if status in CLOSED else "")
                cards.append(
                    {
                        "id": card_id,
                        "title": title,
                        "status": status,
                        "lane": task.get("assignee") or "",
                        "ticket": ticket,
                        "flow": flows.get(card_id) or (card_flow(title) if ticket else ""),
                        "created": _iso(task.get("created_at")),
                        "started": _iso(task.get("started_at")),
                        "completed": _iso(task.get("completed_at")),
                        "heartbeat": _iso(heartbeat) if heartbeat else "",
                        "alive": bool(heartbeat and time.time() - _epoch(heartbeat) < ALIVE_SECONDS),
                        "question": question[:300],
                        "error": (task.get("last_failure_error") or "")[:300],
                        "last_comment": last,
                        "runs": runs,
                        "skills": skills_of(task.get("skills")) if "skills" in columns else [],
                        "result": result[:400],
                    }
                )
        except sqlite3.Error:
            cards = []
        finally:
            connection.close()
    cards = waiting_cards(pack, cards) + cards
    by_status = {status: [card for card in cards if card["status"] == status] for status in COLUMNS}
    done_tickets = sorted({card["ticket"] for card in cards if card["status"] in CLOSED and card["ticket"]})
    activity = {}
    from .activity import ticket_activity

    for ticket in done_tickets:
        rows = ticket_activity(pack, ticket)
        if rows:
            activity[ticket] = rows[-1]["ts"]
    from .tracker import titles

    return {
        "columns": COLUMNS,
        "cards": cards,
        "by_status": by_status,
        "counts": {status: len(items) for status, items in by_status.items()},
        "lanes": sorted({card["lane"] for card in cards if card["lane"]}),
        "ticket_activity": activity,
        "ticket_titles": titles(pack, done_tickets) if done_tickets else {},
        "live": live,
        "done_days": days,
        "recent_hours": int(
            ((pack or {}).get("desktop") or {}).get("done_recent_hours") or 24
        ),  # Done keeps a ticket in view this long
    }


# ---------- a card's Brief and the records it mentions ----------


def _ref_pattern():
    from .paths import records_name

    records = re.escape(records_name().rstrip("/"))
    return re.compile(
        r"(?:workspace/)?(?:" + records + r"/)?(qa/[A-Za-z][A-Za-z0-9]*(?:-[A-Za-z0-9]+)+/[^\s`'\")\]>,;]+)"
    )


def extract_brief(text: str) -> str:
    """The Brief of a card body, a comment or a plan: the text under a Brief heading at any level."""
    from .plan import brief_of

    return brief_of(text or "")


def render_brief(markdown_text: str) -> str:
    """The Brief as a label/value grid, whatever the lane's blank lines: `**Label:** text` opens a field, `- item`
    lines become its list, other lines join its text. A table, a code fence or a numbered list inside a field keeps its
    lines as one block, rendered whole: a lane's row table is a table, not one long line."""
    fields = []

    def field(label="", text=""):
        fields.append({"label": label, "text": text, "items": [], "blocks": [["text", text]] if text else []})

    def block(kind, line):
        if not fields:
            field()
        blocks = fields[-1]["blocks"]
        if kind == "break":
            if blocks and blocks[-1][0] != "break":
                blocks.append(["break", ""])
        elif blocks and blocks[-1][0] == kind:
            if kind == "items":
                blocks[-1][1].append(line)
            else:
                blocks[-1][1] += ("\n" if kind == "raw" else " ") + line
        else:
            blocks.append([kind, [line] if kind == "items" else line])

    fence = ""
    for line in (markdown_text or "").splitlines():
        text = line.rstrip()
        stripped = text.strip()
        if fence:  # inside a code fence: every line, blank ones included
            fields[-1]["blocks"][-1][1] += "\n" + text
            if stripped.startswith(fence):
                fence = ""
            continue
        if not stripped:
            block("break", "")  # a blank line ends the block; the next text starts a new one
            continue
        match = re.match(r"^\*\*([^*]+?):?\*\*:?\s*(.*)$", stripped)
        if match:
            field(match.group(1).strip(), match.group(2).strip())
            continue
        opened = re.match(r"^(`{3,}|~{3,})", stripped)
        if opened:
            fence = opened.group(1)
            block("break", "")
            block("raw", text)
            continue
        if stripped.startswith("|") or re.match(r"^\d+[.)]\s+", stripped):
            block("raw", text)
            continue
        match = re.match(r"^\s*[-*•]\s+(.*)$", text)
        if match:
            block("items", match.group(1).strip())
            fields[-1]["items"].append(match.group(1).strip())
            continue
        block("text", stripped)
    for item in fields:
        item["text"] = " ".join(text for kind, text in item["blocks"] if kind == "text").strip()
        item["blocks"] = [[kind, text] for kind, text in item["blocks"] if kind != "break"]
    return brief_html(fields)


def brief_html(fields) -> str:
    from .render import markdown

    def inline(text):
        rendered = markdown(str(text)).strip()
        return re.sub(r"^<p>|</p>$", "", rendered)

    def items_html(items):
        return "<ul>" + "".join(f"<li>{inline(item)}</li>" for item in items) + "</ul>"

    out = []
    for field in fields:
        blocks = field.get("blocks")
        if blocks:
            value = ""
            for kind, text in blocks:
                if kind == "text":
                    value += f'<div class="t">{inline(text)}</div>'
                elif kind == "items":
                    value += items_html(text)
                else:
                    value += f'<div class="t">{markdown(str(text)).strip()}</div>'  # a table, a fence, a numbered list: whole
            out.append(f'<div class="k">{html.escape(field.get("label") or "")}</div><div class="v">{value}</div>')
            continue
        if not field.get("text") and not field.get("items"):
            continue
        value = f'<div class="t">{inline(field["text"])}</div>' if field.get("text") else ""
        if field.get("items"):
            value += items_html(field["items"])
        out.append(f'<div class="k">{html.escape(field.get("label") or "")}</div><div class="v">{value}</div>')
    return '<div class="cockpit-brief">' + "".join(out) + "</div>"


def attachments(task: dict, comments: list, block_payloads: list) -> dict:
    """Every record path a lane mentioned on the card (body, comments, block reason), markdown rendered, folders
    listed; and the Brief: the newest comment's, else the card's, else the ticket plan's, else one derived from the
    card itself."""
    from .paths import qa
    from .qa_view import kind_of, list_files, read_text
    from .render import markdown

    texts = (
        [task.get("body") or ""]
        + [comment.get("text") or "" for comment in comments]
        + [str(payload or "") for payload in block_payloads]
    )
    out = {"docs": [], "dirs": [], "files": [], "brief": None}
    seen = []
    qa_root = os.path.realpath(qa())
    pattern = _ref_pattern()
    for text in texts:
        for match in pattern.finditer(text):
            rel = match.group(1).rstrip("./:")
            if rel in seen:
                continue
            seen.append(rel)
            real = os.path.realpath(os.path.join(qa_root, rel[len("qa/") :]))
            if not real.startswith(qa_root + os.sep):
                continue
            if os.path.isdir(real):
                out["dirs"].append({"rel": rel, "path": real, "files": list_files(real)[:200]})
            elif os.path.isfile(real):
                if real.endswith(".md"):
                    body = read_text(real, 200000)
                    out["docs"].append({"rel": rel, "path": real, "html": markdown(body)})
                    if not out["brief"] and extract_brief(body):
                        out["brief"] = render_brief(extract_brief(body))
                else:
                    try:
                        size = os.path.getsize(real)
                    except OSError:
                        size = 0
                    out["files"].append({"rel": rel, "path": real, "kind": kind_of(real), "size": size})
    latest = next(
        (brief for brief in (extract_brief(comment.get("text") or "") for comment in reversed(comments)) if brief), ""
    )
    if latest:
        out["brief"] = render_brief(latest)
    if not out["brief"]:
        own = extract_brief(task.get("body") or "")
        if own:
            out["brief"] = render_brief(own)
    if not out["brief"]:
        from .kanban import ticket_of
        from .plan import show

        ticket = ticket_of(task.get("title") or "")
        planned = extract_brief(show(ticket)) if ticket else ""
        if planned:
            out["brief"] = render_brief(planned)
    if not out["brief"]:
        question = block_question(block_payloads)
        body = task.get("body") or ""
        goal = next((line.strip() for line in body.splitlines() if line.strip() and not line.startswith("#")), "")[:240]
        out["brief"] = brief_html(
            [
                {"label": "Question", "text": question[:600], "items": []},
                {"label": "Card", "text": task.get("title") or "", "items": []},
                {
                    "label": "Lane",
                    "text": f"{task.get('assignee') or ''} · {task.get('status') or ''}".strip(" ·"),
                    "items": [],
                },
                {"label": "Goal", "text": goal, "items": []},
            ]
        )
        out["brief_derived"] = True
    return out
