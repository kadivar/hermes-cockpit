# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Errors the CLI prints. exit_code is the process status."""


class CockpitError(Exception):
    exit_code = 1


class PackError(CockpitError):
    exit_code = 2


class NeedMigrate(CockpitError):
    exit_code = 2

    def __init__(self):
        super().__init__(
            'no workspace is bound: run "cockpit init" (replacing an older pipeline: skill cockpit-migrate)'
        )


class Conflict(CockpitError):
    """The act is refused because the board or the slot is in another state."""

    exit_code = 409


class UsageError(CockpitError):
    """A command or an intent named wrongly: the message carries an example of the right form."""

    exit_code = 2
