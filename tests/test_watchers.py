# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The watchers: CI, pull requests, the base branch, the standup and the digest, and how a failed one reads."""

import json
import os
import re

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from cockpitlib.cli import main
from cockpitlib.errors import CockpitError
from cockpitlib.pack import load
from tests.support.boards import put_card
from tests.support.both_packs import PACKS, _client, _notified, _other


@pytest.mark.parametrize("pack_file", PACKS)
def test_a_failed_records_commit_is_a_red_watcher(env, pack_file, monkeypatch):
    import subprocess

    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    pack = load(pack_file)
    other = load(PACKS[0] if pack["name"] == "bravo" else PACKS[1])
    assert pack["workspace_branch"] != other["workspace_branch"]
    from cockpitlib.errors import CockpitError
    from cockpitlib.ops import workspace_watch
    from cockpitlib.paths import watch_dir

    workspace = env["workspace"]
    subprocess.run(["git", "init", "-b", pack["workspace_branch"], str(workspace)], check=True, capture_output=True)
    ticket = f"{pack['tracker']['project']}-1043"
    from cockpitlib.paths import records_name

    folder = workspace / records_name() / "qa" / ticket / "notes"
    folder.mkdir(parents=True)
    note = folder / "row.txt"
    note.write_text(pack["name"] + "\n", encoding="utf-8")
    os.utime(note, (1_000_000, 1_000_000))

    def fail(*_args, **_kwargs):
        raise CockpitError(f"commit failed {pack['name']}")

    monkeypatch.setattr("cockpitlib.state_commit._commit", fail)
    message = workspace_watch(pack)
    assert message == f"commit failed {pack['name']}"
    assert other["name"] not in message
    record = json.load(open(os.path.join(watch_dir(), "workspace-watch.json"), encoding="utf-8"))
    assert record["ok"] is False
    assert record["summary"] == message
    status = subprocess.run(
        ["git", "-C", str(workspace), "status", "--porcelain", "--untracked-files=all"],
        capture_output=True,
        text=True,
        check=True,
    )
    assert "row.txt" in status.stdout
    note.unlink()
    census = workspace / records_name() / "platform" / "census.json"
    census.parent.mkdir(parents=True, exist_ok=True)
    census.write_text(pack["name"] + "\n", encoding="utf-8")
    os.utime(census, (1_000_000, 1_000_000))
    again = workspace_watch(pack)
    assert again == f"commit failed {pack['name']}"
    assert other["name"] not in again


@pytest.mark.parametrize("pack_file", PACKS)
def test_forget_removes_only_that_watch_file(env, pack_file, monkeypatch):
    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    pack = load(pack_file)
    other = load(PACKS[0] if pack["name"] == "bravo" else PACKS[1])
    repo = pack["repos"]["repos"][0]["name"]
    other_repo = other["repos"]["repos"][0]["name"]
    assert repo != other_repo
    from cockpitlib.paths import qa

    ticket = f"{pack['tracker']['project']}-880"
    other_ticket = f"{other['tracker']['project']}-880"
    own = os.path.join(qa(), ticket, "pr", f"{repo}-3.json")
    theirs = os.path.join(qa(), other_ticket, "pr", f"{other_repo}-3.json")
    os.makedirs(os.path.dirname(own), exist_ok=True)
    os.makedirs(os.path.dirname(theirs), exist_ok=True)
    open(own, "w", encoding="utf-8").write("{}\n")
    open(theirs, "w", encoding="utf-8").write("{}\n")
    client = _client()
    assert client.post("/pr-forget", json={}).status_code == 400
    removed = client.post("/pr-forget", json={"ticket": ticket, "repo": repo, "number": 3})
    assert removed.status_code == 200
    assert not os.path.isfile(own)
    assert os.path.isfile(theirs)
    from cockpitlib.ci_watch import record_path

    for who in (ticket, other_ticket):
        os.makedirs(os.path.dirname(record_path(who, repo, "abc" * 14)), exist_ok=True)
        open(record_path(who, repo, "abc" * 14), "w", encoding="utf-8").write("{}")
    assert client.post("/ci-forget", json={}).status_code == 400
    forgotten = client.post("/ci-forget", json={"ticket": ticket, "sha": "abc" * 14})
    assert forgotten.status_code == 200 and forgotten.json()["removed"]
    assert not os.path.isfile(record_path(ticket, repo, "abc" * 14)) and os.path.isfile(
        record_path(other_ticket, repo, "abc" * 14)
    )


@pytest.mark.parametrize("pack_file", PACKS)
def test_the_morning_digest_is_one_screen_of_local_records(env, pack_file, monkeypatch):
    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    pack = load(pack_file)
    other = load(PACKS[0] if pack["name"] == "bravo" else PACKS[1])
    repo = pack["repos"]["repos"][0]["name"]
    other_repo = other["repos"]["repos"][0]["name"]
    assert repo != other_repo
    from cockpitlib.kanban import place_card
    from cockpitlib.ops import morning_digest, perf_sync
    from cockpitlib.outbox import create
    from cockpitlib.paths import platform_dir, qa

    assert morning_digest(pack) == "digest"
    empty = open(os.path.join(platform_dir(), "digest.md"), encoding="utf-8").read()
    assert "Pending outbox: 0" in empty and "Blocked: 0" in empty and "Review: 0" in empty
    assert perf_sync(pack) == "perf"
    assert json.load(open(os.path.join(platform_dir(), "perf.json"), encoding="utf-8"))["approvals"] == []
    ticket = "TASK-8840"
    place_card(pack["board"], f"{ticket}: blocked {pack['name']}", "worker-1", "blocked")
    put_card(pack["board"], f"{ticket}: review {pack['name']}", "reviewer", "review")
    create(pack, ticket, "push-branch", "c", "ship", {"repo": repo, "branch": "main"})
    create(pack, ticket, "tracker-comment", "c", "note", {"body": f"tracker {pack['name']}"})
    create(
        pack, ticket, "open-pr", "c", "open", {"repo": repo, "branch": f"work/{ticket}", "number": 4, "title": ticket}
    )
    folder = os.path.join(qa(), ticket, "pr")
    os.makedirs(folder, exist_ok=True)
    open(os.path.join(folder, "note.txt"), "w", encoding="utf-8").write("x\n")
    open(os.path.join(folder, f"{repo}-4.json"), "w", encoding="utf-8").write(
        json.dumps({"repo": repo, "number": 4, "reviewed_sha": ""})
    )
    open(os.path.join(folder, f"{repo}-5.json"), "w", encoding="utf-8").write(
        json.dumps({"repo": repo, "number": 5, "reviewed_sha": f"sha-{pack['name']}"})
    )
    assert morning_digest(pack) == "digest"
    text = open(os.path.join(platform_dir(), "digest.md"), encoding="utf-8").read()
    assert "Pending outbox: 3" in text
    assert f"blocked {pack['name']}" in text
    assert f"review {pack['name']}" in text
    assert other_repo not in text
    assert perf_sync(pack) == "perf"
    record = json.load(open(os.path.join(platform_dir(), "perf.json"), encoding="utf-8"))
    assert any(row["type"] == "tracker-comment" for row in record["tracker"])
    assert any(row["repo"] == repo and row["number"] == 4 for row in record["pull_requests"])
    assert any(row["sha"] == f"sha-{pack['name']}" and row["repo"] == repo for row in record["approvals"])
    assert all(row["repo"] != other_repo for row in record["pull_requests"] + record["approvals"])


@pytest.mark.parametrize("pack_file", PACKS)
def test_a_forge_timeout_is_retried_once(env, pack_file, monkeypatch):
    import subprocess

    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    pack = load(pack_file)
    other = load(PACKS[0] if pack["name"] == "bravo" else PACKS[1])
    repos = [repo["name"] for repo in pack["repos"]["repos"]]
    assert repos and repos != [repo["name"] for repo in other["repos"]["repos"]]
    from cockpitlib.ops import bumps_scan, watch_base
    from cockpitlib.paths import watch_dir

    calls = {"n": 0}

    def timeout(*_args, **_kwargs):
        calls["n"] += 1
        raise subprocess.TimeoutExpired(cmd="gh", timeout=8)

    monkeypatch.setattr("cockpitlib.gh_cli.subprocess.run", timeout)
    message = watch_base(pack)
    assert message.startswith("forge")
    assert "timeout" in message
    assert other["name"] not in message
    assert calls["n"] == len(repos) * 2
    record = json.load(open(os.path.join(watch_dir(), "base-watch.json"), encoding="utf-8"))
    assert record["ok"] is False
    assert "timeout" in record["output"]
    calls["n"] = 0
    denied = bumps_scan(pack)
    assert denied.startswith("forge")
    assert "timeout" in denied
    assert calls["n"] == len(repos) * 2
    bumps = json.load(open(os.path.join(watch_dir(), "bumps.json"), encoding="utf-8"))
    assert bumps["ok"] is False

    def refuse(*_args, **_kwargs):
        calls["n"] += 1
        return type("R", (), {"returncode": 1, "stdout": "", "stderr": f"denied {pack['name']}"})()

    calls["n"] = 0
    monkeypatch.setattr("cockpitlib.gh_cli.subprocess.run", refuse)
    plain = watch_base(pack)
    assert plain.startswith("forge")
    assert f"denied {pack['name']}" in plain
    assert "timeout" not in plain
    assert calls["n"] == len(repos)


