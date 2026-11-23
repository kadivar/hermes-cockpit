# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""A card a lane parked as `scheduled` itself wakes when its time comes, and the human sees it waiting.

Hermes's schedule tool parks a card "while it waits for a time or external event" and, in its own words, "does not
create a timer": the card stays parked until something unblocks it. The lane writes the time it waits for into the
reason (`SCHEDULED_UNTIL=<ISO8601>`, the marker the tool asks for). A parked card is no ask (it is not blocked) and no
running work, so without this step it waits on the board unseen and past its time.

Every minute, a lane-scheduled card whose time has passed is made ready again with a comment that says why; a card still
waiting, or one parked with no time to wake at, is a row under `cockpit` in the Inbox, with a button that wakes it now.
Cards cockpit parks for a provider's quota are quota.py's (their reason starts with quota.MARK); a plugin's card is its
plugin's. Neither is touched here.
"""

import datetime
import re
import sqlite3
import time

UNTIL = re.compile(r"SCHEDULED_UNTIL=(\S+)")
PREFIX = "scheduled-"


def wake_at(reason):
    """The moment in `SCHEDULED_UNTIL=<ISO8601>` as epoch seconds (a time without a zone is this machine's), else None."""
    found = UNTIL.search(str(reason or ""))
    if not found:
        return None
    text = found.group(1).rstrip(".,;)")
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        return datetime.datetime.fromisoformat(text).timestamp()
    except ValueError:
        return None


def _local(moment: float) -> str:
    return datetime.datetime.fromtimestamp(moment).strftime("%Y-%m-%d %H:%M")


def _row(card: str, title: str, lane: str, reason: str, until) -> dict:
    name = title or card
    if until is None:
        what = f"{name} is parked with no time to wake at: nothing starts it again but you"
        ends, tone = "only when you wake it (the lane named no SCHEDULED_UNTIL time)", "warn"
    else:
        what = f"{name} waits until {_local(until)}: it starts again by itself then"
        ends, tone = f"{_local(until)}, when cockpit makes it ready again", "info"
    return {
        "id": f"{PREFIX}{card}",
        "icon": "⏱",
        "what": what,
        "tone": tone,
        "detail": {
            "title": f"Scheduled: {name}",
            "status": {"text": "scheduled", "color": tone},
            "fields": [
                {"label": "card", "text": f"{card} · {lane}" if lane else card},
                {"label": "what the lane waits for", "text": reason or "(no reason given)"},
                {"label": "ends", "text": ends},
            ],
            "actions": [
                {
                    "label": "Wake it now",
                    "hint": "the card is ready again now; the lane reads why on the card",
                    "act": {"do": "wake", "card": card},
                }
            ],
        },
    }


def _parked(pack, connection) -> list[tuple[str, str, str, str]] | None:
    """[(card, title, lane, reason)] of the lane-scheduled cards: not cockpit's quota parks, not a plugin's cards. None
    when the board keeps no record of why a card was parked, so nothing can be told about whose it is."""
    from .housekeeping import _owned_cards
    from .quota import _ours, _scheduled_reasons

    cards = {
        str(card): (str(title or ""), str(lane or ""))
        for card, title, lane in connection.execute("select id, title, assignee from tasks where status = 'scheduled'")
    }
    reasons = _scheduled_reasons(connection, sorted(cards))
    if reasons is None:
        return None
    owned = _owned_cards(pack)
    return [
        (card, title, lane, str(reasons.get(card) or ""))
        for card, (title, lane) in sorted(cards.items())
        if card not in owned and not _ours(reasons.get(card))
    ]


def step(pack, now=None) -> str:
    """Housekeeping, every minute: wake the lane-scheduled cards whose time has passed; one Inbox row per card still
    parked."""
    from .housekeeping import _db
    from .kanban import BoardWrites
    from .own_rows import keep_only, raise_row
    from .store import log

    moment = float(time.time() if now is None else now)
    connection = _db(pack)
    if connection is None:
        return "0 woke"
    try:
        parked = _parked(pack, connection)
    except sqlite3.Error:
        return "0 woke"
    finally:
        connection.close()
    if parked is None:
        return "0 woke"
    due: list[tuple[str, str, str, str, float]] = []
    waiting: list[tuple[str, str, str, str, float | None]] = []
    for card, title, lane, reason in parked:
        until = wake_at(reason)
        if until is not None and until <= moment:
            due.append((card, title, lane, reason, until))
        else:
            waiting.append((card, title, lane, reason, until))
    if due:
        writes = BoardWrites(pack["board"])
        for card, _title, _lane, reason, until in due:
            writes.comment(
                card,
                "cockpit",
                f"The time this card was scheduled until ({_local(until)}) has passed: it is ready again. "
                f"Pick up where you parked it: {reason}",
            )
            writes.unblock(card)
        writes.flush()
        log(f"WAKE-SCHEDULED {' '.join(card for card, *_ in due)}")
    for card, title, lane, reason, until in waiting:
        raise_row(_row(card, title, lane, reason, until))
    keep_only(PREFIX, {f"{PREFIX}{card}" for card, *_ in waiting})
    return f"{len(due)} woke, {len(waiting)} waiting"


def wake(pack, card: str) -> str:
    """The human's Wake it now: a lane-scheduled card is ready again at once, with a comment saying who woke it."""
    from .errors import CockpitError
    from .housekeeping import _db
    from .kanban import BoardWrites

    card = str(card or "")
    connection = _db(pack)
    if connection is None:
        raise CockpitError("no board to wake a card on")
    try:
        parked = {entry[0]: entry for entry in (_parked(pack, connection) or [])}
    finally:
        connection.close()
    if card not in parked:
        raise CockpitError(f"{card or '?'} is not a card a lane parked as scheduled (any more)")
    writes = BoardWrites(pack["board"])
    writes.comment(
        card,
        "cockpit",
        f"The human woke this card before its scheduled time. Pick up where you parked it: {parked[card][3]}",
    )
    writes.unblock(card)
    writes.flush()
    return f"{card} is ready again"
