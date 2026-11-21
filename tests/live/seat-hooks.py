# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
import os
import sys

sys.path.insert(0, os.environ.get("HERMES_AGENT") or os.path.expanduser("~/.hermes/hermes-agent"))
from hermes_cli.plugins import discover_plugins, get_plugin_manager

discover_plugins(force=True)
manager = get_plugin_manager()
mine = []
for event, hooks in manager._hooks.items():
    for hook in hooks:
        code = getattr(hook, "__code__", None)
        if code and "plugins/cockpit" in code.co_filename:
            mine.append(f"{event}:{hook.__name__}")
print(os.path.basename(os.environ["HERMES_HOME"]), "cockpit register() hooks:", sorted(mine))
