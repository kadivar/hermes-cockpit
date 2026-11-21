# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Page routes. Identity comes from the pack. An empty object is not a response."""

import json
import os
import re
import time
from datetime import UTC

from fastapi import HTTPException, Request

from cockpitlib.errors import CockpitError, NeedMigrate
from cockpitlib.paths import chat_dir, outbox, pack_path, platform_dir, qa, qa_of, watch_dir, worktree_of
from cockpitlib.store import dump_json, read_db, write_bytes, write_text


def _pack():
    path = pack_path()
    if not os.path.isfile(path):
        raise NeedMigrate()
    from cockpitlib.pack import load

    return load(path)


def _guard():
    try:
        return _pack()
    except NeedMigrate as exc:
        raise HTTPException(409, str(exc)) from exc


def _read(path):
    if not os.path.isfile(path):
        return None
    return json.load(open(path, encoding="utf-8"))


def _write(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    dump_json(path, data)


MAX_BYTES = 40 * 1024 * 1024


def _vault_secret(text: str) -> bool:
    """A stored password or seed. A vault that cannot be read does not hide a pattern match."""
    if not text:
        return False
    try:
        from cockpitlib.vault import _items

        items = _items()
    except Exception:  # noqa: BLE001 - items that cannot be read are answered as no
        return False
    for item in items or []:
        if not isinstance(item, dict):
            continue
        for key in ("secret", "otp"):
            value = str(item.get(key) or "")
            if len(value) >= 6 and value in text:
                return True
    return False


def _secret(text: str) -> bool:
    """A password, a key, a private-key block, a one-time seed, or a stored vault secret."""
    from cockpitlib.migrate import secrets_scan

    if secrets_scan(text):
        return True
    lowered = (text or "").lower()
    if "otp=" in lowered or "seed=" in lowered:
        return True
    return _vault_secret(text)


def _under(*roots):
    def check(path):
        real = os.path.realpath(path)
        for root in roots:
            base = os.path.realpath(root)
            if real == base or real.startswith(base + os.sep):
                return real
        raise HTTPException(400, "path is outside qa and outbox")

    return check


def _login_origins(origins, pack=None) -> list:
    """Where an account may log in: the pack's demo_login_origins in order, else the app origin first, then the pack's others."""
    names = (pack or {}).get("demo_login_origins")
    if names:
        return [origins[name] for name in names if origins.get(name)]
    return [url for url in [origins.get("app"), *[value for name, value in origins.items() if name != "app"]] if url]


def _staging(pack):
    path = os.path.join(pack["_dir"], "staging.yaml")
    if not os.path.isfile(path):
        return {"origins": {"app": ""}}
    from cockpitlib import pack_local

    data = pack_local.read(path) or {}
    data.setdefault("origins", {})
    return data


def _page_links(raw) -> list:
    """The demo page reads url and label. A bare string is that url."""
    found = []
    for item in raw or []:
        if isinstance(item, str) and item.strip():
            found.append({"url": item, "label": item})
            continue
        if isinstance(item, dict) and item.get("url"):
            found.append({"url": str(item["url"]), "label": str(item.get("label") or item["url"])})
    return found


def _page_apps(origins, up) -> list:
    apps = []
    for name, url in (origins or {}).items():
        apps.append({"name": str(name), "url": str(url or ""), "up": bool((up or {}).get(name))})
    return apps


def _repos(pack):
    return [repo.get("name") for repo in pack["repos"]["repos"] if repo.get("name")]


def _base(pack):
    return pack.get("base_branch") or "main"


def _act(fn):
    try:
        return fn()
    except CockpitError as exc:
        status = exc.exit_code if exc.exit_code >= 400 else 400
        raise HTTPException(status, str(exc)) from exc


def _ticket(pack, value, blank=False, also=()) -> str:
    """The ticket a request names, checked as the outbox checks it: it names a folder under the records, never a path.
    Anything else is a 400. `blank` lets a request name none; `also` lists the words a route reads beside a key."""
    if (blank and value in (None, "")) or (also and value in also):
        return value or ""
    from cockpitlib.intents import check_ticket

    try:
        return check_ticket(value, (pack or {}).get("ticket_pattern"))
    except CockpitError as exc:
        raise HTTPException(400, str(exc)) from exc


def _chat(value) -> str:
    """The chat a request names: the human's own, or a ticket's by its folder name. A chat is kept under that name, so
    one that is a path is a 400. The diff pane reads a checkout by the same kind of name."""
    from cockpitlib.paths import segment

    try:
        return segment(value or "own", "ticket")
    except CockpitError as exc:
        raise HTTPException(400, str(exc)) from exc


REPO_NAME = re.compile(r"[A-Za-z0-9._-]+(?:/[A-Za-z0-9._-]+)*")
SHA = re.compile(r"[0-9A-Fa-f]{1,64}")


def _diff_mode(value) -> str:
    """The mode a diff is asked in: one of the kernel's own names, 400 for any other."""
    from cockpitlib import diffs

    return _act(lambda: diffs.mode_of(value))


def _repo(value) -> str:
    """The repository a request names, if any: a name, or group/name, of letters, digits, dot, dash and underscore.
    A dot name or anything else could climb out of a record folder: 400."""
    if value in (None, ""):
        return ""
    if (
        not isinstance(value, str)
        or not REPO_NAME.fullmatch(value)
        or any(part in (".", "..") for part in value.split("/"))
    ):
        raise HTTPException(400, f"bad repo {value!r}")
    return value


def _number(value):
    """The pull-request number a request names, as it was sent: digits only, never text that becomes part of a path."""
    if value in (None, "", 0):
        return 0
    if isinstance(value, bool) or not isinstance(value, (int, str)) or not str(value).isdigit():
        raise HTTPException(400, f"bad number {value!r}")
    return value


def _sha(value) -> str:
    """The commit a request names, if any: hexadecimal only."""
    if value in (None, ""):
        return ""
    if not isinstance(value, str) or not SHA.fullmatch(value):
        raise HTTPException(400, f"bad sha {value!r}")
    return value


def _node_counts(tree, changes, days) -> tuple:
    """({node: {total, unseen}}, {parent: {total, unseen}}) over the changes merged in the last `days` days (0: all),
    skipped ones left out. A parent inherits its children's numbers."""
    from cockpitlib.pr_watch import _stamp

    cutoff = time.time() - days * 86400 if days and days > 0 else 0
    counts = {}
    for change in changes:
        if change.get("status") == "skipped":
            continue
        if cutoff and _stamp(str(change.get("merged_at") or "")) < cutoff:
            continue
        for node in change.get("nodes") or []:
            slot = counts.setdefault(str(node), {"total": 0, "unseen": 0})
            slot["total"] += 1
            if not change.get("seen"):
                slot["unseen"] += 1
    inherited = {}
    nodes = (tree or {}).get("nodes") or []
    for node in nodes:
        parent = node.get("parent")
        own = counts.get(node.get("id"))
        if parent and own:
            slot = inherited.setdefault(str(parent), {"total": 0, "unseen": 0})
            slot["total"] += own["total"]
            slot["unseen"] += own["unseen"]
    return counts, inherited


def _platform_tree(pack):
    from cockpitlib.map_build import MISSING, MapError, compiled_tree

    try:
        tree = compiled_tree(pack)
    except MapError as exc:
        return {"nodes": [], "built": None, "repos": []}, str(exc)
    if tree is not None:
        return tree, ""
    return {"nodes": [], "built": None, "repos": []}, MISSING


def _health(name, ok=True, detail=""):
    folder = os.path.join(watch_dir())
    os.makedirs(folder, exist_ok=True)
    record = {"name": name, "ok": ok, "last_run": int(time.time()), "detail": detail}
    _write(os.path.join(folder, f"{name}.json"), record)
    return record


def _chat_path(ticket):
    return os.path.join(chat_dir(), f"{ticket}.json")


def _iso(value):
    if value in (None, ""):
        return ""
    if isinstance(value, str) and not value.isdigit():
        return value
    stamp = float(value)
    if stamp > 1e12:
        stamp = stamp / 1000
    from datetime import datetime

    return datetime.fromtimestamp(stamp, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _plain_html(text):
    """A lane's Markdown as safe HTML (cockpitlib.render)."""
    from cockpitlib.render import markdown

    return markdown((text or "")[:20000])


def _table_columns(connection, table):
    import sqlite3

    try:
        return {row[1] for row in connection.execute(f"pragma table_info({table})")}
    except sqlite3.Error:
        return set()


def _empty_card(card_id):
    return {
        "id": card_id,
        "title": "",
        "status": "",
        "assignee": "",
        "prs": [],
        "created": "",
        "body_html": "",
        "result_html": "",
        "error": "",
        "skills": None,
        "workspace": "",
        "worktree": None,
        "comments": [],
        "events": [],
        "brief": None,
        "attachments": {"docs": [], "dirs": [], "files": [], "brief": None},
    }


def _card_detail(pack, card_id):
    import sqlite3

    from cockpitlib.kanban import db_path

    empty = _empty_card(card_id)
    path = db_path(pack["board"])
    if not os.path.isfile(path):
        return empty
    connection = read_db(path)
    connection.row_factory = sqlite3.Row
    try:
        if "id" not in _table_columns(connection, "tasks"):
            return empty
        row = connection.execute("select * from tasks where id = ?", (card_id,)).fetchone()
        if not row:
            return empty
        task = {key: row[key] for key in row.keys()}
        comments = []
        whole = []  # the same comments with their full text: the Brief is read from these, never from the page's cut
        if "task_id" in _table_columns(connection, "task_comments"):
            for comment in connection.execute(
                "select * from task_comments where task_id = ? order by created_at", (card_id,)
            ):
                body = comment["body"] if "body" in comment.keys() else ""
                comments.append(
                    {
                        "author": comment["author"] if "author" in comment.keys() else "",
                        "ts": _iso(comment["created_at"] if "created_at" in comment.keys() else ""),
                        "html": _plain_html(body),
                        "text": (body or "")[:4000],
                    }
                )
                whole.append({**comments[-1], "text": body or ""})
        events = []
        blocks = []
        if "kind" in _table_columns(connection, "task_events"):
            for event in connection.execute(
                "select kind, created_at from task_events where task_id = ? and kind != ? order by created_at desc limit 12",
                (card_id, "heartbeat"),
            ):
                events.append({"kind": event["kind"], "ts": _iso(event["created_at"])})
            blocks = [
                row[0]
                for row in connection.execute(
                    "select payload from task_events where task_id = ? and kind like '%block%' order by created_at desc limit 3",
                    (card_id,),
                )
            ]
        from cockpitlib.kanban import completion_summary

        result = completion_summary(connection, card_id)  # tasks.result, else the complete call's summary on the event
    except sqlite3.Error:
        return empty
    finally:
        connection.close()
    skills = task.get("skills")
    if isinstance(skills, str) and skills.startswith("["):
        try:
            skills = json.loads(skills)
        except json.JSONDecodeError:
            skills = task.get("skills")
    from cockpitlib.board_view import attachments as card_attachments
    from cockpitlib.kanban import ticket_of
    from cockpitlib.pr_watch import card_prs

    attached = card_attachments(task, whole, blocks)
    ticket = ticket_of(task.get("title") or "")
    prs = card_prs(pack, card_id, ticket)
    from cockpitlib.worktree import card_checkout

    checkout = card_checkout(
        ticket,
        task.get("workspace_path") or "",
        [pr.get("repo") for pr in prs if isinstance(pr, dict)],
        task.get("body") or "",
    )
    return {
        "id": task.get("id") or card_id,
        "title": task.get("title") or "",
        "status": task.get("status") or "",
        "assignee": task.get("assignee") or "",
        "prs": prs,
        "created": _iso(task.get("created_at")),
        "started": _iso(task.get("started_at")),
        "completed": _iso(task.get("completed_at")),
        "body_html": _plain_html(task.get("body") or ""),
        "result_html": _plain_html(result) if result else "",
        "error": task.get("last_failure_error") or "",
        "skills": skills,
        "workspace": task.get("workspace_path") or "",
        "worktree": checkout or None,  # the checkout it works in: the card shows its diff and opens the IDE on it
        "comments": comments,
        "events": events,
        "brief": attached.get("brief"),
        "attachments": attached,
    }


_OPEN_INTENT = {"pending", "endorsed", "held", "returned", "posted"}
_CLOSED_CARD = {"done", "archived", "cancelled"}


def _qa_summary(ticket, pack=None):
    """The ticket's records folder and how many test runs it holds (the QA page's own reading of both). A list of
    tickets passes the pack it already loaded: read again per ticket, the pack was most of a Tickets page."""
    from cockpitlib.qa_view import _runs_of, qa_dir

    folder = qa_dir(ticket)
    if not folder:
        return {"dir": None, "runs": 0}
    return {"dir": folder, "runs": len(_runs_of(folder, pack))}


def _ticket_row(ticket, intents, cards, pack=None):
    from cockpitlib.worktree import worktree_status

    counts = {}
    for card in cards:
        status = card.get("status") or ""
        counts[status] = counts.get(status, 0) + 1
    open_cards = [card for card in cards if (card.get("status") or "") not in _CLOSED_CARD]
    flows = []
    for card in cards:
        flow = card.get("flow") or ""
        if flow and flow not in flows:
            flows.append(flow)
    phase = "in flight"
    if any((card.get("status") or "") in ("blocked", "triage") for card in cards):
        phase = "blocked"
    elif open_cards:
        phase = "running"
    started = ""
    for card in cards:
        if card.get("created_at") and not started:
            started = str(card["created_at"])
    last = max(cards, key=lambda card: (str(card.get("created_at") or ""), str(card.get("id")))) if cards else None
    return {
        "ticket": ticket,
        "intents": {},
        "intent_rows": [{"id": row["id"], "status": row.get("status"), "type": row.get("type")} for row in intents],
        "intents_total": len(intents),
        "intents_open": sum(1 for row in intents if row.get("status") in _OPEN_INTENT),
        "cards": counts,
        "card_list": [
            {"id": card["id"], "title": card["title"], "status": card["status"], "assignee": card["assignee"]}
            for card in cards
        ],
        "cards_total": len(cards),
        "cards_open": len(open_cards),
        "worktrees": worktree_status(ticket),
        "phase": phase,
        "flow": flows[0] if flows else "",
        "flows": flows,
        "qa": _qa_summary(ticket, pack),
        "started": started,
        "last_card": {key: last.get(key) for key in ("id", "title", "status", "flow", "assignee")} if last else None,
    }


def _ticket_index(pack, only: str = ""):
    """Every ticket's row; `only` builds just that ticket's (each row reads its checkouts with git)."""
    from cockpitlib.intents import all_intents
    from cockpitlib.kanban import board_cards

    grouped_intents = {}
    for row in all_intents():
        key = row.get("ticket") or ""
        if not key or (only and key != only):
            continue
        grouped_intents.setdefault(key, []).append(row)
    grouped_cards = {}
    for card in board_cards(pack["board"], pack):
        if only and card["ticket"] != only:
            continue
        grouped_cards.setdefault(card["ticket"], []).append(card)
    keys = sorted(set(grouped_intents) | set(grouped_cards))
    from cockpitlib.tracker import titles

    named = titles(pack, keys)
    # each row asks git about the ticket's checkouts: the tickets are read side by side, and come back in their order
    from concurrent.futures import ThreadPoolExecutor

    with ThreadPoolExecutor(max_workers=8) as pool:
        built = list(
            pool.map(
                lambda key: _ticket_row(key, grouped_intents.get(key) or [], grouped_cards.get(key) or [], pack), keys
            )
        )
    rows = {
        key: {
            **row,
            "summary": named[key],
            "last_active": _last_active(grouped_intents.get(key) or [], grouped_cards.get(key) or []),
        }
        for key, row in zip(keys, built)
    }
    # newest activity first, like the QA evidence table (a ticket's cards and its outbox items)
    return dict(sorted(rows.items(), key=lambda item: (item[1]["last_active"], item[0]), reverse=True))


def _when(value) -> float:
    """A record's time as epoch seconds: a number, or an ISO date."""
    if value in (None, ""):
        return 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        pass
    import datetime

    try:
        return datetime.datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return 0.0


def _last_active(intents, cards) -> float:
    """When the ticket last moved: its newest card (created or completed) or outbox item (created or published)."""
    times = [_when(card.get(key)) for card in cards for key in ("completed_at", "created_at")]
    times += [_when(intent.get("created_at")) for intent in intents]
    times += [
        _when((intent.get("receipt") or {}).get("time"))
        for intent in intents
        if isinstance(intent.get("receipt"), dict)
    ]
    return max(times, default=0.0)


def mount(router):
    @router.get("/repos")
    def repos():
        from cockpitlib.pack import desktop_hints, forge_org, tracker_project, tracker_url
        from cockpitlib.trackers import kind_of

        pack = _guard()
        staging = _staging(pack)
        return {
            "repos": _repos(pack),
            "org": forge_org(pack),
            "board": pack["board"],
            "tracker": tracker_url(pack),
            "project": tracker_project(pack) or "",
            "origins": staging["origins"],
            "mermaid_url": (pack.get("desktop") or {}).get("mermaid_url") or "",
            "hints": desktop_hints(pack),
            # which tracker the pack writes to, so a page names it by its own name or says "tracker"
            "tracker_kind": kind_of(pack.get("tracker") or {}),
        }

    @router.get("/intent-types")
    def intent_types():
        _guard()
        from cockpitlib.intents import TYPES

        return {"types": list(TYPES)}

    @router.post("/hold")
    def hold(body: dict):
        pack = _guard()
        from cockpitlib.outbox import hold as do_hold
        from cockpitlib.outbox import human_gate

        try:
            human_gate()
            row = do_hold(body.get("id"), body.get("reason") or "held", waits=body.get("waits") or "human", pack=pack)
        except (CockpitError, FileNotFoundError) as exc:
            raise HTTPException(400, str(exc)) from exc
        return {"ok": True, "id": row["id"], "status": row["status"]}

    @router.post("/confirm")
    def confirm(body: dict):
        """The human confirms a hold that waits on them and asks nothing: endorsed as theirs; Publish is their next step."""
        pack = _guard()
        from cockpitlib.outbox import confirm as do_confirm

        try:
            row = do_confirm(body.get("id"), pack=pack)
        except (CockpitError, FileNotFoundError) as exc:
            raise HTTPException(400, str(exc)) from exc
        return {"ok": True, "id": row["id"], "status": row["status"]}

    @router.post("/drop")
    def drop(body: dict):
        _guard()
        from cockpitlib.outbox import drop as do_drop
        from cockpitlib.outbox import human_gate

        try:
            human_gate()
            row = do_drop(body.get("id"), body.get("note") or "")
        except (CockpitError, FileNotFoundError) as exc:
            raise HTTPException(400, str(exc)) from exc
        return {"ok": True, "id": row["id"], "status": row["status"]}

    @router.post("/apply-note")
    def apply_note(body: dict):
        """The human applies the patch of an infrastructure note: committed on the ticket's checkout as theirs, its push
        filed for the gate (cockpitlib.infra_note)."""
        pack = _guard()
        if body.get("confirm") != body.get("id"):
            raise HTTPException(400, "confirm must echo the id")
        from cockpitlib.infra_note import apply

        try:
            done = apply(pack, body.get("id") or "")
        except (CockpitError, FileNotFoundError) as exc:
            raise HTTPException(400, str(exc)) from exc
        return {
            "ok": True,
            **done,
            "out": f"{done['commit'][:9]} committed ({len(done['files'])} file(s)); its push is {done['push']}",
        }

    @router.post("/return")
    def return_intent(body: dict):
        """Send an intent back to its lane with the human's instruction: a rework card, and a tester and a reviewer
        behind it when the change is code."""
        pack = _guard()
        from cockpitlib.gate import return_intent as send_back

        try:
            row = send_back(
                pack,
                body.get("id") or "",
                body.get("instruction") or "",
                assignee=body.get("assignee") or "",
                evidence=body.get("evidence") or [],
                chain=not body.get("no_chain"),
            )
        except (CockpitError, FileNotFoundError) as exc:
            raise HTTPException(400, str(exc)) from exc
        returned = row["returned"]
        return {
            "ok": True,
            "id": row["id"],
            "status": row["status"],
            "card_id": returned["card"],
            "lane": returned["lane"],
            "chain": returned["chain"],
            "card_error": returned.get("card_error") or "",
            "out": f"{row['id']} back to {returned['lane'] or 'its lane'} on {returned['card']}"
            + (f" ({returned['card_error']})" if returned.get("card_error") else ""),
        }

    @router.post("/reply")
    def reply(body: dict):
        """The human's answer to the digest, by number: publish all | publish 1-3,5 | hold 4: why | drop 5 | open 2."""
        pack = _guard()
        from cockpitlib.gate import reply as answer

        try:
            lines = answer(pack, body.get("text") or "")
        except (CockpitError, FileNotFoundError) as exc:
            raise HTTPException(400, str(exc)) from exc
        return {"ok": not any("stopped here" in line for line in lines), "lines": lines}

    @router.post("/review-discard")
    def review_discard(body: dict):
        pack = _guard()
        if body.get("confirm") != body.get("id"):
            raise HTTPException(400, "confirm must echo the id")
        from cockpitlib.intents import load, save
        from cockpitlib.publish import discard_pending, forge_for

        try:
            row = load(body.get("id"))
            discard_pending(row, forge_for(pack))
        except (CockpitError, FileNotFoundError) as exc:
            raise HTTPException(400, str(exc)) from exc
        save(row)
        return {"ok": True, "id": row["id"], "status": row["status"], "receipt": row.get("receipt")}

    @router.post("/upload")
    def upload(body: dict):
        pack = _guard()
        ticket = str(body.get("ticket") or "").strip()
        if not ticket:
            raise HTTPException(400, "missing ticket")
        ticket = _ticket(pack, ticket)  # the ticket names a folder under qa/: never a path
        name = os.path.basename(body.get("name") or "note.txt")
        if "b64" in body:  # a file chosen or pasted in the page (bytes): qa/<ticket>/human/<stamp>/<name>
            import base64
            import binascii
            import datetime
            import re

            try:
                raw = base64.b64decode(body["b64"], validate=True)
            except (binascii.Error, ValueError) as exc:
                raise HTTPException(400, "the file could not be read") from exc
            if not raw:
                raise HTTPException(400, "empty file")
            if len(raw) > MAX_BYTES:
                raise HTTPException(400, "file is over 40 MB")
            try:
                if _secret(raw.decode("utf-8")):
                    raise HTTPException(400, "file contains a secret")
            except UnicodeDecodeError:
                pass
            name = re.sub(r"[^A-Za-z0-9._ -]", "_", name)[:120].strip(". ") or "file"
            folder = qa_of(ticket, "human", datetime.datetime.now().strftime("%Y%m%d-%H%M%S"))
            os.makedirs(folder, exist_ok=True)
            path = os.path.join(folder, name)
            stem, ext = os.path.splitext(name)
            count = 1
            while os.path.exists(path):  # two files of one name in the same second are both kept
                count += 1
                path = os.path.join(folder, f"{stem}-{count}{ext}")
            write_bytes(path, raw)
            return {"ok": True, "path": path, "size": len(raw), "pack": pack["name"]}
        folder = qa_of(ticket)
        os.makedirs(folder, exist_ok=True)
        path = os.path.join(folder, name)
        text = body.get("text") or ""
        if len(text.encode("utf-8")) > MAX_BYTES:
            raise HTTPException(400, "file is over 40 MB")
        if _secret(text):
            raise HTTPException(400, "file contains a secret")
        write_text(path, text)
        return {"ok": True, "path": path, "pack": pack["name"]}

    @router.post("/ack")
    def ack(body: dict):
        _guard()
        from cockpitlib.outbox import ack as do_ack

        try:
            row = do_ack(body.get("id"))
        except (CockpitError, FileNotFoundError) as exc:
            raise HTTPException(400, str(exc)) from exc
        return {"ok": True, "id": row["id"], "status": row["status"]}

    @router.post("/reopen-flow")
    def reopen_flow(body: dict):
        pack = _guard()
        from cockpitlib.acts import continue_ticket
        from cockpitlib.errors import Conflict

        try:
            made = continue_ticket(
                pack,
                _ticket(pack, body.get("ticket"), blank=True),
                body.get("prompt") or "",
                body.get("evidence") or [],
                body.get("kind") or "reopen",
                repos=body.get("repos") or None,
            )
        except Conflict as exc:
            raise HTTPException(409, str(exc)) from exc
        except CockpitError as exc:
            raise HTTPException(400, str(exc)) from exc
        if body.get("from_answer"):  # reopened from an answer row: the row records it and leaves
            from cockpitlib.answers import use

            use(str(body["from_answer"]), body.get("kind") or "reopen", made.get("card_id") or "")
        return made

    @router.post("/answer-followup")
    def answer_followup(body: dict):
        """A follow-up question on a finished answer (the patch plan is the preset): a new card of the same mode with the
        answer's files as evidence."""
        pack = _guard()
        from cockpitlib.answers import followup
        from cockpitlib.errors import Conflict

        try:
            return followup(pack, body.get("card") or "", body.get("prompt") or "")
        except Conflict as exc:
            raise HTTPException(409, str(exc)) from exc
        except CockpitError as exc:
            raise HTTPException(400, str(exc)) from exc

    @router.post("/answer-dismiss")
    def answer_dismiss(body: dict):
        pack = _guard()
        from cockpitlib.answers import dismiss

        try:
            return dismiss(pack, body.get("card") or "")
        except CockpitError as exc:
            raise HTTPException(400, str(exc)) from exc

    @router.post("/tracker-note-dismiss")
    def tracker_note_dismiss(body: dict):
        """A tracker comment noted while the ticket's done row waited: read, the row leaves."""
        _guard()
        from cockpitlib.tracker_watch import dismiss

        try:
            return dismiss(body.get("id") or "")
        except CockpitError as exc:
            raise HTTPException(400, str(exc)) from exc

    @router.post("/verify")
    def verify(body: dict):
        pack = _guard()
        from cockpitlib.outbox import verify as do_verify

        try:
            problems = do_verify(body.get("id"), pack=pack)  # with the pack, as endorse verifies: the push checks run
        except (CockpitError, FileNotFoundError) as exc:
            raise HTTPException(400, str(exc)) from exc
        return {
            "ok": not problems,
            "problems": problems,
            "out": "verify ok" if not problems else "verify: " + " · ".join(problems),
        }

    @router.post("/reprobe")
    def reprobe(body: dict):
        """Read git again for a push intent whose probe failed when it was written; it goes back to the gatekeeper."""
        pack = _guard()
        from cockpitlib.outbox import human_gate
        from cockpitlib.outbox import reprobe as do_reprobe

        try:
            human_gate("re-probe")
            row = do_reprobe(str(body.get("id") or ""), pack=pack)
        except (CockpitError, FileNotFoundError, ValueError) as exc:
            raise HTTPException(400, str(exc)) from exc
        return {
            "ok": True,
            "id": row["id"],
            "status": row["status"],
            "out": f"{row['id']} probed again: {row['status']}",
        }

    @router.post("/digest")
    def digest():
        """Number the open intents for the human's reply."""
        pack = _guard()
        from cockpitlib.gate import digest as numbered

        rows = numbered(pack)
        return {"ok": True, "count": len(rows), "rows": rows}

    @router.get("/diff")
    def diff(id: str = "", ticket: str = "", repo: str = "", mode: str = "base"):
        """The diff pane: an intent's push against the base (base), against
        origin (origin), the pair's real change after its rebase step (change) or the rebase itself (rebase); or a ticket
        checkout against the base or origin. Read-only."""
        pack = _guard()
        # a read of a checkout by its folder name: a name no ticket has is an empty pane, as before; a path is refused
        ticket, repo, mode = (_chat(ticket) if ticket else ""), _repo(repo), _diff_mode(mode)
        from cockpitlib import diffs

        def empty(exc):  # no checkout yet: the pane says so instead of failing
            return {
                "ticket": ticket,
                "repo": repo,
                "intent": id,
                "mode": mode,
                "diff": "",
                "stat": "",
                "commits": [],
                "files": [],
                "dropped": [],
                "range": "",
                "head": "",
                "note": str(exc),
            }

        if id:
            from dashboard.cockpit.router import _rows

            rows = _rows(pack)
            row = next((item for item in rows if item.get("id") == id), None)
            if row is None:
                raise HTTPException(404, f"{id} not in the outbox")
            ticket, repo = row.get("ticket") or ticket, (row.get("payload") or {}).get("repo") or repo
            try:
                return diffs.intent_diff(pack, row, rows, mode)
            except CockpitError as exc:
                if str(exc).startswith("no worktree"):
                    return empty(exc)
                raise HTTPException(400, str(exc)) from exc
        if not ticket or not repo:
            raise HTTPException(400, "id, or ticket and repo")
        try:
            return diffs.checkout_diff(pack, ticket, repo, mode)
        except CockpitError as exc:
            if str(exc).startswith("no worktree"):
                return empty(exc)
            raise HTTPException(400, str(exc)) from exc

    @router.post("/fetch")
    def fetch(body: dict):
        pack = _guard()
        from cockpitlib.acts import fetch_ref

        ticket, repo = _ticket(pack, body.get("ticket"), blank=True), _repo(body.get("repo"))
        return _act(lambda: fetch_ref(pack, repo, body.get("branch") or "", ticket))

    @router.get("/worktrees")
    def worktrees(ticket: str = ""):
        pack = _guard()
        ticket = _ticket(pack, ticket, blank=True)
        from cockpitlib.worktree import list_worktrees, ticket_checkouts

        return {"worktrees": ticket_checkouts(ticket, pack) if ticket else list_worktrees()}

    @router.post("/open-ide")
    def open_ide(body: dict):
        """The IDE on a ticket's worktrees, from any pane of the ticket (an intent's pane names the intent). A ticket with
        no worktree yet says so."""
        pack = _guard()
        ticket = _ticket(pack, body.get("ticket"), blank=True)
        if not ticket and body.get("id"):
            from cockpitlib.intents import load

            try:
                ticket = load(str(body["id"])).get("ticket") or ""
            except (FileNotFoundError, ValueError) as exc:
                raise HTTPException(404, f"no intent {body['id']}") from exc
        from cockpitlib.ops import ide_open
        from cockpitlib.worktree import ticket_checkouts

        trees = ticket_checkouts(ticket, pack) if ticket else []
        if ticket and not trees and not body.get("file"):
            return {
                "ok": True,
                "out": f"{ticket} has no worktree yet: the IDE opens on it once a lane makes one",
                "path": "",
                "worktrees": [],
            }
        file = str(body["file"]) if body.get("file") else ""
        try:
            out = ide_open(pack, ticket, file=file, worktrees=trees)
        except CockpitError as exc:
            raise HTTPException(500, str(exc)) from exc
        path = os.path.join(platform_dir(), f"ide-{ticket or 'own'}.json")
        return {"ok": True, "out": out, "path": path, "worktrees": trees}

    @router.post("/open-file")
    def open_file(body: dict):
        pack = _guard()
        path = body.get("path") or ""
        _under(qa(), outbox())(path.split(":")[0])
        from cockpitlib.ops import ide_launch

        try:
            out = ide_launch(pack, "file_command", path=path)
        except CockpitError as exc:
            raise HTTPException(500, str(exc)) from exc
        return {"ok": True, "path": path, "out": out or path}

    @router.get("/platform")
    def platform(days: int = 1):
        """The map with, per node, how many changes of the window touch it and how many are unread (an area carries
        its features' numbers as inherited), the changes themselves, and the base state."""
        pack = _guard()
        path = os.path.join(platform_dir(), "map.json")
        stored = _read(path) or {}
        tree, hint = _platform_tree(pack)
        state = stored.get("state") if isinstance(stored.get("state"), dict) else {}
        from cockpitlib.acts import ordered_changes

        fallback = stored.get("changes") if isinstance(stored.get("changes"), list) else []
        changes = ordered_changes(fallback)
        counts, inherited = _node_counts(tree, changes, days)
        if not counts and isinstance(stored.get("counts"), dict):
            counts = stored["counts"]
            inherited = stored.get("inherited") if isinstance(stored.get("inherited"), dict) else {}
        return {
            "root": stored.get("root") or pack["name"],
            "map": tree,
            "base": _base(pack),
            "hint": hint,
            "counts": counts,
            "inherited": inherited,
            "changes": changes,
            "state": state,
        }

    @router.get("/platform-change")
    def platform_change(repo: str = "", number: int = 0):
        _guard()
        from cockpitlib.acts import change_detail

        return change_detail(_repo(repo), number)

    @router.post("/platform-verdict")
    def platform_verdict(body: dict):
        _guard()
        from cockpitlib.acts import write_verdict

        repo, number = _repo(body.get("repo")), _number(body.get("number"))
        return _act(lambda: write_verdict(repo, number, body.get("text") or ""))

    @router.post("/platform-seen")
    def platform_seen(body: dict):
        pack = _guard()
        from cockpitlib.acts import mark_seen

        repo, number = _repo(body.get("repo")), _number(body.get("number"))
        return _act(lambda: mark_seen(pack, repo, number, mark_all=bool(body.get("all"))))

    @router.post("/platform-scan")
    def platform_scan(body: dict):
        pack = _guard()
        from datetime import datetime

        from cockpitlib.ops import map_build

        now = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        base = _base(pack)
        from cockpitlib.acts import scan_base

        message = map_build(pack) + "\n" + scan_base(pack, days=int(body.get("days") or 7))
        path = os.path.join(platform_dir(), "map.json")
        record = _read(path) or {}
        state = record.get("state") if isinstance(record.get("state"), dict) else {}
        state[base] = {"last_scan": now}
        record["state"] = state
        record["base"] = base
        _write(path, record)
        _health("base-watch", detail=f"scan {base}")
        return {"ok": True, "out": message, "base": base, "days": body.get("days") or 7}

    @router.get("/platform-node-diff")
    def platform_node_diff(id: str = "", days: int = 7):
        pack = _guard()
        from cockpitlib.acts import node_diff

        return node_diff(pack, id, days)

    @router.post("/pr-scan")
    def pr_scan():
        _guard()
        from cockpitlib.ops import watch_pr

        return {"ok": True, "out": watch_pr()}

    @router.post("/pr-treat")
    def pr_treat(body: dict):
        pack = _guard()
        from cockpitlib.acts import treat_pr

        ticket, repo, number = (
            _ticket(pack, body.get("ticket"), blank=True),
            _repo(body.get("repo")),
            _number(body.get("number")),
        )
        return _act(lambda: treat_pr(pack, ticket, repo, number, body.get("note") or ""))

    @router.get("/advisories")
    def advisories():
        """The stack watch's record: every advisory, the sources' health, and the manifest's size."""
        _guard()
        from cockpitlib.advisories import manifest_path
        from cockpitlib.advisories.manifest import counts
        from cockpitlib.advisories.scan import state
        from cockpitlib.store import read_json

        manifest = read_json(manifest_path()) or {}
        return {**state(), "manifest": {"time": manifest.get("time"), "components": counts(manifest)}}

    @router.post("/advisory-ack")
    def advisory_ack(body: dict):
        """Acknowledge with a note: the row leaves the Inbox; the Platform tab keeps it with the note."""
        return _advisory_ack(body, True)

    @router.post("/advisory-unack")
    def advisory_unack(body: dict):
        return _advisory_ack(body, False)

    def _advisory_ack(body, on):
        pack = _guard()
        from cockpitlib.advisories.card import checked
        from cockpitlib.advisories.scan import ack

        advisory_id = _act(lambda: checked(body.get("id")))
        hit = ack(pack, advisory_id, str(body.get("note") or "").strip(), on=on)
        if not hit:
            raise HTTPException(404, f"no advisory {advisory_id}")
        return {"ok": True, "out": f"{hit['id']}: {'acknowledged' if on else 'unacknowledged'}", "advisory": hit}

    @router.post("/advisory-card")
    def advisory_card(body: dict):
        """An analyst card to assess one advisory; 409 while one is open."""
        pack = _guard()
        from cockpitlib.advisories.card import make

        return _act(lambda: make(pack, body.get("id")))

    @router.post("/pr-forget")
    def pr_forget(body: dict):
        pack = _guard()
        from cockpitlib.acts import forget_pr

        ticket, repo, number = (
            _ticket(pack, body.get("ticket"), blank=True),
            _repo(body.get("repo")),
            _number(body.get("number")),
        )
        return _act(lambda: forget_pr(ticket, repo, number))

    @router.post("/pr-seen")
    def pr_seen(body: dict):
        pack = _guard()
        from cockpitlib.acts import mark_pr_seen

        ticket, repo, number = (
            _ticket(pack, body.get("ticket"), blank=True),
            _repo(body.get("repo")),
            _number(body.get("number")),
        )
        return _act(lambda: mark_pr_seen(ticket, repo, number))

    @router.post("/ci-mark")
    def ci_mark(body: dict):
        pack = _guard()
        from cockpitlib.acts import mark_ci

        ticket, repo, sha = (
            _ticket(pack, body.get("ticket"), blank=True),
            _repo(body.get("repo")),
            _sha(body.get("sha")),
        )
        return _act(
            lambda: mark_ci(
                pack,
                ticket,
                sha,
                body.get("verdict") or "",
                repo,
                body.get("run_id") or "",
            )
        )

    @router.post("/ci-forget")
    def ci_forget(body: dict):
        pack = _guard()
        from cockpitlib.acts import forget_ci

        ticket, sha = _ticket(pack, body.get("ticket"), blank=True), _sha(body.get("sha"))
        return _act(lambda: forget_ci(ticket, sha))

    @router.post("/ci-dismiss")
    def ci_dismiss(body: dict):
        pack = _guard()
        from cockpitlib.acts import dismiss_ci

        ticket, repo, sha = (
            _ticket(pack, body.get("ticket"), blank=True),
            _repo(body.get("repo")),
            _sha(body.get("sha")),
        )
        _health("ci-watch", detail=f"dismiss {ticket}")
        return _act(lambda: dismiss_ci(pack, ticket, repo, sha))

    @router.post("/pr-rereview")
    def pr_rereview(body: dict):
        pack = _guard()
        from cockpitlib.pr_watch import request_rereview

        ticket, repo, number = (
            _ticket(pack, body.get("ticket"), blank=True),
            _repo(body.get("repo")),
            _number(body.get("number")),
        )
        return _act(
            lambda: request_rereview(
                pack, ticket, repo, number, body.get("note") or "", supersede=body.get("supersede") or ""
            )
        )

    @router.get("/pr")
    def pr(repo: str = "", number: int = 0, ticket: str = ""):
        pack = _guard()
        ticket, repo = _ticket(pack, ticket, blank=True), _repo(repo)
        from cockpitlib.acts import pr_state
        from cockpitlib.pack import forge_org

        state = pr_state(ticket, repo, number)
        state["org"] = forge_org(pack)
        return state

    @router.get("/pr-diff")
    def pr_diff(repo: str = "", number: int = 0, ticket: str = "", mode: str = ""):
        pack = _guard()
        ticket, repo = _ticket(pack, ticket, blank=True), _repo(repo)
        from cockpitlib.acts import checkout_diff, compare_diff_text, pr_diff_text, pr_state
        from cockpitlib.pack import forge_org

        state = pr_state(ticket, repo, number) if ticket else {}
        reviewed = str(state.get("reviewed_sha") or "")
        head = str(state.get("head_sha") or "")
        if mode == "since" and reviewed and head == reviewed:
            return {"repo": repo, "number": number, "ticket": ticket, "diff": "", "files": [], "commits": []}
        if mode == "since" and reviewed and head:
            since = compare_diff_text(forge_org(pack), repo, reviewed, head)
            if (
                since.strip()
            ):  # only what the author pushed since my review; a rewritten history falls back to the whole PR
                return {
                    "repo": repo,
                    "number": number,
                    "ticket": ticket,
                    "diff": since,
                    "files": [],
                    "commits": [f"{reviewed[:9]}..{head[:9]}"],
                    "note": f"since your review at {reviewed[:9]}",
                }
        text = pr_diff_text(forge_org(pack), repo, number)
        if not text:
            text = checkout_diff(pack, ticket, repo)
        commits = [head or "diff"] if text.strip() else []
        return {"repo": repo, "number": number, "ticket": ticket, "diff": text, "files": [], "commits": commits}

    @router.get("/qa")
    def qa_index(ticket: str = ""):
        """Runs and evidence of one ticket, or the index of every ticket that has runs."""
        _guard()
        from cockpitlib import qa_view

        if ticket:
            if qa_view.qa_dir(ticket) is None and not qa_view.TICKET.match(ticket):
                raise HTTPException(400, "bad ticket")
            return qa_view.ticket(ticket)
        return qa_view.index()

    @router.get("/qa-file")
    def qa_file(path: str):
        """One evidence file: media as base64 (the page makes a blob URL), text inline, markdown rendered too."""
        _guard()
        from cockpitlib import qa_view

        real = _under(qa(), outbox())(path)
        if not os.path.isfile(real):
            raise HTTPException(404, "missing file")
        if os.path.getsize(real) > MAX_BYTES:
            raise HTTPException(400, "file is over 40 MB")
        record = qa_view.file_record(real)
        if record.get("text") and _secret(record["text"]):
            raise HTTPException(400, "file contains a secret")
        return {"path": real, **record}

    @router.get("/tickets")
    def tickets():
        pack = _guard()
        return {"tickets": list(_ticket_index(pack).values())}

    @router.get("/ticket")
    def ticket(ticket: str):
        pack = _guard()
        ticket = _ticket(pack, ticket)
        from cockpitlib.halt import halted

        row = _ticket_index(pack, only=ticket).get(ticket) or _ticket_row(ticket, [], [])
        row["halted"] = bool(halted(ticket))
        from cockpitlib.activity import ticket_activity
        from cockpitlib.plan import _parse, brief_of, show
        from cockpitlib.render import markdown

        text = show(ticket)
        _head, parts = _parse(text)
        brief = brief_of(text)
        row["brief"] = markdown(brief) if brief else None
        row["plan_parts"] = [{"title": name, "html": markdown(body)} for name, body in parts if name.lower() != "brief"]
        row["plan_line"] = next((line.strip() for line in brief.splitlines() if line.strip()), "")[:200]
        row["activity"] = ticket_activity(pack, ticket)[-80:]
        row["intent_list"] = row.pop("intent_rows")
        from cockpitlib.acts import describe_ticket

        row.update(describe_ticket(pack, ticket))
        return row

    @router.post("/ticket-archive")
    def ticket_archive(body: dict):
        pack = _guard()
        ticket = _ticket(pack, body.get("ticket"))
        if body.get("confirm") != ticket:
            raise HTTPException(400, "confirm=<ticket> required")
        from cockpitlib.acts import archive_ticket

        return _act(lambda: archive_ticket(pack, ticket))

    @router.post("/ticket-halt")
    def ticket_halt(body: dict):
        pack = _guard()
        from cockpitlib.acts import halt_ticket

        ticket = _ticket(pack, body.get("ticket"))
        if body.get("confirm") != ticket:
            raise HTTPException(400, "confirm=<ticket> required")
        lines = _act(lambda: halt_ticket(pack, ticket, body.get("note") or ""))
        return {"ok": True, "out": "\n".join(lines)}

    @router.post("/ticket-resume")
    def ticket_resume(body: dict):
        pack = _guard()
        from cockpitlib.acts import resume_ticket

        ticket = _ticket(pack, body.get("ticket"))
        return {"ok": True, "out": resume_ticket(ticket)}

    @router.post("/ticket-delete")
    def ticket_delete(body: dict):
        pack = _guard()
        from cockpitlib.acts import delete_ticket

        ticket = _ticket(pack, body.get("ticket"))
        if body.get("confirm") != ticket:
            raise HTTPException(400, "confirm=<ticket> required")
        return _act(lambda: delete_ticket(pack, ticket, force=bool(body.get("force"))))

    @router.get("/card")
    def card(id: str = ""):
        pack = _guard()
        return _card_detail(pack, id)

    @router.post("/answer")
    def answer(body: dict):
        pack = _guard()
        from cockpitlib.acts import answer_card

        unblock = body.get("unblock", True)
        return _act(lambda: answer_card(pack, body.get("id") or "", body.get("text") or "", unblock=unblock))

    @router.post("/privileged-approve")
    def privileged_approve(body: dict):
        pack = _guard()
        from cockpitlib.lend import approve
        from cockpitlib.vault_key import human_present

        with human_present():  # the human pressed Approve: the vault key may ask them
            return _act(
                lambda: {
                    "ok": True,
                    "out": approve(body.get("card") or "", body.get("lane") or "", body.get("slot") or 1, pack),
                }
            )

    @router.post("/privileged-deny")
    def privileged_deny(body: dict):
        pack = _guard()
        from cockpitlib.lend import deny

        return {"ok": True, "out": deny(body.get("card") or "", pack)}

    @router.post("/privileged-step")
    def privileged_step(body: dict):
        _guard()
        from cockpitlib.lend import use_step

        return _act(lambda: {"ok": True, "out": use_step(body.get("card") or "", body.get("step") or "")})

    @router.post("/platform-unseen")
    def platform_unseen(body: dict):
        _guard()
        from cockpitlib.acts import mark_unseen

        repo, number = _repo(body.get("repo")), _number(body.get("number"))
        return _act(lambda: mark_unseen(repo, number, bool(body.get("all"))))

    @router.post("/login-rejected")
    def login_rejected(body: dict):
        pack = _guard()
        from cockpitlib.vault import reject_login

        return _act(lambda: reject_login(pack, body.get("card") or "", body.get("email") or ""))

    @router.post("/login-fill")
    def login_fill(body: dict):
        """The lane types the identifier. The vault fills the secret on the slot."""
        pack = _guard()
        lane = os.environ.get("COCKPIT_LANE") or ""
        if not lane:
            raise HTTPException(400, "missing lane")
        origin = str((body or {}).get("origin") or "").strip()
        email = str((body or {}).get("email") or "").strip()
        if not origin or not email:
            raise HTTPException(400, "missing login")
        from cockpitlib.vault import fill_login

        slot = int((body or {}).get("slot") or 1)
        return _act(lambda: fill_login(lane, origin, email, slot, pack, (body or {}).get("card") or ""))

    @router.post("/ask-approve")
    def ask_approve(body: dict):
        """The human approves one of the pack's own asks (pack.yaml asks) on the card that made it."""
        pack = _guard()
        from cockpitlib.asks import approve

        return _act(lambda: approve(pack, str(body.get("id") or "")))

    @router.post("/staging-credentials")
    def staging_credentials(body: dict):
        pack = _guard()
        staging = _staging(pack)
        email_in = str(body.get("email") or "").strip().lower()
        from cockpitlib.ops import vault_put

        def go():
            from cockpitlib.accounts import manifest

            listed = [
                str(row["origin"])
                for row in (manifest(pack).get("accounts") or [])
                if str(row.get("identifier") or "").lower() == email_in and row.get("origin")
            ]
            known = {str(value) for value in (staging.get("origins") or {}).values() if value} | set(listed)
            asked = str(body.get("origin") or "")
            # the origin the lane asked for when the pack knows it; else the account's origin in the pack's accounts (a
            # customer logs in elsewhere than an editor); else the app's. An origin the pack does not know is never stored.
            origin = (
                (asked if asked in known else "")
                or (listed[0] if listed else "")
                or (staging.get("origins") or {}).get("app")
                or ""
            )
            from cockpitlib.lane_vault import readers

            lane = str(body.get("lane") or "").strip()
            if not lane and body.get("id"):
                from cockpitlib.lend import _card_lane

                lane = _card_lane(pack, str(body["id"]))
            email = body.get("email") or ""
            if not lane and not readers(pack, origin, email):
                raise CockpitError("name the lane that owns this login, or list it in the pack's shared logins")
            from cockpitlib.vault_key import human_present

            with human_present():  # the human typed this login in: the vault key may ask them
                out = vault_put(
                    pack,
                    origin,
                    email,
                    body.get("password") or "",
                    otp=body.get("otp") or body.get("otp_secret") or None,
                    lane=lane,
                )
            resumed = ""
            if body.get("id"):  # the card that asked resumes, parked in triage or blocked
                from cockpitlib.acts import answer_card

                answered = answer_card(pack, str(body["id"]), f"login stored for {email} on {origin}: continue")
                resumed = f"; {body['id']} {answered.get('out') or 'resumed'}"
            return {"ok": True, "out": f"{out} for {origin}{resumed}", "origin": origin}

        return _act(go)

    @router.get("/standup")
    def standup_get():
        pack = _guard()
        from cockpitlib.setup import standup_enabled

        path = os.path.join(platform_dir(), "standup.md")
        text = ""
        if os.path.isfile(path) and standup_enabled(pack):  # off: no draft, so the Inbox has no standup row
            text = open(path, encoding="utf-8").read()
        sent_path = os.path.join(platform_dir(), "standup.sent")
        sent_body = open(sent_path, encoding="utf-8").read() if os.path.isfile(sent_path) else ""
        kept_path = os.path.join(platform_dir(), "standup.kept")
        kept_body = open(kept_path, encoding="utf-8").read() if os.path.isfile(kept_path) else ""
        status = ""
        if text.strip():
            status = (
                "sent"
                if sent_body.strip() == text.strip()
                else "kept"
                if kept_body.strip() == text.strip()
                else "draft"
            )
        since = ""
        for line in text.splitlines():
            if line.startswith("Since "):
                since = line[len("Since ") :].strip()
                break
        meta = _read(os.path.join(platform_dir(), "standup.json")) or {}
        return {
            "draft": text,
            "note": text,
            "markdown": text,
            "sent": bool(sent_body.strip()) and status == "sent",
            "status": status,
            "markdown_html": _plain_html(text),
            "items": int(meta.get("items") or text.count("\n- ")),
            "day": meta.get("day") or text.split("\n", 1)[0].replace("# Standup ", "").strip(),
            "since": meta.get("since") or since,
            "until": meta.get("until") or "",
            "drafted_at": meta.get("drafted_at") or "",
        }

    @router.post("/standup-update")
    def standup_update(body: dict):
        pack = _guard()
        from cockpitlib.ops import standup_draft

        message = _act(lambda: standup_draft(pack))
        path = os.path.join(platform_dir(), "standup.md")
        return {"ok": True, "path": path, "out": message}

    @router.post("/standup-confirm")
    def standup_confirm(body: dict = None):
        pack = _guard()
        from cockpitlib.acts import standup_send

        return _act(lambda: standup_send(pack, (body or {}).get("text") or ""))

    @router.get("/bumps")
    def bumps():
        pack = _guard()
        from cockpitlib.acts import started_bumps, visible_bumps

        shown = visible_bumps(pack)
        shown["started"] = started_bumps(pack)
        return shown

    @router.post("/bumps-dismiss")
    def bumps_dismiss(body: dict):
        pack = _guard()
        from cockpitlib.acts import dismiss_bumps

        return _act(lambda: dismiss_bumps(pack, body.get("repo") or "", body.get("numbers") or []))

    @router.post("/bumps-release")
    def bumps_release(body: dict):
        _guard()
        from cockpitlib.acts import release_bumps, visible_bumps

        released = release_bumps(body.get("repo") or "", body.get("numbers") or [])
        released["repos"] = list((visible_bumps().get("repos") or {}).keys())
        return released

    @router.post("/bumps-groom")
    def bumps_groom(body: dict):
        pack = _guard()
        from cockpitlib.acts import record_grooming

        return _act(lambda: record_grooming(pack, body.get("repo") or "", body.get("number"), body.get("act") or ""))

    @router.get("/shared-chrome")
    def shared_chrome():
        pack = _guard()
        from cockpitlib.settings import load as load_settings

        data = _read(os.path.join(watch_dir(), "shared-chrome.json")) or {
            "ticket": "",
            "until": 0,
            "hours": load_settings(pack)["shared_chrome_hours"],
        }
        return data

    @router.post("/shared-chrome-release")
    def shared_chrome_release():
        _guard()
        _write(os.path.join(watch_dir(), "shared-chrome.json"), {"ticket": "", "until": 0})
        return {"ok": True}

    @router.get("/refusals")
    def refusals_get():
        pack = _guard()
        from cockpitlib.refusals import unresolved

        return {"refusals": unresolved(pack)}

    @router.post("/refusal-dismiss")
    def refusal_dismiss(body: dict):
        _guard()
        from cockpitlib.refusals import dismiss

        key = str(body.get("key") or body.get("id") or "")
        return {"ok": dismiss(key), "id": key, "out": "refusal dismissed"}

    @router.post("/refusal-send-back")
    def refusal_send_back(body: dict):
        pack = _guard()
        from cockpitlib.kanban import open_cards
        from cockpitlib.lanes import free_lane
        from cockpitlib.refusals import dismiss, find

        row = find(str(body.get("key") or ""))
        ticket = str(body.get("ticket") or row.get("ticket") or "").strip()
        if not ticket:
            raise HTTPException(400, "missing ticket")
        ticket = _ticket(pack, ticket)
        note = str(body.get("note") or "").strip()
        why = (
            f"The {row.get('type')} you wrote on card {row.get('card') or '?'} was refused and nothing went out: {row.get('reason')}\n"
            if row
            else ""
        )
        from cockpitlib.halt import refuse

        try:
            refuse(ticket)
        except CockpitError as exc:
            status = exc.exit_code if exc.exit_code >= 400 else 400
            raise HTTPException(status, str(exc)) from exc
        # back to the kind of lane that wrote the refused intent (a tester's report goes back to a tester, not to a worker)
        wrote = str(row.get("lane") or "").split("-")[0] if row else ""
        kind_of = {
            "worker": "rework",
            "tester": "tester",
            "reviewer": "review",
            "intake": "reopened",
            "analyst": "analyst",
        }
        kind = kind_of.get(wrote, "rework")
        lane = free_lane(wrote if wrote in kind_of else "worker", pack, open_cards(pack["board"]), ticket=ticket)
        body_text = (
            why + (f"Human: {note}\n" if note else "") + "Fix what the refusal names, then write the intent again."
        )
        # an open card already carrying the refused intent (its return's rework card) gets the instruction, not a twin owner
        from cockpitlib.gate import send_back

        iid = str(row.get("intent") or "") if row else ""
        card_id, there = send_back(pack, kind, ticket, lane, body_text, iid, str(row.get("key") or "") if row else "")
        if row:
            dismiss(row["key"])
        said = f"{card_id} already carries {iid}: instruction added" if there else f"{card_id} for {lane}"
        return {"ok": True, "card_id": card_id, "out": said}

    @router.post("/watcher-run")
    def watcher_run(body: dict):
        _guard()
        from cockpitlib.acts import run_watcher

        record = _act(lambda: run_watcher(body.get("name") or "ci-watch"))
        out = str(
            record.get("summary")
            or record.get("detail")
            or ("ok" if record.get("ok") else record.get("error") or "failed")
        )
        return {"ok": record["ok"], "watcher": record, "out": out}

    @router.post("/plugin-act")
    def plugin_act(body: dict, request: Request = None):
        """A button on a plugin row's pane, answered back to that plugin.

        The page names the row and which of its actions; the payload comes off the row file the
        plugin wrote. Cockpit queues it and nothing more — the plugin drains it on its next pass.
        """
        pack = _guard()
        from cockpitlib.inbox import queue_act, row_id
        from cockpitlib.own_rows import PLUGIN, drain

        seen = getattr(request, "client", None)
        client = {
            "host": getattr(seen, "host", ""),
            "ua": (getattr(request, "headers", None) or {}).get("user-agent", ""),
        }
        own = row_id(body.get("plugin")) == PLUGIN
        if own:  # a row cockpit wrote itself: the press is the human's, it is applied now, and the answer says what came of it
            from cockpitlib.outbox import human_gate

            _act(lambda: human_gate("the buttons of an Inbox row"))
        queued = _act(
            lambda: queue_act(str(body.get("plugin") or ""), str(body.get("id") or ""), body.get("index"), client)
        )
        if not own:
            return {"ok": True, **queued}
        mine = [item for item in drain(pack) if item["row"] == row_id(body.get("id"))]
        out = mine[-1]["out"] if mine else "already applied"
        return {"ok": not mine or mine[-1]["ok"], **queued, "applied": True, "out": out}

    @router.post("/plugin-row-dismiss")
    def plugin_row_dismiss(body: dict):
        """Dismiss a row whose plugin is not installed any more: nothing else would ever take it away."""
        pack = _guard()
        from cockpitlib.inbox import dismiss_row
        from cockpitlib.outbox import human_gate

        def dismiss():
            human_gate("dismissing an Inbox row")
            return dismiss_row(str(body.get("plugin") or ""), str(body.get("id") or ""), pack)

        return {"ok": _act(dismiss), "out": "row dismissed"}

    @router.get("/update")
    def update_status():
        """The plugin against its repository: installed commit, local edits, the last check, the Desktop copy."""
        _guard()
        from cockpitlib.self_update import status

        return _act(status)

    @router.post("/update-check")
    def update_check(body: dict = None):
        _guard()
        from cockpitlib.self_update import check

        return _act(check)

    @router.post("/update-apply")
    def update_apply(body: dict = None):
        """Fast-forward the plugin to its repository, refresh what changed, restart the gateway (detached)."""
        _guard()
        from cockpitlib.outbox import human_gate
        from cockpitlib.self_update import apply

        _act(lambda: human_gate("updates"))  # a human act, like hold and drop: a lane's call is refused
        return _act(lambda: apply(restart=(body or {}).get("restart", True) is not False))

    @router.post("/settings")
    def settings_save(body: dict):
        pack = _guard()
        from cockpitlib.settings import save

        record = _act(lambda: save(pack, body or {}))
        return {"ok": True, "seats": record["seats"], "saved": True, "out": "saved"}

    @router.post("/worktree-gc")
    def worktree_gc(body: dict = None):
        """One pass over the stale worktrees, now: {dry_run: true} only lists what would go. The daily pass is the
        worktree_gc setting; this is the page's Preview and Run now."""
        pack = _guard()
        from cockpitlib.cleanup import gc

        body = body or {}
        result = _act(lambda: gc(pack, int(body.get("days") or 0), dry_run=bool(body.get("dry_run"))))
        result["out"] = result["lines"][-1]
        return result

    @router.post("/settings-apply")
    def settings_apply():
        pack = _guard()
        from cockpitlib.settings import ensure_seat_profiles

        created = _act(lambda: ensure_seat_profiles(pack))
        return {"ok": True, "out": "setup ok", "name": pack["name"], "created": created}

    @router.post("/card-archive")
    def card_archive(body: dict):
        pack = _guard()
        from cockpitlib.acts import archive_card

        return _act(lambda: archive_card(pack, body.get("id") or ""))

    @router.post("/sweep")
    def sweep():
        _guard()
        from cockpitlib.acts import request_sweep

        return {"ok": True, "out": request_sweep()}

    @router.get("/sweep-state")
    def sweep_state():
        _guard()
        from cockpitlib.acts import sweep_state as state

        return state()

    @router.get("/sweep-log")
    def sweep_log():
        _guard()
        path = os.path.join(watch_dir(), "sweep.log")
        text = ""
        if os.path.isfile(path):
            text = open(path, encoding="utf-8").read()
        return {"log": text}

    @router.post("/session")
    def session(body: dict):
        pack = _guard()
        from cockpitlib.acts import session_close, session_handoff, session_open

        action = body.get("action") or "open"
        if action == "close":
            out = _act(lambda: session_close(pack, body.get("slot") or 1))
            return {"ok": True, "session": {"action": action, "out": out}}
        if action == "handoff":
            out = _act(lambda: session_handoff(pack, body.get("slot") or 1, body.get("lane") or ""))
            return {"ok": True, "session": {"action": action, "out": out}}
        ticket = _ticket(pack, body.get("ticket"), blank=True)
        out = _act(lambda: session_open(pack, body.get("slot") or "auto", ticket))
        return {"ok": True, "session": {"action": "open", "out": out, "ticket": ticket}}

    @router.get("/slots")
    def slots():
        pack = _guard()
        from cockpitlib.slots import provider_for

        provider = provider_for(pack.get("slot_provider"), pack)
        return {"slots": provider.status(count=max(1, pack["seats"]["slots"]))}

    @router.get("/card-detail")
    def card_detail(id: str = ""):
        pack = _guard()
        return _card_detail(pack, id)

    @router.get("/board")
    def board(include_done_days: int | None = None):
        """Every open card, every card of a live ticket, and the other done ones of the last days (the pack's
        board_done_days unless asked), with the run state, the question when blocked and the last comment."""
        pack = _guard()
        from cockpitlib.board_view import board as board_view

        return board_view(pack, None if include_done_days is None else max(0, min(int(include_done_days), 30)))

    @router.get("/demo")
    def demo(ticket: str = ""):
        pack = _guard()
        ticket = _ticket(pack, ticket, blank=True)
        record = {}
        path = qa_of(ticket, "demo.json") if ticket else ""
        if path and os.path.isfile(path):
            try:
                record = json.load(open(path, encoding="utf-8"))
            except json.JSONDecodeError:
                record = {}
        if not isinstance(record, dict):
            record = {}
        for key in ("password", "secret", "otp", "seed"):
            record.pop(key, None)
        recorded_login = record.get("login") if isinstance(record.get("login"), dict) else {}
        account = record.get("account") or recorded_login.get("username") or recorded_login.get("email") or ""
        origins = _staging(pack)["origins"]
        recorded = record.get("up")
        if isinstance(recorded, dict):
            up = {str(name): bool(recorded.get(name)) for name in origins}
        else:
            from cockpitlib.acts import origins_up

            up = origins_up(origins)
        secret = ""
        if account:
            from cockpitlib.vault import human_secret

            for candidate in _login_origins(
                origins, pack
            ):  # the app first, then the others: a portal account logs in on the portal
                secret = human_secret(candidate, account, pack)
                if secret:
                    break
        slot = record.get("slot") or (1 if path and os.path.isfile(path) else None)
        if not secret and recorded_login.get("password"):
            secret = str(recorded_login["password"])
        if not secret:
            from cockpitlib.slots import read_slot_secret

            stored = read_slot_secret(slot or 1)  # the login the pack's login command set on the slot's own data copy
            if stored.get("password"):
                account = (
                    account or stored.get("username") or ""
                )  # the record's account stays the login; the slot file names it only when the record does not
                secret = stored.get("password") or ""
        login = None
        if account and secret:
            login = {"username": account, "email": account, "password": secret}
        if os.environ.get("COCKPIT_LANE") and isinstance(login, dict):
            login = {key: value for key, value in login.items() if key != "password"}
        slot_env = next((item["name"] for item in pack.get("environments") or [] if item.get("slot")), "")
        from cockpitlib.slots import slot_apps

        own = slot_apps(pack, int(record["slot"]), ticket) if record.get("slot") else []
        if own:  # a slot demo: the slot's own addresses, not the staging origins
            from cockpitlib.acts import origins_up

            origins = {row["name"]: row["url"] for row in own}
            up = origins_up(origins)
            apps = [
                {
                    **item,
                    **(
                        {"repo": row["repo"], "worktree": os.path.isdir(worktree_of(ticket, row["repo"]))}
                        if row["repo"]
                        else {}
                    ),
                }
                for item, row in zip(_page_apps(origins, up), own)
            ]
        else:
            apps = _page_apps(origins, up)
        return {
            "env": record.get("env") or (slot_env if record.get("slot") and slot_env else "staging"),
            "ticket": ticket,
            "account": account,
            "slot": slot,
            "links": _page_links(record.get("links")),
            "steps": record.get("steps") or [],
            "login": login,
            "origins": origins,
            "up": up,
            "apps": apps,
        }

    @router.post("/demo")
    def demo_write(body: dict):
        """The lane writes the demo record. A secret is stored on the slot, not in the file."""
        pack = _guard()
        ticket = str((body or {}).get("ticket") or "").strip()
        if not ticket:
            raise HTTPException(400, "missing ticket")
        ticket = _ticket(pack, ticket)
        from cockpitlib.acts import save_demo

        slot = body.get("slot") or 1
        clean = _act(lambda: save_demo(ticket, body, int(slot)))
        return {"ok": True, "ticket": ticket, "record": clean}

    @router.post("/created")
    def created_data(body: dict):
        """Name created test data and link it on the pack's public origin."""
        pack = _guard()
        ticket = str((body or {}).get("ticket") or "").strip()
        if not ticket:
            raise HTTPException(400, "missing ticket")
        ticket = _ticket(pack, ticket)
        from cockpitlib.acts import keep_created

        saved = _act(lambda: keep_created(ticket, (body or {}).get("name") or "", body.get("body"), pack))
        return {"ok": True, "ticket": ticket, "name": saved["name"], "link": saved["link"]}

    @router.post("/scripted")
    def scripted_write(body: dict):
        """A scripted write runs only when the accepted plan lists that one line."""
        pack = _guard()
        ticket = str((body or {}).get("ticket") or "").strip()
        if not ticket:
            raise HTTPException(400, "missing ticket")
        ticket = _ticket(pack, ticket)
        from cockpitlib.acts import run_listed

        line = _act(lambda: run_listed(ticket, (body or {}).get("request") or "", pack))
        return {"ok": True, "ticket": ticket, "request": line}

    @router.post("/demo-login")
    def demo_login(body: dict):
        pack = _guard()
        from cockpitlib.slots import provider_for, write_slot_secret

        ticket = _ticket(pack, body.get("ticket"), blank=True)
        user = body.get("user") or ""
        login = provider_for(pack.get("slot_provider"), pack).login(ticket, user)
        slot = int(body.get("slot") or 1)
        from cockpitlib.vault import human_secret
        from cockpitlib.vault_key import human_present

        secret = ""
        for candidate in _login_origins(_staging(pack).get("origins") or {}, pack) if user else []:
            with human_present():  # the human pressed New password
                secret = human_secret(candidate, user)
            if secret:
                break
        password = secret or login.get("password") or ""
        if not password:  # never store an empty password for the slot: the login command's answer had none
            raise HTTPException(409, "the pack's login command returned no password: nothing was set")
        write_slot_secret(
            slot,
            {
                "email": login.get("user") or user,
                "username": login.get("user") or user,
                "password": password,
            },
        )
        return {"ok": True, "user": login.get("user") or user, "slot": slot, "out": "set on the slot"}

    @router.get("/session-card")
    def session_card(ticket: str = ""):
        """While the human's manual session on this ticket is open: the slot's app addresses and the logins to pick from, with the
        one the slot holds now. Closed (or no card in the pack): {open: false}."""
        pack = _guard()
        ticket = _ticket(pack, ticket, blank=True)
        from cockpitlib.slots import read_owner, read_slot_secret, read_ticket

        spec = (pack.get("slots") or {}).get("session_card") or {}
        count = max(1, int((pack.get("seats") or {}).get("slots") or 1))
        slot = next(
            (
                number
                for number in range(1, count + 1)
                if ticket and read_ticket(number) == ticket and read_owner(number) == "human"
            ),
            0,
        )
        if not slot or not spec:
            return {"open": False, "ticket": ticket}
        from cockpitlib.slots import slot_apps

        logins = [{"label": row["label"], "user": row["user"]} for row in spec.get("logins") or []]
        stored = read_slot_secret(slot)
        current = (
            {"username": stored.get("username") or stored.get("email") or "", "password": stored.get("password") or ""}
            if stored.get("password")
            else None
        )
        if current and os.environ.get("COCKPIT_LANE"):
            current.pop("password")
        return {
            "open": True,
            "ticket": ticket,
            "slot": slot,
            "apps": [{"name": row["name"], "url": row["url"]} for row in slot_apps(pack, slot, ticket)],
            "logins": logins,
            "default": spec.get("default") or (logins[0]["label"] if logins else ""),
            "current": current,
        }

    @router.post("/session-login")
    def session_login(body: dict):
        """A password for the picked user on the session's slot copy, through the pack's login command; kept as the slot's login."""
        pack = _guard()
        from cockpitlib.slots import provider_for, write_slot_secret

        ticket = str(body.get("ticket") or "")
        user = str(body.get("user") or "")
        if not ticket or not user:
            raise HTTPException(400, "ticket and user")
        ticket = _ticket(pack, ticket)
        slot = int(body.get("slot") or 1)
        login = _act(lambda: provider_for(pack.get("slot_provider"), pack).login(ticket, user))
        if not login.get("password"):
            raise HTTPException(409, "the pack's login command returned no password: nothing was set")
        name = login.get("user") or user
        write_slot_secret(slot, {"email": name, "username": name, "password": login["password"]})
        return {"ok": True, "slot": slot, "user": name, "password": login["password"]}

    @router.post("/demo-start")
    def demo_start(body: dict):
        pack = _guard()
        from cockpitlib.acts import resolve_slot
        from cockpitlib.slots import provider_for

        provider = provider_for(pack.get("slot_provider"), pack)
        ticket, repo = _ticket(pack, body.get("ticket"), blank=True), _repo(body.get("repo"))
        number = _act(lambda: resolve_slot(pack, body.get("slot") or "auto"))
        words = (pack.get("slots") or {}).get("start_repo")
        if words and body.get("repo"):  # the pack starts the one app the card names, not the slot's whole stack
            from cockpitlib.slots import CommandProvider

            ran = _act(lambda: CommandProvider(pack).run("start-repo", number, ticket, words=words, repo=repo))
            if ran["state"] not in ("ok", "working"):
                raise HTTPException(409, f"start {ran['state']}: {ran['tail']}".strip(": "))
            return {"ok": True, "repo": body.get("repo"), "out": "started", "slot": number, "runtime": ran["out"]}
        started = _act(lambda: provider.up(number, ticket))
        return {"ok": True, "repo": body.get("repo"), "out": "started", "slot": number, "runtime": started}

    @router.get("/usage")
    def usage(period: str = "week", by: str = "who", scope: str = "hermes"):
        """Tokens and cost of every seat session and the coding tool's transcripts: the period totals, the period's
        groups by lane / ticket / day / model, the recent sessions, the plan windows and the budget."""
        pack = _guard()
        from cockpitlib.settings import budget_state, load
        from cockpitlib.usage import report

        try:
            gathered = report(pack, period, by, scope)
        except CockpitError as exc:
            raise HTTPException(400, str(exc)) from exc
        budget = {**load(pack)["budget"], **budget_state(pack)}
        return {**gathered, "windows": budget["windows"], "budget": budget}

    @router.get("/pace")
    def plan_pace(days: str = "", start: str = "", end: str = "", peak: str = "", fresh: str = ""):
        """The Usage page's Pace panel (insight only): `cockpit pace --json` plus its inputs and one sentence per
        window. `fresh=1` is Recalculate: it skips the five-minute cache of the plan windows."""
        pack = _guard()
        from cockpitlib.pace import pace, parse_schedule

        try:
            parse_schedule(days, start, end)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        on = lambda value: str(value).lower() in ("1", "true", "yes", "on")  # noqa: E731
        return pace(pack, days=days, start=start, end=end, peak=on(peak), fresh=on(fresh), detail=True)

    @router.post("/chat-open")
    def chat_open(body: dict):
        _guard()
        from cockpitlib.chat import open_chat

        ticket = _chat(body.get("ticket"))
        opened = open_chat(
            ticket,
            int(body.get("cols") or 120),
            int(body.get("rows") or 36),
            bool(body.get("reset")),
            str(body.get("from") or ""),
            str(body.get("card") or ""),
        )
        opened["ok"] = True
        return opened

    @router.get("/chat-read")
    def chat_read(ticket: str = "own", offset: int = 0):
        _guard()
        from cockpitlib.chat import read_chat

        return read_chat(_chat(ticket), offset)

    @router.post("/chat-write")
    def chat_write(body: dict):
        _guard()
        import base64

        from cockpitlib.chat import write_chat
        from cockpitlib.errors import CockpitError

        ticket = _chat(body.get("ticket"))
        if body.get("text") is not None:
            payload = str(body.get("text")).encode()
        else:
            payload = base64.b64decode(body.get("data") or "")
        try:
            write_chat(ticket, payload)
        except CockpitError as exc:
            raise HTTPException(409, str(exc)) from exc
        return {"ok": True}

    @router.post("/chat-resize")
    def chat_resize(body: dict):
        _guard()
        from cockpitlib.chat import resize_chat

        resize_chat(_chat(body.get("ticket")), int(body.get("cols") or 120), int(body.get("rows") or 36))
        return {"ok": True}

    @router.post("/chat-end")
    def chat_end(body: dict):
        _guard()
        from cockpitlib.chat import end_chat

        end_chat(_chat(body.get("ticket")))
        return {"ok": True}

    @router.get("/chat-state")
    def chat_state(ticket: str = "own", card: str = ""):
        _guard()
        from cockpitlib.chat import chat_state as state

        return state(_chat(ticket), card)

    @router.get("/coding-sessions")
    def coding_sessions(scope: str = "pipeline"):
        _guard()
        from cockpitlib.chat import coding_sessions as listed

        return {"sessions": listed(scope), "scope": scope}

    @router.get("/coding-tail")
    def coding_tail(path: str = "", offset: int = 0):
        _guard()
        from cockpitlib.chat import coding_tail as tail

        return tail(path, offset)

    @router.get("/lane-runs")
    def lane_runs():
        pack = _guard()
        import sqlite3
        import time

        from cockpitlib.kanban import db_path

        path = db_path(pack["board"])
        logs = os.path.join(os.path.dirname(path), "logs")
        cards = {}
        if os.path.isfile(path):
            connection = read_db(path)
            try:
                rows = connection.execute("select id, title, status, assignee from tasks").fetchall()
            except sqlite3.Error:
                rows = []
            finally:
                connection.close()
            cards = {row[0]: {"title": row[1] or "", "status": row[2] or "", "assignee": row[3] or ""} for row in rows}
        out = []
        names = os.listdir(logs) if os.path.isdir(logs) else []
        for name in names:
            if not name.endswith(".log"):
                continue
            logfile = os.path.join(logs, name)
            try:
                st = os.stat(logfile)
            except OSError:
                continue
            card_id = name[:-4]
            card = cards.get(card_id, {})
            out.append(
                {
                    "path": logfile,
                    "card": card_id,
                    "title": card.get("title", ""),
                    "status": card.get("status", ""),
                    "assignee": card.get("assignee", ""),
                    "mtime": st.st_mtime,
                    "size": st.st_size,
                    "running": card.get("status") in ("in_progress", "running", "claimed"),
                }
            )
        if not out:
            now = time.time()
            for card_id, card in cards.items():
                out.append(
                    {
                        "path": "",
                        "card": card_id,
                        "title": card.get("title", ""),
                        "status": card.get("status", ""),
                        "assignee": card.get("assignee", ""),
                        "mtime": now,
                        "size": 0,
                        "running": card.get("status") in ("in_progress", "running", "claimed"),
                    }
                )
        out.sort(key=lambda row: (-int(row["running"]), -row["mtime"]))
        from cockpitlib.chat import lane_transcript

        return {"runs": [{**row, "transcript": lane_transcript(row["card"])} for row in out[:40]]}

    @router.get("/lane-tail")
    def lane_tail(path: str = "", offset: int = -1):
        pack = _guard()
        from cockpitlib.lane_feed import lane_tail as tail

        return _act(lambda: tail(pack, path, offset))

    @router.get("/jobs")
    def jobs():
        pack = _guard()
        from cockpitlib.lane_feed import jobs as listed

        return {"jobs": listed(pack)}

    @router.get("/job-stream")
    def job_stream(ticket: str = "", since: str = ""):
        pack = _guard()
        from cockpitlib.lane_feed import job_stream as stream

        return stream(pack, _ticket(pack, ticket, blank=True, also=("all",)), since)

    @router.get("/lane-stream")
    def lane_stream(card: str = "", since: str = ""):
        pack = _guard()
        from cockpitlib.lane_feed import lane_stream as stream

        return stream(pack, card, since)
