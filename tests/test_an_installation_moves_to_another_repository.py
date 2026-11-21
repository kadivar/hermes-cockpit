# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""`cockpit update rehome <url>`: the checkout follows another repository whose branch holds the very tree installed, and
not one working file changes; a different tree, local edits, a clashing worktree or a lane are refused with nothing
changed; a step that fails takes the others back; `--undo` restores the branch, the remotes and the records; and
afterwards an update comes from the new origin."""

import json
import os
import subprocess

import pytest

from cockpitlib import egress, rehome, self_update
from cockpitlib.cli import main
from cockpitlib.errors import CockpitError


def _beside(name):
    """A helper module of tests/support, loaded by its path: the name `tests` may resolve to another folder on a machine
    whose checkout sits next to one."""
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        f"cockpit_tests_{name}", os.path.join(os.path.dirname(os.path.abspath(__file__)), "support", f"{name}.py")
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


git, install = _beside("update_kit").git, _beside("update_kit").install
REFUSED = (
    "cockpit update rehome https://example.test/team/cockpit.git",
    "cockpit update rehome --undo",
    "cockpit  update   rehome https://example.test/x.git --dry-run",
    "cd /tmp && /opt/tools/bin/cockpit update rehome --undo",
)


def _public(tmp_path, plugin, branch="main", name="public"):
    """A repository of one commit, unrelated to the installed history, whose tree is the installed tree. {url, work, commit,
    push(files)}: `push` adds a commit there."""
    url = tmp_path / f"{name}.git"
    subprocess.run(["git", "init", "-q", "--bare", str(url)], check=True)
    work = tmp_path / f"{name}-work"
    subprocess.run(["git", "init", "-q", "-b", branch, str(work)], check=True)
    git(work, "fetch", "-q", str(plugin), "HEAD")
    commit = git(work, "commit-tree", "FETCH_HEAD^{tree}", "-m", "the first public commit")
    git(work, "reset", "-q", "--hard", commit)
    git(work, "remote", "add", "origin", str(url))
    git(work, "push", "-q", "origin", branch)
    git(url, "symbolic-ref", "HEAD", f"refs/heads/{branch}")

    def push(files) -> str:
        for path, text in files.items():
            (work / path).write_text(text, encoding="utf-8")
        git(work, "add", "-A")
        git(work, "commit", "-q", "-m", "a public change")
        git(work, "push", "-q", "origin", branch)
        return git(work, "rev-parse", "HEAD")

    return {"url": str(url), "work": work, "commit": commit, "push": push}


def _disk(root) -> dict:
    """Every file of the working tree (git's own folder aside) as {path: (bytes, mtime_ns)}."""
    found = {}
    for folder, names, files in os.walk(root):
        if ".git" in names:
            names.remove(".git")
        for name in files:
            path = os.path.join(folder, name)
            found[os.path.relpath(path, root)] = (open(path, "rb").read(), os.lstat(path).st_mtime_ns)
    return found


def _git_state(root) -> dict:
    """What a move may change and a refusal may not: the remotes, the refs, HEAD and the checkout's own config."""
    return {
        "remotes": git(root, "remote", "-v"),
        "refs": git(root, "for-each-ref"),
        "head": git(root, "symbolic-ref", "HEAD"),
        "config": sorted(git(root, "config", "--local", "--list").splitlines()),
    }


@pytest.fixture
def made(tmp_path, monkeypatch):
    found = install(tmp_path)
    monkeypatch.setenv("COCKPIT_PLUGIN_ROOT", found["plugin"])
    calls = []
    monkeypatch.setattr(
        rehome,
        "_hermes",
        lambda op, what: calls.append(op) or {"recorded": True, "snapshot": "/h/.install-metadata.json.before-rehome"},
    )
    monkeypatch.setattr(self_update, "_record_hermes_revision", lambda name, revision: "")
    return {**found, "hermes": calls, "tmp": tmp_path}


def test_a_repository_with_the_same_tree_and_another_history_becomes_origin_and_no_file_changes(env, made, capsys):
    plugin, first = made["plugin"], made["first"]
    public = _public(made["tmp"], plugin)
    old_url = git(plugin, "remote", "get-url", "origin")
    open(os.path.join(plugin, "notes.txt"), "w", encoding="utf-8").write("an untracked file stays as it is\n")
    before = _disk(plugin)
    assert main(["update", "rehome", public["url"]]) == 0
    said = capsys.readouterr()
    done = json.loads(said.out)
    assert _disk(plugin) == before  # bytes and times, every file
    assert done["from"] == {"url": old_url, "branch": "master", "commit": first, "tree": done["to"]["tree"]}
    assert (
        done["to"]["commit"] == public["commit"] != first
        and done["to"]["branch"] == "main"
        and done["files_compared"] == 4
    )
    assert (
        git(plugin, "rev-parse", "HEAD") == public["commit"]
        and git(plugin, "rev-parse", "--abbrev-ref", "HEAD") == "main"
    )
    assert (
        subprocess.run(["git", "-C", plugin, "merge-base", first, "HEAD"], capture_output=True, check=False).returncode
        == 1
    )  # unrelated
    assert (
        git(plugin, "remote", "get-url", "origin") == public["url"]
        and git(plugin, "remote", "get-url", "previous") == old_url
    )
    assert git(plugin, "remote", "get-url", "--push", "previous") == "DISABLED"
    assert git(plugin, "rev-parse", "previous/master") == first  # the old refs are kept: the way back
    assert git(plugin, "rev-parse", "--abbrev-ref", "main@{u}") == "origin/main"
    assert git(plugin, "symbolic-ref", "refs/remotes/origin/HEAD") == "refs/remotes/origin/main"
    assert git(plugin, "rev-parse", "master") == first
    assert made["hermes"] == [{"op": "rehome", "name": "plugin", "source": public["url"], "revision": public["commit"]}]
    record = json.load(open(self_update._check_path(), encoding="utf-8"))
    assert record["branch"] == "main" and record["behind"] == 0 and record["local"] == public["commit"]
    assert record["rehomed_from"]["url"] == old_url and record["rehomed_from"]["commit"] == first
    assert (
        "setup --rerender" in said.err and "doctor" in said.err and said.err.rstrip().endswith("update rehome --undo")
    )
    assert "gateway restart" not in said.err  # no code changed
    # pushing to the old repository fails by itself now
    assert (
        subprocess.run(["git", "-C", plugin, "push", "previous", "master"], capture_output=True, check=False).returncode
        != 0
    )


def test_after_the_move_updates_are_checked_and_applied_from_the_new_origin(env, made):
    plugin = made["plugin"]
    public = _public(made["tmp"], plugin)
    rehome.rehome(public["url"], root=plugin)
    made["commit"]("the old repository goes on")  # and is no longer followed
    assert self_update.check(plugin)["remote"]["behind"] == 0
    assert json.load(open(self_update._check_path(), encoding="utf-8"))["rehomed_from"]["commit"] == made["first"]
    newer = public["push"]({"kernel/cockpitlib/a.py": "x = 'public'\n"})
    seen = self_update.check(plugin)
    assert seen["remote"]["behind"] == 1 and seen["remote"]["sha"] == newer and seen["remote"]["branch"] == "main"
    done = self_update.apply(plugin, restart=False)
    assert done["changed"] is True and git(plugin, "rev-parse", "HEAD") == newer
    assert open(os.path.join(plugin, "kernel", "cockpitlib", "a.py"), encoding="utf-8").read() == "x = 'public'\n"
    with pytest.raises(CockpitError, match="an update was applied since"):
        rehome.undo(plugin)
    assert git(plugin, "remote", "get-url", "origin") == public["url"]


def test_a_dry_run_compares_the_trees_and_changes_nothing(env, made, capsys):
    plugin = made["plugin"]
    public = _public(made["tmp"], plugin)
    before, state = _disk(plugin), _git_state(plugin)
    assert main(["update", "rehome", public["url"], "--branch", "main", "--dry-run"]) == 0
    done = json.loads(capsys.readouterr().out)
    assert done["dry_run"] is True and done["changed"] is False and done["from"]["tree"] == done["to"]["tree"]
    assert "the trees are equal" in done["out"] and done["to"]["commit"] == public["commit"]
    assert _disk(plugin) == before and _git_state(plugin) == state and made["hermes"] == []
    assert not os.path.exists(self_update._check_path())


def test_a_repository_with_another_tree_is_refused_with_both_hashes_and_nothing_changes(env, made):
    plugin = made["plugin"]
    public = _public(made["tmp"], plugin)
    other = public["push"]({"kernel/cockpitlib/a.py": "x = 'not what is installed'\n"})
    theirs, ours = git(public["work"], "rev-parse", "HEAD^{tree}"), git(plugin, "rev-parse", "HEAD^{tree}")
    before, state = _disk(plugin), _git_state(plugin)
    for dry in (False, True):
        with pytest.raises(
            CockpitError,
            match=f"refused: the tree of main at .* \\({other[:7]}\\) is {theirs} and the installed tree .* is {ours}",
        ):
            rehome.rehome(public["url"], dry_run=dry, root=plugin)
        assert _disk(plugin) == before and _git_state(plugin) == state and made["hermes"] == []


def test_a_checkout_with_local_edits_or_on_no_branch_is_refused(env, made):
    plugin = made["plugin"]
    public = _public(made["tmp"], plugin)
    path = os.path.join(plugin, "kernel", "cockpitlib", "a.py")
    open(path, "a", encoding="utf-8").write("# edited here\n")
    state = _git_state(plugin)
    with pytest.raises(CockpitError, match="local changes: commit or stash them before moving"):
        rehome.rehome(public["url"], root=plugin)
    assert _git_state(plugin) == state
    git(plugin, "checkout", "-q", "--", "kernel/cockpitlib/a.py")
    git(plugin, "checkout", "-q", "--detach")
    with pytest.raises(CockpitError, match="on no branch: put it on one first"):
        rehome.rehome(public["url"], root=plugin)
    with pytest.raises(CockpitError, match="is not a git checkout"):
        rehome.rehome(public["url"], root=str(made["tmp"]))


def test_a_linked_worktree_that_holds_the_branch_is_refused(env, made):
    plugin = made["plugin"]
    public = _public(made["tmp"], plugin)
    held = str(made["tmp"] / "beside")
    git(plugin, "worktree", "add", "-q", "-b", "main", held)
    state = _git_state(plugin)
    with pytest.raises(CockpitError, match="beside has the branch main checked out"):
        rehome.rehome(public["url"], root=plugin)
    assert _git_state(plugin) == state
    assert git(held, "rev-parse", "--abbrev-ref", "HEAD") == "main"


def test_a_url_or_a_branch_that_cannot_be_right_is_refused_before_anything_is_touched(env, made):
    plugin = made["plugin"]
    public = _public(made["tmp"], plugin)
    state = _git_state(plugin)
    for url, branch, said in (
        ("", "", "which repository"),
        ("--upload-pack=x", "", "which repository"),
        ("https://someone:secret@example.test/x.git", "", "carries a password"),
        (git(plugin, "remote", "get-url", "origin"), "", "already"),
        (public["url"], "-x", "is no branch name"),
        (public["url"], "a..b", "is no branch name"),
        (public["url"], "absent", "could not be fetched"),
        (str(made["tmp"] / "nowhere.git"), "", "did not answer"),
    ):
        with pytest.raises(CockpitError, match=said):
            rehome.rehome(url, branch=branch, root=plugin)
        assert _git_state(plugin) == state
    empty = made["tmp"] / "empty.git"
    subprocess.run(["git", "init", "-q", "--bare", str(empty)], check=True)
    with pytest.raises(CockpitError, match="names no default branch: say which one"):
        rehome.rehome(str(empty), root=plugin)
    for name, said in (("previous", "an earlier move left it"), ("rehome-incoming", "interrupted")):
        git(plugin, "remote", "add", name, public["url"])
        with pytest.raises(CockpitError, match=f"a remote named {name} exists .*{said}.* remote remove {name}"):
            rehome.rehome(public["url"], root=plugin)
        git(plugin, "remote", "remove", name)
    git(plugin, "remote", "rename", "origin", "upstream")
    with pytest.raises(CockpitError, match="no remote named origin"):
        rehome.rehome(public["url"], root=plugin)


@pytest.mark.parametrize("fails", ("hermes", "files", "status", "tree", "head", "remotes"))
def test_a_step_that_fails_takes_every_earlier_step_back(env, made, monkeypatch, fails):
    plugin = made["plugin"]
    public = _public(made["tmp"], plugin)
    self_update.check(plugin)
    record = open(self_update._check_path(), encoding="utf-8").read()
    before, state = _disk(plugin), _git_state(plugin)
    real_out = rehome._out
    if fails == "hermes":

        def helper(op, what):
            if op["op"] == "rehome":
                raise CockpitError("Hermes's install record was not updated: no helper")
            return {"restored": False}

        monkeypatch.setattr(rehome, "_hermes", helper)
    elif fails == "files":
        stamps = iter([{"a": (1, 1, 1)}, {"a": (2, 1, 1)}])
        monkeypatch.setattr(rehome, "_stamps", lambda root: next(stamps))
    else:
        seen = {"status": 0, "tree": 0}
        wrong = {
            "status": lambda args: (
                args[:2] == ("status", "--porcelain")
                and seen.__setitem__("status", seen["status"] + 1) is None
                and seen["status"] == 2
            ),
            "tree": lambda args: (
                args == ("rev-parse", "HEAD^{tree}")
                and seen.__setitem__("tree", seen["tree"] + 1) is None
                and seen["tree"] == 2
            ),
            "head": lambda args: args == ("rev-parse", "HEAD"),
            "remotes": lambda args: args == ("remote", "get-url", "previous"),
        }[fails]
        monkeypatch.setattr(
            rehome, "_out", lambda root, *args: "something else" if wrong(args) else real_out(root, *args)
        )
    with pytest.raises(
        CockpitError,
        match={
            "hermes": "no helper",
            "files": "working files changed: a",
            "status": "git's status",
            "tree": "not the one that was installed",
            "head": "not at the fetched commit",
            "remotes": "remotes are not as they were set",
        }[fails],
    ):
        rehome.rehome(public["url"], root=plugin)
    monkeypatch.setattr(rehome, "_out", real_out)
    assert _disk(plugin) == before and _git_state(plugin) == state
    assert open(self_update._check_path(), encoding="utf-8").read().replace(" ", "") == record.replace(" ", "")


def test_a_way_back_that_fails_too_is_said_with_the_failure(env, made, monkeypatch):
    plugin = made["plugin"]
    public = _public(made["tmp"], plugin)

    def helper(op, what):
        raise CockpitError(f"Hermes's install record was not {what}: no helper")

    monkeypatch.setattr(rehome, "_hermes", helper)
    monkeypatch.setattr(
        rehome, "_write_check", lambda data: (_ for _ in ()).throw(CockpitError("the record is read-only"))
    )
    state = _git_state(plugin)
    with pytest.raises(CockpitError, match="was not updated: no helper"):
        rehome.rehome(public["url"], root=plugin)
    assert _git_state(plugin) == state
    monkeypatch.setattr(
        rehome, "_hermes", lambda op, what: helper(op, what) if op["op"] == "restore_record" else {"recorded": True}
    )
    with pytest.raises(
        CockpitError, match="the record is read-only; and taking the move back failed at: .*was not restored: no helper"
    ):
        rehome.rehome(public["url"], root=plugin)
    assert git(plugin, "remote", "get-url", "origin") != public["url"]  # the git steps were still taken back


def test_undo_restores_the_branch_the_remotes_and_the_records(env, made, capsys):
    plugin, first = made["plugin"], made["first"]
    public = _public(made["tmp"], plugin)
    self_update.check(plugin)
    record = json.load(open(self_update._check_path(), encoding="utf-8"))
    before, state = _disk(plugin), _git_state(plugin)
    rehome.rehome(public["url"], root=plugin)
    assert main(["update", "rehome", "--undo"]) == 0
    done = json.loads(capsys.readouterr().out)
    assert (
        done["to"] == {"url": git(plugin, "remote", "get-url", "origin"), "branch": "master", "commit": first}
        and done["files_compared"] == 4
    )
    assert _disk(plugin) == before and _git_state(plugin) == state
    assert git(plugin, "rev-parse", "--abbrev-ref", "master@{u}") == "origin/master"
    assert json.load(open(self_update._check_path(), encoding="utf-8")) == record
    assert made["hermes"][-1] == {"op": "restore_record", "name": "plugin"}
    with pytest.raises(CockpitError, match="nothing to undo"):
        rehome.undo(plugin)
    # and the old repository is followed again
    newer = made["commit"]("the old repository goes on")
    assert self_update.apply(plugin, restart=False)["changed"] is True and git(plugin, "rev-parse", "HEAD") == newer


def test_a_move_onto_a_branch_of_the_same_name_is_undone_to_the_old_commit_and_upstream(bare, made, monkeypatch):
    # `bare` binds no update record of an earlier check here: the undo writes a plain one
    plugin, first = made["plugin"], made["first"]
    public = _public(made["tmp"], plugin, branch="master")
    git(plugin, "remote", "set-url", "--push", "origin", "https://example.test/push-here.git")
    before, state = _disk(plugin), _git_state(plugin)
    done = rehome.rehome(public["url"], root=plugin, now=100.0)
    assert done["to"]["branch"] == "master" and git(plugin, "rev-parse", "master") == public["commit"] != first
    assert (
        git(plugin, "rev-parse", "--abbrev-ref", "master@{u}") == "origin/master"
        and git(plugin, "rev-parse", "origin/master") == public["commit"]
    )
    assert _disk(plugin) == before
    rehome.undo(plugin, now=200.0)
    assert _disk(plugin) == before and _git_state(plugin) == state and git(plugin, "rev-parse", "master") == first
    assert json.load(open(self_update._check_path(), encoding="utf-8")) == {
        "local": first,
        "branch": "master",
        "checked_at": 200.0,
        "sha": "",
        "short": "",
        "behind": None,
        "error": "",
    }


def test_undo_is_refused_when_the_checkout_is_not_as_the_move_left_it(env, made, monkeypatch):
    plugin, first = made["plugin"], made["first"]
    public = _public(made["tmp"], plugin)
    git(plugin, "config", "cockpit.rehome", "not json")
    with pytest.raises(CockpitError, match="nothing to undo"):
        rehome.undo(plugin)
    git(plugin, "config", "--unset", "cockpit.rehome")
    rehome.rehome(public["url"], root=plugin)
    git(plugin, "remote", "add", "rehome-incoming", public["url"])
    with pytest.raises(CockpitError, match="the remotes are not as the move left them"):
        rehome.undo(plugin)
    git(plugin, "remote", "remove", "rehome-incoming")
    git(plugin, "branch", "-q", "-f", "master", "main")
    with pytest.raises(CockpitError, match=f"the branch master is no longer at {first[:7]}"):
        rehome.undo(plugin)
    git(plugin, "branch", "-q", "-f", "master", first)
    held = str(made["tmp"] / "beside")
    git(plugin, "worktree", "add", "-q", held, "master")
    with pytest.raises(CockpitError, match="beside has the branch master checked out"):
        rehome.undo(plugin)
    git(plugin, "worktree", "remove", held)
    note = json.loads(git(plugin, "config", "--get", "cockpit.rehome"))
    git(plugin, "config", "cockpit.rehome", json.dumps({**note, "commit": "0" * 40}))
    with pytest.raises(CockpitError, match="is not here with the installed tree"):
        rehome.undo(plugin)
    git(plugin, "config", "cockpit.rehome", json.dumps(note))
    stamps = iter([{"a": (1, 1, 1)}, {"a": (2, 1, 1)}])
    monkeypatch.setattr(rehome, "_stamps", lambda root: next(stamps))
    with pytest.raises(CockpitError, match="the move was taken back, and then: working files changed: a"):
        rehome.undo(plugin)
    assert git(plugin, "rev-parse", "--abbrev-ref", "HEAD") == "master"


def test_a_tracked_file_that_is_not_on_disk_is_compared_as_absent(env, made):
    plugin = made["plugin"]
    git(plugin, "update-index", "--assume-unchanged", "desktop/plugin.js")
    os.remove(os.path.join(plugin, "desktop", "plugin.js"))
    assert rehome._stamps(plugin)["desktop/plugin.js"] is None


@pytest.mark.parametrize("command", REFUSED)
def test_the_kernel_denies_a_lane_the_move(command):
    assert egress.check(command) == "blocked"
    assert any("rehome" in pattern for pattern in egress.KERNEL_DENY)


@pytest.mark.parametrize("lane", ("worker-1", "gatekeeper"))
def test_a_lane_cannot_move_the_installation_through_the_verb(env, made, monkeypatch, capsys, lane):
    public = _public(made["tmp"], made["plugin"])
    state = _git_state(made["plugin"])
    monkeypatch.setenv("COCKPIT_LANE", lane)
    for words in (["rehome", public["url"]], ["rehome", public["url"], "--dry-run"], ["rehome", "--undo"]):
        assert main(["update", *words]) == 1
        assert "updates stay with the human" in capsys.readouterr().err
    assert _git_state(made["plugin"]) == state


@pytest.mark.parametrize(
    "words",
    (
        ["rehome"],
        ["rehome", "--undo", "https://example.test/x.git"],
        ["rehome", "a", "b"],
        ["rehome", "https://example.test/x.git", "--to", "abc"],
        ["rehome", "--undo", "--dry-run"],
        ["rehome", "https://example.test/x.git", "--no-restart"],
        ["rehome", "https://example.test/x.git", "--branch"],
        ["apply", "--branch", "main"],
        ["check", "--dry-run"],
        ["rollback", "--undo"],
    ),
)
def test_a_command_line_that_is_no_move_is_refused_with_the_right_form(env, made, capsys, words):
    assert main(["update", *words]) == 2
    assert (
        "cockpit update rehome https://example.test/team/cockpit.git [--branch main] [--dry-run] | cockpit update rehome --undo"
        in capsys.readouterr().err
    )


def test_the_helper_is_asked_once_and_its_refusal_is_an_error(monkeypatch):
    from cockpitlib import hermes_runtime

    asked = []
    monkeypatch.setattr(
        hermes_runtime,
        "run_helper",
        lambda name, request: asked.append((name, request)) or {"results": [{"recorded": True}]},
    )
    assert rehome._hermes({"op": "rehome"}, "updated") == {"recorded": True}
    assert asked == [("plugins", {"ops": [{"op": "rehome"}]})]
    for answer, said in (
        ({"results": [{"error": "locked"}]}, "was not updated: locked"),
        ({"results": []}, "was not updated: no answer"),
        ({"results": [True]}, "no answer"),
    ):
        monkeypatch.setattr(hermes_runtime, "run_helper", lambda name, request, answer=answer: answer)
        with pytest.raises(CockpitError, match=said):
            rehome._hermes({"op": "rehome"}, "updated")
    monkeypatch.setattr(
        hermes_runtime, "run_helper", lambda name, request: (_ for _ in ()).throw(OSError("no runtime"))
    )
    with pytest.raises(CockpitError, match="was not restored: no runtime"):
        rehome._hermes({"op": "restore_record"}, "restored")


def test_the_plugins_helper_sets_source_and_revision_after_a_snapshot_and_restores_from_it(tmp_path, monkeypatch):
    import runpy
    import sys
    import types

    helper = runpy.run_path(
        os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "hermes_bridge", "plugins.py")
    )
    sidecar = tmp_path / ".install-metadata.json"
    stub = types.ModuleType("hermes_cli.plugins_cmd_git")
    stub._install_metadata_path = lambda: sidecar

    def update_record(name, update):
        data = json.loads(sidecar.read_text(encoding="utf-8")) if sidecar.exists() else {}
        record = update(data.get(name))
        if record is not None:
            data[name] = record
            sidecar.write_text(json.dumps(data), encoding="utf-8")

    stub._update_install_record = update_record
    monkeypatch.setitem(sys.modules, "hermes_cli", types.ModuleType("hermes_cli"))
    monkeypatch.setitem(sys.modules, "hermes_cli.plugins_cmd_git", stub)
    commit = "a" * 40
    # a plugin Hermes never installed: no record is made, and there is nothing to restore
    assert helper["_rehome"]({"name": "cockpit", "source": "https://example.test/new.git", "revision": commit}) == {
        "recorded": False,
        "snapshot": "",
    }
    assert helper["_restore_record"]({"name": "cockpit"}) == {"restored": False}
    was = {
        "cockpit": {"source": "https://example.test/old.git#sub", "revision": "b" * 40, "pinned": False},
        "other": {"source": "x", "revision": "c" * 40},
    }
    sidecar.write_text(json.dumps(was), encoding="utf-8")
    done = helper["_rehome"](
        {"name": "cockpit", "source": "https://someone:secret@example.test/new.git", "revision": commit}
    )
    assert done == {"recorded": True, "snapshot": str(sidecar) + ".before-rehome"}
    assert json.loads(open(done["snapshot"], encoding="utf-8").read()) == was
    now = json.loads(sidecar.read_text(encoding="utf-8"))
    assert (
        now["cockpit"] == {"source": "https://example.test/new.git#sub", "revision": commit, "pinned": False}
        and now["other"] == was["other"]
    )
    for bad in (
        {"name": "cockpit", "source": "", "revision": commit},
        {"name": "cockpit", "source": "https://example.test/x.git", "revision": "abc"},
    ):
        with pytest.raises(ValueError, match="a source and a 40-character commit"):
            helper["_rehome"](bad)
    # the others may have changed since: only this plugin's record goes back
    now["other"] = {"source": "y", "revision": "d" * 40}
    sidecar.write_text(json.dumps(now), encoding="utf-8")
    assert helper["_restore_record"]({"name": "cockpit"}) == {"restored": True}
    assert json.loads(sidecar.read_text(encoding="utf-8")) == {"cockpit": was["cockpit"], "other": now["other"]}
    assert helper["_restore_record"]({"name": "absent"}) == {"restored": False}
    assert helper["OPS"]["rehome"] is helper["_rehome"] and helper["OPS"]["restore_record"] is helper["_restore_record"]


def test_a_named_branch_that_is_not_the_repositorys_default_is_followed_all_the_same(env, made):
    plugin = made["plugin"]
    public = _public(made["tmp"], plugin)
    git(public["work"], "push", "-q", "origin", "main:release")
    public["push"]({"kernel/cockpitlib/a.py": "x = 'main went on'\n"})
    done = rehome.rehome(public["url"], branch="release", root=plugin)
    assert done["to"]["branch"] == "release" and git(plugin, "rev-parse", "HEAD") == public["commit"]
    assert git(plugin, "symbolic-ref", "refs/remotes/origin/HEAD") == "refs/remotes/origin/release"
    assert self_update.remote_branch(plugin) == "release" and self_update.check(plugin)["remote"]["behind"] == 0
