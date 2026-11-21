# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Routes the page calls. Without a pack, mutating routes say to migrate."""

import os
import re

from fastapi import APIRouter, Depends, HTTPException
from fastapi.requests import (
    HTTPConnection,
)  # fastapi's own name for it: the project declares fastapi, not what it is built on

from cockpitlib.errors import NeedMigrate
from cockpitlib.paths import pack_path

LOOPBACK_HOSTS = ("localhost", "127.0.0.1", "::1")
OFF = ("", "0", "false", "no", "off")


def allowed_origins(listed: str) -> tuple:
    """The origins COCKPIT_ALLOWED_ORIGINS names (comma-separated, e.g. a configured public URL), without a closing slash."""
    return tuple(item.strip().rstrip("/") for item in str(listed or "").split(",") if item.strip().rstrip("/"))


def origin_refusal(origin: str, host: str, allowed=()) -> str:
    """Why a request with that Origin header is another site's, or "": no Origin at all (the Desktop, a same-origin
    read, a command line), a loopback origin on any port, the very address the request was sent to (this server's own
    page behind a forward) and a listed origin are this installation's own."""
    from urllib.parse import urlsplit

    text = str(origin or "").strip()
    if not text:
        return ""
    try:
        parsed = urlsplit(text)
        name, netloc = (parsed.hostname or "").lower(), parsed.netloc.lower()
        parsed.port  # noqa: B018 - a port that is no number is no origin
    except ValueError:
        name, netloc, parsed = "", "", None
    if parsed is not None and parsed.scheme in ("http", "https") and name:
        if name in LOOPBACK_HOSTS or netloc == str(host or "").strip().lower():
            return ""
        if f"{parsed.scheme}://{netloc}" in [item.lower() for item in allowed]:
            return ""
    return f"a request from another site's origin ({text[:120]}) is refused: list it in COCKPIT_ALLOWED_ORIGINS if it is this dashboard's own address"


def _own_origin(connection: HTTPConnection) -> None:
    """Defence in depth under the host's own protection (its loopback bind, session token and host check), and off
    unless COCKPIT_ORIGIN_CHECK is set: a request whose Origin is another site's is answered 403."""
    if os.environ.get("COCKPIT_ORIGIN_CHECK", "").strip().lower() in OFF:
        return
    why = origin_refusal(
        connection.headers.get("origin", ""),
        connection.headers.get("host", ""),
        allowed_origins(os.environ.get("COCKPIT_ALLOWED_ORIGINS", "")),
    )
    if why:
        raise HTTPException(403, why)


router = APIRouter(dependencies=[Depends(_own_origin)])


def code_stamp() -> float:
    """The newest change to cockpit's Python on disk (kernel, dashboard, hooks)."""
    from cockpitlib.paths import PLUGIN_ROOT

    newest = 0.0
    for folder in ("kernel/cockpitlib", "dashboard/cockpit", "hooks"):
        root = os.path.join(PLUGIN_ROOT, folder)
        for name in os.listdir(root) if os.path.isdir(root) else []:
            if name.endswith(".py"):
                try:
                    newest = max(newest, os.path.getmtime(os.path.join(root, name)))
                except OSError:
                    continue
    return newest


# What this dashboard process loaded. A newer file on disk is not swapped in while it runs: an old and a new copy of
# one module would disagree on their own classes. The Inbox asks for a restart instead.
LOADED = code_stamp()


def code_row() -> dict:
    """An Inbox row while cockpit's code on disk is newer than this dashboard's; else an empty dict."""
    if code_stamp() <= LOADED:
        return {}
    restart = restart_command()
    served = "the gateway serves these pages and" if served_by_gateway() else "this dashboard"
    text = (
        f"cockpit's code changed on disk since these pages started: {served} still runs the code loaded before. "
        f"Restart it when no lane is running ({restart})"
    )
    # not a watcher: there is nothing to Run now, only the restart that loads the new code
    return {
        "name": "gateway" if served_by_gateway() else "dashboard",
        "ok": False,
        "reason": text,
        "summary": text,
        "fails": 0,
        "last_ok": None,
        "last_error": None,
        "error": "",
        "restart": restart,
    }


