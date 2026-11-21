# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The read-only views' edges: a diff pane after a rebase, an intent's Brief per kind,
QA results tables, lane feeds and transcripts, the plan gate's clock and an infrastructure note that cannot be applied."""

import json
import os
import sqlite3
import subprocess
import time

import pytest

from cockpitlib import diffs, infra_note, intent_view, lane_feed, lane_transcripts, plan_gate, qa_view
from cockpitlib.errors import CockpitError


def _git(folder, *args, env=None):
    return subprocess.run(
        ["git", "-C", str(folder), *args], capture_output=True, text=True, check=True, env=env
    ).stdout.strip()


def _commit(repo, name, text, message, env=None):
    (repo / name).write_text(text, encoding="utf-8")
    _git(repo, "add", "-A", env=env)
    _git(repo, "commit", "-q", "-m", message, env=env)
    return _git(repo, "rev-parse", "HEAD", env=env)


@pytest.fixture(scope="module")
def rebased_repo(tmp_path_factory):
    """Built once (the tests only read it): a branch that was pushed, then rebased on a moved base (the rebase step),
    then extended (the content). Its git runs on its own settings, since the per-test ones are not there yet."""
    folder = tmp_path_factory.mktemp("rebased")
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "Dev",
        "GIT_AUTHOR_EMAIL": "dev@example.test",
        "GIT_COMMITTER_NAME": "Dev",
        "GIT_COMMITTER_EMAIL": "dev@example.test",
        "GIT_CONFIG_COUNT": "2",
        "GIT_CONFIG_KEY_0": "commit.gpgsign",
        "GIT_CONFIG_VALUE_0": "false",
        "GIT_CONFIG_KEY_1": "init.defaultBranch",
        "GIT_CONFIG_VALUE_1": "main",
    }
    remote = folder / "origin.git"
    repo = folder / "api"
    subprocess.run(["git", "init", "--bare", "-q", str(remote)], check=True, capture_output=True, env=env)
    subprocess.run(["git", "init", "-q", str(repo)], check=True, capture_output=True, env=env)
    _git(repo, "config", "user.name", "Dev", env=env)  # a test that commits here has an author on a machine with none
    _git(repo, "config", "user.email", "dev@example.test", env=env)
    first = _commit(repo, "README", "hello\n", "init", env)
    _git(repo, "remote", "add", "origin", str(remote), env=env)
    _git(repo, "push", "-q", "origin", "main", env=env)
    _git(repo, "switch", "-q", "-c", "feat", env=env)
    pushed = _commit(repo, "feature.txt", "one\n", "Add the feature", env)
    _git(repo, "push", "-q", "origin", "feat", env=env)
    _git(repo, "switch", "-q", "main", env=env)
    moved = _commit(repo, "base.txt", "base\n", "Move the base", env)
    _git(repo, "push", "-q", "origin", "main", env=env)
    _git(repo, "switch", "-q", "feat", env=env)
    _git(repo, "rebase", "-q", "main", env=env)
    step = _git(repo, "rev-parse", "HEAD", env=env)
    content = _commit(repo, "feature.txt", "one\ntwo\n", "Extend the feature", env)
    _git(repo, "fetch", "-q", "origin", env=env)
    return {"repo": repo, "first": first, "pushed": pushed, "moved": moved, "step": step, "content": content}


@pytest.fixture
def rebased(rebased_repo, monkeypatch):
    repo = rebased_repo["repo"]
    monkeypatch.setattr(diffs, "checkout_of", lambda _ticket, _repo, _pack=None: str(repo))
    step_row = {
        "id": "ACME-1/001-push-branch",
        "ticket": "ACME-1",
        "type": "push-branch",
        "payload": {
            "repo": "api",
            "branch": "feat",
            "sha": rebased_repo["step"],
            "rebase_only": True,
            "base_before": rebased_repo["first"],
            "base_after": rebased_repo["moved"],
            "remote_sha": rebased_repo["pushed"],
            "rebase_proof": "patch ids match",
            "rebase_commits": 1,
        },
    }
    content_row = {
        "id": "ACME-1/002-push-branch",
        "ticket": "ACME-1",
        "type": "push-branch",
        "payload": {"repo": "api", "branch": "feat", "sha": rebased_repo["content"], "after": step_row["id"]},
    }
    return {**rebased_repo, "step_row": step_row, "content_row": content_row, "rows": [step_row, content_row]}


# ---------- diffs ----------


def test_git_says_what_went_wrong_when_it_is_missing_slow_or_refuses(tmp_path, monkeypatch):
    with pytest.raises(CockpitError, match="not a git repository"):
        diffs.git(str(tmp_path), "status")
    assert diffs.last_fetch(str(tmp_path)) is None

    def missing(*_args, **_more):
        raise FileNotFoundError("git")

    def slow(*_args, **_more):
        raise subprocess.TimeoutExpired("git", 30)

    monkeypatch.setattr(subprocess, "run", missing)
    with pytest.raises(CockpitError, match="^git not found$"):
        diffs.git(str(tmp_path), "status")
    monkeypatch.setattr(subprocess, "run", slow)
    with pytest.raises(CockpitError, match="^git status timed out$"):
        diffs.git(str(tmp_path), "status")


def test_a_diff_past_the_limit_is_cut_and_says_so(monkeypatch):
    monkeypatch.setattr(diffs, "MAX_DIFF", 10)
    out = diffs._cut({"diff": "x" * 50, "uncommitted_diff": "short"})
    assert out["diff"] == "x" * 10 + "\n\n… truncated at 10 bytes; open the IDE for the rest\n"
    assert out["uncommitted_diff"] == "short"


def test_a_base_with_no_common_history_is_compared_as_it_is(rebased):
    repo = rebased["repo"]
    lone = _git(repo, "commit-tree", "-m", "an unrelated root", rebased["first"] + "^{tree}")
    out = diffs.diff_payload(str(repo), lone, "HEAD", include_uncommitted=False)
    assert out["merge_base"] == lone[:12] and out["range"] == f"{lone}..HEAD"
    assert [line.split(" ", 1)[1].split(" (")[0] for line in out["commits"]] == [
        "Extend the feature",
        "Add the feature",
        "Move the base",
        "init",
    ]
    assert "uncommitted_diff" not in out


def test_the_change_view_shows_the_content_on_top_of_the_rebase_step(rebased, monkeypatch):
    out = diffs.intent_diff({}, rebased["content_row"], rebased["rows"], mode="change")
    assert out["mode"] == "change" and out["base"] == rebased["step"] and out["head"] == rebased["content"]
    assert out["remote"] == f"rebase step ACME-1/001-push-branch @ {rebased['step'][:9]}"
    assert [line.split(" ", 1)[1].split(" (")[0] for line in out["commits"]] == [
        "Extend the feature",
        "Add the feature",
    ]
    assert "+two" in out["diff"] and "+one" not in out["diff"] and "feature.txt" in out["stat"]
    assert "Extend the feature" in out["range_diff"] and out["uncommitted_status"] == ""
    real = diffs.git

    def no_range_diff(folder, *args, **more):
        if args[0] == "range-diff":
            raise CockpitError("boom")
        return real(folder, *args, **more)

    monkeypatch.setattr(diffs, "git", no_range_diff)
    assert (
        diffs.intent_diff({}, rebased["content_row"], rebased["rows"], mode="change")["range_diff"]
        == "(range-diff failed: boom)"
    )


