# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""A path from a ticket key (or any other name) to a folder under the records or the worktrees is built by
paths.qa_of, paths.outbox_of and paths.worktree_of, which check the key as one path segment and that nothing leaves the
root. No other file joins one of those roots with a name it was given: this test reads the source and fails when one
does. A valid key gives the path it always gave."""

import ast
import os

import pytest

from cockpitlib import paths
from cockpitlib.errors import CockpitError

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SOURCES = (os.path.join(ROOT, "kernel", "cockpitlib"), os.path.join(ROOT, "dashboard", "cockpit"))
ROOTS = ("qa", "outbox", "wt")
NOT_ONE_FOLDER = ("..", "../TASK-100", "TASK-100/..", "a/b", "TASK-100\x00", ".", "TASK-100\\..", "/etc")

pytestmark = pytest.mark.structure


def _root_call(node) -> str:
    """qa(), outbox() or wt(), bare or as paths.qa(): the name of the root, else ""."""
    if not isinstance(node, ast.Call) or node.args or node.keywords:
        return ""
    name = (
        node.func.id
        if isinstance(node.func, ast.Name)
        else node.func.attr
        if isinstance(node.func, ast.Attribute)
        else ""
    )
    return name if name in ROOTS else ""


def _literal(node) -> bool:
    return isinstance(node, ast.Constant) and isinstance(node.value, str)


def hand_built(source: str) -> list:
    """(line, text) of each place a source joins a records or worktrees root with a name that is not written in the
    code: os.path.join(qa(), ticket, …), the same through a variable the function set to the root, and an f-string
    that puts the root in front of a name."""
    found = []
    tree = ast.parse(source)
    scopes = [tree] + [node for node in ast.walk(tree) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))]
    for scope in scopes:
        named = {}
        for node in (
            [] if scope is tree else ast.walk(scope)
        ):  # a name stands for a root only inside the function that set it
            if (
                isinstance(node, ast.Assign)
                and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name)
                and _root_call(node.value)
            ):
                named[node.targets[0].id] = _root_call(node.value)
            if (
                isinstance(node, ast.For)
                and isinstance(node.target, ast.Name)
                and isinstance(node.iter, (ast.Tuple, ast.List))
                and any(_root_call(item) for item in node.iter.elts)
            ):
                named[node.target.id] = "a root"
        for node in ast.walk(scope):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "join"
                and len(node.args) >= 2
            ):
                first = node.args[0]
                rooted = _root_call(first) or (isinstance(first, ast.Name) and named.get(first.id))
                if rooted and not _literal(node.args[1]):
                    found.append((node.lineno, ast.unparse(node)[:120]))
            if isinstance(node, ast.JoinedStr) and any(
                isinstance(part, ast.FormattedValue) and _root_call(part.value) for part in node.values
            ):
                found.append((node.lineno, ast.unparse(node)[:120]))
    return sorted(set(found))


def test_no_file_but_paths_joins_a_root_with_a_name_it_was_given():
    offenders = []
    for base in SOURCES:
        for folder, _dirs, files in os.walk(base):
            for name in sorted(files):
                path = os.path.join(folder, name)
                if not name.endswith(".py") or path == os.path.join(SOURCES[0], "paths.py"):
                    continue
                offenders += [
                    f"{os.path.relpath(path, ROOT)}:{line}: {text}"
                    for line, text in hand_built(open(path, encoding="utf-8").read())
                ]
    assert offenders == [], "build the path with paths.qa_of, outbox_of or worktree_of:\n" + "\n".join(offenders)


def test_the_reader_sees_each_way_of_building_a_path_by_hand():
    assert hand_built("import os\ndef f(t):\n    return os.path.join(qa(), t, 'pr')\n")
    assert hand_built("import os\ndef f(t):\n    return os.path.join(paths.outbox(), t)\n")
    assert hand_built("import os\ndef f(t):\n    base = wt()\n    return os.path.join(base, t)\n")
    assert hand_built("import os\ndef f(t):\n    for base in (outbox(), qa()):\n        yield os.path.join(base, t)\n")
    assert hand_built("def f(t):\n    return f'{qa()}/{t}'\n")
    assert hand_built("import os\ndef f(t):\n    return os.path.join(qa(), 'pr', t)\n") == []
    assert hand_built("import os\ndef f(t):\n    return os.path.join(qa_of(t), 'pr')\n") == []
    assert hand_built("import os\ndef f(t):\n    base = other()\n    return os.path.join(base, t)\n") == []


def test_a_valid_key_gives_the_path_it_always_gave(bare):
    for key in ("TASK-100", "ABC-7", "bumps-2026-01", "workspace", "own"):
        assert paths.qa_of(key) == os.path.join(paths.qa(), key)
        assert paths.qa_of(key, "pr", "api-7.json") == os.path.join(paths.qa(), key, "pr", "api-7.json")
        assert paths.outbox_of(key, "001-body.md") == os.path.join(paths.outbox(), key, "001-body.md")
        assert paths.worktree_of(key) == os.path.join(paths.wt(), key)
        assert paths.worktree_of(key, "api") == os.path.join(paths.wt(), key, "api")
        assert paths.worktree_of(key, "group/api") == os.path.join(paths.wt(), key, "group/api")
    assert paths.qa_of("TASK-100", "evidences/row-1.png") == os.path.join(paths.qa(), "TASK-100", "evidences/row-1.png")


def test_no_key_is_the_roots_own_level_and_never_another_folder(bare):
    assert paths.qa_of("", "ci") == os.path.join(paths.qa(), "ci") == paths.qa_of(None, "ci")
    assert paths.qa_of("") == paths.qa() and paths.worktree_of("") == paths.wt()
    assert paths.outbox_of("_sweep.requested") == os.path.join(paths.outbox(), "_sweep.requested")
    with pytest.raises(CockpitError, match="bad path"):
        paths.qa_of("", "../outside")


@pytest.mark.parametrize("key", NOT_ONE_FOLDER)
def test_a_key_that_is_not_one_folder_is_refused_by_every_helper(bare, key):
    for build in (paths.qa_of, paths.outbox_of, paths.worktree_of):
        with pytest.raises(CockpitError, match="bad ticket"):
            build(key)
    with pytest.raises(CockpitError, match="bad ticket"):
        paths.qa_of(key, "pr")


@pytest.mark.parametrize("part", ("..", "../TASK-200", "pr/../../TASK-200", "/etc/passwd", "a\x00b"))
def test_what_is_joined_below_a_ticket_stays_below_it(bare, part):
    with pytest.raises(CockpitError, match="bad path"):
        paths.qa_of("TASK-100", part)
    with pytest.raises(CockpitError, match="bad path"):
        paths.worktree_of("TASK-100", part)


def test_a_ticket_folder_that_is_a_link_out_of_the_root_is_refused(bare, tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    os.makedirs(paths.qa(), exist_ok=True)
    os.symlink(str(outside), os.path.join(paths.qa(), "TASK-100"))
    with pytest.raises(CockpitError, match="leads outside"):
        paths.qa_of("TASK-100", "plan.md")
    os.makedirs(os.path.join(paths.qa(), "TASK-200"))
    os.symlink(os.path.join(paths.qa(), "TASK-200"), os.path.join(paths.qa(), "TASK-300"))
    assert paths.qa_of("TASK-300", "plan.md").endswith(os.path.join("TASK-300", "plan.md")), (
        "a link that stays inside is a folder"
    )
