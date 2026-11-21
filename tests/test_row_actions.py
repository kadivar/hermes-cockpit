# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Inbox rows that were dead ends get their way out: a provider hold ends now, an unreadable plan reader is read again,
cards parked at the budget ceiling are a row (they had none) and can be let run, and a row whose plugin is not
installed any more can be dismissed."""

import time

import pytest

from cockpitlib import quota
from cockpitlib.errors import CockpitError
from cockpitlib.inbox import put_row, rows
from cockpitlib.pack import load
from tests.support.boards import put_card
from tests.test_quota import (
    PACKS,
    UNREADABLE,
    _client,
    _forget_cache,
    _providers,
    _rows,
    _run,
    _status,
    _usage,
    _worker_log,
)

LATER = "2099-01-01T00:00:00+00:00"


def _setup(monkeypatch, pack_file):
    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    monkeypatch.delenv("COCKPIT_LANE", raising=False)
    return load(pack_file)


def _press(row: str, index: int = 0) -> dict:
    return _client().post("/plugin-act", json={"plugin": "cockpit", "id": row, "index": index}).json()


@pytest.mark.parametrize("pack_file", PACKS)
def test_end_hold_now_ends_a_provider_hold_and_its_cards_start_again(env, pack_file, monkeypatch):
    from cockpitlib.kanban import place_card

    pack = _setup(monkeypatch, pack_file)
    judged, worked = _providers(pack)
    now = time.time()
    walled = place_card(pack["board"], f"{pack['tracker']['project']}-71: worker", "worker-1", "ready")
    _run(pack, walled, "worker-1", "rate_limited", int(now) - 30, error="pid 1 exited rate-limited (quota wall)")
    _worker_log(
        pack,
        walled,
        "Provider said: HTTP 502: Weekly usage limit reached. It resets in 5 days.\n\n[kanban-worker-exit] rc=75\n",
    )
    quota.step(pack, now=now)
    row = _rows()["provider-hold-" + worked]
    assert [action["label"] for action in row["detail"]["actions"]] == ["End hold now"] and _status(
        pack, walled
    ) == "scheduled"
    pressed = _press(row["id"])
    assert pressed["ok"] is True and pressed["applied"] is True and f"the hold on {worked} is ended" in pressed["out"]
    assert quota.holds() == {} and "provider-hold-" + worked not in _rows()
    quota.step(pack, now=now + 60)  # the wall that made the hold is read again and holds nothing: the human ended it
    assert quota.holds(now + 60) == {} and _status(pack, walled) == "ready" and "provider-hold-" + worked not in _rows()
    with pytest.raises(CockpitError, match="is not held"):
        quota.clear_hold(worked)
    with pytest.raises(CockpitError, match=r"provider \? is not held"):
        quota.clear_hold("")
    # a wall after that holds it again, as any wall does
    again = place_card(pack["board"], f"{pack['tracker']['project']}-72: worker", "worker-1", "ready")
    _run(
        pack, again, "worker-1", "rate_limited", int(time.time()) + 120, error="pid 2 exited rate-limited (quota wall)"
    )
    quota.step(pack, now=time.time() + 180)
    assert set(quota.holds(time.time() + 180)) == {worked}


@pytest.mark.parametrize("pack_file", PACKS)
def test_retry_reading_reads_the_plan_again_and_says_when_it_still_cannot(env, pack_file, monkeypatch):
    pack = _setup(monkeypatch, pack_file)
    judged, worked = _providers(pack)
    start = time.time() - 20 * 60
    good = {judged: {"windows": [{"label": "session", "used_percent": 10, "resets_at": LATER}]}}
    _usage({worked: {"windows": [{"label": "week", "used_percent": 5, "resets_at": LATER}]}, **good})
    quota.step(pack, now=start)
    _usage({worked: {"unavailable": UNREADABLE}, **good})
    _forget_cache()
    quota.step(pack, now=start + 60)
    _forget_cache()
    quota.step(pack, now=start + 17 * 60)
    row = _rows()["plan-usage-" + worked]
    assert [action["label"] for action in row["detail"]["actions"]] == ["Retry reading"]
    still = _press(row["id"])
    assert still["ok"] is False and still["out"].startswith(f"refused: plan usage for {worked} is still unreadable")
    kept = _rows()["plan-usage-" + worked]
    assert kept["detail"]["said"] == still["out"] and kept["queued"] == []  # the row says why, and can be pressed again
    _usage({worked: {"windows": [{"label": "week", "used_percent": 6, "resets_at": LATER}]}, **good})
    read = _press(row["id"])
    assert (
        read["ok"] is True
        and read["out"] == f"plan usage for {worked} was read"
        and "plan-usage-" + worked not in _rows()
    )


@pytest.mark.parametrize("pack_file", PACKS)
def test_cards_parked_at_the_budget_ceiling_are_a_row_and_can_be_let_run(env, pack_file, monkeypatch):
    pack = _setup(monkeypatch, pack_file)
    judged, worked = _providers(pack)
    ceiling = pack["budget"]["plan_window_max_pct"]
    now = time.time()
    first = put_card(pack["board"], "TASK-9: worker", "worker-1", "ready")
    second = put_card(pack["board"], "TASK-9: test", "tester-1", "ready")
    other = put_card(pack["board"], "TASK-9: review", "reviewer", "ready")
    over = {
        worked: {"windows": [{"label": "week", "used_percent": ceiling + 1, "resets_at": LATER}]},
        judged: {"windows": [{"label": "week", "used_percent": 1, "resets_at": LATER}]},
    }
    _usage(over)
    quota.step(pack, now=now)
    assert (
        _status(pack, first) == "scheduled" and _status(pack, second) == "scheduled" and _status(pack, other) == "ready"
    )
    row = _rows()["budget-wait-" + worked]
    assert row["what"].startswith(
        f"2 card(s) of seats on {worked} wait at the budget ceiling (window week is {ceiling + 1}%)"
    )
    listed = next(field["items"] for field in row["detail"]["fields"] if field["label"] == "cards waiting")
    assert listed == sorted([f"{first} TASK-9: worker", f"{second} TASK-9: test"])
    assert [action["label"] for action in row["detail"]["actions"]] == ["Run them anyway"]
    assert "budget-wait-" + judged not in _rows() and not [
        ident for ident in _rows() if ident.startswith("provider-hold-")
    ]
    at = row["at"]
    quota.step(pack, now=now + 60)
    assert _rows()["budget-wait-" + worked]["at"] == at  # one row, written once
    pressed = _press(row["id"])
    assert pressed["ok"] is True and pressed["out"] == f"2 card(s) of {worked} start now"
    assert (
        _status(pack, first) == "ready" and _status(pack, second) == "ready" and "budget-wait-" + worked not in _rows()
    )
    later = put_card(pack["board"], "TASK-10: worker", "worker-1", "ready")
    quota.step(pack, now=now + 120)  # still over: the cards the human let run stay ready, a card made since waits
    assert _status(pack, first) == "ready" and _status(pack, second) == "ready" and _status(pack, later) == "scheduled"
    again = _rows()["budget-wait-" + worked]
    assert next(field["items"] for field in again["detail"]["fields"] if field["label"] == "cards waiting") == [
        f"{later} TASK-10: worker"
    ]
    with pytest.raises(CockpitError, match="no card of .* waits at the budget ceiling"):
        quota.release_parked(pack, judged)
    # a provider wall still holds a card the human let run at the budget ceiling
    _run(pack, first, "worker-1", "rate_limited", int(now) + 130, error="pid 1 exited rate-limited (quota wall)")
    quota.step(pack, now=now + 180)
    assert (
        _status(pack, first) == "scheduled"
        and "budget-wait-" + worked not in _rows()
        and "provider-hold-" + worked in _rows()
    )
    quota.clear_hold(worked, now=now + 190)
    # under the ceiling again: nothing waits, no row; a finished card is forgotten
    under = {
        worked: {"windows": [{"label": "week", "used_percent": ceiling - 1, "resets_at": LATER}]},
        judged: over[judged],
    }
    _usage(under)
    _forget_cache()
    from tests.support.boards import raw

    connection = raw(pack["board"])
    connection.execute("update tasks set status = 'done' where id = ?", (second,))
    connection.commit()
    connection.close()
    quota.step(pack, now=now + 240)
    assert _status(pack, later) == "ready" and not [ident for ident in _rows() if ident.startswith("budget-wait-")]
    assert second not in quota._load(quota.HOLDS_FILE)["exempt"] and first in quota._load(quota.HOLDS_FILE)["exempt"]


@pytest.mark.parametrize("pack_file", PACKS)
def test_a_row_whose_plugin_is_gone_can_be_dismissed_and_an_installed_plugins_row_cannot(bare, pack_file, monkeypatch):
    pack = _setup(monkeypatch, pack_file)
    installed = bare["home"] / "plugins" / "ledger-view"
    installed.mkdir(parents=True)
    (installed / "plugin.yaml").write_text("name: ledger-view\n", encoding="utf-8")
    put_row("ledger-view", {"id": "r1", "what": "ledger closed"})
    put_row("left-long-ago", {"id": "r2", "what": "a leftover"})
    put_row("cockpit", {"id": "own", "what": "cockpit's own"})
    found = {row["id"]: row["orphan"] for row in rows(pack)}
    assert found == {"r1": False, "r2": True, "own": False}
    shown = {row["id"]: row["orphan"] for row in _client().get("/needs-you").json()["plugins"]}
    assert shown == found
    client = _client()
    refused = client.post("/plugin-row-dismiss", json={"plugin": "ledger-view", "id": "r1"})
    assert refused.status_code == 400 and "is installed" in refused.json()["detail"]
    assert client.post("/plugin-row-dismiss", json={"plugin": "cockpit", "id": "own"}).status_code == 400
    done = client.post("/plugin-row-dismiss", json={"plugin": "left-long-ago", "id": "r2"}).json()
    assert done == {"ok": True, "out": "row dismissed"} and sorted(row["id"] for row in rows(pack)) == ["own", "r1"]
    assert (
        client.post("/plugin-row-dismiss", json={"plugin": "left-long-ago", "id": "r2"}).json()["ok"] is False
    )  # already gone
    put_row("left-long-ago", {"id": "r3", "what": "another"})
    monkeypatch.setenv("COCKPIT_LANE", "worker-1")
    assert (
        client.post("/plugin-row-dismiss", json={"plugin": "left-long-ago", "id": "r3"}).status_code == 400
    )  # the human's
