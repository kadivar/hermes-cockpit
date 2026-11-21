# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""`outbox new` for a push reads the ticket's own worktree, the same checkout `verify` compares with.

It used to take the sha from the repo's primary ref, so a worktree whose HEAD differed filed an intent that
`verify` ("sha does not match worktree HEAD") and `push` rejected. Now the sha is the worktree HEAD, the branch
defaults to the worktree's, a different --branch keeps the old path (no new refusal), and the primary ref must be at that head.
With --sha, or with no ticket worktree, nothing changed. Both fixture packs run cockpit alone (no supervisor
plugin), which is how a cockpit-only install runs, so every case here is also that install's scenario.
"""

import json
import os
import subprocess

import pytest

from cockpitlib.errors import CockpitError
from cockpitlib.outbox import create, verify
from cockpitlib.pack import load
from cockpitlib.worktree import head_of

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PACKS = (
    os.path.join(ROOT, "packs", "acme", "pack.yaml"),
    os.path.join(ROOT, "packs", "bravo", "pack.yaml"),
)


def _git(folder, *args) -> str:
    return subprocess.run(["git", "-C", str(folder), *args], check=True, capture_output=True, text=True).stdout.strip()


def _commit(folder, name) -> str:
    (folder / name).write_text(name + "\n", encoding="utf-8")
    _git(folder, "add", ".")
    _git(folder, "-c", "user.email=dev@example.test", "-c", "user.name=Dev", "commit", "-q", "-m", name)
    return _git(folder, "rev-parse", "HEAD")


def _setup(env, pack_file, monkeypatch, ticket_no):
    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    monkeypatch.delenv("COCKPIT_LANE", raising=False)
    pack = load(pack_file)
    name = pack["repos"]["repos"][0]["name"]
    ticket = f"{pack['tracker']['project']}-{ticket_no}"
    from cockpitlib.ops import worktree_add

    worktree_add(pack, ticket, name)
    source = env["root"] / "repos" / name
    wt = env["root"] / "wt" / ticket / name
    branch = _git(wt, "branch", "--show-current")
    return pack, name, ticket, source, wt, branch


def _own_clone(env, source, ticket, name, branch):
    """A ticket checkout that is a clone of its own, ahead of the primary ref on the same branch. A linked git worktree
    shares its branch ref with the source, so it cannot diverge; only a clone in the ticket's folder can."""
    clone = env["root"] / "wt" / ticket / name
    _git(source, "worktree", "remove", "--force", str(clone))
    subprocess.run(["git", "clone", "-q", str(source), str(clone)], check=True, capture_output=True)
    _git(clone, "checkout", "-q", "-B", branch)
    _git(clone, "config", "user.email", "dev@example.test")
    _git(clone, "config", "user.name", "Dev")
    return clone


@pytest.mark.parametrize("pack_file", PACKS)
def test_a_clean_worktree_files_the_same_intent_as_before(env, pack_file, monkeypatch):
    pack, name, ticket, source, wt, branch = _setup(env, pack_file, monkeypatch, 2001)
    primary = _git(source, "rev-parse", f"refs/heads/{branch}")
    row = create(pack, ticket, "push-branch", "c", "ship", {"repo": name, "branch": branch})
    assert row["payload"]["sha"] == primary == head_of(ticket, name)
    assert row["payload"]["branch"] == branch
    assert "probe_error" not in row["payload"]
    assert not [item for item in verify(row["id"], pack=pack) if "sha does not match" in item]


@pytest.mark.parametrize("pack_file", PACKS)
def test_a_worktree_ahead_of_the_primary_ref_is_refused_at_new(env, pack_file, monkeypatch):
    pack, name, ticket, source, wt, branch = _setup(env, pack_file, monkeypatch, 2003)
    clone = _own_clone(env, source, ticket, name, branch)
    ahead = _commit(clone, "ahead.txt")
    assert head_of(ticket, name) == ahead != _git(source, "rev-parse", f"refs/heads/{branch}")
    with pytest.raises(
        CockpitError,
        match=f"branch {branch} is at .* but the ticket worktree is at {ahead[:10]}: check the worktree out at .*, or move {branch} to {ahead[:10]}, then file again",
    ):
        create(pack, ticket, "push-branch", "c", "ship", {"repo": name, "branch": branch})


@pytest.mark.parametrize("pack_file", PACKS)
def test_a_branch_that_is_not_the_worktrees_keeps_the_old_path(env, pack_file, monkeypatch):
    pack, name, ticket, source, wt, branch = _setup(env, pack_file, monkeypatch, 2004)
    _git(source, "branch", "other-work")
    other = _git(source, "rev-parse", "refs/heads/other-work")
    row = create(pack, ticket, "push-branch", "c", "ship", {"repo": name, "branch": "other-work"})
    assert row["payload"]["branch"] == "other-work"
    assert row["payload"]["sha"] == other  # the primary's ref, as before: not refused


@pytest.mark.parametrize("pack_file", PACKS)
def test_an_explicit_sha_keeps_todays_path_and_verify_still_judges_it(env, pack_file, monkeypatch):
    pack, name, ticket, source, wt, branch = _setup(env, pack_file, monkeypatch, 2005)
    clone = _own_clone(env, source, ticket, name, branch)
    primary = _git(source, "rev-parse", f"refs/heads/{branch}")
    ahead = _commit(clone, "ahead.txt")
    # No new refusal: the intent is filed with the sha it was given and a branch that is not the worktree's.
    row = create(pack, ticket, "push-branch", "c", "ship", {"repo": name, "branch": "free-form", "sha": primary})
    assert row["payload"]["sha"] == primary and row["payload"]["branch"] == "free-form"
    assert "probe_error" not in row["payload"]
    # And where the early refusal fires without --sha, verify rejects that same intent later: nothing new fails.
    assert any("sha does not match worktree HEAD" in item for item in verify(row["id"], pack=pack))
    other = create(pack, ticket, "push-branch", "c", "ship2", {"repo": name, "branch": "free-2", "sha": ahead})
    assert other["payload"]["sha"] == ahead


