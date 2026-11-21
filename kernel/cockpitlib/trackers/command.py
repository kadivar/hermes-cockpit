# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The pack's own tracker command: the intent as JSON on stdin, the action in COCKPIT_TRACKER_ACTION, JSON back.

The writes (comment, create, transition) and the title read (summary) are every such command's. The reads the comment
watch and the standup note use (comments, me, status) are run only for a pack that names them in `tracker.reads`: a
command written before they existed is never run with an action it does not know. A read the command answers with exit
2 is one it does not have.
"""

import json
import os
import subprocess

from ..errors import CockpitError
from . import base
from .base import Tracker, Unsupported

READS = {"comments": base.COMMENTS, "me": base.IDENTITY, "status": base.STATUS}
NOT_IMPLEMENTED = 2  # a read action's exit when the command does not have it


class CommandTracker(Tracker):
    """The pack's tracker command: the intent as JSON on stdin, the action in COCKPIT_TRACKER_ACTION, JSON back."""

    kind = "command"
    # the command is handed the whole intent: what it does with an attachment, a sprint or a component is its own
    HAS = (
        base.SUMMARY,
        base.COMMENT,
        base.EDIT_COMMENT,
        base.ATTACHMENTS,
        base.CREATE,
        base.TRANSITION,
        base.ASSIGNEE,
        base.SPRINT,
        base.COMPONENT,
    )

    @classmethod
    def offers(cls, config) -> frozenset:
        return frozenset(cls.HAS) | {READS[name] for name in (config or {}).get("reads") or () if name in READS}

    def _run(self, action: str, given: dict) -> dict:
        env = {**os.environ, "COCKPIT_TRACKER_ACTION": action}
        try:
            done = subprocess.run(
                list(self.config["command"]),
                input=json.dumps(given),
                capture_output=True,
                text=True,
                env=env,
                check=False,
                timeout=300,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise CockpitError(f"tracker command: {exc}") from exc
        if done.returncode == NOT_IMPLEMENTED and action in READS:
            raise Unsupported(f"the pack's tracker command has no read for {action}")
        if done.returncode != 0:
            raise CockpitError(
                f"tracker command {action}: {(done.stderr or done.stdout).strip()[-300:] or done.returncode}"
            )
        try:
            found = json.loads(done.stdout or "{}")
        except ValueError as exc:
            raise CockpitError(f"tracker command {action}: its answer is not JSON") from exc
        return found if isinstance(found, dict) else {}

    def _call(self, action: str, intent: dict) -> dict:
        self.writes.append({"method": action, "path": "tracker.command", "body": intent.get("payload")})
        if self.dry_run:
            return {"dry_run": True}
        return self._run(action, intent)

    def _read(self, action: str, given: dict) -> dict:
        """One of the reads a pack names in tracker.reads; one it does not name is not run."""
        if action not in (self.config.get("reads") or ()):
            raise Unsupported(f"the pack's tracker command has no read for {action}")
        return self._run(action, given)

    def comment(self, intent, steps):
        found = self._call("comment", intent)
        return found.get("url") or "", f"comment {found.get('id', '')}".strip(), {"comment": str(found.get("id") or "")}

    def create(self, intent, steps):
        found = self._call("create", intent)
        return found.get("url") or "", str(found.get("key") or ""), {"key": str(found.get("key") or "")}

    def transition(self, intent, steps, issue):
        found = self._call("transition", intent)
        return found.get("url") or "", str(found.get("output") or found.get("status") or ""), {}

    def summary(self, issue: str) -> str:
        """The issue's title from the pack's command (action summary); a read, so it is not listed as a write."""
        writes = list(self.writes)
        found = self._call("summary", {"ticket": issue, "payload": {"issue": issue}})
        self.writes = writes
        return str(found.get("summary") or "")

    def status(self, key: str) -> str:
        return str(self._read("status", {"key": key}).get("status") or "")

    def me(self) -> str:
        try:
            return str(self._read("me", {}).get("login") or "")
        except Unsupported:
            return ""

    def comments(self, key: str, since=None) -> list:
        rows = self._read("comments", {"key": key, "since": since}).get("comments")
        found = []
        for row in rows if isinstance(rows, list) else []:
            if not isinstance(row, dict) or not row.get("id"):
                continue
            author = str(row.get("author") or "")
            created = str(row.get("created") or "")
            found.append(
                {
                    "id": str(row["id"]),
                    "account": author,
                    "author": author or "someone",
                    "created": created,
                    "updated": str(row.get("updated") or created),
                    "text": str(row.get("body") or "").strip(),
                }
            )
        return base.since_then(found, since)
