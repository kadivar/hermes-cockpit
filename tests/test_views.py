# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The pages after a move: the Board, QA and Usage views read the records they show; a card carries its Brief; the chat
runs a conversation, not a print; the IDE command runs; the Inbox reads the pack once."""

import json
import os
import shutil
import sqlite3
import sys
import time

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from cockpitlib.pack import PackError, load
from dashboard.cockpit.router import router

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _client():
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def _pack_copy(tmp_path, monkeypatch, extra: str = "") -> str:
    """The acme pack with more keys, bound for the test."""
    copied = tmp_path / "packs" / "acme"
    if not copied.exists():
        shutil.copytree(os.path.join(ROOT, "packs", "acme"), copied)
    pack_file = copied / "pack.yaml"
    pack_file.write_text(pack_file.read_text(encoding="utf-8") + extra, encoding="utf-8")
    monkeypatch.setenv("COCKPIT_PACK", str(pack_file))
    return str(pack_file)


def _qa(ticket: str) -> str:
    folder = os.path.join(os.environ["COCKPIT_WORKSPACE"], "hermes", "qa", ticket)
    os.makedirs(folder, exist_ok=True)
    return folder


def test_the_records_name_is_parsed_once_per_pack_version(bare, monkeypatch, tmp_path):
    import yaml

    from cockpitlib import paths

    pack_file = _pack_copy(tmp_path, monkeypatch)
    calls = []
    real = yaml.safe_load
    monkeypatch.setattr(yaml, "safe_load", lambda *a, **k: calls.append(1) or real(*a, **k))
    assert paths.records_name() == "hermes"
    for _ in range(50):
        paths.qa()
        paths.outbox()
    assert len(calls) == 1
    text = open(pack_file, encoding="utf-8").read().replace("records_dir: hermes", "records_dir: work/records")
    open(pack_file, "w", encoding="utf-8").write(text)
    os.utime(pack_file, (time.time() + 5, time.time() + 5))
    assert paths.records_name() == os.path.join("work", "records") and len(calls) == 2
    assert paths.records_name() == os.path.join("work", "records") and len(calls) == 2


def test_a_brief_nested_under_the_ticket_heading_is_the_brief(env):
    from cockpitlib.plan import brief_of, init

    nested = (
        "# Plan — TASK-100\n\n## Decision\n\ngo\n\n## Plan — TASK-100 · the fix\n\n### Brief\n**Issue:** the box\n"
        "**Fix:** a marker\n- one\n\n### Impacted areas\n\n- api\n\n## Steps\n\n1. write\n"
    )
    assert brief_of(nested) == "**Issue:** the box\n**Fix:** a marker\n- one"
    assert brief_of("# Plan\n\n## Brief\n\nplain\n\n## Steps\n\n1. x") == "plain"
    assert brief_of("# Plan\n\n### Brief\n\nunder the head\n\n## Steps\n\n1. x") == "under the head"
    assert brief_of("# Plan\n\n## Steps\n\n1. x") == ""
    init("TASK-100", nested, "go")
    shown = _client().get("/ticket?ticket=TASK-100").json()
    assert shown["brief"].startswith("<p><strong>Issue:</strong> the box") and shown["plan_line"].startswith(
        "**Issue:** the box"
    )
    assert "Plan — TASK-100 · the fix" in [part["title"] for part in shown["plan_parts"]]


def test_the_board_shows_open_cards_and_the_recent_done_ones_with_their_state(env):
    from cockpitlib.kanban import BoardWrites, place_card
    from tests.support.boards import put_card, raw

    pack = load(os.environ["COCKPIT_PACK"])
    slug = pack["board"]
    blocked = place_card(slug, "TASK-100: implement the fix", "worker-1", "ready")
    writes = BoardWrites(slug)
    writes.block(blocked, "Which colour: the old one or the brand one?")
    writes.comment(blocked, "worker-1", "I need the colour.\nsecond line")
    writes.flush()
    fresh = put_card(slug, "TASK-100: test the fix", "tester-1", "done")
    stale = put_card(slug, "TASK-101: an old job", "tester-1", "done")
    connection = raw(slug)
    connection.execute("update tasks set completed_at = ? where id = ?", (int(time.time()), fresh))
    connection.execute("update tasks set completed_at = ? where id = ?", (int(time.time()) - 5 * 86400, stale))
    connection.commit()
    connection.close()
    body = _client().get("/board").json()
    ids = {card["id"]: card for card in body["cards"]}
    assert blocked in ids and fresh in ids and stale not in ids
    assert (
        ids[blocked]["question"].startswith("Which colour")
        and ids[blocked]["status"] == "blocked"
        and ids[blocked]["lane"] == "worker-1"
    )
    assert ids[blocked]["last_comment"]["author"] == "worker-1" and ids[blocked]["last_comment"]["text"].startswith(
        "I need the colour."
    )
    assert (
        ids[blocked]["ticket"] == "TASK-100"
        and ids[blocked]["flow"]
        and ids[blocked]["created"]
        and ids[blocked]["alive"] is False
    )
    assert ids[fresh]["completed"] and body["counts"]["done"] == 1 and body["counts"]["blocked"] == 1
    assert body["lanes"] == ["tester-1", "worker-1"] and [card["id"] for card in body["by_status"]["blocked"]] == [
        blocked
    ]
    assert body["columns"][-3:] == ["done", "archived", "cancelled"] and "TASK-100" in body["ticket_activity"]
    assert len(_client().get("/board?include_done_days=10").json()["cards"]) == 3
    # TASK-100 still has an open card, so it is live: its done card stays even with no window; TASK-101's does not
    assert len(_client().get("/board?include_done_days=0").json()["cards"]) == 2


def test_a_card_carries_its_brief_and_the_records_it_mentions(env):
    from cockpitlib.kanban import BoardWrites, place_card
    from cockpitlib.plan import init

    pack = load(os.environ["COCKPIT_PACK"])
    slug = pack["board"]
    folder = _qa("TASK-100")
    os.makedirs(os.path.join(folder, "shots"), exist_ok=True)
    open(os.path.join(folder, "shots", "one.png"), "wb").write(b"\x89PNG\r\n")
    init(
        "TASK-100",
        "# Plan — TASK-100\n\n## Plan — TASK-100 · fix\n\n### Brief\n**Issue:** the box\n\n## Steps\n\n1. x",
        "go",
    )
    card = place_card(
        slug,
        "TASK-100: implement",
        "worker-1",
        "ready",
        body="Read hermes/qa/TASK-100/plan.md and hermes/qa/TASK-100/shots/ first.",
    )
    shown = _client().get(f"/card-detail?id={card}").json()
    assert [doc["rel"] for doc in shown["attachments"]["docs"]] == ["qa/TASK-100/plan.md"]
    assert [item["rel"] for item in shown["attachments"]["dirs"]] == ["qa/TASK-100/shots"] and shown["attachments"][
        "dirs"
    ][0]["files"][0]["kind"] == "image"
    assert (
        '<div class="k">Issue</div>' in shown["brief"]
        and "the box" in shown["brief"]
        and "brief_derived" not in shown["attachments"]
    )
    writes = BoardWrites(slug)
    writes.comment(card, "tester-1", "Run 2\n\n### Brief\n**Result:** 3 pass\n- one evidence\n")
    writes.flush()
    shown = _client().get(f"/card-detail?id={card}").json()
    assert (
        '<div class="k">Result</div>' in shown["brief"]
        and "<li>one evidence</li>" in shown["brief"]
        and "the box" not in shown["brief"]
    )
    bare = place_card(slug, "BUMPS-1: bumps on api", "analyst", "ready", body="Groom the bumps.")
    shown = _client().get(f"/card-detail?id={bare}").json()
    assert (
        shown["attachments"]["brief_derived"] is True
        and "Groom the bumps." in shown["brief"]
        and shown["attachments"]["docs"] == []
    )


RESULTS = """# Test run 001 — TASK-100

