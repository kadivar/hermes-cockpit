# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Applying an update replaces the code every seat runs: it is the human's act. A lane's command is refused by the
kernel's own denies, its call of the verb and of the route is refused too, and the human's goes through."""

import os

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from cockpitlib import egress, self_update
from cockpitlib.cli import main
from cockpitlib.pack import load

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PACKS = (os.path.join(ROOT, "packs", "acme", "pack.yaml"), os.path.join(ROOT, "packs", "bravo", "pack.yaml"))
REFUSED = (
    "cockpit update apply",
    "cockpit update apply --no-restart",
    "cockpit update rollback",
    "cockpit update rollback --to abc1234",
    "cockpit  update   apply",
    "cockpit update rollback",
    "cd /tmp && cockpit update apply",
    "/opt/tools/bin/cockpit update apply",
    "true; cockpit update rollback 20260101",
)
READS = (
    "cockpit update check",
    "cockpit update status",
    "cockpit update",
    "cockpit doctor",
    "echo update apply",
    "cockpit outbox list",
)


def _client():
    from dashboard.cockpit.router import router

    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


@pytest.fixture
def applied(monkeypatch):
    """The updater stands in: it records each call and changes nothing."""
    calls = []
    monkeypatch.setattr(
        self_update,
        "apply",
        lambda root="", restart=True, now=None, to="": calls.append(restart) or {"ok": True, "next": {}},
    )
    return calls


@pytest.mark.parametrize("command", REFUSED)
def test_the_kernel_denies_a_lane_the_update(command):
    assert egress.check(command) == "blocked"
    assert "a denied command" in egress.explained("blocked")


@pytest.mark.parametrize("command", READS)
def test_a_lane_may_still_read_what_an_update_would_do(command):
    assert egress.check(command) == ""


@pytest.mark.parametrize("pack_file", PACKS)
def test_a_pack_cannot_take_the_update_deny_away(pack_file):
    pack = load(pack_file)
    for command in REFUSED:
        assert egress.check(command, extra_deny=(pack.get("egress") or {}).get("deny") or ()) == "blocked"
    assert any("update" in pattern for pattern in egress.KERNEL_DENY)


@pytest.mark.parametrize("pack_file", PACKS)
@pytest.mark.parametrize("lane", ("worker-1", "gatekeeper", "tester-1", "analyst"))
def test_a_lane_cannot_apply_an_update_through_the_route_or_the_verb(
    env, pack_file, monkeypatch, applied, capsys, lane
):
    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    monkeypatch.setenv("COCKPIT_LANE", lane)
    response = _client().post("/update-apply", json={})
    assert response.status_code == 400 and "updates stay with the human" in response.json()["detail"]
    assert main(["update", "apply"]) == 1
    assert "updates stay with the human" in capsys.readouterr().err
    assert applied == []


@pytest.mark.parametrize("pack_file", PACKS)
def test_the_human_applies_an_update_through_the_route_and_the_verb(env, pack_file, monkeypatch, applied, capsys):
    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    monkeypatch.delenv("COCKPIT_LANE", raising=False)
    client = _client()
    assert client.post("/update-apply", json={}).json() == {"ok": True, "next": {}}
    assert client.post("/update-apply", json={"restart": False}).status_code == 200
    assert main(["update", "apply", "--no-restart"]) == 0
    assert applied == [True, False, False]


@pytest.mark.parametrize("pack_file", PACKS)
def test_a_lane_still_reads_the_update_state(env, pack_file, monkeypatch, capsys):
    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    monkeypatch.setenv("COCKPIT_LANE", "worker-1")
    monkeypatch.setattr(self_update, "status", lambda root="": {"installed": "abc"})
    assert _client().get("/update").json() == {"installed": "abc"}
    assert main(["update", "status"]) == 0
    assert '"installed": "abc"' in capsys.readouterr().out
