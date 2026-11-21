# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""A card from kickoff to done: housekeeping, hand-offs between lanes, a crashed run, a ticket's chat and its resume note."""

import io
import json
import os
import re
import sys

import pytest

from cockpitlib.cli import main
from cockpitlib.errors import CockpitError
from cockpitlib.pack import load
from tests.support.boards import put_card
from tests.support.both_packs import PACKS, _client, _other


@pytest.mark.parametrize("pack_file", PACKS)
def test_housekeeping_completes_a_review_from_the_lane_report(env, pack_file, monkeypatch):
    import time

    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    pack = load(pack_file)
    other = load(PACKS[0] if pack["name"] == "bravo" else PACKS[1])
    assert pack["board"] != other["board"]
    from cockpitlib.housekeeping import run, settle_reviews
    from cockpitlib.kanban import board_cards
    from cockpitlib.paths import qa

    ticket = "TASK-8850"
    waiting = put_card(pack["board"], f"{ticket}: review {pack['name']}", "reviewer", "review")
    assert settle_reviews(pack) == "0"
    assert any(card["id"] == waiting and card["status"] == "review" for card in board_cards(pack["board"]))
    folder = os.path.join(qa(), ticket)
    os.makedirs(folder, exist_ok=True)
    open(os.path.join(folder, "review.md"), "w", encoding="utf-8").write(f"findings {pack['name']}\n")
    assert "settle-reviews: 1" in run(pack)
    assert any(card["id"] == waiting and card["status"] == "done" for card in board_cards(pack["board"]))
    time.sleep(0.01)
    held = put_card(pack["board"], f"{ticket}: review again", "reviewer", "review")
    open(os.path.join(folder, "review.md"), "w", encoding="utf-8").write(" \n")
    assert settle_reviews(pack) == "0"
    assert any(card["id"] == held and card["status"] == "review" for card in board_cards(pack["board"]))
    import sqlite3

    from cockpitlib.kanban import db_path

    connection = sqlite3.connect(db_path(pack["board"]))  # the test's own handle: housekeeping's can only read
    if "result" not in {row[1] for row in connection.execute("pragma table_info(tasks)")}:
        connection.execute("alter table tasks add column result text")
    connection.execute("update tasks set result = ? where id = ?", (f"report {pack['name']}", held))
    connection.commit()
    connection.close()
    assert settle_reviews(pack) == "1"
    assert any(card["id"] == held and card["status"] == "done" for card in board_cards(pack["board"]))
    assert other["name"] not in open(os.path.join(folder, "review.md"), encoding="utf-8").read()


@pytest.mark.parametrize("pack_file", PACKS)
def test_a_failed_housekeeping_step_fails_the_minute_run(env, pack_file, monkeypatch):
    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    pack = load(pack_file)
    other = load(PACKS[0] if pack["name"] == "bravo" else PACKS[1])
    assert pack["name"] != other["name"]
    from cockpitlib import housekeeping
    from cockpitlib.ops import watch_ci
    from cockpitlib.paths import watch_dir

    def boom(loaded):
        raise RuntimeError(f"settle {loaded['name']}")

    original = housekeeping.STEPS
    monkeypatch.setattr(housekeeping, "STEPS", (("settle-reviews", boom),) + tuple(original[1:]))
    message = watch_ci(pack)
    assert f"settle {pack['name']}" in message
    assert other["name"] not in message
    assert "warm-waiting:" in message
    health = json.load(open(os.path.join(watch_dir(), "ci-watch.json"), encoding="utf-8"))
    assert health["ok"] is False and f"settle {pack['name']}" in health["summary"]
    house = json.load(open(os.path.join(watch_dir(), "housekeeping.json"), encoding="utf-8"))
    assert house["ok"] is False and "warm-waiting:" in house["summary"]
    monkeypatch.setattr(housekeeping, "STEPS", original)
    cleared = watch_ci(pack)
    assert cleared.startswith("ci-watch")
    health = json.load(open(os.path.join(watch_dir(), "ci-watch.json"), encoding="utf-8"))
    assert health["ok"] is True


@pytest.mark.parametrize("pack_file", PACKS)
def test_a_stale_rate_limit_lets_the_card_run_again(env, pack_file, monkeypatch):
    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    pack = load(pack_file)
    other = load(PACKS[0] if pack["name"] == "bravo" else PACKS[1])
    assert pack["board"] != other["board"]
    from cockpitlib.housekeeping import STALE_RATE_LIMIT, stamp_rate_limit, unstrand
    from cockpitlib.kanban import board_cards, place_card
    from cockpitlib.paths import watch_dir

    ticket = "TASK-8860"
    import sqlite3
    import time

    stale = put_card(pack["board"], f"{ticket}: work {pack['name']}", "worker-1", "running")
    time.sleep(0.01)
    fresh = put_card(pack["board"], f"{ticket}: other", "worker-1", "running")
    from cockpitlib.paths import records_name

    folder = env["workspace"] / records_name() / "watch" / "transcripts"
    folder.mkdir(parents=True)
    transcript = folder / "rate.jsonl"
    transcript.write_text(
        "\n".join(
            [
                "not json",
                "",
                "[]",
                json.dumps({"text": "rate limit", "ticket": ticket}),
                json.dumps({"text": "still working", "card": stale}),
                json.dumps({"text": f"rate limit from {pack['name']}", "card": stale, "ticket": ticket}),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr("sys.stdin", io.StringIO(""))
    assert main(["resume-context"]) == 0
    assert any(card["id"] == stale and card["status"] == "blocked" for card in board_cards(pack["board"]))
    stamped = json.load(open(os.path.join(watch_dir(), "rate-limits.json"), encoding="utf-8"))
    started = stamped[stale]["at"]
    assert unstrand(pack, now=started + 10) == "0"
    assert any(card["id"] == stale and card["status"] == "blocked" for card in board_cards(pack["board"]))
    from cockpitlib.kanban import db_path

    connection = sqlite3.connect(db_path(pack["board"]))
    columns = {row[1] for row in connection.execute("pragma table_info(tasks)")}
    if "result" not in columns:
        connection.execute("alter table tasks add column result text")
    connection.execute("update tasks set result = ? where id = ?", (f"rate-limited {pack['name']}", stale))
    connection.commit()
    connection.close()
    assert unstrand(pack, now=started + 10) == "0"
    assert any(card["id"] == stale and card["status"] == "blocked" for card in board_cards(pack["board"]))
    stamp_rate_limit(pack, fresh, ticket, now=started + STALE_RATE_LIMIT)
    assert unstrand(pack, now=started + STALE_RATE_LIMIT) == "1"
    cards = {card["id"]: card["status"] for card in board_cards(pack["board"])}
    assert cards[stale] == "ready"
    assert cards[fresh] == "blocked"
    import sqlite3

    from cockpitlib.kanban import db_path

    unmarked = place_card(pack["board"], f"{ticket}: unmarked {pack['name']}", "worker-1", "blocked")
    connection = sqlite3.connect(db_path(pack["board"]))
    connection.execute("update tasks set result = ? where id = ?", (f"rate-limited {pack['name']}", unmarked))
    connection.commit()
    connection.close()
    assert unstrand(pack, now=started + STALE_RATE_LIMIT) == "0"
    assert any(card["id"] == unmarked and card["status"] == "blocked" for card in board_cards(pack["board"]))
    left = json.load(open(os.path.join(watch_dir(), "rate-limits.json"), encoding="utf-8"))
    assert stale not in left and fresh in left
    open(os.path.join(watch_dir(), "rate-limits.json"), "w", encoding="utf-8").write("[]")
    assert unstrand(pack, now=started + STALE_RATE_LIMIT) == "0"
    open(os.path.join(watch_dir(), "rate-limits.json"), "w", encoding="utf-8").write("{")
    assert unstrand(pack, now=started + STALE_RATE_LIMIT) == "0"
    open(os.path.join(watch_dir(), "rate-limits.json"), "w", encoding="utf-8").write(
        json.dumps({"ghost": "nope", "late": {"at": "soon"}})
    )
    assert unstrand(pack, now=started + STALE_RATE_LIMIT) == "0"
    from cockpitlib.housekeeping import stamp_from_transcript
    from cockpitlib.housekeeping import stamp_rate_limit as stamp_again

    assert stamp_from_transcript(pack, os.path.join(watch_dir(), "absent.jsonl")) == ""
    assert stamp_again({"board": "no-such-board"}, "missing", ticket, now=1)["at"] == 1
    from cockpitlib import housekeeping as housekeeping_mod

    real_db = housekeeping_mod._db

    class Boom:
        def execute(self, *_args, **_kwargs):
            raise sqlite3.Error("down")

        def close(self):
            return None

    monkeypatch.setattr(housekeeping_mod, "_db", lambda _pack: Boom())
    assert stamp_again(pack, fresh, ticket, now=1)["ticket"] == ticket
    monkeypatch.setattr(housekeeping_mod, "_db", real_db)
    unreadable = os.path.join(watch_dir(), "unreadable.jsonl")
    open(unreadable, "w", encoding="utf-8").write('{"text": "rate limit", "card": "c"}\n')
    real_open = open

    def fail_open(path, *args, **kwargs):
        if str(path).endswith("unreadable.jsonl"):
            raise OSError("read")
        return real_open(path, *args, **kwargs)

    monkeypatch.setattr("builtins.open", fail_open)
    assert stamp_from_transcript(pack, unreadable) == ""
    monkeypatch.setattr(
        "cockpitlib.housekeeping.stamp_from_transcript",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    monkeypatch.setattr("sys.stdin", io.StringIO(""))
    assert main(["resume-context"]) == 0


@pytest.mark.parametrize("pack_file", PACKS)
def test_stop_closes_a_card_hermes_parked_in_triage(env, pack_file):
    """Hermes completes no card it parked in triage: the human's stop releases it first, then completes it."""
    from cockpitlib.acts import answer_card
    from cockpitlib.kanban import BoardWrites, board_cards, place_card

    pack = load(pack_file)
    board = pack["board"]
    card = place_card(board, f"{pack['tracker']['project']}-331: intake", "intake")
    for _ in range(2):  # the same block twice is Hermes's loop guard: triage
        writes = BoardWrites(board)
        writes.block(card, "go? the plan is on the card")
        writes.flush()
        if {item["id"]: item["status"] for item in board_cards(board)}[card] == "blocked":
            writes = BoardWrites(board)
            writes.unblock(card)
            writes.flush()
    assert {item["id"]: item["status"] for item in board_cards(board)}[card] == "triage"
    answer_card(pack, card, "stop: do not continue; I will take it from here.")
    assert {item["id"]: item["status"] for item in board_cards(board)}[card] == "done"


@pytest.mark.parametrize("pack_file", PACKS)
def test_a_crashed_run_is_inserted_once(env, pack_file, monkeypatch, capsys):
    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    pack = load(pack_file)
    other = load(PACKS[0] if pack["name"] == "bravo" else PACKS[1])
    assert pack["name"] != other["name"]
    from cockpitlib.paths import watch_dir
    from cockpitlib.resume import shown_resume

    folder = env["workspace"] / "transcripts"
    folder.mkdir()
    path = folder / "dead.jsonl"
    path.write_text(
        '{"command": "git status", "exit": 0}\n'
        '{"command": "make ' + pack["name"] + '", "exit": 2, "output": "tool dump ' + other["name"] + '"}\n',
        encoding="utf-8",
    )
    os.makedirs(watch_dir(), exist_ok=True)
    open(os.path.join(watch_dir(), "resume-shown.json"), "w", encoding="utf-8").write("{")
    assert shown_resume(str(path)) is False
    open(os.path.join(watch_dir(), "resume-shown.json"), "w", encoding="utf-8").write("{}")
    assert shown_resume(str(path)) is False
    os.remove(os.path.join(watch_dir(), "resume-shown.json"))
    payload = json.dumps({"transcript": str(path)})
    monkeypatch.setattr(sys, "stdin", io.StringIO(payload))
    assert main(["resume-context"]) == 0
    first = capsys.readouterr().out
    assert f"make {pack['name']} exit 2" in first
    assert "git status exit 0" in first
    assert "tool dump" not in first
    assert other["name"] not in first
    logged = open(os.path.join(watch_dir(), "resume.log"), encoding="utf-8").read()
    assert f"make {pack['name']} exit 2" in logged
    assert "git status exit 0" in logged
    assert "tool dump" not in logged
    assert other["name"] not in logged
    monkeypatch.setattr(sys, "stdin", io.StringIO(payload))
    assert main(["resume-context"]) == 0
    assert capsys.readouterr().out == ""
    done = folder / "done.jsonl"
    done.write_text('{"command": "true", "exit": 0, "outcome": "done"}\n', encoding="utf-8")
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps({"transcript": str(done)})))
    assert main(["resume-context"]) == 0
    assert capsys.readouterr().out == ""
    monkeypatch.setattr(sys, "stdin", io.StringIO(""))
    assert main(["resume-context"]) == 0
    assert capsys.readouterr().out == ""
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps([{"output": "tool dump"}])))
    assert main(["resume-context"]) == 0
    assert capsys.readouterr().out == ""
    again = json.dumps([{"command": f"retry {pack['name']}", "exit": 1}])
    monkeypatch.setattr(sys, "stdin", io.StringIO(again))
    assert main(["resume-context"]) == 0
    assert f"retry {pack['name']} exit 1" in capsys.readouterr().out
    assert f"retry {pack['name']} exit 1" in open(os.path.join(watch_dir(), "resume.log"), encoding="utf-8").read()
    monkeypatch.setattr(sys, "stdin", io.StringIO(again))
    assert main(["resume-context"]) == 0
    assert capsys.readouterr().out == ""
    from cockpitlib.resume import mark_resume

    open(os.path.join(watch_dir(), "resume-shown.json"), "w", encoding="utf-8").write("{")
    mark_resume("recovered")
    fresh = folder / "fresh.jsonl"
    fresh.write_text('{"command": "boom", "exit": 3}\n', encoding="utf-8")

    def _boom(*_args, **_kwargs):
        raise RuntimeError("stamp")

    monkeypatch.setattr("cockpitlib.housekeeping.stamp_from_transcript", _boom)
    monkeypatch.setattr(sys, "stdin", io.StringIO(""))
    assert main(["resume-context"]) == 0
    assert "boom exit 3" in capsys.readouterr().out


