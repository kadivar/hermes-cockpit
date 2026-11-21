# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""scripts/check is the one command a contributor and CI both run: it picks its steps by id, reads pytest's own report
into a stable result file, and ends with one verdict line. These tests read its logic and run it in a tree of its own
with stand-in tools; none of them runs this repository's suite."""

import importlib.machinery
import importlib.util
import json
import os
import shutil
import subprocess
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(ROOT, "scripts", "check")


def _load():
    loader = importlib.machinery.SourceFileLoader("cockpit_check_script", SCRIPT)
    module = importlib.util.module_from_spec(importlib.util.spec_from_loader(loader.name, loader))
    loader.exec_module(module)
    return module


check = _load()

JUNIT = """<?xml version="1.0" encoding="utf-8"?>
<testsuites><testsuite name="pytest" errors="1" failures="2" skipped="0" tests="5">
<testcase classname="tests.test_window" name="test_an_empty_day_gives_a_note[pack0]" time="0.01">
<failure message="AssertionError: assert '' == '# Standup'">env = {}

    def test_an_empty_day_gives_a_note(env):
&gt;       assert note == "# Standup"
E       AssertionError: assert '' == '# Standup'

kernel/cockpitlib/window.py:9: in helper
tests/test_window.py:41: AssertionError</failure></testcase>
<testcase classname="tests.test_window.TestHours" name="test_the_hour_is_the_pack_s" time="0.01">
<failure message="KeyError: 'hours'">tests/test_window.py:77: KeyError</failure></testcase>
<testcase classname="tests.reports.test_a_rule" name="test_a_rule" time="0.01">
<error message="failed on setup with &quot;fixture 'nope' not found&quot;">file tests/reports/test_a_rule.py, line 4</error></testcase>
<testcase classname="tests.test_window" name="test_a_fine_one" time="0.01"/>
<testcase classname="tests.test_window" name="test_a_skipped_one" time="0.0"><skipped message="no ffmpeg"/></testcase>
</testsuite></testsuites>
"""

OUTPUT_RED = """....F.E
=========================== short test summary info ============================
FAILED tests/test_window.py::test_an_empty_day_gives_a_note[pack0] - AssertionError: assert '' == '# Standup'
ERROR tests/reports/test_a_rule.py::test_a_rule
BUG tests/reports/test_other.py::test_other (kernel/x.py:3): it raises
============ 2 failed, 3 passed, 1 xfailed, 1 error in 12.31s =============
"""

OUTPUT_GREEN = """........
Required test coverage of 97.5% reached. Total coverage: 98.12%
BUG tests/reports/test_other.py::test_other (kernel/x.py:3): it raises
====================== 2689 passed, 2 skipped, 1 xfailed in 301.22s (0:05:01) ======================
"""

OUTPUT_UNDER = """........
FAIL Required test coverage of 97.5% not reached. Total coverage: 96.40%
============================= 2689 passed in 301.22s =============================
"""


# ---------- which steps run ----------


def test_with_no_selection_every_step_runs_cheapest_first():
    assert check.select() == [
        "env",
        "generated",
        "tokens",
        "lint",
        "typecheck",
        "structure",
        "security-surface",
        "tests",
        "coverage",
        "dashboard",
        "desktop",
    ]


def test_quick_is_everything_before_the_suite():
    assert check.select(quick=True) == [
        "env",
        "generated",
        "tokens",
        "lint",
        "typecheck",
        "structure",
        "security-surface",
    ]


def test_only_runs_the_named_ids_in_running_order_and_coverage_brings_the_suite():
    assert check.select("structure, tokens") == ["tokens", "structure"]
    assert check.select("coverage") == ["tests", "coverage"]
    assert check.select("tests") == ["tests"]


@pytest.mark.parametrize("only, quick", [("nope", False), ("tokens,nope", False), (",", False), ("tokens", True)])
def test_a_selection_it_does_not_know_is_refused_with_the_right_form(only, quick):
    with pytest.raises(check.Usage) as refused:
        check.select(only, quick)
    assert "scripts/check --only tokens,structure" in str(refused.value)


# ---------- the result ----------


