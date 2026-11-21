# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Outside an automated editor session, slots and vaults stay closed."""

import os

from .paths import PLUGIN_ROOT, wt

MARKER_FILE = os.path.join(PLUGIN_ROOT, "kernel", "cockpitlib", "fence_markers.txt")


def markers() -> list:
    found = []
    if not os.path.isfile(MARKER_FILE):
        return found
    for line in open(MARKER_FILE, encoding="utf-8"):
        text = line.strip()
        if text and not text.startswith("#"):
            found.append(text)
    return found


def outside(env=None, cwd=None, worktrees=None) -> bool:
    env = os.environ if env is None else env
    cwd = os.path.realpath(cwd or os.getcwd())
    worktrees = os.path.realpath(worktrees or wt())
    if env.get("COCKPIT_LANE") or env.get("COCKPIT_HUMAN") == "1":
        return False
    if not any(env.get(name) for name in markers()):
        return False
    prefix = worktrees + os.sep
    return not (cwd + os.sep).startswith(prefix) and cwd != worktrees


# What an editor agent outside the lanes may not run: the slots, the vaults, and the pipeline's own writes.
GUARDED = (
    r"\bcockpit\s+(slot|vault|session|publish|apply|setup|outbox\s+(endorse|hold|drop))\b",
    r"\bhermes\b[^|;&]*\bvault\b",
)


def _lane_accounts(pack) -> list:
    """The identifiers the lanes log in with: shared logins and the accounts manifest."""
    from .accounts import manifest

    found = [
        str(row.get("email") or "")
        for row in ((pack or {}).get("logins") or {}).get("shared") or []
        if isinstance(row, dict)
    ]
    found += [row["identifier"] for row in manifest(pack)["accounts"]]
    return [item for item in found if item]


def guard_reason(command: str, pack=None) -> str:
    """Why an editor agent outside the lanes may not run this, or ''."""
    import re

    from .egress import _secret_read
    from .paths import volumes

    text = str(command or "")
    if not text.strip():
        return ""
    for pattern in GUARDED:
        if re.search(pattern, text):
            return "outside the lanes: slots, vaults, and publishing belong to the lanes and the human"
    if _secret_read(text) or os.path.realpath(volumes()) in text:
        return "outside the lanes: the slots and the vaults stay closed"
    for account in _lane_accounts(pack):
        if account in text:
            return f"outside the lanes: {account} is a lane's account"
    return ""


def refuse_outside() -> None:
    """The vault's entry points refuse an editor session outside the lanes."""
    from .errors import CockpitError

    if outside():
        raise CockpitError("outside the lanes: the vaults stay closed")
