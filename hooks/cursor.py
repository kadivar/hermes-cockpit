#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Cursor preToolUse hook: the egress fence for a lane whose model runs Cursor's own agent (a cursor-agent seat).

Hermes never sees that agent's tool calls, so its pre_tool_call hook cannot fence them; Cursor hands each one to this
hook instead. A call outside a cockpit lane (no COCKPIT_LANE: a person's own Cursor session) is allowed untouched. In a
lane, unreadable input and any failure of the fence itself are refused.
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
try:
    from _boot import boot

    boot(__file__)
    BOOT_ERROR = ""
except Exception as exc:  # noqa: BLE001 - judged in main(): a lane is refused, a person's own call goes through
    BOOT_ERROR = f"{type(exc).__name__}: {exc}"

# Cursor's tool names, as its preToolUse payload gives them, mapped to the Hermes names the fence knows.
NAMES = {
    "Shell": "terminal",
    "Write": "write_file",
    "Edit": "write_file",
    "StrReplace": "write_file",
    "MultiEdit": "write_file",
    "Delete": "write_file",
    "EditNotebook": "write_file",
    "ApplyPatch": "apply_patch",
    "Read": "read_file",
    "Grep": "grep",
    "Glob": "glob",
    "LS": "list",
}


def hermes_call(name: str, tool_input):
    """(Hermes tool name, its input) for one Cursor call. An MCP call names only its tool, so its server is `cursor`."""
    tool_input = tool_input if isinstance(tool_input, dict) else {}
    if name.startswith("MCP:"):
        return f"mcp__cursor__{name[4:]}", tool_input
    mapped = NAMES.get(name, name)
    if mapped == "write_file" and "content" in tool_input and "contents" not in tool_input:
        tool_input = {**tool_input, "contents": tool_input["content"]}
    return mapped, tool_input


def _answer(verdict: str, message: str = "") -> int:
    out = {"permission": verdict}
    if message:
        out.update({"user_message": message, "agent_message": message, "message": message})
    print(json.dumps(out))
    return 0


def _verdict(payload) -> tuple:
    name, tool_input = hermes_call(str(payload.get("tool_name") or ""), payload.get("tool_input"))
    # Relative paths and `cd` resolve where the agent stands: the call's cwd, else the card workspace.
    roots = payload.get("workspace_roots") or []
    here = tool_input.get("cwd") or payload.get("cwd") or (roots[0] if roots else "")
    if here and os.path.isdir(here):
        os.chdir(here)
    from cockpitlib.egress import check_tool, explained

    reason = check_tool(name, tool_input)
    return ("deny", explained(reason)) if reason else ("allow", "")


def main() -> int:
    """Cursor lets a call through when its hook crashes, so in a lane every failure here is a refusal instead."""
    lane = os.environ.get("COCKPIT_LANE")
    try:  # read it all first: Cursor is still writing a large Write payload
        payload = json.load(sys.stdin)
    except Exception:  # noqa: BLE001 - an unreadable payload is judged below as none
        payload = None
    if not lane:
        return _answer("allow")
    if BOOT_ERROR:
        return _answer("deny", f"cockpit's fence could not start ({BOOT_ERROR})")
    if payload is None:
        return _answer("deny", "unreadable tool call")
    try:
        return _answer(*_verdict(payload if isinstance(payload, dict) else {}))
    except Exception as exc:  # noqa: BLE001 - whatever went wrong in the fence, the call is denied
        return _answer("deny", f"cockpit's fence failed on this call ({type(exc).__name__}: {exc})")


if __name__ == "__main__":
    raise SystemExit(main())