def test_the_verdict_names_every_failed_id_and_a_skip_never_fails():
    rows = [
        check.check("env", "pass", "ok"),
        check.check("generated", "skip", "absent"),
        check.check("tokens", "fail", "1"),
        check.check("desktop", "fail", "x"),
    ]
    assert check.verdict(rows) == ("fail", "CHECK fail · tokens,desktop")
    assert check.verdict(rows[:2]) == ("pass", "CHECK pass")


def test_the_result_file_has_its_stable_shape():
    rows = [
        check.check(
            "tokens", "fail", "1 forbidden names", [check.failure("tokens", "docs/a.md", None, "x in docs/a.md")]
        )
    ]
    made = check.result("abc123", rows, ["fence", "fence"])
    assert made == {
        "schema": 1,
        "sha": "abc123",
        "verdict": "fail",
        "security_surface": ["fence"],
        "checks": [
            {
                "id": "tokens",
                "status": "fail",
                "summary": "1 forbidden names",
                "rerun": "scripts/check --only tokens",
                "failures": [{"test": "tokens", "file": "docs/a.md", "line": None, "message": "x in docs/a.md"}],
            }
        ],
    }
    assert json.loads(json.dumps(made)) == made


# ---------- reading pytest ----------


def test_a_junit_report_gives_each_failure_its_test_file_line_and_message():
    found = check.junit_failures(JUNIT)
    assert found == [
        {
            "test": "tests/test_window.py::test_an_empty_day_gives_a_note[pack0]",
            "file": "tests/test_window.py",
            "line": 41,
            "message": "AssertionError: assert '' == '# Standup'",
        },
        {
            "test": "tests/test_window.py::TestHours::test_the_hour_is_the_pack_s",
            "file": "tests/test_window.py",
            "line": 77,
            "message": "KeyError: 'hours'",
        },
        {
            "test": "tests/reports/test_a_rule.py::test_a_rule",
            "file": "tests/reports/test_a_rule.py",
            "line": None,
            "message": "failed on setup with \"fixture 'nope' not found\"",
        },
    ]


def test_a_report_that_is_not_xml_gives_no_failures_instead_of_a_crash():
    assert check.junit_failures("") == [] and check.junit_failures("<testsuite><testcase") == []


def test_the_short_summary_is_read_when_no_junit_report_was_written():
    assert check.summary_failures(OUTPUT_RED) == [
        {
            "test": "tests/test_window.py::test_an_empty_day_gives_a_note[pack0]",
            "file": "tests/test_window.py",
            "line": None,
            "message": "AssertionError: assert '' == '# Standup'",
        },
        {
            "test": "tests/reports/test_a_rule.py::test_a_rule",
            "file": "tests/reports/test_a_rule.py",
            "line": None,
            "message": "",
        },
    ]


def test_the_summary_is_pytests_own_last_line_and_counts_the_open_reports():
    assert check.counts(OUTPUT_RED) == "2 failed, 3 passed, 1 xfailed, 1 error"
    assert check.counts("3 passed in 0.12s\n") == "3 passed" and check.counts("Traceback\n") == ""
    assert check.open_reports(OUTPUT_RED) == 1 and check.open_reports("no BUG here\n") == 0


def test_a_green_suite_at_the_gate_passes_both_rows():
    tests, coverage = check.suite_checks(0, OUTPUT_GREEN, "", True, True)
    assert (tests["status"], tests["summary"]) == ("pass", "2689 passed, 2 skipped, 1 xfailed · 1 open reports")
    assert (coverage["status"], coverage["summary"]) == ("pass", "98.12% of the 97.5% required")


def test_a_green_suite_under_the_gate_fails_coverage_alone():
    tests, coverage = check.suite_checks(1, OUTPUT_UNDER, "", True, True)
    assert tests["status"] == "pass" and coverage["status"] == "fail"
    assert coverage["failures"][0]["message"] == "total coverage 96.40% is under 97.5%"
    assert coverage["failures"][0]["file"] == "pyproject.toml"


