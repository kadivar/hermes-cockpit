# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Rows other plugins put on the human's Inbox, and the wake markers housekeeping leaves for them.

A file contract, so no code is imported across plugins: a plugin writes <records>/inbox/<plugin>/<id>.json as
{id, icon, what, action_label, href, tone}, and the Inbox lists it with a link to that plugin's page.

A row may also carry `detail`, and then the Inbox opens a pane for it rather than only navigating. It is
optional in every direction: a row without it reads and behaves exactly as before, a plugin that never
sets it is unchanged, and an install without that plugin has no rows at all.

The pane's buttons answer back the same way, by file: `queue_act` writes <records>/acts/<plugin>/<id>.json
and the plugin drains it on its next pass. The payload is read from the row the plugin itself wrote, never
from the caller — the page says only which action of which row — so a page cannot put a request a plugin
never offered into its queue, and cockpit runs nothing and imports nothing.
"""

import json
import os
import re
import time

from .store import append_line, dump_json

TONES = ("info", "warn", "danger", "ok")
# `detail`, when a row carries one: {title, status: {text, color}, fields: [{label, text, items}],
# actions: [{label, href, hint, act, chat, ide}]}. `fields` renders as a Brief. An action is a link the
# human follows (`href`), a request relayed back to the plugin (`act`), or one of cockpit's own doors on
# the row's `ticket` (`chat`, `ide`).
FIELDS = ("id", "icon", "what", "action_label", "href", "tone", "ticket", "detail")
ROW_ID = re.compile(r"[^A-Za-z0-9._-]+")


def _root() -> str:
    from .paths import records

    return records()


def _folder(plugin: str) -> str:
    return os.path.join(_root(), "inbox", plugin)


def row_id(text: str) -> str:
    return ROW_ID.sub("_", str(text or "")).strip("_")


def put_row(plugin: str, row: dict) -> str:
    from .errors import CockpitError

    if not isinstance(row, dict) or not row_id(row.get("id")) or not str(row.get("what") or "").strip():
        raise CockpitError("an Inbox row has an id and says what it is")
    if row.get("tone", "info") not in TONES:
        raise CockpitError(f"an Inbox row's tone is one of {', '.join(TONES)}")
    ident = row_id(row["id"])
    folder = _folder(row_id(plugin))
    os.makedirs(folder, exist_ok=True)
    kept = {field: row.get(field) for field in FIELDS if row.get(field) is not None}
    dump_json(os.path.join(folder, f"{ident}.json"), {**kept, "id": ident, "at": int(time.time())})
    return ident


def drop_row(plugin: str, ident: str) -> bool:
    path = os.path.join(_folder(row_id(plugin)), f"{row_id(ident)}.json")
    if not os.path.isfile(path):
        return False
    os.remove(path)
    return True


def gone(plugin: str, pack=None) -> bool:
    """The plugin that wrote these rows is not installed any more: nothing will take its rows away, so the human may."""
    from .pack import plugin_dir

    return plugin != "cockpit" and not plugin_dir(pack, plugin)


def dismiss_row(plugin: str, ident: str, pack=None) -> bool:
    """The human's Dismiss on a row whose plugin is gone. A row of a plugin that is installed is that plugin's to end."""
    from .errors import CockpitError

    if not gone(row_id(plugin), pack):
        raise CockpitError(f"{plugin} is installed: its rows end when it says so")
    return drop_row(plugin, ident)


def rows(pack=None) -> list:
    """Every plugin's rows, as the Inbox shows them. A file that is not a row is skipped. A row whose plugin is not
    installed any more says so (`orphan`): the Inbox offers Dismiss on it."""
    base = os.path.join(_root(), "inbox")
    found = []
    if not os.path.isdir(base):
        return found
    for plugin in sorted(os.listdir(base)):
        folder = os.path.join(base, plugin)
        if not os.path.isdir(folder):
            continue
        orphan = gone(plugin, pack)
        for name in sorted(os.listdir(folder)):
            if not name.endswith(".json"):
                continue
            try:
                row = json.load(open(os.path.join(folder, name), encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if isinstance(row, dict) and row.get("id") and row.get("what"):
                found.append(
                    {
                        **{field: row.get(field) for field in FIELDS},
                        "plugin": plugin,
                        "tone": row.get("tone") or "info",
                        "at": row.get("at"),
                        "queued": pending_presses(plugin, row["id"]),
                        "orphan": orphan,
                    }
                )
                found[-1]["detail"] = _rendered_detail(found[-1].get("detail"))
    return found


def _rendered_detail(detail):
    """A plugin's brief and what it said, rendered as markdown for the page (brief_html, said_html) beside the text."""
    if not isinstance(detail, dict):
        return detail
    from .render import markdown

    out = dict(detail)
    for key in ("brief", "said"):
        if str(detail.get(key) or "").strip():
            out[f"{key}_html"] = markdown(str(detail[key]))
    return out


