# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Re-review, the PR watch and the outbox's options: re-review rules and its card, the PR watch (outdated threads,
PRs opened by hand), the notify events, the treat card, bumps, and the rework / hold options of the outbox. Both fixture packs; every
setting is optional and its default is what the kernel did before."""

import json
import os
import shutil
import sqlite3

import pytest
import yaml

from cockpitlib.errors import CockpitError
from cockpitlib.pack import load
from tests.support import words

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PACKS = (os.path.join(ROOT, "packs", "acme", "pack.yaml"), os.path.join(ROOT, "packs", "bravo", "pack.yaml"))


def _copy_pack(pack_file, tmp_path, change) -> str:
    copied = tmp_path / "packs" / os.path.basename(os.path.dirname(pack_file))
    shutil.copytree(os.path.dirname(pack_file), copied)
    data = yaml.safe_load((copied / "pack.yaml").read_text(encoding="utf-8"))
    change(data, copied)
    (copied / "pack.yaml").write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    return str(copied / "pack.yaml")


def _notified():
    path = os.path.join(os.environ["COCKPIT_ROOT"], "notified.log")
    return open(path, encoding="utf-8").read() if os.path.isfile(path) else ""


def _comments(board, card):
    from cockpitlib.kanban import db_path

    connection = sqlite3.connect(f"file:{db_path(board)}?mode=ro", uri=True)
    rows = [row[0] for row in connection.execute("select body from task_comments where task_id = ?", (card,))]
    connection.close()
    return rows


def _notify_all(data, _copied):
    for event in ("rereview", "ticket_done"):
        data["notify"][event] = data["notify"]["ready_for_review"]


def _reviewed_pr(pack_file, monkeypatch, tmp_path, change=None):
    """A PR of a colleague that the human reviewed (CHANGES_REQUESTED) with one thread; returns the pieces the tests share."""
    from tests.support import fake_gh

    path = _copy_pack(pack_file, tmp_path, change) if change else pack_file
    monkeypatch.setenv("COCKPIT_PACK", path)
    monkeypatch.delenv("COCKPIT_LANE", raising=False)
    pack = load(path)
    me = pack["forge"]["human_login"]
    repo = pack["repos"]["repos"][0]["name"]
    full = f"{pack['forge']['org']}/{repo}"
    ticket = f"{pack['tracker']['project']}-1601"
    fake_gh.setup(me=me, repos=[full])
    fake_gh.pull(full, 5, "their-branch", "b" * 40, author="colleague")
    fake_gh.review(full, 5, me, "CHANGES_REQUESTED", body="needs work", commit="b" * 40, at="2026-10-21T08:00:00Z")
    fake_gh.thread(full, 5, 6100, me, "guard this")
    from cockpitlib.outbox import create

    create(
        pack, ticket, "pr-review-submit", "c", "r", {"repo": repo, "number": 5, "sha": "b" * 40}
    )  # the review that put the PR under the ticket
    from cockpitlib import pr_watch

    now = pr_watch._stamp("2026-10-21T08:00:00Z")
    return pack, ticket, repo, full, now


def _resolve(full, number=5, outdated=False):
    from tests.support import fake_gh

    data = fake_gh.state()
    thread = data["repos"][full]["pulls"][str(number)]["threads"][0]
    thread["isResolved"] = not outdated
    thread["isOutdated"] = outdated
    fake_gh.save(data)


@pytest.mark.parametrize("pack_file", PACKS)
def test_a_rereview_waits_the_packs_quiet_time_and_its_card_carries_the_job(env, pack_file, monkeypatch, tmp_path):
    from cockpitlib import pr_watch
    from cockpitlib.kanban import board_cards

    pack, ticket, repo, full, now = _reviewed_pr(
        pack_file,
        monkeypatch,
        tmp_path,
        lambda data, _c: (data["hours"].update(rereview_quiet_minutes=10), _notify_all(data, _c)),
    )
    pr_watch.watch(pack, now=now + 60)
    _resolve(full)
    assert pr_watch.watch(pack, now=now + 300)["cards"] == []  # answered, quiet for 5 of the pack's 10 minutes
    made = pr_watch.watch(pack, now=now + 700)["cards"]
    assert len(made) == 1
    card = {row["id"]: row for row in board_cards(pack["board"], pack)}[made[0]]
    body = card["body"]
    assert "Re-review request" in body and f"{repo}#5" in body and "git diff bbbbbbbbb..bbbbbbbbb" in body
    assert "--review-id" in body and "For each of YOUR threads" in body and "1 resolved" in body
    assert "re-review started" in _notified() and "|rereview|" in _notified()


@pytest.mark.parametrize("pack_file", PACKS)
def test_the_humans_note_reaches_the_rereview_card(env, pack_file, monkeypatch, tmp_path):
    from cockpitlib import pr_watch
    from cockpitlib.kanban import board_cards

    pack, ticket, repo, full, now = _reviewed_pr(pack_file, monkeypatch, tmp_path)
    pr_watch.watch(pack, now=now + 60)
    asked = pr_watch.request_rereview(pack, ticket, repo, 5, note="look at the migration first")
    assert asked["ok"]
    body = {row["id"]: row for row in board_cards(pack["board"], pack)}[asked["card_id"]]["body"]
    assert "## The human's note" in body and "look at the migration first" in body


@pytest.mark.parametrize("pack_file", PACKS)
def test_a_rereview_starts_at_once_when_the_pack_says_so_and_stops_for_approved_halted_or_a_live_review(
    env, pack_file, monkeypatch, tmp_path
):
    from cockpitlib import halt, pr_watch
    from cockpitlib.outbox import create
    from tests.support import fake_gh

    pack, ticket, repo, full, now = _reviewed_pr(
        pack_file, monkeypatch, tmp_path, lambda data, _c: data["forge"].update(rereview_at_once=True)
    )
    pr_watch.watch(pack, now=now + 60)
    _resolve(full)
    halt.write(ticket, "stop")
    held = pr_watch.watch(pack, now=now + 70)
    assert (
        held["cards"] == [] and json.load(open(pr_watch.record_path(ticket, repo, 5)))["rereview_ready"] is False
    )  # halted
    halt.clear(ticket)
    data = fake_gh.state()
    data["repos"][full]["pulls"]["5"]["head"]["sha"] = "c" * 40
    fake_gh.save(data)
    live = create(pack, ticket, "pr-review-submit", "c", "r", {"repo": repo, "number": 5, "sha": "c" * 40})
    assert (
        pr_watch.watch(pack, now=now + 80)["cards"] == [] and live["id"]
    )  # a review for the new head is already at the gate
    live["status"] = "dropped"
    from cockpitlib.intents import save

    save(live)
    assert len(pr_watch.watch(pack, now=now + 90)["cards"]) == 1  # no quiet time: every thread is resolved
    data = fake_gh.state()
    data["repos"][full]["pulls"]["5"]["head"]["sha"] = "d" * 40
    fake_gh.save(data)
    fake_gh.review(
        full, 5, pack["forge"]["human_login"], "APPROVED", body="", commit="d" * 40, at="2026-10-22T08:00:00Z"
    )
    assert pr_watch.watch(pack, now=now + 100)["cards"] == []  # I approved it: nothing to re-review


@pytest.mark.parametrize("pack_file", PACKS)
def test_an_outdated_thread_is_no_open_question_when_the_pack_asks(env, pack_file, monkeypatch, tmp_path):
    from cockpitlib import pr_watch
    from tests.support import fake_gh

    pack, ticket, repo, full, _now = _reviewed_pr(
        pack_file, monkeypatch, tmp_path, lambda data, _c: data["forge"].update(skip_outdated=True)
    )
    me = pack["forge"]["human_login"]
    fake_gh.pull(full, 3, f"work/{ticket}", "a" * 40, title="mine")
    from cockpitlib.intents import save
    from cockpitlib.outbox import create

    opened = create(
        pack, ticket, "open-pr", "c", "o", {"repo": repo, "branch": f"work/{ticket}", "title": "mine", "body": "b"}
    )
    opened["status"] = "published"
    opened["payload"]["number"] = 3
    save(opened)
    pr_watch.watch(pack, now=1_800_000_000)
    fake_gh.thread(full, 3, 7100, "reviewer-x", "rename this", replies=())
    fake_gh.thread(full, 3, 7200, "reviewer-x", "and this one")
    data = fake_gh.state()
    data["repos"][full]["pulls"]["3"]["threads"][0]["isOutdated"] = True
    fake_gh.save(data)
    pr_watch.watch(pack, now=1_800_000_100)
    record = json.load(open(pr_watch.record_path(ticket, repo, 3)))
    assert [row["id"] for row in record["new"]] == ["inline:7200"]
    assert any(row["reason"].startswith("in an outdated thread") for row in record["skipped"])
    thread = [{"isResolved": False, "isOutdated": True, "comments": {"nodes": [{"databaseId": 1}]}}]
    assert (
        me
        and pr_watch.thread_marks(thread).outdated == set()
        and pr_watch.thread_marks(thread, True).outdated == {"inline:1"}
    )


@pytest.mark.parametrize("pack_file", PACKS)
def test_a_pr_the_human_opened_by_hand_on_a_pushed_branch_is_watched_when_the_pack_asks(
    env, pack_file, monkeypatch, tmp_path
):
    from cockpitlib import pr_watch
    from cockpitlib.intents import save
    from cockpitlib.outbox import create
    from tests.support import fake_gh

    path = _copy_pack(pack_file, tmp_path, lambda data, _c: data["forge"].update(discover_prs=True))
    monkeypatch.setenv("COCKPIT_PACK", path)
    monkeypatch.delenv("COCKPIT_LANE", raising=False)
    pack = load(path)
    repo = pack["repos"]["repos"][0]["name"]
    full = f"{pack['forge']['org']}/{repo}"
    ticket = f"{pack['tracker']['project']}-1602"
    fake_gh.setup(me=pack["forge"]["human_login"], repos=[full])
    fake_gh.pull(full, 21, f"work/{ticket}", "a" * 40, title="by hand")
    pushed = create(pack, ticket, "push-branch", "c", "p", {"repo": repo, "branch": f"work/{ticket}"})
    pushed["status"] = "published"
    save(pushed)
    from cockpitlib.forge import Forge

    forge = Forge(pack)
    assert pr_watch.discover(pack, forge) == [(ticket, repo, 21)]
    assert pr_watch.discover(pack, forge) == []  # a record exists: found once
    assert os.path.isfile(pr_watch.record_path(ticket, repo, 21))
    other = create(pack, ticket, "push-branch", "c", "q", {"repo": repo, "branch": "work/x"})
    other["status"] = "published"
    other["payload"]["branch"] = ""
    save(other)
    assert pr_watch.discover(pack, forge) == []  # a push with no branch is skipped
    plain = load(pack_file)
    assert pr_watch.discover(plain, forge) == []  # the setting is off by default
    monkeypatch.setattr(forge, "get", lambda _path: (_ for _ in ()).throw(CockpitError("forge down")))
    os.remove(pr_watch.record_path(ticket, repo, 21))
    assert pr_watch.discover(pack, forge) == []  # a forge that fails leaves the watch alone


@pytest.mark.parametrize("pack_file", PACKS)
def test_the_treat_card_names_each_comment_and_the_pack_can_leave_endorsements(env, pack_file, monkeypatch, tmp_path):
    from cockpitlib import pr_watch
    from cockpitlib.acts import treat_pr
    from cockpitlib.intents import load as load_intent
    from cockpitlib.kanban import board_cards
    from cockpitlib.outbox import create, endorse
    from tests.support import fake_gh

    path = _copy_pack(pack_file, tmp_path, lambda data, _c: data.setdefault("outbox", {}).update(amend_on_treat=False))
    monkeypatch.setenv("COCKPIT_PACK", path)
    monkeypatch.delenv("COCKPIT_LANE", raising=False)
    pack = load(path)
    me = pack["forge"]["human_login"]
    repo = pack["repos"]["repos"][0]["name"]
    full = f"{pack['forge']['org']}/{repo}"
    ticket = f"{pack['tracker']['project']}-1603"
    fake_gh.setup(me=me, repos=[full])
    fake_gh.pull(full, 3, f"work/{ticket}", "a" * 40, title="mine")
    opened = create(
        pack, ticket, "open-pr", "c", "o", {"repo": repo, "branch": f"work/{ticket}", "title": "mine", "body": "b"}
    )
    opened["status"] = "published"
    opened["payload"]["number"] = 3
    from cockpitlib.intents import save

    save(opened)
    edit = endorse(
        create(pack, ticket, "pr-edit", "c", "e", {"repo": repo, "number": 3, "add_labels": ["y"]})["id"],
        "low",
        "",
        "gatekeeper",
        "fixture-a",
        "fixture-large",
    )
    pr_watch.watch(pack, now=1_800_000_000)
    fake_gh.comment(
        full, 3, "reviewer-x", f"please rename this, {pack['name']}", at="2026-10-21T09:00:00Z", inline=True
    )
    pr_watch.watch(pack, now=1_800_000_100)
    treated = treat_pr(pack, ticket, repo, 3)
    assert load_intent(edit["id"])["status"] == "endorsed" and treated["amended"] == [edit["id"]]
    card = {row["id"]: row for row in board_cards(pack["board"], pack)}[treated["card_id"]]
    assert "### reviewer-x" in card["body"] and "id " in card["body"]
    assert (
        "Open intents of this PR (amend one when your change touches it; an untouched one keeps its endorsement): "
        + edit["id"]
        in card["body"]
    )


def _runner(payload):
    class Done:
        returncode, stdout, stderr = 0, json.dumps(payload), ""

    return lambda _argv, **_kw: Done()


@pytest.mark.parametrize("pack_file", PACKS)
def test_bumps_can_be_limited_to_the_repos_that_ship(env, pack_file, monkeypatch, tmp_path):
    from cockpitlib.acts import scan_bumps, visible_bumps

    def change(data, copied):
        data["forge"]["bumps_shipped_only"] = True
        repos = yaml.safe_load((copied / "repos.yaml").read_text(encoding="utf-8"))
        repos["repos"][0]["shipped"] = False
        (copied / "repos.yaml").write_text(yaml.safe_dump(repos, sort_keys=False), encoding="utf-8")

    path = _copy_pack(pack_file, tmp_path, change)
    monkeypatch.setenv("COCKPIT_PACK", path)
    pack = load(path)
    bump = [
        {
            "number": 4,
            "title": "bump",
            "headRefName": "dependabot/npm",
            "headRefOid": "aaa",
            "baseRefName": "main",
            "author": {"login": "dependabot[bot]"},
            "files": [{"path": "a.py"}],
        }
    ]
    scan_bumps(pack, runner=_runner(bump))
    shown = visible_bumps()["repos"]
    assert pack["repos"]["repos"][0]["name"] not in shown
    scan_bumps(load(pack_file), runner=_runner(bump))
    assert load(pack_file)["repos"]["repos"][0]["name"] in visible_bumps()["repos"]


@pytest.mark.parametrize("pack_file", PACKS)
def test_a_bump_batch_pushes_only_to_the_prefix_the_pack_names(env, pack_file, monkeypatch, tmp_path):
    from cockpitlib.outbox import _bump_push_problems

    path = _copy_pack(pack_file, tmp_path, lambda data, _c: data["forge"].update(bump_push_prefix="dependabot/"))
    monkeypatch.setenv("COCKPIT_PACK", path)
    pack = load(path)
    from cockpitlib.kickoff import batch_key

    intent = {"ticket": batch_key(pack), "payload": {"publish_as": "work/mine"}}
    assert _bump_push_problems(pack, intent) == ["a bump pushes only to a `dependabot/` branch, not to work/mine"]
    assert _bump_push_problems(pack, {**intent, "payload": {"branch": "dependabot/npm/x"}}) == []
    assert _bump_push_problems(pack, {"ticket": "OTHER-1", "payload": {"branch": "work/x"}}) == []
    assert _bump_push_problems(load(pack_file), intent) == []  # off by default


@pytest.mark.parametrize("pack_file", PACKS)
def test_the_new_pack_settings_are_checked(env, pack_file, tmp_path):
    count = []

    def bad(change):
        count.append(1)
        with pytest.raises(Exception) as caught:
            load(_copy_pack(pack_file, tmp_path / str(len(count)), change))
        return str(caught.value)

    assert "forge.discover_prs is true or false" in bad(lambda data, _c: data["forge"].update(discover_prs="yes"))
    assert "forge.bump_push_prefix" in bad(lambda data, _c: data["forge"].update(bump_push_prefix=""))
    assert "outbox.ci_rework_chain is true or false" in bad(
        lambda data, _c: data.update(outbox={"ci_rework_chain": "no"})
    )
    assert "outbox.comment_card is true or false" in bad(lambda data, _c: data.update(outbox={"comment_card": 1}))
    assert "outbox.missing_skill is hold" in bad(lambda data, _c: data.update(outbox={"missing_skill": "ignore"}))
    assert "outbox.amend_on_treat is true or false" in bad(lambda data, _c: data.update(outbox={"amend_on_treat": "x"}))
    assert "outbox takes auto" in bad(lambda data, _c: data.update(outbox={"nope": 1}))


@pytest.mark.parametrize("pack_file", PACKS)
def test_a_ci_rework_can_skip_the_tester_and_reviewer_and_a_send_back_comments_the_card(
    env, pack_file, monkeypatch, tmp_path
):
    from cockpitlib.acts import continue_ticket, note_card
    from cockpitlib.gate import return_intent
    from cockpitlib.outbox import create, hold

    path = _copy_pack(
        pack_file, tmp_path, lambda data, _c: data.update(outbox={"ci_rework_chain": False, "comment_card": True})
    )
    monkeypatch.setenv("COCKPIT_PACK", path)
    monkeypatch.delenv("COCKPIT_LANE", raising=False)
    pack = load(path)
    ticket = f"{pack['tracker']['project']}-1604"
    repo = pack["repos"]["repos"][0]["name"]
    made = continue_ticket(pack, ticket, "CI failed at abc: fix it", kind="rework", repos=[repo], chain=False)
    assert made["cards"][0]["chain"] == []
    default = continue_ticket(pack, f"{pack['tracker']['project']}-1605", "CI failed", kind="rework", repos=[repo])
    assert len(default["cards"][0]["chain"]) == 2  # the default keeps its tester and reviewer
    intent = create(pack, ticket, "ticket-done", "worker-1", "done", {})
    intent["card_id"] = made["card_id"]
    from cockpitlib.intents import save

    save(intent)
    hold(intent["id"], "the summary is thin", pack=pack)
    assert any(
        "is held" in line and "the summary is thin" in line for line in _comments(pack["board"], made["card_id"])
    )
    returned = return_intent(pack, intent["id"], "write more", assignee="worker-1")
    assert returned["status"] == "returned"
    assert any(
        "was sent back to worker-1" in line and "write more" in line
        for line in _comments(pack["board"], made["card_id"])
    )
    assert note_card(pack, "", "cockpit", "x") is False and note_card(pack, "t_none", "cockpit", "x") is False


@pytest.mark.parametrize("pack_file", PACKS)
def test_a_missing_skill_sends_the_draft_back_when_the_pack_says_rework(env, pack_file, monkeypatch, tmp_path):
    from cockpitlib import outbox

    path = _copy_pack(pack_file, tmp_path, lambda data, _c: data.update(outbox={"missing_skill": "rework"}))
    monkeypatch.setenv("COCKPIT_PACK", path)
    monkeypatch.delenv("COCKPIT_LANE", raising=False)
    pack = load(path)
    ticket = f"{pack['tracker']['project']}-1606"
    kind = next(iter(pack["skills"]["intent"]))
    intent = outbox.create(pack, ticket, "ticket-done", "worker-1", "x", {})
    intent["type"] = kind
    monkeypatch.setattr("cockpitlib.skill_log.missing", lambda _p, _i: ["pr-review"])
    monkeypatch.setattr("cockpitlib.skill_log.still_running", lambda _p, _i: False)
    seen = {}
    monkeypatch.setattr(
        outbox, "hold", lambda iid, reason, **kw: seen.update(reason=reason, **kw) or {"status": "returned"}
    )
    assert outbox._maybe_hold_skills(pack, intent)["status"] == "returned"
    assert (
        seen["reason"] == "missing skill: pr-review"
        and seen["rework"].startswith("Load pr-review first")
        and seen["chain"] is False
    )
    assert seen["skills"] == ["pr-review"]  # the returned card carries the skill, so the redone draft is not held again
    plain = load(pack_file)
    seen.clear()
    outbox._maybe_hold_skills(plain, intent)
    assert "rework" not in seen and seen["waits"] == "lane"


@pytest.mark.parametrize("pack_file", PACKS)
def test_the_digest_prints_its_rows(env, pack_file, monkeypatch, capsys):
    from cockpitlib.cli import cmd_digest

    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    assert cmd_digest([]) == 0
    printed = capsys.readouterr().out
    assert "# Digest" in printed and "Pending outbox:" in printed
    assert "Blocked:" in printed


@pytest.mark.parametrize("pack_file", PACKS)
def test_a_ticket_done_row_announces_itself_when_the_pack_has_the_event(env, pack_file, monkeypatch, tmp_path):
    from cockpitlib import pr_watch
    from cockpitlib.intents import save
    from cockpitlib.outbox import create
    from tests.support import fake_gh

    path = _copy_pack(pack_file, tmp_path, _notify_all)
    monkeypatch.setenv("COCKPIT_PACK", path)
    monkeypatch.delenv("COCKPIT_LANE", raising=False)
    pack = load(path)
    repo = pack["repos"]["repos"][0]["name"]
    full = f"{pack['forge']['org']}/{repo}"
    ticket = f"{pack['tracker']['project']}-1607"
    fake_gh.setup(me=pack["forge"]["human_login"], repos=[full])
    fake_gh.pull(full, 3, f"work/{ticket}", "a" * 40, title="mine")
    opened = create(
        pack, ticket, "open-pr", "c", "o", {"repo": repo, "branch": f"work/{ticket}", "title": "mine", "body": "b"}
    )
    opened["status"] = "published"
    opened["payload"]["number"] = 3
    save(opened)
    pr_watch.watch(pack, now=1_800_000_000)
    data = fake_gh.state()
    data["repos"][full]["pulls"]["3"].update(merged=True, state="closed")
    fake_gh.save(data)
    assert len(pr_watch.watch(pack, now=1_800_000_100)["done"]) == 1
    assert "|ticket_done|" in _notified()


def _skills_change(path_part, change):
    """A change function that also edits the copied pack's skills.yaml."""

    def apply(data, copied):
        skills = yaml.safe_load((copied / "skills.yaml").read_text(encoding="utf-8"))
        change(skills)
        (copied / "skills.yaml").write_text(yaml.safe_dump(skills, sort_keys=False), encoding="utf-8")

    return apply


