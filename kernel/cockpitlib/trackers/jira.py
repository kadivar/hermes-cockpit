# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Jira as a tracker: its REST API with the human's credentials, or the same calls through Hermes's hosted connector.

`tracker.kind: jira` (`rest` is accepted as another name for it): Jira's REST API with the environment variables the
pack names (tracker.auth_env: [email, token]), never a file. `tracker.kind: connector` (the default): Hermes's hosted
Jira connector, signed in once with `hermes connectors connect jira`; no credential is in any shell or file here.

Every write is read back. A dry run reads (so what it prints carries real ids) and records the writes instead.
"""

import base64
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
import uuid

from ..errors import CockpitError
from . import base
from .base import Tracker


def adf(text: str) -> dict:
    """Plain text as a minimal Atlassian document: one paragraph per blank-line block."""
    return {
        "type": "doc",
        "version": 1,
        "content": [
            {"type": "paragraph", "content": [{"type": "text", "text": block}]}
            for block in str(text).split("\n\n")
            if block.strip()
        ],
    }


def adf_text(node) -> str:
    if isinstance(node, dict):
        return node.get("text", "") + "".join(adf_text(child) for child in node.get("content") or [])
    if isinstance(node, list):
        return "".join(adf_text(child) for child in node)
    return ""


def adf_count(node, kind: str) -> int:
    if isinstance(node, dict):
        return (node.get("type") == kind) + sum(adf_count(child, kind) for child in node.get("content") or [])
    if isinstance(node, list):
        return sum(adf_count(child, kind) for child in node)
    return 0


def comment_rows(found) -> list:
    """Jira's comments as the protocol's comment rows; what is not a comment with an id is left out."""
    rows = []
    for row in found or []:
        if not isinstance(row, dict) or not row.get("id"):
            continue
        author = row.get("author") if isinstance(row.get("author"), dict) else {}
        body = row.get("body")
        rows.append(
            {
                "id": str(row["id"]),
                "account": str(author.get("accountId") or ""),
                "author": str(author.get("displayName") or author.get("name") or "someone"),
                "updated": str(row.get("updated") or row.get("created") or ""),
                "created": str(row.get("created") or ""),
                "text": (adf_text(body) if isinstance(body, dict) else str(body or "")).strip(),
            }
        )
    return rows


# How many single steps a transition with no direct route tries, each undone if it does not lead on.
MOVE_THROUGH_TRIES = 3


class JiraTracker(Tracker):
    kind = "jira"
    noun = "Jira"
    HAS = base.CAPABILITIES

    def __init__(self, config, dry_run=False):
        self.config = config
        self.url = config["url"]
        self.dry_run = dry_run
        self.writes = []

    # ---- the protocol's reads, each made of the calls below
    def me(self) -> str:
        return self._myself()

    def status(self, key: str) -> str:
        return self._status(key)

    def comment_url(self, key: str, comment_id) -> str:
        return self.browse_url(key) + f"?focusedCommentId={comment_id}"

    def comments(self, key: str, since=None) -> list:
        found = (self._request("GET", f"/rest/api/3/issue/{key}/comment?maxResults={base.PAGE}") or {}).get("comments")
        return base.since_then(comment_rows(found), since)

    def summary(self, issue: str) -> str:
        return str(
            ((self._request("GET", f"/rest/api/3/issue/{issue}?fields=summary") or {}).get("fields") or {}).get(
                "summary"
            )
            or ""
        )

    def _auth(self) -> str:
        names = list(self.config.get("auth_env") or [])
        if len(names) != 2:
            raise CockpitError(
                "tracker.auth_env names the two environment variables that hold the tracker email and API token"
            )
        email, token = (os.environ.get(name) or "" for name in names)
        if not email or not token:
            raise CockpitError(f"the tracker credentials are not in this shell ({', '.join(names)})")
        return "Basic " + base64.b64encode(f"{email}:{token}".encode()).decode()

    def _request(self, method: str, path: str, body=None, raw=None, headers=None):
        if method != "GET":
            self.writes.append({"method": method, "path": path, "body": body})
            if self.dry_run:
                return {"dry_run": True}
        data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
        request = urllib.request.Request(self.url + path, data=data, method=method)  # noqa: S310 - the pack's own tracker.url
        request.add_header("Authorization", self._auth())
        request.add_header("Accept", "application/json")
        for key, value in (headers or {"Content-Type": "application/json"}).items():
            request.add_header(key, value)
        try:
            with urllib.request.urlopen(request, timeout=60) as answer:  # noqa: S310 - the pack's own tracker.url
                text = answer.read().decode("utf-8") or "{}"
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")[-300:]
            raise CockpitError(f"tracker {method} {path}: {exc.code} {detail}") from exc
        except (urllib.error.URLError, OSError) as exc:
            raise CockpitError(f"tracker {method} {path}: {exc}") from exc
        try:
            return json.loads(text)
        except ValueError:
            return {}

    def _body(self, payload):
        """(api version, body) from the intent's draft: a .json file is a ready document, any other text is wiki markup."""
        from ..paths import workspace

        if payload.get("body_file"):
            path = os.path.join(workspace(), payload["body_file"])
            text = open(path, encoding="utf-8").read()
            if path.endswith(".json"):
                return "3", json.loads(text)
            return "2", text
        return "2", str(payload.get("body") or "")

    # comments
    def _attachments(self, issue) -> dict:
        found = {}
        for row in (self._request("GET", f"/rest/api/3/issue/{issue}?fields=attachment").get("fields") or {}).get(
            "attachment"
        ) or []:
            if row.get("filename") and row.get("id") is not None:
                found[row["filename"]] = (str(row["id"]), int(row.get("size") or 0))
        return found

    def _upload(self, issue, path):
        from ..paths import workspace

        full = os.path.join(workspace(), path)
        name = os.path.basename(full)
        boundary = "----cockpit-" + uuid.uuid4().hex
        data = (
            (
                f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{name}"\r\n'
                "Content-Type: application/octet-stream\r\n\r\n"
            ).encode()
            + open(full, "rb").read()
            + f"\r\n--{boundary}--\r\n".encode()
        )
        found = self._request(
            "POST",
            f"/rest/api/3/issue/{issue}/attachments",
            body={"file": name},
            raw=data,
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}", "X-Atlassian-Token": "no-check"},
        )
        first = found[0] if isinstance(found, list) and found else {}
        return str(first.get("id") or "")

    def _link(self, body, ids: dict):
        """Every mention of an attached file's name links to it, and an Attachments line closes the comment."""
        if not ids:
            return body
        names = re.compile("|".join(re.escape(name) for name in sorted(ids, key=len, reverse=True)))
        href = {name: f"{self.url}/secure/attachment/{ids[name]}/{urllib.parse.quote(name)}" for name in ids}

        def walk(nodes):
            out = []
            for node in nodes:
                if not isinstance(node, dict):
                    out.append(node)
                    continue
                marks = node.get("marks") or []
                if (
                    node.get("type") == "text"
                    and node.get("text")
                    and not any(mark.get("type") == "link" for mark in marks)
                    and names.search(node["text"])
                ):
                    at = 0
                    for match in names.finditer(node["text"]):
                        if match.start() > at:
                            out.append({**node, "text": node["text"][at : match.start()]})
                        out.append(
                            {
                                **node,
                                "text": match.group(0),
                                "marks": marks + [{"type": "link", "attrs": {"href": href[match.group(0)]}}],
                            }
                        )
                        at = match.end()
                    if at < len(node["text"]):
                        out.append({**node, "text": node["text"][at:]})
                    continue
                if isinstance(node.get("content"), list):
                    node = {**node, "content": walk(node["content"])}
                out.append(node)
            return out

        links = [{"type": "text", "text": "Attachments: ", "marks": [{"type": "strong"}]}]
        for index, name in enumerate(ids):
            if index:
                links.append({"type": "text", "text": " · "})
            links.append({"type": "text", "text": name, "marks": [{"type": "link", "attrs": {"href": href[name]}}]})
        return {**body, "content": walk(body.get("content") or []) + [{"type": "paragraph", "content": links}]}

    def find_comment(self, issue, title):
        for row in self._request("GET", f"/rest/api/3/issue/{issue}/comment?maxResults=100").get("comments") or []:
            first = (
                ((row.get("body") or {}).get("content") or [{}])[0]
                if isinstance(row.get("body"), dict)
                else str(row.get("body") or "")
            )
            text = adf_text(first) if isinstance(first, dict) else first
            if text.strip().lower().startswith(title.lower()):
                return str(row["id"])
        return ""

    def comment(self, intent, steps):
        payload = intent["payload"]
        issue = payload.get("issue") or intent["ticket"]
        version, body = self._body(payload)
        comment_id = payload.get("comment_id") or steps.get("from_comment") or ""
        if payload.get("probe_title") and not comment_id:
            found = self.find_comment(issue, payload["probe_title"])
            if found:
                raise CockpitError(
                    f"{issue} already has a comment starting with '{payload['probe_title']}' (id {found}): "
                    f"amend the intent with --comment-id {found} so this updates it"
                )
        names, ids = [], {}
        have = self._attachments(issue) if payload.get("attach") else {}
        from ..paths import workspace

        for path in payload.get("attach") or []:
            name = os.path.basename(path)
            size = os.path.getsize(os.path.join(workspace(), path))
            if have.get(name, ("", -1))[1] != size and f"attach:{path}" not in steps:
                have[name] = (self._upload(issue, path), size)
            steps[f"attach:{path}"] = name
            names.append(name)
            if have.get(name, ("",))[0]:
                ids[name] = have[name][0]
        if version == "3":
            body = self._link(body, ids)
        elif names:
            body = body.rstrip("\n") + "\n\nAttachments: " + ", ".join(f"[^{name}]" for name in names) + "\n"
        base = f"/rest/api/{version}/issue/{issue}/comment"
        made = (
            self._request("PUT", f"{base}/{comment_id}", {"body": body})
            if comment_id
            else self._request("POST", base, {"body": body})
        )
        out = f"{'updated' if comment_id else 'posted'} on {issue}"
        if self.dry_run:
            return self.browse_url(issue), "would be " + out, {}
        made_id = str(made.get("id") or comment_id)
        back = self._request("GET", f"/rest/api/3/issue/{issue}/comment/{made_id}")
        if str(back.get("id")) != made_id:
            raise CockpitError("read-back: the comment is not readable after the post")
        if comment_id and made_id != str(comment_id):
            raise CockpitError(f"read-back: a new comment {made_id} was made instead of updating {comment_id}")
        if version == "3" and adf_count(body, "expand") != adf_count(back.get("body"), "expand"):
            raise CockpitError("read-back: the tracker flattened the comment's expand blocks")
        return (
            self.browse_url(issue),
            f"{out} (comment {made_id}, read back)" + (f" · attached {', '.join(names)}" if names else ""),
            {"comment": made_id},
        )

    # issues
    def _myself(self) -> str:
        found = str(self._request("GET", "/rest/api/3/myself").get("accountId") or "")
        if not found:
            raise CockpitError("the tracker did not say who you are (/myself)")
        return found

    def _meta(self, project, kind) -> dict:
        types = (
            self._request("GET", f"/rest/api/3/issue/createmeta/{project}/issuetypes?maxResults=50").get("issueTypes")
            or []
        )
        found = next((row for row in types if str(row.get("name")).lower() == kind.lower()), None)
        if not found:
            raise CockpitError(f"{project} has no issue type {kind}")
        fields = (
            self._request("GET", f"/rest/api/3/issue/createmeta/{project}/issuetypes/{found['id']}?maxResults=200").get(
                "fields"
            )
            or []
        )
        return {row["fieldId"]: row for row in fields}

    def _active_sprint(self, project, field):
        query = urllib.parse.quote(f"project = {project} AND sprint in openSprints()")
        for row in (
            self._request("GET", f"/rest/api/3/search/jql?jql={query}&fields={field}&maxResults=5").get("issues") or []
        ):
            for sprint in (row.get("fields") or {}).get(field) or []:
                if sprint.get("state") == "active":
                    return sprint["id"]
        raise CockpitError(f"no active sprint in {project}")

    def create(self, intent, steps):
        payload = intent["payload"]
        project = payload.get("project") or self.config.get("project")
        kind = payload.get("issue_type") or self.config.get("issue_type") or "Task"
        version, description = self._body(payload) if (payload.get("body_file") or payload.get("body")) else ("2", "")
        fields = {
            "project": {"key": project},
            "summary": payload["summary"],
            "issuetype": {"name": kind},
            "description": description,
        }
        if payload.get("labels"):
            fields["labels"] = payload["labels"]
        meta = self._meta(project, kind) if (payload.get("component") or payload.get("sprint")) else {}
        sprint_field = ""
        if payload.get("component"):
            allowed = [row.get("name") for row in (meta.get("components") or {}).get("allowedValues") or []]
            hit = next((name for name in allowed if name and name.lower() == payload["component"].lower()), "")
            if not hit:
                raise CockpitError(f"component '{payload['component']}' is not one of {allowed}")
            fields["components"] = [{"name": hit}]
        if payload.get("assignee"):
            fields["assignee"] = {"accountId": self._myself() if payload["assignee"] == "me" else payload["assignee"]}
        if payload.get("sprint"):
            sprint_field = next(
                (
                    key
                    for key, row in meta.items()
                    if str((row.get("schema") or {}).get("custom") or "").endswith(":gh-sprint")
                ),
                "",
            )
            if not sprint_field:
                raise CockpitError(f"{project}/{kind} has no sprint field")
            fields[sprint_field] = (
                self._active_sprint(project, sprint_field) if payload["sprint"] == "active" else int(payload["sprint"])
            )
        made = self._request("POST", f"/rest/api/{version}/issue", {"fields": fields})
        if self.dry_run:
            return "", f"would create {project} {payload['summary']!r}", {}
        key = str(made.get("key") or "")
        if not key:
            raise CockpitError("the tracker made no issue key")
        wanted = {name: fields[name] for name in ("components", "assignee", sprint_field) if name and name in fields}
        missing = self._missing(key, wanted)
        out = key
        if missing:
            self._request("PUT", f"/rest/api/3/issue/{key}", {"fields": missing})
            still = self._missing(key, wanted)
            if still:
                raise CockpitError(f"read-back: {', '.join(still)} still empty on {key}")
            out += f" (set again after create: {', '.join(missing)})"
        steps["key"] = key
        if payload.get("transition"):
            out += "; " + self._move(key, payload["transition"])
        return self.browse_url(key), out + " · read back", {"key": key}

    def _missing(self, key, wanted) -> dict:
        if not wanted:
            return {}
        back = self._request("GET", f"/rest/api/3/issue/{key}?fields={','.join(wanted)}").get("fields") or {}
        return {
            name: value
            for name, value in wanted.items()
            if not back.get(name)
            or (name == "assignee" and (back.get(name) or {}).get("accountId") != value["accountId"])
        }

    def reachable(self, issue, to):
        want = to.lower()
        moves = self._request("GET", f"/rest/api/3/issue/{issue}/transitions").get("transitions") or []
        hits = [
            row
            for row in moves
            if any(
                name and (name.lower() == want or want in name.lower())
                for name in (row.get("name", ""), (row.get("to") or {}).get("name", ""))
            )
        ]
        exact = [
            row
            for row in hits
            if row.get("name", "").lower() == want or (row.get("to") or {}).get("name", "").lower() == want
        ]
        if len(hits) > 1 and not exact:
            raise CockpitError(f"'{to}' is ambiguous: {[row['name'] for row in hits]}; name one exactly")
        return (exact or hits or [None])[0], moves

    def _status_category(self, issue) -> str:
        """new, indeterminate or done for the issue's status; '' when Jira does not say."""
        status = (self._request("GET", f"/rest/api/3/issue/{issue}?fields=status").get("fields") or {}).get(
            "status"
        ) or {}
        return str((status.get("statusCategory") or {}).get("key") or "")

    def _status(self, issue) -> str:
        return str(
            (
                (self._request("GET", f"/rest/api/3/issue/{issue}?fields=status").get("fields") or {}).get("status")
                or {}
            ).get("name")
            or ""
        )

    def _move(self, issue, to) -> str:
        move, moves = self.reachable(issue, to)
        if move is None:
            return self._move_through(issue, to, moves)
        return self._take(issue, to, move)

    def _take(self, issue, to, move) -> str:
        self._request("POST", f"/rest/api/3/issue/{issue}/transitions", {"transition": {"id": move["id"]}})
        if self.dry_run:
            return f"would move {issue} → {move['name']}"
        now = self._status(issue)
        target = (move.get("to") or {}).get("name") or move["name"]
        if now.lower() != target.lower():
            raise CockpitError(f"read-back: {issue} is '{now}' after '{move['name']}'")
        return f"{to} → {move['name']} (status now {now})"

    def _move_through(self, issue, to, moves) -> str:
        """No transition reaches `to` from here (a workflow that goes To Plan → To Do → In Progress, asked for In
        Progress). Jira says what a status leads to only once the issue is in it, so this takes one step at a time:
        a status that is not done — not started first — and on from there when `to` is reachable. A step that does
        not lead there is undone before the next is tried. A done status, or one Jira does not categorise, is never a
        way through: getting there can close, release or archive the issue."""
        start = self._status(issue)
        if start.lower() == str(to).lower():
            # Already there (a second card asking for the same start): moving away to come back would only churn.
            return f"{issue} is already {start}"

        def category(row):
            return str((((row.get("to") or {}).get("statusCategory")) or {}).get("key") or "")

        # Only a status Jira says is not started or under way: one it does not categorise is never a way through.
        # And never backwards: from a status under way, a step back to not started (In Progress → To Plan) is a move
        # the owner would have to undo, so only a status at least as far along as this one is a way through.
        rank = {"new": 0, "indeterminate": 1}
        here = rank.get(self._status_category(issue), 2)
        steps = [
            row
            for row in moves
            if category(row) in rank
            and rank[category(row)] >= here
            and str((row.get("to") or {}).get("name") or "").lower() != start.lower()
        ]
        steps.sort(key=lambda row: 0 if category(row) == "new" else 1)
        if not steps:
            raise CockpitError(
                f"no transition means '{to}' from '{start}'; available: "
                f"{[(row.get('name'), (row.get('to') or {}).get('name')) for row in moves]}"
            )
        if self.dry_run:
            return f"would move {issue} → {steps[0]['name']}, then → {to} if the workflow allows it from there"
        tried = []
        for step in steps[:MOVE_THROUGH_TRIES]:
            self._take(issue, step["name"], step)
            middle = str((step.get("to") or {}).get("name") or step["name"])
            reached, _moves = self.reachable(issue, to)
            if reached is not None:
                return f"from {start} through {middle}: {self._take(issue, to, reached)}"
            tried.append(middle)
            back, _moves = self.reachable(issue, start)
            if back is None:
                raise CockpitError(
                    f"no way from '{start}' to '{to}' through '{tried[-1]}', and no way back: {issue} is at '{tried[-1]}'"
                )
            self._take(issue, start, back)
        raise CockpitError(
            f"no transition means '{to}' from '{start}', nor from {tried} after one step there; "
            f"{issue} is back at '{start}'"
        )

    def transition(self, intent, steps, issue):
        payload = intent["payload"]
        out = self._move(issue, payload["to"])
        if payload.get("assignee"):
            account = self._myself() if payload["assignee"] == "me" else payload["assignee"]
            self._request("PUT", f"/rest/api/3/issue/{issue}/assignee", {"accountId": account})
            if not self.dry_run:
                back = (self._request("GET", f"/rest/api/3/issue/{issue}?fields=assignee").get("fields") or {}).get(
                    "assignee"
                ) or {}
                if back.get("accountId") != account:
                    raise CockpitError(f"read-back: {issue} is not assigned to {account}")
            out += f"; assigned {payload['assignee']}"
        return self.browse_url(issue), out, {}


