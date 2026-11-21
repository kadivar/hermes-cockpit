# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The recorded reading of a shell hook's stdout for pre_tool_call: {action|decision: block} with message (or reason).
COCKPIT_STUB_HOOKS=shell stands for a Hermes that no longer reads a block there."""

import json
import os


def _parse_response(event, stdout):
    try:
        data = json.loads((stdout or "").strip() or "null")
    except ValueError:
        return None
    if (
        not isinstance(data, dict)
        or event != "pre_tool_call"
        or "shell" in os.environ.get("COCKPIT_STUB_HOOKS", "").split(",")
    ):
        return None
    for verb, first, second in (("action", "message", "reason"), ("decision", "reason", "message")):
        if data.get(verb) == "block":
            return {"action": "block", "message": data.get(first) or data.get(second) or "blocked"}
    return None