@pytest.mark.parametrize("pack_file", PACKS)
def test_an_in_progress_init_may_post_before_the_rows_are_done(env, pack_file, monkeypatch):
    from cockpitlib.test_flow import post_problems

    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    pack = load(pack_file)
    monkeypatch.setattr("cockpitlib.outbox._body_text", lambda payload: payload.get("body") or "")
    intent = {
        "type": "tracker-comment",
        "ticket": f"{pack['tracker']['project']}-1610",
        "payload": {"body": words.worded(pack, "## Test Run\n\nIn progress")},
    }
    assert post_problems(pack, intent) == []  # no rows yet: the init leaves
    final = {**intent, "payload": {"body": words.worded(pack, "## Test Run\n\nTested and Ok")}}
    assert post_problems(pack, final) == [
        "the ticket has no test results to post"
    ]  # a final banner is still held to its rows


@pytest.mark.parametrize("pack_file", PACKS)
def test_an_ack_stays_with_the_human_and_a_reopened_ticket_gets_a_second_done_row(
    env, pack_file, monkeypatch, tmp_path
):
    from cockpitlib import pr_watch
    from cockpitlib.cli import main
    from cockpitlib.intents import all_intents
    from cockpitlib.paths import qa

    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    pack = load(pack_file)
    repo = pack["repos"]["repos"][0]["name"]
    ticket = f"{pack['tracker']['project']}-1611"
    folder = os.path.join(qa(), ticket, "pr")
    os.makedirs(folder)

    def merged(number):
        json.dump(
            {"ticket": ticket, "repo": repo, "number": number, "role": "author", "merged": True, "state": "closed"},
            open(os.path.join(folder, f"{repo}-{number}.json"), "w"),
        )

    merged(3)
    first = pr_watch._ticket_done(pack, ticket)
    assert first and pr_watch._ticket_done(pack, ticket) == ""  # one row per merged set
    row = [item for item in all_intents(ticket) if item["type"] == "ticket-done"][0]
    assert row["payload"]["numbers"] == ["3"]
    monkeypatch.setenv("COCKPIT_LANE", "worker-1")
    assert main(["outbox", "ack", first]) == 1  # a lane does not ack
    monkeypatch.delenv("COCKPIT_LANE")
    assert main(["outbox", "ack", first]) == 0
    assert pr_watch._ticket_done(pack, ticket) == ""  # acknowledged, nothing new merged
    merged(8)  # reopened: a second PR merges
    second = pr_watch._ticket_done(pack, ticket)
    assert (
        second and second != first and len([item for item in all_intents(ticket) if item["type"] == "ticket-done"]) == 2
    )


