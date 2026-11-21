# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""A forge kept in files: pull requests, issues, labels, comments, review threads, reviews and checks as JSON under one
folder, with a bare git repository per repo as the remote a push goes to. No network, no CLI, no credentials.

`forge.kind: local` chooses it; `forge.local.root` names the folder (default: `forge/` in the records folder). Layout:

    <root>/<org>/<repo>.json   the repo's pull requests, issues (once it has one), labels, checks and runs
    <root>/<org>/<repo>.git    the bare repository (made by `remote`), which a checkout has as its origin

It is what a demonstration without an account and a hermetic test use. Someone else's part (a reviewer's thread, a CI
result) is written with the same operations and `author=`, or with `seed_check` and `seed_run`.
"""

import contextlib
import json
import os
import subprocess

from ..errors import CockpitError
from . import base
from .base import Forge

GREEN = ("success", "skipped", "neutral")
STATES = {"REQUEST_CHANGES": "CHANGES_REQUESTED", "COMMENT": "COMMENTED", "APPROVE": "APPROVED"}
HAS = (
    base.PULL_REQUESTS,
    base.DRAFT,
    base.REVIEW_THREADS,
    base.PENDING_REVIEWS,
    base.REACTIONS,
    base.CHECKS,
    base.RUNS,
    base.SEARCH,
    base.LISTING,
    base.DIFF,
    base.ISSUES,
)


class LocalForge(Forge):
    kind = "local"

    def __init__(self, pack, dry_run: bool = False, root: str = ""):
        forge = (pack or {}).get("forge") or {}
        self.org = forge.get("org") or ""
        self.human_login = forge.get("human_login") or ""
        self._root = root or (forge.get("local") or {}).get("root") or ""
        self.dry_run = dry_run
        self.writes = []

    # ---- the files
    def root(self) -> str:
        """The folder this forge lives in: forge.local.root, or forge/ in the records folder."""
        if self._root:
            return os.path.abspath(os.path.expanduser(self._root))
        from ..paths import records

        return os.path.join(records(), "forge")

    def _file(self, repo: str) -> str:
        from ..paths import inside

        owner, name = self.repo(repo).split("/", 1)
        return inside(self.root(), owner, f"{name}.json", what="repo")

    def remote(self, repo: str) -> str:
        """The repo's bare repository, made when it is not there: the origin a push goes to."""
        folder = self._file(repo)[: -len(".json")] + ".git"
        if not os.path.isdir(folder):
            os.makedirs(os.path.dirname(folder), exist_ok=True)
            done = subprocess.run(["git", "init", "--bare", "-q", folder], capture_output=True, text=True, check=False)
            if done.returncode != 0:
                raise CockpitError(f"local forge: git init {folder}: {(done.stderr or '').strip()[-200:]}")
        return folder

    def _git(self, repo: str, *args) -> str:
        """A read of the repo's bare repository; empty when there is none or git refuses."""
        folder = self._file(repo)[: -len(".json")] + ".git"
        if not os.path.isdir(folder):
            return ""
        try:
            done = subprocess.run(
                ["git", "--git-dir", folder, *args], capture_output=True, text=True, check=False, timeout=30
            )
        except (OSError, subprocess.SubprocessError):
            return ""
        return done.stdout if done.returncode == 0 else ""

    def _load(self, repo: str) -> dict:
        try:
            data = json.load(open(self._file(repo), encoding="utf-8"))
        except FileNotFoundError:
            data = {}
        except (OSError, ValueError) as exc:
            raise CockpitError(f"local forge: {self._file(repo)} is unreadable: {exc}") from exc
        for key, empty in (("pulls", {}), ("labels", []), ("checks", {}), ("runs", {})):
            data.setdefault(key, empty)
        data.setdefault("next_id", 1000)
        return data

    @contextlib.contextmanager
    def _change(self, repo: str):
        """Read, change and write one repo's file as one step: the file's lock keeps two writers apart, store's write keeps a reader whole."""
        from ..store import dump_json, locked_file

        path = self._file(repo)
        with locked_file(path):
            data = self._load(repo)
            yield data
            dump_json(path, data, indent=1, sort_keys=True)

    def _pull(self, data: dict, repo: str, number) -> dict:
        found = data["pulls"].get(str(number))
        if found is None:
            raise CockpitError(f"local forge: no pull request {self.repo(repo)}#{number}")
        return found

    def _issue(self, data: dict, repo: str, number) -> dict:
        found = (data.get("issues") or {}).get(str(number))
        if found is None and str(number) in data["pulls"]:
            raise CockpitError(f"local forge: {self.repo(repo)}#{number} is a pull request, not an issue")
        if found is None:
            raise CockpitError(f"local forge: no issue {self.repo(repo)}#{number}")
        return found

    def _labelled(self, data: dict, repo: str, number) -> dict:
        """What carries labels and people under that number: the issue when it is one, else the pull request."""
        return (data.get("issues") or {}).get(str(number)) or self._pull(data, repo, number)

    @staticmethod
    def _number(data: dict) -> int:
        """The next number of the repo: pull requests and issues count on together."""
        return max([int(key) for key in [*data["pulls"], *(data.get("issues") or {})]] or [0]) + 1

    @staticmethod
    def _id(data: dict) -> int:
        data["next_id"] = int(data["next_id"]) + 1
        return data["next_id"]

    def _sent(self, what: str, repo: str, body: dict) -> bool:
        """Keep the write in the journal. False in a dry run: nothing is stored."""
        self.writes.append({"method": what, "path": self.repo(repo) if repo else "", "body": body})
        return not self.dry_run

    @staticmethod
    def _now() -> str:
        from ..time_util import iso

        return iso()

    def _view(self, repo: str, pull: dict) -> dict:
        """The pull request as the protocol shapes it; an open one's head is where its branch is on the remote now."""
        found = {
            key: value
            for key, value in pull.items()
            if key not in ("issue_comments", "review_comments", "threads", "reviews", "labels")
        }
        tip = (
            self._git(repo, "rev-parse", "--verify", "-q", f"refs/heads/{pull['head']['ref']}").strip()
            if pull["state"] == "open"
            else ""
        )
        if tip:
            found["head"] = {**pull["head"], "sha": tip}
        return found

    def _comment_url(self, repo: str, number, made) -> str:
        return f"{self.url(repo, number)}#discussion_r{made}"

    # ---- identity
    def capabilities(self) -> frozenset:
        return frozenset(HAS)

    def me(self) -> str:
        return self.human_login or "human"

    def url(self, repo: str, number=None) -> str:
        page = f"local://{self.repo(repo)}"
        return f"{page}/pull/{number}" if number else page

    # ---- pull requests
    def pr(self, repo: str, number) -> dict:
        data = self._load(repo)
        return self._view(repo, self._pull(data, repo, number))

    def open_prs_for_branch(self, repo: str, branch: str) -> list:
        return [
            self._view(repo, pull)
            for _number, pull in sorted(self._load(repo)["pulls"].items(), key=lambda item: int(item[0]))
            if pull["state"] == "open" and pull["head"]["ref"] == branch
        ]

    def pr_for_head(self, repo: str, head: str, base: str = "") -> dict:
        found = [pull for pull in self.open_prs_for_branch(repo, head) if not base or pull["base"]["ref"] == base]
        return found[0] if found else {}

    def list_prs(self, repo: str, state: str, base: str = "", runner=None) -> list:
        rows = []
        for _number, pull in sorted(self._load(repo)["pulls"].items(), key=lambda item: -int(item[0])):
            is_state = "merged" if pull.get("merged") else pull["state"]
            if is_state != state or (base and pull["base"]["ref"] != base):
                continue
            rows.append(
                {
                    "number": pull["number"],
                    "title": pull["title"],
                    "body": pull["body"],
                    "headRefName": pull["head"]["ref"],
                    "headRefOid": pull["head"]["sha"],
                    "baseRefName": pull["base"]["ref"],
                    "url": pull["html_url"],
                    "createdAt": pull.get("created_at") or "",
                    "mergedAt": pull.get("merged_at") or "",
                    "author": pull["user"],
                    "files": [{"path": path} for path in self._files(repo, pull["base"]["ref"], pull["head"]["ref"])],
                }
            )
        return rows[:40]

    def create_pr(
        self, repo: str, title: str, body: str, head: str, base: str, draft: bool = False, author: str = ""
    ) -> dict:
        if not self._sent(
            "create_pr", repo, {"title": title, "body": body, "head": head, "base": base, "draft": draft}
        ):
            return {"dry_run": True}
        with self._change(repo) as data:
            if any(
                pull["state"] == "open" and pull["head"]["ref"] == head and pull["base"]["ref"] == base
                for pull in data["pulls"].values()
            ):
                raise CockpitError(
                    f"local forge: a pull request of {head} onto {base} is already open in {self.repo(repo)}"
                )
            number = self._number(data)
            pull = {
                "number": number,
                "title": title,
                "body": body or "",
                "draft": bool(draft),
                "state": "open",
                "merged": False,
                "html_url": self.url(repo, number),
                "node_id": f"PR_{number}",
                "created_at": self._now(),
                "head": {
                    "ref": head,
                    "sha": self._git(repo, "rev-parse", "--verify", "-q", f"refs/heads/{head}").strip(),
                },
                "base": {"ref": base},
                "user": {"login": author or self.me()},
                "assignees": [],
                "requested_reviewers": [],
                "labels": [],
                "issue_comments": [],
                "review_comments": {},
                "threads": [],
                "reviews": {},
            }
            data["pulls"][str(number)] = pull
            return self._view(repo, pull)

    def update_pr(self, repo: str, number, fields: dict) -> dict:
        unknown = sorted(set(fields) - {"title", "body", "base"})
        if unknown:
            raise CockpitError(
                f"local forge: a pull request's title, body and base are edited, not {', '.join(unknown)}"
            )
        if not self._sent("update_pr", repo, {"number": number, **fields}):
            return {"dry_run": True}
        with self._change(repo) as data:
            pull = self._pull(data, repo, number)
            for key in ("title", "body"):
                if key in fields:
                    pull[key] = fields[key]
            if "base" in fields:
                pull["base"] = {"ref": fields["base"]}
            return self._view(repo, pull)

    def mark_ready(self, repo: str, number) -> None:
        if not self.pr(repo, number).get("draft"):
            return
        if self._sent("mark_ready", repo, {"number": number}):
            with self._change(repo) as data:
                self._pull(data, repo, number)["draft"] = False

    def close_pr(self, repo: str, number, merged: bool = False) -> None:
        """The pull request is closed, or merged: what a person does on a forge's page, for a demonstration and a test."""
        if self._sent("close_pr", repo, {"number": number, "merged": merged}):
            with self._change(repo) as data:
                pull = self._pull(data, repo, number)
                pull.update(state="closed", merged=bool(merged), **({"merged_at": self._now()} if merged else {}))

    def request_review(self, repo: str, number, logins: list) -> None:
        """Those people are asked for a review of the pull request."""
        if self._sent("request_review", repo, {"number": number, "reviewers": logins}):
            with self._change(repo) as data:
                self._pull(data, repo, number)["requested_reviewers"] = [{"login": login} for login in logins]

    # ---- labels and people
    def labels(self, repo: str, number) -> list:
        return sorted(self._labelled(self._load(repo), repo, number)["labels"])

    def repo_labels(self, repo: str) -> list:
        return list(self._load(repo)["labels"])

    def seed_labels(self, repo: str, labels: list) -> None:
        """The label names the repo has."""
        with self._change(repo) as data:
            data["labels"] = list(labels)

    def _labels(self, what: str, repo: str, number, labels: list, change) -> None:
        if self._sent(what, repo, {"number": number, "labels": labels}):
            with self._change(repo) as data:
                pull = self._labelled(data, repo, number)
                pull["labels"] = sorted(change(set(pull["labels"])))
                data["labels"] = data["labels"] + [label for label in pull["labels"] if label not in data["labels"]]

    def set_labels(self, repo: str, number, labels: list) -> None:
        self._labels("set_labels", repo, number, labels, lambda current: set(labels))

    def add_labels(self, repo: str, number, labels: list) -> None:
        self._labels("add_labels", repo, number, labels, lambda current: current | set(labels))

    def remove_label(self, repo: str, number, label: str) -> None:
        if label not in self.labels(repo, number) and not self.dry_run:
            raise CockpitError(f"local forge: {self.repo(repo)}#{number} has no label {label}")
        self._labels("remove_label", repo, number, [label], lambda current: current - {label})

    def assign(self, repo: str, number, logins: list) -> None:
        if self._sent("assign", repo, {"number": number, "assignees": logins}):
            with self._change(repo) as data:
                self._labelled(data, repo, number)["assignees"] = [{"login": login} for login in logins]

    # ---- conversation
    def comments(self, repo: str, number) -> list:
        pull = self._pull(self._load(repo), repo, number)
        rows = []
        for item in pull["issue_comments"]:
            rows.append(
                {
                    "id": f"issue:{item['id']}",
                    "kind": "comment",
                    "author": item["user"]["login"],
                    "body": item["body"],
                    "url": item["html_url"],
                    "at": item["created_at"],
                }
            )
        for item in pull["review_comments"].values():
            review = pull["reviews"].get(str(item.get("pull_request_review_id") or "")) or {}
            if review.get("state") == "PENDING":
                continue  # a comment of a review still being written is its writer's alone
            rows.append(
                {
                    "id": f"inline:{item['id']}",
                    "kind": "inline",
                    "author": item["user"]["login"],
                    "body": item["body"],
                    "path": item.get("path") or "",
                    "url": item["html_url"],
                    "at": item["created_at"],
                    "in_reply_to": item.get("in_reply_to_id"),
                }
            )
        for item in pull["reviews"].values():
            if item["state"] == "PENDING":
                continue
            rows.append(
                {
                    "id": f"review:{item['id']}",
                    "kind": "review",
                    "author": item["user"]["login"],
                    "body": item["body"],
                    "url": self.review_url(repo, number, item["id"]),
                    "at": item.get("submitted_at") or "",
                    "review_state": item["state"],
                    "commit": item.get("commit_id") or "",
                }
            )
        return sorted(rows, key=lambda row: (row["at"], row["id"]))

    def add_comment(self, repo: str, number, body: str, author: str = "") -> dict:
        if not self._sent("add_comment", repo, {"number": number, "body": body}):
            return {"dry_run": True}
        with self._change(repo) as data:
            pull = self._pull(data, repo, number)
            made = self._id(data)
            row = {
                "id": made,
                "body": body,
                "user": {"login": author or self.me()},
                "created_at": self._now(),
                "html_url": f"{self.url(repo, number)}#issuecomment-{made}",
            }
            pull["issue_comments"].append(row)
            return dict(row)

    def _inline(
        self, data, pull, repo, body, author, path="", line=None, side="RIGHT", review=None, in_reply_to=None
    ) -> dict:
        made = self._id(data)
        row = {
            "id": made,
            "body": body,
            "user": {"login": author or self.me()},
            "created_at": self._now(),
            "reactions": [],
            "html_url": self._comment_url(repo, pull["number"], made),
            "path": path,
            "line": line,
            "side": side,
        }
        if review is not None:
            row["pull_request_review_id"] = review
        if in_reply_to is not None:
            row["in_reply_to_id"] = in_reply_to
        pull["review_comments"][str(made)] = row
        return row

    def _find_comment(self, data: dict, repo: str, comment_id) -> tuple:
        for pull in data["pulls"].values():
            if str(comment_id) in pull["review_comments"]:
                return pull, pull["review_comments"][str(comment_id)]
        raise CockpitError(f"local forge: no review comment {comment_id} in {self.repo(repo)}")

    def reply(self, repo: str, number, comment_id, body: str, author: str = "") -> dict:
        if not self._sent("reply", repo, {"number": number, "comment": comment_id, "body": body}):
            return {"dry_run": True}
        with self._change(repo) as data:
            pull = self._pull(data, repo, number)
            thread = next((item for item in pull["threads"] if int(comment_id) in item["comments"]), None)
            if thread is None:
                raise CockpitError(
                    f"local forge: review comment {comment_id} is in no thread of {self.repo(repo)}#{number}"
                )
            first = pull["review_comments"][str(thread["comments"][0])]
            row = self._inline(
                data,
                pull,
                repo,
                body,
                author,
                path=first.get("path") or "",
                line=first.get("line"),
                in_reply_to=int(comment_id),
            )
            thread["comments"].append(row["id"])
            return {"id": row["id"], "html_url": row["html_url"]}

    def edit_review_comment(self, repo: str, comment_id, body: str) -> None:
        if self._sent("edit_review_comment", repo, {"comment": comment_id, "body": body}):
            with self._change(repo) as data:
                self._find_comment(data, repo, comment_id)[1]["body"] = body

    def reactions(self, repo: str, comment_id) -> list:
        return list(self._find_comment(self._load(repo), repo, comment_id)[1]["reactions"])

    def react(self, repo: str, comment_id, content: str = "+1") -> None:
        if self._sent("react", repo, {"comment": comment_id, "content": content}):
            with self._change(repo) as data:
                found = self._find_comment(data, repo, comment_id)[1]["reactions"]
                mine = {"content": content, "user": {"login": self.me()}}
                if mine not in found:
                    found.append(mine)

    def threads(self, repo: str, number) -> list:
        pull = self._pull(self._load(repo), repo, number)
        me = self.me()
        nodes = []
        for thread in pull["threads"]:
            rows = [pull["review_comments"][str(made)] for made in thread["comments"]]
            review = pull["reviews"].get(str(rows[0].get("pull_request_review_id") or "")) or {}
            if review.get("state") == "PENDING" and review["user"]["login"] != me:
                continue  # another person's pending review is not shown to the human
            nodes.append(
                {
                    "id": thread["id"],
                    "isResolved": bool(thread["isResolved"]),
                    "isOutdated": bool(thread.get("isOutdated")),
                    "comments": {
                        "nodes": [
                            {
                                "databaseId": row["id"],
                                "url": row["html_url"],
                                "createdAt": row["created_at"],
                                "author": {"login": row["user"]["login"]},
                            }
                            for row in rows
                        ]
                    },
                }
            )
        return nodes

    def resolve_thread(self, thread_id: str, repo: str = "") -> None:
        if not self._sent("resolve_thread", repo, {"thread": thread_id}):
            return
        for name in [repo] if repo else self._repos():
            with self._change(name) as data:
                for pull in data["pulls"].values():
                    for thread in pull["threads"]:
                        if thread["id"] == thread_id:
                            thread["isResolved"] = True
                            return
        raise CockpitError(f"local forge: no review thread {thread_id}")

    def _repos(self) -> list:
        from ..paths import inside

        folder = inside(self.root(), self.org, what="organisation")
        return (
            sorted(f"{self.org}/{name[: -len('.json')]}" for name in os.listdir(folder) if name.endswith(".json"))
            if os.path.isdir(folder)
            else []
        )

    # ---- reviews
    @staticmethod
    def _review_view(review: dict) -> dict:
        return {key: value for key, value in review.items() if key != "comments"}

    def reviews(self, repo: str, number) -> list:
        me = self.me()
        return [
            self._review_view(item)
            for item in self._pull(self._load(repo), repo, number)["reviews"].values()
            if item["state"] != "PENDING" or item["user"]["login"] == me
        ]

    def _review(self, pull: dict, repo: str, review) -> dict:
        found = pull["reviews"].get(str(review))
        if found is None:
            raise CockpitError(f"local forge: no review {review} on {self.repo(repo)}#{pull['number']}")
        return found

    def review(self, repo: str, number, review) -> dict:
        return self._review_view(self._review(self._pull(self._load(repo), repo, number), repo, review))

    def review_comments(self, repo: str, number, review) -> list:
        pull = self._pull(self._load(repo), repo, number)
        return [
            {key: row.get(key) for key in ("id", "body", "path", "line")}
            for row in (pull["review_comments"][str(made)] for made in self._review(pull, repo, review)["comments"])
        ]

    def _thread(self, data, pull, repo, review, thread, author) -> None:
        row = self._inline(
            data,
            pull,
            repo,
            thread["body"],
            author,
            path=thread["path"],
            line=int(thread["line"]),
            side=thread.get("side") or "RIGHT",
            review=review["id"],
        )
        review["comments"].append(row["id"])
        pull["threads"].append(
            {"id": f"PRRT_{row['id']}", "isResolved": False, "isOutdated": False, "comments": [row["id"]]}
        )

    def create_review(self, repo: str, number, commit: str, threads: list, author: str = "") -> dict:
        if not self._sent("create_review", repo, {"number": number, "commit_id": commit, "comments": threads}):
            return {"dry_run": True}
        who = author or self.me()
        with self._change(repo) as data:
            pull = self._pull(data, repo, number)
            if any(item["state"] == "PENDING" and item["user"]["login"] == who for item in pull["reviews"].values()):
                raise CockpitError(f"local forge: {who} already has a pending review on {self.repo(repo)}#{number}")
            made = self._id(data)
            review = {
                "id": made,
                "node_id": f"PRR_{made}",
                "state": "PENDING",
                "body": "",
                "user": {"login": who},
                "commit_id": commit,
                "submitted_at": "",
                "comments": [],
            }
            pull["reviews"][str(made)] = review
            for thread in threads:
                self._thread(data, pull, repo, review, thread, who)
            return self._review_view(review)

    def _pending(self, pull: dict, repo: str, review) -> dict:
        found = self._review(pull, repo, review["id"] if isinstance(review, dict) else review)
        if found["state"] != "PENDING":
            raise CockpitError(f"local forge: review {found['id']} is {found['state']}, not pending")
        return found

    def add_review_thread(self, repo: str, number, review: dict, thread: dict) -> None:
        if self._sent("add_review_thread", repo, {"number": number, "review": review.get("id"), **thread}):
            with self._change(repo) as data:
                pull = self._pull(data, repo, number)
                found = self._pending(pull, repo, review)
                self._thread(data, pull, repo, found, thread, found["user"]["login"])

    def update_review(self, repo: str, number, review, body: str) -> None:
        if self._sent("update_review", repo, {"number": number, "review": review, "body": body}):
            with self._change(repo) as data:
                self._pending(self._pull(data, repo, number), repo, review)["body"] = body or ""

    def submit_review(self, repo: str, number, review, event: str, body: str) -> None:
        if event not in STATES:
            raise CockpitError(f"local forge: a review is submitted as one of {', '.join(STATES)}")
        if self._sent("submit_review", repo, {"number": number, "review": review, "event": event, "body": body}):
            with self._change(repo) as data:
                found = self._pending(self._pull(data, repo, number), repo, review)
                found.update(state=STATES[event], body=body or found["body"], submitted_at=self._now())

    def discard_review(self, repo: str, number, review) -> None:
        if self._sent("discard_review", repo, {"number": number, "review": review}):
            with self._change(repo) as data:
                pull = self._pull(data, repo, number)
                found = self._pending(pull, repo, review)
                for made in found["comments"]:
                    pull["review_comments"].pop(str(made), None)
                pull["threads"] = [
                    thread for thread in pull["threads"] if thread["comments"][0] not in found["comments"]
                ]
                del pull["reviews"][str(found["id"])]

    # ---- CI
    def seed_check(
        self, repo: str, sha: str, name: str, conclusion: str = "success", status: str = "completed"
    ) -> None:
        """One check's result on a commit, as a CI system would report it."""
        with self._change(repo) as data:
            rows = [row for row in data["checks"].get(sha) or [] if row["name"] != name]
            data["checks"][sha] = rows + [
                {"name": name, "status": status, "conclusion": conclusion if status == "completed" else None}
            ]

    def checks(self, repo: str, sha: str) -> list:
        rows = self._load(repo)["checks"].get(sha) or []
        bad = [
            f"{row['name']}: {row.get('conclusion') or row.get('status') or ''}"
            for row in rows
            if row.get("status") != "completed" or str(row.get("conclusion")).lower() not in GREEN
        ]
        return bad if rows else ["no checks reported"]

    def seed_run(
        self,
        repo: str,
        run_id: int,
        sha: str,
        name: str,
        status: str = "completed",
        conclusion: str = "success",
        attempt: int = 1,
        jobs=(),
    ) -> None:
        """One CI run of a commit; jobs are [{id, name, conclusion, log}]."""
        with self._change(repo) as data:
            data["runs"][str(run_id)] = {
                "id": run_id,
                "name": name,
                "status": status,
                "conclusion": conclusion if status == "completed" else None,
                "run_attempt": attempt,
                "head_sha": sha,
                "html_url": self.run_url(repo, run_id),
                "jobs": list(jobs),
            }

    def runs(self, repo: str, sha: str) -> list:
        return [
            {key: value for key, value in run.items() if key != "jobs"}
            for _id, run in sorted(self._load(repo)["runs"].items())
            if run.get("head_sha") == sha
        ]

    def _run(self, repo: str, run_id) -> dict:
        return self._load(repo)["runs"].get(str(run_id)) or {}

    def run_jobs(self, repo: str, run_id) -> list:
        return [
            {key: value for key, value in job.items() if key != "log"}
            for job in self._run(repo, run_id).get("jobs") or []
        ]

    def job_log(self, repo: str, job_id):
        for run in self._load(repo)["runs"].values():
            for job in run.get("jobs") or []:
                if str(job.get("id")) == str(job_id):
                    if "log" not in job:
                        raise CockpitError(f"local forge: the log of job {job_id} is gone")
                    return job["log"]
        raise CockpitError(f"local forge: no job {job_id} in {self.repo(repo)}")

    # ---- diff
    def _files(self, repo: str, base: str, head: str) -> list:
        return [line for line in self._git(repo, "diff", "--name-only", f"{base}...{head}").splitlines() if line]

    def compare(self, repo: str, base: str, head: str) -> dict:
        count = self._git(repo, "rev-list", "--count", f"{base}..{head}").strip()
        if not count:
            raise CockpitError(f"local forge: {self.repo(repo)} cannot compare {base[:12]} and {head[:12]}")
        return {"total_commits": int(count), "files": [{"filename": path} for path in self._files(repo, base, head)]}

    def compare_diff(self, repo: str, base: str, head: str) -> str:
        return self._git(repo, "diff", f"{base}...{head}")

    def pr_diff(self, repo: str, number) -> str:
        try:
            pull = self.pr(repo, number)
        except CockpitError:
            return ""
        return self._git(repo, "diff", f"{pull['base']['ref']}...{pull['head']['ref']}")

    # ---- issues
    @staticmethod
    def _moment() -> str:
        """Now, to the microsecond: two comments written one after the other are told apart by their time."""
        import datetime

        return datetime.datetime.now(datetime.UTC).isoformat()

    @staticmethod
    def _at(moment: str):
        """An ISO moment as seconds; None when it is not one (a since that cannot be read leaves no comment out)."""
        import datetime

        try:
            return datetime.datetime.fromisoformat(str(moment).replace("Z", "+00:00")).timestamp()
        except ValueError:
            return None

    @staticmethod
    def _issue_view(issue: dict) -> dict:
        return {
            "number": issue["number"],
            "title": issue["title"],
            "body": issue["body"],
            "state": issue["state"],
            "labels": sorted(issue["labels"]),
            "author": issue["user"]["login"],
            "assignees": [who["login"] for who in issue["assignees"]],
            "url": issue["html_url"],
        }

    @staticmethod
    def _issue_comment_view(row: dict) -> dict:
        return {
            "id": row["id"],
            "author": row["user"]["login"],
            "body": row["body"],
            "url": row["html_url"],
            "created": row["created_at"],
            "updated": row["updated_at"],
        }

    def issue(self, repo: str, number) -> dict:
        return self._issue_view(self._issue(self._load(repo), repo, number))

    def create_issue(self, repo: str, title: str, body: str, labels=(), assignees=(), author: str = "") -> dict:
        if not self._sent(
            "create_issue", repo, {"title": title, "body": body, "labels": list(labels), "assignees": list(assignees)}
        ):
            return {"dry_run": True}
        with self._change(repo) as data:
            number = self._number(data)
            issue = {
                "number": number,
                "title": title,
                "body": body or "",
                "state": "open",
                "labels": sorted(set(labels)),
                "user": {"login": author or self.me()},
                "assignees": [{"login": login} for login in assignees],
                "html_url": self.issue_url(repo, number),
                "created_at": self._now(),
                "comments": [],
            }
            data.setdefault("issues", {})[str(number)] = issue
            data["labels"] = data["labels"] + [label for label in issue["labels"] if label not in data["labels"]]
            return self._issue_view(issue)

    def update_issue(self, repo: str, number, fields: dict) -> dict:
        unknown = sorted(set(fields) - {"title", "body", "state"})
        if unknown or fields.get("state", "open") not in ("open", "closed"):
            raise CockpitError(
                f"local forge: an issue's title, body and state (open, closed) are edited, not {', '.join(unknown) or fields.get('state')}"
            )
        if not self._sent("update_issue", repo, {"number": number, **fields}):
            return {"dry_run": True}
        with self._change(repo) as data:
            issue = self._issue(data, repo, number)
            issue.update({key: fields[key] for key in ("title", "body", "state") if key in fields})
            return self._issue_view(issue)

    def issue_comments(self, repo: str, number, since=None) -> list:
        rows = [self._issue_comment_view(row) for row in self._issue(self._load(repo), repo, number)["comments"]]
        floor = self._at(since) if since else None
        return [row for row in rows if floor is None or self._at(row["updated"]) >= floor]

    def add_issue_comment(self, repo: str, number, body: str, author: str = "") -> dict:
        if not self._sent("add_issue_comment", repo, {"number": number, "body": body}):
            return {"dry_run": True}
        with self._change(repo) as data:
            issue = self._issue(data, repo, number)
            made = self._id(data)
            now = self._moment()
            row = {
                "id": made,
                "body": body,
                "user": {"login": author or self.me()},
                "created_at": now,
                "updated_at": now,
                "html_url": f"{self.issue_url(repo, number)}#issuecomment-{made}",
            }
            issue["comments"].append(row)
            return self._issue_comment_view(row)

    def edit_issue_comment(self, repo: str, comment_id, body: str) -> None:
        if not self._sent("edit_issue_comment", repo, {"comment": comment_id, "body": body}):
            return
        with self._change(repo) as data:
            for issue in (data.get("issues") or {}).values():
                for row in issue["comments"]:
                    if str(row["id"]) == str(comment_id):
                        row.update(body=body, updated_at=self._moment())
                        return
            raise CockpitError(f"local forge: no issue comment {comment_id} in {self.repo(repo)}")

    # ---- search
    def review_requests(self) -> list:
        me = self.me()
        rows = []
        for full in self._repos():
            for _number, pull in sorted(self._load(full)["pulls"].items(), key=lambda item: int(item[0])):
                if pull["state"] == "open" and me in [
                    who.get("login") for who in pull.get("requested_reviewers") or []
                ]:
                    rows.append({"repo": full.split("/", 1)[1], "number": pull["number"], "title": pull["title"]})
        return rows
