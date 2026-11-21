# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""A lane's own coding-tool session (providers.coding.lane_transcript_glob), found by card and read as Live entries.

The coding tool's lines carry no time. A line gets one the first time cockpit reads it: the lines already there when
a transcript is first read are spread between the card's start and the file's last write, and a line that appears
later takes the moment it was read. Kept in this process only."""

import glob
import os
import re
import threading
import time

from .activity import _stamp
from .chat import _lane_glob, card_slug, coding_tail

RECENT_DAYS = 7
_SEEN = {}
_LOCK = threading.Lock()


def _matcher():
    """(regex naming the card part of a transcript path, whether that part is the slug), or (None, False)."""
    template = _lane_glob()
    key = "{card_slug}" if "{card_slug}" in template else "{card}" if "{card}" in template else ""
    if not key:
        return None, False
    head, tail = template.split(key, 1)
    part = lambda text: re.escape(text).replace(r"\*", "[^/]*").replace(r"\?", "[^/]")
    return re.compile("^" + part(head) + "(?P<card>[^/]+?)" + part(tail) + "$"), key == "{card_slug}"


def by_card(cards) -> dict:
    """Card id -> the newest transcript of its run, from one glob over every lane's transcripts."""
    pattern, slugged = _matcher()
    if pattern is None:
        return {}
    named = {(card_slug(card["id"]) if slugged else card["id"]): card["id"] for card in cards}
    oldest = time.time() - RECENT_DAYS * 86400
    found = {}
    for path in glob.glob(_lane_glob().replace("{card_slug}", "*").replace("{card}", "*")):
        match = pattern.match(path)
        card = named.get(match.group("card")) if match else None
        try:
            mtime = os.path.getmtime(path)
        except OSError:
            continue
        if card and mtime >= oldest and mtime > found.get(card, ("", 0))[1]:
            found[card] = (path, mtime)
    return {card: path for card, (path, _mtime) in found.items()}


def entries(path: str, card: dict) -> list:
    """Every entry of the transcript so far, each with the time cockpit gave it."""
    with _LOCK:
        seen = _SEEN.setdefault(path, {"offset": 0, "entries": []})
        read = coding_tail(path, seen["offset"])
        fresh = read["entries"]
        if fresh:
            if not seen["entries"]:
                start = float(card.get("created_at") or 0) or os.path.getmtime(path)
                end = max(start, os.path.getmtime(path))
                stamps = [_stamp(start + (end - start) * (index + 1) / len(fresh)) for index in range(len(fresh))]
            else:
                stamps = [_stamp(time.time())] * len(fresh)
            seen["entries"] += [{**entry, "ts": stamp} for entry, stamp in zip(fresh, stamps)]
        seen["offset"] = read["offset"]
        return list(seen["entries"])


def _forget_old() -> None:
    """Drop what was read of a transcript gone from disk or past RECENT_DAYS: no page lists it any more."""
    oldest = time.time() - RECENT_DAYS * 86400
    with _LOCK:
        for path in list(_SEEN):
            try:
                if os.path.getmtime(path) >= oldest:
                    continue
            except OSError:
                pass
            del _SEEN[path]


def job_rows(cards, since: str = "") -> list:
    """The lanes' session lines for these cards after `since`, as job-stream rows."""
    rows = []
    _forget_old()
    for card_id, path in by_card(cards).items():
        card = next(item for item in cards if item["id"] == card_id)
        for entry in entries(path, card):
            if entry["ts"] > (since or "") and entry.get("kind") in ("prompt", "text", "tool_use", "result"):
                rows.append(
                    {
                        **entry,
                        "src": "hermes",
                        "who": card.get("assignee") or "",
                        "card": card_id,
                        "ticket": card.get("ticket") or "",
                    }
                )
    return rows


def sessions(cards) -> list:
    """The lanes' sessions as coding-tool rows: the card's title stands for the first prompt."""
    rows = []
    for card_id, path in by_card(cards).items():
        card = next(item for item in cards if item["id"] == card_id)
        folder = os.path.join(os.path.dirname(path), "subagents")
        subs = [
            {"name": os.path.splitext(os.path.basename(item))[0], "path": item, "mtime": int(os.path.getmtime(item))}
            for item in sorted(glob.glob(os.path.join(folder, "*.jsonl")))
        ]
        rows.append(
            {
                "id": os.path.splitext(os.path.basename(path))[0],
                "running": card.get("status") == "running",
                "ticket": card.get("ticket") or "",
                "dir": os.path.dirname(path),
                "prompt": f"{card.get('assignee') or 'lane'} · {card.get('title') or card_id}",
                "mtime": int(os.path.getmtime(path)),
                "path": path,
                "subagents": subs,
                "card": card_id,
            }
        )
    return rows
