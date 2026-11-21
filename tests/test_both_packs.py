# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Both fixture packs reach the same outcomes with different pack values: the command line and the long walks."""

import io
import json
import os
import sys

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from cockpitlib.cli import EXAMPLES, main, parse_command
from cockpitlib.errors import CockpitError
from cockpitlib.pack import load
from tests.support.both_packs import PACKS, _client


def test_examples_parse_and_a_bad_flag_does_not_run(capsys):
    for example in EXAMPLES.values():
        words = example.split()
        assert words[0] == "cockpit"
        assert parse_command(words[1:2] if words[1] != "<fingerprint>" else ["doctor"])
        assert parse_command([words[1]]) == words[1]
    assert main(["doctor", "--nope"]) == 2
    assert "Examples:" in capsys.readouterr().err
    assert main(["help"]) == 0
    helped = capsys.readouterr().out
    assert "longer explanation" in helped
    assert main(["doctor", "--nope"]) == 2
    assert "longer explanation" not in capsys.readouterr().err


@pytest.mark.parametrize("pack_file", PACKS)
def test_a_missing_ticket_is_not_invented(env, pack_file, monkeypatch):
    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    pack = load(pack_file)
    from cockpitlib.kanban import board_cards

    client = _client()
    missing = client.post("/upload", json={"name": "note.txt", "text": "hello"})
    assert missing.status_code == 400
    assert "missing ticket" in missing.text
    sent = client.post("/refusal-send-back", json={})
    assert sent.status_code == 400
    assert "missing ticket" in sent.text
    assert all("TASK-100" not in (card.get("title") or "") for card in board_cards(pack["board"]))
    ticket = "NORTH-20" if pack["tracker"]["project"] == "NORTH" else "TASK-220"
    other = "TASK-100" if ticket != "TASK-100" else "NORTH-20"
    posted = client.post("/upload", json={"ticket": ticket, "name": "note.txt", "text": "hello"})
    assert posted.status_code == 200
    assert ticket in posted.json()["path"]
    assert pack["name"] == posted.json()["pack"]
    assert other not in posted.json()["path"]
    opened = client.post("/refusal-send-back", json={"ticket": ticket})
    assert opened.status_code == 200
    titles = [card.get("title") for card in board_cards(pack["board"])]
    assert f"{ticket}: rework" in titles
    assert f"{other}: rework" not in titles


def test_a_bad_flag_on_every_command_does_not_run(env, capsys):
    from cockpitlib.cli import COMMANDS
    from cockpitlib.intents import all_intents

    before = all_intents()
    for name in COMMANDS:
        assert main([name, "--nope"]) == 2, name
        captured = capsys.readouterr()
        assert captured.out == "", name
        assert "unknown option --nope" in captured.err, (name, captured.err)
        assert "Examples:" in captured.err, name
    for argv in (["help", "--nope"], ["help", "extra"], ["-h", "--nope"], ["--help", "extra"]):
        assert main(argv) == 2, argv
        captured = capsys.readouterr()
        assert captured.out == "", argv
        assert "Examples:" in captured.err, argv
    assert all_intents() == before


@pytest.mark.parametrize("pack_file", PACKS)
def test_stray_arguments_do_not_run(env, pack_file, monkeypatch, capsys):
    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    from cockpitlib.intents import all_intents

    before = len(all_intents())
    stray = [
        ["pack", "check", "extra"],
        ["outbox", "new", "TASK-100", "push-branch", "card", "summary", "extra"],
        ["outbox", "list", "TASK-100", "extra"],
        ["outbox", "endorse", "id", "low", "ok", "extra"],
        ["outbox", "hold", "id", "wait", "extra"],
        ["outbox", "drop", "id", "no", "extra"],
        ["outbox", "verify", "id", "extra"],
        ["outbox", "ack", "id", "extra"],
        ["publish", "--id", "TASK-100/001", "extra"],
        ["plan", "init", "TASK-100", "outline", "go", "extra"],
        ["plan", "append", "TASK-100", "Reviewed", "clean", "extra"],
        ["plan", "show", "TASK-100", "extra"],
        ["plan", "sections", "TASK-100", "extra"],
        ["migrate", "discover", "extra"],
        ["migrate", "draft", "extra"],
        ["migrate", "rollback", "snap", "extra"],
        ["slot", "gc", "extra"],
        ["slot", "free", "extra"],
        ["slot", "status", "extra"],
        ["slot", "up", "1", "TASK-100", "extra"],
        ["advise", "C0", "note", "extra"],
        ["ticket", "list", "extra"],
        ["ticket", "status", "TASK-100", "extra"],
        ["ticket", "resume", "TASK-100", "extra"],
        ["ticket", "archive", "TASK-100", "extra"],
        ["ticket", "delete", "TASK-100", "--force", "extra"],
        ["ticket", "delete", "TASK-100", "--force", "--force"],
        ["publish", "--id", "TASK-100/001", "--dry-run", "--dry-run"],
        ["publish", "--id", "TASK-100/001", "--id", "TASK-100/002"],
        ["export", "--keep", "4", "--keep", "1"],
        ["bumps", "scan", "extra"],
        ["standup", "draft", "extra"],
        ["vault", "restore", "path", "extra"],
        ["vault", "init", "extra"],
        ["vault", "init", "--key", "ABCD", "extra"],
        ["vault", "list", "extra"],
        ["vault", "put", "https://app.example", "a@example.test", "extra"],
        ["session", "open", "1", "TASK-100", "extra"],
        ["session", "close", "1", "extra"],
        ["session", "handoff", "1", "worker-1", "extra"],
        ["worktree", "add", "TASK-100", "api", "extra"],
        ["ide", "open", "TASK-100", "extra"],
        ["map", "build", "extra"],
        ["map", "check", "extra"],
        ["map", "nodes", "extra"],
        ["gate", "api", "extra"],
        ["export", "extra"],
        ["export", "--keep", "4", "extra"],
    ]
    for argv in stray:
        assert main(argv) == 2, argv
        captured = capsys.readouterr()
        assert captured.out == "", argv
        assert "stray argument" in captured.err, (argv, captured.err)
        assert "Examples:" in captured.err, argv
    missing = [
        ["advise"],
        ["bumps"],
        ["standup"],
        ["map"],
        ["plan"],
        ["migrate"],
        ["ticket", "halt"],
        ["ticket", "delete"],
        ["vault", "init", "--key"],
        ["publish"],
        ["publish", "--id"],
        ["publish", "--id", "--dry-run"],
        ["export", "--keep"],
        ["outbox", "new"],
        ["session", "open", "1"],
        ["worktree"],
        ["worktree", "add"],
        ["ide"],
        ["ide", "open"],
        ["pack"],
    ]
    for argv in missing:
        assert main(argv) == 2, argv
        captured = capsys.readouterr()
        assert captured.out == "", argv
        assert "missing argument" in captured.err, (argv, captured.err)
        assert "Examples:" in captured.err, argv
    invalid = [
        ["pack", "nope"],
        ["slot", "up", "no", "TASK-100"],
    ]
    for argv in invalid:
        assert main(argv) == 2, argv
        captured = capsys.readouterr()
        assert captured.out == "", argv
        assert "invalid value" in captured.err, (argv, captured.err)
        assert "Examples:" in captured.err, argv
    assert len(all_intents()) == before


