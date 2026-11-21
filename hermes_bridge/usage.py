# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Provider plan windows through Hermes's own usage readers.

Runs inside Hermes's environment (see cockpitlib.hermes_runtime): the standard library and Hermes's modules, never cockpitlib.
stdin: {"providers": [slug, ...]}. stdout: {"results": [{"provider", "windows": [...], "unavailable"}]}, in order.
A read-only fetch: it never rotates, refreshes or benches a credential.
"""

import json
import sys

from agent.account_usage import fetch_account_usage


def _read(provider):
    try:
        snapshot = fetch_account_usage(provider, read_only=True)
    except Exception as exc:  # noqa: BLE001 - one provider's reader failing leaves the others
        return {"provider": provider, "windows": [], "unavailable": str(exc)[:200]}
    if snapshot is None:
        return {"provider": provider, "windows": [], "unavailable": "no usage reader"}
    windows = [
        {
            "label": window.label,
            "used_percent": float(window.used_percent),
            "resets_at": window.reset_at.isoformat() if window.reset_at else None,
            "scope": window.scope,
        }
        for window in snapshot.windows
        if window.used_percent is not None
    ]
    return {"provider": provider, "windows": windows, "unavailable": snapshot.unavailable_reason or ""}


def main() -> int:
    request = json.load(sys.stdin)
    print(json.dumps({"results": [_read(str(name)) for name in request.get("providers") or []]}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
