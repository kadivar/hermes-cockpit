# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Cockpit's own Inbox rows, and the buttons on them.

A situation only the human can end (an intent no sweep decides, a return nobody amends, a provider hold, cards parked at
the budget ceiling) is a row under the plugin name `cockpit`, written through the same file contract every plugin uses
(cockpitlib.inbox): the Inbox opens its pane and a button queues the act the row itself declared. Cockpit is the
plugin that wrote the row, so the route drains the queue at once (`drain`) instead of waiting for a pass. An act
that is refused says why on the row; one that worked removes the row, and the step that raised it puts it back if the
situation is still there.
"""

import json
import os

from .errors import CockpitError
from .store import dump_json

PLUGIN = "cockpit"


def raise_row(row: dict) -> None:
    """Write the row only when it says something new, so its time is when it started."""
    from .quota import _put_once

    _put_once(row)


def clear(ident: str) -> bool:
    from .inbox import drop_row

    return drop_row(PLUGIN, ident)


def ids(prefix: str) -> list:
    from .inbox import _folder

    folder = _folder(PLUGIN)
    names = sorted(os.listdir(folder)) if os.path.isdir(folder) else []
    return [name[:-5] for name in names if name.endswith(".json") and name.startswith(prefix)]


def keep_only(prefix: str, keep) -> None:
    """Drop the rows of this kind whose situation is over."""
    for ident in ids(prefix):
        if ident not in keep:
            clear(ident)


def _say(ident: str, text: str) -> None:
    """What came of a press, on the row the button is on."""
    from .inbox import _folder, row_id

    path = os.path.join(_folder(PLUGIN), f"{row_id(ident)}.json")
    try:
        row = json.load(open(path, encoding="utf-8"))
    except (OSError, ValueError):
        return
    if not isinstance(row.get("detail"), dict):
        return
    row["detail"]["said"] = text
    dump_json(path, row)


def _sweep(pack, act) -> str:
    from .gate import sweep_again

    return sweep_again(act.get("intent") or "")


def _send_back(pack, act) -> str:
    from .gate import return_intent

    row = return_intent(pack, act.get("intent") or "", act.get("instruction") or "Check this intent and amend it.")
    returned = row["returned"]
    return f"{row['id']} back to {returned.get('lane') or 'its lane'}" + (
        f" on {returned['card']}" if returned.get("card") else ""
    )


def _drop(pack, act) -> str:
    from .outbox import drop

    return f"{drop(act.get('intent') or '', act.get('note') or 'dropped from its Inbox row')['id']} dropped"


def _end_hold(pack, act) -> str:
    from .quota import clear_hold

    return clear_hold(act.get("provider") or "")


def _retry_read(pack, act) -> str:
    from .quota import retry_read

    return retry_read(pack, act.get("provider") or "")


def _release(pack, act) -> str:
    from .quota import release_parked

    return release_parked(pack, act.get("provider") or "")


HANDLERS = {
    "sweep": _sweep,
    "send-back": _send_back,
    "drop": _drop,
    "end-hold": _end_hold,
    "retry-read": _retry_read,
    "release": _release,
}


def drain(pack) -> list:
    """Run every queued press of a cockpit row, oldest first: [{row, ok, out}]. A press is taken off the queue before it
    runs, so one that fails is not run again by the next press."""
    from .inbox import acts_dir

    folder = acts_dir(PLUGIN)
    done = []
    for name in sorted(os.listdir(folder)) if os.path.isdir(folder) else []:
        path = os.path.join(folder, name)
        try:
            entry = json.load(open(path, encoding="utf-8"))
        except (OSError, ValueError):
            entry = {}
        os.remove(path)
        act = entry.get("act") if isinstance(entry.get("act"), dict) else {}
        row = str(entry.get("row") or "")
        handler = HANDLERS.get(str(act.get("do") or ""))
        if handler is None:
            done.append({"row": row, "ok": False, "out": f"refused: no such act {act.get('do')!r}"})
            _say(row, done[-1]["out"])
            continue
        try:
            out = handler(pack, act)
        except (CockpitError, FileNotFoundError, ValueError) as exc:
            done.append({"row": row, "ok": False, "out": f"refused: {exc}"})
            _say(row, done[-1]["out"])
            continue
        clear(row)
        done.append({"row": row, "ok": True, "out": out})
    return done