@pytest.mark.parametrize("pack_file", PACKS)
def test_a_breakdown_row_can_come_after_another_and_waits_for_its_last_card(env, pack_file, monkeypatch):
    from cockpitlib.decompose import check, decompose
    from cockpitlib.kanban import place_card
    from cockpitlib.plan import init
    from tests.support.both_packs import _parents

    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    pack = load(pack_file)
    repos = [repo["name"] for repo in pack["repos"]["repos"]][:2]
    ticket = f"{pack['tracker']['project']}-1612"
    init(ticket, "plan", "go")
    for rows, message in (
        ([{"repo": repos[0], "after": "moon"}], "comes after moon"),
        ([{"repo": repos[0], "after": repos[0]}], "comes after"),
        ([{"repo": repos[0], "after": repos[1]}, {"repo": repos[1], "after": repos[0]}], "in a loop"),
    ):
        with pytest.raises(CockpitError, match=message):
            check(pack, ticket, {"repos": rows})
    intake = place_card(pack["board"], f"{ticket}: intake", "intake", "ready")
    monkeypatch.setenv("HERMES_KANBAN_TASK", intake)
    made = decompose(pack, ticket, {"repos": [{"repo": repos[0], "after": repos[1]}, {"repo": repos[1]}]})["cards"]
    monkeypatch.delenv("HERMES_KANBAN_TASK")
    backend = [row for row in made if row["repo"] == repos[1]]
    frontend = [row for row in made if row["repo"] == repos[0]]
    assert made[0]["repo"] == repos[1]  # the repo it waits for is made first
    assert _parents(pack, frontend[0]["card"]) == [backend[-1]["card"]]  # behind the backend's last card
    assert _parents(pack, backend[0]["card"]) == [intake]


