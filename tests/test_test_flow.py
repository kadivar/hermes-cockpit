# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The test flow: the gate's runs, the manual plan and its evidence, reruns, and what a failure opens."""

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
from tests.support.both_packs import PACKS, _client, _other


@pytest.mark.parametrize("pack_file", PACKS)
def test_the_manual_plan_remembers_settings_that_already_existed(env, pack_file, monkeypatch):
    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    pack = load(pack_file)
    other = load(PACKS[0] if pack["name"] == "bravo" else PACKS[1])
    assert pack["name"] != other["name"]
    from cockpitlib.acts import start_manual_plan
    from cockpitlib.paths import qa

    def remembered(ticket: str):
        return json.loads(open(os.path.join(qa(), ticket, "settings-before.json"), encoding="utf-8").read())

    start_manual_plan(pack, "TASK-1027")
    assert remembered("TASK-1027") == {}
    folder = os.path.join(qa(), "TASK-1028")
    os.makedirs(folder, exist_ok=True)
    open(os.path.join(folder, "settings.json"), "w", encoding="utf-8").write(json.dumps({"theme": pack["name"]}))
    start_manual_plan(pack, "TASK-1028")
    assert remembered("TASK-1028") == {"theme": pack["name"]}
    assert other["name"] not in json.dumps(remembered("TASK-1028"))
    open(os.path.join(folder, "settings.json"), "w", encoding="utf-8").write("[]")
    start_manual_plan(pack, "TASK-1028")
    assert remembered("TASK-1028") == {}
    open(os.path.join(folder, "settings.json"), "w", encoding="utf-8").write("{")
    start_manual_plan(pack, "TASK-1028")
    assert remembered("TASK-1028") == {}


@pytest.mark.parametrize("pack_file", PACKS)
def test_a_fail_has_one_recording(env, pack_file):
    pack = load(pack_file)
    other = load(PACKS[0] if pack["name"] == "bravo" else PACKS[1])
    assert pack["name"] != other["name"]
    from cockpitlib.acts import answer_card, record_fail
    from cockpitlib.kanban import place_card
    from cockpitlib.paths import qa
    from cockpitlib.plan import append, init, plan_path

    ticket = "TASK-8942"
    folder = os.path.join(qa(), ticket)
    os.makedirs(folder, exist_ok=True)
    init(ticket, f"check {pack['name']}", "go")
    append(ticket, "Delivered", "tested")
    plan = open(plan_path(ticket), encoding="utf-8").read()
    open(os.path.join(folder, "test-results.md"), "w", encoding="utf-8").write(f"1 ❌ evidences/fail.png\n{plan}")
    card = place_card(pack["board"], f"{ticket}: test", "tester-1", "blocked")
    with pytest.raises(CockpitError, match="one recording"):
        answer_card(pack, card, "complete")
    recordings = os.path.join(folder, "recordings")
    os.makedirs(recordings, exist_ok=True)
    open(os.path.join(recordings, "1.txt"), "w", encoding="utf-8").write("first\n")
    open(os.path.join(recordings, "1-extra.txt"), "w", encoding="utf-8").write("second\n")
    with pytest.raises(CockpitError, match="one recording"):
        answer_card(pack, card, "complete")
    saved = record_fail(ticket, 1, f"the failure for {pack['name']}")
    assert saved["recordings"] == 1
    with pytest.raises(CockpitError, match="unfinished screenshot"):
        answer_card(pack, card, "complete")
    os.makedirs(os.path.join(folder, "evidences"), exist_ok=True)
    open(os.path.join(folder, "evidences", "fail.png"), "wb").write(pack["name"].encode())
    assert answer_card(pack, card, f"complete: proved {pack['name']}")["ok"]
    assert other["name"] not in open(os.path.join(folder, "evidences", "fail.png"), "rb").read().decode()
    assert other["name"] not in open(saved["path"], encoding="utf-8").read()


def test_red_gate_plain_go_and_missing_argument(env, monkeypatch, capsys):
    from cockpitlib.acts import answer_card
    from cockpitlib.intents import all_intents
    from cockpitlib.kanban import open_same, place_card
    from cockpitlib.pack import load
    from cockpitlib.plan import init
    from cockpitlib.test_flow import plain_go
    from dashboard.cockpit.router import router as api_router

    pack = load(os.environ["COCKPIT_PACK"])
    init("TASK-930", "plan", "go")
    app = FastAPI()
    app.include_router(api_router)
    client = TestClient(app)
    from cockpitlib.slots import write_owner, write_ticket

    write_owner(1, "human")
    write_ticket(1, "TASK-930")
    held = client.post("/kickoff", json={"ticket": "TASK-930", "mode": "test"})
    assert held.status_code == 409 and "manual session" in held.text
    assert open_same(pack["board"], "TASK-930: test") == ""
    write_owner(1, "free")
    write_ticket(1, "")
    open(os.path.join(os.environ["COCKPIT_VOLUMES"], "slot-1", "state"), "w", encoding="utf-8").write("warming\n")
    warming = client.post("/kickoff", json={"ticket": "TASK-930", "mode": "test"})
    assert warming.status_code == 409 and "still warming" in warming.text
    os.remove(os.path.join(os.environ["COCKPIT_VOLUMES"], "slot-1", "state"))
    write_owner(1, "lane:worker-1")
    write_ticket(1, "TASK-1")
    bound = client.post("/kickoff", json={"ticket": "TASK-930", "mode": "test"})
    assert bound.status_code == 409 and "bound to" in bound.text
    write_owner(1, "free")
    write_ticket(1, "")
    from cockpitlib.slots import tester_slot

    with pytest.raises(CockpitError, match="not ready"):
        tester_slot({"stores": [{"name": "db", "present": False}]}, "TASK-930")
    monkeypatch.setattr("cockpitlib.repo_gates.run_gates", lambda *_a, **_k: (1, ["api: failed true"]))
    red = client.post("/kickoff", json={"ticket": "TASK-930", "mode": "test"})
    assert red.status_code == 409
    assert "gate is red" in red.text
    assert open_same(pack["board"], "TASK-930: test") == ""
    monkeypatch.setattr("cockpitlib.repo_gates.run_gates", lambda *_a, **_k: (0, ["api: ok true"]))
    assert client.post("/kickoff", json={"ticket": "TASK-930", "mode": "test"}).status_code == 200

    card = place_card(pack["board"], "TASK-930: test run", "tester-1", "blocked")
    assert plain_go("go with changes: rerun") is False
    changed = answer_card(pack, card, "go with changes: rerun")
    assert changed["published"] == ""
    assert not any(row["type"] == "ticket-done" for row in all_intents("TASK-930"))
    # the card is no longer blocked; park another one for the plain go
    again = place_card(pack["board"], "TASK-930: test pass", "tester-1", "blocked")
    gone = answer_card(pack, again, "go")
    assert gone["published"]
    assert any(row["type"] == "ticket-done" and row["ticket"] == "TASK-930" for row in all_intents())
    assert main(["ticket"]) == 2
    err = capsys.readouterr().err
    assert "missing argument" in err and "Examples:" in err


