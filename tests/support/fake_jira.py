# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""A Jira REST stand-in for tests: the calls cockpit's tracker makes, served from memory on a local port."""

import json
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

# status: [(transition name, target status)]
WORKFLOW = {
    "Backlog": [("Start", "In Progress")],
    "In Progress": [("Ask for review", "In Review"), ("Park", "Backlog")],
    "In Review": [("Close", "Done")],
    "Done": [],
}


class Jira:
    def __init__(self, account="acct-1", components=("Core", "Edge"), sprint=77, drop_on_create=()):
        self.account = account
        self.components = list(components)
        self.sprint = sprint
        self.drop_on_create = set(
            drop_on_create
        )  # fields the create silently ignores, as a real tracker sometimes does
        self.issues = {}
        self.requests = []
        self.next_id = 100
        self.flatten = False
        self.fail = {}
        self.stamps = (
            False  # with it, a comment carries its writer and when it was written and edited, as the real tracker's do
        )
        self.ticks = 0

    def _stamp(self) -> dict:
        self.ticks += 1
        return {"updated": f"2026-01-01T00:{self.ticks // 60:02d}:{self.ticks % 60:02d}.000+0000"}

    def issue(self, key, status="Backlog"):
        self.issues.setdefault(key, {"key": key, "status": status, "comments": {}, "attachments": [], "fields": {}})
        return self.issues[key]

    def _id(self):
        self.next_id += 1
        return str(self.next_id)

    def handle(self, method, path, body, raw):
        parts = urlsplit(path)
        route, query = parts.path, parse_qs(parts.query)
        for rule, message in self.fail.items():
            if f"{method} {route}".startswith(rule):
                return 500, {"errorMessages": [message]}
        if route == "/rest/api/3/myself":
            return 200, {"accountId": self.account}
        match = re.fullmatch(r"/rest/api/3/issue/createmeta/([^/]+)/issuetypes(?:/(\d+))?", route)
        if match:
            if not match.group(2):
                return 200, {"issueTypes": [{"id": "10", "name": "Task"}, {"id": "11", "name": "Chore"}]}
            return 200, {
                "fields": [
                    {"fieldId": "components", "allowedValues": [{"name": name} for name in self.components]},
                    {"fieldId": "customfield_200", "schema": {"custom": "com.pyxis.greenhopper.jira:gh-sprint"}},
                ]
            }
        if route == "/rest/api/3/search/jql":
            return 200, {"issues": [{"fields": {"customfield_200": [{"id": self.sprint, "state": "active"}]}}]}
        match = re.fullmatch(r"/rest/api/(2|3)/issue", route)
        if match and method == "POST":
            key = f"{body['fields']['project']['key']}-{self._id()}"
            issue = self.issue(key)
            issue["fields"] = {name: value for name, value in body["fields"].items() if name not in self.drop_on_create}
            return 201, {"key": key}
        match = re.fullmatch(r"/rest/api/(2|3)/issue/([^/]+)(/.*)?", route)
        if not match:
            return 404, {"errorMessages": [f"no route {route}"]}
        issue = self.issues.get(match.group(2))
        if issue is None:
            return 404, {"errorMessages": [f"no issue {match.group(2)}"]}
        tail = match.group(3) or ""
        if not tail and method == "GET":
            fields = {"status": {"name": issue["status"]}, "attachment": issue["attachments"], **issue["fields"]}
            wanted = (query.get("fields") or [""])[0].split(",")
            return 200, {"key": issue["key"], "fields": {name: fields.get(name) for name in wanted if name}}
        if not tail and method == "PUT":
            issue["fields"].update(body["fields"])
            return 204, {}
        if tail == "/assignee":
            issue["fields"]["assignee"] = {"accountId": body["accountId"]}
            return 204, {}
        if tail == "/attachments":
            name = re.search(rb'filename="([^"]+)"', raw).group(1).decode()
            size = len(raw.split(b"\r\n\r\n", 1)[1].rsplit(b"\r\n--", 1)[0])
            made = {"id": self._id(), "filename": name, "size": size}
            issue["attachments"].append(made)
            return 200, [made]
        if tail == "/transitions" and method == "GET":
            return 200, {
                "transitions": [
                    {"id": f"{issue['status']}>{target}", "name": name, "to": {"name": target}}
                    for name, target in WORKFLOW[issue["status"]]
                ]
            }
        if tail == "/transitions":
            move = body["transition"]["id"]
            if not str(move).startswith(issue["status"] + ">"):
                return 400, {"errorMessages": ["transition not available"]}
            issue["status"] = move.split(">", 1)[1]
            return 204, {}
        if tail == "/comment" and method == "GET":
            return 200, {"comments": list(issue["comments"].values())}
        if tail == "/comment":
            made = self._id()
            issue["comments"][made] = {"id": made, "body": body["body"]}
            if self.stamps:
                now = self._stamp()["updated"]
                issue["comments"][made].update(
                    author={"accountId": self.account, "displayName": "The human"}, created=now, updated=now
                )
            return 201, {"id": made}
        match = re.fullmatch(r"/comment/(\d+)", tail)
        if match and match.group(1) in issue["comments"]:
            comment = issue["comments"][match.group(1)]
            if method == "PUT":
                comment["body"] = body["body"]
                if self.stamps:
                    comment.update(self._stamp())
                return 200, {"id": comment["id"]}
            shown = dict(comment)
            if self.flatten and isinstance(shown["body"], dict):
                shown["body"] = {"type": "doc", "content": []}
            return 200, shown
        return 404, {"errorMessages": [f"no route {method} {route}"]}


def _transcript(method, path, body, raw, headers) -> None:
    """When a transcript is being recorded (tests/support/forge_transcript.py), every request is kept there, answered or not."""
    import os

    if not os.environ.get("COCKPIT_FORGE_TRANSCRIPT"):
        return
    from tests.support.forge_transcript import tracker_request

    tracker_request(method, path, body, raw, headers)


def serve(jira: Jira):
    """Start the stand-in; (url, stop)."""

    class Handler(BaseHTTPRequestHandler):
        def _answer(self, method):
            length = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(length) if length else b""
            body = None
            if raw and "json" in (self.headers.get("Content-Type") or ""):
                body = json.loads(raw)
            jira.requests.append(
                {
                    "method": method,
                    "path": self.path,
                    "body": body,
                    "auth": self.headers.get("Authorization"),
                    "token_check": self.headers.get("X-Atlassian-Token"),
                }
            )
            _transcript(
                method,
                self.path,
                body,
                raw,
                {"auth": self.headers.get("Authorization"), "token_check": self.headers.get("X-Atlassian-Token")},
            )
            code, answer = jira.handle(method, self.path, body, raw)
            data = json.dumps(answer).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            self._answer("GET")

        def do_POST(self):
            self._answer("POST")

        def do_PUT(self):
            self._answer("PUT")

        def log_message(self, *_args):
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    # shutdown() waits for the serving loop to look up from its wait: at the default half second every test that
    # took the stand-in paid that at teardown
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True)
    thread.start()

    def stop():
        server.shutdown()
        server.server_close()

    return f"http://127.0.0.1:{server.server_address[1]}", stop
