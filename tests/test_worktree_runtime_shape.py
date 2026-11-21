# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""What a worktree-runtime pack does, pinned surface by surface: a pack shaped like the reference one (runtime
worktree, branch_prefix dev, slots.provider command, no marker beside a worktree). `cockpit worktree add`, the worktree
list and status, the checkout the outbox and the push read, a card's checkout, the gate folder and the worker's write
fence are exactly these, whatever else changes around them."""

import os
import shutil
import subprocess

import pytest

from cockpitlib import egress, git_push, repo_gates, worktree
from cockpitlib.cli import cmd_worktree
from cockpitlib.kanban import place_card
from cockpitlib.ops import worktree_add
from cockpitlib.pack import load

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _git(folder, *args) -> str:
    return subprocess.run(["git", "-C", str(folder), *args], check=True, capture_output=True, text=True).stdout.strip()


@pytest.fixture
def shaped(env, tmp_path, monkeypatch):
    """bravo with the reference pack's shape: branch_prefix dev, runtime worktree, slots.provider command."""
    folder = tmp_path / "shaped"
    shutil.copytree(os.path.join(ROOT, "packs", "bravo"), folder, symlinks=True)
    path = folder / "pack.yaml"
    text = path.read_text(encoding="utf-8")
    assert "branch_prefix: work\n" in text and "runtime: worktree\n" in text and "  provider: command\n" in text
    text = text.replace("branch_prefix: work\n", "branch_prefix: dev\n").replace("'@skills'", str(folder / "skills"))
    path.write_text(text, encoding="utf-8")
    monkeypatch.setenv("COCKPIT_PACK", str(path))
    pack = load(str(path))
    assert (pack["runtime"], pack["branch_prefix"], pack["slots"]["provider"]) == ("worktree", "dev", "command")
    assert "worker_branch_prefixes" not in pack
    return {**env, "pack": pack, "wt": env["root"] / "wt", "repos": env["root"] / "repos"}


def _files(folder) -> list:
    return sorted(os.listdir(folder))


def test_worktree_add_makes_wt_ticket_repo_on_the_ticket_branch(shaped, capsys):
    pack, wt, repos = shaped["pack"], shaped["wt"], shaped["repos"]
    assert cmd_worktree(["add", "NORTH-7001", "site"]) == 0
    assert capsys.readouterr().out == f"{wt / 'NORTH-7001' / 'site'}\n"
    made = wt / "NORTH-7001" / "site"
    assert _files(wt / "NORTH-7001") == ["site"]  # the worktree and nothing beside it
    assert _git(made, "branch", "--show-current") == "dev/NORTH-7001"
    assert _git(made, "rev-parse", "HEAD") == _git(repos / "site", "rev-parse", "origin/main")
    assert _git(made, "config", "--worktree", "remote.origin.pushurl") == "DISABLED"
    assert _git(made, "config", "--worktree", "cockpit.push") == "disabled"
    assert _git(repos / "site", "branch", "--show-current") == "main"  # the repo's own checkout never moves
    assert _git(repos / "site", "status", "--porcelain") == ""
    # again: the same folder, as it stands
    assert worktree_add(pack, "NORTH-7001", "site") == [str(made)]
    assert cmd_worktree(["add", "NORTH-7001", "site"]) == 0 and capsys.readouterr().out == f"{made}\n"