@pytest.mark.parametrize("pack_file", PACKS)
def test_a_crashed_run_keeps_its_heartbeat_note(env, pack_file, monkeypatch, capsys):
    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    pack = load(pack_file)
    other = load(PACKS[0] if pack["name"] == "bravo" else PACKS[1])
    assert pack["name"] != other["name"]

    folder = env["workspace"] / "transcripts"
    folder.mkdir()
    path = folder / "heartbeat.jsonl"
    name = pack["name"]
    path.write_text(
        "\n".join(
            [
                json.dumps({"text": f"narration {name}"}),
                json.dumps({"heartbeat": f"still on {name}"}),
                json.dumps({"heartbeat": "   ", "text": f"blank beat {name}"}),
                json.dumps({"heartbeat": 15, "note": f"clock {name}"}),
                json.dumps({"kind": "heartbeat", "payload": {"note": f"payload {name}"}}),
                json.dumps({"kind": "heartbeat", "payload": {}, "note": f"empty payload {name}"}),
                json.dumps({"kind": "heartbeat", "note": f"no payload {name}"}),
                json.dumps({"kind": "heartbeat", "payload": {"text": f"payload text {name}"}}),
                json.dumps({"type": "heartbeat", "payload": f"typed {name}"}),
                json.dumps({"command": f"gate {name}", "exit": 2}),
                json.dumps({"output": "tool dump"}),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    payload = json.dumps({"transcript": str(path)})
    monkeypatch.setattr(sys, "stdin", io.StringIO(payload))
    assert main(["resume-context"]) == 0
    first = capsys.readouterr().out
    for piece in (
        f"narration {name}",
        f"still on {name}",
        f"blank beat {name}",
        f"clock {name}",
        f"payload {name}",
        f"empty payload {name}",
        f"no payload {name}",
        f"payload text {name}",
        f"typed {name}",
        f"gate {name} exit 2",
    ):
        assert piece in first
    assert "tool dump" not in first
    assert other["name"] not in first
    limited = folder / "limited.jsonl"
    limited.write_text(
        json.dumps({"text": f"rate limit on {name}", "outcome": "rate_limit", "heartbeat": f"waiting {name}"}) + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps({"transcript": str(limited)})))
    assert main(["resume-context"]) == 0
    limited_note = capsys.readouterr().out
    assert f"waiting {name}" in limited_note
    assert f"rate limit on {name}" in limited_note
    reclaimed = folder / "reclaimed.jsonl"
    reclaimed.write_text(
        json.dumps({"note": f"reclaimed {name}", "outcome": "reclaimed"}) + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps({"transcript": str(reclaimed)})))
    assert main(["resume-context"]) == 0
    assert f"reclaimed {name}" in capsys.readouterr().out
    finished = folder / "finished-beat.jsonl"
    finished.write_text(
        json.dumps({"heartbeat": f"done {name}", "outcome": "completed"}) + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps({"transcript": str(finished)})))
    assert main(["resume-context"]) == 0
    assert capsys.readouterr().out == ""
    direct = json.dumps(
        [
            {"heartbeat": f"direct {name}", "text": f"aside {name}"},
            {"heartbeat": f"same {name}", "text": f"same {name}"},
            {"output": "tool dump"},
        ]
    )
    monkeypatch.setattr(sys, "stdin", io.StringIO(direct))
    assert main(["resume-context"]) == 0
    posted = capsys.readouterr().out
    assert f"direct {name}" in posted
    assert f"aside {name}" in posted
    assert posted.count(f"same {name}") == 1
    assert "tool dump" not in posted


@pytest.mark.parametrize("pack_file", PACKS)
def test_a_pre_model_call_inserts_the_dead_run_on_the_first_turn(env, pack_file, monkeypatch, capsys):
    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    pack = load(pack_file)
    other = load(PACKS[0] if pack["name"] == "bravo" else PACKS[1])
    assert pack["name"] != other["name"]
    from cockpitlib.paths import records_name, watch_dir

    folder = env["workspace"] / records_name() / "watch" / "transcripts"
    folder.mkdir(parents=True, exist_ok=True)
    name = pack["name"]

    def plant(filename, body, stamp):
        path = folder / filename
        path.write_text(body, encoding="utf-8")
        os.utime(path, (stamp, stamp))
        return path

    def run(payload):
        monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps({"hook_event_name": "pre_llm_call", **payload})))
        assert main(["resume-context"]) == 0
        return capsys.readouterr().out

    assert run({"extra": {"is_first_turn": True}}) == ""
    plant(
        "crash.jsonl",
        "\n".join(
            [
                "",
                "not-json",
                "[]",
                json.dumps({"command": f"gate {name}", "exit": 2, "output": "tool dump"}),
            ]
        )
        + "\n",
        1_700_000_000,
    )
    assert run({"extra": {"is_first_turn": False}}) == ""
    assert run({"extra": "nope"}) == ""
    assert run({"extra": {"conversation_history": [{}, {}]}}) == ""
    posted = json.loads(run({"extra": {"is_first_turn": True}}))
    assert f"gate {name} exit 2" in posted["context"]
    assert "tool dump" not in posted["context"]
    assert other["name"] not in posted["context"]
    assert run({"extra": {"is_first_turn": True}}) == ""
    logged = open(os.path.join(watch_dir(), "resume.log"), encoding="utf-8").read()
    assert f"gate {name} exit 2" in logged
    assert "tool dump" not in logged
    plant("silent.jsonl", json.dumps({"output": "tool dump"}) + "\n", 1_700_000_050)
    assert run({"extra": {"is_first_turn": True}}) == ""
    plant("done.jsonl", json.dumps({"text": f"finished {name}", "outcome": "completed"}) + "\n", 1_700_000_100)
    assert run({"extra": {"is_first_turn": True}}) == ""
    plant("limited.jsonl", json.dumps({"text": f"rate limit on {name}", "outcome": "rate_limit"}) + "\n", 1_700_000_200)
    limited = json.loads(run({"extra": {"is_first_turn": True}}))
    assert f"rate limit on {name}" in limited["context"]
    assert other["name"] not in limited["context"]
    plant("back.jsonl", json.dumps({"note": f"reclaimed {name}", "outcome": "reclaimed"}) + "\n", 1_700_000_300)
    back = json.loads(run({"is_first_turn": True}))
    assert f"reclaimed {name}" in back["context"]
    plant("died.jsonl", json.dumps({"text": f"crashed {name}", "outcome": "crashed"}) + "\n", 1_700_000_400)
    died = json.loads(run({"extra": {"conversation_history": []}}))
    assert f"crashed {name}" in died["context"]


