# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""A pack's tracker command may answer reads (comments, me, status) besides its writes. They are run only for a pack
that names them in tracker.reads, so a command written before they existed is never run with an action it does not
know; a read the command answers with exit 2 is one it does not have."""

import json
import os
import shutil
import sys

import pytest
import yaml

from cockpitlib import tracker, trackers
from cockpitlib.errors import CockpitError, PackError
from cockpitlib.pack import load
from cockpitlib.trackers import base
from cockpitlib.trackers.command import CommandTracker
from tests.conftest import ROOT
from tests.support.both_packs import PACKS

STARTER = os.path.join(ROOT, "starter", "bin", "tracker")


def _command_pack(tmp_path, pack_file, command, **more) -> str:
    folder = tmp_path / "packs" / os.path.basename(os.path.dirname(pack_file))
    shutil.copytree(os.path.dirname(pack_file), folder)
    raw = yaml.safe_load((folder / "pack.yaml").read_text(encoding="utf-8"))
    named = {key: raw["tracker"][key] for key in ("url", "project")}
    raw["tracker"] = {**named, "command": command, **more}
    (folder / "pack.yaml").write_text(yaml.safe_dump(raw, sort_keys=False, allow_unicode=True), encoding="utf-8")
    return str(folder / "pack.yaml")


def _script(tmp_path, body: str) -> list:
    """A tracker command that keeps every action it was run with in calls.log."""
    path = tmp_path / "tickets.py"
    path.write_text(
        "import json, os, sys\naction = os.environ['COCKPIT_TRACKER_ACTION']\ngiven = json.load(sys.stdin)\n"
        f"open({str(tmp_path / 'calls.log')!r}, 'a').write(action + ' ' + json.dumps(given, sort_keys=True) + '\\n')\n"
        + body,
        encoding="utf-8",
    )
    return [sys.executable, str(path)]


def _calls(tmp_path) -> list:
    path = tmp_path / "calls.log"
    return path.read_text(encoding="utf-8").splitlines() if path.exists() else []


def test_a_command_that_names_no_reads_is_never_run_for_one(tmp_path):
    made = CommandTracker({"command": _script(tmp_path, "print(json.dumps({'summary': 'A title'}))\n")})
    assert (
        base.COMMENTS not in made.capabilities()
        and base.STATUS not in made.capabilities()
        and base.IDENTITY not in made.capabilities()
    )
    with pytest.raises(base.Unsupported, match="the pack's tracker command has no read for comments"):
        made.comments("TASK-100")
    with pytest.raises(base.Unsupported, match="the pack's tracker command has no read for status"):
        made.status("TASK-100")
    assert made.me() == "" and made.statuses(["TASK-100"]) == {} and _calls(tmp_path) == [], "nothing was run"
    assert made.summary("TASK-100") == "A title" and len(_calls(tmp_path)) == 1, (
        "the title read is every command's, as before"
    )


def test_the_reads_a_pack_names_are_run_with_their_own_input_and_answer_the_protocols_rows(tmp_path):
    body = (
        "if action == 'comments':\n"
        "    print(json.dumps({'comments': [{'id': 4, 'author': 'ann', 'created': '2026-01-01T00:00:01Z', 'body': ' first '},\n"
        "        {'id': 5, 'author': 'bot', 'created': '2026-01-01T00:00:02Z', 'updated': '2026-01-01T00:00:09Z', 'body': 'second'},\n"
        "        {'id': 6, 'body': 'no author, no time'}, {'body': 'no id'}, 'not a row']}))\n"
        "elif action == 'me':\n    print(json.dumps({'login': 'bot'}))\n"
        "elif action == 'status':\n    print(json.dumps({'status': 'In Review'}))\n"
    )
    config = {"command": _script(tmp_path, body), "reads": ["comments", "me", "status"]}
    made = trackers.make(config)
    assert type(made) is CommandTracker and {
        base.COMMENTS,
        base.IDENTITY,
        base.STATUS,
    } <= made.capabilities() == trackers.offers(config)
    assert made.comments("TASK-100") == [
        {
            "id": "4",
            "account": "ann",
            "author": "ann",
            "created": "2026-01-01T00:00:01Z",
            "updated": "2026-01-01T00:00:01Z",
            "text": "first",
        },
        {
            "id": "5",
            "account": "bot",
            "author": "bot",
            "created": "2026-01-01T00:00:02Z",
            "updated": "2026-01-01T00:00:09Z",
            "text": "second",
        },
        {"id": "6", "account": "", "author": "someone", "created": "", "updated": "", "text": "no author, no time"},
    ]
    assert [row["id"] for row in made.comments("TASK-100", since="2026-01-01T00:00:05Z")] == ["5", "6"]
    assert made.me() == "bot" and made.status("TASK-100") == "In Review" and made.writes == [], (
        "a read is not journalled as a write"
    )
    assert _calls(tmp_path) == [
        'comments {"key": "TASK-100", "since": null}',
        'comments {"key": "TASK-100", "since": "2026-01-01T00:00:05Z"}',
        "me {}",
        'status {"key": "TASK-100"}',
    ]
    dry = trackers.make(config, dry_run=True)
    assert dry.status("TASK-100") == "In Review", "a dry run still reads"


def test_a_read_answered_with_exit_two_is_one_the_command_does_not_have_and_any_other_exit_is_an_error(tmp_path):
    body = (
        "if action in ('comments', 'me'):\n    sys.exit(2)\n"
        "if action == 'status':\n    print('the tracker is down', file=sys.stderr)\n    sys.exit(1)\n"
        "if action == 'create':\n    sys.exit(2)\n"
    )
    made = CommandTracker({"command": _script(tmp_path, body), "reads": ["comments", "me", "status"]})
    with pytest.raises(base.Unsupported, match="the pack's tracker command has no read for comments"):
        made.comments("TASK-100")
    assert made.me() == ""
    with pytest.raises(CockpitError, match="tracker command status: the tracker is down") as failed:
        made.status("TASK-100")
    assert not isinstance(failed.value, base.Unsupported)
    with pytest.raises(
        CockpitError, match="tracker command create: 2"
    ) as refused:  # a write's exit 2 fails the publish, as it always did
        made.create({"payload": {"summary": "x"}}, {})
    assert not isinstance(refused.value, base.Unsupported)
    odd = CommandTracker(
        {"command": _script(tmp_path, "print(json.dumps({'comments': 'none'}))\n"), "reads": ["comments"]}
    )
    assert odd.comments("TASK-100") == []


@pytest.mark.parametrize("pack_file", PACKS)
def test_the_comment_watch_works_for_a_command_that_reads_and_stays_off_for_one_that_does_not(
    env, pack_file, tmp_path, monkeypatch
):
    from cockpitlib import standup_note, tracker_watch
    from cockpitlib.kanban import place_card
    from cockpitlib.outbox import create

    monkeypatch.setenv("COCKPIT_STARTER_STATE", str(tmp_path / "state"))
    file = _command_pack(tmp_path / "reads", pack_file, [STARTER], reads=["comments", "me", "status"])
    monkeypatch.setenv("COCKPIT_PACK", file)
    pack = load(file)
    ticket = f"{pack['tracker']['project']}-1"
    made = tracker.tracker_for(pack)
    assert made.create({"payload": {"summary": "One", "project": pack["tracker"]["project"]}}, {})[2] == {"key": ticket}
    made.comment({"ticket": ticket, "payload": {"body": "Tested and Ok."}}, {})
    card = place_card(pack["board"], f"{ticket}: tester", "tester-1", "ready")
    create(pack, ticket, "ticket-done", card, "test run finished", {"numbers": ["3"]})
    assert tracker_watch.watch(pack, now=1000.0) == {
        "read": [ticket],
        "notes": [],
        "errors": [],
        "out": "1 read, 0 noted",
    }
    made.comment({"ticket": ticket, "payload": {"body": "Another of our own."}}, {})
    kept = json.loads((tmp_path / "state" / "tracker.json").read_text(encoding="utf-8"))
    kept[ticket]["comments"].append(
        {"id": 3, "author": "ann", "created": "2026-01-01T00:00:01+00:00", "body": "Still broken for me.", "attach": []}
    )
    (tmp_path / "state" / "tracker.json").write_text(json.dumps(kept), encoding="utf-8")
    out = tracker_watch.watch(pack, now=1400.0)
    assert out["read"] == [ticket] and len(out["notes"]) == 1 and tracker_watch._state()["me"] == "me"
    row = tracker_watch.rows()[0]
    assert (row["comment"], row["kind"], row["author"], row["text"]) == ("3", "new", "ann", "Still broken for me.")
    assert row["url"] == f"{pack['tracker']['url'].rstrip('/')}/browse/{ticket}"
    assert standup_note._statuses(pack, [ticket]) == {ticket: "To Do"}
    # the same command in a pack that names no reads: watched as before, which is not at all
    file = _command_pack(tmp_path / "writes", pack_file, [STARTER])
    monkeypatch.setenv("COCKPIT_PACK", file)
    plain = load(file)
    assert tracker_watch.watch(plain, now=2000.0)["errors"] == [
        f"{ticket}: the pack's tracker command has no read for comments"
    ]
    assert standup_note._statuses(plain, [ticket]) == {}


@pytest.mark.parametrize("pack_file", PACKS)
def test_the_reads_a_pack_names_are_checked_when_it_loads(tmp_path, pack_file):
    assert load(_command_pack(tmp_path / "ok", pack_file, ["{pack}/bin/tracker"], reads=["status"]))["tracker"][
        "reads"
    ] == ["status"]
    for index, reads in enumerate(([], ["comments", "delete"], "comments", [3])):
        with pytest.raises(
            PackError, match="tracker.reads lists the read actions the tracker command answers: comments, me, status"
        ):
            load(_command_pack(tmp_path / f"bad-{index}", pack_file, ["{pack}/bin/tracker"], reads=reads))
    folder = tmp_path / "rest"
    file = _command_pack(folder, pack_file, ["{pack}/bin/tracker"], reads=["status"])
    for change in ({"kind": "jira", "command": ["x"]}, {"kind": "connector", "command": None}):
        raw = yaml.safe_load(open(file, encoding="utf-8"))
        raw["tracker"] = {key: value for key, value in {**raw["tracker"], **change}.items() if value is not None}
        open(file, "w", encoding="utf-8").write(yaml.safe_dump(raw, sort_keys=False))
        with pytest.raises(PackError, match="tracker.reads is for a tracker by command"):
            load(file)