# How each fixture's notifier writes a CI-green line: its own prefix and its own arguments.
NOTIFIED = {
    "acme": ("acme|ci_green|ci_green {key}|{body}", "acme pager down"),
    "bravo": ("bravo|ci_green|--to north:{ticket}|{body}", "north relay refused"),
}


@pytest.mark.parametrize("pack_file", PACKS)
def test_an_event_goes_out_once_per_key_and_a_failed_send_waits_in_the_inbox(env, pack_file, monkeypatch):
    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    pack = load(pack_file)
    line, refusal = NOTIFIED[pack["name"]]
    assert line != NOTIFIED["bravo" if pack["name"] == "acme" else "acme"][0]
    from cockpitlib.ci_watch import _announce
    from cockpitlib.notify import notify

    log = env["root"] / "notified.log"

    def lines():
        return log.read_text(encoding="utf-8").splitlines() if log.exists() else []

    ticket = f"{pack['tracker']['project']}-71"
    first = notify(pack, "ci_green", f"{ticket}@abc", "green abc\n", ticket=ticket, sha="abc")
    assert first["sent"] is True and lines() == [line.format(key=f"{ticket}@abc", ticket=ticket, body="green abc")]
    again = notify(pack, "ci_green", f"{ticket}@abc", "green abc\n", ticket=ticket, sha="abc")
    assert again == {**again, "sent": False, "already": True} and len(lines()) == 1
    assert notify(pack, "nothing_named", "k", "x")["out"] == "no notify.nothing_named"

    failed = notify(pack, "ci_green", f"{ticket}@def", "FAIL\n", ticket=ticket, sha="def")
    assert failed["ok"] is False and refusal in failed["out"] and len(lines()) == 1
    rows = {row["name"]: row for row in _client().get("/needs-you").json()["watchers"]}
    assert refusal in rows["notify-ci_green"]["reason"]
    retried = notify(pack, "ci_green", f"{ticket}@def", "green def\n", ticket=ticket, sha="def")
    assert retried["sent"] is True and len(lines()) == 2
    assert "notify-ci_green" not in {row["name"] for row in _client().get("/needs-you").json()["watchers"]}

    # The CI watch announces a green head through the same event, once.
    green = f"{pack['tracker']['project']}-72"
    for _ in range(2):
        _announce(pack, green, "fff", "green")
    assert [row for row in lines() if green in row] == [
        line.format(key=f"{green}@fff", ticket=green, body=f"{green}: CI is green on fff")
    ]


@pytest.mark.parametrize("pack_file", PACKS)
def test_standup_without_a_command_is_stored_and_not_sent(env, pack_file, monkeypatch):
    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    pack = load(pack_file)
    other = load(PACKS[0] if pack["name"] == "bravo" else PACKS[1])
    assert pack["notify"]["standup"] != other["notify"]["standup"]
    from cockpitlib.acts import standup_send
    from cockpitlib.paths import platform_dir

    quiet = dict(pack)
    quiet["notify"] = {"standup": []}
    sent = os.path.join(platform_dir(), "standup.sent")
    os.makedirs(platform_dir(), exist_ok=True)
    open(sent, "w", encoding="utf-8").write("old\n")
    result = standup_send(quiet, f"note {pack['name']}")
    assert not os.path.isfile(sent)
    quiet["notify"] = {"standup": "north-notify" if pack["name"] == "bravo" else "true"}
    stored = standup_send(quiet, f"note {pack['name']}")
    assert stored["sent"] is False
    assert result["sent"] is False
    assert result["out"] == "standup kept: the pack has no notify.standup command to send it"
    note = open(os.path.join(platform_dir(), "standup.md"), encoding="utf-8").read()
    assert pack["name"] in note
    assert other["name"] not in note
    assert not os.path.isfile(os.path.join(platform_dir(), "standup.sent"))
    # confirmed with no channel to send it to: kept, and its Inbox row (shown only for a draft) leaves
    assert _client().get("/standup").json()["status"] == "kept"


@pytest.mark.parametrize("pack_file", PACKS)
def test_standup_update_replaces_an_edit_with_a_fresh_draft(env, pack_file, monkeypatch):
    from cockpitlib.ops import standup_draft
    from cockpitlib.paths import platform_dir

    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    pack = load(pack_file)
    other = load(PACKS[0] if pack["name"] == "bravo" else PACKS[1])
    assert int(pack["hours"]["standup"]) != int(other["hours"]["standup"])
    assert pack["working_days"] != other["working_days"]
    assert pack["notify"]["standup"] != other["notify"]["standup"]
    standup_draft(pack)
    note = os.path.join(platform_dir(), "standup.md")
    open(note, "a", encoding="utf-8").write(f"EDIT {pack['name']}\n")
    assert _client().post("/standup-update", json={}).status_code == 200
    fresh = open(note, encoding="utf-8").read()
    assert f"EDIT {pack['name']}" not in fresh
    hour = f"T{pack['hours']['standup_window']}:00"  # the window opens at its own time, apart from the draft's
    other_hour = f"T{other['hours']['standup_window']}:00"
    since = _client().get("/standup").json()["since"]  # the window opens at its own time, apart from the draft's
    assert hour in since and other_hour not in since and fresh.startswith("**Standup ")
    calls = []

    def _sent(argv, **_kwargs):
        calls.append(list(argv))

        class Result:
            returncode = 0
            stdout = ""
            stderr = ""

        return Result()

    monkeypatch.setattr("cockpitlib.acts.subprocess.run", _sent)
    assert _client().post("/standup-confirm", json={}).status_code == 200
    assert calls[0] == list(pack["notify"]["standup"])
    body = _client().get("/standup").json()
    assert body["status"] == "sent" and body["since"] and hour in body["since"]
    refused = _client().post("/standup-update", json={})
    assert refused.status_code in (400, 409) and "already sent" in refused.text
    os.remove(os.path.join(platform_dir(), "standup-sent.json"))  # the next window
    from cockpitlib.intents import save
    from cockpitlib.outbox import create

    published = create(
        pack, "TASK-1012", "push-branch", "c", "ship", {"repo": pack["repos"]["repos"][0]["name"], "branch": "main"}
    )
    published["status"] = "published"
    published["created_at"] = "2000-01-01T00:00:00Z"
    save(published)
    recent = create(
        pack, "TASK-1013", "push-branch", "c", "ship", {"repo": pack["repos"]["repos"][0]["name"], "branch": "main"}
    )
    recent["status"] = "published"
    save(recent)
    from cockpitlib.paths import outbox
    from cockpitlib.time_util import iso

    os.makedirs(outbox(), exist_ok=True)
    open(os.path.join(outbox(), "_published.log"), "w", encoding="utf-8").write(
        f"old 2000-01-01T00:00:00Z\nnew {iso()}\n"
    )
    changes = os.path.join(platform_dir(), "changes")
    os.makedirs(changes, exist_ok=True)
    repo = pack["repos"]["repos"][0]["name"]
    json.dump(
        {"repo": repo, "number": 2, "status": "relevant", "merged_at": "2000-01-01T00:00:00Z"},
        open(os.path.join(changes, "old.json"), "w", encoding="utf-8"),
    )
    json.dump(
        {"repo": repo, "number": 3, "status": "relevant", "merged_at": iso()},
        open(os.path.join(changes, "new.json"), "w", encoding="utf-8"),
    )
    json.dump(
        {"repo": repo, "number": 4, "status": "unmapped", "merged_at": iso(), "title": pack["name"]},
        open(os.path.join(changes, "unmapped.json"), "w", encoding="utf-8"),
    )
    json.dump(
        {"repo": repo, "number": 5, "status": "skipped", "merged_at": iso()},
        open(os.path.join(changes, "skipped.json"), "w", encoding="utf-8"),
    )
    assert _client().post("/standup-update", json={}).status_code == 200
    from cockpitlib.standup_note import labels

    again = _client().get("/standup").json()
    assert again["status"] == "draft"
    assert "TASK-1012" not in again["draft"]  # published before the window
    assert (
        "TASK-1013" in again["draft"]
        and "branch pushed" in again["draft"]
        and f"**{labels(pack)['developments']}**" in again["draft"]
    )
    assert (
        "Receipts" not in again["draft"] and "receipt new" not in again["draft"]
    )  # the receipt log is not a section of the note
    assert other["repos"]["repos"][0]["name"] not in again["draft"]
    assert os.path.isfile(os.path.join(platform_dir(), "standup.sent"))
    assert "TASK-1012" not in open(os.path.join(platform_dir(), "standup.sent"), encoding="utf-8").read()