@pytest.mark.parametrize("pack_file", PACKS)
def test_review_waits_while_a_person_still_has_a_row(env, pack_file, monkeypatch):
    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    pack = load(pack_file)
    other = load(PACKS[0] if pack["name"] == "bravo" else PACKS[1])
    assert pack["name"] != other["name"]
    from cockpitlib.acts import open_test_rows
    from cockpitlib.paths import qa

    ticket = "TASK-8923"
    folder = os.path.join(qa(), ticket)
    os.makedirs(folder, exist_ok=True)
    results = os.path.join(folder, "test-results.md")
    open(results, "w", encoding="utf-8").write(f"1 ✅ evidences/a.png\n2 waiting on the human {pack['name']}\n")
    with pytest.raises(CockpitError, match="open rows"):
        open_test_rows(ticket)
    open(results, "w", encoding="utf-8").write("1 ✅ evidences/a.png\n2 👤 evidences/b.png\n")
    with pytest.raises(CockpitError, match="open rows"):
        open_test_rows(ticket)
    open(results, "w", encoding="utf-8").write("1 ✅ evidences/a.png\n2 ✅ evidences/b.png\n")
    open(results, "w", encoding="utf-8").write("2 Blocked\n")
    with pytest.raises(CockpitError, match="open rows"):
        open_test_rows(ticket)
    open(results, "w", encoding="utf-8").write("\n1 Unblocked ✅ evidences/a.png\n2 no longer waiting on the human\n")
    open_test_rows(ticket)
    human = os.path.join(folder, "human-rows.json")
    open(human, "w", encoding="utf-8").write("{")
    open_test_rows(ticket)
    open(human, "w", encoding="utf-8").write("{}")
    open_test_rows(ticket)
    json.dump(
        [{"n": 1, "human": False}, {"n": 3, "human": True, "steps": [pack["name"]]}], open(human, "w", encoding="utf-8")
    )
    with pytest.raises(CockpitError, match="open rows"):
        open_test_rows(ticket)
    open(results, "a", encoding="utf-8").write("3 ✅ evidences/c.png\n")
    open_test_rows(ticket)
    assert other["name"] not in open(results, encoding="utf-8").read()


@pytest.mark.parametrize("pack_file", PACKS)
def test_the_router_adds_one_skill(env, pack_file):
    pack = load(pack_file)
    other = load(PACKS[0] if pack["name"] == "bravo" else PACKS[1])
    from cockpitlib.pack import agent_launch

    assert (
        open(agent_launch(pack)["router"], encoding="utf-8").read()
        != open(agent_launch(other)["router"], encoding="utf-8").read()
    )
    from cockpitlib.acts import answer_card
    from cockpitlib.kanban import place_card
    from cockpitlib.outbox import extra_skills
    from cockpitlib.plan import append
    from cockpitlib.skill_log import append as load_skill
    from cockpitlib.skill_log import log_path

    ticket = "TASK-8920"
    assert load_skill(ticket, "worker-1", "cockpit:outbox") == "cockpit:outbox"
    assert load_skill(ticket, "worker-1", "cockpit:outbox") == "cockpit:outbox"
    with pytest.raises(CockpitError, match="skill"):
        load_skill(ticket, "worker-1", " ")
    with pytest.raises(CockpitError, match="a ticket and a lane"):
        log_path(ticket, "../worker-1")
    assert extra_skills(pack, "worker", ["cockpit:outbox", "pr-review"]) == ["pr-review"]
    assert extra_skills(pack, "worker", ["", "pr-review", "pr-review"]) == ["pr-review"]
    assert other["skills"]["kickoff"]["worker"] == pack["skills"]["kickoff"]["worker"]
    for name in ("pr-review", "test"):
        load_skill(ticket, "worker-1", name)
    load_skill(ticket, "worker-2", "jira-tickets")
    from cockpitlib.plan import init as init_plan

    init_plan(ticket, "plan", "go")
    append(ticket, "Delivered", f"shipped {pack['name']}")
    card = place_card(pack["board"], f"{ticket}: work", "worker-1", "blocked")
    with pytest.raises(CockpitError, match="one skill"):
        answer_card(pack, card, "complete")
    open(log_path(ticket, "worker-1"), "w", encoding="utf-8").write("skill:cockpit:outbox\nskill:pr-review\n")
    assert answer_card(pack, card, "complete")["ok"]


@pytest.mark.parametrize("pack_file", PACKS)
def test_a_worker_finish_appends_its_delivered_section(env, pack_file):
    pack = load(pack_file)
    other = load(PACKS[0] if pack["name"] == "bravo" else PACKS[1])
    assert pack["name"] != other["name"]
    from cockpitlib.acts import answer_card
    from cockpitlib.kanban import place_card
    from cockpitlib.plan import show

    ticket = "TASK-1029"
    card = place_card(pack["board"], f"{ticket}: work", "worker-1", "blocked")
    with pytest.raises(CockpitError, match="missing section"):
        answer_card(pack, card, "complete")
    with pytest.raises(CockpitError, match="no plan for TASK-1029"):
        answer_card(pack, card, f"complete: shipped {pack['name']}")
    from cockpitlib.plan import init

    init(ticket, f"# Plan {pack['name']}", "go")
    done = answer_card(pack, card, f"complete: shipped {pack['name']}")
    assert done["ok"]
    text = show(ticket)
    assert "## Delivered" in text and f"shipped {pack['name']}" in text
    assert other["name"] not in text


@pytest.mark.parametrize("pack_file", PACKS)
def test_a_lane_finish_appends_its_own_section(env, pack_file):
    pack = load(pack_file)
    other = load(PACKS[0] if pack["name"] == "bravo" else PACKS[1])
    assert pack["name"] != other["name"]
    from cockpitlib.acts import answer_card
    from cockpitlib.kanban import place_card
    from cockpitlib.paths import qa
    from cockpitlib.plan import append, show

    reviewer = place_card(pack["board"], "TASK-1030: review", "reviewer-1", "blocked")
    from cockpitlib.plan import init

    init("TASK-1030", f"# Plan {pack['name']}", "go")
    with pytest.raises(CockpitError, match="missing section Reviewed"):
        answer_card(pack, reviewer, "complete")
    with pytest.raises(CockpitError, match="missing section Reviewed"):
        answer_card(pack, reviewer, "complete: Reviewed")
    done = answer_card(pack, reviewer, f"complete: notes {pack['name']}")
    assert done["ok"]
    reviewed = show("TASK-1030")
    assert "## Reviewed" in reviewed and f"notes {pack['name']}" in reviewed
    assert other["name"] not in reviewed
    folder = os.path.join(qa(), "TASK-1031")
    os.makedirs(os.path.join(folder, "evidences"), exist_ok=True)
    open(os.path.join(folder, "plan.md"), "w", encoding="utf-8").write("check the row\n")
    open(os.path.join(folder, "test-results.md"), "w", encoding="utf-8").write("check the row ✅ evidences/a.png\n")
    open(os.path.join(folder, "evidences", "a.png"), "wb").write(pack["name"].encode())
    tester = place_card(pack["board"], "TASK-1031: test", "tester-1", "blocked")
    with pytest.raises(CockpitError, match="missing section Tested"):
        answer_card(pack, tester, "complete")
    proved = answer_card(pack, tester, f"complete: proved {pack['name']}")
    assert proved["ok"]
    tested = show("TASK-1031")
    assert "## Tested" in tested and f"proved {pack['name']}" in tested
    assert "## Delivered" not in tested
    assert other["name"] not in tested
    other_card = place_card(pack["board"], "TASK-1032: analyst", "analyst-1", "blocked")
    with pytest.raises(CockpitError, match="missing section Delivered"):
        answer_card(pack, other_card, "complete")
    with pytest.raises(CockpitError, match="no plan for TASK-1032"):
        append("TASK-1032", "Delivered", "kept")
    init("TASK-1032", "", "go")
    append("TASK-1032", "Delivered", "kept")
    assert answer_card(pack, other_card, "complete")["ok"]
    assert "Reviewed" not in show("TASK-1032") and "Tested" not in show("TASK-1032")


