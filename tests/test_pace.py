# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Plan pace: the coding tool subscription's own usage windows read without the coding tool (telemetry stays off), a pure pace
calculator, the provider registry, `cockpit pace --json` and the Usage page's Pace data. Both fixture packs see
the same outcomes; a pack on providers Hermes reads keeps Hermes's reader."""

import datetime
import json
import os
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
SUB = "claude-subscription-directsdk-experimental"
UTC = datetime.UTC
HOUR = 3600.0


def _at(*parts) -> float:
    return datetime.datetime(*parts, tzinfo=UTC).timestamp()


def _iso(epoch: float) -> str:
    return datetime.datetime.fromtimestamp(epoch, UTC).isoformat()


# ---------- 1. the calculator: pure, no I/O, no provider knowledge ----------


def _window(name="Current week", used=50.0, start=None, length=7 * 86400.0, scope="account"):
    from cockpitlib.pace import PlanWindow

    start = _at(2026, 11, 2) if start is None else start  # a Monday 00:00 UTC
    return PlanWindow(name=name, used=used, resets_at=start + length, length=length, scope=scope)


def test_the_ideal_spreads_the_target_linearly_over_the_window_and_the_band_is_three_points():
    from cockpitlib.pace import PaceCalculator, Schedule

    calc = PaceCalculator(target_pct=90, schedule=Schedule(tz=UTC))
    start = _at(2026, 11, 2)
    half = start + 3.5 * 86400
    on = calc.window(_window(used=46.0, start=start), half)
    assert on.ideal == pytest.approx(45.0) and on.verdict == "on"
    assert on.active_hours_left == pytest.approx(84.0)
    assert on.projected == pytest.approx(92.0)  # 46 % in 84 h, at that rate for 84 h more
    assert on.budget_per_hour == pytest.approx((90 - 46) / 84.0)
    assert calc.window(_window(used=48.1, start=start), half).verdict == "ahead"
    assert calc.window(_window(used=41.9, start=start), half).verdict == "behind"
    assert calc.window(_window(used=48.0, start=start), half).verdict == "on"  # exactly on the band edge is on
    # at the start nothing has passed: the ideal is zero and the projection is what is used
    first = calc.window(_window(used=0.0, start=start), start)
    assert first.ideal == 0 and first.projected == 0 and first.verdict == "on"
    # past the target: no budget left, never negative
    assert calc.window(_window(used=95.0, start=start), half).budget_per_hour == 0


def test_active_hours_count_only_the_schedule_and_a_schedule_may_cross_midnight():
    from cockpitlib.pace import PaceCalculator, Schedule

    start = _at(2026, 11, 2)  # Monday
    weekdays = Schedule(days=frozenset({0, 1, 2, 3, 4}), start=datetime.time(9), end=datetime.time(19), tz=UTC)
    calc = PaceCalculator(target_pct=90, schedule=weekdays)
    assert calc.active_seconds(start, start + 7 * 86400) == pytest.approx(50 * HOUR)
    wednesday_noon = start + 2 * 86400 + 12 * HOUR  # Mon, Tue whole + Wed 09-12 = 23 h passed
    result = calc.window(_window(used=30.0, start=start), wednesday_noon)
    assert result.ideal == pytest.approx(90 * 23 / 50)
    assert result.active_hours_left == pytest.approx(27.0)
    # a night shift 22:00-06:00 started on Monday and Tuesday: 16 h, of which Tuesday 00-06 belongs to Monday's shift
    night = Schedule(days=frozenset({0, 1}), start=datetime.time(22), end=datetime.time(6), tz=UTC)
    calc = PaceCalculator(target_pct=90, schedule=night)
    assert calc.active_seconds(start, start + 7 * 86400) == pytest.approx(16 * HOUR)
    assert calc.active_seconds(start + 86400, start + 86400 + 6 * HOUR) == pytest.approx(6 * HOUR)
    # the default is every hour
    assert PaceCalculator(target_pct=90, schedule=Schedule(tz=UTC)).active_seconds(
        start, start + 86400
    ) == pytest.approx(24 * HOUR)


