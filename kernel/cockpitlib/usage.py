# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Token totals from each seat's state.db. An empty database is a zero, not an error."""

import os
import re
import sqlite3
import time

from .paths import hermes_home
from .store import dump_json, read_db


def _databases() -> list:
    home = hermes_home()
    found = []
    direct = os.path.join(home, "state.db")
    if os.path.isfile(direct):
        found.append(direct)
    profiles = os.path.join(home, "profiles")
    if not os.path.isdir(profiles):
        return found
    for name in sorted(os.listdir(profiles)):
        path = os.path.join(profiles, name, "state.db")
        if os.path.isfile(path):
            found.append(path)
    return found


def _rows(path: str) -> list:
    try:
        connection = read_db(path)
        connection.row_factory = sqlite3.Row
        columns = {row[1] for row in connection.execute("pragma table_info(sessions)")}
        if "started_at" not in columns:
            connection.close()
            return []
        picked = [
            name
            for name in (
                "title",
                "model",
                "started_at",
                "input_tokens",
                "output_tokens",
                "cache_read_tokens",
                "cache_write_tokens",
                "estimated_cost_usd",
                "actual_cost_usd",
                "duration_seconds",
            )
            if name in columns
        ]
        query = "select " + ", ".join(picked) + " from sessions where started_at is not null"
        rows = [dict(row) for row in connection.execute(query)]
        connection.close()
        return rows
    except sqlite3.Error:
        return []


def _blank():
    return {"total": 0, "sessions": 0, "cost": 0, "output": 0, "cache_read": 0, "input": 0, "cache_write": 0}


def _add(bucket, row) -> None:
    entered = int(row.get("input_tokens") or 0)
    output = int(row.get("output_tokens") or 0)
    cache = int(row.get("cache_read_tokens") or 0)
    bucket["sessions"] += 1
    bucket["input"] += entered
    bucket["output"] += output
    bucket["cache_read"] += cache
    bucket["cache_write"] += int(row.get("cache_write_tokens") or 0)
    bucket["total"] += entered + output + cache
    bucket["cost"] += float(row.get("actual_cost_usd") or row.get("estimated_cost_usd") or 0)


def collect(pack=None) -> dict:
    now = time.time()
    midnight = now - (now % 86400)
    windows = {"today": midnight, "week": now - 7 * 86400, "month": now - 30 * 86400, "all": 0}
    totals = {name: _blank() for name in windows}
    recent = []
    for path in _databases():
        for row in _rows(path):
            started = float(row.get("started_at") or 0)
            for name, start in windows.items():
                if started >= start:
                    _add(totals[name], row)
            recent.append(
                {
                    "title": row.get("title") or "",
                    "model": row.get("model") or "",
                    "started_at": started,
                    "output": int(row.get("output_tokens") or 0),
                    "cost": float(row.get("actual_cost_usd") or row.get("estimated_cost_usd") or 0),
                }
            )
    recent.sort(key=lambda item: item["started_at"], reverse=True)
    providers = _provider_rows(pack, _databases())
    return {"totals": totals, "recent": recent[:12], "providers": providers}


def _configured(pack) -> dict:
    """One entry per Hermes provider named by the pack. Coding is not a usage row."""
    providers = (pack or {}).get("providers") or {}
    roles = (pack or {}).get("roles") or {}
    used = set()
    for key in roles.values():
        entry = providers.get(key)
        if isinstance(entry, dict):
            used.add(str(entry.get("hermes_provider") or key))
    found = {}
    for name, entry in providers.items():
        if name in ("coding", "chat") or not isinstance(entry, dict):
            continue
        label = str(entry.get("hermes_provider") or name)
        slot = found.setdefault(label, {"entries": [], "used": False})
        slot["entries"].append(entry)
        if label in used:
            slot["used"] = True
    return found