def test_test_kickoff_stops_and_stray_arguments(env, monkeypatch, capsys):
    from cockpitlib.acts import answer_card, open_test_rows, post_test_plan, run_listed
    from cockpitlib.kanban import board_cards
    from cockpitlib.pack import load
    from cockpitlib.paths import qa
    from cockpitlib.plan import init
    from cockpitlib.test_flow import rerun_rows
    from dashboard.cockpit.router import router as api_router

    pack = load(os.environ["COCKPIT_PACK"])
    with pytest.raises(CockpitError, match="local reference"):
        post_test_plan(pack, "TASK-940", "see qa/local")
    posted = post_test_plan(pack, "TASK-940", "create user ada\n")
    assert posted["blocked"] is True
    cards = board_cards(pack["board"])
    assert any(card["id"] == posted["card"] and card["status"] == "blocked" for card in cards)
    with pytest.raises(CockpitError, match="not accepted"):
        run_listed("TASK-940", "create user ada")
    answer_card(pack, posted["card"], "go")
    with pytest.raises(CockpitError, match="refused"):
        run_listed("TASK-940", "delete the user")
    with pytest.raises(CockpitError, match="does not list"):
        run_listed("TASK-940", "create user bob")
    assert run_listed("TASK-940", "create user ada") == "create user ada"
    assert rerun_rows("go with changes: rerun 2, 4") == ["2", "4"]
    from cockpitlib.acts import handover_human_rows
    from cockpitlib.slots import state_dir

    os.makedirs(state_dir(1), exist_ok=True)
    open(os.path.join(state_dir(1), "login.json"), "w", encoding="utf-8").write("{}\n")
    handed = handover_human_rows(
        "TASK-940",
        [
            {"n": 1},
            {"n": 2, "human": True, "links": ["https://app.example/row"], "steps": ["sign in", "read the total"]},
            {"n": 3},
        ],
    )
    assert handed["logged_out"] is True
    assert [row["n"] for row in handed["rows"]] == [1, 3, 2]
    assert handed["rows"][-1]["human"] is True
    assert handed["rows"][-1]["logged_out"] is True
    assert handed["rows"][-1]["links"] == ["https://app.example/row"]
    assert not os.path.isfile(os.path.join(state_dir(1), "login.json"))
    from cockpitlib.acts import record_fail

    with pytest.raises(CockpitError, match="one recording"):
        record_fail("TASK-940", 2, "  ")
    first = record_fail("TASK-940", 2, "first take")
    second = record_fail("TASK-940", 2, "the failure")
    assert first["recordings"] == 1 and second["recordings"] == 1
    assert open(second["path"], encoding="utf-8").read().strip() == "the failure"
    extra = os.path.join(os.path.dirname(second["path"]), "2-extra.txt")
    open(extra, "w", encoding="utf-8").write("extra\n")
    assert record_fail("TASK-940", 2, "only this")["recordings"] == 1
    assert not os.path.isfile(extra)
    from cockpitlib.acts import cleanup_settings, keep_created, snapshot_settings

    with pytest.raises(CockpitError, match="needs a name"):
        keep_created("TASK-940", "  ", {"id": 1})
    created = keep_created("TASK-940", "ada the account", {"id": 1})
    assert created["name"] == "ada the account"
    snapshot_settings("TASK-940", {"theme": "light"})
    restored = cleanup_settings("TASK-940")
    assert restored == {"theme": "light"}
    assert "newflag" not in restored
    assert os.path.isfile(created["path"])
    assert cleanup_settings("TASK-941") == {}
    from cockpitlib.acts import _require_test_table, missing_plan_rows

    assert missing_plan_rows("TASK-941") == []
    plan = os.path.join(qa(), "TASK-940", "test-kickoff.md")
    os.makedirs(os.path.dirname(plan), exist_ok=True)
    open(plan, "w", encoding="utf-8").write("create user ada\nopen the report\n")
    open(os.path.join(qa(), "TASK-940", "test-results.md"), "w", encoding="utf-8").write("1 ✅ evidences/a.png\n")
    with pytest.raises(CockpitError, match="missing plan row 1,2"):
        _require_test_table("TASK-940")
    open(os.path.join(qa(), "TASK-940", "test-results.md"), "w", encoding="utf-8").write(
        "create user ada ✅ evidences/a.png\nopen the report ✅ evidences/b.png\n"
    )
    with pytest.raises(CockpitError, match="unfinished screenshot"):
        _require_test_table("TASK-940")
    os.makedirs(os.path.join(qa(), "TASK-940", "evidences"), exist_ok=True)
    for name in ("a.png", "b.png"):
        open(os.path.join(qa(), "TASK-940", "evidences", name), "wb").write(b"png")
    _require_test_table("TASK-940")
    assert rerun_rows("go") == []
    folder = os.path.join(qa(), "TASK-940")
    os.makedirs(folder, exist_ok=True)
    open(os.path.join(folder, "test-results.md"), "w", encoding="utf-8").write("1 Not run\n")
    with pytest.raises(CockpitError, match="open rows"):
        open_test_rows("TASK-940")
    init("TASK-940", "body", "go")
    app = FastAPI()
    app.include_router(api_router)
    refused = TestClient(app).post("/kickoff", json={"ticket": "TASK-940", "mode": "review"})
    assert refused.status_code == 409
    assert main(["doctor", "extra"]) == 2
    stray = capsys.readouterr().err
    assert "stray argument" in stray and "Examples:" in stray
    assert main(["export", "--keep", "no"]) == 2
    invalid = capsys.readouterr().err
    assert "invalid value" in invalid and "Examples:" in invalid
    for name in ("outbox", "plan", "migrate", "slot", "bumps", "standup", "vault", "session", "worktree", "ide", "map"):
        assert main([name, "nope"]) == 2
        assert "Examples:" in capsys.readouterr().err
    for argv in (
        ["plan", "init"],
        ["plan", "append", "T"],
        ["plan", "show"],
        ["plan", "sections"],
        ["migrate", "rollback"],
        ["slot", "up", "no"],
    ):
        assert main(argv) == 2
        assert "Examples:" in capsys.readouterr().err


