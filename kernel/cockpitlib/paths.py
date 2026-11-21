# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Workspace paths. Records live under the workspace hermes/ directory.

~/.hermes is the installation: seats, crons, the vault, and vault backups.
"""

import os

PLUGIN_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def hermes_home() -> str:
    return os.path.realpath(os.environ.get("COCKPIT_HERMES_HOME") or os.path.expanduser("~/.hermes"))


def binding_file() -> str:
    return os.path.join(hermes_home(), "cockpit.yaml")


_BINDING = {}  # path -> ((mtime_ns, size), what the file said): the file is read again only when it changed


def load_binding():
    """The binding file as a dict. Every path of the records goes through it, thousands of times while one Outbox list
    is built, so an unchanged file is parsed once; a caller gets its own copy."""
    path = binding_file()
    try:
        seen = os.stat(path)
    except OSError:
        return {}
    stamp = (seen.st_mtime_ns, seen.st_size)
    kept = _BINDING.get(path)
    if kept is None or kept[0] != stamp:
        import yaml

        data = yaml.safe_load(open(path)) or {}
        kept = _BINDING[path] = (stamp, data if isinstance(data, dict) else {})
    return dict(kept[1])


def workspace() -> str:
    env = os.environ.get("COCKPIT_WORKSPACE")
    if env:
        return os.path.realpath(env)
    bound = load_binding().get("workspace")
    if bound:
        return os.path.realpath(bound)
    from .errors import NeedMigrate

    raise NeedMigrate()


def root() -> str:
    env = os.environ.get("COCKPIT_ROOT")
    if env:
        return os.path.realpath(env)
    return os.path.dirname(workspace())


def pack_path() -> str:
    env = os.environ.get("COCKPIT_PACK")
    if env:
        return os.path.realpath(env)
    bound = load_binding().get("pack")
    if bound:
        return os.path.realpath(bound)
    return os.path.join(workspace(), "cockpit-pack", "pack.yaml")


def wt() -> str:
    return os.environ.get("COCKPIT_WT") or os.path.join(root(), "wt")


def volumes() -> str:
    return os.environ.get("COCKPIT_VOLUMES") or os.path.join(root(), "volumes")


DEFAULT_RECORDS = "hermes"
_RECORDS = {"key": None, "name": DEFAULT_RECORDS}


def records_name() -> str:
    """The workspace folder the pack names for records (records_dir), or hermes.

    Read straight from the bound pack.yaml, so a path lookup needs no loaded pack. pack.load validates the value.
    The file is parsed once per version of it (path, size, mtime) and of the personal values beside it: every record
    path goes through here, and a page that lists hundreds of intents asked for it thousands of times.
    """
    from . import pack_local
    from .errors import NeedMigrate

    try:
        path = pack_path()
    except NeedMigrate:
        return DEFAULT_RECORDS
    try:
        stat = os.stat(path)
    except OSError:
        return DEFAULT_RECORDS
    real = pack_local.real(path, stat)
    key = (path, stat.st_size, stat.st_mtime_ns, pack_local.stamp(os.path.dirname(real)))
    if _RECORDS["key"] == key:
        return _RECORDS["name"]
    data = pack_local.early(real) or {}
    value = data.get("records_dir") if isinstance(data, dict) else None
    if not isinstance(value, str) or not value.strip() or os.path.isabs(value) or ".." in value.split("/"):
        name = DEFAULT_RECORDS
    else:
        name = os.path.normpath(value.strip())
    _RECORDS["key"] = key
    _RECORDS["name"] = name
    return name


def records() -> str:
    """Records live here. Moving an older layout in is a migration step, not something a lookup does."""
    return os.path.join(workspace(), records_name())


def outbox() -> str:
    return os.path.join(records(), "outbox")


def qa() -> str:
    return os.path.join(records(), "qa")


def watch_dir() -> str:
    return os.path.join(records(), "watch")


def platform_dir() -> str:
    return os.path.join(records(), "platform")


def chat_dir() -> str:
    return os.path.join(records(), "chat")


def segment(name, what: str = "name") -> str:
    """A name that is one path segment. An empty name, a dot name, or one with a separator or a NUL is refused: joined
    to a folder it would name another place."""
    from .errors import CockpitError

    text = name if isinstance(name, str) else ""
    if not text or text in (".", "..") or any(mark in text for mark in ("/", "\\", "\x00")):
        raise CockpitError(f"bad {what} {name!r}")
    return text


def inside(root: str, *names, what: str = "name") -> str:
    """The path of those names under the root, each one segment. A path that a link takes out of the root is refused."""
    from .errors import CockpitError

    path = os.path.join(root, *[segment(name, what) for name in names])
    if not os.path.realpath(path).startswith(os.path.realpath(root) + os.sep):
        raise CockpitError(f"bad {what} {names[-1]!r}: it leads outside {root}")
    return path


def within(root: str, relative, what: str = "name") -> str:
    """That relative path under the root (a repository may be named group/name). One that is absolute, holds a NUL, or
    climbs or is linked out of the root is refused."""
    from .errors import CockpitError

    text = relative if isinstance(relative, str) else ""
    path = os.path.join(root, text)
    if (
        not text
        or "\x00" in text
        or os.path.isabs(text)
        or not os.path.realpath(path).startswith(os.path.realpath(root) + os.sep)
    ):
        raise CockpitError(f"bad {what} {relative!r}")
    return path


def _of(root: str, key, parts, what: str) -> str:
    """The one checked way from a key to its place under a root: the key is one path segment, its folder is not a link
    that leaves the root, and what is joined below it stays below it. No key at all ("" or None) is the root's own
    level, where the records that belong to no ticket live; it is never a way to another folder."""
    from .errors import CockpitError

    if key in ("", None):
        folder = root
    else:
        folder = os.path.join(root, segment(key, what))
        if os.path.islink(folder) and not os.path.realpath(folder).startswith(os.path.realpath(root) + os.sep):
            raise CockpitError(f"bad {what} {key!r}: it leads outside {root}")
    if not parts:
        return folder
    path = os.path.join(folder, *[str(part) for part in parts])
    if any("\x00" in str(part) for part in parts) or not (os.path.normpath(path) + os.sep).startswith(
        os.path.normpath(folder) + os.sep
    ):
        raise CockpitError(f"bad path {os.path.join(*[str(part) for part in parts])!r} under {what} {key!r}")
    return path


def qa_of(ticket, *parts) -> str:
    """The ticket's records folder, or a path under it. Every path built from a ticket key goes through here."""
    return _of(qa(), ticket, parts, "ticket")


def outbox_of(ticket, *parts) -> str:
    """The ticket's outbox folder, or a path under it (also the outbox's own files, by name)."""
    return _of(outbox(), ticket, parts, "ticket")


def worktree_of(ticket, repo: str = "") -> str:
    """The ticket's checkouts folder, or its checkout of one repository (which may be named group/name)."""
    return _of(wt(), ticket, [repo] if repo else [], "ticket")


def receipt_log() -> str:
    return os.path.join(outbox(), "_published.log")