def _provider_rows(pack, databases) -> list:
    """Turns and time for every configured provider. Cost and a plan window only when they apply."""
    sessions = []
    for path in databases:
        for row in _rows(path):
            sessions.append(row)
    rows = []
    for label, info in sorted(_configured(pack).items()):
        models = {label}
        window = None
        for entry in info["entries"]:
            if entry.get("model"):
                models.add(str(entry["model"]))
            if info["used"] and entry.get("plan_window") and window is None:
                window = entry.get("plan_window")
        turns = 0
        seconds = 0
        reported = None
        estimated = None
        for row in sessions:
            if str(row.get("model") or "") not in models:
                continue
            turns += 1
            seconds += int(row.get("duration_seconds") or 0)
            if row.get("actual_cost_usd") is not None:
                reported = float(reported or 0) + float(row["actual_cost_usd"])
                continue
            if row.get("estimated_cost_usd") is not None:
                estimated = float(estimated or 0) + float(row["estimated_cost_usd"])
        item = {"provider": label, "turns": turns, "time": seconds}
        if reported is not None:
            item["cost"] = reported
            item["approximate"] = False
        elif estimated is not None:
            item["cost"] = estimated
            item["approximate"] = True
        if window is not None:
            item["plan_window"] = window
        rows.append(item)
    return rows


WINDOWS_FRESH = 300
# What hermes_bridge/usage.py answers for a provider Hermes has no usage reader for.
NO_READER = "no usage reader"


# Providers that run on the coding tool's subscription (the owner's own login): when Hermes's reader cannot answer for one,
# cockpit reads the plan's windows itself (cockpitlib.plan_windows). The same vendor's API-key provider is not one.
# These are provider ids as Hermes spells them, and the variable the coding tool keeps its login token in: matched
# against the machine's configuration, never printed.
SUBSCRIPTION_PREFIXES = ("claude-subscription", "claude-code", "claude-max")
TOOL_TOKEN_ENV = "CLAUDE_CODE_OAUTH_TOKEN"


def subscription_provider(provider: str) -> bool:
    return str(provider or "").startswith(SUBSCRIPTION_PREFIXES)


def _direct(provider: str, hermes_error: str) -> dict:
    """The subscription's windows read directly, in the shape of Hermes's answer; both errors when neither answered."""
    from . import plan_windows

    read = plan_windows.read()
    if read.get("windows"):
        return {"provider": provider, "windows": read["windows"], "unavailable": ""}
    return {
        "provider": provider,
        "windows": [],
        "unavailable": f"{hermes_error}; direct read: {read.get('error') or 'no answer'}",
    }


def providers_in_use(pack) -> set:
    """The Hermes providers the lanes run on."""
    return {label for label, info in _configured(pack).items() if info["used"]}


# Subscription tokens Hermes accepts where an API key goes (its own check of a token's shape): a credential
# of this shape bills the plan the usage reader measures, not dollars. Console key families are not tokens.
_KEY_FAMILIES = ("sk-ant-api", "sk-ant-usr", "sk-ant-svc", "sk-ant-admin")
_TOKEN_PREFIXES = ("sk-ant-", "eyJ", "cc-")


def _plan_token(value: str) -> bool:
    return not value.startswith(_KEY_FAMILIES) and value.startswith(_TOKEN_PREFIXES)


def _env_values(path: str) -> dict:
    values = {}
    try:
        with open(path, encoding="utf-8") as handle:
            lines = handle.read().splitlines()
    except (OSError, ValueError):  # a .env that is not UTF-8 must not break the budget gate
        return values
    for line in lines:
        line = line.strip()
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        values[name.strip()] = value.strip().strip("'\"")
    return values


def _pool(home: str, provider: str) -> list:
    import json

    try:
        data = json.load(open(os.path.join(home, "auth.json"), encoding="utf-8"))
    except (OSError, ValueError):
        return []
    pool = (data.get("credential_pool") or {}).get(provider) if isinstance(data, dict) else None
    return [entry for entry in pool if isinstance(entry, dict)] if isinstance(pool, list) else []


