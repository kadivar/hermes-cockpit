# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Messages to the human. The pack names one command per event (notify.<event>: argv); the body goes on stdin.

{event}, {key} and the caller's fields are filled into the arguments, and COCKPIT_EVENT and COCKPIT_EVENT_KEY are
set, so one command (hermes send --to ... --file -) can serve every event. An event goes out once per key. A failed
send is a red notify-<event> row in the Inbox until that event next goes out.
"""

import os
import re
import subprocess
import time

from .store import dump_json

EVENT = re.compile(r"^[a-z][a-z0-9_-]*$")
TIMEOUT = 120
# Every event kernel code sends, and the CI states it announces as ci_<state>. Doctor warns about a notify key outside
# them (its command would never run); a test holds this list against the places that send.
EVENTS = (
    "standup",
    "advisory",
    "ready_for_review",
    "updated_after_review",
    "tracker_comment",
    "pr_comments",
    "rereview",
    "pr_stale",
    "pr_stale_review",
    "ticket_done",
)
CI_STATES = ("failed", "green")


def known_event(name: str) -> bool:
    """Whether kernel code sends an event of that name."""
    return name in EVENTS or name in [f"ci_{state}" for state in CI_STATES]


def command(pack, event: str) -> list:
    """The pack's argv for this event. A relative program path is beside pack.yaml."""
    argv = ((pack or {}).get("notify") or {}).get(event) or []
    if not isinstance(argv, list) or not argv:
        return []
    program = str(argv[0])
    if "/" in program and not os.path.isabs(program) and (pack or {}).get("_dir"):
        program = os.path.join(pack["_dir"], program)
    return [program, *[str(part) for part in argv[1:]]]


def run(pack, event: str, body: str, key: str = "", **fields) -> tuple:
    """Run the event's command once. (sent, detail): sent is False with an empty detail when the pack names none."""
    argv = command(pack, event)
    if not argv:
        return False, ""
    values = {"event": event, "key": key, **{name: str(value) for name, value in fields.items()}}
    filled = []
    for part in argv:
        for name, value in values.items():
            part = part.replace("{" + name + "}", value)
        filled.append(part)
    env = {**os.environ, "COCKPIT_EVENT": event, "COCKPIT_EVENT_KEY": key}
    try:
        done = subprocess.run(filled, input=body, capture_output=True, text=True, check=False, env=env, timeout=TIMEOUT)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, f"notify {event} failed: {exc}"
    if done.returncode != 0:
        tail = (done.stderr or done.stdout or "").strip().splitlines()[-1:] or [f"exit {done.returncode}"]
        return False, f"notify {event} failed: {tail[0]}"
    return True, f"notify {event} sent {' '.join(filled)}"


def _ledger_path() -> str:
    from .paths import watch_dir

    return os.path.join(watch_dir(), "notify-sent.json")


def notify(pack, event: str, key: str, body: str, **fields) -> dict:
    """Send this event for this key unless it already went out. A failure is kept for the Inbox and retried on the
    next call with the same key."""
    import json

    from .ops import _health, _health_hold

    path = _ledger_path()
    try:
        ledger = json.load(open(path, encoding="utf-8"))
    except (OSError, ValueError):
        ledger = {}
    sent = ledger.get(event) if isinstance(ledger.get(event), dict) else {}
    if key in sent:
        return {"ok": True, "sent": False, "already": True, "out": f"notify {event} {key} already sent"}
    if not command(pack, event):
        return {"ok": True, "sent": False, "already": False, "out": f"no notify.{event}"}
    ok, detail = run(pack, event, body, key=key, **fields)
    if not ok:
        _health_hold(f"notify-{event}", detail)
        return {"ok": False, "sent": False, "already": False, "out": detail}
    sent[key] = int(time.time())
    ledger[event] = sent
    os.makedirs(os.path.dirname(path), exist_ok=True)
    dump_json(path, ledger)
    _health(f"notify-{event}", detail)
    return {"ok": True, "sent": True, "already": False, "out": detail}