def served_by_gateway() -> bool:
    """Whether the process answering is Hermes's gateway: its state file names this very process."""
    import json

    from cockpitlib.paths import hermes_home

    try:
        with open(os.path.join(hermes_home(), "gateway_state.json"), encoding="utf-8") as handle:
            state = json.load(handle)
    except (OSError, ValueError):
        return False
    return isinstance(state, dict) and state.get("pid") == os.getpid()


def restart_command() -> str:
    """How what serves these pages is restarted: Hermes's systemd service, the gateway itself, or a dashboard started
    by hand."""
    try:
        cgroup = open("/proc/self/cgroup", encoding="utf-8").read()
    except OSError:
        cgroup = ""
    if "hermes-gateway.service" in cgroup:
        # not `hermes gateway restart`: it counts the gateway's own worker pool as a live session and refuses
        return "systemctl --user restart hermes-gateway.service"
    if served_by_gateway():
        return "hermes gateway restart"
    return "hermes dashboard --stop, then hermes dashboard"


def _pack():
    path = pack_path()
    if not os.path.isfile(path):
        raise NeedMigrate()
    from cockpitlib.pack import load

    return load(path)


_PR_URL = re.compile(r"/pull/(\d+)(?:[/?#]|$)")
_PR_FIELDS = (
    "repo",
    "number",
    "url",
    "state",
    "merged",
    "head",
    "head_sha",
    "title",
    "role",
    "base",
    "author",
    "approvals",
    "my_review_state",
    "since_review",
    "my_threads",
    "re_requested",
    "last_activity",
    "rereview",
    "rereview_ready",
)


def _pr_number(item, pr: dict):
    """The PR an intent is about: its payload's number, the number its receipt's URL names (an open-pr learns it when
    it publishes), or the one it carried when written."""
    payload = item.get("payload") or {}
    if payload.get("number"):
        return payload["number"]
    receipt = item.get("receipt") if isinstance(item.get("receipt"), dict) else {}
    match = _PR_URL.search(str(receipt.get("url") or ""))
    if match:
        return int(match.group(1))
    return pr.get("number")


def _with_new_comments(item, inbox=None, seen=None):
    """The list row carries the PR as the watch knows it now (state, merged, approvals: the Inbox's merge and comment
    rows read these), and the new comments the inbox rows hold for it. The PR state an intent carried when it was
    written is the fallback, without its old comment count: a comment is new only while the watch says so. A list
    passes the inbox rows it read once; they are a walk of every ticket's PR records."""
    payload = item.get("payload") or {}
    stored = dict(item.get("pr") or {})
    repo = str(payload.get("repo") or stored.get("repo") or "")
    number = _pr_number(item, stored)
    if not repo or not number:
        return stored or None
    from cockpitlib.outbox import _pr_state
    from cockpitlib.pr_watch import inbox_rows, normal

    ticket = str(item.get("ticket") or "")
    # a ticket's intents name the same PR again and again: a list keeps what it read of one in `seen`, since reading
    # and rendering the record for each intent was most of what a list of long-settled intents still cost
    key = (ticket, repo, str(number))
    if seen is not None and key in seen:
        known = seen[key]
    else:
        current = _pr_state(ticket, repo, number)
        known = {name: value for name, value in normal(current).items() if name in _PR_FIELDS} if current else None
        if seen is not None:
            seen[key] = known
    pr = dict(known) if known is not None else stored
    pr["repo"] = repo
    pr["number"] = number
    pr["new"] = []
    pr["new_count"] = 0
    if pr.get("merged"):
        return pr  # a merged PR's comments are the record's, not Inbox rows: the ticket's done row is what is left to act on
    for row in inbox_rows() if inbox is None else inbox:
        if str(row.get("repo") or "") != repo or str(row.get("number")) != str(number):
            continue
        if row.get("ticket") and row.get("ticket") != ticket:
            continue
        comments = row.get("new") or []
        pr["new_count"] = len(comments)
        pr["new"] = [comment for comment in comments if isinstance(comment, dict)]
        break
    return pr


def _guard():
    try:
        return _pack()
    except NeedMigrate as exc:
        raise HTTPException(409, str(exc)) from exc


_CHAIN_SHOWN = {"endorsed", "posted", "published", "published-manually"}


