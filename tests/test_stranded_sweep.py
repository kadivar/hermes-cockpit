# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""A pending intent the gatekeeper's sweep card ended without endorsing or holding had no row and no sweep request:
it stayed pending for good and kept its ticket from being done. Now the sweep is asked for again, and after the pack's
`outbox.sweep_passes` such sweeps (default 2) the intent is one Inbox row with Sweep now, Send back and Drop."""

import json
import os

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from cockpitlib import gate, own_rows
from cockpitlib.errors import PackError
from cockpitlib.inbox import rows
from cockpitlib.intents import load as load_intent
from cockpitlib.kanban import BoardWrites, board_cards
from cockpitlib.outbox import create, endorse
from cockpitlib.pack import load
from tests.test_settings_a_pack_turns_on import _copy_pack

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PACKS = (os.path.join(ROOT, "packs", "acme", "pack.yaml"), os.path.join(ROOT, "packs", "bravo", "pack.yaml"))


def _client():
    from dashboard.cockpit.router import router

    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def _setup(monkeypatch, pack_file):
    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    monkeypatch.delenv("COCKPIT_LANE", raising=False)
    pack = load(pack_file)
    return pack, pack["repos"]["repos"][0]["name"], f"{pack['tracker']['project']}-3101"


def _sweep_cards(pack) -> list:
    return [card for card in board_cards(pack["board"], pack) if card["flow"] == "sweep"]


def _finish(pack, card) -> None:
    writes = BoardWrites(pack["board"])
    writes.complete(card, result="swept")
    writes.flush()


def _own_rows() -> list:
    return [row for row in rows() if row["plugin"] == "cockpit" and row["id"].startswith(gate.STRANDED_ROW)]


@pytest.mark.parametrize("pack_file", PACKS)
def test_a_pending_intent_two_sweeps_left_undecided_is_swept_again_and_then_a_row(env, pack_file, monkeypatch):
    pack, repo, ticket = _setup(monkeypatch, pack_file)
    left = create(pack, ticket, "pr-comment", "c", "note", {"repo": repo, "number": 1, "body": "a note"})
    decided = create(pack, ticket, "ci-rerun", "c", "rerun", {"repo": repo, "run_id": 7})
    assert gate.sweep(pack) == "1"
    first = _sweep_cards(pack)[0]["id"]
    endorse(decided["id"], "low", "", "gatekeeper", "fixture-a", "fixture-large", pack=pack)
    _finish(pack, first)  # the card ended and said nothing about the other intent
    assert gate.sweep(pack) == "1"  # asked again: a second gatekeeper card, for the intent the first one left
    second = [card for card in _sweep_cards(pack) if card["id"] != first]
    assert len(second) == 1 and left["id"] in second[0]["body"] and decided["id"] not in second[0]["body"]
    assert _own_rows() == []  # one more sweep first
    _finish(pack, second[0]["id"])
    assert gate.sweep(pack) == "0"  # no third card: the intent is the human's now
    found = _own_rows()
    assert len(found) == 1 and left["id"] in found[0]["what"] and found[0]["ticket"] == ticket
    assert [action["label"] for action in found[0]["detail"]["actions"]] == ["Sweep now", "Send back", "Drop"]
    at = found[0]["at"]
    assert (
        gate.sweep(pack) == "0" and len(_sweep_cards(pack)) == 2 and _own_rows()[0]["at"] == at
    )  # one row, written once
    shown = _client().get("/needs-you").json()["plugins"]
    assert [row["id"] for row in shown if row["plugin"] == "cockpit"] == [found[0]["id"]]
    # Sweep now: the count starts over, a sweep is queued and the row leaves
    pressed = _client().post("/plugin-act", json={"plugin": "cockpit", "id": found[0]["id"], "index": 0}).json()
    assert pressed["ok"] is True and pressed["applied"] is True and "sweep is queued" in pressed["out"]
    assert _own_rows() == [] and gate.sweep(pack) == "1"
    third = [card for card in _sweep_cards(pack) if card["status"] != "done"][0]["id"]
    endorse(left["id"], "low", "", "gatekeeper", "fixture-a", "fixture-large", pack=pack)
    _finish(pack, third)
    assert gate.sweep(pack) == "0" and _own_rows() == []
    assert not os.path.exists(gate._outbox_file("_sweep.passes.json"))  # nothing is counted once it is decided


@pytest.mark.parametrize("pack_file", PACKS)
def test_the_row_sends_the_intent_back_or_drops_it(env, pack_file, monkeypatch, tmp_path):
    pack_path = _copy_pack(
        pack_file, tmp_path, lambda data, _dir: data.update(outbox={**(data.get("outbox") or {}), "sweep_passes": 1})
    )
    pack, repo, ticket = _setup(monkeypatch, pack_path)
    assert gate.sweep_passes(pack) == 1 and gate.sweep_passes(load(pack_file)) == 2
    for bad in (0, 11, True, "2"):
        with pytest.raises(PackError, match="sweep_passes"):
            load(
                _copy_pack(
                    pack_file, tmp_path / f"bad-{bad}", lambda data, _dir: data.update(outbox={"sweep_passes": bad})
                )
            )
    back = create(pack, ticket, "pr-comment", "c", "note", {"repo": repo, "number": 1, "body": "a note"})
    gone = create(pack, ticket, "ci-rerun", "c", "rerun", {"repo": repo, "run_id": 7})
    done = create(pack, ticket, "ticket-done", "c", "done", {})  # the human's own row already: never counted
    assert gate.sweep(pack) == "1"
    _finish(pack, _sweep_cards(pack)[0]["id"])
    assert gate.sweep(pack) == "0"  # with one pass allowed the first undecided sweep is enough
    found = {row["id"]: row for row in _own_rows()}
    assert len(found) == 2 and not any(done["id"] in row["what"] for row in found.values())
    client = _client()
    back_row = next(ident for ident, row in found.items() if back["id"] in row["what"])
    gone_row = next(ident for ident, row in found.items() if gone["id"] in row["what"])
    sent = client.post("/plugin-act", json={"plugin": "cockpit", "id": back_row, "index": 1}).json()
    assert sent["ok"] is True and "back to worker" in sent["out"]
    returned = load_intent(back["id"])
    assert returned["status"] == "returned" and "did not decide" in returned["returned"]["instruction"]
    dropped = client.post("/plugin-act", json={"plugin": "cockpit", "id": gone_row, "index": 2}).json()
    assert dropped["ok"] is True and load_intent(gone["id"])["status"] == "dropped"
    assert load_intent(gone["id"])["human"]["note"] == "dropped: no sweep decided it"
    assert _own_rows() == [] and gate.sweep(pack) == "0"
    # a lane cannot press the human's buttons
    monkeypatch.setenv("COCKPIT_LANE", "worker-1")
    assert client.post("/plugin-act", json={"plugin": "cockpit", "id": back_row, "index": 0}).status_code == 400


@pytest.mark.parametrize("pack_file", PACKS[:1])
def test_an_amend_starts_the_count_over_and_owned_or_halted_tickets_get_no_row(env, pack_file, monkeypatch):
    from cockpitlib.halt import write as halt
    from cockpitlib.outbox import amend
    from cockpitlib.owners import own

    pack, repo, ticket = _setup(monkeypatch, pack_file)
    left = create(pack, ticket, "pr-comment", "c", "note", {"repo": repo, "number": 1, "body": "a note"})
    for expected in ("1", "1"):
        assert gate.sweep(pack) == expected
        _finish(pack, [card for card in _sweep_cards(pack) if card["status"] != "done"][0]["id"])
    own("supervisor", [ticket])
    assert gate.sweep(pack) == "0" and _own_rows() == []  # a plugin runs the ticket: its plugin decides, no row
    own("supervisor", [])
    halt(ticket, "stop")
    assert gate.sweep(pack) == "0" and _own_rows() == []
    os.remove(__import__("cockpitlib.halt", fromlist=["path"]).path(ticket))
    assert gate.sweep(pack) == "0" and len(_own_rows()) == 1
    amend(left["id"], summary="changed", pack=pack)  # a changed intent is a new question for the gatekeeper
    assert gate.sweep(pack) == "1" and _own_rows() == []
    state = (
        json.load(open(gate._outbox_file("_sweep.passes.json"), encoding="utf-8"))
        if os.path.exists(gate._outbox_file("_sweep.passes.json"))
        else {}
    )
    assert left["id"] not in state
    # an intent that is gone, a broken counts file and a serving file from before this change are all read without failing
    with open(gate._outbox_file("_sweep.passes.json"), "w", encoding="utf-8") as handle:
        json.dump({f"{ticket}/999-pr-comment": {"n": 5, "stamp": "x"}}, handle)
    assert gate.sweep(pack) == "running"  # nothing is looked at while a sweep card is open
    gate._stranded_rows(pack)
    assert not os.path.exists(gate._outbox_file("_sweep.passes.json"))
    with open(gate._outbox_file("_sweep.passes.json"), "w", encoding="utf-8") as handle:
        handle.write("[]")
    assert gate._passes() == {}
    with open(gate._outbox_file("_sweep.passes.json"), "w", encoding="utf-8") as handle:
        handle.write("not json")
    assert gate._passes() == {}
    open_card = [card for card in _sweep_cards(pack) if card["status"] != "done"][0]["id"]
    with open(gate._outbox_file("_sweep.serving"), "w", encoding="utf-8") as handle:
        handle.write(open_card + "\n")  # the old shape: the card alone
    _finish(pack, open_card)
    assert gate.sweep(pack) == "0" and gate._passes() == {}
    with pytest.raises(FileNotFoundError):
        gate.sweep_again(f"{ticket}/998-pr-comment")


def test_a_press_that_is_refused_says_why_on_the_row_and_can_be_pressed_again(bare, monkeypatch):
    pack, repo, ticket = _setup(monkeypatch, PACKS[0])
    from cockpitlib.inbox import put_row, queue_act

    actions = [
        {"label": "Drop", "act": {"do": "drop", "intent": f"{ticket}/001-ci-rerun"}},
        {"label": "Odd", "act": {"do": "nope"}},
    ]
    put_row("cockpit", {"id": "stranded-x", "what": "x", "detail": {"title": "x", "actions": actions}})
    client = _client()
    refused = client.post("/plugin-act", json={"plugin": "cockpit", "id": "stranded-x", "index": 0}).json()
    assert refused["ok"] is False and refused["out"].startswith("refused: no intent")
    row = next(item for item in rows() if item["id"] == "stranded-x")
    assert row["detail"]["said"] == refused["out"] and row["queued"] == []  # still there, and free to be pressed again
    odd = client.post("/plugin-act", json={"plugin": "cockpit", "id": "stranded-x", "index": 1}).json()
    assert odd["ok"] is False and "no such act" in odd["out"]
    # a press whose file is unreadable, or whose row is gone or has no detail, is dropped without failing
    queue_act("cockpit", "stranded-x", 0)
    folder = __import__("cockpitlib.inbox", fromlist=["acts_dir"]).acts_dir("cockpit")
    for name in os.listdir(folder):
        open(os.path.join(folder, name), "w", encoding="utf-8").write("not json")
    assert own_rows.drain(pack)[0]["ok"] is False
    own_rows._say("no-such-row", "x")
    put_row("cockpit", {"id": "plain", "what": "x"})
    own_rows._say("plain", "x")
    assert own_rows.clear("plain") is True and own_rows.ids("stranded-") == ["stranded-x"]
    # another plugin's row is queued for that plugin, exactly as before
    put_row("other", {"id": "r1", "what": "x", "detail": {"actions": [{"label": "Go", "act": {"do": "drop"}}]}})
    queued = client.post("/plugin-act", json={"plugin": "other", "id": "r1", "index": 0}).json()
    assert queued["ok"] is True and queued["queued"] and "applied" not in queued
