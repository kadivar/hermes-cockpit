# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The board. Reads are read-only SQL; writes go through Hermes's own kanban functions (cockpitlib.hermes_runtime).

A ticket token does not match a longer key.
"""

import json
import os
import re
import sqlite3

from .paths import hermes_home
from .store import dump_json, locked_file, read_db

# `scheduled`: Hermes parks a card that waits on time (cockpitlib.quota at a provider's ceiling); it is not finished
OPEN = ("ready", "todo", "triage", "claimed", "in_progress", "running", "review", "blocked", "scheduled")
FLOWS = (
    (r":\s*(intake|reopened)\b", "intake"),
    (r":\s*test on (staging|local)\b", "test"),
    (r":\s*review the PR", "review"),
    (r":\s*bumps on", "bumps"),
    (r":\s*analysis\b", "analyst"),
    (r"rework", "rework"),
    (r":\s*diagnose CI", "ci-watch"),
)


def db_path(slug: str) -> str:
    return os.path.join(hermes_home(), "kanban", "boards", slug, "kanban.db")


def ticket_of(title: str) -> str:
    match = re.match(r"^\s*([A-Z][A-Z0-9]*(?:-[A-Z0-9]+)+)\b", title or "")
    if not match:
        return ""
    return match.group(1)


def mentions(title: str, ticket: str) -> bool:
    """TASK-1 does not match TASK-12 or XTASK-1."""
    return re.search(rf"(?<![A-Z0-9]){re.escape(ticket)}(?![A-Z0-9])", title or "") is not None


def card_flow(title: str) -> str:
    rest = re.sub(r"^\s*[A-Z][A-Z0-9]*(?:-[A-Z0-9]+)+\s*", "", title or "")
    for pattern, name in FLOWS:
        if re.search(pattern, rest):
            return name
    return "card"


# Cockpit's own card kinds (registry.CARD_KINDS): the kernel's wording and each kind's flow.
from .registry import CARD_KINDS  # noqa: E402 - kept beside the tables it fills

TITLES = {kind: entry["title"] for kind, entry in CARD_KINDS.items()}
KIND_FLOWS = {kind: entry["flow"] for kind, entry in CARD_KINDS.items()}
OPEN_STATUSES = ("ready", "todo", "triage", "running", "review", "blocked", "scheduled")


def _cards(pack) -> dict:
    return ((pack or {}).get("skills") or {}).get("cards") or {}


def card_title(kind: str, ticket: str = "", pack=None, **fields) -> str:
    """The pack's wording for a card kind (skills.yaml cards.titles), else the kernel's. A kind with neither is named
    by its kind."""
    from .registry import card_kinds

    known = card_kinds(pack).get(kind) or {}
    template = (_cards(pack).get("titles") or {}).get(kind) or known.get("title") or "{ticket}: " + kind
    return template.format(ticket=ticket, **fields)


def card_skills(pack, kind: str, repos=(), base=()) -> list:
    """The skills a card of this kind carries: base (a kickoff list), the pack's skills for the kind, then each of
    the card's repos' own skills. Each once, in that order."""
    wanted = list(base or ())
    wanted += (_cards(pack).get("skills") or {}).get(kind) or []
    named = {repo.get("name"): repo for repo in ((pack or {}).get("repos") or {}).get("repos") or []}
    for repo in repos or ():
        wanted += (named.get(repo) or {}).get("skills") or []
    return list(dict.fromkeys(str(name) for name in wanted if name))


def _index_path() -> str:
    from .paths import watch_dir

    return os.path.join(watch_dir(), "cards.json")


def _index() -> dict:
    try:
        loaded = json.load(open(_index_path(), encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return loaded if isinstance(loaded, dict) else {}


def _write_index(path: str, index: dict) -> None:
    """Write cards.json whole: a temp file in its folder, then moved over the old one, so a reader (the card fence)
    sees the old index or the new, never half of one. A failed write leaves the old index and no temp file."""
    dump_json(path, index, mode=0o600)


def remember_card(
    slug: str, card: str, kind: str, ticket: str = "", key: str = "", scope: str = "", repos=(), intent: str = ""
) -> None:
    """Record what cockpit made this card for, so a reworded title never changes its flow or its twin. A card started
    in a scope (a release) records it: the intents its lane writes are in that scope. Its repos say whose pull
    requests are its own. A card that carries an intent back to its lane records the intent: a second instruction for
    the same intent goes onto that card while it is open (open_holder)."""
    path = _index_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with locked_file(path):  # read, add, write as one step: two writers never drop each other's card
        index = _index()
        board = index.get(slug) if isinstance(index.get(slug), dict) else {}
        board[card] = {
            "kind": kind,
            "ticket": ticket,
            "key": key,
            **({"scope": scope} if scope else {}),
            **({"repos": list(repos)} if repos else {}),
            **({"intent": intent} if intent else {}),
        }
        index[slug] = board
        _write_index(path, index)


def mark_card(slug: str, card: str, **fields) -> None:
    """Add facts to what cockpit recorded about a card. A card cockpit did not make gets an entry too."""
    path = _index_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with locked_file(path):
        index = _index()
        board = index.get(slug) if isinstance(index.get(slug), dict) else {}
        entry = board.get(card) if isinstance(board.get(card), dict) else {}
        board[card] = {**entry, **fields}
        index[slug] = board
        _write_index(path, index)


def card_entry(slug: str, card: str) -> dict:
    """What cockpit recorded when it made the card: {kind, ticket, key, scope, repos}; empty for a card it did not make."""
    entry = (_index().get(slug) or {}).get(card)
    return entry if isinstance(entry, dict) else {}


def card_scope(slug: str, card: str) -> str:
    """The scope the card was started in, or empty."""
    entry = (_index().get(slug) or {}).get(card)
    return str(entry.get("scope") or "") if isinstance(entry, dict) else ""


def ticket_scope(slug: str, ticket: str, days: int = 14) -> str:
    """The scope a ticket is being worked in, for an intent no card filed (a CI rerun from a failing check): "release"
    while one of its cards was started in the release scope within `days`, else empty."""
    if not ticket:
        return ""
    import time

    entries = _index().get(slug) or {}
    released = {
        card
        for card, entry in entries.items()
        if isinstance(entry, dict) and entry.get("ticket") == ticket and entry.get("scope") == "release"
    }
    if not released:
        return ""
    since = time.time() - days * 86400
    for row in board_cards(slug):
        if row["id"] in released and row.get("status") != "archived":
            created = _created_at(slug, row["id"])
            if created is None or created >= since:
                return "release"
    return ""


def _created_at(slug: str, card: str):
    connection = None
    try:
        connection = read_db(db_path(slug))
        row = connection.execute("select created_at from tasks where id = ?", (card,)).fetchone()
        return float(row[0]) if row and row[0] is not None else None
    except sqlite3.Error:
        return None
    finally:
        if connection is not None:
            connection.close()


PLACE_WAIT = 120.0  # seconds a second caller waits for the first to finish looking and making its card


def one_at_a_time(run):
    """A function that looks for an open card and makes one when there is none runs alone on this installation. Two
    callers at once would both find none and both make it: a request that arrived twice then starts the same work twice,
    on one checkout. The second caller waits, then finds the first one's card."""
    import functools

    @functools.wraps(run)
    def alone(*args, **kwargs):
        from .paths import watch_dir
        from .store import locked_file

        with locked_file(os.path.join(watch_dir(), "card-making"), wait=PLACE_WAIT):
            return run(*args, **kwargs)

    return alone


