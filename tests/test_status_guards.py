# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Drop and hold are for open intents: one that already left (published, acknowledged), one that is a pending review on
the forge, and one that was dropped are refused instead of being moved to a status the table does not allow. And a
press on row `a-1` is no press on row `a`."""

import os

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from cockpitlib.errors import CockpitError
from cockpitlib.inbox import pending_presses, put_row, queue_act
from cockpitlib.intents import load as load_intent
from cockpitlib.intents import save
from cockpitlib.outbox import create, drop, hold
from cockpitlib.pack import load

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PACKS = (os.path.join(ROOT, "packs", "acme", "pack.yaml"), os.path.join(ROOT, "packs", "bravo", "pack.yaml"))


def _intent(pack, ticket, status):
    repo = pack["repos"]["repos"][0]["name"]
    row = create(pack, ticket, "ci-rerun", "c", "rerun", {"repo": repo, "run_id": 7})
    row["status"] = status
    save(row)
    return row["id"]


@pytest.mark.parametrize("pack_file", PACKS)
def test_drop_and_hold_refuse_an_intent_that_is_not_open(bare, pack_file, monkeypatch):
    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    monkeypatch.delenv("COCKPIT_LANE", raising=False)
    pack = load(pack_file)
    ticket = f"{pack['tracker']['project']}-3801"
    for status in ("published", "published-manually", "acknowledged", "reopened", "dropped"):
        iid = _intent(pack, ticket, status)
        with pytest.raises(CockpitError, match=f"{iid} is {status}; only an open intent is dropped"):
            drop(iid, "no")
        with pytest.raises(CockpitError, match=f"{iid} is {status}; only a pending, endorsed or held intent is held"):
            hold(iid, "wait")
        assert (
            load_intent(iid)["status"] == status and "human" not in load_intent(iid) and "hold" not in load_intent(iid)
        )
    posted = _intent(pack, ticket, "posted")
    with pytest.raises(CockpitError, match="is a pending review on the forge: discard it first"):
        drop(posted, "no")
    with pytest.raises(CockpitError, match="only a pending, endorsed or held intent is held"):
        hold(posted, "wait")
    returned = _intent(pack, ticket, "returned")
    with pytest.raises(CockpitError, match="is returned; only a pending, endorsed or held intent is held"):
        hold(returned, "wait")
    assert drop(returned, "no")["status"] == "dropped"  # a returned intent is open: the human may drop it
    for status in ("pending", "endorsed", "held"):  # as before
        assert hold(_intent(pack, ticket, status), "wait")["status"] == "held"
        assert drop(_intent(pack, ticket, status), "no")["status"] == "dropped"
    from dashboard.cockpit.router import router

    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    left = _intent(pack, ticket, "published")
    assert (
        client.post("/drop", json={"id": left}).status_code == 400
        and client.post("/hold", json={"id": left}).status_code == 400
    )
    assert load_intent(left)["status"] == "published"


def test_a_press_on_one_row_is_not_a_press_on_a_row_whose_name_it_starts_with(bare):
    actions = [{"label": "Zero", "act": {"do": "zero"}}, {"label": "One", "act": {"do": "one"}}]
    put_row("ledger-view", {"id": "a", "what": "row a", "detail": {"actions": actions}})
    put_row("ledger-view", {"id": "a-1", "what": "row a-1", "detail": {"actions": actions}})
    assert queue_act("ledger-view", "a-1", 0)["queued"]
    assert pending_presses("ledger-view", "a-1") == [0]
    assert pending_presses("ledger-view", "a") == []  # it read a-1's press as its own action 1
    assert queue_act("ledger-view", "a", 1)[
        "queued"
    ]  # so this press was answered "already queued" and never reached the plugin
    assert pending_presses("ledger-view", "a") == [1] and pending_presses("ledger-view", "a-1") == [0]
    assert queue_act("ledger-view", "a", 1).get("already") is True
    # a request file of the older shape (<row>-<index>-<time>.json) still counts as that row's press
    from cockpitlib.inbox import acts_dir

    open(os.path.join(acts_dir("ledger-view"), "a-0-1790000000.json"), "w", encoding="utf-8").write("{}")
    open(os.path.join(acts_dir("ledger-view"), "a-x.json"), "w", encoding="utf-8").write("{}")
    assert pending_presses("ledger-view", "a") == [0, 1]
