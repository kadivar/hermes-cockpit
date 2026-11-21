# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""A returned intent that nothing can move any more used to stay `returned` with no row: its close-out card ended
without an amend, the file that kept its instruction was gone (recard skipped it every minute), or its close-out card
could not be placed (retried every minute, silently). Each is now one Inbox row, written once, with Send back again
and Drop."""

import os

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from cockpitlib import gate
from cockpitlib.errors import CockpitError
from cockpitlib.inbox import rows
from cockpitlib.intents import load as load_intent
from cockpitlib.intents import save
from cockpitlib.kanban import BoardWrites
from cockpitlib.outbox import amend, create
from cockpitlib.pack import load

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PACKS = (os.path.join(ROOT, "packs", "acme", "pack.yaml"), os.path.join(ROOT, "packs", "bravo", "pack.yaml"))


def _client():
    from dashboard.cockpit.router import router

    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def _setup(monkeypatch, pack_file, number):
    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    monkeypatch.delenv("COCKPIT_LANE", raising=False)
    pack = load(pack_file)
    return pack, f"{pack['tracker']['project']}-{number}"


def _done(pack, card) -> None:
    writes = BoardWrites(pack["board"])
    writes.complete(card, result="done")
    writes.flush()


def _own_rows() -> list:
    return [row for row in rows() if row["plugin"] == "cockpit" and row["id"].startswith(gate.RETURN_ROW)]


@pytest.mark.parametrize("pack_file", PACKS)
def test_a_close_out_card_that_ended_without_an_amend_is_a_row_and_send_back_again_starts_over(
    env, pack_file, monkeypatch
):
    pack, ticket = _setup(monkeypatch, pack_file, 3201)
    ticks = iter(range(1, 60))  # a return's card is keyed by its time, to the second: every return here has its own
    monkeypatch.setattr(gate, "iso", lambda: f"2026-11-13T10:00:{next(ticks):02d}Z")
    iid = create(pack, ticket, "ticket-done", "worker-1", "done", {})["id"]
    first = gate.return_intent(pack, iid, "write more", assignee="worker-1")["returned"]["card"]
    assert gate.closeout_returned(pack) == "0" and _own_rows() == []  # its rework card is open
    _done(pack, first)
    assert gate.closeout_returned(pack) == "1" and _own_rows() == []  # the close-out card owns it now
    closeout = load_intent(iid)["returned"]["closeout"]["card"]
    _done(pack, closeout)
    assert gate.closeout_returned(pack) == "0"
    found = _own_rows()
    assert len(found) == 1 and iid in found[0]["what"] and closeout in found[0]["what"] and found[0]["ticket"] == ticket
    assert [action["label"] for action in found[0]["detail"]["actions"]] == ["Send back again", "Drop"]
    at = found[0]["at"]
    assert gate.closeout_returned(pack) == "0" and [row["at"] for row in _own_rows()] == [at]  # once
    sent = _client().post("/plugin-act", json={"plugin": "cockpit", "id": found[0]["id"], "index": 0}).json()
    assert sent["ok"] is True and "back to worker-1" in sent["out"]
    again = load_intent(iid)["returned"]
    assert again["instruction"] == "write more" and again["card"] not in ("", first) and "closeout" not in again
    assert _own_rows() == [] and gate.closeout_returned(pack) == "0" and _own_rows() == []
    # the second round ends the same way; this time the human drops it
    _done(pack, again["card"])
    assert gate.closeout_returned(pack) == "1"
    _done(pack, load_intent(iid)["returned"]["closeout"]["card"])
    assert gate.closeout_returned(pack) == "0" and len(_own_rows()) == 1
    dropped = _client().post("/plugin-act", json={"plugin": "cockpit", "id": _own_rows()[0]["id"], "index": 1}).json()
    assert dropped["ok"] is True and load_intent(iid)["status"] == "dropped" and _own_rows() == []
    assert gate.closeout_returned(pack) == "0" and _own_rows() == []


@pytest.mark.parametrize("pack_file", PACKS)
def test_a_return_whose_instruction_file_is_gone_and_one_whose_close_out_cannot_be_placed_are_rows(
    env, pack_file, monkeypatch
):
    from cockpitlib.halt import path as halt_path
    from cockpitlib.halt import write as halt
    from cockpitlib.owners import own
    from cockpitlib.paths import workspace

    pack, ticket = _setup(monkeypatch, pack_file, 3202)
    lost = create(pack, ticket, "ticket-done", "worker-1", "done", {})["id"]
    with monkeypatch.context() as patched:
        patched.setattr(gate, "_rework_card", lambda *_args, **_kwargs: ("", "board busy"))
        returned = gate.return_intent(pack, lost, "more of it", assignee="worker-1")["returned"]
    assert returned["card"] == "" and returned["card_error"] == "board busy"
    assert gate.closeout_returned(pack) == "0" and _own_rows() == []  # recard can still make its card from the file
    os.remove(os.path.join(workspace(), returned["body_file"]))
    assert gate.recard(pack) == "0" and gate.closeout_returned(pack) == "0"
    found = _own_rows()
    assert len(found) == 1 and lost in found[0]["what"] and "instruction is gone" in found[0]["what"]
    own("supervisor", [ticket])
    assert gate.closeout_returned(pack) == "0" and _own_rows() == []  # a plugin runs the ticket: its to settle
    own("supervisor", [])
    halt(ticket, "stop")
    assert gate.closeout_returned(pack) == "0" and _own_rows() == []
    os.remove(halt_path(ticket))
    assert gate.closeout_returned(pack) == "0" and len(_own_rows()) == 1
    sent = _client().post("/plugin-act", json={"plugin": "cockpit", "id": _own_rows()[0]["id"], "index": 0}).json()
    assert (
        sent["ok"] is True
        and load_intent(lost)["returned"]["card"]
        and load_intent(lost)["returned"]["instruction"] == "more of it"
    )
    assert _own_rows() == []
    # a close-out card the board refuses: the reason is on a row until the card can be placed
    other_ticket = f"{pack['tracker']['project']}-3203"
    stuck = create(pack, other_ticket, "ticket-done", "worker-1", "done", {})["id"]
    _done(pack, gate.return_intent(pack, stuck, "", assignee="worker-1")["returned"]["card"])
    with monkeypatch.context() as patched:

        def refused(*_args, **_kwargs):
            raise CockpitError("board down")

        patched.setattr("cockpitlib.kanban.place_card", refused)
        assert gate.closeout_returned(pack) == "0"
        found = [row for row in _own_rows() if stuck in row["what"]]
        assert len(found) == 1 and "board down" in found[0]["what"]
        assert (
            found[0]["detail"]["actions"][0]["act"]["instruction"] == "Redo this intent and amend it."
        )  # none was kept
    assert gate.closeout_returned(pack) == "1" and not [row for row in _own_rows() if stuck in row["what"]]
    # an amend resolves the return: no row, whatever its cards did
    amend(stuck, summary="redone", pack=pack)
    kept = load_intent(lost)
    kept["returned"]["resolved"] = "2026-11-13T10:00:00Z"
    save(kept)
    assert gate.closeout_returned(pack) == "0" and _own_rows() == []