def open_twin(slug: str, kind: str, ticket: str = "", key: str = "", title: str = "") -> str:
    """The open card already made for this ticket, kind, and key. A card made before the index is matched by title."""
    statuses = {card["id"]: card["status"] for card in board_cards(slug)}
    for card, entry in (_index().get(slug) or {}).items():
        if not isinstance(entry, dict):
            continue
        if (entry.get("kind"), entry.get("ticket") or "", entry.get("key") or "") != (kind, ticket, key):
            continue
        if statuses.get(card) in OPEN_STATUSES:
            return card
    # The title is the way to a card made before the index only. A card the index knows under another key is another
    # card with the same words: a ticket's two PRs each get "<ticket>: review the PR", and the second one's Treat
    # comments must not be refused as "already open" for the first.
    same = open_same(slug, title) if title else ""
    return "" if same and isinstance((_index().get(slug) or {}).get(same), dict) else same


def open_holder(slug: str, intent: str) -> str:
    """The open card that already carries this intent back to its lane, whatever its kind (a rework, a tester's or a
    reviewer's card made by a return or a refusal send-back): the newest one, or empty."""
    if not intent:
        return ""
    cards = {card["id"]: card for card in board_cards(slug)}
    found = []
    for card, entry in (_index().get(slug) or {}).items():
        if not isinstance(entry, dict) or intent not in (entry.get("intent"), entry.get("key")):
            continue
        if (cards.get(card) or {}).get("status") in OPEN_STATUSES:
            found.append(cards[card])
    found.sort(key=lambda card: str(card.get("created_at") or ""), reverse=True)
    return found[0]["id"] if found else ""


