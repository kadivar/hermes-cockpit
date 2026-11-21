# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""One behaviour, every tracker: the checks a tracker implementation passes to stand behind the protocol in cockpitlib.trackers.base.

Each `check_*` takes a World: the tracker under test and the few things a test must know or arrange that the protocol
has no operation for (the status a new ticket has and one it can move to, a file to attach, what the tracker holds as
attached). tests/test_every_tracker_answers_the_protocol_alike.py runs every check against every built-in tracker; a
new implementation adds its World there and nothing here.
"""

import os

from cockpitlib.trackers import base


class World:
    """What a check may ask for besides the tracker itself."""

    tracker = None
    project = "TASK"
    first = ""  # the status of a new ticket
    then = ""  # a status a new ticket can move to

    def page_part(self, key: str) -> str:
        """What of a ticket's key its page's address carries: the key itself, unless the tracker's pages are numbered otherwise."""
        return key

    def dry(self):
        """The same tracker in a dry run."""
        raise NotImplementedError

    def attached(self, key: str) -> list:
        """The names of the files the tracker holds as attached to the ticket."""
        raise NotImplementedError

    def file(self, name: str, text: str = "evidence\n") -> str:
        """A file in the workspace. Its path as an intent names it: relative to the workspace."""
        full = os.path.join(os.environ["COCKPIT_WORKSPACE"], name)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "w", encoding="utf-8") as handle:
            handle.write(text)
        return name


def _ticket(world, summary="The export has no header") -> str:
    _url, _out, made = world.tracker.create(
        {"ticket": "", "payload": {"summary": summary, "project": world.project, "body": "Seen on run 1."}}, {}
    )
    return made["key"]


def _comment(world, key, body, **more) -> str:
    _url, _out, made = world.tracker.comment({"ticket": key, "payload": {"issue": key, "body": body, **more}}, {})
    return made["comment"]


def check_a_ticket_is_made_and_its_summary_and_status_are_read(world):
    tracker = world.tracker
    url, out, made = tracker.create(
        {
            "ticket": "",
            "payload": {"summary": "The export has no header", "project": world.project, "body": "Seen on run 1."},
        },
        {},
    )
    key = made["key"]
    assert key.startswith(world.project + "-") and key in out and url
    assert tracker.summary(key) == "The export has no header"
    assert tracker.status(key) == world.first
    second = _ticket(world, "A second one")
    assert second != key and tracker.summary(second) == "A second one"
    assert tracker.statuses([key, second]) == {key: world.first, second: world.first}
    assert world.page_part(key) in tracker.browse_url(key) and tracker.browse_url(key) != tracker.browse_url(second)
    assert tracker.comment_url(key, "7").startswith(tracker.browse_url(key).split("#")[0])


def check_a_comment_is_posted_and_listed(world):
    tracker = world.tracker
    key = _ticket(world)
    assert tracker.comments(key) == []
    url, out, made = tracker.comment({"ticket": key, "payload": {"issue": key, "body": "Tested and Ok."}}, {})
    assert url and made["comment"] and made["comment"] in out
    rows = tracker.comments(key)
    assert [(row["id"], row["text"]) for row in rows] == [(made["comment"], "Tested and Ok.")]
    assert (
        set(rows[0]) >= {"id", "account", "author", "created", "updated", "text"}
        and rows[0]["author"]
        and rows[0]["created"]
    )
    assert rows[0]["account"] == tracker.me() != "", "the pack's own comment is known as its own"


def check_a_comment_is_edited_in_place(world):
    tracker = world.tracker
    key = _ticket(world)
    first = _comment(world, key, "Tested and Not Ok.")
    again = _comment(world, key, "Tested and Ok after the fix.", comment_id=first)
    assert again == first
    assert [(row["id"], row["text"]) for row in tracker.comments(key)] == [(first, "Tested and Ok after the fix.")]


