# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The daily standup note: what the platform did since the window opened, read from the records that already exist
(published intents and their receipts, the PR watch's merges, finished test runs), never from memory.

Sections, a line per ticket under each, the ticket as a link:
    Tested:              - "The order total ignores …" TASK-101 — test results posted on the tracker
    Developed:           Opened: / Merged:  - "…" TASK-102 — api#12 opened
    Reviewed:            - "…" TASK-103 — web#31 changes requested
    Dependency bumps:    - the week's batch — api#45
    Waiting on others:   our PRs without an approval, PRs we sent back for changes, merged tickets the tracker does
                         not call finished yet (the testing after the merge)
"""

import datetime
import glob
import json
import os
import re

from .paths import outbox_of, qa_of

TICKET = re.compile(r"^[A-Z][A-Z0-9]*(?:-[A-Z0-9]+)+$")
RELEASED = ("ready for release", "released", "archive", "archived", "done", "closed")
MINE = (
    "intake",
    "dev",
    "worker",
)  # the flows that make a ticket ours; a test or review flow alone is a colleague's ticket
BUMPS = "BUMPS-"  # the prefix the note has always read as a bump batch, whatever the pack's batch template


def is_bumps(pack, ticket: str) -> bool:
    """The ticket is a bump batch: one the pack's forge.bump_batch template names (the kernel's own matcher), or one
    with the prefix this note has always read."""
    if str(ticket or "").startswith(BUMPS):
        return True
    from .sequence import is_batch

    return is_batch(pack, ticket)


# The note's headings by section id, the order of its sections, and the file its chat-formatted twin is written to: each
# the default of a key of the pack's standup block. `opened` and `merged` are the two halves of `developments`.
LABELS = {
    "testings": "Tested:",
    "developments": "Developed:",
    "opened": "Opened:",
    "merged": "Merged:",
    "reviews": "Reviewed:",
    "bumps": "Dependency bumps:",
    "created": "Created:",
    "closed": "Closed:",
    "also": "Also:",
    "waiting": "Waiting on others:",
}
ORDER = ("testings", "developments", "reviews", "bumps", "created", "closed", "also", "waiting")
CHAT_FILE = "standup.chat"


def labels(pack) -> dict:
    """{section id: heading}: the pack's standup.sections over the kernel's own. A section the pack does not name keeps
    its heading; one it gives an empty heading is hidden, and says so with an empty text here."""
    raw = ((pack or {}).get("standup") or {}).get("sections") or {}
    return {name: own if raw.get(name) is None else str(raw[name]).strip() for name, own in LABELS.items()}


def order(pack) -> list:
    """The note's sections in the order they are printed: the pack's standup.order, else the kernel's own."""
    return list(((pack or {}).get("standup") or {}).get("order") or ORDER)


def chat_file(pack) -> str:
    """The file beside standup.md the chat-formatted note is written to: the pack's standup.chat_file."""
    return str(((pack or {}).get("standup") or {}).get("chat_file") or CHAT_FILE)


def _epoch(value) -> float:
    if value in (None, ""):
        return 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        pass
    try:
        return datetime.datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return 0.0


def tickets() -> list:
    """Every ticket key with an outbox or qa folder."""
    from .paths import outbox, qa

    keys = set()
    for base, folder_of in ((outbox(), outbox_of), (qa(), qa_of)):
        for name in os.listdir(base) if os.path.isdir(base) else []:
            if TICKET.match(name) and os.path.isdir(folder_of(name)):
                keys.add(name)
    return sorted(keys)


def _pr_of(intent: dict) -> dict:
    payload = intent.get("payload") or {}
    url = (intent.get("receipt") or {}).get("url") or payload.get("url") or ""
    match = re.search(r"/pull/(\d+)", str(url))
    return {
        "repo": payload.get("repo") or "",
        "number": str(payload.get("number") or (match.group(1) if match else "")),
        "url": url if "/pull/" in str(url) else "",
    }


