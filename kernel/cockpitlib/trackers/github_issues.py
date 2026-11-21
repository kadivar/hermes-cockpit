# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The issues of the pack's forge as its tracker: no second client, every call is an operation of the forge the pack publishes to.

`tracker.kind: github-issues` chooses it. A ticket `<tracker.project>-<n>` is issue n of `tracker.repo` (a repo of
repos.yaml; the first when unset) under the pack's forge and organisation: with `forge.kind: github` that is GitHub
Issues through the human's own `gh` login, with `forge.kind: local` issues kept in files beside the pull requests.

A ticket's status is `Open` or `Closed`, the issue's state. `tracker.status_labels` ({status: label}, in the pack's
order) adds statuses carried by a label: a ticket has the first of them whose label it carries, when the issue's state
is that status's (closed for a status named in `tracker.closed_statuses`, open for the others), so an issue someone
closed on the forge reads Closed whatever label it still carries. A move to a status sets its label, takes the other
status labels off and opens or closes the issue; a move to Open or Closed takes every status label off.

The forge has no upload for a file on an issue, so this tracker has no attachments; nor sprints, components or a
workflow to move through. Every write is read back. In a dry run the forge keeps the writes and sends none.
"""

import datetime
import os
import re

from ..errors import CockpitError
from . import base
from .base import Tracker

OPEN, CLOSED = "Open", "Closed"
STATES = {OPEN: "open", CLOSED: "closed"}
NUMBER = r"[1-9][0-9]*"  # an issue's number as a key spells it: no sign, no leading zero


class GitHubIssuesTracker(Tracker):
    kind = "github-issues"
    noun = "issue"
    over_forge = True
    HAS = (
        base.SUMMARY,
        base.STATUS,
        base.COMMENTS,
        base.IDENTITY,
        base.COMMENT,
        base.EDIT_COMMENT,
        base.CREATE,
        base.TRANSITION,
        base.ASSIGNEE,
    )

    def __init__(self, config, dry_run: bool = False, pack=None, forge=None):
        super().__init__(config, dry_run)
        pack = pack or {}
        if forge is None:
            from .. import forges

            forge = forges.make(pack, dry_run=dry_run)
        from ..forges import base as forge_base

        if forge_base.ISSUES not in forge.capabilities():
            raise CockpitError(
                f"the pack's forge ({forge.kind}) has no {forge_base.ISSUES}: tracker.kind {self.kind} needs a forge that has them"
            )
        self.forge = forge
        self.writes = forge.writes  # one journal: what this tracker writes, the forge writes
        self.project = str(self.config.get("project") or "")
        if not self.project:
            raise CockpitError(
                f"tracker.kind {self.kind} needs tracker.project: the prefix of its tickets, e.g. GH for GH-12"
            )
        known = [
            str(row.get("name"))
            for row in (pack.get("repos") or {}).get("repos") or []
            if isinstance(row, dict) and row.get("name")
        ]
        self.repo = str(self.config.get("repo") or (known[0] if known else ""))
        if not self.repo or (known and self.repo not in known):
            raise CockpitError(
                f"tracker.repo names the repo whose issues are the tickets, one of repos.yaml ({', '.join(known) or 'none listed'})"
            )
        self.labels = {str(name): str(label) for name, label in (self.config.get("status_labels") or {}).items()}
        self.closed = [str(name) for name in self.config.get("closed_statuses") or []]

    # ---- keys and statuses
    def number(self, key: str) -> int:
        """The issue number a ticket key means; a key of another project, or one whose number is not a plain positive one, is refused."""
        prefix, dash, digits = str(key).rpartition("-")
        if not dash or prefix != self.project or not re.fullmatch(NUMBER, digits):
            raise CockpitError(
                f"{key} is not a ticket of the {self.kind} tracker: its tickets are {self.project}-<n>, "
                f"issue n of {self.forge.repo(self.repo)}"
            )
        return int(digits)

    def key(self, number) -> str:
        """The ticket key of an issue number."""
        return f"{self.project}-{int(number)}"

    def known(self) -> list:
        """Every status a ticket can have: the labelled ones in the pack's order, then Open and Closed."""
        return [*self.labels, OPEN, CLOSED]

    def _state(self, status: str) -> str:
        """The issue state a status means."""
        return "closed" if status == CLOSED or status in self.closed else "open"

    def _named(self, to: str) -> str:
        """The status that name means, in the pack's own spelling."""
        found = next((name for name in self.known() if name.lower() == str(to).strip().lower()), "")
        if not found:
            raise CockpitError(f"{self.kind} tracker: '{to}' is not a status; it has {self.known()}")
        return found

    def _issue(self, key: str) -> dict:
        return self.forge.issue(self.repo, self.number(key))

    def _status(self, issue: dict) -> str:
        carried = {str(label).lower() for label in issue.get("labels") or []}
        state = str(issue.get("state") or "open")
        for name, label in self.labels.items():
            if label.lower() in carried and self._state(name) == state:
                return name
        return CLOSED if state == "closed" else OPEN

    @staticmethod
    def _text(payload: dict) -> str:
        """The intent's draft, Markdown as it is: a file in the workspace, or the text itself."""
        if payload.get("body_file"):
            from ..paths import workspace

            return open(os.path.join(workspace(), payload["body_file"]), encoding="utf-8").read()
        return str(payload.get("body") or "")

    def _who(self, assignee) -> str:
        return self.me() if assignee == "me" else str(assignee)

    # ---- identity and reads
    def me(self) -> str:
        return self.forge.me()

    def browse_url(self, key: str) -> str:
        """tracker.browse_url when the pack gives one; else the issue's page on the forge."""
        if self.config.get("browse_url"):
            return base.link(self.config, key)
        return self.forge.issue_url(self.repo, self.number(key))

    def comment_url(self, key: str, comment_id) -> str:
        return f"{self.browse_url(key)}#issuecomment-{comment_id}"

    def summary(self, key: str) -> str:
        return str(self._issue(key).get("title") or "")

    def status(self, key: str) -> str:
        return self._status(self._issue(key))

    def comments(self, key: str, since=None) -> list:
        floor = base.moment(since)
        # the forge is asked from the whole second before: a moment it rounds is never one it leaves out
        asked = (
            datetime.datetime.fromtimestamp(int(floor), datetime.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
            if floor is not None
            else None
        )
        rows = [
            {
                "id": str(row["id"]),
                "account": str(row.get("author") or ""),
                "author": str(row.get("author") or "someone"),
                "created": str(row.get("created") or ""),
                "updated": str(row.get("updated") or row.get("created") or ""),
                "text": str(row.get("body") or "").strip(),
            }
            for row in self.forge.issue_comments(self.repo, self.number(key), since=asked)
        ]
        return base.since_then(rows, since)

    def find_comment(self, key: str, title: str) -> str:
        for row in self.comments(key):
            if row["text"].lower().startswith(title.lower()):
                return row["id"]
        return ""

    # ---- writes
    def comment(self, intent, steps):
        payload = intent["payload"]
        key = payload.get("issue") or intent["ticket"]
        if payload.get("attach"):
            self._no(base.ATTACHMENTS)
        number = self.number(key)
        body = self._text(payload)
        comment_id = str(payload.get("comment_id") or steps.get("from_comment") or "")
        self._issue(key)  # a ticket that is not there, or is a pull request, is said before anything is written
        before = self.comments(key) if comment_id or payload.get("probe_title") else []
        if payload.get("probe_title") and not comment_id:
            found = next(
                (row["id"] for row in before if row["text"].lower().startswith(str(payload["probe_title"]).lower())), ""
            )
            if found:
                raise CockpitError(
                    f"{key} already has a comment starting with '{payload['probe_title']}' (id {found}): "
                    f"amend the intent with --comment-id {found} so this updates it"
                )
        if comment_id and comment_id not in [row["id"] for row in before]:
            raise CockpitError(f"{self.kind} tracker: {key} has no comment {comment_id}")
        out = f"{'updated' if comment_id else 'posted'} on {key}"
        if comment_id:
            self.forge.edit_issue_comment(self.repo, comment_id, body)
            made = comment_id
        else:
            made = str((self.forge.add_issue_comment(self.repo, number, body) or {}).get("id") or "")
        if self.dry_run:
            return self.browse_url(key), "would be " + out, {}
        back = next((row for row in self.comments(key) if row["id"] == made), None) if made else None
        if back is None or back["text"].split() != body.split():
            raise CockpitError("read-back: the comment is not readable after the post")
        return self.comment_url(key, made), f"{out} (comment {made}, read back)", {"comment": made}

    def create(self, intent, steps):
        payload = intent["payload"]
        for field, capability in (("attach", base.ATTACHMENTS), ("sprint", base.SPRINT), ("component", base.COMPONENT)):
            if payload.get(field):
                self._no(capability)
        project = str(payload.get("project") or self.project)
        if project != self.project:
            raise CockpitError(
                f"{self.kind} tracker: a new ticket is an issue of {self.forge.repo(self.repo)}, {self.project}-<n>; "
                f"it has no project {project}"
            )
        summary = payload["summary"]
        body = self._text(payload) if (payload.get("body_file") or payload.get("body")) else ""
        labels = [str(label) for label in payload.get("labels") or []]
        people = [self._who(payload["assignee"])] if payload.get("assignee") else []
        made = self.forge.create_issue(self.repo, summary, body, labels=labels, assignees=people)
        if self.dry_run:
            return "", f"would create {project} {summary!r}", {}
        if not (made or {}).get("number"):
            raise CockpitError("the forge made no issue number")
        key = self.key(made["number"])
        back = self._issue(key)
        lacking = [
            what
            for what, wrong in (
                ("summary", back.get("title") != summary),
                (
                    "labels",
                    not {label.lower() for label in labels}
                    <= {str(label).lower() for label in back.get("labels") or []},
                ),
                ("assignee", not set(people) <= set(back.get("assignees") or [])),
            )
            if wrong
        ]
        if lacking:
            raise CockpitError(f"read-back: {key} does not carry the {', '.join(lacking)} it was made with")
        steps["key"] = key
        out = key
        if payload.get("transition"):
            out += "; " + self._move(key, payload["transition"])
        return self.browse_url(key), out + " · read back", {"key": key}

    def _move(self, key: str, to: str) -> str:
        target = self._named(to)
        number = self.number(key)
        issue = self._issue(key)
        start = self._status(issue)
        state = self._state(target)
        ours = {label.lower() for label in self.labels.values()}
        wanted = sorted(
            [label for label in issue.get("labels") or [] if str(label).lower() not in ours]
            + ([self.labels[target]] if target in self.labels else [])
        )
        relabel = wanted != sorted(issue.get("labels") or [])
        if start == target and not relabel and issue.get("state") == state:
            return f"{key} is already {start}"
        if relabel:
            self.forge.set_labels(self.repo, number, wanted)
        if issue.get("state") != state:
            self.forge.update_issue(self.repo, number, {"state": state})
        if self.dry_run:
            return f"would move {key} → {target}"
        now = self.status(key)
        if now != target:
            raise CockpitError(f"read-back: {key} is '{now}' after the move to '{target}'")
        return f"{to} → {target} (status now {now})"

    def transition(self, intent, steps, key):
        payload = intent["payload"]
        out = self._move(key, payload["to"])
        if payload.get("assignee"):
            who = self._who(payload["assignee"])
            self.forge.assign(self.repo, self.number(key), [who])
            if not self.dry_run and who not in (self._issue(key).get("assignees") or []):
                raise CockpitError(f"read-back: {key} is not assigned to {who}")
            out += f"; assigned {payload['assignee']}"
        return self.browse_url(key), out, {}