def test_the_rebase_view_shows_the_step_against_origin_with_its_proof(rebased):
    out = diffs.intent_diff({}, rebased["content_row"], rebased["rows"], mode="rebase")
    assert (
        out["mode"] == "rebase"
        and out["head"] == rebased["step"]
        and out["remote"] == "origin/feat"
        and out["fast_forward"] is False
    )
    assert [item["state"] for item in out["dropped"]] == ["replaced"] and "Add the feature" in out["dropped"][0]["line"]
    assert len(out["commits"]) == 1 and "Add the feature" in out["commits"][0]
    assert len(out["commits_base"]) == 1 and "Move the base" in out["commits_base"][0]
    proof = out["rebase"]
    assert proof["proof"] == "patch ids match" and proof["commits"] == 1 and proof["step"] == "ACME-1/001-push-branch"
    assert proof["base_before"] == rebased["first"][:9] and proof["base_after"] == rebased["moved"][:9]
    assert "Add the feature" in proof["range_diff"] and proof["base_log"].endswith("Move the base (Dev)")
    alone = diffs.intent_diff({}, rebased["step_row"], rebased["rows"], mode="rebase")
    assert alone["head"] == rebased["step"] and alone["rebase"]["step"] == "ACME-1/001-push-branch"


def test_the_rebase_view_refuses_an_intent_with_no_rebase_step(rebased):
    row = {**rebased["content_row"], "payload": {"repo": "api", "branch": "feat", "sha": rebased["content"]}}
    with pytest.raises(CockpitError, match="no rebase step for this intent"):
        diffs.intent_diff({}, row, rebased["rows"], mode="rebase")


def test_the_origin_view_of_a_rebase_only_push_carries_the_rebase_and_survives_a_commit_it_cannot_read(rebased):
    out = diffs.intent_diff({}, rebased["step_row"], rebased["rows"], mode="origin")
    assert out["mode"] == "origin" and out["intent"] == "ACME-1/001-push-branch" and out["uncommitted_diff"] == ""
    assert "Add the feature" in out["rebase"]["range_diff"] and out["rebase"]["base_log"].endswith(
        "Move the base (Dev)"
    )
    unknown = {
        **rebased["step_row"],
        "payload": {**rebased["step_row"]["payload"], "remote_sha": "", "base_before": "deadbeef1"},
    }
    proof = diffs.intent_diff({}, unknown, rebased["rows"], mode="origin")["rebase"]
    assert (
        proof["range_diff"] == ""
        and proof["base_log"].startswith("(git failed: ")
        and proof["base_before"] == "deadbeef1"
    )


def test_an_intent_that_names_no_commit_is_diffed_from_the_checkout_head(rebased):
    row = {
        "id": "ACME-1/003-pr-comment",
        "ticket": "ACME-1",
        "type": "pr-comment",
        "payload": {"repo": "acme/api", "number": 4},
    }
    out = diffs.intent_diff({}, row, [])
    assert (
        out["repo"] == "api"
        and out["intent"] == "ACME-1/003-pr-comment"
        and out["head"] == "HEAD"
        and out["base"] == "origin/main"
    )
    assert len(out["commits"]) == 2 and "+two" in out["diff"]


def test_a_checkout_without_the_base_branch_gets_an_empty_pane_that_says_why(rebased):
    out = diffs.intent_diff({"base_branch": "release"}, rebased["content_row"], rebased["rows"], mode="origin")
    assert out["note"] == f"the checkout at {rebased['repo']} has no release to compare against yet"
    assert (
        out["diff"] == ""
        and out["commits"] == []
        and out["mode"] == "origin"
        and out["intent"] == "ACME-1/002-push-branch"
    )


def test_a_ticket_without_a_worktree_is_read_in_the_repo_clone_that_has_the_commit(rebased, monkeypatch):
    def no_worktree(_ticket, _repo, _pack=None):
        raise CockpitError("no worktree for REL-2")

    monkeypatch.setattr(diffs, "checkout_of", no_worktree)
    pack = {"repos": {"repos": [{"name": "api", "path": str(rebased["repo"])}]}}
    row = {
        "id": "REL-2/001-push-branch",
        "ticket": "REL-2",
        "type": "push-branch",
        "payload": {"repo": "api", "sha": rebased["content"]},
    }
    out = diffs.intent_diff(pack, row, [])
    assert out["repo_dir"] == str(rebased["repo"]) and out["head"] == rebased["content"] and len(out["commits"]) == 2
    for refused_pack, payload in (
        (pack, {"repo": "api"}),  # names no commit
        (pack, {"repo": "api", "sha": "deadbeef1"}),  # a commit the clone lacks
        (None, {"repo": "api", "sha": rebased["content"]}),
    ):  # no pack to find the clone in
        with pytest.raises(CockpitError, match="no worktree for REL-2"):
            diffs.intent_diff(refused_pack, {**row, "payload": payload}, [])


# ---------- intent_view ----------


def test_a_file_that_cannot_be_read_says_so_in_its_place(tmp_path):
    assert intent_view.read_text(str(tmp_path / "gone.md"), 100).startswith("(unreadable: ")


def test_the_plan_one_liner_is_its_change_line_else_the_first_line_of_its_brief(monkeypatch):
    from cockpitlib import plan

    monkeypatch.setattr(
        plan,
        "show",
        lambda _ticket: (
            "# ACME-5\n**Change in one line:** Trim the export\n\n## Brief\nLonger words\n\n## Verify\nrun it\n"
        ),
    )
    assert intent_view.plan_one_liner("ACME-5") == ("Trim the export", ["Brief", "Verify"])
    monkeypatch.setattr(plan, "show", lambda _ticket: "## Brief\n\nThe export is trimmed\nmore\n")
    assert intent_view.plan_one_liner("ACME-5") == ("The export is trimmed", ["Brief"])
    monkeypatch.setattr(plan, "show", lambda _ticket: "")
    assert intent_view.plan_one_liner("ACME-5") == ("", [])


def test_a_push_that_recorded_no_shape_is_read_from_the_checkout(rebased):
    row = {
        "ticket": "ACME-1",
        "type": "push-branch",
        "payload": {"repo": "api", "sha": rebased["content"], "base": "main"},
    }
    commits, files, stat = intent_view.push_shape(row, {})
    assert [line.split(" ", 1)[1] for line in commits] == ["Extend the feature", "Add the feature"]
    assert files == ["feature.txt"] and stat == "1 file changed, 2 insertions(+)"
    assert intent_view.push_shape({**row, "payload": {"repo": "api", "sha": "not-a-sha"}}, {}) == ([], [], "")
    assert intent_view.push_shape(
        {**row, "payload": {"repo": "api", "sha": rebased["content"], "base": "ghost"}}, {}
    ) == ([], [], "")