@pytest.mark.parametrize("pack_file", PACKS)
def test_a_standup_draft_lists_the_receipt_that_left(env, pack_file):
    pack = load(pack_file)
    other = load(PACKS[0] if pack["name"] == "bravo" else PACKS[1])
    assert pack["name"] != other["name"]
    from cockpitlib.ops import standup_draft
    from cockpitlib.outbox import create, endorse
    from cockpitlib.paths import platform_dir
    from cockpitlib.publish import execute

    repo = pack["repos"]["repos"][0]["name"]
    other_repo = other["repos"]["repos"][0]["name"]
    ticket = f"{pack['tracker']['project']}-1038"
    row = create(pack, ticket, "push-branch", "c", "ship", {"repo": repo, "branch": "main"})
    row = endorse(row["id"], "low", "", "gatekeeper", "fixture-a", "fixture-large")
    receipt = execute(row, pack=pack)
    assert receipt["ok"] is True
    assert standup_draft(pack).startswith("standup draft")
    draft = open(os.path.join(platform_dir(), "standup.md"), encoding="utf-8").read()
    assert ticket in draft and "branch pushed" in draft  # what left, under the ticket, in the Developments section
    assert other_repo not in draft
    assert other["name"] not in draft


@pytest.mark.parametrize("pack_file", PACKS)
def test_a_watcher_crash_is_a_red_row(env, pack_file, monkeypatch):
    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    pack = load(pack_file)
    other = load(PACKS[0] if pack["name"] == "bravo" else PACKS[1])
    from cockpitlib.cli import main
    from cockpitlib.health import reason
    from cockpitlib.paths import watch_dir

    def boom(_pack):
        raise RuntimeError(f"boom {pack['name']}")

    monkeypatch.setattr("cockpitlib.ops.watch_pr", boom)
    with pytest.raises(RuntimeError, match=pack["name"]):
        main(["watch-pr"])
    record = json.load(open(os.path.join(watch_dir(), "pr-watch.json"), encoding="utf-8"))
    assert record["ok"] is False
    assert record["trace"] is True
    assert reason(record) == "the watcher crashed"
    assert f"boom {pack['name']}" in record["output"]
    assert other["name"] not in record["output"]
    assert record["summary"] == "the watcher crashed"
    monkeypatch.setattr("cockpitlib.ops.slot_gc", boom)
    with pytest.raises(RuntimeError, match=pack["name"]):
        main(["slot", "gc"])
    collected = json.load(open(os.path.join(watch_dir(), "slot-gc.json"), encoding="utf-8"))
    assert collected["ok"] is False and collected["trace"] is True
    assert reason(collected) == "the watcher crashed"
    assert f"boom {pack['name']}" in collected["output"]
    assert other["name"] not in collected["output"]


@pytest.mark.parametrize("pack_file", PACKS)
def test_unseen_relevant_changes_are_listed_first(env, pack_file, monkeypatch):
    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    pack = load(pack_file)
    other = load(PACKS[0] if pack["name"] == "bravo" else PACKS[1])
    repo = pack["repos"]["repos"][0]["name"]
    other_repo = other["repos"]["repos"][0]["name"]
    assert repo != other_repo
    from cockpitlib.paths import platform_dir

    folder = os.path.join(platform_dir(), "changes")
    os.makedirs(folder, exist_ok=True)

    def write(name, row):
        json.dump(row, open(os.path.join(folder, name), "w", encoding="utf-8"))

    write(
        "a-seen.json",
        {
            "repo": repo,
            "number": 1,
            "status": "relevant",
            "seen": True,
            "merged_at": "2026-10-20T00:00:00Z",
            "title": "old",
        },
    )
    write(
        "b-skip.json",
        {
            "repo": repo,
            "number": "nope",
            "status": "skipped",
            "seen": False,
            "merged_at": "2026-10-20T03:00:00Z",
            "title": "tests only",
        },
    )
    write(
        "c-new.json",
        {
            "repo": repo,
            "number": 3,
            "status": "relevant",
            "seen": False,
            "merged_at": "2026-10-20T01:00:00Z",
            "title": f"landed {pack['name']}",
        },
    )
    write(
        "d-other.json",
        {
            "repo": other_repo,
            "number": 4,
            "status": "unmapped",
            "seen": False,
            "merged_at": "2026-10-20T02:00:00Z",
            "title": "elsewhere",
        },
    )
    listed = _client().get("/platform").json()["changes"]
    assert listed[0]["repo"] == repo and listed[0]["number"] == 3
    assert listed[0]["title"] == f"landed {pack['name']}"
    assert [row["number"] for row in listed] == [3, 4, 1, "nope"]


@pytest.mark.parametrize("pack_file", PACKS)
def test_undo_seen_brings_the_change_back(env, pack_file, monkeypatch):
    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    pack = load(pack_file)
    other = load(PACKS[0] if pack["name"] == "bravo" else PACKS[1])
    repo = pack["repos"]["repos"][0]["name"]
    other_repo = other["repos"]["repos"][0]["name"]
    assert repo != other_repo
    from cockpitlib.acts import mark_seen, mark_unseen, ordered_changes
    from cockpitlib.paths import platform_dir

    folder = os.path.join(platform_dir(), "changes")
    os.makedirs(folder, exist_ok=True)
    open(os.path.join(folder, f"{repo}-2.json"), "w", encoding="utf-8").write(
        json.dumps(
            {
                "repo": repo,
                "number": 2,
                "status": "relevant",
                "seen": True,
                "merged_at": "2026-10-02T00:00:00Z",
            }
        )
    )
    open(os.path.join(folder, f"{other_repo}-9.json"), "w", encoding="utf-8").write(
        json.dumps(
            {
                "repo": other_repo,
                "number": 9,
                "status": "relevant",
                "seen": False,
                "merged_at": "2026-10-03T00:00:00Z",
            }
        )
    )
    client = _client()
    assert client.post("/platform-unseen", json={"repo": repo, "number": 2}).status_code == 200
    ordered = ordered_changes()
    first = next(row for row in ordered if row["repo"] == repo and row["number"] == 2)
    assert first["seen"] is False
    assert ordered.index(first) < next(i for i, row in enumerate(ordered) if row["repo"] == other_repo)
    assert mark_seen(pack, repo, 2)["ok"]
    hidden = next(row for row in ordered_changes() if row["repo"] == repo and row["number"] == 2)
    assert hidden["seen"] is True
    assert mark_unseen(repo, 2)["ok"]
    brought = ordered_changes()
    again = next(row for row in brought if row["repo"] == repo and row["number"] == 2)
    assert again["seen"] is False
    assert brought.index(again) == 0


@pytest.mark.parametrize("pack_file", PACKS)
def test_a_forge_read_error_is_a_plain_inbox_reason(env, pack_file, monkeypatch):
    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    pack = load(pack_file)
    other = load(PACKS[0] if pack["name"] == "bravo" else PACKS[1])
    assert pack["forge"]["org"] != other["forge"]["org"]
    from cockpitlib.ops import watch_base
    from dashboard.cockpit.router import router as api_router

    raw = f"forge {pack['forge']['org']}/api: denied {pack['name']}"
    monkeypatch.setattr("cockpitlib.acts.scan_base", lambda *_args, **_kwargs: raw)
    assert watch_base(pack) == raw
    app = FastAPI()
    app.include_router(api_router)
    failed = next(row for row in TestClient(app).get("/needs-you").json()["watchers"] if row["name"] == "base-watch")
    assert failed["reason"] == "the forge read failed"
    assert raw in failed["error"]
    assert other["name"] not in failed["error"]
    assert other["forge"]["org"] not in failed["reason"]