@pytest.mark.parametrize("pack_file", PACKS)
def test_the_reviewer_card_stays_blocked_until_the_tester_finishes(env, pack_file, monkeypatch):
    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    pack = load(pack_file)
    other = load(PACKS[0] if pack["name"] == "bravo" else PACKS[1])
    assert pack["name"] != other["name"]
    from cockpitlib.acts import answer_card, reviewer_ready
    from cockpitlib.kanban import board_cards, place_card
    from cockpitlib.paths import qa

    ticket = f"{pack['tracker']['project']}-1037"
    folder = os.path.join(qa(), ticket, "evidences")
    os.makedirs(folder, exist_ok=True)
    open(os.path.join(qa(), ticket, "plan.md"), "w", encoding="utf-8").write(
        f"check {pack['name']}\n\n## Decision\ngo\n"
    )
    open(os.path.join(qa(), ticket, "test-results.md"), "w", encoding="utf-8").write(
        f"check {pack['name']} ✅ evidences/a.png\n## Decision ✅ evidences/a.png\ngo ✅ evidences/a.png\n"
    )
    open(os.path.join(folder, "a.png"), "wb").write(pack["name"].encode())
    tester = place_card(pack["board"], f"{ticket}: test", "tester-1", "blocked")
    kicked = _client().post("/kickoff", json={"ticket": ticket, "mode": "review"})
    assert kicked.status_code == 200
    reviewer = kicked.json()["card_id"]
    cards = {card["id"]: card for card in board_cards(pack["board"])}
    assert cards[reviewer]["status"] == "blocked"
    assert other["name"] not in cards[reviewer]["title"]
    with pytest.raises(CockpitError, match="reviewer waits"):
        reviewer_ready(pack, ticket)
    assert answer_card(pack, tester, f"complete: proved {pack['name']}")["ok"]
    cards = {card["id"]: card for card in board_cards(pack["board"])}
    assert cards[tester]["status"] == "done"
    assert cards[reviewer]["status"] == "ready"
    reviewer_ready(pack, ticket)


@pytest.mark.parametrize("pack_file", PACKS)
def test_a_dev_card_needs_every_plan_row(env, pack_file):
    pack = load(pack_file)
    other = load(PACKS[0] if pack["name"] == "bravo" else PACKS[1])
    assert pack["name"] != other["name"]
    from cockpitlib.acts import answer_card, missing_plan_rows
    from cockpitlib.kanban import place_card
    from cockpitlib.paths import qa

    ticket = "TASK-8910"
    folder = os.path.join(qa(), ticket)
    os.makedirs(folder, exist_ok=True)
    open(os.path.join(folder, "plan.md"), "w", encoding="utf-8").write(
        f"open {pack['name']}\ncheck the row\n\n## Delivered\n\ntested\n"
    )
    kickoff = os.path.join(folder, "test-kickoff.md")
    open(kickoff, "w", encoding="utf-8").write(f"untested\nopen {pack['name']}\n")
    open(os.path.join(folder, "test-results.md"), "w", encoding="utf-8").write("untested ✅ evidences/a.png\n")
    assert "1" in missing_plan_rows(ticket)
    assert "4" in missing_plan_rows(ticket)
    card = place_card(pack["board"], f"{ticket}: test", "tester-1", "blocked")
    with pytest.raises(CockpitError, match="missing plan row 1,2,3,4"):
        answer_card(pack, card, "complete")
    os.remove(kickoff)
    open(os.path.join(folder, "test-results.md"), "w", encoding="utf-8").write(
        f"open {pack['name']} ✅ evidences/a.png\ncheck the row ✅\n## Delivered ✅ evidences/c.png\ntested ✅ evidences/d.png\n"
    )
    with pytest.raises(CockpitError, match="unfinished screenshot"):
        answer_card(pack, card, "complete")
    open(os.path.join(folder, "test-results.md"), "w", encoding="utf-8").write(
        f"open {pack['name']} ✅ evidences/a.png\ncheck the row ✅ evidences/b.png\n## Delivered ✅ evidences/c.png\ntested ✅ evidences/d.png\nextra ✅ qa/{ticket}/evidences/e.png\n"
    )
    with pytest.raises(CockpitError, match="unfinished screenshot"):
        answer_card(pack, card, "complete")
    shot = os.path.join(folder, "evidences")
    os.makedirs(shot, exist_ok=True)
    for name in ("a.png", "b.png", "c.png", "d.png", "e.png"):
        open(os.path.join(shot, name), "wb").write(pack["name"].encode())
    finished = (
        f"open {pack['name']} ✅ evidences/a.png\n"
        "check the row ✅ evidences/b.png\n"
        "## Delivered ✅ evidences/c.png\n"
        "tested ✅ evidences/d.png\n"
        f"extra ✅ qa/{ticket}/evidences/e.png\n"
    )
    open(os.path.join(folder, "test-results.md"), "w", encoding="utf-8").write(
        finished + "9 Blocked ✅ evidences/a.png\n"
    )
    with pytest.raises(CockpitError, match="unfinished screenshot"):
        answer_card(pack, card, "complete")
    open(os.path.join(folder, "test-results.md"), "w", encoding="utf-8").write(
        finished + "9 Unblocked ✅ evidences/a.png\n2 no longer waiting on the human ✅ evidences/a.png\n"
    )
    from cockpitlib.acts import keep_created, snapshot_settings

    snapshot_settings(ticket, {"theme": pack["name"]})
    open(os.path.join(folder, "settings.json"), "w", encoding="utf-8").write(
        json.dumps({"theme": "changed", "extra": other["name"]})
    )
    created = keep_created(ticket, f"ada {pack['name']}", {"id": 1}, pack)
    assert answer_card(pack, card, f"complete: proved {pack['name']}")["ok"]
    restored = json.loads(open(os.path.join(folder, "settings.json"), encoding="utf-8").read())
    assert restored == {"theme": pack["name"]}
    assert other["name"] not in json.dumps(restored)
    assert os.path.isfile(created["path"])
    assert other["name"] not in open(os.path.join(folder, "plan.md"), encoding="utf-8").read()


@pytest.mark.parametrize("pack_file", PACKS)
def test_the_analyst_writes_a_verdict_without_a_new_card(env, pack_file, monkeypatch):
    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    pack = load(pack_file)
    other = load(PACKS[0] if pack["name"] == "bravo" else PACKS[1])
    repo = pack["repos"]["repos"][0]["name"]
    other_repo = other["repos"]["repos"][0]["name"]
    assert repo != other_repo
    from cockpitlib.acts import changes_dir
    from cockpitlib.kanban import board_cards

    os.makedirs(changes_dir(), exist_ok=True)
    open(os.path.join(changes_dir(), f"{repo}-6.json"), "w", encoding="utf-8").write(
        json.dumps({"repo": repo, "number": 6, "status": "relevant", "seen": False})
    )
    before = len(board_cards(pack["board"]))
    client = _client()
    assert client.post("/platform-verdict", json={"repo": repo, "number": 6, "text": ""}).status_code == 400
    written = client.post("/platform-verdict", json={"repo": repo, "number": 6, "text": f"real {pack['name']}"})
    assert written.status_code == 200
    record = json.load(open(os.path.join(changes_dir(), f"{repo}-6.json"), encoding="utf-8"))
    assert record["verdict"] == f"real {pack['name']}"
    assert other_repo not in record["verdict"]
    assert len(board_cards(pack["board"])) == before
    shown = client.get("/platform-change", params={"repo": repo, "number": 6}).json()
    assert shown["verdict"] == record["verdict"]
    from cockpitlib.acts import write_verdict

    with pytest.raises(CockpitError, match="no change"):
        write_verdict(repo, 99, "x")
    with pytest.raises(CockpitError, match="repo and number"):
        write_verdict("", 0, "x")


@pytest.mark.parametrize("pack_file", PACKS)
def test_continue_opens_a_new_card_and_leaves_closed_cards_closed(env, pack_file):
    from cockpitlib.acts import continue_ticket, halt_ticket, resume_ticket
    from cockpitlib.errors import Conflict
    from cockpitlib.kanban import board_cards

    pack = load(pack_file)
    other = load(PACKS[0] if pack["name"] == "bravo" else PACKS[1])
    assert pack["name"] != other["name"]
    ticket = "TASK-1011"
    done = put_card(pack["board"], f"{ticket}: worker", "worker-1", "done")
    with pytest.raises(CockpitError, match="new details"):
        continue_ticket(pack, ticket, "  ")
    with pytest.raises(CockpitError, match="evidence"):
        continue_ticket(pack, ticket, "go on", evidence={"path": "x"})
    prompt = f"continue {pack['name']}"
    opened = continue_ticket(pack, ticket, prompt, [f"qa/{ticket}/{pack['name']}.png"])
    assert opened["title"] == f"{ticket}: reopened"
    assert opened["status"] == "ready"
    assert opened["closed"] == [done]
    bodies = {item["id"]: item["body"] for item in board_cards(pack["board"])}
    body = bodies[opened["card_id"]]
    assert prompt in body and f"- qa/{ticket}/{pack['name']}.png" in body and "block for go" in body
    text = open(opened["path"], encoding="utf-8").read()
    assert prompt in text and f"qa/{ticket}/{pack['name']}.png" in text
    assert other["name"] not in text
    rework = continue_ticket(pack, ticket, prompt, kind="rework")
    assert rework["title"] == f"{ticket}: rework" and rework["status"] == "ready"
    assert done in rework["closed"]
    cards = {item["id"]: item["status"] for item in board_cards(pack["board"])}
    assert cards[done] == "done"
    assert cards[opened["card_id"]] == "ready"
    assert "## Instruction" in {item["id"]: item["body"] for item in board_cards(pack["board"])}[rework["card_id"]]
    halt_ticket(pack, ticket, "pause")
    with pytest.raises(Conflict, match="halted"):
        continue_ticket(pack, ticket, prompt)
    before = len(board_cards(pack["board"]))
    assert resume_ticket(ticket).startswith("resumed")
    after = board_cards(pack["board"])
    assert len(after) == before
    assert any(item["id"] == done and item["status"] == "done" for item in after)
    refused = _client().post("/reopen-flow", json={"ticket": ticket, "prompt": ""})
    assert refused.status_code == 400


