# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The starter pack is real: each skill a scaffolded pack names is there under its own name, every cockpit command a
starter text cites is one the kernel takes, and each example script answers the contract it is an example of."""

import json
import os
import re
import shlex
import subprocess

import pytest
import yaml

from cockpitlib import cli, helpers, intents, notify, scaffold, tracker
from cockpitlib.pack import load
from cockpitlib.paths import binding_file

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STARTER = os.path.join(ROOT, "starter")
SKILLS = ("implement", "open-pr", "pr-review", "self-review", "test-plan", "ticket-intake", "tracker-notes")
BIN = os.path.join(STARTER, "bin")


def _texts() -> dict:
    found = {}
    for base, _dirs, names in os.walk(STARTER):
        for name in names:
            if name.endswith(".md"):
                found[os.path.relpath(os.path.join(base, name), ROOT)] = open(
                    os.path.join(base, name), encoding="utf-8"
                ).read()
    return found


# ---------- the skills ----------


def test_the_starter_holds_the_seven_skills_each_named_as_its_folder():
    assert scaffold.starter_skills() == sorted(SKILLS)
    for name in SKILLS:
        text = open(os.path.join(STARTER, "skills", name, "SKILL.md"), encoding="utf-8").read()
        assert text.startswith("---\n"), name
        front = yaml.safe_load(text.split("---\n")[1])
        assert sorted(front) == ["description", "name"] and front["name"] == name and len(front["description"]) > 40, (
            name
        )
        assert "\nDo not " in text and re.search(r"(?m)^1\. ", text), (
            f"{name}: numbered steps and explicit Do not lines"
        )
        assert 40 <= len(text.splitlines()) <= 200, name


def test_every_skill_a_scaffolded_pack_names_is_in_the_starter():
    named = {
        skill for wanted in [*scaffold.KICKOFF_SKILLS.values(), *scaffold.INTENT_SKILLS.values()] for skill in wanted
    }
    assert named == set(SKILLS), "a starter skill no card would load, or a card naming a skill that is not there"
    assert set(scaffold.INTENT_SKILLS) <= set(intents.TYPES)
    assert os.path.isfile(os.path.join(STARTER, "souls", "common.md"))


def _cited() -> list:
    """(file, command) for each cockpit command in a starter text: a line of a fenced block, or a code span."""
    found = []
    for name, text in _texts().items():
        spans = re.findall(r"`(cockpit [^`\n]+)`", text)
        for block in re.findall(r"```sh\n(.*?)```", text, re.S):
            spans += [line.strip() for line in block.splitlines() if line.strip().startswith("cockpit ")]
        found += [(name, span) for span in spans]
    return found


OUTBOX_ACTS = ("new", "amend", "show", "verify")
SUBVERBS = {
    "plan": ("init", "append", "show", "sections"),
    "test": ("plan", "fail", "run-dir"),
    "flow": ("decompose", "reopen"),
    "pack": ("check", "effective", "explain"),
}
SELF_FLAGS = {"advise": {"--ticket", "--card", "--said"}, "test": set(), "flow": set()}


@pytest.mark.parametrize("name, command", _cited(), ids=lambda value: value if " " not in str(value) else None)
def test_a_cockpit_command_a_starter_text_cites_is_one_the_kernel_takes(name, command):
    words = shlex.split(re.sub(r"<[^>]+>", "PLACEHOLDER", command))
    verb = words[1]
    assert verb in cli.COMMANDS, f"{name}: {command}"
    flags = [word for word in words[2:] if word.startswith("--")]
    if verb == "outbox":
        assert words[2] in OUTBOX_ACTS, command
        values, switches = cli._payload_flags()
        assert [
            flag for flag in flags if flag not in values | switches | cli.OUTBOX_VALUES | cli.OUTBOX_SWITCHES
        ] == [], command
        if words[2] == "new":
            kind = words[4]
            assert kind in intents.TYPES, command
            required, optional, _one_of = intents.SCHEMAS[kind]
            fields = {"--" + field.replace("_", "-") for field in (*required, *optional)}
            assert [flag for flag in flags if flag not in fields | {"--card", "--summary"}] == [], (
                f"{command}: not a flag of {kind}"
            )
            assert [
                flag for flag in ("--" + field.replace("_", "-") for field in required) if flag not in flags
            ] == [], f"{command}: a required flag is missing"
            assert "--card" in flags and "--summary" in flags, command
        return
    if verb in SUBVERBS:
        assert words[2] in SUBVERBS[verb], command
    allowed = SELF_FLAGS[verb] if verb in cli.SELF_PARSED else cli.FLAGS.get(verb, set())
    assert [flag for flag in flags if flag not in allowed] == [], f"{name}: {command}"


def test_the_starter_texts_cite_commands_and_the_guard_scans_the_starter():
    cited = {command.split()[1] for _name, command in _cited()}
    assert {"outbox", "plan", "gate", "advise", "test", "flow"} <= cited
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "grep_tokens_for_starter", os.path.join(ROOT, "tests", "guards", "grep_tokens.py")
    )
    guard = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(guard)
    assert "starter" in guard.SCAN and guard.main() == 0


# ---------- the scripts, each against its contract ----------


@pytest.fixture
def state(tmp_path, monkeypatch):
    monkeypatch.setenv("COCKPIT_STARTER_STATE", str(tmp_path / "state"))
    return tmp_path / "state"


def _run(name, *argv, stdin="", **env):
    return subprocess.run(
        [os.path.join(BIN, name), *argv],
        input=stdin,
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, **env},
    )


def test_every_script_is_executable_and_says_its_contract_at_the_top():
    assert sorted(os.listdir(BIN)) == ["helper", "notify", "slot", "tracker", "verify"]
    for name in os.listdir(BIN):
        path = os.path.join(BIN, name)
        assert os.access(path, os.X_OK), name
        assert "Contract (" in open(path, encoding="utf-8").read(), name


def test_notify_gets_the_body_on_stdin_and_the_event_in_its_environment(state):
    pack = {"notify": {"ready_for_review": ["bin/notify"]}, "_dir": STARTER}
    sent, detail = notify.run(
        pack, "ready_for_review", "TASK-100: two pull requests wait for you\n", key="TASK-100 api#12"
    )
    assert sent is True and detail.startswith("notify ready_for_review sent ")
    kept = (state / "notify.log").read_text(encoding="utf-8")
    assert " ready_for_review TASK-100 api#12\nTASK-100: two pull requests wait for you\n" in kept
    failed = _run("notify", stdin="body", COCKPIT_EVENT="")
    assert failed.returncode == 1 and "COCKPIT_EVENT is not set" in failed.stderr


def test_the_tracker_answers_each_act_the_kernel_sends_it(state, tmp_path):
    kept = tracker.CommandTracker({"command": [os.path.join(BIN, "tracker")]})
    url, key, extra = kept.create(
        {
            "ticket": "TASK-100",
            "payload": {"summary": "The export has no header", "project": "TASK", "body": "seen on run 1"},
        },
        [],
    )
    assert key == "TASK-1" and extra == {"key": "TASK-1"} and url.endswith("tracker.json#TASK-1")
    assert kept.create({"ticket": "", "payload": {"summary": "second"}}, [])[1] == "TASK-2"
    assert kept.summary("TASK-1") == "The export has no header"
    note = tmp_path / "note.md"
    note.write_text("Tested and Not Ok\n", encoding="utf-8")
    url, said, extra = kept.comment(
        {"ticket": "TASK-1", "payload": {"body_file": str(note), "attach": ["evidences/3.png"]}}, []
    )
    assert said == "comment 1" and extra == {"comment": "1"} and url.endswith("#TASK-1")
    assert kept.comment({"ticket": "TASK-1", "payload": {"issue": "TASK-1", "body": "again"}}, [])[1] == "comment 2"
    assert kept.transition({"ticket": "TASK-1", "payload": {"to": "In Review"}}, [], "TASK-1")[1] == "In Review"
    stored = json.loads((state / "tracker.json").read_text(encoding="utf-8"))
    assert stored["TASK-1"]["status"] == "In Review" and [row["body"] for row in stored["TASK-1"]["comments"]] == [
        "Tested and Not Ok\n",
        "again",
    ]
    assert stored["TASK-1"]["comments"][0]["attach"] == ["evidences/3.png"]
    assert all(row["author"] == "me" and row["created"] for row in stored["TASK-1"]["comments"])
    assert [method["method"] for method in kept.writes] == ["create", "create", "comment", "comment", "transition"], (
        "a summary is a read"
    )
    from cockpitlib.errors import CockpitError

    with pytest.raises(CockpitError, match="a transition names the status"):
        kept.transition({"ticket": "TASK-1", "payload": {}}, [], "TASK-1")
    with pytest.raises(CockpitError, match="names no issue"):
        kept.comment({"payload": {"body": "x"}}, [])
    # the reads a pack names in tracker.reads: the comments with who wrote them and when, who the command is, the status
    reader = tracker.CommandTracker({"command": [os.path.join(BIN, "tracker")], "reads": ["comments", "me", "status"]})
    rows = reader.comments("TASK-1")
    assert [(row["id"], row["account"], row["text"]) for row in rows] == [
        ("1", "me", "Tested and Not Ok"),
        ("2", "me", "again"),
    ]
    assert (
        all(row["created"] and row["updated"] == row["created"] for row in rows)
        and rows[0]["created"] < rows[1]["created"]
    )
    assert [row["id"] for row in reader.comments("TASK-1", since=rows[1]["created"])] == ["2"]
    assert reader.me() == "me" and reader.status("TASK-1") == "In Review"
    assert (
        reader.comment(
            {
                "ticket": "TASK-1",
                "payload": {"body": "again, corrected", "comment_id": "2", "attach": ["evidences/4.png"]},
            },
            [],
        )[1]
        == "comment 2"
    )
    edited = reader.comments("TASK-1")[1]
    assert edited["text"] == "again, corrected" and edited["updated"] > edited["created"]
    with pytest.raises(CockpitError, match="TASK-1 has no comment 9"):
        reader.comment({"ticket": "TASK-1", "payload": {"body": "x", "comment_id": "9"}}, [])
    assert _run("tracker", stdin="{}", COCKPIT_TRACKER_ACTION="delete").returncode == 2
    assert _run("tracker", stdin="not json", COCKPIT_TRACKER_ACTION="comment").returncode == 2
    (state / "tracker.json").write_text("not json", encoding="utf-8")
    assert kept.summary("TASK-9") == ""


def test_a_slot_verb_answers_with_the_four_exit_codes_and_status_is_json(state, tmp_path):
    assert set(helpers.CODES) == {0, 1, 2, 3}, "the slot runtime's contract, which a helper shares"
    assert json.loads(_run("slot", "status", "1").stdout) == {"slot": 1, "state": "stopped", "data": False, "since": 0}
    assert _run("slot", "ready", "1").returncode == 1
    assert _run("slot", "up", "1", SLOT_DEPENDENCY=str(tmp_path / "absent")).returncode == 3
    assert _run("slot", "up", "1", SLOT_WARM_SECONDS="60").returncode == 2, "still working"
    assert _run("slot", "ready", "1", SLOT_WARM_SECONDS="60").returncode == 2
    assert json.loads(_run("slot", "status", "1", SLOT_WARM_SECONDS="60").stdout)["state"] == "working"
    assert _run("slot", "up", "1").returncode == 0 and _run("slot", "ready", "1").returncode == 0, (
        "a second up is the same slot"
    )
    told = json.loads(_run("slot", "status", "1").stdout)
    assert (told["state"], told["data"]) == ("running", True) and told["since"] > 0
    assert _run("slot", "reset", "1").returncode == 1, "a running slot's data is not wiped"
    assert _run("slot", "down", "1").returncode == 0 and _run("slot", "down", "1").returncode == 0
    assert _run("slot", "reset", "1").returncode == 0 and _run("slot", "reset", "1").returncode == 0
    assert json.loads(_run("slot", "status", "1").stdout)["data"] is False
    for argv in (["up"], ["nope", "1"], ["up", "one"]):
        assert _run("slot", *argv).returncode == 1 and "usage: slot" in _run("slot", *argv).stderr


def test_a_helper_answers_with_the_same_codes_and_its_status_lines_are_the_ones_the_kernel_reads(state):
    assert _run("helper", "web", "status").stdout == "web: stopped\n"
    assert _run("helper", "web", "start", HELPER_NEEDS="db").returncode == 3
    assert (
        _run("helper", "db", "start").returncode == 0
        and _run("helper", "web", "start", HELPER_NEEDS="db").returncode == 0
    )
    lines = _run("helper", "all", "status").stdout.splitlines()
    parsed = [helpers.STATUS_LINE.match(line) for line in lines]
    assert all(parsed) and sorted((row["name"], row["state"]) for row in parsed) == [
        ("db", "running"),
        ("web", "running"),
    ]
    assert _run("helper", "web", "stop").stdout == "web: stopped\n" and helpers.STATUS_LINE.match("web: stopped")
    assert _run("helper", "web", "restart").returncode == 1 and _run("helper", "web").returncode != 0


def test_verify_holds_a_push_whose_file_has_a_conflict_marker_as_the_kernel_runs_it(tmp_path):
    from cockpitlib.outbox import _run_verify

    repo = tmp_path / "api"
    repo.mkdir()
    git = ["git", "-C", str(repo), "-c", "user.email=dev@example.test", "-c", "user.name=Dev"]
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    (repo / "clean.txt").write_text("fine\n", encoding="utf-8")
    (repo / "--odd.txt").write_text("fine\n", encoding="utf-8")
    subprocess.run([*git, "add", "."], check=True)
    subprocess.run([*git, "commit", "-q", "-m", "one"], check=True)
    head = subprocess.run([*git, "rev-parse", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()
    pack = {"_dir": STARTER}
    rule = {"verify": [["{pack}/bin/verify", "{files}"]]}
    payload = {"repo": "api", "sha": head, "files": ["clean.txt", "--odd.txt", "deleted.txt"]}
    assert _run_verify(pack, rule, payload, str(repo)) == []
    (repo / "merged.txt").write_text("a\n<<<<<<< ours\nb\n=======\nc\n>>>>>>> theirs\n", encoding="utf-8")
    subprocess.run([*git, "add", "."], check=True)
    subprocess.run([*git, "commit", "-q", "-m", "two"], check=True)
    head = subprocess.run([*git, "rev-parse", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()
    assert _run_verify(pack, rule, {**payload, "sha": head, "files": ["clean.txt", "merged.txt"]}, str(repo)) == [
        "verify verify failed on the pushed range: verify: merged.txt still holds a merge-conflict marker"
    ]


# ---------- init copies the starter in ----------


@pytest.fixture
def machine(tmp_path, monkeypatch):
    home = tmp_path / "h"
    home.mkdir()
    (home / "config.yaml").write_text("model:\n  provider: alpha\n  default: big-1\n", encoding="utf-8")
    monkeypatch.setenv("COCKPIT_HERMES_HOME", str(home))
    monkeypatch.setenv("COCKPIT_HUMAN", "1")
    monkeypatch.setattr(scaffold, "CODING_TOOLS", ("no-such-coding-tool",))
    for name in ("COCKPIT_WORKSPACE", "COCKPIT_PACK", "COCKPIT_ROOT"):
        monkeypatch.delenv(name, raising=False)
    workspace = tmp_path / "w" / "ws"
    workspace.mkdir(parents=True)
    return {"home": home, "workspace": workspace, "pack": workspace / "cockpit-pack"}


def test_init_copies_the_starter_and_the_pack_it_writes_uses_it(machine, monkeypatch, capsys):
    assert cli.main(["init", str(machine["workspace"]), "--no-production", "--write"]) == 0
    assert "tracker     command" in capsys.readouterr().out
    pack = load(str(machine["pack"] / "pack.yaml"))
    for name in SKILLS:
        assert (machine["pack"] / "skills" / name / "SKILL.md").read_text() == open(
            os.path.join(STARTER, "skills", name, "SKILL.md")
        ).read()
    assert all(os.access(machine["pack"] / "bin" / name, os.X_OK) for name in os.listdir(BIN))
    assert pack["skills"]["kickoff"]["rework"] == ["implement", "self-review", "open-pr", "cockpit:outbox"]
    assert pack["skills"]["kickoff"]["bumps"] == ["cockpit:outbox"] and pack["skills"]["intent"][
        "pr-review-submit"
    ] == ["pr-review"]
    assert (
        pack["seat_config"]["_common"]["soul"].endswith("souls/common.md")
        and (machine["pack"] / "souls" / "common.md").is_file()
    )
    assert pack["tracker"] == {
        "kind": "command",
        "command": [str(machine["pack"] / "bin" / "tracker")],
        "reads": ["comments", "me", "status"],
        "url": "https://tracker.example.test",
        "project": "TASK",
    }
    monkeypatch.setenv("COCKPIT_STARTER_STATE", str(machine["workspace"] / "state"))
    kept = tracker.tracker_for(pack)
    assert kept.comment({"ticket": "TASK-100", "payload": {"body": "a first note"}}, [])[1] == "comment 1"
    from cockpitlib.setup import _soul

    monkeypatch.setenv("COCKPIT_WORKSPACE", str(machine["workspace"]))
    assert "Nothing leaves this machine by your hand." in _soul(pack, "worker-1", "worker")
    assert not (machine["pack"] / "README.md").exists(), "the starter's own README stays with the starter"


def test_without_the_starter_the_pack_names_cockpits_own_skill_only(machine, capsys):
    assert (
        cli.main(["init", str(machine["workspace"]), "--no-production", "--write", "--no-starter", "--tracker", "jira"])
        == 0
    )
    pack = load(str(machine["pack"] / "pack.yaml"))
    assert (
        set(map(tuple, pack["skills"]["kickoff"].values())) == {("cockpit:outbox",)} and pack["skills"]["intent"] == {}
    )
    assert sorted(os.listdir(machine["pack"])) == [
        ".gitignore",
        "egress.yaml",
        "pack.local.example.yaml",
        "pack.yaml",
        "repos.yaml",
        "skills",
        "skills.yaml",
    ]
    assert (
        pack["tracker"] == {"url": "https://tracker.example.test", "project": "TASK"} and "seat_config" not in pack
    )  # no kind: the connector


def test_a_plugin_folder_without_a_starter_still_gives_a_pack_and_a_file_that_is_not_text_is_copied_as_it_is(
    machine, tmp_path, monkeypatch, capsys
):
    plugin = tmp_path / "plugin"
    monkeypatch.setattr(scaffold, "PLUGIN_ROOT", str(plugin))
    found = scaffold.detect(str(machine["workspace"]), no_production=True)
    assert found["starter"] is False and found["tracker"] == "jira"
    assert any(note.startswith("the starter pack is not in ") for note in found["notes"])
    (plugin / "starter" / "skills" / "ticket-intake" / "__pycache__").mkdir(parents=True)
    (plugin / "starter" / "skills" / "ticket-intake" / "SKILL.md").write_text(
        "---\nname: ticket-intake\ndescription: read it\n---\n", encoding="utf-8"
    )
    (plugin / "starter" / "skills" / "ticket-intake" / "picture.bin").write_bytes(b"\xff\xfe\x00")
    (plugin / "starter" / "skills" / "ticket-intake" / "__pycache__" / "x.pyc").write_bytes(b"\x00")
    (plugin / "starter" / "skills" / "ticket-intake" / "stale.pyc").write_bytes(b"\x00")
    monkeypatch.setenv(
        "COCKPIT_WORKSPACE", "/srv/another"
    )  # a workspace named in the shell is put back after the check
    assert cli.main(["init", str(machine["workspace"]), "--no-production", "--write", "--no-bind"]) == 0
    assert os.environ["COCKPIT_WORKSPACE"] == "/srv/another" and not os.path.exists(binding_file())
    copied = machine["pack"] / "skills" / "ticket-intake"
    assert (
        sorted(os.listdir(copied)) == ["SKILL.md", "picture.bin"]
        and (copied / "picture.bin").read_bytes() == b"\xff\xfe\x00"
    )
    pack = load(str(machine["pack"] / "pack.yaml"))
    assert pack["skills"]["kickoff"]["intake"] == ["ticket-intake", "cockpit:outbox"] and pack["skills"]["kickoff"][
        "review"
    ] == ["cockpit:outbox"]
    scaffold._remove_made(["/no/such/file/of/this/call"])  # what is already gone is not an error