@pytest.mark.parametrize("pack_file", PACKS)
def test_created_test_data_is_named_on_the_pack_origin(env, pack_file, monkeypatch):
    import yaml

    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    pack = load(pack_file)
    other = load(PACKS[0] if pack["name"] == "bravo" else PACKS[1])
    assert pack["name"] != other["name"]
    origin = str(
        yaml.safe_load(open(os.path.join(pack["_dir"], "staging.yaml"), encoding="utf-8"))["origins"]["app"]
    ).rstrip("/")
    other_origin = str(
        yaml.safe_load(open(os.path.join(other["_dir"], "staging.yaml"), encoding="utf-8"))["origins"]["app"]
    ).rstrip("/")
    assert origin != other_origin
    ticket = f"{pack['tracker']['project']}-1035"
    assert _client().post("/created", json={"name": f"ada {pack['name']}"}).status_code == 400
    assert _client().post("/created", json={"ticket": ticket, "name": "  "}).status_code == 400
    posted = _client().post("/created", json={"ticket": ticket, "name": f"ada {pack['name']}", "body": {"id": 1}})
    assert posted.status_code == 200
    body = posted.json()
    assert body["link"] == f"{origin}/data/ada-{pack['name']}"
    assert other_origin not in body["link"]
    assert other["name"] not in json.dumps(body)
    from cockpitlib.paths import qa

    text = open(os.path.join(qa(), ticket, "created", f"ada-{pack['name']}.json"), encoding="utf-8").read()
    assert body["link"] in text
    assert other["name"] not in text


@pytest.mark.parametrize("pack_file", PACKS)
def test_a_scripted_write_runs_only_the_accepted_line(env, pack_file, monkeypatch):
    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    pack = load(pack_file)
    other = load(PACKS[0] if pack["name"] == "bravo" else PACKS[1])
    assert pack["name"] != other["name"]
    from cockpitlib.paths import qa

    ticket = f"{pack['tracker']['project']}-1036"
    listed = f"create user {pack['name']}"
    assert _client().post("/scripted", json={"request": listed}).status_code == 400
    refused = _client().post("/scripted", json={"ticket": ticket, "request": listed})
    assert refused.status_code == 400
    assert "not accepted" in refused.text
    folder = os.path.join(qa(), ticket)
    os.makedirs(folder, exist_ok=True)
    open(os.path.join(folder, "test-kickoff.md"), "w", encoding="utf-8").write(listed + "\n")
    open(os.path.join(folder, "plan-accepted.json"), "w", encoding="utf-8").write("{}\n")
    posted = _client().post("/scripted", json={"ticket": ticket, "request": listed})
    assert posted.status_code == 200
    assert posted.json()["request"] == listed
    assert other["name"] not in posted.text
    deleted = _client().post("/scripted", json={"ticket": ticket, "request": "delete the user"})
    assert deleted.status_code == 400
    assert "delete" in deleted.text
    foreign = _client().post("/scripted", json={"ticket": ticket, "request": f"create user {other['name']}"})
    assert foreign.status_code == 400
    assert "does not list" in foreign.text


@pytest.mark.parametrize("pack_file", PACKS)
def test_a_rerun_runs_only_the_named_rows(env, pack_file, monkeypatch):
    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    pack = load(pack_file)
    other = load(PACKS[0] if pack["name"] == "bravo" else PACKS[1])
    assert pack["name"] != other["name"]
    from cockpitlib.acts import answer_card
    from cockpitlib.intents import all_intents
    from cockpitlib.kanban import place_card
    from cockpitlib.paths import qa

    ticket = "TASK-1015"
    folder = os.path.join(qa(), ticket)
    os.makedirs(folder, exist_ok=True)
    open(os.path.join(folder, "test-results.md"), "w", encoding="utf-8").write(
        "1 ✅ evidences/a.png\n2 ❌ evidences/b.png\n3 ✅ evidences/c.png\n4 ❌ evidences/d.png\n12 ✅ evidences/e.png\n"
    )
    card = place_card(pack["board"], f"{ticket}: test", "tester-1", "blocked")
    answered = answer_card(pack, card, "go with changes: rerun 2, 4")
    assert answered["published"] == ""
    assert answered["rerun"] == ["2", "4"]
    recorded = json.load(open(os.path.join(qa(), ticket, "rerun.json"), encoding="utf-8"))
    assert recorded["rows"] == ["2", "4"]
    assert recorded["pack"] == pack["name"]
    assert "1" not in recorded["rows"] and "3" not in recorded["rows"]
    results = open(os.path.join(qa(), ticket, "test-results.md"), encoding="utf-8").read()
    assert "2 Not run" in results and "4 Not run" in results
    assert "1 ✅ evidences/a.png" in results and "3 ✅ evidences/c.png" in results
    assert "12 ✅ evidences/e.png" in results
    assert "2 ❌" not in results and "4 ❌" not in results
    assert other["name"] != recorded["pack"]
    os.remove(os.path.join(qa(), ticket, "test-results.md"))
    empty = place_card(pack["board"], f"{ticket}: test empty", "tester-1", "blocked")
    assert answer_card(pack, empty, "go with changes: rerun 9")["rerun"] == ["9"]
    assert not any(item.get("type") == "ticket-done" for item in all_intents(ticket))
    again = place_card(pack["board"], f"{ticket}: test again", "tester-1", "blocked")
    finished = answer_card(pack, again, "go")
    assert finished["rerun"] == []
    assert finished["published"]
    assert any(item["id"] == finished["published"] and item["type"] == "ticket-done" for item in all_intents(ticket))


# How each fixture's test output names a failing test, matching its repos.yaml failures pattern.
FAILURE_LINES = {"acme": "FAIL {name}", "bravo": "not ok 1 - {name}"}


