# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Provider quotas, always respected.

Three guarantees, all on by default (no pack key):

1. A plan window that cannot be read gates on its last good reading. Each provider's last good windows are kept with
   their read time (<watch>/plan-windows-good.json); a failed read returns them marked stale, and the budget gate counts
   them as it counts fresh ones, until the window's own reset has passed. A provider with a reader that has had no good
   read for a quarter hour gets one Inbox row, which leaves once a read succeeds. Unreadable alone refuses no card.
2. A run that ends on a provider's limit (Hermes's quota-wall exit, or a crash whose provider said its usage limit was
   reached) holds that provider until the reset the provider named (half an hour when it named none, at most a week):
   no new card for a seat on it, its seats' ready cards wait, one Inbox row says so. The hold and its row end at the
   reset, or as soon as a later run on that provider finishes.
3. At the ceiling (a held provider, or a plan window or the spend cap over the budget) a running card finishes its
   turn; ready cards of the seats on that provider (the retry Hermes would start, a follow-up card) wait in Hermes's
   `scheduled` state, which the dispatcher never starts, and return to ready once the provider is under the ceiling.
   A card cockpit did not schedule is never released by it: cockpit's own reason starts with MARK, its intent is
   recorded before the write, and a scheduled card whose latest scheduled reason is cockpit's is adopted on the next
   pass (a helper that died part-way leaves nothing parked for good).

