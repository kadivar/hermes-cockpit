# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The lines a pack adds so that a default no longer decides anything for it.

A default the kernel is going to change is listed in pending_defaults.json beside this module, with the value it will
become and why. `cockpit pack pin` prints, for the bound pack, each such key the pack still takes from its default,
with today's value, as YAML to paste into the pack. It only prints: the pack is the adopter's to edit. A pack that
wrote the lines keeps today's behaviour whatever the default becomes. Nothing here changes what a key means; the list
is data for that later release and for a reader of the dump.
"""

import json
import os

from . import pack_keys
from .errors import CockpitError

PENDING_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "pending_defaults.json")


def pending() -> dict:
    """{key: {planned, reason}} of every default listed for change, by the key's registry name. A list that cannot be
    read is an error and never an empty list: an empty one would say there is nothing to pin."""
    try:
        with open(PENDING_FILE, encoding="utf-8") as handle:
            rows = json.load(handle)["pending"]
        return {row["key"]: {"planned": row["planned"], "reason": row["reason"]} for row in rows}
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise CockpitError(f"{PENDING_FILE} does not list the defaults that will change: {exc}") from exc


def _taken(row) -> bool:
    from .pack_effective import DEFAULT, DEFAULT_FALSY

    return row["source"] in (DEFAULT, DEFAULT_FALSY)


def _name(key: str, row) -> str:
    """The registry name of a dump row: its file and the pattern it was read by."""
    file = pack_keys.split(key)[0]
    return row["pattern"] if file == pack_keys.PACK else f"{file}:{row['pattern']}"


def awaited(rows: dict) -> set:
    """The keys of a dump whose value comes from a default that is listed for change."""
    listed = pending()
    return {key for key, row in rows.items() if row["registered"] and _taken(row) and _name(key, row) in listed}


def _placed(files: dict, file: str, path: str) -> bool:
    """True when the pack already writes every block above that key, so adding the key adds no block."""
    from .pack_effective import _raw_at

    if file != pack_keys.PACK and not files[file]:
        return False
    above = path.rsplit(".", 1)[0] if "." in path else ""
    if not above:
        return True
    present, value = _raw_at(files[file], above)
    return present and isinstance(value, dict)


def lines(pack, every: bool = False) -> list:
    """What to add, in the dump's order: [{file, key, value, doc, pending, as_yaml}], and for a pending key what it
    will become and why. Only a key whose default would count as set once written is listed (an empty default written
    out is still unset). With `every`, each key taken from a default; such a key inside a list item, or under a block
    the pack does not have, is listed with as_yaml false, since adding the block could itself change something."""
    from .pack_effective import _files, rows_of

    listed = pending()
    files = _files(pack)
    found = []
    for key, row in rows_of(pack).items():
        entry = pack_keys.find(key) if row["registered"] else None
        if entry is None or "default" not in entry or not _taken(row) or "*" in key or "[]" in key:
            continue
        if isinstance(entry["default"], pack_keys.Key):
            continue  # the value is another key's, which the pack wrote or pins under that key
        name = pack_keys.label(entry)
        if name not in listed and not every:
            continue
        if pack_keys.defaulted(entry, True, row["value"]):
            continue
        file, path = pack_keys.split(key)
        one = {
            "file": file,
            "key": path,
            "value": row["value"],
            "doc": entry["doc"],
            "pending": name in listed,
            "as_yaml": name in listed or ("[" not in path and _placed(files, file, path)),
        }
        if name in listed:
            one.update(listed[name])
        found.append(one)
    return sorted(found, key=lambda one: (pack_keys.FILES.index(one["file"]), one["key"]))


def _inline(value) -> str:
    """A value on one line, as YAML reads it back: plain where that fits on a line, else as JSON, which YAML reads too."""
    import yaml

    text = yaml.safe_dump(value, default_flow_style=True, allow_unicode=True, width=10**9)
    if text.endswith("\n...\n"):
        text = text[:-5]
    text = text.strip()
    return json.dumps(value, ensure_ascii=False, sort_keys=True) if "\n" in text else text


def _emit(node: dict, depth: int, out: list) -> None:
    pad = "  " * depth
    for name, inner in node.items():
        if isinstance(inner, dict) and inner.get("__leaf__") is not True:
            out.append(f"{pad}{_inline(name)}:")
            _emit(inner, depth + 1, out)
            continue
        one = inner["line"]
        out.append(f"{pad}# {one['doc']}")
        if one["pending"]:
            out.append(f"{pad}# its default will become {_inline(one['planned'])}: {one['reason']}")
        out.append(f"{pad}{_inline(name)}: {_inline(one['value'])}")


def render(pack, every: bool = False, as_json: bool = False) -> str:
    """The lines as text: one YAML document per pack file, a comment above each key, each block written once so a
    document merges into the file key by key. Nothing to add prints nothing."""
    found = lines(pack, every)
    if as_json:
        return json.dumps(found, indent=2, sort_keys=True, ensure_ascii=False)
    documents = []
    for file in pack_keys.FILES:
        mine = [one for one in found if one["file"] == file]
        if not mine:
            continue
        out = [f"# {file}: add these lines; a block the file already has takes the keys printed under it"]
        tree = {}
        for one in mine:
            if not one["as_yaml"]:
                continue
            node = tree
            parts = pack_keys.segments(one["key"])
            for part in parts[:-1]:
                node = node.setdefault(part, {})
            node[parts[-1]] = {"__leaf__": True, "line": one}
        _emit(tree, 0, out)
        for one in mine:
            if not one["as_yaml"]:
                out.append(
                    f"# not printed as a line (inside a list item, or under a block the pack does not have): "
                    f"{one['key']} = {_inline(one['value'])}"
                )
        documents.append("\n".join(out))
    return "\n---\n".join(documents)
