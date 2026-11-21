# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Named prompts: cockpit's own under prompts/, and the pack's `prompts: {name: path}` over them. `{{prompt:name}}` in a
soul or a card text is replaced by that prompt's text."""

import os
import re

from .errors import CockpitError

PLACEHOLDER = re.compile(r"\{\{prompt:([a-z0-9][a-z0-9_-]*)\}\}")


def _kernel(name: str) -> str:
    from .paths import PLUGIN_ROOT

    return os.path.join(PLUGIN_ROOT, "prompts", f"{name}.md")


def path_of(pack, name: str) -> str:
    """The file a prompt name reads: the pack's, else cockpit's. Empty when neither has it."""
    listed = ((pack or {}).get("prompts") or {}).get(name)
    if listed:
        return listed
    own = _kernel(name)
    return own if os.path.isfile(own) else ""


def resolve(pack, text: str) -> str:
    """Every placeholder replaced; a name no prompt answers is refused, naming it."""

    def fill(match):
        path = path_of(pack, match.group(1))
        if not path or not os.path.isfile(path):
            raise CockpitError(f"no prompt {match.group(1)}: name it under prompts in pack.yaml")
        return open(path, encoding="utf-8").read().strip()

    return PLACEHOLDER.sub(fill, text or "")


def problems(pack) -> list:
    """Doctor: each prompt the pack names must exist."""
    return [
        f"prompt {name} missing: {path}"
        for name, path in sorted(((pack or {}).get("prompts") or {}).items())
        if not os.path.isfile(path)
    ]