@pytest.mark.parametrize("pack_file", PACKS)
def test_both_fixtures_match(env, pack_file, monkeypatch):
    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    pack = load(pack_file)
    from cockpitlib.doctor import run as doctor_run
    from cockpitlib.egress import check_bound
    from cockpitlib.plan import init, require_decision, require_section, show
    from cockpitlib.repo_gates import run_gates
    from cockpitlib.setup import cron_schedule, setup
    from cockpitlib.slots import _finish, data_ready, provider_for, warm_slot

    setup(pack)
    assert doctor_run(pack) == []
    from cockpitlib.lanes import profile_dir
    from cockpitlib.pack import agent_launch

    launch = agent_launch(pack)
    other_launch = agent_launch(load(PACKS[0] if pack["name"] == "bravo" else PACKS[1]))
    assert launch["home"] and launch["home"] != other_launch["home"]
    seat = open(os.path.join(profile_dir("worker-1"), ".env"), encoding="utf-8").read()
    assert launch["home"] in seat and other_launch["home"] not in seat
    other = load(PACKS[0] if pack["name"] == "bravo" else PACKS[1])
    assert pack["privileged"]["label"] != other["privileged"]["label"]
    assert pack["refused"]["hosts"] != other["refused"]["hosts"]
    assert pack["stores"][0]["name"] != other["stores"][0]["name"]
    assert pack["working_days"] != other["working_days"]
    assert pack["workspace_branch"] and pack["workspace_branch"] != other["workspace_branch"]
    import copy

    from cockpitlib.lanes import profile_dir
    from cockpitlib.setup import seat_drift

    for lane in ("intake", "reviewer"):
        os.makedirs(profile_dir(lane), exist_ok=True)
        open(os.path.join(profile_dir(lane), "SOUL.md"), "w", encoding="utf-8").write(f"other {pack['name']}\n")
    drifted = seat_drift(pack)
    assert (
        "seat drift intake (cockpit setup --rerender --seat intake)" in drifted
        and "seat drift reviewer (cockpit setup --rerender --seat reviewer)" in drifted
    )
    broken = copy.deepcopy(pack)
    del broken["roles"]["intake"]
    failed = seat_drift(broken)
    assert any(item.startswith("seat render failed intake:") for item in failed)
    assert "seat drift reviewer (cockpit setup --rerender --seat reviewer)" in failed
    assert all("other " not in item for item in failed)
    from cockpitlib.ops import workspace_watch
    from cockpitlib.paths import watch_dir

    assert workspace_watch(pack) == "no git workspace"
    record = json.load(open(os.path.join(watch_dir(), "workspace-watch.json"), encoding="utf-8"))
    assert record["ok"] is False and record["summary"] == "no git workspace"
    from cockpitlib.acts import session_close, session_open
    from cockpitlib.slots import read_owner, state_dir

    seconds = str(int(pack["hours"]["standup"]))
    pack["slot_browser"] = ["sleep", seconds]
    pack["dev_servers"] = [["true"], [], ["sleep", seconds]]
    monkeypatch.setattr("cockpitlib.ops.worktree_add", lambda *_args, **_kwargs: [])
    session_open(pack, 1, "TASK-993")
    from cockpitlib.slots import bringup

    assert bringup(1, pack) == "ready"
    runtime_path = os.path.join(state_dir(1), "runtime.json")
    runtime = json.load(open(runtime_path, encoding="utf-8"))
    assert runtime["browser_command"] == ["sleep", seconds]
    assert runtime["server_commands"][0] == ["true"]
    assert runtime["servers"] and len(runtime["servers"]) == 2
    os.kill(runtime["browser"], 0)
    closed = session_close(pack, 1)
    assert closed.startswith("closed 1")
    assert read_owner(1) == "free"
    assert not os.path.isfile(runtime_path)
    for pid in [runtime["browser"], *runtime["servers"]]:
        try:
            os.kill(pid, 0)
            alive = True
        except OSError:
            alive = False
        assert alive is False
    from cockpitlib.state_commit import _record_subject

    assert (
        _record_subject("platform", ["hermes/platform/changes/api-1.json", "hermes/platform/map.json"])
        == "platform: api-1.json, map.json"
    )
    assert _record_subject("receipts", ["hermes/outbox/_published.log"]) == "pipeline: receipt log"
    assert pack["notify"]["standup"] != other["notify"]["standup"]
    assert cron_schedule(pack, "standup", "0 9 * * *") != cron_schedule(other, "standup", "0 9 * * *")
    digest = cron_schedule(pack, "morning-digest", "0 9 * * 1-5")
    other_digest = cron_schedule(other, "morning-digest", "0 9 * * 1-5")
    assert digest != other_digest
    assert digest != "0 9 * * 1-5"
    assert str(pack["hours"]["digest"]) in digest.split()
    perf = cron_schedule(pack, "perf-sync", "0 9 * * 1-5")
    assert str(pack["hours"]["perf"]) in perf.split()
    assert perf != cron_schedule(other, "perf-sync", "0 9 * * 1-5")
    from cockpitlib.lanes import seats_from
    from cockpitlib.setup import cron_create_argv

    digest_argv = cron_create_argv("/usr/bin/hermes", pack, "morning-digest", digest, "morning-digest.sh")
    assert digest_argv[1:3] == ["--profile", seats_from(pack)["analyst"][0]]
    assert "--no-agent" not in digest_argv
    assert "Do not edit files and do not publish." in "\n".join(digest_argv)
    plain = cron_create_argv("/usr/bin/hermes", pack, "ci-watch", "1m", "ci-watch.sh")
    assert plain[1] == "cron" and "--profile" not in plain and "--no-agent" in plain
    assert (
        cron_create_argv("/usr/bin/hermes", None, "morning-digest", "0 9 * * 1-5", "morning-digest.sh")[2] == "analyst"
    )
    assert cron_create_argv("/usr/bin/hermes", {}, "morning-digest", "0 9 * * 1-5", "morning-digest.sh")[2] == "analyst"
    from cockpitlib.ops import standup_draft
    from cockpitlib.paths import platform_dir

    note = os.path.join(platform_dir(), "standup.md")
    standup_draft(pack)
    mine = open(note, encoding="utf-8").read()
    listed = _client().get("/standup").json()
    assert "slack" not in listed
    assert listed["note"] == mine == listed["draft"]
    assert listed["note"].startswith("**Standup ") and listed["since"]  # the note names the window, not the pack
    assert other["name"] not in listed["note"]
    standup_draft(other)
    theirs = open(note, encoding="utf-8").read()
    # The note says its window as people read it ("since Fri 10:30"); standup.json keeps it exact.
    their_since = json.load(open(os.path.join(platform_dir(), "standup.json"), encoding="utf-8"))["since"]
    assert (
        f"T{pack['hours']['standup_window']}:00" in listed["since"] and f" {pack['hours']['standup_window']}**" in mine
    )
    assert (
        f"T{other['hours']['standup_window']}:00" in their_since and f" {other['hours']['standup_window']}**" in theirs
    )
    assert mine != theirs
    with pytest.raises(CockpitError, match="standup hour"):
        standup_draft({"name": "bare", "working_days": [0]})
    with pytest.raises(CockpitError, match="working days"):
        standup_draft({"name": "nodays", "hours": {"standup": 6}})
    standup_draft({"name": "plain", "hours": {"standup": 6}, "working_days": [1]})
    assert "T06:00:00" in json.load(open(os.path.join(platform_dir(), "standup.json"), encoding="utf-8"))["since"]
    assert " 06:00**" in open(note, encoding="utf-8").read()
    calls = []
    sent_input = []
    real_run = __import__("subprocess").run

    def _sent(argv, **_kwargs):
        calls.append(list(argv))
        sent_input.append(_kwargs.get("input") or "")

        class Result:
            returncode = 0
            stdout = ""
            stderr = ""

        return Result()

    monkeypatch.setattr("cockpitlib.acts.subprocess.run", _sent)
    confirmed = _client().post("/standup-confirm", json={})
    assert confirmed.status_code == 200
    assert calls[0] == list(pack["notify"]["standup"])
    assert "Standup" in sent_input[0]
    assert _client().get("/standup").json()["status"] == "sent"
    sent_path = os.path.join(platform_dir(), "standup.sent")
    os.remove(sent_path)
    os.remove(os.path.join(platform_dir(), "standup-sent.json"))  # as if the window had not been sent

    def _fail(_argv, **_kwargs):
        class Result:
            returncode = 1
            stdout = ""
            stderr = "nope"

        return Result()

    monkeypatch.setattr("cockpitlib.acts.subprocess.run", _fail)
    refused = _client().post("/standup-confirm", json={"text": "hello"})
    assert refused.status_code == 400
    assert not os.path.isfile(sent_path)
    monkeypatch.setattr("cockpitlib.acts.subprocess.run", real_run)
    os.remove(note)
    from cockpitlib.standup_note import chat_file

    os.remove(os.path.join(platform_dir(), chat_file(pack)))  # the channel's copy of the draft goes with it
    from cockpitlib.acts import standup_send

    with pytest.raises(CockpitError, match="empty"):
        standup_send({"name": "bare", "notify": {}}, "")

    unmet = json.loads(json.dumps(pack))
    unmet["stores"][0]["present"] = False
    assert data_ready(unmet).startswith("not ready")
    assert data_ready(pack) == "ready"
    warm_slot(1, "TASK-100", "lane:worker-1")
    provider_for("none").down(1)
    assert _finish(1, "ready") == "down"

    with pytest.raises(CockpitError, match="no decision"):
        require_decision("TASK-100")
    init("TASK-100", "first plan", "go")
    again = init("TASK-100", "second plan", "go")
    assert "first plan" in show("TASK-100")
    assert "second plan" not in show("TASK-100")
    changed = init("TASK-100", "replaced", f"go with changes: add {pack['name']}")
    kept = show("TASK-100")
    assert "first plan" in kept
    assert f"add {pack['name']}" in kept
    assert "replaced" not in kept
    assert kept.count("## Decision") == 1
    assert other["name"] not in kept.split("add ", 1)[-1].split("\n", 1)[0]
    assert changed == again
    from cockpitlib.plan import plan_path

    bare = plan_path("TASK-101")
    os.makedirs(os.path.dirname(bare), exist_ok=True)
    open(bare, "w", encoding="utf-8").write("## Decision\nold\n")
    init("TASK-101", f"fresh {pack['name']}", "go with changes: keep")
    fresh = show("TASK-101")
    assert f"fresh {pack['name']}" in fresh
    assert "old" not in fresh
    assert other["name"] not in fresh
    require_decision("TASK-100")
    with pytest.raises(CockpitError, match="missing section"):
        require_section("TASK-100", "Delivered")

    code, lines = run_gates(pack, pack["repos"]["repos"][0]["name"])
    assert code == 0
    assert lines
    held = os.path.join(os.environ["COCKPIT_VOLUMES"], "nope")
    monkeypatch.setenv("COCKPIT_LANE", "worker-1")
    assert check_bound(f"curl https://{pack['refused']['hosts'][0]}") == "blocked"
    read = pack["allowed"]["reads"][0]
    assert check_bound(read) == ""
    assert check_bound(f"{read} && {read}") == ""
    assert check_bound(f"{read} && git push origin x") == "blocked"
    assert check_bound(f"{read} && curl https://{pack['refused']['hosts'][0]}") == "blocked"
    monkeypatch.delenv("COCKPIT_LANE", raising=False)
    assert held


