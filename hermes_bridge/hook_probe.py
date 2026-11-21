# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""What this Hermes offers a plugin's hooks, asked from inside Hermes's environment (see cockpitlib.hermes_runtime), for doctor
to compare with the recorded contract when Hermes is newer than the versions cockpit was checked against. It reads
Hermes's modules and writes nothing: no plugin is discovered, no hook registered, no file touched. The one call it makes
is Hermes's own pre_tool_call dispatch with a recorder in place of the plugin hooks, in this process only, to see which
keywords the dispatch sends and whether a block is honoured.
stdin: ignored. stdout: {"hooks": [...], "telemetry_schema_version": str, "pre_tool_call": {"event", "kwargs", "block"},
"shell_hook": {"block"}, "errors": {part: why}}. A part that could not be asked is in errors, never guessed.
"""

import json

WORD = "cockpit hook probe"


def _hooks():
    from hermes_cli.plugins import VALID_HOOKS

    return sorted(str(name) for name in VALID_HOOKS)


def _schema():
    from hermes_cli.middleware import OBSERVER_SCHEMA_VERSION

    return str(OBSERVER_SCHEMA_VERSION)


def _pre_tool_call():
    """The dispatch a tool call goes through, with the plugin hooks replaced by a recorder that blocks."""
    from hermes_cli import lifecycle, plugins

    seen = {}

    def recorder(hook_name, **kwargs):
        seen["event"] = str(hook_name)
        seen["kwargs"] = sorted(kwargs)
        return [{"action": "block", "message": WORD}]

    real = lifecycle.invoke_hook
    lifecycle.invoke_hook = recorder
    try:
        answer = plugins.get_pre_tool_call_directive("terminal", {"command": "true"})
    finally:
        lifecycle.invoke_hook = real
    return {"event": seen.get("event", ""), "kwargs": seen.get("kwargs", []), "block": tuple(answer) == ("block", WORD)}


def _shell_hook():
    """A shell hook's stdout as Hermes reads it: both spellings of a block, each with its text."""
    from agent.shell_hooks import _parse_response

    want = {"action": "block", "message": WORD}
    ours = _parse_response("pre_tool_call", json.dumps({"action": "block", "message": WORD, "reason": WORD}))
    other = _parse_response("pre_tool_call", json.dumps({"decision": "block", "reason": WORD}))
    return {"block": ours == want and other == want}


PARTS = {
    "hooks": _hooks,
    "telemetry_schema_version": _schema,
    "pre_tool_call": _pre_tool_call,
    "shell_hook": _shell_hook,
}


def main() -> int:
    found = {"errors": {}}
    for name, ask in PARTS.items():
        try:
            found[name] = ask()
        except Exception as exc:  # noqa: BLE001 - the part is reported as not answered; doctor then keeps the version unaccepted
            found["errors"][name] = f"{type(exc).__name__}: {exc}"[:200]
    print(json.dumps(found))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