@pytest.mark.parametrize("pack_file", PACKS)
def test_the_scans_retry_after_the_packs_delay_and_a_staging_run_warms_no_slot(env, pack_file, monkeypatch, tmp_path):
    from cockpitlib import ops
    from cockpitlib.housekeeping import slot_assign, warm_waiting
    from tests.support.boards import put_card

    path = _copy_pack(pack_file, tmp_path, lambda data, _c: data["hours"].update(retry_seconds=7))
    monkeypatch.setenv("COCKPIT_PACK", path)
    pack = load(path)
    slept = []
    monkeypatch.setattr("time.sleep", lambda seconds: slept.append(seconds))
    answers = iter(["forge timeout", "base-watch 0"])
    assert ops._once(lambda: next(answers), pack) == "base-watch 0" and slept == [7.0]
    slept.clear()
    answers = iter(["forge timeout", "ok"])
    assert ops._once(lambda: next(answers)) == "ok" and slept == [0.0]  # no setting: at once, as before
    with pytest.raises(CockpitError, match="retry_seconds"):
        load(_copy_pack(pack_file, tmp_path / "bad", lambda data, _c: data["hours"].update(retry_seconds=0)))
    ticket = f"{pack['tracker']['project']}-1613"
    staging = put_card(pack["board"], f"{ticket}: test on staging", "tester-1", "ready")
    local = put_card(pack["board"], f"{pack['tracker']['project']}-1614: test on local", "tester-2", "ready")
    monkeypatch.setattr("cockpitlib.housekeeping.data_ready", lambda *_a, **_k: "ready")
    monkeypatch.setattr("cockpitlib.housekeeping._unbound", lambda _n: [1])
    warmed = []
    monkeypatch.setattr("cockpitlib.housekeeping.warm_slot", lambda slot, tkt, owner, _p: warmed.append(tkt))
    monkeypatch.setattr("cockpitlib.housekeeping.claim", lambda _s: None)
    warm_waiting(pack)
    assert warmed == [f"{pack['tracker']['project']}-1614"]  # the local run gets the slot, the staging run none
    slot_assign(pack)
    from tests.test_slots_plan_gate_and_privileged_lend import _comments

    assert _comments(pack["board"], staging) == [] and _comments(pack["board"], local)