def board_cards(slug: str, pack=None) -> list:
    """Every card on the board that names a ticket. A card with no ticket key is skipped. Given the pack, a plugin
    kind from its plugin block reads with that kind's flow."""
    path = db_path(slug)
    if not os.path.isfile(path):
        return []
    connection = read_db(path)
    connection.row_factory = sqlite3.Row
    try:
        columns = {row[1] for row in connection.execute("pragma table_info(tasks)")}
        if "title" not in columns or "id" not in columns:
            return []
        rows = connection.execute("select * from tasks").fetchall()
    except sqlite3.Error:
        return []
    finally:
        connection.close()
    found = []
    kinds = _index().get(slug) or {}
    from .registry import card_kinds

    known = card_kinds(pack)  # once for the board, not once per card
    for row in rows:
        title = row["title"] or ""
        ticket = ticket_of(title)
        if not ticket:
            continue
        entry = kinds.get(row["id"]) if isinstance(kinds.get(row["id"]), dict) else {}
        kind = entry.get("kind")
        found.append(
            {
                "id": row["id"],
                "title": title,
                "status": row["status"] if "status" in columns else "",
                # Who ended it, when it was not its lane: cockpit sets "owner" when it closes a card for the
                # human (a `stop` reply, a halt). A plugin watching its own cards reads this rather than
                # guessing from the closing text, which says different things for different ways of ending.
                "ended_by": entry.get("ended_by") or "",
                "assignee": row["assignee"] if "assignee" in columns else "",
                "ticket": ticket,
                "flow": _flow_of(kind, title, pack, known),
                "created_at": row["created_at"] if "created_at" in columns else "",
                "body": row["body"] if "body" in columns else "",
                "skills": skills_of(row["skills"]) if "skills" in columns else [],
            }
        )
    return found


def _flow_of(kind, title, pack=None, known=None) -> str:
    """The flow of the kind cockpit recorded for the card: its own, a plugin's (registered in this process or in the
    pack's plugin block), or the plugin kind's own name. A card made before the index is read by its title. A caller
    with many cards passes the kinds it read once."""
    if not kind:
        return card_flow(title)
    if known is None:
        from .registry import card_kinds

        known = card_kinds(pack)
    return (known.get(kind) or {}).get("flow") or kind


def skills_of(raw) -> list:
    """Hermes stores a card's skills as a JSON list."""
    try:
        value = json.loads(raw) if raw else []
    except (TypeError, ValueError):
        return []
    return [str(item) for item in value] if isinstance(value, list) else []


def _ticket_ids(connection, ticket: str) -> list:
    columns = {row[1] for row in connection.execute("pragma table_info(tasks)")}
    if "id" not in columns or "title" not in columns:
        return []
    found = []
    for row in connection.execute("select id, title from tasks"):
        if ticket_of(row[1] or "") == ticket:
            found.append(row[0])
    return found