A wall replayed from the last week counts only for the provider the run was on: the provider its run recorded, the one
its message names, or its seat's config when not set up again since. A run whose provider is unknown counts only from
the last day.
"""

import datetime
import json
import os
import re
import time

from .store import dump_json, read_db

DEFAULT_HOLD = 30 * 60
CAP = 7 * 86400
UNREADABLE_AFTER = 15 * 60
UNKNOWN_LOOKBACK = 86400  # a wall whose run's provider is unknown counts only this far back
MARK = (
    "cockpit quota: "  # the start of every reason cockpit parks a card with; only such cards are cockpit's to release
)
ROW_PLUGIN = "cockpit"
GOOD_FILE = "plan-windows-good.json"
HOLDS_FILE = "provider-holds.json"
# Hermes's worker exit trailer (hermes_cli.kanban_db KANBAN_WORKER_EXIT_TRAILER) and its quota-wall exit code
TRAILER = re.compile(r"^\[kanban-worker-exit\] rc=(\d+)\s*$", re.M)
WALL_EXIT = "75"
# What a provider says when a limit stops a run. A crashed run counts only on the strong forms: its error carries the
# lane's last output, which may mention a quota for any reason.
LIMIT_WORDS = re.compile(
    r"usage limit|rate[- ]limit|quota|credit balance is too low|usage is exhausted|too many requests|"
    r"\b429\b|limit reached|resets? in|retry[- ]after|billing",
    re.I,
)
LIMIT_STRONG = re.compile(
    r"usage limit reached|limit reached|credit balance is too low|usage is exhausted|"
    r"quota (?:exceeded|wall)|exited rate-limited|HTTP 429|rate[- ]limit(?:ed)? (?:reached|exceeded)",
    re.I,
)
# run outcomes that are a failure of the run (a crash whose provider said its limit was reached is a wall too)
FAILED = ("crashed", "timed_out", "spawn_failed", "failed")
_UNITS = {
    "s": 1,
    "sec": 1,
    "second": 1,
    "m": 60,
    "min": 60,
    "minute": 60,
    "h": 3600,
    "hr": 3600,
    "hour": 3600,
    "d": 86400,
    "day": 86400,
    "w": 7 * 86400,
    "week": 7 * 86400,
}
_IN = re.compile(
    r"(?:resets?|try again|retry|available again)\s+in\s+(?:about\s+)?(\d+(?:\.\d+)?)\s*"
    r"(seconds?|secs?|s|minutes?|mins?|m|hours?|hrs?|h|days?|d|weeks?|w)\b",
    re.I,
)
_AFTER = re.compile(r"retry[- ]after[\"']?\s*[:=]?\s*(\d+)", re.I)
_AT = re.compile(
    r"(?:resets?|reset_at|available again|retry)\s*(?:at|on|after)?\s*[:=]?\s*[\"']?"
    r"(\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:Z|[+-]\d{2}:?\d{2})?)",
    re.I,
)


def _watch(name: str) -> str:
    from .paths import watch_dir

    return os.path.join(watch_dir(), name)


def _load(name: str) -> dict:
    try:
        data = json.load(open(_watch(name), encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _save(name: str, data: dict) -> None:
    path = _watch(name)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    dump_json(path, data)


def when(epoch) -> str:
    """A moment as the owner reads it: local date and time with the zone."""
    if not epoch:
        return ""
    return datetime.datetime.fromtimestamp(float(epoch)).astimezone().strftime("%Y-%m-%d %H:%M %Z").strip()


def _epoch(stamp):
    try:
        moment = datetime.datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=datetime.UTC)
    return moment.timestamp()


# ---------- 1. the last good reading of each provider's plan windows ----------


def _key(window: dict) -> str:
    return f"{window.get('scope') or 'account'}\x00{window.get('name')}"


def _spent(window: dict, moment: float) -> bool:
    """The window has reset since it was read: its reading no longer says anything."""
    reset = _epoch(window.get("resets_at")) if window.get("resets_at") else None
    return reset is not None and reset <= moment


def _stale(window: dict, moment: float) -> dict:
    from .usage import _resets_in

    read = float(window.get("read_at") or 0)
    shown = {key: value for key, value in window.items() if key != "read_at"}
    return {
        **shown,
        "stale": True,
        "read_at": read,
        "age": int(moment - read),
        "resets_in": _resets_in(window.get("resets_at"), moment),
    }


def with_last_good(reads: dict, moment: float) -> list:
    """reads: {provider: {"windows": [...], "error": ""}} from one read of the usage readers. Returns every window to
    show: the fresh ones, and for a provider (or a window) the read could not answer, its last good reading marked
    stale, as long as that window has not reset since. Keeps each provider's last good reading and since when it fails."""
    store = _load(GOOD_FILE)
    out = []
    for provider, read in reads.items():
        entry = store.get(provider) if isinstance(store.get(provider), dict) else {}
        kept = {key: window for key, window in (entry.get("windows") or {}).items() if isinstance(window, dict)}
        fresh = list(read.get("windows") or [])
        error = str(read.get("error") or "")
        if fresh or not error:
            # an answer: what it names replaces the old reading; what it leaves out is kept only when it said why
            named = {_key(window): {**window, "read_at": moment} for window in fresh}
            missing = {key: window for key, window in kept.items() if key not in named} if error else {}
            out += fresh + [_stale(window, moment) for window in missing.values() if not _spent(window, moment)]
            store[provider] = {"windows": {**missing, **named}, "good_at": moment, "failing_since": None, "error": ""}
            continue
        out += [_stale(window, moment) for window in kept.values() if not _spent(window, moment)]
        store[provider] = {
            "windows": kept,
            "good_at": entry.get("good_at"),
            "error": error,
            "failing_since": entry.get("failing_since") or moment,
        }
    _save(GOOD_FILE, store)
    return out


def aged(windows: list, moment: float) -> list:
    """A kept read's windows with the age of the stale ones as of now."""
    return [_stale(window, moment) if window.get("stale") else window for window in windows]


def unreadable(pack, moment: float) -> dict:
    """{provider: (failing_since, good_at, error)} for each lane provider whose reader has had no good read for a
    quarter hour. A provider the gate does not read (no reader, or every seat on an API key) is never one."""
    from .usage import providers_in_use, providers_on_key

    store = _load(GOOD_FILE)
    gated = providers_in_use(pack) - providers_on_key(pack)
    found = {}
    for provider in sorted(gated):
        entry = store.get(provider)
        if not isinstance(entry, dict) or not entry.get("failing_since"):
            continue
        since = float(entry.get("good_at") or entry["failing_since"])
        if moment - since > UNREADABLE_AFTER:
            found[provider] = (
                entry["failing_since"],
                entry.get("good_at"),
                str(entry.get("error") or ""),
                [window for window in (entry.get("windows") or {}).values() if not _spent(window, moment)],
            )
    return found