@pytest.mark.parametrize("pack_file", PACKS)
def test_a_base_watch_analyst_card_carries_the_packs_text_and_a_lane_records_its_verdict(
    env, pack_file, monkeypatch, tmp_path, capsys
):
    from cockpitlib.acts import changes_dir, open_analyst
    from cockpitlib.cli import main
    from cockpitlib.kanban import board_cards

    def change(skills):
        skills.setdefault("cards", {})["analyst"] = {
            "base": "Explain {change} ({repo}) on {ticket}: verdict with `watch-base verdict`, id {id}, sha {sha}."
        }

    path = _copy_pack(pack_file, tmp_path, _skills_change("skills.yaml", change))
    monkeypatch.setenv("COCKPIT_PACK", path)
    pack = load(path)
    repo = pack["repos"]["repos"][0]["name"]
    ticket = f"{pack['tracker']['project']}-PLATFORM"
    card = open_analyst(pack, "base", ticket, repos=[repo], change=f"{repo}#7")
    body = {row["id"]: row for row in board_cards(pack["board"], pack)}[card]["body"]
    assert f"Explain {repo}#7 ({repo}) on {ticket}" in body and f"id {repo}#7" in body
    assert open_analyst(pack, "base", ticket, repos=[repo], change=f"{repo}#8", body="own text") and open_analyst(
        load(pack_file), "base", ticket, repos=[repo], change=f"{repo}#9"
    )
    for bad in ({"base": ""}, {"base": "{nope}"}, ["x"]):
        with pytest.raises(CockpitError, match="cards.analyst"):
            load(
                _copy_pack(
                    pack_file,
                    tmp_path / str(len(str(bad))) / str(abs(hash(str(bad)))),
                    _skills_change(
                        "skills.yaml", lambda skills, bad=bad: skills.setdefault("cards", {}).update(analyst=bad)
                    ),
                )
            )
    # the verdict: a change that exists takes it, from words or from a file
    os.makedirs(changes_dir(), exist_ok=True)
    json.dump(
        {"repo": repo, "number": 7, "status": "relevant"}, open(os.path.join(changes_dir(), f"{repo}-7.json"), "w")
    )
    assert main(["watch-base", "verdict", repo, "7", "two", "sentences", "for", "whom"]) == 0
    assert json.load(open(os.path.join(changes_dir(), f"{repo}-7.json")))["verdict"] == "two sentences for whom"
    note = tmp_path / "verdict.txt"
    note.write_text("from a file\n")
    assert main(["watch-base", "verdict", repo, "7", "--file", str(note)]) == 0
    assert json.load(open(os.path.join(changes_dir(), f"{repo}-7.json")))["verdict"] == "from a file"
    capsys.readouterr()
    assert main(["watch-base", "verdict", repo]) == 2 and main(["watch-base", "verdict", repo, "x", "y"]) == 2
    assert (
        main(["watch-base", "verdict", repo, "7", "--file"]) == 2
        and main(["watch-base", "verdict", repo, "7", "--file", str(tmp_path / "none")]) == 2
    )
    assert main(["watch-base", "stray"]) == 2


