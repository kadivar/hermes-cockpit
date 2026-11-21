# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Cockpit updating itself: the status of the checkout against its repository, the hourly check, the Inbox row, and the
update (fast-forward, dependencies when they changed, bytecode, the Desktop bundle time, Hermes's record, the gateway)."""

import json
import os
import subprocess
import time

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from cockpitlib.errors import CockpitError
from dashboard.cockpit.router import router


def _client():
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def _git(folder, *args):
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "Dev",
        "GIT_AUTHOR_EMAIL": "dev@example.test",
        "GIT_COMMITTER_NAME": "Dev",
        "GIT_COMMITTER_EMAIL": "dev@example.test",
    }
    return subprocess.run(
        ["git", "-C", folder, *args], check=True, capture_output=True, text=True, env=env
    ).stdout.strip()


def _plugin_pair(tmp_path):
    """A plugin checkout with a bare origin that is one commit ahead once `advance` runs."""
    origin = tmp_path / "origin.git"
    subprocess.run(["git", "init", "-q", "--bare", str(origin)], check=True)
    seed = tmp_path / "seed"
    seed.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "master", str(seed)], check=True)
    (seed / "pyproject.toml").write_text("[project]\nname = 'x'\ndependencies = []\n", encoding="utf-8")
    (seed / "desktop").mkdir()
    (seed / "desktop" / "plugin.js").write_text("export {}\n", encoding="utf-8")
    (seed / "kernel" / "cockpitlib").mkdir(parents=True)
    (seed / "kernel" / "cockpitlib" / "a.py").write_text("x = 1\n", encoding="utf-8")
    import importlib.util  # by path: the name `tests` may resolve to another folder beside this checkout

    spec = importlib.util.spec_from_file_location(
        "cockpit_tests_update_kit", os.path.join(os.path.dirname(os.path.abspath(__file__)), "support", "update_kit.py")
    )
    kit = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(kit)
    kit.launcher(
        seed
    )  # the update runs the incoming tree's own `bin/cockpit pack check` before it moves: this one passes
    _git(str(seed), "add", "-A")
    _git(str(seed), "commit", "-q", "-m", "first")
    _git(str(seed), "remote", "add", "origin", str(origin))
    _git(str(seed), "push", "-q", "origin", "master")
    plugin = tmp_path / "plugin"
    subprocess.run(["git", "clone", "-q", "-b", "master", str(origin), str(plugin)], check=True)

    def advance(touch_pyproject=False, touch_desktop=False, message="second"):
        (seed / "kernel" / "cockpitlib" / "a.py").write_text(f"x = {time.time()}\n", encoding="utf-8")
        if touch_pyproject:
            (seed / "pyproject.toml").write_text("[project]\nname = 'x'\ndependencies = ['PyYAML']\n", encoding="utf-8")
        if touch_desktop:
            (seed / "desktop" / "plugin.js").write_text(f"export const v = {time.time()}\n", encoding="utf-8")
        _git(str(seed), "add", "-A")
        _git(str(seed), "commit", "-q", "-m", message)
        _git(str(seed), "push", "-q", "origin", "master")
        return _git(str(seed), "rev-parse", "HEAD")

    return str(plugin), advance


def test_status_check_and_the_inbox_row_follow_the_repository(env, tmp_path, monkeypatch):
    from cockpitlib import self_update

    plugin, advance = _plugin_pair(tmp_path)
    monkeypatch.setenv("COCKPIT_PLUGIN_ROOT", plugin)
    seen = self_update.status(plugin)
    assert (
        seen["installed"]["branch"] == "master"
        and seen["installed"]["follows"] == "origin/master"
        and seen["installed"]["subject"] == "first"
        and seen["dirty"] is False
        and seen["remote"] == {}
    )
    assert self_update.inbox_row() == {}
    assert self_update.check_if_due(plugin, now=1000.0) == "up to date"
    assert (
        self_update.check_if_due(plugin, now=1000.0 + 10) == "up to date"
    )  # within the hour: the record answers, no fetch
    newest = advance()
    assert self_update.check_if_due(plugin, now=1000.0 + 10) == "up to date"
    seen = self_update.check(plugin, now=5000.0)
    assert seen["remote"]["behind"] == 1 and seen["remote"]["sha"] == newest and seen["remote"]["error"] == ""
    assert self_update.check_if_due(plugin, now=5000.0 + 10) == "1 behind"
    row = self_update.inbox_row()
    assert row["name"] == "update" and "1 commit(s) behind" in row["reason"] and newest[:7] in row["reason"]
    body = _client().get("/needs-you").json()
    assert any(item["name"] == "update" for item in body["watchers"])
    shown = _client().get("/update").json()
    assert shown["remote"]["behind"] == 1 and shown["installed"]["short"] == seen["installed"]["short"]
    # a checkout that moved since the check no longer carries the count
    _git(plugin, "pull", "-q", "--ff-only", "origin", "master")
    assert self_update.status(plugin)["remote"]["behind"] is None and self_update.inbox_row() == {}
    # a local branch with no counterpart on origin (a fix branch checked out in place) still follows origin's default branch
    _git(plugin, "checkout", "-q", "-b", "live/fix")
    assert self_update.remote_branch(plugin) == "master"
    newest = advance(message="after the fix branch")
    seen = self_update.check(plugin, now=6000.0)
    assert (
        seen["remote"]["behind"] == 1
        and seen["remote"]["branch"] == "master"
        and seen["installed"]["branch"] == "live/fix"
        and seen["installed"]["follows"] == ""  # it follows nothing, and the page says so
    )
    done = self_update.apply(plugin, restart=False)
    assert done["to"] == newest[:7] and _git(plugin, "rev-parse", "--abbrev-ref", "HEAD") == "live/fix"
    _git(plugin, "checkout", "-q", "master")
    # an origin that does not answer is a recorded error, not a failure
    _git(plugin, "remote", "set-url", "origin", str(tmp_path / "gone.git"))
    seen = self_update.check(plugin, now=9000.0)
    assert seen["remote"]["error"] and seen["remote"]["behind"] is None
    assert self_update.check_if_due(plugin, now=20000.0).startswith("check skipped")


