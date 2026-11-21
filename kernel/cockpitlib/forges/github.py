# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""GitHub, as the human's own `gh` login: REST and GraphQL through `gh api`, bodies as JSON files.

A dry run still reads (so what it prints carries real ids) and records every write instead of sending it.
`forge.host` names a GitHub Enterprise host; without it this is github.com and `gh` is called with no host at all.
"""

import json
import os
import subprocess
import tempfile
import urllib.parse

from ..errors import CockpitError
from ..store import dump_json
from . import base
from .base import Forge

HOST = "github.com"
THREADS = (
    "query($o:String!,$r:String!,$n:Int!){repository(owner:$o,name:$r){pullRequest(number:$n){reviewThreads(first:100)"
    "{nodes{id isResolved isOutdated comments(first:100){nodes{databaseId url createdAt author{login}}}}}}}}"
)
RESOLVE = "mutation($id:ID!){resolveReviewThread(input:{threadId:$id}){thread{isResolved}}}"
ADD_THREAD = (
    "mutation($review:ID!,$path:String!,$body:String!,$line:Int!,$side:DiffSide){addPullRequestReviewThread(input:"
    "{pullRequestReviewId:$review,path:$path,body:$body,line:$line,side:$side}){thread{id comments(first:1){nodes{databaseId}}}}}"
)
READY = "mutation($id:ID!){markPullRequestReadyForReview(input:{pullRequestId:$id}){pullRequest{isDraft}}}"
GREEN = ("success", "skipped", "neutral")


def _seg(value) -> str:
    """A name or an id as one segment of an API address: a label with a space or a slash is sent as that label, never
    as two words or a deeper path. Letters, digits and `-._~` stand as they are."""
    return urllib.parse.quote(str(value), safe="")


def _ref(value) -> str:
    """A branch or a commit inside an API address: its slashes stay (a branch is named with them), and whatever would
    end the path or start another query field (`#`, `?`, `&`, a space, `%`) is encoded."""
    return urllib.parse.quote(str(value), safe="/")


LISTED = "number,title,body,headRefName,headRefOid,baseRefName,url,createdAt,mergedAt,author,files"

# The writes of GitHub's own CLI. A lane's forge writes go through the outbox, so these are refused for every lane of
# every pack, whichever forge the pack publishes to. gh api with a field or an input file is a POST unless told otherwise.
CLI_DENY = (
    r"\bgh\s+pr\s+(create|comment|review|edit|merge|ready|close|reopen|lock|unlock)\b",
    r"\bgh\s+release\s+(create|edit|delete|upload|delete-asset)\b",
    r"\bgh\s+api\b.*\s(--method|-X)\s*(POST|PUT|PATCH|DELETE)\b",
    r"\bgh\s+issue\s+(create|comment|edit|close|reopen|delete|transfer|lock|unlock|pin|unpin|develop)\b",
    r"\bgh\s+workflow\s+(run|enable|disable)\b",
    r"\bgh\s+run\s+(rerun|cancel|delete)\b",
    r"\bgh\s+repo\s+(create|delete|edit|fork|rename|archive|unarchive|sync|set-default|deploy-key)\b",
    r"\bgh\s+label\s+(create|edit|delete|clone)\b",
    r"\bgh\s+(secret|variable)\s+(set|delete|remove)\b",
    r"\bgh\s+gist\s+(create|edit|delete)\b",
    r"\bgh\s+api\b.*\s(-f|-F|--field|--raw-field|--input)(\s|=)",
    r"\bgh\s+api\b.*\bmutation\b",
)


class GitHubForge(Forge):
    kind = "github"
    default_hosts = (HOST,)
    host = HOST

    def __init__(self, pack, dry_run: bool = False, runner=None):
        forge = (pack or {}).get("forge") or {}
        self.org = forge.get("org") or ""
        self.human_login = forge.get("human_login") or ""
        self.host = forge.get("host") or HOST
        self.dry_run = dry_run
        self.runner = runner or subprocess.run
        self.writes = []
        self._me = ""

    def _gh(self, args, body=None):
        path = ""
        if body is not None:
            handle = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8")
            json.dump(body, handle)
            handle.close()
            path = handle.name
            args = [*args, "--input", path]
        try:
            done = self._paced([*self._api(), *args])
        except OSError as exc:
            raise CockpitError(f"gh: {exc}") from exc
        finally:
            if path:
                os.unlink(path)
        if done.returncode != 0:
            raise CockpitError(
                f"gh api {' '.join(args[:3])}: {(done.stderr or done.stdout or 'failed').strip()[-300:]}"
            )
        text = (done.stdout or "").strip()
        try:
            return json.loads(text) if text else {}
        except ValueError:
            return text

    def _api(self) -> list:
        """`gh api`, on the pack's own host when it is not github.com."""
        return ["gh", "api"] if self.host == HOST else ["gh", "api", "--hostname", self.host]

    def _cli_repo(self, repo: str) -> str:
        """The repo as gh's --repo takes it: the host comes first when it is not github.com."""
        return self.repo(repo) if self.host == HOST else f"{self.host}/{self.repo(repo)}"

    def _paced(self, argv):
        """Run gh. GitHub's secondary rate limit refuses a burst with a 403 that names scraping or the secondary limit,
        with the hourly quota untouched, and asks for a pause of a minute or more. One new try after a few seconds
        settles a short burst. A second refusal starts a pause every cockpit process keeps (the watches, the lanes'
        commands, a publish): until it is over a call fails at once and says when to try again, instead of asking
        GitHub again and keeping the limit alive. The Desktop gives a request thirty seconds, so a publish answers
        well inside that: a wait longer than the Desktop's reads there as a lost connection."""
        until = self._pause_until()
        if until > self.clock():
            raise CockpitError(self._pause_said(until))
        done = self.runner(argv, capture_output=True, text=True, check=False)
        if not self._refused(done):
            return done
        self.pause(self.retry_after)
        done = self.runner(argv, capture_output=True, text=True, check=False)
        if not self._refused(done):
            return done
        until = self.clock() + self.pause_seconds
        self._set_pause(until)
        raise CockpitError(self._pause_said(until))

    @staticmethod
    def _refused(done) -> bool:
        said = f"{done.stderr or ''}{done.stdout or ''}".lower()
        return done.returncode != 0 and "403" in said and ("secondary rate limit" in said or "scraping github" in said)

    @staticmethod
    def _pause_said(until: float) -> str:
        import time

        return (
            "GitHub is refusing requests for a moment (its secondary rate limit, not the hourly quota): "
            f"try again after {time.strftime('%H:%M:%S', time.localtime(until))}"
        )

    @staticmethod
    def _pause_file() -> str:
        from ..paths import watch_dir

        return os.path.join(watch_dir(), "forge-pause.json")

    def _pause_until(self) -> float:
        try:
            return float(json.load(open(self._pause_file(), encoding="utf-8")).get("until") or 0)
        except Exception:  # noqa: BLE001 - no file, no workspace bound, or a damaged file: no pause is known
            return 0.0

    def _set_pause(self, until: float) -> None:
        try:
            path = self._pause_file()
            os.makedirs(os.path.dirname(path), exist_ok=True)
            dump_json(path, {"until": until})
        except Exception:  # noqa: BLE001, S110 - the pause is advice to the other processes; this call still says it
            pass

    retry_after = 4  # seconds before the one new try
    pause_seconds = 90  # how long every process leaves GitHub alone after a second refusal
    pause = staticmethod(__import__("time").sleep)
    clock = staticmethod(__import__("time").time)

    # ---- identity
    def capabilities(self) -> frozenset:
        return frozenset(base.CAPABILITIES)

    def hosts(self) -> list:
        return [self.host]

    @classmethod
    def cli_deny(cls) -> tuple:
        return CLI_DENY

    def repo(self, name: str) -> str:
        return name if "/" in name else f"{self.org}/{name}"

    # ---- the transport: GitHub's REST paths and GraphQL, which the operations below are made of
    def get(self, path: str):
        return self._gh([path])

    def get_if_changed(self, path: str, etag: str = "") -> dict:
        """A conditional read: {changed, etag, body}. An unchanged answer (304) is not counted against the rate limit, so
        a watcher can ask every pass; `gh` exits 1 on it, so the status line decides."""
        args = ["-i", path, *(["-H", f"If-None-Match: {etag}"] if etag else [])]
        try:
            done = self._paced([*self._api(), *args])
        except OSError as exc:
            raise CockpitError(f"gh: {exc}") from exc
        head, _, text = (done.stdout or "").replace("\r\n", "\n").partition("\n\n")
        status = (head.split("\n", 1)[0].split() + ["", ""])[1]
        if status == "304":
            return {"changed": False, "etag": etag, "body": None}
        if done.returncode != 0:
            raise CockpitError(f"gh api {path}: {(done.stderr or done.stdout or 'failed').strip()[-300:]}")
        found = next(
            (line.split(":", 1)[1].strip() for line in head.split("\n") if line.lower().startswith("etag:")), ""
        )
        try:
            body = json.loads(text) if text.strip() else {}
        except ValueError:
            body = text
        return {"changed": True, "etag": found, "body": body}

    def write(self, method: str, path: str, body=None):
        self.writes.append({"method": method, "path": path, "body": body})
        if self.dry_run:
            return {"dry_run": True}
        return self._gh([path, "--method", method], body if body is not None else {})

    def graphql(self, query: str, variables: dict, write: bool = False):
        if write:
            self.writes.append({"method": "GRAPHQL", "path": "graphql", "body": variables})
            if self.dry_run:
                return {"dry_run": True}
        found = self._gh(["graphql"], {"query": query, "variables": variables})
        if isinstance(found, dict) and found.get("errors"):
            raise CockpitError(f"graphql: {found['errors'][0].get('message')}")
        return (found or {}).get("data") or {}

    def me(self) -> str:
        if not self._me:
            self._me = self.human_login or str((self.get("user") or {}).get("login") or "")
        return self._me

    def url(self, repo: str, number=None) -> str:
        page = f"https://{self.host}/{self.repo(repo)}"
        return f"{page}/pull/{number}" if number else page

    # ---- pull requests
    def pr(self, repo: str, number) -> dict:
        return self.get(f"repos/{self.repo(repo)}/pulls/{_seg(number)}") or {}

    def pr_for_head(self, repo: str, head: str, base: str = "") -> dict:
        owner = self.repo(repo).split("/")[0]
        query = f"repos/{self.repo(repo)}/pulls?state=open&head={owner}:{_ref(head)}" + (
            f"&base={_ref(base)}" if base else ""
        )
        found = self.get(query) or []
        return found[0] if isinstance(found, list) and found else {}

    def open_prs_for_branch(self, repo: str, branch: str) -> list:
        owner = self.repo(repo).split("/", 1)[0]
        return self.get(f"repos/{self.repo(repo)}/pulls?state=open&head={owner}:{_ref(branch)}") or []

    def list_prs(self, repo: str, state: str, base: str = "", runner=None) -> list:
        from ..gh_cli import ForgeError, run_json

        args = ["gh", "pr", "list", "--repo", self._cli_repo(repo), "--state", state, "--limit", "40", "--json", LISTED]
        if base:
            args.extend(["--base", base])
        try:
            data = run_json(args, runner=runner)
        except json.JSONDecodeError as exc:
            raise ForgeError(str(exc)) from exc
        return data if isinstance(data, list) else []

    def create_pr(self, repo: str, title: str, body: str, head: str, base: str) -> dict:
        return self.write(
            "POST",
            f"repos/{self.repo(repo)}/pulls",
            {"title": title, "body": body, "head": head, "base": base, "draft": False},
        )

    def update_pr(self, repo: str, number, fields: dict) -> dict:
        return self.write("PATCH", f"repos/{self.repo(repo)}/pulls/{_seg(number)}", fields)

    def mark_ready(self, repo: str, number) -> None:
        found = self.pr(repo, number)
        if found.get("draft"):
            self.graphql(READY, {"id": found.get("node_id")}, write=True)

    # ---- labels and people
    def labels(self, repo: str, number) -> list:
        return sorted(row["name"] for row in self.get(f"repos/{self.repo(repo)}/issues/{_seg(number)}/labels") or [])

    def repo_labels(self, repo: str) -> list:
        return [row["name"] for row in self.get(f"repos/{self.repo(repo)}/labels?per_page=100") or []]

    def set_labels(self, repo: str, number, labels: list) -> None:
        self.write("PUT", f"repos/{self.repo(repo)}/issues/{_seg(number)}/labels", {"labels": labels})

    def add_labels(self, repo: str, number, labels: list) -> None:
        self.write("POST", f"repos/{self.repo(repo)}/issues/{_seg(number)}/labels", {"labels": labels})

    def remove_label(self, repo: str, number, label: str) -> None:
        self.write("DELETE", f"repos/{self.repo(repo)}/issues/{_seg(number)}/labels/{_seg(label)}")

    def assign(self, repo: str, number, logins: list) -> None:
        self.write("POST", f"repos/{self.repo(repo)}/issues/{_seg(number)}/assignees", {"assignees": logins})

    # ---- CI
    def checks(self, repo: str, sha: str) -> list:
        """What is not green on that commit: '<name>: <state>' for each check still running or failed."""
        bad = []
        runs = (self.get(f"repos/{self.repo(repo)}/commits/{_ref(sha)}/check-runs") or {}).get("check_runs") or []
        for run in runs:
            state = run.get("conclusion") or run.get("status") or ""
            if run.get("status") != "completed" or str(run.get("conclusion")).lower() not in GREEN:
                bad.append(f"{run.get('name')}: {state}")
        statuses = (self.get(f"repos/{self.repo(repo)}/commits/{_ref(sha)}/status") or {}).get("statuses") or []
        for status in statuses:
            if status.get("state") != "success":
                bad.append(f"{status.get('context')}: {status.get('state')}")
        if not runs and not statuses:
            bad.append("no checks reported")
        return bad

    def runs(self, repo: str, sha: str) -> list:
        return (self.get(f"repos/{self.repo(repo)}/actions/runs?head_sha={_ref(sha)}&per_page=100") or {}).get(
            "workflow_runs"
        ) or []

    def runs_if_changed(self, repo: str, sha: str, etag: str = "") -> dict:
        found = self.get_if_changed(f"repos/{self.repo(repo)}/actions/runs?head_sha={_ref(sha)}&per_page=100", etag)
        runs = ((found["body"] or {}).get("workflow_runs") or []) if found["changed"] else None
        return {"changed": found["changed"], "etag": found["etag"], "runs": runs}

    def run_jobs(self, repo: str, run_id) -> list:
        return (self.get(f"repos/{self.repo(repo)}/actions/runs/{_seg(run_id)}/jobs") or {}).get("jobs") or []

    def job_log(self, repo: str, job_id):
        return self.get(f"repos/{self.repo(repo)}/actions/jobs/{_seg(job_id)}/logs")

    def rerun_failed(self, repo: str, run_id) -> None:
        self.write("POST", f"repos/{self.repo(repo)}/actions/runs/{_seg(run_id)}/rerun-failed-jobs", {})

    # ---- conversation
    def comments(self, repo: str, number) -> list:
        prefix = f"repos/{self.repo(repo)}"
        rows = []
        for item in self.get(f"{prefix}/issues/{_seg(number)}/comments?per_page=100") or []:
            rows.append(
                {
                    "id": f"issue:{item['id']}",
                    "kind": "comment",
                    "author": (item.get("user") or {}).get("login") or "",
                    "body": item.get("body") or "",
                    "url": item.get("html_url") or "",
                    "at": item.get("created_at") or "",
                }
            )
        for item in self.get(f"{prefix}/pulls/{_seg(number)}/comments?per_page=100") or []:
            rows.append(
                {
                    "id": f"inline:{item['id']}",
                    "kind": "inline",
                    "author": (item.get("user") or {}).get("login") or "",
                    "body": item.get("body") or "",
                    "path": item.get("path") or "",
                    "url": item.get("html_url") or "",
                    "at": item.get("created_at") or "",
                    "in_reply_to": item.get("in_reply_to_id") or item.get("in_reply_to"),
                }
            )
        for item in self.get(f"{prefix}/pulls/{_seg(number)}/reviews?per_page=100") or []:
            if item.get("state") == "PENDING":
                continue
            rows.append(
                {
                    "id": f"review:{item['id']}",
                    "kind": "review",
                    "author": (item.get("user") or {}).get("login") or "",
                    "body": item.get("body") or "",
                    "url": item.get("html_url") or "",
                    "at": item.get("submitted_at") or "",
                    "review_state": item.get("state") or "",
                    "commit": item.get("commit_id") or "",
                }
            )
        return sorted(rows, key=lambda row: (row["at"], row["id"]))

    def add_comment(self, repo: str, number, body: str) -> dict:
        return self.write("POST", f"repos/{self.repo(repo)}/issues/{_seg(number)}/comments", {"body": body})

    def reply(self, repo: str, number, comment_id, body: str) -> dict:
        return self.write(
            "POST", f"repos/{self.repo(repo)}/pulls/{_seg(number)}/comments/{_seg(comment_id)}/replies", {"body": body}
        )

    def edit_review_comment(self, repo: str, comment_id, body: str) -> None:
        self.write("PATCH", f"repos/{self.repo(repo)}/pulls/comments/{_seg(comment_id)}", {"body": body})

    def reactions(self, repo: str, comment_id) -> list:
        return self.get(f"repos/{self.repo(repo)}/pulls/comments/{_seg(comment_id)}/reactions") or []

    def react(self, repo: str, comment_id, content: str = "+1") -> None:
        self.write("POST", f"repos/{self.repo(repo)}/pulls/comments/{_seg(comment_id)}/reactions", {"content": content})

    def threads(self, repo: str, number) -> list:
        owner, name = self.repo(repo).split("/", 1)
        data = self.graphql(THREADS, {"o": owner, "r": name, "n": int(number)})
        return (((data.get("repository") or {}).get("pullRequest") or {}).get("reviewThreads") or {}).get("nodes") or []

    def resolve_thread(self, thread_id: str) -> None:
        self.graphql(RESOLVE, {"id": thread_id}, write=True)

    # ---- reviews
    def reviews(self, repo: str, number) -> list:
        return self.get(f"repos/{self.repo(repo)}/pulls/{_seg(number)}/reviews") or []

    def review(self, repo: str, number, review) -> dict:
        return self.get(f"repos/{self.repo(repo)}/pulls/{_seg(number)}/reviews/{_seg(review)}") or {}

    def review_comments(self, repo: str, number, review) -> list:
        return self.get(f"repos/{self.repo(repo)}/pulls/{_seg(number)}/reviews/{_seg(review)}/comments") or []

    def create_review(self, repo: str, number, commit: str, threads: list) -> dict:
        return self.write(
            "POST",
            f"repos/{self.repo(repo)}/pulls/{_seg(number)}/reviews",
            {"commit_id": commit, "body": "", "comments": threads},
        )

    def add_review_thread(self, repo: str, number, review: dict, thread: dict) -> None:
        self.graphql(
            ADD_THREAD,
            {
                "review": review.get("node_id"),
                "path": thread["path"],
                "body": thread["body"],
                "line": thread["line"],
                "side": thread["side"],
            },
            write=True,
        )

    def update_review(self, repo: str, number, review, body: str) -> None:
        self.write("PUT", f"repos/{self.repo(repo)}/pulls/{_seg(number)}/reviews/{_seg(review)}", {"body": body})

    def submit_review(self, repo: str, number, review, event: str, body: str) -> None:
        self.write(
            "POST",
            f"repos/{self.repo(repo)}/pulls/{_seg(number)}/reviews/{_seg(review)}/events",
            {"event": event, "body": body},
        )

    def discard_review(self, repo: str, number, review) -> None:
        self.write("DELETE", f"repos/{self.repo(repo)}/pulls/{_seg(number)}/reviews/{_seg(review)}")

    # ---- diff
    def compare(self, repo: str, base: str, head: str) -> dict:
        return self.get(f"repos/{self.repo(repo)}/compare/{_ref(base)}...{_ref(head)}") or {}

    def compare_diff(self, repo: str, base: str, head: str) -> str:
        try:
            done = subprocess.run(
                [
                    *self._api(),
                    f"repos/{self.repo(repo)}/compare/{_ref(base)}...{_ref(head)}",
                    "-H",
                    "Accept: application/vnd.github.diff",
                ],
                capture_output=True,
                text=True,
                timeout=15,
                check=False,
            )
        except (OSError, subprocess.SubprocessError):
            return ""
        return done.stdout if done.returncode == 0 else ""

    def pr_diff(self, repo: str, number) -> str:
        try:
            done = subprocess.run(
                ["gh", "pr", "diff", str(number), "--repo", self._cli_repo(repo)],
                capture_output=True,
                text=True,
                timeout=8,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            return ""
        if done.returncode != 0:
            return ""
        return done.stdout or ""

    # ---- search
    def review_requests(self) -> list:
        query = urllib.parse.quote(f"is:pr is:open review-requested:{self.me()} org:{self.org}")
        rows = []
        for item in (self.get(f"search/issues?q={query}&per_page=20") or {}).get("items") or []:
            rows.append(
                {
                    "repo": str(item.get("repository_url") or "").rsplit("/", 1)[-1],
                    "number": item.get("number"),
                    "title": item.get("title") or "",
                }
            )
        return rows

    # ---- issues
    @staticmethod
    def _issue_view(found: dict) -> dict:
        return {
            "number": found.get("number"),
            "title": found.get("title") or "",
            "body": found.get("body") or "",
            "state": found.get("state") or "open",
            "labels": sorted(
                str((row.get("name") if isinstance(row, dict) else row) or "") for row in found.get("labels") or []
            ),
            "author": (found.get("user") or {}).get("login") or "",
            "assignees": [str((row or {}).get("login") or "") for row in found.get("assignees") or []],
            "url": found.get("html_url") or "",
        }

    @staticmethod
    def _issue_comment_view(found: dict) -> dict:
        return {
            "id": found.get("id"),
            "author": (found.get("user") or {}).get("login") or "",
            "body": found.get("body") or "",
            "url": found.get("html_url") or "",
            "created": found.get("created_at") or "",
            "updated": found.get("updated_at") or found.get("created_at") or "",
        }

    def issue(self, repo: str, number) -> dict:
        found = self.get(f"repos/{self.repo(repo)}/issues/{_seg(number)}")
        if not isinstance(found, dict) or not found.get("number"):
            raise CockpitError(f"no issue {self.repo(repo)}#{number}")
        if found.get("pull_request") is not None:  # the issues API answers for a pull request too
            raise CockpitError(f"{self.repo(repo)}#{number} is a pull request, not an issue")
        return self._issue_view(found)

    def create_issue(self, repo: str, title: str, body: str, labels=(), assignees=()) -> dict:
        made = self.write(
            "POST",
            f"repos/{self.repo(repo)}/issues",
            {
                "title": title,
                "body": body or "",
                **({"labels": list(labels)} if labels else {}),
                **({"assignees": list(assignees)} if assignees else {}),
            },
        )
        return made if self.dry_run else self._issue_view(made if isinstance(made, dict) else {})

    def update_issue(self, repo: str, number, fields: dict) -> dict:
        unknown = sorted(set(fields) - {"title", "body", "state"})
        if unknown or fields.get("state", "open") not in ("open", "closed"):
            raise CockpitError(
                f"an issue's title, body and state (open, closed) are edited, not {', '.join(unknown) or fields.get('state')}"
            )
        made = self.write("PATCH", f"repos/{self.repo(repo)}/issues/{_seg(number)}", dict(fields))
        return made if self.dry_run else self._issue_view(made if isinstance(made, dict) else {})

    def issue_comments(self, repo: str, number, since=None) -> list:
        asked = f"&since={urllib.parse.quote(str(since), safe=':')}" if since else ""
        found = self.get(f"repos/{self.repo(repo)}/issues/{_seg(number)}/comments?per_page=100{asked}") or []
        return [self._issue_comment_view(item) for item in found if isinstance(item, dict) and item.get("id")]

    def add_issue_comment(self, repo: str, number, body: str) -> dict:
        made = self.write("POST", f"repos/{self.repo(repo)}/issues/{_seg(number)}/comments", {"body": body})
        return made if self.dry_run else self._issue_comment_view(made if isinstance(made, dict) else {})

    def edit_issue_comment(self, repo: str, comment_id, body: str) -> None:
        self.write("PATCH", f"repos/{self.repo(repo)}/issues/comments/{_seg(comment_id)}", {"body": body})


# what a forge answered before the protocol: an object with these may stand in for one (a test's double, a pack's own)
BEFORE = (
    "org",
    "human_login",
    "dry_run",
    "writes",
    "repo",
    "me",
    "url",
    "pr",
    "pr_for_head",
    "labels",
    "checks",
    "threads",
)


class Wrapped(GitHubForge):
    """An object from before the protocol, which answers GitHub's REST paths (get, write, graphql) and perhaps some of
    the first operations: read as a GitHub forge over it. What it answers itself it still answers; every operation named
    since is made of its get, write and graphql, so it is asked exactly what it was asked before."""

    def __init__(self, inner):  # super().__init__ reads a pack; this forge is whatever the object is
        self._inner = inner
        self._me = ""
        self.writes = []
        for name in BEFORE:
            if hasattr(inner, name):
                setattr(self, name, getattr(inner, name))

    def capabilities(self) -> frozenset:
        return frozenset(
            name
            for name in base.CAPABILITIES
            if name != base.CONDITIONAL_READS or hasattr(self._inner, "get_if_changed")
        )

    def get(self, path: str):
        return self._inner.get(path)

    def get_if_changed(self, path: str, etag: str = "") -> dict:
        return self._inner.get_if_changed(path, etag)

    def write(self, method: str, path: str, body=None):
        return self._inner.write(method, path, body) if body is not None else self._inner.write(method, path)

    def graphql(self, query: str, variables: dict, write: bool = False):
        return self._inner.graphql(query, variables, write=write) if write else self._inner.graphql(query, variables)
