# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The tracker is a protocol (cockpitlib.trackers.base) with one implementation per `tracker.kind`. The kernel asks it for
operations; what a tracker lacks is a capability it does not name, refused when the intent is written."""

import os
import shutil

import pytest
import yaml

from cockpitlib import pack as packs
from cockpitlib import tracker, trackers
from cockpitlib.errors import CockpitError, PackError
from cockpitlib.pack import load
from cockpitlib.trackers import base
from cockpitlib.trackers.command import CommandTracker
from cockpitlib.trackers.jira import ConnectorTracker, JiraTracker
from cockpitlib.trackers.local import LocalTracker
from tests.support.both_packs import PACKS


def _pack_with(tmp_path, pack_file, **changes) -> str:
    folder = tmp_path / "packs" / os.path.basename(os.path.dirname(pack_file))
    shutil.copytree(os.path.dirname(pack_file), folder)
    raw = yaml.safe_load((folder / "pack.yaml").read_text(encoding="utf-8"))
    raw["tracker"] = {**(raw.get("tracker") or {}), **changes}
    for name in [name for name, value in raw["tracker"].items() if value is None]:
        raw["tracker"].pop(name)
    (folder / "pack.yaml").write_text(yaml.safe_dump(raw, sort_keys=False, allow_unicode=True), encoding="utf-8")
    return str(folder / "pack.yaml")


def test_the_kind_picks_the_implementation():
    assert trackers.kind_of({}) == "connector" and trackers.kind_of({"command": ["bin/tracker"]}) == "command"
    assert trackers.kind_of({"kind": "jira"}) == "jira" and trackers.implementation("jira") is JiraTracker
    assert (
        trackers.implementation("connector") is ConnectorTracker
        and trackers.implementation("command") is CommandTracker
    )
    assert trackers.implementation("local") is LocalTracker
    with pytest.raises(PackError, match="tracker.kind is one of connector, jira, command, local"):
        trackers.implementation("spreadsheet")
    assert (
        set(trackers.NAMES) == set(packs.TRACKER_KINDS)
        and tuple(LocalTracker({}).moves) == packs.TRACKER_LOCAL_STATUSES
    )
    assert tuple(base.BROWSE_FIELDS) == packs.TRACKER_PAGE_FIELDS
    made = trackers.make({"kind": "jira", "url": "https://tracker.example.test"}, dry_run=True)
    assert type(made) is JiraTracker and made.dry_run and made.kind == "jira"
    assert tracker.tracker_kind({"kind": "jira"}) == "jira" and tracker.tracker_kind({"kind": "local"}) == "local"
    # the older module still hands out every name code imported from it
    assert (
        tracker.JiraTracker is JiraTracker
        and tracker.CommandTracker is CommandTracker
        and tracker.ConnectorTracker is ConnectorTracker
    )
    assert tracker.adf("a\n\nb")["content"][1]["content"][0]["text"] == "b" and tracker.MOVE_THROUGH_TRIES == 3


def test_a_tracker_that_answers_nothing_refuses_each_operation_by_the_capability_it_needs():
    bare = base.Tracker({})
    assert bare.capabilities() == frozenset() and bare.me() == "" and bare.writes == [] and not bare.dry_run
    asked = {
        base.SUMMARY: lambda: bare.summary("TASK-100"),
        base.STATUS: lambda: bare.status("TASK-100"),
        base.COMMENTS: lambda: bare.comments("TASK-100"),
        base.EDIT_COMMENT: lambda: bare.find_comment("TASK-100", "Run"),
        base.TRANSITION_THROUGH: lambda: bare.reachable("TASK-100", "Done"),
        base.COMMENT: lambda: bare.comment({}, {}),
        base.CREATE: lambda: bare.create({}, {}),
        base.TRANSITION: lambda: bare.transition({}, {}, "TASK-100"),
    }
    for capability, ask in asked.items():
        with pytest.raises(base.Unsupported, match=f"the pack tracker has no {capability}$"):
            ask()
    assert bare.statuses(["TASK-100"]) == {}, "a ticket whose status cannot be read is left out"
    assert bare.comment_url("TASK-100", 7) == bare.browse_url("TASK-100") == "/browse/TASK-100"


def test_an_intent_names_what_it_needs_of_the_tracker():
    assert base.needs("tracker-comment", {"body": "x"}) == [base.COMMENT]
    assert base.needs("tracker-comment", {"attach": ["a.png"], "probe_title": "Run"}) == [
        base.COMMENT,
        base.ATTACHMENTS,
        base.EDIT_COMMENT,
    ]
    assert base.needs("tracker-comment", {"comment_from": "TASK-100/001-tracker-comment"}) == [
        base.COMMENT,
        base.EDIT_COMMENT,
    ]
    assert base.needs("tracker-create", {"summary": "x"}) == [base.CREATE]
    assert base.needs(
        "tracker-create", {"component": "Core", "sprint": "active", "assignee": "me", "transition": "Doing"}
    ) == [base.CREATE, base.COMPONENT, base.SPRINT, base.ASSIGNEE, base.TRANSITION]
    assert base.needs("tracker-transition", {"to": "Done"}) == [base.TRANSITION]
    assert base.needs("tracker-transition", {"to": "Done", "assignee": "me"}) == [base.TRANSITION, base.ASSIGNEE]
    assert base.needs("open-pr", {}) == [] and base.needs("tracker-comment", None) == [base.COMMENT]
    assert base.missing(LocalTracker.offers({}), "tracker-create", {"component": "Core", "sprint": "active"}) == [
        base.COMPONENT,
        base.SPRINT,
    ]
    for kind in ("jira", "connector", "command"):  # what an existing pack's tracker took before, it takes now
        have = trackers.offers({"kind": kind, "command": ["bin/tracker"]})
        for intent, payload in (
            ("tracker-comment", {"attach": ["a"], "comment_id": "1", "probe_title": "t"}),
            ("tracker-create", {"component": "c", "sprint": "active", "assignee": "me", "transition": "x"}),
            ("tracker-transition", {"to": "x", "assignee": "me"}),
        ):
            assert base.missing(have, intent, payload) == [], (kind, intent)


def test_a_tickets_page_is_the_packs_template_or_the_browse_page():
    config = {"url": "https://tracker.example.test", "project": "TASK"}
    assert base.link(config, "TASK-100") == "https://tracker.example.test/browse/TASK-100"
    assert (
        base.link({**config, "browse_url": "{url}/projects/{project}/issues/{key}"}, "WEB-7")
        == "https://tracker.example.test/projects/WEB/issues/WEB-7"
    )
    assert (
        base.link({**config, "browse_url": "https://other.example.test/t/{key}?p={project}"}, "nokey")
        == "https://other.example.test/t/nokey?p=TASK"
    )
    assert base.link({"url": "https://tracker.example.test/"}, "TASK-1") == "https://tracker.example.test/browse/TASK-1"


@pytest.mark.parametrize("pack_file", PACKS)
def test_the_browse_template_reaches_every_link_the_kernel_writes(env, pack_file, tmp_path, monkeypatch):
    plain = load(pack_file)
    ticket = f"{plain['tracker']['project']}-2301"
    assert tracker.browse(plain, ticket) == f"{plain['tracker']['url'].rstrip('/')}/browse/{ticket}", (
        "a pack without the key links as before"
    )
    file = _pack_with(tmp_path, pack_file, browse_url="{url}/issues/{project}/{key}")
    monkeypatch.setenv("COCKPIT_PACK", file)
    pack = load(file)
    page = f"{plain['tracker']['url'].rstrip('/')}/issues/{plain['tracker']['project']}/{ticket}"
    assert tracker.browse(pack, ticket) == page
    made = tracker.tracker_for(pack)
    assert made.browse_url(ticket) == page and made.comment_url(ticket, 12) == page + "?focusedCommentId=12"
    from cockpitlib import standup_note

    assert (
        standup_note._fmt(pack, "md")[0](ticket) == f"[{ticket}]({page})"
        and standup_note._fmt(pack, "slack")[0](ticket) == f"<{page}|{ticket}>"
    )
    for bad in ("{url}/issues", "{url}/{key}/{board}", 7, "{url}/{}/{key}"):
        with pytest.raises(PackError, match=r"tracker.browse_url is a ticket's page with \{key\} in it"):
            load(_pack_with(tmp_path / str(abs(hash(str(bad)))), pack_file, browse_url=bad))


def test_a_tracker_that_cannot_be_made_still_has_the_page_its_settings_spell(monkeypatch):
    def broken(config, dry_run=False):
        raise CockpitError("no such tracker here")

    monkeypatch.setattr(trackers, "make", broken)
    assert (
        tracker.browse({"tracker": {"url": "https://tracker.example.test"}}, "TASK-100")
        == "https://tracker.example.test/browse/TASK-100"
    )


def test_a_moment_is_read_from_a_number_or_an_iso_text_and_anything_else_is_none():
    assert base.moment(12) == 12.0 and base.moment(1.5) == 1.5 and base.moment("1700000000.25") == 1700000000.25
    assert (
        base.moment("2026-01-01T00:00:01Z")
        == base.moment("2026-01-01T00:00:01.000+0000")
        == base.moment("2026-01-01T00:00:01")
        == 1767225601.0
    )
    assert base.moment("2026-01-01T01:00:01+01:00") == 1767225601.0
    assert (
        base.moment("") is None
        and base.moment(None) is None
        and base.moment("yesterday") is None
        and base.moment(True) is None
    )
    rows = [
        {"id": "1", "created": "2026-01-01T00:00:01Z", "updated": "2026-01-01T00:00:01Z"},
        {"id": "2", "created": "2026-01-01T00:00:05Z"},
        {"id": "3", "created": "not a time"},
    ]
    assert [row["id"] for row in base.since_then(rows, "2026-01-01T00:00:05Z")] == ["2", "3"], (
        "a row with no readable time is kept"
    )
    assert base.since_then(rows, None) == rows and base.since_then(rows, "whenever") == rows


def test_an_object_from_before_the_protocol_is_read_through_what_it_answers():
    class Old:
        def _request(self, method, path):
            assert (method, path) == ("GET", "/rest/api/3/issue/TASK-100/comment?maxResults=100")
            return {
                "comments": [
                    {
                        "id": 5,
                        "author": {"accountId": "a-1", "displayName": "Ann"},
                        "created": "2026-01-01T00:00:01.000+0000",
                        "body": {"type": "doc", "content": [{"type": "text", "text": " hello "}]},
                    },
                    "not a row",
                    {"no": "id"},
                ]
            }

        def _status(self, key):
            return "In Review"

        def _myself(self):
            return "a-1"

        def reachable(self, key, to):
            return None, []

    seen = trackers.seam(Old(), {"url": "https://tracker.example.test"})
    assert (
        seen.capabilities() == {base.COMMENTS, base.STATUS, base.IDENTITY, base.TRANSITION_THROUGH}
        and seen.noun == "Jira"
    )
    assert seen.comments("TASK-100") == [
        {
            "id": "5",
            "account": "a-1",
            "author": "Ann",
            "updated": "2026-01-01T00:00:01.000+0000",
            "created": "2026-01-01T00:00:01.000+0000",
            "text": "hello",
        }
    ]
    assert (
        seen.me() == "a-1"
        and seen.status("TASK-100") == "In Review"
        and seen.statuses(["TASK-100"]) == {"TASK-100": "In Review"}
    )
    assert seen.comment_url("TASK-100", 5) == "https://tracker.example.test/browse/TASK-100?focusedCommentId=5"
    nothing = trackers.seam(object())
    assert nothing.capabilities() == frozenset() and nothing.me() == ""
    with pytest.raises(CockpitError, match="the pack's tracker command has no read for comments"):
        nothing.comments("TASK-100")
    made = JiraTracker({"url": "https://tracker.example.test"})
    assert trackers.seam(made) is made and trackers.seam(None) is None
    assert (
        trackers.has(made, base.TRANSITION_THROUGH)
        and trackers.has(Old(), base.TRANSITION_THROUGH)
        and not trackers.has(object(), base.TRANSITION_THROUGH)
    )
    assert not trackers.has(CommandTracker({"command": ["bin/tracker"]}), base.TRANSITION_THROUGH)


def test_jira_answers_the_protocols_reads_with_the_calls_it_always_made(jira, monkeypatch):
    monkeypatch.setenv("TRACKER_EMAIL", "human@example.test")
    monkeypatch.setenv("TRACKER_AUTH", "token-1")
    made = trackers.make({"kind": "jira", "url": jira.url, "auth_env": ["TRACKER_EMAIL", "TRACKER_AUTH"]})
    issue = jira.issue("TASK-100", "In Review")
    issue["comments"]["1"] = {
        "id": "1",
        "author": {"accountId": "a-2", "name": "old-style"},
        "created": "2026-01-01T00:00:01.000+0000",
        "body": "first",
    }
    issue["comments"]["2"] = {
        "id": "2",
        "created": "2026-01-01T00:00:01.000+0000",
        "updated": "2026-01-01T00:00:09.000+0000",
        "body": "second",
    }
    assert [(row["id"], row["account"], row["author"], row["text"]) for row in made.comments("TASK-100")] == [
        ("1", "a-2", "old-style", "first"),
        ("2", "", "someone", "second"),
    ]
    assert [row["id"] for row in made.comments("TASK-100", since="2026-01-01T00:00:05Z")] == ["2"]
    assert (
        made.me() == jira.account
        and made.status("TASK-100") == "In Review"
        and made.statuses(["TASK-100", "TASK-404"]) == {"TASK-100": "In Review"}
    )
    assert [(row["method"], row["path"]) for row in jira.requests] == [
        ("GET", "/rest/api/3/issue/TASK-100/comment?maxResults=100"),
        ("GET", "/rest/api/3/issue/TASK-100/comment?maxResults=100"),
        ("GET", "/rest/api/3/myself"),
        ("GET", "/rest/api/3/issue/TASK-100?fields=status"),
        ("GET", "/rest/api/3/issue/TASK-100?fields=status"),
        ("GET", "/rest/api/3/issue/TASK-404?fields=status"),
    ]
    assert (
        made.capabilities() == frozenset(base.CAPABILITIES)
        and ConnectorTracker({"url": "x"}, call=lambda *_a: {}).kind == "connector"
    )


@pytest.mark.parametrize("pack_file", PACKS)
def test_an_intent_the_packs_tracker_cannot_publish_is_refused_when_it_is_written(
    env, pack_file, tmp_path, monkeypatch
):
    from cockpitlib.outbox import create

    plain = load(pack_file)
    ticket = f"{plain['tracker']['project']}-2302"
    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    assert create(
        plain, ticket, "tracker-create", "c", "a ticket", {"summary": "x", "component": "Core", "sprint": "active"}
    )["id"], "as before"
    file = _pack_with(tmp_path, pack_file, kind="local", auth_env=None)
    monkeypatch.setenv("COCKPIT_PACK", file)
    pack = load(file)
    assert tracker.capabilities(pack) == LocalTracker.offers({})
    for payload, lacking in (
        ({"summary": "x", "component": "Core"}, "component"),
        ({"summary": "x", "sprint": "active"}, "sprint"),
    ):
        with pytest.raises(
            CockpitError,
            match=rf"the pack's tracker \(local\) has no {lacking}: this tracker-create cannot be published to it",
        ):
            create(pack, ticket, "tracker-create", "c", "a ticket", payload)
    assert create(pack, ticket, "tracker-create", "c", "a ticket", {"summary": "x", "assignee": "me"})["id"]