def seat_on_key(home: str, provider: str) -> bool:
    """Whether this seat runs the provider on an API key of its own, billed by the dollar: the provider's key in the
    seat's .env (`<PROVIDER>_API_KEY`, as Hermes names a provider's key) or a pool holding only API keys. An OAuth or
    setup token under the key's name, a pool that also holds a login, or no credential at all (Hermes then falls back
    to the account's login) is the plan, and so is a login token beside the key, which Hermes uses first
    (`<PROVIDER>_TOKEN`, the coding tool's own TOOL_TOKEN_ENV)."""
    stem = provider.upper().replace("-", "_")
    values = _env_values(os.path.join(home, ".env"))
    if any(values.get(name) for name in (f"{stem}_TOKEN", f"{stem}_OAUTH_TOKEN", TOOL_TOKEN_ENV)):
        return False
    key = values.get(f"{stem}_API_KEY", "")
    if key:
        return not _plan_token(key)
    pool = _pool(home, provider)
    return bool(pool) and all(
        entry.get("auth_type") == "api_key"
        and not _plan_token(str(entry.get("access_token") or entry.get("api_key") or ""))
        for entry in pool
    )


def providers_on_key(pack) -> set:
    """The lane providers every seat of which bills an API key of its own. A plan window (the subscription the usage
    reader measures) says nothing about them: the dollar cap is their budget. A provider with any seat on the plan, or
    with no seat set up yet, keeps its windows."""
    from .lanes import profile_dir, seats_from
    from .settings import load

    providers = (pack or {}).get("providers") or {}
    roles = (pack or {}).get("roles") or {}
    shaped = dict(pack)
    shaped["seats"] = load(pack)["seats"]
    homes = {}
    for kind, lanes in seats_from(shaped).items():
        entry = providers.get(roles.get(kind))
        if not isinstance(entry, dict):
            continue
        label = str(entry.get("hermes_provider") or roles.get(kind))
        homes.setdefault(label, []).extend(profile_dir(lane) for lane in lanes)
    return {
        label
        for label, found in homes.items()
        if found and all(os.path.isdir(home) and seat_on_key(home, label) for home in found)
    }


def spent_this_month(now=None) -> float:
    """Cost of every seat session since the first of this calendar month (local time)."""
    import datetime

    moment = datetime.datetime.fromtimestamp(time.time() if now is None else now)
    start = moment.replace(day=1, hour=0, minute=0, second=0, microsecond=0).timestamp()
    return sum(
        float(row.get("actual_cost_usd") or row.get("estimated_cost_usd") or 0)
        for path in _databases()
        for row in _rows(path)
        if float(row.get("started_at") or 0) >= start
    )


def _resets_in(stamp, moment: float) -> str:
    import datetime

    try:
        left = datetime.datetime.fromisoformat(str(stamp)).timestamp() - moment
    except (TypeError, ValueError):
        return ""
    if left <= 0:
        return "now"
    if left < 3600:
        return f"{int(left // 60)}m"
    if left < 2 * 86400:
        return f"{int(left // 3600)}h"
    return f"{int(left // 86400)}d"


