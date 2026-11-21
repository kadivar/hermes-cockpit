# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""A pack's `allowed.reads` exempts a command line from the pack's own denies and from nothing the kernel refuses: the
kernel's deny list, the forge command line's write rules, the push that hides behind git's options, a commit that skips
its hooks and an HTTP write to the forge are judged first, whatever the pack lists. Doctor names an entry a kernel deny
matches as a security error."""

import pytest

from cockpitlib import doctor, egress
from cockpitlib.pack import load, policy
from tests.support.both_packs import PACKS

SEATS = ("worker-1", "reviewer", "")  # a seat that writes, a seat that only reads, the human
KERNEL_REFUSED = (
    "git push origin main",
    "git push",
    "git -C /work/api push origin work/TASK-100",
    "sh -c 'git -C /work/api push'",
    "git remote add mirror https://forge.example.test/x.git",
    "git config remote.origin.pushurl https://forge.example.test/x.git",
    "git commit --no-verify -m x",
    "git commit -n -m x",
    "gh pr create --title x",
    "gh pr merge 7 --squash",
    "gh api repos/example/api/pulls/7 -X PATCH -f title=new",
    "curl -X POST https://api.github.com/repos/example/api/pulls -d x",
    "cockpit publish TASK-100/push-branch-1",
    "cockpit update apply",
)


def _listing(monkeypatch, pack_file, *entries):
    """The fixture pack with those lines added to its allowed.reads."""
    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    real = policy

    def listed(loaded):
        rules = real(loaded)
        rules["reads"] = rules["reads"] + list(entries)
        return rules

    monkeypatch.setattr("cockpitlib.pack.policy", listed)
    return load(pack_file)


@pytest.mark.parametrize("pack_file", PACKS)
@pytest.mark.parametrize("lane", SEATS)
def test_a_line_the_kernel_refuses_is_refused_though_the_pack_lists_it_as_a_read(env, pack_file, lane, monkeypatch):
    _listing(monkeypatch, pack_file, *KERNEL_REFUSED)
    if lane:
        monkeypatch.setenv("COCKPIT_LANE", lane)
    for command in KERNEL_REFUSED:
        assert egress.check_bound(command) == "blocked", command
        assert egress.check_tool("terminal", {"command": command}) != "", command


@pytest.mark.parametrize("pack_file", PACKS)
def test_a_listed_push_is_refused_with_the_words_of_an_unlisted_one(env, pack_file, monkeypatch):
    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    monkeypatch.setenv("COCKPIT_LANE", "worker-1")
    before = {
        command: egress.explained(egress.check_tool("terminal", {"command": command})) for command in KERNEL_REFUSED
    }
    _listing(monkeypatch, pack_file, *KERNEL_REFUSED)
    after = {
        command: egress.explained(egress.check_tool("terminal", {"command": command})) for command in KERNEL_REFUSED
    }
    assert after == before and all(said.startswith("blocked: ") for said in after.values())


@pytest.mark.parametrize("pack_file", PACKS)
def test_an_allowed_read_still_passes_the_packs_own_denies(env, pack_file, monkeypatch):
    pack = load(pack_file)
    host = pack["refused"]["hosts"][0]
    production = pack["egress"]["production_hosts"][0].replace("\\", "")
    refused_host, folder = f"curl https://{host}/status", f"ls repos/{production}"
    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    monkeypatch.setenv("COCKPIT_LANE", "worker-1")
    assert egress.check_bound(refused_host) == "blocked" and egress.check_bound(folder) == "blocked"
    _listing(monkeypatch, pack_file, refused_host, folder)
    read = pack["allowed"]["reads"][0]
    assert egress.check_bound(read) == ""
    assert egress.check_bound(refused_host) == "" and egress.check_bound(folder) == ""
    assert egress.check_bound(f"{read} && {folder}") == ""
    assert egress.check_bound(f"{folder} && git push origin main") == "blocked"
    assert egress.check_bound(f"{folder} extra") == "blocked", "an entry is matched exactly"


@pytest.mark.parametrize("pack_file", PACKS)
def test_doctor_names_an_allowed_read_a_kernel_deny_matches(env, pack_file, monkeypatch):
    pack = load(pack_file)
    assert doctor.allowed_read_problems(pack) == []
    pack["allowed"] = {"reads": [*pack["allowed"]["reads"], "git push origin main", "gh pr create -t x", "git log"]}
    assert doctor.allowed_read_problems(pack) == [
        "allowed.reads lists a command the kernel refuses: git push origin main",
        "allowed.reads lists a command the kernel refuses: gh pr create -t x",
    ]
    spec = doctor.CHECKS["egress.allowed-read-denied"]
    assert spec["severity"] == "error" and spec["security"] and "allowed.reads" in spec["fix"]


def test_the_kernels_own_refusal_reads_no_pack_rule():
    assert egress.kernel_refusal("git status") == ""
    assert egress.kernel_refusal("ledgerctl purge") == ""
    assert egress.kernel_refusal("git push") == "blocked"
    assert egress.kernel_refusal(None) == "unreadable tool call"
