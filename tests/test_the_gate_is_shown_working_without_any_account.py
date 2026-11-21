# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""`cockpit demo gate`: the outbox gate shown working in a sandbox under the temp folder, with no Hermes, no forge
account and no tracker. It runs on a machine with no bound workspace and on one bound elsewhere, and touches neither."""

import hashlib
import json
import os
import subprocess
import tempfile

import pytest

from cockpitlib import cli, demo, sandbox
from cockpitlib.errors import CockpitError


def _tree(folder: str) -> str:
    """One digest of every file and folder name under a folder, and of every file's content."""
    seen = hashlib.sha256()
    for where, dirs, files in os.walk(folder):
        dirs.sort()
        seen.update(where.encode())
        for name in sorted(files):
            seen.update(name.encode())
            with open(os.path.join(where, name), "rb") as handle:
                seen.update(handle.read())
    return seen.hexdigest()


@pytest.fixture
def temp(tmp_path, monkeypatch):
    """The temp folder the demo builds under, as this test's own: what is left there afterwards is the demo's."""
    folder = tmp_path / "temp"
    folder.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(folder))
    return folder


def test_the_whole_demo_runs_on_a_machine_with_no_workspace_and_leaves_nothing(temp, capsys, monkeypatch):
    for name in list(os.environ):
        if name.startswith("COCKPIT_") and name != "COCKPIT_HERMES_HOME":
            monkeypatch.delenv(name)
    assert cli.main(["demo", "gate", "--yes"]) == 0
    out = capsys.readouterr().out
    assert "REFUSED (hook exit 2): blocked: a denied command" in out and "git push origin work/DEMO-1" in out
    assert "(--yes: not waiting for Enter)" in out and "the same commit: the only way out was through the gate." in out
    order = [
        out.index(text)
        for text in (
            "REFUSED (hook exit 2)",
            "cockpit outbox new DEMO-1 push-branch",
            "cockpit outbox verify DEMO-1/001-push-branch",
            "cockpit outbox endorse DEMO-1/001-push-branch",
            "cockpit publish --id DEMO-1/001-push-branch --dry-run",
            "The remote now has the branch",
            "read back from the local forge: pull request #1",
            "read back from the local tracker: comment 1 on DEMO-1",
        )
    ]
    assert order == sorted(order)
    assert out.count("the remote still has no work/DEMO-1: nothing there") == 2, (
        "after the refusal and after the dry run"
    )
    assert os.listdir(temp) == [], "without --keep nothing remains"
    assert str(temp) in out and "<sandbox>" in out


def test_the_demo_leaves_a_bound_workspace_as_it_was_and_keep_leaves_the_sandbox(env, temp, capsys, monkeypatch):
    decoy = env["workspace"].parent
    (env["home"] / "cockpit.yaml").write_text(
        f"workspace: {env['workspace']}\npack: {os.environ['COCKPIT_PACK']}\n", encoding="utf-8"
    )
    (env["workspace"] / "note.txt").write_text("mine\n", encoding="utf-8")
    monkeypatch.setenv("COCKPIT_LANE", "worker-9")  # even from a lane's shell: the child shells are the demo's own
    before = {name: _tree(str(decoy / name)) for name in ("ws", "root", "hermes")}
    asked = []
    assert demo.gate(keep=True, ask=lambda text: asked.append(text) or "") == 0
    assert {name: _tree(str(decoy / name)) for name in ("ws", "root", "hermes")} == before, (
        "the bound workspace, its repos and the Hermes home"
    )
    assert asked == ["    Press Enter to publish, as the human: "]
    out = capsys.readouterr().out
    kept = [name for name in os.listdir(temp) if name.startswith("cockpit-demo-")]
    assert len(kept) == 1 and f"the sandbox is kept for you to look at: {os.path.realpath(temp / kept[0])}" in out
    base = temp / kept[0]
    remote = base / "forge" / "demo" / "app.git"
    sha = subprocess.run(
        ["git", "--git-dir", str(remote), "rev-parse", "work/DEMO-1"], capture_output=True, text=True, check=True
    ).stdout.strip()
    assert sha in out
    assert (
        json.loads((base / "forge" / "demo" / "app.json").read_text(encoding="utf-8"))["pulls"]["1"]["title"]
        == "DEMO-1: the change"
    )
    ticket = json.loads((base / "tracker" / "DEMO-1.json").read_text(encoding="utf-8"))
    assert [row["body"] for row in ticket["comments"]] == ["The pull request is open: one file, as asked."]
    assert sorted(
        name for name in os.listdir(base / "ws" / "hermes" / "outbox" / "DEMO-1") if name.endswith(".json")
    ) == ["001-push-branch.json", "002-open-pr.json", "003-tracker-comment.json"]


