# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Plan pace: how a subscription's usage windows are being spent against cockpit's quota ceiling. Insight only:
nothing here gates, parks or starts a card.

Three parts, each replaceable on its own:

- `PlanPaceSource` (abstract): a provider's plan windows as `PlanWindow`s (name, used %, reset, length, scope) with when
  they were read. One subclass per kind of plan, registered with `@register`; `source_for(provider)` picks the first
  that handles the provider. A new provider is one new subclass, nothing else changes. `MaxPlanSource` reads the
  coding tool's subscription (Max, Pro) through `usage.plan_windows` (Hermes's reader first, the plan's own figures when it cannot).
- `PaceCalculator` (pure: no I/O, no provider knowledge): per window the ideal % by now (the target spread linearly
  over the window's active hours), the verdict against it (ahead / on / behind, a band of 3 points), the % projected
  at the reset at the current pace, the budget per remaining active hour, the active hours left; and which window
  binds (the account window most ahead of its ideal).
- `Schedule`: the active hours (days, start, end; all hours by default; an end before the start crosses midnight and
  belongs to the start's day). Peak hours (05:00-11:00 America/Los_Angeles on weekdays, when the plan's sessions
  drain faster) are off by default; when on they are left out of the spendable hours entirely: the ideal does not
  grow during them and the budget is spread over the hours outside them.

`efficiency` adds what the week's seat sessions and card runs say: tokens per card run (no passed-step count is
known to cockpit), the share of runs that failed or were retried, the Opus share of tokens, the cache-read share of
input. `pace(pack, ...)` puts it together for `cockpit pace --json` and the Usage page.
"""

import datetime
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from .store import read_db

BAND = 3.0
HOUR = 3600.0
SESSION = 5 * HOUR
WEEK = 7 * 86400.0
ALL_DAYS = frozenset(range(7))
PEAK_ZONE = "America/Los_Angeles"
PEAK_START, PEAK_END = datetime.time(5), datetime.time(11)
PEAK_DAYS = frozenset(range(5))
# Hermes run outcomes that spent tokens on work that did not stand (cockpitlib.quota.FAILED plus walls and reclaims)
WASTED = ("crashed", "timed_out", "spawn_failed", "failed", "rate_limited", "reclaimed", "gave_up")


# ---------- the data ----------


@dataclass(frozen=True)
class PlanWindow:
    name: str
    used: float
    resets_at: float  # epoch seconds
    length: float  # seconds
    scope: str = "account"


@dataclass(frozen=True)
class WindowPace:
    name: str
    used: float
    resets_at: float
    scope: str
    ideal: float
    verdict: str
    projected: float
    budget_per_hour: float
    active_hours_left: float


@dataclass(frozen=True)
class PaceReport:
    windows: list
    binding: str
    verdict: str


def _local_zone():
    return datetime.datetime.now().astimezone().tzinfo


@dataclass(frozen=True)
class Schedule:
    """Active hours: on `days` (0 = Monday) from `start` to `end` in `tz`; start == end is the whole day."""

    days: frozenset = ALL_DAYS
    start: datetime.time = datetime.time(0)
    end: datetime.time = datetime.time(0)
    tz: object = field(default_factory=_local_zone)

    @property
    def always(self) -> bool:
        return self.days == ALL_DAYS and self.start == self.end

    def describe(self) -> str:
        if self.always:
            return "all hours"
        names = "Mon Tue Wed Thu Fri Sat Sun".split()
        days = ",".join(names[day] for day in sorted(self.days))
        hours = "all day" if self.start == self.end else f"{self.start.strftime('%H:%M')}-{self.end.strftime('%H:%M')}"
        return f"{days} {hours}"

    def intervals(self, begin: float, end: float) -> list:
        """The active intervals (epoch pairs) overlapping [begin, end], clipped to it."""
        return _daily(self.days, self.start, self.end, self.tz, begin, end)


def _daily(days, start, stop, zone, begin: float, end: float) -> list:
    if end <= begin:
        return []
    first = datetime.datetime.fromtimestamp(begin, zone).date() - datetime.timedelta(days=1)
    last = datetime.datetime.fromtimestamp(end, zone).date()
    out = []
    day = first
    while day <= last:
        if day.weekday() in days:
            opens = datetime.datetime.combine(day, start, zone).timestamp()
            shut_day = day if stop > start else day + datetime.timedelta(days=1)
            shuts = datetime.datetime.combine(shut_day, stop, zone).timestamp()
            low, high = max(opens, begin), min(shuts, end)
            if high > low:
                out.append((low, high))
        day += datetime.timedelta(days=1)
    return out


def _overlap(left: list, right: list) -> float:
    total = 0.0
    for a, b in left:
        for c, d in right:
            total += max(0.0, min(b, d) - max(a, c))
    return total


# ---------- the calculator ----------


class PaceCalculator:
    """Pure: windows, the target %, the schedule, now in; the pace per window out."""

    def __init__(self, target_pct, schedule=None, peak=False, band=BAND):
        self.target = float(target_pct)
        self.schedule = schedule or Schedule()
        self.peak = bool(peak)
        self.band = float(band)

    def active_seconds(self, begin: float, end: float) -> float:
        active = self.schedule.intervals(begin, end)
        spent = sum(high - low for low, high in active)
        if not self.peak or not active:
            return spent
        from zoneinfo import ZoneInfo

        peak = _daily(PEAK_DAYS, PEAK_START, PEAK_END, ZoneInfo(PEAK_ZONE), begin, end)
        return max(0.0, spent - _overlap(active, peak))

    def window(self, window: PlanWindow, now: float) -> WindowPace:
        start = window.resets_at - window.length
        now = min(max(now, start), window.resets_at)
        total = self.active_seconds(start, window.resets_at)
        passed = self.active_seconds(start, now)
        left = self.active_seconds(now, window.resets_at)
        ideal = self.target * passed / total if total else self.target
        used = float(window.used)
        gap = used - ideal
        verdict = "ahead" if gap > self.band else "behind" if gap < -self.band else "on"
        projected = used + (used / passed) * left if passed else used
        hours_left = left / HOUR
        budget = max(0.0, self.target - used) / hours_left if hours_left else 0.0
        return WindowPace(
            name=window.name,
            used=used,
            resets_at=window.resets_at,
            scope=window.scope,
            ideal=ideal,
            verdict=verdict,
            projected=projected,
            budget_per_hour=budget,
            active_hours_left=hours_left,
        )

    def report(self, windows, now: float) -> PaceReport:
        paced = [self.window(window, now) for window in windows]
        candidates = [item for item in paced if item.scope == "account"] or paced
        binding = max(candidates, key=lambda item: item.used - item.ideal, default=None)
        return PaceReport(
            windows=paced, binding=binding.name if binding else "", verdict=binding.verdict if binding else "on"
        )


# ---------- the sources ----------

SOURCES = []


def register(cls):
    SOURCES.append(cls)
    return cls


def source_for(provider: str):
    for cls in SOURCES:
        if cls.handles(provider):
            return cls()
    return None


def _epoch(stamp):
    try:
        moment = datetime.datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return (moment if moment.tzinfo else moment.replace(tzinfo=datetime.UTC)).timestamp()


class PlanPaceSource(ABC):
    """A provider's plan windows for the calculator."""

    @classmethod
    @abstractmethod
    def handles(cls, provider: str) -> bool:
        """Whether this source reads that provider's plan."""

    @abstractmethod
    def windows(self, pack, provider: str, now: float, fresh: bool = False) -> dict:
        """{windows: [PlanWindow], read_at: epoch, stale: bool, error: str}."""