def plan_windows(pack, now=None, fresh=False) -> dict:
    """{windows: [{provider, name, used, resets_at, resets_in, scope}], error, unmetered}: each provider's plan windows from
    Hermes's read-only usage readers, kept for five minutes. A reader that cannot answer is an error, not a zero: its
    provider's last good windows come back marked `stale` (with `read_at` and `age`) and gate as before; a provider
    Hermes has no reader for is unmetered, which is a fact about it, not a failure. A subscription provider
    Hermes's reader cannot answer for (the coding tool skips its usage fetch with telemetry off) is read directly from the
    plan (cockpitlib.plan_windows); Hermes's reader stays first, so a provider it answers for is read as before.
    `fresh` skips the five-minute cache (the Usage page's Recalculate)."""
    import json

    from .errors import CockpitError
    from .paths import watch_dir

    moment = time.time() if now is None else now
    wanted = sorted(providers_in_use(pack))
    path = os.path.join(watch_dir(), "plan-windows.json")
    try:
        kept = json.load(open(path, encoding="utf-8"))
    except (OSError, ValueError):
        kept = {}
    if (
        not fresh
        and isinstance(kept, dict)
        and kept.get("providers") == wanted
        and 0 <= moment - float(kept.get("at") or 0) < WINDOWS_FRESH
    ):
        from .quota import aged

        return {
            "windows": aged(kept.get("windows") or [], moment),
            "error": kept.get("error") or "",
            "unmetered": kept.get("unmetered") or [],
        }
    errors, unmetered = [], []
    reads = {}  # provider -> what this read answered for it: its windows, or why it could not
    if wanted:
        from .hermes_runtime import run_helper

        try:
            results = run_helper("usage", {"providers": wanted}).get("results") or []
        except CockpitError as exc:
            results = [{"provider": provider, "windows": [], "unavailable": str(exc)} for provider in wanted]
            if not any(subscription_provider(provider) for provider in wanted):
                results, errors = [], [str(exc)]
                reads = {provider: {"windows": [], "error": str(exc)} for provider in wanted}
        results = [
            _direct(str(result["provider"]), str(result["unavailable"]))
            if subscription_provider(result.get("provider"))
            and result.get("unavailable")
            and result.get("unavailable") != NO_READER
            and not result.get("windows")
            else result
            for result in results
        ]
        for result in results:
            if result.get("unavailable") == NO_READER and not result.get("windows"):
                unmetered.append(str(result.get("provider")))
                continue
            if result.get("unavailable") and not result.get("windows"):
                errors.append(f"{result.get('provider')}: {result['unavailable']}")
            if result.get("provider") is None:
                continue
            read = reads.setdefault(
                str(result.get("provider")), {"windows": [], "error": str(result.get("unavailable") or "")}
            )
            for window in result.get("windows") or []:
                read["windows"].append(
                    {
                        "provider": result.get("provider"),
                        "name": window.get("label"),
                        "used": round(float(window["used_percent"])),
                        "resets_at": window.get("resets_at"),
                        "resets_in": _resets_in(window.get("resets_at"), moment),
                        "scope": window.get("scope") or "account",
                    }
                )
    # A read that failed is not a zero: each provider it could not answer keeps its last good reading (cockpitlib.quota)
    from .quota import with_last_good

    windows = with_last_good(reads, moment)
    record = {"at": moment, "providers": wanted, "windows": windows, "error": "; ".join(errors), "unmetered": unmetered}
    os.makedirs(os.path.dirname(path), exist_ok=True)
    dump_json(path, record)
    return {"windows": windows, "error": record["error"], "unmetered": unmetered}


# ---------- the Usage page: every seat session and the coding tool's transcripts, by lane / ticket / day / model ----------

_TICKET_IN = re.compile(r"\b([A-Z][A-Z0-9]*(?:-[A-Z][A-Z0-9]*)*-[0-9]+)\b")
# list prices, USD per million tokens (input, output); a cache read is 10 % of input, a cache write 125 %. A coding tool
# on a subscription bills no token: these are the "what it would cost" estimates the page labels as such.
PRICES = (
    ("haiku", (1.0, 5.0)),
    ("sonnet", (3.0, 15.0)),
    ("opus", (5.0, 25.0)),
    ("fable", (5.0, 25.0)),
    ("mythos", (5.0, 25.0)),
)
CODING_WHO = "coding tool (lanes)"
PERIODS = ("today", "week", "month", "all")
GROUPINGS = ("who", "ticket", "day", "model")
_TRANSCRIPTS = {"key": None, "rows": []}


def _ticket_in(text: str) -> str:
    match = _TICKET_IN.search(text or "")
    return match.group(1) if match else ""


