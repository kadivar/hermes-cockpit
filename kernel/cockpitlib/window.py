# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""When a standup note starts. The pack sets the hour and the working days."""

import datetime


def clock(value) -> tuple:
    """(hour, minute) of a pack time: a whole hour, or "HH:MM"."""
    from .errors import PackError

    text = str(value).strip()
    if isinstance(value, int) or text.isdigit():
        hour, minute = int(text), 0
    elif len(text) == 5 and text[2] == ":" and text[:2].isdigit() and text[3:].isdigit():
        hour, minute = int(text[:2]), int(text[3:])
    else:
        raise PackError(f"a time is a whole hour or HH:MM, not {value!r}")
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise PackError(f"a time is a whole hour or HH:MM, not {value!r}")
    return hour, minute


def pack_standup(pack) -> tuple:
    """The start of the standup window (hours.standup_window, else the standup time) and the working days."""
    from .errors import CockpitError

    hours = (pack or {}).get("hours") or {}
    value = hours.get("standup_window")
    if value is None:
        value = hours.get("standup")
    if value is None:
        raise CockpitError("pack has no standup hour")
    days = (pack or {}).get("working_days")
    if not days:
        raise CockpitError("pack has no working days")
    hour, minute = clock(value)
    return hour, tuple(int(day) for day in days), minute


def window_start(moment=None, *, hour: int, working=(0, 1, 2, 3, 4), minute: int = 0) -> datetime.datetime:
    """The last working day's start time, on the local wall clock. Monday starts on Friday.

    The walk back is on the wall clock, and the offset is that day's own: across a daylight-saving change, today's
    offset on an earlier day would move the start an hour (10:30 read as 11:30)."""
    local = (moment or datetime.datetime.now()).astimezone()
    wall = local.replace(tzinfo=None)
    days = set(working)
    cursor = wall.replace(hour=hour, minute=minute, second=0, microsecond=0)
    while cursor.weekday() not in days or cursor > wall:
        cursor = cursor - datetime.timedelta(days=1)
        cursor = cursor.replace(hour=hour, minute=minute, second=0, microsecond=0)
    return cursor.astimezone()