def test_peak_hours_are_left_out_of_the_spendable_hours_when_turned_on():
    from cockpitlib.pace import PaceCalculator, Schedule

    start = _at(2026, 11, 2)  # Monday; Los Angeles is UTC-8 after Nov 1
    plain = PaceCalculator(target_pct=90, schedule=Schedule(tz=UTC))
    peaked = PaceCalculator(target_pct=90, schedule=Schedule(tz=UTC), peak=True)
    week = (start, start + 7 * 86400)
    assert plain.active_seconds(*week) == pytest.approx(168 * HOUR)
    assert peaked.active_seconds(*week) == pytest.approx((168 - 5 * 6) * HOUR)  # 05-11 Pacific, five weekdays
    # Monday 13:00-19:00 UTC is 05:00-11:00 Pacific: all peak
    assert peaked.active_seconds(start + 13 * HOUR, start + 19 * HOUR) == 0
    # the weekend has no peak
    assert peaked.active_seconds(start + 5 * 86400, start + 7 * 86400) == pytest.approx(48 * HOUR)


def test_the_binding_window_is_the_most_ahead_account_window_and_gives_the_verdict():
    from cockpitlib.pace import PaceCalculator, Schedule

    start = _at(2026, 11, 2)
    now = start + 3.5 * 86400
    calc = PaceCalculator(target_pct=90, schedule=Schedule(tz=UTC))
    session = _window(name="Current session", used=80.0, start=now - 2.5 * HOUR, length=5 * HOUR)
    week = _window(used=40.0, start=start)
    model = _window(name="Fable week", used=99.0, start=start, scope="model")
    report = calc.report([week, session, model], now)
    assert [item.name for item in report.windows] == ["Current week", "Current session", "Fable week"]
    assert report.binding == "Current session" and report.verdict == "ahead"
    assert calc.report([], now).binding == "" and calc.report([], now).verdict == "on"


# ---------- 2. the direct reader of the subscription's usage windows ----------


def _login(tmp_path, monkeypatch, expires_in=3600.0, token="fake-access-token"):
    folder = tmp_path / "claude"
    folder.mkdir(exist_ok=True)
    (folder / ".credentials.json").write_text(
        json.dumps({"claudeAiOauth": {"accessToken": token, "expiresAt": int((time.time() + expires_in) * 1000)}})
    )
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(folder))


LIVE_SHAPE = {
    "five_hour": {"utilization": 21.0, "resets_at": "2099-01-01T05:00:00+00:00"},
    "seven_day": {"utilization": 16.0, "resets_at": "2099-01-05T00:00:00+00:00"},
    "seven_day_opus": None,
    "seven_day_sonnet": None,
    "limits": [
        {"kind": "session", "group": "session", "percent": 21, "resets_at": "2099-01-01T05:00:00+00:00", "scope": None},
        {
            "kind": "weekly_all",
            "group": "weekly",
            "percent": 16,
            "resets_at": "2099-01-05T00:00:00+00:00",
            "scope": None,
        },
        {
            "kind": "weekly_scoped",
            "group": "weekly",
            "percent": 3,
            "resets_at": "2099-01-05T00:00:00+00:00",
            "scope": {"model": {"id": None, "display_name": "Fable"}, "surface": None},
        },
    ],
}


def test_the_direct_reader_maps_the_subscriptions_windows_and_sends_the_token_only_as_a_header(
    bare, tmp_path, monkeypatch
):
    from cockpitlib import plan_windows

    _login(tmp_path, monkeypatch)
    seen = {}

    def fetch(url, headers, timeout):
        seen.update(url=url, headers=headers)
        return LIVE_SHAPE

    read = plan_windows.read(fetch=fetch)
    assert seen["url"] == "https://api.anthropic.com/api/oauth/usage"
    assert (
        seen["headers"]["Authorization"] == "Bearer fake-access-token"
        and seen["headers"]["anthropic-beta"] == "oauth-2025-04-20"
    )
    assert read["error"] == ""
    assert read["windows"] == [
        {
            "label": "Current session",
            "used_percent": 21.0,
            "resets_at": "2099-01-01T05:00:00+00:00",
            "scope": "account",
        },
        {"label": "Current week", "used_percent": 16.0, "resets_at": "2099-01-05T00:00:00+00:00", "scope": "account"},
        {"label": "Fable week", "used_percent": 3.0, "resets_at": "2099-01-05T00:00:00+00:00", "scope": "model"},
    ]
    # an older response without limits[]: the top-level windows (fractions read as percent), Opus/Sonnet model-scoped
    legacy = {
        "five_hour": {"utilization": 0.4, "resets_at": "2099-01-01T05:00:00Z"},
        "seven_day": {"utilization": 12},
        "seven_day_opus": {"utilization": 30, "resets_at": "2099-01-05T00:00:00Z"},
        "seven_day_sonnet": "odd",
    }
    labels = [
        (w["label"], w["used_percent"], w["scope"]) for w in plan_windows.read(fetch=lambda *a, **k: legacy)["windows"]
    ]
    assert labels == [
        ("Current session", 40.0, "account"),
        ("Current week", 12.0, "account"),
        ("Opus week", 30.0, "model"),
    ]