def _price(model: str, usage: dict) -> float:
    name = (model or "").lower()
    entered, output = next((price for key, price in PRICES if key in name), (5.0, 25.0))
    return (
        (usage.get("input_tokens") or 0) * entered
        + (usage.get("cache_read_input_tokens") or 0) * entered * 0.1
        + (usage.get("cache_creation_input_tokens") or 0) * entered * 1.25
        + (usage.get("output_tokens") or 0) * output
    ) / 1e6


def _session_rows(path: str) -> list:
    """Every session of one state.db with the columns the page reads; an older database without some is read without them."""
    wanted = (
        "id",
        "title",
        "model",
        "started_at",
        "ended_at",
        "last_activity_at",
        "input_tokens",
        "output_tokens",
        "cache_read_tokens",
        "cache_write_tokens",
        "estimated_cost_usd",
        "actual_cost_usd",
        "duration_seconds",
        "api_call_count",
        "tool_call_count",
    )
    try:
        connection = read_db(path)
        connection.row_factory = sqlite3.Row
        columns = {row[1] for row in connection.execute("pragma table_info(sessions)")}
        if "started_at" not in columns:
            connection.close()
            return []
        picked = [name for name in wanted if name in columns]
        rows = [
            dict(row)
            for row in connection.execute("select " + ", ".join(picked) + " from sessions where started_at is not null")
        ]
        connection.close()
        return rows
    except sqlite3.Error:
        return []


def _seconds(row: dict) -> float:
    if row.get("duration_seconds"):
        return float(row["duration_seconds"] or 0)
    try:
        start = float(row.get("started_at") or 0)
        end = float(row.get("ended_at") or row.get("last_activity_at") or 0)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, end - start) if start and end else 0.0


def seat_rows() -> list:
    """One row per seat session: who is the seat (default for the root home), the ticket from the title."""
    home = hermes_home()
    rows = []
    for path in _databases():
        who = "default" if os.path.dirname(path) == home else os.path.basename(os.path.dirname(path))
        for row in _session_rows(path):
            rows.append(
                {
                    "src": "hermes",
                    "who": who,
                    "ticket": _ticket_in(row.get("title") or ""),
                    "title": (row.get("title") or "")[:80],
                    "model": row.get("model") or "",
                    "epoch": float(row.get("started_at") or 0),
                    "seconds": _seconds(row),
                    "input": int(row.get("input_tokens") or 0),
                    "output": int(row.get("output_tokens") or 0),
                    "cache_read": int(row.get("cache_read_tokens") or 0),
                    "cache_write": int(row.get("cache_write_tokens") or 0),
                    "cost": float(row.get("actual_cost_usd") or row.get("estimated_cost_usd") or 0),
                    "estimate": row.get("actual_cost_usd") is None,
                    "calls": int(row.get("api_call_count") or 0),
                    "tools": int(row.get("tool_call_count") or 0),
                    "session": str(row.get("id") or ""),
                }
            )
    return rows


