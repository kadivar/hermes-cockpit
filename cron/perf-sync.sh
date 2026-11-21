#!/bin/sh
# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
exec "$(CDPATH= cd -- "$(dirname "$0")" && pwd)/run" perf
