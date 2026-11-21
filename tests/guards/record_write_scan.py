# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Where the kernel and the routes write a file, found by reading the source: `open` in a writing mode, `os.fdopen`
and `os.open` for writing, `Path.write_text`/`write_bytes`, `os.replace`/`os.rename`, the `shutil` copies and moves,
and the calls of `store`'s own writers. A write is atomic here only when it goes through `store`; everything else is
listed for review in tests/contract/record-writes.json, which says for each whether the file is a shared record."""

import ast
import glob
import os

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TREES = (os.path.join(ROOT, "kernel", "cockpitlib"), os.path.join(ROOT, "dashboard", "cockpit"))
# store's writers: the one atomic path (and its exclusive-create and append forms).
HELPERS = ("write_json", "dump_json", "write_text", "write_bytes", "copy_file", "append_line", "log")
SHUTIL = ("copy", "copy2", "copyfile", "copytree", "move")
WRITING = set("wax+")


def _text(node) -> str:
    return ast.unparse(node)


def _mode(call):
    """The mode an open() call names, or None when it reads: a mode that is not a literal counts as writing."""
    node = call.args[1] if len(call.args) > 1 else next((kw.value for kw in call.keywords if kw.arg == "mode"), None)
    if node is None:
        return None
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value if WRITING & set(node.value) else None
    return _text(node)


def _os_open_writes(call) -> bool:
    return len(call.args) > 1 and any(
        flag in _text(call.args[1]) for flag in ("O_WRONLY", "O_RDWR", "O_CREAT", "O_APPEND")
    )


class _Scan(ast.NodeVisitor):
    def __init__(self, file):
        self.file, self.scope, self.hits, self.store_names = file, [], [], set()

    def visit_ImportFrom(self, node):
        if (node.module or "").split(".")[-1] == "store":
            self.store_names.update(alias.asname or alias.name for alias in node.names)
        self.generic_visit(node)

    def _scoped(self, node):
        self.scope.append(node.name)
        self.generic_visit(node)
        self.scope.pop()

    visit_FunctionDef = visit_AsyncFunctionDef = visit_ClassDef = _scoped

    def _hit(self, node, form, target, mode="", atomic=False):
        self.hits.append(
            {
                "file": self.file,
                "line": node.lineno,
                "function": ".".join(self.scope) or "<module>",
                "form": form,
                "target": target,
                "mode": mode,
                "atomic": atomic or os.path.basename(self.file) == "store.py",
            }
        )

    def visit_Call(self, node):
        func = node.func
        name = func.id if isinstance(func, ast.Name) else func.attr if isinstance(func, ast.Attribute) else ""
        owner = _text(func.value) if isinstance(func, ast.Attribute) else ""
        first = _text(node.args[0]) if node.args else ""
        if name == "open" and owner in ("", "io", "codecs") and _mode(node):
            self._hit(node, "open", first, _mode(node))
        elif name == "fdopen" and owner == "os" and _mode(node):
            self._hit(node, "os.fdopen", first, _mode(node))
        elif name == "open" and owner == "os" and _os_open_writes(node):
            self._hit(node, "os.open", first, _text(node.args[1]))
        elif (
            name in ("write_text", "write_bytes")
            and owner
            and owner.split(".")[-1] != "store"
            and owner not in self.store_names
        ):
            self._hit(node, "Path." + name, owner)
        elif name in ("replace", "rename") and owner == "os":
            self._hit(node, "os." + name, _text(node.args[1]) if len(node.args) > 1 else first)
        elif name in SHUTIL and owner == "shutil":
            self._hit(node, "shutil." + name, _text(node.args[1]) if len(node.args) > 1 else first)
        elif name in HELPERS and (owner.split(".")[-1] == "store" or (not owner and name in self.store_names)):
            self._hit(node, "store." + name, first, atomic=True)
        self.generic_visit(node)


def scan_source(file, source) -> list:
    """Every write in one source text, in line order."""
    found = _Scan(file)
    found.visit(ast.parse(source))
    return sorted(found.hits, key=lambda hit: (hit["line"], hit["form"]))


def scan() -> list:
    """Every write in the kernel and the routes, by file and line."""
    hits = []
    for tree in TREES:
        for path in sorted(glob.glob(os.path.join(tree, "**", "*.py"), recursive=True)):
            with open(path, encoding="utf-8") as handle:
                hits += scan_source(os.path.relpath(path, ROOT), handle.read())
    return hits


def key(hit) -> tuple:
    """What names a write on the reviewed list: where it is and what it writes, never its line."""
    return (hit["file"], hit["function"], hit["form"], hit["target"])


def unlisted(hits) -> list:
    """The writes that do not go through store, with how many times each (file, function, form, target) occurs."""
    counts = {}
    for hit in hits:
        if not hit["atomic"]:
            counts[key(hit)] = counts.get(key(hit), 0) + 1
    return counts


if __name__ == "__main__":
    for hit in scan():
        print(
            f"{hit['file']}:{hit['line']}\t{hit['function']}\t{hit['form']}\t{hit['mode']}\t{'store' if hit['atomic'] else '-'}\t{hit['target']}"
        )
