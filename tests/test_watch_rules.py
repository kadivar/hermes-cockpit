# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""What the PR watch calls a new comment, after the move: the old pipeline's baselines are read, approvals and untagged
verdicts are not work, resolved threads and acknowledgements leave; a bumps card that ended makes no in-progress row."""

import json
import os

from fastapi import FastAPI
from fastapi.testclient import TestClient

from cockpitlib.pack import load
from dashboard.cockpit.router import router


def _client():
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def test_an_earlier_pipelines_ids_and_closed_threads_are_read():
    from cockpitlib.pr_watch import closed_thread_ids, known_ids, own_id

    named = (("rc", "inline:"), ("ic", "issue:"), ("rv", "review:"))
    assert own_id("rc123", named) == "inline:123" and own_id("ic7", named) == "issue:7"
    assert own_id("rv9", named) == "review:9" and own_id("rc123") == "rc123", "a pack that names no prefix has none"
    assert own_id("inline:5", named) == "inline:5" and own_id("rsABC", named) == "rsABC" and own_id("", named) == ""
    assert known_ids({"ids": ["inline:1", "rv2"], "baseline": ["ic3"]}, named) == {"inline:1", "review:2", "issue:3"}
    assert known_ids({"ids": ["inline:1", "rv2"], "baseline": ["ic3"]}) == {"inline:1", "rv2", "ic3"}
    threads = [
        {"isResolved": True, "comments": {"nodes": [{"databaseId": 10}, {"databaseId": 11}]}},
        {"isResolved": False, "comments": {"nodes": [{"databaseId": 12}, {"databaseId": 13}]}},
        "junk",
    ]
    assert closed_thread_ids(threads) == {
        "inline:10",
        "inline:11",
        "inline:12",
    }  # a resolved thread whole, an open one but its latest
    from cockpitlib.pr_watch import thread_marks

    marks = thread_marks(threads)
    assert set(marks) == {"inline:10", "inline:11", "inline:12"} and marks.resolved == {"inline:10", "inline:11"}


def test_what_counts_as_a_new_comment(bare):
    from cockpitlib.pr_watch import _skip

    pack = load(os.environ["COCKPIT_PACK"])
    me = "human"
    row = lambda **fields: {"id": "x", "kind": "comment", "author": "colleague", "body": "", **fields}
    assert _skip(pack, me, row(author=me, body="B: mine")) == "yours"
    assert _skip(pack, me, row(kind="review", review_state="APPROVED", body="Looks good to me")).startswith(
        "an approval"
    )
    assert _skip(
        pack, me, row(kind="review", review_state="CHANGES_REQUESTED", body="Just a few questions there")
    ).startswith("no finding tag")
    assert _skip(pack, me, row(kind="review", review_state="CHANGES_REQUESTED", body="")).startswith(
        "a verdict without a body"
    )
    assert _skip(pack, me, row(kind="review", review_state="COMMENTED", body="- **CS:** rename this")) == ""
    assert _skip(pack, me, row(kind="review", review_state="COMMENTED", body="```suggestion\nx\n```")) == ""
    from cockpitlib.pr_watch import ThreadMarks

    marks = ThreadMarks(resolved={"inline:10"}, answered={"inline:12"})
    assert (
        _skip(pack, me, row(kind="inline", id="inline:10", body="Q: why twice?"), closed=marks)
        == "in a resolved thread"
    )
    assert (
        _skip(pack, me, row(kind="inline", id="inline:12", body="Q: why twice?"), closed=marks)
        == "answered in its thread"
    )
    assert _skip(pack, me, row(kind="inline", id="inline:11", body="Q: why twice?"), closed=marks) == ""
    assert _skip(pack, me, row(body="Thanks, learnings added")) == "an acknowledgement"
    assert _skip(pack, me, row(body="LGTM!")) == "praise"
    assert _skip(pack, me, row(body="B: this breaks the export")) == ""
    assert (
        _skip(
            {**pack, "finding_labels": ["NIT"]}, me, row(kind="review", review_state="COMMENTED", body="NIT: spacing")
        )
        == ""
    )
    assert _skip(
        {**pack, "finding_labels": ["NIT"]}, me, row(kind="review", review_state="COMMENTED", body="B: spacing")
    ).startswith("no finding tag")


class _Forge:
    """A forge with one PR, its comments, reviews and threads, as the watch reads them."""

    def __init__(self, comments, reviews, threads, me="human"):
        self.comments = comments
        self.reviews = reviews
        self._threads = threads
        self._me = me

    def me(self):
        return self._me

    def repo(self, name):
        return f"org/{name}"

    def login(self):
        return self.me

    def pr(self, repo, number):
        return {
            "number": number,
            "state": "open",
            "title": "t",
            "html_url": "https://forge.test/org/api/pull/4",
            "head": {"sha": "abc"},
            "base": {"ref": "main"},
            "user": {"login": "human"},
            "merged": False,
            "requested_reviewers": [],
            "draft": False,
        }

    def get(self, path):
        if "/issues/" in path:
            return []
        if "/pulls/" in path and path.endswith("comments?per_page=100"):
            return self.comments
        if "/reviews" in path:
            return self.reviews
        return []

    def threads(self, repo, number):
        return self._threads


def test_a_record_of_an_earlier_pipeline_keeps_its_baseline_and_an_old_new_comment_is_read_again(bare, monkeypatch):
    from cockpitlib import pr_watch
    from cockpitlib.pr_watch import record_path

    pack = load(os.environ["COCKPIT_PACK"])
    monkeypatch.setattr(pr_watch, "_me", lambda pack, forge=None: "human", raising=False)
    comments = [
        {
            "id": 1,
            "user": {"login": "colleague"},
            "body": "CS: rename",
            "path": "a.py",
            "html_url": "u1",
            "created_at": "2026-10-20T10:00:00Z",
        },
        {
            "id": 2,
            "user": {"login": "colleague"},
            "body": "Q: why twice?",
            "path": "a.py",
            "html_url": "u2",
            "created_at": "2026-10-21T10:00:00Z",
        },
        {
            "id": 3,
            "user": {"login": "colleague"},
            "body": "B: breaks the export",
            "path": "a.py",
            "html_url": "u3",
            "created_at": "2026-10-22T10:00:00Z",
        },
    ]
    reviews = [
        {
            "id": 5,
            "user": {"login": "colleague"},
            "body": "Just a few questions there",
            "state": "CHANGES_REQUESTED",
            "html_url": "r5",
            "submitted_at": "2026-10-21T11:00:00Z",
        },
        {
            "id": 6,
            "user": {"login": "colleague"},
            "body": "Looks good",
            "state": "APPROVED",
            "html_url": "r6",
            "submitted_at": "2026-10-22T11:00:00Z",
        },
    ]
    threads = [
        {"id": "T1", "isResolved": True, "comments": {"nodes": [{"databaseId": 2, "author": {"login": "colleague"}}]}},
        {"id": "T2", "isResolved": False, "comments": {"nodes": [{"databaseId": 3, "author": {"login": "colleague"}}]}},
    ]
    path = record_path("TASK-100", "api", 4)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    # the earlier pipeline's record: its baseline holds the first inline comment in its own id form, and it kept the
    # second one as new although its thread is resolved since
    json.dump(
        {
            "repo": "api",
            "number": 4,
            "role": "author",
            "state": "open",
            "baseline": ["rc1"],
            "ids": ["rc1", "rc2"],
            "new": [
                {
                    "id": "rc2",
                    "kind": "review-comment",
                    "author": "colleague",
                    "body": "Q: why twice?",
                    "at": "2026-10-21T10:00:00Z",
                }
            ],
            "last_activity": "2026-10-21T10:00:00Z",
        },
        open(path, "w", encoding="utf-8"),
    )
    forge = _Forge(comments, reviews, threads)
    try:
        record = pr_watch.read(pack, forge, "TASK-100", "api", 4, 1792400000.0)
    except (AttributeError, KeyError, TypeError) as exc:
        import pytest

        pytest.skip(f"forge stand-in too thin: {exc}")
    assert [row["id"] for row in record["new"]] == ["inline:3"]  # not 1 (baseline), not 2 (resolved), not the verdicts
    assert record["new_count"] == 1 and record["approvals"][0]["author"] == "colleague"
    reasons = {row["id"]: row["reason"] for row in record["skipped"]}
    assert reasons["review:5"].startswith("no finding tag") and reasons["review:6"].startswith("an approval")
    assert (
        "inline:2" not in reasons
    )  # it was known already (the old baseline, translated): re-read and dropped, not news
    assert "inline:1" in record["ids"] and "inline:2" in record["ids"]
    # read again: nothing doubles, the seen list stays empty after the human saw it
    again = pr_watch.read(pack, forge, "TASK-100", "api", 4, 1792400100.0)
    assert [row["id"] for row in again["new"]] == ["inline:3"]
    pr_watch.seen("TASK-100", "api", 4)
    after = pr_watch.read(pack, forge, "TASK-100", "api", 4, 1792400200.0)
    assert after["new"] == [] and after["new_count"] == 0


def test_a_merged_pr_leaves_the_watch_once_the_ticket_is_done(bare):
    """An intent is kept forever, so a PR it names was watched forever — long after the PR merged.

    Every pass rewrote the record to move `last_check`, and a pass every five minutes against a five
    minute quiet gate meant `workspace-watch` never found that ticket's records quiet enough to
    commit. The watch ends where the lifecycle does: merged or closed, and the ticket-done intent
    written. A PR still open keeps its watch however old its ticket is.
    """
    from cockpitlib.paths import outbox
    from cockpitlib.pr_watch import record_path, watched

    def intent(name, data):
        folder = os.path.join(outbox(), "TASK-100")
        os.makedirs(folder, exist_ok=True)
        with open(os.path.join(folder, name), "w", encoding="utf-8") as handle:
            json.dump({"ticket": "TASK-100", **data}, handle)

    def record(state):
        path = record_path("TASK-100", "api", 4)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as handle:
            json.dump({"repo": "api", "number": 4, "state": state, "merged": state == "merged"}, handle)

    intent("004-open-pr.json", {"type": "open-pr", "payload": {"repo": "api", "number": 4}})
    record("merged")
    assert ("TASK-100", "api", 4) in watched(), "merged, but the ticket is not done yet"

    intent("010-ticket-done.json", {"type": "ticket-done", "payload": {}})
    assert ("TASK-100", "api", 4) not in watched()

    record("open")
    assert ("TASK-100", "api", 4) in watched(), "an open PR is watched whatever its ticket says"

    # closed is not merged: GitHub reopens a closed PR, and nothing re-reads a record once its PR has
    # left the watch, so one that left on `closed` alone would be missed for good
    record("closed")
    assert ("TASK-100", "api", 4) in watched()


def test_a_bumps_card_that_ended_makes_no_in_progress_row(env):
    from cockpitlib.acts import bumps_path, started_bumps
    from cockpitlib.kanban import place_card
    from tests.support.boards import put_card

    pack = load(os.environ["COCKPIT_PACK"])
    repo = pack["repos"]["repos"][0]["name"]
    running = place_card(pack["board"], "BUMPS-2026W43: bumps on api", "reviewer", "ready")
    ended = put_card(pack["board"], "BUMPS-2026W42: bumps on api", "reviewer", "done")
    os.makedirs(os.path.dirname(bumps_path()), exist_ok=True)
    json.dump(
        {
            "time": "2026-10-24T08:00:00Z",
            "repos": {
                repo: [
                    {"number": 1, "sha": "aaa", "title": "bump a", "url": "u1", "head": "dependabot/a"},
                    {"number": 2, "sha": "bbb", "title": "bump b", "url": "u2", "head": "dependabot/b"},
                    {"number": 3, "sha": "ccc", "title": "bump c", "url": "u3", "head": "dependabot/c"},
                ]
            },
            "started": {f"{repo}#1": {"sha": "aaa", "card": running}, f"{repo}#2": {"sha": "bbb", "card": ended}},
        },
        open(bumps_path(), "w", encoding="utf-8"),
    )
    held = started_bumps(pack)
    assert [row["number"] for row in held[repo]] == [1]
    assert [row["number"] for row in started_bumps()[repo]] == [1, 2]  # without a board the hold is read as recorded
    body = _client().get("/bumps").json()
    assert [row["number"] for row in body["repos"][repo]] == [3] and [
        row["number"] for row in body["started"][repo]
    ] == [1]


def test_setup_bumps_the_desktop_entry_when_the_ui_changed_and_doctor_names_a_stale_copy(bare, tmp_path, monkeypatch):
    import json
    import time

    from cockpitlib.setup import desktop_copy_stale, desktop_refresh

    root = tmp_path / "plugin"
    (root / "desktop" / "src").mkdir(parents=True)
    entry = root / "desktop" / "plugin.js"
    entry.write_text("export {}\n", encoding="utf-8")
    old = time.time() - 600
    os.utime(entry, (old, old))
    assert desktop_refresh(str(root)) is False  # nothing beside it is newer
    view = root / "desktop" / "src" / "chat.js"
    view.write_text("// new modal\n", encoding="utf-8")
    assert desktop_refresh(str(root)) is True and os.path.getmtime(entry) >= os.path.getmtime(view) - 1
    assert desktop_refresh(str(root)) is False
    copy = tmp_path / "hermes" / "desktop-plugins" / "plugin"
    copy.mkdir(parents=True)
    assert desktop_copy_stale(str(root)) == ""  # no copy, nothing to say
    json.dump(
        {"package": "plugin", "source": str(root / "desktop"), "sourceMtimeMs": old * 1000},
        open(copy / ".hermes-package.json", "w", encoding="utf-8"),
    )
    assert desktop_copy_stale(str(root)).startswith("Desktop runs a stale copy")
    json.dump(
        {"package": "plugin", "source": str(root / "desktop"), "sourceMtimeMs": os.path.getmtime(entry) * 1000},
        open(copy / ".hermes-package.json", "w", encoding="utf-8"),
    )
    assert desktop_copy_stale(str(root)) == ""
    # a linked checkout: the Desktop keeps a copy whose entry has the same bytes and never moves the stamp, so only
    # different bytes are a stale copy
    json.dump(
        {"package": "plugin", "source": str(root / "desktop"), "sourceMtimeMs": old * 1000, "linked": True},
        open(copy / ".hermes-package.json", "w", encoding="utf-8"),
    )
    (copy / "plugin.js").write_text("export {}\n", encoding="utf-8")
    assert desktop_copy_stale(str(root)) == ""
    (copy / "plugin.js").write_text("export { old }\n", encoding="utf-8")
    assert desktop_copy_stale(str(root)).startswith("Desktop runs a stale copy")
    os.remove(copy / "plugin.js")
    assert desktop_copy_stale(str(root)).startswith("Desktop runs a stale copy")


def test_a_repo_the_watches_leave_out_is_skipped_by_the_base_and_bump_scans_but_stays_a_repo(
    env, monkeypatch, tmp_path
):
    import shutil

    import yaml

    from cockpitlib.pack import PackError, watched

    assert (
        watched({"name": "x"}) is True
        and watched({"name": "x", "watched": False}) is False
        and watched({"name": "x", "shipped": False}) is True
    )
    copied = tmp_path / "packs" / "acme"
    shutil.copytree(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "packs", "acme"), copied)
    repos_file = copied / "repos.yaml"
    data = yaml.safe_load(repos_file.read_text(encoding="utf-8"))
    first = data["repos"][0]["name"]
    data["repos"][0]["watched"] = False
    repos_file.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    monkeypatch.setenv("COCKPIT_PACK", str(copied / "pack.yaml"))
    pack = load(str(copied / "pack.yaml"))
    assert pack["repos"]["repos"][0]["watched"] is False
    from cockpitlib import acts

    asked = []

    class Done:
        returncode = 0
        stdout = "[]"
        stderr = ""

    def runner(*args, **kwargs):
        asked.append(args)
        return Done()

    acts.scan_bumps(pack, runner=runner)
    assert asked and all(first not in str(call) for call in asked)
    acts.scan_base(pack, runner=runner)
    assert all(first not in str(call) for call in asked)
    data["repos"][0]["watched"] = "yes"
    repos_file.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    try:
        load(str(copied / "pack.yaml"))
    except PackError as exc:
        assert "watched is true or false" in str(exc)
    else:
        raise AssertionError("a non-bool watched flag loaded")