def _what(kind, payload, **more):
    return intent_view.brief_fields({"type": kind, "payload": payload, **more})[0]["text"]


def test_the_brief_names_what_leaves_for_each_kind_of_intent():
    assert (
        _what("open-pr", {"repo": "api", "title": "Trim", "branch": "feat"})
        == "a new PR on api: Trim (feat → the base branch)"
    )
    assert _what("pr-comment", {"repo": "api", "number": 4}) == "a comment on api#4, top level"
    assert (
        _what("pr-comment", {"repo": "api", "number": 4, "in_reply_to": 9, "resolve": True})
        == "a comment on api#4 as a reply in a review thread, resolving it"
    )
    assert _what("pr-edit", {}, target="api#4") == "PR metadata on api#4"
    assert _what("tracker-create", {"summary": "Flaky export"}) == "a new tracker ticket: Flaky export"
    assert _what("tracker-transition", {"to": "In Review"}, ticket="ACME-5") == "tracker issue ACME-5 → In Review"
    assert _what("ci-rerun", {"repo": "api", "run_id": 77}) == "a rerun of CI run 77 on api (flaky verdict)"
    assert _what("infra-note", {}, target="the CI workflow") == "the CI workflow"
    pushed = _what(
        "pr-patch-apply",
        {
            "repo": "api",
            "number": 4,
            "branch": "feat",
            "sha": "abc1234",
            "remote_sha": "0001111",
            "commits": ["a", "b"],
            "files": ["x.py"],
        },
    )
    assert pushed.startswith(
        "the patch apply on api#4, in one go: the push of `feat` (2 commit(s), 1 file(s)), then every agreed"
    )
    assert "no push (nothing new on the branch)" in _what(
        "pr-patch-apply", {"repo": "api", "number": 4, "commits": ["a"]}
    )


def test_the_brief_lists_what_was_checked_and_what_a_push_touches():
    files = [f"src/f{index}.py" for index in range(9)]
    row = {
        "type": "pr-patch-apply",
        "status": "held",
        "hold": {"reason": "needs a look"},
        "chain": {"role": "content", "step1_status": "published"},
        "returned": {"lane": "worker-1", "instruction": "split it", "resolved": True},
        "pr": {"new_count": 2},
        "ci": {"state": "failure", "sha": "abc1234", "summary": "2 failed"},
        "payload": {
            "repo": "api",
            "number": 4,
            "after": "ACME-1/001-push-branch",
            "commits": ["a"],
            "files": files,
            "diffstat": "9 files changed",
        },
    }
    fields = {field["label"]: field["items"] for field in intent_view.brief_fields(row)}
    assert fields["Checked"] == [
        "held by the gatekeeper: needs a look",
        "paired with the rebase step ACME-1/001-push-branch (published)",
        "sent back once to worker-1: split it · reworked",
        "2 PR comment(s) arrived after the pipeline's pass",
        "CI failure @ abc1234: 2 failed",
    ]
    assert fields["Touches"] == ["9 files changed"] + [f"`{name}`" for name in files[:8]] + ["… 1 more"]
    rerun = intent_view.brief_fields({"type": "ci-rerun", "payload": {"repo": "api", "run_id": 77, "attempt": 2}})
    assert rerun[3]["items"] == ["run 77 · attempt 2"]


def test_the_brief_of_a_finished_ticket_tells_what_shipped_and_its_trail(monkeypatch):
    from cockpitlib import plan

    monkeypatch.setattr(
        plan, "show", lambda _ticket: "**Change in one line:** Trim the export\n## Brief\nwords\n## Verify\nrun\n"
    )
    row = {"type": "ticket-done", "ticket": "ACME-5", "payload": {"number": 12, "merged_at": "2026-11-01T10:00:00Z"}}
    fields = intent_view.brief_fields(row)
    assert fields[0]["text"].startswith("nothing. Your acknowledgement")
    assert fields[3]["items"] == [
        "shipped: Trim the export",
        "trail: Brief, Verify",
        "PR #12 merged at 2026-11-01T10:00",
    ]


def test_an_enriched_intent_renders_a_tracker_document_and_keeps_its_receipt_lines(tmp_path, monkeypatch):
    from cockpitlib import paths

    body = tmp_path / "001-body.json"
    body.write_text(
        json.dumps(
            {
                "type": "doc",
                "version": 1,
                "content": [{"type": "paragraph", "content": [{"type": "text", "text": "Hello tracker"}]}],
            }
        ),
        encoding="utf-8",
    )
    plain = tmp_path / "001-data.json"
    plain.write_text('{"rows": 3}', encoding="utf-8")
    notes = tmp_path / "001-notes.md"
    notes.write_text("# Notes\n", encoding="utf-8")
    receipts = tmp_path / "_published.log"
    receipts.write_text(
        "POSTED ACME-5/001-tracker-comment ok\nPOSTED ACME-5/002-tracker-comment ok\n", encoding="utf-8"
    )
    monkeypatch.setattr(paths, "receipt_log", lambda: str(receipts))
    row = {
        "id": "ACME-5/001-tracker-comment",
        "ticket": "ACME-5",
        "type": "tracker-comment",
        "status": "pending",
        "summary": "Report the run",
        "payload": {"issue": "ACME-5"},
        "files": {"body_file": str(body), "data": str(plain), "notes": str(notes), "gone": str(tmp_path / "no.md")},
    }
    out = intent_view.enrich(row, {})
    assert (
        "Hello tracker" in out["file_html"]["body_file"]
        and "data" not in out["file_html"]
        and "<h1" in out["file_html"]["notes"]
    )
    assert out["file_contents"]["gone"].startswith("(unreadable: ") and out["file_truncated"] == []
    assert (
        out["log"] == ["POSTED ACME-5/001-tracker-comment ok"]
        and out["outgoing"] == "body_file"
        and out["ci_override_allowed"] is False
    )
    assert "a comment on the tracker issue ACME-5" in out["brief"] and "waiting for the gatekeeper" in out["brief"]
    assert "files" in row and "brief" not in row  # the list row itself is left as it was


# ---------- qa_view ----------


def test_evidence_files_are_listed_by_kind_without_the_hidden_ones(tmp_path, monkeypatch):
    for name in ("clip.mov", "report.pdf", "dump.bin", ".DS_Store", "note.md"):
        (tmp_path / name).write_bytes(b"1234")
    assert qa_view.read_text(str(tmp_path / "missing.md")) == ""
    real = os.path.getsize
    monkeypatch.setattr(
        os.path,
        "getsize",
        lambda path: (_ for _ in ()).throw(OSError("gone")) if str(path).endswith(".bin") else real(path),
    )
    assert [(item["rel"], item["kind"], item["size"]) for item in qa_view.list_files(str(tmp_path))] == [
        ("clip.mov", "video", 4),
        ("dump.bin", "other", 0),
        ("note.md", "text", 4),
        ("report.pdf", "pdf", 4),
    ]