@pytest.mark.parametrize("pack_file", PACKS)
def test_handoff_without_a_lane_skips_a_frozen_worker(env, pack_file, monkeypatch):
    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    pack = load(pack_file)
    other = load(PACKS[0] if pack["name"] == "bravo" else PACKS[1])
    from cockpitlib.acts import session_handoff
    from cockpitlib.kanban import board_cards
    from cockpitlib.paths import watch_dir
    from cockpitlib.settings import frozen_path
    from cockpitlib.slots import read_owner, write_owner, write_ticket

    ticket = f"{pack['tracker']['project']}-1048"
    write_owner(1, "human")
    write_ticket(1, ticket)
    os.makedirs(watch_dir(), exist_ok=True)
    json.dump(
        {"seats": {"slots": 2, "intake": 1, "reviewer": 1, "analyst": 1}},
        open(os.path.join(watch_dir(), "settings.json"), "w", encoding="utf-8"),
    )
    json.dump(["worker-1"], open(frozen_path(), "w", encoding="utf-8"))
    posted = _client().post("/session", json={"action": "handoff", "slot": 1})
    assert posted.status_code == 200
    assert "lane:worker-2" in posted.json()["session"]["out"]
    assert read_owner(1) == "lane:worker-2"
    opened = [card for card in board_cards(pack["board"]) if card.get("title") == f"{ticket}: work"]
    assert opened and opened[-1]["assignee"] == "worker-2"
    assert other["name"] not in opened[-1]["title"]
    with pytest.raises(CockpitError, match="slot 1 is not the human's to hand off"):
        session_handoff(pack, 1, "lane:worker-2")
    assert all(card.get("assignee") != "lane:worker-2" for card in board_cards(pack["board"]))


@pytest.mark.parametrize("pack_file", PACKS)
def test_halt_reclaims_the_ticket_chat(env, pack_file, monkeypatch):
    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    monkeypatch.setenv("COCKPIT_CHAT_ARGV", "sleep 30")
    pack = load(pack_file)
    other = load(PACKS[0] if pack["name"] == "bravo" else PACKS[1])
    assert pack["name"] != other["name"]
    from cockpitlib.acts import halt_ticket
    from cockpitlib.chat import _TERMS, end_chat, open_chat

    ticket = "TASK-1022"
    kept = "TASK-1023"
    open_chat(ticket)
    open_chat(kept)
    own_pid = _TERMS[ticket].pid
    kept_pid = _TERMS[kept].pid
    try:
        lines = halt_ticket(pack, ticket, pack["name"])
        assert "reclaimed chat" in lines
        assert other["name"] not in " ".join(lines)
        assert ticket not in _TERMS
        assert kept in _TERMS and _TERMS[kept].alive
    finally:
        end_chat(ticket)
        end_chat(kept)
        for pid in (own_pid, kept_pid):
            try:
                os.waitpid(pid, os.WNOHANG)
            except OSError:
                pass


@pytest.mark.parametrize("pack_file", PACKS)
def test_unfinished_review_returns_to_the_tester(env, pack_file):
    import sqlite3

    from cockpitlib.housekeeping import return_unfinished
    from cockpitlib.kanban import db_path
    from cockpitlib.paths import qa

    pack = load(pack_file)
    path = db_path(pack["board"])
    os.makedirs(os.path.dirname(path), exist_ok=True)
    bare = sqlite3.connect(path)
    bare.execute("create table tasks (id text, title text, status text)")
    bare.commit()
    bare.close()
    assert return_unfinished(pack) == "0"
    os.remove(path)
    connection = sqlite3.connect(path)
    connection.execute("create table tasks (id text, title text, status text, assignee text)")
    connection.execute("insert into tasks values ('noise', 'note', 'ready', 'worker-1')")
    connection.execute("insert into tasks values ('missing', 'TASK-982: review', 'blocked', 'reviewer')")
    connection.execute("insert into tasks values ('review', 'TASK-980: review', 'blocked', 'reviewer')")
    connection.execute("insert into tasks values ('tester', 'TASK-980: test', 'blocked', 'tester-1')")
    connection.execute("insert into tasks values ('done-review', 'TASK-981: review', 'blocked', 'reviewer')")
    connection.execute("insert into tasks values ('human', 'TASK-983: review', 'blocked', 'reviewer')")
    connection.execute("insert into tasks values ('person', 'TASK-984: review', 'blocked', 'reviewer')")
    connection.execute("insert into tasks values ('cleared', 'TASK-985: review', 'blocked', 'reviewer')")
    connection.commit()
    connection.close()
    open_rows = os.path.join(qa(), "TASK-980")
    os.makedirs(open_rows, exist_ok=True)
    open(os.path.join(open_rows, "test-results.md"), "w", encoding="utf-8").write("1 Not run\n")
    finished = os.path.join(qa(), "TASK-981")
    os.makedirs(finished, exist_ok=True)
    open(os.path.join(finished, "test-results.md"), "w", encoding="utf-8").write("1 ✅ evidences/a.png\n")
    waiting = os.path.join(qa(), "TASK-983")
    os.makedirs(waiting, exist_ok=True)
    open(os.path.join(waiting, "test-results.md"), "w", encoding="utf-8").write(
        f"2 waiting on the human {pack['name']}\n"
    )
    person = os.path.join(qa(), "TASK-984")
    os.makedirs(person, exist_ok=True)
    open(os.path.join(person, "test-results.md"), "w", encoding="utf-8").write("3 👤\n")
    cleared = os.path.join(qa(), "TASK-985")
    os.makedirs(cleared, exist_ok=True)
    open(os.path.join(cleared, "test-results.md"), "w", encoding="utf-8").write(
        f"1 Unblocked ✅ evidences/a.png\n2 no longer waiting on the human {pack['name']}\n"
    )
    assert return_unfinished(pack) == "3"
    connection = sqlite3.connect(path)
    review = connection.execute("select assignee, status from tasks where id = 'review'").fetchone()
    tester = connection.execute("select assignee, status from tasks where id = 'tester'").fetchone()
    stayed = connection.execute("select assignee, status from tasks where id = 'done-review'").fetchone()
    missing = connection.execute("select assignee, status from tasks where id = 'missing'").fetchone()
    human = connection.execute("select assignee, status from tasks where id = 'human'").fetchone()
    marked = connection.execute("select assignee, status from tasks where id = 'person'").fetchone()
    cleared_row = connection.execute("select assignee, status from tasks where id = 'cleared'").fetchone()
    connection.close()
    assert review == ("tester-1", "ready")
    assert tester == ("tester-1", "blocked")
    assert stayed == ("reviewer", "blocked")
    assert missing == ("reviewer", "blocked")
    assert human == ("tester-1", "ready")
    assert marked == ("tester-1", "ready")
    assert cleared_row == ("reviewer", "blocked")


@pytest.mark.parametrize("pack_file", PACKS)
def test_a_card_is_created_by_hermes_with_its_body_skills_and_parent(env, pack_file, monkeypatch):
    import sqlite3

    from cockpitlib.kanban import db_path, place_card

    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    pack = load(pack_file)
    ticket = f"{pack['tracker']['project']}-310"
    skill = sorted(pack["skills"]["kickoff"]["worker"])[0]
    parent = place_card(pack["board"], f"{ticket}: work", "worker-1", body=f"do it for {pack['name']}", skills=[skill])
    child = place_card(pack["board"], f"{ticket}: test", "tester-1", parents=[parent])
    parked = place_card(pack["board"], f"{ticket}: wait", "intake", "blocked")
    with pytest.raises(ValueError, match="ready or blocked"):
        place_card(pack["board"], f"{ticket}: run", "worker-1", "running")
    db = sqlite3.connect(db_path(pack["board"]))
    rows = {row[0]: row[1:] for row in db.execute("select id, status, body, skills, created_by from tasks")}
    links = db.execute("select parent_id, child_id from task_links").fetchall()
    db.close()
    assert parent.startswith("t_")
    assert rows[parent] == ("ready", f"do it for {pack['name']}", json.dumps([skill]), "cockpit")
    assert rows[child][0] == "todo"
    assert rows[parked][0] == "blocked"
    assert links == [(parent, child)]


@pytest.mark.parametrize("pack_file", PACKS)
def test_housekeeping_sees_a_block_hermes_recorded(env, pack_file, monkeypatch):
    import sqlite3

    from cockpitlib.housekeeping import STALE_RATE_LIMIT, settle_reviews, stamp_rate_limit, unblock_logins, unstrand
    from cockpitlib.kanban import BoardWrites, block_reason, board_cards, db_path, place_card

    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    pack = load(pack_file)
    board = pack["board"]
    ticket = f"{pack['tracker']['project']}-320"
    login = place_card(board, f"{ticket}: test", "tester-1")
    parked = place_card(board, f"{ticket}: work", "worker-1")
    other = place_card(board, f"{ticket}: other", "worker-1")
    writes = BoardWrites(board)
    reason = f"CREDENTIALS NEEDED · {pack['privileged']['environment']} · qa@{pack['name']}.test"
    writes.block(login, reason)
    writes.block(other, "missing the switch")
    assert writes.flush() == [True, True]
    db = sqlite3.connect(db_path(board))
    assert block_reason(db, login) == reason
    assert db.execute("select result from tasks where id = ?", (login,)).fetchone()[0] in (None, "")
    db.close()
    assert unblock_logins(pack) == "1"
    statuses = {card["id"]: card["status"] for card in board_cards(board)}
    assert statuses[login] == "ready" and statuses[other] == "blocked"
    stamp_rate_limit(pack, parked, ticket, now=1_000)
    assert {card["id"]: card["status"] for card in board_cards(board)}[parked] == "blocked"
    assert unstrand(pack, now=1_000 + STALE_RATE_LIMIT - 1) == "0"
    assert unstrand(pack, now=1_000 + STALE_RATE_LIMIT) == "1"
    assert {card["id"]: card["status"] for card in board_cards(board)}[parked] == "ready"
    review = put_card(board, f"{ticket}: review", "reviewer", "review")
    db = sqlite3.connect(db_path(board))
    db.execute("update tasks set result = ? where id = ?", (f"report for {pack['name']}", review))
    db.commit()
    db.close()
    assert settle_reviews(pack) == "1"
    db = sqlite3.connect(db_path(board))
    assert db.execute("select status, result from tasks where id = ?", (review,)).fetchone() == (
        "done",
        f"report for {pack['name']}",
    )
    assert db.execute(
        "select kind from task_events where task_id = ? order by id desc limit 1", (review,)
    ).fetchone() == ("completed",)
    db.close()