@pytest.mark.parametrize("pack_file", PACKS)
def test_a_timeout_is_retried_once_before_it_is_recorded(env, pack_file, monkeypatch):
    from cockpitlib.ops import bumps_scan, export_keep, watch_base
    from cockpitlib.paths import watch_dir

    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    pack = load(pack_file)
    other = load(PACKS[0] if pack["name"] == "bravo" else PACKS[1])
    calls = {"base": 0, "bumps": 0, "export": 0}

    def base(_pack):
        calls["base"] += 1
        if calls["base"] == 1:
            return "forge 503"
        return f"base {pack['name']}"

    def bumps(_pack):
        calls["bumps"] += 1
        return "forge 503"

    monkeypatch.setattr("cockpitlib.acts.scan_base", base)
    monkeypatch.setattr("cockpitlib.acts.scan_bumps", bumps)
    assert watch_base(pack) == f"base {pack['name']}"
    assert calls["base"] == 2
    assert json.load(open(os.path.join(watch_dir(), "base-watch.json"), encoding="utf-8"))["ok"] is True
    assert bumps_scan(pack) == "forge 503"
    assert calls["bumps"] == 2
    assert json.load(open(os.path.join(watch_dir(), "bumps.json"), encoding="utf-8"))["ok"] is False
    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    from dashboard.cockpit.payload import build
    from dashboard.cockpit.router import router as api_router

    app = FastAPI()
    app.include_router(api_router)
    client = TestClient(app)
    failed = next(row for row in client.get("/needs-you").json()["watchers"] if row["name"] == "bumps")
    assert failed["reason"] == "the forge returned an error"
    assert "503" in failed["error"]
    shown = next(row for row in build(pack, {})["inbox"] if row.get("id") == "bumps")
    assert shown["summary"] == "the forge returned an error"
    assert shown["output"] == "forge 503"

    def cleared(_pack):
        return f"bumps {pack['name']}"

    monkeypatch.setattr("cockpitlib.acts.scan_bumps", cleared)
    assert bumps_scan(pack) == f"bumps {pack['name']}"
    assert all(row["name"] != "bumps" for row in client.get("/needs-you").json()["watchers"])
    assert all(row.get("id") != "bumps" for row in build(pack, {})["inbox"])

    def boom(_keep=4):
        calls["export"] += 1
        if calls["export"] == 1:
            raise OSError("503")
        return "vault backup 1"

    monkeypatch.setattr("cockpitlib.vault.backup_vault", boom)
    monkeypatch.setattr("cockpitlib.vault.needs_seal", lambda: False)
    assert export_keep(pack) == "export"
    assert calls["export"] == 2
    assert json.load(open(os.path.join(watch_dir(), "export.json"), encoding="utf-8"))["ok"] is True
    returned = {"n": 0}

    def soft(_keep=4):
        returned["n"] += 1
        if returned["n"] == 1:
            return "503"
        return "vault backup 1"

    monkeypatch.setattr("cockpitlib.vault.backup_vault", soft)
    assert export_keep(pack) == "export"
    assert returned["n"] == 2
    assert json.load(open(os.path.join(watch_dir(), "export.json"), encoding="utf-8"))["ok"] is True
    other = load(PACKS[0] if pack["name"] == "bravo" else PACKS[1])
    monkeypatch.setattr("cockpitlib.vault.backup_vault", lambda _keep=4: f"504 {pack['name']}")
    assert export_keep(pack) == "export"
    stuck = json.load(open(os.path.join(watch_dir(), "export.json"), encoding="utf-8"))
    assert stuck["ok"] is False and "504" in stuck["summary"] and pack["name"] in stuck["summary"]
    assert other["name"] not in stuck["summary"]
    monkeypatch.setattr("cockpitlib.vault.backup_vault", lambda _keep=4: "vault backup 0")
    assert export_keep(pack) == "failed"
    empty = json.load(open(os.path.join(watch_dir(), "export.json"), encoding="utf-8"))
    assert empty["ok"] is False and empty["summary"] == "exit 0 with no record"
    assert other["name"] not in empty["summary"]

    import subprocess

    timeouts = {"n": 0}

    def timed(_keep=4):
        timeouts["n"] += 1
        raise subprocess.TimeoutExpired("vault", 8)

    monkeypatch.setattr("cockpitlib.vault.backup_vault", timed)
    assert export_keep(pack) == "export"
    assert timeouts["n"] == 2
    held = json.load(open(os.path.join(watch_dir(), "export.json"), encoding="utf-8"))
    assert held["ok"] is False
    assert "timed out" in held["detail"].lower()
    assert other["name"] not in held["detail"]

    def denied(_pack):
        calls["base"] += 1
        return "forge 401"

    monkeypatch.setattr("cockpitlib.acts.scan_base", denied)
    before = calls["base"]
    assert watch_base(pack) == "forge 401"
    assert calls["base"] == before + 1

    def disk(_keep=4):
        raise OSError("disk full")

    monkeypatch.setattr("cockpitlib.vault.backup_vault", disk)
    assert export_keep(pack) == "export"
    assert json.load(open(os.path.join(watch_dir(), "export.json"), encoding="utf-8"))["ok"] is False
    from cockpitlib.ops import standup_draft
    from cockpitlib.paths import platform_dir

    changes = os.path.join(platform_dir(), "changes")
    os.makedirs(changes, exist_ok=True)
    open(os.path.join(changes, "note.txt"), "w", encoding="utf-8").write("x\n")
    assert standup_draft(pack).startswith("standup draft")


@pytest.mark.parametrize("pack_file", PACKS)
def test_only_a_failed_watcher_is_an_inbox_row(env, pack_file, monkeypatch):
    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    pack = load(pack_file)
    other = load(PACKS[0] if pack["name"] == "bravo" else PACKS[1])
    from cockpitlib.health import failing_records
    from cockpitlib.ops import _health, _health_hold
    from cockpitlib.paths import watch_dir
    from dashboard.cockpit.payload import build

    assert pack["name"] != other["name"]
    assert failing_records(os.path.join(watch_dir(), "missing")) == []
    folder = watch_dir()
    os.makedirs(folder, exist_ok=True)
    open(os.path.join(folder, "settings.json"), "w", encoding="utf-8").write(json.dumps({"seats": {"slots": 1}}))
    open(os.path.join(folder, "notes.json"), "w", encoding="utf-8").write("{")
    open(os.path.join(folder, "list.json"), "w", encoding="utf-8").write("[]")
    _health("pr-watch", f"quiet {pack['name']}")
    _health_hold("bumps", f"forge 503 {pack['name']}")
    client = _client()
    watchers = client.get("/needs-you").json()["watchers"]
    assert [row["name"] for row in watchers] == ["bumps"]
    assert watchers[0]["reason"] == "the forge returned an error"
    assert pack["name"] in watchers[0]["error"]
    assert other["name"] not in watchers[0]["error"]
    inbox = build(pack, {})["inbox"]
    assert any(row.get("id") == "bumps" and row.get("output") == watchers[0]["error"] for row in inbox)
    assert all(row.get("id") not in ("settings", "notes", "list", "pr-watch") for row in inbox)


@pytest.mark.parametrize("pack_file", PACKS)
def test_a_forge_read_error_turns_ci_watch_red(env, pack_file, monkeypatch):
    from cockpitlib.health import load as load_health
    from cockpitlib.intents import save
    from cockpitlib.ops import watch_ci
    from cockpitlib.outbox import create
    from cockpitlib.paths import watch_dir
    from tests.support import fake_gh

    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    pack = load(pack_file)
    name = pack["repos"]["repos"][0]["name"]
    org = pack["forge"]["org"]
    row = create(
        pack, f"{pack['tracker']['project']}-1402", "push-branch", "c", "ship", {"repo": name, "branch": "main"}
    )
    row["status"] = "published"
    save(row)
    fake_gh.fail("GET actions/runs", f"{pack['name']} forge unavailable")
    message = watch_ci(pack)
    assert message.startswith(f"forge {org}/{name}: ") and f"{pack['name']} forge unavailable" in message
    assert load_health(watch_dir(), "ci-watch")["ok"] is False
    data = fake_gh.state()
    data["fail"] = {}
    fake_gh.save(data)
    assert watch_ci(pack) == "ci-watch 0" and load_health(watch_dir(), "ci-watch")["ok"] is True


def test_run_now_runs_a_watcher_once_at_a_time(env, monkeypatch):
    import fcntl

    from cockpitlib.acts import run_watcher
    from cockpitlib.paths import watch_dir

    os.makedirs(watch_dir(), exist_ok=True)
    with open(os.path.join(watch_dir(), ".run-ci-watch.sh.lock"), "w", encoding="utf-8") as held:
        fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)
        assert run_watcher("ci-watch") == {
            "ok": True,
            "out": "ci-watch is already running",
            "name": "ci-watch",
            "script": "ci-watch.sh",
            "already": True,
        }
        assert run_watcher("housekeeping")["already"], "the housekeeping record is written by the same job"
    assert not run_watcher("ci-watch").get("already"), "free again once the first run ends"