def _read_json(path):
    try:
        data = json.load(open(path, encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data


def _runs(pack, ticket: str, *inner) -> list:
    """A ticket's run folders (or a file inside each) by the pack's testflow.run_dir, oldest first."""
    from .test_flow import run_folders

    folder = qa_of(ticket)
    paths = [os.path.join(folder, run, *inner) for run in run_folders(pack, folder)]
    return [path for path in paths if os.path.exists(path)]


def collect(since: float, until: float, pack=None) -> dict:
    """What was done in [since, until): {ticket: {developed, tested, reviewed, bumps, merged, created, done, other}},
    one dict per act (what, url, at)."""
    from .intents import all_intents
    from .test_flow import results_file

    results_name = results_file(pack)
    out = {}

    def add(ticket, kind, what, url="", at=0.0):
        out.setdefault(ticket, {}).setdefault(kind, []).append({"what": what, "url": url, "at": at})

    for ticket in tickets():
        batch = is_bumps(pack, ticket)
        for intent in all_intents(ticket):
            status = str(intent.get("status", ""))
            if not status.startswith("published") and status != "acknowledged":
                continue
            at = _epoch((intent.get("receipt") or {}).get("time")) or _epoch(intent.get("created_at"))
            if not since <= at < until:
                continue
            kind = intent.get("type")
            payload = intent.get("payload") or {}
            pr = _pr_of(intent)
            receipt = intent.get("receipt") or {}
            if batch:
                if kind in ("push-branch", "pr-edit", "pr-review-submit", "tracker-create", "tracker-transition"):
                    add(ticket, "bumps", f"{pr['repo']}#{pr['number']}" if pr["number"] else kind, pr["url"], at)
            elif kind in ("push-branch", "open-pr", "pr-patch-apply"):
                what = {
                    "push-branch": "branch pushed",
                    "open-pr": "PR opened",
                    "pr-patch-apply": "review answered with a patch",
                }[kind]
                add(
                    ticket,
                    "developed",
                    what + (f" ({pr['repo']}#{pr['number']})" if pr["number"] else ""),
                    pr["url"],
                    at,
                )
            elif kind == "pr-review-submit":
                event = (payload.get("event") or "").upper()
                verdict = {"APPROVE": "approved", "REQUEST_CHANGES": "changes requested", "COMMENT": "commented"}.get(
                    event, "reviewed"
                )
                add(ticket, "reviewed", f"{pr['repo']}#{pr['number']} {verdict}".strip(), pr["url"], at)
            elif (
                kind == "tracker-comment"
                and (payload.get("comment_from") or payload.get("comment_id"))
                and _runs(pack, ticket)
            ):
                add(ticket, "tested", "test results posted on the tracker", receipt.get("url") or "", at)
            elif kind == "tracker-create":
                key = receipt.get("key") or str(receipt.get("url") or "").rsplit("/", 1)[-1]
                add(
                    ticket,
                    "created",
                    f"tracker ticket {key} ({(payload.get('summary') or '')[:60]})".strip(),
                    receipt.get("url") or "",
                    at,
                )
            elif kind == "ticket-done":
                add(ticket, "done", "ticket closed", "", at)
            elif kind in ("pr-comment", "tracker-comment", "tracker-transition", "pr-edit", "ci-rerun"):
                what = {
                    "pr-comment": "PR comment",
                    "tracker-comment": "tracker comment",
                    "tracker-transition": f"tracker moved to {payload.get('to') or payload.get('transition') or '…'}",
                    "pr-edit": "PR edited",
                    "ci-rerun": "CI rerun",
                }[kind]
                add(ticket, "other", what, pr["url"] or receipt.get("url") or "", at)
        for path in glob.glob(qa_of(ticket, "pr", "*.json")):  # merges the watch saw
            state = _read_json(path)
            if not isinstance(state, dict):
                continue
            at = _epoch(state.get("merged_at"))
            if state.get("merged") and since <= at < until:
                name = f"{state.get('repo')}#{state.get('number')} merged"
                if batch:
                    add(ticket, "bumps", name, state.get("url") or "", at)
                else:
                    add(
                        ticket,
                        "merged",
                        name + (" (our PR)" if state.get("role") == "author" else " (reviewed by us)"),
                        state.get("url") or "",
                        at,
                    )
        for path in _runs(pack, ticket, results_name):  # runs finished
            at = os.path.getmtime(path)
            if since <= at < until and not any(
                x["what"] == "test results posted on the tracker" for x in out.get(ticket, {}).get("tested", [])
            ):
                add(
                    ticket,
                    "bumps" if batch else "tested",
                    f"{os.path.basename(os.path.dirname(path))} finished",
                    "",
                    at,
                )
    return out


def open_work(pack) -> list:
    """The tickets the pipeline knows, with their flows, PRs and last card: [{ticket, flows, prs, last_card}], bumps
    batches left out."""
    from .kanban import board_cards
    from .pr_watch import prs_of

    if not pack.get("board"):
        return []  # a pack that names no board (an older one) has no open work to list
    found = {}
    for card in board_cards(pack["board"], pack):
        ticket = card.get("ticket") or ""
        if not ticket or is_bumps(pack, ticket):
            continue
        row = found.setdefault(ticket, {"ticket": ticket, "flows": [], "prs": [], "last_card": ""})
        if card.get("flow") and card["flow"] not in row["flows"]:
            row["flows"].append(card["flow"])
        created = str(card.get("created_at") or "")
        if created > str(row["last_card"]):
            row["last_card"] = created
    for ticket in tickets():
        if is_bumps(pack, ticket):
            continue
        prs = prs_of(ticket)
        if prs:
            found.setdefault(ticket, {"ticket": ticket, "flows": [], "prs": [], "last_card": ""})["prs"] = prs
    return list(found.values())


def mine(acts: dict, open_: list) -> set:
    """The tickets that are ours: an intake or dev flow, a PR we authored, a push or PR of ours in the window."""
    out = {
        ticket
        for ticket, act in acts.items()
        if act.get("developed") or any(x["what"].endswith("(our PR)") for x in act.get("merged") or [])
    }
    for row in open_ or []:
        flows = {str(flow).split("·")[0] for flow in row.get("flows") or []}
        if flows & set(MINE) or any((pr.get("role") or "author") == "author" for pr in row.get("prs") or []):
            out.add(row["ticket"])
    return out


def finished(statuses: dict, ticket: str) -> bool:
    return (statuses or {}).get(ticket, "").strip().lower() in RELEASED


def waiting(open_: list, statuses: dict, touched=None, ours=None) -> dict:
    """What waits on a colleague, per touched ticket: our open PRs without an approval, PRs we sent back for changes
    (Review), our merged PRs whose tracker ticket is not finished yet (Test). {ticket: [{kind, what, url}]}"""
    out = {}
    ours = ours if ours is not None else mine({}, open_)
    for row in open_:
        ticket = row["ticket"]
        if touched is not None and ticket not in touched:
            continue
        if finished(statuses, ticket):
            continue
        whats, merged = [], []
        for pr in row.get("prs") or []:
            name = f"{pr.get('repo')}#{pr.get('number')}"
            if pr.get("merged"):
                if (pr.get("role") or "author") == "author":
                    merged.append(name)
                continue
            if pr.get("state") not in (None, "", "open", "OPEN"):
                continue
            if (pr.get("role") or "author") == "author" and not pr.get("approvals"):
                whats.append(
                    {"kind": "Review", "what": f"{name} waiting for a review approval", "url": pr.get("url") or ""}
                )
            elif pr.get("role") == "reviewer" and pr.get("my_review_state") == "CHANGES_REQUESTED":
                whats.append(
                    {
                        "kind": "Review",
                        "what": f"{name} waiting for the author's changes after our review",
                        "url": pr.get("url") or "",
                    }
                )
        status = (statuses.get(ticket) or "").strip()
        if merged and ticket in ours and status:
            whats.append(
                {
                    "kind": "Test",
                    "what": f"{', '.join(merged)} merged, tracker still '{status}': waiting for the testing after the merge",
                    "url": "",
                }
            )
        if whats:
            out[ticket] = whats
    return out


def _fmt(pack, fmt: str):
    from .tracker import browse

    def ticket(shape: str):
        """The ticket as a link in that shape, or as its bare key when the tracker has no page for it."""

        def said(t):
            page = browse(pack, t)
            return shape.format(page=page, key=t) if page else t

        return said

    if fmt == "slack":
        jira = ticket("<{page}|{key}>")
        plink = lambda a: f"<{a['url']}|{a['what']}>" if a.get("url") else a["what"]
        head = lambda t: f"*{t}*"
    else:
        jira = ticket("[{key}]({page})")
        plink = lambda a: f"[{a['what']}]({a['url']})" if a.get("url") else a["what"]
        head = lambda t: f"**{t}**"
    link = lambda t: t if t.startswith(BUMPS) else jira(t)
    return link, plink, head


def _line(ticket, title, acts, link, plink) -> str:
    name = f'"{title.strip()}" ' if title and title.strip() else ""
    details = ", ".join(plink(a) for a in acts)
    return f"- {name}{link(ticket)} — {details}" if details else f"- {name}{link(ticket)}"


def _renamed(acts, old, new):
    return [dict(a, what=a["what"].replace(old, new)) for a in acts]


def sections(pack, acts: dict, titles: dict, fmt: str = "md", open_=None, statuses=None, touched=None) -> list:
    """The note's body: titled sections, a line per ticket under each; an empty section is left out."""
    link, plink, head = _fmt(pack, fmt)
    titles = titles or {}
    ours = mine(acts, open_)
    out = []

    named = labels(pack)
    made = {}  # section id -> its lines, built in the kernel's own order and printed in the pack's

    def block(name, rows):
        if rows and named[name]:
            made[name] = [head(named[name]), *rows, ""]

    def row(ticket, items):
        return _line(ticket, titles.get(ticket, ""), items, link, plink)

    def per(kind, keep=lambda t, a: True):
        return [row(t, acts[t][kind]) for t in sorted(acts) if acts[t].get(kind) and keep(t, acts[t])]

    block("testings", per("tested", lambda t, a: t not in ours))
    opened = [
        row(
            t,
            acts[t]["developed"]
            + _renamed(
                acts[t].get("tested") or [], "test results posted on the tracker", "tested, results on the tracker"
            ),
        )
        for t in sorted(acts)
        if t in ours and acts[t].get("developed")
    ]
    merged = [
        row(t, _renamed([x for x in acts[t]["merged"] if x["what"].endswith("(our PR)")], " (our PR)", ""))
        for t in sorted(acts)
        if t in ours and any(x["what"].endswith("(our PR)") for x in acts[t].get("merged") or [])
    ]
    halves = [
        line
        for name, rows in (("opened", opened), ("merged", merged))
        if rows and named[name]
        for line in (named[name], *rows)
    ]
    block("developments", halves)
    reviews = [
        row(
            t,
            (acts[t].get("reviewed") or [])
            + _renamed(
                [x for x in acts[t].get("merged") or [] if x["what"].endswith("(reviewed by us)")],
                "merged (reviewed by us)",
                "merged after our review",
            ),
        )
        for t in sorted(acts)
        if acts[t].get("reviewed") or any(x["what"].endswith("(reviewed by us)") for x in acts[t].get("merged") or [])
    ]
    block("reviews", reviews)
    block("bumps", per("bumps"))
    block("created", per("created"))
    block("closed", per("done"))
    block("also", per("other", lambda t, a: not any(a.get(k) for k in ("tested", "developed", "reviewed", "merged"))))
    if open_:
        waits = waiting(open_, statuses or {}, touched, ours)
        block(
            "waiting",
            [
                f"- {kind}: " + row(t, [a for a in waits[t] if a["kind"] == kind])[2:]
                for t in sorted(waits)
                for kind in ("Review", "Test")
                if any(a["kind"] == kind for a in waits[t])
            ],
        )
    for name in order(pack):
        out.extend(made.get(name) or [])
    while out and out[-1] == "":
        out.pop()
    return out


def touched(acts: dict, open_: list, since: float, until: float) -> set:
    """The tickets the window touched: an act in it, or a card made in it."""
    return set(acts) | {row["ticket"] for row in open_ or [] if since <= _epoch(row.get("last_card")) < until}


def note(pack, acts, titles, since: float, until: float, fmt: str = "md", open_=None, statuses=None) -> str:
    head = (
        f"Standup {datetime.datetime.fromtimestamp(until).astimezone().strftime('%a %d %b %Y')} — "
        f"since {datetime.datetime.fromtimestamp(since).astimezone().strftime('%a %H:%M')}"
    )
    body = sections(pack, acts, titles, fmt, open_, statuses, touched(acts, open_, since, until)) or [
        "- nothing left the machine in this window"
    ]
    return (f"*{head}*" if fmt == "slack" else f"**{head}**") + "\n\n" + "\n".join(body) + "\n"


def _statuses(pack, keys) -> dict:
    """The tracker's status per ticket, when the tracker answers; a tracker that cannot leaves every ticket open."""
    from . import tracker, trackers

    try:
        reader = trackers.seam(tracker.tracker_for(pack))
    except Exception:  # noqa: BLE001 - a tracker that cannot be made gives no statuses
        return {}
    if trackers.base.STATUS not in reader.capabilities():
        return {}
    return reader.statuses([key for key in keys if not key.startswith(BUMPS)])


def draft(pack, since: float, until: float) -> dict:
    """Collect, name the tickets (tracker titles), build the note in both formats."""
    from .tracker import titles

    acts = collect(since, until, pack)
    open_ = open_work(pack)
    keys = sorted(touched(acts, open_, since, until))
    try:
        named = titles(pack, keys, refresh=True) if keys else {}
    except Exception:  # noqa: BLE001 - a failed refresh falls back to the titles already kept
        named = titles(pack, keys) if keys else {}
    statuses = _statuses(pack, keys)
    waits = waiting(open_, statuses, set(keys))
    return {
        "since": datetime.datetime.fromtimestamp(since).astimezone().isoformat(timespec="seconds"),
        "until": datetime.datetime.fromtimestamp(until).astimezone().isoformat(timespec="seconds"),
        "acts": acts,
        "titles": named,
        "waiting": waits,
        "statuses": statuses,
        "markdown": note(pack, acts, named, since, until, "md", open_, statuses),
        "slack": note(pack, acts, named, since, until, "slack", open_, statuses),
        "items": sum(len(v) for a in acts.values() for v in a.values()) + sum(len(v) for v in waits.values()),
    }
