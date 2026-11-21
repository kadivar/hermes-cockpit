# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""ISO timestamps and the quiet window the workspace watch uses."""

import datetime


def iso(now=None) -> str:
    moment = now or datetime.datetime.now(datetime.UTC)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=datetime.UTC)
    return moment.astimezone(datetime.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def stamp(value) -> float:
    """Epoch seconds of an ISO timestamp `iso` wrote; 0 when it is missing or unreadable."""
    try:
        return datetime.datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return 0.0


def quiet(mtime: float, now: float, seconds: int = 300) -> bool:
    """True when nothing has been written inside the quiet window."""
    if mtime < 0:
        return False
    return (now - mtime) >= seconds