def test_a_red_suite_fails_the_tests_row_with_the_junit_failures():
    tests, coverage = check.suite_checks(1, OUTPUT_RED, JUNIT, True, True)
    assert tests["status"] == "fail" and len(tests["failures"]) == 3 and tests["failures"][0]["line"] == 41
    assert coverage["status"] == "fail" and coverage["summary"] == "the run printed no coverage total"


def test_a_suite_that_dies_without_a_report_still_fails(tmp_path):
    rows = check.suite_checks(3, "INTERNALERROR> boom\n", "", False, True)
    assert len(rows) == 1 and (rows[0]["status"], rows[0]["summary"]) == ("fail", "pytest exited 3")


def test_coverage_that_is_not_enforced_is_a_skip_and_not_asked_for_is_no_row():
    tests, coverage = check.suite_checks(0, OUTPUT_UNDER, "", True, False)
    assert tests["status"] == "pass" and coverage["status"] == "skip"
    assert [row["id"] for row in check.suite_checks(0, OUTPUT_GREEN, "", False, True)] == ["tests"]


# ---------- open reports ----------


def test_the_open_reports_are_read_from_the_folder_s_sources(tmp_path):
    (tmp_path / "README.md").write_text("# reports\n", encoding="utf-8")
    (tmp_path / "test_an_empty_day_gives_a_note.py").write_text(
        "import pytest\n\n\n@pytest.mark.known_bug('kernel/x.py:3', 'it raises')\ndef test_an_empty_day_gives_a_note():\n    assert False\n",
        encoding="utf-8",
    )
    assert check.reports(str(tmp_path)) == [
        (
            "tests/reports/test_an_empty_day_gives_a_note.py::test_an_empty_day_gives_a_note",
            "kernel/x.py:3",
            "it raises",
        )
    ]
    assert check.reports(str(tmp_path / "absent")) == []


# ---------- the security surface ----------

MODULE = 'import re\n\nKERNEL_DENY = (\n    r"\\bgit\\s+push\\b",\n    r"--no-verify",\n)\nKERNEL_NEVER = (r"(?i)^DELETE\\b", r"bulk")\n\n\ndef check(command):\n    return ""\n'


def test_a_block_ends_at_the_closing_bracket_of_its_own_indent_or_on_its_own_line():
    assert check.blocks(MODULE, r"^KERNEL_[A-Z_]+ = \(") == [(3, 6), (7, 7)]
    nested = 'owned = {\n    "approvals": {\n        "deny": ["git push*"],\n    },\n    "plugins": {},\n}\n'
    assert check.blocks(nested, r"^\s*\"approvals\": \{") == [(2, 4)]


def test_a_zero_context_diff_is_read_as_the_lines_each_side_lost_and_gained():
    diff = "@@ -4 +4 @@\n-a\n+b\n@@ -9,0 +10,2 @@\n+c\n+d\n@@ -20,3 +22,0 @@\n-e\n-f\n-g\n"
    assert check.hunks(diff) == ([(4, 4), (20, 22)], [(4, 4), (10, 11)])


def test_only_a_change_inside_the_block_touches_it_and_a_lost_block_counts_as_touched():
    pattern = r"^KERNEL_[A-Z_]+ = \("
    assert check.block_touched(MODULE, MODULE, "@@ -11 +11 @@\n", pattern) is False
    assert check.block_touched(MODULE, MODULE, "@@ -5 +5 @@\n", pattern) is True
    assert check.block_touched(MODULE, MODULE, "@@ -5,0 +6 @@\n", pattern) is True  # a deny added
    assert check.block_touched(MODULE, MODULE, "@@ -4 +3,0 @@\n", pattern) is True  # a deny removed
    assert check.block_touched(MODULE, "import re\n", "@@ -3,5 +2,0 @@\n", pattern) is True
    assert check.block_touched(MODULE, MODULE.replace("KERNEL_", "LOOSE_"), "@@ -3 +3 @@\n", pattern) is True
    assert check.block_touched(MODULE, MODULE, "", pattern) is False


def _git(repo, *argv):
    subprocess.run(
        ["git", "-c", "user.name=Dev", "-c", "user.email=dev@example.test", "-C", str(repo), *argv],
        check=True,
        capture_output=True,
    )