def _with_chain(rows) -> list:
    """Publish order, and a hidden first step until the following intent is endorsed."""
    from cockpitlib.intents import ORDER

    by_id = {row.get("id"): row for row in rows}
    follower = {}
    for row in rows:
        parent = (row.get("payload") or {}).get("after") or ""
        if parent and parent not in follower:
            follower[parent] = row
    for row in rows:
        row["order"] = ORDER.get(row.get("type"), 99)
        chain = {}
        child = follower.get(row.get("id"))
        if child and child.get("status") not in _CHAIN_SHOWN:
            chain["followed_by"] = child.get("id") or ""
        elif child and child.get("status") == "endorsed":
            chain["pair"] = (
                child.get("id") or ""
            )  # endorsed too: its Publish sends both, so the Inbox makes one row of the pair
        parent_id = (row.get("payload") or {}).get("after") or ""
        if parent_id:
            chain["role"] = "content"
            chain["step1_status"] = (by_id.get(parent_id) or {}).get("status") or ""
        if chain:
            row["chain"] = chain
    return rows


def _files(payload) -> dict:
    """The intent's drafts and attachments, by field, as paths the page opens."""
    from cockpitlib.intents import FIELDS
    from cockpitlib.paths import workspace

    found = {}
    for field, shape in FIELDS.items():
        if shape == "file" and payload.get(field):
            found[field] = os.path.join(workspace(), payload[field])
        if shape == "files":
            for index, item in enumerate(payload.get(field) or []):
                found[f"{field}_{index}"] = os.path.join(workspace(), item)
    return found


def _skills(pack, item, cards=None) -> dict:
    """What the intent's type requires of the lane that wrote it, and whether it loaded it."""
    from cockpitlib.skill_log import loaded, missing

    required = ((pack.get("skills") or {}).get("intent") or {}).get(item.get("type")) or []
    names = [" or ".join(entry) if isinstance(entry, list) else entry for entry in required]
    gaps = missing(pack, item, cards)
    return {
        "required": names,
        "loaded": loaded(item.get("ticket") or "", item.get("created_by") or ""),
        "missing": gaps,
        "ok": not gaps,
    }


def _rendered(record, keys) -> dict:
    """The markdown a lane or the gatekeeper wrote in these fields, rendered for the page; the raw fields stay beside it.
    Empty when the record has none of them."""
    from cockpitlib.render import markdown

    found = {
        key: markdown(str(record[key]))
        for key in keys
        if isinstance(record, dict) and str(record.get(key) or "").strip()
    }
    return found


def _awaiting_push(items) -> dict:
    """(ticket, repo, sha) of the ticket's own pushes -> the PR head the watch may still show for it: any head ("") while
    the push has not gone out, and the head the push replaced (its lease) once it is published, until the watch reads
    the PR again."""
    from cockpitlib.intents import OPEN_STATUSES, PUBLISHED

    found = {}
    for item in items:
        payload = item.get("payload") or {}
        if item.get("type") != "push-branch" or not payload.get("sha"):
            continue
        key = (item.get("ticket"), payload.get("repo"), payload["sha"])
        if item.get("status") in OPEN_STATUSES:
            found[key] = ""
        elif item.get("status") in PUBLISHED and payload.get("remote_sha"):
            found.setdefault(key, str(payload["remote_sha"]))
    return found


def _stale_head(item, awaiting=None) -> dict:
    """A review whose PR head moved after it was written: publishing would mis-anchor its lines. A review of a commit
    that one of the ticket's own pushes sends is not that: the head has not moved, it has not got there yet (a bump
    batch reviews the rebased commit before its push stage is out), or the push is out and the watch's record still
    shows the head it replaced. Any other head is a move."""
    from cockpitlib.outbox import _pr_state

    payload = item.get("payload") or {}
    if item.get("type") != "pr-review-submit" or item.get("status") not in ("pending", "endorsed", "held", "returned"):
        return None
    head = _pr_state(item.get("ticket"), payload.get("repo"), payload.get("number")).get("head_sha") or ""
    sha = payload.get("sha") or ""
    if not head or not sha or head.startswith(sha) or sha.startswith(head):
        return None
    before = (awaiting or {}).get((item.get("ticket"), payload.get("repo"), sha))
    if before is not None and (before == "" or head.startswith(before) or before.startswith(head)):
        return None
    return {"reviewed": sha[:9], "now": head[:9]}


