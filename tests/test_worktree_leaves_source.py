# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""`cockpit worktree add` never switches the repo's own checkout: whatever branch it is on (agent/v*, rc, a ticket
branch the human holds) and even when it is the workspace repo, the ticket gets wt/<ticket>/<repo> on its own branch,
under the held branch's suffix when the human's checkout has that branch. Both fixture packs."""

import os
import subprocess

import pytest

from cockpitlib.pack import load

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PACKS = (
    os.path.join(ROOT, "packs", "acme", "pack.yaml"),
    os.path.join(ROOT, "packs", "bravo", "pack.yaml"),
)
AGENT = "agent/next-release-fixes"


def _head(folder) -> str:
    done = subprocess.run(
        ["git", "-C", str(folder), "rev-parse", "--abbrev-ref", "HEAD"], check=True, capture_output=True, text=True
    )
    return done.stdout.strip()


def _checkout(folder, branch) -> None:
    subprocess.run(["git", "-C", str(folder), "checkout", "-q", "-b", branch], check=True, capture_output=True)


def _side(ticket, name) -> str:
    return os.path.join(os.environ["COCKPIT_WT"], ticket, name)


@pytest.mark.parametrize("pack_file", PACKS)
def test_a_source_on_an_agent_branch_is_left_as_it_is(env, pack_file, monkeypatch):
    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    pack = load(pack_file)
    from cockpitlib.ops import worktree_add

    repo = pack["repos"]["repos"][0]
    name = repo["name"]
    source = env["root"] / "repos" / name
    assert os.path.realpath(source) != os.path.realpath(env["workspace"])
    _checkout(source, AGENT)
    ticket = f"{pack['tracker']['project']}-151"
    before = _head(source)
    assert before == AGENT
    made = worktree_add(pack, ticket, name)
    side = _side(ticket, name)
    assert _head(source) == before
    assert os.path.realpath(made[0]) == os.path.realpath(side)
    assert os.path.realpath(side) != os.path.realpath(source)
    assert _head(side) == f"{pack['branch_prefix']}/{ticket}"


@pytest.mark.parametrize("pack_file", PACKS)
def test_a_source_on_rc_stays_on_rc(env, pack_file, monkeypatch):
    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    pack = load(pack_file)
    from cockpitlib.ops import worktree_add

    name = pack["repos"]["repos"][0]["name"]
    source = env["root"] / "repos" / name
    _checkout(source, "rc")
    ticket = f"{pack['tracker']['project']}-152"
    branch = f"{pack['branch_prefix']}/{ticket}"
    made = worktree_add(pack, ticket, name)
    side = _side(ticket, name)
    assert _head(source) == "rc"
    assert os.path.realpath(made[0]) == os.path.realpath(side)
    assert _head(side) == branch


@pytest.mark.parametrize("pack_file", PACKS)
def test_three_tickets_are_added_and_the_human_checkout_does_not_move(env, pack_file, monkeypatch):
    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    pack = load(pack_file)
    from cockpitlib.ops import worktree_add

    repo = pack["repos"]["repos"][0]
    name = repo["name"]
    suffix = repo["branch_suffix_when_held"]
    assert suffix
    source = env["root"] / "repos" / name
    tickets = [f"{pack['tracker']['project']}-{number}" for number in (301, 302, 303)]
    held = f"{pack['branch_prefix']}/{tickets[0]}"
    _checkout(source, held)
    assert _head(source) == held
    folders = []
    for ticket in tickets:
        made = worktree_add(pack, ticket, name)
        side = _side(ticket, name)
        # The source is the human checkout. worktree add must leave its branch where it was.
        assert _head(source) == held
        assert os.path.realpath(made[0]) == os.path.realpath(side)
        assert os.path.realpath(side) != os.path.realpath(source)
        folders.append(side)
    assert _head(folders[0]) == held + suffix
    assert _head(folders[1]) == f"{pack['branch_prefix']}/{tickets[1]}"
    assert _head(folders[2]) == f"{pack['branch_prefix']}/{tickets[2]}"


@pytest.mark.parametrize("pack_file", PACKS)
def test_a_workspace_checkout_is_not_switched(env, pack_file, monkeypatch):
    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    pack = load(pack_file)
    from cockpitlib.ops import worktree_add

    repo = pack["repos"]["repos"][0]
    name = repo["name"]
    folder = env["workspace"]
    base = repo.get("base") or pack.get("base_branch") or "main"
    subprocess.run(["git", "init", "-q", "-b", base, str(folder)], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(folder), "config", "user.email", "dev@example.test"], check=True, capture_output=True
    )
    subprocess.run(["git", "-C", str(folder), "config", "user.name", "Dev"], check=True, capture_output=True)
    (folder / "README").write_text(pack["name"] + "\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(folder), "add", "README"], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(folder), "commit", "-qm", "init"], check=True, capture_output=True)
    stay = pack["workspace_branch"]
    if stay != base:
        subprocess.run(["git", "-C", str(folder), "checkout", "-q", "-b", stay], check=True, capture_output=True)
    assert _head(folder) == stay
    repo["path"] = str(folder)
    ticket = f"{pack['tracker']['project']}-154"
    made = worktree_add(pack, ticket, name)
    side = _side(ticket, name)
    assert _head(folder) == stay
    assert os.path.realpath(made[0]) == os.path.realpath(side)
    assert os.path.realpath(side) != os.path.realpath(folder)
    assert _head(side) == f"{pack['branch_prefix']}/{ticket}"
