# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
import os
import sys

sys.path.insert(0, os.environ.get("HERMES_AGENT") or os.path.expanduser("~/.hermes/hermes-agent"))
from hermes_cli.plugins import discover_plugins, get_plugin_manager, get_pre_tool_call_block_message

discover_plugins(force=True)
manager = get_plugin_manager()
manager._hooks["pre_tool_call"] = [
    cb
    for cb in manager._hooks.get("pre_tool_call", [])
    if "plugins/cockpit" in getattr(getattr(cb, "__code__", None), "co_filename", "")
]
for command in ("git status", "git push origin x", "curl https://" + os.environ["REFUSED"] + "/"):
    directive = get_pre_tool_call_block_message(
        "terminal", {"command": command}, task_id="t", session_id="s", tool_call_id="c"
    )
    print("PRETOOL", repr(command), "->", directive)
