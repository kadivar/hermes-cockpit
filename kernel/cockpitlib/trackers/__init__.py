# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The trackers a pack can write to, by `tracker.kind`. Each is one implementation of the protocol in `base`.

`make` is what `tracker.tracker_for` returns. `seam` is for code that is handed a tracker: it gives back the tracker
itself, or the reads of an object from before the protocol. `offers` says what a pack's tracker has before one is made,
so an intent it cannot publish is refused when it is written.
"""

from ..errors import PackError
from .base import Tracker, Unsupported, link, missing, needs  # noqa: F401 - the protocol's names, for the code that uses a tracker

DEFAULT = "connector"
KINDS = {
    "jira": ("jira", "JiraTracker"),
    "connector": ("jira", "ConnectorTracker"),
    "command": ("command", "CommandTracker"),
    "local": ("local", "LocalTracker"),
    "github-issues": ("github_issues", "GitHubIssuesTracker"),
}
NAMES = ("connector", *[name for name in KINDS if name != "connector"])  # every kind a pack may write


def kind_of(config) -> str:
    """The tracker kind of that tracker section: connector unless it says otherwise; one that only names its command means the command."""
    return config.get("kind") or ("command" if config.get("command") else DEFAULT)


def implementation(kind: str):
    """The class that answers for that kind."""
    if kind not in KINDS:
        raise PackError(f"tracker.kind is one of {', '.join(NAMES)}")
    import importlib

    module, name = KINDS[kind]
    return getattr(importlib.import_module(f"{__name__}.{module}"), name)


def make(config, dry_run: bool = False, pack=None) -> Tracker:
    """The tracker of that tracker section, as the human; one whose tickets live on the pack's forge is handed the pack too."""
    made = implementation(kind_of(config))
    return made(config, dry_run, pack=pack) if made.over_forge else made(config, dry_run)


def offers(config) -> frozenset:
    """The capabilities the tracker of that tracker section has: read off its kind and settings, with nothing made or run."""
    return implementation(kind_of(config)).offers(config)


def seam(tracker, config=None):
    """A tracker that answers the protocol: the one given, or the reads of an older object that answers REST paths."""
    if tracker is None or isinstance(tracker, Tracker):
        return tracker
    from .base import Wrapped

    return Wrapped(tracker, config)


def has(tracker, capability: str) -> bool:
    """Whether a tracker, or an object from before the protocol, has that capability."""
    return capability in seam(tracker).capabilities()
