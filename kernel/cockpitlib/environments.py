# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Where a test runs. The pack's `environments: [{name, origins, slot}]`, else two neutral ones: `local` (a slot of
this machine) and `staging` (the origins in staging.yaml, no slot)."""

import os

from .errors import CockpitError


def environments(pack) -> list:
    listed = (pack or {}).get("environments")
    if listed:
        return [
            {"name": item["name"], "origins": dict(item.get("origins") or {}), "slot": bool(item.get("slot", False))}
            for item in listed
        ]
    from . import pack_local

    path = os.path.join((pack or {}).get("_dir") or "", "staging.yaml")
    staging = {}
    if os.path.isfile(path):
        staging = (pack_local.read(path) or {}).get("origins") or {}
    return [
        {"name": "local", "origins": {}, "slot": True},
        {"name": "staging", "origins": dict(staging), "slot": False},
    ]


def pick(pack, name: str = "") -> dict:
    """The named environment; the first one when none is named."""
    found = environments(pack)
    if not name:
        return found[0]
    for item in found:
        if item["name"] == name:
            return item
    raise CockpitError(f"no environment {name}: the pack has {', '.join(item['name'] for item in found)}")


def lines(environment: dict) -> str:
    text = (
        f"Environment: {environment['name']}"
        + (" (a slot of this machine)" if environment["slot"] else " (no slot)")
        + "\n"
    )
    for key, value in sorted(environment["origins"].items()):
        text += f"Origin {key}: {value}\n"
    return text