def test_the_surface_names_what_a_branch_touches_since_its_base(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    (repo / "kernel" / "cockpitlib").mkdir(parents=True)
    (repo / "hooks").mkdir()
    (repo / "kernel" / "cockpitlib" / "egress.py").write_text(MODULE, encoding="utf-8")
    (repo / "kernel" / "cockpitlib" / "setup.py").write_text(
        'owned = {\n    "approvals": {\n        "deny": ["git push*"],\n    },\n}\nx = 1\n', encoding="utf-8"
    )
    (repo / "kernel" / "cockpitlib" / "fence.py").write_text("GUARDED = ()\n", encoding="utf-8")
    (repo / "hooks" / "egress.py").write_text("pass\n", encoding="utf-8")
    _git(tmp_path, "init", "-q", str(repo))
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "base")
    _git(repo, "branch", "base")
    monkeypatch.setattr(check, "ROOT", str(repo))
    assert check.surface("base") == []
    (repo / "kernel" / "cockpitlib" / "egress.py").write_text(
        MODULE.replace('return ""', 'return "no"'), encoding="utf-8"
    )
    (repo / "kernel" / "cockpitlib" / "setup.py").write_text(
        'owned = {\n    "approvals": {\n        "deny": ["git push*"],\n    },\n}\nx = 2\n', encoding="utf-8"
    )
    _git(repo, "commit", "-q", "-am", "outside the blocks")
    assert check.surface("base") == []
    (repo / "kernel" / "cockpitlib" / "egress.py").write_text(
        MODULE.replace('    r"--no-verify",\n', ""), encoding="utf-8"
    )
    (repo / "kernel" / "cockpitlib" / "fence.py").write_text("GUARDED = (1,)\n", encoding="utf-8")
    _git(repo, "commit", "-q", "-am", "a deny removed, the fence changed")
    assert check.surface("base") == ["fence", "kernel-denies"]
    # the working tree counts before it is committed
    (repo / "kernel" / "cockpitlib" / "setup.py").write_text(
        'owned = {\n    "approvals": {\n        "deny": [],\n    },\n}\nx = 2\n', encoding="utf-8"
    )
    (repo / "hooks" / "egress.py").write_text("raise SystemExit(0)\n", encoding="utf-8")
    assert check.surface("base") == ["egress-hook", "fence", "kernel-denies", "seat-approvals"]


# ---------- the script, run in a tree of its own ----------

FAKE_TEST = """#!/usr/bin/env bash
# a stand-in for scripts/test: it records how it was called and writes the junit report it was asked for
echo "workers=$TEST_WORKERS args=$*"
for arg in "$@"; do
  case "$arg" in --junitxml=*) cp "$(dirname "$0")/../junit.xml" "${arg#--junitxml=}" ;; esac
done
cat "$(dirname "$0")/../output.txt"
exit "$(cat "$(dirname "$0")/../status.txt")"
"""


def _tree(tmp_path, tokens_exit=0, python_ok=True, tools=""):
    """The script in a tree of its own: a stand-in interpreter, token scan and scripts/test, and an installed desktop.
    `tools` is the shell text that answers `python -m <tool> …`; without it no tool of the dev extra is installed."""
    tree = tmp_path / "tree"
    for folder in ("scripts", ".venv/bin", "tests/reports", "desktop/node_modules"):
        (tree / folder).mkdir(parents=True)
    shutil.copy(SCRIPT, tree / "scripts" / "check")
    fake = tree / ".venv" / "bin" / "python"
    fake.write_text(
        "#!/usr/bin/env bash\n"
        + ('if [ "$1" = "-c" ]; then exit %d; fi\n' % (0 if python_ok else 1))
        + ('if [ "$1" = "-m" ]; then shift\n' + (tools or "exit 1") + "\nfi\n")
        # a script of the tree is run as itself; anything else this stand-in is handed is the token scan
        + 'if [ -x "$1" ] && [ "${1#scripts/}" != "$1" ]; then exec "$@"; fi\n'
        + (
            'if [ "%d" != "0" ]; then echo "ui-vendor-names.txt: Vendor in docs/guide.md"; exit 1; fi\necho "tokens ok"\n'
            % tokens_exit
        ),
        encoding="utf-8",
    )
    fake.chmod(0o755)
    (tree / "scripts" / "test").write_text(FAKE_TEST, encoding="utf-8")
    (tree / "scripts" / "test").chmod(0o755)
    (tree / "desktop" / "package-lock.json").write_text("{}", encoding="utf-8")
    (tree / "desktop" / "node_modules" / ".package-lock.json").write_text("{}", encoding="utf-8")
    (tree / "junit.xml").write_text(JUNIT, encoding="utf-8")
    (tree / "output.txt").write_text(OUTPUT_RED, encoding="utf-8")
    (tree / "status.txt").write_text("1", encoding="utf-8")
    return tree