@pytest.mark.parametrize("pack_file", PACKS)
def test_the_accounts_manifest_can_ask_its_command_to_verify_each_account(env, pack_file, monkeypatch, tmp_path):
    from cockpitlib import accounts

    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    pack = load(pack_file)
    seen = []
    monkeypatch.setattr(
        accounts,
        "rows",
        lambda _p, now=None: [
            {
                "stored": True,
                "identifier": "a@x.test",
                "expected": ["tester-1"],
                "seats": ["tester-1"],
                "origin": "https://x",
            },
            {"stored": True, "identifier": "b@x.test", "expected": ["tester-1"], "seats": [], "origin": "https://x"},
        ],
    )

    def asked(_pack, action, row):
        seen.append((action, row["identifier"]))
        raise CockpitError(f"accounts verify {row['identifier']} failed: exit 1 login refused")

    monkeypatch.setattr(accounts, "_run_command", asked)
    monkeypatch.setattr(accounts, "manifest", lambda _p: {"command": ["x"], "accounts": [], "verify_command": False})
    assert accounts.verify(pack) == ["missing on tester-1: b@x.test"] and seen == []  # off by default: placement only
    monkeypatch.setattr(accounts, "manifest", lambda _p: {"command": ["x"], "accounts": [], "verify_command": True})
    assert accounts.verify(pack) == [
        "accounts verify a@x.test failed: exit 1 login refused",
        "missing on tester-1: b@x.test",
    ]
    assert seen == [("verify", "a@x.test")]  # a misplaced account is not logged in
    monkeypatch.undo()
    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    bad = tmp_path / "accounts.yaml"
    bad.write_text("command: [x]\nverify_command: sometimes\naccounts: []\n")
    with pytest.raises(Exception, match="verify_command is true or false"):
        accounts.manifest({"logins": {"accounts": str(bad)}, "_dir": str(tmp_path)})


def _client():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from dashboard.cockpit.router import router

    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


@pytest.mark.parametrize("pack_file", PACKS)
def test_a_session_checks_out_the_named_repos_and_close_follows_the_packs_rules(env, pack_file, monkeypatch, tmp_path):
    from cockpitlib import acts
    from cockpitlib.acts import session_close, session_open
    from cockpitlib.slots import read_owner, read_ticket, write_owner, write_ticket

    path = _copy_pack(
        pack_file,
        tmp_path,
        lambda data, _c: data.update(
            slots={**(data.get("slots") or {}), "close": {"human_only": True, "keep_stack": True}}
        ),
    )
    monkeypatch.setenv("COCKPIT_PACK", path)
    pack = load(path)
    repos = [repo["name"] for repo in pack["repos"]["repos"]]
    ticket = f"{pack['tracker']['project']}-1620"
    with pytest.raises(CockpitError, match="not a repo of this pack"):
        session_open(pack, 1, ticket, ["moon"])
    added = []
    monkeypatch.setattr("cockpitlib.ops.worktree_add", lambda _p, tkt, name="": added.append((tkt, name)) or [])
    assert session_open(pack, 1, ticket, [repos[0]]) == f"session {ticket}" and (ticket, repos[0]) in added
    downs = []
    monkeypatch.setattr(
        acts, "_provider", lambda _p: type("P", (), {"down": lambda self, number: downs.append(number)})()
    )
    write_owner(1, "lane:worker-1")
    with pytest.raises(CockpitError, match="not a manual session"):
        session_close(pack, 1)
    assert read_owner(1) == "lane:worker-1"  # refused before anything was touched
    write_owner(1, "human")
    write_ticket(1, ticket)
    assert (
        session_close(pack, 1).startswith("closed 1")
        and downs == []
        and read_owner(1) == "free"
        and read_ticket(1) == ""
    )
    plain = load(pack_file)  # default: the stack goes down
    write_owner(1, "human")
    session_close(plain, 1)
    assert downs == [1]
    for wrong in ({"human_only": "yes"}, {"other": True}, ["x"]):
        with pytest.raises(CockpitError, match="slots.close takes"):
            load(
                _copy_pack(
                    pack_file,
                    tmp_path / str(abs(hash(str(wrong)))),
                    lambda data, _c: data.update(slots={**(data.get("slots") or {}), "close": wrong}),
                )
            )
    with pytest.raises(CockpitError, match="start_repo"):
        load(
            _copy_pack(
                pack_file,
                tmp_path / "start",
                lambda data, _c: data.update(slots={**(data.get("slots") or {}), "start_repo": "go"}),
            )
        )


