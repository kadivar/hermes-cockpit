# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""After go, intake breaks the ticket into cards: per repo, the pack's chain of kinds (a worker, then a tester, then a
reviewer, say), each the child of the one before. Intake writes the breakdown; the kernel checks it against the pack
and the plan and makes the cards through the board."""

import os
import re

from .errors import CockpitError
from .paths import qa_of
from .store import dump_json

DEFAULT_CHAIN = (
    "work",
    "tester",
    "review",
)  # the chain's tester runs the approved plan's rows; `test` is a Test kickoff
ROLE_OF = {"work": "worker", "rework": "worker", "test": "tester", "tester": "tester", "review": "reviewer"}
DEFAULT_BODY = """{ticket}: {role} on {repo}.

Plan: {plan}
Slot: {slot}
PRs: {prs}
Plan gate: {plan_gate}
"""
GATES = ("auto", "human")


def chain(pack) -> list:
    return list((((pack or {}).get("skills") or {}).get("cards") or {}).get("decompose") or DEFAULT_CHAIN)


def body_template(pack) -> str:
    path = (((pack or {}).get("skills") or {}).get("cards") or {}).get("body")
    if path:
        return open(path, encoding="utf-8").read()
    return DEFAULT_BODY


def _model_id(text) -> str:
    """The row's `model` as a model id, or "" when it is not one. The field is a card's model override: Hermes sends
    it to the provider as the model name. Intake wrote what its contract calls the worker's level, "sonnet high +
    advisor", and both work cards of a ticket failed twice on the provider's 404 ("model: sonnet high + advisor") and
    were given up. A model id has no spaces; a description of a level is the lane's own configuration
    (the pack's roles), so it is not passed on."""
    value = str(text or "").strip()
    return value if value and not re.search(r"[\s+,;]", value) else ""


def check(pack, ticket: str, breakdown) -> list:
    """The breakdown's rows, normalised: [{repo, slot, prs, plan_gate, model}]. Anything the pack does not know is refused."""
    from .plan import decided

    if not decided(ticket):
        raise CockpitError(f"{ticket} has no go: the breakdown comes after it")
    rows = breakdown.get("repos") if isinstance(breakdown, dict) else None
    if not isinstance(rows, list) or not rows:
        raise CockpitError("the breakdown lists repos: [{repo, slot, prs, plan_gate}]")
    known = {repo["name"] for repo in pack["repos"]["repos"] if repo.get("name")}
    seen = set()
    found = []
    for row in rows:
        if not isinstance(row, dict) or set(row) - {"repo", "slot", "prs", "plan_gate", "model", "note", "after"}:
            raise CockpitError("each breakdown row takes repo, slot, prs, plan_gate, model, note and after")
        repo = str(row.get("repo") or "")
        if repo not in known:
            raise CockpitError(f"{repo or 'a row'} is not a repo of this pack ({', '.join(sorted(known))})")
        if repo in seen:
            raise CockpitError(f"{repo} is listed twice")
        seen.add(repo)
        gate = str(row.get("plan_gate") or "auto")
        if gate not in GATES:
            raise CockpitError(f"plan_gate is auto or human, not {gate}")
        prs = row.get("prs") or []
        if not isinstance(prs, list):
            raise CockpitError("prs is a list")
        found.append(
            {
                "repo": repo,
                "slot": str(row.get("slot") or "auto"),
                "prs": [str(item) for item in prs],
                "plan_gate": gate,
                "model": _model_id(row.get("model")),
                "note": str(row.get("note") or ""),
                **({"after": str(row["after"])} if row.get("after") else {}),
            }
        )
    return _in_order(found)


def _in_order(rows: list) -> list:
    """A row with `after: <repo>` is made once that repo's row is, and its first card waits for that repo's last card (the backend
    before the frontend). Rows without it keep their order."""
    repos = {row["repo"] for row in rows}
    for row in rows:
        if row.get("after") and (row["after"] not in repos or row["after"] == row["repo"]):
            raise CockpitError(f"{row['repo']} comes after {row['after']}, which is not another row of this breakdown")
    ordered = []
    pending = list(rows)
    while pending:
        ready = [row for row in pending if not row.get("after") or row["after"] in {done["repo"] for done in ordered}]
        if not ready:
            raise CockpitError("the rows come after each other in a loop")
        ordered.append(ready[0])
        pending.remove(ready[0])
    return ordered


def _queue_path() -> str:
    from .paths import watch_dir

    return os.path.join(watch_dir(), "decompose-queue.json")


def decompose_or_queue(pack, ticket: str, breakdown) -> dict:
    """decompose(), from the command line. Hermes closes the board to a command a lane runs itself ("delegate_task child
    contexts cannot mutate Kanban tasks"), so intake's own `flow decompose` is refused there. Cards intake then makes
    by hand with its board tool carry seats and a stack of its own choosing, which can contradict the stack the
    kickoff bound and leave the worker unable to start any.
    The breakdown is checked now, kept, and the housekeeping makes the cards on its next pass (decompose_queued)."""
    rows = check(pack, ticket, breakdown)
    try:
        return decompose(pack, ticket, breakdown)
    except CockpitError as exc:
        if not os.environ.get("COCKPIT_LANE") or "helper failed" not in str(exc):
            raise
    from .browser_card import _lane_card
    from .store import read_json, write_json

    waiting = [row for row in (read_json(_queue_path()) or []) if isinstance(row, dict) and row.get("ticket") != ticket]
    waiting.append(
        {
            "ticket": ticket,
            "breakdown": breakdown,
            "parent": _lane_card(pack),
            "lane": os.environ.get("COCKPIT_LANE") or "",
        }
    )
    write_json(_queue_path(), waiting)
    return {
        "ok": True,
        "queued": True,
        "ticket": ticket,
        "cards": [],
        "out": f"the breakdown of {ticket} ({len(rows)} repo(s)) is queued: the board is closed to a lane's own command, the "
        "housekeeping makes the cards within a minute, on the seats of the stack the ticket holds. Do not make them "
        "by hand; finish your card.",
    }


def decompose_queued(pack) -> str:
    """The housekeeping step: make the cards of the breakdowns lanes filed while the board was closed to them. One that
    fails again stays queued with what was said."""
    from .store import log, read_json, write_json

    waiting = [row for row in (read_json(_queue_path()) or []) if isinstance(row, dict)]
    if not waiting:
        return "0"
    left, made = [], 0
    for row in waiting:
        try:
            done = decompose(pack, row["ticket"], row["breakdown"], parent_card=row.get("parent") or "")
            log(f"DECOMPOSE-QUEUED {row['ticket']} → {' '.join(card['card'] for card in done['cards'])}")
            made += 1
        except (CockpitError, KeyError) as exc:
            left.append({**row, "error": str(exc)[-200:]})
    write_json(_queue_path(), left)
    return str(made)


def _stack_of(pack, ticket: str, asked: str) -> str:
    """The stack a card is told: the one the ticket holds when it holds one (the kickoff binds it), else what the row asked."""
    from .slots import slot_of

    own = slot_of(ticket, int(((pack or {}).get("seats") or {}).get("slots") or 0))
    return str(own) if own else asked


def decompose(pack, ticket: str, breakdown, parent_card=None) -> dict:
    """Make each repo's chain of cards. A card already made for the same ticket, repo and kind is kept, not doubled.
    `parent_card`: the card the chain hangs from when this does not run inside it (the housekeeping's queued breakdown)."""
    from .halt import refuse
    from .kanban import card_skills, card_title, open_cards, place_card
    from .lanes import free_lane
    from .plan import plan_path
    from .skill_log import current_card

    refuse(ticket)
    rows = check(pack, ticket, breakdown)
    if parent_card is None:
        _board, parent_card = current_card()
    template = body_template(pack)
    made = []
    last = {}
    for row in rows:
        parent = last.get(row.get("after")) or (parent_card if parent_card else "")
        for kind in chain(pack):
            role = ROLE_OF.get(kind, "worker")
            lane = free_lane(role, pack, open_cards(pack["board"]), ticket=ticket)
            title = card_title(kind, ticket, pack=pack, repo=row["repo"])
            if row["repo"] not in title:
                title = f"{title} ({row['repo']})"
            body = template.format(
                ticket=ticket,
                role=role,
                repo=row["repo"],
                plan=plan_path(ticket),
                slot=_stack_of(pack, ticket, row["slot"]),
                prs=", ".join(row["prs"]) or "none yet",
                plan_gate=row["plan_gate"],
                note=row["note"],
            )
            card = place_card(
                pack["board"],
                title,
                lane,
                "ready",
                body=body,
                parents=[parent] if parent else (),
                skills=card_skills(pack, kind, repos=[row["repo"]]),
                kind=kind,
                ticket=ticket,
                pack=pack,
                repos=[row["repo"]],
                idempotency_key=f"decompose-{ticket}-{row['repo']}-{kind}",
                model_override=row["model"] if role == "worker" else "",
            )
            made.append({"repo": row["repo"], "kind": kind, "lane": lane, "card": card, "parent": parent})
            parent = card
        last[row["repo"]] = parent
    folder = qa_of(ticket)
    os.makedirs(folder, exist_ok=True)
    dump_json(os.path.join(folder, "breakdown.json"), {"rows": rows, "cards": made}, indent=1)
    return {"ok": True, "ticket": ticket, "cards": made}
