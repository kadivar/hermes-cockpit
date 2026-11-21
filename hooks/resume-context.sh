#!/bin/sh
# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later

# First turn of a respawned card. Fail open. Tool output never enters the note.
root=$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)
input=$(cat || true)
printf '%s' "$input" | "$root/bin/cockpit" resume-context || true
exit 0