def _rows(pack) -> list:
    """Every intent with the fields the Outbox and Inbox read (tests/contract/outbox-list-fields.json)."""
    from cockpitlib.ci_watch import state_for
    from cockpitlib.gate import numbers
    from cockpitlib.intents import all_intents
    from cockpitlib.pr_watch import inbox_rows, prs_of
    from cockpitlib.sequence import waits

    rows = []
    counts = {}
    numbered = numbers()
    inbox = inbox_rows()
    items = all_intents()
    awaiting = _awaiting_push(items)
    # the board is read once for the whole list: read per intent, a long list takes longer than the Desktop waits for
    # an answer
    from cockpitlib.board_view import stale_days
    from cockpitlib.kanban import board_cards

    cards = {card["id"]: card for card in board_cards(str(pack["board"]))}
    stopped = {}  # ticket -> the human halted it: its standing rows (a review in progress) leave the Inbox with it

    def halted_ticket(ticket: str) -> bool:
        if ticket not in stopped:
            from cockpitlib.halt import halted

            stopped[ticket] = halted(ticket) is not None if ticket else False
        return stopped[ticket]

    by_ticket = {}  # a ticket's PRs are read and rendered once, not once per intent of the ticket
    pr_records = {}  # and so is the record of the PR an intent names (_with_new_comments)

    def prs(ticket: str) -> list:
        if ticket not in by_ticket:
            by_ticket[ticket] = prs_of(ticket)
        return by_ticket[ticket]

    for item in items:
        status = item.get("status") or "pending"
        counts[status] = counts.get(status, 0) + 1
        payload = item.get("payload") or {}
        rows.append(
            {
                "id": item.get("id"),
                "ticket": item.get("ticket"),
                "type": item.get("type"),
                "status": status,
                "summary": item.get("agent_summary") or "",
                "risk": (item.get("endorsement") or {}).get("risk") or item.get("risk_hint") or "",
                "target": payload.get("repo") or payload.get("issue") or "",
                "payload": payload,
                "path": item.get("id"),
                "created_at": item.get("created_at"),
                "created_by": item.get("created_by"),
                "digest_no": numbered.get(item.get("id")) or 0,
                "endorsed": item.get("endorsement"),
                "ci": state_for(item.get("ticket") or "", payload.get("repo") or "", payload.get("sha") or "", pack)
                or item.get("ci"),
                "pr": _with_new_comments(item, inbox, pr_records),
                "prs": prs(item.get("ticket") or ""),
                "halted": halted_ticket(item.get("ticket") or ""),
                "card_id": item.get("card_id") or "",
                "hold": item.get("hold"),
                "hold_html": _rendered(item.get("hold"), ("ask", "reason", "rework")),
                "endorsed_html": _rendered(item.get("endorsement"), ("notes",)),
                "receipt": item.get("receipt"),
                "review": item.get("review"),
                "returned": item.get("returned"),
                "returned_html": _rendered(item.get("returned"), ("instruction",)),
                "human": item.get("human"),
                "history": item.get("history") or [],
                "evidence": item.get("evidence") or [],
                "files": _files(payload),
                "skills": _skills(pack, item, cards),
                "stale_head": _stale_head(item, awaiting),
                "waits": waits(item, pack),
                "stale_days": stale_days(item),
            }
        )
    rows = _with_chain(rows)
    for row in rows:
        row["_count"] = counts
    return rows


@router.get("/list")
def list_intents():
    """Every intent with the fields the Outbox and Inbox read (tests/contract/outbox-list-fields.json)."""
    pack = _guard()
    rows = _rows(pack)
    counts = rows[0].pop("_count") if rows else {}
    for row in rows:
        row.pop("_count", None)
    return {"name": pack["name"], "intents": [row["id"] for row in rows], "counts": counts, "rows": rows}


@router.get("/intent")
def intent(id: str):
    """One intent as its pane reads it: the list row, what leaves (rendered), its receipt log lines and its Brief."""
    pack = _guard()
    from cockpitlib.intent_view import enrich

    row = next((item for item in _rows(pack) if item.get("id") == id), None)
    if row is None:
        raise HTTPException(404, f"{id} not in the outbox")
    row.pop("_count", None)
    return enrich(row, pack)