def check_a_ticket_moves_to_another_status(world):
    tracker = world.tracker
    key = _ticket(world)
    url, out, made = tracker.transition({"ticket": key, "payload": {"issue": key, "to": world.then}}, {}, key)
    assert world.then in out and made == {}
    assert tracker.status(key) == world.then


def check_the_comments_since_a_moment_are_the_ones_written_or_edited_from_then_on(world):
    tracker = world.tracker
    key = _ticket(world)
    first = _comment(world, key, "The first note.")
    second = _comment(world, key, "The second note.")
    rows = {row["id"]: row for row in tracker.comments(key)}
    assert [row["id"] for row in tracker.comments(key, since=rows[second]["updated"])] == [second]
    assert [row["id"] for row in tracker.comments(key, since=rows[first]["created"])] == [first, second]
    assert [row["id"] for row in tracker.comments(key, since=None)] == [first, second]
    _comment(world, key, "The first note, corrected.", comment_id=first)
    later = tracker.comments(key, since=rows[second]["updated"])
    assert sorted(row["id"] for row in later) == sorted([first, second]), "an edit is news too"
    assert {row["id"]: row["text"] for row in later}[first] == "The first note, corrected."


def check_a_file_is_attached_with_a_comment(world):  # or refused, by a tracker that says it has no attachments
    tracker = world.tracker
    key = _ticket(world)
    path = world.file("evidence/shot-3.txt")
    steps = {}
    if base.ATTACHMENTS not in tracker.capabilities():  # by what the tracker says it has, never by its kind
        try:
            tracker.comment(
                {"ticket": key, "payload": {"issue": key, "body": "See shot-3.txt.", "attach": [path]}}, steps
            )
        except base.Unsupported as exc:
            assert base.ATTACHMENTS in str(exc) and tracker.comments(key) == [], (
                "refused by the capability's name, and nothing was posted"
            )
            return
        raise AssertionError("a tracker without attachments took a comment with a file")
    _url, out, made = tracker.comment(
        {"ticket": key, "payload": {"issue": key, "body": "See shot-3.txt.", "attach": [path]}}, steps
    )
    assert made["comment"] and world.attached(key) == ["shot-3.txt"]
    assert len(tracker.comments(key)) == 1


def check_a_dry_run_journals_and_writes_nothing(world):
    key = _ticket(world)
    dry = world.dry()
    assert dry.dry_run and dry.writes == []
    _url, out, made = dry.comment({"ticket": key, "payload": {"issue": key, "body": "Not sent."}}, {})
    assert not any(made.values()) and len(dry.writes) == 1, "nothing was made"
    dry.transition({"ticket": key, "payload": {"issue": key, "to": world.then}}, {}, key)
    _url, out, made = dry.create({"ticket": "", "payload": {"summary": "Not made", "project": world.project}}, {})
    assert not any(made.values()) and len(dry.writes) == 3
    assert world.tracker.comments(key) == [] and world.tracker.status(key) == world.first


def check_it_says_what_it_is_and_what_it_has(world):
    tracker = world.tracker
    assert tracker.kind and set(tracker.capabilities()) <= set(base.CAPABILITIES)
    assert {
        base.SUMMARY,
        base.STATUS,
        base.COMMENTS,
        base.IDENTITY,
        base.COMMENT,
        base.EDIT_COMMENT,
        base.CREATE,
        base.TRANSITION,
    } <= set(tracker.capabilities())
    assert tracker.capabilities() == type(tracker).offers(tracker.config)
    lacking = [
        name for name in (base.ATTACHMENTS,) if name not in tracker.capabilities()
    ]  # the one of these a tracker may lack
    assert base.missing(tracker.capabilities(), "tracker-comment", {"attach": ["a.png"], "comment_id": "7"}) == lacking
    assert tracker.noun and isinstance(tracker.writes, list)


CHECKS = [value for name, value in sorted(globals().items()) if name.startswith("check_")]