def _check(tree, *args, **shell):
    env = {key: value for key, value in os.environ.items() if not key.startswith(("CHECK_", "TEST_WORKERS"))}
    return subprocess.run(
        [sys.executable, str(tree / "scripts" / "check"), *args],
        capture_output=True,
        text=True,
        check=False,
        env={**env, **shell},
        cwd=str(tree),
        timeout=120,
    )


def test_a_green_step_ends_with_check_pass_and_writes_the_result_only_when_asked(tmp_path):
    tree = _tree(tmp_path)
    done = _check(tree, "--only", "tokens")
    assert done.returncode == 0 and done.stdout.strip().splitlines()[-1] == "CHECK pass"
    assert not (tree / "check-result.json").exists()
    assert _check(tree, "--only", "tokens", "--json").returncode == 0
    told = json.loads((tree / "check-result.json").read_text(encoding="utf-8"))
    assert (
        told["schema"] == 1
        and told["verdict"] == "pass"
        and set(told) == {"schema", "sha", "verdict", "checks", "security_surface"}
    )
    assert told["checks"] == [
        {
            "id": "tokens",
            "status": "pass",
            "summary": "no forbidden name in the scanned tree",
            "failures": [],
            "rerun": "scripts/check --only tokens",
        }
    ]


def test_a_red_step_ends_with_check_fail_and_its_id_and_exits_one(tmp_path):
    tree = _tree(tmp_path, tokens_exit=1)
    done = _check(tree, "--only", "tokens", "--json")
    assert done.returncode == 1 and done.stdout.strip().splitlines()[-1] == "CHECK fail · tokens"
    row = json.loads((tree / "check-result.json").read_text(encoding="utf-8"))["checks"][0]
    assert row["status"] == "fail" and row["failures"] == [
        {
            "test": "tokens",
            "file": "docs/guide.md",
            "line": None,
            "message": "ui-vendor-names.txt: Vendor in docs/guide.md",
        }
    ]


def test_the_suite_step_passes_the_workers_and_the_extra_arguments_and_reads_the_failures(tmp_path):
    tree = _tree(tmp_path)
    done = _check(tree, "--only", "tests", "--workers", "1", "--json", CHECK_TEST_ARGS="-q tests/test_window.py")
    assert done.returncode == 1 and done.stdout.strip().splitlines()[-1] == "CHECK fail · tests"
    assert "workers=1 args=-rs -q tests/test_window.py --junitxml=" in done.stdout and "--cov" not in done.stdout
    row = json.loads((tree / "check-result.json").read_text(encoding="utf-8"))["checks"][0]
    assert row["id"] == "tests" and row["status"] == "fail" and row["rerun"] == "scripts/check --only tests"
    assert row["failures"][0] == {
        "test": "tests/test_window.py::test_an_empty_day_gives_a_note[pack0]",
        "file": "tests/test_window.py",
        "line": 41,
        "message": "AssertionError: assert '' == '# Standup'",
    }


def test_the_coverage_gate_is_asked_of_the_suite_unless_the_run_says_not_to_enforce_it(tmp_path):
    tree = _tree(tmp_path)
    (tree / "junit.xml").write_text("<testsuites/>", encoding="utf-8")
    (tree / "output.txt").write_text(OUTPUT_GREEN, encoding="utf-8")
    (tree / "status.txt").write_text("0", encoding="utf-8")
    done = _check(tree, "--only", "coverage")
    assert (
        done.returncode == 0
        and "workers=4 args=-rs --cov=cockpitlib --cov=dashboard.cockpit --junitxml=" in done.stdout
    )
    assert "-- coverage: pass · 98.12% of the 97.5% required" in done.stdout
    off = _check(tree, "--only", "coverage", CHECK_COVERAGE="0")
    assert off.returncode == 0 and "--cov" not in off.stdout and "-- coverage: skip" in off.stdout
    assert "--cov" not in _check(tree, "--only", "coverage", "--no-coverage").stdout


