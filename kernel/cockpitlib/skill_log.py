# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Which skills a lane loaded for a ticket.

Hermes loads a skill two ways: the lane calls skill_view, or the card names it and Hermes preloads it with
--skills. The first is recorded here from the skill_view result, one log per ticket and lane, so one lane's
load never answers for another. The second is read off the card.
"""

import json
import os

from .errors import CockpitError
from .paths import qa_of
from .store import append_line


def log_path(ticket: str, lane: str) -> str:
    if not ticket or not lane or os.sep in lane or lane.startswith("."):
        raise CockpitError("skill log needs a ticket and a lane")
    return qa_of(ticket, "skills", f"{lane}.log")


def loaded(ticket: str, lane: str) -> list:
    """The skills the lane logged for the ticket. No ticket or no lane (a human's intent) loaded nothing."""
    try:
        path = log_path(ticket, lane)
    except CockpitError:
        return []
    text = open(path, encoding="utf-8").read() if os.path.isfile(path) else ""
    return names_in(text)


def names_in(text) -> list:
    names = []
    for line in (text or "").splitlines():
        line = line.strip()
        if not line.startswith("skill:"):
            continue
        name = line.split(":", 1)[1].strip()
        if name and name not in names:
            names.append(name)
    return names


def append(ticket: str, lane: str, name: str) -> str:
    label = (name or "").strip()
    if not label:
        raise CockpitError("skill")
    path = log_path(ticket, lane)
    if label in loaded(ticket, lane):
        return label
    os.makedirs(os.path.dirname(path), exist_ok=True)
    append_line(path, f"skill:{label}\n")
    return label


def viewed_name(args, result) -> str:
    """The skill a skill_view result loaded, or empty. A plugin skill keeps its plugin:name; a local one is
    named as its SKILL.md names it. Reading one of a skill's other files is not loading it."""
    if not isinstance(args, dict) or args.get("file_path"):
        return ""
    try:
        payload = json.loads(result) if isinstance(result, str) else None
    except ValueError:
        return ""
    if not isinstance(payload, dict) or payload.get("success") is not True:
        return ""
    asked = str(args.get("name") or "").strip()
    if ":" in asked:
        return asked
    return str(payload.get("name") or asked).strip()


def current_card(env=None) -> tuple:
    """(board, card) of the kanban run this process belongs to. Hermes names both in a worker's environment."""
    env = os.environ if env is None else env
    card = env.get("HERMES_KANBAN_TASK") or ""
    board = env.get("HERMES_KANBAN_BOARD") or ""
    if card and not board:
        from .pack import load
        from .paths import pack_path

        board = str(load(pack_path())["board"])
    return board, card


def card_of(board: str, card: str) -> dict:
    from .kanban import board_cards

    return next((row for row in board_cards(board) if row["id"] == card), {}) if board and card else {}


def current_ticket(env=None) -> str:
    env = os.environ if env is None else env
    if env.get("COCKPIT_TICKET"):
        return env["COCKPIT_TICKET"]
    return card_of(*current_card(env)).get("ticket") or ""


def record_view(args, result, env=None) -> str:
    """transform_tool_result for skill_view: log what the lane loaded on its current ticket."""
    env = os.environ if env is None else env
    lane = env.get("COCKPIT_LANE") or ""
    name = viewed_name(args, result)
    if not lane or not name:
        return ""
    ticket = current_ticket(env)
    if not ticket:
        return ""
    return append(ticket, lane, name)


def missing(pack, intent, cards=None) -> list:
    """The intent type's required skills the creating lane has not loaded. An entry that is a list is any one of
    them. A human's intent requires none. `cards` is the board's cards by id when the caller already read them (a list of
    every intent would otherwise read the whole board once per intent)."""
    lane = intent.get("created_by") or "human"
    required = ((pack.get("skills") or {}).get("intent") or {}).get(intent["type"]) or []
    if lane in ("human", "") or not required:
        return []
    have = set(loaded(intent["ticket"], lane))
    # the cards that produced this content: the intent's own card, and the rework card a return or a treatment made (its run
    # amended the draft, so the skills it carried count)
    produced = [
        intent.get("card_id") or "",
        (intent.get("returned") or {}).get("card") or "",
        *[str(row.get("card") or "") for row in intent.get("treatments") or [] if isinstance(row, dict)],
    ]
    for card_id in produced:
        card = (
            {}
            if not card_id
            else cards.get(card_id) or {}
            if cards is not None
            else card_of(str(pack["board"]), card_id)
        )
        if card.get("assignee") == lane:
            have.update(card.get("skills") or [])
    gaps = []
    for entry in required:
        options = entry if isinstance(entry, list) else [entry]
        if not have.intersection(options):
            gaps.append(" or ".join(options))
    return gaps


def still_running(pack, intent) -> bool:
    return card_of(str(pack["board"]), intent.get("card_id") or "").get("status") == "running"
