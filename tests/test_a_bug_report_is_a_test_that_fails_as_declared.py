# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""A bug report is one test marked known_bug: while its assertion fails the run is green and lists it, once it passes
the run fails and asks for the marker to be dropped, and a report that cannot run is an ordinary failure. The marker is
tests/conftest.py's; each case here runs it in a folder of its own, outside this repository's settings."""

import os
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

HEAD = "import pytest\n\n\n"
OPEN = (
    HEAD
    + '@pytest.mark.known_bug("lib/note.py:12", "an empty day raises")\ndef test_an_empty_day_gives_a_note():\n    assert 1 + 1 == 3\n'
)
FIXED = (
    HEAD
    + '@pytest.mark.known_bug("lib/note.py:12", "an empty day raises")\ndef test_an_empty_day_gives_a_note():\n    assert 1 + 1 == 2\n'
)
CRASH = (
    HEAD
    + '@pytest.mark.known_bug("lib/note.py:12", "an empty day raises")\ndef test_an_empty_day_gives_a_note():\n    raise KeyError("day")\n'
)
BAD_IMPORT = "import pytest\nimport a_module_nobody_has\n\n\n" + OPEN[len(HEAD) :]
BAD_FIXTURE = HEAD + (
    "@pytest.fixture\ndef day():\n    assert False, 'the fixture broke'\n\n\n"
    '@pytest.mark.known_bug("lib/note.py:12", "an empty day raises")\n'
    "def test_an_empty_day_gives_a_note(day):\n    assert 1 + 1 == 3\n"
)
NO_TEXTS = HEAD + "@pytest.mark.known_bug\ndef test_an_empty_day_gives_a_note():\n    assert 1 + 1 == 3\n"
PLAIN = "def test_a_plain_rule_holds():\n    assert True\n"


def _run(tmp_path, body: str, *args):
    """pytest over one report in a folder that holds this repository's conftest and nothing else of it."""
    folder = tmp_path / "run"
    folder.mkdir()
    shutil.copy(os.path.join(ROOT, "tests", "conftest.py"), folder / "conftest.py")
    (folder / "pytest.ini").write_text(
        "[pytest]\nmarkers =\n    known_bug(where, what): an open bug report\n", encoding="utf-8"
    )
    (folder / "test_report.py").write_text(body, encoding="utf-8")
    (folder / "test_plain.py").write_text(PLAIN, encoding="utf-8")
    shell = {key: value for key, value in os.environ.items() if not key.startswith(("PYTEST_", "COV_", "COVERAGE_"))}
    return subprocess.run(
        [sys.executable, "-m", "pytest", "-p", "no:cacheprovider", "-p", "no:cov", "-rfE", *args, str(folder)],
        cwd=str(folder),
        capture_output=True,
        text=True,
        check=False,
        env=shell,
        timeout=300,
    )


def test_a_report_whose_assertion_fails_keeps_the_run_green_and_is_listed(tmp_path):
    done = _run(tmp_path, OPEN, "-p", "no:xdist")
    assert done.returncode == 0, done.stdout + done.stderr
    assert "BUG test_report.py::test_an_empty_day_gives_a_note (lib/note.py:12): an empty day raises" in done.stdout
    assert "1 passed, 1 xfailed" in done.stdout


def test_a_report_is_listed_once_when_the_run_is_spread_over_workers(tmp_path):
    done = _run(tmp_path, OPEN, "-n", "2")
    assert done.returncode == 0, done.stdout + done.stderr
    assert (
        done.stdout.count("BUG test_report.py::test_an_empty_day_gives_a_note (lib/note.py:12): an empty day raises")
        == 1
    )


def test_a_report_that_passes_fails_the_run_and_asks_for_the_marker_to_be_dropped(tmp_path):
    done = _run(tmp_path, FIXED, "-p", "no:xdist")
    assert done.returncode == 1
    assert "the bug this report describes is fixed (lib/note.py:12: an empty day raises)" in done.stdout
    assert "Remove the known_bug marker and move the file from tests/reports/ into tests/" in done.stdout
    assert "1 failed, 1 passed" in done.stdout and "BUG test_report.py" not in done.stdout


def test_a_report_that_raises_anything_but_a_failed_assertion_fails_the_run(tmp_path):
    done = _run(tmp_path, CRASH, "-p", "no:xdist")
    assert done.returncode == 1
    assert "KeyError" in done.stdout and "1 failed, 1 passed" in done.stdout and "BUG test_report.py" not in done.stdout


def test_a_report_that_cannot_be_imported_fails_the_run(tmp_path):
    done = _run(tmp_path, BAD_IMPORT, "-p", "no:xdist")
    assert done.returncode != 0
    assert (
        "a_module_nobody_has" in done.stdout
        and "xfailed" not in done.stdout
        and "BUG test_report.py" not in done.stdout
    )


def test_a_failed_assertion_in_a_report_s_fixture_is_an_error_not_the_expected_failure(tmp_path):
    done = _run(tmp_path, BAD_FIXTURE, "-p", "no:xdist")
    assert done.returncode == 1
    assert (
        "1 passed, 1 error" in done.stdout and "xfailed" not in done.stdout and "BUG test_report.py" not in done.stdout
    )


def test_a_marker_without_its_two_texts_stops_the_run_with_an_example(tmp_path):
    done = _run(tmp_path, NO_TEXTS, "-p", "no:xdist")
    assert done.returncode not in (0, 1)
    assert "known_bug takes two texts" in done.stdout + done.stderr