def test_without_the_test_tools_env_fails_with_the_install_command_and_the_rest_is_not_run(tmp_path):
    tree = _tree(tmp_path, python_ok=False)
    done = _check(tree, "--only", "env,tokens", "--json")
    assert done.returncode == 1 and done.stdout.strip().splitlines()[-1] == "CHECK fail · env"
    assert "uv venv .venv && uv pip install --python .venv/bin/python -e '.[test]'" in done.stdout
    rows = json.loads((tree / "check-result.json").read_text(encoding="utf-8"))["checks"]
    assert [(row["id"], row["status"]) for row in rows] == [("env", "fail"), ("tokens", "skip")]
    assert rows[1]["summary"] == "not run: env failed"


def test_a_generator_that_is_not_in_the_checkout_is_skipped_with_a_note(tmp_path):
    done = _check(_tree(tmp_path), "--only", "generated")
    assert done.returncode == 0 and "scripts/gen is not in this checkout: skipped" in done.stdout
    assert "-- generated: skip" in done.stdout


def test_a_stale_generated_file_fails_the_generated_step(tmp_path):
    tree = _tree(tmp_path)
    (tree / "scripts" / "gen").write_text(
        "#!/usr/bin/env bash\necho 'docs/reference/keys.md is stale'\nexit 1\n", encoding="utf-8"
    )
    (tree / "scripts" / "gen").chmod(0o755)
    done = _check(tree, "--only", "generated")
    assert done.returncode == 1 and done.stdout.strip().splitlines()[-1] == "CHECK fail · generated"


def test_the_security_surface_without_a_base_is_a_skip(tmp_path):
    done = _check(_tree(tmp_path), "--only", "security-surface")
    assert done.returncode == 0 and "-- security-surface: skip · no base ref" in done.stdout


def test_an_unknown_id_exits_two_and_names_the_ids(tmp_path):
    done = _check(_tree(tmp_path), "--only", "nope")
    assert (
        done.returncode == 2
        and "env, generated, tokens, lint, typecheck, structure, security-surface, tests, coverage, dashboard, desktop"
        in done.stderr
    )
    assert "CHECK" not in done.stdout


def test_reports_lists_the_open_reports_and_runs_nothing(tmp_path):
    tree = _tree(tmp_path)
    assert _check(tree, "--reports").stdout.strip() == "no open reports"
    (tree / "tests" / "reports" / "test_an_empty_day_gives_a_note.py").write_text(
        "import pytest\n\n\n@pytest.mark.known_bug('kernel/x.py:3', 'it raises')\ndef test_an_empty_day_gives_a_note():\n    assert False\n",
        encoding="utf-8",
    )
    done = _check(tree, "--reports")
    assert done.returncode == 0 and done.stdout.splitlines() == [
        "BUG tests/reports/test_an_empty_day_gives_a_note.py::test_an_empty_day_gives_a_note (kernel/x.py:3): it raises",
        "1 open reports",
    ]


def test_help_names_every_id_and_warns_about_the_worker_count(tmp_path):
    done = _check(_tree(tmp_path), "--help")
    flat = " ".join(done.stdout.split())
    assert done.returncode == 0 and "security-surface, tests, coverage, dashboard, desktop" in flat
    assert "A higher number can starve everything else on a laptop" in flat and "CHECK_TEST_ARGS" in flat


# ---------- the lint step ----------

RUFF = """if [ "$1" = "ruff" ] && [ "$2" = "--version" ]; then echo "ruff 0.0.0"; exit 0; fi
if [ "$1" = "ruff" ] && [ "$2" = "check" ]; then %s; fi
if [ "$1" = "ruff" ] && [ "$2" = "format" ]; then %s; fi
exit 1"""
CLEAN = ('echo "All checks passed!"; exit 0', 'echo "3 files already formatted"; exit 0')