def test_a_ticket_folder_is_found_however_its_case_was_written(tmp_path, monkeypatch):
    from cockpitlib import paths

    (tmp_path / "acme-7").mkdir()
    monkeypatch.setattr(paths, "qa", lambda: str(tmp_path))
    real = os.path.isdir
    with monkeypatch.context() as patch:  # a case-sensitive disk, whatever this machine's is
        patch.setattr(
            os.path, "isdir", lambda path: real(path) and os.path.basename(path) in os.listdir(os.path.dirname(path))
        )
        assert qa_view.qa_dir("ACME-7") == os.path.join(str(tmp_path), "acme-7")
        assert qa_view.qa_dir("ACME-8") is None


def test_a_results_table_without_a_scenario_column_still_gives_its_rows_dates_and_evidence(tmp_path):
    path = tmp_path / "test-results.md"
    path.write_text(
        "# Run 3\nDate: 2026-03-04 in the evening\n- **Ticket under test:** ACME-7\n\n## Summary\n"
        "| 9 | ❌ before any header |\n| # | Verdict | Evidence |\n|---|---|---|\n| 1 | ✅ pass | shots/*.png |\n",
        encoding="utf-8",
    )
    out = qa_view.parse_results(str(path))
    assert out["rows"] == [
        {
            "n": "1",
            "scenario": "✅ pass",
            "result": "✅ pass",
            "verdict": "pass",
            "note": "",
            "evidence": [{"label": "shots/*.png", "rel": "shots/*.png", "glob": True}],
        }
    ]
    assert out["date"] == "2026-03-04" and out["date_detail"] == "2026-03-04 in the evening"
    assert out["meta"]["Under test"] == "ACME-7" and out["title"] == "Run 3" and out["sections"] == {}


def test_the_qa_index_skips_underscore_folders_and_loose_files(tmp_path, monkeypatch):
    from cockpitlib import paths

    (tmp_path / "_archive" / "run-1").mkdir(parents=True)
    (tmp_path / "README.md").write_text("notes\n", encoding="utf-8")
    (tmp_path / "ACME-7" / "run-1").mkdir(parents=True)
    monkeypatch.setattr(paths, "qa", lambda: str(tmp_path))
    monkeypatch.setattr(
        qa_view,
        "_runs_of",
        lambda folder, _pack=None: sorted(name for name in os.listdir(folder) if name.startswith("run-")),
    )
    found = qa_view.index({})["tickets"]
    assert [(item["ticket"], item["runs"], item["last_run"], item["scenarios"]) for item in found] == [
        ("ACME-7", 1, "run-1", 0)
    ]


def test_a_media_file_past_the_limit_is_not_inlined(tmp_path, monkeypatch):
    clip = tmp_path / "clip.mov"
    clip.write_bytes(b"0123456789")
    monkeypatch.setattr(qa_view, "MEDIA_LIMIT", 4)
    assert qa_view.file_record(str(clip)) == {
        "kind": "large",
        "mime": "video/quicktime",
        "size": 10,
        "text": "10 bytes: open it from the folder instead",
    }


# ---------- lane_feed ----------


def test_the_jobs_list_survives_a_board_without_events_and_an_intent_with_no_readable_time(tmp_path, monkeypatch):
    from cockpitlib import intents, kanban

    board = tmp_path / "kanban.db"
    connection = sqlite3.connect(str(board))
    connection.execute("create table tasks (id text, title text)")
    connection.commit()
    connection.close()
    monkeypatch.setattr(kanban, "db_path", lambda _slug: str(board))
    monkeypatch.setattr(
        intents,
        "all_intents",
        lambda: [
            {"ticket": "ACME-3", "created_at": "not a time"},
            {"ticket": "", "created_at": ""},
            {"ticket": "ACME-2", "created_at": "2026-01-02T00:00:00Z"},
        ],
    )
    found = lane_feed.jobs({"board": "acme"})
    assert [item["ticket"] for item in found] == ["ACME-2", "ACME-3"]
    assert found[0]["last"].startswith("2026-01-02T00:00") and found[1]["last"] == ""


def test_a_message_whose_tool_calls_do_not_parse_keeps_its_text_only():
    rows = [
        ("assistant", "thinking it over", "{not json", None, 1767225600),
        ("assistant", "", json.dumps([{"function": {"name": "terminal", "arguments": "ls"}}]), None, 1767225601),
    ]
    found = lane_feed._entries(rows, {"who": "worker-1"})
    assert [(item["kind"], item.get("name"), item["text"], item["who"]) for item in found] == [
        ("text", None, "thinking it over", "worker-1"),
        ("tool_use", "terminal", "", "worker-1"),
    ]


# ---------- lane_transcripts ----------


def test_a_transcript_that_vanished_is_skipped_and_what_was_read_of_it_is_forgotten(tmp_path, monkeypatch):
    for card in ("t_aa", "t_bb"):
        (tmp_path / card).mkdir()
    kept = tmp_path / "t_aa" / "run.jsonl"
    kept.write_text("{}\n", encoding="utf-8")
    gone = tmp_path / "t_bb" / "run.jsonl"
    os.symlink(str(tmp_path / "nowhere.jsonl"), str(gone))  # listed by the glob, not there to read
    old = tmp_path / "old.jsonl"
    old.write_text("{}\n", encoding="utf-8")
    long_ago = time.time() - (lane_transcripts.RECENT_DAYS + 1) * 86400
    os.utime(str(old), (long_ago, long_ago))
    monkeypatch.setattr(lane_transcripts, "_lane_glob", lambda: str(tmp_path / "{card}" / "run.jsonl"))
    assert lane_transcripts.by_card([{"id": "t_aa"}, {"id": "t_bb"}]) == {"t_aa": str(kept)}
    seen = {
        str(kept): {"offset": 3, "entries": []},
        str(gone): {"offset": 9, "entries": []},
        str(old): {"offset": 1, "entries": []},
    }
    monkeypatch.setattr(lane_transcripts, "_SEEN", seen)
    lane_transcripts._forget_old()
    assert seen == {str(kept): {"offset": 3, "entries": []}}


# ---------- plan_gate ----------


def _board(path, tables):
    connection = sqlite3.connect(str(path))
    for statement in tables:
        connection.execute(statement)
    connection.commit()
    return connection


def test_the_plan_clock_ignores_an_advisor_time_it_cannot_read_and_a_board_without_events(tmp_path, monkeypatch):
    from cockpitlib import advise

    monkeypatch.setattr(plan_gate, "_card", lambda _pack, _card: {"ticket": "ACME-1"})
    monkeypatch.setattr(
        advise,
        "calls",
        lambda _ticket: [
            {"card": "t_1", "checkpoint": "C0", "time": "around noon"},
            {"card": "t_1", "checkpoint": "C0", "time": "2026-01-01T00:00:00Z"},
            {"card": "t_2", "checkpoint": "C0", "time": "2025-01-01T00:00:00Z"},
        ],
    )
    connection = _board(tmp_path / "empty.db", [])
    assert plan_gate._plan_asked_at({}, connection, "t_1") == 1767225600.0
    connection.close()


