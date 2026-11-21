# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The kernel's denies for a changed remote and for the git settings that redirect or disguise a push read git's argv,
as the push deny does: an option between `git` and the verb, a wrapper or an inner shell line carries none of them past
the fence. Listing remotes and reading settings behind the same options stays a read."""

import pytest

from cockpitlib import egress
from tests.support.both_packs import PACKS

SEATS = ("worker-1", "reviewer", "")  # a seat that writes, a seat that only reads, the human

REMOTE_CHANGES = (
    "git -C /work/api remote add mirror https://forge.example.test/x.git",
    "git -C /work/api remote set-url origin https://forge.example.test/x.git",
    "git -C /work/api remote set-url --push origin https://forge.example.test/x.git",
    "git -C /work/api remote rename origin old",
    "git -C /work/api remote remove origin",
    "git -C /work/api remote rm origin",
    "git --git-dir=/work/api/.git remote add mirror https://forge.example.test/x.git",
    "git --no-pager -C /work/api remote -v add mirror https://forge.example.test/x.git",
    "sudo git -C /work/api remote add mirror https://forge.example.test/x.git",
    "sh -c 'git -C /work/api remote set-url origin https://forge.example.test/x.git'",
    "echo $(git -C /work/api remote remove origin)",
    "cd /work/api && git -c user.name=x remote add mirror https://forge.example.test/x.git",
)
CONFIG_WRITES = (
    "git -C /work/api config remote.origin.pushurl https://forge.example.test/x.git",
    "git -C /work/api config --worktree --unset remote.origin.pushurl",
    "git -C /work/api config --add remote.origin.pushurl https://forge.example.test/x.git",
    "git -C /work/api config --replace-all remote.origin.pushurl https://forge.example.test/x.git",
    "git -C /work/api config --unset-all remote.origin.pushurl",
    "git -C /work/api config remote.origin.url https://forge.example.test/x.git",
    "git -C /work/api config url.https://forge.example.test/.insteadOf https://example.test/",
    "git config --global url.ssh://git@forge.example.test/.pushInsteadOf https://example.test/",
    "git config --global --add url.https://forge.example.test/.insteadof https://example.test/",
    "git config core.sshCommand 'ssh -i /tmp/key'",
    "git -C /work/api config --local core.sshcommand ssh",
    "git config alias.p push",
    "git config --global alias.sync '!git push origin HEAD'",
    "git -C /work/api config --unset alias.p",
    "git -C /work/api config core.hooksPath /dev/null",
    "git -C /work/api config set remote.origin.pushurl https://forge.example.test/x.git",
    "git -C /work/api config unset remote.origin.pushurl",
    "git config set --global alias.p push",
    "git -C /work/api config --file .git/config alias.p push",
    "git -C /work/api config --rename-section remote.origin remote.old",
    "git config --remove-section alias",
    "git -C /work/api config --edit",
    "git config -e",
    "sudo git -C /work/api config alias.p push",
    'bash -lc "git -C /work/api config alias.p push"',
)
ON_THE_COMMAND_LINE = (
    "git -c alias.p=push p origin main",
    "git -c alias.p=push -C /work/api p",
    "git -C /work/api -c 'alias.sync=!git push' sync",
    "git --config-env=alias.p=PUSHED p",
    "git --config-env alias.p=PUSHED p origin",
    "git -c url.https://forge.example.test/.insteadOf=https://example.test/ push",
    "git -c core.sshCommand=ssh send-pack origin HEAD",
    "git -C /work/api send-pack origin HEAD:refs/heads/main",
)
ALREADY_REFUSED = (
    "git remote add mirror https://forge.example.test/x.git",
    "git remote set-url origin https://forge.example.test/x.git",
    "git remote -v",
    "git config remote.origin.pushurl https://forge.example.test/x.git",
    "git config core.hooksPath /dev/null",
    "git -c core.hooksPath=/dev/null commit -m x",
)
READS = (
    "git -C /work/api remote -v",
    "git -C /work/api remote",
    "git -C /work/api remote show origin",
    "git -C /work/api remote get-url origin",
    "git -C /work/api remote get-url --push origin",
    "git --no-pager -C /work/api remote --verbose",
    "git -C /work/api remote update",
    "git -C /work/api config --get remote.origin.pushurl",
    "git -C /work/api config --get-all remote.origin.url",
    "git -C /work/api config --get-regexp '^alias\\.'",
    "git -C /work/api config --list",
    "git config -l",
    "git config --global --list --show-origin",
    "git -C /work/api config get remote.origin.url",
    "git -C /work/api config list",
    "git -C /work/api config remote.origin.url",
    "git -C /work/api config alias.p",
    "git config user.name",
    "git -C /work/api config user.name 'A Lane'",
    "git -C /work/api config --local user.email lane@example.test",
    "git config --global core.autocrlf input",
    "git -C /work/api config --unset user.name",
    "git -c color.ui=never -C /work/api status",
    "git -c user.name=x -C /work/api commit -m 'TASK-100: the fix'",
    "git -c core.sshCommand=ssh -C /work/api fetch origin",
    "git -C /work/api log --grep 'remote add'",
    "git -C /work/api show HEAD:docs/alias.push.md",
    "cat docs/remote-add.md",
    "grep -rn pushurl docs",
)


@pytest.mark.parametrize("command", REMOTE_CHANGES)
def test_a_changed_remote_behind_gits_own_options_is_refused(command):
    assert egress.check(command) == "blocked"
    assert "remote" in egress.explained("blocked")


@pytest.mark.parametrize("command", CONFIG_WRITES)
def test_a_setting_that_redirects_or_disguises_a_push_is_not_written_behind_gits_own_options(command):
    assert egress.check(command) == "blocked"
    assert "a denied command" in egress.explained("blocked")


@pytest.mark.parametrize("command", ON_THE_COMMAND_LINE)
def test_an_alias_or_a_plumbing_push_on_the_command_line_is_refused(command):
    assert egress.check(command) == "blocked"


@pytest.mark.parametrize("command", ALREADY_REFUSED)
def test_what_the_kernel_refused_with_the_words_adjacent_is_still_refused(command):
    assert egress.check(command) == "blocked"


@pytest.mark.parametrize("command", READS)
def test_listing_remotes_and_reading_settings_stays_a_read(command):
    assert egress.check(command) == ""


def test_a_line_the_fence_cannot_read_is_a_change_when_it_names_git_and_the_change():
    assert egress.check("git -C /work/api remote add mirror 'x") == "blocked"
    assert egress.check("git -C /work/api config alias.p 'push") == "blocked"
    assert egress.check("git -C /work/api config --unset remote.origin.pushurl 'x") == "blocked"
    assert egress.check("git -C /work/api config user.name 'A Lane") == ""
    assert egress.check("git -C /work/api status 'x") == ""


@pytest.mark.parametrize("pack_file", PACKS)
@pytest.mark.parametrize("lane", SEATS)
def test_every_seat_and_the_human_get_the_refusal(env, pack_file, monkeypatch, lane):
    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    if lane:
        monkeypatch.setenv("COCKPIT_LANE", lane)
    else:
        monkeypatch.delenv("COCKPIT_LANE", raising=False)
    for command in REMOTE_CHANGES + CONFIG_WRITES + ON_THE_COMMAND_LINE:
        assert egress.check_bound(command) == "blocked", command
    for command in (
        "git -C /work/api remote -v",
        "git -C /work/api config --get remote.origin.url",
        "git -C /work/api config --list",
    ):
        assert egress.check_bound(command) == egress.check_bound("git status"), command