def test_apply_fast_forwards_refreshes_what_changed_and_asks_the_gateway_to_restart(env, tmp_path, monkeypatch):
    from cockpitlib import self_update

    plugin, advance = _plugin_pair(tmp_path)
    monkeypatch.setenv("COCKPIT_PLUGIN_ROOT", plugin)
    launched = []
    monkeypatch.setattr(self_update, "_spawn", lambda argv, wait=0.0: launched.append(list(argv)) or "")
    monkeypatch.setattr(self_update.shutil, "which", lambda name: "/usr/bin/hermes" if name == "hermes" else None)
    recorded = []
    monkeypatch.setattr(
        self_update, "_record_hermes_revision", lambda name, revision: recorded.append((name, revision)) or ""
    )
    done = self_update.apply(plugin, restart=True)
    assert done["changed"] is False and done["out"] == "already up to date" and launched == [] and recorded == []
    pip_log = tmp_path / "pip.log"
    os.makedirs(os.path.join(plugin, ".venv", "bin"), exist_ok=True)
    pip = os.path.join(plugin, ".venv", "bin", "pip")
    open(pip, "w", encoding="utf-8").write(f'#!/bin/sh\necho "$@" >> {pip_log}\n')
    os.chmod(pip, 0o755)
    os.makedirs(os.path.join(plugin, "kernel", "cockpitlib", "__pycache__"), exist_ok=True)
    old_entry = os.path.getmtime(os.path.join(plugin, "desktop", "plugin.js"))
    newest = advance(touch_pyproject=True)
    time.sleep(0.05)
    done = self_update.apply(plugin, restart=True, now=7000.0)
    assert (
        done["changed"] is True
        and done["to"] == newest[:7]
        and done["commits"]
        and done["commits"][0].endswith(" second")
    )
    assert done["pip"] == "dependencies refreshed" and "install -q -e ." in pip_log.read_text(encoding="utf-8")
    assert (
        not os.path.isdir(os.path.join(plugin, "kernel", "cockpitlib", "__pycache__")) and done["bytecode_cleared"] == 1
    )
    assert (
        done["desktop"] is False and os.path.getmtime(os.path.join(plugin, "desktop", "plugin.js")) == old_entry
    )  # nothing under desktop/ changed
    assert (
        launched == [["/usr/bin/hermes", "gateway", "restart"]]
        and recorded == [(os.path.basename(plugin), newest)]
        and done["restart"] == "requested"
    )
    assert self_update.status(plugin)["remote"]["behind"] == 0 and self_update.inbox_row() == {}
    # a second apply with nothing new restarts nothing; one without restart never launches
    advance(touch_desktop=True, message="third")
    done = self_update.apply(plugin, restart=False)
    assert (
        done["changed"] is True and done["restart"] == "skipped" and len(launched) == 1 and done["desktop"] is True
    )  # the bundle changed: the Desktop needs its restart
    # local edits refuse the update
    open(os.path.join(plugin, "kernel", "cockpitlib", "a.py"), "a", encoding="utf-8").write("# edited here\n")
    with pytest.raises(CockpitError, match="local changes"):
        self_update.apply(plugin)
    assert _client().get("/update").json()["dirty"] is True
    assert _client().post("/update-apply", json={}).status_code == 400
    _git(plugin, "checkout", "--", "kernel/cockpitlib/a.py")
    advance(message="fourth")
    shown = _client().post("/update-apply", json={"restart": False}).json()
    assert shown["ok"] and shown["changed"] is True and shown["restart"] == "skipped"
    assert _client().post("/update-check", json={}).json()["remote"]["behind"] == 0