@pytest.mark.parametrize("pack_file", PACKS)
def test_ci_is_watched_per_commit_one_card_per_failed_attempt_and_green_once_settled(
    env, pack_file, monkeypatch, capsys
):
    from cockpitlib import ci_watch
    from cockpitlib.intents import load as load_intent
    from cockpitlib.kanban import BoardWrites, board_cards
    from cockpitlib.outbox import create, endorse
    from cockpitlib.paths import qa
    from cockpitlib.publish import execute
    from tests.support import fake_gh

    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    monkeypatch.delenv("COCKPIT_LANE", raising=False)
    pack = load(pack_file)
    repo = pack["repos"]["repos"][0]["name"]
    full = f"{pack['forge']['org']}/{repo}"
    fake_gh.setup(me=pack["forge"]["human_login"], repos=[full])
    ticket = f"{pack['tracker']['project']}-1401"
    settle, quiet = pack["hours"]["ci_settle_minutes"] * 60, pack["hours"]["no_ci_minutes"] * 60
    extra = pack["watchers"]["ci"]["failed_states"][0]

    def published(branch):
        fake_gh.commit(repo, branch, name=f"{branch.replace('/', '-')}.txt")
        row = endorse(
            create(pack, ticket, "push-branch", "c", "push", {"repo": repo, "branch": branch})["id"],
            "low",
            "",
            "gatekeeper",
            "fixture-a",
            "fixture-large",
        )
        assert execute(row, pack=pack)["ok"]
        return load_intent(row["id"])["payload"]["sha"]

    silent = published(f"work/{ticket}-quiet")
    assert ci_watch.watch(pack, now=1000)["none"] == [] and ci_watch.watch(pack, now=1000 + quiet)["none"] == [silent]
    record = json.load(open(ci_watch.record_path(ticket, repo, silent), encoding="utf-8"))
    assert record["state"] == "none" and record["settled"]
    sha = published(f"work/{ticket}")
    jobs = [
        {
            "id": 71,
            "name": "unit",
            "conclusion": "failure",
            "log": "\n".join(f"line {n}" for n in range(60)) + f"\nFAIL {pack['name']}",
        }
    ]
    fake_gh.run(full, 7001, sha, "tests", conclusion="failure", jobs=jobs)
    fake_gh.run(full, 7002, sha, "build", status="in_progress")
    fake_gh.run(full, 7003, sha, "deploy-preview", conclusion=extra)
    done = ci_watch.watch(pack, now=2000)
    assert len(done["cards"]) == 2 and done["failed"] == [{"ticket": ticket, "sha": sha}]
    cards = {card["id"]: card for card in board_cards(pack["board"], pack)}
    first = cards[done["cards"][0]]
    assert (
        first["flow"] == "ci-watch"
        and first["assignee"].startswith("analyst")
        and f"FAIL {pack['name']}" in first["body"]
    )
    assert "line 59" in first["body"] and "line 5\n" not in first["body"] and "--run-id 7001" in first["body"]
    assert ci_watch.watch(pack, now=2100)["cards"] == []  # the same attempts make no second card
    fake_gh.run(full, 7001, sha, "tests", conclusion="failure", attempt=2, jobs=jobs)
    assert len(ci_watch.watch(pack, now=2200)["cards"]) == 1
    shown = ci_watch.state_for(ticket, repo, sha, pack)
    assert shown["state"] == "failed" and shown["analysing"] and not shown["handled"] and "tests" in shown["summary"]
    writes = BoardWrites(pack["board"])
    for card in shown["cards"].values():
        writes.complete(card, result="flaky")
    writes.flush()
    assert ci_watch.state_for(ticket, repo, sha, pack)["handled"]
    # The runs pass on a rerun: green waits for the runs to settle, is announced once, and the commit is not read again.
    fake_gh.run(full, 7001, sha, "tests", conclusion="success", attempt=3)
    fake_gh.run(full, 7002, sha, "build", conclusion="success")
    fake_gh.run(full, 7003, sha, "deploy-preview", conclusion="success")
    assert ci_watch.watch(pack, now=3000)["green"] == [] and ci_watch.watch(pack, now=3000 + settle - 1)["green"] == []
    assert ci_watch.watch(pack, now=3000 + settle)["green"] == [sha]
    record = json.load(open(ci_watch.record_path(ticket, repo, sha), encoding="utf-8"))
    assert record["settled"] and [run["passed_after_rerun"] for run in record["runs"] if run["name"] == "tests"] == [
        True
    ]
    before = len(fake_gh.calls())
    ci_watch.watch(pack, now=9999)
    assert not [call for call in fake_gh.calls()[before:] if f"head_sha={sha}" in call["path"]]
    assert _notified().count("|ci_green|") == 1
    # A rerun published for a run of the commit reads it again; a dismissed commit is not read.
    rerun = endorse(
        create(pack, ticket, "ci-rerun", "c", "x", {"repo": repo, "run_id": 7001})["id"],
        "low",
        "",
        "gatekeeper",
        "fixture-a",
        "fixture-large",
    )
    receipt = execute(rerun, pack=pack)
    assert "reads the commit again" in receipt.get("output", ""), receipt
    assert not json.load(open(ci_watch.record_path(ticket, repo, sha), encoding="utf-8"))["settled"]
    other = published(f"work/{ticket}-other")
    fake_gh.run(
        full, 7101, other, "tests", conclusion="failure", jobs=[{"id": 81, "name": "unit", "conclusion": "failure"}]
    )
    assert ci_watch.dismiss(pack, ticket, repo, other)["ok"]
    assert ci_watch.watch(pack, now=4000)["cards"] == [] and ci_watch.state_for(ticket, repo, other) == {}
    with pytest.raises(CockpitError, match="bad repo"):
        ci_watch.dismiss(pack, "", repo, other)
    # The heads of the human's own open PRs are watched; a PR the human only reviews is not.
    folder = os.path.join(qa(), ticket, "pr")
    os.makedirs(folder, exist_ok=True)
    open(os.path.join(folder, f"{repo}-8.json"), "w", encoding="utf-8").write(
        json.dumps({"repo": repo, "head_sha": "8" * 40, "head": "h8"})
    )
    open(os.path.join(folder, f"{repo}-9.json"), "w", encoding="utf-8").write(
        json.dumps({"repo": repo, "head_sha": "9" * 40, "role": "reviewer"})
    )
    shas = {sha for _ticket, _repo, sha, _branch in ci_watch.commits(pack)}
    assert "8" * 40 in shas and "9" * 40 not in shas
    assert ci_watch.forget(ticket, silent)["removed"] and not os.path.exists(ci_watch.record_path(ticket, repo, silent))
    # the whole sha: `head_sha=8` alone also fails the read of any real commit whose sha happens to start with 8
    fake_gh.fail("GET actions/runs\\?head_sha=8{40}", f"forge down {pack['name']}")
    assert any(f"forge down {pack['name']}" in error for error in ci_watch.watch(pack, now=5000)["errors"])
    assert os.path.exists(ci_watch.record_path(ticket, repo, silent)), (
        "the forgotten commit is read again: only the failing read is lost"
    )
    assert (
        main(["ci", "flaky", ticket, sha, "--run-id", "7001", "--repo", repo]) == 0
        and '"verdict": "flaky"' in capsys.readouterr().out
    )
    assert main(["ci", "maybe", ticket, sha]) == 2 and main(["ci", "flaky", ticket, sha, "--colour"]) == 2