def test_the_direct_reader_never_refreshes_and_says_why_it_could_not_read(bare, tmp_path, monkeypatch):
    from cockpitlib import plan_windows

    called = []
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "nowhere"))
    assert plan_windows.read(fetch=lambda *a, **k: called.append(1))["error"].startswith("no subscription login")
    _login(tmp_path, monkeypatch, expires_in=-60)
    expired = plan_windows.read(fetch=lambda *a, **k: called.append(1))
    assert expired["windows"] == [] and "expired" in expired["error"] and not called  # no call, no refresh
    _login(tmp_path, monkeypatch)

    def refused(*_a, **_k):
        raise plan_windows.ReadError("HTTP 401")

    failed = plan_windows.read(fetch=refused)
    assert failed == {"windows": [], "error": "plan usage read failed: HTTP 401"}
    assert "fake-access-token" not in json.dumps(failed)


# ---------- 3. the reader behind the budget gate ----------


@pytest.fixture
def sub_pack(request, env, monkeypatch):
    """A copy of the fixture pack with every seat on the subscription provider (a subscription-only pack)."""
    import shutil

    import yaml

    dest = env["root"] / "packs" / os.path.basename(os.path.dirname(request.param))
    shutil.copytree(os.path.dirname(request.param), dest)
    data = yaml.safe_load(open(dest / "pack.yaml", encoding="utf-8"))
    for entry in data["providers"].values():
        if isinstance(entry, dict) and entry.get("hermes_provider"):
            entry["hermes_provider"] = SUB
    open(dest / "pack.yaml", "w", encoding="utf-8").write(yaml.safe_dump(data))
    monkeypatch.setenv("COCKPIT_PACK", str(dest / "pack.yaml"))
    return str(dest / "pack.yaml")


def _usage(data) -> None:
    json.dump(data, open(os.path.join(os.environ["COCKPIT_ROOT"], "fake-usage.json"), "w", encoding="utf-8"))


def _forget_cache() -> None:
    from cockpitlib.paths import watch_dir

    path = os.path.join(watch_dir(), "plan-windows.json")
    if os.path.exists(path):
        os.remove(path)


def _rows() -> dict:
    from cockpitlib.inbox import rows

    return {row["id"]: row for row in rows() if row["plugin"] == "cockpit"}


@pytest.mark.parametrize("sub_pack", PACKS, indirect=True)
def test_when_hermes_cannot_read_the_subscription_the_direct_reader_answers_and_the_gate_and_inbox_follow(
    sub_pack, tmp_path, monkeypatch
):
    from cockpitlib import plan_windows
    from cockpitlib.quota import step
    from cockpitlib.settings import budget_state

    pack = load(sub_pack)
    ceiling = pack["budget"]["plan_window_max_pct"]
    _usage({SUB: {"unavailable": UNREADABLE}})
    start = time.time()
    answers = {"read": {"windows": [], "error": "plan usage read failed: HTTP 500"}}
    monkeypatch.setattr(plan_windows, "read", lambda fetch=None: answers["read"])
    blind = budget_state(pack, now=start)
    assert UNREADABLE in blind["error"] and "HTTP 500" in blind["error"] and blind["over"] is False
    _forget_cache()
    step(pack, now=start + 16 * 60)
    assert "plan-usage-" + SUB in _rows()  # neither reader answered: the row stands
    later = _iso(start + 3 * 86400)
    answers["read"] = {
        "windows": [
            {"label": "Current week", "used_percent": ceiling + 1, "resets_at": later, "scope": "account"},
            {"label": "Fable week", "used_percent": 100, "resets_at": later, "scope": "model"},
        ],
        "error": "",
    }
    _forget_cache()
    state = budget_state(pack, now=start + 17 * 60)
    assert state["error"] == "" and state["over"] is True and state["why"] == f"window Current week is {ceiling + 1}%"
    assert {w["name"]: w["used"] for w in state["windows"] if w["provider"] == SUB} == {
        "Current week": ceiling + 1,
        "Fable week": 100,
    }
    _forget_cache()
    step(pack, now=start + 18 * 60)
    assert "plan-usage-" + SUB not in _rows()  # the direct reader answered: the row leaves