@pytest.mark.parametrize("pack_file", PACKS)
def test_a_chat_starts_where_the_pack_says_with_the_packs_environment(env, pack_file, monkeypatch, tmp_path):
    from cockpitlib import chat
    from cockpitlib.paths import wt

    path = _copy_pack(
        pack_file,
        tmp_path,
        lambda data, _c: data.setdefault("providers", {}).update(
            chat={"command": ["true"], "cwd": "{wt}/{ticket}", "env": {"PATH": "/pack/bin:{PATH}", "WHERE": "{ticket}"}}
        ),
    )
    monkeypatch.setenv("COCKPIT_PACK", path)
    pack = load(path)
    ticket = f"{pack['tracker']['project']}-1621"
    assert chat.chat_cwd(ticket) != os.path.join(wt(), ticket)  # no such folder yet: the old rules
    os.makedirs(os.path.join(wt(), ticket))
    assert chat.chat_cwd(ticket) == os.path.join(wt(), ticket) and chat.chat_cwd("own")
    env_of = chat.chat_env(ticket)
    assert (
        env_of["WHERE"] == ticket
        and env_of["PATH"].startswith("/pack/bin:")
        and env_of["PATH"].endswith(os.environ["PATH"])
    )
    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    assert chat.chat_env(ticket) == {}  # the default is no extra environment
    for bad, message in (
        ({"command": ["true"], "cwd": ""}, "providers.chat.cwd"),
        ({"command": ["true"], "env": {"A": 1}}, "providers.chat.env"),
        ({"command": ["true"], "env": ["x"]}, "providers.chat.env"),
    ):
        with pytest.raises(CockpitError, match=message):
            load(
                _copy_pack(
                    pack_file,
                    tmp_path / str(abs(hash(str(bad)))),
                    lambda data, _c, bad=bad: data.setdefault("providers", {}).update(chat=bad),
                )
            )
    from cockpitlib.chat import Term

    term = Term(["sh", "-c", "echo $WHERE; sleep 0.2"], os.path.join(wt(), ticket), 80, 24, env=env_of)
    import time

    time.sleep(0.5)
    assert ticket in term.read(0)[0].decode()
    term.kill()


@pytest.mark.parametrize("pack_file", PACKS)
def test_the_demo_card_defaults_to_the_slot_environment_and_finds_a_portal_logins_secret(
    env, pack_file, monkeypatch, tmp_path
):
    from cockpitlib.paths import qa

    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    pack = load(pack_file)
    ticket = f"{pack['tracker']['project']}-1622"
    os.makedirs(os.path.join(qa(), ticket))
    json.dump({"slot": 2, "account": "customer@x.test"}, open(os.path.join(qa(), ticket, "demo.json"), "w"))
    monkeypatch.setattr(
        "dashboard.cockpit.routes.pages._staging",
        lambda _p: {"origins": {"app": "https://app.x.test", "portal": "https://dp.x.test"}},
    )
    asked = []

    def secret(origin, account, _pack=None):
        asked.append(origin)
        return "portal-secret" if origin == "https://dp.x.test" else ""

    monkeypatch.setattr("cockpitlib.vault.human_secret", secret)
    shown = _client().get(f"/demo?ticket={ticket}").json()
    slot_env = next(item["name"] for item in pack["environments"] if item.get("slot"))
    assert (
        shown["env"] == slot_env and shown["login"]["password"] == "portal-secret"
    )  # the slot's own environment; the portal's login
    assert asked == ["https://app.x.test", "https://dp.x.test"]  # the app first, then the others
    json.dump({"account": "customer@x.test"}, open(os.path.join(qa(), ticket, "demo.json"), "w"))
    assert _client().get(f"/demo?ticket={ticket}").json()["env"] == "staging"  # no slot named: a staging demo
    monkeypatch.setattr("cockpitlib.vault.human_secret", lambda origin, account, _pack=None: "")
    monkeypatch.setattr("cockpitlib.vault._items", lambda: [])
    monkeypatch.setattr(
        "dashboard.cockpit.routes.pages._staging",
        lambda _p: {"origins": {"app": "https://app.x.test", "portal": "https://dp.x.test"}},
    )
    monkeypatch.setattr(
        "cockpitlib.slots.CommandProvider.login",
        lambda self, tkt, user: {"user": user, "password": "from-the-pack"},
        raising=False,
    )
    sent = _client().post("/demo-login", json={"ticket": ticket, "user": "customer@x.test", "slot": 2})
    assert sent.status_code in (200, 409)


@pytest.mark.parametrize("pack_file", PACKS)
def test_a_demo_start_runs_the_packs_command_for_the_one_app_it_names(env, pack_file, monkeypatch, tmp_path):
    path = _copy_pack(
        pack_file,
        tmp_path,
        lambda data, _c: data.setdefault("slots", {}).update(start_repo=["true", "{slot}", "{ticket}", "{repo}"]),
    )
    monkeypatch.setenv("COCKPIT_PACK", path)
    pack = load(path)
    ticket = f"{pack['tracker']['project']}-1623"
    repo = pack["repos"]["repos"][0]["name"]
    calls = []

    def run(self, verb, slot, ticket="", args=(), words=None, repo=""):
        calls.append((verb, int(slot), ticket, list(words), repo))
        return {"verb": verb, "slot": int(slot), "code": 0, "state": "ok", "out": "up", "tail": ""}

    monkeypatch.setattr("cockpitlib.slots.CommandProvider.run", run)
    done = _client().post("/demo-start", json={"ticket": ticket, "repo": repo, "slot": 1}).json()
    assert (
        done["ok"]
        and done["runtime"] == "up"
        and calls == [("start-repo", 1, ticket, ["true", "{slot}", "{ticket}", "{repo}"], repo)]
    )

    def broken(self, verb, slot, ticket="", args=(), words=None, repo=""):
        return {"verb": verb, "slot": int(slot), "code": 1, "state": "failed", "out": "", "tail": "no such app"}

    monkeypatch.setattr("cockpitlib.slots.CommandProvider.run", broken)
    refused = _client().post("/demo-start", json={"ticket": ticket, "repo": repo, "slot": 1})
    assert refused.status_code == 409 and "no such app" in refused.text


