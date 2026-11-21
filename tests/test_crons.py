# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Cron scripts find cockpit without PATH, and the workspace watch writes local commits only."""

import json
import os
import subprocess

from cockpitlib.pack import load
from cockpitlib.state_commit import state_commit
from tests.support.boards import put_card


def _git(folder, *args):
    env = os.environ.copy()
    env["GIT_AUTHOR_NAME"] = "Dev"
    env["GIT_AUTHOR_EMAIL"] = "dev@example.test"
    env["GIT_COMMITTER_NAME"] = "Dev"
    env["GIT_COMMITTER_EMAIL"] = "dev@example.test"
    subprocess.run(["git", "-C", folder, *args], check=True, capture_output=True, env=env)


def _old(path):
    os.utime(path, (1_000_000_000, 1_000_000_000))


def test_state_commit_is_local_and_quiet(env):
    pack = load(os.environ["COCKPIT_PACK"])
    assert state_commit(pack) == "HOLD no git workspace"
    from cockpitlib.ops import workspace_watch

    assert workspace_watch(pack) == "no git workspace"
    health = json.load(
        open(os.path.join(str(env["workspace"]), "hermes", "watch", "workspace-watch.json"), encoding="utf-8")
    )
    assert health["ok"] is False and health["summary"] == "no git workspace"
    os.remove(os.path.join(str(env["workspace"]), "hermes", "watch", "workspace-watch.json"))
    assert pack["workspace_branch"] == "master"
    root = str(env["workspace"])
    _git(root, "init", "-b", "master")
    git_dir = subprocess.run(
        ["git", "-C", root, "rev-parse", "--git-dir"], check=True, capture_output=True, text=True
    ).stdout.strip()
    if not os.path.isabs(git_dir):
        git_dir = os.path.join(root, git_dir)
    for name in ("index.lock", "MERGE_HEAD", "CHERRY_PICK_HEAD", "REVERT_HEAD", "BISECT_LOG"):
        path = os.path.join(git_dir, name)
        open(path, "w", encoding="utf-8").write("x")
        assert name in state_commit(pack)
        os.remove(path)
    for name in ("rebase-merge", "rebase-apply"):
        path = os.path.join(git_dir, name)
        os.makedirs(path)
        assert name in state_commit(pack)
        os.rmdir(path)
    fresh = os.path.join(root, "hermes", "qa", "TASK-100", "note.txt")
    os.makedirs(os.path.dirname(fresh))
    open(fresh, "w", encoding="utf-8").write("now\n")
    assert "still changing" in state_commit(pack, quiet_seconds=10**9)
    _old(fresh)
    put_card("acme", "TASK-100: intake", "intake", "running")
    assert "still running" in state_commit(pack, quiet_seconds=0)
    kept = os.path.join(root, "hermes", "watch", "note.json")
    os.makedirs(os.path.dirname(kept), exist_ok=True)
    open(kept, "w", encoding="utf-8").write("{}\n")
    open(os.path.join(root, "hermes", "qa", "README"), "w", encoding="utf-8").write("human\n")
    sweep = os.path.join(root, "hermes", "outbox", "_sweep.requested")
    os.makedirs(os.path.dirname(sweep), exist_ok=True)
    open(sweep, "w", encoding="utf-8").write("x\n")
    record = os.path.join(root, "hermes", "qa", "TASK-200", "done.txt")
    os.makedirs(os.path.dirname(record))
    open(record, "w", encoding="utf-8").write("done\n")
    _old(record)
    platform = os.path.join(root, "hermes", "platform", "changes", "api-1.json")
    os.makedirs(os.path.dirname(platform))
    open(platform, "w", encoding="utf-8").write("{}\n")
    _old(platform)
    receipt = os.path.join(root, "hermes", "outbox", "_published.log")
    open(receipt, "w", encoding="utf-8").write("one\n")
    _old(receipt)
    made = state_commit(pack, quiet_seconds=0)
    assert "TASK-200" in made and "api-1.json" in made and "receipt log" in made
    logged = subprocess.run(["git", "-C", root, "log", "--oneline"], check=True, capture_output=True, text=True).stdout
    assert "TASK-200" in logged and "api-1.json" in logged
    assert (
        "origin" not in subprocess.run(["git", "-C", root, "remote"], check=True, capture_output=True, text=True).stdout
    )
    open(receipt, "a", encoding="utf-8").write("two\n")
    _old(receipt)
    assert "within the hour" in state_commit(pack, quiet_seconds=0)
    status = subprocess.run(
        ["git", "-C", root, "status", "--porcelain"], check=True, capture_output=True, text=True
    ).stdout
    assert "README" in status and "hermes/watch/" in status and "_sweep.requested" in status
    _git(root, "checkout", "-b", "elsewhere")
    held = os.path.join(root, "hermes", "qa", "TASK-300", "held.txt")
    os.makedirs(os.path.dirname(held))
    open(held, "w", encoding="utf-8").write("wait\n")
    _old(held)
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from cockpitlib.ops import workspace_watch
    from dashboard.cockpit.router import router

    text = workspace_watch(pack)
    assert text == "workspace is on elsewhere; workspace-watch commits only on master"
    assert (
        "TASK-300"
        not in subprocess.run(
            ["git", "-C", root, "log", "--oneline"], check=True, capture_output=True, text=True
        ).stdout
    )
    health = json.load(open(os.path.join(root, "hermes", "watch", "workspace-watch.json"), encoding="utf-8"))
    assert health["ok"] is False and health["fails"] == 1
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    row = next(item for item in client.get("/needs-you").json()["watchers"] if item["name"] == "workspace-watch")
    assert row["ok"] is False and "elsewhere" in row["reason"]
    _git(root, "checkout", "master")
    resumed = workspace_watch(pack)
    assert "TASK-300" in resumed
    health = json.load(open(os.path.join(root, "hermes", "watch", "workspace-watch.json"), encoding="utf-8"))
    assert health["ok"] is True and health["fails"] == 0
    assert all(item["name"] != "workspace-watch" for item in client.get("/needs-you").json()["watchers"])