@pytest.mark.parametrize("pack_file", PACKS)
def test_a_twin_is_found_by_its_kind_not_its_words(env, pack_file, monkeypatch):
    from cockpitlib.kanban import BoardWrites, board_cards, card_title, open_twin, place_card

    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    pack = load(pack_file)
    board = pack["board"]
    ticket = f"{pack['tracker']['project']}-340"
    worded = place_card(board, f"{ticket}: propose a plan for {pack['name']}", "intake", kind="intake", ticket=ticket)
    assert open_twin(board, "intake", ticket) == worded
    assert {card["id"]: card["flow"] for card in board_cards(board)}[worded] == "intake"
    assert open_twin(board, "intake", f"{pack['tracker']['project']}-341") == ""
    ci = place_card(board, card_title("ci", ticket, sha="abc"), "analyst", kind="ci", ticket=ticket, key="abc")
    assert open_twin(board, "ci", ticket, "abc") == ci
    assert open_twin(board, "ci", ticket, "def") == ""
    writes = BoardWrites(board)
    writes.complete(ci, result="done")
    writes.flush()
    assert open_twin(board, "ci", ticket, "abc") == ""
    older = place_card(board, card_title("rework", ticket), "worker-1")
    assert open_twin(board, "rework", ticket, title=card_title("rework", ticket)) == older
    assert card_title("question", ticket) == f"{ticket}: question"


@pytest.mark.parametrize("pack_file", PACKS)
def test_records_land_in_the_packs_records_dir_and_are_committed_there(env, pack_file, monkeypatch):
    import subprocess

    from cockpitlib.ops import workspace_watch
    from cockpitlib.plan import init

    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    pack = load(pack_file)
    other = load(PACKS[0] if pack["name"] == "bravo" else PACKS[1])
    assert pack["records_dir"] != other["records_dir"]
    workspace = env["workspace"]
    subprocess.run(["git", "init", "-b", pack["workspace_branch"], str(workspace)], check=True, capture_output=True)
    ticket = f"{pack['tracker']['project']}-350"
    path = init(ticket, f"plan for {pack['name']}", "go")
    assert path == os.path.join(str(workspace), pack["records_dir"], "qa", ticket, "plan.md")
    assert not os.path.exists(os.path.join(str(workspace), other["records_dir"], "qa", ticket))
    os.utime(path, (1_000_000, 1_000_000))
    env_git = {
        **os.environ,
        "GIT_AUTHOR_NAME": "Dev",
        "GIT_AUTHOR_EMAIL": "dev@example.test",
        "GIT_COMMITTER_NAME": "Dev",
        "GIT_COMMITTER_EMAIL": "dev@example.test",
    }
    monkeypatch.setattr(os, "environ", env_git)
    workspace_watch(pack)
    logged = subprocess.run(
        ["git", "-C", str(workspace), "log", "--name-only", "--format=%s"], capture_output=True, text=True, check=True
    ).stdout
    assert f"{pack['records_dir']}/qa/{ticket}/plan.md" in logged


@pytest.mark.parametrize("pack_file", PACKS)
def test_a_second_ticket_does_not_attach_to_the_first_chat(env, pack_file, monkeypatch):
    from cockpitlib.chat import end_chat, open_chat

    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    monkeypatch.setenv("COCKPIT_CHAT_ARGV", "/bin/sleep 30")
    pack = load(pack_file)
    from cockpitlib.pack import agent_launch

    other = load(PACKS[0] if pack["name"] == "bravo" else PACKS[1])
    home = agent_launch(pack)["home"]
    assert home != agent_launch(other)["home"]
    first = open_chat("TASK-1")
    second = open_chat("TASK-2")
    own = open_chat("own")
    try:
        assert first["cwd"] == home and second["cwd"] == home
        assert own["cwd"] == os.environ["COCKPIT_WORKSPACE"]
        assert first["attached"] is False and second["attached"] is False and own["attached"] is False
        from cockpitlib import chat as chatmod

        assert chatmod._TERMS["TASK-1"].pid != chatmod._TERMS["TASK-2"].pid
        assert chatmod._TERMS["own"].pid not in (chatmod._TERMS["TASK-1"].pid, chatmod._TERMS["TASK-2"].pid)
        assert open_chat("TASK-1")["attached"] is True
        assert open_chat("TASK-2")["attached"] is True
        assert chatmod._TERMS["TASK-1"] is not chatmod._TERMS["TASK-2"]
    finally:
        end_chat("TASK-1")
        end_chat("TASK-2")
        end_chat("own")
    monkeypatch.delenv("COCKPIT_CHAT_ARGV", raising=False)
    try:
        open_chat("TASK-1")
        open_chat("own")
        from cockpitlib import chat as chatmod

        assert chatmod._TERMS["TASK-1"].argv == list(pack["providers"]["coding"]["command"])
        assert chatmod._TERMS["own"].argv != list(pack["providers"]["coding"]["command"])
    finally:
        end_chat("TASK-1")
        end_chat("own")
    from cockpitlib.chat import _coding_command

    monkeypatch.setattr(
        "cockpitlib.pack.load", lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("no pack"))
    )
    assert _coding_command() == []
    monkeypatch.setattr("cockpitlib.pack.load", lambda *_args, **_kwargs: {"providers": {"coding": {"command": []}}})
    assert _coding_command() == []
    monkeypatch.setattr(
        "cockpitlib.pack.load", lambda *_args, **_kwargs: {"providers": {"coding": {"command": "true"}}}
    )
    assert _coding_command() == []
    monkeypatch.setattr("cockpitlib.pack.load", lambda *_args, **_kwargs: {"providers": {"coding": {"command": [""]}}})
    assert _coding_command() == []