@pytest.mark.parametrize("pack_file", PACKS)
def test_a_ci_card_counts_the_runs_flaky_history_and_a_dismissed_commit_stays_quiet(
    env, pack_file, monkeypatch, tmp_path
):
    import shutil

    import yaml

    from cockpitlib import ci_watch
    from cockpitlib.errors import PackError
    from cockpitlib.intents import save
    from cockpitlib.kanban import board_cards
    from cockpitlib.outbox import create
    from tests.support import fake_gh

    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    pack = load(pack_file)
    repo = pack["repos"]["repos"][0]["name"]
    full = f"{pack['forge']['org']}/{repo}"
    ticket = f"{pack['tracker']['project']}-1403"

    def watched(branch):
        sha = fake_gh.commit(repo, branch, name=f"{branch.replace('/', '-')}.txt")
        row = create(pack, ticket, "push-branch", "c", "p", {"repo": repo, "branch": branch})
        row["status"] = "published"
        save(row)
        return sha

    first = watched(f"work/{ticket}-a")
    fake_gh.run(full, 9001, first, "suite", conclusion="failure")
    ci_watch.watch(pack, now=100)
    fake_gh.run(full, 9001, first, "suite", conclusion="success", attempt=2)
    ci_watch.watch(pack, now=200)
    second = watched(f"work/{ticket}-b")
    jobs = [
        {"id": 91, "name": "lint", "conclusion": "success"},
        {"id": 92, "name": f"{pack['name']}-unit", "conclusion": "failure"},
    ]
    fake_gh.run(full, 9002, second, "suite", conclusion="failure", jobs=jobs)
    fake_gh.run(full, 9003, second, "build", status="queued")
    done = ci_watch.watch(pack, now=300)
    body = {card["id"]: card for card in board_cards(pack["board"], pack)}[done["cards"][0]]["body"]
    assert (
        "Flaky history of this run on the ticket: 1 time(s)" in body
        and "(log unreadable" in body
        and "### lint" not in body
    )
    third = watched(f"work/{ticket}-c")
    fake_gh.run(full, 9004, third, "suite", status="in_progress")
    ci_watch.watch(pack, now=400)
    assert json.load(open(ci_watch.record_path(ticket, repo, third), encoding="utf-8"))["state"] == "running"
    assert ci_watch.dismiss(pack, ticket, repo, third)["records"] and ci_watch.state_for(ticket, repo, third)["handled"]
    name = os.path.basename(os.path.dirname(pack_file))
    copied = tmp_path / "packs" / name
    shutil.copytree(os.path.dirname(pack_file), copied)
    raw = yaml.safe_load((copied / "pack.yaml").read_text(encoding="utf-8"))
    for bad, message in (
        ({"limits": {"x": {"stale_minutes": 0}}}, "whole minutes"),
        ({"ci": {"states": []}}, "watchers.ci takes failed_states"),
        ({"base": {"noise": "*.md"}}, "watchers.base.noise is a list"),
        ({"other": {}}, "watchers takes"),
    ):
        (copied / "pack.yaml").write_text(
            yaml.safe_dump({**raw, "watchers": bad}, sort_keys=False, allow_unicode=True), encoding="utf-8"
        )
        with pytest.raises(PackError, match=re.escape(message)):
            load(str(copied / "pack.yaml"))


@pytest.mark.parametrize("pack_file", PACKS)
def test_the_pr_watch_counts_what_others_wrote_and_rereviews_once_per_head(env, pack_file, monkeypatch):
    from cockpitlib import pr_watch
    from cockpitlib.acts import treat_pr
    from cockpitlib.health import load as load_health
    from cockpitlib.intents import load as load_intent
    from cockpitlib.intents import save
    from cockpitlib.kanban import board_cards
    from cockpitlib.ops import watch_pr
    from cockpitlib.outbox import create, endorse
    from cockpitlib.paths import platform_dir, watch_dir
    from tests.support import fake_gh

    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    monkeypatch.delenv("COCKPIT_LANE", raising=False)
    pack = load(pack_file)
    forge_cfg = pack["forge"]
    me, bot, tag = forge_cfg["human_login"], forge_cfg["bots"][0], forge_cfg["mention_tags"][0]
    repo = pack["repos"]["repos"][0]["name"]
    full = f"{pack['forge']['org']}/{repo}"
    ticket = f"{pack['tracker']['project']}-1501"
    fake_gh.setup(me=me, repos=[full])
    fake_gh.pull(full, 3, f"work/{ticket}", "a" * 40, title="mine")
    fake_gh.comment(full, 3, "reviewer-x", "an old remark", at="2026-10-01T09:00:00Z")
    fake_gh.pull(full, 8, f"work/{ticket}-other", "e" * 40, title="another")
    opened = create(
        pack, ticket, "open-pr", "c", "o", {"repo": repo, "branch": f"work/{ticket}", "title": "mine", "body": "b"}
    )
    opened["status"] = "published"
    opened["payload"]["number"] = 3
    save(opened)
    other_pr = endorse(
        create(pack, ticket, "pr-edit", "c", "e", {"repo": repo, "number": 8, "add_labels": ["x"]})["id"],
        "low",
        "",
        "gatekeeper",
        "fixture-a",
        "fixture-large",
    )
    same_pr = endorse(
        create(pack, ticket, "pr-edit", "c", "e", {"repo": repo, "number": 3, "add_labels": ["y"]})["id"],
        "low",
        "",
        "gatekeeper",
        "fixture-a",
        "fixture-large",
    )
    assert watch_pr(pack, now=1_800_000_000) == "pr-watch 0"  # the first read is the baseline: nothing is new
    fake_gh.comment(full, 3, "reviewer-x", f"please rename this, {pack['name']}", at="2026-10-21T09:00:00Z")
    fake_gh.comment(full, 3, me, "my own note", at="2026-10-21T09:01:00Z")
    fake_gh.comment(full, 3, bot, "build finished", at="2026-10-21T09:02:00Z")
    fake_gh.comment(full, 3, bot, f"{tag} the deploy needs you", at="2026-10-21T09:03:00Z")
    fake_gh.comment(full, 3, "reviewer-y", "LGTM!", at="2026-10-21T09:04:00Z")
    fake_gh.comment(full, 3, "reviewer-y", "this branch looks off", at="2026-10-21T09:05:00Z", inline=True)
    fake_gh.review(
        full, 3, "reviewer-x", "COMMENTED", body="see the inline notes", commit="a" * 40, at="2026-10-21T09:06:00Z"
    )
    fake_gh.review(full, 3, "reviewer-z", "APPROVED", commit="a" * 40, at="2026-10-21T09:07:00Z")
    assert watch_pr(pack, now=1_800_000_100) == "pr-watch 1"
    record = json.load(open(pr_watch.record_path(ticket, repo, 3), encoding="utf-8"))
    # work for the human: the remark, the bot's mention, the inline note. Not work: an approval (the merge row has it) and a
    # verdict whose body carries no finding tag (its inline notes are counted on their own)
    assert record["role"] == "author" and record["new_count"] == 3, [row["body"] for row in record["new"]]
    reasons = {row["reason"] for row in record["skipped"]}
    assert (
        {"yours", "a bot's", "praise"} <= reasons
        and any(reason.startswith("an approval") for reason in reasons)
        and any(reason.startswith("no finding tag") for reason in reasons)
    )
    assert [row["author"] for row in record["approvals"]] == ["reviewer-z"]
    assert _notified().count("|pr_comments|") == (1 if "pr_comments" in pack["notify"] else 0)
    assert watch_pr(pack, now=1_800_000_200) == "pr-watch 1" and record["new_count"] == 3  # nothing counted twice
    assert [row["number"] for row in pr_watch.inbox_rows()] == [3]
    treated = treat_pr(pack, ticket, repo, 3)
    assert f"please rename this, {pack['name']}" in treated["out"] and treated["amended"] == [same_pr["id"]]
    assert load_intent(other_pr["id"])["status"] == "endorsed" and pr_watch.inbox_rows() == []
    rows = {row["id"]: row for row in _client().get("/list").json()["rows"]}
    assert rows[opened["id"]]["prs"][0]["number"] == 3 and rows[opened["id"]]["prs"][0]["role"] == "author"
    # A PR the human reviews: one re-review card per head, once the human's threads are answered and it has been quiet.
    fake_gh.pull(full, 5, "their-branch", "b" * 40, author="colleague")
    review_intent = create(pack, ticket, "pr-review-submit", "c", "r", {"repo": repo, "number": 5, "sha": "b" * 40})
    fake_gh.review(full, 5, me, "CHANGES_REQUESTED", body="needs work", commit="b" * 40, at="2026-10-21T08:00:00Z")
    fake_gh.thread(full, 5, 6100, me, "guard this")
    now = pr_watch._stamp("2026-10-21T08:00:00Z")
    watch_pr(pack, now=now + 60)
    shown = json.load(open(pr_watch.record_path(ticket, repo, 5), encoding="utf-8"))
    assert (
        shown["role"] == "reviewer" and shown["my_review_state"] == "CHANGES_REQUESTED" and not shown["rereview_ready"]
    )
    data = fake_gh.state()
    data["repos"][full]["pulls"]["5"]["threads"][0]["isResolved"] = True
    fake_gh.save(data)
    assert pr_watch.watch(pack, now=now + 600)["cards"] == []  # answered, but not quiet yet
    first = pr_watch.watch(pack, now=now + 3 * 3600)["cards"]
    assert len(first) == 1 and pr_watch.watch(pack, now=now + 4 * 3600)["cards"] == []
    card = {row["id"]: row for row in board_cards(pack["board"], pack)}[first[0]]
    assert card["assignee"].startswith("reviewer") and card["flow"] == "review" and f"{repo}#5" in card["body"]
    data = fake_gh.state()
    data["repos"][full]["pulls"]["5"]["head"]["sha"] = "c" * 40
    fake_gh.save(data)
    pr_watch.watch(pack, now=now + 5 * 3600)
    assert len(pr_watch.watch(pack, now=now + 8 * 3600)["cards"]) == 1  # the new head is quiet again: its own card
    assert review_intent["id"]
    # A PR quiet too long is pinged once; once every PR merged and nothing is open, the ticket gets its done row.
    stale = (pack["hours"].get("pr_stale_hours") or pr_watch.STALE_HOURS) * 3600
    pr_watch.watch(pack, now=1_800_000_100 + stale + 10)
    pr_watch.watch(pack, now=1_800_000_100 + stale + 20)
    assert _notified().count("|pr_stale|") == (1 if "pr_stale" in pack["notify"] else 0)
    for row in all_open(ticket):
        row["status"] = "dropped"
        save(row)
    from cockpitlib.kanban import BoardWrites

    writes = BoardWrites(pack["board"])
    for row in board_cards(pack["board"], pack):
        if row["ticket"] == ticket and row["status"] not in ("done", "archived"):
            writes.complete(row["id"], result="done")
    writes.flush()
    data = fake_gh.state()
    data["repos"][full]["pulls"]["3"].update(merged=True, state="closed")
    data["repos"][full]["pulls"]["8"].update(merged=True, state="closed")
    data["repos"][full]["pulls"]["5"].update(state="closed")
    fake_gh.save(data)
    done = pr_watch.watch(pack, now=1_900_000_000)
    assert len(done["done"]) == 1 and load_intent(done["done"][0])["type"] == "ticket-done"
    assert pr_watch.watch(pack, now=1_900_000_100)["done"] == []
    # A graduated bump PR, in no ticket, is watched under the platform records; a forge error turns the watch red.
    fake_gh.pull(full, 9, "bump/parser", "d" * 40, author=bot)
    os.makedirs(platform_dir(), exist_ok=True)
    json.dump(
        {"prs": [{"repo": repo, "number": 9}]},
        open(os.path.join(platform_dir(), "graduated-prs.json"), "w", encoding="utf-8"),
    )
    pr_watch.watch(pack, now=1_900_000_200)
    assert os.path.isfile(pr_watch.record_path("", repo, 9))
    fake_gh.comment(full, 9, "reviewer-x", "ready?", at="2026-10-22T09:00:00Z")
    pr_watch.watch(pack, now=1_900_000_300)
    assert {(row["ticket"], row["number"]) for row in pr_watch.inbox_rows()} == {("", 9)}
    fake_gh.fail("GET pulls/9$", f"forge down {pack['name']}")
    assert (
        watch_pr(pack, now=1_900_000_400).startswith("forge ") and load_health(watch_dir(), "pr-watch")["ok"] is False
    )
    with pytest.raises(CockpitError, match="no watch record"):
        pr_watch.seen(ticket, repo, 404)


