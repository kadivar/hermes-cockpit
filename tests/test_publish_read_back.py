# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""A publish to the forge or the tracker sends what the intent recorded, and every write is read back."""

import json
import os
import re

import pytest

from cockpitlib.cli import main
from cockpitlib.errors import CockpitError
from cockpitlib.pack import load
from tests.support import words
from tests.support.both_packs import PACKS, _LyingForge, _other, _thread_nodes


@pytest.mark.parametrize("pack_file", PACKS)
def test_an_intent_takes_typed_flags_and_keeps_its_own_copy_of_each_draft(env, pack_file, monkeypatch, capsys):
    from cockpitlib.intents import load as load_intent
    from cockpitlib.paths import workspace
    from tests.support import fake_gh

    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    monkeypatch.setenv("COCKPIT_LANE", "worker-1")
    pack = load(pack_file)
    other = _other(pack)
    repo = pack["repos"]["repos"][0]["name"]
    ticket = f"{pack['tracker']['project']}-1101"
    branch = f"work/{ticket}"
    sha = fake_gh.commit(repo, branch, name=f"{pack['name']}.txt")
    draft = env["workspace"] / "pr.md"
    draft.write_text(f"Body {pack['name']}\n", encoding="utf-8")
    base = ["outbox", "new", ticket]
    assert main([*base, "push-branch", "--card", "t_1", "--summary", "push", "--repo", repo, "--branch", branch]) == 0
    pushed = capsys.readouterr().out.splitlines()[0]
    assert (
        main(
            [
                *base,
                "open-pr",
                "--card",
                "t_1",
                "--summary",
                "open",
                "--repo",
                repo,
                "--branch",
                branch,
                "--title",
                f"{ticket}: {pack['name']}",
                "--body-file",
                str(draft),
                "--labels",
                "first, second",
                "--ready",
            ]
        )
        == 0
    )
    printed = capsys.readouterr().out.splitlines()
    opened = load_intent(printed[0])
    assert printed[1].endswith(f"{printed[0].split('/')[1]}.json")
    payload = opened["payload"]
    assert (payload["labels"], payload["ready"], payload["after"], payload["head"]) == (
        ["first", "second"],
        True,
        pushed,
        branch,
    )
    assert opened["created_by"] == "worker-1" and payload["remote_sha"] == sha
    assert payload["body_file"].startswith(f"{pack['records_dir']}/outbox/{ticket}/")
    draft.write_text("changed later\n", encoding="utf-8")
    assert open(os.path.join(workspace(), payload["body_file"]), encoding="utf-8").read() == f"Body {pack['name']}\n"
    assert main(["outbox", "show", opened["id"]]) == 0 and f"Body {pack['name']}" in capsys.readouterr().out
    assert main([*base, "open-pr", "--card", "t_1", "--summary", "open", "--repo", repo, "--branch", branch]) == 2
    assert "open-pr needs --title (e.g. cockpit outbox new <ticket> open-pr" in capsys.readouterr().err
    assert main([*base, "pr-edit", "--card", "t_1", "--summary", "x", "--repo", repo, "--number", "seven"]) == 2
    assert "--number is a number" in capsys.readouterr().err
    assert main([*base, "pr-edit", "--card", "t_1", "--summary", "x", "--repo", repo, "--number", "7"]) == 2
    assert "pr-edit needs one of --base" in capsys.readouterr().err
    assert main([*base, "push-branch", "--card", "t_1", "--summary", "x", "--repo", repo, "--colour", "red"]) == 2
    assert "unknown option --colour" in capsys.readouterr().err
    assert (
        main([*base, "push-branch", "--summary", "x"]) == 2
        and "new needs --card and --summary" in capsys.readouterr().err
    )
    assert (
        main(
            [
                *base,
                "pr-comment",
                "--card",
                "t_1",
                "--summary",
                "x",
                "--repo",
                repo,
                "--number",
                "3",
                "--body-file",
                "absent.md",
            ]
        )
        == 1
    )
    assert "--body-file absent.md: no such file" in capsys.readouterr().err
    assert (
        main([*base, "tracker-comment", "--card", "t_1", "--summary", "x", "--body", "ok", "--attach", "/etc/hosts"])
        == 1
    )
    assert "an attachment lives under the workspace" in capsys.readouterr().err
    evidence = env["workspace"] / pack["records_dir"] / "qa" / ticket / "row-1.png"
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_bytes(b"png")
    assert (
        main([*base, "tracker-comment", "--card", "t_1", "--summary", "x", "--body", "ok", "--attach", str(evidence)])
        == 0
    )
    attached = load_intent(capsys.readouterr().out.splitlines()[0])["payload"]
    assert attached["attach"] == [f"{pack['records_dir']}/qa/{ticket}/row-1.png"] and attached["issue"] == ticket
    assert (
        main(
            [
                "outbox",
                "amend",
                opened["id"],
                "--summary",
                "retitled",
                "--title",
                f"{ticket}: again",
                "--labels",
                "third",
            ]
        )
        == 0
    )
    amended = load_intent(opened["id"])
    assert (amended["payload"]["title"], amended["payload"]["labels"], amended["agent_summary"]) == (
        f"{ticket}: again",
        ["third"],
        "retitled",
    )
    assert (
        main(["outbox", "amend", opened["id"], "extra"]) == 2
        and main(["outbox", "show", opened["id"], "--repo", repo]) == 2
    )
    assert other["name"] not in json.dumps(amended)


@pytest.mark.parametrize("pack_file", PACKS)
def test_a_push_intent_records_what_it_sends_and_waits_when_someone_else_wrote_part_of_it(env, pack_file, monkeypatch):
    from cockpitlib.outbox import amend, create, endorse, verify
    from tests.support import fake_gh

    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    pack = load(pack_file)
    repo = pack["repos"]["repos"][0]
    name = repo["name"]
    ticket = f"{pack['tracker']['project']}-1102"
    branch = f"work/{ticket}{repo['branch_suffix_when_held']}"
    published = f"work/{ticket}"
    first = fake_gh.commit(name, branch, name="one.txt", text="one\n")
    sha = fake_gh.commit(name, branch, name="two.txt", text="two\n")
    made = create(pack, ticket, "push-branch", "c", "push", {"repo": name, "branch": branch})
    payload = made["payload"]
    assert (
        payload["publish_as"] == published
        and payload["sha"] == sha
        and payload["remote_sha"] == ""
        and made["status"] == "pending"
    )
    assert [line.split(" ", 1)[1] for line in payload["commits"]] == ["change one.txt", "change two.txt"]
    assert payload["files"] == ["one.txt", "two.txt"] and "2 files changed" in payload["diffstat"]
    assert payload["base"] == "origin/main" and payload["foreign"] == [] and first != sha
    with pytest.raises(CockpitError, match="already an open push"):
        create(pack, ticket, "push-branch", "c", "again", {"repo": name, "branch": branch})
    other_ticket = f"{pack['tracker']['project']}-1103"
    shared = f"work/{other_ticket}"
    fake_gh.commit(name, shared, name="mine.txt")
    fake_gh.commit(name, shared, name="theirs.txt", email=f"someone@{pack['name']}.test")
    held = create(pack, other_ticket, "push-branch", "c", "push", {"repo": name, "branch": shared})
    assert held["status"] == "held" and held["hold"]["waits"] == "human"
    assert f"commits by someone@{pack['name']}.test" in held["hold"]["reason"]
    unreadable = create(
        pack,
        f"{pack['tracker']['project']}-1104",
        "push-branch",
        "c",
        "push",
        {"repo": name, "branch": "work/x", "sha": "f" * 40},
    )
    assert "is not a commit" in unreadable["payload"]["probe_error"]
    assert any("git could not be read" in item for item in verify(unreadable["id"], pack=pack))
    with pytest.raises(CockpitError, match="does not verify: git could not be read"):
        endorse(unreadable["id"], "low", "", "gatekeeper", "fixture-a", "fixture-large", pack=pack)
    with pytest.raises(CockpitError, match="rebase-only push is the first of the pair"):
        create(
            pack,
            ticket,
            "push-branch",
            "c",
            "x",
            {"repo": name, "branch": "work/y", "rebase_only": True, "after": made["id"]},
        )
    # The repo's verify command runs on the pushed range: a failure keeps the gatekeeper from endorsing.
    bad = "TABS-HERE\n" if pack["name"] == "acme" else "spaced line \n"
    fake_gh.commit(name, branch, name="three.txt", text=bad)
    amended = amend(made["id"], summary="one more", pack=pack)
    assert amended["payload"]["sha"] != sha and amended["status"] == "pending"
    problems = verify(made["id"], pack=pack)
    assert any(item.startswith("verify ") and "failed on the pushed range" in item for item in problems), problems
    with pytest.raises(CockpitError, match="failed on the pushed range"):
        endorse(made["id"], "low", "", "gatekeeper", "fixture-a", "fixture-large", pack=pack)
    fake_gh.commit(name, branch, name="three.txt", text="clean\n")
    amend(made["id"], pack=pack)
    assert verify(made["id"], pack=pack) == []
    assert endorse(made["id"], "low", "", "gatekeeper", "fixture-a", "fixture-large", pack=pack)["status"] == "endorsed"
    with pytest.raises(CockpitError, match="only a pending or held intent is endorsed"):
        endorse(made["id"], "low", "", "gatekeeper", "fixture-a", "fixture-large", pack=pack)
    # The remote moved after the intent was written: verify names it, and amending takes the new lease.
    clone = env["root"] / "elsewhere"
    import subprocess

    subprocess.run(["git", "clone", "-q", str(env["root"] / "remotes" / f"{name}.git"), str(clone)], check=True)
    subprocess.run(["git", "-C", str(clone), "push", "-q", "origin", f"HEAD:refs/heads/{published}"], check=True)
    assert any("the remote moved since the intent was written" in item for item in verify(made["id"], pack=pack))
    assert amend(made["id"], pack=pack)["payload"]["remote_sha"] == fake_gh.remote(name, published)
    assert _other(pack)["name"] not in json.dumps(load_intent_of(made["id"]))