class ConnectorTracker(JiraTracker):
    """Jira through Hermes's hosted connector. The REST tracker's logic is kept whole — the transition matching, the
    read-backs, the attachment links, the dry run — and each REST call it makes is made as the connector operation
    that does the same thing. The connector answers with Jira's own JSON, so nothing above this layer changes. A
    call it has no operation for is refused, never guessed."""

    kind = "connector"

    def __init__(self, config, dry_run=False, call=None):
        super().__init__(config, dry_run)
        self.connector = str(config.get("connector") or "jira")
        if call is None:
            from ..connector import call
        self._call = call

    def _auth(self) -> str:
        raise CockpitError("the connector tracker holds no credential")

    def _op(self, tool, arguments):
        return self._call(self.connector, tool, arguments) or {}

    def _request(self, method: str, path: str, body=None, raw=None, headers=None):
        if method != "GET":
            self.writes.append({"method": method, "path": path, "body": body})
            if self.dry_run:
                return {"dry_run": True}
        route, query = urllib.parse.urlsplit(path).path, urllib.parse.parse_qs(urllib.parse.urlsplit(path).query)
        first = lambda name: (query.get(name) or [""])[0]  # noqa: E731
        issue = re.fullmatch(r"/rest/api/[23]/issue/([^/]+)(?:/(comment|transitions|assignee)(?:/([^/]+))?)?", route)
        if method == "GET" and route == "/rest/api/3/myself":
            return self._op("GET_CURRENT_USER", {})
        if method == "GET" and route == "/rest/api/3/search/jql":
            arguments = {"jql": first("jql"), "max_results": int(first("maxResults") or 50)}
            if first("fields"):
                arguments["fields"] = first("fields").split(",")
            return self._op("SEARCH_FOR_ISSUES_USING_JQL_GET", arguments)
        if method == "POST" and re.fullmatch(r"/rest/api/[23]/issue", route):
            return self._create(body or {})
        if not issue:
            raise CockpitError(f"the connector tracker has no operation for {method} {route}")
        key, part, item = issue.groups()
        if part is None and method == "GET":
            arguments = {"issue_id_or_key": key}
            if first("fields"):
                arguments["fields"] = first("fields").split(",")
            return self._op("GET_ISSUE", arguments)
        if part is None and method == "PUT":
            return self._op("EDIT_ISSUE", {"issue_id_or_key": key, "fields": (body or {}).get("fields") or {}})
        if part == "comment" and method == "GET" and item:
            return self._op("GET_COMMENT", {"issue_id_or_key": key, "comment_id": item})
        if part == "comment" and method == "GET":
            return self._op(
                "LIST_ISSUE_COMMENTS", {"issue_id_or_key": key, "max_results": int(first("maxResults") or 50)}
            )
        if part == "comment" and method in ("POST", "PUT"):
            text = (body or {}).get("body")
            # A ready document (ADF) goes as the body itself; text goes as the comment, which the connector renders.
            words = (
                {"additional_properties": {"body": text}, "text": adf_text(text)}
                if isinstance(text, dict)
                else {"text": str(text or "")}
            )
            if method == "POST":
                arguments = {"issue_id_or_key": key, "comment": words["text"]}
                tool = "ADD_COMMENT"
            else:
                arguments = {"issue_id_or_key": key, "comment_id": item, "comment_text": words["text"]}
                tool = "UPDATE_COMMENT"
            if "additional_properties" in words:
                arguments["additional_properties"] = words["additional_properties"]
            return self._op(tool, arguments)
        if part == "transitions" and method == "GET":
            return self._op("GET_TRANSITIONS", {"issue_id_or_key": key})
        if part == "transitions" and method == "POST":
            move = str(((body or {}).get("transition") or {}).get("id") or "")
            return self._op("TRANSITION_ISSUE", {"issue_id_or_key": key, "transition_id_or_name": move})
        if part == "assignee" and method == "PUT":
            return self._op(
                "ASSIGN_ISSUE", {"issue_id_or_key": key, "account_id": str((body or {}).get("accountId") or "")}
            )
        raise CockpitError(f"the connector tracker has no operation for {method} {route}")

    def _create(self, body):
        fields = dict(body.get("fields") or {})
        arguments = {
            "project_key": str((fields.pop("project", None) or {}).get("key") or ""),
            "summary": str(fields.pop("summary", "") or ""),
            "issue_type": str((fields.pop("issuetype", None) or {}).get("name") or ""),
        }
        description = fields.pop("description", None)
        if description:
            arguments["description"] = description
        if fields.get("labels"):
            arguments["labels"] = fields.pop("labels")
        if (fields.get("assignee") or {}).get("accountId"):
            arguments["assignee"] = fields.pop("assignee")["accountId"]
        if fields:  # components by name, the sprint field: Jira's own field shapes, set as they are
            arguments["additional_properties"] = json.dumps(fields)
        return self._op("CREATE_ISSUE", arguments)

    def _upload(self, issue, path):
        from ..paths import workspace

        full = os.path.join(workspace(), path)
        self.writes.append(
            {"method": "POST", "path": f"connector ADD_ATTACHMENT {issue}", "body": {"file": os.path.basename(full)}}
        )
        if self.dry_run:
            return ""
        found = self._op("ADD_ATTACHMENT", {"issue_key": issue, "file_to_upload": full})
        first = found[0] if isinstance(found, list) and found else (found if isinstance(found, dict) else {})
        return str(first.get("id") or "")

    def _meta(self, project, kind) -> dict:
        found = self._op(
            "GET_ISSUE_CREATE_METADATA",
            {"projectKeys": [project], "issuetypeNames": [kind], "expand": "projects.issuetypes.fields"},
        )
        types = [
            row
            for item in found.get("projects") or []
            for row in item.get("issuetypes") or []
            if str(row.get("name")).lower() == kind.lower()
        ]
        if not types:
            raise CockpitError(f"{project} has no issue type {kind}")
        return {key: {**row, "fieldId": key} for key, row in (types[0].get("fields") or {}).items()}

    def _active_sprint(self, project, field):
        # The connector's search answers a summary of each issue without custom fields: find an issue in an open
        # sprint, then read the sprint field off the issue itself.
        query = f"/rest/api/3/search/jql?jql={urllib.parse.quote(f'project = {project} AND sprint in openSprints()')}&maxResults=5"
        for row in self._request("GET", query).get("issues") or []:
            sprints = (
                (self._op("GET_ISSUE", {"issue_id_or_key": row.get("key"), "fields": [field]}).get("fields") or {}).get(
                    field
                )
            ) or []
            for sprint in sprints:
                if sprint.get("state") == "active":
                    return sprint["id"]
        raise CockpitError(f"no active sprint in {project}")
