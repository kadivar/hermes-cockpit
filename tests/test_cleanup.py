# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""cockpitlib.cleanup: the pass over stale worktrees removes a ticket folder only when every gate passes, the Settings
page's worktree_gc turns the daily pass on (off by default), `cockpit worktree gc` and POST /worktree-gc run it by hand."""

import io
import json
import os
import shutil
import sqlite3
import subprocess
import time
from contextlib import redirect_stdout

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from cockpitlib.cleanup import DEFAULT_DAYS, gc, inventory, last_pass, run_if_due
from cockpitlib.cli import main
from cockpitlib.errors import CockpitError
from cockpitlib.kanban import db_path
from cockpitlib.pack import PackError, load
from cockpitlib.settings import load as load_settings
from cockpitlib.settings import save as save_settings
from cockpitlib.slots import write_owner, write_ticket
from dashboard.cockpit.router import router

OLD = time.time() - 30 * 86400
GIT_ENV = {
    **os.environ,
    "GIT_AUTHOR_NAME": "Dev",
    "GIT_AUTHOR_EMAIL": "dev@example.test",
    "GIT_COMMITTER_NAME": "Dev",
    "GIT_COMMITTER_EMAIL": "dev@example.test",
    "GIT_AUTHOR_DATE": "2025-01-01T00:00:00",
    "GIT_COMMITTER_DATE": "2025-01-01T00:00:00",
}


def _pack():
    return load(os.environ["COCKPIT_PACK"])


def _client():
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def _git(folder, *args):
    return subprocess.run(
        ["git", "-C", str(folder), *args], check=True, capture_output=True, text=True, env=GIT_ENV
    ).stdout


def _age(folder):
    for current, _dirs, files in os.walk(folder):
        for name in [current] + [os.path.join(current, f) for f in files]:
            os.utime(name, (OLD, OLD))


def _checkout(env, ticket, repo="api"):
    """A ticket checkout whose last commit is a year old and on origin (the fixture's init commit is dated now)."""
    source = env["root"] / "repos" / repo
    folder = env["root"] / "wt" / ticket / repo
    _git(source, "worktree", "add", "-q", str(folder), "-b", f"work/{ticket}")
    (folder / "start.txt").write_text("start\n", encoding="utf-8")
    _git(folder, "add", "start.txt")
    _git(folder, "commit", "-q", "-m", "start")
    _git(folder, "push", "-q", "origin", f"work/{ticket}")
    (env["root"] / "wt" / ticket / "NOTES.md").write_text("ticket\n", encoding="utf-8")
    return folder


def _copy_pack(tmp_path, suffix: str) -> str:
    """The acme pack copied under a packs/ folder (a fixture pack resolves @skills there), with lines appended."""

    copied = tmp_path / "packs" / "acme"
    if copied.exists():
        shutil.rmtree(copied)
    shutil.copytree(os.path.dirname(os.environ["COCKPIT_PACK"]), copied)
    (copied / "pack.yaml").write_text((copied / "pack.yaml").read_text(encoding="utf-8") + suffix, encoding="utf-8")
    return str(copied / "pack.yaml")


def _card(ticket, status="ready"):
    path = db_path("acme")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    connection = sqlite3.connect(path)
    connection.execute(
        "create table if not exists tasks (id text, title text, status text, result text, assignee text)"
    )
    connection.execute("insert into tasks values (?, ?, ?, '', 'worker-1')", (ticket, f"{ticket}: work", status))
    connection.commit()
    connection.close()


