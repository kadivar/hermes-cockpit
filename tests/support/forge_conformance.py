# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""One behaviour, every forge: the checks a forge implementation passes to stand behind the protocol in cockpitlib.forges.base.

Each `check_*` takes a World: the forge under test and the few things a test must arrange that the protocol has no
operation for, because on a real forge someone else does them (a pushed branch, a reviewer's thread, a draft, a CI
result). tests/test_every_forge_answers_the_protocol_alike.py runs every check against every built-in forge; a new
implementation adds its World there and nothing here.
"""

import os
import subprocess

from cockpitlib.errors import CockpitError
from cockpitlib.forges import base


class World:
    """What a check may ask for besides the forge itself. `repo` is a repo of the pack with a checkout and a remote."""

    forge = None
    repo = ""

    def dry(self):
        """The same forge in a dry run."""
        raise NotImplementedError

    def branch(self, name: str) -> str:
        """A branch one commit ahead of main, on the forge's remote. Its sha."""
        raise NotImplementedError

    def draft(self, head: str) -> int:
        """A draft pull request of that branch onto main. Its number."""
        raise NotImplementedError

    def their_thread(self, number: int, body: str) -> int:
        """A review thread someone else opened on the pull request. The id of its first comment."""
        raise NotImplementedError

    def check(self, sha: str, name: str, conclusion: str) -> None:
        """A finished check on the commit."""
        raise NotImplementedError

    def main(self) -> str:
        """The sha of main."""
        folder = os.path.join(os.environ["COCKPIT_ROOT"], "repos", self.repo)
        return subprocess.run(
            ["git", "-C", folder, "rev-parse", "main"], check=True, capture_output=True, text=True
        ).stdout.strip()


def _open(world, head="work/one", title="A change", body="What it does."):
    sha = world.branch(head)
    made = world.forge.create_pr(world.repo, title, body, head, "main")
    return made["number"], sha


def check_a_pull_request_is_opened_read_and_found_by_its_head(world):
    forge = world.forge
    number, sha = _open(world)
    found = forge.pr(world.repo, number)
    assert (found["number"], found["title"], found["body"], found["state"]) == (
        number,
        "A change",
        "What it does.",
        "open",
    )
    assert (
        not found["draft"]
        and not found["merged"]
        and found["head"] == {"ref": "work/one", "sha": sha}
        and found["base"]["ref"] == "main"
    )
    assert found["user"]["login"] == forge.me() and found["html_url"] == forge.url(world.repo, number)
    assert forge.url(world.repo, number).endswith(f"/pull/{number}") and forge.url(world.repo, number).startswith(
        forge.url(world.repo)
    )
    assert forge.pr_for_head(world.repo, "work/one", "main")["number"] == number
    assert forge.pr_for_head(world.repo, "work/one")["number"] == number
    assert (
        forge.pr_for_head(world.repo, "work/one", "release") == {} and forge.pr_for_head(world.repo, "work/none") == {}
    )
    assert [row["number"] for row in forge.open_prs_for_branch(world.repo, "work/one")] == [number]
    assert forge.open_prs_for_branch(world.repo, "work/none") == []


def check_a_pull_request_is_edited_field_by_field(world):
    forge = world.forge
    number, _sha = _open(world)
    forge.update_pr(world.repo, number, {"title": "A better title"})
    found = forge.pr(world.repo, number)
    assert (found["title"], found["body"], found["base"]["ref"]) == ("A better title", "What it does.", "main")
    forge.update_pr(world.repo, number, {"body": "More words.", "base": "release"})
    found = forge.pr(world.repo, number)
    assert (found["title"], found["body"], found["base"]["ref"]) == ("A better title", "More words.", "release")


