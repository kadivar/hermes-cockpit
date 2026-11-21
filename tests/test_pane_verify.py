# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The pane's Verify said ok for an intent endorse then refused: it verified without the pack, so the push checks (the
remote lease, the repo's verify commands) never ran."""

import os

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from cockpitlib.errors import CockpitError
from cockpitlib.intents import load as load_intent
from cockpitlib.intents import save
from cockpitlib.ops import worktree_add
from cockpitlib.outbox import create, endorse
from cockpitlib.pack import load

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PACKS = (os.path.join(ROOT, "packs", "acme", "pack.yaml"), os.path.join(ROOT, "packs", "bravo", "pack.yaml"))


def _client():
    from dashboard.cockpit.router import router

    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


@pytest.mark.parametrize("pack_file", PACKS)
def test_the_panes_verify_says_what_endorse_would_say(env, pack_file, monkeypatch):
    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    monkeypatch.delenv("COCKPIT_LANE", raising=False)
    pack = load(pack_file)
    name = pack["repos"]["repos"][0]["name"]
    ticket = f"{pack['tracker']['project']}-3405"
    worktree_add(pack, ticket, name)
    row = create(
        pack, ticket, "push-branch", "c", "ship", {"repo": name, "branch": f"{pack['branch_prefix']}/{ticket}"}
    )
    client = _client()
    assert client.post("/verify", json={"id": row["id"]}).json()["ok"] is True
    kept = load_intent(row["id"])
    kept["payload"]["remote_sha"] = "0" * 40  # the remote is not where the intent says it was
    save(kept)
    with pytest.raises(CockpitError, match="the remote moved"):
        endorse(row["id"], "low", "", "gatekeeper", "fixture-a", "fixture-large", pack=pack)
    checked = client.post("/verify", json={"id": row["id"]}).json()
    assert checked["ok"] is False and any("the remote moved" in item for item in checked["problems"])
