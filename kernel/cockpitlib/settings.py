# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Seats and budget live in the pack. A page save overlays them under hermes/watch/."""

import json
import os

from .errors import CockpitError
from .paths import watch_dir
from .store import dump_json


def _base(pack) -> dict:
    budget = pack.get("budget") or {}
    return {
        "seats": dict(pack["seats"]),
        "budget": {
            "monthly_usd": float(budget.get("monthly_usd") or 0),
            "plan_window_max_pct": int(budget.get("plan_window_max_pct") or 90),
        },
        "shared_chrome_hours": int(pack["shared_chrome_hours"])
        if pack.get("shared_chrome_hours") not in (None, "")
        else 0,
        "worktree_gc": _worktree_gc_base(pack),
    }


def _worktree_gc_base(pack) -> dict:
    """The daily pass over stale worktrees (cockpitlib.cleanup): off unless the pack or a save turns it on."""
    from .cleanup import DEFAULT_DAYS

    given = pack.get("worktree_gc") or {}
    return {"enabled": bool(given.get("enabled", False)), "days": int(given.get("days") or DEFAULT_DAYS)}


def _flag(value) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)) and value in (0, 1):
        return bool(value)
    if isinstance(value, str) and value.strip().lower() in ("true", "false", "1", "0", "on", "off", "yes", "no"):
        return value.strip().lower() in ("true", "1", "on", "yes")
    raise ValueError("not a flag")


def _overlay_path() -> str:
    return os.path.join(watch_dir(), "settings.json")


def load(pack) -> dict:
    data = _base(pack)
    path = _overlay_path()
    if not os.path.isfile(path):
        return data
    try:
        overlay = json.load(open(path, encoding="utf-8"))
    except json.JSONDecodeError:
        return data
    if not isinstance(overlay, dict):
        return data
    if isinstance(overlay.get("seats"), dict):
        data["seats"] = {**data["seats"], **overlay["seats"]}
    if isinstance(overlay.get("budget"), dict):
        data["budget"] = {**data["budget"], **overlay["budget"]}
    if "shared_chrome_hours" in overlay:
        data["shared_chrome_hours"] = int(overlay["shared_chrome_hours"])
    if isinstance(overlay.get("worktree_gc"), dict):
        data["worktree_gc"] = {**data["worktree_gc"], **overlay["worktree_gc"]}
    return data


def save(pack, body) -> dict:
    """Persist seats, budget, and the browser-loan duration. The pack file stays the source a migrate wrote."""
    current = load(pack)
    nested = body.get("settings") if isinstance(body, dict) else None
    if isinstance(nested, dict):
        body = {**body, **nested}
    seats = body.get("seats") if isinstance(body.get("seats"), dict) else current["seats"]
    budget = body.get("budget") if isinstance(body.get("budget"), dict) else current["budget"]
    gc = body.get("worktree_gc") if isinstance(body.get("worktree_gc"), dict) else current["worktree_gc"]
    try:
        record = {
            "seats": {
                "slots": int(seats.get("slots", current["seats"]["slots"])),
                "intake": int(seats.get("intake", current["seats"]["intake"])),
                "reviewer": int(seats.get("reviewer", current["seats"]["reviewer"])),
                "analyst": int(seats.get("analyst", current["seats"]["analyst"])),
            },
            "budget": {
                "monthly_usd": float(budget.get("monthly_usd", current["budget"]["monthly_usd"])),
                "plan_window_max_pct": int(budget.get("plan_window_max_pct", current["budget"]["plan_window_max_pct"])),
            },
            "shared_chrome_hours": int(body.get("shared_chrome_hours", current["shared_chrome_hours"])),
            "worktree_gc": {
                "enabled": _flag(gc.get("enabled", current["worktree_gc"]["enabled"])),
                "days": int(gc.get("days", current["worktree_gc"]["days"])),
            },
        }
    except (TypeError, ValueError) as exc:
        raise CockpitError("settings must be numbers") from exc
    from .cleanup import DAYS_RANGE

    if not DAYS_RANGE[0] <= record["worktree_gc"]["days"] <= DAYS_RANGE[1]:
        raise CockpitError(f"worktree_gc.days is a whole number of days from {DAYS_RANGE[0]} to {DAYS_RANGE[1]}")
    path = _overlay_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    dump_json(path, record)
    _freeze(current, record)
    return record


def frozen_path() -> str:
    return os.path.join(watch_dir(), "frozen-seats.json")


def frozen() -> set:
    path = frozen_path()
    if not os.path.isfile(path):
        return set()
    try:
        data = json.load(open(path, encoding="utf-8"))
    except json.JSONDecodeError:
        return set()
    if not isinstance(data, list):
        return set()
    return {str(item) for item in data}


def _named(kind: str, count: int, per_slot: bool) -> list:
    from .lanes import lanes_of

    if count <= 0:
        return []
    return lanes_of(kind, count, per_slot)


def _mark(names: set, kind: str, per_slot: bool, old: int, new: int) -> None:
    if new < old:
        names.update(_named(kind, old, per_slot)[new:])
    names.difference_update(_named(kind, new, per_slot))