def _ticket_cards(slug: str, ticket: str, skip=()) -> list:
    path = db_path(slug)
    if not os.path.isfile(path):
        return []
    connection = read_db(path)
    try:
        columns = {row[1] for row in connection.execute("pragma table_info(tasks)")}
        ids = _ticket_ids(connection, ticket)
        if "status" in columns and skip:
            ids = [
                card
                for card in ids
                if connection.execute("select status from tasks where id = ?", (card,)).fetchone()[0] not in skip
            ]
        return ids
    finally:
        connection.close()


def delete_ticket_cards(slug: str, ticket: str) -> list:
    """Remove this ticket's cards and their comments, events, runs, and links, through Hermes. Local board only."""
    ids = _ticket_cards(slug, ticket)
    writes = BoardWrites(slug)
    for card in ids:
        writes.delete(card)
    done = writes.flush()
    return [card for card, removed in zip(ids, done) if removed]


def archive_ticket_cards(slug: str, ticket: str) -> list:
    """Archive this ticket's cards through Hermes. A running card's worker is stopped by Hermes."""
    ids = _ticket_cards(slug, ticket, skip=("archived",))
    writes = BoardWrites(slug)
    for card in ids:
        writes.archive(card)
    done = writes.flush()
    return [card for card, archived in zip(ids, done) if archived]


def open_cards(slug: str, statuses=OPEN) -> dict:
    """Open cards per lane. `statuses` narrows what counts as open (capacity may leave out a card waiting on a human)."""
    path = db_path(slug)
    if not os.path.isfile(path):
        return {}
    connection = read_db(path)
    try:
        rows = connection.execute(
            f"select assignee, title from tasks where status in ({','.join('?' * len(statuses))})",
            tuple(statuses),
        ).fetchall()
    except sqlite3.Error:
        return {}
    finally:
        connection.close()
    counts = {}
    for assignee, _title in rows:
        if assignee:
            counts[assignee] = counts.get(assignee, 0) + 1
    return counts


def open_card_rows(slug: str, pack=None) -> list:
    """Every open card as the Inbox lists it. A blocked or triage card says why it waits (block_reason, the time it
    blocked); a card a plugin owns names that plugin."""
    path = db_path(slug)
    if not os.path.isfile(path):
        return []
    from .registry import card_kinds

    known = card_kinds(pack)  # once for the list, as in board_cards
    owners = {name: entry["owner"] for name, entry in known.items() if entry.get("owner")}
    kinds = _index().get(slug) or {}
    connection = read_db(path)
    connection.row_factory = sqlite3.Row
    found = []
    try:
        columns = {row[1] for row in connection.execute("pragma table_info(tasks)")}
        if not {"id", "title", "status"} <= columns:
            return []
        rows = connection.execute(f"select * from tasks where status in ({','.join('?' * len(OPEN))})", OPEN).fetchall()
        tables = {row[0] for row in connection.execute("select name from sqlite_master where type = 'table'")}
        for row in rows:
            entry = kinds.get(row["id"]) if isinstance(kinds.get(row["id"]), dict) else {}
            kind = entry.get("kind") or ""
            title = row["title"] or ""
            card = {
                "id": row["id"],
                "title": title,
                "status": row["status"],
                "assignee": row["assignee"] if "assignee" in columns else "",
                "ticket": entry.get("ticket") or ticket_of(title),
                "kind": kind,
                "flow": _flow_of(kind or None, title, pack, known),
                "owner": owners.get(kind, ""),
                "created_at": row["created_at"] if "created_at" in columns else None,
                "block_reason": "",
                "blocked_at": None,
            }
            if row["status"] in ("blocked", "triage"):
                card["block_reason"] = block_reason(connection, row["id"])
                card["question"] = card["block_reason"]
                # An analyst asks in markdown — a list of options, a table, a fenced diff — and the
                # Inbox showed the source of it. The card body beside it has always been rendered;
                # the question is the part the human has to read to answer, so it is rendered too.
                from .render import markdown

                card["question_html"] = markdown(card["question"] or "")
                # What the lane asks, and the document it is asking about, whichever of them it put in the block
                # and whichever it posted as a comment: one analyst blocks with its whole report and asks in a
                # comment, another blocks with one line and leaves the report as a comment folded in the card.
                ask, report = ask_and_report(connection, row["id"], card["assignee"], card["block_reason"])
                card["ask"], card["ask_html"] = ask, markdown(ask)
                card["report"], card["report_html"] = report, markdown(report) if report else ""
                card["parked"] = row["status"] == "triage"  # Hermes's loop guard parked it: it still waits on the human
                # blocked until the human publishes an intent that has not left yet: that intent's Publish row is the
                # act, and the card is unblocked when it is out, so the Inbox makes no second row of the card
                from .gate import publish_wait

                card["waits_publish"] = ""
                if row["status"] == "blocked":
                    wait = publish_wait(card["block_reason"], row["id"])
                    card["waits_publish"] = (wait["open"] or [""])[0]
                    if not wait["open"] and wait["out"]:
                        # everything it waited for is out: the housekeeping's next pass unblocks it (once per block),
                        # so it is no row for that minute either
                        from .housekeeping import _block_key, published_seen

                        if _block_key(connection, row["id"]) not in published_seen():
                            card["waits_publish"] = wait["out"][0]
                from .asks import row as ask_row

                card["pack_ask"] = ask_row(pack, card["question"])  # one of the pack's own approvals (pack.yaml asks)
                # A tester asking for the review of a run that is not finished: the Inbox offers Send back, not go.
                card["not_ready"] = []
                if str(card["assignee"] or "").startswith("tester") and card["ticket"]:
                    from .test_flow import run_not_ready

                    card["not_ready"] = run_not_ready(pack, card["ticket"], card["question"], card=row["id"])
                if "task_events" in tables:
                    at = connection.execute(
                        "select max(created_at) from task_events where task_id = ? and kind in "
                        "('blocked', 'block_loop_detected')",
                        (row["id"],),
                    ).fetchone()
                    card["blocked_at"] = at[0] if at else None
            found.append(card)
    except sqlite3.Error:
        return found
    finally:
        connection.close()
    return found


