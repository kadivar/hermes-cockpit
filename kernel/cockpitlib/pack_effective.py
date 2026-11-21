# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""What a pack's settings come to: every registry key with the value in force and where that value came from.

It only observes. The pack is loaded first (so a pack that does not load has no dump), then each file is read as the
pack wrote it and every key is resolved by the registry's own rule for it. Two kernels that print the same dump for a
pack give that pack the same settings; the values are the pack's own words, so two machines print the same too, save
where the pack asks for a personal value (`{home}`, `{local.<name>}`: pack_local), which is printed filled in.
"""

import json
import os

from . import pack_keys
from .errors import UsageError

PACK_SOURCE, DEFAULT, DEFAULT_FALSY, SETTINGS = "pack", "default", "default-falsy", "settings"
SOURCES = (PACK_SOURCE, DEFAULT, DEFAULT_FALSY, SETTINGS)
HIDDEN = "<set>"
PENDING_NOTE = "  (this default will change: cockpit pack pin)"
# What the Settings page overlays (settings.load): each key of these blocks, and the browser-loan hours.
OVERLAID = ("seats", "budget", "worktree_gc")


def _tree(file: str) -> dict:
    """The registry's keys of one file as a tree: {entry, children: {name | * | []: node}}."""
    root = {"entry": None, "children": {}}
    for entry in pack_keys.entries(file):
        node = root
        for part in pack_keys.segments(entry["path"]):
            node = node["children"].setdefault(part, {"entry": None, "children": {}})
        node["entry"] = entry
    return root


def _secret(name) -> bool:
    from .pack import SECRET_NAME

    return bool(SECRET_NAME.search(str(name)))


def _shown(value, name=""):
    """A value as the dump prints it: plain data, with whatever sits under a name that reads like a secret hidden."""
    if name and _secret(name) and value is not None:
        return HIDDEN
    if isinstance(value, dict):
        return {str(key): _shown(item, key) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_shown(item) for item in value]
    return value if isinstance(value, (str, int, float, bool)) or value is None else str(value)


def _raw_at(data, path: str) -> tuple:
    """(present, value) of a plain dotted path in a file as the pack wrote it."""
    node = data
    for part in pack_keys.segments(path):
        if not isinstance(node, dict) or part not in node:
            return False, None
        node = node[part]
    return True, node


class _Dump:
    def __init__(self, files: dict):
        self.files, self.rows = files, {}

    def lookup(self, path: str):
        """The value in force of another pack.yaml key, by the registry's rule for it."""
        present, value = _raw_at(self.files[pack_keys.PACK], path)
        entry = pack_keys.find(path)
        if entry is not None and pack_keys.defaulted(entry, present, value):
            return pack_keys.default_of(entry, self.lookup)
        return value

    def row(self, file, path, entry, present, value, name="", under=None) -> None:
        """One line of the dump. `under` is the registry place that vouches for a value with no entry of its own: an
        item of a registered list, or a key of a block whose keys are its owner's."""
        key = path if file == pack_keys.PACK else f"{file}:{path}"
        found = {
            "value": _shown(value, name),
            "source": PACK_SOURCE if present else DEFAULT,
            "registered": entry is not None or bool(under),
            "pattern": entry["path"] if entry else under or "",
        }
        if entry is not None and pack_keys.defaulted(entry, present, value):
            found["value"] = _shown(pack_keys.default_of(entry, self.lookup))
            found["source"] = DEFAULT_FALSY if present else DEFAULT
        self.rows[key] = found

    def walk(self, file, node, path, present, value, name="", under=None) -> None:
        entry, children = node["entry"], node["children"]
        listed = "[]" in children
        block = value is None or isinstance(value, list if listed else dict)
        if not children or not block:
            self.row(
                file, path, entry, present, value, name, under
            )  # a leaf, or a value that is not the block the registry expects
            return
        if entry is not None:
            self.row(
                file, path, entry, present, None if value is None else f"<list of {len(value)}>" if listed else "<map>"
            )
        if listed:
            items = entry["path"] + "[]" if entry else ""
            for index, item in enumerate(value or []):
                self.walk(file, children["[]"], f"{path}[{index}]", True, item, under=items)
            if not value:
                self.walk(file, children["[]"], f"{path}[]", False, None, under=items)
            return
        data = value or {}
        below = lambda key: f"{path}.{key}" if path else str(key)
        for key in sorted(child for child in children if child != "*"):
            self.walk(file, children[key], below(key), key in data, data.get(key), key)
        others = sorted((key for key in data if key not in children), key=str)
        for key in others:
            if "*" in children:
                self.walk(file, children["*"], below(key), True, data[key], key)
            else:
                self.row(
                    file,
                    below(key),
                    None,
                    True,
                    data[key],
                    key,
                    under=entry["path"] + ".*" if entry and entry.get("open") else None,
                )
        if "*" in children and not others:
            self.walk(file, children["*"], below("*"), False, None)


def _read(path: str, folder: str = "", fill_home: bool = True):
    from . import pack_local

    if not path or not os.path.isfile(path):
        return {}
    data = pack_local.read(path, folder, fill_home)
    return data if isinstance(data, dict) else {}


