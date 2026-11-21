# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Write a watcher's record only when it says something new, and keep the watcher's own bookkeeping out of it.

The CI and PR watchers read the forge on a timer and used to rewrite every record each pass just to move `last_check`.
A record rewritten every minute is never quiet, so `workspace-watch` could not commit a ticket's records, and when it
did the commit was a timestamp. Now a record is written only when a fact in it changed (`last_check` alone is not one),
and when each record was last read, with the forge's ETag for that read, lives in a per-machine file under the
records' `watch/` folder, which `workspace-watch` never commits. The readers merge that time back in as `last_check`,
so the page's "checked N ago" stays honest.
"""

import json
import os

from .store import dump_json
from .time_util import iso, stamp

IGNORED = ("last_check",)


def _plain(data) -> dict:
    return json.loads(json.dumps(data))


def unchanged(path: str, data: dict) -> bool:
    """True when the file already holds `data`, `last_check` aside."""
    try:
        old = json.load(open(path, encoding="utf-8"))
    except (OSError, ValueError):
        return False
    if not isinstance(old, dict) or not isinstance(data, dict):
        return False
    new = _plain(data)
    return {k: v for k, v in old.items() if k not in IGNORED} == {k: v for k, v in new.items() if k not in IGNORED}


def write_record(path: str, data: dict) -> bool:
    """Write `data` as JSON unless the file already says the same. Returns whether it wrote."""
    if unchanged(path, data):
        return False
    _dump(path, data)
    return True


def _dump(path: str, data) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    dump_json(path, data, indent=1)


def _checks_path(kind: str) -> str:
    from .paths import watch_dir

    return os.path.join(watch_dir(), f"{kind}-checked.json")


def _key(path: str) -> str:
    from .paths import records

    return os.path.relpath(path, records())


def _load(kind: str) -> dict:
    try:
        data = json.load(open(_checks_path(kind), encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


class Checks:
    """When one watcher last read each record from the forge, and the ETag of that read. Saved once per pass."""

    def __init__(self, kind: str):
        self.kind = kind
        self.data = _load(kind)

    def get(self, path: str) -> dict:
        found = self.data.get(_key(path))
        return found if isinstance(found, dict) else {}

    def mark(self, path: str, etag=None) -> None:
        row = {**self.get(path), "at": iso()}
        if etag is not None:
            row["etag"] = etag
        self.data[_key(path)] = row

    def at(self, path: str, record: dict) -> float:
        """Epoch of the newest read: this file's, or the record's own `last_check` (one written before this file)."""
        return max(stamp(self.get(path).get("at")), stamp(record.get("last_check")))

    def save(self) -> None:
        _dump(_checks_path(self.kind), self.data)


def with_checked(kind: str, path: str, record: dict) -> dict:
    """The record as the page shows it: `last_check` is its newest read, from the checks file when that is newer."""
    if not record:
        return record
    seen = _load(kind).get(_key(path))
    at = seen.get("at") if isinstance(seen, dict) else ""
    if at and stamp(at) > stamp(record.get("last_check")):
        return {**record, "last_check": at}
    return record
