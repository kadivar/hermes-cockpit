# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""A ticket's checkouts: one per repo on the ticket branch, who may push from them, and what a card shows of them."""

import json
import os

import pytest

from cockpitlib.errors import CockpitError
from cockpitlib.pack import load
from tests.support.both_packs import PACKS, _client


def test_a_card_shows_the_checkout_it_works_in_and_a_ticket_its_checkouts(env, tmp_path):
    """The Inbox card's Diff and Open IDE need the checkout a card works in; the Tickets page needs each checkout's branch,
    unpushed commits and changed files."""
    import subprocess

    from cockpitlib.paths import wt
    from cockpitlib.worktree import card_checkout, worktree_status

    def repo(ticket, name):
        folder = os.path.join(wt(), ticket, name)
        os.makedirs(folder)
        for argv in (
            ["init", "-q", "-b", "work"],
            ["config", "user.email", "t@example.test"],
            ["config", "user.name", "t"],
            ["commit", "-q", "--allow-empty", "-m", "one"],
        ):
            subprocess.run(["git", "-C", folder, *argv], check=True, capture_output=True)
        return folder

    api = repo("TASK-7", "api")
    assert card_checkout("TASK-7", os.path.join(wt(), "TASK-7")) == {
        "ticket": "TASK-7",
        "repo": "api",
    }  # the only checkout
    repo("TASK-7", "web")
    assert card_checkout("TASK-7", os.path.join(wt(), "TASK-7")) == {}  # two checkouts and nothing names one
    assert card_checkout("TASK-7", api) == {"ticket": "TASK-7", "repo": "api"}  # the card's workspace is one checkout
    assert card_checkout("TASK-7", "", ["web"]) == {"ticket": "TASK-7", "repo": "web"}  # its pull request's repo
    assert card_checkout("TASK-7", "", [], "Slot: 1\nRepo: web · branch x\n") == {"ticket": "TASK-7", "repo": "web"}
    assert card_checkout("TASK-7", "", ["missing"]) == {} and card_checkout("", api) == {}

    open(os.path.join(api, "note.txt"), "w").write("x")
    rows = {row["repo"]: row for row in worktree_status("TASK-7")}
    assert rows["api"]["branch"] == "work" and rows["api"]["unpushed"] == 1 and rows["api"]["dirty"] == 1
    assert rows["web"]["dirty"] == 0 and rows["api"]["dir"] == api
    assert worktree_status("TASK-404") == []