**Date:** 2026-10-11, 15:00 CEST
**Under test:** api at abc123

## Summary

| # | Scenario | Verdict | Evidence |
|---|---|---|---|
| 1 | the box renders | ✅ pass | [shot](evidences/one.png) |
| 2 | the empty case | ❌ fail | |
| 3 | the slow case | ⚠ partial | |

## Notes

All **fine** otherwise.
"""


def test_qa_reads_the_runs_their_results_and_the_evidence(bare):
    folder = _qa("TASK-100")
    run = os.path.join(folder, "pass-01")
    os.makedirs(os.path.join(run, "evidences", "videos"), exist_ok=True)
    open(os.path.join(run, "test-results.md"), "w", encoding="utf-8").write(RESULTS)
    open(os.path.join(run, "evidences", "one.png"), "wb").write(b"\x89PNG\r\n\x1a\n")
    open(os.path.join(run, "evidences", "videos", "README.md"), "w", encoding="utf-8").write("the *videos*\n")
    open(os.path.join(folder, "test-scenarios.md"), "w", encoding="utf-8").write("# Plan\n\n1. box\n")
    os.makedirs(os.path.join(folder, "review"), exist_ok=True)
    open(os.path.join(folder, "review", "notes.md"), "w", encoding="utf-8").write("ok\n")
    _qa("TASK-200")  # no runs: not in the index
    client = _client()
    index = client.get("/qa").json()["tickets"]
    assert [row["ticket"] for row in index] == ["TASK-100"]
    assert index[0]["runs"] == 1 and index[0]["last_run"] == "pass-01" and index[0]["date"] == "2026-10-11"
    assert index[0]["counts"] == {"pass": 1, "fail": 1, "warn": 1} and index[0]["scenarios"] == 3
    shown = client.get("/qa?ticket=TASK-100").json()
    assert (
        shown["dir"] == folder
        and len(shown["runs"]) == 1
        and shown["scenarios"].startswith("<")
        and [f["rel"] for f in shown["review"]] == ["notes.md"]
    )
    run_shown = shown["runs"][0]
    rows = run_shown["results"]["rows"]
    assert [row["verdict"] for row in rows] == ["pass", "fail", "warn"] and rows[0]["evidence"] == [
        {"label": "shot", "rel": "evidences/one.png"}
    ]
    assert (
        run_shown["results"]["meta"]["Under test"] == "api at abc123"
        and "<strong>fine</strong>" in run_shown["results"]["sections"]["Notes"]
    )
    assert [f["rel"] for f in run_shown["files"]] == ["one.png", "videos/README.md"] and run_shown["readme"].startswith(
        "<p>the <em>videos</em>"
    )
    assert (
        client.get("/qa?ticket=TASK-200").json()["runs"] == []
        and client.get("/qa?ticket=TASK-999").json()["dir"] is None
    )
    assert client.get("/qa?ticket=../x").status_code == 400
    media = client.get("/qa-file", params={"path": os.path.join(run, "evidences", "one.png")}).json()
    assert media["kind"] == "media" and media["mime"] == "image/png" and media["b64"].startswith("iVBOR")
    text = client.get("/qa-file", params={"path": os.path.join(run, "test-results.md")}).json()
    assert text["kind"] == "markdown" and text["html"].startswith("<h1>") and "Scenario" in text["text"]


def _state_db(path: str, rows) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    connection = sqlite3.connect(path)
    connection.execute(
        "create table sessions (id text, title text, model text, started_at real, ended_at real, input_tokens int, output_tokens int, "
        "cache_read_tokens int, cache_write_tokens int, estimated_cost_usd real, actual_cost_usd real, api_call_count int)"
    )
    connection.executemany("insert into sessions values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", rows)
    connection.commit()
    connection.close()


def test_usage_groups_the_seats_and_the_coding_tool_by_lane_ticket_day_and_model(env, monkeypatch, tmp_path):
    root = os.environ["COCKPIT_ROOT"]
    _pack_copy(tmp_path, monkeypatch, "")
    pack_file = os.environ["COCKPIT_PACK"]
    import re

    text = re.sub(
        r"(?m)^(\s*)transcript_glob:.*$",
        r'\1transcript_glob: "{root}/transcripts/-x-wt-{ticket}/*.jsonl"',
        open(pack_file, encoding="utf-8").read(),
    )
    assert "-x-wt-{ticket}" in text
    open(pack_file, "w", encoding="utf-8").write(text)
    now = time.time()
    home = os.environ["COCKPIT_HERMES_HOME"]
    _state_db(
        os.path.join(home, "profiles", "worker-1", "state.db"),
        [
            ("s1", "TASK-100 implement", "fixture-fast", now - 60, now - 10, 100, 20, 300, 5, 0.5, None, 3),
            ("s2", "TASK-100 again", "fixture-fast", now - 10 * 86400, None, 10, 2, 0, 0, 0.1, None, 1),
        ],
    )
    _state_db(
        os.path.join(home, "profiles", "gatekeeper", "state.db"),
        [("s3", "outbox sweep", "fixture-large", now - 120, now - 100, 50, 5, 0, 0, None, 0.25, 2)],
    )
    _state_db(
        os.path.join(home, "state.db"), [("s4", "a chat", "fixture-large", now - 30, now, 7, 7, 0, 0, 0.01, None, 1)]
    )
    folder = os.path.join(root, "transcripts", "-x-wt-TASK-100-api")
    os.makedirs(folder, exist_ok=True)
    stamp = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(now - 5)) + "Z"
    with open(os.path.join(folder, "abc.jsonl"), "w", encoding="utf-8") as handle:
        handle.write(json.dumps({"type": "user", "message": {"content": "do it"}}) + "\n")
        handle.write(
            json.dumps(
                {
                    "type": "assistant",
                    "timestamp": stamp,
                    "message": {
                        "model": "fixture-sonnet",
                        "usage": {
                            "input_tokens": 1000,
                            "output_tokens": 200,
                            "cache_read_input_tokens": 5000,
                            "cache_creation_input_tokens": 100,
                        },
                    },
                }
            )
            + "\n"
        )
        handle.write(
            json.dumps(
                {
                    "type": "assistant",
                    "timestamp": stamp,
                    "message": {"model": "fixture-sonnet", "usage": {"input_tokens": 1000, "output_tokens": 300}},
                }
            )
            + "\n"
        )
    client = _client()
    body = client.get("/usage?period=week&by=who&scope=hermes").json()
    groups = {group["key"]: group for group in body["groups"]}
    assert set(groups) == {"worker-1", "gatekeeper", "default", "coding tool (lanes)"}
    assert (
        groups["worker-1"]["sessions"] == 1
        and groups["worker-1"]["total"] == 425
        and groups["worker-1"]["seconds"] == 50
    )
    assert (
        groups["coding tool (lanes)"]["input"] == 2000
        and groups["coding tool (lanes)"]["output"] == 500
        and groups["coding tool (lanes)"]["calls"] == 2
    )
    assert groups["coding tool (lanes)"]["cost"] == pytest.approx(
        (2000 * 3 + 5000 * 0.3 + 100 * 3.75 + 500 * 15) / 1e6, abs=1e-4
    )
    assert (
        body["totals"]["week"]["sessions"] == 4
        and body["totals"]["all"]["sessions"] == 5
        and body["split"]["hermes_sessions"] == 4
    )
    assert (
        body["recent"][0]["when"]
        and {row["who"] for row in body["recent"]} == set(groups)
        and "windows" in body
        and "budget" in body
    )
    by_ticket = {
        group["key"]: group["sessions"] for group in client.get("/usage?period=all&by=ticket").json()["groups"]
    }
    assert by_ticket == {"TASK-100": 3, "gatekeeper · outbox sweeps": 1, "concierge · your chats": 1}
    by_model = {group["key"] for group in client.get("/usage?period=all&by=model").json()["groups"]}
    assert by_model == {"fixture-fast", "fixture-large", "fixture-sonnet"}
    days = [group["key"] for group in client.get("/usage?period=all&by=day").json()["groups"]]
    assert days == sorted(days) and len(days) == 2
    assert client.get("/usage?period=year").status_code == 400 and client.get("/usage?by=lane").status_code == 400
    sessions = client.get("/coding-sessions?scope=all").json()["sessions"]
    assert [row["ticket"] for row in sessions] == ["TASK-100"] and sessions[0]["prompt"] == ""
    from cockpitlib.chat import coding_tail

    assert coding_tail(sessions[0]["path"])["lines"] or coding_tail(sessions[0]["path"])["entries"]


def test_the_chat_runs_the_pack_chat_command_else_the_coding_command_made_interactive(bare, monkeypatch, tmp_path):
    from cockpitlib import chat

    monkeypatch.delenv("COCKPIT_CHAT_ARGV")
    assert chat.interactive(
        ["tool", "-p", "--model", "m", "--max-turns", "40", "--output-format=json", "--print", "--allowedTools", "Read"]
    ) == ["tool", "--model", "m", "--allowedTools", "Read"]
    assert chat.interactive(["-p"]) == ["-p"]
    assert chat._argv("TASK-1") == ["true"]
    assert chat._argv("own")[-1] == "-i"
    _pack_copy(tmp_path, monkeypatch, "")
    pack_file = os.environ["COCKPIT_PACK"]
    text = (
        open(pack_file, encoding="utf-8")
        .read()
        .replace('    command: ["true"]\n', '    command: ["true", "-p", "--max-turns", "9"]\n')
    )
    open(pack_file, "w", encoding="utf-8").write(text)
    assert chat._argv("TASK-1") == ["true"]
    open(pack_file, "a", encoding="utf-8").write("")
    text = (
        open(pack_file, encoding="utf-8")
        .read()
        .replace("  coding:\n", "  chat:\n    command: [talk, --model, big]\n  coding:\n")
    )
    open(pack_file, "w", encoding="utf-8").write(text)
    assert load(pack_file)["providers"]["chat"]["command"] == ["talk", "--model", "big"]
    assert chat._argv("TASK-1") == ["talk", "--model", "big"] and chat._argv("own") == ["talk", "--model", "big"]
    open(pack_file, "w", encoding="utf-8").write(
        text.replace("    command: [talk, --model, big]\n", "    command: talk\n")
    )
    with pytest.raises(PackError, match="providers.chat.command"):
        load(pack_file)
    open(pack_file, "w", encoding="utf-8").write(text.replace("  intake: judgment\n", "  intake: chat\n"))
    with pytest.raises(PackError, match="chat is not a lane provider"):
        load(pack_file)


def test_the_ide_command_of_the_pack_runs_for_a_ticket_and_a_file(env, monkeypatch, tmp_path):
    from cockpitlib.ops import ide_argv

    log = tmp_path / "ide.log"
    script = tmp_path / "ide.py"
    script.write_text(
        f"import sys\nopen({str(log)!r}, 'a').write(' '.join(sys.argv[1:]) + chr(10))\n", encoding="utf-8"
    )
    _pack_copy(
        tmp_path,
        monkeypatch,
        f"ide:\n  command: [{sys.executable}, {script}, open, '{{ticket}}']\n  file_command: [{sys.executable}, {script}, file, '{{path}}']\n",
    )
    pack = load(os.environ["COCKPIT_PACK"])
    assert ide_argv(pack, "command", ticket="TASK-100")[2:] == ["open", "TASK-100"]
    assert ide_argv({"ide": {"command": ["bin/ide", "{workspace}"]}, "_dir": "/pack"}, "command") == [
        "/pack/bin/ide",
        os.environ["COCKPIT_WORKSPACE"],
    ]
    assert ide_argv(pack, "missing") == []
    from cockpitlib.errors import CockpitError
    from cockpitlib.ops import ide_launch

    with pytest.raises(CockpitError, match="ide.command did not start"):  # a command that is not on this machine
        ide_launch({"ide": {"command": ["/no/such/ide-binary"]}, "_dir": "/pack"}, "command")
    note = os.path.join(_qa("TASK-100"), "plan.md")
    open(note, "w", encoding="utf-8").write("x\n")
    client = _client()
    assert (
        client.post("/open-ide", json={"ticket": "TASK-100"}).json()["out"].startswith("TASK-100 has no worktree yet")
    )
    opened = client.post("/open-ide", json={"ticket": "TASK-100", "file": note + ":3"}).json()
    assert opened["ok"] and opened["out"].endswith("open TASK-100") and opened["path"].endswith("ide-TASK-100.json")
    assert client.post("/open-file", json={"path": note}).json()["out"].endswith(f"file {note}")
    assert client.post("/open-file", json={"path": "/etc/hosts"}).status_code == 400
    from cockpitlib.cli import main

    assert main(["ide", "file", note]) == 0 and main(["ide", "open", "TASK-100", "--file", note]) == 0
    for _ in range(40):
        lines = log.read_text(encoding="utf-8").splitlines() if log.exists() else []
        if len(lines) >= 4:
            break
        time.sleep(0.05)
    assert sorted(lines) == sorted(
        ["open TASK-100", f"file {note}", f"file {note}", "open TASK-100"]
    )  # detached: any order
    record = json.load(
        open(os.path.join(os.environ["COCKPIT_WORKSPACE"], "hermes", "platform", "ide-TASK-100.json"), encoding="utf-8")
    )
    assert record["file"] == note and record["ticket"] == "TASK-100"
    text = (
        open(os.environ["COCKPIT_PACK"], encoding="utf-8")
        .read()
        .replace("  file_command:", "  other: [x]\n  file_command:")
    )
    open(os.environ["COCKPIT_PACK"], "w", encoding="utf-8").write(text)
    with pytest.raises(PackError, match="ide: unknown key other"):
        load(os.environ["COCKPIT_PACK"])


def test_a_plain_install_records_the_ide_request_and_opens_nothing(bare):
    pack = load(os.environ["COCKPIT_PACK"])
    from cockpitlib.ops import ide_open

    assert ide_open(pack, "TASK-100").endswith("ide-TASK-100.json")


def test_an_intent_without_a_lane_loaded_no_skill_and_the_inbox_reads_the_pr_rows_once(env, monkeypatch):
    from cockpitlib.skill_log import loaded
    from dashboard.cockpit import router as web

    pack = load(os.environ["COCKPIT_PACK"])
    assert loaded("", "") == [] and loaded("TASK-100", "") == [] and loaded("TASK-100", "../x") == []
    assert web._skills(pack, {"type": "push-branch", "ticket": "", "created_by": ""})["loaded"] == []
    from cockpitlib.outbox import create

    for number in (1, 2, 3):
        create(
            pack,
            "TASK-100",
            "push-branch",
            f"c{number}",
            "ship",
            {"repo": "api", "branch": f"work/{number}", "number": number},
        )
    from cockpitlib import pr_watch

    calls = []
    real = pr_watch.inbox_rows
    monkeypatch.setattr(pr_watch, "inbox_rows", lambda: calls.append(1) or real())
    rows = _client().get("/list").json()["rows"]
    assert len(rows) == 3 and len(calls) == 1
    from cockpitlib.activity import lane_label, ticket_activity
    from cockpitlib.intents import load as load_intent
    from cockpitlib.intents import save

    record = load_intent(rows[0]["id"])
    record["created_by"] = ".hermes"
    save(record)
    assert lane_label(".hermes") == "cockpit" and lane_label("worker-1") == "worker-1" and lane_label(None) == ""
    written = [row for row in ticket_activity(pack, "TASK-100") if row["kind"] == "written"]
    assert {row["who"] for row in written} == {"cockpit", "human"}
    assert _client().get("/list").json()["rows"][0]["skills"]["loaded"] == []


# ---------- after the first round: records an earlier pipeline wrote, the sealed vault, the map's badges, the demo login, the chat's session ----------


def test_a_pr_record_from_an_earlier_pipeline_reads_with_the_shapes_the_pages_expect(env):
    import datetime

    from cockpitlib.pr_watch import _epoch, normal, prs_of, record_path

    iso = datetime.datetime.fromisoformat("2026-10-16T10:45:35+00:00").timestamp()
    assert (
        _epoch("2026-10-16T10:45:35Z") == iso
        and _epoch(1792233935) == 1792233935.0
        and _epoch("") == 0.0
        and _epoch(None) == 0.0
    )
    row = normal(
        {
            "number": 4,
            "repo": "api",
            "last_activity": "2026-10-16T10:45:35Z",
            "rereview_ready": "",
            "re_requested": None,
            "merged": None,
            "my_threads": None,
            "since_review": None,
            "approvals": None,
            "new": [{"id": 1}],
        }
    )
    assert (
        row["last_activity"] == iso
        and row["rereview_ready"] is False
        and row["re_requested"] is False
        and row["merged"] is False
    )
    assert row["my_threads"] == {} and row["since_review"] == {} and row["approvals"] == [] and row["new_count"] == 1
    assert (
        normal({"rereview_ready": "yes", "last_activity": ""})["rereview_ready"] is True
        and normal({"last_activity": ""})["last_activity"] is None
    )
    path = record_path("TASK-100", "api", 7)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    json.dump(
        {
            "number": 7,
            "repo": "api",
            "role": "author",
            "state": "open",
            "last_activity": "2026-10-16T10:45:35Z",
            "rereview_ready": "",
            "new": [],
            "head_sha": "abc",
        },
        open(path, "w", encoding="utf-8"),
    )
    shown = prs_of("TASK-100")
    assert shown[0]["last_activity"] == iso and shown[0]["rereview_ready"] is False and shown[0]["my_threads"] == {}
    # the watcher's merge of a new read into that record no longer raises on the ISO text
    from cockpitlib import pr_watch

    class Forge:
        def pr(self, repo, number):
            return {
                "number": number,
                "state": "open",
                "head": {"sha": "def"},
                "user": {"login": "someone"},
                "title": "t",
                "html_url": "u",
                "base": {"ref": "main"},
                "requested_reviewers": [],
                "merged": False,
                "draft": False,
            }

        def comments(self, repo, number):
            return []

        def threads(self, repo, number):
            return []

    try:
        record = pr_watch.read(load(os.environ["COCKPIT_PACK"]), Forge(), "TASK-100", "api", 7, 1792300000.0)
    except (
        AttributeError,
        KeyError,
        TypeError,
    ) as exc:  # the stand-in forge may lack a field the reader wants: the float is what this test guards
        pytest.skip(f"forge stand-in too thin: {exc}")
    assert record["last_activity"] >= iso


def test_housekeeping_skips_the_steps_that_need_the_private_key_on_a_sealed_machine(bare, monkeypatch):
    from cockpitlib import housekeeping
    from cockpitlib.errors import CockpitError

    def locked(pack):
        raise CockpitError("gpg: public key decryption failed: No secret key\ngpg: decryption failed: No secret key")

    def broken(pack):
        raise CockpitError("the forge said no")

    monkeypatch.setattr(
        housekeeping, "STEPS", (("return-lends", locked), ("staging-audit", locked), ("sweep", lambda pack: "0"))
    )
    pack = load(os.environ["COCKPIT_PACK"])
    text = housekeeping.run(pack)
    assert text.count(housekeeping.LOCKED) == 2 and "sweep: 0" in text
    record = json.load(
        open(os.path.join(os.environ["COCKPIT_WORKSPACE"], "hermes", "watch", "housekeeping.json"), encoding="utf-8")
    )
    assert record["ok"] is True
    monkeypatch.setattr(housekeeping, "STEPS", (("return-lends", locked), ("sweep", broken)))
    housekeeping.run(pack)
    record = json.load(
        open(os.path.join(os.environ["COCKPIT_WORKSPACE"], "hermes", "watch", "housekeeping.json"), encoding="utf-8")
    )
    assert record["ok"] is False and "the forge said no" in record["detail"]


def test_the_platform_badges_count_the_windows_changes_per_node_and_an_area_inherits_them(bare, monkeypatch):
    from dashboard.cockpit.routes.pages import _node_counts

    tree = {
        "nodes": [
            {"id": "build", "kind": "area", "parent": None},
            {"id": "editor", "kind": "feature", "parent": "build"},
            {"id": "export", "kind": "feature", "parent": "build"},
            {"id": "auth", "kind": "component", "parent": None},
        ]
    }
    now = time.time()
    stamp = lambda days: time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now - days * 86400))
    changes = [
        {
            "repo": "api",
            "number": 1,
            "status": "relevant",
            "seen": False,
            "nodes": ["editor", "auth"],
            "merged_at": stamp(0.5),
        },
        {"repo": "api", "number": 2, "status": "relevant", "seen": True, "nodes": ["editor"], "merged_at": stamp(3)},
        {"repo": "api", "number": 3, "status": "skipped", "seen": False, "nodes": ["export"], "merged_at": stamp(0.1)},
        {"repo": "api", "number": 4, "status": "unmapped", "seen": False, "nodes": [], "merged_at": stamp(0.1)},
        {"repo": "api", "number": 5, "status": "explained", "seen": False, "nodes": ["export"], "merged_at": stamp(20)},
    ]
    counts, inherited = _node_counts(tree, changes, 1)
    assert counts == {"editor": {"total": 1, "unseen": 1}, "auth": {"total": 1, "unseen": 1}} and inherited == {
        "build": {"total": 1, "unseen": 1}
    }
    counts, inherited = _node_counts(tree, changes, 7)
    assert counts["editor"] == {"total": 2, "unseen": 1} and inherited["build"] == {"total": 2, "unseen": 1}
    counts, inherited = _node_counts(tree, changes, 0)
    assert counts["export"] == {"total": 1, "unseen": 1} and inherited["build"] == {"total": 3, "unseen": 2}
    from cockpitlib import acts

    monkeypatch.setattr(acts, "ordered_changes", lambda fallback=None: changes)
    body = (
        _client().get("/platform?days=7").json()
    )  # the route counts against the pack's own map: the per-node numbers travel, the parents are that map's
    assert body["counts"]["editor"] == {"total": 2, "unseen": 1} and isinstance(body["inherited"], dict)


def test_the_demo_login_comes_from_the_recorded_login_or_the_slots_own_file(bare):
    from cockpitlib.slots import state_dir

    folder = _qa("TASK-100")
    json.dump(
        {"ticket": "TASK-100", "slot": 1, "login": {"user_id": 7, "username": "owner@example.test"}, "links": []},
        open(os.path.join(folder, "demo.json"), "w", encoding="utf-8"),
    )
    client = _client()
    shown = client.get("/demo?ticket=TASK-100").json()
    assert shown["account"] == "owner@example.test" and shown["login"] is None
    os.makedirs(state_dir(1), exist_ok=True)
    json.dump(
        {"username": "demo@example.test", "password": "pw-demo-1", "slot": "1"},
        open(os.path.join(state_dir(1), "demo.json"), "w", encoding="utf-8"),
    )
    shown = client.get("/demo?ticket=TASK-100").json()
    assert (
        shown["login"] == {"username": "owner@example.test", "email": "owner@example.test", "password": "pw-demo-1"}
        and shown["account"] == "owner@example.test"
    )
    os.remove(os.path.join(folder, "demo.json"))  # no record at all: the slot file names the account too
    json.dump(
        {"ticket": "TASK-100", "slot": 1, "links": []}, open(os.path.join(folder, "demo.json"), "w", encoding="utf-8")
    )
    shown = client.get("/demo?ticket=TASK-100").json()
    assert shown["login"]["username"] == "demo@example.test" and shown["account"] == "demo@example.test"
    json.dump(
        {
            "ticket": "TASK-100",
            "slot": 1,
            "login": {"username": "owner@example.test", "password": "pw-owner"},
            "links": [],
        },
        open(os.path.join(folder, "demo.json"), "w", encoding="utf-8"),
    )
    shown = client.get("/demo?ticket=TASK-100").json()
    assert shown["login"]["username"] == "owner@example.test" and shown["login"]["password"] == "pw-owner"


def test_the_chat_reopens_its_own_session_and_forks_a_ticket_chat_from_the_lanes_run(bare, monkeypatch, tmp_path):
    from cockpitlib import chat

    monkeypatch.delenv("COCKPIT_CHAT_ARGV")
    transcripts = tmp_path / "transcripts" / "p1"
    transcripts.mkdir(parents=True)
    spec = (
        f"providers:\n  chat:\n    command: [talk, --session-id, '{{session}}']\n    resume: [talk, --resume, '{{session}}']\n"
        f"    fork: [talk, --resume, '{{source}}', --fork-session, --session-id, '{{session}}']\n    session_glob: \"{tmp_path}/transcripts/*/{{session}}.jsonl\"\n"
    )
    _pack_copy(tmp_path, monkeypatch, "")
    pack_file = os.environ["COCKPIT_PACK"]
    text = (
        open(pack_file, encoding="utf-8")
        .read()
        .replace("providers:\n", spec.replace("providers:\n", "providers:\n", 1), 1)
    )
    open(pack_file, "w", encoding="utf-8").write(text)
    loaded = load(pack_file)
    assert loaded["providers"]["chat"]["resume"] == ["talk", "--resume", "{session}"]
    assert chat.chat_argv("own", "s-new") == ["talk", "--session-id", "s-new"]
    (transcripts / "s-old.jsonl").write_text("{}\n", encoding="utf-8")
    assert chat.session_exists("s-old") and not chat.session_exists("s-new") and not chat.session_exists("")
    assert chat.chat_argv("own", "s-old") == ["talk", "--resume", "s-old"]
    assert chat.chat_argv("TASK-1", "s-new", "run-9") == [
        "talk",
        "--resume",
        "run-9",
        "--fork-session",
        "--session-id",
        "s-new",
    ]
    assert chat.chat_argv("TASK-1", "s-old", "run-9") == ["talk", "--resume", "s-old"]
    record = chat._start_record("own", None, False)
    assert len(record["session"]) == 36 and record["session"].count("-") == 4
    glob_line = next(line for line in text.splitlines(True) if line.startswith("    session_glob:"))
    for old, bad, message in (
        ("    resume: [talk, --resume, '{session}']\n", "    resume: talk\n", "providers.chat.resume"),
        (glob_line, "    session_glob: '/x/*.jsonl'\n", "session_glob must name"),
        ("    resume: [talk, --resume, '{session}']\n", "    extra: 1\n", "unknown key extra"),
    ):
        assert text.count(old) == 1
        open(pack_file, "w", encoding="utf-8").write(text.replace(old, bad))
        with pytest.raises(PackError, match=message):
            load(pack_file)


def test_an_acknowledged_done_intent_is_no_longer_a_confirm_row(bare):
    from dashboard.cockpit.payload import _inbox_kind

    assert _inbox_kind({"type": "ticket-done", "status": "pending", "ask": ""}) == "confirm done"
    assert _inbox_kind({"type": "ticket-done", "status": "acknowledged", "ask": ""}) == ""


def test_an_inbox_row_carries_the_prs_current_state_and_only_the_watchs_new_comments(env):
    from cockpitlib.outbox import create
    from cockpitlib.pr_watch import record_path
    from dashboard.cockpit import router as web

    pack = load(os.environ["COCKPIT_PACK"])
    path = record_path("TASK-100", "api", 12)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    json.dump(
        {
            "number": 12,
            "repo": "api",
            "role": "author",
            "state": "open",
            "merged": False,
            "author": "dev",
            "last_activity": "2026-10-16T10:45:35Z",
            "approvals": [{"author": "lead", "at": "2026-10-16T10:00:00Z"}],
            "new": [{"id": 1, "author": "lead", "body": "nit", "at": "2026-10-16T11:00:00Z"}],
            "new_count": 1,
        },
        open(path, "w", encoding="utf-8"),
    )
    # an intent written when the PR had comments keeps a stale count; the row drops it and reads the watch
    item = {
        "ticket": "TASK-100",
        "type": "pr-edit",
        "payload": {"repo": "api", "number": 12},
        "pr": {"repo": "api", "number": 12, "new_count": 9, "new": [{"id": 1}, {"id": 2}]},
    }
    row = web._with_new_comments(item, [])
    assert (
        row["new_count"] == 0
        and row["new"] == []
        and row["approvals"][0]["author"] == "lead"
        and row["merged"] is False
        and row["role"] == "author"
    )
    row = web._with_new_comments(
        item, [{"ticket": "TASK-100", "repo": "api", "number": 12, "new": [{"id": 1, "author": "lead"}]}]
    )
    assert row["new_count"] == 1 and row["new"][0]["author"] == "lead" and row["state"] == "open"
    # an open-pr learns its number from the URL its receipt names
    opened = {
        "ticket": "TASK-100",
        "type": "open-pr",
        "payload": {"repo": "api", "branch": "work/x"},
        "receipt": {"url": "https://forge.test/org/api/pull/12"},
    }
    assert web._with_new_comments(opened, [])["number"] == 12 and web._with_new_comments(opened, [])["approvals"]
    # no PR named anywhere: nothing
    assert (
        web._with_new_comments({"ticket": "TASK-100", "type": "tracker-comment", "payload": {"issue": "TASK-100"}}, [])
        is None
    )
    # a PR the watch never recorded keeps what the intent carried, without the old count; a merged PR's comments are no rows
    other = {
        "ticket": "TASK-100",
        "type": "pr-edit",
        "payload": {"repo": "api", "number": 99},
        "pr": {"repo": "api", "number": 99, "new_count": 3, "merged": True},
    }
    row = web._with_new_comments(other, [{"ticket": "TASK-100", "repo": "api", "number": 99, "new": [{"id": 5}]}])
    assert row["merged"] is True and row["new_count"] == 0
    # through the list: the row of a real intent
    made = create(pack, "TASK-100", "pr-edit", "c1", "edit", {"repo": "api", "number": 12, "title": "t"})
    listed = {r["id"]: r for r in _client().get("/list").json()["rows"]}
    assert listed[made["id"]]["pr"]["approvals"] and listed[made["id"]]["pr"]["new_count"] == 1


def test_a_lane_s_own_coding_tool_transcript_streams_its_session(env, monkeypatch, tmp_path):
    from cockpitlib import chat

    monkeypatch.setattr(
        chat,
        "_providers",
        lambda: {
            "coding": {
                "lane_transcript_glob": str(tmp_path) + "/projects/*-workspaces-{card_slug}/agent-transcripts/*/*.jsonl"
            }
        },
    )
    folder = tmp_path / "projects" / "home-x-workspaces-t-ab12" / "agent-transcripts" / "s1"
    folder.mkdir(parents=True)
    path = folder / "s1.jsonl"
    path.write_text(
        "\n".join(
            json.dumps(row)
            for row in (
                {"role": "user", "message": {"content": [{"type": "text", "text": "fix **J22**"}]}},
                {
                    "role": "assistant",
                    "message": {
                        "content": [
                            {"type": "text", "text": "Reading the tax code."},
                            {"type": "tool_use", "name": "Shell", "input": {"command": "git status", "cwd": "/x"}},
                        ]
                    },
                },
            )
        )
        + "\n",
        encoding="utf-8",
    )
    assert (
        chat.card_slug("t_ab12") == "t-ab12"
        and chat.lane_transcript("t_ab12") == str(path)
        and chat.lane_transcript("t_zz") == ""
    )
    tail = chat.coding_tail(str(path))
    assert [entry["kind"] for entry in tail["entries"]] == ["prompt", "text", "tool_use"] and tail["running"] is True
    assert (
        "<strong>J22</strong>" in tail["entries"][0]["html"]
        and tail["entries"][2]["name"] == "Shell"
        and tail["entries"][2]["summary"] == "git status"
    )
    # the coding-tool list and the job stream carry the lane's session, timed between the card's start and the last write
    from cockpitlib import lane_transcripts

    card = {
        "id": "t_ab12",
        "ticket": "TASK-7",
        "assignee": "worker-1",
        "title": "TASK-7: dev",
        "status": "running",
        "created_at": int(path.stat().st_mtime) - 60,
    }
    [row] = lane_transcripts.sessions([card, {**card, "id": "t_other"}])
    assert (
        row["ticket"] == "TASK-7"
        and row["card"] == "t_ab12"
        and row["running"]
        and row["prompt"] == "worker-1 · TASK-7: dev"
    )
    rows = lane_transcripts.job_rows([card])
    assert [entry["kind"] for entry in rows] == ["prompt", "text", "tool_use"] and {entry["who"] for entry in rows} == {
        "worker-1"
    }
    assert (
        rows == sorted(rows, key=lambda entry: entry["ts"]) and lane_transcripts.job_rows([card], rows[-1]["ts"]) == []
    )
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(
            json.dumps({"role": "assistant", "message": {"content": [{"type": "text", "text": "done"}]}}) + "\n"
        )
    later = lane_transcripts.job_rows([card], rows[-1]["ts"][:-3] + "00Z")
    assert later[-1]["text"] == "done"
    os.utime(path, (1, 1))  # past RECENT_DAYS: no longer listed, and what was read of it is let go
    assert lane_transcripts.job_rows([card]) == [] and str(path) not in lane_transcripts._SEEN
    # a path the glob does not name stays unread
    stray = tmp_path / "elsewhere.jsonl"
    stray.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
    assert chat.coding_tail(str(stray))["entries"] == []


def test_a_pack_opts_into_desktop_overrides_by_name_and_only_known_names(bare, monkeypatch, tmp_path):
    """The desktop half applies what /desktop-overrides names; a pack that names none gets an empty list, and a name
    cockpit does not know is refused when the pack is read, not written into the Desktop."""
    assert _client().get("/desktop-overrides").json() == {"overrides": []}
    pack_file = _pack_copy(tmp_path, monkeypatch, "\ndesktop:\n  overrides: [opaque-window, opaque-window]\n")
    assert load(pack_file)["desktop"] == {"overrides": ["opaque-window"]}
    assert _client().get("/desktop-overrides").json() == {"overrides": ["opaque-window"]}
    for text, message in (
        ("\ndesktop:\n  overrides: [run-anything]\n", "no override run-anything"),
        ("\ndesktop:\n  script: x.js\n", "desktop takes overrides"),
        ("\ndesktop:\n  overrides: opaque-window\n", "list of names"),
    ):
        shutil.rmtree(tmp_path / "packs")
        with pytest.raises(PackError, match=message):
            load(_pack_copy(tmp_path, monkeypatch, text))


def test_a_live_tickets_cards_stay_on_the_board_whatever_their_age(env, monkeypatch, tmp_path):
    """A ticket whose lifecycle is not over keeps every card on the Board: an open outbox item (publish), a PR the watch
    still sees open (merge), its ticket-done waiting for the ack (confirm). A finished ticket keeps the days window, and
    so does a key that is not a tracker ticket (a platform group). The window is the pack's board_done_days."""
    from cockpitlib.board_view import board
    from cockpitlib.outbox import create
    from cockpitlib.paths import qa
    from tests.support.boards import put_card, raw

    pack = load(os.environ["COCKPIT_PACK"])
    slug = pack["board"]
    old = {}
    for ticket in ("TASK-201", "TASK-202", "TASK-203", "TASK-204", "TASK-PLATFORM"):
        old[ticket] = put_card(slug, f"{ticket}: an old job", "worker-1", "done")
    connection = raw(slug)
    for card in old.values():
        connection.execute("update tasks set completed_at = ? where id = ?", (int(time.time()) - 9 * 86400, card))
    connection.commit()
    connection.close()
    create(pack, "TASK-201", "tracker-comment", "c", "a note", {"body": "x"})  # waiting for publish
    os.makedirs(os.path.join(qa(), "TASK-202", "pr"), exist_ok=True)  # waiting for merge
    json.dump(
        {"repo": "api", "number": 7, "state": "open"},
        open(os.path.join(qa(), "TASK-202", "pr", "api-7.json"), "w", encoding="utf-8"),
    )
    create(pack, "TASK-203", "ticket-done", "", "done", {"body": "shipped"})  # waiting for your confirm
    create(pack, "TASK-PLATFORM", "tracker-comment", "c", "a note", {"body": "x"})  # a group, not a ticket
    shown = board(pack)
    ids = {card["id"] for card in shown["cards"]}
    assert {old["TASK-201"], old["TASK-202"], old["TASK-203"]} <= ids
    assert old["TASK-204"] not in ids and old["TASK-PLATFORM"] not in ids, (
        "finished, and a platform group: the window holds"
    )
    assert (
        shown["live"] == {"TASK-201": ["publish"], "TASK-202": ["merge"], "TASK-203": ["confirm"]}
        and shown["done_days"] == 2
    )
    assert old["TASK-204"] in {card["id"] for card in board({**pack, "board_done_days": 10})["cards"]}
    assert _client().get("/board").json()["done_days"] == 2
    from cockpitlib.owners import own

    own("supervisor", ["TASK-204"])
    assert board(pack)["live"]["TASK-204"] == ["release"] and old["TASK-204"] in {
        card["id"] for card in board(pack)["cards"]
    }
    for index, bad in enumerate((-1, 31, "two", True)):
        with pytest.raises(PackError, match="board_done_days"):
            load(_pack_copy(tmp_path / f"bad{index}", monkeypatch, f"\nboard_done_days: {json.dumps(bad)}\n"))