def check_labels_are_added_set_and_removed_and_people_assigned(world):
    forge = world.forge
    number, _sha = _open(world)
    assert forge.labels(world.repo, number) == []
    forge.add_labels(world.repo, number, ["review", "bug"])
    assert forge.labels(world.repo, number) == ["bug", "review"]
    forge.add_labels(world.repo, number, ["bug", "urgent"])
    assert forge.labels(world.repo, number) == ["bug", "review", "urgent"]
    forge.remove_label(world.repo, number, "review")
    assert forge.labels(world.repo, number) == ["bug", "urgent"]
    forge.set_labels(world.repo, number, ["done"])
    assert forge.labels(world.repo, number) == ["done"]
    forge.assign(world.repo, number, [forge.me()])
    assert [row["login"] for row in forge.pr(world.repo, number)["assignees"]] == [forge.me()]


def check_a_conversation_comment_is_made_and_listed(world):
    forge = world.forge
    number, _sha = _open(world)
    assert forge.comments(world.repo, number) == []
    made = forge.add_comment(world.repo, number, "Ready for a look.")
    assert made["html_url"]
    rows = forge.comments(world.repo, number)
    assert [(row["id"], row["kind"], row["author"], row["body"], row["url"]) for row in rows] == [
        (f"issue:{made['id']}", "comment", forge.me(), "Ready for a look.", made["html_url"])
    ]


def check_a_review_thread_is_replied_to_thumbed_and_resolved(world):
    forge = world.forge
    number, _sha = _open(world)
    first = world.their_thread(number, "Why this default?")
    thread = next(
        row for row in forge.threads(world.repo, number) if row["comments"]["nodes"][0]["databaseId"] == first
    )
    assert not thread["isResolved"] and thread["comments"]["nodes"][0]["author"]["login"] != forge.me()
    made = forge.reply(world.repo, number, first, "Because the old one lost data.")
    after = next(row for row in forge.threads(world.repo, number) if row["id"] == thread["id"])
    assert [row["author"]["login"] == forge.me() for row in after["comments"]["nodes"]] == [False, True]
    assert after["comments"]["nodes"][1]["databaseId"] == made["id"]
    assert forge.reactions(world.repo, first) == []
    forge.react(world.repo, first, "+1")
    assert [(row["content"], row["user"]["login"]) for row in forge.reactions(world.repo, first)] == [
        ("+1", forge.me())
    ]
    forge.resolve_thread(thread["id"])
    assert next(row for row in forge.threads(world.repo, number) if row["id"] == thread["id"])["isResolved"]
    inline = [row for row in forge.comments(world.repo, number) if row["kind"] == "inline"]
    assert {row["id"] for row in inline} == {f"inline:{first}", f"inline:{made['id']}"}


def check_a_review_is_written_pending_amended_and_submitted(world):
    forge = world.forge
    number, sha = _open(world)
    me = forge.me()
    threads = [
        {"path": "src/a.txt", "line": 1, "side": "RIGHT", "body": "First finding."},
        {"path": "src/b.txt", "line": 2, "side": "RIGHT", "body": "Second finding."},
    ]
    made = forge.create_review(world.repo, number, sha, threads)
    review = made["id"]
    assert forge.review(world.repo, number, review)["state"] == "PENDING"
    pending = [
        row for row in forge.reviews(world.repo, number) if row["state"] == "PENDING" and row["user"]["login"] == me
    ]
    assert [row["id"] for row in pending] == [review]
    got = forge.review_comments(world.repo, number, review)
    assert sorted(row["path"] for row in got) == ["src/a.txt", "src/b.txt"]
    forge.add_review_thread(
        world.repo, number, pending[0], {"path": "src/c.txt", "line": 3, "side": "RIGHT", "body": "Third finding."}
    )
    got = forge.review_comments(world.repo, number, review)
    assert sorted(row["path"] for row in got) == ["src/a.txt", "src/b.txt", "src/c.txt"]
    first = next(row for row in got if row["path"] == "src/a.txt")
    forge.edit_review_comment(world.repo, first["id"], "First finding, said better.")
    assert {row["id"]: row["body"] for row in forge.review_comments(world.repo, number, review)}[
        first["id"]
    ] == "First finding, said better."
    forge.update_review(world.repo, number, review, "Three things.")
    state = forge.review(world.repo, number, review)
    assert (state["state"], state["body"]) == ("PENDING", "Three things.")
    assert [
        row for row in forge.comments(world.repo, number) if row["kind"] == "review"
    ] == []  # not a comment until it is submitted
    forge.submit_review(world.repo, number, review, "REQUEST_CHANGES", "Three things to change.")
    state = forge.review(world.repo, number, review)
    assert (state["state"], state["body"]) == ("CHANGES_REQUESTED", "Three things to change.")
    said = [row for row in forge.comments(world.repo, number) if row["kind"] == "review"]
    assert [(row["id"], row["author"], row["review_state"], row["body"]) for row in said] == [
        (f"review:{review}", me, "CHANGES_REQUESTED", "Three things to change.")
    ]
    assert len(forge.threads(world.repo, number)) == 3


