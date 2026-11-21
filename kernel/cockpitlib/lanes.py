# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Seats and which one receives the next card."""

import os
import re

from .paths import hermes_home


def lanes_of(kind: str, count: int, per_slot: bool) -> list:
    if per_slot:
        return [f"{kind}-{index}" for index in range(1, count + 1)]
    return [kind] + [f"{kind}-{index}" for index in range(2, count + 1)]


def seats_from(pack, seats=None) -> dict:
    """The lanes of each kind. `seats` names the counts in force when they are not the pack's own.

    The pack's counts are what a seat is *declared* as; the settings are what it *is* — the Settings
    page writes the owner's number there without touching the pack. Dispatch has always read the
    settings (`free_lane`), so a count raised there put cards on lanes nobody had provisioned.
    """
    seats = seats or pack["seats"]
    return {
        "intake": lanes_of("intake", seats["intake"], False),
        "reviewer": lanes_of("reviewer", seats["reviewer"], False),
        "analyst": lanes_of("analyst", seats["analyst"], False),
        "worker": lanes_of("worker", seats["slots"], True),
        "tester": lanes_of("tester", seats["slots"], True),
        "gatekeeper": ["gatekeeper"],
        **({"advisor": ["advisor"]} if advisor_seat(pack) else {}),
    }


# The kinds of seat in the order the Live page lists their lanes: the order a ticket passes through them, then the two
# that serve the others. It is a page's order, not pack.ROLES': the gatekeeper is listed before the analyst there.
LIVE_KINDS = ("intake", "worker", "tester", "reviewer", "gatekeeper", "analyst", "advisor")


def live_order(pack) -> list:
    """The pack's seats in the order the Live page lists them: by kind (LIVE_KINDS), each kind's seats by number. The
    counts are the ones in force (the Settings page's over the pack's); a pack without seats has none."""
    from .errors import CockpitError

    if not (pack or {}).get("seats"):
        return []
    try:
        from .settings import load

        seats = load(pack)["seats"]
    except (CockpitError, OSError):  # no workspace to read the settings from: the pack's own counts
        seats = pack["seats"]
    found = seats_from(pack, seats)
    return [lane for kind in LIVE_KINDS for lane in found.get(kind) or []]


def advisor_seat(pack) -> bool:
    """The kernel asks the advisor through its own seat: the pack names checkpoints, no command of its own, and the
    advisor does not run inside the coding tool."""
    advisor = (pack or {}).get("advisor") or {}
    return bool(advisor.get("checkpoints")) and not advisor.get("command") and not advisor.get("in_tool")


def free_lane(kind: str, pack, open_cards: dict, ticket: str = "") -> str:
    """The seat for the next card of a kind: the least loaded. With the pack's `lanes.by_slot: true`, a worker or tester card
    of a ticket that holds a slot goes to that slot's seat (worker-N, tester-N), which has the worktree and the slot data;
    once the slot is released, to the seat that last worked the ticket (its worktree and memory are there)."""
    from .errors import CockpitError
    from .settings import frozen, load

    per_slot = kind in ("worker", "tester")
    seats = load(pack)["seats"]
    count = seats["slots"] if per_slot else seats[kind]
    blocked = frozen()
    names = [name for name in lanes_of(kind, count, per_slot) if name not in blocked]
    if not names:
        raise CockpitError(f"no seat for {kind}")
    if per_slot and ticket and ((pack or {}).get("lanes") or {}).get("by_slot"):
        from .slots import slot_of

        own = slot_of(ticket, count)
        if own and f"{kind}-{own}" in names:
            return f"{kind}-{own}"
        stuck = _sticky_lane(pack, kind, ticket, names)
        if stuck:
            return stuck
    return min(names, key=lambda name: (open_cards.get(name, 0), names.index(name)))


def _sticky_lane(pack, kind: str, ticket: str, names: list) -> str:
    """The seat of this kind that most recently had a card of the ticket, any status, when it is still one of `names`."""
    from .kanban import board_cards

    cards = [
        card
        for card in board_cards(pack["board"], pack)
        if card["ticket"] == ticket and re.fullmatch(rf"{re.escape(kind)}(-\d+)?", str(card.get("assignee") or ""))
    ]
    for card in sorted(cards, key=lambda card: str(card.get("created_at") or ""), reverse=True):
        if card["assignee"] in names:
            return card["assignee"]
    return ""


def role_provider(pack, role: str) -> dict:
    return pack["providers"][pack["roles"][role]]


def profile_dir(lane: str) -> str:
    return os.path.join(hermes_home(), "profiles", lane)
