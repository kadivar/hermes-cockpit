# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Cards, watches and the Demo card: one repo's bumps card, conversation comments without a finding tag, the reviewer's stale ping, a
card per failed rerun attempt, the repo's flaky history, a session refused on a lane's slot, the slot Demo card's own apps, the
base watch's branch and its card's PR link and files, the bump scan's own repo flag and the Board's Done window. Both fixture packs;
every new setting is optional and its default is what the kernel did before."""

import json
import os
import shutil

import pytest
import yaml

from cockpitlib.errors import CockpitError, Conflict
from cockpitlib.pack import load

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PACKS = (os.path.join(ROOT, "packs", "acme", "pack.yaml"), os.path.join(ROOT, "packs", "bravo", "pack.yaml"))


def _copy_pack(pack_file, tmp_path, change, repos_change=None) -> str:
    copied = tmp_path / "packs" / os.path.basename(os.path.dirname(pack_file))
    shutil.copytree(os.path.dirname(pack_file), copied)
    data = yaml.safe_load((copied / "pack.yaml").read_text(encoding="utf-8"))
    change(data)
    (copied / "pack.yaml").write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    if repos_change:
        repos = yaml.safe_load((copied / "repos.yaml").read_text(encoding="utf-8"))
        repos_change(repos["repos"])
        (copied / "repos.yaml").write_text(yaml.safe_dump(repos, sort_keys=False), encoding="utf-8")
    return str(copied / "pack.yaml")


def _client():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from dashboard.cockpit.router import router

    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def _notified():
    path = os.path.join(os.environ["COCKPIT_ROOT"], "notified.log")
    return open(path, encoding="utf-8").read() if os.path.isfile(path) else ""


def _bad(pack_file, tmp_path, change, repos_change=None, match=""):
    folder = tmp_path / f"bad{len(os.listdir(tmp_path)) if os.path.isdir(tmp_path) else 0}"
    with pytest.raises(CockpitError, match=match):
        load(_copy_pack(pack_file, folder, change, repos_change))


@pytest.mark.parametrize("pack_file", PACKS)
def test_one_repos_bumps_card_names_its_repo_and_a_second_repo_is_no_twin(env, pack_file, monkeypatch):
    from cockpitlib.kanban import board_cards
    from cockpitlib.kickoff import batch_key, start

    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    pack = load(pack_file)
    monkeypatch.setattr("cockpitlib.capacity.refusal_for", lambda *_a, **_k: "")
    first, second = [repo["name"] for repo in pack["repos"]["repos"]][:2]
    ticket = batch_key(pack)
    a = start(pack, "bumps", ticket=ticket, repo=first)
    b = start(pack, "bumps", ticket=ticket, repo=second)
    assert a["card_id"] != b["card_id"]
    titles = {card["id"]: card["title"] for card in board_cards(pack["board"])}
    assert (
        titles[a["card_id"]] == f"{ticket}: bumps on {first}" and titles[b["card_id"]] == f"{ticket}: bumps on {second}"
    )
    with pytest.raises(Conflict, match="already open"):
        start(pack, "bumps", ticket=ticket, repo=first)  # the same repo twice is a twin


@pytest.mark.parametrize("pack_file", PACKS)
def test_a_conversation_comment_without_a_finding_tag_is_skipped_when_the_pack_asks(bare, pack_file, tmp_path):
    from cockpitlib.pr_watch import _skip

    plain = load(pack_file)
    strict = load(_copy_pack(pack_file, tmp_path, lambda data: data["forge"].update(tagged_comments_only=True)))
    chatter = {
        "id": "issue:1",
        "kind": "comment",
        "author": "a-bot-like-reviewer",
        "body": "Walkthrough: this PR changes the export.",
    }
    inline = {**chatter, "id": "inline:2", "kind": "inline"}
    assert _skip(plain, "me", chatter) == ""  # default: counted, as before
    assert _skip(strict, "me", chatter).startswith("a conversation comment without a finding tag")
    assert _skip(strict, "me", inline) == ""  # a comment on the code still counts
    tag = (strict["forge"].get("mention_tags") or [None])[0]
    if tag:
        assert _skip(strict, "me", {**chatter, "body": f"{tag} please look"}) == ""
    _bad(
        pack_file, tmp_path, lambda data: data["forge"].update(tagged_comments_only="yes"), match="tagged_comments_only"
    )


@pytest.mark.parametrize("pack_file", PACKS)
def test_a_pr_you_asked_changes_on_that_goes_quiet_is_pinged_once_when_the_pack_names_the_event(
    env, pack_file, monkeypatch, tmp_path
):
    from cockpitlib import pr_watch
    from cockpitlib.outbox import create
    from tests.support import fake_gh

    def change(data):
        data["notify"]["pr_stale_review"] = data["notify"]["ready_for_review"]

    path = _copy_pack(pack_file, tmp_path, change)
    monkeypatch.setenv("COCKPIT_PACK", path)
    monkeypatch.delenv("COCKPIT_LANE", raising=False)
    pack = load(path)
    me = pack["forge"]["human_login"]
    repo = pack["repos"]["repos"][0]["name"]
    full = f"{pack['forge']['org']}/{repo}"
    ticket = f"{pack['tracker']['project']}-2101"
    fake_gh.setup(me=me, repos=[full])
    fake_gh.pull(full, 5, "their-branch", "b" * 40, author="colleague")
    create(pack, ticket, "pr-review-submit", "c", "r", {"repo": repo, "number": 5, "sha": "b" * 40})
    fake_gh.review(full, 5, me, "CHANGES_REQUESTED", body="needs work", commit="b" * 40, at="2026-10-21T08:00:00Z")
    now = pr_watch._stamp("2026-10-21T08:00:00Z")
    stale = (pack["hours"].get("pr_stale_hours") or pr_watch.STALE_HOURS) * 3600
    pr_watch.watch(pack, now=now + 60)
    pr_watch.watch(pack, now=now + stale + 120)
    pr_watch.watch(pack, now=now + stale + 240)
    assert _notified().count("|pr_stale_review|") == 1
    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    assert "pr_stale_review" not in load(pack_file)["notify"]  # no entry: the event stays silent


@pytest.mark.parametrize("pack_file", PACKS)
def test_a_rerun_that_fails_after_a_finished_diagnosis_gets_its_own_card_when_the_pack_asks(
    env, pack_file, monkeypatch, tmp_path
):
    from cockpitlib import ci_watch
    from cockpitlib.kanban import BoardWrites, board_cards

    path = _copy_pack(
        pack_file,
        tmp_path,
        lambda data: data.setdefault("watchers", {}).setdefault("ci", {}).update(card_per_attempt=True),
    )
    monkeypatch.setenv("COCKPIT_PACK", path)
    pack = load(path)
    plain = load(pack_file)
    monkeypatch.setattr(ci_watch, "_tail", lambda *_a, **_k: "the log")
    ticket = f"{pack['tracker']['project']}-2102"
    repo = pack["repos"]["repos"][0]["name"]
    run = {"id": 71, "name": "tests", "run_attempt": 1, "html_url": "https://forge.test/run/71"}
    first = ci_watch._card(pack, ticket, repo, "c" * 40, "work/x", run, None)
    writes = BoardWrites(pack["board"])
    writes.complete(first, result="flaky")
    writes.flush()
    assert (
        ci_watch._card(plain, ticket, repo, "c" * 40, "work/x", {**run, "run_attempt": 2}, None) == first
    )  # default: the verdict stands
    again = ci_watch._card(pack, ticket, repo, "c" * 40, "work/x", {**run, "run_attempt": 2}, None)
    assert again != first
    body = {card["id"]: card for card in board_cards(pack["board"], pack)}[again]["body"]
    assert "is not flaky twice" in body and "attempt 2" in body
    _bad(
        pack_file,
        tmp_path,
        lambda data: data.setdefault("watchers", {}).setdefault("ci", {}).update(card_per_attempt="x"),
        match="card_per_attempt",
    )


def test_the_ci_card_names_the_repos_flaky_history_on_other_tickets(bare):
    from cockpitlib import ci_watch
    from cockpitlib.paths import qa

    for ticket, count in (("T-1", 2), ("T-2", 1), ("T-3", 0)):
        folder = os.path.join(qa(), ticket, "ci")
        os.makedirs(folder)
        runs = [{"name": "tests", "passed_after_rerun": True}] * count + [{"name": "lint", "passed_after_rerun": True}]
        json.dump({"repo": "api", "runs": runs}, open(os.path.join(folder, "api-abc.json"), "w"))
    json.dump(
        {"repo": "web", "runs": [{"name": "tests", "passed_after_rerun": True}]},
        open(os.path.join(qa(), "T-3", "ci", "web-abc.json"), "w"),
    )
    assert ci_watch._repo_flaky("api", "tests") == [("T-1", 2), ("T-2", 1)]
    assert (
        ci_watch._repo_line("api", "tests", "T-1")
        == "Flaky history of this run on the repo's other tickets: 1 time(s): T-2 (1)."
    )
    assert ci_watch._repo_line("api", "deploy", "T-1").endswith("none.")


@pytest.mark.parametrize("pack_file", PACKS)
def test_a_session_on_a_slot_a_lane_holds_is_refused(bare, pack_file, monkeypatch):
    from cockpitlib.acts import session_open
    from cockpitlib.slots import write_owner

    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    pack = load(pack_file)
    monkeypatch.setattr("cockpitlib.slots.data_ready", lambda *_a, **_k: "ready")
    write_owner(1, "lane:worker-1")
    with pytest.raises(CockpitError, match="busy with the pipeline"):
        session_open(pack, 1, f"{pack['tracker']['project']}-2103")


@pytest.mark.parametrize("pack_file", PACKS)
def test_a_slot_demo_shows_the_slots_own_apps_with_start_where_the_checkout_exists(
    env, pack_file, monkeypatch, tmp_path
):
    from cockpitlib.paths import qa, wt

    repo = load(pack_file)["repos"]["repos"][0]["name"]

    def change(data):
        slots = data.setdefault("slots", {})
        slots["ports"] = {**(slots.get("ports") or {}), "web": 5100, "https": 8200}
        slots["session_card"] = {
            "apps": {
                "App": {"url": "https://app.local.test:{port.web}", "repo": repo},
                "API": "https://api.local.test:{port.https}",
            }
        }

    path = _copy_pack(pack_file, tmp_path, change)
    monkeypatch.setenv("COCKPIT_PACK", path)
    pack = load(path)
    ticket = f"{pack['tracker']['project']}-2104"
    os.makedirs(os.path.join(qa(), ticket))
    os.makedirs(os.path.join(wt(), ticket, repo))
    json.dump({"slot": 2}, open(os.path.join(qa(), ticket, "demo.json"), "w"))
    monkeypatch.setattr("cockpitlib.acts.origins_up", lambda origins: {name: name == "API" for name in origins})
    shown = _client().get(f"/demo?ticket={ticket}").json()
    assert shown["apps"] == [
        {"name": "App", "url": "https://app.local.test:5102", "up": False, "repo": repo, "worktree": True},
        {"name": "API", "url": "https://api.local.test:8202", "up": True},
    ]
    json.dump({"account": "a@x.test"}, open(os.path.join(qa(), ticket, "demo.json"), "w"))
    assert [app["name"] for app in _client().get(f"/demo?ticket={ticket}").json()["apps"]] != [
        "App",
        "API",
    ]  # no slot: the staging apps
    _bad(
        pack_file,
        tmp_path,
        lambda data: data.setdefault("slots", {}).update(
            session_card={"apps": {"x": {"url": "https://x", "other": 1}}}
        ),
        match="session_card",
    )


@pytest.mark.parametrize("pack_file", PACKS)
def test_the_base_watch_reads_the_repos_watch_branch_and_its_card_carries_the_link_and_files(
    env, pack_file, monkeypatch, tmp_path
):
    from cockpitlib import acts
    from cockpitlib.kanban import board_cards

    first = load(pack_file)["repos"]["repos"][0]["name"]

    def repos_change(repos):
        repos[0]["watch_base"] = "release"

    def skills(data):
        pass

    path = _copy_pack(pack_file, tmp_path, skills, repos_change)
    copied = os.path.dirname(path)
    skills_file = os.path.join(copied, "skills.yaml")
    data = yaml.safe_load(open(skills_file))
    data.setdefault("cards", {})["analyst"] = {"base": "Explain {change}: {url}\nFiles:\n{files}"}
    yaml.safe_dump(data, open(skills_file, "w"), sort_keys=False)
    monkeypatch.setenv("COCKPIT_PACK", path)
    pack = load(path)
    asked = {}
    pr = {
        "number": 7,
        "title": "change",
        "mergedAt": "2026-10-27T10:00:00Z",
        "url": "https://forge.test/pr/7",
        "author": {"login": "dev"},
        "files": [{"path": f"src/f{n}.py"} for n in range(32)],
    }

    def listed(org, name, state, runner=None, base=""):
        asked[name] = base
        return [pr] if name == first else []

    monkeypatch.setattr(acts, "list_prs", listed)
    monkeypatch.setattr(acts, "attribute", lambda *_a: ["node"])
    acts.scan_base(pack, now=1_793_200_000)
    assert asked[first] == "release"
    card = next(
        card
        for card in board_cards(pack["board"], pack)
        if card.get("title", "").endswith(f"{first}#7") or f"{first}#7" in (card.get("body") or "")
    )
    assert "https://forge.test/pr/7" in card["body"] and "- src/f0.py" in card["body"] and "… 2 more" in card["body"]
    _bad(pack_file, tmp_path, lambda data: None, lambda repos: repos[0].update(watch_base=""), match="watch_base")


@pytest.mark.parametrize("pack_file", PACKS)
def test_a_repo_can_be_bump_scanned_apart_from_the_watches(env, pack_file, tmp_path):
    from cockpitlib.pack import bump_scanned, watched

    assert bump_scanned({"name": "a"}) and not bump_scanned({"name": "a", "watched": False})  # default: as watched says
    assert bump_scanned({"name": "a", "watched": False, "bumps": True}) and not bump_scanned(
        {"name": "a", "bumps": False}
    )
    assert watched({"name": "a", "bumps": True, "watched": False}) is False
    _bad(
        pack_file,
        tmp_path,
        lambda data: None,
        lambda repos: repos[0].update(bumps="yes"),
        match="bumps is true or false",
    )


@pytest.mark.parametrize("pack_file", PACKS)
def test_the_boards_done_window_comes_from_the_pack(bare, pack_file, monkeypatch, tmp_path):
    from cockpitlib.board_view import board

    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    assert board(load(pack_file))["recent_hours"] == 24  # default, as before
    pack = load(
        _copy_pack(pack_file, tmp_path, lambda data: data.setdefault("desktop", {}).update(done_recent_hours=72))
    )
    assert board(pack)["recent_hours"] == 72
    _bad(
        pack_file,
        tmp_path,
        lambda data: data.setdefault("desktop", {}).update(done_recent_hours=0),
        match="done_recent_hours",
    )


# --- the CI watch asks a failed branch head every pass for free, and the records change only on a fact -------------------


@pytest.mark.parametrize("pack_file", PACKS)
def test_a_failed_branch_head_is_asked_every_pass_for_free_and_a_rerun_by_hand_is_seen_at_once(
    env, pack_file, monkeypatch
):
    from cockpitlib import ci_watch
    from cockpitlib.intents import load as load_intent
    from cockpitlib.outbox import create, endorse
    from cockpitlib.publish import execute
    from cockpitlib.record_write import Checks
    from tests.support import fake_gh

    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    monkeypatch.delenv("COCKPIT_LANE", raising=False)
    pack = load(pack_file)
    assert "ci_reread_minutes" not in (pack.get("hours") or {})
    repo = pack["repos"]["repos"][0]["name"]
    full = f"{pack['forge']['org']}/{repo}"
    fake_gh.setup(me=pack["forge"]["human_login"], repos=[full])
    ticket = f"{pack['tracker']['project']}-1477"
    branch = f"work/{ticket}"
    settle = float((pack.get("hours") or {}).get("ci_settle_minutes") or ci_watch.SETTLE_MINUTES) * 60

    def published(name):
        fake_gh.commit(repo, branch, name=name)
        row = endorse(
            create(pack, ticket, "push-branch", "c", "push", {"repo": repo, "branch": branch})["id"],
            "low",
            "",
            "gatekeeper",
            "fixture-a",
            "fixture-large",
        )
        assert execute(row, pack=pack)["ok"]
        return load_intent(row["id"])["payload"]["sha"]

    def asked(sha, since):
        return [call for call in fake_gh.calls()[since:] if f"head_sha={sha}" in call["path"]]

    old = published("old.txt")
    fake_gh.run(full, 8101, old, "tests", conclusion="failure")
    ci_watch.watch(pack, now=1000)
    ci_watch.watch(pack, now=1000 + settle)
    sha = published("new.txt")  # the branch moved on: the old failed commit is no longer its head
    fake_gh.run(full, 8102, sha, "tests", conclusion="failure")
    assert len(ci_watch.watch(pack, now=2000)["cards"]) == 1
    ci_watch.watch(pack, now=2000 + settle)  # the runs are unchanged (a 304): the settle clock still moves on
    path = ci_watch.record_path(ticket, repo, sha)
    record = json.load(open(path, encoding="utf-8"))
    assert record["settled"] and record["state"] == "failed"
    assert json.load(open(ci_watch.record_path(ticket, repo, old), encoding="utf-8"))["settled"]
    mtime, before = os.path.getmtime(path), len(fake_gh.calls())
    for n in range(3):
        assert ci_watch.watch(pack, now=2000 + settle + 60 * (n + 1))["cards"] == []
    calls = asked(sha, before)
    assert len(calls) == 3 and all(call.get("if_none_match") for call in calls)  # every pass, each a conditional read
    assert os.path.getmtime(path) == mtime  # nothing new: the record is not written
    assert not asked(old, before)  # an older push on the branch waits for the slow re-read
    seen = Checks("ci").get(path)
    assert (
        seen["etag"] == calls[-1]["if_none_match"] and ci_watch.state_for(ticket, repo, sha)["last_check"] == seen["at"]
    )
    # A rerun started by hand on the forge is seen on the next pass; its green follows once it settles.
    fake_gh.run(full, 8102, sha, "tests", status="in_progress", attempt=2)
    later = 2000 + settle + 600
    ci_watch.watch(pack, now=later)
    record = json.load(open(path, encoding="utf-8"))
    assert record["state"] == "running" and "settled" not in record
    fake_gh.run(full, 8102, sha, "tests", conclusion="success", attempt=2)
    assert ci_watch.watch(pack, now=later + 60)["green"] == []
    assert ci_watch.watch(pack, now=later + 60 + settle)["green"] == [sha]
    record = json.load(open(path, encoding="utf-8"))
    assert record["settled"] and record["runs"][0]["passed_after_rerun"]


def test_the_forge_reads_conditionally_and_says_when_nothing_changed():
    from types import SimpleNamespace

    from cockpitlib.forge import Forge

    replies, asked = [], []

    def runner(args, **_kw):
        asked.append(args)
        reply = replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply

    forge = Forge({}, runner=runner)
    replies.append(
        SimpleNamespace(returncode=0, stdout='HTTP/2.0 200 OK\r\nEtag: W/"a1"\r\n\r\n{"workflow_runs": []}', stderr="")
    )
    assert forge.get_if_changed("repos/o/r/actions/runs") == {
        "changed": True,
        "etag": 'W/"a1"',
        "body": {"workflow_runs": []},
    }
    assert asked[-1] == ["gh", "api", "-i", "repos/o/r/actions/runs"]
    replies.append(
        SimpleNamespace(returncode=1, stdout='HTTP/2.0 304 Not Modified\nEtag: W/"a1"\n\n', stderr="gh: HTTP 304")
    )
    assert forge.get_if_changed("repos/o/r/actions/runs", 'W/"a1"') == {
        "changed": False,
        "etag": 'W/"a1"',
        "body": None,
    }
    assert asked[-1][-2:] == ["-H", 'If-None-Match: W/"a1"']
    replies.append(SimpleNamespace(returncode=0, stdout="HTTP/2.0 200 OK\n\nplain", stderr=""))
    assert forge.get_if_changed("x") == {
        "changed": True,
        "etag": "",
        "body": "plain",
    }  # no ETag, a body that is no JSON
    replies.append(SimpleNamespace(returncode=0, stdout="HTTP/2.0 200 OK\n\n", stderr=""))
    assert forge.get_if_changed("x")["body"] == {}
    replies.append(
        SimpleNamespace(returncode=1, stdout="HTTP/2.0 404 Not Found\n\n{}", stderr="gh: Not Found (HTTP 404)")
    )
    with pytest.raises(CockpitError, match="Not Found"):
        forge.get_if_changed("x")
    replies.append(OSError("no gh"))
    with pytest.raises(CockpitError, match="no gh"):
        forge.get_if_changed("x")


def test_the_pages_show_when_a_record_was_last_read_though_the_record_was_not_written(bare):
    from cockpitlib.acts import pr_state
    from cockpitlib.outbox import _pr_state
    from cockpitlib.paths import qa, records, records_name
    from cockpitlib.record_write import Checks, with_checked, write_record
    from cockpitlib.state_commit import _concern

    path = os.path.join(qa(), "T-9", "pr", "api-5.json")
    write_record(path, {"ticket": "T-9", "repo": "api", "number": 5, "last_check": "2026-01-01T00:00:00Z"})
    assert (
        pr_state("T-9", "api", 5)["last_check"] == "2026-01-01T00:00:00Z"
    )  # no read recorded yet: the record's own time
    checks = Checks("pr")
    checks.mark(path)
    checks.save()
    at = Checks("pr").get(path)["at"]
    assert pr_state("T-9", "api", 5)["last_check"] == at and _pr_state("T-9", "api", 5)["last_check"] == at
    assert json.load(open(path, encoding="utf-8"))["last_check"] == "2026-01-01T00:00:00Z"  # the record is untouched
    assert with_checked("pr", path, {}) == {}
    assert with_checked("pr", path, {"last_check": "2999-01-01T00:00:00Z"})["last_check"] == "2999-01-01T00:00:00Z"
    kept = os.path.relpath(os.path.join(records(), "watch", "pr-checked.json"), os.path.dirname(records()))
    assert (
        os.path.isfile(os.path.join(os.path.dirname(records()), kept))
        and _concern(f"{records_name().rstrip('/')}/watch/pr-checked.json") == ""
    )
    open(os.path.join(records(), "watch", "pr-checked.json"), "w").write("[]")
    assert Checks("pr").data == {} and Checks("pr").get(path) == {}  # a checks file that is no map reads as none
