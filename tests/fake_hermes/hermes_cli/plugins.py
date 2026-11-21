# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The recorded plugin hook surface (tests/contract/hermes-hooks.json): the hook names and the pre_tool_call dispatch.
COCKPIT_STUB_HOOKS, a comma list, stands for a Hermes that changed one of them: `no-event` (transform_terminal_output is
gone), `drop-kwarg` (tool_call_id is no longer sent), `no-block` (a block is ignored), `renamed` (the dispatch function is
gone)."""

import os

_CHANGED = os.environ.get("COCKPIT_STUB_HOOKS", "").split(",")

VALID_HOOKS = {
    "pre_tool_call",
    "post_tool_call",
    "transform_terminal_output",
    "transform_tool_result",
    "pre_llm_call",
    "post_llm_call",
}
if "no-event" in _CHANGED:
    VALID_HOOKS.discard("transform_terminal_output")


def get_pre_tool_call_directive(
    tool_name, args, task_id="", session_id="", tool_call_id="", turn_id="", api_request_id="", middleware_trace=None
):
    """(directive, message): "block" with its message when a hook vetoes the call; a block without a message is ignored."""
    from hermes_cli.lifecycle import invoke_hook

    payload = {
        "tool_name": tool_name,
        "args": args if isinstance(args, dict) else {},
        "task_id": task_id,
        "session_id": session_id,
        "tool_call_id": tool_call_id,
        "turn_id": turn_id,
        "api_request_id": api_request_id,
        "middleware_trace": list(middleware_trace or []),
    }
    if "drop-kwarg" in _CHANGED:
        payload.pop("tool_call_id")
    for result in invoke_hook("pre_tool_call", **payload):
        message = result.get("message") if isinstance(result, dict) else None
        if (
            isinstance(result, dict)
            and result.get("action") == "block"
            and isinstance(message, str)
            and message
            and "no-block" not in _CHANGED
        ):
            return ("block", message)
    return (None, None)


if "renamed" in _CHANGED:
    del get_pre_tool_call_directive