@pytest.mark.parametrize("pack_file", PACKS)
def test_the_gate_logs_each_run_names_new_failures_and_runs_once_per_ticket(env, pack_file, monkeypatch, capsys):
    import shlex
    import subprocess
    import time

    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    pack = load(pack_file)
    say = FAILURE_LINES[pack["name"]]
    other = FAILURE_LINES["bravo" if pack["name"] == "acme" else "acme"]
    from cockpitlib.acts import halt_ticket
    from cockpitlib.paths import workspace, wt
    from cockpitlib.repo_gates import _gate_folder, _outside, gates_dir, run_gates, start_background, wait

    repo = dict(pack["repos"]["repos"][0])
    ticket = f"{pack['tracker']['project']}-180"
    monkeypatch.setenv("COCKPIT_TICKET", ticket)
    checkout = os.path.join(wt(), ticket, repo["name"])
    os.makedirs(checkout)

    def shaped(*commands):
        return {**pack, "repos": {"repos": [dict(repo, gates=list(commands))]}}

    # It runs in the ticket's checkout and keeps a log per run.
    code, lines = run_gates(shaped("pwd"), repo["name"])
    assert code == 0 and os.path.realpath(lines[0].split("—", 1)[1].strip()) == os.path.realpath(checkout)
    assert lines[-1].startswith(f"log: {gates_dir(ticket)}") and os.path.isfile(lines[-1][5:])
    assert _gate_folder(pack, repo, "") == workspace()

    # The baseline hides what already fails on this slot; a new failure is listed; the exit code is the gate's own.
    known = say.format(name="Known.one")
    assert (
        run_gates(shaped(f"printf '%s\\n' {shlex.quote(known)}; exit 4"), record_baseline=True)[1][1]
        == "baseline: 1 known failures"
    )
    fresh = say.format(name=f"New.{pack['name']}")
    code, lines = run_gates(shaped(f"printf '%s\\n%s\\n' {shlex.quote(known)} {shlex.quote(fresh)}; exit 5"))
    assert code == 5 and f"new failure: New.{pack['name']}" in lines and "new failure: Known.one" not in lines
    code, lines = run_gates(shaped(f"printf '%s\\n' {shlex.quote(other.format(name='Other.style'))}; exit 1"))
    assert code == 1 and not any(line.startswith("new failure") for line in lines)
    assert run_gates(shaped("false | true"))[0] == 1

    # A gate command already running in this ticket's checkout blocks the next run; the same command elsewhere does not.
    slow = f"sleep 30; echo {pack['name']}"
    held = subprocess.Popen(["bash", "-c", slow], cwd=checkout)
    stray = subprocess.Popen(["bash", "-c", "true; sleep 30"], cwd=str(env["root"]))
    try:
        deadline = time.time() + 3
        while time.time() < deadline and not _outside(slow, [checkout]):
            time.sleep(0.05)
        assert run_gates(shaped(slow)) == (1, ["gate already running"])
        assert _outside("true; sleep 30", [checkout]) is False
    finally:
        for proc in (held, stray):
            proc.kill()
            proc.wait(timeout=5)

    # In the background (a process that loads the pack from disk): an id at once, --wait collects it, a second start
    # is refused, and halt reclaims it.
    import shutil

    import yaml

    copied = env["root"] / "packs" / pack["name"]
    shutil.copytree(os.path.dirname(pack_file), copied)

    def on_disk(command):
        data = yaml.safe_load((copied / "repos.yaml").read_text(encoding="utf-8"))
        data["repos"][0]["gates"] = [command]
        (copied / "repos.yaml").write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
        monkeypatch.setenv("COCKPIT_PACK", str(copied / "pack.yaml"))
        return load(str(copied / "pack.yaml"))

    run_id = start_background(on_disk(f"sleep 0.3; printf '%s\\n' {shlex.quote(fresh)}; exit 6"))
    assert run_id and start_background(shaped("true")) == ""
    code, lines = wait(run_id)
    assert code == 6 and f"new failure: New.{pack['name']}" in lines
    assert main(["gate", "--wait", run_id]) == 6 and f"New.{pack['name']}" in capsys.readouterr().out
    long_run = start_background(on_disk("sleep 30; true"))
    assert main(["gate", "--background"]) == 1 and "gate already running" in capsys.readouterr().out
    reclaimed = [line for line in halt_ticket(pack, ticket, pack["name"]) if line.startswith("reclaimed gate")]
    assert reclaimed and wait(long_run)[0] == 143
    assert wait("nope") == (2, ["no gate run nope"])
    assert main(["gate", "--repo"]) == 2 and main(["gate", "a", "b"]) == 2


@pytest.mark.parametrize("pack_file", PACKS)
def test_evidence_refuses_a_secret_past_the_old_window(env, pack_file, monkeypatch):
    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    pack = load(pack_file)
    from cockpitlib.paths import outbox, qa

    folder = os.path.join(qa(), "TASK-100")
    os.makedirs(folder, exist_ok=True)
    os.makedirs(outbox(), exist_ok=True)
    secret = os.path.join(folder, "shot.txt")
    open(secret, "w", encoding="utf-8").write(("pad\n" * 20000) + f"password={pack['name']}\n")
    client = _client()
    refused = client.get("/qa-file", params={"path": secret})
    assert refused.status_code == 400
    assert "secret" in refused.text
    uploaded = client.post("/upload", json={"ticket": "TASK-100", "name": "leak.txt", "text": f"otp={pack['name']}"})
    assert uploaded.status_code == 400
    assert not os.path.isfile(os.path.join(folder, "leak.txt"))
    key = "AKIAIOSFODNN7EXAMPLE"
    private = "-----BEGIN PRIVATE KEY-----\nabc\n"
    token = f"api_key={pack['privileged']['label']}-token"
    for name, text in (
        ("key.txt", f"token {key}"),
        ("block.txt", private),
        ("token.txt", token),
        ("seed.txt", f"seed={pack['name']}"),
    ):
        posted = client.post("/upload", json={"ticket": "TASK-100", "name": name, "text": text})
        assert posted.status_code == 400
        assert key not in posted.text and "PRIVATE KEY" not in posted.text and token not in posted.text
        assert not os.path.isfile(os.path.join(folder, name))
    planted = os.path.join(folder, "planted.txt")
    open(planted, "w", encoding="utf-8").write(private)
    served_secret = client.get("/qa-file", params={"path": planted})
    assert served_secret.status_code == 400
    assert "PRIVATE KEY" not in served_secret.text
    hidden = f"lane-secret-{pack['name']}-{pack['privileged']['label']}"
    assert "password" not in hidden and "seed=" not in hidden
    monkeypatch.setattr(
        "cockpitlib.vault._items",
        lambda: [
            "nope",
            {"secret": "ab", "otp": ""},
            {"origin": "https://app.test", "email": "a@b.c", "secret": hidden, "otp": ""},
        ],
    )
    bare = os.path.join(folder, "bare.txt")
    open(bare, "w", encoding="utf-8").write(f"the page showed {hidden}\n")
    served_hidden = client.get("/qa-file", params={"path": bare})
    assert served_hidden.status_code == 400
    assert hidden not in served_hidden.text
    posted_hidden = client.post("/upload", json={"ticket": "TASK-100", "name": "bare-upload.txt", "text": hidden})
    assert posted_hidden.status_code == 400
    assert hidden not in posted_hidden.text
    from cockpitlib.errors import CockpitError

    monkeypatch.setattr("cockpitlib.vault._items", lambda: (_ for _ in ()).throw(CockpitError("vault is unreadable")))
    body = ("y" * 50000) + pack["name"]
    clean = os.path.join(outbox(), f"{pack['name']}-note.txt")
    open(clean, "w", encoding="utf-8").write(body)
    served = client.get("/qa-file", params={"path": clean}).json()
    assert served["text"] == body
    huge = os.path.join(folder, "huge.bin")
    with open(huge, "wb") as handle:
        handle.seek(40 * 1024 * 1024)
        handle.write(b"x")
    assert client.get("/qa-file", params={"path": huge}).status_code == 400