def all_open(ticket):
    from cockpitlib.intents import OPEN_STATUSES, all_intents

    return [row for row in all_intents(ticket) if row.get("status") in OPEN_STATUSES]


# Files only the pack's own noise globs (watchers.base.noise) make noise, and look-alikes a segment-bound glob leaves alone.
BASE_NOISE = {
    "acme": (["yarn.lock"], ["src/yarn.lock"]),
    "bravo": (["CHANGELOG.json", "fixtures/a/b.json"], ["src/CHANGELOG.json"]),
}


@pytest.mark.parametrize("pack_file", PACKS)
def test_the_base_watch_reads_since_its_cursor_skips_the_packs_noise_and_cards_a_change_once(
    env, pack_file, monkeypatch
):
    import datetime

    from cockpitlib.acts import _anchor_hit, _noise_only, changes_dir, scan_base, segment_glob
    from cockpitlib.kanban import BoardWrites, board_cards
    from cockpitlib.paths import platform_dir

    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    pack = load(pack_file)
    noise, signal = BASE_NOISE[pack["name"]]
    assert _noise_only(noise, pack) and not _noise_only(signal, pack)
    assert not _noise_only([noise[-1]], _other(pack))  # the other fixture's noise is its own
    assert segment_glob("src/*.ts").match("src/a.ts") and not segment_glob("src/*.ts").match("src/x/a.ts")
    assert segment_glob("src/**/*.ts").match("src/x/y/a.ts") and segment_glob("src/**/*.ts").match("src/a.ts")
    assert _anchor_hit("src/orders/", "src/orders/a.py") and _anchor_hit("src/*/api/**", "src/orders/api/x.py")
    assert not _anchor_hit("src/*/api/**", "src/orders/deep/api/x.py") and _anchor_hit("src/o?ders", "src/orders/x")
    repo = pack["repos"]["repos"][0]["name"]
    merged = [
        {
            "number": 11,
            "title": "a",
            "files": [f"src/{pack['name']}.py"],
            "author": {"login": "dev"},
            "mergedAt": "2026-10-20T10:00:00Z",
        },
        {"number": 12, "title": "b", "files": noise, "author": {"login": "dev"}, "mergedAt": "2026-10-20T11:00:00Z"},
        {
            "number": 13,
            "title": "c",
            "files": ["src/x.py"],
            "author": {"login": pack["forge"]["bots"][0]},
            "mergedAt": "2026-10-20T12:00:00Z",
        },
    ]

    class Reply:
        def __init__(self, body):
            self.returncode, self.stderr, self.stdout = 0, "", json.dumps(body)

    runner = lambda argv: Reply(merged if argv[argv.index("--repo") + 1].endswith("/" + repo) else [])  # noqa: E731
    now = datetime.datetime(2026, 10, 22, tzinfo=datetime.UTC).timestamp()
    assert scan_base(pack, runner=runner, now=now) == "base-watch 3"
    statuses = {
        number: json.load(open(os.path.join(changes_dir(), f"{repo}-{number}.json"), encoding="utf-8"))["status"]
        for number in (11, 12, 13)
    }
    assert statuses == {11: "unmapped", 12: "skipped", 13: "skipped"}
    assert (
        json.load(open(os.path.join(platform_dir(), "base-cursor.json"), encoding="utf-8"))[repo]
        == "2026-10-20T12:00:00Z"
    )
    assert scan_base(pack, runner=runner, now=now) == "base-watch 0"
    cards = [card for card in board_cards(pack["board"], pack) if card["flow"] == "platform"]
    assert len(cards) == 1 and cards[0]["ticket"] == f"{pack['tracker']['project']}-PLATFORM"
    writes = BoardWrites(pack["board"])
    writes.complete(cards[0]["id"], result="explained")
    writes.flush()
    os.remove(os.path.join(platform_dir(), "base-cursor.json"))  # read everything again: the change still has its card
    assert scan_base(pack, runner=runner, now=now) == "base-watch 3"
    assert len([card for card in board_cards(pack["board"], pack) if card["flow"] == "platform"]) == 1


@pytest.mark.parametrize("pack_file", PACKS)
def test_the_digest_lists_review_requests_and_replies_in_the_humans_threads(env, pack_file, monkeypatch):
    from tests.support import fake_gh

    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    pack = load(pack_file)
    other = _other(pack)
    from cockpitlib.ops import morning_digest
    from cockpitlib.paths import platform_dir, qa

    repo = pack["repos"]["repos"][0]["name"]
    full = f"{pack['forge']['org']}/{repo}"
    me = pack["forge"]["human_login"]
    fake_gh.setup(me=me, repos=[full, f"{other['forge']['org']}/{repo}"])
    fake_gh.pull(full, 31, "work/a", "a" * 40, title=f"asks {pack['name']}", author="someone")
    fake_gh.pull(full, 32, "work/b", "b" * 40, title="not asked", author="someone")
    fake_gh.pull(f"{other['forge']['org']}/{repo}", 33, "work/c", "c" * 40, title="other org", author="someone")
    data = fake_gh.state()
    for full_name, number in ((full, "31"), (f"{other['forge']['org']}/{repo}", "33")):
        data["repos"][full_name]["pulls"][number]["requested_reviewers"] = [{"login": me}]
    fake_gh.save(data)
    ticket = "TASK-8870"
    folder = os.path.join(qa(), ticket, "pr")
    os.makedirs(folder, exist_ok=True)
    json.dump(
        {"repo": repo, "number": 9, "replies": [{"author": f"peer-{pack['name']}", "body": "answered your thread"}]},
        open(os.path.join(folder, f"{repo}-9.json"), "w", encoding="utf-8"),
    )
    assert morning_digest(pack) == "digest"
    text = open(os.path.join(platform_dir(), "digest.md"), encoding="utf-8").read()
    assert (
        "Review requested: 1" in text
        and f"{repo}#31 asks {pack['name']}" in text
        and "#33" not in text
        and "#32" not in text
    )
    assert "Replies in your threads: 1" in text and f"{repo}#9 by peer-{pack['name']}: answered your thread" in text
    query = next(call["path"] for call in fake_gh.calls() if call["path"].startswith("search/issues"))
    assert me in query and other["forge"]["human_login"] not in query
    fake_gh.fail("GET search/issues", "HTTP 502")
    assert morning_digest(pack) == "digest"
    text = open(os.path.join(platform_dir(), "digest.md"), encoding="utf-8").read()
    assert "Review requested" not in text and "Replies in your threads: 1" in text