@pytest.mark.parametrize("pack_file", PACKS)
def test_a_reply_whose_draft_changed_after_it_went_is_sent_again(env, pack_file, monkeypatch):
    from cockpitlib import publish
    from tests.support.both_packs import _LyingForge, _thread_nodes

    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    pack = load(pack_file)
    repo = pack["repos"]["repos"][0]["name"]
    sent = {"Kreply": {"time": "t", "value": "u", "body": publish._digest("first words")}}
    nodes = [_thread_nodes(mine=True)]
    forge = _LyingForge(pack, threads=nodes)
    same = publish._thread(
        forge,
        {"id": "T-1/001-pr-comment", "receipt_steps": dict(sent)},
        repo,
        1,
        1,
        "",
        "first words",
        False,
        False,
        "K",
        True,
    )[1]
    assert "reply already sent" in same and forge.writes == []  # the same text: once
    forge = _LyingForge(pack, threads=nodes)
    revised = publish._thread(
        forge,
        {"id": "T-1/001-pr-comment", "receipt_steps": dict(sent)},
        repo,
        1,
        1,
        "",
        "better words",
        False,
        False,
        "K",
        True,
    )[1]
    assert "replied again with the revised text" in revised and [write[0] for write in forge.writes] == ["POST"]
    old = {"Kreply": {"time": "t", "value": "u"}}  # a receipt from before the hash: kept as it was
    forge = _LyingForge(pack, threads=nodes)
    assert (
        "reply already sent"
        in publish._thread(
            forge, {"id": "T-1/001-pr-comment", "receipt_steps": old}, repo, 1, 1, "", "any", False, False, "K", True
        )[1]
    )
    intent = {"id": "T-1/002-pr-comment", "receipt_steps": {}}
    forge = _LyingForge(pack, threads=nodes)
    assert "you already replied" in publish._thread(forge, intent, repo, 1, 1, "", "x", False, False, "K", True)[1]
    kept = {"id": "T-1/003-pr-comment", "receipt_steps": {}, "payload": {}}
    monkeypatch.setattr(publish, "save", lambda _intent: None)
    publish._keep(kept, "Kreply", "u", False, body="words")
    assert kept["receipt_steps"]["Kreply"]["body"] == publish._digest("words")
    publish._keep(kept, "Kother", "v", False)
    assert "body" not in kept["receipt_steps"]["Kother"]


@pytest.mark.parametrize("pack_file", PACKS)
def test_a_close_can_leave_the_tester_runs_and_a_handoff_runs_the_packs_hook(env, pack_file, monkeypatch, tmp_path):
    from cockpitlib import acts
    from cockpitlib.acts import session_close, session_handoff
    from cockpitlib.slots import read_owner, state_dir, write_owner, write_ticket

    marker = tmp_path / "handed"

    def change(data, _c):
        slots = data.setdefault("slots", {})
        slots["close"] = {"keep_runs": True}
        slots["session"] = {**(slots.get("session") or {}), "handoff": ["sh", "-c", f"echo $COCKPIT_TICKET > {marker}"]}

    path = _copy_pack(pack_file, tmp_path, change)
    monkeypatch.setenv("COCKPIT_PACK", path)
    pack = load(path)
    ticket = f"{pack['tracker']['project']}-1624"
    write_owner(1, "human")
    write_ticket(1, ticket)
    assert (
        session_handoff(pack, 1, "worker-1").endswith("lane:worker-1")
        and marker.read_text().strip() == ticket
        and state_dir(1)
    )
    ended = []
    monkeypatch.setattr(acts, "finish_open_runs", lambda _p, tkt: ended.append(tkt) or [])
    write_owner(1, "human")
    session_close(pack, 1)
    assert ended == [] and read_owner(1) == "free"  # keep_runs: the tester cards stay
    write_owner(1, "human")
    write_ticket(1, ticket)
    session_close(load(pack_file), 1)
    assert ended == [ticket]  # by default a close fails the open runs
    for bad in ({"keep_runs": "yes"},):
        with pytest.raises(CockpitError, match="slots.close takes"):
            load(
                _copy_pack(pack_file, tmp_path / "bad", lambda data, _c: data.setdefault("slots", {}).update(close=bad))
            )
    with pytest.raises(CockpitError, match="slots.session takes"):
        load(
            _copy_pack(
                pack_file,
                tmp_path / "bad2",
                lambda data, _c: data.setdefault("slots", {}).update(session={"later": ["true"]}),
            )
        )


def test_discover_skips_what_is_no_published_push_with_a_branch(monkeypatch):
    from cockpitlib import pr_watch

    rows = [
        {"type": "open-pr", "status": "published", "ticket": "T-1", "payload": {"repo": "api"}},
        {"type": "push-branch", "status": "pending", "ticket": "T-1", "payload": {"repo": "api", "branch": "work/T-1"}},
        {"type": "push-branch", "status": "published", "ticket": "T-1", "payload": {"repo": "api", "branch": ""}},
    ]
    monkeypatch.setattr(pr_watch, "all_intents", lambda *_a: rows)

    class Forge:
        def repo(self, name):
            raise AssertionError("no row here reaches the forge")

    assert pr_watch.discover({"forge": {"discover_prs": True}}, Forge()) == []


def test_the_advisor_line_is_asked_only_of_the_card_kinds_the_pack_names(env, monkeypatch, tmp_path):
    from cockpitlib.egress import check_tool
    from cockpitlib.kanban import place_card

    pack_file = next(path for path in PACKS if (load(path).get("advisor") or {}).get("in_tool"))
    path = _copy_pack(pack_file, tmp_path, lambda data, _c: data["advisor"].update(report_on=["work"]))
    monkeypatch.setenv("COCKPIT_PACK", path)
    pack = load(path)
    ticket = f"{pack['tracker']['project']}-1630"
    work = place_card(pack["board"], f"{ticket}: work", "worker-1", "ready", kind="work", ticket=ticket, pack=pack)
    rework = place_card(
        pack["board"], f"{ticket}: rework", "worker-1", "ready", kind="rework", ticket=ticket, pack=pack
    )
    monkeypatch.setenv("COCKPIT_LANE", "worker-1")
    monkeypatch.setenv("HERMES_KANBAN_TASK", rework)
    assert check_tool("kanban_complete", {"summary": "packaged the patch"}) == ""  # a kind the pack leaves out
    monkeypatch.setenv("HERMES_KANBAN_TASK", work)
    assert "lacks the advisor line" in check_tool("kanban_complete", {"summary": "done"})
    monkeypatch.setenv("HERMES_KANBAN_TASK", "t_unknown")
    assert "lacks the advisor line" in check_tool(
        "kanban_complete", {"summary": "done"}
    )  # a card of no known kind keeps the rule
    monkeypatch.delenv("COCKPIT_LANE")
    for bad in ("work", [""], [1]):
        with pytest.raises(CockpitError, match="report_on"):
            load(
                _copy_pack(
                    pack_file,
                    tmp_path / str(abs(hash(str(bad)))),
                    lambda data, _c, bad=bad: data["advisor"].update(report_on=bad),
                )
            )