def test_a_go_counts_only_after_the_plan_was_asked_and_a_board_without_comments_never_says_ok(tmp_path, monkeypatch):
    from cockpitlib import advise, kanban

    monkeypatch.setattr(plan_gate, "_card", lambda _pack, _card: {"ticket": "ACME-1"})
    monkeypatch.setattr(
        advise, "calls", lambda _ticket: [{"card": "t_1", "checkpoint": "C0", "time": "2026-01-01T00:00:00Z"}]
    )
    bare = tmp_path / "bare.db"
    _board(bare, []).close()
    monkeypatch.setattr(kanban, "db_path", lambda _slug: str(bare))
    assert plan_gate.said_ok({"board": "acme"}, "t_1") is False
    full = tmp_path / "full.db"
    connection = _board(full, ["create table task_comments (task_id text, author text, body text, created_at real)"])
    connection.execute(
        "insert into task_comments values ('t_1', 'human', 'human: go', 5)"
    )  # answered an earlier question
    connection.commit()
    monkeypatch.setattr(kanban, "db_path", lambda _slug: str(full))
    assert plan_gate.said_ok({"board": "acme"}, "t_1") is False
    connection.execute("insert into task_comments values ('t_1', 'human', 'human: plan ok', 1767225601)")
    connection.commit()
    connection.close()
    assert plan_gate.said_ok({"board": "acme"}, "t_1") is True


# ---------- infra_note ----------


