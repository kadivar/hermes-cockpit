# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Hermes plugin entry. Registers the bundled migrate skill and the egress hook."""

import os
import sys

_ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_ROOT, "kernel"))


def register(ctx):
    root = _ROOT
    # A cockpit process outside Hermes (a cron job, the CLI) calls Hermes's connectors on Hermes's interpreter.
    try:
        from cockpitlib.connector import record_runtime

        record_runtime()
    except Exception:  # noqa: BLE001, S110 - the record of the runtime is advisory: the load goes on without it
        pass
    for name in ("outbox", "cockpit-ops", "cockpit-migrate", "platform-map"):
        ctx.register_skill(name, os.path.join(root, "skills", name, "SKILL.md"))

    # Hermes calls hooks by keyword (tool_name=, args=, ...) and keeps a block only when it carries a message.
    def on_tool(tool_name=None, args=None, **_kwargs):
        from cockpitlib.egress import DELEGATE_TOOLS, check_delegate, check_tool, explained

        if tool_name in DELEGATE_TOOLS:
            reason = check_delegate(args if isinstance(args, dict) else {})
            if reason:
                return {"action": "block", "message": reason}
            return None
        reason = check_tool(tool_name or "", args, payload=_kwargs)  # the keywords may name the running card
        if reason:
            return {"action": "block", "message": explained(reason)}
        return None

    def _scrubbed(text):
        from cockpitlib.vault import scrub_result

        if not isinstance(text, str) or not text:
            return None
        cleaned = scrub_result(text)
        if cleaned == text:
            return None
        return cleaned

    def on_result(result=None, tool_name=None, args=None, **_kwargs):
        if tool_name == "skill_view":
            # Recording never changes or breaks the result the lane sees.
            try:
                from cockpitlib.skill_log import record_view

                record_view(args, result)
            except Exception:  # noqa: BLE001, S110 - the view record is advisory: the tool's result is returned either way
                pass
        return _scrubbed(result)

    def on_terminal(output=None, **_kwargs):
        return _scrubbed(output)

    ctx.register_hook("transform_tool_result", on_result)
    ctx.register_hook("transform_terminal_output", on_terminal)
    ctx.register_hook("pre_tool_call", on_tool)