def _row_unreadable(provider, failing_since, good_at, error, left) -> dict:
    what = f"plan usage unreadable for {provider} since {when(failing_since)}: {error or 'the reader did not answer'}; "
    if not good_at:
        what += "no reading yet"
    elif left:
        what += f"the gate uses the last reading from {when(good_at)}"
    else:
        what += f"the gate uses the last reading from {when(good_at)}, whose windows have all reset since: nothing gates on it"
    fields = [
        {"label": "provider", "text": provider},
        {"label": "unreadable since", "text": when(failing_since)},
        {"label": "reader said", "text": error or "nothing"},
        {"label": "last good reading", "text": when(good_at) if good_at else "none yet"},
    ]
    if left:
        fields.append(
            {
                "label": "windows the gate keeps",
                "items": [f"{window.get('name')} {window.get('used')}%" for window in left],
            }
        )
    return {
        "id": f"plan-usage-{provider}",
        "icon": "📉",
        "what": what,
        "tone": "warn",
        "detail": {
            "title": f"Plan usage unreadable: {provider}",
            "status": {"text": "unreadable", "color": "warn"},
            "fields": fields,
            "actions": [
                {
                    "label": "Retry reading",
                    "hint": "read the plan usage again now, without waiting for the next read",
                    "act": {"do": "retry-read", "provider": provider},
                }
            ],
        },
    }


def retry_read(pack, provider: str, now=None) -> str:
    """The human's Retry reading on an unreadable provider's row: read the plan windows again now. A reader that still
    does not answer is said, and the row stays."""
    from .errors import CockpitError
    from .inbox import drop_row
    from .usage import plan_windows

    moment = time.time() if now is None else now
    plan_windows(pack, moment, fresh=True)
    entry = _load(GOOD_FILE).get(provider)
    if isinstance(entry, dict) and entry.get("failing_since"):
        raise CockpitError(
            f"plan usage for {provider} is still unreadable: {entry.get('error') or 'the reader did not answer'}"
        )
    drop_row(ROW_PLUGIN, f"plan-usage-{provider}")
    return f"plan usage for {provider} was read"


# ---------- 2. provider holds ----------


def reset_after(message: str, at: float) -> float:
    """When the limit the provider described ends: its "resets in N <unit>", its reset time, or its Retry-After, from the
    moment the run ended; half an hour when it named none (or a time already past), at most a week."""
    text = message or ""
    found = None
    match = _IN.search(text)
    if match:
        unit = match.group(2).lower().rstrip("s") or "s"
        found = at + float(match.group(1)) * _UNITS.get(unit, _UNITS.get(unit[:1], 60))
    if found is None:
        match = _AT.search(text)
        reset = _epoch(match.group(1)) if match else None
        if reset is not None and reset > at:
            found = reset
    if found is None:
        match = _AFTER.search(text)
        if match:
            found = at + int(match.group(1))
    if found is None or found <= at:
        found = at + DEFAULT_HOLD
    return min(found, at + CAP)


def lane_providers(pack) -> dict:
    """{lane: the Hermes provider its seat runs}, from the pack's roles and the seat counts in force."""
    from .lanes import seats_from
    from .settings import load

    providers = (pack or {}).get("providers") or {}
    roles = (pack or {}).get("roles") or {}
    shaped = dict(pack)
    shaped["seats"] = load(pack)["seats"]
    found = {}
    for kind, lanes in seats_from(shaped).items():
        name = roles.get(kind)
        entry = providers.get(name)
        if not isinstance(entry, dict):
            continue
        for lane in lanes:
            found[lane] = str(entry.get("hermes_provider") or name)
    return found