def transcript_rows() -> list:
    """The coding tool's transcripts the pack's glob names (subagents included), booked per day from each turn's
    timestamp: a session can span days. Cached by the files' mtimes."""
    import datetime
    import glob
    import json

    from .chat import _pattern, ticket_of_transcript

    pattern = _pattern("*")
    if not pattern:
        return []
    paths = sorted(glob.glob(pattern))
    sub_pattern = os.path.join(os.path.dirname(pattern), "*", "subagents", os.path.basename(pattern))
    paths += sorted(glob.glob(sub_pattern))
    key = tuple((path, os.path.getmtime(path)) for path in paths if os.path.isfile(path))
    if _TRANSCRIPTS["key"] == key:
        return _TRANSCRIPTS["rows"]
    rows = []
    for path in paths:
        if not os.path.isfile(path):
            continue
        ticket = ticket_of_transcript(path)
        sub = f"{os.sep}subagents{os.sep}" in path
        days = {}
        try:
            with open(path, encoding="utf-8", errors="replace") as handle:
                for line in handle:
                    if '"usage"' not in line or '"assistant"' not in line:
                        continue
                    try:
                        data = json.loads(line)
                    except ValueError:
                        continue
                    message = data.get("message") or {}
                    usage = message.get("usage") or {}
                    if data.get("type") != "assistant" or not usage:
                        continue
                    stamp = data.get("timestamp") or ""
                    try:
                        epoch = (
                            datetime.datetime.fromisoformat(stamp.replace("Z", "+00:00")).timestamp()
                            if stamp
                            else os.path.getmtime(path)
                        )
                    except ValueError:
                        epoch = os.path.getmtime(path)
                    day = datetime.datetime.fromtimestamp(epoch).astimezone().strftime("%Y-%m-%d")
                    acc = days.setdefault(
                        day,
                        {
                            "input": 0,
                            "output": 0,
                            "cache_read": 0,
                            "cache_write": 0,
                            "calls": 0,
                            "models": set(),
                            "first": epoch,
                            "last": epoch,
                            "cost": 0.0,
                        },
                    )
                    acc["cost"] += _price(message.get("model"), usage)
                    acc["input"] += usage.get("input_tokens") or 0
                    acc["output"] += usage.get("output_tokens") or 0
                    acc["cache_read"] += usage.get("cache_read_input_tokens") or 0
                    acc["cache_write"] += usage.get("cache_creation_input_tokens") or 0
                    acc["calls"] += 1
                    acc["models"].add(message.get("model") or "")
                    acc["first"] = min(acc["first"], epoch)
                    acc["last"] = max(acc["last"], epoch)
        except OSError:
            continue
        name = os.path.splitext(os.path.basename(path))[0]
        for day, acc in sorted(days.items()):
            models = sorted(model for model in acc["models"] if model)
            rows.append(
                {
                    "src": "coding",
                    "who": CODING_WHO,
                    "ticket": ticket,
                    "title": ("↳ subagent " if sub else "")
                    + name[:12]
                    + (f" · {day}" if len(days) > 1 else "")
                    + (f" · {ticket}" if ticket else ""),
                    "model": models[0] if len(models) == 1 else ", ".join(models),
                    "epoch": acc["first"],
                    "seconds": max(0.0, acc["last"] - acc["first"]),
                    "input": acc["input"],
                    "output": acc["output"],
                    "cache_read": acc["cache_read"],
                    "cache_write": acc["cache_write"],
                    "cost": round(acc["cost"], 4),
                    "estimate": True,
                    "calls": acc["calls"],
                    "tools": 0,
                    "session": name,
                }
            )
    _TRANSCRIPTS["key"] = key
    _TRANSCRIPTS["rows"] = rows
    return rows


def usage_rows() -> list:
    rows = seat_rows() + transcript_rows()
    return [
        row for row in rows if row["input"] or row["output"] or row["cache_read"] or row["cache_write"] or row["cost"]
    ]


def periods(now=None) -> dict:
    """Local midnight today, the rolling week (today and six days before), the rolling thirty days, everything."""
    import datetime

    moment = datetime.datetime.fromtimestamp(time.time() if now is None else now).astimezone()
    today = moment.replace(hour=0, minute=0, second=0, microsecond=0)
    return {
        "today": today.timestamp(),
        "week": (today - datetime.timedelta(days=6)).timestamp(),
        "month": (today - datetime.timedelta(days=29)).timestamp(),
        "all": 0.0,
    }