def open_same(slug: str, title: str) -> str:
    path = db_path(slug)
    if not os.path.isfile(path):
        return ""
    connection = read_db(path)
    try:
        row = connection.execute(
            f"select id from tasks where title = ? and status in ({','.join('?' * len(OPEN))}) limit 1",
            (title, *OPEN),
        ).fetchone()
    except sqlite3.Error:
        return ""
    finally:
        connection.close()
    return row[0] if row else ""


SHORT_ASK = 600  # past this a block reason is a document, not a question


def ask_and_report(connection, card_id: str, lane: str, reason: str) -> tuple:
    """(ask, report) for a blocked card: the short question the lane put to the owner, and the document it asks
    about — its report since the owner last answered. The ask is the lane's latest `BLOCKED:` comment, or the block
    reason when that is short; the report is the block reason when that is long, else the lane's latest long
    comment. Either may be empty; the report is never the ask again."""
    comments = []
    tables = {row[0] for row in connection.execute("select name from sqlite_master where type = 'table'")}
    if "task_comments" in tables:
        comments = [
            (str(author or ""), str(body or ""))
            for author, body in connection.execute(
                "select author, body from task_comments where task_id = ? order by created_at, id", (card_id,)
            )
        ]
    last_human = max(
        (i for i, (author, body) in enumerate(comments) if author == "human" or body.startswith("Human:")), default=-1
    )
    mine = [body.strip() for author, body in comments[last_human + 1 :] if author == lane and body.strip()]
    blocked = [body for body in mine if body.upper().startswith("BLOCKED:")]
    reason = str(reason or "").strip()
    if blocked:
        ask = blocked[-1].split(":", 1)[1].strip()
        if ask.lower().startswith("needs_input:"):
            ask = ask.split(":", 1)[1].strip()
    elif len(reason) <= SHORT_ASK:
        ask = reason
    else:
        ask = reason.split("\n\n", 1)[0].strip()[:SHORT_ASK]
    if len(reason) > SHORT_ASK:
        report = reason
    else:
        report = next(
            (body for body in reversed(mine) if len(body) > SHORT_ASK and not body.upper().startswith("BLOCKED:")), ""
        )
    return ask, ("" if report.strip() == ask.strip() else report)


