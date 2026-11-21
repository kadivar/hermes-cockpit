# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The type ratchet. The checker's errors are counted per file in tests/contract/type-errors.json; the `typecheck` step
of scripts/check (scripts/baselines --check types) fails when a file has more than its count or a file that is not
listed has any. A count may fall, and writing the file again records it. No error is silenced to reach a count."""

import importlib.machinery
import importlib.util
import json
import os
import re
import tomllib

import pytest

pytestmark = pytest.mark.structure

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _script(name: str):
    loader = importlib.machinery.SourceFileLoader(f"cockpit_{name}_script", os.path.join(ROOT, "scripts", name))
    module = importlib.util.module_from_spec(importlib.util.spec_from_loader(loader.name, loader))
    loader.exec_module(module)
    return module


baselines = _script("baselines")
BASELINE = json.load(open(os.path.join(ROOT, baselines.TYPES), encoding="utf-8"))
OUTPUT = (
    'kernel/a.py:3: error: Item "None" of "dict | None" has no attribute "get"  [union-attr]\n'
    "kernel/a.py:3: note: a note is no error\n"
    'kernel/a.py:9:4: error: Incompatible return value type (got "None", expected "str")  [return-value]\n'
    'scripts/check:12: error: Need type annotation for "found"  [var-annotated]\n'
)


def test_the_baseline_counts_errors_of_files_that_exist_in_the_code_that_is_checked():
    assert BASELINE and all(isinstance(count, int) and count > 0 for count in BASELINE.values())
    assert list(BASELINE) == sorted(BASELINE)
    checked = set(baselines.sources(baselines.TYPED, ROOT))
    assert set(BASELINE) <= checked, sorted(set(BASELINE) - checked)
    assert {
        "kernel/cockpitlib/egress.py",
        "dashboard/cockpit/routes/pages.py",
        "hooks/egress.py",
        "scripts/check",
    } <= checked
    assert not any(name.startswith("tests/") for name in checked)


def test_the_checker_is_set_for_the_oldest_supported_python_and_one_platform():
    project = tomllib.load(open(os.path.join(ROOT, "pyproject.toml"), "rb"))
    settings = project["tool"]["mypy"]
    assert f">={settings['python_version']}" == project["project"]["requires-python"]
    assert settings["platform"] == "linux" and settings["check_untyped_defs"] is False
    # what is installed beside the code is read as untyped, so a dependency's release does not move a count
    (untyped,) = settings["overrides"]
    assert untyped["follow_imports"] == "skip" and {"yaml", "fastapi", "hermes_cli.*", "agent.*"} <= set(
        untyped["module"]
    )


def test_no_error_is_silenced_in_the_code_that_is_checked():
    silenced = []
    for name in baselines.sources(baselines.TYPED, ROOT):
        text = open(os.path.join(ROOT, name), encoding="utf-8").read()
        silenced += [
            f"{name}:{number}"
            for number, line in enumerate(text.splitlines(), 1)
            if re.search(r"#\s*type:\s*ignore", line)
        ]
    assert silenced == [], "fix the error, or leave it counted: a silenced error is no longer seen"


def test_the_checkers_lines_are_counted_per_file_and_a_note_is_no_error():
    assert baselines.type_errors(OUTPUT) == {"kernel/a.py": 2, "scripts/check": 1}
    assert baselines.type_errors("Success: no issues found in 3 source files\n") == {}


def test_a_file_with_more_errors_than_its_count_and_a_file_that_is_not_listed_are_each_named():
    baseline = {"kernel/a.py": 1, "kernel/b.py": 4, "scripts/check": 1}
    counted = {"kernel/a.py": 2, "kernel/b.py": 3, "kernel/new.py": 1, "scripts/check": 1}
    assert baselines.type_problems(baseline, counted) == [
        "kernel/a.py has 2 type errors, 1 are allowed: fix the new ones",
        "kernel/new.py has 1 type error(s) and none are allowed there: fix them",
    ]
    assert baselines.improved(baseline, counted) == ["kernel/b.py"]
    assert baselines.improved(baseline, {"scripts/check": 1}) == ["kernel/a.py", "kernel/b.py"]


def _stubbed(monkeypatch, output, code=1, installed=True):
    monkeypatch.setattr(baselines, "has_mypy", lambda python: installed)
    monkeypatch.setattr(baselines, "run_mypy", lambda root, python: (code, output))


def test_the_command_writes_the_counts_and_its_check_passes_until_a_file_gets_worse(tmp_path, monkeypatch, capsys):
    (tmp_path / "tests" / "contract").mkdir(parents=True)
    root = str(tmp_path)
    _stubbed(monkeypatch, OUTPUT)
    assert baselines.main(["types"], root) == 0
    assert capsys.readouterr().out == "tests/contract/type-errors.json: 3 errors in 2 files\n"
    written = json.loads((tmp_path / "tests" / "contract" / "type-errors.json").read_text(encoding="utf-8"))
    assert written == {"kernel/a.py": 2, "scripts/check": 1}
    assert baselines.main(["--check", "types"], root) == 0
    assert capsys.readouterr().out == "types: no file is worse than its baseline (3 errors counted)\n"
    # one error fewer passes, and says how to record it
    _stubbed(monkeypatch, OUTPUT.split("scripts/check", maxsplit=1)[0])
    assert baselines.main(["--check", "types"], root) == 0
    assert "1 file(s) have fewer errors than their count: scripts/baselines types records it" in capsys.readouterr().out
    # one error more fails, with the checker's own lines for that file and no other
    _stubbed(monkeypatch, OUTPUT + 'scripts/check:40: error: "None" not callable  [misc]\n')
    assert baselines.main(["--check", "types"], root) == 1
    out = capsys.readouterr().out
    assert 'scripts/check:40: error: "None" not callable  [misc]' in out and "kernel/a.py:3" not in out
    assert out.splitlines()[-2:] == [
        "scripts/check has 2 type errors, 1 are allowed: fix the new ones",
        "types: 1 problem(s)",
    ]
    # a clean run is a count of nothing
    _stubbed(monkeypatch, "", code=0)
    assert baselines.main(["types"], root) == 0 and "0 errors in 0 files" in capsys.readouterr().out


def test_a_checker_that_stops_without_a_verdict_or_is_not_installed_never_reads_as_a_pass(
    tmp_path, monkeypatch, capsys
):
    (tmp_path / "tests" / "contract").mkdir(parents=True)
    (tmp_path / "tests" / "contract" / "type-errors.json").write_text("{}", encoding="utf-8")
    root = str(tmp_path)
    _stubbed(monkeypatch, "pyproject.toml: [mypy]: unknown option\n", code=2)
    assert baselines.main(["--check", "types"], root) == 1
    assert capsys.readouterr().out.splitlines()[-1] == "types: the type checker stopped without a verdict"
    _stubbed(monkeypatch, "mypy: can't read file 'kernel'\n", code=1)  # an exit of 1 with no error line is no verdict
    assert baselines.main(["types"], root) == 1
    _stubbed(monkeypatch, "", installed=False)
    assert baselines.main(["--check", "types"], root) == baselines.NO_MYPY
    assert "mypy is not installed in " in capsys.readouterr().out


def test_the_checker_runs_in_the_checkouts_own_interpreter_when_it_has_one(tmp_path):
    assert baselines.interpreter(str(tmp_path)) == baselines.sys.executable
    local = tmp_path / ".venv" / "bin" / "python"
    local.parent.mkdir(parents=True)
    local.write_text("#!/bin/sh\n[ \"$2\" = mypy ] && echo 'x.py:1: error: no  [misc]'\nexit 1\n", encoding="utf-8")
    local.chmod(0o755)
    assert baselines.interpreter(str(tmp_path)) == str(local)
    assert not baselines.has_mypy(str(local))
    code, output = baselines.run_mypy(str(tmp_path), str(local))
    assert code == 1 and baselines.type_errors(output) == {"x.py": 1}