@pytest.mark.parametrize("pack_file", PACKS)
def test_flaky_reruns_and_real_reopens_intake(env, pack_file, monkeypatch):
    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    pack = load(pack_file)
    from cockpitlib.acts import answer_card, intake_waiting, mark_ci
    from cockpitlib.intents import load as load_intent
    from cockpitlib.kanban import board_cards

    repo = pack["repos"]["repos"][0]["name"]
    other = load(PACKS[0] if pack["name"] == "bravo" else PACKS[1])
    assert repo != other["repos"]["repos"][0]["name"]
    with pytest.raises(CockpitError, match="flaky or real"):
        mark_ci(pack, "TASK-980", "abc", "maybe", repo)
    with pytest.raises(CockpitError, match="ticket and sha"):
        mark_ci(pack, "", "abc", "flaky", repo)
    with pytest.raises(CockpitError, match="repo"):
        mark_ci(pack, "TASK-980", "abc", "flaky", "")
    with pytest.raises(CockpitError, match="id of the failed run"):
        mark_ci(pack, "TASK-980", "abc", "flaky", repo)
    from cockpitlib.outbox import create

    pushed = create(pack, "TASK-982", "push-branch", "c", "ship", {"repo": repo, "branch": "main"})
    found = mark_ci(pack, "TASK-982", pushed["payload"]["sha"], "flaky", "", run_id="4401")
    assert found["created"] is True and load_intent(found["intent"])["payload"]["repo"] == repo
    assert load_intent(found["intent"])["payload"]["run_id"] == 4401
    flaky = mark_ci(pack, "TASK-980", "abc", "flaky", repo, run_id="4402")
    assert flaky["created"] is True
    again = mark_ci(pack, "TASK-980", "abc", "flaky", repo, run_id="4402")
    assert again["created"] is False and again["intent"] == flaky["intent"]
    saved = load_intent(flaky["intent"])
    assert saved["type"] == "ci-rerun" and saved["payload"]["repo"] == repo
    assert intake_waiting(pack, "TASK-980") == ""
    client = _client()
    marked = client.post("/ci-mark", json={"ticket": "TASK-981", "sha": "def", "verdict": "real", "repo": repo}).json()
    assert marked["waiting"] == "proposal" and marked["created"] is True
    card = intake_waiting(pack, "TASK-981")
    assert card == marked["card_id"]
    shown = next(item for item in board_cards(pack["board"]) if item["id"] == card)
    assert (
        shown["status"] == "ready" and f"at def in {repo}" in shown["body"] and "block for go" in shown["body"]
    )  # intake proposes first
    refused = client.post("/kickoff", json={"ticket": "TASK-981", "mode": "rework"})
    assert refused.status_code == 409 and "waiting for go" in refused.text
    assert (
        client.post("/ci-mark", json={"ticket": "TASK-981", "sha": "def", "verdict": "real"}).json()["created"] is False
    )
    from cockpitlib.kanban import BoardWrites

    writes = BoardWrites(pack["board"])
    writes.block(card, "waiting for go")
    writes.flush()
    assert intake_waiting(pack, "TASK-981") == card
    assert answer_card(pack, card, "go")["ok"] is True
    assert intake_waiting(pack, "TASK-981") == ""


@pytest.mark.parametrize("pack_file", PACKS)
def test_a_real_failure_is_a_comment_on_an_open_intake_card(env, pack_file, monkeypatch):
    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    pack = load(pack_file)
    other = load(PACKS[0] if pack["name"] == "bravo" else PACKS[1])
    assert pack["board"] != other["board"]
    from cockpitlib.acts import mark_ci
    from cockpitlib.kanban import board_cards, place_card

    ticket = f"{pack['tracker']['project']}-1041"
    ready = place_card(pack["board"], f"{ticket}: intake", "intake", "ready")
    marked = mark_ci(pack, ticket, "abc", "real", pack["repos"]["repos"][0]["name"])
    assert marked["created"] is False
    assert marked["card_id"] == ready
    assert marked["waiting"] == "proposal"
    cards = [item for item in board_cards(pack["board"]) if item["title"] == f"{ticket}: intake"]
    assert len(cards) == 1
    assert cards[0]["status"] == "ready"
    assert other["name"] not in cards[0]["title"]
    import sqlite3

    from cockpitlib.kanban import db_path

    connection = sqlite3.connect(db_path(pack["board"]))
    said = [
        row[0]
        for row in connection.execute(
            "select body from task_comments where task_id = ? and author = 'analyst'", (ready,)
        )
    ]
    connection.close()
    assert len(said) == 1 and f"at abc in {pack['repos']['repos'][0]['name']}" in said[0]
    again = mark_ci(pack, ticket, "abc", "real", pack["repos"]["repos"][0]["name"])
    assert again["created"] is False and again["card_id"] == ready
    refused = _client().post("/kickoff", json={"ticket": ticket, "mode": "rework"})
    assert refused.status_code == 409
    assert "waiting for go" in refused.text


@pytest.mark.parametrize("pack_file", PACKS)
def test_created_data_is_linked_on_the_public_origin(env, pack_file, monkeypatch):
    import yaml

    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    pack = load(pack_file)
    from cockpitlib.acts import _public_origin, keep_created

    other = load(PACKS[0] if pack["name"] == "bravo" else PACKS[1])
    origin = _public_origin(pack)
    assert origin and origin != _public_origin(other)
    created = keep_created("TASK-993", "ada the account", {"id": 1}, pack)
    assert created["link"] == f"{origin}/data/ada-the-account"
    stored = json.load(open(created["path"], encoding="utf-8"))
    assert stored["name"] == "ada the account" and stored["link"] == created["link"]
    assert "password" not in json.dumps(stored)
    assert _public_origin({}) == ""
    bare = env["root"] / "nostage"
    bare.mkdir()
    assert _public_origin({"_dir": str(bare)}) == ""
    (bare / "staging.yaml").write_text("- app\n", encoding="utf-8")
    assert _public_origin({"_dir": str(bare)}) == ""
    (bare / "staging.yaml").write_text(yaml.safe_dump({"origins": ["app"]}), encoding="utf-8")
    assert _public_origin({"_dir": str(bare)}) == ""