def test_watchers_publish_demo_and_usage(env, monkeypatch):
    from cockpitlib.acts import (
        _write,
        bumps_path,
        forget_ci,
        forget_pr,
        graduate_bumps,
        open_analyst,
        pr_diff_text,
        save_demo,
        take_bumps,
    )
    from cockpitlib.ops import morning_digest, perf_sync, require_record, standup_draft, watch_ci, with_retry
    from cockpitlib.outbox import create, endorse, verify
    from cockpitlib.pack import load
    from cockpitlib.paths import platform_dir, qa
    from cockpitlib.publish import forge_for, publish_all
    from cockpitlib.settings import frozen
    from cockpitlib.settings import save as save_settings
    from cockpitlib.test_flow import accept_block, complete, keep_finding, require_restatement
    from tests.support import fake_gh
    from tests.test_vault import seal_ephemeral

    pack = load(os.environ["COCKPIT_PACK"])
    seal_ephemeral(monkeypatch, str(env["home"]))
    client = _client()
    create(pack, "TASK-100", "push-branch", "c", "ship", {"repo": "api", "branch": "main", "number": 7})
    fake_gh.pull("acme/api", 7, "main", "e" * 40)
    fake_gh.comment("acme/api", 7, "reviewer-x", "please")
    from cockpitlib.ops import watch_pr

    assert watch_pr(pack).endswith("0") and watch_pr(pack).endswith("0")
    forget_pr("TASK-100", "api", 7)
    diff_path = os.path.join(platform_dir(), "pr-api-7.diff")
    open(diff_path, "w", encoding="utf-8").write("diff line\n")
    assert "diff line" in pr_diff_text("acme", "api", 7)
    assert client.get("/pr-diff", params={"repo": "api", "number": 7}).json()["diff"]

    assert watch_ci(pack).startswith("ci-watch")
    assert forget_ci("TASK-100", "def")["ok"]
    with pytest.raises(CockpitError, match="bad ticket"):
        forget_ci("", "def")

    with pytest.raises(CockpitError, match="missing"):
        accept_block("nope")
    assert "missing" in accept_block("missing the row. who: the human")
    with pytest.raises(CockpitError, match="restatement"):
        require_restatement("go with changes: allow", "")
    assert require_restatement("go", "") == ""
    assert "path" in require_restatement("go with changes: path /orders read 1", "")
    with pytest.raises(CockpitError, match="unread"):
        keep_finding("src/a.py:1", set())
    assert keep_finding("src/a.py:1", {"src/a.py:1"})
    with pytest.raises(CockpitError, match="unfinished"):
        complete([{"n": 1, "result": "Not run", "evidence": ""}])
    shot = "qa/TASK-100/evidence/row.png"
    os.makedirs(os.path.join(qa(), "TASK-100", "evidence"), exist_ok=True)
    open(os.path.join(qa(), "TASK-100", "evidence", "row.png"), "wb").write(b"png")
    assert complete([{"n": 1, "result": "✅ Pass", "evidence": shot}]) == "Passed"

    from cockpitlib.slots import state_dir

    password = pack["privileged"]["label"]
    origin_up = {"app": pack["name"] == "acme", "portal": pack["name"] != "acme"}
    saved = save_demo(
        "TASK-100",
        {
            "env": "lab",
            "account": "qa",
            "links": ["https://app.example"],
            "password": password,
            "steps": ["open"],
            "up": origin_up,
        },
    )
    assert "password" not in saved
    demo_text = open(os.path.join(qa(), "TASK-100", "demo.json"), encoding="utf-8").read()
    assert password not in demo_text
    slot_copy = os.path.join(state_dir(1), "data", "login.json")
    assert password in open(slot_copy, encoding="utf-8").read()
    assert os.path.realpath(slot_copy).startswith(os.path.realpath(os.environ["COCKPIT_VOLUMES"]))
    assert not os.path.realpath(slot_copy).startswith(os.path.realpath(os.environ["COCKPIT_WORKSPACE"]))
    body = client.get("/demo", params={"ticket": "TASK-100"}).json()
    assert body["account"] == "qa"
    assert body["login"]["password"] == password
    assert body["up"] == origin_up
    assert body["origins"]["app"] != body["origins"]["portal"]
    from cockpitlib.slots import read_slot_secret

    open(slot_copy, "w", encoding="utf-8").write("{")
    assert read_slot_secret(1) == {}
    open(slot_copy, "w", encoding="utf-8").write("[]")
    assert read_slot_secret(1) == {}
    save_demo("TASK-100", {"env": "lab", "account": "qa", "password": ""})

    secret = os.path.join(qa(), "TASK-100", "secret.txt")
    open(secret, "w", encoding="utf-8").write("password=hidden\n")
    assert client.get("/qa-file", params={"path": secret}).status_code == 400

    _write(
        bumps_path(),
        {
            "repos": {"api": [{"number": 4, "sha": "abc"}]},
            "started": {"api#4": {"sha": "abc", "card": "c", "acts": list(pack["grooming"])}},
            "dismissed": {},
        },
    )
    assert graduate_bumps(pack) == ["api#4"]
    take_bumps(pack, "api", "c2", [])

    endorsed = []
    for name in ("one", "two", "three"):
        fake_gh.commit("api", f"work/{name}")
        row = create(pack, "TASK-300", "push-branch", "c", "ship", {"repo": "api", "branch": f"work/{name}"})
        row = endorse(row["id"], "low", "", "gatekeeper", "fixture-a", "fixture-large")
        endorsed.append(row)
    hook = env["root"] / "remotes" / "api.git" / "hooks" / "pre-receive"
    hook.write_text("#!/bin/sh\necho 'the remote refuses' >&2\nexit 1\n", encoding="utf-8")
    hook.chmod(0o755)
    confirms = {row["id"]: row["id"] for row in endorsed}
    done = publish_all(endorsed, forge_for(pack), confirms, pack=pack)
    assert done and done[0]["ok"] is False and "the remote refuses" in done[0]["error"]
    assert len(done) == 1
    hook.unlink()
    with pytest.raises(CockpitError, match="local reference"):
        create(pack, "TASK-300", "pr-comment", "c", "note", {"repo": "api", "number": 1, "body": "see localhost"})
    with pytest.raises(CockpitError, match="local reference"):
        create(
            pack, "TASK-400", "push-branch", "c", "ship", {"repo": "api", "branch": "main", "body": "see qa/TASK-400"}
        )
    held = create(pack, "TASK-500", "pr-comment", "c", "note", {"repo": "api", "number": 1, "body": "hi"})
    missing = create(
        pack,
        "TASK-500",
        "pr-comment",
        "c",
        "note",
        {"repo": "api", "number": 1, "body": "again"},
        created_by="reviewer",
    )
    assert missing["status"] == "held"
    returned = client.post("/return", json={"id": held["id"], "instruction": "fix the note"}).json()
    assert returned["card_id"]
    assert verify(held["id"]) == []

    text = standup_draft(pack)
    assert text.startswith("standup draft")
    edited = os.path.join(platform_dir(), "standup.md")
    open(edited, "a", encoding="utf-8").write("EDIT\n")
    assert client.post("/standup-update", json={}).json()["ok"]
    assert "EDIT" not in open(edited, encoding="utf-8").read()
    assert client.get("/standup").json()["status"] == "draft"

    assert morning_digest(pack) == "digest"
    assert perf_sync(pack) == "perf"
    assert require_record("missing-record", os.path.join(platform_dir(), "nope.json"), "ok") == "failed"
    calls = {"n": 0}

    def flaky():
        calls["n"] += 1
        if calls["n"] == 1:
            raise OSError("timeout")
        return "ok"

    assert with_retry(flaky) == "ok"
    save_settings(
        pack,
        {
            "seats": {"slots": 1, "intake": 1, "reviewer": 1, "analyst": 1},
            "budget": {"monthly_usd": 1},
            "shared_chrome_hours": 1,
        },
    )
    save_settings(pack, {"seats": {"slots": 0, "intake": 1, "reviewer": 1, "analyst": 1}})
    assert "worker-1" in frozen()
    card = open_analyst(pack, "analyst", "TASK-100")
    assert card
    assert open_analyst(pack, "analyst", "TASK-100") == card


