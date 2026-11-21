# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Where the kernel gives a pack key a default at the place it reads it: `x.get("key") or DEFAULT` and
`x.get("key", DEFAULT)`, found by reading the source. A receiver counts when it is the pack, a block of it, or a name
the function set from one; the key must be one the registry knows."""

import ast
import glob
import os

from cockpitlib import pack_keys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
KERNEL = os.path.join(ROOT, "kernel", "cockpitlib")
COMPANIONS = {"repos": pack_keys.REPOS, "skills": pack_keys.SKILLS, "egress": pack_keys.EGRESS}
# Names that are the loaded pack, and the files where `data` is one too (the validators).
PACK_NAMES = ("pack",)
DATA_FILES = ("pack.py", "helpers.py", "registry.py")
# A parameter or an attribute that holds a block of the pack, where no assignment in the function says so.
GIVEN = {
    ("*", "repo"): "repos.yaml:repos[]",
    ("pack.py", "egress"): "egress.yaml:",
    ("tracker.py", "config"): "tracker",
    ("tracker.py", "self.config"): "tracker",
    ("trackers/__init__.py", "config"): "tracker",
    ("trackers/base.py", "config"): "tracker",
    ("trackers/base.py", "self.config"): "tracker",
    ("trackers/jira.py", "config"): "tracker",
    ("trackers/jira.py", "self.config"): "tracker",
    ("trackers/command.py", "config"): "tracker",
    ("trackers/command.py", "self.config"): "tracker",
    ("trackers/local.py", "self.config"): "tracker",
    ("slots.py", "self.config"): "slots",
    ("vault.py", "privileged"): "privileged",
    ("capacity.py", "rules"): "capacity",
    ("helpers.py", "raw"): "helpers.yaml:helpers.*",
}
# A function whose answer is a block of the pack.
CALLS = {
    ("git_push.py", "repo_entry"): "repos.yaml:repos[]",
    ("publish.py", "repo_entry"): "repos.yaml:repos[]",
    ("advise.py", "config"): "advisor",
    ("tracker.py", "_config"): "tracker",
    ("egress.py", "_config"): "tracker",
}
EMPTY = ("{}", "[]", "()", "''", "None", "set()", "dict()", "list()")


def _child(prefix, key):
    """The registry place of a key under a place, or None when the registry has none there."""
    if prefix is None or not isinstance(key, str):
        return None
    if prefix == "" and key in COMPANIONS:
        return COMPANIONS[key] + ":"
    path = key if prefix == "" or prefix.endswith(":") else f"{prefix}.{key}"
    name = (prefix if prefix.endswith(":") else "") + (key if prefix.endswith(":") else path)
    return name if pack_keys.find(name) is not None else None


def _text(node) -> str:
    return ast.unparse(node)


class _Function:
    def __init__(self, file, aliases):
        self.file, self.aliases = file, dict(aliases)

    def place(self, node):
        """The registry place an expression holds: "" for the pack itself, a key's label for a block, or None."""
        if isinstance(node, ast.Name):
            if node.id in self.aliases:
                return self.aliases[node.id]
            if node.id in PACK_NAMES or (node.id == "data" and self.file in DATA_FILES):
                return ""
            return GIVEN.get((self.file, node.id), GIVEN.get(("*", node.id)))
        if isinstance(node, ast.Attribute):
            return GIVEN.get((self.file, _text(node)))
        if isinstance(node, ast.BoolOp) and isinstance(node.op, ast.Or):
            return self.place(node.values[0])
        if isinstance(node, ast.Subscript) and isinstance(node.slice, ast.Constant):
            return _child(self.place(node.value), node.slice.value)
        if isinstance(node, ast.Call):
            if _is_get(node):
                return _child(self.place(node.func.value), node.args[0].value)
            if isinstance(node.func, ast.Name) and node.func.id in ("dict", "list") and len(node.args) == 1:
                return self.place(node.args[0])
            if isinstance(node.func, ast.Name):
                return CALLS.get((self.file, node.func.id))
        return None

    def items(self, node):
        """The place of one item of a list the expression holds."""
        place = self.place(node)
        return place + "[]" if place and pack_keys.find(place + "[]._") is None and _has_items(place) else None