@pytest.fixture
def note(tmp_path, monkeypatch):
    from cockpitlib import outbox, paths, worktree

    monkeypatch.delenv("COCKPIT_LANE", raising=False)
    repo = tmp_path / "wt" / "api"
    repo.mkdir(parents=True)
    _git(repo, "init", "-q", "-b", "bump/x")
    _git(repo, "config", "user.email", "me@example.test")
    _git(repo, "config", "user.name", "Me")
    (repo / "run.yml").write_text("node: 18\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "base")
    patch = tmp_path / "ws" / "records" / "qa" / "BATCH-1" / "node.patch"
    patch.parent.mkdir(parents=True)
    patch.write_text("--- a/run.yml\n+++ b/run.yml\n@@ -1 +1 @@\n-node: 18\n+node: 22\n", encoding="utf-8")
    intent = {
        "id": "BATCH-1/009-infra-note",
        "ticket": "BATCH-1",
        "type": "infra-note",
        "status": "pending",
        "created_by": "reviewer-2",
        "agent_summary": "Run the e2e job on Node 22",
        "payload": {"repo": "api", "branch": "bump/x", "patch_file": "records/qa/BATCH-1/node.patch"},
    }
    made = []
    monkeypatch.setattr(infra_note, "load", lambda _id: intent)
    monkeypatch.setattr(infra_note, "save", lambda _row: None)
    monkeypatch.setattr(infra_note, "log", lambda _line: None)
    monkeypatch.setattr(paths, "workspace", lambda: str(tmp_path / "ws"))
    monkeypatch.setattr(worktree, "_checkout", lambda _ticket, _repo, _pack=None: str(repo))
    monkeypatch.setattr(outbox, "create", lambda *args, **more: made.append(args) or {"id": "BATCH-1/010-push-branch"})
    return {"repo": repo, "intent": intent, "made": made, "patch": patch, "head": _git(repo, "rev-parse", "HEAD")}


def _untouched(note, branch):
    return (
        _git(note["repo"], "rev-parse", "HEAD"),
        _git(note["repo"], "rev-parse", "--abbrev-ref", "HEAD"),
        _git(note["repo"], "status", "--porcelain"),
        note["made"],
        note["intent"]["status"],
    ) == (note["head"], branch, "", [], "pending")


def test_a_note_whose_patch_file_is_gone_or_whose_branch_is_unknown_is_not_applied(note):
    note["intent"]["payload"]["branch"] = "bump/gone"
    with pytest.raises(CockpitError, match="bump/gone cannot be checked out in .*api: "):
        infra_note.apply({}, "BATCH-1/009-infra-note")
    assert _untouched(note, "bump/x")
    os.remove(note["patch"])
    with pytest.raises(CockpitError, match="^no patch file records/qa/BATCH-1/node.patch$"):
        infra_note.apply({}, "BATCH-1/009-infra-note")
    assert _untouched(note, "bump/x")


def test_a_commit_the_repo_refuses_leaves_the_checkout_clean_and_files_no_push(note):
    hooks = note["repo"] / ".git" / "hooks"
    hooks.mkdir(exist_ok=True)
    hook = hooks / "pre-commit"
    hook.write_text("#!/bin/sh\necho 'the hook says no' >&2\nexit 1\n", encoding="utf-8")
    hook.chmod(0o755)
    with pytest.raises(CockpitError, match="the commit was refused: the hook says no"):
        infra_note.apply({}, "BATCH-1/009-infra-note")
    assert _untouched(note, "bump/x") and (note["repo"] / "run.yml").read_text(encoding="utf-8") == "node: 18\n"


def test_a_failed_apply_returns_the_checkout_to_the_branch_it_was_on(note):
    _git(note["repo"], "switch", "-q", "-c", "side")
    note["patch"].write_text("--- a/run.yml\n+++ b/run.yml\n@@ -1 +1 @@\n-node: 16\n+node: 22\n", encoding="utf-8")
    with pytest.raises(CockpitError, match="the patch does not apply on bump/x"):
        infra_note.apply({}, "BATCH-1/009-infra-note")
    assert _untouched(note, "side")


# ---------- pace ----------


class _FakePlan:
    """A plan source for the provider `fake-plan`; `answer` is what it reads, or the error it raises."""

    answer = {"windows": [], "read_at": 0, "stale": False, "error": ""}

    @classmethod
    def handles(cls, provider):
        return provider == "fake-plan"

    def windows(self, pack, provider, now, fresh=False):
        if isinstance(self.answer, Exception):
            raise self.answer
        return self.answer


@pytest.fixture
def fake_plan(monkeypatch):
    from cockpitlib import pace, settings

    class Source(_FakePlan):
        pass

    monkeypatch.setattr(pace, "SOURCES", [Source])
    monkeypatch.setattr(pace, "_provider", lambda _pack: "fake-plan")
    monkeypatch.setattr(pace, "efficiency", lambda _pack, _now: {"tokens": 7})
    monkeypatch.setattr(settings, "load", lambda _pack: {"budget": {"plan_window_max_pct": 90}})
    return Source


def test_the_usage_page_gets_one_sentence_per_window_for_each_verdict(fake_plan):
    from cockpitlib import pace

    now = 1767225600.0
    half = pace.WEEK / 2
    fake_plan.answer = {
        "windows": [
            pace.PlanWindow(name, used, now + half, pace.WEEK)
            for name, used in (("Hot", 80), ("Even", 45), ("Cool", 10))
        ],
        "read_at": now - 60,
        "stale": False,
        "error": "",
    }
    out = pace.pace({"name": "acme"}, now=now, detail=True)
    assert (
        out["error"] == ""
        and out["binding"] == "Hot"
        and out["verdict"] == "ahead"
        and out["efficiency"] == {"tokens": 7}
    )
    assert [row["sentence"] for row in out["windows"]] == [
        "Hot: 80% used, ahead of the 45% ideal by now; at this pace 160% by the reset against a 90% target.",
        "Even: 45% used, on pace with the 45% ideal by now.",
        "Cool: 10% used, behind the 45% ideal by now; 1.0% per active hour is left to spend before the reset.",
    ]
    assert (
        out["inputs"]["schedule"] == "all hours"
        and out["inputs"]["peak_hours"] == "not counted"
        and out["inputs"]["target_pct"] == 90
    )


def test_pace_answers_with_the_error_when_the_plan_read_fails_or_reads_nothing(fake_plan, monkeypatch):
    from cockpitlib import pace

    now = 1767225600.0
    fake_plan.answer = RuntimeError("the reader fell over")
    monkeypatch.setattr(pace, "efficiency", lambda _pack, _now: (_ for _ in ()).throw(RuntimeError("no seat rows")))
    failed = pace.pace({"name": "acme"}, now=now)
    assert (
        failed["error"] == "plan usage read failed: the reader fell over"
        and failed["windows"] == []
        and failed["provider"] == "fake-plan"
    )
    assert failed["efficiency"] == {"error": "no seat rows"}  # a side figure, never the reason pace fails
    fake_plan.answer = {"windows": [], "read_at": now, "stale": False, "error": ""}
    nothing = pace.pace({"name": "acme"}, now=now)
    assert (
        nothing["error"] == "no plan window read for fake-plan"
        and nothing["verdict"] == "on"
        and nothing["binding"] == ""
    )


def test_a_pack_whose_quota_limit_cannot_be_read_gets_the_blank_answer_with_why(monkeypatch):
    from cockpitlib import pace, settings

    def broken(_pack):
        raise CockpitError("budget is not a mapping")

    monkeypatch.setattr(settings, "load", broken)
    blank = pace.blank({"name": "acme"}, "why", now=1767225600.0)
    assert blank["target_pct"] == 0 and blank["error"] == "why" and blank["read_at"] == "2026-01-01T00:00:00+00:00"
    out = pace.pace({"name": "acme"}, now=1767225600.0)
    assert (
        out["error"] == "quota limit unreadable: budget is not a mapping"
        and out["provider"] == ""
        and out["windows"] == []
    )


def test_days_that_are_not_numbers_are_refused_by_name():
    from cockpitlib import pace

    with pytest.raises(ValueError, match="^--days takes weekday numbers 0-6"):
        pace.parse_schedule(days="mon,tue")
    assert pace.parse_schedule(days="0, 2,").days == frozenset({0, 2})


def test_the_max_plan_source_skips_a_window_without_a_reset_and_dates_a_stale_read(tmp_path, monkeypatch):
    from cockpitlib import pace, paths, usage

    now = 1767225600.0
    read = {
        "error": "the reader is down",
        "windows": [
            {
                "provider": "claude-code",
                "name": "Current week",
                "used": 40,
                "resets_at": "2026-01-03T00:00:00Z",
                "stale": True,
                "read_at": now - 600,
            },
            {"provider": "claude-code", "name": "Fable week", "used": 9, "resets_at": "soon"},
            {"provider": "claude-code", "name": "Opus week", "used": 9, "resets_at": None},
            {"provider": "other", "name": "Current week", "used": 99, "resets_at": "2026-01-03T00:00:00Z"},
        ],
    }
    monkeypatch.setattr(usage, "plan_windows", lambda _pack, _now, fresh=False: read)
    monkeypatch.setattr(paths, "watch_dir", lambda: str(tmp_path))
    source = pace.MaxPlanSource()
    out = source.windows({}, "claude-code", now)
    assert out["windows"] == [pace.PlanWindow("Current week", 40.0, now + 2 * 86400, pace.WEEK, "account")]
    assert out["stale"] is True and out["read_at"] == now - 600 and out["error"] == "the reader is down"
    # No window of this provider at all: the read is dated by the kept file, else by now.
    assert source.windows({}, "claude-max", now) == {
        "windows": [],
        "read_at": now,
        "stale": False,
        "error": "the reader is down",
    }
    (tmp_path / "plan-windows.json").write_text(json.dumps({"at": now - 900}), encoding="utf-8")
    assert source.windows({}, "claude-max", now)["read_at"] == now - 900
    (tmp_path / "plan-windows.json").write_text("[1, 2]", encoding="utf-8")
    assert source.windows({}, "claude-max", now)["read_at"] == now


def test_card_runs_are_counted_from_the_board_and_a_board_that_cannot_be_read_counts_none(tmp_path, monkeypatch):
    from cockpitlib import kanban, pace

    board = tmp_path / "kanban.db"
    monkeypatch.setattr(kanban, "db_path", lambda _slug: str(board))
    connection = _board(board, ["create table tasks (id text)"])
    assert pace._card_runs({"board": "acme"}, 100) == {"runs": 0, "wasted": 0}  # an older board without runs
    connection.execute("create table task_runs (outcome text, ended_at integer)")
    connection.executemany(
        "insert into task_runs values (?, ?)",
        [("completed", 150), ("crashed", 160), ("rate_limited", 170), (None, 180), ("failed", 50), ("crashed", None)],
    )
    connection.commit()
    connection.close()
    assert pace._card_runs({"board": "acme"}, 100) == {"runs": 4, "wasted": 2}
    board.write_bytes(b"this is not a database, whatever its name says" * 40)
    assert pace._card_runs({"board": "acme"}, 100) == {"runs": 0, "wasted": 0}

    def no_board(_slug):
        raise CockpitError("no board")

    monkeypatch.setattr(kanban, "db_path", no_board)
    assert pace._card_runs(None, 100) == {"runs": 0, "wasted": 0}


# ---------- tracker ----------


class _Connector:
    """Records each connector operation and answers from `answers` (a value, or a function of the arguments)."""

    def __init__(self, **answers):
        self.calls = []
        self.answers = answers

    def __call__(self, connector, tool, arguments):
        self.calls.append((tool, arguments))
        answer = self.answers.get(tool)
        return answer(arguments) if callable(answer) else answer


def _connected(fake, dry_run=False):
    from cockpitlib.tracker import ConnectorTracker

    return ConnectorTracker({"url": "https://acme.atlassian.net", "project": "TASK"}, dry_run, call=fake)


def test_a_rest_answer_that_is_not_json_reads_as_empty(monkeypatch):
    import urllib.request

    from cockpitlib.tracker import JiraTracker

    monkeypatch.setenv("T_EMAIL", "human@example.test")
    monkeypatch.setenv("T_TOKEN", "token-1")
    asked = []

    class Answer:
        def __enter__(self):
            return self

        def __exit__(self, *_exc):
            return False

        def read(self):
            return b"<html>signed out</html>"

    monkeypatch.setattr(urllib.request, "urlopen", lambda request, timeout=0: asked.append(request) or Answer())
    tracker = JiraTracker({"url": "https://tracker.example.test", "auth_env": ["T_EMAIL", "T_TOKEN"]})
    assert tracker._request("GET", "/rest/api/3/myself") == {} and tracker.summary("TASK-1") == ""
    assert [request.full_url for request in asked] == [
        "https://tracker.example.test/rest/api/3/myself",
        "https://tracker.example.test/rest/api/3/issue/TASK-1?fields=summary",
    ]
    assert asked[0].get_header("Authorization").startswith("Basic ") and tracker.writes == []


def test_the_connector_tracker_holds_no_credential():
    with pytest.raises(CockpitError, match="^the connector tracker holds no credential$"):
        _connected(_Connector())._auth()


def test_each_rest_call_is_made_as_the_connector_operation_that_does_the_same():
    fake = _Connector(
        SEARCH_FOR_ISSUES_USING_JQL_GET={"issues": [{"key": "TASK-1"}]},
        EDIT_ISSUE=None,
        LIST_ISSUE_COMMENTS={"comments": []},
        UPDATE_COMMENT={"id": "7"},
    )
    tracker = _connected(fake)
    assert tracker._request(
        "GET", "/rest/api/3/search/jql?jql=project%20%3D%20TASK&maxResults=5&fields=summary,status"
    ) == {"issues": [{"key": "TASK-1"}]}
    assert tracker._request("GET", "/rest/api/3/search/jql?jql=project%20%3D%20TASK") == {"issues": [{"key": "TASK-1"}]}
    assert tracker._request("PUT", "/rest/api/3/issue/TASK-1", {"fields": {"labels": ["qa"]}}) == {}
    assert tracker._request("GET", "/rest/api/3/issue/TASK-1/comment?maxResults=20") == {"comments": []}
    assert tracker._request("PUT", "/rest/api/3/issue/TASK-1/comment/7", {"body": "Reworded"}) == {"id": "7"}
    assert fake.calls == [
        (
            "SEARCH_FOR_ISSUES_USING_JQL_GET",
            {"jql": "project = TASK", "max_results": 5, "fields": ["summary", "status"]},
        ),
        ("SEARCH_FOR_ISSUES_USING_JQL_GET", {"jql": "project = TASK", "max_results": 50}),
        ("EDIT_ISSUE", {"issue_id_or_key": "TASK-1", "fields": {"labels": ["qa"]}}),
        ("LIST_ISSUE_COMMENTS", {"issue_id_or_key": "TASK-1", "max_results": 20}),
        ("UPDATE_COMMENT", {"issue_id_or_key": "TASK-1", "comment_id": "7", "comment_text": "Reworded"}),
    ]
    assert [write["method"] for write in tracker.writes] == ["PUT", "PUT"]
    with pytest.raises(CockpitError, match="no operation for DELETE /rest/api/3/issue/TASK-1/comment/7"):
        tracker._request("DELETE", "/rest/api/3/issue/TASK-1/comment/7")


def test_a_created_issue_carries_its_description():
    fake = _Connector(CREATE_ISSUE={"key": "TASK-9"})
    document = {"type": "doc", "version": 1, "content": []}
    made = _connected(fake)._request(
        "POST",
        "/rest/api/3/issue",
        {
            "fields": {
                "project": {"key": "TASK"},
                "summary": "Totals",
                "issuetype": {"name": "Bug"},
                "description": document,
            }
        },
    )
    assert made == {"key": "TASK-9"}
    assert fake.calls == [
        ("CREATE_ISSUE", {"project_key": "TASK", "summary": "Totals", "issue_type": "Bug", "description": document})
    ]


def test_an_attachment_goes_up_by_its_path_in_the_workspace_and_a_dry_run_only_records_it(tmp_path, monkeypatch):
    monkeypatch.setenv("COCKPIT_WORKSPACE", str(tmp_path))
    full = os.path.join(os.path.realpath(str(tmp_path)), "records/qa/TASK-1/shot.png")
    fake = _Connector(ADD_ATTACHMENT=[{"id": 501}])
    tracker = _connected(fake)
    assert tracker._upload("TASK-1", "records/qa/TASK-1/shot.png") == "501"
    assert fake.calls == [("ADD_ATTACHMENT", {"issue_key": "TASK-1", "file_to_upload": full})]
    assert tracker.writes == [
        {"method": "POST", "path": "connector ADD_ATTACHMENT TASK-1", "body": {"file": "shot.png"}}
    ]
    assert _connected(_Connector(ADD_ATTACHMENT={"id": "502"}))._upload("TASK-1", "a.png") == "502"
    assert _connected(_Connector(ADD_ATTACHMENT="done"))._upload("TASK-1", "a.png") == ""
    silent = _Connector()
    rehearsal = _connected(silent, dry_run=True)
    assert rehearsal._upload("TASK-1", "a.png") == "" and silent.calls == [] and len(rehearsal.writes) == 1


def test_the_create_fields_of_an_issue_type_are_read_by_name_whatever_its_case():
    fake = _Connector(
        GET_ISSUE_CREATE_METADATA={
            "projects": [
                {
                    "issuetypes": [
                        {"name": "Task", "fields": {"summary": {"name": "Summary"}}},
                        {
                            "name": "Bug",
                            "fields": {
                                "customfield_10020": {"name": "Sprint"},
                                "components": {"allowedValues": [{"name": "Billing"}]},
                            },
                        },
                    ]
                }
            ]
        }
    )
    tracker = _connected(fake)
    assert tracker._meta("TASK", "bug") == {
        "customfield_10020": {"name": "Sprint", "fieldId": "customfield_10020"},
        "components": {"allowedValues": [{"name": "Billing"}], "fieldId": "components"},
    }
    assert fake.calls[0][1] == {
        "projectKeys": ["TASK"],
        "issuetypeNames": ["bug"],
        "expand": "projects.issuetypes.fields",
    }
    with pytest.raises(CockpitError, match="^TASK has no issue type Epic$"):
        tracker._meta("TASK", "Epic")


def test_the_active_sprint_is_read_off_an_issue_that_is_in_an_open_one():
    sprints = {
        "TASK-1": [{"id": 3, "state": "closed"}],
        "TASK-2": [{"id": 3, "state": "closed"}, {"id": 4, "state": "active"}],
        "TASK-3": None,
    }
    fake = _Connector(
        SEARCH_FOR_ISSUES_USING_JQL_GET={"issues": [{"key": "TASK-1"}, {"key": "TASK-3"}, {"key": "TASK-2"}]},
        GET_ISSUE=lambda arguments: {"fields": {"customfield_10020": sprints[arguments["issue_id_or_key"]]}},
    )
    assert _connected(fake)._active_sprint("TASK", "customfield_10020") == 4
    assert fake.calls[0] == (
        "SEARCH_FOR_ISSUES_USING_JQL_GET",
        {"jql": "project = TASK AND sprint in openSprints()", "max_results": 5},
    )
    assert fake.calls[-1] == ("GET_ISSUE", {"issue_id_or_key": "TASK-2", "fields": ["customfield_10020"]})
    with pytest.raises(CockpitError, match="^no active sprint in TASK$"):
        _connected(
            _Connector(SEARCH_FOR_ISSUES_USING_JQL_GET={"issues": [{"key": "TASK-1"}]}, GET_ISSUE={"fields": {}})
        )._active_sprint("TASK", "f")


# ---------- owners ----------


@pytest.fixture
def owner_files(tmp_path, monkeypatch):
    from cockpitlib import owners

    folder = tmp_path / "owners"
    monkeypatch.setattr(owners, "_folder", lambda: str(folder))
    return folder


def test_a_plugin_without_a_usable_name_owns_nothing(owner_files):
    from cockpitlib import owners

    for name in ("", None, "../.."):
        with pytest.raises(ValueError, match="a plugin name"):
            owners.own(name, ["REL-1"])
        with pytest.raises(ValueError, match="a plugin name"):
            owners.own_prs(name, [{"ticket": "REL-1", "repo": "api", "number": 4}])
    assert not owner_files.exists()


def test_only_readable_fresh_lists_say_who_owns_a_ticket_or_a_pr(owner_files):
    from cockpitlib import owners

    now = time.time()
    assert owners.own("release", ["REL-1", " REL-2 ", ""]) == 2
    assert (
        owners.own_prs(
            "release", [{"ticket": "REL-1", "repo": "api", "number": "4", "ready": 1}, {"ticket": "REL-2"}, "junk"]
        )
        == 1
    )
    assert (
        owners.own("lapsed", ["OLD-1"]) == 1
        and owners.own_prs("lapsed", [{"ticket": "OLD-1", "repo": "api", "number": 9}]) == 1
    )
    for folder in (owner_files, owner_files / "prs"):
        (folder / "notes.txt").write_text("not a list\n", encoding="utf-8")
        (folder / "torn.json").write_text('{"tickets": ["TORN-1"], "prs": [{"ticket"', encoding="utf-8")
        kept = json.loads((folder / "lapsed.json").read_text(encoding="utf-8"))
        (folder / "lapsed.json").write_text(
            json.dumps({**kept, "at": now - owners.LAPSE_SECONDS - 5}), encoding="utf-8"
        )
    assert owners.owned(now) == {"REL-1": "release", "REL-2": "release"}
    assert (
        owners.owner_of("REL-2", now) == "release"
        and owners.owner_of("OLD-1", now) == ""
        and owners.owner_of("TORN-1", now) == ""
    )
    assert owners.registered_prs(now) == [
        {"ticket": "REL-1", "repo": "api", "number": 4, "url": "", "ready": True, "plugin": "release"}
    ]


# ---------- asks ----------


@pytest.fixture
def asking_card(tmp_path, monkeypatch):
    from cockpitlib import acts, asks, kanban, skill_log

    board = tmp_path / "kanban.db"
    _board(board, []).close()
    answered = []
    monkeypatch.setattr(
        skill_log,
        "card_of",
        lambda _board_name, _card: {"id": "t_1", "status": "blocked", "assignee": "worker-1", "title": "ACME-1 worker"},
    )
    monkeypatch.setattr(kanban, "db_path", lambda _slug: str(board))
    monkeypatch.setattr(kanban, "block_reason", lambda _connection, _card: "DEPLOY? the staging stack")
    monkeypatch.setattr(acts, "answer_card", lambda *args: answered.append(args) or {"out": "resumed"})
    monkeypatch.setattr(asks, "_RUNNING", set())
    pack = {
        "board": "acme",
        "_dir": str(tmp_path),
        "asks": {"deploy": {"mark": "DEPLOY?", "command": [str(tmp_path / "no-such-command"), "{card}"]}},
    }
    return {"pack": pack, "answered": answered}


def test_an_approval_command_that_cannot_start_is_said_and_the_card_can_be_approved_again(asking_card):
    from cockpitlib import asks

    with pytest.raises(CockpitError, match="^deploy: the approval command could not start: "):
        asks.approve(asking_card["pack"], "t_1")
    assert asks._RUNNING == set() and asking_card["answered"] == []


def test_a_second_approve_while_the_first_still_runs_is_refused(asking_card):
    from cockpitlib import asks

    asks._RUNNING.add("t_1")
    with pytest.raises(CockpitError, match="^deploy: the approval for t_1 is already running$"):
        asks.approve(asking_card["pack"], "t_1")
    assert asks._RUNNING == {"t_1"} and asking_card["answered"] == []  # the running one keeps its claim


# ---------- state_commit ----------


@pytest.fixture
def records_repo(tmp_path, monkeypatch):
    from cockpitlib import state_commit

    root = tmp_path / "ws"
    root.mkdir()
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "me@example.test")
    _git(root, "config", "user.name", "Me")
    (root / "README").write_text("hello\n", encoding="utf-8")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "init")
    monkeypatch.setattr(state_commit, "workspace", lambda: str(root))
    monkeypatch.setattr(state_commit, "records_name", lambda: "records")
    return root