def window_length(name: str) -> float:
    """A subscription plan window's length from its label: the session is five hours, every weekly limit seven days."""
    return SESSION if "session" in str(name).lower() else WEEK


@register
class MaxPlanSource(PlanPaceSource):
    """The coding tool's subscription (Max, Pro): its 5-hour session, its week and any model's own week, from plan_windows."""

    @classmethod
    def handles(cls, provider: str) -> bool:
        from .usage import subscription_provider

        return subscription_provider(provider)

    def windows(self, pack, provider: str, now: float, fresh: bool = False) -> dict:
        from .usage import plan_windows

        read = plan_windows(pack, now, fresh=fresh)
        mine = [window for window in read.get("windows") or [] if window.get("provider") == provider]
        found, stale, read_at = [], False, now
        for window in mine:
            reset = _epoch(window.get("resets_at"))
            if reset is None:
                continue
            found.append(
                PlanWindow(
                    name=str(window.get("name")),
                    used=float(window.get("used") or 0),
                    resets_at=reset,
                    length=window_length(window.get("name")),
                    scope=str(window.get("scope") or "account"),
                )
            )
            if window.get("stale"):
                stale = True
                read_at = min(read_at, float(window.get("read_at") or now))
        if not mine:
            import json
            import os

            from .paths import watch_dir

            try:
                kept = json.load(open(os.path.join(watch_dir(), "plan-windows.json"), encoding="utf-8"))
                read_at = float(kept.get("at") or now)
            except (OSError, ValueError, TypeError, AttributeError):
                read_at = now
        error = str(read.get("error") or "") if (not found or stale) else ""
        return {"windows": found, "read_at": read_at, "stale": stale, "error": error}


