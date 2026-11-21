# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Read-only forge helper. Writes live in publish."""

import json
import subprocess


class ForgeError(Exception):
    pass


def run_json(argv, runner=None):
    if runner is not None:
        result = runner(argv)
    else:
        try:
            result = subprocess.run(argv, capture_output=True, text=True, check=False, timeout=8)
        except subprocess.TimeoutExpired as exc:
            raise ForgeError("timeout") from exc
        except OSError as exc:  # no `gh` on this PATH (Hermes cron runs with a bare one): the forge is unreachable, a watcher records that and goes on
            raise ForgeError(f"{argv[0]}: {exc.strerror or exc}") from exc
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        raise ForgeError(detail or f"exit {result.returncode}")
    if not result.stdout:
        return None
    return json.loads(result.stdout)
