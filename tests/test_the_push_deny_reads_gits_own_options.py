# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The kernel's push deny reads git's argv: an option between `git` and the verb (-C, -c, --git-dir, --work-tree,
--no-pager …), a wrapper, or an inner shell line does not carry a push past it. What was refused stays refused and a
read stays a read, for a seat that writes, a seat that only reads, and the human."""

import os

import pytest

from cockpitlib import egress

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PACKS = (os.path.join(ROOT, "packs", "acme", "pack.yaml"), os.path.join(ROOT, "packs", "bravo", "pack.yaml"))
SEATS = ("worker-1", "reviewer", "")  # a seat that writes, a seat that only reads, the human

BEHIND_OPTIONS = (
    "git -C /work/api push origin work/TASK-100",
    "git -C /work/api push",
    "git -C /work/a -C b push --force",
    "git -c user.name=x push origin main",
    "git -c core.sshCommand=ssh -C /work/api push",
    "git --git-dir=/work/api/.git push origin main",
    "git --git-dir /work/api/.git --work-tree /work/api push",
    "git --work-tree=/work/api push",
    "git --no-pager push origin main",
    "git -p push",
    "git --namespace x push",
    "git --exec-path=/opt/git push",
    "git --no-optional-locks -C /work/api push -u origin HEAD",
    "cd /work/api && git -C . push",
    "true; git -C /work/api push",
    "sudo git -C /work/api push",
    "env GIT_SSH=x git -C /work/api push",
    "GIT_TRACE=1 git -C /work/api push",
    "/usr/bin/git -C /work/api push",
    "sh -c 'git -C /work/api push'",
    'bash -lc "git -C /work/api push origin main"',
    "echo $(git -C /work/api push)",
    "if git -C /work/api push; then echo ok; fi",
    "git -C '/work/my api' push",
)
ALREADY_REFUSED = (
    "git push",
    "git push origin main",
    "git  push --force",
    "cd /work/api && git push",
    "git remote add x https://forge.example.test/x.git",
    "git config remote.origin.pushurl https://forge.example.test/x.git",
    "git commit --no-verify -m x",
    "gh pr create --title x",
    "echo git push",
)
READS = (
    "git -C /work/api status",
    "git -C /work/api log --oneline origin/main..HEAD",
    "git -C /work/api log --grep push",
    "git -C /work/api diff --stat",
    "git --no-pager -C /work/api show HEAD",
    "git -c color.ui=never -C /work/api branch --show-current",
    "git --git-dir=/work/api/.git rev-parse HEAD",
    "git -C /work/api stash push -m wip",
    "git -C /work/api stash list",
    "git -C /work/api fetch origin",
    "git -C /work/api ls-remote origin",
    "git status",
    "git log -1 --format=%s",
    "git help push",
    "ls /work/api/push",
    "cat docs/push-notes.md",
    "grep -n pushed notes.md",
    "python3 scripts/pushover.py",
)


@pytest.mark.parametrize("command", BEHIND_OPTIONS)
def test_a_push_behind_gits_own_options_is_refused(command):
    assert egress.check(command) == "blocked"
    assert "a denied command" in egress.explained("blocked") and "push" in egress.explained("blocked")


@pytest.mark.parametrize("command", ALREADY_REFUSED)
def test_what_the_kernel_refused_before_is_still_refused(command):
    assert egress.check(command) == "blocked"


@pytest.mark.parametrize("command", READS)
def test_a_read_through_gits_own_options_is_still_a_read(command):
    assert egress.check(command) == ""


def test_a_line_the_fence_cannot_read_is_a_push_when_it_names_git_and_push():
    assert egress.check("git -C /work/api push origin 'main") == "blocked"
    assert egress.check("git -C /work/api status 'main") == ""  # unreadable, and no push in it: as before
    assert egress.check("echo 'unbalanced") == ""
    assert egress.check(None) == "unreadable tool call"


@pytest.mark.parametrize("pack_file", PACKS)
@pytest.mark.parametrize("lane", SEATS)
def test_every_seat_and_the_human_get_the_same_answer_as_for_a_plain_push(env, pack_file, monkeypatch, lane):
    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    if lane:
        monkeypatch.setenv("COCKPIT_LANE", lane)
    else:
        monkeypatch.delenv("COCKPIT_LANE", raising=False)
    plain = egress.check_bound("git push origin work/TASK-100")
    assert plain == "blocked"
    for command in BEHIND_OPTIONS:
        assert egress.check_bound(command) == plain, command
    assert egress.check_tool("terminal", {"command": "git -C /work/api push origin work/TASK-100"}) != ""
    for command in (
        "git -C /work/api status",
        "git --no-pager -C /work/api log --oneline -3",
        "git -C /work/api stash list",
    ):
        assert egress.check_bound(command) == egress.check_bound("git status"), command
