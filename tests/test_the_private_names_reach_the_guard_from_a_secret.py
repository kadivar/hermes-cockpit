# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The names of the places this tool was first used in are never a file of the repository. CI hands them to
scripts/check as the text of a secret; the tokens step keeps them in a file of that run, names it to the guard, and
fails a run that requires them and has none. No later step inherits them."""

import json
import os

import pytest
import yaml

from tests.test_one_command_runs_everything_ci_runs import _check, _tree, check

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# a stand-in guard: it prints what it was handed, so the test reads the hand-over
GUARD = (
    '#!/usr/bin/env bash\nif [ "$1" = "-c" ]; then exit 0; fi\n'
    'echo "file=${COCKPIT_EXTRA_TOKENS:-none} text=${EXTRA_TOKENS:-none}"\n'
    'if [ -n "$COCKPIT_EXTRA_TOKENS" ]; then echo "lines=$(grep -c . "$COCKPIT_EXTRA_TOKENS")"; fi\necho "tokens ok"\n'
)


def _guarded(tmp_path):
    tree = _tree(tmp_path)
    (tree / ".venv" / "bin" / "python").write_text(GUARD, encoding="utf-8")
    return tree


def _row(tree) -> dict:
    return json.loads((tree / "check-result.json").read_text(encoding="utf-8"))["checks"][0]


def test_the_secrets_text_becomes_a_file_of_the_run_that_the_guard_is_handed_and_is_gone_after(tmp_path):
    tree = _guarded(tmp_path)
    done = _check(
        tree, "--only", "tokens", "--json", EXTRA_TOKENS="first-name\nsecond name\n", CHECK_EXTRA_TOKENS="required"
    )
    assert done.returncode == 0 and "lines=2" in done.stdout
    handed = [line for line in done.stdout.splitlines() if line.startswith("file=")][0]
    path = handed.split("file=", 1)[1].split(" text=")[0]
    assert path.endswith("private-names.txt") and not path.startswith(str(tree)) and not os.path.exists(path)
    assert handed.endswith("text=none")  # the text itself is not passed on
    assert "first-name" not in done.stdout + done.stderr
    assert _row(tree)["summary"] == "no forbidden name in the scanned tree · with the private list"


def test_a_run_that_requires_the_names_fails_without_them_and_says_what_to_set(tmp_path):
    tree = _guarded(tmp_path)
    done = _check(tree, "--only", "tokens", "--json", CHECK_EXTRA_TOKENS="required", EXTRA_TOKENS="  \n")
    assert done.returncode == 1 and done.stdout.strip().splitlines()[-1] == "CHECK fail · tokens"
    assert (
        "set the repository secret EXTRA_TOKENS" in done.stdout and "tokens ok" not in done.stdout
    )  # the guard is not run
    row = _row(tree)
    assert row["status"] == "fail" and row["summary"] == "the private list of names is not set"
    assert row["failures"] == [
        {"test": "tokens", "file": ".github/workflows/ci.yml", "line": None, "message": check.NO_NAMES}
    ]


@pytest.mark.parametrize(
    "shell", [{}, {"CHECK_EXTRA_TOKENS": "optional"}, {"CHECK_EXTRA_TOKENS": "optional", "EXTRA_TOKENS": ""}]
)
def test_a_run_without_secrets_goes_on_with_the_committed_lists_and_says_so(tmp_path, shell):
    tree = _guarded(tmp_path)
    done = _check(tree, "--only", "tokens", "--json", **shell)
    assert done.returncode == 0 and "file=none" in done.stdout
    assert "the private list of names is not set here (EXTRA_TOKENS)" in done.stdout
    assert _row(tree)["summary"] == "no forbidden name in the scanned tree"


def test_a_local_file_named_by_the_contributor_is_used_as_it_is(tmp_path):
    tree = _guarded(tmp_path)
    own = tmp_path / "mine.txt"
    own.write_text("a name\n", encoding="utf-8")
    done = _check(
        tree,
        "--only",
        "tokens",
        "--json",
        COCKPIT_EXTRA_TOKENS=str(own),
        EXTRA_TOKENS="other",
        CHECK_EXTRA_TOKENS="required",
    )
    assert done.returncode == 0 and f"file={own} " in done.stdout and "lines=1" in done.stdout and own.exists()
    assert _row(tree)["summary"].endswith("with the private list")


def test_ci_hands_the_secret_to_the_one_command_and_requires_it_on_a_push_to_the_default_branch():
    with open(os.path.join(ROOT, ".github", "workflows", "ci.yml"), encoding="utf-8") as handle:
        steps = yaml.safe_load(handle)["jobs"]["test"]["steps"]
    env = [step for step in steps if step.get("run") == "scripts/check --json"][0]["env"]
    assert env["EXTRA_TOKENS"] == "${{ secrets.EXTRA_TOKENS }}"
    assert env["CHECK_EXTRA_TOKENS"] == (
        "${{ github.event_name == 'push' && github.ref_name == github.event.repository.default_branch "
        "&& 'required' || 'optional' }}"
    )
    # no other step sees the secret
    assert [
        step for step in steps if "EXTRA_TOKENS" in json.dumps(step) and step.get("run") != "scripts/check --json"
    ] == []
