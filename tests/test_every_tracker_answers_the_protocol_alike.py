# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Every built-in tracker passes the one conformance suite (tests/support/tracker_conformance.py): Jira's REST API through the
stand-in on a local port, the pack's command through the starter pack's example, the local tracker over its files, and
the issues of the pack's forge twice: over the GitHub stand-in and over the forge kept in files."""

import json
import os

import pytest

from cockpitlib import trackers
from tests.conftest import PACK, ROOT
from tests.support.tracker_conformance import CHECKS, World


class JiraWorld(World):
    first, then = "Backlog", "In Progress"

    def __init__(self, tmp_path, monkeypatch, request):
        from tests.support.fake_jira import Jira, serve

        self.jira = Jira()
        self.jira.stamps = True
        url, stop = serve(self.jira)
        request.addfinalizer(stop)
        monkeypatch.setenv("TRACKER_EMAIL", "human@example.test")
        monkeypatch.setenv("TRACKER_AUTH", "token-1")
        self.config = {
            "kind": "jira",
            "url": url,
            "project": self.project,
            "auth_env": ["TRACKER_EMAIL", "TRACKER_AUTH"],
        }
        self.tracker = trackers.make(self.config)

    def dry(self):
        return trackers.make(self.config, dry_run=True)

    def attached(self, key):
        return [row["filename"] for row in self.jira.issues[key]["attachments"]]


class CommandWorld(World):
    first, then = "To Do", "In Review"

    def __init__(self, tmp_path, monkeypatch, request):
        self.state = tmp_path / "starter-state"
        monkeypatch.setenv("COCKPIT_STARTER_STATE", str(self.state))
        self.config = {
            "kind": "command",
            "command": [os.path.join(ROOT, "starter", "bin", "tracker")],
            "reads": ["comments", "me", "status"],
            "url": "https://tracker.example.test",
            "project": self.project,
        }
        self.tracker = trackers.make(self.config)

    def dry(self):
        return trackers.make(self.config, dry_run=True)

    def attached(self, key):
        kept = json.loads((self.state / "tracker.json").read_text(encoding="utf-8"))
        return [os.path.basename(path) for row in kept[key]["comments"] for path in row["attach"]]


class LocalWorld(World):
    first, then = "To Do", "In Progress"

    def __init__(self, tmp_path, monkeypatch, request):
        self.config = {
            "kind": "local",
            "url": "",
            "project": self.project,
            "local": {"root": str(tmp_path / "tickets")},
        }
        self.tracker = trackers.make(self.config)

    def dry(self):
        return trackers.make(self.config, dry_run=True)

    def attached(self, key):
        return [row["name"] for row in self.tracker.attachments(key)]


class IssuesWorld(World):
    """Tickets as the issues of the first repo of the pack, on the forge the stand-in `gh` answers for."""

    first, then = "Open", "Closed"
    forge_kind = "github"

    def __init__(self, tmp_path, monkeypatch, request):
        from cockpitlib import tracker
        from cockpitlib.pack import load
        from tests.support import fake_gh

        pack = load(PACK)
        self.pack = {
            **pack,
            "forge": {**(pack.get("forge") or {}), "kind": self.forge_kind},
            "tracker": {"kind": "github-issues", "project": self.project},
        }
        self.config = tracker._config(self.pack)
        self.tracker = trackers.make(self.config, pack=self.pack)
        if self.forge_kind == "github":
            fake_gh.setup(me=self.tracker.forge.me(), repos=[self.tracker.forge.repo(self.tracker.repo)])

    def dry(self):
        return trackers.make(self.config, dry_run=True, pack=self.pack)

    def page_part(self, key):
        return f"/issues/{key.rsplit('-', 1)[1]}"

    def attached(self, key):
        raise AssertionError("an issue holds no file: the check is the refusal")


class LocalIssuesWorld(IssuesWorld):
    """The same over the forge kept in files: no network, no CLI."""

    forge_kind = "local"


WORLDS = {
    "jira": JiraWorld,
    "command": CommandWorld,
    "local": LocalWorld,
    "github-issues": IssuesWorld,
    "github-issues-local": LocalIssuesWorld,
}
KIND = {"github-issues-local": "github-issues"}  # a kind that has a second World: the same tracker over another forge


def test_every_built_in_tracker_has_a_world_here_or_is_jira_by_another_road():
    # the connector tracker is the REST tracker's own logic with each call made as a connector operation: its tests are
    # tests/test_tracker_connector.py, over the connector's operations
    assert {KIND.get(name, name) for name in WORLDS} | {"connector"} == set(trackers.KINDS)
    assert len(CHECKS) >= 8 and all(check.__name__.startswith("check_") for check in CHECKS)


@pytest.mark.parametrize("check", CHECKS, ids=lambda check: check.__name__[len("check_") :])
@pytest.mark.parametrize("kind", sorted(WORLDS))
def test_a_tracker_passes_the_conformance_check(bare, kind, check, tmp_path, monkeypatch, request):
    world = WORLDS[kind](tmp_path, monkeypatch, request)
    assert world.tracker.kind == KIND.get(kind, kind)
    check(world)