@router.post("/ci-override")
def ci_override_route(body: dict):
    """The human approves despite CI, with a reason (the pack's outbox.ci_override)."""
    pack = _guard()
    from cockpitlib.errors import CockpitError
    from cockpitlib.outbox import ci_override

    try:
        intent = ci_override(pack, body.get("id") or "", body.get("reason") or "")
    except CockpitError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"ok": True, "id": intent["id"], "ci_override": intent["ci_override"]}


@router.post("/publish")
def publish(body: dict):
    """Publish one intent as the human. On a posted review this is stage 2: the verdict and summary the human gives."""
    pack = _guard()
    if body.get("confirm") != body.get("id"):
        raise HTTPException(400, "confirm must echo the id")
    from cockpitlib.errors import CockpitError
    from cockpitlib.intents import load, save
    from cockpitlib.publish import execute, forge_for, submit_review

    row = load(body["id"])
    if str(row.get("status") or "").startswith(
        "published"
    ):  # already out (a later stage published it first): nothing to do
        return {
            "pack": pack["name"],
            "receipt": {**(row.get("receipt") or {}), "ok": True, "already": True},
            "out": f"{row['id']} already published",
        }
    dry = bool(body.get("dry_run"))
    try:
        if row.get("type") == "pr-review-submit" and row.get("status") == "posted":
            receipt = submit_review(
                row,
                forge_for(pack, dry),
                event=body.get("event"),
                body=body.get("summary") if "summary" in body else None,
                explicit=bool(body.get("event")),
                pack=pack,
                dry_run=dry,
            )
        else:
            # `approve`: the human pressed Publish on this one review and its confirmation named the proposed APPROVE,
            # as naming its number does in a digest reply. Without it an APPROVE a lane proposed is refused, and the
            # Desktop had no way to send one at all ("APPROVE must be named by the human", every bump approval).
            forge = forge_for(pack, dry)
            receipt = execute(row, forge, dry_run=dry, pack=pack, explicit_approve=bool(body.get("approve")))
            if not dry and receipt.get("ok"):
                from cockpitlib.publish import link_siblings

                save(row)  # first, so the fill reads this PR as out
                link_siblings(forge, row, receipt)  # the ticket's PRs name each other once the second one is open
    except CockpitError as exc:
        raise HTTPException(400, str(exc)) from exc
    if not dry:
        save(row)
    if not receipt.get("ok") and not receipt.get("dry_run"):
        raise HTTPException(400, str(receipt.get("error") or "refused"))
    done = "dry run" if receipt.get("dry_run") else "published"
    return {"pack": pack["name"], "receipt": receipt, "out": f"{row.get('id') or ''} {done}".strip()}


def held_slots(count: int) -> list:
    """'slot N is TICKET's' for each lane slot a ticket holds."""
    from cockpitlib.slots import read_owner, read_ticket

    return [
        f"slot {slot} is {read_ticket(slot)}'s"
        for slot in range(1, count + 1)
        if read_owner(slot) not in ("free", "", "human") and read_ticket(slot)
    ]


@router.get("/capacity")
def capacity():
    pack = _guard()
    from cockpitlib.capacity import caps_for
    from cockpitlib.kanban import open_cards
    from cockpitlib.settings import load as load_settings
    from cockpitlib.slots import free_slots

    seats = load_settings(pack)["seats"]
    caps = caps_for(pack, seats, len(free_slots(seats["slots"])), open_cards(pack["board"]))
    held = held_slots(seats["slots"]) if caps["dev"] <= 0 else []
    spec = (
        ("dev", "Dev", caps["dev"], max(seats["intake"], 1)),
        ("test", "Test", caps["test"], max(seats["slots"], seats["intake"])),
        ("review", "Review", caps["review"], seats["reviewer"]),
        ("bump", "Bump", caps["review"], seats["reviewer"]),
        ("question", "Question", caps["question"], seats["analyst"]),
    )
    flows = []
    for key, label, free, total in spec:
        # the colour follows the free count: none is red, the last of several is amber, a seat all free is green
        tone = "ok"
        if free <= 0:
            tone = "danger"
        if free == 1 and total > 1:
            tone = "warn"
        why = f"{label} {free} of {total}"
        if key == "test" and caps["test_why"]:
            why = caps["test_why"]
        if key == "dev" and held:
            # 0 for a new ticket, not for these: a ticket's own idle slot still seats its next card (kickoff.own_idle_slot)
            why = f"{why} · {', '.join(held)} — only {'its' if len(held) == 1 else 'their'} own cards can start"
        flows.append(
            {
                "key": key,
                "label": label,
                "free": free,
                "of": total,
                "tone": tone,
                "why": why,
                **({"local": caps["test_local"]} if key == "test" else {}),
            }
        )
    caps["flows"] = flows
    caps["time"] = "now"
    from cockpitlib.environments import environments

    caps["environments"] = [{"name": item["name"], "slot": item["slot"]} for item in environments(pack)]
    return caps