def test_a_git_call_that_fails_raises_with_gits_own_words(records_repo):
    from cockpitlib import state_commit

    with pytest.raises(CockpitError, match="unknown revision|ambiguous argument"):
        state_commit._git(str(records_repo), ["rev-parse", "no-such-ref"])
    assert state_commit._git(str(records_repo), ["rev-parse", "no-such-ref"], check=False).returncode != 0


def test_a_record_kind_nobody_commits_has_no_concern(records_repo):
    from cockpitlib import state_commit

    assert (
        state_commit._concern("records/notes/ACME-1/draft.md") == ""
        and state_commit._concern("records/qa/ACME-1/plan.md") == "ticket:ACME-1"
    )


def test_only_watch_and_chat_records_changing_is_nothing_new(records_repo):
    from cockpitlib import state_commit

    for name in ("records/watch/pr-watch.json", "records/chat/today.md", "records/qa/README.md"):
        path = records_repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("x\n", encoding="utf-8")
    head = _git(records_repo, "rev-parse", "HEAD")
    assert state_commit.state_commit({"board": "acme", "workspace_branch": "main"}) == "workspace-watch: nothing new"
    assert _git(records_repo, "rev-parse", "HEAD") == head


def test_a_detached_workspace_is_held_and_nothing_is_committed(records_repo):
    from cockpitlib import state_commit

    path = records_repo / "records" / "platform" / "base.json"
    path.parent.mkdir(parents=True)
    path.write_text("{}\n", encoding="utf-8")
    head = _git(records_repo, "rev-parse", "HEAD")
    _git(records_repo, "checkout", "-q", "--detach")
    assert state_commit._branch(str(records_repo)) == "detached"
    assert (
        state_commit.state_commit({"board": "acme", "workspace_branch": "main"}, now=time.time() + 3600)
        == "HOLD workspace is on detached; workspace-watch commits only on main"
    )
    assert _git(records_repo, "rev-parse", "HEAD") == head and "records/" in _git(records_repo, "status", "--porcelain")