def block_reason(connection, card_id: str) -> str:
    """Why the card's latest block happened; ask it of a blocked card (or one Hermes sent to triage as a block loop).

    Hermes keeps it on the latest blocked or block_loop_detected event; an older board kept it in result.
    """
    tables = {row[0] for row in connection.execute("select name from sqlite_master where type = 'table'")}
    if "task_events" in tables:
        row = connection.execute(
            "select payload from task_events where task_id = ? and kind in ('blocked', 'block_loop_detected') "
            "order by id desc limit 1",
            (card_id,),
        ).fetchone()
        try:
            payload = json.loads(row[0]) if row and row[0] else {}
        except json.JSONDecodeError:
            payload = {}
        reason = str(payload.get("reason") or "") if isinstance(payload, dict) else ""
        if reason and reason != "initial_status":
            return reason
    columns = {row[1] for row in connection.execute("pragma table_info(tasks)")}
    if "result" in columns:
        row = connection.execute("select result from tasks where id = ?", (card_id,)).fetchone()
        if row and row[0]:
            return str(row[0])
    # A run that ended without a board call (a crash, a protocol violation) leaves no block reason: its error, else the
    # card's last comment, is what the human has to read to decide.
    if "last_failure_error" in columns:
        row = connection.execute("select last_failure_error from tasks where id = ?", (card_id,)).fetchone()
        if row and row[0]:
            return str(row[0])
    if "task_comments" in tables:
        found = {item[1] for item in connection.execute("pragma table_info(task_comments)")}
        order = "created_at desc" if "created_at" in found else "rowid desc"
        # the lane's last word, never the human's own answer read back as the lane's question
        mine = " and coalesce(author, '') != 'human'" if "author" in found else ""
        row = connection.execute(
            f"select body from task_comments where task_id = ?{mine} and body not like 'Human:%' "
            f"order by {order} limit 1",
            (card_id,),
        ).fetchone()
        if row and row[0]:
            return str(row[0])
    return ""


def completion_summary(connection, card_id: str) -> str:
    """What the card ended with: `tasks.result` when the lane set it, else the summary of its last `completed` event.
    Hermes puts the lane's kanban_complete(summary=…) in that event and leaves `result` empty, so a done card read
    from `result` alone showed nothing where its verdict should be."""
    columns = {row[1] for row in connection.execute("pragma table_info(tasks)")}
    if "result" in columns:
        row = connection.execute("select result from tasks where id = ?", (card_id,)).fetchone()
        if row and row[0]:
            return str(row[0])
    tables = {row[0] for row in connection.execute("select name from sqlite_master where type = 'table'")}
    if "task_events" not in tables:
        return ""
    row = connection.execute(
        "select payload from task_events where task_id = ? and kind = 'completed' order by id desc limit 1", (card_id,)
    ).fetchone()
    try:
        payload = json.loads(row[0]) if row and row[0] else {}
    except json.JSONDecodeError:
        payload = {}
    return str(payload.get("summary") or "") if isinstance(payload, dict) else ""


def block_kind(reason: str):
    """The Hermes block kind for one of cockpit's block reasons.

    Hermes treats a second block of the same kind after an unblock as a loop and sends the card to triage, so
    different causes carry different kinds, and a real repeat of one cause still reaches a human.
    """
    text = (reason or "").strip().lower()
    if text.startswith("waiting"):
        return "needs_input"
    if text.startswith(("credentials needed", "privileged login needed")):
        return "capability"
    if "rate-limited" in text:
        return "transient"
    return None


PR_URL = re.compile(r"https?://github\.com/[^/\s]+/([^/\s]+)/pull/(\d+)(#[\w-]+)?", re.I)


