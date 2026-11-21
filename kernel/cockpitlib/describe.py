# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""This kernel as data, for a tool that would otherwise read its source: the verbs with their flags, the intent types,
the kickoff modes and card kinds, the words a lane is told to write, the seat kinds. Every value is read from the table
the kernel itself runs on, so the description cannot drift from the behaviour. It reads no workspace and no pack: what a
pack or a plugin adds is not here. The top-level shape is pinned (tests/contract/describe.json)."""

import os


def _version() -> str:
    """The plugin's version as its manifest states it; empty when the manifest is unreadable."""
    import yaml

    from .paths import PLUGIN_ROOT

    try:
        with open(os.path.join(PLUGIN_ROOT, "plugin.yaml"), encoding="utf-8") as handle:
            data = yaml.safe_load(handle) or {}
    except (OSError, yaml.YAMLError):
        return ""
    return str(data.get("version") or "") if isinstance(data, dict) else ""


def verbs() -> dict:
    """Each command: the flags the command line accepts before the command runs (a self-parsed command checks its own, so
    its list is empty), whether it takes no argument at all, and one example that parses."""
    from .cli import COMMANDS, EXAMPLES, FLAGS, SELF_PARSED, ZERO_ARGS

    return {
        name: {
            "flags": sorted(FLAGS.get(name, ())),
            "zero_args": name in ZERO_ARGS,
            "self_parsed": name in SELF_PARSED,
            "example": EXAMPLES.get(name, ""),
        }
        for name in COMMANDS
    }


def marks() -> dict:
    """The words a lane writes that the kernel or the human reads back: the start of a block that asks for the privileged
    login, the start of a block on a 2FA step, the tester's review request (a pack may word its own: testflow.review_mark),
    and the block that closes a run without a failure video."""
    from .lend import MARK, TWO_FACTOR_MARK
    from .test_flow import NO_VIDEO_MARK, REVIEW_MARK

    return {
        "privileged_login": MARK,
        "two_factor": TWO_FACTOR_MARK,
        "review": REVIEW_MARK,
        "no_failure_video": NO_VIDEO_MARK,
    }


def describe() -> dict:
    """{api_version, api_min_supported, version, verbs, intent_types, kickoff_modes,
    card_kinds, marks, roles, seat_kinds}: cockpit's own, before any pack."""
    from . import plugin_api, registry
    from .intents import TYPES
    from .pack import ROLES

    return {
        "api_version": plugin_api.API_VERSION,
        "api_min_supported": plugin_api.API_MIN_SUPPORTED,
        "version": _version(),
        "verbs": verbs(),
        "intent_types": list(TYPES),
        "kickoff_modes": {name: dict(entry) for name, entry in registry.KICKOFF_MODES.items()},
        "card_kinds": {name: dict(entry) for name, entry in registry.CARD_KINDS.items()},
        "marks": marks(),
        "roles": list(ROLES),
        "seat_kinds": list(registry.ROLES),
    }