def kind_provider(pack, kind: str) -> str:
    name = ((pack or {}).get("roles") or {}).get(kind)
    entry = ((pack or {}).get("providers") or {}).get(name)
    return str(entry.get("hermes_provider") or name) if isinstance(entry, dict) else ""


def holds(now=None) -> dict:
    """{provider: hold} for each provider held now."""
    moment = time.time() if now is None else now
    return {
        provider: hold
        for provider, hold in (_load(HOLDS_FILE).get("holds") or {}).items()
        if isinstance(hold, dict) and float(hold.get("until") or 0) > moment
    }


def hold_text(provider: str, hold: dict) -> str:
    return f"provider {provider} limit reached; held until {when(hold.get('until'))}"


def held_refusal(pack, kind: str, now=None) -> str:
    """Why a new card for a seat of this kind cannot start: its provider is held. '' when it can."""
    provider = kind_provider(pack, kind)
    hold = holds(now).get(provider) if provider else None
    return hold_text(provider, hold) if hold else ""


def _said(pack, card: str, error: str) -> str:
    """What the provider said when it stopped the run: the limit lines of the worker's log around its last quota-wall
    exit, else the run's own error. Secrets masked."""
    from .kanban import db_path

    path = os.path.join(os.path.dirname(db_path(pack["board"])), "logs", f"{card}.log")
    text = ""
    try:
        with open(path, "rb") as handle:
            handle.seek(max(0, os.path.getsize(path) - 12000))
            text = handle.read().decode("utf-8", errors="replace")
    except OSError:
        text = ""
    marks = list(TRAILER.finditer(text))
    walls = [index for index, mark in enumerate(marks) if mark.group(1) == WALL_EXIT]
    pieces = []
    if walls:
        index = walls[-1]
        before = text[marks[index - 1].end() if index else 0 : marks[index].start()]
        after = text[marks[index].end() : marks[index + 1].start() if index + 1 < len(marks) else len(text)]
        pieces = [before, after]
    pieces.append(error or "")
    said = ""
    for piece in pieces:
        lines = [
            line.strip() for line in re.split(r"[\n\r]+|(?<=[.!])\s+(?=[A-Z])", piece) if LIMIT_WORDS.search(line or "")
        ]
        lines = [line for line in lines if "requeued without counting" not in line]
        if lines:
            said = " ".join(lines[:3])
            break
    said = re.sub(r"\s+", " ", said).strip()[:400]
    try:
        from .scrub import scrub

        said = scrub(said)
    except Exception:  # noqa: BLE001, S110 - a message is never worth failing the gate for
        pass
    return said


_REPORTED = re.compile(r"(?:^|\s)([\w.-]+) reported that your", re.M)


def _known_providers(pack) -> set:
    return {
        str(entry.get("hermes_provider") or name)
        for name, entry in ((pack or {}).get("providers") or {}).items()
        if isinstance(entry, dict)
    }


def _seat_provider(lane: str, cache: dict) -> tuple:
    """(when the seat's config was last written, the provider it names): '' when it has none to read."""
    if lane not in cache:
        from .lanes import profile_dir

        path = os.path.join(profile_dir(lane), "config.yaml")
        try:
            import yaml

            written = os.path.getmtime(path)
            model = (yaml.safe_load(open(path, encoding="utf-8")) or {}).get("model")
            cache[lane] = (written, str(model.get("provider") or "") if isinstance(model, dict) else "")
        except Exception:  # noqa: BLE001 - an unreadable config says nothing about the run
            cache[lane] = (0.0, "")
    return cache[lane]