def _files(pack) -> dict:
    """Each pack file as the pack wrote it, personal values filled in (pack_local): the three it must have, and the
    others where it names or has them."""
    from .accounts import manifest_path

    folder = pack["_dir"]
    beside = lambda name: os.path.join(folder, name)
    helpers = pack.get("helpers")
    return {
        pack_keys.PACK: _read(pack["_path"]),
        pack_keys.REPOS: _read(beside("repos.yaml")),
        pack_keys.SKILLS: _read(beside("skills.yaml")),
        pack_keys.EGRESS: _read(beside("egress.yaml")),
        pack_keys.STAGING: _read(beside("staging.yaml")),
        pack_keys.HELPERS: _read(beside(helpers)) if isinstance(helpers, str) else {},
        pack_keys.ACCOUNTS: _read(manifest_path(pack), folder),
        pack_keys.MIGRATE: _read(beside("migrate.yaml"), fill_home=False),
    }


def _overlay() -> dict:
    """What a Settings save put over the pack, read as settings.load reads it; nothing where no workspace is bound."""
    from .errors import CockpitError
    from .settings import _overlay_path

    try:
        with open(_overlay_path(), encoding="utf-8") as handle:
            data = json.load(handle)
    except (CockpitError, OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _settings(pack, rows) -> None:
    overlay = _overlay()
    if not overlay:
        return
    from .settings import load

    merged = load(pack)

    def put(key, value) -> None:
        entry = pack_keys.find(key)
        rows[key] = {
            "value": _shown(value),
            "source": SETTINGS,
            "registered": entry is not None,
            "pattern": entry["path"] if entry else "",
        }

    for block in OVERLAID:
        for key in sorted(overlay[block]) if isinstance(overlay.get(block), dict) else ():
            put(f"{block}.{key}", merged[block][key])
    if "shared_chrome_hours" in overlay:
        put("shared_chrome_hours", merged["shared_chrome_hours"])


def rows_of(pack) -> dict:
    """{key: {value, source, registered, pattern}} for a loaded pack: every registry key, and every key the pack sets."""
    files = _files(pack)
    dump = _Dump(files)
    for file in pack_keys.FILES:
        dump.walk(file, _tree(file), "", True, files[file])
    _settings(pack, dump.rows)
    return dict(sorted(dump.rows.items()))


def effective(pack, sources: bool = False) -> dict:
    """The dump: {key: value}, or {key: {value, source}} with the sources."""
    return {key: _sourced(row) if sources else row["value"] for key, row in rows_of(pack).items()}


def _sourced(row) -> dict:
    return {"value": row["value"], "source": row["source"]}


def render(pack, sources: bool = False, as_json: bool = False) -> str:
    """The dump as text, the same for the same pack: sorted keys, one key a line (or JSON, indented). With the sources,
    a line whose value comes from a default that is listed for change says so after its source; the JSON, which two
    kernels are compared by, carries no such mark (`cockpit pack pin --json` lists those keys)."""
    found = effective(pack, sources)
    if as_json:
        return json.dumps(found, indent=2, sort_keys=True, ensure_ascii=False)
    marked = set()
    if sources:
        from .pack_pin import awaited

        marked = awaited(rows_of(pack))
    lines = []
    for key, row in found.items():
        value = json.dumps(row["value"] if sources else row, sort_keys=True, ensure_ascii=False)
        soon = PENDING_NOTE if key in marked else ""
        lines.append(f"{key} = {value}" + (f"  [{row['source']}]{soon}" if sources else ""))
    return "\n".join(lines)


def explain(pack, name: str) -> dict:
    """One key: its doc and shape from the registry, and each value it has in this pack with its source. A name the
    registry and the pack do not know is a UsageError that lists the close ones."""
    import difflib

    rows = rows_of(pack)
    entry = pack_keys.find(name)
    wanted = pack_keys.label(entry) if entry else ""
    file, path = pack_keys.split(name)
    exact = path if file == pack_keys.PACK else f"{file}:{path}"
    if exact in rows:
        values = {exact: rows[exact]}
    else:
        values = {
            key: row
            for key, row in rows.items()
            if entry
            and row["registered"]
            and (pack_keys.split(key)[0], row["pattern"]) == (entry["file"], entry["path"])
        }
    if not values:
        known = sorted({*rows, *(pack_keys.label(item) for item in pack_keys.ENTRIES)})
        close = difflib.get_close_matches(str(name), known, n=5, cutoff=0.5)
        raise UsageError(
            f"no pack key {name}"
            + (f" (close: {', '.join(close)})" if close else "")
            + "; e.g. cockpit pack explain forge.bump_batch"
        )
    found = {"key": wanted or exact, "values": {key: _sourced(row) for key, row in values.items()}}
    if entry is None:
        return {**found, "doc": "A key the pack sets that the registry does not describe.", "file": file}
    found.update({"doc": entry["doc"], "file": entry["file"], "type": entry["type"]})
    for field in ("enum", "min", "max", "required", "security", "when", "example"):
        if field in entry:
            found[field] = _shown(entry[field])
    if "default" in entry:
        default = entry["default"]
        found["default"] = repr(default) if isinstance(default, (pack_keys.Ref, pack_keys.Key)) else _shown(default)
    return found


def render_explain(found: dict, as_json: bool = False) -> str:
    if as_json:
        return json.dumps(found, indent=2, sort_keys=True, ensure_ascii=False)
    lines = [
        f"{key} = {json.dumps(row['value'], sort_keys=True, ensure_ascii=False)}  [{row['source']}]"
        for key, row in found["values"].items()
    ]
    lines.append(f"  {found['doc']}")
    shape = [
        f"{field} {json.dumps(found[field], ensure_ascii=False)}"
        for field in ("type", "file", "enum", "min", "max", "required", "security")
        if field in found
    ]
    if "default" in found:
        shape.append(f"default {json.dumps(found['default'], ensure_ascii=False)} when {found.get('when')}")
    lines.append("  " + " · ".join(shape))
    return "\n".join(lines)
