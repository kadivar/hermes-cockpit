# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""forge.kind local: pull requests, reviews and checks live in files under one folder and a push goes to a bare
repository there. No network, no CLI, no credentials: the outbox publishes to it and the watch reads it like any forge."""

import json
import os
import shutil
import subprocess
import time

import pytest
import yaml

from cockpitlib import egress, forges
from cockpitlib.errors import CockpitError, PackError
from cockpitlib.forges import base
from cockpitlib.forges.local import LocalForge
from cockpitlib.pack import load
from tests.support import fake_gh
from tests.support.both_packs import PACKS


def _local_pack(tmp_path, pack_file, **local) -> str:
    folder = (
        tmp_path / "packs" / os.path.basename(os.path.dirname(pack_file))
    )  # a fixture pack's @anchors need the folder above to be packs
    shutil.copytree(os.path.dirname(pack_file), folder)
    raw = yaml.safe_load((folder / "pack.yaml").read_text(encoding="utf-8"))
    raw["forge"] = {**(raw.get("forge") or {}), "kind": "local", **({"local": local} if local else {})}
    (folder / "pack.yaml").write_text(yaml.safe_dump(raw, sort_keys=False, allow_unicode=True), encoding="utf-8")
    return str(folder / "pack.yaml")


def _pushed(forge, repo: str, branch: str, text: str = "one") -> str:
    sha = fake_gh.commit(repo, branch, name=f"{branch.replace('/', '-')}.txt", text=f"{text}\n")
    folder = os.path.join(os.environ["COCKPIT_ROOT"], "repos", repo)
    subprocess.run(
        ["git", "-C", folder, "push", "-q", forge.remote(repo), "main", branch], check=True, capture_output=True
    )
    return sha


@pytest.mark.parametrize("pack_file", PACKS)
def test_an_intent_is_published_to_the_local_forge_and_the_watch_reads_what_a_reviewer_wrote(
    env, pack_file, tmp_path, monkeypatch
):
    from cockpitlib import pr_watch
    from cockpitlib.outbox import create, endorse
    from cockpitlib.publish import execute, forge_for

    file = _local_pack(tmp_path, pack_file)
    monkeypatch.setenv("COCKPIT_PACK", file)
    monkeypatch.setenv("PATH", "/usr/bin:/bin")  # no forge CLI is on the path, and none is asked for
    pack = load(file)
    forge = forge_for(pack)
    assert (
        type(forge) is LocalForge
        and forge.hosts() == []
        and LocalForge.cli_deny() == ()
        and base.RERUN not in forge.capabilities()
    )
    assert forge.root() == os.path.join(str(env["workspace"]), os.path.basename(os.path.dirname(forge.root())), "forge")
    repo = pack["repos"]["repos"][0]["name"]
    ticket = f"{pack['tracker']['project']}-2101"
    branch = f"work/{ticket}"
    sha = _pushed(forge, repo, branch)
    draft = env["workspace"] / "pr.md"
    draft.write_text(f"Ticket {ticket}\n", encoding="utf-8")
    made = create(
        pack,
        ticket,
        "open-pr",
        "c",
        "open",
        {"repo": repo, "branch": branch, "title": f"{ticket}: a change", "body_file": str(draft), "labels": ["review"]},
    )
    receipt = execute(endorse(made["id"], "low", "", "gatekeeper", "fixture-a", "fixture-large"), pack=pack)
    assert receipt["ok"] and receipt["url"] == f"local://{forge.org}/{repo}/pull/1" and "read back" in receipt["output"]
    found = forge.pr(repo, 1)
    assert (found["title"], found["head"], forge.labels(repo, 1)) == (
        f"{ticket}: a change",
        {"ref": branch, "sha": sha},
        ["review"],
    )
    record = pr_watch.read(pack, forge, ticket, repo, 1, time.time())
    assert (record["state"], record["role"], record["head_sha"], record["url"]) == (
        "open",
        "author",
        sha,
        receipt["url"],
    )
    forge.add_comment(repo, 1, "Please add a test.", author="reviewer")
    record = pr_watch.read(pack, forge, ticket, repo, 1, time.time())
    assert [(row["author"], row["body"]) for row in record["new"]] == [("reviewer", "Please add a test.")]
    later = _pushed(forge, repo, branch, "two")
    assert later != sha and forge.pr(repo, 1)["head"]["sha"] == later  # an open pull request's head follows its branch
    with pytest.raises(
        CockpitError, match=r"the pack's forge \(local\) has no rerun: a ci-rerun cannot be published to it"
    ):
        create(pack, ticket, "ci-rerun", "c", "again", {"repo": repo, "run_id": 7})
    assert (
        egress.forge_hosts(pack)[0] == "github.com"
    )  # the built-in forge hosts stay fenced for a pack on the local forge


def test_the_local_forge_keeps_its_files_where_the_pack_says_and_refuses_what_is_not_there(env, tmp_path):
    root = tmp_path / "forge"
    forge = LocalForge({"forge": {"org": "example", "local": {"root": str(root)}}})
    assert forge.root() == str(root) and forge.me() == "human" and forge.url("api") == "local://example/api"
    assert (
        forge.compare_diff("api", "a", "b") == ""
        and forge.pr_diff("api", 1) == ""
        and forge.repo_labels("api") == []
        and forge.review_requests() == []
    )
    with pytest.raises(CockpitError, match="no pull request example/api#1"):
        forge.pr("api", 1)
    with pytest.raises(CockpitError, match="cannot compare"):
        forge.compare("api", "a", "b")
    with pytest.raises(CockpitError, match="bad repo"):
        forge.pr("../outside", 1)
    number = forge.create_pr("api", "T", "B", "work/x", "main")["number"]
    assert forge.pr("api", number)["head"] == {
        "ref": "work/x",
        "sha": "",
    }  # no repository yet: the pull request still exists
    with pytest.raises(CockpitError, match="already open"):
        forge.create_pr("api", "T", "B", "work/x", "main")
    with pytest.raises(CockpitError, match="title, body and base are edited, not state"):
        forge.update_pr("api", number, {"state": "closed"})
    with pytest.raises(CockpitError, match="has no label nope"):
        forge.remove_label("api", number, "nope")
    with pytest.raises(CockpitError, match="in no thread"):
        forge.reply("api", number, 5, "hello")
    with pytest.raises(CockpitError, match="no review comment 5"):
        forge.reactions("api", 5)
    with pytest.raises(CockpitError, match="no review thread T9"):
        forge.resolve_thread("T9")
    with pytest.raises(CockpitError, match="no review 9"):
        forge.review("api", number, 9)
    review = forge.create_review("api", number, "abc", [{"path": "a.txt", "line": 1, "body": "x"}])["id"]
    with pytest.raises(CockpitError, match="already has a pending review"):
        forge.create_review("api", number, "abc", [])
    with pytest.raises(CockpitError, match="submitted as one of"):
        forge.submit_review("api", number, review, "MAYBE", "")
    thread = forge.threads("api", number)[0]["id"]
    forge.resolve_thread(thread, repo="api")
    assert forge.threads("api", number)[0]["isResolved"]
    forge.submit_review("api", number, review, "APPROVE", "fine")
    for refused in (
        lambda: forge.update_review("api", number, review, "late"),
        lambda: forge.discard_review("api", number, review),
        lambda: forge.add_review_thread("api", number, {"id": review}, {"path": "a", "line": 1, "body": "b"}),
    ):
        with pytest.raises(CockpitError, match="is APPROVED, not pending"):
            refused()
    other = forge.create_review(
        "api", number, "abc", [{"path": "b.txt", "line": 2, "body": "theirs"}], author="reviewer"
    )["id"]
    assert [row["id"] for row in forge.reviews("api", number)] == [
        review
    ]  # another person's pending review is theirs alone
    assert len(forge.threads("api", number)) == 1 and [row["kind"] for row in forge.comments("api", number)] == [
        "inline",
        "review",
    ]
    forge.submit_review("api", number, other, "COMMENT", "")
    assert len(forge.threads("api", number)) == 2
    (root / "example" / "api.json").write_text("{not json", encoding="utf-8")
    with pytest.raises(CockpitError, match="is unreadable"):
        forge.pr("api", number)


def test_the_local_forge_lists_closes_asks_for_reviews_and_reports_ci(env, tmp_path):
    pack = {"forge": {"org": "example", "human_login": "dev", "local": {"root": str(tmp_path / "forge")}}}
    forge = LocalForge(pack)
    repo = "api"
    sha = _pushed(forge, repo, "work/one")
    main = subprocess.run(
        ["git", "--git-dir", forge.remote(repo), "rev-parse", "main"], check=True, capture_output=True, text=True
    ).stdout.strip()
    one = forge.create_pr(repo, "One", "", "work/one", "main")["number"]
    two = forge.create_pr(repo, "Two", "", "work/two", "release", author="someone")["number"]
    forge.request_review(repo, two, ["dev"])
    assert forge.review_requests() == [{"repo": "api", "number": two, "title": "Two"}]
    listed = forge.list_prs(repo, "open")
    assert [(row["number"], row["headRefName"], row["baseRefName"], row["author"]["login"]) for row in listed] == [
        (two, "work/two", "release", "someone"),
        (one, "work/one", "main", "dev"),
    ]
    assert (
        listed[1]["headRefOid"] == sha
        and listed[1]["files"] == [{"path": "work-one.txt"}]
        and listed[1]["url"] == forge.url(repo, one)
    )
    assert [row["number"] for row in forge.list_prs(repo, "open", base="main")] == [one] and forge.list_prs(
        repo, "merged"
    ) == []
    forge.close_pr(repo, one, merged=True)
    forge.close_pr(repo, two)
    assert [row["number"] for row in forge.list_prs(repo, "merged")] == [one] and [
        row["number"] for row in forge.list_prs(repo, "closed")
    ] == [two]
    assert (
        forge.pr(repo, one)["merged"]
        and forge.pr(repo, one)["merged_at"]
        and forge.pr_for_head(repo, "work/one") == {}
        and forge.review_requests() == []
    )
    assert forge.compare(repo, main, sha) == {"total_commits": 1, "files": [{"filename": "work-one.txt"}]}
    assert "work-one.txt" in forge.compare_diff(repo, main, sha) and "work-one.txt" in forge.pr_diff(repo, one)
    forge.seed_labels(repo, ["Bug", "Review"])
    forge.add_labels(repo, one, ["extra"])
    assert forge.repo_labels(repo) == ["Bug", "Review", "extra"]
    forge.seed_check(repo, sha, "unit", status="in_progress")
    assert forge.checks(repo, sha) == ["unit: in_progress"]
    forge.seed_run(
        repo,
        7,
        sha,
        "tests",
        conclusion="failure",
        jobs=[
            {"id": 71, "name": "unit", "conclusion": "failure", "log": "boom"},
            {"id": 72, "name": "lint", "conclusion": "success"},
        ],
    )
    forge.seed_run(repo, 8, "other", "tests", status="in_progress")
    assert [(run["id"], run["conclusion"], run["html_url"]) for run in forge.runs(repo, sha)] == [
        (7, "failure", forge.run_url(repo, 7))
    ]
    assert forge.runs(repo, "other")[0]["conclusion"] is None
    assert forge.run_jobs(repo, 7) == [
        {"id": 71, "name": "unit", "conclusion": "failure"},
        {"id": 72, "name": "lint", "conclusion": "success"},
    ]
    assert forge.job_log(repo, 71) == "boom" and forge.run_jobs(repo, 99) == []
    with pytest.raises(CockpitError, match="the log of job 72 is gone"):
        forge.job_log(repo, 72)
    with pytest.raises(CockpitError, match="no job 5"):
        forge.job_log(repo, 5)
    with pytest.raises(base.Unsupported, match="the local forge has no rerun"):
        forge.rerun_failed(repo, 7)
    with pytest.raises(base.Unsupported, match="no conditional-reads"):
        forge.runs_if_changed(repo, sha)


def test_a_dry_run_of_the_local_forge_journals_every_write_and_stores_none(env, tmp_path):
    pack = {"forge": {"org": "example", "local": {"root": str(tmp_path / "forge")}}}
    forge = LocalForge(pack)
    number = forge.create_pr("api", "T", "B", "work/x", "main", draft=True)["number"]
    review = forge.create_review("api", number, "abc", [{"path": "a.txt", "line": 1, "body": "x"}])
    comment = forge.review_comments("api", number, review["id"])[0]["id"]
    thread = forge.threads("api", number)[0]["id"]
    before = json.load(open(tmp_path / "forge" / "example" / "api.json", encoding="utf-8"))
    dry = LocalForge(pack, dry_run=True)
    assert dry.create_pr("api", "T2", "", "work/y", "main") == {"dry_run": True} and dry.create_review(
        "api", number, "abc", []
    ) == {"dry_run": True}
    assert dry.reply("api", number, comment, "r") == {"dry_run": True}
    dry.mark_ready("api", number)
    dry.close_pr("api", number)
    dry.request_review("api", number, ["a"])
    dry.set_labels("api", number, ["a"])
    dry.remove_label("api", number, "nope")
    dry.assign("api", number, ["a"])
    dry.edit_review_comment("api", comment, "e")
    dry.react("api", comment)
    dry.resolve_thread(thread)
    dry.add_review_thread("api", number, review, {"path": "b", "line": 1, "body": "b"})
    dry.update_review("api", number, review["id"], "s")
    dry.submit_review("api", number, review["id"], "COMMENT", "s")
    dry.discard_review("api", number, review["id"])
    assert len(dry.writes) == 16 and dry.writes[0] == {
        "method": "create_pr",
        "path": "example/api",
        "body": {"title": "T2", "body": "", "head": "work/y", "base": "main", "draft": False},
    }
    assert json.load(open(tmp_path / "forge" / "example" / "api.json", encoding="utf-8")) == before
    forge.react("api", comment)
    forge.react("api", comment)
    assert len(forge.reactions("api", comment)) == 1  # the same reaction twice is one
    forge.discard_review("api", number, review["id"])
    assert forge.threads("api", number) == [] and forge.reviews("api", number) == []


@pytest.mark.parametrize("local", [{"root": ""}, {"root": 3}, {"folder": "/x"}, "here"])
def test_a_local_forge_block_that_names_no_folder_is_refused_at_load(tmp_path, local):
    file = _local_pack(tmp_path, PACKS[0])
    raw = yaml.safe_load(open(file, encoding="utf-8"))
    raw["forge"]["local"] = local
    open(file, "w", encoding="utf-8").write(yaml.safe_dump(raw, sort_keys=False))
    with pytest.raises(PackError, match="forge.local takes root"):
        load(file)


def test_the_local_kind_is_a_registered_forge_with_no_host_and_no_cli(tmp_path):
    pack = load(_local_pack(tmp_path, PACKS[0], root=str(tmp_path / "forge")))
    assert (
        forges.kind_of(pack) == "local"
        and type(forges.make(pack)) is LocalForge
        and forges.make(pack).root() == str(tmp_path / "forge")
    )
    assert forges.default_hosts() == ["github.com"] and forges.cli_deny() == forges.implementation("github").cli_deny()
    assert (
        base.missing(forges.make(pack), "ci-rerun", {}) == [base.RERUN]
        and base.missing(forges.make(pack), "pr-review-submit", {}) == []
    )


def test_a_git_that_fails_is_a_refusal_for_the_remote_and_an_empty_answer_for_a_read(env, tmp_path, monkeypatch):
    forge = LocalForge({"forge": {"org": "example", "local": {"root": str(tmp_path / "forge")}}})
    real = subprocess.run
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda argv, **_kwargs: type("Done", (), {"returncode": 1, "stdout": "", "stderr": "no space left"})(),
    )
    with pytest.raises(CockpitError, match="git init .*no space left"):
        forge.remote("api")
    monkeypatch.setattr(subprocess, "run", real)
    forge.remote("api")

    def gone(argv, **_kwargs):
        raise OSError("no git")

    monkeypatch.setattr(subprocess, "run", gone)
    assert forge.compare_diff("api", "a", "b") == ""
