# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""tracker.kind local: tickets live as JSON files under one folder. No network, no command, no credentials: the outbox
publishes to it and the comment watch reads it like any tracker."""

import json
import os
import shutil

import pytest
import yaml

from cockpitlib import tracker
from cockpitlib.errors import CockpitError, PackError
from cockpitlib.pack import load
from cockpitlib.trackers import base
from cockpitlib.trackers.local import ME, STATUSES, LocalTracker
from tests.support.both_packs import PACKS


def _local_pack(tmp_path, pack_file, **local) -> str:
    folder = tmp_path / "packs" / os.path.basename(os.path.dirname(pack_file))
    shutil.copytree(os.path.dirname(pack_file), folder)
    raw = yaml.safe_load((folder / "pack.yaml").read_text(encoding="utf-8"))
    named = {key: raw["tracker"][key] for key in ("url", "project")}
    raw["tracker"] = {**named, "kind": "local", **({"local": local} if local else {})}
    (folder / "pack.yaml").write_text(yaml.safe_dump(raw, sort_keys=False, allow_unicode=True), encoding="utf-8")
    return str(folder / "pack.yaml")


@pytest.mark.parametrize("pack_file", PACKS)
def test_tracker_intents_are_published_to_the_local_tracker_and_read_back(env, pack_file, tmp_path, monkeypatch):
    from cockpitlib.outbox import create, endorse
    from cockpitlib.publish import execute

    file = _local_pack(tmp_path, pack_file)
    monkeypatch.setenv("COCKPIT_PACK", file)
    monkeypatch.setenv("PATH", "/usr/bin:/bin")
    pack = load(file)
    project = pack["tracker"]["project"]
    made = tracker.tracker_for(pack)
    assert type(made) is LocalTracker and made.root() == os.path.join(
        str(env["workspace"]), pack["records_dir"], "tracker"
    )
    ticket = f"{project}-1"

    def ready(kind, payload):
        return endorse(
            create(pack, ticket, kind, "c", "tracker", payload)["id"],
            "low",
            "",
            "gatekeeper",
            "fixture-a",
            "fixture-large",
        )

    receipt = execute(
        ready(
            "tracker-create",
            {
                "summary": f"A ticket of {pack['name']}",
                "body": "What is wrong.",
                "labels": ["bug"],
                "assignee": "me",
                "transition": "in progress",
            },
        ),
        pack=pack,
    )
    assert receipt["ok"], receipt
    assert receipt["url"] == "file://" + os.path.join(made.root(), f"{ticket}.json") and receipt["output"].startswith(
        f"{ticket}; in progress → In Progress"
    )
    kept = json.load(open(os.path.join(made.root(), f"{ticket}.json"), encoding="utf-8"))
    assert (kept["key"], kept["summary"], kept["body"], kept["status"], kept["labels"], kept["assignee"]) == (
        ticket,
        f"A ticket of {pack['name']}",
        "What is wrong.",
        "In Progress",
        ["bug"],
        ME,
    )
    assert tracker.titles(pack, [ticket], refresh=True) == {ticket: f"A ticket of {pack['name']}"}
    evidence = env["workspace"] / pack["records_dir"] / "qa" / ticket / "row-1.png"
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_bytes(b"picture")
    note = env["workspace"] / "note.md"
    note.write_text("Run for the first build: Not Ok, see row-1.png\n", encoding="utf-8")
    first = execute(
        ready(
            "tracker-comment",
            {"issue": ticket, "body_file": str(note), "attach": [str(evidence)], "probe_title": "Run for"},
        ),
        pack=pack,
    )
    assert first["ok"] and first["output"] == f"posted on {ticket} (comment 1, read back) · attached row-1.png", first
    assert [(row["name"], row["size"]) for row in made.attachments(ticket)] == [("row-1.png", 7)]
    twin = execute(
        ready("tracker-comment", {"issue": ticket, "body_file": str(note), "probe_title": "Run for"}), pack=pack
    )
    assert not twin["ok"] and "already has a comment starting with 'Run for' (id 1)" in twin["error"]
    note.write_text("Run for the second build: Ok\n", encoding="utf-8")
    again = execute(ready("tracker-comment", {"issue": ticket, "body_file": str(note), "comment_id": "1"}), pack=pack)
    assert again["ok"] and again["output"] == f"updated on {ticket} (comment 1, read back)"
    assert [row["text"] for row in made.comments(ticket)] == ["Run for the second build: Ok"] and made.find_comment(
        ticket, "run for"
    ) == "1"
    assert made.find_comment(ticket, "Nothing like it") == ""
    gone = execute(ready("tracker-comment", {"issue": ticket, "body": "x", "comment_id": "9"}), pack=pack)
    assert not gone["ok"] and f"{ticket} has no comment 9" in gone["error"]
    moved = execute(ready("tracker-transition", {"issue": ticket, "to": "Done", "assignee": "ann"}), pack=pack)
    assert (
        moved["ok"]
        and moved["output"] == "Done → Done (status now Done); assigned ann"
        and made.status(ticket) == "Done"
    )
    assert json.load(open(os.path.join(made.root(), f"{ticket}.json"), encoding="utf-8"))["assignee"] == "ann"
    dry = execute(ready("tracker-transition", {"issue": ticket, "to": "To Do"}), pack=pack, dry_run=True)
    assert dry["ok"] and dry["output"] == f"would move {ticket} → To Do" and made.status(ticket) == "Done"
    assert dry["actions"] == [
        {"method": "transition", "path": f"local tracker {ticket}", "body": {"to": "To Do", "through": []}}
    ]


@pytest.mark.parametrize("pack_file", PACKS)
def test_the_comment_watch_reads_the_local_tracker_and_skips_the_packs_own_comments(
    env, pack_file, tmp_path, monkeypatch
):
    from cockpitlib import tracker_watch
    from cockpitlib.kanban import place_card
    from cockpitlib.outbox import create

    file = _local_pack(tmp_path, pack_file, root=str(tmp_path / "tickets"))
    monkeypatch.setenv("COCKPIT_PACK", file)
    pack = load(file)
    made = tracker.tracker_for(pack)
    assert made.root() == str(tmp_path / "tickets")
    ticket = f"{pack['tracker']['project']}-7301"
    made.seed(ticket, "A finished ticket")
    made.add_comment(ticket, "Before the watch.", "ann")
    card = place_card(pack["board"], f"{ticket}: tester", "tester-1", "ready")
    create(pack, ticket, "ticket-done", card, "test run finished", {"numbers": ["3"]})
    assert tracker_watch.watch(pack, now=1000.0)["read"] == [ticket] and tracker_watch.rows() == []
    made.add_comment(ticket, "A post of our own.")
    said = made.add_comment(ticket, "It still fails on the second page.", "ann")
    out = tracker_watch.watch(pack, now=1400.0)
    assert out["read"] == [ticket] and len(out["notes"]) == 1
    row = tracker_watch.rows()[0]
    assert (row["comment"], row["kind"], row["author"], row["text"]) == (
        said,
        "new",
        "ann",
        "It still fails on the second page.",
    )
    assert row["url"] == f"file://{tmp_path / 'tickets' / (ticket + '.json')}#comment-{said}"
    assert tracker_watch._state()["me"] == ME


def test_a_ticket_moves_only_where_the_packs_transitions_lead_and_goes_through_when_there_is_a_way(bare, tmp_path):
    moves = {"To Do": ["In Progress"], "In Progress": ["In Review", "To Do"], "In Review": ["Done"], "Done": []}
    made = LocalTracker({"project": "TASK", "local": {"root": str(tmp_path / "t"), "transitions": moves}})
    made.seed("TASK-1", "One")
    assert (
        made.reachable("TASK-1", "in progress")[0]["name"] == "In Progress"
        and made.reachable("TASK-1", "Done")[0] is None
    )
    assert [row["name"] for row in made.reachable("TASK-1", "Done")[1]] == ["In Progress"]
    _url, out, _made = made.transition({"payload": {"to": "Done"}}, {}, "TASK-1")
    assert (
        out == "from To Do through In Progress, In Review: Done → Done (status now Done)"
        and made.status("TASK-1") == "Done"
    )
    assert made.transition({"payload": {"to": "done"}}, {}, "TASK-1")[1] == "TASK-1 is already Done"
    with pytest.raises(CockpitError, match="no transition means 'To Do' from 'Done'; available: \\[\\]"):
        made.transition({"payload": {"to": "To Do"}}, {}, "TASK-1")
    with pytest.raises(
        CockpitError, match="'Shipped' is not a status; it has \\['To Do', 'In Progress', 'In Review', 'Done'\\]"
    ):
        made.transition({"payload": {"to": "Shipped"}}, {}, "TASK-1")
    plain = LocalTracker({"local": {"root": str(tmp_path / "p"), "statuses": ["Open", "Closed"]}})
    assert plain.moves == {"Open": ["Closed"], "Closed": ["Open"]} and plain.seed("WEB-1")["status"] == "Open"
    assert list(LocalTracker({}).moves) == STATUSES


def test_a_ticket_that_is_not_there_is_never_invented_and_a_broken_file_is_said(bare, tmp_path):
    made = LocalTracker({"project": "TASK"}, root=str(tmp_path / "t"))
    for ask in (
        lambda: made.summary("TASK-9"),
        lambda: made.status("TASK-9"),
        lambda: made.comments("TASK-9"),
        lambda: made.comment({"ticket": "TASK-9", "payload": {"body": "x"}}, {}),
        lambda: LocalTracker({}, dry_run=True, root=str(tmp_path / "t")).comment(
            {"ticket": "TASK-9", "payload": {"body": "x"}}, {}
        ),
        lambda: made.transition({"payload": {"to": "Done"}}, {}, "TASK-9"),
    ):
        with pytest.raises(CockpitError, match="local tracker: no ticket TASK-9"):
            ask()
    assert not os.path.exists(os.path.join(made.root(), "TASK-9.json"))
    with pytest.raises(CockpitError):
        made.summary("../outside")
    made.seed("TASK-1", "One")
    with open(os.path.join(made.root(), "TASK-1.json"), "w", encoding="utf-8") as handle:
        handle.write("not json")
    with pytest.raises(CockpitError, match="TASK-1.json is unreadable"):
        made.summary("TASK-1")


def test_a_new_ticket_takes_the_next_number_of_its_project_and_what_the_tracker_lacks_is_refused(bare, tmp_path):
    made = LocalTracker(
        {"project": "TASK", "url": "https://tracker.example.test", "browse_url": "{url}/t/{key}"},
        root=str(tmp_path / "t"),
    )
    made.seed("TASK-7", "Seeded")
    made.seed("TASKS-90", "Another project")
    url, out, kept = made.create({"payload": {"summary": "Next"}}, {})
    assert (url, out, kept) == ("https://tracker.example.test/t/TASK-8", "TASK-8 · read back", {"key": "TASK-8"})
    assert made.create({"payload": {"summary": "Other", "project": "WEB", "assignee": "ann"}}, {})[2] == {
        "key": "WEB-1"
    }
    assert made.comment_url("TASK-8", "2") == "https://tracker.example.test/t/TASK-8#comment-2"
    for field, capability in (("sprint", base.SPRINT), ("component", base.COMPONENT)):
        with pytest.raises(base.Unsupported, match=f"the local tracker has no {capability}"):
            made.create({"payload": {"summary": "x", field: "one"}}, {})
    with pytest.raises(CockpitError, match="a new ticket needs a project"):
        LocalTracker({}, root=str(tmp_path / "t")).create({"payload": {"summary": "x"}}, {})
    dry = LocalTracker({"project": "TASK"}, dry_run=True, root=str(tmp_path / "t"))
    assert dry.create({"payload": {"summary": "Not made"}}, {}) == ("", "would create TASK 'Not made'", {})
    assert (
        dry.transition({"payload": {"to": "Done", "assignee": "me"}}, {}, "TASK-8")[1]
        == "would move TASK-8 → Done; assigned me"
    )
    assert made.status("TASK-8") == "To Do" and not os.path.exists(os.path.join(made.root(), "TASK-9.json"))
    assert [row["method"] for row in dry.writes] == ["create", "transition", "assign"]


@pytest.mark.parametrize("pack_file", PACKS)
def test_the_local_trackers_settings_are_checked_when_the_pack_loads(tmp_path, pack_file):
    good = load(
        _local_pack(
            tmp_path / "good",
            pack_file,
            root="/srv/tickets",
            statuses=["Open", "Doing", "Closed"],
            transitions={"Open": ["Doing"], "Doing": ["Closed", "Open"]},
        )
    )
    assert good["tracker"]["local"]["statuses"] == ["Open", "Doing", "Closed"]
    made = tracker.tracker_for(good)
    assert made.root() == "/srv/tickets" and made.moves == {
        "Open": ["Doing"],
        "Doing": ["Closed", "Open"],
        "Closed": [],
    }
    bad = (
        ({"folder": "x"}, "tracker.local takes root"),
        ({"root": ""}, "tracker.local takes root"),
        ({"root": 3}, "tracker.local takes root"),
        ({"statuses": []}, "tracker.local.statuses is a list of status names"),
        ({"statuses": "Open"}, "tracker.local.statuses is a list"),
        ({"statuses": ["Open", "open"]}, "tracker.local.statuses is a list"),
        ({"statuses": ["Open", ""]}, "tracker.local.statuses is a list"),
        ({"transitions": ["Open"]}, "tracker.local.transitions maps a status"),
        ({"transitions": {"Open": ["Done"]}}, "tracker.local.transitions maps"),
        ({"transitions": {"To Do": "Done"}}, "tracker.local.transitions maps"),
        ({"transitions": {"To Do": ["Shipped"]}}, "tracker.local.transitions maps"),
    )
    for index, (local, message) in enumerate(bad):
        with pytest.raises(PackError, match=message):
            load(_local_pack(tmp_path / f"bad-{index}", pack_file, **local))
    folder = tmp_path / "list"
    file = _local_pack(folder, pack_file)
    raw = yaml.safe_load(open(file, encoding="utf-8"))
    raw["tracker"]["local"] = ["root"]
    open(file, "w", encoding="utf-8").write(yaml.safe_dump(raw, sort_keys=False))
    with pytest.raises(PackError, match="tracker.local takes root"):
        load(file)


def test_a_write_the_files_do_not_show_afterwards_is_a_failed_read_back(bare, tmp_path, monkeypatch):
    made = LocalTracker({"project": "TASK"}, root=str(tmp_path / "t"))
    made.seed("TASK-1", "One")
    monkeypatch.setattr(
        LocalTracker, "_save", lambda self, ticket: None
    )  # a disk that takes the write and keeps nothing
    with pytest.raises(CockpitError, match="read-back: the comment is not readable after the post"):
        made.comment({"ticket": "TASK-1", "payload": {"body": "x"}}, {})
    with pytest.raises(CockpitError, match="read-back: TASK-1 is 'To Do' after the move to 'Done'"):
        made.transition({"payload": {"to": "Done"}}, {}, "TASK-1")
    monkeypatch.setattr(LocalTracker, "summary", lambda self, key: "")
    with pytest.raises(CockpitError, match="read-back: TASK-2 does not carry the summary it was made with"):
        made.create({"payload": {"summary": "Two"}}, {})
