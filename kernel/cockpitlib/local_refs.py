# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tracker bodies must not name files that exist only on this machine."""

import os
import re

PATTERNS = (
    (re.compile(r"(?:^|[\s`(])qa/", re.M), "a qa path"),
    (re.compile(r"(?:^|[\s`(])outbox/", re.M), "an outbox path"),
    (re.compile(r"\bwt/"), "a worktree path"),
    (re.compile(r"file://"), "a file URL"),
    (re.compile(r"\blocalhost\b|\b127\.0\.0\.1\b|\[::1\]|(?:^|[\s`(])::1\b"), "a loopback host"),
    (re.compile(r"/home/|/Users/|(?:^|[\s`(])~/"), "a home path"),
    (re.compile(r"(?:^|[\s`('\"])/(?:private/)?tmp/", re.M), "a temp path"),
)


def _bound_pack():
    from .errors import NeedMigrate, PackError
    from .pack import load
    from .paths import pack_path

    try:
        return load(pack_path())
    except (PackError, NeedMigrate, FileNotFoundError):
        return {}


def _pack_patterns(pack) -> list:
    """The pack's own local domains, the records folder, and this machine's slot and worktree folders."""
    from .paths import records_name, volumes, wt

    found = []
    for domain in ((pack or {}).get("egress") or {}).get("local_domains") or []:
        found.append((re.compile(domain), "a local domain"))
    found.append((re.compile(r"(?:^|[\s`(])" + re.escape(records_name().rstrip("/")) + "/", re.M), "a records path"))
    for folder, reason in ((volumes(), "a slot path"), (wt(), "a worktree path")):
        if folder:
            found.append((re.compile(re.escape(os.path.realpath(folder))), reason))
    return found


def find_local_refs(text: str, pack=None) -> list:
    """Every kind of local reference in the text. Without a pack, the bound pack's local domains count."""
    if not text:
        return []
    patterns = list(PATTERNS) + _pack_patterns(pack if pack is not None else _bound_pack())
    found = []
    for pattern, reason in patterns:
        if pattern.search(text) and reason not in found:
            found.append(reason)
    return found