def pr_url_pattern(pack=None):
    """A pull-request link on any forge this installation knows: every built-in forge's own host, the host the pack
    names (forge.host), and the file-backed forge's local:// links. With no pack given, the bound pack's host is read; a
    pack that cannot be read leaves the built-in hosts."""
    from . import forges

    if pack is None:
        try:
            from .pack import load
            from .paths import pack_path

            pack = load(pack_path())
        except Exception:  # noqa: BLE001 - a comment is still written while the pack is down
            pack = {}
    forge = (pack or {}).get("forge")
    named = str(forge.get("host") or "").strip() if isinstance(forge, dict) else ""
    hosts = "|".join(re.escape(host) for host in dict.fromkeys([*forges.default_hosts(), *([named] if named else [])]))
    return re.compile(rf"(?:https?://(?:{hosts})|local:/)/[^/\s]+/([^/\s]+)/pull/(\d+)(#[\w-]+)?", re.I)


def defuse_pr_links(text: str, pack=None) -> str:
    """A forge's PR link in a card comment holds the card for good: Hermes's respawn guard (`active_pr`) reads it as a
    worker who already opened a PR. On the card it becomes `repo#n` (with its anchor); the forge link stays elsewhere.
    A link to any forge counts (pr_url_pattern), so a card reads the same whichever forge the pack publishes to."""

    def one(match):
        anchor = match.group(3) or ""
        return f"{match.group(1)}#{match.group(2)}" + (f" ({anchor.lstrip('#')})" if anchor else "")

    return pr_url_pattern(pack).sub(one, text or "")


class BoardWrites:
    """Card writes queued while the board is read, then sent to Hermes in one helper call."""

    def __init__(self, slug: str):
        self.slug = slug
        self.ops = []

    def _add(self, op: str, **fields) -> None:
        self.ops.append({"op": op, **{key: value for key, value in fields.items() if value is not None}})

    def block(self, card: str, reason: str, kind=None, guard: bool = False) -> None:
        """`guard`: block only a ready card no dispatcher has claimed (after an unblock, a claim in between wins)."""
        self._add(
            "block",
            id=card,
            reason=reason,
            kind=kind or block_kind(reason),
            require_ready_unclaimed=True if guard else None,
        )

    def unblock(self, card: str) -> None:
        """blocked or scheduled -> ready (todo under an open parent)."""
        self._add("unblock", id=card)

    def schedule(self, card: str, reason: str) -> None:
        """Hermes's `scheduled`: the card waits on time, not on a human, and the dispatcher never starts it until an
        unblock. False for a card that is not ready or that a dispatcher has claimed, or on a Hermes without the state."""
        self._add("schedule", id=card, reason=reason)

    def complete(self, card: str, result=None, summary=None) -> None:
        self._add("complete", id=card, result=result, summary=summary)

    def assign(self, card: str, lane: str) -> None:
        self._add("assign", id=card, profile=lane)

    def comment(self, card: str, author: str, body: str) -> None:
        self._add("comment", id=card, author=author, body=defuse_pr_links(body))

    def edit(self, card: str, body=None) -> None:
        self._add("edit", id=card, body=body)

    def archive(self, card: str) -> None:
        self._add("archive", id=card)

    def delete(self, card: str) -> None:
        """Hermes's hard delete: the card and every row that names it."""
        self._add("delete", id=card)

    def reclaim(self, card: str, reason=None) -> None:
        self._add("reclaim", id=card, reason=reason)

    def specify(self, card: str) -> None:
        """triage -> todo (Hermes keeps parent gating); promote then makes it ready."""
        self._add("specify", id=card)

    def promote(self, card: str, reason=None) -> None:
        self._add("promote", id=card, actor="cockpit", reason=reason)

    def flush(self) -> list:
        """One answer per queued write, in order. Nothing queued sends nothing."""
        from .hermes_runtime import run_helper

        if not self.ops:
            return []
        ops, self.ops = self.ops, []
        return run_helper("board", {"board": self.slug, "ops": ops})["results"]


EFFORT_MARK = "@reasoning_effort="


