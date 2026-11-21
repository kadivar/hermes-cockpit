# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""A refused outbox write is logged and kept as a row. It becomes an Inbox row only after the lane's card has ended without
fixing it: while the card works (or blocks, asking the human itself) the lane may still put it right, and an intent of the
same ticket and type made later settles it, and so does a later amend of the refused intent itself."""

import os
import time

from .store import log, read_json, write_json

ENDED = ("done", "archived", "cancelled")


def _path() -> str:
    from .paths import watch_dir

    return os.path.join(watch_dir(), "refusals.json")


def _load() -> list:
    rows = (read_json(_path()) or {}).get("refusals") or []
    return [row for row in rows if isinstance(row, dict) and row.get("key")]


def _save(rows: list) -> None:
    write_json(_path(), {"refusals": rows})


def record(ticket: str, kind: str, card: str, lane: str, reason: str, intent: str = "") -> None:
    extra = f" intent={intent}" if intent else ""
    log(f"REFUSE {ticket} {kind} card={card} lane={lane}{extra} :: {reason}")
    key = "|".join((ticket or "", kind or "", card or "", intent or ""))
    rows = [row for row in _load() if row["key"] != key]
    rows.append(
        {
            "key": key,
            "id": key,
            "ticket": ticket,
            "type": kind,
            "card": card,
            "lane": lane,
            "reason": reason,
            "intent": intent,
            "at": int(time.time()),
        }
    )
    _save(rows[-200:])


def find(key: str) -> dict:
    return next((row for row in _load() if row["key"] == key), {})


def dismiss(key: str) -> bool:
    rows = _load()
    kept = [row for row in rows if row["key"] != key]
    _save(kept)
    return len(kept) != len(rows)


def unresolved(pack) -> list:
    """The rows the human must see, newest first, with the card's end state and title."""
    from .intents import all_intents
    from .kanban import board_cards

    cards = {card["id"]: card for card in board_cards(pack["board"], pack)}
    intents = all_intents()
    out = []
    for row in _load():
        card = cards.get(row.get("card") or "") or {}
        if row.get("card") and card and card.get("status") not in ENDED:
            continue  # the card may still put it right
        if any(
            item.get("ticket") == row["ticket"]
            and item.get("type") == row["type"]
            and _stamp(item.get("created_at")) > row["at"]
            for item in intents
        ):
            continue  # a later intent of the same ticket and type settles it
        if row.get("intent") and any(
            item.get("id") == row["intent"] and _stamp(item.get("amended_at")) > row["at"] for item in intents
        ):
            continue  # the refused amend's own intent was amended since
        from .render import markdown

        out.append(
            {
                **row,
                "card_status": card.get("status") or "",
                "card_title": card.get("title") or "",
                "card_lane": card.get("assignee") or row.get("lane") or "",
                "reason_html": markdown(str(row.get("reason") or "")),  # a lane writes its reasons in markdown
                "time": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(row["at"])),
            }
        )
    return sorted(out, key=lambda row: -row["at"])


def _stamp(value) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    import datetime

    try:
        return datetime.datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return 0.0
