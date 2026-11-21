# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Whether the installed Hermes still offers the hook shapes cockpit was checked against (tests/contract/hermes-hooks.json),
asked live from inside Hermes's own interpreter. Doctor uses it for a Hermes newer than the verified versions: the egress
hook rides on these shapes, so the answer is empty only when every compared shape matched, and a probe that cannot run
(no contract file, no runtime command, a helper that fails, is slow or answers something else) is a reason too."""

import json
import os
import subprocess

from .errors import CockpitError

PROBE_TIMEOUT = 30
CONTRACT = ("tests", "contract", "hermes-hooks.json")
SENT_LATER = ("telemetry_schema_version",)  # added by Hermes's dispatch after the point the probe records at


def contract_path() -> str:
    from .paths import PLUGIN_ROOT

    return os.path.join(PLUGIN_ROOT, *CONTRACT)


def _contract() -> dict:
    """The recorded shapes, or an empty dict when the file is missing or not what the probe compares against."""
    try:
        data = json.load(open(contract_path(), encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    events = data.get("events") if isinstance(data, dict) else None
    pre = events.get("pre_tool_call") if isinstance(events, dict) else None
    if (
        not isinstance(pre, dict)
        or not isinstance(pre.get("kwargs"), list)
        or not pre["kwargs"]
        or not isinstance(data.get("telemetry_schema_version"), str)
    ):
        return {}
    return data


def _offered() -> dict:
    """What the helper inside Hermes answered. Raises CockpitError when it could not be asked."""
    from .hermes_runtime import HELPERS, runtime_argv
    from .paths import hermes_home

    try:
        argv = runtime_argv(os.path.join(HELPERS, "hook_probe.py"))
        done = subprocess.run(
            argv,
            input="{}",
            capture_output=True,
            text=True,
            timeout=PROBE_TIMEOUT,
            env={**os.environ, "HERMES_HOME": hermes_home()},
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise CockpitError(f"no answer within {PROBE_TIMEOUT} s") from exc
    except OSError as exc:
        raise CockpitError(str(exc)[:160]) from exc
    if done.returncode != 0:
        raise CockpitError(
            ((done.stderr or done.stdout or "").strip().splitlines() or [f"exit {done.returncode}"])[-1][-160:]
        )
    try:
        found = json.loads(done.stdout)
    except ValueError as exc:
        raise CockpitError("the helper answered no JSON") from exc
    if not isinstance(found, dict):
        raise CockpitError("the helper answered no JSON object")
    return found


def differences(contract: dict, offered: dict) -> list:
    """Each recorded shape the offered ones do not meet. A part the helper did not answer is a difference."""
    found = (
        [f"{part} could not be read ({why})" for part, why in sorted((offered.get("errors") or {}).items())]
        if isinstance(offered.get("errors"), dict)
        else ["the helper's errors could not be read"]
    )
    hooks = offered.get("hooks") if isinstance(offered.get("hooks"), list) else []
    found += [f"{event} is not a hook this Hermes offers" for event in contract["events"] if event not in hooks]
    if offered.get("telemetry_schema_version") != contract["telemetry_schema_version"]:
        found.append(
            f"the hook payload schema is {offered.get('telemetry_schema_version')!r}, not {contract['telemetry_schema_version']!r}"
        )
    pre = offered.get("pre_tool_call") if isinstance(offered.get("pre_tool_call"), dict) else {}
    sent = pre.get("kwargs") if isinstance(pre.get("kwargs"), list) else []
    if pre.get("event") != "pre_tool_call":
        found.append("a tool call is not dispatched to pre_tool_call")
    gone = [key for key in contract["events"]["pre_tool_call"]["kwargs"] if key not in SENT_LATER and key not in sent]
    if gone:
        found.append("pre_tool_call no longer sends " + ", ".join(gone))
    if pre.get("block") is not True:
        found.append("a pre_tool_call block with a message is not honoured")
    shell = offered.get("shell_hook") if isinstance(offered.get("shell_hook"), dict) else {}
    if shell.get("block") is not True:
        found.append("a shell hook's block is not honoured")
    return found


def probe() -> str:
    """Empty when the installed Hermes met every recorded hook shape the probe compares; else why it did not, or why the
    probe could not run. It never raises: a caller reads any text as "not accepted"."""
    contract = _contract()
    if not contract:
        return f"the recorded hook contract ({contract_path()}) is missing or unreadable, so there is nothing to compare with"
    try:
        offered = _offered()
    except CockpitError as exc:
        return f"the probe could not run: {exc}"
    return "; ".join(differences(contract, offered))
