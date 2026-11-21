# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Seed and read the forge stand-in (tests/bin/gh). Test setup only."""

import json
import os


def _root() -> str:
    return os.environ["COCKPIT_ROOT"]


def state() -> dict:
    try:
        return json.load(open(os.path.join(_root(), "fake-gh.json"), encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save(data: dict) -> None:
    json.dump(data, open(os.path.join(_root(), "fake-gh.json"), "w", encoding="utf-8"), indent=1)


def calls() -> list:
    path = os.path.join(_root(), "fake-gh-calls.jsonl")
    if not os.path.isfile(path):
        return []
    return [json.loads(line) for line in open(path, encoding="utf-8") if line.strip()]


def writes() -> list:
    return [
        call
        for call in calls()
        if call["method"] != "GET" and not (call["path"] == "graphql" and "query(" in json.dumps(call["body"]))
    ]


def repo(data: dict, full: str) -> dict:
    return data.setdefault("repos", {}).setdefault(full, {"pulls": {}, "labels": [], "checks": {}, "runs": {}})


def setup(me: str = "human", labels=None, repos=()) -> dict:
    data = state()
    data["me"] = me
    for full in repos:
        repo(data, full)["labels"] = list(labels or [])
    save(data)
    return data


def head(full: str, branch: str, sha: str) -> None:
    """The commit a branch points at on the forge, for a PR opened on it."""
    data = state()
    data.setdefault("heads", {})[f"{full}:{branch}"] = sha
    save(data)


def pull(
    full: str,
    number: int,
    head_ref: str,
    sha: str,
    base: str = "main",
    title: str = "",
    body: str = "",
    draft=False,
    author: str = "",
) -> dict:
    """A PR on the forge; its author is the human unless named."""
    data = state()
    found = {
        "number": number,
        "title": title,
        "body": body,
        "draft": draft,
        "head": {"ref": head_ref, "sha": sha},
        "base": {"ref": base},
        "user": {"login": author or data.get("me") or "human"},
        "merged": False,
        "requested_reviewers": [],
        "state": "open",
        "node_id": f"PR_{number}",
        "html_url": f"https://github.com/{full}/pull/{number}",
        "labels": [],
        "assignees": [],
        "issue_comments": [],
        "reviews": {},
        "review_comments": {},
        "threads": [],
        "files": [],
    }
    repo(data, full)["pulls"][str(number)] = found
    save(data)
    return found


def thread(full: str, number: int, comment_id: int, author: str, body: str = "nit", resolved=False, replies=()) -> str:
    """A review thread opened by someone, with later replies [(author, body)]."""
    data = state()
    found = repo(data, full)["pulls"][str(number)]
    ids = [comment_id]
    found["review_comments"][str(comment_id)] = {
        "id": comment_id,
        "body": body,
        "path": "src/a.txt",
        "line": 1,
        "user": {"login": author},
        "html_url": f"https://github.com/{full}/pull/{number}#discussion_r{comment_id}",
        "reactions": [],
    }
    for offset, (who, text) in enumerate(replies, 1):
        made = comment_id + offset
        found["review_comments"][str(made)] = {
            "id": made,
            "body": text,
            "user": {"login": who},
            "reactions": [],
            "html_url": f"https://github.com/{full}/pull/{number}#discussion_r{made}",
        }
        ids.append(made)
    found["threads"].append({"id": f"PRRT_{comment_id}", "isResolved": resolved, "comments": ids})
    save(data)
    return f"PRRT_{comment_id}"


def checks(full: str, sha: str, runs=(), statuses=()) -> None:
    data = state()
    repo(data, full)["checks"][sha] = {"check_runs": list(runs), "statuses": list(statuses)}
    save(data)


def fail(rule: str, message: str) -> None:
    data = state()
    data.setdefault("fail", {})[rule] = message
    save(data)


def commit(
    repo: str,
    branch: str,
    name: str = "change.txt",
    text: str = "change\n",
    email: str = "dev@example.test",
    start: str = "main",
    message: str = "",
) -> str:
    """A commit on a branch of the repo's main checkout (made from `start` when new). Its sha."""
    import subprocess

    folder = os.path.join(_root(), "repos", repo)
    run = lambda *args: subprocess.run(
        ["git", "-C", folder, *args], check=True, capture_output=True, text=True
    ).stdout.strip()  # noqa: E731
    current = run("branch", "--show-current")
    exists = (
        subprocess.run(
            ["git", "-C", folder, "rev-parse", "--verify", "-q", f"refs/heads/{branch}"],
            check=False,
            capture_output=True,
        ).returncode
        == 0
    )
    run("checkout", "-q", branch) if exists else run("checkout", "-q", "-b", branch, start)
    open(os.path.join(folder, name), "w", encoding="utf-8").write(text)
    run("add", name)
    env = {
        **os.environ,
        "GIT_AUTHOR_EMAIL": email,
        "GIT_AUTHOR_NAME": email.split("@", maxsplit=1)[0],
        "GIT_COMMITTER_EMAIL": email,
        "GIT_COMMITTER_NAME": email.split("@", maxsplit=1)[0],
    }
    subprocess.run(
        ["git", "-C", folder, "commit", "-q", "-m", message or f"change {name}"],
        check=True,
        capture_output=True,
        env=env,
    )
    sha = run("rev-parse", "HEAD")
    run("checkout", "-q", current)
    return sha


def remote(repo: str, branch: str) -> str:
    """The branch's sha on the repo's bare origin, or empty."""
    import subprocess

    done = subprocess.run(
        [
            "git",
            "--git-dir",
            os.path.join(_root(), "remotes", f"{repo}.git"),
            "rev-parse",
            "--verify",
            "-q",
            f"refs/heads/{branch}",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    return done.stdout.strip()


def run(
    full: str,
    run_id: int,
    sha: str,
    name: str,
    status: str = "completed",
    conclusion: str = "success",
    attempt: int = 1,
    jobs=(),
) -> None:
    """A workflow run on a commit; jobs are [{id, name, conclusion, log}]."""
    data = state()
    runs = repo(data, full)["runs"]
    previous = runs.get(str(run_id)) or {}
    runs[str(run_id)] = {
        **previous,
        "id": run_id,
        "name": name,
        "status": status,
        "conclusion": conclusion if status == "completed" else None,
        "run_attempt": attempt,
        "head_sha": sha,
        "html_url": f"https://github.com/{full}/actions/runs/{run_id}",
        "jobs": list(jobs),
    }
    save(data)


def comment(
    full: str,
    number: int,
    author: str,
    body: str,
    at: str = "2026-10-20T10:00:00Z",
    inline: bool = False,
    in_reply_to: int = 0,
) -> int:
    """A conversation comment (or an inline review comment) on a PR. Its id."""
    data = state()
    pull = repo(data, full)["pulls"][str(number)]
    data["next_id"] = int(data.get("next_id") or 5000) + 1
    made = data["next_id"]
    row = {
        "id": made,
        "body": body,
        "user": {"login": author},
        "created_at": at,
        "reactions": [],
        "html_url": f"https://github.com/{full}/pull/{number}#c{made}",
    }
    if inline:
        row.update(path="src/a.txt", line=1, **({"in_reply_to_id": in_reply_to} if in_reply_to else {}))
        pull["review_comments"][str(made)] = row
        thread = (
            next((item for item in pull["threads"] if in_reply_to in item["comments"]), None) if in_reply_to else None
        )
        if thread:
            thread["comments"].append(made)
        else:
            pull["threads"].append({"id": f"PRRT_{made}", "isResolved": False, "comments": [made]})
    else:
        pull["issue_comments"].append(row)
    save(data)
    return made


def review(
    full: str,
    number: int,
    author: str,
    state_name: str,
    body: str = "",
    commit: str = "",
    at: str = "2026-10-20T11:00:00Z",
) -> int:
    data = state()
    pull = repo(data, full)["pulls"][str(number)]
    data["next_id"] = int(data.get("next_id") or 5000) + 1
    made = data["next_id"]
    pull["reviews"][str(made)] = {
        "id": made,
        "node_id": f"PRR_{made}",
        "state": state_name,
        "body": body,
        "user": {"login": author},
        "commit_id": commit,
        "submitted_at": at,
        "comments": [],
    }
    save(data)
    return made


def issue(
    full: str, number: int, title: str, body: str = "", state_name: str = "open", labels=(), author: str = ""
) -> dict:
    """An issue on the forge, as someone made it there; its author is the human unless named."""
    data = state()
    found = {
        "number": number,
        "title": title,
        "body": body,
        "state": state_name,
        "user": {"login": author or data.get("me") or "human"},
        "labels": sorted(labels),
        "assignees": [],
        "html_url": f"https://github.com/{full}/issues/{number}",
        "created_at": "2026-01-01T00:00:00Z",
        "issue_comments": [],
    }
    repo(data, full).setdefault("issues", {})[str(number)] = found
    save(data)
    return found


def issue_comment(full: str, number: int, author: str, body: str) -> int:
    """A comment someone wrote on an issue, later than every comment before it. Its id."""
    data = state()
    held = repo(data, full)["issues"][str(number)]
    data["next_id"] = int(data.get("next_id") or 5000) + 1
    data["tick"] = int(data.get("tick") or 0) + 1
    now = f"2026-01-01T{data['tick'] // 3600:02d}:{data['tick'] // 60 % 60:02d}:{data['tick'] % 60:02d}Z"
    held["issue_comments"].append(
        {
            "id": data["next_id"],
            "body": body,
            "user": {"login": author},
            "created_at": now,
            "updated_at": now,
            "html_url": f"https://github.com/{full}/issues/{number}#issuecomment-{data['next_id']}",
        }
    )
    save(data)
    return data["next_id"]
