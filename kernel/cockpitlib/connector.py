# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Hermes's hosted connectors (Nous Portal holds the app's grant), called from cockpit.

Cockpit runs on its own interpreter, which does not carry Hermes's dependencies, so a call runs as a short child on
Hermes's interpreter: the same bootstrap Hermes's own spawned helpers use (the checkout on the path, hermes_bootstrap
first), then the connector dispatch an agent's tool call goes through. No credential is read or held here; the
child's answer is the connector's reply.

Which interpreter: COCKPIT_HERMES_PYTHON and COCKPIT_HERMES_ROOT when set; otherwise what cockpit's Hermes plugin
recorded the last time Hermes loaded it (hermes-runtime.json in the Hermes home); otherwise Hermes's standard layout.
"""

import glob
import json
import os
import subprocess
import sys

from .errors import CockpitError
from .store import dump_json

RUNTIME_FILE = os.path.join("cockpit", "hermes-runtime.json")
# Run with -c, not as a file: a script's own folder goes first on sys.path, and cockpit's module names would then
# shadow Hermes's top-level ones.
CHILD = """
import json, sys
sys.path.insert(0, sys.argv[1])
try:
    import hermes_bootstrap  # noqa: F401  selects Hermes's environment; must come first
except ModuleNotFoundError as exc:
    if exc.name != "hermes_bootstrap":
        raise
from tools.connectors.dispatch import dispatch_connector_call
request = json.load(sys.stdin)
sys.stdout.write(dispatch_connector_call(request["tool"], request.get("arguments") or {}, request.get("id") or "cockpit"))
"""


def _home() -> str:
    from .paths import hermes_home

    return hermes_home()


def record_runtime() -> None:
    """Called where Hermes loads cockpit: remember the interpreter and checkout a cockpit process outside Hermes
    (a cron job, the CLI) runs connector calls on. Written only when it changed; never raises."""
    try:
        import hermes_bootstrap  # noqa: F401

        root = os.path.dirname(os.path.abspath(sys.modules["hermes_bootstrap"].__file__))
    except Exception:  # noqa: BLE001 - no Hermes to look in: nothing to record
        return
    try:
        path = os.path.join(_home(), RUNTIME_FILE)
        found = {"python": sys.executable, "root": root}
        try:
            if json.load(open(path, encoding="utf-8")) == found:
                return
        except (OSError, ValueError):
            pass
        os.makedirs(os.path.dirname(path), exist_ok=True)
        dump_json(path, found)
    except Exception:  # noqa: BLE001 - the record is advisory: a failed write is no error
        return


def runtime() -> tuple:
    """(python, root) to run a connector call on, or raise saying how to point cockpit at Hermes."""
    python, root = os.environ.get("COCKPIT_HERMES_PYTHON") or "", os.environ.get("COCKPIT_HERMES_ROOT") or ""
    if not (python and root):
        try:
            found = json.load(open(os.path.join(_home(), RUNTIME_FILE), encoding="utf-8"))
            python, root = python or found.get("python") or "", root or found.get("root") or ""
        except (OSError, ValueError):
            pass
    if not (python and root):
        base = _home()
        root = root or os.path.join(base, "hermes-agent")
        bundled = sorted(glob.glob(os.path.join(base, "tools", "python-*", "bin", "python3")))
        python = python or (bundled[-1] if bundled else "")
    if not (python and os.path.exists(python) and os.path.isfile(os.path.join(root, "hermes_bootstrap.py"))):
        raise CockpitError(
            "cockpit cannot find Hermes to call its connectors: start Hermes once (cockpit records it), "
            "or set COCKPIT_HERMES_PYTHON and COCKPIT_HERMES_ROOT"
        )
    return python, root


def call(connector: str, tool: str, arguments: dict, timeout: int = 180):
    """The connector operation's data (Jira's own answer, for Jira), or CockpitError in the connector's words."""
    python, root = runtime()
    request = {"tool": f"connectors__{connector}__{tool}", "arguments": arguments, "id": f"cockpit-{tool.lower()}"}
    try:
        done = subprocess.run(
            [python, "-I", "-c", CHILD, root],
            input=json.dumps(request),
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise CockpitError(f"the Hermes {connector} connector ({tool}): {exc}") from exc
    if done.returncode != 0:
        raise CockpitError(f"the Hermes {connector} connector ({tool}): {(done.stderr or done.stdout).strip()[-300:]}")
    try:
        answer = json.loads(done.stdout.strip().splitlines()[-1]) if done.stdout.strip() else {}
    except ValueError as exc:
        raise CockpitError(f"the Hermes {connector} connector ({tool}): its answer is not JSON") from exc
    return answer_data(connector, tool, answer)


def answer_data(connector: str, tool: str, answer: dict):
    """What the operation returned, or why not. Not connected says how to connect."""
    error = answer.get("error") if isinstance(answer, dict) else None
    if error:
        code = str((error or {}).get("code") or "") if isinstance(error, dict) else ""
        message = str((error or {}).get("message") or error) if isinstance(error, dict) else str(error)
        if code in ("CONNECTION_REQUIRED", "NOT_CONNECTED", "ACCOUNT_REQUIRED") or "connect" in code.lower():
            raise CockpitError(
                f"the Hermes {connector} connector is not connected: run `hermes connectors connect {connector}`"
            )
        raise CockpitError(f"the Hermes {connector} connector ({tool}): {message}" + (f" [{code}]" if code else ""))
    response = (answer or {}).get("response") if isinstance(answer, dict) else None
    if not isinstance(response, dict):
        raise CockpitError(f"the Hermes {connector} connector ({tool}) gave no response")
    if response.get("successful") is False:
        raise CockpitError(f"the Hermes {connector} connector ({tool}): {response.get('error') or 'the call failed'}")
    return response.get("data")