def test_a_pack_with_no_branch_does_not_commit(env):
    root = str(env["workspace"])
    _git(root, "init", "-b", "master")
    _git(root, "commit", "--allow-empty", "-m", "init")
    note = os.path.join(root, "hermes", "qa", "TASK-100", "note.txt")
    os.makedirs(os.path.dirname(note))
    open(note, "w", encoding="utf-8").write("x\n")
    _old(note)
    from cockpitlib.ops import workspace_watch

    text = workspace_watch({"board": "acme", "name": "bare"})
    assert (
        text == "workspace-watch: records stay uncommitted (the pack names no workspace_branch)"
    )  # a choice, not a fault
    assert "master" not in text
    from cockpitlib.paths import watch_dir

    assert json.load(open(os.path.join(watch_dir(), "workspace-watch.json"), encoding="utf-8"))["ok"] is True
    logged = subprocess.run(["git", "-C", root, "log", "--oneline"], check=True, capture_output=True, text=True).stdout
    assert "TASK-100" not in logged
    status = subprocess.run(
        ["git", "-C", root, "status", "--porcelain"], check=True, capture_output=True, text=True
    ).stdout
    assert "hermes/" in status


def test_the_entry_points_run_on_a_bare_path(env):
    """Hermes cron and the shell hook run without a login PATH. `bin/cockpit` and `hooks/egress.py` must still start: on a host
    whose `python3` lacks PyYAML they re-exec on the plugin's .venv when it exists. With no arguments cockpit prints its usage (2)."""
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    bare = dict(os.environ, PATH="/usr/bin:/bin")
    done = subprocess.run([os.path.join(root, "bin", "cockpit")], check=False, capture_output=True, text=True, env=bare)
    assert done.returncode == 2 and "usage" in (done.stdout + done.stderr).lower(), done.stderr[-400:]
    hook = subprocess.run(
        [os.path.join(root, "hooks", "egress.py")],
        check=False,
        input='{"tool":"terminal","tool_input":{"command":"git status"}}',
        capture_output=True,
        text=True,
        env=bare,
    )
    assert hook.returncode == 0, hook.stderr[-400:]


def test_a_bare_path_gets_the_users_bin_folders(tmp_path):
    """A helper's probe started from cron must find a tool in ~/bin (kubectl, say): without it a healthy stack reads down."""
    import sys

    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    (tmp_path / "bin").mkdir()
    script = f"import os, runpy; runpy.run_path({os.path.join(root, 'bin', 'cockpit')!r}, run_name='entry'); print(os.environ['PATH'])"
    done = subprocess.run(
        [sys.executable, "-c", script],
        check=False,
        capture_output=True,
        text=True,
        env=dict(os.environ, PATH="/usr/bin:/bin", HOME=str(tmp_path)),
    )
    parts = done.stdout.strip().splitlines()[-1].split(os.pathsep)
    assert parts[:2] == ["/usr/bin", "/bin"] and str(tmp_path / "bin") in parts, done.stderr[-400:]


def test_the_slot_cleanup_cadence_comes_from_the_pack():
    """slots.gc_minutes: a pack whose tickets finish often frees a slot within minutes; without it the job stays hourly."""
    from cockpitlib.setup import cron_schedule

    assert cron_schedule({"slots": {"gc_minutes": 10}}, "slot-gc", "1h") == "10m"
    assert cron_schedule({"slots": {}}, "slot-gc", "1h") == "1h" and cron_schedule({}, "slot-gc", "1h") == "1h"
    import pytest

    from cockpitlib.pack import PackError, _slots

    with pytest.raises(PackError, match="gc_minutes"):
        _slots({"slots": {"provider": "command", "commands": {}, "gc_minutes": 0}})