def check_a_pending_review_is_discarded(world):
    forge = world.forge
    number, sha = _open(world)
    made = forge.create_review(
        world.repo, number, sha, [{"path": "src/a.txt", "line": 1, "side": "RIGHT", "body": "A finding."}]
    )
    forge.discard_review(world.repo, number, made["id"])
    assert [row for row in forge.reviews(world.repo, number) if row["id"] == made["id"]] == []


def check_what_is_not_green_on_a_commit_is_named(world):
    forge = world.forge
    _number, sha = _open(world)
    assert forge.checks(world.repo, sha) == ["no checks reported"]
    world.check(sha, "unit", "success")
    assert forge.checks(world.repo, sha) == []
    world.check(sha, "lint", "failure")
    assert forge.checks(world.repo, sha) == ["lint: failure"]


def check_a_draft_is_marked_ready_once(world):
    forge = world.forge
    world.branch("work/draft")
    number = world.draft("work/draft")
    assert forge.pr(world.repo, number)["draft"]
    forge.mark_ready(world.repo, number)
    assert not forge.pr(world.repo, number)["draft"]
    before = len(forge.writes)
    forge.mark_ready(world.repo, number)
    assert len(forge.writes) == before and not forge.pr(world.repo, number)["draft"]


def check_two_commits_are_compared(world):
    forge = world.forge
    sha = world.branch("work/one")
    found = forge.compare(world.repo, world.main(), sha)
    assert found["total_commits"] == 1 and len(found["files"]) == 1


def check_a_dry_run_reads_and_journals_and_writes_nothing(world):
    number, _sha = _open(world)
    dry = world.dry()
    assert dry.dry_run and dry.writes == []
    assert dry.pr(world.repo, number)["title"] == "A change"
    assert dry.update_pr(world.repo, number, {"title": "Not sent"}) == {"dry_run": True}
    assert dry.add_comment(world.repo, number, "Not sent") == {"dry_run": True}
    dry.add_labels(world.repo, number, ["not-sent"])
    assert len(dry.writes) == 3
    assert world.forge.pr(world.repo, number)["title"] == "A change" and world.forge.labels(world.repo, number) == []
    assert world.forge.comments(world.repo, number) == []


def check_a_missing_pull_request_is_a_refusal_not_an_empty_answer(world):
    try:
        world.forge.pr(world.repo, 999)
    except CockpitError:
        return
    raise AssertionError("a pull request that is not there was read")


