# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""scripts/test never falls back to one slow process by itself: without pytest and pytest-xdist it stops and names the
install command. TEST_WORKERS=0 is one process on purpose."""

import os
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _copy(tmp_path, python_body: str):
    """The script in a tree of its own, with a stand-in interpreter that records how it was called."""
    tree = tmp_path / "tree"
    (tree / "scripts").mkdir(parents=True)
    (tree / ".venv" / "bin").mkdir(parents=True)
    shutil.copy(os.path.join(ROOT, "scripts", "test"), tree / "scripts" / "test")
    fake = tree / ".venv" / "bin" / "python"
    fake.write_text("#!/usr/bin/env bash\n" + python_body, encoding="utf-8")
    fake.chmod(0o755)
    return tree


def _run(tree, workers=None, *args):
    env = {key: value for key, value in os.environ.items() if key != "TEST_WORKERS"}
    if workers is not None:
        env["TEST_WORKERS"] = workers
    return subprocess.run(
        ["bash", str(tree / "scripts" / "test"), *args], capture_output=True, text=True, env=env, check=False
    )


def test_without_the_test_tools_it_stops_and_names_the_install_command(tmp_path):
    tree = _copy(tmp_path, 'if [ "$1" = "-c" ]; then exit 1; fi\necho "ran: $*"\n')
    done = _run(tree)
    assert done.returncode == 2 and "ran:" not in done.stdout
    assert "uv venv .venv && uv pip install --python .venv/bin/python -e '.[test]'" in done.stderr
    one = _run(tree, "0", "tests/x.py")  # one process, asked for: no check, no -n
    assert one.returncode == 0 and one.stdout.strip() == "ran: -m pytest tests/x.py"


def test_with_the_test_tools_it_runs_on_workers_and_a_given_n_wins(tmp_path):
    tree = _copy(tmp_path, 'if [ "$1" = "-c" ]; then exit 0; fi\necho "ran: $*"\n')
    assert _run(tree).stdout.strip() == "ran: -m pytest -n 6 --dist worksteal"
    assert _run(tree, "8", "tests/x.py").stdout.strip() == "ran: -m pytest -n 8 --dist worksteal tests/x.py"
    assert _run(tree, "8", "-n", "2").stdout.strip() == "ran: -m pytest -n 2"
    assert sys.executable  # the real interpreter is not used by these runs
