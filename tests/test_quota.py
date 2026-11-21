# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Provider quotas are always respected: a plan window that cannot be read gates on its last good reading, a provider's
limit holds that provider's seats until it resets, and at the ceiling a running card finishes its turn while its retry
and new cards wait. Both fixture packs reach the same outcomes."""

import json
import os
import sqlite3
import time

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from cockpitlib.pack import load
from dashboard.cockpit.router import router

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PACKS = (
    os.path.join(ROOT, "packs", "acme", "pack.yaml"),
    os.path.join(ROOT, "packs", "bravo", "pack.yaml"),
)
UNREADABLE = "the coding tool skips the usage fetch with nonessential traffic off"


def _client():
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def _usage(data) -> None:
    json.dump(data, open(os.path.join(os.environ["COCKPIT_ROOT"], "fake-usage.json"), "w", encoding="utf-8"))


def _forget_cache() -> None:
    from cockpitlib.paths import watch_dir

    path = os.path.join(watch_dir(), "plan-windows.json")
    if os.path.exists(path):
        os.remove(path)


def _providers(pack):
    judged = pack["providers"][pack["roles"]["reviewer"]]["hermes_provider"]
    worked = pack["providers"][pack["roles"]["worker"]]["hermes_provider"]
    assert judged != worked
    return judged, worked


def _rows(plugin="cockpit") -> dict:
    from cockpitlib.inbox import rows

    return {row["id"]: row for row in rows() if row["plugin"] == plugin}


def _status(pack, card) -> str:
    from cockpitlib.kanban import db_path

    connection = sqlite3.connect(db_path(pack["board"]))
    try:
        return connection.execute("select status from tasks where id = ?", (card,)).fetchone()[0]
    finally:
        connection.close()


def _run(pack, card, lane, outcome, ended, error="", started=None) -> None:
    from cockpitlib.kanban import db_path

    connection = sqlite3.connect(db_path(pack["board"]))
    connection.execute(
        "insert into task_runs (task_id, profile, status, started_at, ended_at, outcome, error) values (?, ?, ?, ?, ?, ?, ?)",
        (card, lane, outcome, started if started is not None else ended - 60, ended, outcome, error),
    )
    connection.commit()
    connection.close()


def _worker_log(pack, card, text) -> None:
    from cockpitlib.kanban import db_path

    folder = os.path.join(os.path.dirname(db_path(pack["board"])), "logs")
    os.makedirs(folder, exist_ok=True)
    with open(os.path.join(folder, f"{card}.log"), "a", encoding="utf-8") as handle:
        handle.write(text)


# ---------- 1. never fail open on an unreadable plan window ----------


@pytest.mark.parametrize("pack_file", PACKS)
def test_an_unreadable_plan_window_gates_on_its_last_good_reading_and_says_so_after_a_quarter_hour(
    env, pack_file, monkeypatch
):
    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    pack = load(pack_file)
    from cockpitlib.quota import step
    from cockpitlib.settings import budget_state
    from cockpitlib.usage import WINDOWS_FRESH

    judged, worked = _providers(pack)
    ceiling = pack["budget"]["plan_window_max_pct"]
    later = "2099-01-01T00:00:00+00:00"
    start = time.time()
    _usage(
        {
            worked: {
                "windows": [
                    {"label": f"week {pack['name']}", "used_percent": ceiling + 1, "resets_at": later},
                    {"label": "session", "used_percent": 25, "resets_at": later},
                ]
            },
            judged: {"windows": [{"label": "session", "used_percent": 10, "resets_at": later}]},
        }
    )
    fresh = budget_state(pack, now=start)
    assert fresh["over"] is True and fresh["error"] == ""
    # The reader refuses (the coding tool with its telemetry off): the gate keeps the last good reading, marked stale.
    _usage(
        {
            worked: {"unavailable": UNREADABLE},
            judged: {"windows": [{"label": "session", "used_percent": 10, "resets_at": later}]},
        }
    )
    blind = budget_state(pack, now=start + WINDOWS_FRESH)
    assert blind["over"] is True and blind["why"] == f"window week {pack['name']} is {ceiling + 1}%"
    assert UNREADABLE in blind["error"]
    stale = [window for window in blind["windows"] if window["provider"] == worked]
    assert {window["name"] for window in stale} == {f"week {pack['name']}", "session"}
    assert all(window["stale"] is True and window["age"] == WINDOWS_FRESH for window in stale)
    assert all(not window.get("stale") for window in blind["windows"] if window["provider"] == judged)
    # No Inbox row before a quarter hour without a good read, one row after it, gone once a read succeeds.
    assert "plan-usage-" + worked not in _rows()
    step(pack, now=start + WINDOWS_FRESH)
    assert "plan-usage-" + worked not in _rows()
    _forget_cache()
    step(pack, now=start + 16 * 60)
    row = _rows()["plan-usage-" + worked]
    assert row["what"].startswith(f"plan usage unreadable for {worked} since ") and UNREADABLE in row["what"]
    assert "the gate uses the last reading from " in row["what"]
    assert "plan-usage-" + judged not in _rows()
    _forget_cache()
    step(pack, now=start + 17 * 60)
    assert len([ident for ident in _rows() if ident.startswith("plan-usage-")]) == 1  # one row, not one per read
    _usage(
        {
            worked: {"windows": [{"label": f"week {pack['name']}", "used_percent": ceiling - 1, "resets_at": later}]},
            judged: {"windows": [{"label": "session", "used_percent": 10, "resets_at": later}]},
        }
    )
    _forget_cache()
    step(pack, now=start + 18 * 60)
    assert "plan-usage-" + worked not in _rows()
    assert budget_state(pack, now=start + 18 * 60)["over"] is False


@pytest.mark.parametrize("pack_file", PACKS)
def test_a_stale_window_past_its_reset_no_longer_gates_and_a_partial_read_keeps_the_missing_label(
    env, pack_file, monkeypatch
):
    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    pack = load(pack_file)
    from cockpitlib.settings import budget_state
    from cockpitlib.usage import WINDOWS_FRESH

    _judged, worked = _providers(pack)
    ceiling = pack["budget"]["plan_window_max_pct"]
    import datetime

    start = 4_000_000_000.0
    soon = datetime.datetime.fromtimestamp(start + 3600, datetime.UTC).isoformat()  # within the next day
    _usage(
        {
            worked: {
                "windows": [
                    {"label": "session", "used_percent": ceiling + 5, "resets_at": soon},
                    {"label": "week", "used_percent": ceiling + 2, "resets_at": "2099-01-01T00:00:00+00:00"},
                ]
            }
        }
    )
    assert budget_state(pack, now=start)["over"] is True
    # A read that answers only one window and says why the other is missing: the other keeps its last reading.
    _usage(
        {
            worked: {
                "windows": [{"label": "session", "used_percent": 1, "resets_at": soon}],
                "unavailable": "week window missing",
            }
        }
    )
    partial = budget_state(pack, now=start + WINDOWS_FRESH)
    named = {window["name"]: window for window in partial["windows"] if window["provider"] == worked}
    assert named["session"]["used"] == 1 and not named["session"].get("stale")
    assert named["week"]["stale"] is True and partial["why"] == f"window week is {ceiling + 2}%"
    # Unreadable after the session window has reset: that reading is spent and no longer counts; the week's still does.
    _usage({worked: {"unavailable": UNREADABLE}})
    _forget_cache()
    past = budget_state(pack, now=start + 2 * 86400)
    assert {window["name"] for window in past["windows"] if window["provider"] == worked} == {"week"}


@pytest.mark.parametrize("pack_file", PACKS)
def test_a_reader_that_never_answered_raises_no_reading_yet_and_refuses_no_card(env, pack_file, monkeypatch):
    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    pack = load(pack_file)
    from cockpitlib.quota import step
    from cockpitlib.settings import budget_state

    judged, worked = _providers(pack)
    start = time.time()
    _usage({worked: {"unavailable": UNREADABLE}})  # judged: no reader at all (unmetered), never a row
    state = budget_state(pack, now=start)
    assert state["over"] is False and UNREADABLE in state["error"] and judged in state["unmetered"]
    step(pack, now=start)
    assert not [ident for ident in _rows() if ident.startswith("plan-usage-")]
    _forget_cache()
    step(pack, now=start + 16 * 60)
    row = _rows()["plan-usage-" + worked]
    assert row["what"].endswith("no reading yet")
    assert "plan-usage-" + judged not in _rows()
    # Unreadable is not over: a card still starts (a pack without a reading keeps working).
    kicked = _client().post("/kickoff", json={"ticket": "TASK-100", "mode": "analyst", "prompt": "why"})
    assert kicked.status_code == 200, kicked.text


# ---------- 2. a provider limit holds that provider's seats until reset, with one Inbox row ----------


def test_a_provider_message_names_its_reset():
    from cockpitlib.quota import CAP, DEFAULT_HOLD, reset_after

    at = 1_000_000.0
    assert reset_after("HTTP 502: Weekly usage limit reached. It resets in 5 days. Buy credits", at) == at + 5 * 86400
    assert reset_after("limit reached, resets in 3 hours", at) == at + 3 * 3600
    assert reset_after("Rate limited. Try again in 45 minutes.", at) == at + 45 * 60
    assert reset_after("429 Too Many Requests; Retry-After: 120", at) == at + 120
    assert reset_after("usage limit reached; resets at 1970-01-13T00:00:00+00:00", at) == 12 * 86400
    assert reset_after("usage limit reached; resets at 1970-01-13T00:00:00Z", at) == 12 * 86400
    assert reset_after("Your credit balance is too low", at) == at + DEFAULT_HOLD
    assert reset_after("weekly limit, resets in 30 days", at) == at + CAP
    assert (
        reset_after("usage limit reached; resets at 1970-01-01T00:00:00Z", at) == at + DEFAULT_HOLD
    )  # a past reset says nothing


@pytest.mark.parametrize("pack_file", PACKS)
def test_a_quota_wall_holds_the_providers_seats_until_reset_with_one_inbox_row(env, pack_file, monkeypatch):
    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    pack = load(pack_file)
    from cockpitlib.kanban import place_card
    from cockpitlib.quota import step

    judged, worked = _providers(pack)
    now = time.time()
    ticket = f"{pack['tracker']['project']}-71"
    walled = place_card(pack["board"], f"{ticket}: worker", "worker-1", "ready")
    analyst = place_card(pack["board"], f"{ticket}: analyst", "analyst", "ready")
    reviewer = place_card(pack["board"], f"{ticket}: review", "reviewer", "ready")
    _run(
        pack,
        walled,
        "worker-1",
        "rate_limited",
        int(now) - 30,
        error="pid 1 exited rate-limited (quota wall) — requeued without counting a failure",
    )
    _worker_log(
        pack,
        walled,
        "working...\nProvider said: HTTP 502: Weekly usage limit reached. It resets in 5 days. "
        "Buy credits to keep going now.\nSession: local-abc\n\n[kanban-worker-exit] rc=75\n",
    )
    step(pack, now=now)
    # every ready card of a seat on that provider waits (scheduled, no failure counted); another provider's does not
    assert _status(pack, walled) == "scheduled" and _status(pack, analyst) == "scheduled"
    assert _status(pack, reviewer) == "ready"
    rows = {ident: row for ident, row in _rows().items() if ident.startswith("provider-hold-")}
    assert list(rows) == ["provider-hold-" + worked]
    what = rows["provider-hold-" + worked]["what"]
    assert what.startswith(f"provider {worked} limit reached; held until ")
    assert "worker-1" in what and "analyst" in what and "Weekly usage limit reached. It resets in 5 days" in what
    assert "reviewer" not in what
    # a new card for a seat on that provider is refused with the hold; another provider's seat still starts
    client = _client()
    refused = client.post("/kickoff", json={"ticket": "TASK-100", "mode": "analyst", "prompt": "why"})
    assert refused.status_code == 409 and f"provider {worked} limit reached; held until " in refused.json()["detail"]
    other = client.post(
        "/kickoff",
        json={"ticket": f"{pack['tracker']['project']}-72", "mode": "intake", "prompt": "the report is wrong"},
    )
    assert "limit reached" not in other.text
    # a second wall on the same provider extends the hold: still one row
    again = place_card(pack["board"], f"{ticket}: tester", "tester-1", "ready")
    _run(
        pack,
        again,
        "tester-1",
        "crashed",
        int(now) + 30,
        error="pid 2 exited with code 1 Worker's last output: 'Provider said: HTTP 502: Weekly usage limit reached. It resets in 6 days.'",
    )
    step(pack, now=now + 60)
    assert _status(pack, again) == "scheduled"
    assert [ident for ident in _rows() if ident.startswith("provider-hold-")] == ["provider-hold-" + worked]
    from cockpitlib.quota import holds

    held = holds(now=now + 60)
    assert set(held) == {worked} and held[worked]["until"] == int(now) + 30 + 6 * 86400
    # at reset the hold, its row and the wait end: the cards are ready again (the next one may try)
    step(pack, now=now + 7 * 86400)
    assert holds(now=now + 7 * 86400) == {}
    assert not [ident for ident in _rows() if ident.startswith("provider-hold-")]
    assert {_status(pack, card) for card in (walled, analyst, again)} == {"ready"}


@pytest.mark.parametrize("pack_file", PACKS)
def test_a_later_success_on_the_provider_clears_its_hold_and_a_wall_without_a_reset_holds_half_an_hour(
    env, pack_file, monkeypatch
):
    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    pack = load(pack_file)
    from cockpitlib.kanban import place_card
    from cockpitlib.quota import DEFAULT_HOLD, holds, step

    _judged, worked = _providers(pack)
    now = int(time.time())
    walled = place_card(pack["board"], "TASK-5: worker", "worker-1", "ready")
    _run(pack, walled, "worker-1", "rate_limited", now - 10, error="pid 1 exited rate-limited (quota wall)")
    _worker_log(
        pack,
        walled,
        "[kanban-worker-exit] rc=75\nBilling or credits exhausted: HTTP 400: Your credit balance is too low.\n",
    )
    step(pack, now=now)
    assert holds(now=now)[worked]["until"] == now - 10 + DEFAULT_HOLD
    assert "credit balance is too low" in _rows()["provider-hold-" + worked]["what"]
    assert _status(pack, walled) == "scheduled"
    step(pack, now=now + 60)  # the same run read again extends nothing and adds no row
    assert holds(now=now + 60)[worked]["until"] == now - 10 + DEFAULT_HOLD
    # a card that ran on that provider after the wall and finished: the provider answers again
    done = place_card(pack["board"], "TASK-6: analyst", "analyst", "ready")
    _run(pack, done, "analyst", "completed", now + 120, started=now + 30)
    step(pack, now=now + 180)
    assert holds(now=now + 180) == {} and "provider-hold-" + worked not in _rows()
    assert _status(pack, walled) == "ready"
    step(pack, now=now + 240)  # the old wall is not read as new
    assert holds(now=now + 240) == {}
    # a wall from before the seat was set up again (a provider switch) says nothing about the provider it runs now
    from cockpitlib.lanes import profile_dir

    switched = place_card(pack["board"], "TASK-7: worker", "worker-1", "ready")
    _run(
        pack,
        switched,
        "worker-1",
        "crashed",
        now + 300,
        error="Provider said: HTTP 502: Weekly usage limit reached. It resets in 4 days.",
    )
    os.makedirs(profile_dir("worker-1"), exist_ok=True)
    config = os.path.join(profile_dir("worker-1"), "config.yaml")
    open(config, "w", encoding="utf-8").write("model: {}\n")
    os.utime(config, (now + 400, now + 400))
    step(pack, now=now + 500)
    assert holds(now=now + 500) == {} and _status(pack, switched) == "ready"


@pytest.mark.parametrize("pack_file", PACKS)
def test_a_waiting_card_is_still_open_so_no_twin_starts_beside_it(env, pack_file, monkeypatch):
    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    pack = load(pack_file)
    from cockpitlib.kanban import BoardWrites, open_card_rows, open_cards
    from tests.support.boards import put_card

    card = put_card(pack["board"], "TASK-12: worker", "worker-1", "ready")
    writes = BoardWrites(pack["board"])
    writes.schedule(card, "provider x limit reached; held until later")
    assert writes.flush() == [True]
    assert open_cards(pack["board"]).get("worker-1") == 1
    assert [row["status"] for row in open_card_rows(pack["board"], pack) if row["id"] == card] == ["scheduled"]


# ---------- 3. at the ceiling a running card finishes its turn; its retry and new cards wait ----------


@pytest.mark.parametrize("pack_file", PACKS)
def test_at_the_ceiling_a_running_card_finishes_but_retries_and_follow_ups_wait_until_under(
    env, pack_file, monkeypatch
):
    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    pack = load(pack_file)
    from cockpitlib.quota import step
    from tests.support.boards import put_card

    judged, worked = _providers(pack)
    ceiling = pack["budget"]["plan_window_max_pct"]
    later = "2099-01-01T00:00:00+00:00"
    now = time.time()
    running = put_card(pack["board"], "TASK-8: worker", "worker-1", "running")
    retry = put_card(pack["board"], "TASK-9: worker", "worker-2" if pack["seats"]["slots"] > 1 else "worker-1", "ready")
    _run(pack, retry, "worker-1", "crashed", int(now) - 30, error="pid 3 exited with code 1")
    follow = put_card(pack["board"], "TASK-9: test", "tester-1", "ready")
    other = put_card(pack["board"], "TASK-9: review", "reviewer", "ready")
    _usage(
        {
            worked: {"windows": [{"label": "week", "used_percent": ceiling + 1, "resets_at": later}]},
            judged: {"windows": [{"label": "week", "used_percent": 1, "resets_at": later}]},
        }
    )
    step(pack, now=now)
    assert _status(pack, running) == "running"  # never killed
    assert _status(pack, retry) == "scheduled" and _status(pack, follow) == "scheduled"
    assert _status(pack, other) == "ready"  # the other provider is under its ceiling
    assert not [ident for ident in _rows() if ident.startswith("provider-hold-")]  # the ceiling is no provider wall
    # scheduled cards wait on time, not on the human: they are no "asks" row in the Inbox
    asks = [card for card in _client().get("/needs-you").json()["cards"] if card["status"] in ("blocked", "triage")]
    assert not asks
    _usage(
        {
            worked: {"windows": [{"label": "week", "used_percent": ceiling - 1, "resets_at": later}]},
            judged: {"windows": [{"label": "week", "used_percent": 1, "resets_at": later}]},
        }
    )
    _forget_cache()
    step(pack, now=now + 60)
    assert _status(pack, retry) == "ready" and _status(pack, follow) == "ready" and _status(pack, running) == "running"


@pytest.mark.parametrize("pack_file", PACKS)
def test_a_spend_cap_reached_holds_every_provider_and_a_card_scheduled_by_someone_else_is_left_alone(
    env, pack_file, monkeypatch
):
    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    pack = load(pack_file)
    from cockpitlib.kanban import BoardWrites
    from cockpitlib.quota import step
    from tests.support.boards import put_card

    if not pack["budget"]["monthly_usd"]:
        pytest.skip("this pack sets no spend cap")
    monkeypatch.setattr("cockpitlib.usage.spent_this_month", lambda now=None: pack["budget"]["monthly_usd"] + 1)
    mine = put_card(pack["board"], "TASK-10: worker", "worker-1", "ready")
    theirs = put_card(pack["board"], "TASK-11: review", "reviewer", "ready")
    writes = BoardWrites(pack["board"])
    writes.schedule(theirs, "the lane's own wait")
    writes.flush()
    step(pack)
    assert _status(pack, mine) == "scheduled" and _status(pack, theirs) == "scheduled"
    monkeypatch.setattr("cockpitlib.usage.spent_this_month", lambda now=None: 0.0)
    step(pack)
    assert _status(pack, mine) == "ready" and _status(pack, theirs) == "scheduled"


@pytest.mark.parametrize("pack_file", PACKS)
def test_the_quota_step_runs_in_housekeeping(env, pack_file, monkeypatch):
    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    pack = load(pack_file)
    from cockpitlib.housekeeping import STEPS

    assert "quota" in dict(STEPS)
    assert dict(STEPS)["quota"](pack).startswith("0 held")


# ---------- review round: races, stranded cards, scheduled test cards, replayed walls ----------


def _over(pack, worked, judged, over=True) -> None:
    ceiling = pack["budget"]["plan_window_max_pct"]
    later = "2099-01-01T00:00:00+00:00"
    _usage(
        {
            worked: {
                "windows": [{"label": "week", "used_percent": ceiling + 1 if over else ceiling - 1, "resets_at": later}]
            },
            judged: {"windows": [{"label": "week", "used_percent": 1, "resets_at": later}]},
        }
    )
    _forget_cache()


def _waiting() -> dict:
    from cockpitlib.quota import HOLDS_FILE, _load

    return _load(HOLDS_FILE).get("waiting") or {}


def _forget_waiting() -> None:
    from cockpitlib.quota import HOLDS_FILE, _load, _save

    state = _load(HOLDS_FILE)
    state["waiting"] = {}
    _save(HOLDS_FILE, state)


@pytest.mark.parametrize("pack_file", PACKS)
def test_schedule_refuses_a_card_that_was_claimed_or_started_since_it_was_read(env, pack_file, monkeypatch):
    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    pack = load(pack_file)
    from cockpitlib.kanban import BoardWrites
    from tests.support.boards import put_card, raw

    claimed = put_card(pack["board"], "TASK-20: worker", "worker-1", "ready")
    running = put_card(pack["board"], "TASK-21: worker", "worker-1", "running")
    connection = raw(pack["board"])
    connection.execute("update tasks set claim_lock = 'host:1' where id = ?", (claimed,))
    connection.execute("update tasks set worker_pid = 4242, claim_lock = 'host:2' where id = ?", (running,))
    connection.commit()
    connection.close()
    writes = BoardWrites(pack["board"])
    writes.schedule(claimed, "provider x limit reached; held until later")
    writes.schedule(running, "provider x limit reached; held until later")
    assert writes.flush() == [False, False]
    connection = raw(pack["board"])
    rows = dict(
        (card, (status, lock, pid))
        for card, status, lock, pid in connection.execute(
            "select id, status, claim_lock, worker_pid from tasks where id in (?, ?)", (claimed, running)
        )
    )
    connection.close()
    assert rows[claimed] == ("ready", "host:1", None)
    assert rows[running] == ("running", "host:2", 4242)  # its worker keeps running and is still known


@pytest.mark.parametrize("pack_file", PACKS)
def test_a_card_claimed_between_the_read_and_the_write_keeps_running_and_is_not_cockpits(env, pack_file, monkeypatch):
    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    pack = load(pack_file)
    from cockpitlib import kanban
    from cockpitlib.quota import step
    from tests.support.boards import put_card, raw

    judged, worked = _providers(pack)
    card = put_card(pack["board"], "TASK-22: worker", "worker-1", "ready")
    _over(pack, worked, judged)
    real = kanban.BoardWrites.flush

    def claimed_meanwhile(self):
        # the dispatcher claims the card after housekeeping read the board and before the helper writes
        connection = raw(pack["board"])
        connection.execute(
            "update tasks set status = 'running', claim_lock = 'host:9', worker_pid = 777 where id = ?", (card,)
        )
        connection.commit()
        connection.close()
        return real(self)

    monkeypatch.setattr(kanban.BoardWrites, "flush", claimed_meanwhile)
    step(pack, now=time.time())
    monkeypatch.setattr(kanban.BoardWrites, "flush", real)
    connection = raw(pack["board"])
    assert connection.execute("select status, worker_pid from tasks where id = ?", (card,)).fetchone() == (
        "running",
        777,
    )
    connection.close()
    assert card not in _waiting()


@pytest.mark.parametrize("pack_file", PACKS)
def test_a_helper_that_dies_mid_flush_leaves_no_parked_card_behind(env, pack_file, monkeypatch):
    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    pack = load(pack_file)
    from cockpitlib import hermes_runtime
    from cockpitlib.errors import CockpitError
    from cockpitlib.quota import step
    from tests.support.boards import put_card

    judged, worked = _providers(pack)
    card = put_card(pack["board"], "TASK-23: worker", "worker-1", "ready")
    _over(pack, worked, judged)
    real = hermes_runtime.run_helper

    def dies_after_writing(name, payload, *args, **kwargs):
        answer = real(name, payload, *args, **kwargs)
        if name == "board":
            raise CockpitError("helper board: killed")
        return answer

    monkeypatch.setattr(hermes_runtime, "run_helper", dies_after_writing)
    now = time.time()
    with pytest.raises(CockpitError):
        step(pack, now=now)
    monkeypatch.setattr(hermes_runtime, "run_helper", real)
    assert _status(pack, card) == "scheduled"
    assert card in _waiting()  # the intent was recorded before the write
    _over(pack, worked, judged, over=False)
    step(pack, now=now + 60)
    assert _status(pack, card) == "ready" and card not in _waiting()


@pytest.mark.parametrize("pack_file", PACKS)
def test_a_card_cockpit_parked_without_a_record_is_adopted_and_released_but_never_someone_elses(
    env, pack_file, monkeypatch
):
    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    pack = load(pack_file)
    from cockpitlib.kanban import BoardWrites
    from cockpitlib.quota import step
    from tests.support.boards import put_card

    judged, worked = _providers(pack)
    mine = put_card(pack["board"], "TASK-24: worker", "worker-1", "ready")
    taken = put_card(pack["board"], "TASK-25: tester", "tester-1", "ready")
    theirs = put_card(pack["board"], "TASK-26: analyst", "analyst", "ready")
    writes = BoardWrites(pack["board"])
    writes.schedule(theirs, "the lane's own wait")
    writes.flush()
    _over(pack, worked, judged)
    now = time.time()
    step(pack, now=now)
    assert _status(pack, mine) == "scheduled" and _status(pack, taken) == "scheduled"
    # someone else takes over one of cockpit's cards: released, then parked again for their own reason
    writes.unblock(taken)
    writes.schedule(taken, "a human's wait until Monday")
    writes.flush()
    _forget_waiting()  # the record of what cockpit parked is lost (a crash before it was saved)
    _over(pack, worked, judged, over=False)
    step(pack, now=now + 60)
    assert _status(pack, mine) == "ready"  # adopted from its own reason on the board, and released
    assert _status(pack, taken) == "scheduled" and _status(pack, theirs) == "scheduled"
    assert _waiting() == {}


@pytest.mark.parametrize("pack_file", PACKS)
def test_a_run_ending_fails_a_waiting_test_card_too(env, pack_file, monkeypatch):
    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    pack = load(pack_file)
    from cockpitlib.acts import finish_open_runs
    from cockpitlib.kanban import BoardWrites, block_reason
    from tests.support.boards import put_card, raw

    card = put_card(pack["board"], "TASK-27: test", "tester-1", "ready")
    writes = BoardWrites(pack["board"])
    writes.schedule(card, "provider x limit reached; held until later")
    assert writes.flush() == [True]
    assert finish_open_runs(pack, "TASK-27") == [card]
    assert _status(pack, card) == "blocked"
    reader = raw(pack["board"])
    assert block_reason(reader, card) == f"failed {pack['name']}"
    reader.close()


@pytest.mark.parametrize("pack_file", PACKS)
def test_a_waiting_intake_card_still_holds_the_work_behind_it(env, pack_file, monkeypatch):
    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    pack = load(pack_file)
    from cockpitlib.acts import intake_waiting
    from cockpitlib.kanban import BoardWrites, place_card

    card = place_card(pack["board"], "TASK-28: intake", "intake", "ready", ticket="TASK-28", pack=pack)
    writes = BoardWrites(pack["board"])
    writes.schedule(card, "provider x limit reached; held until later")
    assert writes.flush() == [True]
    assert intake_waiting(pack, "TASK-28") == card


def _run_with(pack, card, lane, outcome, ended, error="", metadata=None) -> None:
    from cockpitlib.kanban import db_path

    connection = sqlite3.connect(db_path(pack["board"]))
    connection.execute(
        "insert into task_runs (task_id, profile, status, started_at, ended_at, outcome, error, metadata) "
        "values (?, ?, ?, ?, ?, ?, ?, ?)",
        (card, lane, outcome, ended - 60, ended, outcome, error, json.dumps(metadata) if metadata else None),
    )
    connection.commit()
    connection.close()


def _seat_config(lane, provider, at) -> None:
    from cockpitlib.lanes import profile_dir

    os.makedirs(profile_dir(lane), exist_ok=True)
    path = os.path.join(profile_dir(lane), "config.yaml")
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(f"model:\n  default: some-model\n  provider: {provider}\n")
    os.utime(path, (at, at))


WALL = "pid 1 exited with code 1 Provider said: HTTP 502: Weekly usage limit reached. It resets in 5 days."


@pytest.mark.parametrize("pack_file", PACKS)
def test_a_cursor_wall_from_days_ago_does_not_hold_the_provider_the_seat_runs_now(env, pack_file, monkeypatch):
    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    pack = load(pack_file)
    from cockpitlib.kanban import place_card
    from cockpitlib.quota import holds, step

    _judged, worked = _providers(pack)  # stands for the Direct SDK provider the worker seat runs now
    now = int(time.time())
    # the seat's config (not set up again since) says it ran Cursor when it hit the wall three days ago
    _seat_config("worker-1", "cursor-agent", now - 4 * 86400)
    card = place_card(pack["board"], "TASK-30: worker", "worker-1", "ready")
    _run_with(pack, card, "worker-1", "crashed", now - 3 * 86400, error=WALL)
    step(pack, now=now)
    assert holds(now=now) == {} and _status(pack, card) == "ready"


@pytest.mark.parametrize("pack_file", PACKS)
def test_a_wall_whose_run_names_another_provider_holds_nothing(env, pack_file, monkeypatch):
    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    pack = load(pack_file)
    from cockpitlib.kanban import place_card
    from cockpitlib.quota import holds, step

    now = int(time.time())
    card = place_card(pack["board"], "TASK-31: worker", "worker-1", "ready")
    _run_with(pack, card, "worker-1", "crashed", now - 600, error=WALL, metadata={"provider": "cursor-agent"})
    step(pack, now=now)
    assert holds(now=now) == {}


@pytest.mark.parametrize("pack_file", PACKS)
def test_a_wall_on_an_unknown_provider_counts_only_from_the_last_day_and_a_known_match_from_the_week(
    env, pack_file, monkeypatch
):
    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    pack = load(pack_file)
    from cockpitlib.kanban import place_card
    from cockpitlib.quota import holds, step

    _judged, worked = _providers(pack)
    now = int(time.time())
    old = place_card(pack["board"], "TASK-32: worker", "worker-1", "ready")
    _run_with(pack, old, "worker-1", "crashed", now - 2 * 86400, error=WALL)  # no config, no metadata: unknown
    step(pack, now=now)
    assert holds(now=now) == {}
    recent = place_card(pack["board"], "TASK-33: worker", "worker-1", "ready")
    _run_with(pack, recent, "worker-1", "crashed", now - 3600, error=WALL)
    step(pack, now=now + 1)
    assert set(holds(now=now + 1)) == {worked}
    # a seat whose config says it ran this very provider then: its wall from days ago still holds
    from cockpitlib.quota import HOLDS_FILE, _save

    _save(HOLDS_FILE, {})
    _seat_config("analyst", worked, now - 4 * 86400)
    known = place_card(pack["board"], "TASK-34: analyst", "analyst", "ready")
    _run_with(pack, known, "analyst", "crashed", now - 2 * 86400, error=WALL)
    later = now + 2
    from cockpitlib.kanban import db_path

    connection = sqlite3.connect(db_path(pack["board"]))
    connection.execute("delete from task_runs where task_id = ?", (recent,))
    connection.commit()
    connection.close()
    step(pack, now=later)
    assert set(holds(now=later)) == {worked} and holds(now=later)[worked]["cards"] == [known]


@pytest.mark.parametrize("pack_file", PACKS)
def test_failing_a_waiting_test_card_never_blocks_one_a_worker_claimed_in_between(env, pack_file, monkeypatch):
    """finish_open_runs unblocks a parked test card and then blocks it: a dispatcher claim between the two must win
    (the worker runs on, its pid kept), and the card is not reported failed."""
    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    pack = load(pack_file)
    from cockpitlib import kanban
    from cockpitlib.acts import finish_open_runs
    from tests.support.boards import put_card, raw

    card = put_card(pack["board"], "TASK-29: test", "tester-1", "ready")
    writes = kanban.BoardWrites(pack["board"])
    writes.schedule(card, "provider x limit reached; held until later")
    assert writes.flush() == [True]
    real = kanban.BoardWrites.flush

    def claimed_between(self):
        if [op["op"] for op in self.ops] == ["unblock", "block"]:
            unblock, block = self.ops
            self.ops = [unblock]
            done = real(self)
            connection = raw(pack["board"])
            connection.execute(
                "update tasks set status = 'running', claim_lock = 'host:9', worker_pid = 777 where id = ?", (card,)
            )
            connection.commit()
            connection.close()
            self.ops = [block]
            return done + real(self)
        return real(self)

    monkeypatch.setattr(kanban.BoardWrites, "flush", claimed_between)
    assert finish_open_runs(pack, "TASK-29") == []
    connection = raw(pack["board"])
    assert connection.execute("select status, worker_pid from tasks where id = ?", (card,)).fetchone() == (
        "running",
        777,
    )
    connection.close()


@pytest.mark.parametrize("pack_file", PACKS)
def test_a_card_cockpit_parked_whose_lane_lost_its_provider_is_still_released(env, pack_file, monkeypatch):
    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    pack = load(pack_file)
    from cockpitlib.kanban import BoardWrites
    from cockpitlib.quota import MARK, step
    from tests.support.boards import put_card

    judged, worked = _providers(pack)
    card = put_card(pack["board"], "TASK-30: gone", "no-such-lane", "ready")
    writes = BoardWrites(pack["board"])
    writes.schedule(card, f"{MARK}provider x limit reached; held until later")
    assert writes.flush() == [True]
    _forget_waiting()
    _over(pack, worked, judged)
    step(pack, now=time.time())
    assert _status(pack, card) == "ready", "an unknown provider is under no ceiling cockpit knows: released"
