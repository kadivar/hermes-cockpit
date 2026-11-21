#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The forge of a replay: a quiet one. A read is answered from the recorded reads, a write is refused, nothing leaves.

REPLAY_FORGE_READS names the recorded reads ({"login": …, "pulls": {"owner/name#7": {…}}}), REPLAY_CALLS the file every
call is appended to, REPLAY_VIEW the view that was being captured when the call was made.
"""

import json
import os
import re
import sys

LISTS = (
    "comments",
    "reviews",
    "files",
    "commits",
    "pulls",
    "labels",
    "jobs",
    "issues",
    "assignees",
    "reactions",
    "requested_reviewers",
)
THREADS = {"data": {"repository": {"pullRequest": {"reviewThreads": {"nodes": []}}}}}


def note(kind: str, what: str) -> None:
    path = os.environ.get("REPLAY_CALLS")
    if not path:
        return
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(
            json.dumps({"tool": "gh", "kind": kind, "what": what, "view": os.environ.get("REPLAY_VIEW") or ""}) + "\n"
        )


def fail(message: str) -> None:
    print(message, file=sys.stderr)
    sys.exit(1)


def reads() -> dict:
    try:
        found = json.load(open(os.environ.get("REPLAY_FORGE_READS") or "", encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return found if isinstance(found, dict) else {}


def pull(recorded: dict, owner: str, name: str, number: str):
    """The recorded pull request: by its full name, or by its repo name when the record kept no URL."""
    pulls = recorded.get("pulls") or {}
    return pulls.get(f"{owner}/{name}#{number}") or pulls.get(f"*/{name}#{number}")


def rest(path: str):
    """A quiet forge's answer to one read: the pull request as its record last saw it, and nothing new anywhere."""
    recorded = reads()
    plain = path.split("?", 1)[0].strip("/")
    if plain == "user":
        return {"login": recorded.get("login") or "replay-human"}
    if plain.startswith("search/"):
        return {"items": [], "total_count": 0}
    one = re.fullmatch(r"repos/([^/]+)/([^/]+)/pulls/(\d+)", plain)
    if one:
        found = pull(recorded, *one.groups())
        if found is None:
            fail(f"HTTP 404: replay has no recorded read of {plain}")
        return found
    last = plain.rsplit("/", 1)[-1]
    if last == "check-runs":
        return {"check_runs": [], "total_count": 0}
    if last == "status":
        return {"statuses": [], "state": "pending"}
    if last == "runs":
        return {"workflow_runs": [], "total_count": 0}
    if last in LISTS:
        return []
    fail(f"HTTP 404: replay has no recorded read of {plain}")


def api(words: list) -> None:
    method, body, path, include, index = "GET", None, "", False, 0
    while index < len(words):
        word = words[index]
        if word in ("--method", "-X"):
            method = words[index + 1].upper()
            index += 2
        elif word == "--input":
            try:
                body = json.load(open(words[index + 1], encoding="utf-8"))
            except (OSError, ValueError):
                body = {}
            index += 2
        elif word in ("-H", "-f", "-F", "--jq", "-q", "--hostname", "--cache", "-t", "--template"):
            if word in ("-f", "-F") and method == "GET" and path != "graphql":
                method = "POST"  # as gh does: a field makes the call a POST unless a method was named
            index += 2
        elif word in ("-i", "--include"):
            include = True
            index += 1
        elif word.startswith("-"):
            index += 1
        else:
            path = path or word
            index += 1
    if path == "graphql":
        query = str((body or {}).get("query") or "")
        if not query.lstrip().startswith("query"):
            note("write", "GRAPHQL mutation")
            fail("replay: a write to the forge is refused")
        note("read", "GRAPHQL query")
        print(json.dumps(THREADS if "reviewThreads" in query else {"data": {}}))
        return
    if method != "GET":
        note("write", f"{method} {path}")
        fail("replay: a write to the forge is refused")
    note("read", f"GET {path}")
    answer = rest(path)
    if include:
        print('HTTP/2.0 200 OK\nEtag: W/"replay"\n\n' + json.dumps(answer))
        return
    print(json.dumps(answer))


READ_VERBS = {
    ("pr", "list"),
    ("pr", "view"),
    ("pr", "diff"),
    ("pr", "checks"),
    ("run", "list"),
    ("run", "view"),
    ("auth", "status"),
    ("repo", "view"),
    ("issue", "list"),
    ("issue", "view"),
}


def main(argv: list) -> None:
    if argv[:1] == ["api"]:
        api(argv[1:])
        return
    verb = tuple(argv[:2])
    if verb not in READ_VERBS:
        note("write", " ".join(argv[:2]))
        fail("replay: this forge command is refused")
    note("read", " ".join(argv[:2]))
    if verb in (("pr", "list"), ("run", "list"), ("issue", "list")) and "--json" in argv:
        print("[]")
        return
    fail("replay: no recorded read of this forge command")


if __name__ == "__main__":
    main(sys.argv[1:])
