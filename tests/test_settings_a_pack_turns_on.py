# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Settings a pack turns on, each with its default: every behaviour here sits under a setting or fires only where the kernel
contradicted its own documented intent. Both fixture packs."""

import json
import os
import pathlib
import shutil
import sqlite3

import pytest
import yaml

from cockpitlib import test_flow
from cockpitlib.errors import CockpitError
from cockpitlib.pack import load
from tests.support import words
from tests.support.boards import put_card, raw

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PACKS = (os.path.join(ROOT, "packs", "acme", "pack.yaml"), os.path.join(ROOT, "packs", "bravo", "pack.yaml"))


def _copy_pack(pack_file, tmp_path, change) -> str:
    copied = tmp_path / "packs" / os.path.basename(os.path.dirname(pack_file))
    shutil.copytree(os.path.dirname(pack_file), copied)
    data = yaml.safe_load((copied / "pack.yaml").read_text(encoding="utf-8"))
    change(data, copied)
    (copied / "pack.yaml").write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    return str(copied / "pack.yaml")


def _wide(data, _dir):
    data.update(seats={**data["seats"], "slots": 3})


def _by_slot(data, _dir):
    _wide(data, _dir)
    data.update(lanes={"by_slot": True})


def _age(slug, card, when):
    connection = raw(slug)
    connection.execute("update tasks set created_at = ? where id = ?", (when, card))
    connection.commit()
    connection.close()


# 1. one lane set per ticket


@pytest.mark.parametrize("pack_file", PACKS)
def test_a_ticket_whose_slot_was_released_goes_back_to_the_seat_that_last_worked_it(
    env, pack_file, monkeypatch, tmp_path
):
    from cockpitlib.lanes import free_lane
    from cockpitlib.settings import frozen_path
    from cockpitlib.slots import write_owner, write_ticket

    base = load(_copy_pack(pack_file, tmp_path / "plain", _wide))
    pack_path = _copy_pack(pack_file, tmp_path, _by_slot)
    monkeypatch.setenv("COCKPIT_PACK", pack_path)
    pack = load(pack_path)
    ticket = "TASK-71"
    older = put_card(pack["board"], f"{ticket}: work", "worker-2", "done")
    newer = put_card(pack["board"], f"{ticket}: rework", "worker-3", "done")
    _age(pack["board"], older, 100)
    _age(pack["board"], newer, 200)
    put_card(pack["board"], f"{ticket}: tester", "tester-3", "done")
    write_owner(3, "free")  # the slot is released: slot_of finds nothing
    write_ticket(3, ticket)
    busy = {"worker-1": 0, "worker-3": 4, "tester-1": 0, "tester-3": 4}
    assert (
        free_lane("worker", pack, busy, ticket=ticket) == "worker-3"
    )  # the newest card of the kind, not the least loaded
    assert free_lane("tester", pack, busy, ticket=ticket) == "tester-3"
    assert free_lane("reviewer", pack, {}, ticket=ticket) == "reviewer"  # pooled kinds are unchanged
    assert free_lane("worker", pack, busy, ticket="TASK-72") == "worker-1"  # a ticket without cards: the least loaded
    assert free_lane("worker", base, busy, ticket=ticket) == "worker-1"  # without the setting: the least loaded
    write_owner(1, "lane:worker-1")  # a live slot still wins over the history
    write_ticket(1, ticket)
    assert free_lane("worker", pack, busy, ticket=ticket) == "worker-1"
    write_owner(1, "free")
    os.makedirs(os.path.dirname(frozen_path()), exist_ok=True)
    json.dump(["worker-3"], open(frozen_path(), "w", encoding="utf-8"))
    assert free_lane("worker", pack, busy, ticket=ticket) == "worker-2"  # frozen: the next newest seat of the ticket
    json.dump(["worker-3", "worker-2"], open(frozen_path(), "w", encoding="utf-8"))
    assert free_lane("worker", pack, busy, ticket=ticket) == "worker-1"  # none left: the least loaded


@pytest.mark.parametrize("pack_file", PACKS)
def test_the_tester_fallback_is_the_least_loaded_seat_not_the_first(env, pack_file, monkeypatch, tmp_path):
    from cockpitlib.housekeeping import _tester_lane
    from cockpitlib.kanban import db_path

    pack_path = _copy_pack(pack_file, tmp_path, _wide)
    monkeypatch.setenv("COCKPIT_PACK", pack_path)
    pack = load(pack_path)
    put_card(pack["board"], "TASK-73: test", "tester-1", "ready")
    put_card(pack["board"], "TASK-74: test", "tester-1", "running")
    connection = sqlite3.connect(f"file:{db_path(pack['board'])}?mode=ro", uri=True)
    try:
        assert _tester_lane(connection, "TASK-75", pack) == "tester-2"
        assert _tester_lane(connection, "TASK-73", pack) == "tester-1"  # the tester already on the ticket
    finally:
        connection.close()


@pytest.mark.parametrize("pack_file", PACKS)
def test_a_handoff_under_by_slot_keeps_the_chain_on_the_slots_seats(env, pack_file, monkeypatch, tmp_path):
    from cockpitlib.acts import session_handoff
    from cockpitlib.kanban import board_cards
    from cockpitlib.slots import write_owner, write_ticket

    pack_path = _copy_pack(pack_file, tmp_path, _by_slot)
    monkeypatch.setenv("COCKPIT_PACK", pack_path)
    pack = load(pack_path)
    write_owner(2, "human")
    write_ticket(2, "TASK-76")
    put_card(pack["board"], "TASK-77: work", "worker-1", "ready")  # worker-2 is not the least loaded by accident
    assert session_handoff(pack, 2, "").endswith("lane:worker-2")
    seats = {card["assignee"] for card in board_cards(pack["board"]) if card["ticket"] == "TASK-76"}
    assert {"worker-2", "tester-2"} <= seats


# 2. one open card per intent


def _client():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from dashboard.cockpit.router import router

    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def _comments(board, card):
    from cockpitlib.kanban import db_path

    connection = sqlite3.connect(f"file:{db_path(board)}?mode=ro", uri=True)
    rows = [row[0] for row in connection.execute("select body from task_comments where task_id = ?", (card,))]
    connection.close()
    return rows


def _status(board, card):
    from cockpitlib.kanban import board_cards

    return next(item["status"] for item in board_cards(board) if item["id"] == card)


@pytest.mark.parametrize("pack_file", PACKS)
def test_a_second_instruction_for_an_intent_goes_onto_the_card_that_already_carries_it(env, pack_file, monkeypatch):
    from cockpitlib import refusals
    from cockpitlib.gate import recard, return_intent
    from cockpitlib.intents import load as load_intent
    from cockpitlib.intents import save
    from cockpitlib.kanban import BoardWrites, board_cards, open_holder, open_twin
    from cockpitlib.outbox import create

    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    monkeypatch.delenv("COCKPIT_LANE", raising=False)
    pack = load(pack_file)
    ticket = f"{pack['tracker']['project']}-81"
    intent = create(pack, ticket, "ticket-done", "worker-1", "done", {})
    iid = intent["id"]
    first = return_intent(pack, iid, "write more", assignee="worker-1")["returned"]["card"]
    assert first and open_holder(pack["board"], iid) == first
    assert open_twin(pack["board"], "rework", ticket) == first  # the kickoff's twin check still finds it
    writes = BoardWrites(pack["board"])
    writes.block(first, "waiting for the human")
    writes.flush()
    again = return_intent(pack, iid, "and the table", assignee="worker-1")["returned"]
    assert again["card"] == first  # no second owner
    assert any("and the table" in line for line in _comments(pack["board"], first))
    assert _status(pack["board"], first) == "ready"  # a waiting holder is woken
    rework = [card for card in board_cards(pack["board"]) if card["ticket"] == ticket and card["flow"] == "rework"]
    assert len(rework) == 1
    # recard: the housekeeping step sees the holder and makes nothing
    kept = load_intent(iid)
    kept["returned"]["card"] = ""
    save(kept)
    assert recard(pack) == "1" and load_intent(iid)["returned"]["card"] == first
    assert len([card for card in board_cards(pack["board"]) if card["ticket"] == ticket]) == 1
    # a refusal of an amend of the same intent: Send back lands on the holder too
    refusals.record(ticket, "ticket-done", "", "worker-1", "the summary is thin", intent=iid)
    key = refusals.unresolved(pack)[0]["key"]
    answer = _client().post("/refusal-send-back", json={"key": key, "note": "say what changed"}).json()
    assert answer["card_id"] == first and "already carries" in answer["out"]
    assert any("say what changed" in line for line in _comments(pack["board"], first))
    assert refusals.unresolved(pack) == []
    # a refusal at create has no intent: a card as before
    refusals.record(ticket, "tracker-comment", "", "tester-2", "no table")
    key = refusals.unresolved(pack)[0]["key"]
    made = _client().post("/refusal-send-back", json={"key": key}).json()["card_id"]
    assert made != first and _status(pack["board"], made) in ("ready", "todo")
    # the holder done: the next return makes a new card
    writes.complete(first, result="done")
    writes.flush()
    assert open_holder(pack["board"], iid) == ""
    monkeypatch.setattr(
        "cockpitlib.gate.iso", lambda: "2026-10-28T23:59:59Z"
    )  # a return in a later second than the first
    assert return_intent(pack, iid, "once more", assignee="worker-1")["returned"]["card"] not in ("", first)


# 3. a returned intent keeps an owner until it is amended


@pytest.mark.parametrize("pack_file", PACKS)
def test_a_returned_intent_whose_cards_ended_without_an_amend_gets_one_close_out_card(env, pack_file, monkeypatch):
    from cockpitlib import housekeeping
    from cockpitlib.gate import closeout_returned, return_intent
    from cockpitlib.intents import load as load_intent
    from cockpitlib.intents import save
    from cockpitlib.kanban import BoardWrites, board_cards, open_holder
    from cockpitlib.outbox import create
    from cockpitlib.owners import own

    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    monkeypatch.delenv("COCKPIT_LANE", raising=False)
    pack = load(pack_file)
    board = pack["board"]
    ticket = f"{pack['tracker']['project']}-82"
    writes = BoardWrites(board)
    iid = create(pack, ticket, "ticket-done", "tester-1", "done", {})[
        "id"
    ]  # written by a tester: the close-out goes to a tester seat
    card = return_intent(pack, iid, "write more", assignee="tester-1")["returned"]["card"]
    behind = put_card(board, f"{ticket}: tester", "tester-1", "running")
    kept = load_intent(iid)
    kept["returned"]["chain"] = [["tester-1", behind]]
    save(kept)
    assert closeout_returned(pack) == "0"  # the rework card is still open
    writes.complete(card, result="done")
    writes.flush()
    assert closeout_returned(pack) == "0"  # a card behind it is still open
    writes.complete(behind, result="tested")
    writes.flush()
    assert closeout_returned(pack) == "1"
    made = load_intent(iid)["returned"]["closeout"]["card"]
    closeout = next(item for item in board_cards(board) if item["id"] == made)
    assert closeout["assignee"].startswith("tester") and closeout["status"] in ("ready", "todo")
    assert (
        f"amend {iid}" in closeout["body"]
        and card in closeout["body"]
        and behind in closeout["body"]
        and "write more" in closeout["body"]
    )
    assert open_holder(board, iid) == made  # it carries the intent: a send back lands on it
    assert closeout_returned(pack) == "0"  # one per return
    writes.complete(made, result="dropped")
    writes.flush()
    assert closeout_returned(pack) == "0"  # and none after it ended either
    # an amend resolved the return: nothing to close out
    other = create(pack, ticket, "ticket-done", "worker-1", "done", {})["id"]
    second = return_intent(pack, other, "more", assignee="worker-1")["returned"]["card"]
    writes.complete(second, result="done")
    writes.flush()
    kept = load_intent(other)
    kept["returned"]["resolved"] = "2026-10-28T12:00:00Z"
    save(kept)
    assert closeout_returned(pack) == "0"
    # a ticket a plugin runs is left to the plugin; a board that refuses the card keeps the reason and the step goes on
    third_ticket = f"{pack['tracker']['project']}-83"
    third = create(pack, third_ticket, "ticket-done", "worker-1", "done", {})["id"]
    writes.complete(return_intent(pack, third, "more", assignee="worker-1")["returned"]["card"], result="done")
    writes.flush()
    own("supervisor", [third_ticket])
    assert closeout_returned(pack) == "0"
    own("supervisor", [])
    with monkeypatch.context() as patched:

        def refused(*_args, **_kwargs):
            raise CockpitError("board down")

        patched.setattr("cockpitlib.kanban.place_card", refused)
        assert closeout_returned(pack) == "0" and load_intent(third)["returned"]["closeout_error"] == "board down"
    assert closeout_returned(pack) == "1" and "closeout_error" not in load_intent(third)["returned"]
    assert "closeout-returned" in dict(housekeeping.STEPS)
    # a card of a plugin's kind on the ticket: left to the plugin
    fourth_ticket = f"{pack['tracker']['project']}-84"
    fourth = create(pack, fourth_ticket, "ticket-done", "worker-1", "done", {})["id"]
    rework_card = return_intent(pack, fourth, "more", assignee="worker-1")["returned"]["card"]
    writes.complete(rework_card, result="done")
    writes.flush()
    with monkeypatch.context() as patched:
        patched.setattr("cockpitlib.housekeeping._owned_cards", lambda _pack: {rework_card: "supervisor"})
        assert closeout_returned(pack) == "0"
    assert closeout_returned(pack) == "1"


@pytest.mark.parametrize("pack_file", PACKS)
def test_a_close_out_comments_the_card_that_wrote_the_intent_when_the_pack_asks(env, pack_file, monkeypatch, tmp_path):
    from cockpitlib.gate import closeout_returned, return_intent
    from cockpitlib.intents import load as load_intent
    from cockpitlib.kanban import BoardWrites, open_holder
    from cockpitlib.outbox import create

    pack_path = _copy_pack(
        pack_file, tmp_path, lambda data, _dir: data.update(outbox={**(data.get("outbox") or {}), "comment_card": True})
    )
    monkeypatch.setenv("COCKPIT_PACK", pack_path)
    monkeypatch.delenv("COCKPIT_LANE", raising=False)
    pack = load(pack_path)
    ticket = f"{pack['tracker']['project']}-85"
    writer = put_card(pack["board"], f"{ticket}: work", "worker-1", "done")
    iid = create(pack, ticket, "ticket-done", writer, "done", {})["id"]
    assert open_holder(pack["board"], "") == ""
    card = return_intent(pack, iid, "more", assignee="worker-1")["returned"]["card"]
    writes = BoardWrites(pack["board"])
    writes.complete(card, result="done")
    writes.flush()
    assert closeout_returned(pack) == "1"
    made = load_intent(iid)["returned"]["closeout"]["card"]
    assert any("is still returned" in line and made in line for line in _comments(pack["board"], writer))


# 4. a thread row that says "changed differently, explained, the reviewer closes it"


@pytest.mark.parametrize("pack_file", PACKS)
def test_an_answered_row_replies_and_leaves_the_thread_open(env, pack_file, monkeypatch, tmp_path):
    from cockpitlib import patch_apply

    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    pack = load(pack_file)
    manifest = tmp_path / "threads.json"
    manifest.write_text(
        json.dumps(
            [
                {"n": 1, "comment_id": 4000, "thread": "PRRT_4000", "type": "Code"},
                {
                    "n": 2,
                    "comment_id": 4010,
                    "thread": "PRRT_4010",
                    "type": "Answered",
                    "reply": f"done with a token instead, see {pack['name']}",
                },
                {"n": 3, "comment_id": 4020, "thread": "PRRT_4020", "type": "Deferred", "reply": "later"},
            ]
        ),
        encoding="utf-8",
    )
    found = patch_apply.rows(str(manifest))
    answered = found[1]
    assert (
        answered["react"] is False
        and answered["resolve"] is False
        and answered["reply"].startswith("done with a token")
    )
    assert found[0]["react"] and found[0]["resolve"]
    planned = patch_apply.actions(found)
    assert planned[1] == {
        "id": "PRRT_4010",
        "react": False,
        "resolve": False,
        "reply": True,
        "leave_open": True,
        "body": answered["reply"],
    }
    assert patch_apply.leave_open(answered, False) and not patch_apply.leave_open(found[0], False)
    assert patch_apply.counts(found)["Answered"] == 1
    text = patch_apply.body({"repo": "r", "number": 7, "sha": "abc1234567", "branch": "b"}, found)
    assert (
        "1 code · 0 housekeeping · 1 deferred · 1 answered." in text
        and "| 2 | `4010` |  | Answered | reply, stays open |" in text
    )
    # an Answered row needs its reply; a Code row with a reply is still refused, now with the remedy
    for rows, message in (
        ([{"comment_id": 1, "type": "Answered"}], "an Answered row is answered with a reply"),
        ([{"comment_id": 1, "type": "Code", "reply": "no"}], "no reply; type it Answered"),
    ):
        manifest.write_text(json.dumps(rows), encoding="utf-8")
        with pytest.raises(CockpitError, match=message):
            patch_apply.rows(str(manifest))
    # the three older types read exactly as before
    manifest.write_text(
        json.dumps(
            [
                {"n": 1, "comment_id": 1, "thread": "T1", "type": "Code"},
                {"n": 2, "comment_id": 2, "thread": "T2", "type": "GitHub housekeeping"},
                {"n": 3, "comment_id": 3, "thread": "T3", "type": "Deferred", "reply": "later"},
            ]
        ),
        encoding="utf-8",
    )
    old = patch_apply.rows(str(manifest))
    assert [(row["react"], row["resolve"]) for row in old] == [(True, True), (True, True), (False, False)]
    assert "1 code · 1 housekeeping · 1 deferred." in patch_apply.body({"repo": "r", "number": 7}, old)


# 5. an advisor line that cannot be read is recorded, refused clearly, and holds the plan gate


@pytest.mark.parametrize("pack_file", PACKS)
def test_an_unread_advisor_line_holds_the_plan_gate_even_when_the_board_refuses_the_write(
    env, pack_file, monkeypatch, capsys
):
    from cockpitlib.advise import advise, calls
    from cockpitlib.cli import main
    from cockpitlib.kanban import BoardWrites, board_cards, place_card
    from cockpitlib.plan import init
    from cockpitlib.plan_gate import gate

    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    monkeypatch.delenv("COCKPIT_LANE", raising=False)
    pack = load(pack_file)
    entry = pack["advisor"]["checkpoints"]["C0"]
    answers = entry["answers"]
    ticket = f"{pack['tracker']['project']}-84"
    init(ticket, "plan", "go")
    card = place_card(pack["board"], f"{ticket}: work", "worker-1", "ready")
    assert gate(pack, card) == "auto"

    def refused(_self):
        raise CockpitError(
            "hermes board helper failed: delegate_task child contexts cannot mutate Kanban tasks or boards"
        )

    with monkeypatch.context() as patched:
        patched.setattr(BoardWrites, "flush", refused)
        result = advise(pack, "C0", ticket=ticket, card=card, said="ADVISOR: C0 = FINE")
    assert result["ok"] is False and result["board"].startswith("not written: hermes board helper failed")
    assert f"names none of {', '.join(answers)}" in result["reason"] and f"C0=<{'|'.join(answers)}>" in result["reason"]
    assert calls(ticket)[-1]["verdict"] == "" and calls(ticket)[-1]["card"] == card  # recorded all the same
    assert {item["id"]: item["status"] for item in board_cards(pack["board"])}[
        card
    ] == "ready"  # the block never landed
    assert gate(pack, card) == "human"  # the gate holds anyway
    with monkeypatch.context() as patched:  # the CLI prints and exits 1
        patched.setattr(BoardWrites, "flush", refused)
        assert main(["advise", "C0", "--ticket", ticket, "--card", card, "--said", "C0 = FINE"]) == 1
        printed = capsys.readouterr().out
        assert '"board": "not written' in printed and '"ok": false' in printed
        assert (
            main(["advise", "C0", "--ticket", ticket, "--card", card, "--said", f"ADVISOR: C0={answers[0]}"]) == 0
        )  # read: exit 0
    assert gate(pack, card) == "auto"  # a later line that reads releases it
    written = advise(pack, "C0", ticket=ticket, card=card, said=f"C0={answers[0]}")
    assert written["ok"] and written["board"] == "written"
    holding = (entry.get("block_on") or answers[1:])[0]
    advise(pack, "C0", ticket=ticket, card=card, said=f"C0={holding}")
    assert gate(pack, card) == "human"  # a holding verdict holds
    advise(pack, "C0", ticket=ticket, card=card, said=f"C0={answers[0]}")
    assert gate(pack, card) == "human"  # and stays held, as before


# 6. one browser per lane card


@pytest.mark.parametrize("pack_file", PACKS)
def test_under_browser_session_a_lanes_browser_exec_names_its_session_and_each_seat_has_its_own_harness(
    env, pack_file, monkeypatch, tmp_path
):
    from cockpitlib.doctor import _harness_problems
    from cockpitlib.egress import check_tool
    from cockpitlib.setup import _write_seat_env, seat_harness_home

    plain = _copy_pack(pack_file, tmp_path / "plain", lambda data, _dir: None)
    pack_path = _copy_pack(pack_file, tmp_path, lambda data, _dir: data.update(lanes={"browser_session": True}))
    for wrong in ({"browser_session": "yes"}, {"browser_session": True, "other": 1}):
        with pytest.raises(CockpitError, match="lanes takes"):
            load(
                _copy_pack(
                    pack_file, tmp_path / str(abs(hash(str(wrong)))), lambda data, _dir: data.update(lanes=wrong)
                )
            )
    pack = load(pack_path)
    assert pack["lanes"] == {"browser_session": True}
    # the egress check: a lane without a session is refused with the session to pass; a session, the human, or a pack
    # without the setting are untouched
    monkeypatch.setenv("COCKPIT_PACK", pack_path)
    monkeypatch.delenv("COCKPIT_LANE", raising=False)
    monkeypatch.delenv("COCKPIT_TICKET", raising=False)
    assert check_tool("browser_exec", {"code": "print(page_info())"}) == ""
    monkeypatch.setenv("COCKPIT_LANE", "tester-2")
    monkeypatch.setenv("COCKPIT_TICKET", "TASK-85")
    refused = check_tool("browser_exec", {"code": "print(page_info())"})
    assert refused.startswith("browser_exec needs a session") and 'session "tester-2-TASK-85"' in refused
    assert check_tool("browser_exec", {"code": "print(page_info())", "session": "tester-2-TASK-85"}) == ""
    assert check_tool("terminal", {"command": "ls"}) == ""
    monkeypatch.setenv("COCKPIT_PACK", plain)
    assert check_tool("browser_exec", {"code": "print(page_info())"}) == ""
    # the seat's .env: one BH_HOME line under the seat, written once, never over a person's or the pack's own
    folder = tmp_path / "profiles" / "tester-2"
    folder.mkdir(parents=True)
    env_path = str(folder / ".env")
    assert seat_harness_home(load(plain), env_path) == ""
    line = seat_harness_home(pack, env_path)
    assert line == f"BH_HOME={folder / 'browser-harness'}"
    _write_seat_env(pack, "tester-2", env_path, "tester")
    _write_seat_env(pack, "tester-2", env_path, "tester")
    written = open(env_path, encoding="utf-8").read().splitlines()
    assert written.count(line) == 1 and "COCKPIT_LANE=tester-2" in written
    assert _harness_problems(pack, "tester-2", str(folder), "\n".join(written)) == []
    assert _harness_problems(pack, "tester-2", str(folder), "COCKPIT_LANE=tester-2\n") == [
        "tester-2 env lacks BH_HOME (lanes.browser_session): cockpit setup --rerender --seat tester-2"
    ]
    assert _harness_problems(load(plain), "tester-2", str(folder), "COCKPIT_LANE=tester-2\n") == []
    open(env_path, "w", encoding="utf-8").write("BH_HOME=/somewhere/mine\n")
    _write_seat_env(pack, "tester-2", env_path, "tester")
    mine = open(env_path, encoding="utf-8").read().splitlines()
    assert "BH_HOME=/somewhere/mine" in mine and line not in mine
    _write_seat_env(load(plain), "tester-2", env_path, "tester")
    assert (
        "BH_HOME=/somewhere/mine" in open(env_path, encoding="utf-8").read()
    )  # a pack without the setting leaves it be


# 7. a test report's results post attaches the failed rows' screenshots and videos, those only


def _results(folder, rows):
    table = ["## Summary", "", "| # | Scenario | Result | Evidence |", "|---|---|---|---|", *rows]
    os.makedirs(folder, exist_ok=True)
    text = "# Results\n\n" + "\n".join(table) + "\n"  # written in the bound pack's own words
    (folder / "test-results.md").write_text(words.worded(test_flow.bound(), text), encoding="utf-8")


def _media(folder, *names):
    kept = words.evidence(test_flow.bound())
    (folder / kept).mkdir(parents=True, exist_ok=True)
    for name in names:
        (folder / kept / name).write_bytes(b"x")


@pytest.mark.parametrize("pack_file", PACKS)
def test_a_results_post_attaches_the_failed_rows_media_and_only_that(env, pack_file, monkeypatch, tmp_path):
    from cockpitlib.outbox import amend, create
    from cockpitlib.paths import qa, workspace
    from cockpitlib.test_flow import failed_media, run_pattern

    plain = load(pack_file)
    pack_path = _copy_pack(
        pack_file,
        tmp_path,
        lambda data, _dir: data.update(testflow={**(data.get("testflow") or {}), "attach": "failed"}),
    )
    with pytest.raises(CockpitError, match="testflow.attach is failed"):
        load(
            _copy_pack(
                pack_file,
                tmp_path / "wrong",
                lambda data, _dir: data.update(testflow={**(data.get("testflow") or {}), "attach": "all"}),
            )
        )
    monkeypatch.setenv("COCKPIT_PACK", pack_path)
    monkeypatch.delenv("COCKPIT_LANE", raising=False)
    pack = load(pack_path)
    ticket = f"{pack['tracker']['project']}-86"
    folder = pathlib.Path(qa()) / ticket
    first = folder / run_pattern(pack).format(n=1)
    _results(
        first,
        [
            "| 1 | login | ✅ Pass | [shot](evidences/1-login.png) |",
            "| 2 | export | ❌ **Fail** | [shot](evidences/2-export.png) [clip](evidences/2-export.mp4) [call](evidences/2.mcp.json) |",
            "| 3 | print | ❌ Fail | [clip](evidences/3-print.mov) |",
        ],
    )
    _media(first, "1-login.png", "2-export.png", "2-export.mp4", "2.mcp.json", "3-print.mov")
    rel = lambda name: os.path.relpath(str(first / words.evidence(pack) / name), workspace())
    assert failed_media(pack, ticket) == [
        rel("2-export.png"),
        rel("2-export.mp4"),
        rel("3-print.mov"),
    ]  # row order, no .mcp.json
    body = folder / "post.md"
    body.write_text(words.worded(pack, "# Test Run\n\nTested and Not Ok: rows 2 and 3 failed.\n"), encoding="utf-8")
    init = folder / "init.md"
    init.write_text(words.worded(pack, "# Test Run\n\nIn progress.\n"), encoding="utf-8")
    # a lane's results post gets the failed rows' media; its own --attach of a passed row is refused
    with pytest.raises(CockpitError, match="attaches only the failed rows"):
        create(
            pack,
            ticket,
            "tracker-comment",
            "t_1",
            "results",
            {"body_file": str(body), "probe_title": words.title(pack), "attach": [rel("1-login.png")]},
            created_by="tester-1",
        )
    made = create(
        pack,
        ticket,
        "tracker-comment",
        "t_1",
        "results",
        {"body_file": str(body), "probe_title": words.title(pack)},
        created_by="tester-1",
    )
    assert made["payload"]["attach"] == [rel("2-export.png"), rel("2-export.mp4"), rel("3-print.mov")]
    # an init is not a results post: what the lane passed stands (sorted, as before)
    kept = create(
        pack,
        ticket,
        "tracker-comment",
        "t_1",
        "init",
        {"body_file": str(init), "probe_title": words.title(pack), "attach": [rel("1-login.png")]},
        created_by="tester-1",
    )
    assert kept["payload"]["attach"] == [rel("1-login.png")]
    # the human's extra file rides along after the failures
    human = create(
        pack,
        ticket,
        "tracker-comment",
        "",
        "results",
        {"body_file": str(body), "probe_title": words.title(pack), "attach": [rel("1-login.png")]},
    )
    assert human["payload"]["attach"] == [
        rel("2-export.png"),
        rel("2-export.mp4"),
        rel("3-print.mov"),
        rel("1-login.png"),
    ]
    # a newer run with a failed row that has no screenshot or video is refused; --run picks the older run; an unknown run is refused
    second = folder / run_pattern(pack).format(n=2)
    _results(second, ["| 1 | login | ❌ Fail | [note](evidences/1.txt) |"])
    _media(second, "1.txt")
    with pytest.raises(CockpitError, match="row 1 failed without a screenshot or video"):
        amend(made["id"], payload={}, created_by="tester-1", pack=pack)
    older = amend(made["id"], payload={"run": first.name}, created_by="tester-1", pack=pack)
    assert (
        older["payload"]["attach"] == [rel("2-export.png"), rel("2-export.mp4"), rel("3-print.mov")]
        and older["payload"]["run"] == first.name
    )
    with pytest.raises(CockpitError, match="no test run nowhere"):
        amend(made["id"], payload={"run": "nowhere"}, created_by="tester-1", pack=pack)
    empty = folder / run_pattern(pack).format(n=3)
    empty.mkdir()
    with pytest.raises(CockpitError, match="has no test-results.md"):
        failed_media(pack, ticket, empty.name)
    # without the setting: today's behaviour, the lane's own sorted list
    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    before = create(
        plain,
        ticket,
        "tracker-comment",
        "t_1",
        "results",
        {"body_file": str(body), "probe_title": words.title(pack), "attach": [rel("3-print.mov"), rel("1-login.png")]},
        created_by="tester-1",
    )
    assert before["payload"]["attach"] == sorted([rel("3-print.mov"), rel("1-login.png")])


# 8. a pack without stores never gets an "empty copy" slot


@pytest.mark.parametrize("pack_file", PACKS)
def test_a_pack_without_stores_leaves_no_empty_copy_and_tolerates_one_left_behind(
    env, pack_file, monkeypatch, tmp_path
):
    from cockpitlib.acts import begin_change
    from cockpitlib.kanban import place_card
    from cockpitlib.slots import (
        _stores_path,
        apply_capacity,
        capture_baseline,
        data_ready,
        read_ticket,
        ready_answer,
        restore_baseline,
        state_dir,
        tester_slot,
        write_owner,
        write_ticket,
    )

    with_stores = load(pack_file)
    assert with_stores["stores"]
    pack_path = _copy_pack(pack_file, tmp_path, lambda data, _dir: data.pop("stores", None))
    monkeypatch.setenv("COCKPIT_PACK", pack_path)
    pack = load(pack_path)
    assert not pack.get("stores")
    capture_baseline(pack, 1)
    apply_capacity(pack, 1)
    assert not os.path.isfile(_stores_path(1))  # nothing to copy, no copy
    assert data_ready(pack, 1) == "ready" and ready_answer(1, pack) == "ready"
    os.makedirs(state_dir(1), exist_ok=True)
    json.dump([], open(_stores_path(1), "w", encoding="utf-8"))  # left behind by an older kernel
    assert data_ready(pack, 1) == "ready" and ready_answer(1, pack) == "ready"
    assert ready_answer(1) == "not ready empty copy"  # no pack to ask: the answer of before
    assert data_ready(with_stores, 1) == "not ready empty copy"  # a pack that declares stores still refuses it
    restore_baseline(1)
    assert not os.path.isfile(_stores_path(1))  # a reset clears it
    write_owner(1, "free")
    write_ticket(1, "")
    place_card(pack["board"], "TASK-87: intake", "intake", "ready")
    assert begin_change(pack, "TASK-87", "read the ticket", "lane:intake")["slot"] == 1 and read_ticket(1) == "TASK-87"
    write_owner(1, "lane:worker-1")
    open(os.path.join(state_dir(1), "state"), "w", encoding="utf-8").write("ready\n")  # the bring-up finished
    tester_slot(pack, "TASK-87", 1)  # no refusal: both checks pass
    # a pack with stores keeps its copy on a baseline and a reset
    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    capture_baseline(with_stores, 2)
    assert json.load(open(_stores_path(2), encoding="utf-8"))[0]["name"] == with_stores["stores"][0]["name"]
    restore_baseline(2)
    assert os.path.isfile(_stores_path(2))


# 9. the Inbox's "done, confirm?" row: once per ticket, and only for a ticket the human develops


@pytest.mark.parametrize("pack_file", PACKS)
def test_a_done_row_is_made_once_and_under_done_rows_developed_only_for_a_developed_ticket(
    env, pack_file, monkeypatch, tmp_path
):
    from cockpitlib.acts import answer_card, developed
    from cockpitlib.intents import all_intents, save
    from cockpitlib.kanban import place_card
    from cockpitlib.outbox import create
    from cockpitlib.owners import own
    from cockpitlib.paths import qa
    from cockpitlib.plugin_api import ack_tickets, done_waiting
    from cockpitlib.pr_watch import _ticket_done

    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    monkeypatch.delenv("COCKPIT_LANE", raising=False)
    pack = load(pack_file)
    project = pack["tracker"]["project"]
    done_of = lambda ticket: [row for row in all_intents(ticket) if row["type"] == "ticket-done"]
    # today's packs: a test card's plain go makes the row, but never a second one while it waits
    ticket = f"{project}-88"
    card = place_card(pack["board"], f"{ticket}: test", "tester-1", "blocked", kind="test", ticket=ticket, pack=pack)

    def waits(board, which):  # the tester asks again, the human answers go again
        from cockpitlib.kanban import BoardWrites

        writes = BoardWrites(board)
        writes.block(which, "the staging data changed: continue?")
        writes.flush()

    assert answer_card(pack, card, "go")["ok"] and len(done_of(ticket)) == 1
    waits(pack["board"], card)
    assert answer_card(pack, card, "go")["ok"] and len(done_of(ticket)) == 1
    assert done_waiting([ticket]) == [{"id": done_of(ticket)[0]["id"], "ticket": ticket}]
    assert ack_tickets([ticket]) == [done_of(ticket)[0]["id"]]
    waits(pack["board"], card)
    assert (
        answer_card(pack, card, "go")["ok"] and len(done_of(ticket)) == 2
    )  # acknowledged: a new go may make a new row
    # under kickoff.done_rows: developed, a test the human only asked for makes none
    for wrong in ({"done_rows": "all"}, {"done_rows": True}):
        with pytest.raises(CockpitError, match="kickoff"):
            load(
                _copy_pack(
                    pack_file,
                    tmp_path / str(abs(hash(str(wrong)))),
                    lambda data, _dir: data.update(kickoff={**(data.get("kickoff") or {}), **wrong}),
                )
            )
    pack_path = _copy_pack(
        pack_file,
        tmp_path,
        lambda data, _dir: data.update(kickoff={**(data.get("kickoff") or {}), "done_rows": "developed"}),
    )
    monkeypatch.setenv("COCKPIT_PACK", pack_path)
    strict = load(pack_path)
    tested = f"{project}-89"
    only_test = place_card(
        strict["board"], f"{tested}: test", "tester-1", "blocked", kind="test", ticket=tested, pack=strict
    )
    assert not developed(strict, tested)
    assert answer_card(strict, only_test, "go")["ok"] and done_of(tested) == []
    # what makes a ticket developed: a dev card, a session, an author PR record, a push, a plugin that runs it
    dev = f"{project}-90"
    place_card(strict["board"], f"{dev}: intake", "intake", "ready", kind="intake", ticket=dev, pack=strict)
    assert developed(strict, dev)
    with_session = f"{project}-91"
    os.makedirs(os.path.join(qa(), with_session), exist_ok=True)
    json.dump({"slot": 1}, open(os.path.join(qa(), with_session, "session.json"), "w", encoding="utf-8"))
    assert developed(strict, with_session)
    with_pr = f"{project}-92"
    repo = strict["repos"]["repos"][0]["name"]
    os.makedirs(os.path.join(qa(), with_pr, "pr"), exist_ok=True)
    json.dump(
        {"repo": repo, "number": 7, "role": "author", "merged": True, "url": "https://example/7"},
        open(os.path.join(qa(), with_pr, "pr", f"{repo}-7.json"), "w", encoding="utf-8"),
    )
    assert developed(strict, with_pr)
    reviewed = f"{project}-93"
    os.makedirs(os.path.join(qa(), reviewed, "pr"), exist_ok=True)
    json.dump(
        {"repo": repo, "number": 8, "role": "reviewer", "merged": True},
        open(os.path.join(qa(), reviewed, "pr", f"{repo}-8.json"), "w", encoding="utf-8"),
    )
    assert not developed(strict, reviewed)  # a teammate's PR the human reviewed
    owned = f"{project}-94"
    own("supervisor", [owned])
    assert developed(strict, owned)
    own("supervisor", [])
    assert not developed(strict, owned)
    pushed = f"{project}-98"
    save(
        {
            "id": f"{pushed}/001-push-branch",
            "type": "push-branch",
            "ticket": pushed,
            "status": "published",
            "created_at": "2026-10-28T10:00:00Z",
            "created_by": "worker-1",
            "payload": {"repo": repo, "branch": "work/x"},
        }
    )
    assert developed(strict, pushed)  # a push of its own
    # the watch's row: a merged author PR is a developed ticket, so it still gets its row, once
    with monkeypatch.context() as patched:  # the belt: the watch asks too
        patched.setattr("cockpitlib.acts.developed", lambda _pack, _ticket: False)
        assert _ticket_done(strict, with_pr) == ""
    assert (
        _ticket_done(strict, with_pr).endswith("-ticket-done")
        and _ticket_done(strict, with_pr) == ""
        and len(done_of(with_pr)) == 1
    )
    assert create(strict, with_pr, "ticket-done", "pr-watch", "again", {})["id"] == done_of(with_pr)[0]["id"]


# 10. the Desktop shows a lane's Brief as the lane wrote it: a table is a table, a fence is a fence


def test_a_briefs_table_and_fence_keep_their_lines_and_the_grid_keeps_its_labels():
    from cockpitlib.board_view import render_brief

    brief = "\n".join(
        [
            "**Changes:** two rows below",
            "",
            "| # | Row | What changed |",
            "|---:|---|---|",
            "| 1 | Q | `.cards:empty { display: none; }` |",
            "| 2 | B | advice blocks split |",
            "",
            "**Issue:** one line",
            "and its continuation",
            "- first item",
            "- second item",
            "",
            "```css",
            "a { color: red; }",
            "",
            "b { color: blue; }",
            "```",
            "**Steps:** do it",
            "1. open the page",
            "2. print it",
        ]
    )
    out = render_brief(brief)
    assert "<table>" in out and "<td>1</td>" in out and "<code>.cards:empty { display: none; }</code>" in out
    assert out.count("<tr>") == 3 and "| # |" not in out
    assert (
        '<div class="k">Changes</div>' in out
        and '<div class="k">Issue</div>' in out
        and '<div class="k">Steps</div>' in out
    )
    assert "one line and its continuation" in out  # plain lines still join
    assert "<li>first item</li><li>second item</li>" in out
    assert (
        '<pre><code class="language-css">a { color: red; }\n\nb { color: blue; }' in out
    )  # the blank line inside the fence stays
    assert "<ol>" in out or "<li>open the page</li>" in out  # the numbered list is a list
    assert render_brief("**Issue:** one\n\n**Evidence:**\n- one evidence") == render_brief(
        "**Issue:** one\n**Evidence:**\n- one evidence"
    )
    bare = render_brief("| a | b |\n|---|---|\n| 1 | 2 |")  # a Brief that opens with a table, no label
    assert "<table>" in bare and "<td>2</td>" in bare and '<div class="k"></div>' in bare


@pytest.mark.parametrize("pack_file", PACKS)
def test_the_page_gets_lane_written_markdown_rendered_beside_the_text(env, pack_file, monkeypatch):
    from cockpitlib import inbox, refusals
    from cockpitlib.gate import return_intent
    from cockpitlib.intents import load as load_intent
    from cockpitlib.intents import save
    from cockpitlib.kanban import BoardWrites, place_card
    from cockpitlib.outbox import create, hold

    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    monkeypatch.delenv("COCKPIT_LANE", raising=False)
    pack = load(pack_file)
    ticket = f"{pack['tracker']['project']}-95"
    client = _client()
    # a hold's ask and reason, a return's instruction, the endorsement's notes
    iid = create(pack, ticket, "ticket-done", "worker-1", "done", {})["id"]
    hold(iid, "the table has **two** gaps: `row 3`", pack=pack, ask="Drop it, or keep `row 3`?")
    row = next(item for item in client.get("/list").json()["rows"] if item["id"] == iid)
    assert row["hold"]["reason"].startswith("the table has **two**")  # the text stays
    assert "<strong>two</strong>" in row["hold_html"]["reason"] and "<code>row 3</code>" in row["hold_html"]["ask"]
    return_intent(pack, iid, "say it as a `list`:\n- one\n- two", assignee="worker-1")
    row = next(item for item in client.get("/list").json()["rows"] if item["id"] == iid)
    assert "<li>one</li>" in row["returned_html"]["instruction"] and row["returned"]["instruction"].startswith("say it")
    kept = load_intent(iid)
    kept["endorsement"] = {
        "by": "gatekeeper",
        "risk": "low",
        "notes": "checked the *rows*",
        "time": "2026-10-28T10:00:00Z",
    }
    save(kept)
    row = next(item for item in client.get("/list").json()["rows"] if item["id"] == iid)
    assert "<em>rows</em>" in row["endorsed_html"]["notes"]
    plain = create(
        pack, f"{pack['tracker']['project']}-97", "ticket-done", "worker-1", "done", {}
    )  # nothing held, returned or endorsed
    row = next(item for item in client.get("/list").json()["rows"] if item["id"] == plain["id"])
    assert row["hold_html"] == {} and row["returned_html"] == {} and row["endorsed_html"] == {}
    # a refusal's reason
    refusals.record(ticket, "tracker-comment", "", "tester-2", "no `Summary` table")
    shown = refusals.unresolved(pack)[0]
    assert shown["reason"] == "no `Summary` table" and "<code>Summary</code>" in shown["reason_html"]
    # a plugin row's brief and what it said
    folder = os.path.join(inbox._root(), "inbox", "demo")
    os.makedirs(folder, exist_ok=True)
    json.dump(
        {
            "id": "r1",
            "what": "a release waits",
            "detail": {"brief": "release **3.2** waits", "said": "refused: `x`", "fields": []},
        },
        open(os.path.join(folder, "r1.json"), "w", encoding="utf-8"),
    )
    detail = next(item for item in inbox.rows() if item["id"] == "r1")["detail"]
    assert (
        detail["brief"] == "release **3.2** waits"
        and "<strong>3.2</strong>" in detail["brief_html"]
        and "<code>x</code>" in detail["said_html"]
    )
    # a card's Brief is read from the whole comment, not the page's 4,000-character cut
    card = place_card(pack["board"], f"{ticket}: work", "worker-1", "ready")
    writes = BoardWrites(pack["board"])
    writes.comment(card, "worker-1", ("filler " * 900) + "\n\n### Brief\n**Result:** found past the cut\n")
    writes.flush()
    shown = client.get(f"/card-detail?id={card}").json()
    assert "found past the cut" in shown["brief"] and len(shown["comments"][0]["text"]) == 4000


# 11. a lane's newer review of a PR drops its older one that is not on the forge yet


@pytest.mark.parametrize("pack_file", PACKS)
def test_under_supersede_reviews_a_newer_lane_review_drops_the_older_unposted_one(
    env, pack_file, monkeypatch, tmp_path
):
    from cockpitlib.intents import load as load_intent
    from cockpitlib.intents import save
    from cockpitlib.outbox import create

    pack_path = _copy_pack(
        pack_file,
        tmp_path,
        lambda data, _dir: data.update(outbox={**(data.get("outbox") or {}), "supersede_reviews": True}),
    )
    with pytest.raises(CockpitError, match="supersede_reviews"):
        load(
            _copy_pack(
                pack_file,
                tmp_path / "wrong",
                lambda data, _dir: data.update(outbox={**(data.get("outbox") or {}), "supersede_reviews": "yes"}),
            )
        )
    monkeypatch.setenv("COCKPIT_PACK", pack_path)
    monkeypatch.delenv("COCKPIT_LANE", raising=False)
    pack = load(pack_path)
    plain = load(pack_file)
    ticket = f"{pack['tracker']['project']}-96"
    repo = pack["repos"]["repos"][0]["name"]
    review = lambda who, number=355, **extra: create(
        pack if not extra.pop("plain", False) else plain,
        ticket,
        "pr-review-submit",
        "t_r",
        "review",
        {"repo": repo, "number": number, "sha": "abc1234", "body": "looks fine", **extra},
        created_by=who,
    )
    first = review("reviewer")
    posted = review("reviewer", number=356)
    kept = load_intent(posted["id"])
    kept["status"] = "posted"
    save(kept)
    human = review("human")
    second = review("reviewer")
    assert (
        load_intent(first["id"])["status"] == "dropped"
        and load_intent(first["id"])["dropped"]["reason"] == f"superseded by {second['id']}"
    )
    assert load_intent(posted["id"])["status"] == "posted"  # on the forge: the human's call
    assert load_intent(human["id"])["status"] != "dropped"  # the human's own stays
    assert load_intent(second["id"])["status"] != "dropped"
    third = review("reviewer", plain=True)  # without the setting: nothing dropped
    assert load_intent(second["id"])["status"] != "dropped" and load_intent(third["id"])["status"] != "dropped"


# 12. the plugin API: a run limit on a started card, archiving a plugin's own card, a run's outcome and error


@pytest.mark.parametrize("pack_file", PACKS)
def test_a_plugin_starts_a_card_with_a_run_limit_and_archives_its_own_cards(env, pack_file, monkeypatch):
    from cockpitlib import plugin_api
    from cockpitlib.kanban import open_cards, place_card

    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    monkeypatch.delenv("COCKPIT_LANE", raising=False)
    pack = load(pack_file)
    from cockpitlib.settings import load as load_settings
    from cockpitlib.settings import save as save_settings

    save_settings(
        pack, {"seats": {**load_settings(pack)["seats"], "slots": 2}}
    )  # two tickets' worker cards: a slot each
    board = pack["board"]
    ticket = f"{pack['tracker']['project']}-99"
    assert plugin_api.API_VERSION == 1

    def limit_of(card):
        connection = sqlite3.connect(
            f"file:{__import__('cockpitlib.kanban', fromlist=['db_path']).db_path(board)}?mode=ro", uri=True
        )
        try:
            return connection.execute("select max_runtime_seconds from tasks where id = ?", (card,)).fetchone()[0]
        finally:
            connection.close()

    # R1: the limit reaches the task; the default carries none; a bad value is refused before anything starts
    for bad in (-1, "1800", True, 1.5):
        with pytest.raises(CockpitError, match="max_runtime_seconds is a whole number"):
            plugin_api.start_card("rework", ticket, policy="release", max_runtime_seconds=bad)
    assert plugin_api.board_cards(ticket) == []
    limited = plugin_api.start_card("rework", ticket, body="unit 1", policy="release", max_runtime_seconds=1800)
    assert limit_of(limited["card_id"]) == 1800
    other = f"{pack['tracker']['project']}-100"
    plain = plugin_api.start_card("rework", other, body="unit 2", policy="release")
    assert limit_of(plain["card_id"]) in (None, 0)
    # R2: a plugin archives only a card of a kind it owns; the reason is commented first; a running worker is ended
    plugin_api.register_card_kind("sv-check", "{ticket}: sv check", flow="review", role="reviewer", owner="supervisor")
    mine = place_card(board, f"{ticket}: sv check", "reviewer", "ready", kind="sv-check", ticket=ticket, pack=pack)
    connection = raw(board)
    connection.execute("update tasks set status = 'running' where id = ?", (mine,))
    connection.execute(
        "insert into task_runs (task_id, status, started_at, outcome, error) values (?, 'running', 1, NULL, NULL)",
        (mine,),
    )
    connection.commit()
    connection.close()
    assert open_cards(board).get("reviewer", 0) >= 1
    with pytest.raises(CockpitError, match=f"card {limited['card_id']} is not supervisor's"):
        plugin_api.archive(limited["card_id"], "replaced", "supervisor")  # cockpit's own kind
    with pytest.raises(CockpitError, match="is not ledger's"):
        plugin_api.archive(mine, "replaced", "ledger")  # another plugin
    with pytest.raises(CockpitError, match="is not supervisor's"):
        plugin_api.archive("t_nowhere", "replaced", "supervisor")
    done = plugin_api.archive(mine, "replaced: the unit's branch moved", "supervisor")
    assert done == {"archived": True, "was_running": True}
    assert next(card for card in plugin_api.board_cards(ticket) if card["id"] == mine)["status"] == "archived"
    assert [line for line in _comments(board, mine) if "branch moved" in line]
    assert plugin_api.archive(mine, "again", "supervisor") == {"archived": False, "was_running": False}
    assert len([line for line in _comments(board, mine) if "again" in line]) == 0
    assert open_cards(board).get("reviewer", 0) == 0  # it counts in no capacity
    # R3: a run carries Hermes's outcome and error as recorded
    run = plugin_api.runs(mine)[-1]
    assert {"id", "status", "outcome", "error", "summary", "metadata", "profile", "started_at", "ended_at"} <= set(run)
    assert run["outcome"] == "reclaimed" and run["status"] == "reclaimed"
    connection = raw(board)
    connection.execute(
        "insert into task_runs (task_id, status, started_at, outcome, error) values (?, 'failed', 2, 'failed', 'elapsed 1900s > limit 1800s')",
        (mine,),
    )
    connection.commit()
    connection.close()
    assert plugin_api.runs(mine)[-1]["error"].startswith("elapsed")
