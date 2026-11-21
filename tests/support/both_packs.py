# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""What the tests that run over both fixture packs share: the packs, a client of the routes, and stand-ins."""

import os
import re

from fastapi import FastAPI
from fastapi.testclient import TestClient

from cockpitlib.pack import load
from dashboard.cockpit.router import router

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


PACKS = (
    os.path.join(ROOT, "packs", "acme", "pack.yaml"),
    os.path.join(ROOT, "packs", "bravo", "pack.yaml"),
)


def _client():
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


# Each fixture's plugin adds its own card kind and kickoff mode, and the pack sends that mode to a seat of its choice.
PLUGIN_MODES = {
    "acme": ("ledger-view", "ledger-close", "{ticket}: ledger close", "ledger", "question", "reviewer"),
    "bravo": ("trace-tap", "trace-sample", "{ticket}: trace sample", "trace", "dev", "tester"),
}


def _plugged(pack_file, tmp_path) -> str:
    """A copy of the fixture whose plugin block registers the plugin's card kind and kickoff mode."""
    import shutil

    import yaml

    name = os.path.basename(os.path.dirname(pack_file))
    plugin, kind, title, flow, bucket, lane = PLUGIN_MODES[name]
    copied = tmp_path / "packs" / name
    shutil.copytree(os.path.dirname(pack_file), copied)
    raw = yaml.safe_load((copied / "pack.yaml").read_text(encoding="utf-8"))
    block = raw["plugins"][plugin]
    block["card_kinds"] = {kind: {"title": title, "flow": flow, "role": "analyst"}}
    block["kickoff_modes"] = {
        kind: {
            "lane_kind": "analyst",
            "capacity_bucket": bucket,
            "title_kind": kind,
            "preflight": [],
            "text": f"{plugin} starts {kind}",
            "label": f"{kind} → {lane}",
        }
    }
    raw["kickoff"] = {"lanes": {kind: lane}}
    (copied / "pack.yaml").write_text(yaml.safe_dump(raw, sort_keys=False, allow_unicode=True), encoding="utf-8")
    return str(copied / "pack.yaml")


def _other(pack):
    return load(PACKS[0] if pack["name"] == "bravo" else PACKS[1])


class _LyingForge:
    """A forge whose reads disagree with what was written: every read-back must refuse."""

    def __init__(self, pack, pr=None, labels=(), threads=(), answers=None):
        self.org = pack["forge"]["org"]
        self.dry_run = False
        self.writes = []
        self._pr = pr or {}
        self._labels = list(labels)
        self._threads = list(threads)
        self.answers = answers or {}

    def repo(self, name):
        return f"{self.org}/{name}"

    def url(self, repo, number=None):
        return f"https://github.com/{self.repo(repo)}" + (f"/pull/{number}" if number else "")

    def me(self):
        return "human"

    def pr(self, repo, number):
        return self._pr

    def labels(self, repo, number):
        return self._labels

    def threads(self, repo, number):
        return self._threads.pop(0) if len(self._threads) > 1 else self._threads[0]

    def checks(self, repo, sha):
        return []

    def get(self, path):
        for pattern, answer in self.answers.items():
            if re.search(pattern, path):
                return answer() if callable(answer) else answer
        return {}

    def write(self, method, path, body=None):
        self.writes.append((method, path))
        return self.answers.get(f"{method} {path}", {"id": 1, "number": 1, "html_url": "u"})

    def graphql(self, query, variables, write=False):
        self.writes.append(("GRAPHQL", query[:20]))
        return {}


def _thread_nodes(resolved=False, mine=False, extra=()):
    comments = [{"databaseId": 1, "url": "u", "author": {"login": "them"}}]
    if mine:
        comments.append({"databaseId": 2, "url": "u2", "author": {"login": "human"}})
    comments += [{"databaseId": 10 + index, "url": "u", "author": {"login": who}} for index, who in enumerate(extra)]
    return [{"id": "T1", "isResolved": resolved, "comments": {"nodes": comments}}]


def _notified():
    path = os.path.join(os.environ["COCKPIT_ROOT"], "notified.log")
    return open(path, encoding="utf-8").read() if os.path.isfile(path) else ""


def _parents(pack, card):
    import sqlite3

    from cockpitlib.kanban import db_path

    connection = sqlite3.connect(db_path(pack["board"]))
    found = [row[0] for row in connection.execute("select parent_id from task_links where child_id = ?", (card,))]
    connection.close()
    return found
