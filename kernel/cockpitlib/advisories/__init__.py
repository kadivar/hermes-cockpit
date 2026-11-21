# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The stack advisory watch: what the pack's shipped repos build and run (manifest), public advisory sources (sources),
matching and state (match), and the scan that writes the platform's advisories.json (scan). A component format is one
entry in manifest.READERS; a source is one entry in sources.REGISTRY."""

import os

from ..paths import platform_dir


def state_path() -> str:
    """Written whole by every scan; a record, not committed."""
    return os.path.join(platform_dir(), "advisories.json")


def manifest_path() -> str:
    return os.path.join(platform_dir(), "stack-manifest.json")


def acks_path() -> str:
    """The human's acknowledgements, {id: {time, note}}: kept with the platform records."""
    return os.path.join(platform_dir(), "advisories-acks.json")


def cache_dir() -> str:
    return os.path.join(platform_dir(), "advisories-cache")