@pytest.mark.parametrize("pack_file", PACKS)
def test_a_human_can_push_and_a_lane_cannot(env, pack_file, monkeypatch):
    import subprocess

    monkeypatch.delenv("COCKPIT_LANE", raising=False)
    pack = load(pack_file)
    other = load(PACKS[0] if pack["name"] == "bravo" else PACKS[1])
    name = pack["repos"]["repos"][0]["name"]
    assert name != other["repos"]["repos"][0]["name"]
    git_env = os.environ.copy()
    git_env.update(
        {
            "GIT_AUTHOR_NAME": "Dev",
            "GIT_AUTHOR_EMAIL": "dev@example.test",
            "GIT_COMMITTER_NAME": "Dev",
            "GIT_COMMITTER_EMAIL": "dev@example.test",
        }
    )
    for repo in pack["repos"]["repos"]:
        source = env["root"] / "repos" / repo["name"]
        source.mkdir(parents=True, exist_ok=True)
        if (source / ".git").exists():
            continue
        subprocess.run(["git", "init", str(source)], check=True, capture_output=True)
        (source / "README").write_text(f"{pack['name']}\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(source), "add", "README"], check=True, capture_output=True)
        subprocess.run(["git", "-C", str(source), "commit", "-m", "init"], check=True, capture_output=True, env=git_env)
    origin = f"https://git.{pack['name']}.test/{name}.git"
    source = env["root"] / "repos" / name
    subprocess.run(["git", "-C", str(source), "remote", "remove", "origin"], check=False, capture_output=True)
    subprocess.run(["git", "-C", str(source), "remote", "add", "origin", origin], check=True, capture_output=True)
    from cockpitlib.acts import session_handoff, session_open
    from cockpitlib.worktree import _checkout

    def pushurl(path):
        for args in (["--worktree", "--get"], ["--get"]):
            done = subprocess.run(
                ["git", "-C", path, "config", *args, "remote.origin.pushurl"],
                check=False,
                capture_output=True,
                text=True,
            )
            if done.returncode == 0:
                return done.stdout.strip()
        return ""

    def push_target(path):
        done = subprocess.run(
            ["git", "-C", path, "remote", "get-url", "--push", "origin"], check=False, capture_output=True, text=True
        )
        return (done.stdout or "").strip()

    assert session_open(pack, 1, "TASK-8943").startswith("session")
    folder = _checkout("TASK-8943", name)
    assert pushurl(folder) == ""
    assert push_target(folder) == origin
    assert other["name"] not in push_target(folder)
    assert other["name"] not in folder
    monkeypatch.setenv("COCKPIT_LANE", "worker-1")
    assert "worker-1" in session_handoff(pack, 1, "worker-1")
    assert pushurl(folder) == "DISABLED"
    from cockpitlib.acts import _set_push_mode

    _set_push_mode({"repos": {"repos": [{"name": ""}, {"name": "missing-repo"}]}}, "TASK-8943", True)


@pytest.mark.parametrize("pack_file", PACKS)
def test_a_pull_request_card_puts_the_checkout_back_in_lane_mode(env, pack_file, monkeypatch):
    import subprocess

    monkeypatch.delenv("COCKPIT_LANE", raising=False)
    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    pack = load(pack_file)
    other = load(PACKS[0] if pack["name"] == "bravo" else PACKS[1])
    name = pack["repos"]["repos"][0]["name"]
    assert name != other["repos"]["repos"][0]["name"]
    git_env = os.environ.copy()
    git_env.update(
        {
            "GIT_AUTHOR_NAME": "Dev",
            "GIT_AUTHOR_EMAIL": "dev@example.test",
            "GIT_COMMITTER_NAME": "Dev",
            "GIT_COMMITTER_EMAIL": "dev@example.test",
        }
    )
    for repo in pack["repos"]["repos"]:
        source = env["root"] / "repos" / repo["name"]
        source.mkdir(parents=True, exist_ok=True)
        if (source / ".git").exists():
            continue
        subprocess.run(["git", "init", str(source)], check=True, capture_output=True)
        (source / "README").write_text(f"{pack['name']}\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(source), "add", "README"], check=True, capture_output=True)
        subprocess.run(["git", "-C", str(source), "commit", "-m", "init"], check=True, capture_output=True, env=git_env)
    origin = f"https://git.{pack['name']}.test/{name}.git"
    source = env["root"] / "repos" / name
    subprocess.run(["git", "-C", str(source), "remote", "remove", "origin"], check=False, capture_output=True)
    subprocess.run(["git", "-C", str(source), "remote", "add", "origin", origin], check=True, capture_output=True)
    from cockpitlib.acts import session_open, treat_pr
    from cockpitlib.worktree import _checkout

    ticket = f"{pack['tracker']['project']}-8944"
    assert session_open(pack, 1, ticket).startswith("session")
    folder = _checkout(ticket, name)

    def push_target(path):
        done = subprocess.run(
            ["git", "-C", path, "remote", "get-url", "--push", "origin"], check=False, capture_output=True, text=True
        )
        return (done.stdout or "").strip()

    assert push_target(folder) == origin
    opened = treat_pr(pack, ticket, name, 4, note=pack["name"])
    assert opened["card_id"]
    assert push_target(folder) == "DISABLED"
    mode = subprocess.run(
        ["git", "-C", folder, "config", "--worktree", "--get", "cockpit.push"],
        check=False,
        capture_output=True,
        text=True,
    )
    assert mode.stdout.strip() == "disabled"
    assert other["name"] not in push_target(folder)
    assert other["name"] not in opened["out"]


@pytest.mark.parametrize("pack_file", PACKS)
def test_one_checkout_per_repo_stays_on_the_ticket_branch(env, pack_file, monkeypatch):
    import subprocess

    pack = load(pack_file)
    other = load(PACKS[0] if pack["name"] == "bravo" else PACKS[1])
    name = pack["repos"]["repos"][0]["name"]
    assert name != other["repos"]["repos"][0]["name"]
    from cockpitlib.ops import worktree_add
    from cockpitlib.worktree import dest

    source = env["root"] / "repos" / name
    source.mkdir(parents=True, exist_ok=True)
    if not (source / ".git").exists():
        subprocess.run(["git", "init", str(source)], check=True, capture_output=True)
        (source / "README").write_text(f"{pack['name']}\n", encoding="utf-8")
        git = os.environ.copy()
        git["GIT_AUTHOR_NAME"] = "Dev"
        git["GIT_AUTHOR_EMAIL"] = "dev@example.test"
        git["GIT_COMMITTER_NAME"] = "Dev"
        git["GIT_COMMITTER_EMAIL"] = "dev@example.test"
        subprocess.run(["git", "-C", str(source), "add", "README"], check=True, capture_output=True)
        subprocess.run(["git", "-C", str(source), "commit", "-m", "init"], check=True, capture_output=True, env=git)
    branch = f"{pack['branch_prefix']}/TASK-8940"
    subprocess.run(["git", "-C", str(source), "branch", branch], check=False, capture_output=True)
    first = worktree_add(pack, "TASK-8940", name)
    second = worktree_add(pack, "TASK-8940", name)
    assert first == second
    assert len(first) == 1
    folder = first[0]
    current = subprocess.run(
        ["git", "-C", folder, "rev-parse", "--abbrev-ref", "HEAD"], check=True, capture_output=True, text=True
    ).stdout.strip()
    assert current == branch
    assert folder == dest("TASK-8940", name)
    assert other["name"] not in folder

    def _noop(*_args, **_kwargs):
        class Result:
            returncode = 1
            stdout = ""
            stderr = ""

        return Result()

    monkeypatch.setattr("cockpitlib.worktree.subprocess.run", _noop)
    from cockpitlib.worktree import add, dest

    with pytest.raises(CockpitError, match="git worktree add failed"):
        add("TASK-8941", name, pack["branch_prefix"], str(source))
    assert not os.path.isdir(dest("TASK-8941", name))


# Each fixture's first repo: what it copies, where its hooks are, the file it writes, its after-add mark, its suffix.
WORKTREE_SETUP = {
    "acme": {
        "copy": ".env.sample",
        "hooks": ".githooks",
        "file": (".env.worktree", "API_MODE=worktree\n"),
        "mark": ".after-add",
        "suffix": "-lane",
    },
    "bravo": {
        "copy": "config/app.yaml",
        "hooks": "tools/hooks",
        "file": ("conf/local.ini", "[ledger]\nmode = lane\n"),
        "mark": ".north-ready",
        "suffix": ".alt",
    },
}


@pytest.mark.parametrize("pack_file", PACKS)
def test_a_worktree_branches_from_the_fresh_base_and_carries_the_repos_setup(env, pack_file, monkeypatch):
    import subprocess

    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    pack = load(pack_file)
    own = WORKTREE_SETUP[pack["name"]]
    from cockpitlib.worktree import add, dest

    repo = pack["repos"]["repos"][0]
    source = env["root"] / "repos" / repo["name"]
    remote = env["root"] / "remote.git"
    git = lambda *args, cwd=source: subprocess.run(
        ["git", "-C", str(cwd), "-c", "user.name=Dev", "-c", "user.email=d@x.test", *args],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    subprocess.run(["git", "init", "-q", "--bare", str(remote)], check=True)
    source.mkdir(parents=True, exist_ok=True)
    if not (source / ".git").exists():
        subprocess.run(["git", "init", "-q", str(source)], check=True)
    (source / os.path.dirname(own["copy"]) if os.path.dirname(own["copy"]) else source).mkdir(
        parents=True, exist_ok=True
    )
    (source / own["copy"]).write_text("copied\n", encoding="utf-8")
    (source / "README").write_text("one\n", encoding="utf-8")
    git("add", "README")
    git("commit", "-qm", "one")
    git("remote", "set-url", "origin", str(remote))
    git("push", "-q", "origin", "main")
    # The remote moves on; the worktree must start from it, not from the stale local main.
    other_clone = env["root"] / "other-clone"
    subprocess.run(["git", "clone", "-q", str(remote), str(other_clone)], check=True)
    (other_clone / "README").write_text("two\n", encoding="utf-8")
    git("commit", "-qam", "two", cwd=other_clone)
    git("push", "-q", "origin", "main", cwd=other_clone)
    fresh = git("rev-parse", "HEAD", cwd=other_clone)
    ticket = f"{pack['tracker']['project']}-170"
    folder = add(ticket, repo["name"], pack["branch_prefix"], str(source), base="main", setup=repo)
    assert folder == dest(ticket, repo["name"])
    assert git("rev-parse", "HEAD", cwd=folder) == fresh
    assert (env["root"] / "wt" / ticket / repo["name"] / own["copy"]).read_text(encoding="utf-8") == "copied\n"
    assert git("config", "--worktree", "core.hooksPath", cwd=folder) == str(source / own["hooks"])
    assert open(os.path.join(folder, own["file"][0]), encoding="utf-8").read() == own["file"][1]
    assert os.path.isfile(os.path.join(folder, own["mark"]))
    # --from starts at that ref instead.
    old = git("rev-parse", "HEAD~0", cwd=source)
    other = add(
        f"{pack['tracker']['project']}-171",
        repo["name"],
        pack["branch_prefix"],
        str(source),
        branch_from=old,
        base="main",
        setup=repo,
    )
    assert git("rev-parse", "HEAD", cwd=other) == old
    with pytest.raises(CockpitError, match="no ref nope"):
        add(
            f"{pack['tracker']['project']}-172",
            repo["name"],
            pack["branch_prefix"],
            str(source),
            branch_from="nope",
            setup=repo,
        )
    with pytest.raises(CockpitError, match="no trunk-x to branch from"):
        add(
            f"{pack['tracker']['project']}-173",
            repo["name"],
            pack["branch_prefix"],
            str(source),
            base="trunk-x",
            setup=repo,
        )
    # A branch the human has checked out is taken under the repo's own suffix; without one it is refused.
    held = f"{pack['tracker']['project']}-174"
    git("checkout", "-qb", f"{pack['branch_prefix']}/{held}")
    lane = add(held, repo["name"], pack["branch_prefix"], str(source), base="main", setup=repo)
    assert git("rev-parse", "--abbrev-ref", "HEAD", cwd=lane) == f"{pack['branch_prefix']}/{held}{own['suffix']}"
    git("checkout", "-qb", f"{pack['branch_prefix']}/{pack['tracker']['project']}-175")
    with pytest.raises(CockpitError, match="set branch_suffix_when_held"):
        add(
            f"{pack['tracker']['project']}-175",
            repo["name"],
            pack["branch_prefix"],
            str(source),
            base="main",
            setup={key: value for key, value in repo.items() if key != "branch_suffix_when_held"},
        )
    with pytest.raises(CockpitError, match="after_add sh -c exit 3"):
        add(
            f"{pack['tracker']['project']}-176",
            repo["name"],
            pack["branch_prefix"],
            str(source),
            base="main",
            setup={"after_add": [["sh", "-c", "exit 3"]]},
        )


@pytest.mark.parametrize("pack_file", PACKS)
def test_worktree_add_checks_the_ticket_branch_out_beside_the_repo(env, pack_file, monkeypatch):
    import subprocess

    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    pack = load(pack_file)
    from cockpitlib.errors import PackError
    from cockpitlib.ops import worktree_add
    from cockpitlib.pack import _runtime

    assert pack["runtime"] == "worktree"
    with pytest.raises(PackError, match="^runtime$"):
        _runtime({"runtime": "side"})
    with pytest.raises(PackError, match="^runtime$"):
        _runtime({"runtime": "mounted"})
    for accepted in ({}, {"runtime": ""}, {"runtime": None}):  # absent means worktree and is left absent
        _runtime(accepted)
        assert not accepted.get("runtime")
    name = pack["repos"]["repos"][0]["name"]
    source = env["root"] / "repos" / name
    if not (source / ".git").exists():
        source.mkdir(parents=True)
        subprocess.run(["git", "init", str(source)], check=True, capture_output=True)
        git_env = os.environ.copy()
        git_env["GIT_AUTHOR_NAME"] = "Dev"
        git_env["GIT_AUTHOR_EMAIL"] = "dev@example.test"
        git_env["GIT_COMMITTER_NAME"] = "Dev"
        git_env["GIT_COMMITTER_EMAIL"] = "dev@example.test"
        (source / "README").write_text("hello\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(source), "add", "README"], check=True, capture_output=True)
        subprocess.run(["git", "-C", str(source), "commit", "-m", "init"], check=True, capture_output=True, env=git_env)
    before = subprocess.check_output(["git", "-C", str(source), "branch", "--show-current"], text=True).strip()
    made = worktree_add(pack, "TASK-995", name)
    side = os.path.join(os.environ["COCKPIT_WT"], "TASK-995", name)
    current = subprocess.check_output(["git", "-C", str(source), "branch", "--show-current"], text=True).strip()
    from cockpitlib.worktree import mode

    def pushurl(path):
        done = subprocess.run(
            ["git", "-C", str(path), "config", "--get", "remote.origin.pushurl"],
            capture_output=True,
            text=True,
            check=False,
        )
        return (done.stdout or "").strip()

    assert current == before
    assert os.path.isdir(side)
    assert side in made
    assert (
        subprocess.check_output(["git", "-C", side, "branch", "--show-current"], text=True).strip()
        == f"{pack['branch_prefix']}/TASK-995"
    )
    assert pushurl(source) == ""
    assert pushurl(side) == "DISABLED"
    assert mode("TASK-995", name, True) == "ALLOWED"
    assert pushurl(side) == ""
    assert pushurl(source) == ""
    assert worktree_add(pack, "TASK-995", name)
    assert pushurl(side) == ""
    assert mode("TASK-995", name, False) == "DISABLED"
    # an unset runtime with no slot provider is the worktree runtime too: the same folder, the repo's checkout unmoved
    unset = {key: value for key, value in pack.items() if key != "runtime"}
    unset["slot_provider"] = "none"
    assert worktree_add(unset, "TASK-994", name) == [os.path.join(os.environ["COCKPIT_WT"], "TASK-994", name)]
    assert subprocess.check_output(["git", "-C", str(source), "branch", "--show-current"], text=True).strip() == before


@pytest.mark.parametrize("pack_file", PACKS)
def test_open_ide_finds_the_ticket_of_any_pane_and_says_when_it_has_no_worktree(env, pack_file, monkeypatch):
    from cockpitlib import worktree
    from cockpitlib.outbox import create

    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    monkeypatch.delenv("COCKPIT_LANE", raising=False)
    pack = load(pack_file)
    ticket = f"{pack['tracker']['project']}-1601"
    repo = pack["repos"]["repos"][0]["name"]
    made = create(pack, ticket, "tracker-comment", "c", "note", {"body": f"hello {pack['name']}"})
    client = _client()
    bare = client.post("/open-ide", json={"id": made["id"]}).json()
    assert (
        bare["out"] == f"{ticket} has no worktree yet: the IDE opens on it once a lane makes one"
        and bare["worktrees"] == []
    )
    assert client.post("/open-ide", json={"id": f"{ticket}/099-tracker-comment"}).status_code == 404
    monkeypatch.setattr(
        worktree,
        "list_worktrees",
        lambda name: [{"repo": repo, "path": f"/wt/{name}/{repo}"}] if name == ticket else [],
    )
    opened = client.post("/open-ide", json={"ticket": ticket}).json()
    assert (
        opened["path"].endswith(f"ide-{ticket}.json")
        and json.load(open(opened["path"], encoding="utf-8"))["worktrees"][0]["repo"] == repo
    )
    other = f"{pack['tracker']['project']}-1602"
    filed = client.post(
        "/open-ide", json={"ticket": other, "file": "/x/intent.json"}
    ).json()  # a file opens whatever the worktrees
    assert json.load(open(filed["path"], encoding="utf-8"))["file"] == "/x/intent.json"
    assert client.post("/open-ide", json={}).json()["path"].endswith("ide-own.json")
