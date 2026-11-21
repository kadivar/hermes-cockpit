# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Web dashboard API. Hermes loads this file by path, so the plugin root goes on sys.path here."""

import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)
_KERNEL = os.path.join(_ROOT, "kernel")
if _KERNEL not in sys.path:
    sys.path.insert(0, _KERNEL)

from dashboard.cockpit.router import router  # noqa: E402, F401 the name Hermes mounts; the path above comes first
