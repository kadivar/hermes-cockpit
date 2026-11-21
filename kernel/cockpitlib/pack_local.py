# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""A pack's personal values: what differs between two people who share one pack.

Every YAML file of a pack is read through `read`. In its string values, and only there, `{home}` becomes the user's
home folder and `{local.<name>}` becomes the value `pack.local.yaml` beside pack.yaml gives that name. No other brace
form is touched and no key is rewritten, so a file that uses neither token is returned exactly as it was parsed. A
name the local file does not set is a PackError that says which file and key used it; the kernel never guesses one.
"""

import copy
import os
import re

from .errors import PackError

LOCAL_FILE = "pack.local.yaml"
NAME = re.compile(r"[a-z][a-z0-9_]*")
HOME = "{home}"
TOKEN = re.compile(r"\{home\}|\{local\.([a-z][a-z0-9_]*)\}")
# The pack's files a load does not read, each with whether `{home}` is filled in it: in migrate.yaml that token is the
# runtime's home, which the migration fills itself.
LATE = (("staging.yaml", True), ("migrate.yaml", False), (os.path.join("platform", "map.yaml"), True))
_KEPT: dict = {}  # pack.local.yaml path -> (its stamp, the home it was filled with, its values)
_REAL: dict = {}  # (a pack.yaml path, the file it leads to) -> that file's own path


class Unset(PackError):
    """A file uses names pack.local.yaml does not set: one line for each use, the first being the message's first."""

    def __init__(self, lines: list):
        super().__init__("\n".join(lines))
        self.lines = list(lines)


def home() -> str:
    """The folder `{home}` stands for."""
    return os.path.expanduser("~")


def local_path(pack_dir: str) -> str:
    return os.path.join(pack_dir, LOCAL_FILE)


def stamp(pack_dir: str):
    """The state of the pack's local file, for a reader that keeps what it read: None while there is none."""
    try:
        seen = os.stat(local_path(pack_dir))
    except OSError:
        return None
    return (seen.st_mtime_ns, seen.st_size, seen.st_ino)


def real(path: str, seen) -> str:
    """The file a pack.yaml path leads to, given its stat: the local file sits beside that one. Asked on every path
    lookup, so the links are walked once per file."""
    key = (path, seen.st_ino, seen.st_dev)
    if key not in _REAL:
        _REAL.clear()
        _REAL[key] = os.path.realpath(path)
    return _REAL[key]