def check_an_issue_is_made_read_edited_closed_and_opened_again(world):
    forge = world.forge
    assert base.ISSUES in forge.capabilities()
    made = forge.create_issue(
        world.repo, "The export has no header", "Seen on run 1.", labels=["bug"], assignees=[forge.me()]
    )
    number = made["number"]
    found = forge.issue(world.repo, number)
    assert found == made and set(found) >= {"number", "title", "body", "state", "labels", "author", "assignees", "url"}
    assert (found["title"], found["body"], found["state"], found["labels"]) == (
        "The export has no header",
        "Seen on run 1.",
        "open",
        ["bug"],
    )
    assert (found["author"], found["assignees"]) == (forge.me(), [forge.me()])
    assert found["url"] == forge.issue_url(world.repo, number) == f"{forge.url(world.repo)}/issues/{number}"
    assert (
        forge.update_issue(world.repo, number, {"title": "The export lost its header"})["title"]
        == "The export lost its header"
    )
    found = forge.issue(world.repo, number)
    assert (found["title"], found["body"], found["state"]) == ("The export lost its header", "Seen on run 1.", "open")
    forge.update_issue(world.repo, number, {"body": "Seen on runs 1 and 2.", "state": "closed"})
    found = forge.issue(world.repo, number)
    assert (found["title"], found["body"], found["state"]) == (
        "The export lost its header",
        "Seen on runs 1 and 2.",
        "closed",
    )
    forge.update_issue(world.repo, number, {"state": "open"})
    assert forge.issue(world.repo, number)["state"] == "open"
    plain = forge.create_issue(world.repo, "A second one", "")
    assert plain["number"] != number and (plain["body"], plain["labels"], plain["assignees"]) == ("", [], [])
    for fields in ({"state": "merged"}, {"labels": ["x"]}):
        try:
            forge.update_issue(world.repo, number, fields)
        except CockpitError:
            continue
        raise AssertionError(f"an issue was edited with {fields}")


def check_an_issue_and_a_pull_request_never_share_a_number(world):
    forge = world.forge
    pull, _sha = _open(world)
    issue = forge.create_issue(world.repo, "A report", "")["number"]
    world.branch("work/two")
    later = forge.create_pr(world.repo, "Another change", "", "work/two", "main")["number"]
    assert len({pull, issue, later}) == 3 and pull < issue < later
    assert (
        forge.pr(world.repo, later)["title"] == "Another change"
        and forge.issue(world.repo, issue)["title"] == "A report"
    )
    for ask in (lambda: forge.issue(world.repo, pull), lambda: forge.pr(world.repo, issue)):
        try:
            ask()
        except CockpitError:
            continue
        raise AssertionError("a pull request was read as an issue, or an issue as a pull request")


def check_an_issue_carries_labels_and_people_like_a_pull_request(world):
    forge = world.forge
    number = forge.create_issue(world.repo, "A report", "", labels=["bug"])["number"]
    assert forge.labels(world.repo, number) == ["bug"]
    forge.add_labels(world.repo, number, ["in progress"])
    assert forge.labels(world.repo, number) == ["bug", "in progress"] == forge.issue(world.repo, number)["labels"]
    forge.set_labels(world.repo, number, ["bug", "in review"])
    assert forge.issue(world.repo, number)["labels"] == ["bug", "in review"]
    forge.remove_label(world.repo, number, "bug")
    assert forge.labels(world.repo, number) == ["in review"]
    forge.assign(world.repo, number, [forge.me()])
    assert forge.issue(world.repo, number)["assignees"] == [forge.me()]


