# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""What every hook script does before it imports cockpitlib: a Python with PyYAML, a usual PATH, the kernel on sys.path."""

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))


def run_on_the_plugin_venv(script: str) -> None:
    """A host whose `python3` cannot run the kernel (no PyYAML, or older than 3.11) re-execs on the plugin's own venv when
    one exists beside it: `python3 -m venv .venv && .venv/bin/pip install -e .` in the plugin folder. Hermes cron starts
    with a bare PATH, so that python3 is the one this script finds first."""
    try:
        import yaml  # noqa: F401

        if sys.version_info >= (3, 11):  # noqa: UP036 - cron may start a python older than this package requires
            return
    except ImportError:
        pass
    venv = os.path.join(ROOT, ".venv", "bin", "python")
    if (
        os.path.exists(venv)
        and os.path.realpath(sys.executable) != os.path.realpath(venv)
        and not os.environ.get("COCKPIT_NO_VENV")
    ):
        os.execv(venv, [venv, os.path.realpath(script), *sys.argv[1:]])  # noqa: S606 - this script again under the checkout's interpreter: a fixed argv, no shell


def complete_a_bare_path() -> None:
    """Hermes cron and the shell hook start without a login PATH. git, gh, gpg and hermes may live in a directory that PATH lacks
    (Homebrew on macOS, ~/.local/bin, Hermes's own bin): add the usual ones that exist, after what PATH already has."""
    have = os.environ.get("PATH", "")
    parts = have.split(os.pathsep) if have else []
    home = os.path.expanduser("~")
    for extra in (
        "/usr/local/bin",
        "/opt/homebrew/bin",
        os.path.join(home, ".local", "bin"),
        os.path.join(home, ".hermes", "bin"),
        os.path.dirname(sys.executable),
    ):
        if extra and extra not in parts and os.path.isdir(extra):
            parts.append(extra)
    os.environ["PATH"] = os.pathsep.join(parts)


def boot(script: str) -> None:
    run_on_the_plugin_venv(script)
    complete_a_bare_path()
    kernel = os.path.join(ROOT, "kernel")
    if kernel not in sys.path:
        sys.path.insert(0, kernel)