def test_worktree_add_without_a_repo_makes_every_repo_and_from_starts_at_the_ref(shaped, capsys):
    _pack, wt, repos = shaped["pack"], shaped["wt"], shaped["repos"]
    assert cmd_worktree(["add", "NORTH-7002"]) == 0
    assert capsys.readouterr().out == f"{wt / 'NORTH-7002' / 'ledger'}\n{wt / 'NORTH-7002' / 'site'}\n"
    assert _files(wt / "NORTH-7002") == ["ledger", "site"]
    for name in ("ledger", "site"):
        assert _git(wt / "NORTH-7002" / name, "branch", "--show-current") == "dev/NORTH-7002"
        assert _git(repos / name, "branch", "--show-current") == "main"
    assert (wt / "NORTH-7002" / "ledger" / ".north-ready").is_file()  # the repo's after_add ran in the worktree
    _git(repos / "site", "checkout", "-q", "-b", "feature/pr")
    (repos / "site" / "one.txt").write_text("one\n", encoding="utf-8")
    _git(repos / "site", "add", ".")
    _git(repos / "site", "commit", "-q", "-m", "one")
    head = _git(repos / "site", "rev-parse", "HEAD")
    _git(repos / "site", "checkout", "-q", "main")
    assert cmd_worktree(["add", "NORTH-7003", "site", "--from", "feature/pr"]) == 0
    assert capsys.readouterr().out == f"{wt / 'NORTH-7003' / 'site'}\n"
    assert _git(wt / "NORTH-7003" / "site", "rev-parse", "HEAD") == head
    assert _git(wt / "NORTH-7003" / "site", "branch", "--show-current") == "dev/NORTH-7003"
    assert _git(repos / "site", "branch", "--show-current") == "main"


def test_the_list_the_status_and_the_checkout_every_reader_uses(shaped):
    pack, wt, repos = shaped["pack"], shaped["wt"], shaped["repos"]
    worktree_add(pack, "NORTH-7004", "site")
    made = str(wt / "NORTH-7004" / "site")
    assert worktree.list_worktrees("NORTH-7004") == [made] and worktree.list_worktrees() == [made]
    assert worktree.ticket_checkouts("NORTH-7004", pack) == [made]
    assert worktree._checkout("NORTH-7004", "site", pack) == made and worktree._checkout("NORTH-7004", "site") == made
    assert git_push.checkout(pack, "NORTH-7004", "site") == made
    assert git_push.checkout(pack, "NORTH-7004", "ledger") == str(
        repos / "ledger"
    )  # no worktree: the repo's own checkout
    head = _git(made, "rev-parse", "HEAD")
    assert worktree.head_of("NORTH-7004", "site", pack) == head and worktree.head_of("NORTH-7004", "ledger", pack) == ""
    assert git_push._worktree_facts(pack, "NORTH-7004", "site", "") == ("dev/NORTH-7004", head)
    assert worktree.worktree_status("NORTH-7004", pack) == [
        {"repo": "site", "dir": made, "branch": "dev/NORTH-7004", "unpushed": 0, "dirty": 0}
    ]
    (wt / "NORTH-7004" / "site" / "new.txt").write_text("x\n", encoding="utf-8")
    _git(made, "add", ".")
    _git(made, "-c", "user.email=dev@example.test", "-c", "user.name=Dev", "commit", "-q", "-m", "work")
    (wt / "NORTH-7004" / "site" / "loose.txt").write_text("x\n", encoding="utf-8")
    assert worktree.worktree_status("NORTH-7004", pack) == [
        {"repo": "site", "dir": made, "branch": "dev/NORTH-7004", "unpushed": 1, "dirty": 1}
    ]
    assert worktree.card_checkout("NORTH-7004", made) == {"ticket": "NORTH-7004", "repo": "site"}
    assert worktree.card_checkout("NORTH-7004") == {"ticket": "NORTH-7004", "repo": "site"}
    assert worktree.card_checkout("NORTH-7004", str(repos / "site")) == {
        "ticket": "NORTH-7004",
        "repo": "site",
    }  # its only checkout
    worktree_add(pack, "NORTH-7004", "ledger")
    assert worktree.card_checkout("NORTH-7004", str(repos / "site")) == {}
    assert worktree.card_checkout("NORTH-7004", repos=["ledger"]) == {"ticket": "NORTH-7004", "repo": "ledger"}
    assert worktree.mode("NORTH-7004", "site", True, pack) == "ALLOWED"
    assert _git(made, "config", "--worktree", "cockpit.push") == "allowed"
    assert worktree.mode("NORTH-7004", "site", False, pack) == "DISABLED"
    assert _git(made, "config", "--worktree", "remote.origin.pushurl") == "DISABLED"


