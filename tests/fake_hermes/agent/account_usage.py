# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""fetch_account_usage(provider, read_only=) from $COCKPIT_ROOT/fake-usage.json: {provider: {windows: [...], unavailable, raise}}."""

import datetime
import json
import os
from dataclasses import dataclass, field


@dataclass(frozen=True)
class AccountUsageWindow:
    label: str
    used_percent: float = None
    reset_at: datetime.datetime = None
    detail: str = None
    scope: str = "account"


@dataclass(frozen=True)
class AccountUsageSnapshot:
    provider: str
    source: str
    fetched_at: datetime.datetime
    windows: tuple = field(default_factory=tuple)
    unavailable_reason: str = None


def fetch_account_usage(provider, *, base_url=None, api_key=None, read_only=False, identity_id=None):
    path = os.path.join(os.environ.get("COCKPIT_ROOT", ""), "fake-usage.json")
    data = json.load(open(path, encoding="utf-8")) if os.path.isfile(path) else {}
    entry = data.get(provider)
    if entry is None:
        return None
    if entry.get("raise"):
        raise RuntimeError(entry["raise"])
    windows = tuple(
        AccountUsageWindow(
            label=row["label"],
            used_percent=row.get("used_percent"),
            scope=row.get("scope", "account"),
            reset_at=datetime.datetime.fromisoformat(row["resets_at"]) if row.get("resets_at") else None,
        )
        for row in entry.get("windows") or []
    )
    return AccountUsageSnapshot(
        provider=provider,
        source="fake",
        fetched_at=datetime.datetime.now(datetime.UTC),
        windows=windows,
        unavailable_reason=entry.get("unavailable"),
    )
