# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The dashboard router can refuse a request another site's page made: with COCKPIT_ORIGIN_CHECK set, a request whose
Origin header is neither a loopback origin, the address the request itself was sent to, nor one the installation lists
is answered 403. A request with no Origin (the Desktop, a same-origin read, curl) passes unchanged, and without the
setting nothing is checked: the routes answer as they always did."""

import pytest

from dashboard.cockpit import router as web
from tests.support.both_packs import PACKS, _client

LOOPBACK = (
    "http://localhost",
    "http://localhost:9119",
    "https://localhost:8443",
    "http://127.0.0.1:9119",
    "http://[::1]:9119",
    "http://LOCALHOST:5174",
)
FOREIGN = (
    "https://evil.example.test",
    "http://evil.example.test:9119",
    "http://localhost.evil.example.test",
    "null",
    "file://",
    "http://127.0.0.1.evil.example.test",
    "https://cockpit.example.test",
    "http://[::1",
    "not an origin",
)


@pytest.fixture
def client(env, monkeypatch):
    monkeypatch.setenv("COCKPIT_PACK", PACKS[0])
    return _client()


def _get(client, origin=None, host=None):
    headers = {**({"origin": origin} if origin is not None else {}), **({"host": host} if host else {})}
    return client.get("/list", headers=headers)


def test_without_the_setting_no_origin_is_refused(client, monkeypatch):
    monkeypatch.delenv("COCKPIT_ORIGIN_CHECK", raising=False)
    for origin in (None, *LOOPBACK, *FOREIGN):
        assert _get(client, origin).status_code == 200, origin
    assert client.post("/sweep", json={}, headers={"origin": "https://evil.example.test"}).status_code != 403


@pytest.mark.parametrize("off", ("", "0", "false", "no", "off"))
def test_the_setting_is_off_for_every_spelling_of_no(client, monkeypatch, off):
    monkeypatch.setenv("COCKPIT_ORIGIN_CHECK", off)
    assert _get(client, "https://evil.example.test").status_code == 200


def test_with_the_setting_a_request_with_no_origin_passes_unchanged(client, monkeypatch):
    before = _get(client).json()
    monkeypatch.setenv("COCKPIT_ORIGIN_CHECK", "1")
    after = _get(client)
    assert after.status_code == 200 and after.json().keys() == before.keys()


@pytest.mark.parametrize("origin", LOOPBACK)
def test_with_the_setting_a_loopback_origin_on_any_port_passes(client, monkeypatch, origin):
    monkeypatch.setenv("COCKPIT_ORIGIN_CHECK", "1")
    assert _get(client, origin).status_code == 200


@pytest.mark.parametrize("origin", FOREIGN)
def test_with_the_setting_another_sites_origin_is_refused_on_reads_and_writes(client, monkeypatch, origin):
    monkeypatch.setenv("COCKPIT_ORIGIN_CHECK", "1")
    refused = _get(client, origin)
    assert refused.status_code == 403 and "origin" in refused.json()["detail"]
    assert client.post("/sweep", json={}, headers={"origin": origin}).status_code == 403
    assert (
        client.post(
            "/publish", json={"id": "TASK-1/001-x", "confirm": "TASK-1/001-x"}, headers={"origin": origin}
        ).status_code
        == 403
    )


def test_with_the_setting_the_address_the_request_was_sent_to_is_its_own_origin(client, monkeypatch):
    monkeypatch.setenv("COCKPIT_ORIGIN_CHECK", "1")
    assert _get(client, "http://box.example.test:9119", host="box.example.test:9119").status_code == 200
    assert _get(client, "http://BOX.example.test:9119", host="box.example.test:9119").status_code == 200
    assert _get(client, "http://box.example.test:9119", host="box.example.test:8000").status_code == 403, (
        "another port is another origin"
    )
    assert _get(client, "http://evil.example.test", host="box.example.test:9119").status_code == 403


def test_with_the_setting_a_listed_origin_passes_and_only_that_one(client, monkeypatch):
    monkeypatch.setenv("COCKPIT_ORIGIN_CHECK", "1")
    monkeypatch.setenv("COCKPIT_ALLOWED_ORIGINS", "https://cockpit.example.test, https://other.example.test:8443/ ,")
    assert _get(client, "https://cockpit.example.test").status_code == 200
    assert _get(client, "https://COCKPIT.example.test").status_code == 200
    assert _get(client, "https://other.example.test:8443").status_code == 200
    assert _get(client, "http://cockpit.example.test").status_code == 403, "another scheme is another origin"
    assert _get(client, "https://cockpit.example.test:8443").status_code == 403
    assert _get(client, "https://evil.example.test").status_code == 403


def test_the_rule_reads_an_origin_and_nothing_else():
    assert web.origin_refusal("", "localhost:9119", ()) == ""
    assert web.origin_refusal("http://localhost:1", "", ()) == ""
    assert web.origin_refusal("https://a.example.test", "", ("https://a.example.test",)) == ""
    assert "another site" in web.origin_refusal("https://a.example.test", "localhost:9119", ())
    assert web.allowed_origins("") == () and web.allowed_origins(" https://a.example.test/ ,x") == (
        "https://a.example.test",
        "x",
    )