def check_an_issue_is_commented_on_and_a_comment_edited(world):
    forge = world.forge
    number = forge.create_issue(world.repo, "A report", "")["number"]
    other = forge.create_issue(world.repo, "Another report", "")["number"]
    assert forge.issue_comments(world.repo, number) == []
    first = forge.add_issue_comment(world.repo, number, "Tested and Not Ok.")
    second = forge.add_issue_comment(world.repo, number, "Second note.")
    forge.add_issue_comment(world.repo, other, "On the other one.")
    rows = forge.issue_comments(world.repo, number)
    assert [(row["id"], row["author"], row["body"]) for row in rows] == [
        (first["id"], forge.me(), "Tested and Not Ok."),
        (second["id"], forge.me(), "Second note."),
    ]
    assert rows[0] == first and set(first) >= {"id", "author", "body", "url", "created", "updated"}
    assert (
        first["url"].startswith(forge.issue_url(world.repo, number))
        and first["created"] == first["updated"] < second["created"]
    )
    assert [row["id"] for row in forge.issue_comments(world.repo, number, since=second["created"])] == [second["id"]]
    forge.edit_issue_comment(world.repo, first["id"], "Tested and Ok after the fix.")
    rows = forge.issue_comments(world.repo, number)
    assert [(row["id"], row["body"]) for row in rows] == [
        (first["id"], "Tested and Ok after the fix."),
        (second["id"], "Second note."),
    ]
    assert rows[0]["created"] == first["created"] and rows[0]["updated"] > second["updated"]
    assert sorted(row["id"] for row in forge.issue_comments(world.repo, number, since=second["created"])) == sorted(
        [first["id"], second["id"]]
    )
    assert [row["body"] for row in forge.issue_comments(world.repo, other)] == ["On the other one."]
    try:
        forge.edit_issue_comment(world.repo, 999999, "Nothing to edit.")
    except CockpitError:
        return
    raise AssertionError("a comment that is not there was edited")


def check_a_dry_run_reads_an_issue_and_journals_its_writes(world):
    number = world.forge.create_issue(world.repo, "A report", "", labels=["bug"])["number"]
    said = world.forge.add_issue_comment(world.repo, number, "As it is.")
    dry = world.dry()
    assert dry.issue(world.repo, number)["title"] == "A report" and len(dry.issue_comments(world.repo, number)) == 1
    assert dry.create_issue(world.repo, "Not made", "") == {"dry_run": True}
    assert dry.update_issue(world.repo, number, {"state": "closed"}) == {"dry_run": True}
    assert dry.add_issue_comment(world.repo, number, "Not sent") == {"dry_run": True}
    dry.edit_issue_comment(world.repo, said["id"], "Not sent")
    assert len(dry.writes) == 4
    found = world.forge.issue(world.repo, number)
    assert (found["state"], found["labels"]) == ("open", ["bug"])
    assert [row["body"] for row in world.forge.issue_comments(world.repo, number)] == ["As it is."]
    try:
        world.forge.issue(world.repo, number + 1)
    except CockpitError:
        return
    raise AssertionError("the dry run made an issue, or one that is not there was read")


def check_a_missing_issue_is_a_refusal_not_an_empty_answer(world):
    for ask in (
        lambda: world.forge.issue(world.repo, 999),
        lambda: world.forge.issue_comments(world.repo, 999),
        lambda: world.forge.add_issue_comment(world.repo, 999, "To no one."),
        lambda: world.forge.update_issue(world.repo, 999, {"state": "closed"}),
    ):
        try:
            ask()
        except CockpitError:
            continue
        raise AssertionError("an issue that is not there was read or written")


def check_it_says_what_it_is_and_what_it_has(world):
    forge = world.forge
    assert (
        forge.kind
        and forge.me()
        and forge.repo(world.repo) == f"{forge.org}/{world.repo}"
        and forge.repo("other/name") == "other/name"
    )
    assert set(forge.capabilities()) <= set(base.CAPABILITIES)
    assert {
        base.PULL_REQUESTS,
        base.DRAFT,
        base.REVIEW_THREADS,
        base.PENDING_REVIEWS,
        base.REACTIONS,
        base.CHECKS,
        base.DIFF,
    } <= set(forge.capabilities())
    assert isinstance(forge.hosts(), list) and isinstance(type(forge).cli_deny(), tuple)
    assert forge.branch_url(world.repo, "work/one").startswith(forge.url(world.repo))
    assert forge.review_url(world.repo, 4, 9).startswith(forge.url(world.repo, 4)) and forge.run_url(
        world.repo, 5
    ).startswith(forge.url(world.repo))
    assert forge.issue_url(world.repo, 6) == f"{forge.url(world.repo)}/issues/6"


CHECKS = [value for name, value in sorted(globals().items()) if name.startswith("check_")]
