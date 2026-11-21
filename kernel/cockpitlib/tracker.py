# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The pack's tracker: which one `tracker.kind` picks, a ticket's link, and the cache of ticket titles.

The protocol and its implementations live in `trackers/` (`base.py` the operations and capabilities, `jira.py` Jira's
REST API and Hermes's connector, `command.py` the pack's own command, `local.py` tickets in files, `github_issues.py`
the issues of the pack's forge). tracker.kind picks one: `connector` (the default), `jira` (`rest` is accepted as
another name for it), `command`, `local` or `github-issues`. This module
is what the rest of the kernel imports: the pack's tracker section read once (`_config`), the tracker made of it
(`tracker_for`), and the names code written before the package imported from here.

Every write is read back. A dry run reads (so what it prints carries real ids) and records the writes instead.
"""

import json
import os

from . import trackers
from .errors import CockpitError
from .store import dump_json
from .trackers.command import CommandTracker  # noqa: F401 - imported from here by code and tests from before the package
from .trackers.jira import MOVE_THROUGH_TRIES, ConnectorTracker, JiraTracker, adf, adf_count, adf_text  # noqa: F401 - the same


def _config(pack) -> dict:
    tracker = dict((pack or {}).get("tracker") or {})
    for field in ("url", "project"):
        tracker[field] = tracker.get(field) or ""  # a key written with no value is an absent key, never the text "None"
    tracker["url"] = str(tracker["url"]).rstrip("/")
    return tracker


def tracker_kind(config) -> str:
    """connector unless the pack says otherwise; a pack that only names its command keeps meaning the command."""
    return trackers.kind_of(config)


def _made(pack, config, *more):
    """The tracker of that section; one whose tickets live on the pack's forge is made with the pack as well."""
    if trackers.implementation(trackers.kind_of(config)).over_forge:
        return trackers.make(config, *more, pack=pack)
    return trackers.make(config, *more)


def tracker_for(pack, dry_run: bool = False):
    return _made(pack, _config(pack), dry_run)


def reader_for(pack):
    """The pack's tracker for a read, answering the protocol whatever `tracker_for` handed back."""
    return trackers.seam(tracker_for(pack), _config(pack))


def capabilities(pack) -> frozenset:
    """What the pack's tracker has, known without making one."""
    return trackers.offers(_config(pack))


def browse(pack, issue: str) -> str:
    """A ticket's page on the pack's tracker; empty when none can be built. A page spelled from the tracker's address
    by a pack that gives no address would be a path on no host (`/browse/TASK-100`): no link is better than that one."""
    config = _config(pack)
    try:
        said = _made(pack, config).browse_url(issue)
    except CockpitError:  # a tracker that cannot be made still has the page its settings spell
        said = trackers.link(config, issue)
    return "" if trackers.base.unspelled(config) and said == trackers.link(config, issue) else said


TITLES_FRESH = 6 * 3600


def titles(pack, tickets, refresh: bool = False, now=None) -> dict:
    """{ticket: title} from the cache; with refresh, the missing and stale ones are read from the tracker first. A
    tracker that cannot answer leaves the cache as it was."""
    import time

    from .paths import watch_dir

    moment = time.time() if now is None else now
    path = os.path.join(watch_dir(), "tracker-titles.json")
    try:
        kept = json.load(open(path, encoding="utf-8"))
    except (OSError, ValueError):
        kept = {}
    kept = kept if isinstance(kept, dict) else {}
    if refresh:
        reader = tracker_for(pack)
        changed = False
        for ticket in tickets:
            entry = kept.get(ticket) or {}
            if entry and moment - float(entry.get("at") or 0) < TITLES_FRESH:
                continue
            try:
                kept[ticket] = {"title": reader.summary(ticket), "at": moment}
            except CockpitError:
                continue
            changed = True
        if changed:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            dump_json(path, kept)
    return {ticket: (kept.get(ticket) or {}).get("title") or "" for ticket in tickets}