@pytest.mark.parametrize("pack_file", PACKS)
def test_a_tester_run_without_complete_or_block_is_failed(env, pack_file, monkeypatch):
    import time

    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    pack = load(pack_file)
    from cockpitlib.acts import session_close
    from cockpitlib.kanban import board_cards, place_card
    from cockpitlib.paths import qa
    from cockpitlib.slots import write_owner, write_ticket

    other = load(PACKS[0] if pack["name"] == "bravo" else PACKS[1])
    assert pack["name"] != other["name"]
    running = put_card(pack["board"], "TASK-997: test", "tester-1", "running")
    time.sleep(0.01)
    ready = place_card(pack["board"], f"TASK-997: test {pack['name']}", "tester-1", "ready")
    time.sleep(0.01)
    todo = put_card(pack["board"], f"TASK-997: test todo {pack['name']}", "tester-1", "todo")
    time.sleep(0.01)
    worker = put_card(pack["board"], f"TASK-997: work {pack['name']}", "worker-1", "todo")
    time.sleep(0.01)
    blocked = place_card(pack["board"], "TASK-997: test blocked", "tester-1", "blocked")
    time.sleep(0.01)
    done = put_card(pack["board"], "TASK-997: test done", "tester-1", "done")
    time.sleep(0.01)
    other_ticket = place_card(pack["board"], "TASK-996: test", "tester-1", "ready")
    write_owner(1, "lane:tester-1")
    write_ticket(1, "TASK-997")
    assert session_close(pack, 1).startswith("closed")
    cards = {item["id"]: item["status"] for item in board_cards(pack["board"])}
    from cockpitlib.kanban import block_reason
    from tests.support.boards import raw

    reader = raw(pack["board"])
    for card in (running, ready):
        assert cards[card] == "blocked"
        assert block_reason(reader, card) == f"failed {pack['name']}"
    reader.close()
    assert cards[todo] == "todo"
    assert cards[worker] == "todo"
    assert cards[blocked] == "blocked"
    assert cards[done] == "done"
    assert cards[other_ticket] == "ready"
    record = json.load(open(os.path.join(qa(), "TASK-997", "run-ended.json"), encoding="utf-8"))
    assert record["pack"] == pack["name"] and set(record["failed"]) == {running, ready}
    assert session_close(pack, 1).startswith("closed")
    assert set(json.load(open(os.path.join(qa(), "TASK-997", "run-ended.json"), encoding="utf-8"))["failed"]) == {
        running,
        ready,
    }


@pytest.mark.parametrize("pack_file", PACKS)
def test_a_test_kickoff_publishes_only_on_the_second_go(env, pack_file):
    import sqlite3

    pack = load(pack_file)
    other = load(PACKS[0] if pack["name"] == "bravo" else PACKS[1])
    assert pack["name"] != other["name"]
    from cockpitlib.acts import answer_card, post_test_plan
    from cockpitlib.intents import all_intents
    from cockpitlib.intents import load as load_intent
    from cockpitlib.kanban import board_cards, db_path
    from cockpitlib.paths import qa

    ticket = "TASK-9944"
    posted = post_test_plan(pack, ticket, f"plan for {pack['name']}\n")
    tracker = load_intent(posted["intent"])
    assert tracker["status"] != "published"
    assert tracker["type"] == "tracker-comment"
    from cockpitlib.acts import run_listed

    listed = f"plan for {pack['name']}"
    with pytest.raises(CockpitError, match="not accepted"):
        run_listed(ticket, listed)
    first = answer_card(pack, posted["card"], "go")
    assert run_listed(ticket, listed) == listed
    with pytest.raises(CockpitError, match="does not list"):
        run_listed(ticket, f"plan for {other['name']}")
    with pytest.raises(CockpitError, match="refused"):
        run_listed(ticket, "delete the row")
    assert first["published"] == ""
    marker = json.load(open(os.path.join(qa(), ticket, "plan-accepted.json"), encoding="utf-8"))
    assert marker["pack"] == pack["name"]
    assert other["name"] not in marker["pack"]
    assert not any(row["type"] == "ticket-done" for row in all_intents(ticket))
    card = next(item for item in board_cards(pack["board"]) if item["id"] == posted["card"])
    assert card["status"] == "ready"
    connection = sqlite3.connect(db_path(pack["board"]))
    connection.execute("update tasks set status = 'blocked' where id = ?", (posted["card"],))
    connection.commit()
    connection.close()
    second = answer_card(pack, posted["card"], "go")
    assert second["published"]
    done = [row for row in all_intents(ticket) if row["type"] == "ticket-done"]
    assert len(done) == 1
    assert done[0]["id"] == second["published"]


