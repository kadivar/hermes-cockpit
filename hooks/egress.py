#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""pre_tool_call hook. Unreadable input blocks. A match exits 2 and names the reason as the message."""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
from _boot import boot  # noqa: E402

boot(__file__)


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except Exception:  # noqa: BLE001 - an unreadable tool call is blocked
        print(json.dumps({"action": "block", "message": "unreadable tool call", "reason": "unreadable tool call"}))
        return 2
    tool_input = payload.get("tool_input") or payload.get("args") or {}
    name = str(payload.get("tool") or payload.get("tool_name") or "")
    from cockpitlib.egress import DELEGATE_TOOLS

    if name in DELEGATE_TOOLS:
        from cockpitlib.egress import check_delegate

        request = tool_input if isinstance(tool_input, dict) else {}
        reason = check_delegate(request)
        if reason:
            print(json.dumps({"action": "block", "message": reason, "reason": reason}))
            return 2
        return 0
    from cockpitlib.egress import check_tool, explained

    reason = check_tool(name, tool_input, payload=payload)  # the payload names the running card
    if reason:
        message = explained(reason)
        print(json.dumps({"action": "block", "message": message, "reason": message}))
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