def test_the_gate_runs_in_the_worktree(shaped):
    pack, wt, _repos = shaped["pack"], shaped["wt"], shaped["repos"]
    worktree_add(pack, "NORTH-7005", "site")
    by_name = {repo["name"]: repo for repo in pack["repos"]["repos"]}
    assert repo_gates._gate_folder(pack, by_name["site"], "NORTH-7005") == str(wt / "NORTH-7005" / "site")
    assert os.path.realpath(repo_gates._gate_folder(pack, by_name["ledger"], "NORTH-7005")) == os.path.realpath(
        shaped["workspace"]
    )


def test_a_worker_writes_in_its_worktree_and_nowhere_in_the_repos_own_checkout(shaped, monkeypatch):
    pack, wt, repos = shaped["pack"], shaped["wt"], shaped["repos"]
    worktree_add(pack, "NORTH-7006", "site")
    card = place_card(
        pack["board"],
        "NORTH-7006: work",
        "worker-1",
        "ready",
        ticket="NORTH-7006",
        pack=pack,
        repos=["site"],
        kind="worker",
    )
    monkeypatch.setenv("COCKPIT_LANE", "worker-1")
    monkeypatch.setenv("HERMES_KANBAN_TASK", card)
    monkeypatch.setenv("HERMES_KANBAN_BOARD", pack["board"])

    def edit(path) -> str:
        return egress._worker_write("", pack, targets=[str(path)])

    assert edit(wt / "NORTH-7006" / "site" / "app.py") == ""
    assert edit(repos / "site" / "app.py") == "blocked"
    assert edit(repos / "ledger" / "app.py") == "blocked"
    assert edit(shaped["workspace"] / "notes.md") == "blocked"
    _git(
        repos / "site", "checkout", "-q", "-b", "dev/NORTH-7999"
    )  # a ticket branch in the repo's own checkout opens nothing
    assert edit(repos / "site" / "app.py") == "blocked"
    assert egress._worker_write(f"echo x > {wt / 'NORTH-7006' / 'site' / 'a.txt'}", pack) == ""
    assert egress._worker_write(f"echo x > {repos / 'site' / 'a.txt'}", pack) == "blocked"
    told = egress.fence_explain(pack, card, str(repos / "site" / "app.py"))
    assert (
        told["allowed"] is False
        and told["why"]
        == f"a write outside your ticket checkouts ({repos / 'site' / 'app.py'}); records change through cockpit verbs"
    )
    assert egress.fence_explain(pack, card, str(wt / "NORTH-7006" / "site" / "app.py"))["allowed"] is True
    monkeypatch.setenv("COCKPIT_LANE", "reviewer-1")  # only a worker's edits are held to its checkouts by this rule
    assert edit(repos / "site" / "app.py") == ""