@pytest.mark.parametrize("pack_file", PACKS)
def test_a_red_gate_does_not_start_the_manual_plan(env, pack_file, monkeypatch):
    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    pack = load(pack_file)
    from cockpitlib.acts import post_test_plan
    from cockpitlib.kanban import board_cards
    from cockpitlib.paths import qa

    other = load(PACKS[0] if pack["name"] == "bravo" else PACKS[1])
    name = pack["repos"]["repos"][0]["name"]
    assert name != other["repos"]["repos"][0]["name"]
    from cockpitlib.acts import start_manual_plan

    red = dict(pack)
    red["repos"] = {"repos": [{"name": name, "gates": ["false"]}]}
    other_gate = other["repos"]["repos"][0]["gates"][0]
    own_gate = pack["repos"]["repos"][0]["gates"][0]
    assert own_gate != other_gate
    from cockpitlib.slots import state_dir, write_owner

    unready = dict(pack)
    unready["stores"] = [dict(pack["stores"][0], present=False)]
    with pytest.raises(CockpitError, match="not ready") as caught:
        start_manual_plan(unready, "TASK-998")
    assert pack["stores"][0]["name"] in str(caught.value)
    assert other["stores"][0]["name"] not in str(caught.value)
    assert not os.path.isfile(os.path.join(qa(), "TASK-998", "manual-plan.md"))
    write_owner(1, "human")
    with pytest.raises(CockpitError, match="manual session"):
        start_manual_plan(pack, "TASK-998")
    assert not os.path.isfile(os.path.join(qa(), "TASK-998", "manual-plan.md"))
    write_owner(1, "free")
    before = [item["id"] for item in board_cards(pack["board"])]
    kept = f"keep@{other['name']}.test"
    for slot, account in ((1, f"lane@{pack['name']}.test"), (2, kept)):
        slot_dir = state_dir(slot)
        os.makedirs(slot_dir, exist_ok=True)
        open(os.path.join(slot_dir, "login.json"), "w", encoding="utf-8").write(json.dumps({"email": account}))
    with pytest.raises(CockpitError, match=f"gate is red: {name}: failed false"):
        start_manual_plan(red, "TASK-998")
    assert not os.path.isfile(os.path.join(qa(), "TASK-998", "manual-plan.md"))
    assert not os.path.isfile(os.path.join(state_dir(1), "login.json"))
    assert kept in open(os.path.join(state_dir(2), "login.json"), encoding="utf-8").read()
    assert [item["id"] for item in board_cards(pack["board"])] == before
    posted = post_test_plan(red, "TASK-998", f"row one {pack['name']}\n")
    assert posted["blocked"] is True
    kickoff = open(os.path.join(qa(), "TASK-998", "test-kickoff.md"), encoding="utf-8").read()
    assert f"row one {pack['name']}" in kickoff
    assert other["name"] not in kickoff
    card = next(item for item in board_cards(pack["board"]) if item["id"] == posted["card"])
    assert card["status"] == "blocked"
    assert f"row one {pack['name']}" in (card["body"] or "")
    started = start_manual_plan(pack, "TASK-998")
    manual = open(started["path"], encoding="utf-8").read()
    assert own_gate in manual
    assert other_gate not in manual


@pytest.mark.parametrize("pack_file", PACKS)
def test_a_gate_run_covers_the_ticket_s_checkouts_and_tells_each_gate_the_ticket(env, pack_file, monkeypatch):
    """A repo the ticket never checked out falls back to the workspace, where its tools can only fail: it is not gated.
    Each gate learns its ticket (COCKPIT_TICKET), also when the run is started for a ticket, not from its card."""
    import copy

    from cockpitlib.paths import wt
    from cockpitlib.repo_gates import run_gates

    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    monkeypatch.delenv("COCKPIT_TICKET", raising=False)
    pack = copy.deepcopy(load(pack_file))
    first, second = pack["repos"]["repos"][:2]
    first["gates"] = ['printf "%s" "$COCKPIT_TICKET" > gate-ticket.txt']
    second["gates"] = ["exit 9"]
    ticket = f"{pack['tracker']['project']}-611"
    checkout = os.path.join(wt(), ticket, first["name"])
    os.makedirs(checkout)
    code, lines = run_gates(pack, ticket=ticket)
    assert code == 0 and not any(line.startswith(second["name"] + ":") for line in lines)
    assert open(os.path.join(checkout, "gate-ticket.txt"), encoding="utf-8").read() == ticket
    code, lines = run_gates(
        pack, ticket=f"{pack['tracker']['project']}-612"
    )  # no checkout at all: every repo runs, as before
    assert code != 0 and any(line.startswith(second["name"] + ":") for line in lines)