def model_and_effort(pack, lane: str, model: str) -> tuple:
    """A card model `name@reasoning_effort=<level>`: Cursor's SDK takes it whole as its model id; any other provider
    runs `name` with Hermes's own reasoning_effort, so a pack keeps one way to name a card's effort whatever provider
    its lanes run on. ('', '') for no model; the effort is '' when the model names none."""
    if not model or EFFORT_MARK not in model or not isinstance(pack, dict):
        return model, ""
    role = (pack.get("roles") or {}).get(re.sub(r"-\d+$", "", lane or ""))
    provider = ((pack.get("providers") or {}).get(role) or {}).get("hermes_provider") if role else ""
    # Both Cursor SDKs take the whole id. Splitting leaves `high,fast=false`, which Hermes rejects.
    if provider in ("cursor", "cursor-subscription-directsdk"):
        return model, ""
    name, _, effort = model.partition(EFFORT_MARK)
    return name, effort


def place_card(
    slug: str,
    title: str,
    lane: str,
    status: str = "ready",
    body=None,
    skills=None,
    parents=(),
    reason="",
    kind: str = "",
    ticket: str = "",
    key: str = "",
    pack=None,
    repos=(),
    idempotency_key: str = "",
    model_override: str = "",
    max_runtime_seconds: int = 0,
    scope: str = "",
    intent: str = "",
) -> str:
    """Create one card with Hermes's own create_task. A new card is ready (todo under an open parent) or blocked.

    A blocked card with a reason is created and then blocked with that reason and its kind, so the reason is readable.
    Given the pack, a card of a kind also carries the pack's skills for that kind and for its repos. `intent` names the
    intent the card carries back to its lane (open_holder).
    """
    from .hermes_runtime import run_helper

    if status not in ("ready", "blocked"):
        raise ValueError(f"a new card is ready or blocked, not {status}")
    if pack is not None and kind:
        skills = card_skills(pack, kind, repos, base=skills or ())
    op = {"op": "create", "title": title, "assignee": lane, "created_by": "cockpit"}
    if status == "blocked" and reason:
        op["block"] = {"reason": reason, "kind": block_kind(reason)}
    if status == "blocked" and not reason:
        op["initial_status"] = "blocked"
    if body:
        op["body"] = body
    if skills:
        op["skills"] = list(skills)
    if parents:
        op["parents"] = list(parents)
    # Hermes returns the live card already made with this key instead of a second one.
    model_override, reasoning_effort = model_and_effort(pack, lane, model_override)
    for field, value in (
        ("idempotency_key", idempotency_key),
        ("model_override", model_override),
        ("max_runtime_seconds", max_runtime_seconds),
        ("reasoning_effort", reasoning_effort),
    ):
        if value:
            op[field] = value
    card = run_helper("board", {"board": slug, "ops": [op]})["results"][0]
    if kind:
        remember_card(slug, card, kind, ticket or ticket_of(title), key, scope, repos, intent)
    return card


def task_runs(slug: str, card: str) -> list:
    """A card's runs, oldest first, with each run's metadata parsed: a lane's claims ride on its closing run."""
    path = db_path(slug)
    if not os.path.isfile(path):
        return []
    connection = read_db(path)
    connection.row_factory = sqlite3.Row
    try:
        if "task_runs" not in {
            row[0] for row in connection.execute("select name from sqlite_master where type = 'table'")
        }:
            return []
        rows = connection.execute("select * from task_runs where task_id = ? order by id", (card,)).fetchall()
    finally:
        connection.close()
    found = []
    for row in rows:
        keys = row.keys()
        try:
            metadata = json.loads(row["metadata"]) if "metadata" in keys and row["metadata"] else {}
        except (TypeError, ValueError):
            metadata = {}
        found.append(
            {
                "id": row["id"],
                "status": row["status"] if "status" in keys else "",
                "outcome": row["outcome"] if "outcome" in keys else None,
                "summary": row["summary"] if "summary" in keys else None,
                "metadata": metadata if isinstance(metadata, dict) else {},
                "profile": row["profile"] if "profile" in keys else "",
                "started_at": row["started_at"] if "started_at" in keys else None,
                "ended_at": row["ended_at"] if "ended_at" in keys else None,
                "error": row["error"] if "error" in keys else None,
            }
        )
    return found