@pytest.mark.parametrize("pack_file", PACKS)
def test_without_a_ticket_worktree_the_primary_ref_is_used_as_before(env, pack_file, monkeypatch):
    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    monkeypatch.delenv("COCKPIT_LANE", raising=False)
    pack = load(pack_file)
    name = pack["repos"]["repos"][0]["name"]
    ticket = f"{pack['tracker']['project']}-2006"
    source = env["root"] / "repos" / name
    assert head_of(ticket, name) == ""
    _git(source, "branch", "free-branch")
    sha = _git(source, "rev-parse", "refs/heads/free-branch")
    row = create(pack, ticket, "push-branch", "c", "ship", {"repo": name, "branch": "free-branch"})
    assert row["payload"]["sha"] == sha and row["payload"]["branch"] == "free-branch"
    assert "probe_error" not in row["payload"]


@pytest.mark.parametrize("pack_file", PACKS)
def test_a_cockpit_only_install_refuses_early_only_what_verify_would_refuse_later(env, pack_file, monkeypatch):
    """A cockpit-only pack (worktree runtime, no supervisor): the fixture packs, cockpit alone (no supervisor plugin). Clean worktree: the intent
    verifies. Diverged worktree: `new` refuses, and the intent the old code would have filed fails verify. --sha: as before."""
    pack, name, ticket, source, wt, branch = _setup(env, pack_file, monkeypatch, 2008)
    clean = create(pack, ticket, "push-branch", "c", "ship", {"repo": name, "branch": branch})
    assert not [item for item in verify(clean["id"], pack=pack) if "sha does not match" in item]
    pack, name, ticket, source, wt, branch = _setup(env, pack_file, monkeypatch, 2007)
    clone = _own_clone(env, source, ticket, name, branch)
    primary = _git(source, "rev-parse", f"refs/heads/{branch}")
    _commit(clone, "ahead.txt")
    with pytest.raises(CockpitError, match="then file again"):
        create(pack, ticket, "push-branch", "c", "again", {"repo": name, "branch": branch})
    old = create(pack, ticket, "push-branch", "c", "old way", {"repo": name, "branch": branch, "sha": primary})
    assert any("sha does not match worktree HEAD" in item for item in verify(old["id"], pack=pack))
    assert old["payload"]["sha"] == primary


@pytest.mark.parametrize("pack_file", PACKS[:1])
def test_a_queued_press_carries_via_and_when_and_a_consumer_can_ignore_them(bare, pack_file, monkeypatch):
    from cockpitlib import plugin_api
    from cockpitlib.inbox import acts_dir, queue_act

    ident = plugin_api.inbox_row(
        "supervisor",
        {
            "id": "stuck:U1/check",
            "what": "check is stuck on U1",
            "tone": "danger",
            "detail": {
                "title": "t",
                "brief": "b",
                "actions": [
                    {"label": "Requeue", "act": {"release": "V1-0-0", "action": "requeue"}},
                    {"label": "Waive", "act": {"release": "V1-0-0", "action": "waive"}},
                ],
            },
        },
    )
    done = queue_act("supervisor", ident, 0)
    assert set(done) == {"queued", "plugin", "label"}, "the answer to the page is unchanged"
    queued = json.load(open(os.path.join(acts_dir("supervisor"), os.listdir(acts_dir("supervisor"))[0])))
    assert queued["via"] == "pane" and isinstance(queued["at"], int) and "client" not in queued
    # a consumer that knows only the old fields sees the same request
    old_view = {key: queued[key] for key in ("id", "at", "row", "act")}
    assert old_view["act"] == {"release": "V1-0-0", "action": "requeue"} and old_view["row"] == ident
    with_client = queue_act("supervisor", ident, 1, {"host": "127.0.0.1", "ua": "pytest", "empty": ""})
    names = [n for n in os.listdir(acts_dir("supervisor")) if n.endswith("-1.json")]
    second = json.load(open(os.path.join(acts_dir("supervisor"), names[0])))
    assert (
        second["client"] == {"host": "127.0.0.1", "ua": "pytest"} and second["via"] == "pane" and with_client["queued"]
    )


@pytest.mark.parametrize("pack_file", PACKS)
def test_a_worktree_branch_the_primary_does_not_have_keeps_the_old_path(env, pack_file, monkeypatch):
    from cockpitlib.git_push import _worktree_facts

    pack, name, ticket, source, wt, branch = _setup(env, pack_file, monkeypatch, 2007)
    clone = _own_clone(env, source, ticket, name, branch)
    _git(clone, "checkout", "-q", "-b", "only-in-the-clone")
    assert _worktree_facts(pack, ticket, name, "") == (
        "only-in-the-clone",
        "",
    )  # no primary ref to compare with: as before
    from cockpitlib.errors import CockpitError
    from cockpitlib.git_push import _git as checked

    with pytest.raises(CockpitError, match="^git rev-parse no-such-ref"):  # a git that fails says which call
        checked(str(clone), "rev-parse", "no-such-ref")
    assert checked(str(clone), "rev-parse", "no-such-ref", check=False) == ""