@router.get("/desktop-overrides")
def desktop_overrides():
    """The Desktop fixes the pack opts into (pack.yaml desktop.overrides); the desktop half applies them."""
    pack = _guard()
    return {"overrides": ((pack.get("desktop") or {}).get("overrides")) or []}


@router.get("/settings")
def settings():
    pack = _guard()
    from cockpitlib.settings import load

    data = load(pack)
    from cockpitlib.paths import watch_dir, workspace

    data["path"] = os.path.relpath(os.path.join(watch_dir(), "settings.json"), workspace())
    data["display_name"] = pack["providers"]["coding"].get("display_name") or "Chat"
    from cockpitlib.settings import budget_state

    data["settings"] = {
        "seats": data["seats"],
        "budget": dict(data["budget"]),
        "shared_chrome_hours": data["shared_chrome_hours"],
        "worktree_gc": dict(data["worktree_gc"]),
    }
    data["limits"] = {"slots": [0, 8], "intake": [1, 8], "reviewer": [1, 8], "analyst": [1, 8]}
    from cockpitlib.cleanup import DAYS_RANGE, last_pass

    data["limits"]["worktree_gc_days"] = list(DAYS_RANGE)
    data["worktree_gc"] = {**data["worktree_gc"], "last": last_pass()}
    from cockpitlib.settings import missing_lanes

    data["missing_lanes"] = missing_lanes(pack)
    data["apply"] = {"running": False}
    data["budget"] = {**data["budget"], **budget_state(pack)}
    return data


@router.post("/kickoff")
def kickoff(body: dict):
    pack = _guard()
    from cockpitlib.errors import CockpitError
    from cockpitlib.kickoff import start
    from cockpitlib.settings import load as load_settings
    from dashboard.cockpit.routes.pages import _ticket

    ticket = _ticket(pack, body.get("ticket"), blank=True)
    try:
        made = start(
            pack,
            body.get("mode") or "intake",
            ticket=ticket,
            prompt=body.get("prompt") or "",
            repos=body.get("repos") or [],
            repo=body.get("repo") or "",
            prs=body.get("prs") or [],
            chrome=bool(body.get("chrome")),
            seats=load_settings(pack)["seats"],
            environment=body.get("env") or "",
            evidence=body.get("evidence") or [],
        )
        if isinstance(made, dict) and not made.get("out"):  # the toast says what started
            made["out"] = (
                f"{made.get('card_id') or ''} {made.get('title') or ''} for {made.get('lane') or 'a lane'}".strip()
            )
        if body.get("from_answer"):  # kicked off from an answer row: the row records it and leaves
            from cockpitlib.answers import use

            use(str(body["from_answer"]), body.get("mode") or "intake", (made or {}).get("card_id") or "")
        return made
    except CockpitError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.get("/kickoff-modes")
def kickoff_modes_route():
    """The modes Kick off offers: cockpit's own and the ones plugins beside it registered, with the lane each uses."""
    pack = _guard()
    from cockpitlib.registry import kickoff_modes

    return {
        "modes": [
            {
                "mode": name,
                "label": entry["label"],
                "text": entry["text"],
                "lane_kind": entry["lane_kind"],
                "owner": entry["owner"],
            }
            for name, entry in kickoff_modes(pack).items()
        ]
    }


@router.get("/plugin-pages")
def plugin_pages_route():
    """The pages of the plugins beside cockpit, for the link that crosses to them. Empty when there are none."""
    pack = _guard()
    from cockpitlib.registry import plugin_pages

    return {"pages": plugin_pages(pack)}