@pytest.mark.parametrize("pack_file", PACKS)
def test_a_ticket_chat_forks_the_lane_run(env, pack_file, monkeypatch):
    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    monkeypatch.delenv("COCKPIT_CHAT_ARGV", raising=False)
    pack = load(pack_file)
    other = load(PACKS[0] if pack["name"] == "bravo" else PACKS[1])
    pattern = pack["providers"]["coding"]["transcript_glob"]
    assert pattern != other["providers"]["coding"]["transcript_glob"]
    from cockpitlib.chat import (
        _coding_command,
        _context,
        _meta,
        _read_record,
        chat_state,
        coding_sessions,
        coding_tail,
        end_chat,
        lane_runs,
        open_chat,
    )
    from cockpitlib.paths import chat_dir, qa, root

    ticket = "TASK-8801"
    folder = pattern.replace("{root}", root()).replace("{ticket}", ticket)
    folder = folder[: folder.rfind("/")]
    os.makedirs(folder, exist_ok=True)
    older = os.path.join(folder, "run-old.jsonl")
    newer = os.path.join(folder, "run-new.jsonl")
    advisor = os.path.join(folder, "run-new-advisor.jsonl")
    open(older, "w", encoding="utf-8").write(
        "\n"
        '{"card":"c9","prompt":"older ' + pack["name"] + '"}\n'
        '{"type":"tool_result","output":"secret-tool"}\n'
        "[]\n"
        '{"command":"make check","output":"secret-tool","exit":1}\n' + "\n".join(["{}"] * 41) + "\n"
        '{"prompt":"too late"}\n'
    )
    open(newer, "w", encoding="utf-8").write("\n" + "not-json " + pack["name"] + "\n" + "[]\n")
    open(advisor, "w", encoding="utf-8").write('{"text":"side"}\n')
    os.utime(older, (1_700_000_000, 1_700_000_000))
    os.utime(newer, (1_700_000_100, 1_700_000_100))
    assert _meta("/no/such-transcript") == ("", "")
    assert _context("/no/such-transcript") == ""
    assert "secret-tool" not in _context(older)
    assert "make check" in _context(older)
    picked = [row["id"] for row in lane_runs(ticket)]
    assert picked == ["run-old", "run-new"]
    assert lane_runs("own") == []
    bare = coding_sessions("pipeline")
    assert bare == []
    os.makedirs(os.path.join(os.environ["COCKPIT_WT"], ticket), exist_ok=True)
    listed = coding_sessions("pipeline")
    assert [row["id"] for row in listed] == ["run-new", "run-old"]
    assert listed[0]["ticket"] == ticket
    assert listed[0]["prompt"].startswith("not-json")
    assert listed[0]["subagents"] and listed[0]["subagents"][0]["path"] == advisor
    assert listed[1]["prompt"].startswith("older")
    assert "run-new" in [row["id"] for row in coding_sessions("all")]
    open(newer + ".pid", "w", encoding="utf-8").write(str(os.getpid()))
    assert coding_sessions("all")[0]["running"] is True
    open(newer + ".pid", "w", encoding="utf-8").write("nope")
    assert coding_sessions("all")[0]["running"] is False
    open(newer + ".pid", "w", encoding="utf-8").write("0")
    assert coding_sessions("all")[0]["running"] is False
    open(newer + ".pid", "w", encoding="utf-8").write("999999")
    assert coding_sessions("all")[0]["running"] is False
    state = chat_state(ticket, "c9")
    assert state["best"]["session"] == "run-old"
    assert state["best"]["source"] == "c9"
    assert state["personal"] is False
    assert chat_state("own")["personal"] is True
    assert chat_state("own")["best"] == {}
    try:
        opened = open_chat(ticket, source="run-old")
        assert opened["attached"] is False
        assert opened["forked_from"] == "run-old"
        from cockpitlib import chat as chatmod

        assert chatmod._TERMS[ticket].argv == list(pack["providers"]["coding"]["command"])
        assert chatmod._TERMS[ticket].fork == older
        context = open(os.path.join(qa(), ticket, "fork-context.txt"), encoding="utf-8").read()
        assert "make check" in context and "secret-tool" not in context
        kept = opened["session"]
        chatmod._TERMS[ticket].alive = False
        resumed = open_chat(ticket)
        assert resumed["session"] == kept
        assert resumed["forked_from"] == "run-old"
        restarted = open_chat(ticket, reset=True, card="c9")
        assert restarted["session"] != kept
        assert restarted["forked_from"] == "run-old"
        stored = _read_record(ticket)
        assert stored["previous"][0]["session"] == kept
        own = open_chat("own")
        assert own["forked_from"] == ""
        assert chatmod._TERMS["own"].argv != list(pack["providers"]["coding"]["command"])
        assert chatmod._TERMS["own"].fork == ""
        assert _read_record("own")["personal"] is True
        other_ticket = "TASK-8802"
        other_dir = pattern.replace("{root}", root()).replace("{ticket}", other_ticket)
        other_dir = other_dir[: other_dir.rfind("/")]
        os.makedirs(other_dir, exist_ok=True)
        other_run = os.path.join(other_dir, "run-b.jsonl")
        open(other_run, "w", encoding="utf-8").write('{"prompt":"second"}\npartial')
        second = open_chat(other_ticket)
        assert second["forked_from"] == "run-b"
        assert chatmod._TERMS[other_ticket] is not chatmod._TERMS[ticket]
        assert chatmod._TERMS[other_ticket].fork == other_run
    finally:
        end_chat(ticket)
        end_chat("TASK-8802")
        end_chat("own")
    client = _client()
    page = client.get("/chat-state", params={"ticket": ticket, "card": "c9"}).json()
    assert page["best"]["session"] == "run-old"
    assert page["exists"] is True
    tail = client.get("/coding-tail", params={"path": newer, "offset": 0}).json()
    assert any(row["text"].startswith("not-json") for row in tail["entries"])
    partial = coding_tail(other_run, 0)
    assert partial["entries"][0]["text"] == "second"
    assert partial["offset"] < os.path.getsize(other_run)
    again = coding_tail(other_run, partial["offset"])
    assert again["lines"] == ["partial"]
    assert coding_tail("/etc/passwd", 0)["entries"] == []
    assert coding_tail(newer, -1)["offset"] >= 0
    assert coding_tail(newer, 10**9)["lines"]
    open(os.path.join(qa(), ticket, "chat.json"), "w", encoding="utf-8").write("{")
    assert _read_record(ticket) == {}
    open(os.path.join(qa(), ticket, "chat.json"), "w", encoding="utf-8").write("[1]")
    assert _read_record(ticket) == {}
    open(os.path.join(chat_dir(), "own.json"), "w", encoding="utf-8").write('{"session":"old","previous":"nope"}')
    try:
        reset_own = open_chat("own", reset=True)
        assert reset_own["forked_from"] == ""
        assert _read_record("own")["previous"][0]["session"] == "old"
    finally:
        end_chat("own")

    def no_mtime(_path):
        raise OSError("mtime")

    monkeypatch.setattr("cockpitlib.chat.os.path.getmtime", no_mtime)
    from cockpitlib.chat import _describe

    assert _describe(older, ticket)["mtime"] == 0
    assert coding_sessions("all")
    monkeypatch.setattr(
        "cockpitlib.chat.os.waitpid", lambda *_args, **_kwargs: (_ for _ in ()).throw(ChildProcessError())
    )
    try:
        open_chat("TASK-8810")
        import time

        time.sleep(0.3)
    finally:
        end_chat("TASK-8810")
    held_open = open

    def no_binary(path, mode="r", *args, **kwargs):
        if "b" in str(mode):
            raise OSError("binary")
        return held_open(path, mode, *args, **kwargs)

    monkeypatch.setattr("builtins.open", no_binary)
    assert coding_tail(newer, 0)["entries"] == []
    monkeypatch.setattr("cockpitlib.chat.os.path.getsize", lambda _path: (_ for _ in ()).throw(OSError("size")))
    assert coding_tail(newer, 0)["entries"] == []
    monkeypatch.setattr("cockpitlib.pack.load", lambda *_args, **_kwargs: {"providers": {"coding": "true"}})
    assert _coding_command() == []
    monkeypatch.setattr(
        "cockpitlib.pack.load",
        lambda *_args, **_kwargs: {"providers": {"coding": {"command": ["true"], "transcript_glob": 3}}},
    )
    assert coding_sessions("all") == []
    monkeypatch.setattr(
        "cockpitlib.pack.load",
        lambda *_args, **_kwargs: {
            "providers": {"coding": {"command": ["true"], "transcript_glob": "{root}/../x/{ticket}/*.jsonl"}}
        },
    )
    assert coding_sessions("all") == []
    monkeypatch.setattr(
        "cockpitlib.pack.load",
        lambda *_args, **_kwargs: {
            "providers": {"coding": {"command": ["true"], "transcript_glob": "relative/{ticket}/*.jsonl"}}
        },
    )
    assert coding_sessions("all") == []


def test_the_card_index_is_replaced_whole_so_a_reader_never_sees_half_a_file(env, monkeypatch):
    """cards.json is written to a temp file in its folder and moved over the old one: a write that fails midway leaves
    the previous index readable (the card fence reads it), and no temp file stays behind."""

    from cockpitlib import kanban
    from cockpitlib.kanban import card_entry, mark_card, remember_card

    remember_card("b", "t_1", "worker", "TASK-1", repos=["one"])
    mark_card("b", "t_1", seen=True)
    path = kanban._index_path()
    before = open(path, encoding="utf-8").read()
    present = sorted(os.listdir(os.path.dirname(path)))
    assert card_entry("b", "t_1") == {"kind": "worker", "ticket": "TASK-1", "key": "", "repos": ["one"], "seen": True}
    from cockpitlib import store

    real = os.write

    def torn(fd, data):
        real(fd, b'{"b": {"t_1": {"kind"')  # half a file, then the writer dies
        raise OSError("disk full")

    monkeypatch.setattr(store.os, "write", torn)
    for write in (
        lambda: remember_card("b", "t_2", "worker", "TASK-2", repos=["two"]),
        lambda: mark_card("b", "t_1", seen=False),
    ):
        with pytest.raises(OSError):
            write()
        assert open(path, encoding="utf-8").read() == before
        assert card_entry("b", "t_1")["repos"] == ["one"]
        assert sorted(os.listdir(os.path.dirname(path))) == present  # the temp file is gone
    monkeypatch.setattr(store.os, "write", real)
    remember_card("b", "t_2", "worker", "TASK-2", repos=["two"])
    assert card_entry("b", "t_2")["repos"] == ["two"] and sorted(os.listdir(os.path.dirname(path))) == present


# What each fixture attaches to cards: kind skills, repo skills, and its own wording for one kind.
CARD_SKILLS = {
    "acme": {
        "rework": ["local-review"],
        "ci": ["analyze-ticket"],
        "repo": ("api", ["pr-review"]),
        "title": ("analyst", "{ticket}: analysis"),
    },
    "bravo": {
        "pr-treat": ["finding-moderation"],
        "test-kickoff": ["jira-tickets"],
        "repo": ("ledger", ["open-prs"]),
        "title": ("pr-treat", "{ticket}: treat the PR"),
    },
}


