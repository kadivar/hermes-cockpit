# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""What the human runs after an update, as one line for their shell: the plugin's own launcher resolved for this machine
(a bare `cockpit` is on nobody's PATH by default), the seats re-rendered on the new kernel, doctor, and the Desktop started
again when its UI changed. One line, the steps joined with &&, so a copy and a paste do it all and stop at the first
failure. The same shape serves the Settings page, the Inbox row and `cockpit update apply`."""

import os
import shlex
import shutil
import sys


def _os_name() -> str:
    return os.name


def _platform() -> str:
    return sys.platform


def quote(path) -> str:
    """A path as the shell of this machine takes it: double quotes on Windows, POSIX quoting elsewhere."""
    return f'"{path}"' if _os_name() == "nt" else shlex.quote(str(path))


def launcher(name: str = "cockpit", root: str = "") -> str:
    """The command that runs this plugin's `bin/<name>` here: the link `cockpit setup` made under the Hermes home's bin
    when it exists, else the checkout's own script; on Windows the script through the checkout's venv python, else `py -3`."""
    from .paths import PLUGIN_ROOT, hermes_home

    root = root or PLUGIN_ROOT
    script = os.path.join(root, "bin", name)
    if _os_name() == "nt":
        python = os.path.join(root, ".venv", "Scripts", "python.exe")
        return (quote(python) if os.path.isfile(python) else "py -3") + " " + quote(script)
    link = os.path.join(hermes_home(), "bin", name)
    return quote(link if os.path.exists(link) else script)


def hermes_command() -> str:
    """Hermes's own command, where PATH finds it, else the bare name."""
    found = shutil.which("hermes")
    return quote(found) if found else "hermes"


def desktop_restart() -> dict:
    """The Desktop quit and started again where a command can do it (macOS); elsewhere a reminder that prints last, so
    the line still ends on what is left to do by hand."""
    if _platform() == "darwin":
        return {
            "what": "restart the Desktop",
            "command": "osascript -e 'quit app \"Hermes\"' && sleep 3 && open -a Hermes",
        }
    if _os_name() == "nt":
        return {"what": "restart the Desktop", "command": 'echo "now quit the Hermes Desktop and start it again"'}
    return {"what": "restart the Desktop", "command": "echo 'now quit the Hermes Desktop and start it again'"}


def steps(result: dict, root: str = "") -> list:
    """After `apply`: the gateway restart when the update could not ask for it, the seats re-rendered on the new kernel,
    doctor, and the Desktop when its UI changed. Nothing when nothing changed. [{what, command}] in the order to run."""
    if not (result or {}).get("changed"):
        return []
    cockpit = launcher("cockpit", root)
    found = []
    if result.get("restart") != "requested":
        found.append({"what": "restart the gateway", "command": f"{hermes_command()} gateway restart"})
    found.append({"what": "re-render the seats on the new kernel", "command": f"{cockpit} setup --rerender"})
    found.append({"what": "check the install", "command": f"{cockpit} doctor"})
    if result.get("desktop"):
        found.append(desktop_restart())
    return found


def after(result: dict, root: str = "") -> dict:
    """{steps, line}: the steps and the one line that runs them in order."""
    found = steps(result, root)
    return {"steps": found, "line": " && ".join(step["command"] for step in found)}