def test_lint_without_its_tool_is_skipped_with_the_line_that_installs_it(tmp_path):
    done = _check(_tree(tmp_path), "--only", "lint", "--json")
    assert done.returncode == 0 and done.stdout.strip().splitlines()[-1] == "CHECK pass"
    assert "-- lint: skip · ruff is not installed: uv pip install" in done.stdout
    assert "--require-hashes -r requirements-dev.lock" in done.stdout and "CHECK_LINT=required" in done.stdout


def test_lint_without_its_tool_fails_where_the_run_requires_it(tmp_path):
    tree = _tree(tmp_path)
    done = _check(tree, "--only", "lint", "--json", CHECK_LINT="required")
    assert done.returncode == 1 and done.stdout.strip().splitlines()[-1] == "CHECK fail · lint"
    row = json.loads((tree / "check-result.json").read_text(encoding="utf-8"))["checks"][0]
    assert row["summary"] == "ruff is not installed and CHECK_LINT=required"
    assert row["failures"][0]["file"] == "requirements-dev.lock"


def test_lint_passes_when_no_rule_fires_and_every_file_is_formatted(tmp_path):
    done = _check(_tree(tmp_path, tools=RUFF % CLEAN), "--only", "lint", CHECK_LINT="required")
    assert done.returncode == 0
    assert "-- lint: pass · no rule finding, and every file is in the formatter's layout" in done.stdout
    assert "$ .venv/bin/python -m ruff check --output-format concise ." in done.stdout
    assert "$ .venv/bin/python -m ruff format --check ." in done.stdout


def test_a_rule_finding_and_an_unformatted_file_each_fail_lint_with_their_place(tmp_path):
    finding = "echo 'kernel/x.py:3:8: F401 `os` imported but unused'; echo 'Found 1 error.'; exit 1"
    layout = "echo 'Would reformat: kernel/y.py'; echo '1 file would be reformatted'; exit 1"
    tree = _tree(tmp_path, tools=RUFF % (finding, layout))
    done = _check(tree, "--only", "lint", "--json")
    assert done.returncode == 1 and "-- lint: fail · 1 rule findings, 1 files not formatted" in done.stdout
    row = json.loads((tree / "check-result.json").read_text(encoding="utf-8"))["checks"][0]
    assert row["failures"] == [
        {"test": "F401", "file": "kernel/x.py", "line": 3, "message": "`os` imported but unused"},
        {
            "test": "format",
            "file": "kernel/y.py",
            "line": None,
            "message": "not in the formatter's layout: run `ruff format`",
        },
    ]


def test_a_linter_that_stops_without_a_finding_still_fails_lint(tmp_path):
    broken = "echo 'ruff failed'; echo '  Cause: unknown rule'; exit 2"
    tree = _tree(tmp_path, tools=RUFF % (broken, broken))
    done = _check(tree, "--only", "lint", "--json")
    row = json.loads((tree / "check-result.json").read_text(encoding="utf-8"))["checks"][0]
    assert done.returncode == 1 and [item["test"] for item in row["failures"]] == ["ruff check", "ruff format"]


def test_ci_requires_the_lint_step_and_installs_its_tools_from_their_lock():
    ci = open(os.path.join(ROOT, ".github", "workflows", "ci.yml"), encoding="utf-8").read()
    assert "CHECK_LINT: required" in ci and "pip install --require-hashes -r requirements-dev.lock" in ci
    assert "CHECK_TYPES: required" in ci


# ---------- the typecheck step ----------

MYPY = """if [ "$1" = "mypy" ] && [ "$2" = "--version" ]; then echo "mypy 0.0"; exit 0; fi
exit 1"""
BASELINES = '#!/usr/bin/env bash\necho "$0 $*" > "$(dirname "$0")/../asked.txt"\n%s\n'


def _typed(tmp_path, script):
    tree = _tree(tmp_path, tools=MYPY)
    (tree / "scripts" / "baselines").write_text(BASELINES % script, encoding="utf-8")
    (tree / "scripts" / "baselines").chmod(0o755)
    return tree