def _ran_on(metadata, texts, lane: str, ended: float, known: set, seats: dict) -> str:
    """The provider a run was on, from what was recorded about it; '' when nothing says. In order: its run's metadata,
    the provider its limit message names ("<provider> reported that your ..."), its seat's config when not written
    since the run (the config then in force)."""
    try:
        meta = json.loads(metadata) if metadata else {}
    except (TypeError, ValueError):
        meta = {}
    if isinstance(meta, dict):
        for key in ("provider", "hermes_provider"):
            if meta.get(key):
                return str(meta[key])
    for text in texts:
        for match in _REPORTED.finditer(text or ""):
            if match.group(1) in known:
                return match.group(1)
    written, provider = _seat_provider(lane, seats)
    if provider and written <= ended:
        return provider
    return ""


def _walls(pack, connection, state: dict, lanes: dict, moment: float) -> None:
    """Read the runs that ended since the last pass: a limit run holds (or extends the hold on) its provider; a run that
    finished on a held provider after its last wall ends the hold. A run counts only for the provider it was on: one
    whose recorded provider differs is someone else's wall, and one whose provider is unknown counts only from the last
    day (the seat may have switched providers since without being set up again)."""
    tables = {row[0] for row in connection.execute("select name from sqlite_master where type = 'table'")}
    if "task_runs" not in tables:
        return
    columns = {row[1] for row in connection.execute("pragma table_info(tasks)")}
    overrides = {}
    if "provider_override" in columns:
        overrides = {
            str(card): str(value)
            for card, value in connection.execute(
                "select id, provider_override from tasks where coalesce(provider_override, '') != ''"
            )
        }
    metadata = (
        "metadata" if "metadata" in {row[1] for row in connection.execute("pragma table_info(task_runs)")} else "null"
    )
    since = max(float(state.get("seen_end") or 0), moment - CAP)
    rows = connection.execute(
        f"select id, task_id, profile, outcome, error, started_at, ended_at, {metadata} from task_runs "
        "where ended_at is not null and ended_at >= ? order by ended_at, id",
        (int(since),),
    ).fetchall()
    held = state.setdefault("holds", {})
    cleared = state.setdefault("cleared", {})
    known, seats = _known_providers(pack), {}
    for _run, card, lane, outcome, error, started, ended, recorded in rows:
        provider = overrides.get(str(card)) or lanes.get(str(lane or ""))
        state["seen_end"] = max(float(state.get("seen_end") or 0), float(ended))
        if not provider:
            continue
        if not overrides.get(str(card)) and _rendered_since(str(lane), float(ended)):
            continue  # the seat was set up again after this run (a provider switch): which provider it ran is unknown
        outcome = str(outcome or "")
        wall = outcome == "rate_limited" or (outcome in FAILED and LIMIT_STRONG.search(str(error or "")))
        said = (_said(pack, str(card), str(error or "")) or str(error or "")[:400]) if wall else ""
        ran = overrides.get(str(card)) or _ran_on(
            recorded, (said, str(error or "")), str(lane or ""), float(ended), known, seats
        )
        if ran and ran != provider:
            continue  # the run was on another provider: its wall or its success says nothing about this one
        if wall:
            if float(ended) <= float(cleared.get(provider) or 0):
                continue
            if not ran and float(ended) < moment - UNKNOWN_LOOKBACK:
                continue
            until = reset_after(said, float(ended))
            if until <= moment:
                continue
            hold = held.get(provider) or {"since": int(ended), "until": 0, "cards": []}
            hold["until"] = int(max(float(hold.get("until") or 0), until))
            hold["last"] = int(max(float(hold.get("last") or 0), float(ended)))
            hold["said"] = said or hold.get("said") or ""
            hold["cards"] = sorted(set(hold.get("cards") or []) | {str(card)})
            held[provider] = hold
            continue
        hold = held.get(provider)
        if hold and outcome == "completed" and started is not None and float(started) >= float(hold.get("last") or 0):
            held.pop(provider, None)
            cleared[provider] = float(ended)


def _rendered_since(lane: str, ended: float) -> bool:
    from .lanes import profile_dir

    try:
        return os.path.getmtime(os.path.join(profile_dir(lane), "config.yaml")) > ended
    except OSError:
        return False


