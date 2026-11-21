# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Watcher health records and the Inbox sentence for a failure."""

import json
import os
import re
import time

from .store import dump_json

TRANSIENT = ("timeout", "timed out", "429", "502", "503", "504", "unreachable")


def failing_records(folder: str) -> list:
    """Watcher health files that are not ok. Other JSON in the watch directory is not an Inbox row."""
    found = []
    if not folder or not os.path.isdir(folder):
        return found
    for name in sorted(os.listdir(folder)):
        if not name.endswith(".json"):
            continue
        path = os.path.join(folder, name)
        try:
            record = json.load(open(path, encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(record, dict) or "ok" not in record:
            continue
        text = reason(record)
        if not text:
            continue
        found.append({"name": name[:-5], "record": record, "reason": text})
    return found


def stale_minutes(pack, name: str, schedule: str) -> int:
    """How long a job may go without a successful run: the pack's limit, else three intervals (at least a quarter
    hour) for an every-N job, two days for a daily one, four for one on working days (a weekend sits between), eight
    for a weekly one."""
    limit = ((((pack or {}).get("watchers") or {}).get("limits") or {}).get(name) or {}).get("stale_minutes")
    if limit:
        return int(limit)
    every = re.fullmatch(r"(\d+)([mh])", schedule or "")
    if every:
        minutes = int(every.group(1)) * (60 if every.group(2) == "h" else 1)
        return max(3 * minutes, 15)
    fields = (schedule or "").split()
    days = fields[4] if len(fields) == 5 else "*"
    if days == "*":
        return 2 * 24 * 60
    if re.fullmatch(r"\d", days):
        return 8 * 24 * 60
    return 4 * 24 * 60


def stale_records(pack, folder: str, now=None) -> list:
    """Registered jobs that have not succeeded within their limit: an old success, or no run at all since the job
    was registered (the cron file's time). A job that is not registered is doctor's matter, not a row here."""
    from .setup import CRON_JOBS, cron_home, cron_schedule, registered_jobs

    moment = time.time() if now is None else now
    registered = {str(job.get("name")) for job in registered_jobs(pack) if isinstance(job, dict)}
    found = []
    for name, default, _script in CRON_JOBS:
        if name not in registered:
            continue
        limit = stale_minutes(pack, name, cron_schedule(pack, name, default)) * 60
        record = load_quiet(folder, name)
        if record:
            if not record.get("ok"):
                continue
            last = float(record.get("last_ok") or record.get("last_run") or 0)
            if moment - last > limit:
                found.append({"name": name, "record": record, "reason": f"no successful run in {_span(moment - last)}"})
            continue
        jobs = os.path.join(cron_home(pack, name), "cron", "jobs.json")
        since = os.path.getmtime(jobs) if os.path.isfile(jobs) else moment
        if moment - since > limit:
            found.append(
                {
                    "name": name,
                    "record": {"ok": False, "never_ran": True},
                    "reason": f"never ran in the {_span(moment - since)} since it was registered",
                }
            )
    return found


def watcher_rows(pack, folder: str, now=None) -> list:
    """Every watcher that needs the human: the failing ones, then the stale and never-ran ones."""
    rows = failing_records(folder)
    named = {row["name"] for row in rows}
    return rows + [row for row in stale_records(pack, folder, now) if row["name"] not in named]


def _span(seconds: float) -> str:
    minutes = int(seconds // 60)
    if minutes < 120:
        return f"{minutes} minutes"
    if minutes < 48 * 60:
        return f"{minutes // 60} hours"
    return f"{minutes // (24 * 60)} days"


def load_quiet(folder: str, name: str):
    try:
        return load(folder, name)
    except (OSError, ValueError):
        return None


def reason(record) -> str:
    if not record:
        return "no successful run yet"
    if record.get("ok"):
        return ""
    text = (record.get("output") or "").lower()
    if "timeout" in text or "timed out" in text:
        return "the run timed out"
    if "secondary rate limit" in text or "scraping github" in text:
        return "GitHub refused a burst of requests (its secondary rate limit): the next pass tries again"
    if "401" in text or "403" in text or "token" in text:
        return "the forge rejected the token"
    if any(code in text for code in ("429", "502", "503", "504")):
        return "the forge returned an error"
    if text.startswith("forge"):
        return "the forge read failed"
    if record.get("trace"):
        return "the watcher crashed"
    return record.get("summary") or "the watcher failed"


def transient(output: str) -> bool:
    text = (output or "").lower()
    return any(token in text for token in TRANSIENT)


def should_retry(output: str, attempt: int) -> bool:
    return attempt < 1 and transient(output)


def load(folder: str, name: str):
    path = os.path.join(folder, f"{name}.json")
    if not os.path.isfile(path):
        return None
    return json.load(open(path, encoding="utf-8"))


def save(folder: str, name: str, record) -> None:
    os.makedirs(folder, exist_ok=True)
    dump_json(os.path.join(folder, f"{name}.json"), record)