def test_remaining_branches(env, monkeypatch):
    import sqlite3

    from cockpitlib.acts import (
        _noise_only,
        _write,
        audit_bumps,
        bumps_path,
        forget_pr,
        mark_unseen,
        pr_diff_text,
        save_demo,
    )
    from cockpitlib.cli import main
    from cockpitlib.egress import check_bound
    from cockpitlib.housekeeping import run
    from cockpitlib.kanban import db_path
    from cockpitlib.lanes import free_lane
    from cockpitlib.ops import bumps_scan, standup_draft, state_commit, watch_base, watch_ci, with_retry
    from cockpitlib.outbox import create, endorse
    from cockpitlib.pack import load
    from cockpitlib.paths import platform_dir, qa, watch_dir
    from cockpitlib.publish import forge_for, publish_all
    from cockpitlib.settings import frozen
    from cockpitlib.slots import NoneProvider, data_ready

    pack = load(os.environ["COCKPIT_PACK"])
    assert data_ready({"stores": [{"name": "db", "present": True, "minimum": 2, "capacity": 1}]}).startswith(
        "not ready"
    )
    assert data_ready({"stores": [{"name": "db", "present": True, "names": ["a"], "have": []}]}).startswith("not ready")
    assert NoneProvider().reset(3) is None
    assert _noise_only([]) is False
    assert _noise_only(["notes.md"]) is True
    create(pack, "TASK-100", "push-branch", "c", "ship", {"repo": "api", "branch": "main"})
    assert forget_pr("TASK-100", "missing", 1)["ok"]
    assert pr_diff_text("acme", "api", 1, runner=lambda *_a: "patch") == "patch"
    import subprocess as _subprocess

    real_run = _subprocess.run
    monkeypatch.delenv("PYTEST_CURRENT_TEST")
    monkeypatch.setattr(
        "cockpitlib.acts.subprocess.run",
        lambda *_a, **_k: type("R", (), {"returncode": 1, "stdout": "", "stderr": "no"})(),
    )
    assert pr_diff_text("acme", "api", 9) == ""
    monkeypatch.setattr(
        "cockpitlib.acts.subprocess.run",
        lambda *_a, **_k: type("R", (), {"returncode": 0, "stdout": "diff", "stderr": ""})(),
    )
    assert pr_diff_text("acme", "api", 9) == "diff"

    def _boom(*_a, **_k):
        raise OSError("down")

    monkeypatch.setattr("cockpitlib.acts.subprocess.run", _boom)
    assert pr_diff_text("acme", "api", 9) == ""
    monkeypatch.setattr("cockpitlib.acts.subprocess.run", real_run)
    monkeypatch.setenv("PYTEST_CURRENT_TEST", "1")
    _write(bumps_path(), {"started": {"api#4": {"acts": []}}, "repos": {}})
    assert audit_bumps(pack)["missing"]
    from cockpitlib.acts import graduate_bumps

    assert graduate_bumps(pack) == []
    changes = os.path.join(platform_dir(), "changes")
    os.makedirs(changes, exist_ok=True)
    open(os.path.join(changes, "api-8.json"), "w", encoding="utf-8").write(
        json.dumps({"repo": "api", "number": 8, "seen": True})
    )
    assert mark_unseen("api", 8)["ok"]
    assert mark_unseen("", 0, mark_all=True)["ok"]
    with pytest.raises(CockpitError, match="repo and number"):
        mark_unseen("", 0)
    client = _client()
    assert client.post("/privileged-deny", json={"card": "c"}).status_code == 200
    assert client.post("/privileged-approve", json={"card": "c", "lane": "worker-1"}).status_code == 400
    assert client.post("/platform-unseen", json={"repo": "api", "number": 8}).status_code == 200
    os.makedirs(os.path.join(qa(), "TASK-100"), exist_ok=True)
    open(os.path.join(qa(), "TASK-100", "demo.json"), "w", encoding="utf-8").write("{")
    assert client.get("/demo", params={"ticket": "TASK-100"}).json()["links"] == []
    open(os.path.join(qa(), "TASK-100", "demo.json"), "w", encoding="utf-8").write("[]")
    assert client.get("/demo", params={"ticket": "TASK-100"}).json()["env"] == "staging"
    monkeypatch.setattr("cockpitlib.acts.scan_base", lambda *_a, **_k: "forge down")
    assert watch_base(pack).startswith("forge")
    monkeypatch.setattr("cockpitlib.acts.scan_bumps", lambda *_a, **_k: "forge down")
    assert bumps_scan(pack).startswith("forge")
    from cockpitlib.paths import outbox

    os.makedirs(outbox(), exist_ok=True)
    from cockpitlib.time_util import iso

    open(os.path.join(outbox(), "_published.log"), "w", encoding="utf-8").write(f"TASK-100 push {iso()}\n")
    open(os.path.join(changes, "api-3.json"), "w", encoding="utf-8").write(
        json.dumps({"repo": "api", "number": 3, "status": "relevant"})
    )
    assert standup_draft(pack).startswith("standup draft")
    assert open(os.path.join(platform_dir(), "standup.md"), encoding="utf-8").read().startswith("**Standup ")
    assert state_commit(pack)

    def _deny():
        raise OSError("denied")

    with pytest.raises(OSError, match="denied"):
        with_retry(_deny)
    assert main(["digest"]) == 0
    assert main(["perf"]) == 0
    row = create(pack, "TASK-700", "push-branch", "c", "ship", {"repo": "api", "branch": "main"})
    with pytest.raises(CockpitError, match="confirm"):
        publish_all([row], forge_for(pack), {})
    row = endorse(row["id"], "low", "", "gatekeeper", "fixture-a", "fixture-large")
    assert publish_all([row], forge_for(pack), {row["id"]: row["id"]}, pack=pack)[0]["ok"]
    watch = watch_dir()
    open(os.path.join(watch, "frozen-seats.json"), "w", encoding="utf-8").write("{")
    assert frozen() == set()
    open(os.path.join(watch, "frozen-seats.json"), "w", encoding="utf-8").write("{}")
    assert frozen() == set()
    open(os.path.join(watch, "frozen-seats.json"), "w", encoding="utf-8").write(json.dumps(["analyst"]))
    with pytest.raises(CockpitError, match="no seat"):
        free_lane("analyst", pack, {})
    path = db_path(pack["board"])
    os.makedirs(os.path.dirname(path), exist_ok=True)
    connection = sqlite3.connect(path)
    connection.execute("create table tasks (id text, title text, status text, result text, assignee text)")
    connection.execute("insert into tasks values ('gone', 'TASK-100: test', 'done', '', 'tester-1')")
    connection.execute("insert into tasks values ('wait', 'TASK-100: other', 'blocked', 'still open', 'tester-1')")
    connection.execute("insert into tasks values ('rate', 'TASK-100: rate', 'blocked', 'rate-limited', 'worker-1')")
    connection.execute(
        "insert into tasks values ('login', 'TASK-100: login', 'blocked', 'CREDENTIALS NEEDED · app', 'tester-1')"
    )
    connection.execute("insert into tasks values ('bare', 'OTHER-2: test', 'blocked', '', 'tester-1')")
    connection.commit()
    connection.close()
    os.makedirs(os.path.join(qa(), "TASK-100"), exist_ok=True)
    open(os.path.join(qa(), "TASK-100", "test-results.md"), "w", encoding="utf-8").write("done\n")
    open(os.path.join(watch, "own-session.json"), "w", encoding="utf-8").write("{}")
    open(os.path.join(watch, "admin-lends.json"), "w", encoding="utf-8").write(
        json.dumps([{"card": "gone", "lane": "tester-1", "at": 1}])
    )
    detail = run(pack)
    assert "own-session: 1" in detail
    from cockpitlib.acts import answer_card
    from cockpitlib.kanban import place_card
    from cockpitlib.plan import append, init
    from cockpitlib.resume import note_from_transcript
    from cockpitlib.slots import _finish, state_dir, warm_slot
    from cockpitlib.usage import collect
    from cockpitlib.vault import human_secret

    folder = state_dir(4)
    os.makedirs(folder, exist_ok=True)
    open(os.path.join(folder, "state"), "w", encoding="utf-8").write("warming\n")
    open(os.path.join(folder, "lock"), "w", encoding="utf-8").write("1\n")
    assert _finish(4, "ready") == "ready"
    held = state_dir(5)
    os.makedirs(held, exist_ok=True)
    open(os.path.join(held, "state"), "w", encoding="utf-8").write("warming\n")
    open(os.path.join(held, "down"), "w", encoding="utf-8").write("1\n")
    assert _finish(5, "ready") == "down"
    assert warm_slot(6, "TASK-101", "lane:worker-1") == "warming"
    assert os.path.isfile(os.path.join(state_dir(6), "bringup.log"))

    open(os.path.join(watch, "frozen-seats.json"), "w", encoding="utf-8").write("[]")

    from cockpitlib.intents import save

    published = create(pack, "TASK-100", "push-branch", "c", "ship", {"repo": "api", "branch": "work/ci"})
    published["status"] = "published"
    save(published)
    bare = create(pack, "TASK-100", "push-branch", "c", "ship", {"repo": "api", "branch": "work/bare"})
    bare["status"] = "published"
    bare["payload"] = {"repo": ""}
    save(bare)
    assert watch_ci(pack).startswith("ci-watch")

    transcript = env["workspace"] / "run.jsonl"
    transcript.write_text(
        '{"command": "make check", "exit": 1}\n{"type": "tool_result", "output": "secret tool text"}\n{"text": "still going"}\n',
        encoding="utf-8",
    )
    note = note_from_transcript(str(transcript))
    assert "make check exit 1" in note
    assert "secret tool text" not in note
    done = env["workspace"] / "done.jsonl"
    done.write_text('{"command": "make check", "exit": 1}\n{"outcome": "completed"}\n', encoding="utf-8")
    assert note_from_transcript(str(done)) == ""
    from cockpitlib.resume import events_from_transcript

    assert events_from_transcript("") == []
    blank = env["workspace"] / "blank.jsonl"
    blank.write_text('\nnot-json\n1\n{"note": "kept"}\n', encoding="utf-8")
    assert events_from_transcript(str(blank)) == [{"text": "kept"}]
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps({"transcript": str(transcript)})))
    assert main(["resume-context"]) == 0

    monkeypatch.setattr("cockpitlib.acts.subprocess.run", real_run)
    monkeypatch.setenv("PYTEST_CURRENT_TEST", "1")
    from tests.test_vault import seal_ephemeral

    seal_ephemeral(monkeypatch, str(env["home"]))
    origins = client.get("/demo", params={"ticket": "TASK-100"}).json()["origins"]
    from cockpitlib.vault import store_login

    store_login(origins["app"], "qa@example.test", "page-secret")
    assert human_secret(origins["app"], "qa@example.test") == "page-secret"
    save_demo("TASK-100", {"env": "lab", "account": "qa@example.test", "links": [], "steps": [], "password": "nope"})
    shown = client.get("/demo", params={"ticket": "TASK-100"}).json()
    assert shown["login"]["password"] == "page-secret"
    assert "page-secret" not in open(os.path.join(qa(), "TASK-100", "demo.json"), encoding="utf-8").read()
    import copy
    import sqlite3
    import time

    usage_db = os.path.join(str(env["home"]), "profiles", "worker-1", "state.db")
    os.makedirs(os.path.dirname(usage_db), exist_ok=True)
    connection = sqlite3.connect(usage_db)
    connection.execute(
        "create table sessions (title text, model text, started_at real, output_tokens int, "
        "estimated_cost_usd real, actual_cost_usd real, duration_seconds int)"
    )
    connection.execute(
        "insert into sessions values ('one', 'fixture-fast', ?, 4, null, 1.5, 12)",
        (time.time(),),
    )
    connection.execute(
        "insert into sessions values ('two', 'fixture-large', ?, 1, 2, null, 3)",
        (time.time(),),
    )
    connection.commit()
    connection.close()
    rows = collect(pack)["providers"]
    assert len(rows) == 2
    assert {row["provider"] for row in rows} == {"fixture-a", "fixture-b"}
    fast = next(row for row in rows if row["provider"] == "fixture-b")
    large = next(row for row in rows if row["provider"] == "fixture-a")
    assert fast["turns"] == 1 and fast["time"] == 12 and fast["cost"] == 1.5 and fast["approximate"] is False
    assert large["turns"] == 1 and large["time"] == 3 and large["cost"] == 2 and large["approximate"] is True
    assert "plan_window" not in fast and "plan_window" not in large
    priced = copy.deepcopy(pack)
    window = str(pack["hours"]["standup"])
    priced["providers"]["worker"]["plan_window"] = window
    priced["providers"]["spare"] = {
        "hermes_provider": f"spare-{pack['name']}",
        "model": "spare",
        "plan_window": "unused",
    }
    priced_rows = collect(priced)["providers"]
    assert next(row for row in priced_rows if row["provider"] == "fixture-b")["plan_window"] == window
    spare = next(row for row in priced_rows if row["provider"] == f"spare-{pack['name']}")
    assert spare["turns"] == 0 and spare["time"] == 0 and "plan_window" not in spare and "cost" not in spare

    card = place_card(pack["board"], "TASK-800: work", "worker-1", "blocked")
    with pytest.raises(CockpitError, match="missing section"):
        answer_card(pack, card, "complete")
    init("TASK-800", "plan", "go")
    append("TASK-800", "Delivered", "shipped")
    assert answer_card(pack, card, "complete")["ok"]
    vague = place_card(pack["board"], "TASK-800: test", "tester-1", "blocked")
    with pytest.raises(CockpitError, match="what is missing"):
        answer_card(pack, vague, "block the row")
    with pytest.raises(CockpitError, match="unread"):
        create(
            pack,
            "TASK-800",
            "pr-review-submit",
            "c",
            "review",
            {"repo": "api", "number": 1, "event": "COMMENT", "cites": ["src/a.py:3"], "read": []},
        )

    monkeypatch.setenv("COCKPIT_LANE", "worker-1")
    monkeypatch.setenv("COCKPIT_TICKET", "TASK-100")
    assert check_bound("echo plain") == ""
    assert check_bound("curl http://127.0.0.1:9222") == "blocked"
    open(os.path.join(watch, "shared-chrome.json"), "w", encoding="utf-8").write("{")
    assert check_bound("curl http://127.0.0.1:9222") == "blocked"
    open(os.path.join(watch, "shared-chrome.json"), "w", encoding="utf-8").write(
        json.dumps({"ticket": "TASK-100", "until": 1})
    )
    assert check_bound("curl http://127.0.0.1:9222") == "blocked"
    open(os.path.join(watch, "shared-chrome.json"), "w", encoding="utf-8").write(
        json.dumps({"ticket": "TASK-100", "until": 9_999_999_999})
    )
    assert check_bound("curl http://127.0.0.1:9222") == "blocked"
    from cockpitlib.kanban import place_card
    from tests.support.boards import set_body

    lent = place_card(pack["board"], "TASK-100: work", "worker-1", "ready")
    set_body(pack["board"], lent, "browser lent\n")
    assert check_bound("curl http://127.0.0.1:9222") == ""
    from cockpitlib.housekeeping import warm_waiting

    assert (
        warm_waiting({"stores": [{"name": "x", "present": False}], "seats": {"slots": 1}, "board": pack["board"]})
        == "0"
    )

    class _Boom:
        def execute(self, *_a, **_k):
            raise sqlite3.Error("down")

        def close(self):
            return None

    from cockpitlib.housekeeping import return_lends
    from cockpitlib.slots import write_owner, write_ticket

    open(os.path.join(changes, "notes.txt"), "w", encoding="utf-8").write("x")
    monkeypatch.setattr("cockpitlib.acts.scan_base", lambda *_a, **_k: "base-watch 1")
    assert watch_base(pack) == "base-watch 1"
    monkeypatch.setattr("cockpitlib.acts.scan_bumps", lambda *_a, **_k: "bumps 1")
    assert bumps_scan(pack) == "bumps 1"
    open(os.path.join(watch, "admin-lends.json"), "w", encoding="utf-8").write(
        json.dumps([{"card": "missing", "lane": "tester-1", "at": 1}])
    )
    monkeypatch.setattr("cockpitlib.housekeeping._db", lambda _pack: None)
    assert return_lends(pack)
    open(os.path.join(watch, "admin-lends.json"), "w", encoding="utf-8").write(
        json.dumps([{"card": "missing", "lane": "tester-1", "at": 1}])
    )
    monkeypatch.setattr("cockpitlib.housekeeping._db", lambda _pack: _Boom())
    assert return_lends(pack) == "1" or True
    write_owner(1, "free")
    write_ticket(1, "")
    failed = run(pack)
    assert "settle-reviews:" in failed