# ---------- efficiency ----------


def _card_runs(pack, since: float) -> dict:
    """{runs, wasted}: the board's card runs that ended since then; zeros without a board."""
    import os
    import sqlite3

    from .kanban import db_path

    try:
        path = db_path((pack or {}).get("board") or "")
    except Exception:  # noqa: BLE001 - no board is no runs
        return {"runs": 0, "wasted": 0}
    if not path or not os.path.isfile(path):
        return {"runs": 0, "wasted": 0}
    try:
        connection = read_db(path)
        try:
            tables = {row[0] for row in connection.execute("select name from sqlite_master where type = 'table'")}
            if "task_runs" not in tables:
                return {"runs": 0, "wasted": 0}
            rows = connection.execute(
                "select outcome from task_runs where ended_at is not null and ended_at >= ?", (int(since),)
            ).fetchall()
        finally:
            connection.close()
    except sqlite3.Error:
        return {"runs": 0, "wasted": 0}
    return {"runs": len(rows), "wasted": sum(1 for (outcome,) in rows if str(outcome or "") in WASTED)}


def efficiency(pack, now: float) -> dict:
    """This week's seat sessions (the Usage page's week) and card runs, as plain figures; None where nothing to divide."""
    from .usage import periods, seat_rows

    since = periods(now)["week"]
    rows = [row for row in seat_rows() if float(row.get("epoch") or 0) >= since]
    tokens = sum(int(row.get(key) or 0) for row in rows for key in ("input", "output", "cache_read", "cache_write"))
    opus = sum(
        int(row.get(key) or 0)
        for row in rows
        if "opus" in str(row.get("model") or "").lower()
        for key in ("input", "output", "cache_read", "cache_write")
    )
    entered = sum(int(row.get(key) or 0) for row in rows for key in ("input", "cache_read", "cache_write"))
    cached = sum(int(row.get("cache_read") or 0) for row in rows)
    runs = _card_runs(pack, since)
    share = lambda part, whole: round(part / whole, 4) if whole else None  # noqa: E731
    return {
        "basis": "card run",
        "since": datetime.datetime.fromtimestamp(since, datetime.UTC).isoformat(),
        "tokens": tokens,
        "sessions": len(rows),
        "card_runs": runs["runs"],
        "wasted_runs": runs["wasted"],
        "tokens_per_run": round(tokens / runs["runs"]) if runs["runs"] else None,
        "wasted_share": share(runs["wasted"], runs["runs"]),
        "opus_share": share(opus, tokens),
        "cache_read_share": share(cached, entered),
    }


# ---------- the whole answer ----------


def parse_schedule(days=None, start=None, end=None, tz=None) -> Schedule:
    """Schedule from the CLI/route words ('0,1,2', '09:00', '19:00'); ValueError naming the flag when one is wrong."""
    picked = ALL_DAYS
    if days not in (None, ""):
        try:
            picked = frozenset(int(part) for part in str(days).split(",") if part.strip() != "")
        except ValueError:
            raise ValueError("--days takes weekday numbers 0-6 (0 = Monday), comma separated") from None
        if not picked or any(day < 0 or day > 6 for day in picked):
            raise ValueError("--days takes weekday numbers 0-6 (0 = Monday), comma separated")
    times = []
    for flag, value in (("--start", start), ("--end", end)):
        if value in (None, ""):
            times.append(datetime.time(0))
            continue
        try:
            times.append(datetime.datetime.strptime(str(value), "%H:%M").time())
        except ValueError:
            raise ValueError(f"{flag} takes a time HH:MM") from None
    return Schedule(days=picked, start=times[0], end=times[1], tz=tz or _local_zone())


def _iso(epoch) -> str:
    return datetime.datetime.fromtimestamp(float(epoch), datetime.UTC).isoformat() if epoch else ""


