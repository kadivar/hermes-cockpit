# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The recorded hook dispatch entry: plugin hooks are invoked by name with keywords. No plugin is loaded here."""


def invoke_hook(hook_name, **kwargs):
    return []
