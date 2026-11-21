# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The kernel asks a forge for operations; GitHub's are made of the same `gh` calls as before, and an object from before
the protocol (a double that answers REST paths) still stands in for a forge."""

import json

import pytest

from cockpitlib import forges
from cockpitlib.errors import CockpitError, PackError
from cockpitlib.forges import base
from cockpitlib.forges.github import ADD_THREAD, RESOLVE, GitHubForge, Wrapped


class _Done:
    def __init__(self, stdout="", returncode=0, stderr=""):
        self.stdout, self.returncode, self.stderr = stdout, returncode, stderr


def _recording(answers=None):
    calls = []

    def runner(argv, **_kwargs):
        body = json.load(open(argv[argv.index("--input") + 1], encoding="utf-8")) if "--input" in argv else None
        calls.append(([word for word in argv if not word.endswith(".json")], body))
        for part, answer in (answers or {}).items():
            if part in " ".join(argv):
                return _Done(json.dumps(answer))
        return _Done("{}")

    return calls, runner


def test_the_compatibility_module_still_names_the_github_forge_and_its_queries():
    from cockpitlib import forge

    assert (
        forge.Forge is GitHubForge
        and forge.READY
        and forge.RESOLVE
        and forge.ADD_THREAD
        and forge.THREADS
        and forge.GREEN
    )
    assert isinstance(forges.make({"forge": {"org": "example"}}), GitHubForge) and forges.kind_of({}) == "github"
    with pytest.raises(PackError, match="forge.kind is one of"):
        forges.implementation("nowhere")


def test_each_github_operation_is_the_call_it_was():
    calls, runner = _recording(
        {
            "search/issues": {
                "items": [{"repository_url": "https://api.example.test/repos/example/api", "number": 4, "title": "T"}]
            },
            "labels?per_page": [{"name": "Bug"}],
            "/jobs": {"jobs": [{"id": 1}]},
            "actions/runs?head_sha": {"workflow_runs": [{"id": 9}]},
        }
    )
    forge = GitHubForge({"forge": {"org": "example", "human_login": "dev"}}, runner=runner)
    assert forge.review_requests() == [{"repo": "api", "number": 4, "title": "T"}]
    assert (
        forge.repo_labels("api") == ["Bug"]
        and forge.run_jobs("api", 7) == [{"id": 1}]
        and forge.runs("api", "abc") == [{"id": 9}]
    )
    forge.set_labels("api", 3, ["a"])
    forge.assign("api", 3, ["dev"])
    forge.rerun_failed("api", 7)
    forge.discard_review("api", 3, 5)
    forge.update_review("api", 3, 5, "s")
    forge.submit_review("api", 3, 5, "COMMENT", "s")
    forge.edit_review_comment("api", 8, "b")
    forge.add_review_thread("api", 3, {"node_id": "N"}, {"path": "a", "body": "b", "line": 1, "side": "RIGHT"})
    forge.resolve_thread("T1")
    assert [(argv[2:], body) for argv, body in calls] == [
        (["search/issues?q=is%3Apr%20is%3Aopen%20review-requested%3Adev%20org%3Aexample&per_page=20"], None),
        (["repos/example/api/labels?per_page=100"], None),
        (["repos/example/api/actions/runs/7/jobs"], None),
        (["repos/example/api/actions/runs?head_sha=abc&per_page=100"], None),
        (["repos/example/api/issues/3/labels", "--method", "PUT", "--input"], {"labels": ["a"]}),
        (["repos/example/api/issues/3/assignees", "--method", "POST", "--input"], {"assignees": ["dev"]}),
        (["repos/example/api/actions/runs/7/rerun-failed-jobs", "--method", "POST", "--input"], {}),
        (["repos/example/api/pulls/3/reviews/5", "--method", "DELETE", "--input"], {}),
        (["repos/example/api/pulls/3/reviews/5", "--method", "PUT", "--input"], {"body": "s"}),
        (
            ["repos/example/api/pulls/3/reviews/5/events", "--method", "POST", "--input"],
            {"event": "COMMENT", "body": "s"},
        ),
        (["repos/example/api/pulls/comments/8", "--method", "PATCH", "--input"], {"body": "b"}),
        (
            ["graphql", "--input"],
            {"query": ADD_THREAD, "variables": {"review": "N", "path": "a", "body": "b", "line": 1, "side": "RIGHT"}},
        ),
        (["graphql", "--input"], {"query": RESOLVE, "variables": {"id": "T1"}}),
    ]
    assert all(argv[:2] == ["gh", "api"] for argv, _body in calls)
    assert forge.branch_url("api", "work/x") == "https://github.com/example/api/tree/work/x"
    assert forge.review_url("api", 3, 5) == "https://github.com/example/api/pull/3#pullrequestreview-5"
    assert forge.run_url("api", 7) == "https://github.com/example/api/actions/runs/7"
    assert forge.hosts() == ["github.com"] and set(forge.capabilities()) == set(base.CAPABILITIES)
    assert (
        any("gh" in pattern and "pr" in pattern for pattern in GitHubForge.cli_deny())
        and forges.cli_deny() == GitHubForge.cli_deny()
    )


def test_the_diffs_and_the_listing_are_the_commands_they_were(monkeypatch):
    import subprocess

    asked = []

    def run(argv, **kwargs):
        asked.append((argv, kwargs.get("timeout")))
        return _Done("diff --git", 0)

    monkeypatch.setattr(subprocess, "run", run)
    forge = GitHubForge({"forge": {"org": "example"}})
    assert (
        forge.compare_diff("example/api", "a", "b") == "diff --git" and forge.pr_diff("example/api", 7) == "diff --git"
    )
    assert asked == [
        (["gh", "api", "repos/example/api/compare/a...b", "-H", "Accept: application/vnd.github.diff"], 15),
        (["gh", "pr", "diff", "7", "--repo", "example/api"], 8),
    ]
    listed = []
    assert forge.list_prs(
        "example/api", "merged", base="main", runner=lambda argv: listed.append(argv) or _Done('[{"number": 1}]')
    ) == [{"number": 1}]
    assert listed == [
        [
            "gh",
            "pr",
            "list",
            "--repo",
            "example/api",
            "--state",
            "merged",
            "--limit",
            "40",
            "--json",
            "number,title,body,headRefName,headRefOid,baseRefName,url,createdAt,mergedAt,author,files",
            "--base",
            "main",
        ]
    ]


def test_a_read_handed_no_pack_asks_the_bound_packs_forge_and_github_when_none_is_bound(bare, monkeypatch):
    from cockpitlib import acts

    assert isinstance(acts._bound_forge(), GitHubForge) and acts._bound_forge().org
    monkeypatch.setenv("COCKPIT_PACK", str(bare["root"] / "no-pack.yaml"))
    assert isinstance(acts._bound_forge(), GitHubForge) and acts._bound_forge().org == ""


class _Old:
    """A forge double from before the protocol: REST paths, and two of the first operations."""

    dry_run = True

    def __init__(self):
        self.asked = []

    def repo(self, name):
        return f"old/{name}"

    def pr(self, repo, number):
        return {"draft": True, "node_id": "P1"}

    def get(self, path):
        self.asked.append(("GET", path))
        return (
            [{"id": 1, "user": {"login": "rev"}, "body": "hello", "created_at": "2026-01-01T00:00:00Z"}]
            if "/issues/" in path
            else []
        )

    def write(self, method, path, body=None):
        self.asked.append((method, path, body))
        return {"html_url": "u"}

    def graphql(self, query, variables, write=False):
        self.asked.append(("GRAPHQL", variables, write))
        return {}


def test_an_object_from_before_the_protocol_is_asked_what_it_was_asked_before():
    old = _Old()
    forge = forges.seam(old)
    assert isinstance(forge, Wrapped) and forges.seam(forge) is forge and forges.seam(None) is None
    assert forge.dry_run is True and forge.writes == [] and forge.repo("api") == "old/api"
    assert [row["id"] for row in forge.comments("api", 2)] == ["issue:1"]
    forge.mark_ready("api", 2)
    forge.discard_review("api", 2, 5)
    assert forge.add_comment("api", 2, "hi") == {"html_url": "u"}
    assert forge.threads("api", 2) == []
    assert old.asked == [
        ("GET", "repos/old/api/issues/2/comments?per_page=100"),
        ("GET", "repos/old/api/pulls/2/comments?per_page=100"),
        ("GET", "repos/old/api/pulls/2/reviews?per_page=100"),
        ("GRAPHQL", {"id": "P1"}, True),
        ("DELETE", "repos/old/api/pulls/2/reviews/5", None),
        ("POST", "repos/old/api/issues/2/comments", {"body": "hi"}),
        ("GRAPHQL", {"o": "old", "r": "api", "n": 2}, False),
    ]
    assert (
        base.CONDITIONAL_READS not in forge.capabilities()
        and forge.url("api", 2) == "https://github.com/old/api/pull/2"
    )
    with pytest.raises(AttributeError):
        forge.get_if_changed("x")
    old.get_if_changed = lambda path, etag: {"changed": False, "etag": etag, "body": None}
    assert base.CONDITIONAL_READS in forges.seam(old).capabilities()
    assert forges.seam(old).runs_if_changed("api", "abc", "e1") == {"changed": False, "etag": "e1", "runs": None}


def test_a_forge_without_an_operation_refuses_by_the_name_of_what_it_lacks():
    class Bare(base.Forge):
        kind = "bare"

    forge = Bare()
    assert forge.capabilities() == frozenset() and forge.hosts() == [] and Bare.cli_deny() == () and forge.me() == ""
    assert forge.compare_diff("api", "a", "b") == "" and forge.pr_diff("api", 1) == "" and forge.repo("api") == "/api"
    calls = [
        (forge.url, ("api",)),
        (forge.pr, ("api", 1)),
        (forge.pr_for_head, ("api", "h")),
        (forge.open_prs_for_branch, ("api", "h")),
        (forge.list_prs, ("api", "open")),
        (forge.create_pr, ("api", "t", "b", "h", "main")),
        (forge.update_pr, ("api", 1, {})),
        (forge.mark_ready, ("api", 1)),
        (forge.labels, ("api", 1)),
        (forge.repo_labels, ("api",)),
        (forge.set_labels, ("api", 1, [])),
        (forge.add_labels, ("api", 1, [])),
        (forge.remove_label, ("api", 1, "x")),
        (forge.assign, ("api", 1, [])),
        (forge.comments, ("api", 1)),
        (forge.add_comment, ("api", 1, "b")),
        (forge.reply, ("api", 1, 2, "b")),
        (forge.edit_review_comment, ("api", 2, "b")),
        (forge.reactions, ("api", 2)),
        (forge.react, ("api", 2)),
        (forge.threads, ("api", 1)),
        (forge.resolve_thread, ("T",)),
        (forge.reviews, ("api", 1)),
        (forge.review, ("api", 1, 2)),
        (forge.review_comments, ("api", 1, 2)),
        (forge.create_review, ("api", 1, "sha", [])),
        (forge.add_review_thread, ("api", 1, {}, {})),
        (forge.update_review, ("api", 1, 2, "b")),
        (forge.submit_review, ("api", 1, 2, "COMMENT", "b")),
        (forge.discard_review, ("api", 1, 2)),
        (forge.checks, ("api", "sha")),
        (forge.runs, ("api", "sha")),
        (forge.runs_if_changed, ("api", "sha")),
        (forge.run_jobs, ("api", 1)),
        (forge.job_log, ("api", 1)),
        (forge.rerun_failed, ("api", 1)),
        (forge.compare, ("api", "a", "b")),
        (forge.review_requests, ()),
    ]
    for call, args in calls:
        with pytest.raises(base.Unsupported, match="the bare forge has no "):
            call(*args)
    assert issubclass(base.Unsupported, CockpitError)


def test_an_intent_type_names_the_capabilities_it_needs():
    assert base.needs("open-pr", {}) == [base.PULL_REQUESTS] and base.needs("open-pr", {"ready": True}) == [
        base.PULL_REQUESTS,
        base.DRAFT,
    ]
    assert base.needs("pr-edit", {"ready": True}) == [base.PULL_REQUESTS, base.DRAFT] and base.needs(
        "pr-comment", {}
    ) == [base.PULL_REQUESTS]
    assert base.needs("pr-comment", {"in_reply_to": 1, "react": True}) == [base.REVIEW_THREADS, base.REACTIONS]
    assert base.needs("pr-patch-apply", {}) == [base.REVIEW_THREADS] and base.needs("pr-review-submit", {}) == [
        base.PENDING_REVIEWS,
        base.REVIEW_THREADS,
    ]
    assert (
        base.needs("ci-rerun", {}) == [base.RERUN]
        and base.needs("push-branch", None) == []
        and base.needs("tracker-comment", {}) == []
    )
    assert base.missing(GitHubForge({}), "ci-rerun", {}) == []