@pytest.mark.parametrize("pack_file", PACKS)
def test_perf_sync_runs_the_pack_command_and_a_failure_turns_the_watcher_red(env, pack_file, monkeypatch, tmp_path):
    import shutil

    import yaml

    from cockpitlib.errors import PackError

    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    pack = load(pack_file)
    other = _other(pack)
    assert pack["perf"]["command"] != other["perf"]["command"]
    from cockpitlib.ops import perf_sync
    from cockpitlib.paths import platform_dir, watch_dir

    assert perf_sync(pack) == "perf"
    logged = open(os.path.join(os.environ["COCKPIT_ROOT"], "perf.log"), encoding="utf-8").read()
    assert os.path.join(platform_dir(), "perf.json") in logged and other["name"] not in logged
    assert json.load(open(os.path.join(watch_dir(), "perf-sync.json"), encoding="utf-8"))["ok"] is True
    monkeypatch.setenv("ACME_PERF_FAIL", "1")
    monkeypatch.setenv("NORTH_METRICS_DOWN", "1")
    assert perf_sync(pack) == "perf"
    health = json.load(open(os.path.join(watch_dir(), "perf-sync.json"), encoding="utf-8"))
    assert health["ok"] is False and health["summary"].startswith("perf command failed: ")
    assert ("acme perf board unreachable" if pack["name"] == "acme" else "north metrics sink closed") in health[
        "summary"
    ]
    from cockpitlib.ops import _pack_command

    assert "No such file" in _pack_command(pack, ["bin/missing-perf"]) or "Errno" in _pack_command(
        pack, ["bin/missing-perf"]
    )
    name = os.path.basename(os.path.dirname(pack_file))
    copied = tmp_path / "packs" / name
    shutil.copytree(os.path.dirname(pack_file), copied)
    raw = yaml.safe_load((copied / "pack.yaml").read_text(encoding="utf-8"))
    for change, message in (
        (("perf", {"command": "bin/perf"}), "perf.command must be a command"),
        (("perf", {"cmd": ["x"]}), "perf takes command"),
        (("export", {"keep": 0}), "export.keep is a whole number"),
        (("export", {"keep": True}), "export.keep is a whole number"),
        (("export", {"commands": "x"}), "export.commands is a list"),
        (("export", {"commands": [[]]}), "export.commands[0] must be a command"),
        (("export", {"when": 1}), "export takes commands and keep"),
    ):
        (copied / "pack.yaml").write_text(
            yaml.safe_dump({**raw, change[0]: change[1]}, sort_keys=False, allow_unicode=True), encoding="utf-8"
        )
        with pytest.raises(PackError, match=re.escape(message)):
            load(str(copied / "pack.yaml"))


@pytest.mark.parametrize("pack_file", PACKS)
def test_export_runs_every_pack_command_keeps_the_packs_count_and_one_failure_is_red(env, pack_file, monkeypatch):
    import yaml

    from tests.test_vault import seal_ephemeral

    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    pack = load(pack_file)
    other = _other(pack)
    assert pack["export"]["keep"] != other["export"]["keep"]
    from cockpitlib.ops import export_keep
    from cockpitlib.paths import platform_dir, records, watch_dir
    from cockpitlib.vault import store_login

    seal_ephemeral(monkeypatch, str(env["home"]))
    staging = yaml.safe_load(open(os.path.join(os.path.dirname(pack_file), "staging.yaml"), encoding="utf-8"))
    store_login(staging["origins"]["app"], f"qa@{pack['name']}.test", "pw-export-1", lane="tester-1")
    assert export_keep(pack) == "export"
    assert (
        json.load(open(os.path.join(platform_dir(), "export.json"), encoding="utf-8"))["keep"] == pack["export"]["keep"]
    )
    log = os.path.join(os.environ["COCKPIT_ROOT"], "export.log")
    lines = open(log, encoding="utf-8").read().splitlines()
    assert len(lines) == len(pack["export"]["commands"]) and all(records() in line for line in lines)
    assert json.load(open(os.path.join(watch_dir(), "export.json"), encoding="utf-8"))["ok"] is True
    first = pack["export"]["commands"][0]
    failing = first[1] if pack["name"] == "acme" else first[2]
    monkeypatch.setenv("ACME_ARCHIVE_FAIL" if pack["name"] == "acme" else "NORTH_SNAPSHOT_DOWN", failing)
    os.remove(log)
    assert export_keep(pack) == "export"
    assert (
        len(open(log, encoding="utf-8").read().splitlines()) == len(pack["export"]["commands"]) - 1
    )  # the rest still ran
    health = json.load(open(os.path.join(watch_dir(), "export.json"), encoding="utf-8"))
    assert (
        health["ok"] is False
        and f"{os.path.basename(first[0])}: " in health["summary"]
        and failing in health["summary"]
    )


@pytest.mark.parametrize("pack_file", PACKS)
def test_a_registered_job_with_an_old_success_or_no_run_is_a_watcher_row(env, pack_file, monkeypatch):
    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    pack = load(pack_file)
    other = _other(pack)
    from cockpitlib.health import stale_minutes, stale_records, watcher_rows
    from cockpitlib.ops import _health, _health_hold
    from cockpitlib.paths import hermes_home, watch_dir
    from cockpitlib.setup import CRON_JOBS, cron_schedule
    from dashboard.cockpit.payload import _watcher_rows

    schedules = {name: cron_schedule(pack, name, default) for name, default, _script in CRON_JOBS}
    limited = next(iter(pack["watchers"]["limits"]))
    assert stale_minutes(pack, limited, schedules[limited]) == pack["watchers"]["limits"][limited]["stale_minutes"]
    assert stale_minutes(other, limited, schedules[limited]) != stale_minutes(pack, limited, schedules[limited])
    assert stale_minutes(pack, "ci-watch", "1m") == 15 and stale_minutes(pack, "base-watch", "2h") in (360, 900)
    assert stale_minutes({}, "standup", "0 7 * * *") == 2880 and stale_minutes({}, "export", "0 7 * * 5") == 8 * 1440
    assert stale_minutes({}, "bumps", "0 7 * * 1,2,3") == 4 * 1440
    assert stale_records(pack, watch_dir()) == []  # nothing registered yet
    jobs = os.path.join(hermes_home(), "cron", "jobs.json")
    os.makedirs(os.path.dirname(jobs), exist_ok=True)
    json.dump(
        {"jobs": [{"name": "ci-watch"}, {"name": limited}, {"name": "pr-watch"}]}, open(jobs, "w", encoding="utf-8")
    )
    registered = os.path.getmtime(jobs)
    assert stale_records(pack, watch_dir(), now=registered + 60) == []
    later = registered + 3 * 86400
    rows = {row["name"]: row for row in stale_records(pack, watch_dir(), now=later)}
    assert (
        rows["ci-watch"]["reason"] == "never ran in the 3 days since it was registered"
        and rows["ci-watch"]["record"]["never_ran"]
    )
    assert (limited in rows) == (pack["watchers"]["limits"][limited]["stale_minutes"] < 3 * 1440)
    _health("ci-watch", "fine")
    recent = json.load(open(os.path.join(watch_dir(), "ci-watch.json"), encoding="utf-8"))["last_ok"]
    assert "ci-watch" not in {row["name"] for row in stale_records(pack, watch_dir(), now=recent + 60)}
    old = {row["name"]: row for row in stale_records(pack, watch_dir(), now=recent + 7100)}
    assert old["ci-watch"]["reason"] == "no successful run in 118 minutes"
    assert {row["name"]: row for row in stale_records(pack, watch_dir(), now=recent + 3 * 3600)}["ci-watch"][
        "reason"
    ] == "no successful run in 3 hours"
    _health_hold("pr-watch", f"watch stopped {pack['name']}")
    both = watcher_rows(pack, watch_dir(), now=later)
    assert [row["name"] for row in both].count("pr-watch") == 1 and both[0]["reason"] == f"watch stopped {pack['name']}"
    shown = {row["id"]: row for row in _watcher_rows(pack)}
    assert "pr-watch" in shown and shown["pr-watch"]["kind"] == "fix watcher"
    assert any(row["name"] == "pr-watch" for row in _client().get("/needs-you").json()["watchers"])
    open(os.path.join(watch_dir(), "ci-watch.json"), "w", encoding="utf-8").write("{bad")
    assert "ci-watch" in {row["name"] for row in stale_records(pack, watch_dir(), now=later)}
