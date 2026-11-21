# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Run a small helper inside Hermes's own environment.

Hermes publishes the command that starts its interpreter with its bootstrap (`hermes --print-runtime-command`).
Cockpit keeps its own interpreter and dependencies; a helper in the plugin's hermes_bridge/ uses only the standard library and
Hermes's modules, takes JSON on stdin, and answers JSON on stdout.
"""

import json
import os
import shutil
import subprocess

from .errors import CockpitError
from .paths import PLUGIN_ROOT, hermes_home

ENTRY = "__cockpit_entry__"
LITERAL = f"runpy.run_module('{ENTRY}', run_name='__main__', alter_sys=True)"
HELPERS = os.path.join(PLUGIN_ROOT, "hermes_bridge")
_published = {}


def runtime_argv(script: str) -> list:
    """Hermes's own launch command, running this script instead of a module."""
    hermes = shutil.which("hermes")
    if not hermes:
        raise CockpitError("hermes not found")
    base = _published.get(hermes)
    if base is None:
        done = subprocess.run(
            [hermes, "--print-runtime-command", "--module", ENTRY],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        try:
            base = json.loads(done.stdout)
        except json.JSONDecodeError:
            base = None
        if not isinstance(base, list) or not base or not isinstance(base[-1], str) or base[-1].count(LITERAL) != 1:
            raise CockpitError("hermes did not publish a runtime command")
        _published[hermes] = base
    argv = list(base)
    argv[-1] = argv[-1].replace(LITERAL, f"runpy.run_path({script!r}, run_name='__main__')")
    return argv


def run_helper(name: str, request: dict) -> dict:
    """One helper process for a batch of requests. A failed helper raises with its last words."""
    script = os.path.join(HELPERS, f"{name}.py")
    env = os.environ.copy()
    env["HERMES_HOME"] = hermes_home()
    done = subprocess.run(
        runtime_argv(script),
        input=json.dumps(request),
        capture_output=True,
        text=True,
        timeout=120,
        env=env,
        check=False,
    )
    if done.returncode != 0:
        detail = (done.stderr or done.stdout or "").strip()[-300:]
        raise CockpitError(f"hermes {name} helper failed: {detail}")
    try:
        return json.loads(done.stdout)
    except json.JSONDecodeError as exc:
        raise CockpitError(f"hermes {name} helper answered no JSON") from exc