@pytest.mark.parametrize("pack_file", PACKS)
def test_a_provider_hermes_reads_keeps_hermess_reader_and_others_never_reach_the_direct_one(
    env, pack_file, monkeypatch
):
    """A cockpit-only pack's path: Hermes's reader answers (for a subscription provider too), so the direct reader is never asked; nor for a
    provider that is not a subscription, nor for one Hermes has no reader for (unmetered stays unmetered)."""
    from cockpitlib import plan_windows
    from cockpitlib.settings import budget_state

    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    pack = load(pack_file)
    asked = []
    monkeypatch.setattr(plan_windows, "read", lambda fetch=None: asked.append(1) or {"windows": [], "error": "x"})
    _usage({"fixture-a": {"unavailable": UNREADABLE}})
    budget_state(pack, now=time.time())
    assert asked == []
    from cockpitlib.usage import subscription_provider

    assert subscription_provider(SUB) and subscription_provider("claude-code") and subscription_provider("claude-max")
    assert (
        not subscription_provider("fixture-a")
        and not subscription_provider("cursor")
        and not subscription_provider("anthropic")
    )


# ---------- 4. the source registry and `cockpit pace --json` ----------


def test_a_new_provider_is_one_source_class_and_unknown_providers_have_none():
    from cockpitlib.pace import MaxPlanSource, PlanPaceSource, register, source_for

    assert isinstance(source_for(SUB), MaxPlanSource) and isinstance(source_for("claude-code"), MaxPlanSource)
    assert source_for("cursor") is None

    @register
    class FakeSource(PlanPaceSource):
        @classmethod
        def handles(cls, provider):
            return provider == "fake-plan"

        def windows(self, pack, provider, now, fresh=False):
            return {"windows": [], "read_at": now, "stale": False, "error": ""}

    try:
        assert isinstance(source_for("fake-plan"), FakeSource)
    finally:
        from cockpitlib import pace

        pace.SOURCES.remove(FakeSource)


def test_the_max_plan_source_gives_each_window_its_length():
    from cockpitlib.pace import window_length

    assert window_length("Current session") == 5 * HOUR
    assert window_length("Current week") == 7 * 86400 and window_length("Fable week") == 7 * 86400
    assert window_length("Opus week") == 7 * 86400


CONTRACT = {"provider", "target_pct", "read_at", "stale", "error", "windows", "binding", "verdict", "efficiency"}
WINDOW_KEYS = {"name", "used", "resets_at", "ideal", "verdict", "projected", "budget_per_hour", "active_hours_left"}