def test_every_gate_keeps_its_folder_and_the_stale_clean_one_goes(env):
    pack = _pack()
    clean = _checkout(env, "TASK-1")
    _age(clean.parent)
    dirty = _checkout(env, "TASK-2")
    (dirty / "README").write_text("changed\n", encoding="utf-8")
    _age(dirty.parent)
    held = _checkout(env, "TASK-3")
    _age(held.parent)
    write_owner(1, "lane:worker-1")
    write_ticket(1, "TASK-3")
    carded = _checkout(env, "TASK-4")
    _age(carded.parent)
    _card("TASK-4")
    _checkout(env, "TASK-5")  # touched now
    ahead = _checkout(env, "TASK-6")
    (ahead / "b.txt").write_text("b\n", encoding="utf-8")
    _git(ahead, "add", "b.txt")
    _git(ahead, "commit", "-q", "-m", "local only")
    _age(ahead.parent)
    stray = env["root"] / "wt" / "TASK-7 web"
    stray.mkdir()
    _age(stray)
    _card("TASK-1", "done")  # a done card is no reason to keep
    rows = {row["ticket"]: row["keep"] for row in inventory(pack)}
    assert rows["TASK-1"] == "" and rows["TASK-7 web"] == ""
    assert rows["TASK-2"] == "api has uncommitted changes"
    assert rows["TASK-3"] == "a slot holds it"
    assert rows["TASK-4"] == "open card: TASK-4: work"
    assert rows["TASK-5"].startswith("touched within 14 days")
    assert rows["TASK-6"] == "api has commits not on a remote"

    preview = gc(pack, dry_run=True)
    assert [item["ticket"] for item in preview["removed"]] == ["TASK-1", "TASK-7 web"] and preview["dry_run"]
    assert "would remove TASK-1 (up to" in preview["lines"][0] and preview["lines"][-1].startswith("would free up to")
    assert clean.exists()  # a preview removes nothing

    result = gc(pack)
    assert [item["ticket"] for item in result["removed"]] == ["TASK-1", "TASK-7 web"] and len(result["kept"]) == 5
    assert not clean.parent.exists() and not stray.exists()
    for ticket in ("TASK-2", "TASK-3", "TASK-4", "TASK-5", "TASK-6"):
        assert (env["root"] / "wt" / ticket / "api" / "README").exists()
    listed = _git(env["root"] / "repos" / "api", "worktree", "list", "--porcelain")
    assert str(clean) not in listed and str(dirty) in listed
    assert "work/TASK-1" in _git(env["root"] / "repos" / "api", "branch", "--list", "work/TASK-1")  # the branch stays
    assert (
        result["lines"][-1].startswith("freed up to")
        and "2 removed, 5 kept (untouched for 14 days)" in result["lines"][-1]
    )


def test_the_period_is_the_callers_and_checked(env):
    pack = _pack()
    folder = _checkout(env, "TASK-1")
    _age(folder.parent)
    assert inventory(pack, days=60)[0]["keep"].startswith("touched within 60 days")
    assert gc(pack, days=7, dry_run=True)["removed"][0]["ticket"] == "TASK-1"
    with pytest.raises(CockpitError, match="1 to 365"):
        gc(pack, days=0 - 1)
    with pytest.raises(CockpitError, match="1 to 365"):
        gc(pack, days=400)
    assert inventory(pack, days=0)[0]["keep"] == ""  # 0 = the default period


def test_the_daily_pass_waits_for_the_setting_and_runs_once_a_day(env):
    pack = _pack()
    folder = _checkout(env, "TASK-1")
    _age(folder.parent)
    assert load_settings(pack)["worktree_gc"] == {"enabled": False, "days": DEFAULT_DAYS}
    assert run_if_due(pack) == "off" and folder.exists() and last_pass() == {}
    save_settings(pack, {"settings": {"worktree_gc": {"enabled": True, "days": 10}}})
    assert load_settings(pack)["worktree_gc"] == {"enabled": True, "days": 10}
    now = time.time()
    assert run_if_due(pack, now=now) == "removed 1, kept 0, freed up to 0 KB" and not folder.exists()
    assert last_pass()["removed"] == ["TASK-1"] and last_pass()["days"] == 10
    _age((_checkout(env, "TASK-2")).parent)
    assert (
        run_if_due(pack, now=now + 3600) == "removed 1, kept 0, freed up to 0 KB (1h ago)"
    )  # throttled: the record's line
    assert (env["root"] / "wt" / "TASK-2").exists()
    assert (
        run_if_due(pack, now=now + 86401) == "removed 1, kept 0, freed up to 0 KB"
        and not (env["root"] / "wt" / "TASK-2").exists()
    )
    from cockpitlib.housekeeping import STEPS

    assert dict(STEPS)["worktree-gc"](pack).startswith("removed 1, kept 0")  # the step is wired: the record's line


