# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""What one pr-patch-apply intent does: the branch push, then one action per judged review thread.

The manifest (threads_file, JSON) has one row per thread: {n, comment_id, thread, location, reviewer, type, reply}.
Code and GitHub housekeeping rows get a thumbs-up and are resolved, with no reply. Deferred rows get the reply, and
the thread stays open. Answered rows are code that was changed differently from what the thread asked: the reply says
how, and the thread stays open for the reviewer to close.
"""

import json
import os

from .errors import CockpitError

TYPES = ("Code", "GitHub housekeeping", "Deferred", "Answered")
REPLIED = ("Deferred", "Answered")  # a reply, no thumbs-up, the thread left open


def actions(rows) -> list:
    planned = []
    for row in rows or []:
        kind = row.get("type")
        if kind in ("Code", "GitHub housekeeping"):
            planned.append(
                {"id": row.get("thread"), "react": True, "resolve": True, "reply": False, "leave_open": False}
            )
            continue
        if kind in REPLIED:
            planned.append(
                {
                    "id": row.get("thread"),
                    "react": False,
                    "resolve": False,
                    "reply": True,
                    "leave_open": True,
                    "body": row.get("reply") or "",
                }
            )
            continue
        planned.append({"id": row.get("thread"), "react": False, "resolve": False, "reply": False, "leave_open": True})
    return planned


def leave_open(row, newer_comment: bool) -> bool:
    """A thread that gained a comment after the plan stays open."""
    if newer_comment:
        return True
    return row.get("type") in REPLIED


def rows(path: str) -> list:
    """The manifest's rows with react and resolve set from their type, or the first bad row named."""
    from .paths import workspace

    full = path if os.path.isabs(path) else os.path.join(workspace(), path)
    try:
        data = json.load(open(full, encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise CockpitError(f"the threads file is not readable JSON ({exc})") from exc
    items = data.get("rows") if isinstance(data, dict) else data
    if not isinstance(items, list) or not items:
        raise CockpitError("the threads file has no rows (one per judged thread)")
    found = []
    for index, row in enumerate(items, 1):
        if not isinstance(row, dict):
            raise CockpitError(f"row {index} is not an object")
        number, kind, reply = row.get("n", index), row.get("type"), str(row.get("reply") or "").strip()
        if kind not in TYPES:
            raise CockpitError(f"row {number}: type is one of {', '.join(TYPES)}, not {kind!r}")
        if not str(row.get("comment_id") or "").isdigit():
            raise CockpitError(f"row {number}: comment_id is the review comment's id")
        article = "an" if kind[0].lower() in "aeiou" else "a"
        if kind in REPLIED and not reply:
            raise CockpitError(f"row {number}: {article} {kind} row is answered with a reply")
        if kind not in REPLIED and reply:
            raise CockpitError(
                f"row {number}: {article} {kind} row is resolved with a thumbs-up and no reply; "
                "type it Answered to reply and leave the thread open"
            )
        found.append(
            {
                **row,
                "n": number,
                "comment_id": int(row["comment_id"]),
                "reply": reply,
                "react": kind not in REPLIED,
                "resolve": kind not in REPLIED,
            }
        )
    return found


def counts(found) -> dict:
    return {kind: sum(1 for row in found if row["type"] == kind) for kind in TYPES}


def pushes(payload) -> bool:
    """The apply sends commits: its sha is not what the remote already has."""
    return bool(payload.get("sha")) and payload.get("sha") != payload.get("remote_sha")


def body(payload, found) -> str:
    """What leaves, in words: the push, then one row per thread with what the forge will show."""
    tally = counts(found)
    lines = [
        f"## Patch apply · {payload.get('repo')}#{payload.get('number')}",
        "",
        f"One act: the push, then every thread below. {tally['Code']} code · {tally['GitHub housekeeping']} housekeeping · "
        f"{tally['Deferred']} deferred" + (f" · {tally['Answered']} answered" if tally["Answered"] else "") + ".",
        "",
        "### Push",
    ]
    if pushes(payload):
        lease = (
            f" (lease: the remote at `{payload['remote_sha'][:9]}`)" if payload.get("remote_sha") else " (new branch)"
        )
        lines.append(f"- branch `{payload.get('publish_as') or payload.get('branch')}` → `{payload['sha'][:9]}`{lease}")
        lines += [f"- {commit}" for commit in (payload.get("commits") or [])[:12]]
    else:
        lines.append("- nothing to push (housekeeping and replies only)")
    lines += ["", "### Threads", "", "| # | Location | Reviewer | Type | On the forge |", "|---:|---|---|---|---|"]
    for row in found:
        what = "thumbs-up + resolve" if row["resolve"] else "reply, stays open"
        lines.append(
            f"| {row['n']} | `{row.get('location') or row['comment_id']}` | {row.get('reviewer') or ''} | {row['type']} | {what} |"
        )
    for row in found:
        if row["reply"]:
            lines += ["", f"**Reply on #{row['n']}**:", "", *["> " + line for line in row["reply"].splitlines()]]
    return "\n".join(lines) + "\n"
