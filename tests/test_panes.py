# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The Inbox panes after the move: an intent's pane is the enriched list row with its Brief, the diff pane reads the
checkout in every mode, the demo card's staging login comes from a seat store on a sealed machine, and the standup
note has its sections."""

import json
import os
import subprocess
import time

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from cockpitlib.pack import load
from dashboard.cockpit.router import router


def _client():
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def _git(folder, *args):
    base = {
        **os.environ,
        "GIT_AUTHOR_NAME": "Dev",
        "GIT_AUTHOR_EMAIL": "dev@example.test",
        "GIT_COMMITTER_NAME": "Dev",
        "GIT_COMMITTER_EMAIL": "dev@example.test",
    }
    return subprocess.run(["git", "-C", folder, *args], check=True, capture_output=True, text=True, env=base).stdout


def _checkout(ticket: str, repo: str) -> str:
    """A ticket checkout under wt/ with one commit on top of origin/main, as a lane leaves it."""
    source = os.path.join(os.environ["COCKPIT_ROOT"], "repos", repo)
    folder = os.path.join(os.environ["COCKPIT_WT"], ticket, repo)
    os.makedirs(os.path.dirname(folder), exist_ok=True)
    subprocess.run(["git", "clone", "-q", source, folder], check=True, capture_output=True)
    _git(folder, "fetch", "-q", "origin")
    _git(folder, "checkout", "-q", "-b", f"work/{ticket}")
    open(os.path.join(folder, "feature.txt"), "w", encoding="utf-8").write("one\n")
    _git(folder, "add", "feature.txt")
    _git(folder, "commit", "-q", "-m", f"add the feature [{ticket}]")
    return folder


def _stamp(epoch: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime(epoch))


def test_an_intent_pane_is_the_list_row_with_what_leaves_its_log_and_its_brief(env):
    from cockpitlib.outbox import create, endorse

    pack = load(os.environ["COCKPIT_PACK"])
    folder = _checkout("TASK-100", "api")
    sha = _git(folder, "rev-parse", "HEAD").strip()
    note = os.path.join(os.environ["COCKPIT_WORKSPACE"], "hermes", "qa", "TASK-100", "comment.md")
    os.makedirs(os.path.dirname(note), exist_ok=True)
    open(note, "w", encoding="utf-8").write("Hello **there**\n")
    pushed = create(
        pack,
        "TASK-100",
        "push-branch",
        "c1",
        "ship the feature",
        {"repo": "api", "branch": "work/TASK-100", "sha": sha, "base": "origin/main"},
    )
    endorse(pushed["id"], "low", "fine", "gatekeeper", "fixture-a", "fixture-large")
    comment = create(
        pack,
        "TASK-100",
        "tracker-comment",
        "c1",
        "tell the tracker",
        {"issue": "TASK-100", "body_file": os.path.relpath(note, os.environ["COCKPIT_WORKSPACE"])},
    )
    client = _client()
    shown = client.get("/intent", params={"id": pushed["id"]}).json()
    assert (
        shown["id"] == pushed["id"]
        and shown["status"] == "endorsed"
        and shown["target"] == "api"
        and "skills" in shown
        and "waits" in shown
    )
    assert (
        '<div class="k">What leaves</div>' in shown["brief"]
        and "1 commit(s), 1 file(s)" in shown["brief"]
        and "gatekeeper endorsed, risk low: fine" in shown["brief"]
    )
    assert "<code>feature.txt</code>" in shown["brief"] and shown["outgoing"] is None and shown["file_contents"] == {}
    assert all(pushed["id"] in line for line in shown["log"])  # the receipt log's lines about this intent only
    shown = client.get("/intent", params={"id": comment["id"]}).json()
    assert shown["outgoing"] == "body_file" and shown["file_contents"]["body_file"] == "Hello **there**\n"
    assert "<strong>there</strong>" in shown["file_html"]["body_file"] and shown["file_truncated"] == []
    assert (
        "a comment on the tracker issue TASK-100" in shown["brief"] and "waiting for the gatekeeper" in shown["brief"]
    )
    assert client.get("/intent", params={"id": "TASK-100/099-push-branch"}).status_code == 404
    from cockpitlib.intent_view import adf_of, brief_fields, plan_one_liner

    assert (
        adf_of('{"type": "doc", "content": []}') == {"type": "doc", "content": []}
        and adf_of("not json") is None
        and adf_of('{"type": "x"}') is None
    )
    assert plan_one_liner("TASK-404") == ("", [])
    fields = brief_fields(
        {
            "type": "ticket-done",
            "ticket": "TASK-100",
            "payload": {"repo": "api", "number": 4, "merged_at": "2026-10-22T08:30:00Z"},
            "status": "pending",
            "summary": "all merged",
        }
    )
    assert (
        fields[0]["text"].startswith("nothing. Your acknowledgement")
        and fields[1]["text"] == "all merged"
        and "PR #4 merged at 2026-10-22T08:30" in fields[3]["items"]
    )
    fields = brief_fields(
        {
            "type": "pr-review-submit",
            "ticket": "TASK-100",
            "payload": {"repo": "api", "number": 4, "event": "APPROVE"},
            "status": "posted",
            "file_contents": {"body_file": "1. **B:** wrong\n- CS: style\nQ: why?\n"},
            "review": {"url": "https://forge.test/r/1"},
        }
    )
    assert (
        "stage 2 of 2" in fields[0]["text"]
        and "findings: 1 blocking (B), 1 code style (CS), 1 question (Q)" in fields[3]["items"]
        and "pending review: https://forge.test/r/1" in fields[3]["items"]
    )


def test_the_diff_pane_reads_the_checkout_against_the_base_and_against_origin(env):
    from cockpitlib import diffs
    from cockpitlib.outbox import create

    pack = load(os.environ["COCKPIT_PACK"])
    folder = _checkout("TASK-100", "api")
    sha = _git(folder, "rev-parse", "HEAD").strip()
    pushed = create(
        pack,
        "TASK-100",
        "push-branch",
        "c1",
        "ship",
        {"repo": "api", "branch": "work/TASK-100", "sha": sha, "base": "origin/main"},
    )
    client = _client()
    shown = client.get("/diff", params={"id": pushed["id"], "mode": "base"}).json()
    assert (
        shown["head"] == sha
        and shown["merge_base"]
        and len(shown["commits"]) == 1
        and "feature.txt" in shown["stat"]
        and "+one" in shown["diff"]
    )
    assert (
        shown["uncommitted_status"] == ""
        and shown["ticket"] == "TASK-100"
        and shown["repo"] == "api"
        and shown["intent"] == pushed["id"]
    )
    origin = client.get("/diff", params={"id": pushed["id"], "mode": "origin"}).json()
    assert (
        origin["remote"] == "origin/work/TASK-100"
        and origin["remote_exists"] is False
        and origin["commits"] == []
        and "not known locally" in origin["note"]
    )
    # the branch reaches origin with an older tip; a local amend then shows what the force push drops
    _git(folder, "push", "-q", "origin", "work/TASK-100")
    open(os.path.join(folder, "feature.txt"), "a", encoding="utf-8").write("two\n")
    _git(folder, "commit", "-q", "-a", "--amend", "-m", "add the feature, twice [TASK-100]")
    new_sha = _git(folder, "rev-parse", "HEAD").strip()
    from cockpitlib.outbox import drop

    drop(pushed["id"], "amended")  # one open push per branch: the amended tip gets its own intent
    amended = create(
        pack,
        "TASK-100",
        "push-branch",
        "c1",
        "ship again",
        {"repo": "api", "branch": "work/TASK-100", "sha": new_sha, "base": "origin/main"},
    )
    origin = client.get("/diff", params={"id": amended["id"], "mode": "origin"}).json()
    assert origin["remote_exists"] is True and len(origin["commits"]) == 1 and origin["fast_forward"] is False
    assert [row["state"] for row in origin["dropped"]] == ["lost"] and "+two" in origin["diff"]
    whole = client.get("/diff", params={"ticket": "TASK-100", "repo": "api"}).json()
    assert (
        whole["head"] == "HEAD"
        and len(whole["commits"]) == 1
        and client.get("/diff", params={"ticket": "TASK-100", "repo": "api", "mode": "origin"}).json()["remote"]
        == "origin/work/TASK-100"
    )
    assert (
        client.get("/diff").status_code == 400
        and client.get("/diff", params={"id": "TASK-100/099-open-pr"}).status_code == 404
    )
    missing = client.get(
        "/diff", params={"ticket": "TASK-100", "repo": "nope"}
    ).json()  # no checkout: an empty pane that says so
    assert missing["diff"] == "" and missing["commits"] == [] and missing["note"].startswith("no worktree")
    assert client.get("/diff", params={"ticket": "../x", "repo": "api"}).status_code == 400
    assert (
        diffs.remote_branch_of("work/x-wt") == "work/x-wt"
        and diffs.remote_branch_of("work/x-wt", "", {"desktop": {"diff_held_suffix": "-wt"}}) == "work/x"
        and diffs.remote_branch_of("work/x-wt", "pub") == "pub"
        and diffs.ref_ok("a..b") is False
    )
    with pytest.raises(Exception):
        diffs.intent_diff(
            pack, {"type": "tracker-comment", "ticket": "TASK-100", "payload": {"issue": "TASK-100"}}, [], "base"
        )


def test_the_staging_login_comes_from_a_seat_store_when_the_sealed_store_cannot_open_here(bare, monkeypatch):
    from cockpitlib import lane_vault
    from cockpitlib import vault as own

    pack = load(os.environ["COCKPIT_PACK"])
    origin = pack["logins"]["shared"][0]["origin"]
    calls = []
    for lane in ("tester-1", "intake"):
        store = os.path.join(os.environ["COCKPIT_HERMES_HOME"], "profiles", lane, "vault")
        os.makedirs(store, exist_ok=True)
        open(os.path.join(store, "vault.json.enc"), "wb").write(b"x")

    def fake_run(ops):
        calls.append(ops)
        return [
            "pw-from-tester" if op["home"].endswith("tester-1") and op["identifier"] == "qa@example.test" else None
            for op in ops
        ]

    monkeypatch.setattr(lane_vault, "_run", fake_run)
    assert lane_vault.secret_for(pack, origin, "qa@example.test") == "pw-from-tester"
    assert [op["home"].rsplit("/", 1)[-1] for op in calls[0]][:1] == ["tester-1"] and all(
        op["op"] == "secret" for op in calls[0]
    )
    assert (
        lane_vault.secret_for(pack, origin, "nobody@example.test") == ""
        and lane_vault.secret_for(pack, origin, "") == ""
    )
    monkeypatch.setattr(own, "_previous", lambda origin, email, scope="": None)  # the sealed store answers nothing here
    assert own.human_secret(origin, "qa@example.test", pack) == "pw-from-tester"
    monkeypatch.setattr(own, "_previous", lambda origin, email, scope="": {"secret": "pw-own"})
    assert own.human_secret(origin, "qa@example.test", pack) == "pw-own"
    folder = os.path.join(os.environ["COCKPIT_WORKSPACE"], "hermes", "qa", "TASK-100")
    os.makedirs(folder, exist_ok=True)
    monkeypatch.setattr(own, "_previous", lambda origin, email, scope="": None)
    json.dump(
        {"env": "staging", "account": "qa@example.test", "links": [], "steps": []},
        open(os.path.join(folder, "demo.json"), "w", encoding="utf-8"),
    )
    shown = _client().get("/demo", params={"ticket": "TASK-100"}).json()
    assert shown["env"] == "staging" and shown["login"] == {
        "username": "qa@example.test",
        "email": "qa@example.test",
        "password": "pw-from-tester",
    }


def test_the_standup_note_has_its_sections_per_ticket(env, monkeypatch):
    from cockpitlib import standup_note
    from cockpitlib.intents import load as load_intent
    from cockpitlib.intents import save
    from cockpitlib.kanban import place_card
    from cockpitlib.outbox import create
    from cockpitlib.pr_watch import record_path

    pack = load(os.environ["COCKPIT_PACK"])
    now = time.time()
    since = now - 3600
    folder = os.path.join(os.environ["COCKPIT_WORKSPACE"], "hermes", "qa", "TASK-100")
    os.makedirs(os.path.join(folder, "pass-01"), exist_ok=True)
    open(os.path.join(folder, "pass-01", "test-results.md"), "w", encoding="utf-8").write("# run\n")
    # ours: a dev card, a published PR, a merged PR of ours; a colleague's: a review we posted
    place_card(pack["board"], "TASK-100: implement", "worker-1", "ready")
    opened = create(
        pack,
        "TASK-100",
        "open-pr",
        "c1",
        "pr",
        {"repo": "api", "branch": "work/TASK-100", "base": "main", "title": "the feature"},
    )
    record = load_intent(opened["id"])
    record["status"] = "published"
    record["receipt"] = {"time": _stamp(now - 60), "url": "https://forge.test/org/api/pull/7"}
    save(record)
    review = create(
        pack,
        "TASK-200",
        "pr-review-submit",
        "c2",
        "review",
        {"repo": "web", "number": 9, "event": "REQUEST_CHANGES", "sha": "abc"},
    )
    record = load_intent(review["id"])
    record["status"] = "published"
    record["receipt"] = {"time": _stamp(now - 50), "url": "https://forge.test/org/web/pull/9"}
    save(record)
    for ticket, repo, number, data in (
        ("TASK-100", "api", 7, {"role": "author", "state": "open", "merged": False, "approvals": []}),
        ("TASK-300", "api", 3, {"role": "author", "state": "merged", "merged": True, "merged_at": _stamp(now - 30)}),
        (
            "TASK-200",
            "web",
            9,
            {"role": "reviewer", "state": "open", "merged": False, "my_review_state": "CHANGES_REQUESTED"},
        ),
    ):
        path = record_path(ticket, repo, number)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        json.dump(
            {"repo": repo, "number": number, "url": f"https://forge.test/org/{repo}/pull/{number}", **data},
            open(path, "w", encoding="utf-8"),
        )
    acts = standup_note.collect(since, now + 1, pack)
    assert [a["what"] for a in acts["TASK-100"]["developed"]] == ["PR opened (api#7)"] and acts["TASK-100"]["tested"][
        0
    ]["what"] == "pass-01 finished"
    assert (
        acts["TASK-200"]["reviewed"][0]["what"] == "web#9 changes requested"
        and acts["TASK-300"]["merged"][0]["what"] == "api#3 merged (our PR)"
    )
    open_ = standup_note.open_work(pack)
    assert {row["ticket"] for row in open_} == {"TASK-100", "TASK-200", "TASK-300"} and standup_note.mine(
        acts, open_
    ) >= {"TASK-100", "TASK-300"}
    monkeypatch.setattr(standup_note, "_statuses", lambda pack, keys: {"TASK-300": "In Review"})
    built = standup_note.draft(pack, since, now + 1)
    text = built["markdown"]
    assert (
        text.startswith("**Standup ")
        and "**Developments:**\nOpened PRs:\n- [TASK-100](" in text
        and "PR opened (api#7)](https://forge.test/org/api/pull/7)" in text
    )
    assert "pass-01 finished" in text  # our own test run rides on the development line
    assert "**PR reviews:**\n- [TASK-200](" in text and "web#9 changes requested" in text
    assert "Merged:\n- [TASK-300](" in text and "api#3 merged](https://forge.test/org/api/pull/3)" in text
    assert (
        "**Waiting on colleagues:**" in text
        and "- Review: [TASK-100]" in text
        and "api#7 waiting for a review approval" in text
    )
    assert "- Review: [TASK-200]" in text and "waiting for the author's changes after our review" in text
    assert "- Test: [TASK-300]" in text and "tracker still 'In Review'" in text
    assert (
        "Receipts" not in text
        and built["slack"].startswith("*Standup ")
        and "<https://forge.test/org/api/pull/7|PR opened (api#7)>" in built["slack"]
    )
    assert built["items"] == 7
    # through the kernel's draft and route
    from cockpitlib.ops import standup_draft

    assert standup_draft(pack).startswith("standup draft: ")
    shown = _client().get("/standup").json()
    assert (
        shown["status"] == "draft"
        and shown["items"] >= 1
        and shown["day"]
        and shown["since"]
        and shown["drafted_at"]
        and "<strong>Developments:</strong>" in shown["markdown_html"]
    )
    from cockpitlib.paths import platform_dir

    assert (
        open(os.path.join(platform_dir(), standup_note.chat_file(pack)), encoding="utf-8")
        .read()
        .startswith("*Standup ")
    )
    # turned off in the pack: the draft that is there is not shown, so the Inbox has no standup row
    monkeypatch.setattr("dashboard.cockpit.routes.pages._guard", lambda: {**pack, "standup_enabled": False})
    hidden = _client().get("/standup").json()
    assert hidden["status"] == "" and hidden["draft"] == ""
