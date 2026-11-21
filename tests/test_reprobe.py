# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""A push intent whose git could not be read once (`probe_error`) never verified again: only Send back or Drop cleared
it. Re-probe reads git again through the amend path, with the payload as it was; a hold over a probe error is also
tried again by the housekeeping re-check, a few times, minutes apart."""

import os

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from cockpitlib import gate
from cockpitlib.errors import CockpitError
from cockpitlib.intents import load as load_intent
from cockpitlib.ops import worktree_add
from cockpitlib.outbox import create, endorse, hold, reprobe, verify
from cockpitlib.pack import load

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PACKS = (os.path.join(ROOT, "packs", "acme", "pack.yaml"), os.path.join(ROOT, "packs", "bravo", "pack.yaml"))


def _client():
    from dashboard.cockpit.router import router

    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def _unreadable(monkeypatch, pack_file, number):
    """A push intent written while git could not be read."""
    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    monkeypatch.delenv("COCKPIT_LANE", raising=False)
    pack = load(pack_file)
    name = pack["repos"]["repos"][0]["name"]
    ticket = f"{pack['tracker']['project']}-{number}"
    worktree_add(pack, ticket, name)
    branch = f"{pack['branch_prefix']}/{ticket}"
    with monkeypatch.context() as patched:

        def locked(*_args, **_kwargs):
            raise CockpitError("index.lock exists")

        patched.setattr("cockpitlib.git_push.probe", locked)
        row = create(pack, ticket, "push-branch", "c", "ship", {"repo": name, "branch": branch})
    assert (
        row["status"] == "pending"
        and row["payload"]["probe_error"] == "index.lock exists"
        and "sha" not in row["payload"]
    )
    assert any("git could not be read" in item for item in verify(row["id"], pack=pack))
    with pytest.raises(CockpitError, match="does not verify"):
        endorse(row["id"], "low", "", "gatekeeper", "fixture-a", "fixture-large", pack=pack)
    return pack, name, ticket, row["id"]


@pytest.mark.parametrize("pack_file", PACKS)
def test_re_probe_reads_git_again_and_the_intent_goes_back_to_the_gatekeeper(env, pack_file, monkeypatch):
    pack, name, ticket, iid = _unreadable(monkeypatch, pack_file, 3401)
    hold(iid, "git could not be read: index.lock exists", waits="human", pack=pack)
    client = _client()
    with monkeypatch.context() as patched:  # still locked: the answer says so and the intent stays as it is

        def locked(*_args, **_kwargs):
            raise CockpitError("index.lock exists")

        patched.setattr("cockpitlib.git_push.probe", locked)
        refused = client.post("/reprobe", json={"id": iid})
        assert refused.status_code == 400 and "still cannot be read: index.lock exists" in refused.json()["detail"]
    assert load_intent(iid)["status"] == "held" and load_intent(iid)["payload"]["probe_error"]
    before = {
        key: value
        for key, value in load_intent(iid)["payload"].items()
        if key in ("repo", "branch", "publish_as", "after")
    }
    os.remove(gate._outbox_file("_sweep.requested"))
    probed = client.post("/reprobe", json={"id": iid}).json()
    assert probed["ok"] is True and probed["status"] == "pending" and "probed again" in probed["out"]
    row = load_intent(iid)
    assert "probe_error" not in row["payload"] and len(row["payload"]["sha"]) == 40 and "hold" not in row
    assert {key: row["payload"].get(key) for key in before} == before  # what goes out was not changed
    assert row["history"][-1]["event"] == "git read again (re-probe)" and row["history"][-1]["by"] == "human"
    assert os.path.exists(gate._outbox_file("_sweep.requested"))  # the gatekeeper looks at it again
    assert not [item for item in verify(iid, pack=pack) if "git could not be read" in item]
    assert endorse(iid, "low", "", "gatekeeper", "fixture-a", "fixture-large", pack=pack)["status"] == "endorsed"
    # nothing to re-probe on an intent whose git was read, on one that is not a push, or on one that left
    with pytest.raises(CockpitError, match="has no probe error"):
        reprobe(iid, pack=pack)
    assert client.post("/reprobe", json={"id": f"{ticket}/999-push-branch"}).status_code == 400
    monkeypatch.setenv("COCKPIT_LANE", "worker-1")
    assert client.post("/reprobe", json={"id": iid}).status_code == 400  # the human's button


@pytest.mark.parametrize("pack_file", PACKS)
def test_the_cli_re_probes_and_a_closed_intent_is_refused(env, pack_file, monkeypatch, capsys):
    from cockpitlib.cli import main
    from cockpitlib.outbox import drop

    pack, name, ticket, iid = _unreadable(monkeypatch, pack_file, 3402)
    assert main(["outbox", "reprobe", iid]) == 0
    assert "probed again: pending" in capsys.readouterr().out and "probe_error" not in load_intent(iid)["payload"]
    other = _unreadable(monkeypatch, pack_file, 3403)[3]
    drop(other, "no")
    with pytest.raises(CockpitError, match="is dropped; only a pending, held or endorsed intent is probed again"):
        reprobe(other, pack=pack)
    monkeypatch.setenv("COCKPIT_LANE", "worker-1")
    assert main(["outbox", "reprobe", iid]) != 0


@pytest.mark.parametrize("pack_file", PACKS)
def test_a_hold_over_a_probe_error_is_tried_again_by_the_re_check(env, pack_file, monkeypatch):
    pack, name, ticket, iid = _unreadable(monkeypatch, pack_file, 3404)
    hold(iid, "git could not be read: index.lock exists", waits="human", pack=pack)
    assert gate._now() > 1_700_000_000  # the real clock, before the test takes it over
    clock = [1_800_000_000.0]
    monkeypatch.setattr(gate, "_now", lambda: clock[0])
    with monkeypatch.context() as patched:

        def locked(*_args, **_kwargs):
            raise CockpitError("index.lock exists")

        patched.setattr("cockpitlib.git_push.probe", locked)
        assert gate.resweep_held(pack) == "0"
        assert load_intent(iid)["hold"]["probe_retry"] == {"n": 1, "at": int(clock[0])}
        assert (
            gate.resweep_held(pack) == "0" and load_intent(iid)["hold"]["probe_retry"]["n"] == 1
        )  # not again within minutes
        for tries in range(2, gate.PROBE_RETRIES + 1):
            clock[0] += gate.PROBE_RETRY_S + 1
            assert gate.resweep_held(pack) == "0" and load_intent(iid)["hold"]["probe_retry"]["n"] == tries
    clock[0] += gate.PROBE_RETRY_S + 1
    assert (
        gate.resweep_held(pack) == "0" and load_intent(iid)["status"] == "held"
    )  # tried enough: the human's Re-probe is left
    kept = load_intent(iid)
    kept["hold"]["probe_retry"]["n"] = 1
    from cockpitlib.intents import save

    save(kept)
    assert gate.resweep_held(pack) == "1"
    row = load_intent(iid)
    assert row["status"] == "pending" and "probe_error" not in row["payload"] and row["history"][-1]["by"] == "resweep"