def _provider(pack) -> str:
    """The lane provider whose plan the pace reads: the worker's when it has a source, else the first that has one."""
    from .quota import kind_provider
    from .usage import providers_in_use

    worker = kind_provider(pack, "worker")
    ordered = ([worker] if worker else []) + sorted(providers_in_use(pack) - {worker})
    return next((provider for provider in ordered if source_for(provider)), worker or "")


def _sentence(item: WindowPace, target: float) -> str:
    if item.verdict == "ahead":
        return (
            f"{item.name}: {item.used:.0f}% used, ahead of the {item.ideal:.0f}% ideal by now; at this pace "
            f"{item.projected:.0f}% by the reset against a {target:.0f}% target."
        )
    if item.verdict == "behind":
        return (
            f"{item.name}: {item.used:.0f}% used, behind the {item.ideal:.0f}% ideal by now; "
            f"{item.budget_per_hour:.1f}% per active hour is left to spend before the reset."
        )
    return f"{item.name}: {item.used:.0f}% used, on pace with the {item.ideal:.0f}% ideal by now."


def blank(pack, error: str, now=None) -> dict:
    """The contract with nothing read and why."""
    target = 0
    try:
        from .settings import load

        target = int(load(pack)["budget"]["plan_window_max_pct"]) if pack else 0
    except Exception:  # noqa: BLE001 - a broken pack still gets its answer
        target = 0
    return {
        "provider": "",
        "target_pct": target,
        "read_at": _iso(time.time() if now is None else now),
        "stale": False,
        "error": error,
        "windows": [],
        "binding": "",
        "verdict": "on",
        "efficiency": {},
    }


def pace(pack, days=None, start=None, end=None, peak=False, fresh=False, now=None, detail=False) -> dict:
    """The contract `cockpit pace --json` prints; never raises: what could not be read or parsed is in `error`.
    `detail` adds what the Usage page shows beyond the contract (inputs, scope, one sentence per window)."""
    from .settings import load

    moment = time.time() if now is None else now
    out = blank(pack, "", moment)
    try:
        target = int(load(pack)["budget"]["plan_window_max_pct"])
    except Exception as exc:  # noqa: BLE001 - an unreadable quota limit is an error in the answer, not a crash
        out["error"] = f"quota limit unreadable: {exc}"[:200]
        return out
    try:
        schedule = parse_schedule(days, start, end)
    except ValueError as exc:
        out["error"] = str(exc)
        return out
    provider = _provider(pack)
    out["provider"] = provider
    try:
        out["efficiency"] = efficiency(pack, moment)
    except Exception as exc:  # noqa: BLE001 - efficiency is a side figure, never the reason pace fails
        out["efficiency"] = {"error": str(exc)[:200]}
    if detail:
        out["inputs"] = {
            "target_pct": target,
            "schedule": schedule.describe(),
            "peak": bool(peak),
            "peak_hours": f"weekdays {PEAK_START.strftime('%H:%M')}-{PEAK_END.strftime('%H:%M')} {PEAK_ZONE}, "
            "left out of the spendable hours"
            if peak
            else "not counted",
            "band": BAND,
            "now": _iso(moment),
        }
    source = source_for(provider)
    if source is None:
        out["error"] = f"no plan pace source for provider {provider or '(none)'}"
        return out
    try:
        read = source.windows(pack, provider, moment, fresh=fresh)
    except Exception as exc:  # noqa: BLE001 - exit 0 with the error, the supervisor's contract
        out["error"] = f"plan usage read failed: {str(exc)[:200]}"
        return out
    out.update(
        read_at=_iso(read.get("read_at") or moment), stale=bool(read.get("stale")), error=str(read.get("error") or "")
    )
    if not read["windows"] and not out["error"]:
        out["error"] = f"no plan window read for {provider}"
    report = PaceCalculator(target, schedule, peak).report(read["windows"], moment)
    for item in report.windows:
        row = {
            "name": item.name,
            "used": int(round(item.used)),
            "resets_at": _iso(item.resets_at),
            "ideal": round(item.ideal, 1),
            "verdict": item.verdict,
            "projected": round(item.projected, 1),
            "budget_per_hour": round(item.budget_per_hour, 2),
            "active_hours_left": round(item.active_hours_left, 1),
        }
        if detail:
            row.update(scope=item.scope, sentence=_sentence(item, target))
        out["windows"].append(row)
    out.update(binding=report.binding, verdict=report.verdict)
    return out