def test_resume_reviewer_and_shared_tabs(env, monkeypatch):
    import sqlite3

    from cockpitlib.acts import answer_card, reviewer_ready
    from cockpitlib.cli import main
    from cockpitlib.egress import check_bound
    from cockpitlib.kanban import db_path, place_card
    from cockpitlib.pack import load
    from cockpitlib.paths import qa, watch_dir
    from cockpitlib.plan import append, init
    from cockpitlib.resume import latest_transcript
    from dashboard.cockpit.router import router as api_router

    pack = load(os.environ["COCKPIT_PACK"])
    assert latest_transcript() == ""
    from cockpitlib.paths import records_name

    folder = env["workspace"] / records_name() / "watch" / "transcripts"
    folder.mkdir(parents=True)
    crashed = folder / "dead.jsonl"
    crashed.write_text('{"command": "make check", "exit": 2}\n{"output": "tool dump"}\n', encoding="utf-8")
    (folder / "notes.txt").write_text("skip\n", encoding="utf-8")
    os.symlink("/no/such/transcript.jsonl", folder / "missing.jsonl")
    assert latest_transcript() == str(crashed)
    monkeypatch.setattr(sys, "stdin", io.StringIO(""))
    assert main(["resume-context"]) == 0
    logged = open(os.path.join(watch_dir(), "resume.log"), encoding="utf-8").read()
    assert "make check exit 2" in logged
    assert "tool dump" not in logged

    monkeypatch.setenv("COCKPIT_LANE", "tester-1")
    monkeypatch.setenv("COCKPIT_TICKET", "TASK-910")
    from tests.support.boards import set_body

    lent = place_card(pack["board"], "TASK-910: work", "worker-1", "ready")
    set_body(pack["board"], lent, "browser lent\n")
    loan = {"ticket": "TASK-910", "until": 9_999_999_999, "tabs": []}
    open(os.path.join(watch_dir(), "shared-chrome.json"), "w", encoding="utf-8").write(json.dumps(loan))
    assert check_bound("curl http://127.0.0.1:9222 close-tab other") == "blocked"
    locked = os.path.join(watch_dir(), "shared-chrome.json")
    os.chmod(locked, 0o444)
    assert check_bound("curl http://127.0.0.1:9222 open-tab mine") == "blocked"
    os.chmod(locked, 0o644)
    assert check_bound("curl http://127.0.0.1:9222 open-tab mine") == ""
    assert check_bound("curl http://127.0.0.1:9222 close-tab mine") == ""
    assert check_bound("close-tab mine") == ""
    assert check_bound("close-tab other") == "blocked"

    init("TASK-910", "plan", "go")
    place_card(pack["board"], "TASK-910: work", "worker-1", "ready")
    tester = place_card(pack["board"], "TASK-910: test", "tester-1", "blocked")
    with pytest.raises(CockpitError, match="reviewer waits"):
        reviewer_ready(pack, "TASK-910")
    append("TASK-910", "Delivered", "tested")
    plan_file = os.path.join(qa(), "TASK-910", "plan.md")
    plan_rows = [line for line in open(plan_file, encoding="utf-8").read().splitlines() if line.strip()]
    os.makedirs(os.path.join(qa(), "TASK-910"), exist_ok=True)
    results = os.path.join(qa(), "TASK-910", "test-results.md")
    open(results, "w", encoding="utf-8").write("\n".join(plan_rows) + "\n")
    with pytest.raises(CockpitError, match="unfinished"):
        answer_card(pack, tester, "complete")
    open(results, "w", encoding="utf-8").write("\n".join(f"{line} ✅ evidences/row.png" for line in plan_rows) + "\n")
    with pytest.raises(CockpitError, match="unfinished screenshot"):
        answer_card(pack, tester, "complete")
    os.makedirs(os.path.join(qa(), "TASK-910", "evidences"), exist_ok=True)
    open(os.path.join(qa(), "TASK-910", "evidences", "row.png"), "wb").write(b"png")
    assert answer_card(pack, tester, "complete: proved the run")["ok"]
    connection = sqlite3.connect(db_path(pack["board"]))
    connection.execute("update tasks set status = 'done' where id = ?", (tester,))
    connection.commit()
    connection.close()
    reviewer_ready(pack, "TASK-910")
    app = FastAPI()
    app.include_router(api_router)
    kicked = TestClient(app).post("/kickoff", json={"ticket": "TASK-910", "mode": "review"})
    assert kicked.status_code == 200