def test_the_update_command_prints_the_status_the_check_and_the_apply(env, tmp_path, monkeypatch, capsys):
    from cockpitlib import self_update
    from cockpitlib.cli import main

    plugin, advance = _plugin_pair(tmp_path)
    monkeypatch.setenv("COCKPIT_PLUGIN_ROOT", plugin)
    monkeypatch.setattr(self_update, "_record_hermes_revision", lambda name, revision: "")
    assert main(["update"]) == 0 and json.loads(capsys.readouterr().out)["installed"]["subject"] == "first"
    advance()
    assert main(["update", "check"]) == 0 and json.loads(capsys.readouterr().out)["remote"]["behind"] == 1
    assert main(["update", "apply", "--no-restart"]) == 0
    printed = capsys.readouterr()
    assert json.loads(printed.out)["changed"] is True  # the JSON stays whole on stdout
    assert (
        printed.err.startswith("# after the update, run:\n")
        and " setup --rerender && " in printed.err
        and " doctor" in printed.err
    )
    assert os.path.join(plugin, "bin", "cockpit") in printed.err  # the launcher by its real path, not a bare `cockpit`
    assert main(["update", "nope"]) == 2 and main(["update", "apply", "--now"]) == 2


def test_the_line_left_to_the_human_after_an_update_is_one_line_for_this_machines_shell(env, tmp_path, monkeypatch):
    from cockpitlib import after_update, self_update
    from cockpitlib.paths import hermes_home

    plugin, advance = _plugin_pair(tmp_path)
    monkeypatch.setenv("COCKPIT_PLUGIN_ROOT", plugin)
    monkeypatch.setattr(self_update, "_record_hermes_revision", lambda name, revision: "")
    monkeypatch.setattr(after_update, "_platform", lambda: "linux")
    monkeypatch.setattr(
        after_update.shutil, "which", lambda name: "/opt/hermes/bin/hermes" if name == "hermes" else None
    )
    script = os.path.join(plugin, "bin", "cockpit")
    # nothing changed: nothing to run
    assert after_update.after({"changed": False}) == {"steps": [], "line": ""}
    assert self_update.apply(plugin, restart=False)["next"] == {"steps": [], "line": ""}
    # the launcher: the link setup made under the Hermes home's bin; the checkout's own script on a machine without it
    link = os.path.join(hermes_home(), "bin", "cockpit")
    if not os.path.exists(
        link
    ):  # the fixture's link may point at a plugin root this test does not have: a real launcher file stands in
        os.makedirs(os.path.dirname(link), exist_ok=True)
        if os.path.lexists(link):
            os.remove(link)
        open(link, "w", encoding="utf-8").write("#!/bin/sh\n")
    assert after_update.launcher("cockpit", plugin) == link
    with monkeypatch.context() as bare:
        bare.setenv("COCKPIT_HERMES_HOME", str(tmp_path / "other-home"))
        assert after_update.launcher("cockpit", plugin) == script
    assert link in self_update.inbox_row().get("reason", link)  # the Inbox row names it too (when there is a row)
    # an update the gateway restart was asked for: the seats, then doctor; the Desktop untouched when its UI did not change
    advance()
    done = self_update.apply(plugin, restart=False, now=100.0)  # restart skipped: the line restarts the gateway first
    assert [step["what"] for step in done["next"]["steps"]] == [
        "restart the gateway",
        "re-render the seats on the new kernel",
        "check the install",
    ]
    assert done["next"]["line"] == f"/opt/hermes/bin/hermes gateway restart && {link} setup --rerender && {link} doctor"
    requested = after_update.after({"changed": True, "restart": "requested", "desktop": False}, plugin)
    assert requested["line"] == f"{link} setup --rerender && {link} doctor"
    # the Desktop's UI changed: on macOS the line quits and starts it again; elsewhere it ends on the reminder
    monkeypatch.setattr(after_update, "_platform", lambda: "darwin")
    mac = after_update.after({"changed": True, "restart": "requested", "desktop": True}, plugin)["line"]
    assert mac.endswith("doctor && osascript -e 'quit app \"Hermes\"' && sleep 3 && open -a Hermes")
    monkeypatch.setattr(after_update, "_platform", lambda: "linux")
    assert after_update.after({"changed": True, "restart": "requested", "desktop": True}, plugin)["line"].endswith(
        "&& echo 'now quit the Hermes Desktop and start it again'"
    )
    # Windows: the script through the checkout's venv python when it exists, else py -3; double quotes; hermes by its path
    monkeypatch.setattr(after_update, "_os_name", lambda: "nt")
    assert after_update.launcher("cockpit", plugin) == f'py -3 "{script}"'
    os.makedirs(os.path.join(plugin, ".venv", "Scripts"), exist_ok=True)
    open(os.path.join(plugin, ".venv", "Scripts", "python.exe"), "w", encoding="utf-8").write("")
    python = os.path.join(plugin, ".venv", "Scripts", "python.exe")
    assert after_update.launcher("cockpit", plugin) == f'"{python}" "{script}"'
    win = after_update.after({"changed": True, "restart": "hermes not found", "desktop": True}, plugin)
    assert win["line"] == (
        f'"/opt/hermes/bin/hermes" gateway restart && "{python}" "{script}" setup --rerender && "{python}" "{script}" doctor '
        '&& echo "now quit the Hermes Desktop and start it again"'
    )
    monkeypatch.setattr(after_update.shutil, "which", lambda name: None)
    assert after_update.hermes_command() == "hermes"