def _row_hold(provider: str, hold: dict, seats: list) -> dict:
    said = hold.get("said") or "no message"
    what = (
        f"{hold_text(provider, hold)}: seats {', '.join(seats) or 'none'} wait (cards stay queued, no failure counted). "
        f"The provider said: {said}"
    )
    return {
        "id": f"provider-hold-{provider}",
        "icon": "⏸",
        "what": what,
        "tone": "warn",
        "detail": {
            "title": f"Provider limit: {provider}",
            "status": {"text": f"held until {when(hold.get('until'))}", "color": "warn"},
            "fields": [
                {"label": "provider", "text": provider},
                {"label": "held until", "text": when(hold.get("until"))},
                {"label": "seats waiting", "items": seats},
                {"label": "cards that hit the limit", "items": hold.get("cards") or []},
                {"label": "the provider said", "text": said},
                {
                    "label": "ends",
                    "text": "at that time (the next card may then try), or as soon as a run on this provider finishes",
                },
            ],
            "actions": [
                {
                    "label": "End hold now",
                    "hint": "the limit is over (credits bought, a plan changed): the seats' cards "
                    "start again on the next pass",
                    "act": {"do": "end-hold", "provider": provider},
                }
            ],
        },
    }


def clear_hold(provider: str, now=None) -> str:
    """The human's End hold now: the provider's hold ends at once, and no run that ended before now holds it again. Its
    waiting cards are released by the next pass, as at a reset."""
    from .errors import CockpitError
    from .inbox import drop_row

    moment = time.time() if now is None else now
    state = _load(HOLDS_FILE)
    hold = (state.get("holds") or {}).pop(provider, None)
    if not isinstance(hold, dict):
        raise CockpitError(f"provider {provider or '?'} is not held")
    state.setdefault("cleared", {})[provider] = moment
    _save(HOLDS_FILE, state)
    drop_row(ROW_PLUGIN, f"provider-hold-{provider}")
    return f"the hold on {provider} is ended: its seats' cards start again on the next pass"


def _row_budget(provider: str, why: str, cards: list) -> dict:
    count = len(cards)
    what = (
        f"{count} card(s) of seats on {provider} wait at the budget ceiling ({why}): they start again once it is under"
    )
    return {
        "id": f"budget-wait-{provider}",
        "icon": "⏸",
        "what": what,
        "tone": "warn",
        "detail": {
            "title": f"Waiting at the budget ceiling: {provider}",
            "status": {"text": "waiting", "color": "warn"},
            "fields": [
                {"label": "provider", "text": provider},
                {"label": "the ceiling", "text": why},
                {"label": "cards waiting", "items": cards},
                {
                    "label": "ends",
                    "text": "when the provider is under the ceiling again (its window resets, or the "
                    "budget in Settings is raised)",
                },
            ],
            "actions": [
                {
                    "label": "Run them anyway",
                    "hint": "these cards start now; cards made later still wait",
                    "act": {"do": "release", "provider": provider},
                }
            ],
        },
    }


def release_parked(pack, provider: str, now=None) -> str:
    """The human's Run them anyway: the cards cockpit made wait for this provider's budget ceiling start now and are
    not parked for it again. Cards made later still wait, and a provider's own limit still holds them."""
    from .errors import CockpitError
    from .inbox import drop_row
    from .kanban import BoardWrites

    moment = time.time() if now is None else now
    state = _load(HOLDS_FILE)
    waiting = state.setdefault("waiting", {})
    cards = sorted(
        card for card, entry in waiting.items() if isinstance(entry, dict) and entry.get("provider") == provider
    )
    if not cards:
        raise CockpitError(f"no card of {provider or '?'} waits at the budget ceiling")
    writes = BoardWrites(pack["board"])
    for card in cards:
        state.setdefault("exempt", {})[card] = int(moment)
        waiting.pop(card)
        writes.unblock(card)
    _save(HOLDS_FILE, state)
    writes.flush()
    drop_row(ROW_PLUGIN, f"budget-wait-{provider}")
    return f"{len(cards)} card(s) of {provider} start now"