def _freeze(previous, record) -> None:
    """A seat removed from the overlay keeps its profile and receives no new cards."""
    names = set(frozen())
    for key in ("intake", "reviewer", "analyst"):
        _mark(names, key, False, int(previous["seats"].get(key) or 0), int(record["seats"][key]))
    old_slots = int(previous["seats"].get("slots") or 0)
    new_slots = int(record["seats"]["slots"])
    _mark(names, "worker", True, old_slots, new_slots)
    _mark(names, "tester", True, old_slots, new_slots)
    path = frozen_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    dump_json(path, sorted(names))


def missing_lanes(pack) -> list:
    """Overlay seats that do not have a profile yet. Apply creates those and leaves the rest."""
    from .lanes import profile_dir, seats_from

    shaped = dict(pack)
    shaped["seats"] = load(pack)["seats"]
    missing = []
    for names in seats_from(shaped).values():
        for lane in names:
            if os.path.isfile(os.path.join(profile_dir(lane), "config.yaml")):
                continue
            missing.append(lane)
    return missing


def lend_chrome(pack, ticket: str) -> dict:
    """The saved loan duration is the timer. The card is lent until that many hours pass."""
    import time

    from .paths import watch_dir

    hours = float(load(pack)["shared_chrome_hours"])
    started = int(time.time())
    record = {
        "ticket": ticket,
        "at": started,
        "until": started + int(hours * 3600),
        "hours": hours,
        "tabs": [],
    }
    path = os.path.join(watch_dir(), "shared-chrome.json")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    dump_json(path, record)
    return record


def ensure_seat_profiles(pack) -> list:
    """Create a profile for each overlay seat that does not have one. A removed seat keeps its profile.

    A seat is its config *and* its plugins. `_profile` writes the config, which names the provider the
    pack gives that kind — and the provider is a plugin, reached only through the seat's own plugins/.
    Creating one without the other made a lane that dispatch would hand cards to and whose every card
    then died in `_construct_agent` with `Unknown provider`, before the agent existed to say so.
    """
    from .lanes import profile_dir, seats_from
    from .setup import _profile, _seat_plugin

    shaped = dict(pack)
    shaped["seats"] = load(pack)["seats"]
    created = []
    for kind, lanes in seats_from(shaped).items():
        for lane in lanes:
            if os.path.isfile(os.path.join(profile_dir(lane), "config.yaml")):
                continue
            _profile(shaped, lane, kind)
            _seat_plugin(lane, shaped, kind)
            created.append(lane)
    return created


def over_budget(spent: float, cap: float, windows: list, max_pct: int, providers_in_use: set) -> str:
    reasons = []
    if cap and spent >= cap:
        reasons.append(f"spent {spent:.2f} of {cap:.2f}")
    for window in windows:
        provider = window.get("provider") or ""
        if provider not in providers_in_use:
            continue
        if window.get("used", 0) >= max_pct:
            reasons.append(f"window {window.get('name')} is {window.get('used')}%")
    return "; ".join(reasons)


def budget_state(pack, now=None) -> dict:
    """What stops new kickoffs: this month's spend against the cap, and the fullest account plan window against the
    ceiling. A model-scoped window caps one model family, not the lanes, so it is shown and not counted. Nor is the
    window of a provider whose every seat bills an API key of its own: it measures a subscription those seats do not
    use (`metered_by_key`), and the dollar cap is their budget. A window the reader could not read this time counts with
    its last good reading (`stale`), so an unreadable reader never opens the gate."""
    from .usage import plan_windows, providers_in_use, providers_on_key, spent_this_month

    budget = load(pack)["budget"]
    used = providers_in_use(pack)
    keyed = providers_on_key(pack) & used
    read = plan_windows(pack, now)
    counted = [
        window
        for window in read["windows"]
        if window.get("scope") == "account" and window.get("provider") in used - keyed
    ]
    spent = spent_this_month(now)
    why = over_budget(spent, budget["monthly_usd"], counted, budget["plan_window_max_pct"], used - keyed)
    fullest = max(counted, key=lambda window: window.get("used") or 0, default=None)
    # Which providers are at their ceiling: one over its own window, every one over the spend cap (cockpitlib.quota makes
    # their seats' ready cards wait; a running card finishes its turn).
    over_providers = {}
    for provider in sorted(used):
        reasons = []
        if budget["monthly_usd"] and spent >= budget["monthly_usd"]:
            reasons.append(f"spent {spent:.2f} of {budget['monthly_usd']:.2f}")
        mine = over_budget(
            0,
            0,
            [window for window in counted if window.get("provider") == provider],
            budget["plan_window_max_pct"],
            used - keyed,
        )
        if mine:
            reasons.append(mine)
        if reasons:
            over_providers[provider] = "; ".join(reasons)
    from .quota import holds

    return {
        "month_usd": round(spent, 2),
        "cap_usd": budget["monthly_usd"],
        "max_pct": budget["plan_window_max_pct"],
        "window": fullest,
        "windows": read["windows"],
        "error": read["error"],
        "unmetered": read.get("unmetered") or [],
        "over": bool(why),
        "why": why,
        "over_providers": over_providers,
        "holds": [
            {"provider": provider, "until": hold.get("until"), "said": hold.get("said") or ""}
            for provider, hold in sorted(holds(now).items())
        ],
        "families": sorted(used),
        "metered_by_key": sorted(keyed),
        "ignored": sorted({str(window.get("provider")) for window in read["windows"] if window not in counted}),
    }