def test_the_verb_takes_gate_and_its_two_switches_and_nothing_else(capsys):
    assert cli.main(["demo"]) == 2 and cli.main(["demo", "lane"]) == 2 and cli.main(["demo", "gate", "extra"]) == 2
    assert cli.main(["demo", "gate", "--fast"]) == 2
    assert "cockpit demo gate [--yes] [--keep]" in capsys.readouterr().err


def test_a_shell_that_would_reach_outside_the_sandbox_runs_nothing(temp, tmp_path, monkeypatch):
    ran = []
    monkeypatch.setattr(subprocess, "run", lambda *args, **kwargs: ran.append(args))
    real = sandbox.shell

    def leaky(base, setenv, delenv, pack, **more):
        made = real(base, setenv, delenv, pack, **more)
        setenv("COCKPIT_VOLUMES", str(tmp_path / "elsewhere"))
        return made

    monkeypatch.setattr(sandbox, "shell", leaky)
    monkeypatch.setattr(sandbox, "repos", lambda *args, **kwargs: None)
    with pytest.raises(CockpitError, match=r"would reach outside its sandbox \(COCKPIT_VOLUMES\): nothing was run"):
        demo.gate(yes=True, say=lambda text: None)
    assert ran == [] and os.listdir(temp) == []
    one = demo.Demo(say=lambda text: None, yes=True)
    one.env.update({name: str(tmp_path / "elsewhere") for name in sandbox.PATHS})
    with pytest.raises(CockpitError, match="would reach outside its sandbox"):
        one.run(["true"])
    assert ran == []
    assert sandbox.outside(
        one.base, {**{name: os.path.join(one.base, "x") for name in sandbox.PATHS}, "GNUPGHOME": ""}
    ) == ["GNUPGHOME"]
    assert sandbox.outside(one.base, {name: one.base + "-twin/x" for name in sandbox.PATHS}) == list(sandbox.PATHS)


class _Done:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode, self.stdout, self.stderr = returncode, stdout, stderr


def _stubbed(monkeypatch, answers):
    """A demo whose child commands answer from a table keyed by a word of the command, without running anything."""
    said = []
    one = demo.Demo(say=said.append, yes=True)

    def run(argv, lane=False, stdin="", quiet=False, cwd=""):
        for word, done in answers.items():
            if word in argv:
                return done
        return _Done()

    monkeypatch.setattr(one, "run", run)
    return one, said


def test_a_sandbox_whose_pack_cannot_be_written_or_loaded_stops_the_demo(temp, monkeypatch):
    monkeypatch.setattr(sandbox, "repos", lambda *args, **kwargs: None)
    one, _said = _stubbed(monkeypatch, {"init": _Done(2, stderr="no starter here")})
    with pytest.raises(CockpitError, match="the demo could not write its pack: no starter here"):
        one.build()
    two, _said = _stubbed(monkeypatch, {"check": _Done(2, stderr="forge.kind is one of")})
    monkeypatch.setattr(two, "_local", lambda pack: None)
    with pytest.raises(CockpitError, match="the demo's pack does not load: forge.kind is one of"):
        two.build()


def test_a_step_that_does_not_do_what_it_shows_stops_the_demo_there(temp, monkeypatch):
    def played(answers, remote=("", "")):
        one, said = _stubbed(monkeypatch, answers)
        one.made = {"root": one.base}
        one.remote, one.repo, one.forge_root = "", "", ""
        one.env["COCKPIT_WT"], one.env["COCKPIT_WORKSPACE"] = os.path.join(one.base, "wt"), os.path.join(one.base, "ws")
        os.makedirs(os.path.join(one.base, "wt", "DEMO-1", "app"))
        os.makedirs(os.path.join(one.base, "ws", "hermes", "outbox", "DEMO-1"))
        open(os.path.join(one.base, "ws", "hermes", "outbox", "DEMO-1", "001-push-branch.json"), "w").close()
        monkeypatch.setattr(one, "git", lambda *argv, where="": "a" * 40)
        shas = iter(remote)
        monkeypatch.setattr(one, "remote_sha", lambda: next(shas, remote[-1]))
        return one

    refused = _Done(2, stdout=json.dumps({"message": "blocked: a denied command"}))
    hook = os.path.join(demo.PLUGIN_ROOT, "hooks", "egress.py")
    with pytest.raises(CockpitError, match=r"step 2: the hook did not refuse the push \(exit 0\)"):
        played({}).play()
    with pytest.raises(CockpitError, match="step 2: the hook did not refuse the push"):
        played({hook: _Done(2, stdout="not json")}).play()
    with pytest.raises(CockpitError, match=r"stopped at step 3 \(outbox new push-branch\): exit 1"):
        played({hook: refused, "new": _Done(1)}).play()
    with pytest.raises(CockpitError, match="step 9: the remote has nothing, the lane committed aaaa"):
        played({hook: refused}).play()
    one = demo.Demo(say=lambda text: None)
    one.repo = one.base
    with pytest.raises(CockpitError, match="the demo's git rev-parse work/none failed"):
        one.git("rev-parse", "work/none")