@pytest.mark.parametrize("sub_pack", PACKS, indirect=True)
def test_cockpit_pace_json_keeps_its_contract(sub_pack, monkeypatch, capsys):
    from cockpitlib import plan_windows
    from cockpitlib.cli import main

    pack = load(sub_pack)
    _usage({SUB: {"unavailable": UNREADABLE}})
    now = time.time()
    monkeypatch.setattr(
        plan_windows,
        "read",
        lambda fetch=None: {
            "windows": [
                {"label": "Current session", "used_percent": 21, "resets_at": _iso(now + 2 * HOUR), "scope": "account"},
                {"label": "Current week", "used_percent": 16, "resets_at": _iso(now + 4 * 86400), "scope": "account"},
            ],
            "error": "",
        },
    )
    assert (
        main(["pace", "--json", "--days", "0,1,2,3,4", "--start", "09:00", "--end", "19:00", "--peak", "--fresh"]) == 0
    )
    out = json.loads(capsys.readouterr().out)
    assert set(out) == CONTRACT
    assert out["provider"] == SUB and out["target_pct"] == pack["budget"]["plan_window_max_pct"] and out["error"] == ""
    assert out["stale"] is False and out["read_at"].endswith("+00:00")
    assert [w["name"] for w in out["windows"]] == ["Current session", "Current week"]
    assert all(set(w) == WINDOW_KEYS for w in out["windows"])
    assert out["windows"][0]["used"] == 21 and isinstance(out["windows"][0]["ideal"], float)
    assert out["verdict"] in ("ahead", "on", "behind") and out["binding"] in ("Current session", "Current week")
    assert {"basis", "tokens", "tokens_per_run", "wasted_share", "opus_share", "cache_read_share"} <= set(
        out["efficiency"]
    )
    # the cache: without --fresh a second read inside five minutes asks no reader
    monkeypatch.setattr(plan_windows, "read", lambda fetch=None: pytest.fail("cached read asked the reader"))
    assert main(["pace", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["windows"][0]["used"] == 21


@pytest.mark.parametrize("pack_file", PACKS)
def test_cockpit_pace_exits_zero_with_the_error_when_nothing_is_readable_or_flags_are_wrong(
    bare, pack_file, monkeypatch, capsys
):
    from cockpitlib.cli import main

    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    _usage({"fixture-a": {"unavailable": UNREADABLE}})
    assert main(["pace", "--json"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert set(out) == CONTRACT and out["windows"] == [] and out["error"] and out["verdict"] == "on"
    assert main(["pace", "--json", "--start", "9am"]) == 0
    bad = json.loads(capsys.readouterr().out)
    assert set(bad) == CONTRACT and "--start" in bad["error"]
    assert main(["pace", "--json", "--days", "0,9"]) == 0
    assert "--days" in json.loads(capsys.readouterr().out)["error"]


def test_efficiency_reads_this_weeks_seat_sessions_and_card_runs(bare, monkeypatch):
    from cockpitlib import pace

    now = time.time()
    rows = [
        {
            "model": "claude-opus-5-5",
            "epoch": now - 3600,
            "input": 100,
            "output": 50,
            "cache_read": 800,
            "cache_write": 100,
        },
        {
            "model": "claude-sonnet-5",
            "epoch": now - 7200,
            "input": 300,
            "output": 150,
            "cache_read": 0,
            "cache_write": 0,
        },
        {
            "model": "claude-opus-5-5",
            "epoch": now - 30 * 86400,
            "input": 10**9,
            "output": 0,
            "cache_read": 0,
            "cache_write": 0,
        },
    ]
    monkeypatch.setattr("cockpitlib.usage.seat_rows", lambda: rows)
    monkeypatch.setattr(pace, "_card_runs", lambda pack, since: {"runs": 4, "wasted": 1})
    eff = pace.efficiency({}, now)
    assert eff["tokens"] == 1500 and eff["basis"] == "card run" and eff["tokens_per_run"] == 375
    assert eff["wasted_share"] == pytest.approx(0.25)
    assert eff["opus_share"] == pytest.approx(1050 / 1500)
    assert eff["cache_read_share"] == pytest.approx(800 / 1300, abs=1e-3)
    monkeypatch.setattr(pace, "_card_runs", lambda pack, since: {"runs": 0, "wasted": 0})
    empty = pace.efficiency({}, now)
    assert empty["tokens_per_run"] is None and empty["wasted_share"] is None


# ---------- 5. the Usage page's Pace route ----------


@pytest.mark.parametrize("sub_pack", PACKS, indirect=True)
def test_the_pace_route_feeds_the_usage_page_with_the_inputs_and_recalculate_bypasses_the_cache(sub_pack, monkeypatch):
    from cockpitlib import plan_windows

    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    _usage({SUB: {"unavailable": UNREADABLE}})
    now = time.time()
    reads = []

    def read(fetch=None):
        reads.append(1)
        return {
            "windows": [
                {
                    "label": "Current week",
                    "used_percent": 16 + len(reads),
                    "resets_at": _iso(now + 4 * 86400),
                    "scope": "account",
                }
            ],
            "error": "",
        }

    monkeypatch.setattr(plan_windows, "read", read)
    body = client.get("/pace").json()
    assert set(CONTRACT) <= set(body) and body["windows"][0]["used"] == 17
    assert (
        body["inputs"]["schedule"] == "all hours"
        and body["inputs"]["peak"] is False
        and "sentence" in body["windows"][0]
    )
    assert client.get("/pace").json()["windows"][0]["used"] == 17 and len(reads) == 1
    fresh = client.get("/pace?fresh=1&days=0,1,2,3,4&start=09:00&end=19:00&peak=1").json()
    assert (
        fresh["windows"][0]["used"] == 18 and fresh["inputs"]["peak"] is True and "09:00" in fresh["inputs"]["schedule"]
    )
    assert client.get("/pace?start=nope").status_code == 400