@router.get("/helpers")
def helpers_route(group: str = ""):
    """The pack's helpers with their status rows and last runs, and the choices of each helper that takes one."""
    pack = _guard()
    from cockpitlib.errors import CockpitError
    from cockpitlib.helpers import options, status

    try:
        found = status(pack, group)
    except CockpitError as exc:
        raise HTTPException(404, str(exc)) from exc
    for entry in found["helpers"]:
        entry["options"] = options(pack, entry["name"]) if entry["takes_choice"] else []
    return found


@router.post("/helper")
def helper_route(body: dict):
    """Start a helper's verb in the background. A helper with a warning runs only when confirm names it."""
    pack = _guard()
    from cockpitlib.errors import CockpitError
    from cockpitlib.helpers import _entry, run

    name = body.get("name") or ""
    try:
        entry = _entry(pack, name)
        if (entry["warn"] or entry["self"]) and body.get("confirm") != name:
            raise HTTPException(400, f"confirm={name} required: {entry['warn'] or 'this stops the page you are on'}")
        return run(pack, name, body.get("verb") or "", body.get("choice") or "", background=True)
    except CockpitError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.post("/intake-finish")
def intake_finish(body: dict):
    pack = _guard()
    from cockpitlib.acts import finish_intake
    from cockpitlib.errors import CockpitError

    try:
        return finish_intake(pack, body.get("id") or "", body.get("proposal") or "")
    except CockpitError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.get("/screen")
def screen():
    pack = _guard()
    from dashboard.cockpit.payload import build

    return build(pack, capacity())


@router.post("/setup")
def run_setup():
    pack = _guard()
    from cockpitlib.setup import setup

    setup(pack)
    return {"ok": True, "name": pack["name"]}


@router.get("/needs-you")
def needs_you():
    pack = _guard()
    from cockpitlib.health import watcher_rows
    from cockpitlib.paths import watch_dir

    rows = []
    for item in watcher_rows(pack, watch_dir()):
        record = item["record"]
        text = item["reason"]
        rows.append(
            {
                "name": item["name"],
                "ok": False,
                "reason": text,
                "summary": text,
                "fails": record.get("fails") or 0,
                "last_ok": record.get("last_ok"),
                "last_error": record.get("last_error"),
                "error": record.get("output") or "",
            }
        )
    if code_row():
        rows.append(code_row())
    # The host gateway runs every cron and the dispatcher: while it is down nothing above can fail visibly. Only while
    # cockpit is switched on (the human's own stop is no failure).
    from cockpitlib.pack_migration import _gateway_running
    from cockpitlib.setup import gateway_status

    if gateway_status() != "stopped" and not _gateway_running():
        down = "the Hermes gateway is down: no cron or lane runs until it is back (hermes gateway start)"
        rows.insert(
            0,
            {
                "name": "gateway",
                "ok": False,
                "reason": down,
                "summary": down,
                "fails": 1,
                "last_ok": None,
                "last_error": None,
                "error": "",
            },
        )
    from cockpitlib.inbox import rows as plugin_rows
    from cockpitlib.kanban import open_card_rows
    from cockpitlib.lend import inbox_rows
    from cockpitlib.self_update import inbox_row

    pending_update = inbox_row()
    if pending_update:
        rows.append(pending_update)
    from cockpitlib.answers import rows as answer_rows
    from cockpitlib.pr_watch import merge_ready
    from cockpitlib.tracker_watch import rows as tracker_notes

    # answers: a finished question card's summary and files, a row until used or dismissed (cockpitlib.answers)
    # tracker_notes: a tracker comment new or edited while the ticket's done row waits (cockpitlib.tracker_watch)
    return {
        "rows": rows,
        "cards": open_card_rows(pack["board"], pack),
        "watchers": rows,
        "privileged": inbox_rows(pack),
        "plugins": plugin_rows(pack),
        "merge_ready": merge_ready(),
        "answers": answer_rows(pack),
        "tracker_notes": tracker_notes(),
    }


from dashboard.cockpit.routes.pages import mount  # noqa: E402 - the routes import this module's names: they are mounted once those exist
from dashboard.cockpit.routes.vault import mount as mount_vault  # noqa: E402 - the routes import this module's names: they are mounted once those exist

mount(router)
mount_vault(router)
