# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""A tracker kept in files: one JSON file per ticket under one folder. No network, no command, no credentials.

`tracker.kind: local` chooses it; `tracker.local.root` names the folder (default: `tracker/` in the records folder).
A ticket is `<root>/<KEY>.json`: {key, summary, body, status, labels, assignee, comments: [{id, author, created, updated,
body, attach}], attachments: [{name, path, size}]}. An attachment is kept by its path, never copied.

`tracker.local.statuses` is the statuses a ticket can have, the first being a new ticket's. A ticket may move from any
to any, unless `tracker.local.transitions` maps each status to the ones it may move to: then a move with no direct
route goes the shortest way there. It has no sprints and no components. It is what a demonstration without an account and a hermetic
test use; someone else's comment is written with `add_comment(key, body, author)`.
"""

import contextlib
import datetime
import json
import os

from ..errors import CockpitError
from . import base
from .base import Tracker

STATUSES = ["To Do", "In Progress", "In Review", "Done"]
ME = "human"


class LocalTracker(Tracker):
    kind = "local"
    HAS = tuple(name for name in base.CAPABILITIES if name not in (base.SPRINT, base.COMPONENT))

    def __init__(self, config, dry_run: bool = False, root: str = ""):
        super().__init__(config, dry_run)
        local = self.config.get("local") or {}
        self._root = root or local.get("root") or ""
        names = [str(name) for name in local.get("statuses") or STATUSES]
        told = local.get("transitions")
        # each status and the ones a ticket may move to from it: with no transitions named, every status leads to every other
        self.moves = {
            name: ([str(to) for to in told.get(name) or []] if told else [to for to in names if to != name])
            for name in names
        }

    # ---- the files
    def root(self) -> str:
        """The folder this tracker lives in: tracker.local.root, or tracker/ in the records folder."""
        if self._root:
            return os.path.abspath(os.path.expanduser(self._root))
        from ..paths import records

        return os.path.join(records(), "tracker")

    def _file(self, key: str) -> str:
        from ..paths import inside

        return inside(self.root(), f"{key}.json", what="ticket")

    def _load(self, key: str) -> dict:
        try:
            return json.load(open(self._file(key), encoding="utf-8"))
        except FileNotFoundError as exc:
            raise CockpitError(f"local tracker: no ticket {key}") from exc
        except (OSError, ValueError) as exc:
            raise CockpitError(f"local tracker: {self._file(key)} is unreadable: {exc}") from exc

    @contextlib.contextmanager
    def _locked(self):
        """One writer at a time over the folder: a new ticket's number and a ticket's change are each one step."""
        from ..store import locked_file

        with locked_file(
            os.path.join(self.root(), "tickets")
        ):  # the folder's one lock: .tickets.lock, which no listing reads
            yield

    def _save(self, ticket: dict) -> None:
        from ..store import dump_json

        dump_json(self._file(ticket["key"]), ticket, indent=1, sort_keys=True)

    @contextlib.contextmanager
    def _change(self, key: str):
        with self._locked():
            ticket = self._load(key)
            yield ticket
            self._save(ticket)

    def _sent(self, what: str, key: str, body: dict) -> bool:
        """Keep the write in the journal. False in a dry run: nothing is stored."""
        self.writes.append({"method": what, "path": f"local tracker {key}".strip(), "body": body})
        return not self.dry_run

    @staticmethod
    def _now() -> str:
        return datetime.datetime.now(datetime.UTC).isoformat()

    def _text(self, payload: dict) -> str:
        """The intent's draft: a file in the workspace, or the text itself."""
        if payload.get("body_file"):
            from ..paths import workspace

            return open(os.path.join(workspace(), payload["body_file"]), encoding="utf-8").read()
        return str(payload.get("body") or "")

    # ---- identity and reads
    def me(self) -> str:
        return ME

    def browse_url(self, key: str) -> str:
        """tracker.browse_url when the pack gives one; else the ticket's own file."""
        return base.link(self.config, key) if self.config.get("browse_url") else "file://" + self._file(key)

    def comment_url(self, key: str, comment_id) -> str:
        return f"{self.browse_url(key)}#comment-{comment_id}"

    def summary(self, key: str) -> str:
        return str(self._load(key).get("summary") or "")

    def status(self, key: str) -> str:
        return str(self._load(key).get("status") or "")

    def comments(self, key: str, since=None) -> list:
        rows = [
            {
                "id": str(row["id"]),
                "account": str(row.get("author") or ""),
                "author": str(row.get("author") or "someone"),
                "created": str(row.get("created") or ""),
                "updated": str(row.get("updated") or row.get("created") or ""),
                "text": str(row.get("body") or "").strip(),
            }
            for row in self._load(key).get("comments") or []
        ]
        return base.since_then(rows, since)

    def find_comment(self, key: str, title: str) -> str:
        for row in self.comments(key):
            if row["text"].lower().startswith(title.lower()):
                return row["id"]
        return ""

    def attachments(self, key: str) -> list:
        """The files attached to the ticket, each {name, path, size}."""
        return list(self._load(key).get("attachments") or [])

    # ---- writes
    def seed(self, key: str, summary: str = "", body: str = "", status: str = "") -> dict:
        """A ticket with that key, as if someone made it in the tracker: what a demonstration and a test start from."""
        ticket = {
            "key": key,
            "summary": summary,
            "body": body,
            "status": status or next(iter(self.moves)),
            "labels": [],
            "assignee": "",
            "comments": [],
            "attachments": [],
            "created": self._now(),
        }
        with self._locked():
            self._save(ticket)
        return ticket

    def add_comment(self, key: str, body: str, author: str = "") -> str:
        """A comment by that author (the human when none is named), outside any intent. Its id."""
        with self._change(key) as ticket:
            return self._append(ticket, body, [], author or ME)

    def _append(self, ticket: dict, body: str, attach: list, author: str) -> str:
        made = str(1 + max([int(row["id"]) for row in ticket["comments"]] or [0]))
        now = self._now()
        ticket["comments"].append(
            {"id": made, "author": author, "created": now, "updated": now, "body": body, "attach": attach}
        )
        return made

    def comment(self, intent, steps):
        payload = intent["payload"]
        key = payload.get("issue") or intent["ticket"]
        body = self._text(payload)
        comment_id = str(payload.get("comment_id") or steps.get("from_comment") or "")
        if payload.get("probe_title") and not comment_id:
            found = self.find_comment(key, payload["probe_title"])
            if found:
                raise CockpitError(
                    f"{key} already has a comment starting with '{payload['probe_title']}' (id {found}): "
                    f"amend the intent with --comment-id {found} so this updates it"
                )
        from ..paths import workspace

        files = [
            {"name": os.path.basename(path), "path": path, "size": os.path.getsize(os.path.join(workspace(), path))}
            for path in payload.get("attach") or []
        ]
        names = [row["name"] for row in files]
        out = f"{'updated' if comment_id else 'posted'} on {key}"
        if not self._sent(
            "comment", key, {"body": body, "attach": [row["path"] for row in files], "comment_id": comment_id}
        ):
            self._load(key)  # a dry run still reads: a ticket that is not there is said now
            return self.browse_url(key), "would be " + out, {}
        with self._change(key) as ticket:
            if comment_id:
                row = next((row for row in ticket["comments"] if str(row["id"]) == comment_id), None)
                if row is None:
                    raise CockpitError(f"local tracker: {key} has no comment {comment_id}")
                row.update(
                    body=body,
                    updated=self._now(),
                    attach=sorted(set(row.get("attach") or []) | {item["path"] for item in files}),
                )
                made = comment_id
            else:
                made = self._append(ticket, body, [row["path"] for row in files], ME)
            kept = {row["name"]: row for row in ticket["attachments"]}
            kept.update({row["name"]: row for row in files})
            ticket["attachments"] = list(kept.values())
        for name in names:
            steps[f"attach:{name}"] = name
        back = next((row for row in self.comments(key) if row["id"] == made), None)
        if back is None or back["text"] != body.strip():
            raise CockpitError("read-back: the comment is not readable after the post")
        return (
            self.browse_url(key),
            f"{out} (comment {made}, read back)" + (f" · attached {', '.join(names)}" if names else ""),
            {"comment": made},
        )

    def create(self, intent, steps):
        payload = intent["payload"]
        for field, capability in (("sprint", base.SPRINT), ("component", base.COMPONENT)):
            if payload.get(field):
                self._no(capability)
        project = str(payload.get("project") or self.config.get("project") or "")
        if not project:
            raise CockpitError("local tracker: a new ticket needs a project (the intent's, or tracker.project)")
        ticket = {
            "summary": payload["summary"],
            "body": self._text(payload) if (payload.get("body_file") or payload.get("body")) else "",
            "status": next(iter(self.moves)),
            "labels": list(payload.get("labels") or []),
            "assignee": (ME if payload["assignee"] == "me" else str(payload["assignee"]))
            if payload.get("assignee")
            else "",
            "comments": [],
            "attachments": [],
            "created": self._now(),
        }
        if not self._sent(
            "create",
            "",
            {"project": project, **{name: ticket[name] for name in ("summary", "body", "labels", "assignee")}},
        ):
            return "", f"would create {project} {payload['summary']!r}", {}
        with self._locked():
            numbers = [
                int(name[len(project) + 1 : -len(".json")])
                for name in os.listdir(self.root())
                if name.startswith(project + "-")
                and name.endswith(".json")
                and name[len(project) + 1 : -len(".json")].isdigit()
            ]
            key = f"{project}-{1 + max(numbers or [0])}"
            self._save({"key": key, **ticket})
        if self.summary(key) != payload["summary"]:
            raise CockpitError(f"read-back: {key} does not carry the summary it was made with")
        steps["key"] = key
        out = key
        if payload.get("transition"):
            out += "; " + self._move(key, payload["transition"])
        return self.browse_url(key), out + " · read back", {"key": key}

    def _named(self, to: str) -> str:
        """The status that name means, in its own spelling: the case is the tracker's, not the asker's."""
        found = next((name for name in self.moves if name.lower() == str(to).strip().lower()), "")
        if not found:
            raise CockpitError(f"local tracker: '{to}' is not a status; it has {list(self.moves)}")
        return found

    def reachable(self, key: str, to: str) -> tuple:
        now = self.status(key)
        moves = [{"id": f"{now}>{name}", "name": name, "to": {"name": name}} for name in self.moves.get(now) or []]
        return next((row for row in moves if row["name"].lower() == str(to).strip().lower()), None), moves

    def _way(self, start: str, to: str) -> list:
        """The statuses from start to that one, the shortest way the moves allow; empty when there is none."""
        ways, seen = [[start]], {start}
        while ways:
            way = ways.pop(0)
            for name in self.moves.get(way[-1]) or []:
                if name == to:
                    return way[1:] + [name]
                if name not in seen:
                    seen.add(name)
                    ways.append(way + [name])
        return []

    def _move(self, key: str, to: str) -> str:
        target = self._named(to)
        start = self.status(key)
        if start == target:
            return f"{key} is already {start}"
        way = self._way(start, target)
        if not way:
            raise CockpitError(f"no transition means '{to}' from '{start}'; available: {self.moves.get(start) or []}")
        if not self._sent("transition", key, {"to": target, "through": way[:-1]}):
            return f"would move {key} → {target}"
        with self._change(key) as ticket:
            ticket["status"] = target
        now = self.status(key)
        if now != target:
            raise CockpitError(f"read-back: {key} is '{now}' after the move to '{target}'")
        through = f"from {start} through {', '.join(way[:-1])}: " if way[:-1] else ""
        return f"{through}{to} → {target} (status now {now})"

    def transition(self, intent, steps, key):
        payload = intent["payload"]
        out = self._move(key, payload["to"])
        if payload.get("assignee"):
            who = ME if payload["assignee"] == "me" else str(payload["assignee"])
            if self._sent("assign", key, {"assignee": who}):
                with self._change(key) as ticket:
                    ticket["assignee"] = who
            out += f"; assigned {payload['assignee']}"
        return self.browse_url(key), out, {}
