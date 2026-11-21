# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The forge as it was first written: GitHub through the human's own `gh` login. It lives in `forges.github` now, one
implementation of the protocol in `forges.base`; the names this module had are still here for the code that imports them.
"""

from .forges.github import ADD_THREAD, GREEN, READY, RESOLVE, THREADS  # noqa: F401
from .forges.github import GitHubForge as Forge  # noqa: F401