def load_intent_of(iid):
    from cockpitlib.intents import load as load_intent

    return load_intent(iid)


@pytest.mark.parametrize("pack_file", PACKS)
def test_a_push_leaves_from_the_main_checkout_against_its_lease(env, pack_file, monkeypatch):
    import subprocess

    from cockpitlib.outbox import create, endorse
    from cockpitlib.publish import execute
    from tests.support import fake_gh

    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    monkeypatch.delenv("COCKPIT_LANE", raising=False)
    pack = load(pack_file)
    name = pack["repos"]["repos"][0]["name"]
    source = env["root"] / "repos" / name
    git = lambda *args: subprocess.run(
        ["git", "-C", str(source), *args], check=True, capture_output=True, text=True
    ).stdout.strip()  # noqa: E731
    ticket = f"{pack['tracker']['project']}-1105"
    branch = f"work/{ticket}"

    def publish(payload, summary="push"):
        made = create(pack, ticket, "push-branch", "c", summary, payload)
        made = endorse(made["id"], "low", "", "gatekeeper", "fixture-a", "fixture-large")
        return made, execute(made, pack=pack)

    first_sha = fake_gh.commit(name, branch, name=f"{pack['name']}.txt")
    row, receipt = publish({"repo": name, "branch": branch})
    assert receipt["ok"] and "fast-forward" in receipt["output"] and fake_gh.remote(name, branch) == first_sha
    again, receipt = publish({"repo": name, "branch": branch}, "same again")
    assert receipt["ok"] and receipt["output"] == "already on the remote (nothing pushed)"
    # The base moves on the remote; the branch is rebased onto it. A rebase-only push proves the patches are the same.
    clone = env["root"] / f"clone-{pack['name']}"
    subprocess.run(["git", "clone", "-q", str(env["root"] / "remotes" / f"{name}.git"), str(clone)], check=True)
    (clone / "base.txt").write_text("base moved\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(clone), "add", "base.txt"], check=True)
    subprocess.run(
        ["git", "-C", str(clone), "-c", "user.email=b@x.test", "-c", "user.name=B", "commit", "-qm", "base"], check=True
    )
    subprocess.run(["git", "-C", str(clone), "push", "-q", "origin", "main"], check=True)
    git("fetch", "-q", "origin")
    git("checkout", "-q", branch)
    git("-c", "user.email=dev@example.test", "-c", "user.name=Dev", "rebase", "-q", "origin/main")
    rebased = git("rev-parse", "HEAD")
    git("checkout", "-q", "main")
    row, receipt = publish({"repo": name, "branch": branch, "rebase_only": True}, "rebase")
    assert "patches identical" in row["payload"]["rebase_proof"] and row["payload"]["remote_sha"] == first_sha
    assert (
        receipt["ok"]
        and f"force-with-lease on {first_sha[:10]}" in receipt["output"]
        and fake_gh.remote(name, branch) == rebased
    )
    # A rebase that also changes content is refused, and so is a branch with an unsquashed fixup.
    git("checkout", "-q", branch)
    git(
        "-c",
        "user.email=dev@example.test",
        "-c",
        "user.name=Dev",
        "rebase",
        "-q",
        "--onto",
        "origin/main~1",
        "origin/main",
    )
    (source / f"{pack['name']}.txt").write_text("other content\n", encoding="utf-8")
    git(
        "-c",
        "user.email=dev@example.test",
        "-c",
        "user.name=Dev",
        "commit",
        "-qam",
        f"fixup! change {pack['name']}.txt",
    )
    git("checkout", "-q", "main")
    with pytest.raises(CockpitError, match="rebase-only: "):
        create(pack, ticket, "push-branch", "c", "rebase", {"repo": name, "branch": branch, "rebase_only": True})
    row, receipt = publish({"repo": name, "branch": branch}, "with a fixup")
    assert not receipt["ok"] and "unsquashed fixups" in receipt["error"] and fake_gh.remote(name, branch) == rebased
    # The remote branch moves after the intent is written: the lease refuses the push.
    other = f"{branch}-two"
    two = fake_gh.commit(name, other, name="two.txt")
    made = endorse(
        create(pack, ticket, "push-branch", "c", "two", {"repo": name, "branch": other})["id"],
        "low",
        "",
        "gatekeeper",
        "fixture-a",
        "fixture-large",
    )
    subprocess.run(["git", "-C", str(clone), "fetch", "-q", "origin"], check=True)
    subprocess.run(["git", "-C", str(clone), "push", "-q", "origin", "origin/main:refs/heads/" + other], check=True)
    receipt = execute(made, pack=pack)
    assert (
        not receipt["ok"]
        and "moved since the intent was written" in receipt["error"]
        and fake_gh.remote(name, other) != two
    )
    git("branch", "-f", branch, "main")
    stale = endorse(
        create(pack, ticket, "push-branch", "c", "stale", {"repo": name, "branch": f"{branch}-three"})["id"],
        "low",
        "",
        "gatekeeper",
        "fixture-a",
        "fixture-large",
    )
    assert not execute(stale, pack=pack)["ok"]


@pytest.mark.parametrize("pack_file", PACKS)
def test_a_pull_request_is_opened_once_its_siblings_are_linked_and_each_edit_is_read_back(env, pack_file, monkeypatch):
    from cockpitlib.intents import load as load_intent
    from cockpitlib.outbox import create, endorse
    from cockpitlib.publish import execute, forge_for, publish_all
    from tests.support import fake_gh

    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    monkeypatch.delenv("COCKPIT_LANE", raising=False)
    pack = load(pack_file)
    org = pack["forge"]["org"]
    first, second = (repo["name"] for repo in pack["repos"]["repos"][:2])
    ticket = f"{pack['tracker']['project']}-1106"
    branch = f"work/{ticket}"
    fake_gh.setup(me=pack["forge"]["human_login"], repos=[f"{org}/{first}", f"{org}/{second}"])
    drafts = {}
    for name, sibling in ((first, second), (second, first)):
        drafts[name] = env["workspace"] / f"{name}.md"
        drafts[name].write_text(f"Ticket {ticket}\n\nRelated:\n- ({sibling}) TBD\n", encoding="utf-8")
    # The first repo already has a PR open for the branch: it is edited, not opened a second time.
    fake_gh.pull(f"{org}/{first}", 4, branch, "a" * 40, title="old title")
    rows = []
    for name in (first, second):
        made = create(
            pack,
            ticket,
            "open-pr",
            "c",
            "open",
            {
                "repo": name,
                "branch": branch,
                "title": f"{ticket}: {pack['name']}",
                "body_file": str(drafts[name]),
                "labels": [f"{pack['name']}-review"],
            },
        )
        rows.append(endorse(made["id"], "low", "", "gatekeeper", "fixture-a", "fixture-large"))
    receipts = publish_all(rows, forge_for(pack), {row["id"]: row["id"] for row in rows}, pack=pack)
    assert [receipt["ok"] for receipt in receipts] == [True, True]
    assert "already open" in receipts[0]["output"] and receipts[1]["url"].endswith(f"{org}/{second}/pull/1")
    state = fake_gh.state()["repos"]
    edited, opened = state[f"{org}/{first}"]["pulls"]["4"], state[f"{org}/{second}"]["pulls"]["1"]
    assert (
        edited["title"] == opened["title"] == f"{ticket}: {pack['name']}" and len(state[f"{org}/{first}"]["pulls"]) == 1
    )
    assert edited["labels"] == opened["labels"] == [f"{pack['name']}-review"]
    assert f"- ({second}) https://github.com/{org}/{second}/pull/1" in edited["body"]
    assert f"- ({first}) https://github.com/{org}/{first}/pull/4" in opened["body"]
    assert load_intent(rows[1]["id"])["payload"]["number"] == 1
    # Every field of an edit is read back after it is sent.
    fake_gh.pull(f"{org}/{first}", 9, f"{branch}-b", "b" * 40, title=f"{ticket} bump", draft=True)
    data = fake_gh.state()
    data["repos"][f"{org}/{first}"]["pulls"]["9"]["labels"] = ["stale", "keep"]
    fake_gh.save(data)
    body = env["workspace"] / "edit.md"
    body.write_text(f"new body {pack['name']}\n", encoding="utf-8")
    edit = create(
        pack,
        ticket,
        "pr-edit",
        "c",
        "edit",
        {
            "repo": first,
            "number": 9,
            "base": "main",
            "title_append": f"[{ticket}]",
            "body_file": str(body),
            "add_labels": ["fresh"],
            "remove_labels": ["stale", "absent"],
            "assignee": "me",
            "ready": True,
        },
    )
    edit = endorse(edit["id"], "low", "", "gatekeeper", "fixture-a", "fixture-large")
    receipt = execute(edit, pack=pack)
    assert receipt["ok"], receipt
    shown = fake_gh.state()["repos"][f"{org}/{first}"]["pulls"]["9"]
    assert (
        shown["title"] == f"{ticket} bump [{ticket}]"
        and shown["body"] == f"new body {pack['name']}\n"
        and shown["draft"] is False
    )
    assert shown["labels"] == ["fresh", "keep"] and shown["assignees"] == [{"login": pack["forge"]["human_login"]}]
    again = endorse(
        create(
            pack,
            ticket,
            "pr-edit",
            "c",
            "edit",
            {"repo": first, "number": 9, "title_append": f"[{ticket}]", "labels": ["only"], "add_labels": ["also"]},
        )["id"],
        "low",
        "",
        "gatekeeper",
        "fixture-a",
        "fixture-large",
    )
    assert execute(again, pack=pack)["ok"]
    shown = fake_gh.state()["repos"][f"{org}/{first}"]["pulls"]["9"]
    assert shown["title"] == f"{ticket} bump [{ticket}]" and shown["labels"] == ["also", "only"]
    # A forge that does not keep what it was sent fails the read-back.
    lost = endorse(
        create(
            pack, ticket, "pr-edit", "c", "edit", {"repo": first, "number": 9, "assignee": f"{pack['name']}-friend"}
        )["id"],
        "low",
        "",
        "gatekeeper",
        "fixture-a",
        "fixture-large",
    )

    from cockpitlib.forge import Forge

    real = Forge.write

    def forgetful(self, method, path, body=None):
        if path.endswith("/assignees"):
            self.writes.append({"method": method, "path": path, "body": body})
            return {}
        return real(self, method, path, body)

    monkeypatch.setattr(Forge, "write", forgetful)
    refused = execute(lost, pack=pack)
    assert not refused["ok"] and f"not assigned to {pack['name']}-friend" in refused["error"]
    assert _other(pack)["forge"]["human_login"] not in json.dumps(fake_gh.calls())


@pytest.mark.parametrize("pack_file", PACKS)
def test_a_patch_apply_pushes_then_answers_each_thread_and_resumes_where_it_stopped(env, pack_file, monkeypatch):
    from cockpitlib.intents import load as load_intent
    from cockpitlib.outbox import create, endorse
    from cockpitlib.paths import qa
    from cockpitlib.publish import execute
    from tests.support import fake_gh

    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    monkeypatch.delenv("COCKPIT_LANE", raising=False)
    pack = load(pack_file)
    org = pack["forge"]["org"]
    repo = pack["repos"]["repos"][0]["name"]
    full = f"{org}/{repo}"
    me = pack["forge"]["human_login"]
    reviewer = f"{pack['name']}-reviewer"
    ticket = f"{pack['tracker']['project']}-1107"
    branch = f"work/{ticket}"
    fake_gh.setup(me=me, repos=[full])
    sha = fake_gh.commit(repo, branch, name="fix.txt")
    fake_gh.pull(full, 5, branch, sha)
    fake_gh.thread(full, 5, 4001, reviewer, "rename this")
    fake_gh.thread(full, 5, 4010, reviewer, "unused import")
    fake_gh.thread(full, 5, 4020, reviewer, "why not cache it?")
    fake_gh.thread(full, 5, 4030, reviewer, "typo", replies=[(reviewer, "and one more thing")])
    plan = env["workspace"] / "plan.json"
    plan.write_text(
        json.dumps(
            {
                "rows": [
                    {
                        "n": 1,
                        "comment_id": 4001,
                        "thread": "PRRT_4001",
                        "location": "a.py:1",
                        "reviewer": reviewer,
                        "type": "Code",
                    },
                    {"n": 2, "comment_id": 4010, "thread": "PRRT_4010", "type": "GitHub housekeeping"},
                    {
                        "n": 3,
                        "comment_id": 4020,
                        "thread": "PRRT_4020",
                        "type": "Deferred",
                        "reply": f"later, in {pack['name']}",
                    },
                    {"n": 4, "comment_id": 4030, "type": "Code"},
                ]
            }
        ),
        encoding="utf-8",
    )
    for bad, message in (
        ({"rows": []}, "no rows"),
        ([{"comment_id": 1, "type": "Maybe"}], "type is one of"),
        ([{"comment_id": "x", "type": "Code"}], "comment_id"),
        ([{"comment_id": 1, "type": "Deferred"}], "answered with a reply"),
        ([{"comment_id": 1, "type": "Code", "reply": "no"}], "no reply"),
        (["row"], "is not an object"),
    ):
        wrong = env["workspace"] / "wrong.json"
        wrong.write_text(json.dumps(bad), encoding="utf-8")
        with pytest.raises(CockpitError, match=message):
            create(
                pack,
                ticket,
                "pr-patch-apply",
                "c",
                "apply",
                {"repo": repo, "number": 5, "branch": branch, "threads_file": str(wrong)},
            )
    (env["workspace"] / "wrong.json").write_text("{not json", encoding="utf-8")
    with pytest.raises(CockpitError, match="not readable JSON"):
        create(
            pack,
            ticket,
            "pr-patch-apply",
            "c",
            "apply",
            {"repo": repo, "number": 5, "branch": branch, "threads_file": str(env["workspace"] / "wrong.json")},
        )
    made = create(
        pack,
        ticket,
        "pr-patch-apply",
        "c",
        "apply",
        {"repo": repo, "number": 5, "branch": branch, "threads_file": str(plan)},
    )
    body = open(os.path.join(env["workspace"], made["payload"]["body_file"]), encoding="utf-8").read()
    assert (
        "2 code · 1 housekeeping · 1 deferred" in body
        and f"later, in {pack['name']}" in body
        and "(new branch)" in body
    )
    made = endorse(made["id"], "low", "", "gatekeeper", "fixture-a", "fixture-large")
    fake_gh.fail("POST comments/4020/replies", f"forge hiccup {pack['name']}")
    stopped = execute(made, pack=pack)
    assert (
        not stopped["ok"] and f"forge hiccup {pack['name']}" in stopped["error"] and fake_gh.remote(repo, branch) == sha
    )
    kept = load_intent(made["id"])
    assert f"push:{sha[:12]}" in kept["receipt_steps"] and "4001:resolve" in kept["receipt_steps"]
    data = fake_gh.state()
    data["fail"] = {}
    fake_gh.save(data)
    kept["status"] = "endorsed"
    receipt = execute(kept, pack=pack)
    assert receipt["ok"], receipt
    assert "push: already done" in receipt["output"] and "left open" in receipt["output"]
    pull = fake_gh.state()["repos"][full]["pulls"]["5"]
    threads = {thread["id"]: thread for thread in pull["threads"]}
    assert threads["PRRT_4001"]["isResolved"] and threads["PRRT_4010"]["isResolved"]
    assert not threads["PRRT_4020"]["isResolved"] and not threads["PRRT_4030"]["isResolved"]
    replies = [row for row in pull["review_comments"].values() if row.get("in_reply_to") == 4020]
    assert [row["body"] for row in replies] == [f"later, in {pack['name']}"]
    assert pull["review_comments"]["4001"]["reactions"] == [{"content": "+1", "user": {"login": me}}]
    pushes = [call for call in fake_gh.calls() if call["path"].endswith("/replies")]
    assert len(pushes) == 2  # the failed one and the one that went through; nothing posted twice
    # A reply on a PR the human reviews is its own intent; the human's own open PR answers in its patch apply.
    folder = os.path.join(qa(), ticket, "pr")
    os.makedirs(folder, exist_ok=True)
    open(os.path.join(folder, f"{repo}-5.json"), "w", encoding="utf-8").write(
        json.dumps({"role": "author", "state": "open"})
    )
    with pytest.raises(CockpitError, match="your own open PR"):
        create(pack, ticket, "pr-comment", "c", "reply", {"repo": repo, "number": 5, "in_reply_to": 4030, "body": "ok"})
    open(os.path.join(folder, f"{repo}-5.json"), "w", encoding="utf-8").write(
        json.dumps({"role": "reviewer", "state": "open"})
    )
    with pytest.raises(CockpitError, match="not your PR"):
        create(
            pack,
            ticket,
            "pr-patch-apply",
            "c",
            "apply",
            {"repo": repo, "number": 5, "branch": branch, "threads_file": str(plan)},
        )
    for bad, message in (
        ({"resolve": True}, "--resolve needs --thread"),
        ({"react": True}, "add --in-reply-to"),
        ({"in_reply_to": None}, "needs --body-file"),
    ):
        with pytest.raises(CockpitError, match=re.escape(message)):
            create(
                pack,
                ticket,
                "pr-comment",
                "c",
                "reply",
                {
                    "repo": repo,
                    "number": 5,
                    **({} if "in_reply_to" in bad else {"body": "x"}),
                    **{k: v for k, v in bad.items() if v},
                },
            )
    reply = endorse(
        create(
            pack,
            ticket,
            "pr-comment",
            "c",
            "reply",
            {
                "repo": repo,
                "number": 5,
                "in_reply_to": 4030,
                "thread": "PRRT_4030",
                "body": "Agreed",
                "resolve": True,
                "react": True,
            },
        )["id"],
        "low",
        "",
        "gatekeeper",
        "fixture-a",
        "fixture-large",
    )
    assert execute(reply, pack=pack)["ok"]
    assert (
        fake_gh.state()["repos"][full]["pulls"]["5"]["threads"][3]["isResolved"] is False
    )  # someone wrote after the plan
    wrong_thread = endorse(
        create(
            pack,
            ticket,
            "pr-comment",
            "c",
            "reply",
            {"repo": repo, "number": 5, "in_reply_to": 4030, "thread": "PRRT_9999", "body": "x"},
        )["id"],
        "low",
        "",
        "gatekeeper",
        "fixture-a",
        "fixture-large",
    )
    assert "is in PRRT_4030" in execute(wrong_thread, pack=pack)["error"]
    nowhere = endorse(
        create(pack, ticket, "pr-comment", "c", "reply", {"repo": repo, "number": 5, "in_reply_to": 777, "body": "x"})[
            "id"
        ],
        "low",
        "",
        "gatekeeper",
        "fixture-a",
        "fixture-large",
    )
    assert "is in no thread" in execute(nowhere, pack=pack)["error"]
    again = endorse(
        create(
            pack, ticket, "pr-comment", "c", "reply", {"repo": repo, "number": 5, "in_reply_to": 4020, "body": "again"}
        )["id"],
        "low",
        "",
        "gatekeeper",
        "fixture-a",
        "fixture-large",
    )
    assert "you already replied" in execute(again, pack=pack)["output"]


@pytest.mark.parametrize("pack_file", PACKS)
def test_more_threads_join_the_humans_own_pending_review_and_it_stays_pending(env, pack_file, monkeypatch):
    from cockpitlib.outbox import create, endorse
    from cockpitlib.publish import execute
    from tests.support import fake_gh

    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    monkeypatch.delenv("COCKPIT_LANE", raising=False)
    pack = load(pack_file)
    org, repo = pack["forge"]["org"], pack["repos"]["repos"][0]["name"]
    full = f"{org}/{repo}"
    ticket = f"{pack['tracker']['project']}-1108"
    head = "9" * 40
    fake_gh.setup(me=pack["forge"]["human_login"], repos=[full])
    fake_gh.pull(full, 6, f"work/{ticket}", head)
    first = env["workspace"] / "first.json"
    first.write_text(json.dumps([{"path": "a.py", "line": 2, "body": "one", "start_line": 1}]), encoding="utf-8")
    posted = endorse(
        create(
            pack,
            ticket,
            "pr-review-submit",
            "c",
            "r",
            {"repo": repo, "number": 6, "sha": head, "threads_file": str(first)},
        )["id"],
        "low",
        "",
        "gatekeeper",
        "fixture-a",
        "fixture-large",
    )
    assert execute(posted, pack=pack)["stage"] == "pending"
    review = posted["review"]["id"]
    existing = fake_gh.state()["repos"][full]["pulls"]["6"]["reviews"][str(review)]["comments"][0]
    more = env["workspace"] / "more.json"
    more.write_text(
        json.dumps(
            [{"path": f"{pack['name']}.py", "line": 7, "body": "two"}, {"path": "b.py", "line": 3, "body": "three"}]
        ),
        encoding="utf-8",
    )
    patches = env["workspace"] / "patches.json"
    patches.write_text(json.dumps([{"id": existing, "body": f"one, sharper ({pack['name']})"}]), encoding="utf-8")
    summary = env["workspace"] / "summary.md"
    summary.write_text(f"summary {pack['name']}\n", encoding="utf-8")
    with pytest.raises(CockpitError, match="never submits it: drop --event"):
        create(
            pack,
            ticket,
            "pr-review-submit",
            "c",
            "r",
            {"repo": repo, "number": 6, "sha": head, "review_id": review, "event": "COMMENT"},
        )
    with pytest.raises(CockpitError, match="need --review-id"):
        create(
            pack,
            ticket,
            "pr-review-submit",
            "c",
            "r",
            {"repo": repo, "number": 6, "sha": head, "patch_comments": str(patches)},
        )
    append = endorse(
        create(
            pack,
            ticket,
            "pr-review-submit",
            "c",
            "r",
            {
                "repo": repo,
                "number": 6,
                "sha": head,
                "review_id": review,
                "threads_file": str(more),
                "patch_comments": str(patches),
                "review_body_update": str(summary),
            },
        )["id"],
        "low",
        "",
        "gatekeeper",
        "fixture-a",
        "fixture-large",
    )
    receipt = execute(append, pack=pack)
    assert receipt["ok"] and f"pending review {review}: +2 thread(s), 1 patched" in receipt["output"]
    pending = fake_gh.state()["repos"][full]["pulls"]["6"]
    shown = pending["reviews"][str(review)]
    assert shown["state"] == "PENDING" and shown["body"] == f"summary {pack['name']}\n" and len(shown["comments"]) == 3
    assert pending["review_comments"][str(existing)]["body"] == f"one, sharper ({pack['name']})"
    stranger = endorse(
        create(
            pack,
            ticket,
            "pr-review-submit",
            "c",
            "r",
            {"repo": repo, "number": 6, "sha": head, "review_id": 12345, "threads_file": str(more)},
        )["id"],
        "low",
        "",
        "gatekeeper",
        "fixture-a",
        "fixture-large",
    )
    assert "is not a pending review of yours" in execute(stranger, pack=pack)["error"]
    moved = endorse(
        create(pack, ticket, "pr-review-submit", "c", "r", {"repo": repo, "number": 6, "sha": "8" * 40})["id"],
        "low",
        "",
        "gatekeeper",
        "fixture-a",
        "fixture-large",
    )
    assert "the PR head moved" in execute(moved, pack=pack)["error"]


@pytest.mark.parametrize("pack_file", PACKS)
def test_the_tracker_gets_comments_issues_and_moves_and_each_is_read_back(env, pack_file, monkeypatch, jira):
    from cockpitlib.intents import load as load_intent
    from cockpitlib.outbox import create, endorse
    from cockpitlib.publish import execute

    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    monkeypatch.delenv("COCKPIT_LANE", raising=False)
    pack = load(pack_file)
    project = pack["tracker"]["project"]
    ticket = f"{project}-1109"
    jira.issue(ticket)

    def ready(kind, payload, summary="tracker"):
        made = create(pack, ticket, kind, "c", summary, payload)
        return endorse(made["id"], "low", "", "gatekeeper", "fixture-a", "fixture-large")

    evidence = env["workspace"] / pack["records_dir"] / "qa" / ticket / "row-1.png"
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_bytes(b"picture-" + pack["name"].encode())
    doc = env["workspace"] / "run.json"
    doc.write_text(
        json.dumps(
            {
                "type": "doc",
                "version": 1,
                "content": [
                    {
                        "type": "paragraph",
                        "content": [{"type": "text", "text": f"Run for {pack['name']}: see row-1.png for the screen"}],
                    },
                    {
                        "type": "expand",
                        "content": [{"type": "paragraph", "content": [{"type": "text", "text": "details"}]}],
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    first = ready("tracker-comment", {"body_file": str(doc), "attach": [str(evidence)], "probe_title": "Run for"})
    receipt = execute(first, pack=pack)
    assert receipt["ok"], receipt
    issue = jira.issues[ticket]
    [comment] = issue["comments"].values()
    attachment = issue["attachments"][0]
    assert attachment["filename"] == "row-1.png" and attachment["size"] == len(b"picture-" + pack["name"].encode())
    texts = [node for node in comment["body"]["content"][0]["content"] if node.get("marks")]
    assert texts[0]["text"] == "row-1.png" and texts[0]["marks"][0]["attrs"]["href"].endswith(
        f"/secure/attachment/{attachment['id']}/row-1.png"
    )
    assert comment["body"]["content"][-1]["content"][0]["text"] == "Attachments: "
    assert load_intent(first["id"])["receipt_steps"]["comment"]["value"] == comment["id"]
    uploads = [row for row in jira.requests if row["path"].endswith("/attachments")]
    assert len(uploads) == 1 and uploads[0]["token_check"] == "no-check" and uploads[0]["auth"].startswith("Basic ")
    # The results post updates the comment the first one made, after publishing it first when it was still waiting.
    note = env["workspace"] / "note.md"
    note.write_text(f"h3. Results for {pack['name']}\n", encoding="utf-8")
    pending_first = ready("tracker-comment", {"body": f"draft {pack['name']}"})
    follow = ready(
        "tracker-comment", {"body_file": str(note), "comment_from": pending_first["id"], "attach": [str(evidence)]}
    )
    assert execute(follow, pack=pack)["ok"]
    made_by_first = load_intent(pending_first["id"])["receipt_steps"]["comment"]["value"]
    assert issue["comments"][made_by_first]["body"] == f"h3. Results for {pack['name']}\n\nAttachments: [^row-1.png]\n"
    assert len([row for row in jira.requests if row["path"].endswith("/attachments") and row["method"] == "POST"]) == 1
    # A second post under the same heading would be a duplicate: it is refused, naming the comment to update.
    twin = ready("tracker-comment", {"body_file": str(doc), "probe_title": "Run for"})
    refused = execute(twin, pack=pack)
    assert not refused["ok"] and f"--comment-id {comment['id']}" in refused["error"]
    jira.flatten = True
    flat = ready("tracker-comment", {"body_file": str(doc)})
    assert "flattened" in execute(flat, pack=pack)["error"]
    jira.flatten = False
    # An issue: the component the project allows, the active sprint, the human as assignee; a field the tracker dropped is set again.
    jira.drop_on_create = {"components"}
    made = ready(
        "tracker-create",
        {
            "summary": f"bump {pack['name']}",
            "component": jira.components[1].lower(),
            "sprint": "active",
            "assignee": "me",
            "labels": ["deps"],
            "transition": "In Progress",
        },
    )
    receipt = execute(made, pack=pack)
    assert receipt["ok"], receipt
    key = load_intent(made["id"])["receipt_steps"]["key"]["value"]
    created = jira.issues[key]
    assert (
        created["fields"]["components"] == [{"name": jira.components[1]}]
        and created["fields"]["customfield_200"] == jira.sprint
    )
    assert created["fields"]["assignee"] == {"accountId": jira.account} and created["status"] == "In Progress"
    assert (
        created["fields"]["issuetype"] == {"name": pack["tracker"]["issue_type"]}
        and "set again after create: components" in receipt["output"]
    )
    jira.drop_on_create = {"components", "assignee"}
    stubborn = ready("tracker-create", {"summary": "stubborn", "component": "Core", "assignee": "me"})
    original = jira.handle

    def ignores_put(method, path, body, raw):
        if method == "PUT" and path.startswith("/rest/api/3/issue/") and "/comment" not in path:
            return 204, {}
        return original(method, path, body, raw)

    monkeypatch.setattr(jira, "handle", ignores_put)
    assert "still empty" in execute(stubborn, pack=pack)["error"]
    monkeypatch.setattr(jira, "handle", original)
    assert (
        "is not one of"
        in execute(ready("tracker-create", {"summary": "x", "component": "Nowhere"}), pack=pack)["error"]
    )
    # A move the workflow cannot make yet waits for the endorsed move that gets there; then both go, in order.
    to_progress = ready("tracker-transition", {"issue": ticket, "to": "In Progress"})
    to_review = ready("tracker-transition", {"issue": ticket, "to": "In Review", "assignee": "me"})
    assert to_review["payload"]["after"] == to_progress["id"]
    receipt = execute(to_review, pack=pack)
    assert (
        receipt["ok"] and issue["status"] == "In Review" and issue["fields"]["assignee"] == {"accountId": jira.account}
    )
    assert load_intent(to_progress["id"])["status"] == "published"
    lost = ready("tracker-transition", {"issue": ticket, "to": "Backlog"})
    assert "no transition means 'Backlog' from 'In Review'" in execute(lost, pack=pack)["error"]
    jira.issue(f"{ticket}9", status="In Progress")
    vague = ready("tracker-transition", {"issue": f"{ticket}9", "to": "a"})
    assert "is ambiguous" in execute(vague, pack=pack)["error"]
    for name in pack["tracker"]["auth_env"]:
        monkeypatch.delenv(name)
    absent = ready("tracker-comment", {"body": "late"})
    assert f"not in this shell ({', '.join(pack['tracker']['auth_env'])})" in execute(absent, pack=pack)["error"]
    assert _other(pack)["tracker"]["project"] not in json.dumps(jira.requests)


@pytest.mark.parametrize("pack_file", PACKS)
def test_a_pack_may_send_tracker_writes_to_its_own_command(env, pack_file, monkeypatch, tmp_path):
    import shutil

    import yaml

    from cockpitlib.errors import PackError
    from cockpitlib.intents import load as load_intent
    from cockpitlib.outbox import create, endorse
    from cockpitlib.publish import execute

    monkeypatch.delenv("COCKPIT_LANE", raising=False)
    name = os.path.basename(os.path.dirname(pack_file))
    copied = tmp_path / "packs" / name
    shutil.copytree(os.path.dirname(pack_file), copied)
    seen = tmp_path / "seen.jsonl"
    command = copied / "bin" / "tickets"
    command.write_text(
        '#!/bin/sh\nread -r line\necho "$COCKPIT_TRACKER_ACTION $line" >> ' + str(seen) + "\n"
        'case "$COCKPIT_TRACKER_ACTION" in\n'
        f'  create) echo \'{{"key": "{name.upper()}-9", "url": "https://tickets.{name}.test/9"}}\';;\n'
        '  comment) echo \'{"id": "55"}\';;\n'
        "  *) echo 'not json';;\nesac\n",
        encoding="utf-8",
    )
    command.chmod(0o755)
    raw = yaml.safe_load((copied / "pack.yaml").read_text(encoding="utf-8"))
    named = {key: raw["tracker"][key] for key in ("url", "project")}
    raw["tracker"] = {**named, "kind": "command", "command": ["{pack}/bin/tickets"]}
    (copied / "pack.yaml").write_text(yaml.safe_dump(raw, sort_keys=False, allow_unicode=True), encoding="utf-8")
    monkeypatch.setenv("COCKPIT_PACK", str(copied / "pack.yaml"))
    pack = load(str(copied / "pack.yaml"))
    assert pack["tracker"]["command"] == [str(copied / "bin" / "tickets")]
    ticket = f"{pack['tracker']['project']}-1110"
    made = endorse(
        create(pack, ticket, "tracker-create", "c", "t", {"summary": f"via {name}"})["id"],
        "low",
        "",
        "gatekeeper",
        "fixture-a",
        "fixture-large",
    )
    receipt = execute(made, pack=pack)
    assert receipt["ok"] and receipt["url"] == f"https://tickets.{name}.test/9"
    assert load_intent(made["id"])["payload"]["key"] == f"{name.upper()}-9"
    line = seen.read_text(encoding="utf-8").splitlines()[0]
    assert line.startswith("create ") and json.loads(line.split(" ", 1)[1])["payload"]["summary"] == f"via {name}"
    note = endorse(
        create(pack, ticket, "tracker-comment", "c", "t", {"body": "hi"})["id"],
        "low",
        "",
        "gatekeeper",
        "fixture-a",
        "fixture-large",
    )
    assert execute(note, pack=pack)["ok"] and load_intent(note["id"])["receipt_steps"]["comment"]["value"] == "55"
    move = endorse(
        create(pack, ticket, "tracker-transition", "c", "t", {"to": "Done"})["id"],
        "low",
        "",
        "gatekeeper",
        "fixture-a",
        "fixture-large",
    )
    assert "its answer is not JSON" in execute(move, pack=pack)["error"]
    for broken, message in (
        ({"kind": "command"}, "needs tracker.command"),
        ({"command": "tickets"}, "argv list"),
        ({"auth_env": ["ONE"]}, "names two environment variables"),
        ({"kind": "mail"}, "tracker.kind is one of connector, jira, command"),
        ({"summary_max": 0}, "positive whole number"),
        ({"colour": 1}, "tracker takes"),
    ):
        (copied / "pack.yaml").write_text(
            yaml.safe_dump({**raw, "tracker": {**named, **broken}}, sort_keys=False, allow_unicode=True),
            encoding="utf-8",
        )
        with pytest.raises(PackError, match=re.escape(message)):
            load(str(copied / "pack.yaml"))
    for broken, message in (
        ({"bots": "one"}, "list of names"),
        ({"review_labels": {"MERGE": {}}}, "maps REQUEST_CHANGES"),
        ({"review_labels": {"APPROVE": {"add": "x"}}}, "{add: [labels]"),
        ({"colour": 1}, "forge takes"),
    ):
        (copied / "pack.yaml").write_text(
            yaml.safe_dump(
                {**raw, "forge": {"org": raw["forge"]["org"], **broken}}, sort_keys=False, allow_unicode=True
            ),
            encoding="utf-8",
        )
        with pytest.raises(PackError, match=re.escape(message)):
            load(str(copied / "pack.yaml"))


@pytest.mark.parametrize("pack_file", PACKS)
def test_a_test_results_comment_leaves_only_when_the_rows_agree_with_its_banner(env, pack_file, monkeypatch, jira):
    from cockpitlib.outbox import create, endorse
    from cockpitlib.paths import qa
    from cockpitlib.publish import execute
    from cockpitlib.test_flow import next_run_dir, post_problems

    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    monkeypatch.delenv("COCKPIT_LANE", raising=False)
    pack = load(pack_file)
    ticket = f"{pack['tracker']['project']}-1111"
    jira.issue(ticket)
    folder = os.path.join(qa(), ticket)
    os.makedirs(folder, exist_ok=True)

    def post(text):
        return endorse(
            create(pack, ticket, "tracker-comment", "c", "results", {"body": words.worded(pack, text)})["id"],
            "low",
            "",
            "gatekeeper",
            "fixture-a",
            "fixture-large",
        )

    assert "has no test results" in execute(post(f"Tested and Ok for {pack['name']}"), pack=pack)["error"]
    run = os.path.join(folder, next_run_dir(pack, folder))
    os.makedirs(run)
    results = os.path.join(run, "test-results.md")
    open(results, "w", encoding="utf-8").write(
        words.worded(pack, "| 1 | login | ✅ evidences/1.png |\n| 2 | export | Not run |\n")
    )
    assert "still open" in execute(post("Tested and Ok"), pack=pack)["error"]
    open(results, "w", encoding="utf-8").write(
        words.worded(pack, "| 1 | login | ✅ evidences/1.png |\n| 2 | export | ❌ evidences/2.png |\n")
    )
    wrong = execute(post(f"Tested and Ok\n\n{pack['name']} rows"), pack=pack)
    said = words.worded(pack, "the post says 'Tested and Ok' but the rows call for 'Tested and Not Ok'")
    assert said in wrong["error"]
    assert "In progress" in execute(post("In progress, then Tested and Not Ok"), pack=pack)["error"]
    assert execute(post(f"Tested and Not Ok\n\n{pack['name']}: row 2 failed"), pack=pack)["ok"]
    assert (
        post_problems(pack, {"type": "tracker-comment", "ticket": ticket, "payload": {"body": "a plain comment"}}) == []
    )
    assert post_problems(pack, {"type": "pr-comment", "ticket": ticket, "payload": {"body": words.ok(pack)}}) == []


@pytest.mark.parametrize("pack_file", PACKS)
def test_every_read_back_that_disagrees_stops_the_publish(env, pack_file, monkeypatch, jira):
    from cockpitlib import publish
    from cockpitlib.intents import load as load_intent
    from cockpitlib.intents import save
    from cockpitlib.outbox import create, drop, endorse

    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    monkeypatch.delenv("COCKPIT_LANE", raising=False)
    pack = load(pack_file)
    repo = pack["repos"]["repos"][0]["name"]
    ticket = f"{pack['tracker']['project']}-1112"
    scratch = f"{pack['tracker']['project']}-1199"  # synthetic records the read-back helpers save, apart from the ticket's own
    jira.issue(ticket)
    pr = {
        "base": {"ref": "main"},
        "title": pack["name"],
        "body": "b",
        "assignees": [],
        "draft": True,
        "head": {"sha": "a" * 40},
    }
    lying = _LyingForge(pack, pr=pr, labels=["kept"])
    for want, message in (
        ({"base": "trunk"}, "base main != trunk"),
        ({"title": "other"}, "title"),
        ({"body": "c"}, "body differs"),
        ({"labels": ["x"]}, "labels ['kept'] != ['x']"),
        ({"add_labels": ["x"]}, "miss"),
        ({"remove_labels": ["kept"]}, "still carry"),
        ({"ready": True}, "still a draft"),
    ):
        with pytest.raises(CockpitError, match=re.escape(message)):
            publish._verify_pr(lying, repo, 1, want)
    intent = {"id": f"{scratch}/001-pr-comment", "receipt_steps": {"Kreply": {}}}
    assert (
        "reply already sent"
        in publish._thread(
            _LyingForge(pack, threads=[_thread_nodes()]), intent, repo, 1, 1, "", "text", False, False, "K", True
        )[1]
    )
    for nodes, kwargs, message in (
        (_thread_nodes(), {"reply": "text"}, "no reply of yours"),
        (_thread_nodes(), {"resolve": True}, "is not resolved"),
        (_thread_nodes(resolved=True), {}, "resolved although the row only replies"),
    ):
        before = _thread_nodes()
        forge = _LyingForge(pack, threads=[before, nodes])
        with pytest.raises(CockpitError, match=message):
            publish._thread(
                forge,
                {"id": f"{scratch}/050-pr-comment"},
                repo,
                1,
                1,
                "",
                kwargs.get("reply", ""),
                False,
                kwargs.get("resolve", False),
                "",
                False,
            )
    # A review the forge holds differently from what was sent.
    review_payload = {"repo": repo, "number": 1, "sha": "a" * 40, "review_id": 7}
    answers = {
        r"/reviews$": [{"id": 7, "state": "PENDING", "user": {"login": "human"}, "node_id": "N7"}],
        r"/reviews/7/comments": [],
        r"/reviews/7$": {"state": "COMMENTED"},
    }
    row = {"id": f"{scratch}/051-pr-review-submit", "payload": review_payload}
    with pytest.raises(CockpitError, match="stays pending"):
        publish._pr_review_submit(pack, row, _LyingForge(pack, pr=pr, answers=answers), False)
    patches = env["workspace"] / "p.json"
    patches.write_text(json.dumps([{"id": 3, "body": "new"}]), encoding="utf-8")
    with pytest.raises(CockpitError, match="does not show its new text"):
        publish._pr_review_submit(
            pack,
            {"id": f"{scratch}/051-pr-review-submit", "payload": {**review_payload, "patch_comments": str(patches)}},
            _LyingForge(pack, pr=pr, answers={**answers, r"/reviews/7/comments": [{"id": 3, "body": "old"}]}),
            False,
        )
    summary = env["workspace"] / "s.md"
    summary.write_text("new summary", encoding="utf-8")
    with pytest.raises(CockpitError, match="summary did not change"):
        publish._pr_review_submit(
            pack,
            {
                "id": f"{scratch}/051-pr-review-submit",
                "payload": {**review_payload, "review_body_update": str(summary)},
            },
            _LyingForge(pack, pr=pr, answers={**answers, r"/reviews/7$": {"state": "PENDING", "body": "old"}}),
            False,
        )
    threads = env["workspace"] / "t.json"
    threads.write_text(json.dumps([{"path": "a.py", "line": 1, "body": "x"}]), encoding="utf-8")
    counting = {**answers, r"/reviews/7/comments": lambda: []}
    with pytest.raises(CockpitError, match="shows 0 comments, not 1"):
        publish._pr_review_submit(
            pack,
            {"id": f"{scratch}/051-pr-review-submit", "payload": {**review_payload, "threads_file": str(threads)}},
            _LyingForge(pack, pr=pr, answers=counting),
            False,
        )
    done = {
        "id": f"{scratch}/051-pr-review-submit",
        "payload": {**review_payload, "threads_file": str(threads)},
        "receipt_steps": {"append:0": {}},
    }
    assert (
        "would add 0 thread(s)"
        in publish._pr_review_submit(pack, done, _LyingForge(pack, pr=pr, answers=answers), True)[1]
    )
    fresh = {r"/reviews$": [], r"/reviews/1/comments": []}
    with pytest.raises(CockpitError, match="the forge shows 0"):
        publish._pr_review_submit(
            pack,
            {
                "id": f"{scratch}/051-pr-review-submit",
                "payload": {"repo": repo, "number": 1, "sha": "a" * 40, "threads_file": str(threads)},
            },
            _LyingForge(pack, pr=pr, answers=fresh),
            False,
        )
    assert (
        "would post a pending review"
        in publish._pr_review_submit(
            pack,
            {"id": f"{scratch}/051-pr-review-submit", "payload": {"repo": repo, "number": 1, "sha": "a" * 40}},
            _LyingForge(pack, pr=pr, answers=fresh),
            True,
        )[1]
    )
    # Stage two refuses anything but a pending review of the human's, and reads the verdict back.
    posted = {
        "id": f"{ticket}/009-pr-review-submit",
        "type": "pr-review-submit",
        "status": "posted",
        "payload": {"repo": repo, "number": 1, "sha": "a" * 40},
        "review": {"id": 7},
    }
    with pytest.raises(CockpitError, match="the verdict is one of"):
        publish.submit_review(dict(posted), lying, event="MERGE", pack=pack)
    with pytest.raises(CockpitError, match="not pending"):
        publish.submit_review(
            dict(posted), _LyingForge(pack, answers={r"/reviews/7$": {"state": "DISMISSED"}}), pack=pack
        )
    assert publish.submit_review(
        dict(posted), _LyingForge(pack, answers={r"/reviews/7$": {"state": "PENDING"}}), pack=pack, dry_run=True
    )["dry_run"]
    with pytest.raises(CockpitError, match="is PENDING after the submit"):
        publish.submit_review(
            dict(posted), _LyingForge(pack, answers={r"/reviews/7$": {"state": "PENDING"}}), pack=pack
        )
    with pytest.raises(CockpitError, match="only a posted"):
        publish.submit_review({**posted, "status": "endorsed"}, lying, pack=pack)
    event = next(iter(pack["forge"]["review_labels"]))
    stuck = _LyingForge(
        pack,
        labels=["unrelated"],
        answers={r"/labels\?": [{"name": label.title()} for label in pack["forge"]["review_labels"][event]["add"]]},
    )
    with pytest.raises(CockpitError, match="missing"):
        publish._review_labels(pack, stuck, repo, 1, event)
    assert publish._review_labels(pack, stuck, repo, 1, "COMMENT") == ""
    # The intent's own state refuses before the forge is asked.
    no_vouch = create(pack, ticket, "infra-note", "c", "n", {"body": "x"})
    with pytest.raises(CockpitError, match="is not executed"):
        publish.execute(no_vouch, pack=pack)
    bare = endorse(
        create(pack, ticket, "ci-rerun", "c", "n", {"repo": repo, "run_id": 3})["id"],
        "low",
        "",
        "gatekeeper",
        "fixture-a",
        "fixture-large",
    )
    bare.pop("endorsement")
    with pytest.raises(CockpitError, match="has no endorsement"):
        publish.execute(bare, pack=pack)
    approve = endorse(
        create(
            pack, ticket, "pr-review-submit", "c", "n", {"repo": repo, "number": 1, "sha": "a" * 40, "event": "APPROVE"}
        )["id"],
        "low",
        "",
        "gatekeeper",
        "fixture-a",
        "fixture-large",
    )
    with pytest.raises(CockpitError, match="APPROVE must be named"):
        publish.execute(approve, pack=pack)
    odd = dict(bare, type="mystery", endorsement={"by": "gatekeeper"})
    assert "no publisher for mystery" in publish.execute(odd, pack=pack)["error"]
    assert publish._first({"payload": {"after": f"{ticket}/099-push-branch"}}, {}) == {}
    assert publish.execute(
        endorse(
            create(pack, ticket, "ci-rerun", "c", "n", {"repo": repo, "run_id": 4})["id"],
            "low",
            "",
            "gatekeeper",
            "fixture-a",
            "fixture-large",
        )
    )["ok"]  # the bound pack, when none is given
    # A comment that updates another follows that one's fate.
    source = create(pack, ticket, "tracker-comment", "c", "init", {"body": f"init {pack['name']}"})
    follow = endorse(
        create(pack, ticket, "tracker-comment", "c", "post", {"body": "post", "comment_from": source["id"]})["id"],
        "low",
        "",
        "gatekeeper",
        "fixture-a",
        "fixture-large",
    )
    assert "publish or drop it first" in publish.execute(follow, pack=pack)["error"]
    drop(source["id"])
    assert publish.execute(load_intent(follow["id"]), pack=pack)["ok"]
    silent = create(pack, ticket, "tracker-comment", "c", "init", {"body": "init"})
    silent = endorse(silent["id"], "low", "", "gatekeeper", "fixture-a", "fixture-large")
    silent["status"] = "published"
    save(silent)
    later = endorse(
        create(pack, ticket, "tracker-comment", "c", "post", {"body": "post", "comment_from": silent["id"]})["id"],
        "low",
        "",
        "gatekeeper",
        "fixture-a",
        "fixture-large",
    )
    assert "recorded no comment id" in publish.execute(later, pack=pack)["error"]
    failing = endorse(
        create(pack, ticket, "tracker-comment", "c", "init", {"body": "init"})["id"],
        "low",
        "",
        "gatekeeper",
        "fixture-a",
        "fixture-large",
    )
    after_failing = endorse(
        create(pack, ticket, "tracker-comment", "c", "post", {"body": "post", "comment_from": failing["id"]})["id"],
        "low",
        "",
        "gatekeeper",
        "fixture-a",
        "fixture-large",
    )
    jira.fail = {f"POST /rest/api/2/issue/{ticket}/comment": f"tracker down {pack['name']}"}
    assert f"tracker down {pack['name']}" in publish.execute(after_failing, pack=pack)["error"]
    jira.fail = {}
    # A move by the issue an earlier create makes.
    made = endorse(
        create(pack, ticket, "tracker-create", "c", "c", {"summary": "made"})["id"],
        "low",
        "",
        "gatekeeper",
        "fixture-a",
        "fixture-large",
    )
    moved = endorse(
        create(pack, ticket, "tracker-transition", "c", "m", {"to": "In Progress", "issue_from": made["id"]})["id"],
        "low",
        "",
        "gatekeeper",
        "fixture-a",
        "fixture-large",
    )
    assert moved["payload"]["after"] == made["id"]
    assert (
        publish.execute(load_intent(moved["id"]), pack=pack)["ok"] and load_intent(made["id"])["status"] == "published"
    )
    key = load_intent(made["id"])["receipt_steps"]["key"]["value"]
    unmade = endorse(
        create(pack, ticket, "tracker-create", "c", "c", {"summary": "later"})["id"],
        "low",
        "",
        "gatekeeper",
        "fixture-a",
        "fixture-large",
    )
    early = create(pack, ticket, "tracker-transition", "c", "m", {"to": "In Progress", "issue_from": unmade["id"]})
    early["payload"]["after"] = ""
    early = endorse(early["id"], "low", "", "gatekeeper", "fixture-a", "fixture-large")
    early["payload"]["after"] = ""
    assert "has no key yet" in publish.execute(early, pack=pack)["error"]
    assert jira.issues[key]["status"] == "In Progress"
    jira.issue(f"{ticket}8")
    first = endorse(
        create(pack, ticket, "tracker-transition", "c", "m", {"issue": f"{ticket}8", "to": "In Progress"})["id"],
        "low",
        "",
        "gatekeeper",
        "fixture-a",
        "fixture-large",
    )
    second = endorse(
        create(pack, ticket, "tracker-transition", "c", "m", {"issue": f"{ticket}8", "to": "In Review"})["id"],
        "low",
        "",
        "gatekeeper",
        "fixture-a",
        "fixture-large",
    )
    second["payload"]["after"] = ""
    jira.fail = {f"POST /rest/api/3/issue/{ticket}8/transitions": "no moves today"}
    assert "(the move before this one)" in publish.execute(second, pack=pack)["error"]
    jira.fail = {}
    assert (
        publish.execute(load_intent(second["id"]), pack=pack)["ok"]
        and jira.issues[f"{ticket}8"]["status"] == "In Review"
    )
    assert load_intent(first["id"])["status"] == "published"
    # publish_all records a refusal as a failed receipt and stops.
    refused = publish.publish_all([no_vouch], fakegh_forge(pack), {no_vouch["id"]: no_vouch["id"]}, pack=pack)
    assert refused == [{"ok": False, "error": "infra-note is not executed", "id": no_vouch["id"]}]
    # The sibling links: a body whose link does not stick fails its read-back.
    stays = _LyingForge(pack, pr={"body": f"- ({repo}) TBD\n- (elsewhere) TBD"})
    for index, name in enumerate((repo, "elsewhere")):
        receipt = {"url": f"https://github.com/{pack['forge']['org']}/{name}/pull/{index + 1}"}
        row = endorse(
            create(
                pack,
                f"{ticket}5",
                "open-pr",
                "c",
                "o",
                {"repo": name if name == repo else repo, "branch": f"work/{index}", "title": "t"},
            )["id"],
            "low",
            "",
            "gatekeeper",
            "fixture-a",
            "fixture-large",
        )
        row.update(status="published", receipt=receipt)
        row["payload"]["repo"] = name
        save(row)
    with pytest.raises(CockpitError, match="still shows TBD"):
        publish.backfill_related(stays, f"{ticket}5")


def fakegh_forge(pack):
    from cockpitlib.publish import forge_for

    return forge_for(pack)


@pytest.mark.parametrize("pack_file", PACKS)
def test_an_intent_the_forge_or_tracker_would_refuse_is_refused_when_written(env, pack_file, monkeypatch, jira):
    from cockpitlib import tracker as trackers
    from cockpitlib.intents import save
    from cockpitlib.outbox import amend, create, hold, verify
    from tests.support import fake_gh

    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    monkeypatch.delenv("COCKPIT_LANE", raising=False)
    pack = load(pack_file)
    repo = pack["repos"]["repos"][0]["name"]
    ticket = f"{pack['tracker']['project']}-1113"
    push = create(pack, ticket, "push-branch", "c", "p", {"repo": repo, "branch": "main"})
    comment = create(pack, ticket, "tracker-comment", "c", "n", {"body": "x"})
    refusals = (
        ("pr-edit", {"repo": repo, "number": 1, "title": "a", "title_append": "b"}, "pick one"),
        ("tracker-comment", {"body": "x", "issue": f"{ticket}9", "comment_from": comment["id"]}, "on the same issue"),
        ("tracker-comment", {"body": "x", "comment_from": push["id"]}, "on the same issue"),
        ("tracker-transition", {"to": "Done", "issue_from": comment["id"]}, "names the tracker-create intent"),
        ("tracker-transition", {"to": "Done", "after": comment["id"]}, "names the review, push, create or move"),
        (
            "pr-comment",
            {"repo": repo, "number": 1, "body": "x", "after": comment["id"]},
            "names a push intent with a sha",
        ),
        ("tracker-comment", {"body": "x", "attach": ["absent.png"]}, "absent.png: no such file"),
        (
            "tracker-comment",
            {"body": "x", "comment_from": f"{ticket}/098-tracker-comment"},
            f"no intent {ticket}/098-tracker-comment",
        ),
    )
    for kind, payload, message in refusals:
        with pytest.raises(CockpitError, match=re.escape(message)):
            create(pack, ticket, kind, "c", "x", payload)
    if pack["tracker"].get("summary_max"):
        with pytest.raises(CockpitError, match=f"this tracker takes {pack['tracker']['summary_max']}"):
            create(pack, ticket, "tracker-create", "c", "x", {"summary": "s" * (pack["tracker"]["summary_max"] + 1)})
    updates = create(pack, ticket, "tracker-comment", "c", "x", {"body": "x", "comment_id": "5", "probe_title": "Run"})
    assert "probe_title" not in updates["payload"]
    fake_gh.commit(repo, "work/later", name="later.txt")
    pushed = create(pack, ticket, "push-branch", "c", "p", {"repo": repo, "branch": "work/later"})
    after = create(pack, ticket, "push-branch", "c", "p", {"repo": repo, "branch": "work/after", "after": pushed["id"]})
    assert after["payload"]["remote_sha"] == pushed["payload"]["sha"]
    fix = create(
        pack, ticket, "pr-comment", "c", "x", {"repo": repo, "number": 1, "body": f"see {pushed['payload']['sha'][:9]}"}
    )
    assert fix["payload"]["after"] == pushed["id"]
    # Amend refuses what was refused at creation, and a pending review on the forge until it is discarded.
    posted = create(pack, ticket, "pr-review-submit", "c", "x", {"repo": repo, "number": 1, "sha": "a" * 40})
    posted["status"] = "posted"
    save(posted)
    with pytest.raises(CockpitError, match="discard it first"):
        amend(posted["id"], pack=pack)
    posted["status"] = "published"
    save(posted)
    with pytest.raises(CockpitError, match="only an open intent is amended"):
        amend(posted["id"], pack=pack)
    reply = create(
        pack,
        ticket,
        "pr-comment",
        "c",
        "x",
        {"repo": repo, "number": 1, "in_reply_to": 9, "thread": "T", "body": "x", "resolve": True},
    )
    flat = amend(reply["id"], payload={"body": "plain"}, pack=pack, top_level=True)
    assert not set(flat["payload"]) & {"in_reply_to", "thread", "resolve", "react"}
    with pytest.raises(CockpitError, match="pick one"):
        amend(
            create(pack, ticket, "pr-edit", "c", "x", {"repo": repo, "number": 1, "title": "t"})["id"],
            payload={"title_append": "b"},
            pack=pack,
        )
    returned = create(pack, ticket, "pr-edit", "c", "x", {"repo": repo, "number": 1, "title": "t"})
    returned["status"] = "returned"
    save(returned)
    assert "resolved" in amend(returned["id"], payload={"title": "u"}, pack=pack)["returned"]
    fake_gh.commit(repo, "work/shared", email=f"other@{pack['name']}.test")
    shared = create(pack, ticket, "push-branch", "c", "p", {"repo": repo, "branch": "work/shared"})
    assert amend(shared["id"], pack=pack)["status"] == "held"
    # Verify names what is missing or broken in the intent's own files.
    broken = create(pack, ticket, "tracker-comment", "c", "x", {"body": "x"})
    broken["payload"].update(attach=["gone.png"], rebase_only=True, content_changed=True)
    save(broken)
    assert {"missing gone.png", "rebase mixed with content"} <= set(verify(broken["id"], pack=pack))
    plan = env["workspace"] / "plan.json"
    plan.write_text(json.dumps([{"comment_id": 1, "type": "Code"}]), encoding="utf-8")
    apply = create(
        pack,
        ticket,
        "pr-patch-apply",
        "c",
        "x",
        {"repo": repo, "number": 1, "branch": "work/apply", "threads_file": str(plan)},
    )
    open(os.path.join(env["workspace"], apply["payload"]["threads_file"]), "w", encoding="utf-8").write("[]")
    assert any(item.startswith("manifest: ") for item in verify(apply["id"], pack=pack))
    stray = create(pack, ticket, "push-branch", "c", "p", {"repo": repo, "branch": "work/stray"})
    stray["payload"]["repo"] = "nowhere"
    save(stray)
    assert verify(stray["id"], pack=pack) == ["unknown repo nowhere"]
    hold(push["id"], "wait")
    # The tracker's own refusals and dry runs.
    jira.issue(ticket)
    tracker = trackers.tracker_for(pack)
    assert trackers.adf("one\n\ntwo")["content"][1]["content"][0]["text"] == "two"
    assert trackers.adf_text([{"text": "a"}, "b"]) == "a" and trackers.adf_count([{"type": "expand"}, 3], "expand") == 1
    with pytest.raises(CockpitError, match="has no issue type Epic"):
        tracker._meta(pack["tracker"]["project"], "Epic")
    monkeypatch.setattr(jira, "account", "")
    with pytest.raises(CockpitError, match="did not say who you are"):
        tracker._myself()
    original = jira.handle
    monkeypatch.setattr(
        jira,
        "handle",
        lambda method, path, body, raw: (
            (200, {"issues": []}) if "search" in path else original(method, path, body, raw)
        ),
    )
    with pytest.raises(CockpitError, match="no active sprint"):
        tracker._active_sprint(pack["tracker"]["project"], "customfield_200")
    monkeypatch.setattr(
        jira,
        "handle",
        lambda method, path, body, raw: (
            (200, {"fields": []}) if "issuetypes/" in path else original(method, path, body, raw)
        ),
    )
    with pytest.raises(CockpitError, match="has no sprint field"):
        tracker.create({"ticket": ticket, "payload": {"summary": "s", "sprint": "active"}}, {})
    monkeypatch.setattr(
        jira,
        "handle",
        lambda method, path, body, raw: (
            (201, {}) if method == "POST" and path.endswith("/issue") else original(method, path, body, raw)
        ),
    )
    with pytest.raises(CockpitError, match="made no issue key"):
        tracker.create({"ticket": ticket, "payload": {"summary": "s"}}, {})
    monkeypatch.setattr(
        jira,
        "handle",
        lambda method, path, body, raw: (
            (200, {"id": "other"}) if method == "GET" and "/comment/" in path else original(method, path, body, raw)
        ),
    )
    with pytest.raises(CockpitError, match="not readable after the post"):
        tracker.comment({"ticket": ticket, "payload": {"body": "x"}}, {})
    monkeypatch.setattr(jira, "handle", original)
    jira.issues[ticket]["comments"]["900"] = {"id": "900", "body": "old"}
    monkeypatch.setattr(
        jira,
        "handle",
        lambda method, path, body, raw: (
            (200, {"id": "901"})
            if method == "PUT" or path.endswith("/comment/901")
            else original(method, path, body, raw)
        ),
    )
    with pytest.raises(CockpitError, match="instead of updating 900"):
        tracker.comment({"ticket": ticket, "payload": {"body": "x", "comment_id": "900"}}, {})
    monkeypatch.setattr(
        jira,
        "handle",
        lambda method, path, body, raw: (
            (204, {}) if path.endswith("/transitions") and method == "POST" else original(method, path, body, raw)
        ),
    )
    with pytest.raises(CockpitError, match="read-back: .* is 'Backlog' after 'Start'"):
        tracker.transition({"payload": {"to": "In Progress"}}, {}, ticket)
    monkeypatch.setattr(
        jira,
        "handle",
        lambda method, path, body, raw: (204, {}) if path.endswith("/assignee") else original(method, path, body, raw),
    )
    with pytest.raises(CockpitError, match="is not assigned to"):
        tracker.transition({"payload": {"to": "In Progress", "assignee": "acct-x"}}, {}, ticket)
    monkeypatch.setattr(
        jira,
        "handle",
        lambda method, path, body, raw: (
            (200, "not an object") if path.endswith("/myself") else original(method, path, body, raw)
        ),
    )
    with pytest.raises(Exception):
        tracker._myself()
    monkeypatch.setattr(jira, "handle", original)
    dry = trackers.tracker_for(pack, dry_run=True)
    assert dry.comment({"ticket": ticket, "payload": {"body": "x"}}, {})[1].startswith("would be posted")
    assert dry._move(
        ticket, "In Review" if jira.issues[ticket]["status"] == "In Progress" else "In Progress"
    ).startswith("would move")
    two = env["workspace"] / pack["records_dir"] / "qa" / ticket / "b.png"
    two.parent.mkdir(parents=True, exist_ok=True)
    two.write_bytes(b"b")
    one = two.with_name("a.png")
    one.write_bytes(b"a")
    linked = tracker._link(
        {"content": [{"type": "text", "text": "a.png"}, {"type": "rule"}, "raw"]}, {"a.png": "1", "b.png": "2"}
    )
    assert [node.get("text") for node in linked["content"][-1]["content"]][1:4] == ["a.png", " · ", "b.png"]
    import socket

    closed = socket.socket()
    closed.bind(("127.0.0.1", 0))
    port = closed.getsockname()[1]
    closed.close()  # nothing listens there now: the connection is refused at once
    monkeypatch.setattr(
        trackers,
        "_config",
        lambda pack: {"kind": "jira", "url": f"http://127.0.0.1:{port}", "auth_env": pack["tracker"]["auth_env"]},
    )
    with pytest.raises(CockpitError, match="tracker GET"):
        trackers.tracker_for(pack).find_comment(ticket, "x")
    monkeypatch.setattr(trackers, "_config", lambda pack: {"kind": "jira", "url": jira.url})
    with pytest.raises(CockpitError, match="names the two environment variables"):
        trackers.tracker_for(pack).find_comment(ticket, "x")
    command = trackers.CommandTracker({"command": [str(env["root"] / "absent-tickets")]})
    with pytest.raises(CockpitError, match="tracker command: "):
        command._call("create", {"payload": {}})
    failing = env["root"] / "fails"
    failing.write_text("#!/bin/sh\necho 'down for now' >&2\nexit 4\n", encoding="utf-8")
    failing.chmod(0o755)
    with pytest.raises(CockpitError, match="down for now"):
        trackers.CommandTracker({"command": [str(failing)]})._call("create", {"payload": {}})
    assert trackers.CommandTracker({"command": [str(failing)]}, dry_run=True)._call("create", {"payload": {}}) == {
        "dry_run": True
    }
    moved = env["root"] / "moves"
    moved.write_text('#!/bin/sh\necho \'{"status": "Done"}\'\n', encoding="utf-8")
    moved.chmod(0o755)
    assert trackers.CommandTracker({"command": [str(moved)]}).transition({"payload": {}}, {}, ticket) == (
        "",
        "Done",
        {},
    )


@pytest.mark.parametrize("pack_file", PACKS)
def test_a_push_refuses_a_branch_or_remote_it_cannot_trust(env, pack_file, monkeypatch, capsys):
    import subprocess

    from cockpitlib.git_push import push, rebase_proof, remote_tip
    from cockpitlib.intents import check_payload
    from cockpitlib.outbox import create, endorse
    from cockpitlib.publish import execute
    from tests.support import fake_gh

    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    monkeypatch.delenv("COCKPIT_LANE", raising=False)
    pack = load(pack_file)
    first, second = (repo["name"] for repo in pack["repos"]["repos"][:2])
    ticket = f"{pack['tracker']['project']}-1114"
    with pytest.raises(CockpitError, match="unknown repo nowhere"):
        create(pack, ticket, "push-branch", "c", "p", {"repo": "nowhere", "branch": "x"})
    with pytest.raises(CockpitError, match="nothing to rebase"):
        create(pack, ticket, "push-branch", "c", "p", {"repo": first, "branch": "work/new", "rebase_only": True})
    branch = f"work/{ticket}"
    fake_gh.commit(first, branch)
    pushed = endorse(
        create(pack, ticket, "push-branch", "c", "p", {"repo": first, "branch": branch})["id"],
        "low",
        "",
        "gatekeeper",
        "fixture-a",
        "fixture-large",
    )
    assert execute(pushed, pack=pack)["ok"]
    with pytest.raises(CockpitError, match="the base did not move"):
        create(pack, ticket, "push-branch", "c", "p", {"repo": first, "branch": branch, "rebase_only": True})
    later = endorse(
        create(pack, ticket, "push-branch", "c", "p", {"repo": first, "branch": f"{branch}-b"})["id"],
        "low",
        "",
        "gatekeeper",
        "fixture-a",
        "fixture-large",
    )
    fake_gh.commit(first, f"{branch}-b", name="moved.txt")
    assert "not the intent's" in execute(later, pack=pack)["error"]
    rewritten = {
        "id": f"{ticket}/090-push-branch",
        "ticket": ticket,
        "payload": {
            "repo": first,
            "branch": branch,
            "sha": fake_gh.commit(first, f"{branch}-c", start="main", name="x.txt"),
        },
    }
    rewritten["payload"]["branch"] = f"{branch}-c"
    rewritten["payload"]["publish_as"] = branch
    with pytest.raises(CockpitError, match="has no lease"):
        push(pack, rewritten)
    source = env["root"] / "repos" / second
    subprocess.run(["git", "-C", str(source), "remote", "set-url", "origin", str(env["root"] / "gone.git")], check=True)
    with pytest.raises(CockpitError, match="git ls-remote origin"):
        remote_tip(str(source), "main")
    subprocess.run(["git", "-C", str(source), "remote", "remove", "origin"], check=True)
    with pytest.raises(CockpitError, match="has no origin remote"):
        push(
            pack,
            {
                "payload": {
                    "repo": second,
                    "branch": "main",
                    "sha": subprocess.check_output(["git", "-C", str(source), "rev-parse", "main"], text=True).strip(),
                    "base": "main",
                }
            },
        )
    with pytest.raises(CockpitError, match="nothing to rebase"):
        rebase_proof(str(source), {"sha": "x"})
    with pytest.raises(CockpitError, match="unknown type mystery"):
        check_payload("mystery", {})
    with pytest.raises(CockpitError, match="--event is one of"):
        check_payload("pr-review-submit", {"repo": first, "number": 1, "sha": "a", "event": "LOVE"})
    with pytest.raises(CockpitError, match="names an intent like"):
        check_payload("push-branch", {"repo": first, "branch": "b", "after": "yesterday"})
    assert (
        main(["outbox", "new", ticket, "push-branch", "--card"]) == 2
        and "--card needs a value" in capsys.readouterr().err
    )
    # A patch apply with nothing to push answers its threads only; a dry run of an edit to an open PR changes nothing.
    full = f"{pack['forge']['org']}/{first}"
    fake_gh.setup(me=pack["forge"]["human_login"], repos=[full])
    fake_gh.pull(full, 3, branch, fake_gh.remote(first, branch), draft=True)
    fake_gh.thread(full, 3, 5001, "someone")
    plan = env["workspace"] / "plan.json"
    plan.write_text(
        json.dumps([{"comment_id": 5001, "thread": "PRRT_5001", "type": "GitHub housekeeping"}]), encoding="utf-8"
    )
    apply = create(
        pack,
        ticket,
        "pr-patch-apply",
        "c",
        "a",
        {"repo": first, "number": 3, "branch": branch, "threads_file": str(plan)},
    )
    assert (
        "nothing to push"
        in open(os.path.join(env["workspace"], apply["payload"]["body_file"]), encoding="utf-8").read()
    )
    apply = endorse(apply["id"], "low", "", "gatekeeper", "fixture-a", "fixture-large")
    dry = execute(dict(apply), pack=pack, dry_run=True)
    assert dry["ok"] and dry["output"].startswith("push: nothing") and fake_gh.writes() == []
    assert execute(apply, pack=pack)["ok"]
    reopen = endorse(
        create(
            pack,
            f"{ticket}0",
            "open-pr",
            "c",
            "o",
            {"repo": first, "branch": branch, "title": "t", "body": "plain", "ready": True},
        )["id"],
        "low",
        "",
        "gatekeeper",
        "fixture-a",
        "fixture-large",
    )
    assert (
        execute(reopen, pack=pack, dry_run=True)["ok"] and fake_gh.state()["repos"][full]["pulls"]["3"]["draft"] is True
    )
    assert execute(reopen, pack=pack)["ok"] and fake_gh.state()["repos"][full]["pulls"]["3"]["draft"] is False
    from cockpitlib.publish import backfill_related, forge_for

    assert backfill_related(forge_for(pack), f"{ticket}0") == []
