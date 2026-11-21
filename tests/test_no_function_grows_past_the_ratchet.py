# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The complexity ratchet. A function of the running code may have at most 15 decisions and 80 lines; the ones that are
over today are listed with their numbers in tests/contract/complexity.json, and the list only shrinks: a listed function
may not grow, a new one may not be over, and one that got under both limits must leave the list.
`scripts/baselines complexity` writes the list again; the measure is the one in that script."""

import importlib.machinery
import importlib.util
import json
import os

import pytest

pytestmark = pytest.mark.structure

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _script(name: str):
    loader = importlib.machinery.SourceFileLoader(f"cockpit_{name}_script", os.path.join(ROOT, "scripts", name))
    module = importlib.util.module_from_spec(importlib.util.spec_from_loader(loader.name, loader))
    loader.exec_module(module)
    return module


baselines = _script("baselines")
BASELINE = json.load(open(os.path.join(ROOT, baselines.COMPLEXITY), encoding="utf-8"))

SAMPLE = '''
def plain(x):
    return x


def decided(rows, flag):
    """Every kind of decision once."""
    found = [row for row in rows if row and flag]
    for row in rows:
        if row > 1 or flag:
            continue
        elif row:
            pass
    while flag:
        flag = False
    try:
        with open("x") as handle:
            handle.read()
    except OSError:
        pass
    match rows:
        case []:
            pass
        case _:
            pass
    return found


class Box:
    def method(self, x):
        def inner(y):
            return y if y else 0

        return [inner(item) for item in x]


def twice():
    pass


def twice():
    pass
'''


def test_no_function_is_worse_than_its_baseline_and_none_stays_listed_once_it_fits():
    assert baselines.complexity_problems(BASELINE, baselines.measure(ROOT)) == []


def test_the_limits_are_fifteen_decisions_and_eighty_lines_and_the_list_is_what_the_measure_writes():
    assert BASELINE["limits"] == {"complexity": 15, "lines": 80} == baselines.LIMITS
    assert set(BASELINE["functions"]) == set(baselines.complexity_baseline(baselines.measure(ROOT))["functions"])
    assert all(baselines.over(numbers) for numbers in BASELINE["functions"].values())


def test_the_measure_reads_the_code_that_runs_and_no_test():
    measured = baselines.measure(ROOT)
    files = {name.split("::")[0] for name in measured}
    assert {
        "kernel/cockpitlib/egress.py",
        "dashboard/cockpit/routes/pages.py",
        "hooks/egress.py",
        "scripts/check",
    } <= files
    assert "bin/cockpit" in baselines.sources(baselines.MEASURED, ROOT)
    assert not any(name.startswith(("tests/", "packs/")) for name in files)


def test_each_kind_of_decision_counts_once_and_a_nested_function_is_measured_as_itself():
    found = baselines.functions(SAMPLE)
    assert found["plain"] == {"complexity": 1, "lines": 2}
    # the comprehension's `if` and its `and`, for, if, or, elif, while, with, except, and two cases
    assert found["decided"]["complexity"] == 1 + 2 + 1 + 1 + 1 + 1 + 1 + 1 + 1 + 2
    assert found["decided"]["lines"] == 21
    # the inner function's own decision is not its outer's, and a conditional expression is not counted
    assert found["Box.method"] == {"complexity": 1, "lines": 5} and found["Box.method.inner"]["complexity"] == 1
    assert set(found) == {"plain", "decided", "Box.method", "Box.method.inner", "twice", "twice#2"}


def test_a_function_that_grows_a_new_one_over_a_limit_and_one_that_now_fits_are_each_named():
    baseline = {
        "limits": {"complexity": 15, "lines": 80},
        "functions": {
            "a.py::grew": {"complexity": 20, "lines": 90},
            "a.py::fits": {"complexity": 16, "lines": 40},
            "a.py::gone": {"complexity": 30, "lines": 100},
            "a.py::same": {"complexity": 16, "lines": 81},
            "a.py::shrank": {"complexity": 40, "lines": 200},
        },
    }
    measured = {
        "a.py::grew": {"complexity": 21, "lines": 95},
        "a.py::fits": {"complexity": 15, "lines": 40},
        "a.py::same": {"complexity": 16, "lines": 81},
        "a.py::shrank": {"complexity": 30, "lines": 100},
        "a.py::new_long": {"complexity": 2, "lines": 81},
        "a.py::new_small": {"complexity": 15, "lines": 80},
    }
    assert baselines.complexity_problems(baseline, measured) == [
        "a.py::fits is under both limits now: take it off the list (scripts/baselines complexity)",
        "a.py::grew grew: complexity 20 -> 21: it may only shrink",
        "a.py::grew grew: lines 90 -> 95: it may only shrink",
        "a.py::new_long is new over a limit (complexity 2 of 15, 81 lines of 80): make it smaller",
        "a.py::gone is listed and no longer exists: take it off the list (scripts/baselines complexity)",
    ]


def test_the_command_writes_the_list_and_its_check_says_what_got_worse(tmp_path, capsys):
    (tmp_path / "kernel" / "cockpitlib").mkdir(parents=True)
    (tmp_path / "tests" / "contract").mkdir(parents=True)
    module = tmp_path / "kernel" / "cockpitlib" / "long.py"
    module.write_text("def long():\n" + "    pass\n" * 80, encoding="utf-8")
    (tmp_path / "bin").mkdir()
    (tmp_path / "bin" / "tool").write_text("#!/usr/bin/env python3\ndef main():\n    pass\n", encoding="utf-8")
    (tmp_path / "bin" / "notes.txt").write_text("def not python\n", encoding="utf-8")
    (tmp_path / "bin" / "run").write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    root = str(tmp_path)
    assert baselines.sources(baselines.MEASURED, root) == ["bin/tool", "kernel/cockpitlib/long.py"]
    assert baselines.main(["complexity"], root) == 0
    assert capsys.readouterr().out == "tests/contract/complexity.json: 1 functions over a limit\n"
    written = json.loads((tmp_path / "tests" / "contract" / "complexity.json").read_text(encoding="utf-8"))
    assert written["functions"] == {"kernel/cockpitlib/long.py::long": {"complexity": 1, "lines": 81}}
    assert baselines.main(["--check", "complexity"], root) == 0
    assert "no function is worse than its baseline" in capsys.readouterr().out
    module.write_text("def long():\n" + "    pass\n" * 81, encoding="utf-8")
    assert baselines.main(["--check", "complexity"], root) == 1
    assert "kernel/cockpitlib/long.py::long grew: lines 81 -> 82: it may only shrink" in capsys.readouterr().out
    assert (
        baselines.main(["--check", "everything"], root) == 2 and "scripts/baselines --check" in capsys.readouterr().err
    )