@pytest.mark.parametrize("pack_file", PACKS)
def test_every_card_carries_its_kind_and_repo_skills_and_the_packs_wording(env, pack_file, monkeypatch):
    import subprocess

    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    pack = load(pack_file)
    expected = CARD_SKILLS[pack["name"]]
    other = CARD_SKILLS["bravo" if pack["name"] == "acme" else "acme"]
    from cockpitlib.acts import open_analyst, post_test_plan, treat_pr
    from cockpitlib.kanban import TITLES, board_cards, card_skills, card_title, open_twin
    from cockpitlib.outbox import extra_skills

    repo, repo_skills = expected["repo"]
    assert repo_skills != other["repo"][1]
    source = env["root"] / "repos" / repo
    if not (source / ".git").exists():
        source.mkdir(parents=True)
        subprocess.run(["git", "init", str(source)], check=True, capture_output=True)
        (source / "README").write_text("hello\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(source), "add", "README"], check=True, capture_output=True)
        subprocess.run(
            [
                "git",
                "-C",
                str(source),
                "-c",
                "user.name=Dev",
                "-c",
                "user.email=dev@example.test",
                "commit",
                "-m",
                "init",
            ],
            check=True,
            capture_output=True,
        )
    project = pack["tracker"]["project"]

    def skills_of(card):
        return next(row["skills"] for row in board_cards(pack["board"]) if row["id"] == card)

    made = {
        "rework": _client().post("/refusal-send-back", json={"ticket": f"{project}-61"}).json()["card_id"],
        "ci": open_analyst(pack, "ci", f"{project}-62", repos=[repo], sha="abc"),
        "pr-treat": treat_pr(pack, f"{project}-63", repo, 5)["card_id"],
        "test-kickoff": post_test_plan(pack, f"{project}-64", f"lane checks {pack['name']}\n")["card"],
    }
    repos = {"ci": [repo], "pr-treat": [repo]}
    for kind, card in made.items():
        assert skills_of(card) == [*expected.get(kind, []), *(repo_skills if kind in repos else [])], kind
        assert skills_of(card) == card_skills(pack, kind, repos.get(kind, ()))
    assert any(expected.get(kind) for kind in made) and any(other.get(kind) for kind in made)

    kind, wording = expected["title"]
    assert TITLES[kind] != wording and card_title(kind, f"{project}-65", pack=pack) == wording.format(
        ticket=f"{project}-65"
    )
    assert card_title(other["title"][0], f"{project}-65", pack=pack) == TITLES[other["title"][0]].format(
        ticket=f"{project}-65"
    )
    titles = {row["id"]: row for row in board_cards(pack["board"])}
    if kind == "pr-treat":
        assert titles[made["pr-treat"]]["title"] == wording.format(ticket=f"{project}-63")
        assert titles[made["pr-treat"]]["flow"] == "review"
    if kind == "analyst":
        card = open_analyst(pack, "analyst", f"{project}-65")
        assert titles.get(card) is None and board_cards(pack["board"])[-1]["title"] == wording.format(
            ticket=f"{project}-65"
        )
        assert open_analyst(pack, "analyst", f"{project}-65") == card
        assert open_twin(pack["board"], "analyst", f"{project}-65") == card

    # The router's one extra skill is counted beyond what the card already carries.
    carried = skills_of(made["pr-treat"])
    assert extra_skills(pack, "worker", [*carried, "test"], carried) == ["test"]
    assert len(extra_skills(pack, "worker", [*carried, "test"])) == 1 + len(carried)


@pytest.mark.parametrize("pack_file", PACKS)
def test_settle_reviews_ignores_an_old_review_file_and_unstrand_frees_a_ready_card_held_by_a_stale_rate_limit(
    env, pack_file, monkeypatch
):
    import sqlite3
    import time

    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    pack = load(pack_file)
    assert pack["board"] != _other(pack)["board"]
    from cockpitlib.housekeeping import SETTLED_RUN, settle_reviews, unstrand
    from cockpitlib.kanban import board_cards, db_path, place_card
    from cockpitlib.paths import qa

    ticket = "TASK-8880"
    folder = os.path.join(qa(), ticket)
    os.makedirs(folder, exist_ok=True)
    review = os.path.join(folder, "review.md")
    open(review, "w", encoding="utf-8").write(f"old findings {pack['name']}\n")
    card = put_card(pack["board"], f"{ticket}: review {pack['name']}", "reviewer", "review")
    made = time.time()
    os.utime(review, (made - 600, made - 600))
    assert settle_reviews(pack) == "0"  # written for an earlier card
    os.utime(review, (made + 5, made + 5))
    assert settle_reviews(pack) == "1"
    assert {row["id"]: row["status"] for row in board_cards(pack["board"])}[card] == "done"
    now = int(time.time())
    cards = {}
    for name, error, outcome, ended, claim in (
        ("stale", f"429 rate limit from {pack['name']}", "completed", now - SETTLED_RUN - 60, None),
        ("quota", "Quota exceeded for the day", None, None, None),
        ("fresh", "rate-limited", "completed", now - 30, None),
        ("crashed", "rate limit", "crashed", now - 4000, None),
        ("running", "rate limit", None, 0, None),
        ("claimed", "rate limit", "completed", now - 4000, "lock-1"),
        ("other", "disk full", "completed", now - 4000, None),
    ):
        cards[name] = place_card(pack["board"], f"{ticket}: {name} {pack['name']}", "worker-1", "ready")
        connection = sqlite3.connect(db_path(pack["board"]))
        connection.execute(
            "update tasks set last_failure_error = ?, claim_lock = ? where id = ?", (error, claim, cards[name])
        )
        if ended is not None:
            connection.execute(
                "insert into task_runs (task_id, status, started_at, ended_at, outcome) values (?, 'done', ?, ?, ?)",
                (cards[name], now - 5000, ended or None, outcome),
            )
        connection.commit()
        connection.close()
    assert unstrand(pack, now=now) == "2"
    connection = sqlite3.connect(db_path(pack["board"]))
    state = {
        row[0]: row[1:] for row in connection.execute("select id, status, last_failure_error, block_kind from tasks")
    }
    connection.close()
    assert state[cards["stale"]] == ("ready", None, "transient") and state[cards["quota"]] == (
        "ready",
        None,
        "transient",
    )
    for name in ("fresh", "crashed", "running", "claimed", "other"):
        assert state[cards[name]][0] == "ready" and state[cards[name]][1] is not None and state[cards[name]][2] is None
    assert unstrand(pack, now=now) == "0"


@pytest.mark.parametrize("pack_file", PACKS)
def test_each_card_gets_only_its_own_resume_note(env, pack_file, monkeypatch):
    import time

    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    pack = load(pack_file)
    from cockpitlib.chat import root
    from cockpitlib.paths import records_name
    from cockpitlib.resume import hook_context, latest_transcript, transcript_for

    folder = env["workspace"] / records_name() / "watch" / "transcripts"
    folder.mkdir(parents=True, exist_ok=True)
    crashed = json.dumps({"text": f"halfway {pack['name']}"}) + "\n"
    mine = folder / "card-a.jsonl"
    mine.write_text(crashed.replace("halfway", "mine"), encoding="utf-8")
    time.sleep(0.02)
    tagged = folder / "x.jsonl"
    tagged.write_text(
        json.dumps({"session_id": "sess-9", "text": "by session"}) + "\n" + "not json\n", encoding="utf-8"
    )
    time.sleep(0.02)
    sub = folder / "subagents"
    sub.mkdir()
    (sub / "card-a.jsonl").write_text(crashed.replace("halfway", "child"), encoding="utf-8")
    time.sleep(0.02)
    theirs = folder / "card-b.jsonl"
    theirs.write_text(crashed.replace("halfway", "theirs"), encoding="utf-8")
    assert latest_transcript() == str(theirs)
    monkeypatch.setenv("HERMES_KANBAN_TASK", "card-a")
    assert transcript_for({}) == str(mine)
    note = hook_context({"hook_event_name": "pre_llm_call", "is_first_turn": True}, pack)
    assert f"mine {pack['name']}" in note and "theirs" not in note and "child" not in note
    monkeypatch.setenv("HERMES_KANBAN_TASK", "card-none")
    assert transcript_for({}) == "" and hook_context({"is_first_turn": True}, pack) == ""
    monkeypatch.delenv("HERMES_KANBAN_TASK")
    assert transcript_for({"session_id": "sess-9"}) == str(tagged)
    assert transcript_for({"extra": {"task_id": "card-b"}}) == str(theirs)
    template = pack["providers"]["coding"]["transcript_glob"]
    lane_runs = template.replace("{root}", root()).replace("{ticket}", "T-1").rsplit("/", 1)[0]
    os.makedirs(lane_runs, exist_ok=True)
    globbed = os.path.join(lane_runs, "sess-77.jsonl")
    open(globbed, "w", encoding="utf-8").write(crashed)
    assert transcript_for({"session_id": "sess-77"}) == os.path.realpath(globbed)
    os.chmod(str(tagged), 0)
    try:
        assert transcript_for({"session_id": "sess-none"}) == ""
    finally:
        os.chmod(str(tagged), 0o644)


@pytest.mark.parametrize("pack_file", PACKS)
def test_the_machine_is_held_awake_only_while_a_lane_card_runs(env, pack_file, monkeypatch, tmp_path):
    import shutil
    import sqlite3
    import time

    import yaml

    from cockpitlib.errors import PackError

    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    pack = load(pack_file)
    assert pack["awake"] != _other(pack)["awake"]
    from cockpitlib.housekeeping import awake, run
    from cockpitlib.kanban import db_path, place_card

    log = os.path.join(os.environ["COCKPIT_ROOT"], "awake.log")
    assert awake({"board": pack["board"]}) == "0" and awake(pack) == "0"  # no command / no board yet
    card = place_card(pack["board"], f"{pack['tracker']['project']}-402: work", "worker-1", "ready")
    assert awake(pack) == "0" and not os.path.exists(log)
    connection = sqlite3.connect(db_path(pack["board"]))
    connection.execute("update tasks set status = 'running' where id = ?", (card,))
    connection.commit()
    connection.close()
    assert "awake: 1" in run(pack)
    for _ in range(50):
        if os.path.exists(log):
            break
        time.sleep(0.05)
    text = open(log, encoding="utf-8").read()
    assert ("acme-awake|-t 150" in text) is (pack["name"] == "acme") and ("north-nosleep 200" in text) is (
        pack["name"] == "bravo"
    )
    broken = {**pack, "awake": {"command": ["/no/such/awake"]}}
    with pytest.raises(RuntimeError, match="awake:"):
        awake(broken)
    name = os.path.basename(os.path.dirname(pack_file))
    copied = tmp_path / "packs" / name
    shutil.copytree(os.path.dirname(pack_file), copied)
    raw = yaml.safe_load((copied / "pack.yaml").read_text(encoding="utf-8"))
    for value, message in (
        ({"cmd": ["x"]}, "awake takes command"),
        ({"command": "x"}, "awake.command must be a command"),
    ):
        (copied / "pack.yaml").write_text(yaml.safe_dump({**raw, "awake": value}, sort_keys=False), encoding="utf-8")
        with pytest.raises(PackError, match=re.escape(message)):
            load(str(copied / "pack.yaml"))