def _aggregate(rows: list, key_of) -> list:
    out = {}
    seen = set()
    for row in rows:
        key = key_of(row) or "(none)"
        acc = out.setdefault(
            key,
            {
                "key": key,
                "sessions": 0,
                "input": 0,
                "output": 0,
                "cache_read": 0,
                "cache_write": 0,
                "cost": 0.0,
                "calls": 0,
                "tools": 0,
                "total": 0,
                "seconds": 0.0,
            },
        )
        acc["seconds"] += float(row.get("seconds") or 0)
        if (key, row.get("session")) not in seen:
            seen.add((key, row.get("session")))
            acc["sessions"] += 1
        for field in ("input", "output", "cache_read", "cache_write", "calls", "tools"):
            acc[field] += int(row.get(field) or 0)
        acc["cost"] += float(row.get("cost") or 0)
    for acc in out.values():
        acc["total"] = acc["input"] + acc["output"] + acc["cache_read"] + acc["cache_write"]
    return sorted(out.values(), key=lambda acc: (-acc["cost"] if acc["cost"] else 0, -acc["total"]))


def _origin(row: dict) -> str:
    """Where a ticket-less session came from, instead of a flat '(no ticket)'."""
    who = row.get("who") or ""
    title = (row.get("title") or "").lower()
    if who == "gatekeeper" and any(word in title for word in ("sweep", "outbox", "re-check", "re-verify")):
        return "gatekeeper · outbox sweeps"
    if who in ("default", "assistant"):
        return "concierge · your chats"
    return "lanes · not tied to a ticket"


def _iso(epoch: float) -> str:
    import datetime

    return datetime.datetime.fromtimestamp(epoch, datetime.UTC).strftime("%Y-%m-%dT%H:%M:%SZ") if epoch else ""


def report(pack, period: str = "week", by: str = "who", scope: str = "hermes", now=None) -> dict:
    """What the Usage page shows: the period totals, the groups of the period by lane / ticket / day / model, the
    recent sessions, the split (everything here went through the stack: outside use is not read)."""
    import datetime

    from .errors import CockpitError

    if period not in PERIODS:
        raise CockpitError("period today|week|month|all")
    if by not in GROUPINGS:
        raise CockpitError("by who|ticket|day|model")
    if scope not in ("hermes", "all"):
        raise CockpitError("scope hermes|all")
    rows = usage_rows()
    windows = periods(now)
    selected = [row for row in rows if row["epoch"] >= windows[period]]
    key_of = {
        "who": lambda row: row["who"],
        "ticket": lambda row: row["ticket"] or _origin(row),
        "day": lambda row: (
            datetime.datetime.fromtimestamp(row["epoch"]).strftime("%Y-%m-%d") if row["epoch"] else "(no date)"
        ),
        "model": lambda row: row["model"] or "(no model)",
    }[by]
    groups = _aggregate(selected, key_of)
    if by == "day":
        groups.sort(key=lambda acc: acc["key"])
    else:
        groups.sort(key=lambda acc: (-acc["sessions"], -acc["total"]))
    totals = {}
    for name, start in windows.items():
        agg = _aggregate([row for row in rows if row["epoch"] >= start], lambda row: "all")
        totals[name] = (
            agg[0]
            if agg
            else {
                "key": "all",
                "sessions": 0,
                "input": 0,
                "output": 0,
                "cache_read": 0,
                "cache_write": 0,
                "cost": 0.0,
                "calls": 0,
                "tools": 0,
                "total": 0,
                "seconds": 0.0,
            }
        )
    inside = totals[period]
    sessions = inside["sessions"]
    split = {
        "hermes": inside["total"],
        "outside": 0,
        "total": inside["total"],
        "hermes_pct": 100 if inside["total"] else 0,
        "hermes_sessions": sessions,
        "outside_sessions": 0,
        "hermes_cost": inside["cost"],
        "outside_cost": 0.0,
    }
    recent = sorted(selected, key=lambda row: -row["epoch"])[:40]
    return {
        "period": period,
        "by": by,
        "scope": scope,
        "split": split,
        "totals": totals,
        "groups": groups,
        "recent": [{**row, "when": _iso(row["epoch"])} for row in recent],
        "providers": _provider_rows(pack, _databases()),
        "note": "costs are list-price estimates where the provider reports none; the coding tool's rows come from the pack's transcript glob",
    }