@pytest.mark.parametrize("pack_file", PACKS)
def test_a_test_runs_where_the_pack_says_with_its_evidence_and_its_capacity_rules(
    env, pack_file, monkeypatch, tmp_path, capsys
):
    import shutil

    import yaml

    from cockpitlib.errors import PackError

    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    pack = load(pack_file)
    other = _other(pack)
    from cockpitlib.environments import environments, pick
    from cockpitlib.kanban import board_cards
    from cockpitlib.paths import qa, watch_dir, workspace
    from cockpitlib.plan import init
    from cockpitlib.settings import load as load_settings
    from cockpitlib.slots import write_owner, write_ticket

    places = environments(pack)
    assert [item["name"] for item in places] != [item["name"] for item in environments(other)]
    slotted = next(item["name"] for item in places if item["slot"])
    remote = next(item for item in places if not item["slot"])
    assert pick(pack)["name"] == places[0]["name"]
    with pytest.raises(CockpitError, match="no environment moon"):
        pick(pack, "moon")
    ticket = f"{pack['tracker']['project']}-71"
    init(ticket, "plan", "go")
    client = _client()
    from cockpitlib.settings import save as save_settings

    seats = {**load_settings(pack)["seats"], "slots": 3}
    save_settings(pack, {"seats": seats})
    write_owner(1, "human")
    write_ticket(1, ticket)
    refused = client.post("/kickoff", json={"ticket": ticket, "mode": "test", "env": slotted})
    assert refused.status_code == 409 and "manual session" in refused.text  # a slot test needs this machine's slot
    proof = os.path.join(workspace(), "proofs", f"{pack['name']}.png")
    os.makedirs(os.path.dirname(proof), exist_ok=True)
    open(proof, "wb").write(b"png")
    assert (
        client.post(
            "/kickoff", json={"ticket": ticket, "mode": "test", "env": remote["name"], "evidence": ["../outside.png"]}
        ).status_code
        == 409
    )
    assert client.post("/kickoff", json={"ticket": ticket, "mode": "test", "env": "moon"}).status_code == 409
    started = client.post(
        "/kickoff",
        json={"ticket": ticket, "mode": "test", "env": remote["name"], "evidence": [f"proofs/{pack['name']}.png"]},
    )
    assert started.status_code == 200, started.text
    body = next(card["body"] for card in board_cards(pack["board"]) if card["id"] == started.json()["card_id"])
    assert f"Environment: {remote['name']} (no slot)" in body and f"Evidence: proofs/{pack['name']}.png" in body
    assert all(f"Origin {key}: {value}" in body for key, value in remote["origins"].items())
    for number in range(1, seats["slots"] + 1):
        write_owner(number, "lane:worker-1")
        write_ticket(number, f"{pack['tracker']['project']}-9{number}")
    flows = {flow["key"]: flow for flow in client.get("/capacity").json()["flows"]}
    assert flows["test"]["local"] == 0
    needs = pack["capacity"]["test_needs_slot"]
    assert (flows["test"]["free"] == 0) is needs  # a staging test needs no slot where the pack says so
    shown = client.get("/capacity").json()
    assert {item["name"] for item in shown["environments"]} == {item["name"] for item in places}
    second = f"{pack['tracker']['project']}-72"
    init(second, "plan", "go")
    answer = client.post("/kickoff", json={"ticket": second, "mode": "test", "env": remote["name"]})
    assert (answer.status_code == 200) is (not needs), answer.text
    os.makedirs(watch_dir(), exist_ok=True)
    json.dump(
        {"findings": [f"stray login {pack['name']}"]},
        open(os.path.join(watch_dir(), "staging-audit.json"), "w", encoding="utf-8"),
    )
    third = f"{pack['tracker']['project']}-73"
    init(third, "plan", "go")
    blocked = client.post("/kickoff", json={"ticket": third, "mode": "test", "env": remote["name"]})
    blocks = pack["capacity"]["audit_blocks_tests"]
    if blocks:
        assert blocked.status_code == 409 and f"stray login {pack['name']}" in blocked.text
        assert (
            f"stray login {pack['name']}"
            in {flow["key"]: flow for flow in client.get("/capacity").json()["flows"]}["test"]["why"]
        )
    else:
        assert "stray login" not in blocked.text
    from cockpitlib.capacity import audit_finding

    open(os.path.join(watch_dir(), "staging-audit.json"), "w", encoding="utf-8").write("{bad")
    assert audit_finding() == ""

    plan = tmp_path / "plan.md"
    plan.write_text(f"row one {pack['name']}\n", encoding="utf-8")
    assert main(["test", "plan", f"{pack['tracker']['project']}-74", str(plan)]) == 0
    assert '"blocked": true' in capsys.readouterr().out
    assert main(["test", "plan", f"{pack['tracker']['project']}-74", str(tmp_path / "none.md")]) == 2
    assert main(["test", "fail", f"{pack['tracker']['project']}-74", "2", f"broke {pack['name']}"]) == 0
    assert '"recordings": 1' in capsys.readouterr().out
    assert main(["test", "run-dir", f"{pack['tracker']['project']}-74"]) == 0
    assert capsys.readouterr().out.strip().startswith(os.path.join(qa(), f"{pack['tracker']['project']}-74"))
    assert main(["test", "nope"]) == 2 and main(["test", "fail", "a", "b", "c", "--x"]) == 2
    name = os.path.basename(os.path.dirname(pack_file))
    copied = tmp_path / "packs" / name
    shutil.copytree(os.path.dirname(pack_file), copied)
    raw = yaml.safe_load((copied / "pack.yaml").read_text(encoding="utf-8"))
    for change, message in (
        (("environments", []), "environments is a list"),
        (("environments", [{"name": "Bad"}]), "each environment is"),
        (("environments", [{"name": "a"}, {"name": "a"}]), "listed twice"),
        (("environments", [{"name": "a", "origins": {"app": "ftp://x"}}]), "http(s) origin"),
        (("environments", [{"name": "a", "slot": "yes"}]), "slot is true or false"),
        (("capacity", {"test_needs_slot": 1}), "capacity takes"),
    ):
        (copied / "pack.yaml").write_text(
            yaml.safe_dump({**raw, change[0]: change[1]}, sort_keys=False, allow_unicode=True), encoding="utf-8"
        )
        with pytest.raises(PackError, match=re.escape(message)):
            load(str(copied / "pack.yaml"))
    plain = {key: value for key, value in raw.items() if key not in ("environments", "capacity")}
    (copied / "pack.yaml").write_text(yaml.safe_dump(plain, sort_keys=False, allow_unicode=True), encoding="utf-8")
    defaults = environments(load(str(copied / "pack.yaml")))
    assert [(item["name"], item["slot"]) for item in defaults] == [("local", True), ("staging", False)]
    assert (
        defaults[1]["origins"]["app"]
        == yaml.safe_load((copied / "staging.yaml").read_text(encoding="utf-8"))["origins"]["app"]
    )


QA_RUN = "# Run\n**Date:** 2026-10-29\n\n## Summary\n| # | Scenario | Result | Evidence |\n|---|---|---|---|\n| 1 | box | ✅ Pass | [shot](evidences/1-box.png) |\n"


@pytest.mark.parametrize("pack_file", PACKS)
def test_the_qa_page_and_the_standup_note_read_the_runs_where_the_pack_writes_them(env, pack_file, monkeypatch):
    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    pack = load(pack_file)
    from cockpitlib import qa_view, standup_note
    from cockpitlib.paths import qa
    from cockpitlib.test_flow import next_run_dir

    ticket = f"{pack['tracker']['project']}-72"
    folder = os.path.join(qa(), ticket)
    own = next_run_dir(pack, folder)  # the pack's own pattern (acme pass-01, bravo round1)
    plain = os.path.join(folder, "run-7")  # the kernel's own pattern, which neither pack names
    for run in (own, plain, os.path.join(folder, "some_other_folder")):
        os.makedirs(run)
        open(os.path.join(run, "test-results.md"), "w", encoding="utf-8").write(QA_RUN)
    name = os.path.basename(own)
    client = _client()
    row = next(item for item in client.get("/qa").json()["tickets"] if item["ticket"] == ticket)
    assert row["runs"] == 1 and row["last_run"] == name and row["counts"]["pass"] == 1
    shown = client.get("/qa", params={"ticket": ticket}).json()
    assert [run["name"] for run in shown["runs"]] == [name]
    tested = sorted(act["what"] for act in standup_note.collect(0, 4e9, pack)[ticket]["tested"])
    assert tested == [f"{name} finished"]
    without = sorted(act["what"] for act in standup_note.collect(0, 4e9)[ticket]["tested"])
    assert without == ["run-7 finished"], "with no pack the runs are read by the kernel's own pattern"
    import cockpitlib.plugin_api

    def broken(pack=None):
        raise CockpitError("the pack does not load")

    monkeypatch.setattr(cockpitlib.plugin_api, "_pack", broken)  # a pack that does not load: the kernel's own pattern
    assert [run["name"] for run in qa_view.ticket(ticket)["runs"]] == ["run-7"]
    assert next(item for item in qa_view.index()["tickets"] if item["ticket"] == ticket)["runs"] == 1


def test_the_runs_of_a_padded_pattern_are_listed_by_number_and_a_file_is_no_run(env, tmp_path):
    from cockpitlib.paths import qa
    from cockpitlib.test_flow import run_folders

    folder = os.path.join(qa(), "TASK-73")
    for name in ("check_002", "check_010", "check_001"):
        os.makedirs(os.path.join(folder, name))
    open(os.path.join(folder, "check_009"), "w", encoding="utf-8").write("a file, not a run\n")
    padded = {"testflow": {"run_dir": "check_{n:03d}"}}
    assert run_folders(padded, folder) == ["check_001", "check_002", "check_010"]
    assert run_folders(None, folder) == [] and run_folders(padded, str(tmp_path / "none")) == []
