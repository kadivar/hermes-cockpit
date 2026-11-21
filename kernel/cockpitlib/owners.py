# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tickets a plugin runs itself (a release supervisor's units), so cockpit's own watchers leave the follow-up to it.

A plugin rewrites its whole list on each of its passes; a list it stopped refreshing lapses, so a plugin that was
removed (or a release that ended) gives its tickets back by itself. With no plugin, no ticket is owned and every
watcher does what it always did."""

import json
import os
import time

from .store import dump_json

LAPSE_SECONDS = 3600


def _folder() -> str:
    from .paths import watch_dir

    return os.path.join(watch_dir(), "owners")


def own(plugin: str, tickets) -> int:
    """The tickets `plugin` runs now (the whole list). Returns how many."""
    name = "".join(ch for ch in str(plugin or "") if ch.isalnum() or ch in "-_")
    if not name:
        raise ValueError("a plugin name")
    listed = sorted({str(ticket).strip() for ticket in tickets or () if str(ticket).strip()})
    os.makedirs(_folder(), exist_ok=True)
    path = os.path.join(_folder(), f"{name}.json")
    dump_json(path, {"tickets": listed, "at": time.time()})
    return len(listed)


def owned(now=None) -> dict:
    """Every ticket a plugin runs now, and which plugin."""
    moment = time.time() if now is None else now
    folder = _folder()
    found = {}
    for name in sorted(os.listdir(folder)) if os.path.isdir(folder) else []:
        if not name.endswith(".json"):
            continue
        try:
            record = json.load(open(os.path.join(folder, name), encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if moment - float(record.get("at") or 0) > LAPSE_SECONDS:
            continue
        for ticket in record.get("tickets") or []:
            found.setdefault(ticket, name[: -len(".json")])
    return found


def owner_of(ticket: str, now=None) -> str:
    """The plugin that runs this ticket, or ''."""
    return owned(now).get(ticket, "")


def _prs_path(plugin: str) -> str:
    name = "".join(ch for ch in str(plugin or "") if ch.isalnum() or ch in "-_")
    if not name:
        raise ValueError("a plugin name")
    return os.path.join(_folder(), "prs", f"{name}.json")


def own_prs(plugin: str, prs) -> int:
    """The PRs of the tickets `plugin` runs, the whole list: [{ticket, repo, number, url, ready}]. Cockpit's PR watch
    follows them like its own, so a ticket gets its merge and its ticket-done ack; `ready` says the plugin is done with
    the PR and it waits for the human's merge."""
    listed = []
    for item in prs or ():
        try:
            listed.append(
                {
                    "ticket": str(item["ticket"]),
                    "repo": str(item["repo"]),
                    "number": int(item["number"]),
                    "url": str(item.get("url") or ""),
                    "ready": bool(item.get("ready")),
                }
            )
        except (KeyError, TypeError, ValueError):
            continue
    path = _prs_path(plugin)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    dump_json(path, {"prs": listed, "at": time.time()})
    return len(listed)


def registered_prs(now=None) -> list:
    """Every PR a plugin registered and still refreshes, with the plugin that did."""
    moment = time.time() if now is None else now
    folder = os.path.join(_folder(), "prs")
    found = []
    for name in sorted(os.listdir(folder)) if os.path.isdir(folder) else []:
        if not name.endswith(".json"):
            continue
        try:
            record = json.load(open(os.path.join(folder, name), encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if moment - float(record.get("at") or 0) > LAPSE_SECONDS:
            continue
        found += [
            {**item, "plugin": name[: -len(".json")]} for item in record.get("prs") or [] if isinstance(item, dict)
        ]
    return found
