# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Every built-in forge passes the one conformance suite (tests/support/forge_conformance.py): GitHub through the stand-in `gh`,
and the local forge over its files and a bare repository."""

import os
import subprocess

import pytest

from cockpitlib import forges
from cockpitlib.pack import load
from tests.conftest import PACK
from tests.support import fake_gh
from tests.support.forge_conformance import CHECKS, World


def _commit(repo: str, branch: str) -> str:
    return fake_gh.commit(repo, branch, name=f"{branch.replace('/', '-')}.txt", text=f"{branch}\n")


class GitHubWorld(World):
    def __init__(self):
        self.pack = load(PACK)
        self.repo = self.pack["repos"]["repos"][0]["name"]
        self.forge = forges.make(self.pack)
        self.full = self.forge.repo(self.repo)
        fake_gh.setup(me=self.forge.human_login or "human", repos=[self.full])

    def dry(self):
        return forges.make(self.pack, dry_run=True)

    def branch(self, name: str) -> str:
        sha = _commit(self.repo, name)
        fake_gh.head(self.full, name, sha)
        data = fake_gh.state()
        fake_gh.repo(data, self.full).setdefault("compares", {})[f"{self.main()}...{sha}"] = {
            "total_commits": 1,
            "files": [{"filename": "one.txt"}],
        }
        fake_gh.save(data)
        return sha

    def draft(self, head: str) -> int:
        fake_gh.pull(self.full, 50, head, fake_gh.state()["heads"][f"{self.full}:{head}"], draft=True)
        return 50

    def their_thread(self, number: int, body: str) -> int:
        fake_gh.thread(self.full, number, 7001, "reviewer", body)
        return 7001

    def check(self, sha: str, name: str, conclusion: str) -> None:
        data = fake_gh.state()
        held = fake_gh.repo(data, self.full)["checks"].setdefault(sha, {"check_runs": [], "statuses": []})
        held["check_runs"].append({"name": name, "status": "completed", "conclusion": conclusion})
        fake_gh.save(data)


class LocalWorld(World):
    def __init__(self):
        pack = load(PACK)
        self.pack = {**pack, "forge": {**(pack.get("forge") or {}), "kind": "local"}}
        self.repo = pack["repos"]["repos"][0]["name"]
        self.forge = forges.make(self.pack)

    def dry(self):
        return forges.make(self.pack, dry_run=True)

    def branch(self, name: str) -> str:
        sha = _commit(self.repo, name)
        folder = os.path.join(os.environ["COCKPIT_ROOT"], "repos", self.repo)
        subprocess.run(
            ["git", "-C", folder, "push", "-q", self.forge.remote(self.repo), "main", name],
            check=True,
            capture_output=True,
        )
        return sha

    def draft(self, head: str) -> int:
        return self.forge.create_pr(self.repo, "A draft", "", head, "main", draft=True)["number"]

    def their_thread(self, number: int, body: str) -> int:
        made = self.forge.create_review(
            self.repo, number, "", [{"path": "src/a.txt", "line": 1, "side": "RIGHT", "body": body}], author="reviewer"
        )
        self.forge.submit_review(self.repo, number, made["id"], "COMMENT", "")
        return self.forge.review_comments(self.repo, number, made["id"])[0]["id"]

    def check(self, sha: str, name: str, conclusion: str) -> None:
        self.forge.seed_check(self.repo, sha, name, conclusion)


WORLDS = {"github": GitHubWorld, "local": LocalWorld}


def test_every_built_in_forge_has_a_world_here():
    assert set(WORLDS) == set(forges.KINDS)
    assert len(CHECKS) >= 12 and all(check.__name__.startswith("check_") for check in CHECKS)


@pytest.mark.parametrize("check", CHECKS, ids=lambda check: check.__name__[len("check_") :])
@pytest.mark.parametrize("kind", sorted(WORLDS))
def test_a_forge_passes_the_conformance_check(env, kind, check):
    world = WORLDS[kind]()
    assert world.forge.kind == kind
    check(world)
