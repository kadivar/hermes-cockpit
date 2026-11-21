# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""A halt marker stops every creator until the human resumes."""

import json
import os

from .paths import qa_of, segment
from .store import dump_json


def path(ticket: str) -> str:
    """The ticket's halt marker. No ticket is the records' own marker; a key that is a path is refused."""
    return qa_of(segment(ticket, "ticket") if ticket else "", "halt.json")


def halted(ticket: str):
    file = path(ticket)
    if not os.path.isfile(file):
        return None
    return json.load(open(file, encoding="utf-8"))


def _own(ticket: str) -> str:
    """The marker of a named ticket, for the two that write and remove: no ticket is read as the records' own marker and
    is never written or removed as one."""
    return path(segment(ticket, "ticket"))


def write(ticket: str, note: str = "") -> None:
    file = _own(ticket)
    os.makedirs(os.path.dirname(file), exist_ok=True)
    dump_json(file, {"note": note})


def clear(ticket: str) -> bool:
    file = _own(ticket)
    if not os.path.isfile(file):
        return False
    os.remove(file)
    return True


def describe(ticket: str, record) -> str:
    note = (record or {}).get("note") or ""
    extra = f" ({note})" if note else ""
    return f"{ticket} is halted{extra}"


def refuse(ticket: str) -> None:
    """A halted ticket accepts no new creator. Resume lifts this."""
    record = halted(ticket or "")
    if not record:
        return
    from .errors import Conflict

    raise Conflict(describe(ticket, record))
