# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The recorded hook payload schema. COCKPIT_STUB_HOOKS=schema stands for a Hermes that moved to another one."""

import os

OBSERVER_SCHEMA_VERSION = (
    "hermes.observer.v2" if "schema" in os.environ.get("COCKPIT_STUB_HOOKS", "").split(",") else "hermes.observer.v1"
)
