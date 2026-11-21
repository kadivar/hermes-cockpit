# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The reports discipline: a test carries the known_bug marker if and only if its file is under tests/reports/, one
report per file, each file named for the behaviour. A report elsewhere would hide a red test in the suite, and a plain
test in the reports folder would be listed nowhere."""

import ast
import os

import pytest

pytestmark = pytest.mark.structure

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TESTS = os.path.join(ROOT, "tests")
REPORTS = os.path.join(TESTS, "reports")


def _marked(node) -> bool:
    """Whether a decorator, or a module's pytestmark, names the known_bug marker."""
    return any(isinstance(part, ast.Attribute) and part.attr == "known_bug" for part in ast.walk(node))


def _read(path: str) -> tuple:
    """(test functions that carry the marker, test functions that do not, whether the module marks all of them)."""
    tree = ast.parse(open(path, encoding="utf-8").read(), path)
    whole = any(
        isinstance(node, ast.Assign)
        and any(getattr(target, "id", "") == "pytestmark" for target in node.targets)
        and _marked(node.value)
        for node in tree.body
    )
    with_marker, without = [], []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test_"):
            (with_marker if whole or any(_marked(item) for item in node.decorator_list) else without).append(node.name)
    return with_marker, without, whole


def _test_files(folder: str) -> list:
    return sorted(
        os.path.join(dirpath, name)
        for dirpath, _dirs, names in os.walk(folder)
        for name in names
        if name.endswith(".py")
    )


def test_no_test_outside_the_reports_folder_carries_the_marker():
    stray = [
        os.path.relpath(path, ROOT)
        for path in _test_files(TESTS)
        if not path.startswith(REPORTS + os.sep) and (_read(path)[0] or _read(path)[2])
    ]
    assert stray == [], f"known_bug outside tests/reports/: {stray}"


def test_every_test_in_the_reports_folder_carries_the_marker_one_report_a_file():
    assert os.path.isfile(os.path.join(REPORTS, "README.md"))
    for path in _test_files(REPORTS):
        name = os.path.relpath(path, ROOT)
        assert os.path.basename(path).startswith("test_"), (
            f"{name}: a report file is named test_<behaviour sentence>.py"
        )
        with_marker, without, _whole = _read(path)
        assert without == [], f"{name}: {without} carry no known_bug marker; a plain test belongs in tests/"
        assert len(with_marker) == 1, f"{name}: one report per file, found {with_marker}"


def test_the_reader_tells_a_marked_test_from_a_plain_one(tmp_path):
    sample = tmp_path / "test_sample.py"
    sample.write_text(
        "import pytest\n\n\n@pytest.mark.known_bug('a.py:1', 'x')\ndef test_one():\n    assert False\n\n\n"
        "def test_two():\n    assert 'known_bug'\n",
        encoding="utf-8",
    )
    assert _read(str(sample)) == (["test_one"], ["test_two"], False)
    sample.write_text(
        "import pytest\n\npytestmark = pytest.mark.known_bug('a.py:1', 'x')\n\n\ndef test_one():\n    assert False\n",
        encoding="utf-8",
    )
    assert _read(str(sample)) == (["test_one"], [], True)