def test_the_setting_is_saved_checked_and_overlaid(env, tmp_path):
    pack = _pack()
    saved = save_settings(pack, {"worktree_gc": {"enabled": "true", "days": "21"}})
    assert saved["worktree_gc"] == {"enabled": True, "days": 21}
    assert save_settings(pack, {"seats": {"intake": 1}})["worktree_gc"] == {
        "enabled": True,
        "days": 21,
    }  # untouched by another save
    with pytest.raises(CockpitError, match="numbers"):
        save_settings(pack, {"worktree_gc": {"enabled": "maybe"}})
    with pytest.raises(CockpitError, match="worktree_gc.days"):
        save_settings(pack, {"worktree_gc": {"days": 0}})
    path = env["workspace"] / "hermes" / "watch" / "settings.json"
    path.write_text(
        json.dumps({"seats": {"intake": 3}}), encoding="utf-8"
    )  # an overlay from before the setting: the default
    assert load_settings(pack)["worktree_gc"] == {"enabled": False, "days": DEFAULT_DAYS}
    path.unlink()
    assert load_settings(load(_copy_pack(tmp_path, "\nworktree_gc: {enabled: true, days: 30}\n")))["worktree_gc"] == {
        "enabled": True,
        "days": 30,
    }  # the pack sets the start state
    for bad, message in (
        (" {enabled: 1}", "true or false"),
        (" {days: 0}", "1 to 365"),
        (" {days: 2, extra: 1}", "enabled and days only"),
        (" 5", "enabled and days only"),
    ):
        with pytest.raises(PackError, match=message):
            load(_copy_pack(tmp_path, "\nworktree_gc:" + bad + "\n"))


def test_the_command_and_the_route_run_the_pass_by_hand(env):
    folder = _checkout(env, "TASK-1")
    _age(folder.parent)
    out = io.StringIO()
    with redirect_stdout(out):
        assert main(["worktree", "gc", "--dry-run", "--days", "7"]) == 0
    assert "would remove TASK-1 (up to" in out.getvalue() and folder.exists()
    for argv in (
        ["worktree", "gc", "--days"],
        ["worktree", "gc", "--days", "x"],
        ["worktree", "gc", "extra"],
        ["worktree", "gc", "--bogus"],
    ):
        with redirect_stdout(io.StringIO()):
            assert main(argv) == 2, argv
    client = _client()
    page = client.get("/settings").json()
    assert page["settings"]["worktree_gc"] == {"enabled": False, "days": DEFAULT_DAYS} and page["limits"][
        "worktree_gc_days"
    ] == [1, 365]
    assert page["worktree_gc"]["last"] == {}
    preview = client.post("/worktree-gc", json={"dry_run": True}).json()
    assert (
        preview["removed"][0]["ticket"] == "TASK-1"
        and preview["out"].startswith("would free up to")
        and folder.exists()
    )
    assert client.post("/settings", json={"settings": {"worktree_gc": {"enabled": True, "days": 5}}}).json()["ok"]
    assert client.get("/settings").json()["settings"]["worktree_gc"] == {"enabled": True, "days": 5}
    ran = client.post("/worktree-gc", json={}).json()
    assert ran["removed"][0]["ticket"] == "TASK-1" and not folder.exists() and ran["out"].startswith("freed up to")
    assert client.post("/worktree-gc", json={"days": 999}).status_code >= 400
    with redirect_stdout(io.StringIO()):
        assert main(["worktree", "gc"]) == 0
