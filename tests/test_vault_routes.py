# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The Vault page's routes: metadata in lists, a value only through /vault-reveal, nothing for a lane."""

import pytest

from tests.test_routes import _client
from tests.test_vault import seal_ephemeral

GETS = ("/vaults", "/vault-records", "/vault-record")
POSTS = (
    "/vault-create",
    "/vault-rename",
    "/vault-delete",
    "/vault-save",
    "/vault-record-delete",
    "/vault-move",
    "/vault-reveal",
)


@pytest.fixture
def client(env, monkeypatch):
    seal_ephemeral(monkeypatch, str(env["home"]))
    return _client()


def test_the_page_walks_a_record_from_creation_to_deletion(client):
    page = client.get("/vaults").json()
    assert page["sealed"] and not page["locked"] and [k["name"] for k in page["kinds"]] == ["login", "key", "note"]
    assert [(v["name"], v["builtin"]) for v in page["vaults"]] == [("human", True), ("lane", True)]
    assert client.post("/vault-create", json={"name": "ops"}).json()["ok"]
    made = client.post(
        "/vault-save",
        json={
            "vault": "ops",
            "kind": "key",
            "title": "CI token",
            "secret": "tok-123456",
            "tags": "ci",
            "notes": "rotate monthly",
        },
    )
    assert made.status_code == 200 and made.json()["ok"] and made.json()["id"]
    rid = made.json()["id"]
    listing = client.get("/vault-records", params={"vault": "ops", "q": "ci", "kind": "key", "tag": "ci"})
    assert listing.status_code == 200 and listing.json()["tags"] == ["ci"]
    assert "tok-123456" not in listing.text and "rotate monthly" not in listing.text
    detail = client.get("/vault-record", params={"vault": "ops", "id": rid})
    assert detail.json()["record"]["has_secret"] and "tok-123456" not in detail.text and detail.json()["seats"] == []
    shown = client.post("/vault-reveal", json={"vault": "ops", "id": rid, "field": "secret"}).json()
    assert shown["value"] == "tok-123456" and shown["expires_in"] == 30
    assert (
        client.post("/vault-reveal", json={"vault": "ops", "id": rid, "field": "notes"}).json()["value"]
        == "rotate monthly"
    )
    assert client.post("/vault-save", json={"vault": "ops", "id": rid, "kind": "key", "secret": "tok-654321"}).json()[
        "ok"
    ]
    assert (
        client.post("/vault-reveal", json={"vault": "ops", "id": rid, "field": "history", "index": 0}).json()["value"]
        == "tok-123456"
    )
    assert (
        client.post("/vault-move", json={"vault": "ops", "id": rid, "to": "human"}).json()["out"]
        == "CI token moved to human"
    )
    refused = client.post("/vault-record-delete", json={"vault": "human", "id": rid})
    assert refused.status_code == 400 and "confirm" in refused.text
    assert (
        client.post("/vault-record-delete", json={"vault": "human", "id": rid, "confirm": "wrong"}).status_code == 400
    )
    assert (
        client.post("/vault-record-delete", json={"vault": "human", "id": rid, "confirm": rid}).json()["out"]
        == "CI token deleted"
    )
    assert client.post("/vault-rename", json={"name": "ops", "to": "runbooks"}).json()["ok"]
    assert client.post("/vault-delete", json={"name": "runbooks"}).status_code == 400
    assert client.post("/vault-delete", json={"name": "runbooks", "confirm": "runbooks"}).json()["ok"]
    assert client.post("/vault-delete", json={"name": "lane", "confirm": "lane"}).status_code == 400  # built in
    assert client.post("/vault-save", json={"vault": "human", "kind": "bogus"}).status_code == 400


def test_a_lane_never_reaches_the_vault_routes(client, monkeypatch):
    monkeypatch.setenv("COCKPIT_LANE", "tester-1")
    for path in GETS:
        response = client.get(path)
        assert response.status_code == 400 and "stay with the human" in response.text, path
    for path in POSTS:
        response = client.post(path, json={})
        assert response.status_code == 400 and "stay with the human" in response.text, path


def test_the_page_says_so_when_the_vault_is_not_sealed(bare):
    page = _client().get("/vaults").json()
    assert not page["sealed"] and page["locked"] and "not sealed" in page["reason"]
    assert client_status(bare) == 400


def client_status(env):
    return (
        _client()
        .post("/vault-save", json={"vault": "human", "kind": "key", "title": "k", "secret": "kkkkkk"})
        .status_code
    )