def pending_presses(plugin: str, ident: str) -> list:
    """The indexes of a row's actions pressed and not yet taken by its plugin: the request files still waiting. The
    pane reads them, so a press shows as queued however often the pane is drawn again, not only in the pane that
    was pressed."""
    folder = acts_dir(plugin)
    # <row>-<index>.json (or the older <row>-<index>-<time>.json), and nothing else: a prefix match read the press of
    # row `a-1` as action 1 of row `a`
    shape = re.compile(rf"^{re.escape(row_id(ident))}-(\d+)(?:-\d{{9,}})?\.json$")
    found = set()
    for name in os.listdir(folder) if os.path.isdir(folder) else []:
        match = shape.match(name)
        if match:
            found.add(int(match.group(1)))
    return sorted(found)


def acts_dir(plugin: str) -> str:
    return os.path.join(_root(), "acts", row_id(plugin))


def queue_act(plugin: str, ident: str, index: int, client: dict = None) -> dict:
    """Queue one of a row's own declared actions for the plugin that wrote the row.

    The page names the row and which of its actions; the payload comes off that row's file, so the
    only requests that can reach a plugin are the ones it offered on its own row. Cockpit neither
    runs nor interprets it — the plugin drains the file and decides what it means. The entry also carries `via`
    ("pane"), `at` and, when known, `client`, to say where a press came from; a plugin that does not know them ignores them.
    """
    from .errors import CockpitError

    name = row_id(plugin)
    path = os.path.join(_folder(name), f"{row_id(ident)}.json")
    try:
        row = json.load(open(path, encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise CockpitError(f"no Inbox row {name}/{ident}") from exc
    actions = ((row.get("detail") or {}).get("actions") or []) if isinstance(row, dict) else []
    if not isinstance(index, int) or index < 0 or index >= len(actions):
        raise CockpitError(f"row {name}/{ident} has no action {index}")
    act = (actions[index] or {}).get("act") if isinstance(actions[index], dict) else None
    if not isinstance(act, dict) or not act:
        raise CockpitError(f"action {index} of {name}/{ident} is not one this row asks for")
    label = str((actions[index] or {}).get("label") or "")
    # The same button on the same row while its first press still waits for the plugin is the same request: a second
    # file would be acted on twice (a requeue run twice, two cards). It answers with the press already queued.
    # One file per row and action, created exclusively, so two presses landing together cannot both write one.
    if index in pending_presses(name, ident):
        return {"queued": "", "already": True, "plugin": name, "label": label}
    folder = acts_dir(name)
    os.makedirs(folder, exist_ok=True)
    ident_act = f"{row_id(ident)}-{index}-{int(time.time())}"
    entry = {"id": ident_act, "at": int(time.time()), "row": row_id(ident), "act": act, "via": "pane"}
    if client:  # who pressed it, when the call knows: advisory, nothing reads it as required
        entry["client"] = {key: str(value)[:200] for key, value in client.items() if value}
    try:
        dump_json(os.path.join(folder, f"{row_id(ident)}-{index}.json"), entry, exclusive=True)
    except FileExistsError:
        return {"queued": "", "already": True, "plugin": name, "label": label}
    return {"queued": ident_act, "plugin": name, "label": label}


def wake_path(plugin: str) -> str:
    return os.path.join(_root(), "wake", row_id(plugin))


def wake(plugin: str, card: str = "") -> str:
    """Touch the plugin's wake marker, naming the card that needs it."""
    path = wake_path(plugin)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    append_line(path, f"{int(time.time())} {card}\n")
    return path