# ---------- 3. the wait: ready cards of a provider at its ceiling ----------


def _ceiling(pack, moment: float) -> tuple:
    """({provider: why it is at its ceiling}, the budget state)."""
    from .settings import budget_state

    budget = budget_state(pack, now=moment)
    gate = {}
    for provider, why in (budget.get("over_providers") or {}).items():
        gate[provider] = f"budget ceiling: {why}; waits until under the ceiling"
    for provider, hold in holds(moment).items():
        gate[provider] = hold_text(provider, hold)
    return gate, budget


def _ours(reason) -> bool:
    return str(reason or "").startswith(MARK)


def _scheduled_reasons(connection, cards: list):
    """{card: the reason of its latest move to scheduled} (Hermes's `scheduled` event, else the run that move ended);
    None when the board keeps neither, so nothing can be told about who parked a card."""
    tables = {row[0] for row in connection.execute("select name from sqlite_master where type = 'table'")}
    events, runs = "task_events" in tables, "task_runs" in tables
    if not events and not runs:
        return None
    found = {}
    for card in cards:
        reason = None
        if events:
            row = connection.execute(
                "select payload from task_events where task_id = ? and kind = 'scheduled' order by id desc limit 1",
                (card,),
            ).fetchone()
            try:
                payload = json.loads(row[0]) if row and row[0] else {}
            except (TypeError, ValueError):
                payload = {}
            reason = payload.get("reason") if isinstance(payload, dict) else None
        if reason is None and runs:
            row = connection.execute(
                "select summary from task_runs where task_id = ? and outcome = 'scheduled' order by id desc limit 1",
                (card,),
            ).fetchone()
            reason = row[0] if row else None
        found[card] = reason
    return found


def _put_once(row: dict) -> None:
    """Write the row only when it says something new, so its time is when it started, not the last minute."""
    from .inbox import _folder, put_row, row_id

    path = os.path.join(_folder(ROW_PLUGIN), f"{row_id(row['id'])}.json")
    try:
        current = json.load(open(path, encoding="utf-8"))
    except (OSError, ValueError):
        current = {}
    if current.get("what") == row["what"] and current.get("detail") == row.get("detail"):
        return
    put_row(ROW_PLUGIN, row)


def _drop_rows(prefix: str, keep: set) -> None:
    from .inbox import _folder, drop_row

    folder = _folder(ROW_PLUGIN)
    for name in sorted(os.listdir(folder)) if os.path.isdir(folder) else []:
        ident = name[:-5] if name.endswith(".json") else ""
        if ident.startswith(prefix) and ident not in keep:
            drop_row(ROW_PLUGIN, ident)