def test_typecheck_without_its_tool_is_skipped_and_fails_where_the_run_requires_it(tmp_path):
    tree = _tree(tmp_path)
    done = _check(tree, "--only", "typecheck")
    assert done.returncode == 0 and "-- typecheck: skip · mypy is not installed: uv pip install" in done.stdout
    required = _check(tree, "--only", "typecheck", CHECK_TYPES="required")
    assert required.returncode == 1 and required.stdout.strip().splitlines()[-1] == "CHECK fail · typecheck"
    assert "mypy is not installed and CHECK_TYPES=required" in required.stdout


def test_typecheck_passes_when_no_file_is_worse_than_its_baseline(tmp_path):
    tree = _typed(tmp_path, 'echo "types: no file is worse than its baseline (12 errors counted)"; exit 0')
    done = _check(tree, "--only", "typecheck", CHECK_TYPES="required")
    assert done.returncode == 0
    assert "-- typecheck: pass · types: no file is worse than its baseline (12 errors counted)" in done.stdout
    # the interpreter the suite runs is the one that runs the checker
    assert "$ .venv/bin/python scripts/baselines --check types" in done.stdout


def test_a_file_with_more_type_errors_than_its_count_fails_typecheck_and_is_named(tmp_path):
    said = (
        'echo \'kernel/a.py:3: error: Item "None" has no attribute "get"  [union-attr]\'; '
        "echo 'kernel/a.py has 3 type errors, 2 are allowed: fix the new ones'; "
        "echo 'kernel/b.py has 1 type error(s) and none are allowed there: fix them'; "
        "echo 'types: 2 problem(s)'; exit 1"
    )
    tree = _typed(tmp_path, said)
    done = _check(tree, "--only", "typecheck", "--json")
    assert done.returncode == 1 and "-- typecheck: fail · types: 2 problem(s)" in done.stdout
    row = json.loads((tree / "check-result.json").read_text(encoding="utf-8"))["checks"][0]
    assert [(item["test"], item["file"]) for item in row["failures"]] == [
        ("types", "kernel/a.py"),
        ("types", "kernel/b.py"),
    ]
    assert row["failures"][0]["message"] == "kernel/a.py has 3 type errors, 2 are allowed: fix the new ones"


def test_a_checker_that_stops_without_a_verdict_fails_typecheck(tmp_path):
    tree = _typed(tmp_path, "echo 'types: the type checker stopped without a verdict'; exit 1")
    done = _check(tree, "--only", "typecheck", "--json")
    row = json.loads((tree / "check-result.json").read_text(encoding="utf-8"))["checks"][0]
    assert done.returncode == 1 and row["failures"] == [
        {
            "test": "types",
            "file": "scripts/baselines",
            "line": None,
            "message": "types: the type checker stopped without a verdict",
        }
    ]


# ---------- the coverage gate's figure ----------


def test_the_coverage_gate_is_written_once_in_pyproject_and_counts_branches():
    import tomllib

    settings = tomllib.load(open(os.path.join(ROOT, "pyproject.toml"), "rb"))["tool"]["coverage"]
    figure = settings["report"]["fail_under"]
    assert settings["run"]["branch"] is True and settings["report"]["precision"] == 2
    # the measure rounded down to one decimal: a gate, not a wish
    assert isinstance(figure, float) and 95 <= figure < 100 and round(figure, 1) == figure
    assert not any("fail-under" in word for word in check.COVERAGE)
    # no other file states the figure: each names the place it is written
    for name in (
        "scripts/check",
        ".github/workflows/ci.yml",
        "CONTRIBUTING.md",
        "AGENTS.md",
        "docs/contributing/architecture.md",
        ".agents/skills/contribute/SKILL.md",
    ):
        text = open(os.path.join(ROOT, name), encoding="utf-8").read()
        assert "fail-under" not in text and f"{figure}%" not in text and f"{int(figure)}%" not in text, name
    for name in ("docs/contributing/architecture.md", ".agents/skills/contribute/SKILL.md"):
        text = " ".join(open(os.path.join(ROOT, name), encoding="utf-8").read().split())
        assert "`fail_under` in `pyproject.toml`" in text, name
