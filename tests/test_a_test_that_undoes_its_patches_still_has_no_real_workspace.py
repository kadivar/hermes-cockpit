# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The tests' sandbox belongs to the process, not to a fixture: undoing every monkeypatch never reaches the machine.

A test that called monkeypatch.undo() used to drop the fixtures' own environment with its patches, and the next kernel
call resolved the workspace this machine is bound to. tests/conftest.py now points the process at an empty Hermes home
when it is read and drops the binding a shell carries, so with everything undone there is no workspace at all.
"""

import os
import subprocess
import sys

import pytest

from cockpitlib import paths
from cockpitlib.errors import NeedMigrate
from tests import conftest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REAL = os.path.realpath(os.path.expanduser("~/.hermes"))


def _under(path: str, folder: str) -> bool:
    return os.path.realpath(path) == folder or os.path.realpath(path).startswith(folder + os.sep)


def test_with_every_patch_undone_the_kernel_finds_no_workspace_and_an_empty_home_of_the_run(env, monkeypatch):
    assert paths.workspace() == os.path.realpath(str(env["workspace"]))
    monkeypatch.undo()
    with pytest.raises(NeedMigrate):
        paths.workspace()
    home = paths.hermes_home()
    assert home == conftest._SANDBOX_HOME and not _under(home, REAL) and os.listdir(home) == []
    assert paths.load_binding() == {} and not os.path.exists(paths.binding_file())
    assert not any(
        os.environ.get(name) for name in ("COCKPIT_WORKSPACE", "COCKPIT_ROOT", "COCKPIT_PACK", "COCKPIT_LANE")
    )
    with pytest.raises(NeedMigrate):
        paths.outbox()


def test_a_process_a_test_starts_inherits_the_empty_home_even_with_every_patch_undone(monkeypatch):
    monkeypatch.undo()
    code = (
        f"import sys\nsys.path.insert(0, {os.path.join(ROOT, 'kernel')!r})\nfrom cockpitlib import paths\n"
        "print(paths.hermes_home())\ntry:\n    paths.workspace()\nexcept Exception as exc:\n    print(type(exc).__name__)\n"
    )
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True).stdout.split()
    assert out == [conftest._SANDBOX_HOME, "NeedMigrate"]


def test_each_test_still_gets_its_own_empty_home_inside_the_runs_temp_folders():
    home = paths.hermes_home()
    assert home != conftest._SANDBOX_HOME and not _under(home, REAL) and not conftest._inside(home, conftest._REAL_HOME)
    assert conftest._inside(conftest._SANDBOX_HOME, conftest._SANDBOX_HOME) and not conftest._inside(
        REAL, conftest._SANDBOX_HOME
    )