def _parse(path: str):
    import yaml

    with open(path, encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def _strings(node):
    """Every string value under a parsed node: of a mapping its values, never its keys."""
    if isinstance(node, str):
        yield node
    elif isinstance(node, dict):
        for value in node.values():
            yield from _strings(value)
    elif isinstance(node, list):
        for value in node:
            yield from _strings(value)


def _homed(node, folder: str):
    """A value of the local file with `{home}` filled in its strings."""
    if isinstance(node, str):
        return node.replace(HOME, folder)
    if isinstance(node, dict):
        return {key: _homed(value, folder) for key, value in node.items()}
    if isinstance(node, list):
        return [_homed(value, folder) for value in node]
    return node


def _checked(raw, folder: str) -> dict:
    """The local file's mapping, checked: names of lowercase letters, digits and underscores, and no value that asks
    for another local value."""
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise PackError(f"{LOCAL_FILE} must be a mapping of names to values")
    for name, value in raw.items():
        if not isinstance(name, str) or not NAME.fullmatch(name):
            raise PackError(
                f"{LOCAL_FILE}: {name!r} is not a name: lowercase letters, digits and underscores, starting with a letter"
            )
        if any(match.group(1) for text in _strings(value) for match in TOKEN.finditer(text)):
            raise PackError(
                f"{LOCAL_FILE}: {name} uses {{local.…}}: a personal value is written out, it never names another one"
            )
    return {name: _homed(value, folder) for name, value in raw.items()}


def values(pack_dir: str) -> dict:
    """{name: value} of pack.local.yaml beside the pack, `{home}` filled in; empty when there is no such file. The file
    is parsed once per version of it and per home; a caller gets its own copy."""
    path, seen, folder = local_path(pack_dir), stamp(pack_dir), home()
    if seen is None:
        _KEPT.pop(path, None)
        return {}
    kept = _KEPT.get(path)
    if kept is None or kept[:2] != (seen, folder):
        kept = _KEPT[path] = (seen, folder, _checked(_parse(path), folder))
    return copy.deepcopy(kept[2])


class _Fill:
    """One file being filled: where it is, what the names stand for (read when the first one is asked), and the uses
    of a name that is not set."""

    def __init__(self, file: str, pack_dir: str, fill_home: bool):
        self.file, self.pack_dir, self.fill_home = file, pack_dir, fill_home
        self.known: dict | None = None
        self.unset: list = []

    def local(self, name: str, where: str):
        """(set, value) of one name, noting a use of a name that is not set."""
        if self.known is None:
            self.known = values(self.pack_dir)
        if name not in self.known:
            self.unset.append(
                f'{self.file}, {where}: {{local.{name}}} is not set: add "{name}: …" to {LOCAL_FILE} beside the pack'
            )
            return False, None
        return True, self.known[name]

    def piece(self, match, where: str) -> str:
        """What one token inside a longer text becomes: the home, or a local value that is one piece of text."""
        name = match.group(1)
        if name is None:
            return home() if self.fill_home else match.group(0)
        found, value = self.local(name, where)
        if not found:
            return match.group(0)
        if isinstance(value, bool) or not isinstance(value, (str, int, float)):
            raise PackError(
                f"{self.file}, {where}: {{local.{name}}} is a {type(value).__name__} in {LOCAL_FILE}: inside a longer "
                "text it must be a text or a number (alone as the whole value it keeps its type)"
            )
        return str(value)

    def text(self, text: str, where: str):
        whole = TOKEN.fullmatch(text)
        if whole is not None and whole.group(1):
            found, value = self.local(whole.group(1), where)
            return copy.deepcopy(value) if found else text
        return TOKEN.sub(lambda match: self.piece(match, where), text)

    def node(self, node, where: str = ""):
        if isinstance(node, str):
            return self.text(node, where)
        if isinstance(node, dict):
            return {key: self.node(value, f"{where}.{key}" if where else str(key)) for key, value in node.items()}
        if isinstance(node, list):
            return [self.node(value, f"{where}[{index}]") for index, value in enumerate(node)]
        return node


def fill(data, file: str, pack_dir: str, fill_home: bool = True, unset=None):
    """Parsed YAML with the two tokens filled in its string values. Data that uses neither is returned as it is. Every
    use of an unset name is one line of the Unset raised; a caller that hands a list for those lines gets them there
    instead, and the token stays as written."""
    if not any(TOKEN.search(text) for text in _strings(data)):
        return data
    state = _Fill(file, pack_dir, fill_home)
    filled = state.node(data)
    if state.unset and unset is None:
        raise Unset(state.unset)
    if unset is not None:
        unset += state.unset
    return filled


def read(path: str, pack_dir: str = "", fill_home: bool = True, unset=None):
    """One YAML file of a pack, parsed and filled. pack_dir is the folder of pack.yaml when the file is not beside it;
    fill_home is False for a file where `{home}` already has a meaning of its own."""
    return fill(_parse(path), os.path.basename(path), pack_dir or os.path.dirname(path), fill_home, unset)


def early(path: str):
    """pack.yaml for a reader that runs before the pack is checked (a path lookup): filled where it can be, as written
    where it cannot. The load itself refuses what this reader lets pass."""
    try:
        return read(path, unset=[])
    except PackError:
        return _parse(path)


def unset_late(pack_dir: str) -> list:
    """The line for every use of an unset name in the files a load does not read (LATE), so a load refuses what a
    later reader of them would. A file that is not there, or that no reader could parse, is that reader's to refuse."""
    import yaml

    lines: list = []
    for name, fill_home in LATE:
        path = os.path.join(pack_dir, name)
        try:
            with open(path, encoding="utf-8") as handle:
                asks = "{local." in handle.read()
            if asks:
                read(path, pack_dir, fill_home, lines)
        except (OSError, UnicodeError, yaml.YAMLError):
            continue
    return lines
