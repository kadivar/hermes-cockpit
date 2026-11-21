# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The coding tool subscription's own usage windows (the 5-hour session and the weeks), read without the coding tool.

The coding tool's own usage view asks its vendor's usage endpoint with the local login's access token; the
tool skips that fetch while its nonessential traffic (telemetry) is off, so Hermes's reader for a subscription provider
can refuse. This module asks the same endpoint itself, read-only:

- the token comes from the coding tool's local login (the credentials file in its configuration folder, see TOOL), is
  sent only as the Authorization header and is never logged, printed or returned;
- it never refreshes or rotates the token (it is the coding tool's, and a refresh here could log the tool out): an
  expired token is an error, and the caller keeps its last good reading;
- the answer maps to the windows Hermes's readers give: {label, used_percent, resets_at, scope}, the 5-hour session and
  the week account-scoped, a model's own weekly limit model-scoped.
"""

import datetime
import json
import math
import os
import time

# The coding tool's own identifiers, matched against this machine and sent to its endpoint: never printed, never shown.
TOOL = {
    "url": "https://api.anthropic.com/api/oauth/usage",
    "version_header": "anthropic-beta",
    "config_env": "CLAUDE_CONFIG_DIR",
    "config_folder": ".claude",
    "login_key": "claudeAiOauth",
}
URL = TOOL["url"]
BETA = "oauth-2025-04-20"
TIMEOUT = 15.0
LIMIT_LABELS = {"session": "Current session", "weekly_all": "Current week"}
# The response's own field per window, read when it lists no `limits`: (field, label, scope).
WINDOW_FIELDS = (
    ("five_hour", "Current session", "account"),
    ("seven_day", "Current week", "account"),
    ("seven_day_opus", "Opus week", "model"),
    ("seven_day_sonnet", "Sonnet week", "model"),
)


class ReadError(Exception):
    """The endpoint could not be asked or did not answer with JSON. Its text never carries the token."""


def credentials_path() -> str:
    folder = os.environ.get(TOOL["config_env"]) or os.path.join(os.path.expanduser("~"), TOOL["config_folder"])
    return os.path.join(folder, ".credentials.json")


def _token(now: float):
    """(token, '') or ('', why not)."""
    try:
        data = json.load(open(credentials_path(), encoding="utf-8"))
    except (OSError, ValueError):
        return "", "no subscription login on this machine (no readable .credentials.json)"
    login = data.get(TOOL["login_key"]) if isinstance(data, dict) else None
    token = str((login or {}).get("accessToken") or "") if isinstance(login, dict) else ""
    if not token:
        return "", "no subscription login on this machine (no access token)"
    expires = login.get("expiresAt")
    if isinstance(expires, (int, float)) and not isinstance(expires, bool) and expires / 1000.0 <= now:
        stamp = datetime.datetime.fromtimestamp(expires / 1000.0, datetime.UTC).isoformat()
        return "", f"the subscription login token expired at {stamp}; the coding tool renews it on its next run"
    return token, ""


def _fetch(url: str, headers: dict, timeout: float) -> dict:
    import urllib.error
    import urllib.request

    request = urllib.request.Request(url, headers=headers, method="GET")  # noqa: S310 - a fixed https URL
    try:
        with urllib.request.urlopen(request, timeout=timeout) as answer:  # noqa: S310 - a fixed https URL
            return json.loads(answer.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise ReadError(f"HTTP {exc.code}") from None
    except (urllib.error.URLError, OSError, ValueError) as exc:
        raise ReadError(
            type(exc).__name__ + (f": {exc.reason}" if isinstance(exc, urllib.error.URLError) else "")
        ) from None


def _percent(value, fraction=False):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        return None
    return float(value) * 100.0 if fraction and value <= 1 else float(value)


def _stamp(value):
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        datetime.datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return value.strip()


def windows_of(payload) -> list:
    """The response's windows; an unknown shape gives what it can, never raises."""
    payload = payload if isinstance(payload, dict) else {}
    limits = payload.get("limits")
    limits = [entry for entry in limits if isinstance(entry, dict)] if isinstance(limits, list) else []
    found = []
    if limits:
        for entry in limits:
            used = _percent(entry.get("percent"))
            if used is None:
                continue
            kind = entry.get("kind") if isinstance(entry.get("kind"), str) else ""
            scope = entry.get("scope") if isinstance(entry.get("scope"), dict) else {}
            model = scope.get("model") if isinstance(scope.get("model"), dict) else {}
            name = model.get("display_name") if isinstance(model.get("display_name"), str) else ""
            label = LIMIT_LABELS.get(kind) or (f"{name} week" if name else kind or "unknown")
            found.append(
                {
                    "label": label,
                    "used_percent": used,
                    "resets_at": _stamp(entry.get("resets_at")),
                    "scope": "model" if name else "account",
                }
            )
        return found
    for key, label, scope in WINDOW_FIELDS:
        window = payload.get(key)
        used = _percent(window.get("utilization"), fraction=True) if isinstance(window, dict) else None
        if used is not None:
            found.append(
                {"label": label, "used_percent": used, "resets_at": _stamp(window.get("resets_at")), "scope": scope}
            )
    return found


def read(fetch=None, now=None) -> dict:
    """{windows: [...], error: ''}: one read of the subscription's windows; on failure no windows and why."""
    moment = time.time() if now is None else now
    token, why = _token(moment)
    if not token:
        return {"windows": [], "error": why}
    headers = {
        "Authorization": f"Bearer {token}",
        TOOL["version_header"]: BETA,
        "Accept": "application/json",
        "Content-Type": "application/json",
        "User-Agent": "hermes-cockpit",
    }
    try:
        payload = (fetch or _fetch)(URL, headers, TIMEOUT)
    except ReadError as exc:
        return {"windows": [], "error": f"plan usage read failed: {exc}"}
    found = windows_of(payload)
    return {"windows": found, "error": "" if found else "plan usage read answered no window"}