def test_a_release_unit_on_feature_ticket_cut_from_a_release_branch_lives_in_its_worktree(shaped, monkeypatch):
    """The other shape in use: runtime worktree, branch_prefix feature, a unit's worktree on feature/<ticket> cut from a
    release branch, and a file left beside the worktree by older tooling
    (wt/<ticket>/<repo>.mounted, naming the repo's own checkout). The checkout, the push, the diff, the gate and the
    fence all use the worktree; the leftover file and the repo's own checkout count for nothing."""
    path = shaped["pack"]["_path"]
    text = open(path, encoding="utf-8").read()
    assert "branch_prefix: dev\n" in text
    open(path, "w", encoding="utf-8").write(text.replace("branch_prefix: dev\n", "branch_prefix: feature\n"))
    pack = load(path)
    assert pack["runtime"] == "worktree" and pack["branch_prefix"] == "feature"
    wt, repos = shaped["wt"], shaped["repos"]
    source, made = repos / "site", wt / "NORTH-7007" / "site"
    _git(source, "branch", "release/v1")
    _git(source, "checkout", "-q", "-b", "agent/v1-unit")  # the repo's own checkout sits on some other branch
    assert worktree_add(pack, "NORTH-7007", "site", "release/v1") == [str(made)]
    (wt / "NORTH-7007" / "site.mounted").write_text(str(source), encoding="utf-8")
    (made / "unit.py").write_text("x = 1\n", encoding="utf-8")
    _git(made, "add", "unit.py")
    _git(made, "-c", "user.name=t", "-c", "user.email=t@example.test", "commit", "-q", "-m", "unit")
    head = _git(made, "rev-parse", "HEAD")
    assert _git(made, "rev-parse", "--abbrev-ref", "HEAD") == "feature/NORTH-7007"
    assert _git(made, "merge-base", "HEAD", "release/v1") == _git(source, "rev-parse", "release/v1") != head
    assert (
        _git(source, "rev-parse", "--abbrev-ref", "HEAD") == "agent/v1-unit"
        and _git(source, "rev-parse", "HEAD") != head
    )
    assert worktree._checkout("NORTH-7007", "site", pack) == str(made) == worktree._checkout("NORTH-7007", "site")
    assert git_push.checkout(pack, "NORTH-7007", "site") == str(made)
    assert worktree.head_of("NORTH-7007", "site", pack) == head
    assert git_push._worktree_facts(pack, "NORTH-7007", "site", "") == ("feature/NORTH-7007", head)
    from cockpitlib.diffs import checkout_of

    assert checkout_of("NORTH-7007", "site", pack) == str(made)
    assert worktree.list_worktrees("NORTH-7007") == [str(made)] == worktree.ticket_checkouts("NORTH-7007", pack)
    assert worktree.worktree_status("NORTH-7007", pack) == [
        {"repo": "site", "dir": str(made), "branch": "feature/NORTH-7007", "unpushed": 1, "dirty": 0}
    ]
    assert worktree.card_checkout("NORTH-7007", str(made)) == {"ticket": "NORTH-7007", "repo": "site"}
    assert worktree.card_checkout("NORTH-7007", str(source)) == {
        "ticket": "NORTH-7007",
        "repo": "site",
    }  # its only checkout
    by_name = {repo["name"]: repo for repo in pack["repos"]["repos"]}
    assert repo_gates._gate_folder(pack, by_name["site"], "NORTH-7007") == str(made)
    card = place_card(
        pack["board"],
        "NORTH-7007: work",
        "worker-1",
        "ready",
        ticket="NORTH-7007",
        pack=pack,
        repos=["site"],
        kind="worker",
    )
    other = place_card(
        pack["board"],
        "NORTH-7007: other",
        "worker-1",
        "ready",
        ticket="NORTH-7007",
        pack=pack,
        repos=["ledger"],
        kind="worker",
    )
    monkeypatch.setenv("COCKPIT_LANE", "worker-1")
    monkeypatch.setenv("HERMES_KANBAN_BOARD", pack["board"])

    def edit(target) -> str:
        return egress._worker_write("", pack, targets=[str(target)])

    for running in (card, other, ""):  # whatever card runs, and with none
        monkeypatch.setenv("HERMES_KANBAN_TASK", running)
        assert edit(made / "app.py") == ""
        assert edit(source / "app.py") == "blocked" and edit(repos / "ledger" / "app.py") == "blocked"
        assert edit(shaped["workspace"] / "x") == "blocked"
    told = egress.fence_explain(pack, card, str(source / "app.py"))
    assert (
        told["allowed"] is False
        and told["why"]
        == f"a write outside your ticket checkouts ({source / 'app.py'}); records change through cockpit verbs"
    )
    assert egress.fence_explain(pack, card, str(made / "app.py"))["allowed"] is True