def _has_items(place) -> bool:
    file, path = pack_keys.split(place)
    return any(entry["file"] == file and entry["path"].startswith(path + "[]") for entry in pack_keys.ENTRIES)


def _is_get(node) -> bool:
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "get"
        and 1 <= len(node.args) <= 2
        and isinstance(node.args[0], ast.Constant)
        and isinstance(node.args[0].value, str)
    )


def _functions(tree):
    """(qualified name, node) of every function, a method as Class.method; the module's own body is "<module>"."""
    found = [("<module>", tree)]

    def walk(node, prefix):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                found.append((prefix + child.name, child))
                walk(child, prefix)
            elif isinstance(child, ast.ClassDef):
                walk(child, prefix + child.name + ".")
            else:
                walk(child, prefix)

    walk(tree, "")
    return found


def _own(node):
    """The nodes of a function's own body, not of the functions and classes written inside it."""
    stack = list(ast.iter_child_nodes(node))
    while stack:
        item = stack.pop()
        yield item
        if not isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            stack.extend(ast.iter_child_nodes(item))


def _scan_function(file, name, node, trivial) -> list:
    scope = _Function(file, {})
    own = list(_own(node))
    for _ in range(3):  # an alias may be set from another alias written further down
        for item in own:
            if isinstance(item, ast.Assign) and len(item.targets) == 1 and isinstance(item.targets[0], ast.Name):
                place = scope.place(item.value)
                if place is not None:
                    scope.aliases[item.targets[0].id] = place
            elif isinstance(item, (ast.For, ast.comprehension)) and isinstance(item.target, ast.Name):
                place = scope.items(item.iter)
                if place is not None:
                    scope.aliases[item.target.id] = place
    fallbacks = {}
    for item in own:
        if isinstance(item, ast.BoolOp) and isinstance(item.op, ast.Or):
            for index, value in enumerate(item.values[:-1]):
                if _is_get(value) and len(value.args) == 1:
                    fallbacks[id(value)] = ("or", " or ".join(_text(rest) for rest in item.values[index + 1 :]))
    hits = []
    for item in own:
        if not _is_get(item):
            continue
        form, fallback = ("get", _text(item.args[1])) if len(item.args) == 2 else fallbacks.get(id(item), ("", ""))
        key = _child(scope.place(item.func.value), item.args[0].value)
        if not form or key is None or (fallback in EMPTY and not trivial):
            continue
        entry = pack_keys.find(key)
        if entry is None:  # a whole companion file (pack["egress"]) is no key of its own
            continue
        hits.append(
            {
                "file": file,
                "function": name,
                "key": pack_keys.label(entry),
                "form": form,
                "fallback": fallback,
                "line": item.lineno,
            }
        )
    return hits


def scan_source(file: str, text: str, trivial: bool = False) -> list:
    """The defaults one module's source gives, as scan() lists them."""
    hits = []
    for name, node in _functions(ast.parse(text)):
        hits.extend(_scan_function(file, name, node, trivial))
    return sorted(hits, key=lambda hit: (hit["line"], hit["key"]))


def scan(trivial: bool = False) -> list:
    """Every default given at a reading place in kernel/cockpitlib, as {file, function, key, form, fallback, line}. An
    empty fallback ({}, [], "", None) is the absence of a value and is left out unless asked for."""
    hits = []
    for path in sorted(glob.glob(os.path.join(KERNEL, "**", "*.py"), recursive=True)):
        file = os.path.relpath(path, KERNEL)
        if file != "pack_keys.py":  # the table itself reads no pack
            hits.extend(scan_source(file, open(path, encoding="utf-8").read(), trivial))
    return hits


def functions_of(file: str) -> set:
    """The qualified names of the functions a kernel module defines."""
    tree = ast.parse(open(os.path.join(KERNEL, file), encoding="utf-8").read())
    return {name for name, _ in _functions(tree)}


if __name__ == "__main__":
    for hit in scan():
        print(f"{hit['file']}:{hit['line']} {hit['function']} {hit['key']} [{hit['form']}] {hit['fallback']}")