def step(pack, now=None) -> str:
    """Housekeeping, every minute: read the walls, end the holds that are over, make the ready cards of a provider at
    its ceiling wait and release the ones cockpit made wait once it is under, and keep the Inbox rows in step."""
    from .kanban import BoardWrites, db_path

    moment = time.time() if now is None else now
    state = _load(HOLDS_FILE)
    lanes = lane_providers(pack)
    path = db_path((pack or {}).get("board") or "")
    connection = read_db(path) if os.path.isfile(path) else None
    try:
        if connection is not None:
            _walls(pack, connection, state, lanes, moment)
        cleared = state.setdefault("cleared", {})
        for provider, hold in list((state.get("holds") or {}).items()):
            if not isinstance(hold, dict) or float(hold.get("until") or 0) <= moment:
                state["holds"].pop(provider, None)
                cleared[provider] = max(float(cleared.get(provider) or 0), float((hold or {}).get("last") or 0))
        _save(HOLDS_FILE, state)
        gate, _budget = _ceiling(pack, moment)
        held_now = holds(moment)
        waiting = state.setdefault("waiting", {})
        exempt = state.setdefault("exempt", {})  # cards the human let run at the budget ceiling (release_parked)
        titles = {}
        writes = BoardWrites(pack["board"])
        parked, released = [], []
        if connection is not None:
            columns = {row[1] for row in connection.execute("pragma table_info(tasks)")}
            claim = " and claim_lock is null" if "claim_lock" in columns else ""
            override = "provider_override" if "provider_override" in columns else "null"
            status = {str(card): str(value) for card, value in connection.execute("select id, status from tasks")}
            titles = {str(card): str(title or "") for card, title in connection.execute("select id, title from tasks")}
            for card in [card for card in exempt if status.get(card) in (None, "done", "archived")]:
                exempt.pop(card)
            scheduled = {
                str(card): str(chosen or "") or lanes.get(str(lane or "")) or ""
                for card, lane, chosen in connection.execute(
                    f"select id, assignee, {override} from tasks where status = 'scheduled'"
                )
            }
            reasons = _scheduled_reasons(connection, sorted(scheduled))
            for card, entry in list(waiting.items()):
                reason = (reasons or {}).get(card)
                if status.get(card) != "scheduled" or (reason is not None and not _ours(reason)):
                    waiting.pop(card)  # done, archived, or moved on by someone else: no longer cockpit's to release
                    continue
                entry.pop("pending", None)
            for card, provider in scheduled.items():
                # cockpit parked it and lost the record (a helper or a save that died part-way): it is cockpit's again
                # (a lane that lost its provider adopts with none: no ceiling cockpit knows holds it, so it is released)
                if card not in waiting and reasons is not None and _ours(reasons.get(card)):
                    waiting[card] = {"provider": provider, "at": int(moment), "adopted": True}
            for card, entry in list(waiting.items()):
                if entry.get("provider") not in gate:
                    writes.unblock(card)
                    released.append(card)
            for card, lane, chosen in connection.execute(
                f"select id, assignee, {override} from tasks where status = 'ready'{claim}"
            ):
                provider = str(chosen or "") or lanes.get(str(lane or ""))
                if provider in gate and not (str(card) in exempt and provider not in held_now):
                    writes.schedule(str(card), MARK + gate[provider])
                    parked.append((str(card), provider))
                    waiting[str(card)] = {"provider": provider, "at": int(moment), "pending": True}
        _save(HOLDS_FILE, state)  # the intent first: a helper that dies part-way leaves its cards recorded
        answers = writes.flush()
        for card in released:
            waiting.pop(card, None)
        for (card, _provider), done in zip(parked, answers[len(released) :]):
            if done:
                waiting[card].pop("pending", None)
            else:  # an older Hermes without the scheduled state, or a card claimed meanwhile, does not wait
                waiting.pop(card, None)
        _save(HOLDS_FILE, state)
    finally:
        if connection is not None:
            connection.close()
    active = holds(moment)
    for provider, hold in active.items():
        _put_once(_row_hold(provider, hold, sorted(lane for lane, runs in lanes.items() if runs == provider)))
    _drop_rows("provider-hold-", {f"provider-hold-{provider}" for provider in active})
    # cards waiting at a budget ceiling (no provider wall): one row per provider, with the cards and a way to let them run
    parked = {}
    for card, entry in sorted(waiting.items()):
        if entry.get("provider") in gate and entry.get("provider") not in active:
            parked.setdefault(entry["provider"], []).append(f"{card} {titles.get(card) or ''}".strip())
    for provider, cards in parked.items():
        _put_once(
            _row_budget(
                provider,
                gate[provider].removeprefix("budget ceiling: ").removesuffix("; waits until under the ceiling"),
                cards,
            )
        )
    _drop_rows("budget-wait-", {f"budget-wait-{provider}" for provider in parked})
    blind = unreadable(pack, moment)
    for provider, (since, good_at, error, left) in blind.items():
        _put_once(_row_unreadable(provider, since, good_at, error, left))
    _drop_rows("plan-usage-", {f"plan-usage-{provider}" for provider in blind})
    return f"{len(active)} held, {len(waiting)} waiting"
