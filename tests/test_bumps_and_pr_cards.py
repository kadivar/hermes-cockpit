# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Dependency bumps and pull-request cards: candidates, grooming, treat cards and what a card shows of its PRs."""

import json
import os
import re

import pytest

from cockpitlib.cli import main
from cockpitlib.pack import load
from tests.support.both_packs import PACKS, _client, _other


@pytest.mark.parametrize("pack_file", PACKS)
def test_a_copy_only_merge_is_skipped(env, pack_file, monkeypatch):
    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    pack = load(pack_file)
    other = load(PACKS[0] if pack["name"] == "bravo" else PACKS[1])
    repo = pack["repos"]["repos"][0]["name"]
    other_repo = other["repos"]["repos"][0]["name"]
    assert repo != other_repo
    from cockpitlib.acts import _noise_only, changes_dir, scan_base

    assert _noise_only(["locales/en.json", "copy/home.md", "messages.po"]) is True
    assert _noise_only(["src/locales/en.json"]) is True
    assert _noise_only(["locales/en.json", "src/app.ts"]) is False

    class Reply:
        def __init__(self, body):
            self.returncode = 0
            self.stderr = ""
            self.stdout = json.dumps(body)

    def runner(argv):
        target = argv[argv.index("--repo") + 1]
        if not target.endswith("/" + repo):
            return Reply([])
        return Reply(
            [
                {
                    "number": 1,
                    "title": "copy",
                    "files": ["locales/en.json", "i18n/app.json"],
                    "author": {"login": "dev"},
                    "mergedAt": "2026-10-01T00:00:00Z",
                },
                {
                    "number": 2,
                    "title": "product",
                    "files": [f"src/{pack['name']}.ts"],
                    "author": {"login": "dev"},
                    "url": f"https://git.{pack['name']}.test/pull/2",
                    "body": f"notes {pack['name']} <kept>",
                    "mergedAt": "2026-10-02T00:00:00Z",
                },
                {
                    "number": 3,
                    "title": "release",
                    "files": [f"src/{pack['name']}.ts"],
                    "author": {"login": "release[bot]"},
                    "mergedAt": "2026-10-03T00:00:00Z",
                },
                {
                    "number": 4,
                    "title": "deps",
                    "headRefName": "dependabot/npm",
                    "files": [f"src/{pack['name']}.ts"],
                    "author": {"login": "dependabot"},
                    "mergedAt": "2026-10-04T00:00:00Z",
                },
            ]
        )

    os.makedirs(changes_dir(), exist_ok=True)
    open(os.path.join(changes_dir(), f"{repo}-2.json"), "w", encoding="utf-8").write(
        json.dumps({"repo": repo, "number": 2, "verdict": f"kept {pack['name']}", "seen": False})
    )
    import datetime

    assert scan_base(
        pack, runner=runner, now=datetime.datetime(2026, 10, 5, tzinfo=datetime.UTC).timestamp()
    ).startswith("base-watch")
    skipped = json.load(open(os.path.join(changes_dir(), f"{repo}-1.json"), encoding="utf-8"))
    product = json.load(open(os.path.join(changes_dir(), f"{repo}-2.json"), encoding="utf-8"))
    assert skipped["status"] == "skipped"
    assert "verdict" not in skipped
    assert product["status"] == "unmapped"
    assert product["verdict"] == f"kept {pack['name']}"
    assert other["name"] not in product["verdict"]
    assert product["author"] == "dev"
    assert product["url"] == f"https://git.{pack['name']}.test/pull/2"
    assert other["name"] not in product["url"]
    assert skipped["author"] == "dev" and skipped["url"] == ""
    from cockpitlib.acts import change_detail

    shown = change_detail(repo, 2)
    assert f"notes {pack['name']}" in shown["body_html"]
    assert "&lt;kept&gt;" in shown["body_html"]
    assert other["name"] not in shown["body_html"]
    assert shown["diff"] == ""
    from cockpitlib.paths import platform_dir

    folder = platform_dir()
    os.makedirs(folder, exist_ok=True)
    open(os.path.join(folder, f"pr-{repo}-2.diff"), "w", encoding="utf-8").write(
        f"diff --git a/src/{pack['name']}.ts b/src/{pack['name']}.ts\n"
    )
    forged = change_detail(repo, 2)
    assert forged["diff"]["diff"].startswith("diff --git")
    assert pack["name"] in forged["diff"]["diff"]
    assert other["name"] not in forged["diff"]["diff"]
    bot = json.load(open(os.path.join(changes_dir(), f"{repo}-3.json"), encoding="utf-8"))
    bump = json.load(open(os.path.join(changes_dir(), f"{repo}-4.json"), encoding="utf-8"))
    assert bot["status"] == "skipped" and bump["status"] == "skipped"
    assert other_repo not in bot["repo"] and other_repo not in bump["repo"]
    import sqlite3

    from cockpitlib.kanban import db_path

    connection = sqlite3.connect(db_path(pack["board"]))
    titles = [row[0] for row in connection.execute("select title from tasks")]
    connection.close()
    platform = f"{pack['tracker']['project']}-PLATFORM: base change"
    assert titles == [f"{platform} {repo}#2"]  # one card, on the platform ticket, only for the change that matters
    from cockpitlib.kanban import board_cards

    assert [card["flow"] for card in board_cards(pack["board"], pack)] == ["platform"]
    assert (
        scan_base(pack, runner=runner, now=datetime.datetime(2026, 10, 6, tzinfo=datetime.UTC).timestamp())
        == "base-watch 0"
    )
    assert other_repo not in " ".join(titles)


@pytest.mark.parametrize("pack_file", PACKS)
def test_a_bump_kickoff_opens_one_card_per_repo(env, pack_file, monkeypatch):
    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    pack = load(pack_file)
    other = load(PACKS[0] if pack["name"] == "bravo" else PACKS[1])
    names = [item["name"] for item in pack["repos"]["repos"]]
    other_names = [item["name"] for item in other["repos"]["repos"]]
    assert names != other_names
    assert pack["tracker"]["project"] != other["tracker"]["project"]
    from cockpitlib.kanban import board_cards

    client = _client()
    first = client.post("/kickoff", json={"mode": "bumps", "repos": names, "prompt": f"batch {pack['name']}"})
    assert first.status_code == 200
    cards = first.json()["cards"]
    assert [row["repo"] for row in cards] == names
    assert all(row["already"] is False for row in cards)
    titles = [item["title"] for item in board_cards(pack["board"])]
    for name in names:
        from cockpitlib.kickoff import batch_key

        assert f"{batch_key(pack)}: bumps on {name}" in titles
    assert all(other["tracker"]["project"] not in title for title in titles)
    second = client.post("/kickoff", json={"mode": "bumps", "repos": names})
    assert second.status_code == 200, second.text
    again = second.json()["cards"]
    assert [row["card_id"] for row in again] == [row["card_id"] for row in cards]
    assert all(row["already"] is True for row in again)
    assert titles == [item["title"] for item in board_cards(pack["board"])]
    blocked = client.post("/kickoff", json={"mode": "bumps", "repos": names + ["extra"]})
    assert blocked.status_code == 409
    assert "bumps on extra" not in " ".join(item["title"] for item in board_cards(pack["board"]))


@pytest.mark.parametrize("pack_file", PACKS)
def test_release_returns_a_bump_to_the_candidates(env, pack_file, monkeypatch):
    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    pack = load(pack_file)
    other = load(PACKS[0] if pack["name"] == "bravo" else PACKS[1])
    repo = pack["repos"]["repos"][0]["name"]
    other_repo = other["repos"]["repos"][0]["name"]
    assert repo != other_repo
    from cockpitlib.acts import bumps_path, take_bumps, visible_bumps

    os.makedirs(os.path.dirname(bumps_path()), exist_ok=True)
    json.dump(
        {
            "repos": {
                repo: [{"number": 4, "sha": "abc", "title": f"deps {pack['name']}"}],
                other_repo: [{"number": 9, "sha": "zzz", "title": "other"}],
            },
            "started": {},
        },
        open(bumps_path(), "w", encoding="utf-8"),
    )
    take_bumps(pack, repo, "card-a", [4])
    assert all(row.get("number") != 4 for row in visible_bumps().get("repos", {}).get(repo, []))
    client = _client()
    listed = client.get("/bumps").json()
    assert listed["started"][repo][0]["card"] == "card-a"
    assert other_repo not in listed["started"]
    released = client.post("/bumps-release", json={"repo": repo, "numbers": [4]})
    assert released.status_code == 200
    assert any(row.get("number") == 4 for row in visible_bumps()["repos"][repo])
    assert all(row.get("number") != 4 for row in client.get("/bumps").json().get("started", {}).get(repo, []))
    assert other_repo in visible_bumps()["repos"]
    data = json.load(open(bumps_path(), encoding="utf-8"))
    data["repos"][repo].append("skip")
    json.dump(data, open(bumps_path(), "w", encoding="utf-8"))
    from cockpitlib.acts import started_bumps

    assert repo not in started_bumps()


@pytest.mark.parametrize("pack_file", PACKS)
def test_a_dismissed_bump_returns_when_the_head_moves(env, pack_file, monkeypatch):
    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    pack = load(pack_file)
    other = load(PACKS[0] if pack["name"] == "bravo" else PACKS[1])
    repo = pack["repos"]["repos"][0]["name"]
    other_repo = other["repos"]["repos"][0]["name"]
    assert repo != other_repo
    from cockpitlib.acts import bumps_path, dismiss_bumps, scan_bumps, visible_bumps

    rows = [
        {
            "number": 4,
            "title": "deps",
            "headRefName": "dependabot/npm",
            "headRefOid": "aaa",
            "author": {"login": "dependabot"},
            "files": [],
        }
    ]

    class Result:
        def __init__(self, body):
            self.returncode = 0
            self.stderr = ""
            self.stdout = body

    def runner(argv):
        target = argv[argv.index("--repo") + 1]
        if not target.endswith("/" + repo):
            return Result("[]")
        return Result(json.dumps(rows))

    assert scan_bumps(pack, runner=runner).startswith("bumps")
    assert dismiss_bumps(pack, repo, [4])["dismissed"] == [4]
    assert all(row.get("number") != 4 for row in visible_bumps().get("repos", {}).get(repo, []))
    assert scan_bumps(pack, runner=runner).startswith("bumps")
    assert all(row.get("number") != 4 for row in visible_bumps().get("repos", {}).get(repo, []))
    rows[0]["headRefOid"] = f"moved-{pack['name']}"
    assert scan_bumps(pack, runner=runner).startswith("bumps")
    shown = visible_bumps()["repos"][repo]
    assert any(row.get("number") == 4 and row.get("sha") == f"moved-{pack['name']}" for row in shown)
    assert other_repo not in visible_bumps()["repos"]
    data = json.load(open(bumps_path(), encoding="utf-8"))
    data["dismissed"][f"{repo}#4"] = "aaa"
    data["repos"][repo] = [{"number": 4, "sha": ""}]
    json.dump(data, open(bumps_path(), "w", encoding="utf-8"))
    assert all(row.get("number") != 4 for row in visible_bumps().get("repos", {}).get(repo, []))
    data["dismissed"][f"{repo}#4"] = "dismissed"
    json.dump(data, open(bumps_path(), "w", encoding="utf-8"))
    assert all(row.get("number") != 4 for row in visible_bumps().get("repos", {}).get(repo, []))
    data["repos"][repo][0]["sha"] = "now"
    json.dump(data, open(bumps_path(), "w", encoding="utf-8"))
    assert any(row.get("number") == 4 for row in visible_bumps()["repos"][repo])


@pytest.mark.parametrize("pack_file", PACKS)
def test_a_second_bump_accept_does_not_open_another_card(env, pack_file, monkeypatch):
    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    pack = load(pack_file)
    other = load(PACKS[0] if pack["name"] == "bravo" else PACKS[1])
    repo = pack["repos"]["repos"][0]["name"]
    other_repo = other["repos"]["repos"][0]["name"]
    assert repo != other_repo
    from cockpitlib.acts import bump_card, bumps_path
    from cockpitlib.kanban import board_cards

    os.makedirs(os.path.dirname(bumps_path()), exist_ok=True)
    json.dump(
        {
            "repos": {repo: [{"number": 4, "sha": "abc", "title": "deps"}]},
            "started": {},
        },
        open(bumps_path(), "w", encoding="utf-8"),
    )
    assert bump_card("", [4]) == ""
    assert bump_card(repo, ["nope"]) == ""
    client = _client()
    first = client.post("/kickoff", json={"ticket": "TASK-8921", "mode": "bumps", "repo": repo, "prs": [4]})
    assert first.status_code == 200
    body = first.json()
    assert body["card_id"] and body.get("already") is not True
    second = client.post("/kickoff", json={"ticket": "TASK-8922", "mode": "bumps", "repo": repo, "prs": [4]})
    assert second.status_code == 409
    assert body["card_id"] in second.text
    titles = [item["title"] for item in board_cards(pack["board"])]
    assert f"TASK-8921: bumps on {repo}" in titles  # one repo's bumps card names its repo
    assert not any(title.startswith("TASK-8922: bumps") for title in titles)
    assert other_repo not in " ".join(titles)


@pytest.mark.parametrize("pack_file", PACKS)
def test_forget_removes_both_pull_request_watch_files(env, pack_file):
    pack = load(pack_file)
    other = load(PACKS[0] if pack["name"] == "bravo" else PACKS[1])
    repo = pack["repos"]["repos"][0]["name"]
    assert repo != other["repos"]["repos"][0]["name"]
    from cockpitlib.acts import forget_pr
    from cockpitlib.paths import platform_dir, qa
    from cockpitlib.pr_watch import inbox_rows as new_comment_rows

    ticket = "TASK-883"
    body = {"ticket": ticket, "repo": repo, "number": 4, "new": [{"id": "c", "body": pack["name"]}]}
    paths = [
        os.path.join(qa(), ticket, "pr", f"{repo}-4.json"),
        os.path.join(platform_dir(), "pr", f"{repo}-4.json"),
    ]
    for path in paths:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        open(path, "w", encoding="utf-8").write(json.dumps(body))
    assert any(row["repo"] == repo and row["number"] == 4 for row in new_comment_rows())
    assert forget_pr(ticket, repo, 4)["ok"]
    assert all(not os.path.isfile(path) for path in paths)
    assert all(row["repo"] != repo or row["number"] != 4 for row in new_comment_rows())
    assert other["name"] not in json.dumps(body["new"])


@pytest.mark.parametrize("pack_file", PACKS)
def test_a_groomed_pull_request_leaves_the_bump_flow(env, pack_file, monkeypatch):
    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    pack = load(pack_file)
    other = load(PACKS[0] if pack["name"] == "bravo" else PACKS[1])
    assert pack["grooming"] != other["grooming"]
    from cockpitlib.acts import _write, bumps_path, record_grooming
    from cockpitlib.paths import platform_dir

    repo = pack["repos"]["repos"][0]["name"]
    other_repo = other["repos"]["repos"][0]["name"]
    checks = list(pack["grooming"])
    foreign = next(act for act in other["grooming"] if act not in checks)
    key = f"{repo}#4"
    _write(
        bumps_path(),
        {
            "repos": {repo: [{"number": 4, "sha": "abc"}], other_repo: [{"number": 9, "sha": "zzz"}]},
            "started": {
                key: {"sha": "abc", "card": "c", "acts": []},
                f"{other_repo}#9": {"sha": "zzz", "card": "d", "acts": list(other["grooming"])},
            },
        },
    )
    assert _client().post("/bumps-groom", json={"repo": repo, "number": "nope", "act": checks[0]}).status_code == 400
    assert _client().post("/bumps-groom", json={"repo": repo, "number": 5, "act": checks[0]}).status_code == 400
    refused = _client().post("/bumps-groom", json={"repo": repo, "number": 4, "act": foreign})
    assert refused.status_code == 400
    assert foreign not in json.dumps(refused.json())
    first = record_grooming(pack, repo, 4, checks[0])
    assert first["graduated"] is False and first["acts"] == [checks[0]]
    again = record_grooming(pack, repo, 4, checks[0])
    assert again["acts"] == [checks[0]]
    for act in checks[1:-1]:
        record_grooming(pack, repo, 4, act)
    last = _client().post("/bumps-groom", json={"repo": repo, "number": 4, "act": checks[-1]})
    assert last.status_code == 200
    assert last.json()["graduated"] is True
    assert other["name"] not in last.text
    stored = json.load(open(bumps_path(), encoding="utf-8"))
    assert key not in (stored.get("started") or {})
    assert f"{other_repo}#9" in stored["started"]
    graduated = json.load(open(os.path.join(platform_dir(), "graduated-prs.json"), encoding="utf-8"))
    assert {"repo": repo, "number": 4, "pack": pack["name"]} in graduated["prs"]
    assert all(item.get("repo") != other_repo for item in graduated["prs"] if isinstance(item, dict))


@pytest.mark.parametrize("pack_file", PACKS)
def test_grooming_checks_come_from_the_pack(env, pack_file, monkeypatch):
    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    pack = load(pack_file)
    from cockpitlib.acts import _write, audit_bumps, bumps_path, graduate_bumps
    from cockpitlib.errors import PackError
    from cockpitlib.kanban import board_cards
    from cockpitlib.pack import _grooming
    from cockpitlib.paths import platform_dir
    from cockpitlib.pr_watch import record_path, watch
    from tests.support import fake_gh

    other = load(PACKS[0] if pack["name"] == "bravo" else PACKS[1])
    checks = list(pack["grooming"])
    assert checks and checks != list(other["grooming"])
    with pytest.raises(PackError, match="grooming"):
        _grooming({"grooming": "push"})
    repo = pack["repos"]["repos"][0]["name"]
    key = f"{repo}#7"
    before = board_cards(pack["board"])
    _write(
        bumps_path(),
        {"started": {key: {"acts": checks[:-1], "card": "c", "sha": "abc"}, "repo#x": {"acts": []}}, "repos": {}},
    )
    missing = audit_bumps(pack)
    assert missing["missing"][0]["pr"] == key and missing["missing"][0]["missing"] == [checks[-1]]
    assert graduate_bumps(pack) == []
    assert board_cards(pack["board"]) == before
    stored = json.load(open(bumps_path(), encoding="utf-8"))
    stored["started"][key]["acts"] = checks
    _write(bumps_path(), stored)
    assert graduate_bumps(pack) == [key]
    assert key not in (json.load(open(bumps_path(), encoding="utf-8")).get("started") or {})
    graduated = json.load(open(os.path.join(platform_dir(), "graduated-prs.json"), encoding="utf-8"))
    assert {"repo": repo, "number": 7, "pack": pack["name"]} in graduated["prs"]
    graduated["prs"].append("skip")
    _write(os.path.join(platform_dir(), "graduated-prs.json"), graduated)
    listed = [
        {
            "number": 7,
            "title": "done",
            "headRefName": "dependabot/npm",
            "headRefOid": "abc",
            "author": {"login": "dependabot"},
            "files": [],
        },
        {
            "number": 8,
            "title": f"open {pack['name']}",
            "headRefName": "dependabot/npm",
            "headRefOid": "def",
            "author": {"login": "dependabot"},
            "files": [],
        },
    ]

    class Listed:
        def __init__(self, body):
            self.returncode = 0
            self.stdout = body
            self.stderr = ""

    def runner(argv):
        target = argv[argv.index("--repo") + 1]
        if not target.endswith("/" + repo):
            return Listed("[]")
        return Listed(json.dumps(listed))

    from cockpitlib.acts import scan_bumps, visible_bumps

    assert scan_bumps(pack, runner=runner).startswith("bumps")
    shown = visible_bumps().get("repos", {}).get(repo, [])
    assert all(row.get("number") != 7 for row in shown)
    assert any(row.get("number") == 8 and pack["name"] in row.get("title", "") for row in shown)
    graduated["prs"] = [item for item in graduated["prs"] if isinstance(item, dict)]
    _write(os.path.join(platform_dir(), "graduated-prs.json"), graduated)

    full = f"{pack['forge']['org']}/{repo}"
    fake_gh.setup(me=pack["forge"]["human_login"], repos=[full])
    fake_gh.pull(full, 7, "dependabot/npm", "a" * 40, author="dependabot")
    first = fake_gh.comment(full, 7, "reviewer-x", "hi")
    assert watch(pack, now=100)["rows"] == []
    watched = json.load(open(record_path("", repo, 7), encoding="utf-8"))
    assert watched["ids"] == [f"issue:{first}"] and watched["role"] == "reviewer"
    fake_gh.comment(full, 7, "reviewer-x", "more", at="2026-10-21T10:00:00Z")
    watch(pack, now=200)
    assert json.load(open(record_path("", repo, 7), encoding="utf-8"))["new_count"] == 1
    _write(bumps_path(), {"started": {f"{repo}#nope": {"acts": checks}}, "repos": {repo: [{"number": 9}]}})
    assert graduate_bumps(pack) == [f"{repo}#nope"]
    graduated = json.load(open(os.path.join(platform_dir(), "graduated-prs.json"), encoding="utf-8"))
    graduated["prs"].append({"repo": "", "number": 1})
    graduated["prs"].append({"repo": repo, "number": 8})
    _write(os.path.join(platform_dir(), "graduated-prs.json"), graduated)

    assert any("#8" in error for error in watch(pack, now=300)["errors"])


@pytest.mark.parametrize("pack_file", PACKS)
def test_bump_grooming_follows_the_published_intents_and_the_batch_has_the_packs_key(
    env, pack_file, monkeypatch, tmp_path
):
    import shutil

    import yaml

    from cockpitlib.acts import (
        _write,
        audit_bumps,
        bumps_path,
        derive_grooming,
        graduate_bumps,
        record_grooming,
        take_bumps,
    )
    from cockpitlib.errors import PackError
    from cockpitlib.intents import save
    from cockpitlib.kickoff import batch_key
    from cockpitlib.outbox import create

    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    pack = {
        **load(pack_file),
        "bump_sequence": None,
    }  # the stages' order is its own test: here every act is filed alone
    repo = pack["repos"]["repos"][0]["name"]
    key = batch_key(pack, now=1_792_000_000)
    assert key != batch_key(_other(pack), now=1_792_000_000) and key.startswith(pack["tracker"]["project"] + "-")
    _write(
        bumps_path(), {"repos": {repo: [{"number": 4, "sha": "a" * 40, "head": "dependabot/parser"}]}, "started": {}}
    )
    take_bumps(pack, repo, "t_card", [4])

    def published(kind, payload):
        row = create(pack, key, kind, "t_card", "x", payload)
        row["status"] = "published"
        save(row)
        return row

    published("push-branch", {"repo": repo, "branch": "dependabot/parser"})
    for rule in pack["grooming_rules"][1:]:
        payload = {"repo": repo, "number": 4, "sha": "a" * 40}
        if rule["field"]:
            payload[rule["field"]] = ["x"] if rule["field"].endswith("labels") else f"[{key}]"
        if rule["event"]:
            payload["event"] = rule["event"]
        published(rule["intent"], payload)
    proved = derive_grooming(pack)
    assert sorted(act for _pr, act in proved) == sorted(rule["name"] for rule in pack["grooming_rules"])
    assert derive_grooming(pack) == []
    manual = [name for name in pack["grooming"] if name not in {rule["name"] for rule in pack["grooming_rules"]}]
    assert audit_bumps(pack)["missing"] == [{"pr": f"{repo}#4", "missing": manual}]
    assert graduate_bumps(pack) == []
    done = [record_grooming(pack, repo, 4, name) for name in manual]
    assert [row["graduated"] for row in done] == [False] * (len(manual) - 1) + [True]  # the last tick completes the set
    name = os.path.basename(os.path.dirname(pack_file))
    copied = tmp_path / "packs" / name
    shutil.copytree(os.path.dirname(pack_file), copied)
    raw = yaml.safe_load((copied / "pack.yaml").read_text(encoding="utf-8"))
    for change, message in (
        (("grooming", [{"name": "push", "intent": "deploy"}]), "an intent type and a payload field"),
        (("grooming", "push"), "grooming"),
        (("forge", {**raw["forge"], "bump_batch": "{project}-{season}"}), "forge.bump_batch: 'season'"),
        (("forge", {**raw["forge"], "bump_batch": "bumps of {week}"}), "is not a ticket key"),
    ):
        (copied / "pack.yaml").write_text(
            yaml.safe_dump({**raw, change[0]: change[1]}, sort_keys=False, allow_unicode=True), encoding="utf-8"
        )
        with pytest.raises(PackError, match=re.escape(message)):
            load(str(copied / "pack.yaml"))


@pytest.mark.parametrize("pack_file", PACKS)
def test_pr_links_never_reach_a_card_and_a_guarded_card_is_handed_off_and_back(env, pack_file, monkeypatch):
    import sqlite3
    import time

    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    pack = load(pack_file)
    other = _other(pack)
    from cockpitlib.acts import answer_card
    from cockpitlib.housekeeping import GUARD_SECONDS, unguard
    from cockpitlib.kanban import db_path, defuse_pr_links, place_card
    from cockpitlib.settings import load as load_settings
    from cockpitlib.settings import save as save_settings

    repo = pack["repos"]["repos"][0]["name"]
    url = f"https://github.com/{pack['forge']['org']}/{repo}/pull/41#discussion_r9"
    assert defuse_pr_links(f"see {url} and https://github.com/x/y/pull/7") == f"see {repo}#41 (discussion_r9) and y#7"
    assert (
        defuse_pr_links("") == ""
        and defuse_pr_links("https://github.com/x/y/issues/7") == "https://github.com/x/y/issues/7"
    )
    save_settings(pack, {"seats": {**load_settings(pack)["seats"], "slots": 2}})
    ticket = f"{pack['tracker']['project']}-401"
    card = place_card(pack["board"], f"{ticket}: work", "worker-1", "blocked", reason="waiting for the answer")
    answer_card(pack, card, f"go, it is {url}")
    connection = sqlite3.connect(db_path(pack["board"]))
    bodies = [row[0] for row in connection.execute("select body from task_comments where task_id = ?", (card,))]
    connection.close()
    assert any(f"{repo}#41" in body for body in bodies) and not any("github.com" in body for body in bodies)
    now = int(time.time())
    single = place_card(pack["board"], f"{ticket}: review", "reviewer", "ready")
    fresh = place_card(pack["board"], f"{ticket}: work two", "worker-2", "ready")
    other_reason = place_card(pack["board"], f"{ticket}: work three", "worker-2", "ready")
    connection = sqlite3.connect(db_path(pack["board"]))
    for guarded, reason, age in (
        (card, "active_pr", GUARD_SECONDS + 5),
        (single, "active_pr", GUARD_SECONDS + 5),
        (fresh, "active_pr", 10),
        (other_reason, "recent_success", 999),
    ):
        connection.execute(
            "insert into task_events (task_id, kind, payload, created_at) values (?, 'respawn_guarded', ?, ?)",
            (guarded, json.dumps({"reason": reason}), now - age),
        )
    connection.commit()
    connection.close()
    assert unguard(pack, now=now) == "1"  # the only reviewer seat cannot hand off; the fresh one waits
    connection = sqlite3.connect(db_path(pack["board"]))
    events = [
        (row[0], row[1])
        for row in connection.execute(
            "select kind, payload from task_events where task_id = ? and kind = 'assigned' order by id", (card,)
        )
    ]
    assignee = connection.execute("select assignee from tasks where id = ?", (card,)).fetchone()[0]
    said = connection.execute(
        "select body from task_comments where task_id = ? order by id desc limit 1", (card,)
    ).fetchone()[0]
    connection.close()
    assert [json.loads(payload)["assignee"] for _kind, payload in events][-2:] == [
        "worker-2",
        "worker-1",
    ] and assignee == "worker-1"
    assert said.startswith("unguarded:") and other["name"] not in said
    assert unguard(pack, now=now) == "0"  # the handoff is the last event now: not guarded again
    assert unguard({"board": f"none-{pack['name']}"}) == "0"


@pytest.mark.parametrize("pack_file", PACKS)
def test_a_second_batch_of_comments_folds_into_the_treat_card_still_at_its_plan(env, pack_file, monkeypatch):
    import sqlite3
    import subprocess

    from cockpitlib.acts import treat_pr
    from cockpitlib.errors import Conflict
    from cockpitlib.kanban import BoardWrites, board_cards, db_path
    from cockpitlib.outbox import create
    from cockpitlib.pr_watch import record_path

    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    monkeypatch.delenv("COCKPIT_LANE", raising=False)
    pack = load(pack_file)
    name = pack["repos"]["repos"][0]["name"]
    ticket = f"{pack['tracker']['project']}-1401"
    source = env["root"] / "repos" / name
    if not (source / ".git").exists():
        source.mkdir(parents=True)
        subprocess.run(["git", "init", "-q", str(source)], check=True)
        (source / "README").write_text("hello\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(source), "add", "README"], check=True)
        subprocess.run(
            [
                "git",
                "-C",
                str(source),
                "-c",
                "user.name=Dev",
                "-c",
                "user.email=dev@example.test",
                "commit",
                "-qm",
                "init",
            ],
            check=True,
        )

    def batch(*comments):
        path = record_path(ticket, name, 8)
        record = (
            json.load(open(path, encoding="utf-8"))
            if os.path.exists(path)
            else {"repo": name, "number": 8, "role": "author", "state": "open"}
        )
        record["new"] = [{"id": index, "body": f"{text} ({pack['name']})"} for index, text in comments]
        os.makedirs(os.path.dirname(path), exist_ok=True)
        json.dump(record, open(path, "w", encoding="utf-8"))

    def status(card):
        return next(row["status"] for row in board_cards(pack["board"]) if row["id"] == card)

    batch((1, "rename the helper"), (2, "add a test"))
    first = treat_pr(pack, ticket, name, 8)["card_id"]
    writes = BoardWrites(pack["board"])
    writes.block(first, "patch plan ready: go?", "needs_input")
    writes.flush()
    batch((3, "drop the flag"))
    second = treat_pr(pack, ticket, name, 8)
    assert second["supersedes"] == first and status(first) == "done"
    assert "One plan here covers all 3 comment(s)" in second["out"]
    assert all(
        f"{text} ({pack['name']})" in second["out"] for text in ("rename the helper", "add a test", "drop the flag")
    )
    connection = sqlite3.connect(db_path(pack["board"]))
    result = connection.execute("select result from tasks where id = ?", (first,)).fetchone()[0]
    note = connection.execute(
        "select body from task_comments where task_id = ? order by id desc limit 1", (first,)
    ).fetchone()[0]
    connection.close()
    assert (
        result.startswith(f"superseded: 1 newer comment(s) on {name}#8")
        and note == f"superseded by {second['card_id']}: its comments are planned there"
    )
    treatments = json.load(open(record_path(ticket, name, 8), encoding="utf-8"))["treatments"]
    assert [row["card"] for row in treatments] == [first, second["card_id"]] and treatments[1]["supersedes"] == first
    assert [comment["id"] for comment in treatments[1]["comments"]] == [1, 2, 3]
    # Past its plan, the card keeps running and a new batch waits as before.
    card = second["card_id"]
    for past in ("running", "plan ok", "an intent"):
        writes.block(card, "patch plan ready: go?", "needs_input")
        writes.flush()
        if past == "running":
            writes.unblock(card)
            writes.flush()
        if past == "plan ok":
            writes.comment(card, "human", "human: plan ok")
            writes.flush()
        if past == "an intent":
            connection = sqlite3.connect(db_path(pack["board"]))
            connection.execute("delete from task_comments where task_id = ? and body = 'human: plan ok'", (card,))
            connection.commit()
            connection.close()
            create(
                pack, ticket, "pr-comment", card, "reply", {"repo": name, "number": 8, "body": "done in the next push"}
            )
        batch((4, "one more"))
        with pytest.raises(Conflict, match=f"already open: card {card}"):
            treat_pr(pack, ticket, name, 8)
        assert status(card) != "done"
    assert _other(pack)["name"] not in json.dumps(treatments)


@pytest.mark.parametrize("pack_file", PACKS)
def test_the_bump_scan_reads_only_watched_repos(env, pack_file, monkeypatch, tmp_path):
    import shutil

    import yaml

    from cockpitlib.acts import scan_bumps, visible_bumps
    from cockpitlib.errors import PackError
    from cockpitlib.pack import shipped, watched

    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    pack = load(pack_file)
    product, tooling = (repo["name"] for repo in pack["repos"]["repos"][:2])
    assert all(shipped(repo) and watched(repo) for repo in pack["repos"]["repos"])
    pack["repos"]["repos"][1]["watched"] = (
        False  # a repo the watches leave out; shipped alone keeps only the advisories away
    )
    asked = []

    class Listed:
        returncode, stderr = 0, ""

        def __init__(self, body):
            self.stdout = body

    def runner(argv):
        target = argv[argv.index("--repo") + 1]
        asked.append(target.rsplit("/", 1)[-1])
        return Listed(
            json.dumps(
                [
                    {
                        "number": 3,
                        "title": f"bump {pack['name']}",
                        "headRefName": "dependabot/npm",
                        "headRefOid": "abc",
                        "author": {"login": "dependabot"},
                        "files": [],
                    }
                ]
            )
        )

    assert scan_bumps(pack, runner=runner) == "bumps 1"
    assert asked == [product] and list(visible_bumps().get("repos", {})) == [product]
    name = os.path.basename(os.path.dirname(pack_file))
    copied = tmp_path / "packs" / name
    shutil.copytree(os.path.dirname(pack_file), copied)
    raw = yaml.safe_load((copied / "repos.yaml").read_text(encoding="utf-8"))
    raw["repos"][1]["shipped"] = "no"
    (copied / "repos.yaml").write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")
    with pytest.raises(PackError, match=f"repos.yaml {tooling}: shipped is true or false"):
        load(str(copied / "pack.yaml"))
    raw["repos"][1]["shipped"] = False
    (copied / "repos.yaml").write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")
    assert not shipped(load(str(copied / "pack.yaml"))["repos"]["repos"][1])


@pytest.mark.parametrize("pack_file", PACKS)
def test_the_stack_watch_raises_one_row_per_uncovered_production_alert(env, pack_file, monkeypatch, capsys):
    from cockpitlib.acts import _write, bumps_path
    from cockpitlib.advisories import sources
    from cockpitlib.advisories.scan import state
    from cockpitlib.ops import advisories_scan
    from cockpitlib.paths import watch_dir
    from tests.support.advisory_feeds import feeds, stack

    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    monkeypatch.delenv("COCKPIT_LANE", raising=False)
    pack = load(pack_file)
    made = stack(env["root"], pack)
    fetch, ids = feeds(pack)
    monkeypatch.setattr(sources, "http", fetch)
    told = advisories_scan(pack)
    named = pack["advisories"]["sources"]
    assert f"sources ok {len(named)} of {len(named)}" in told
    record = state()
    assert sorted(record["sources"]) == sorted(named) and set(_other(pack)["advisories"]["sources"]) - set(
        named
    ) <= set(sources.NAMES) - set(record["sources"])
    by_id = {row["id"]: row for row in record["advisories"]}
    critical = by_id[f"CVE-2026-{len(pack['name'])}001"]  # the OSV entry, under its CVE alias
    assert critical["alert"] and critical["status"] == "fix-available" and critical["hits"][0]["name"] == made["parser"]
    dev = by_id[ids["high"]]
    assert dev["hits"] and not dev["hits"][0]["production"] and not dev["alert"]
    exploited = by_id.get("CVE-2026-7001")
    assert (exploited is not None and exploited["exploited"] and exploited["alert"]) is ("kev" in named)
    assert (any(row["source"] == "hn" and row["status"] == "candidate" for row in record["advisories"])) is (
        "hn" in named
    )
    php = next((row for row in record["advisories"] if row["source"] == "php.net" and row["hits"]), None)
    assert (php is not None and php["severity"] == "high" and not php["alert"]) is (
        "php.net" in named
    )  # bravo raises no row for a high
    assert json.load(open(os.path.join(watch_dir(), "advisories.json"), encoding="utf-8"))["ok"]
    # A bump PR that already bumps the package covers it: the fix is in flight, no row.
    _write(
        bumps_path(),
        {
            "repos": {
                made["repo"]: [
                    {"number": 31, "title": f"Bump {made['parser']} from 1.2.0 to 1.2.4", "url": "u", "head": "h"}
                ]
            }
        },
    )
    advisories_scan(pack)
    covered = next(row for row in state()["advisories"] if row["id"] == critical["id"])
    assert covered["bump_prs"][0]["number"] == 31 and not covered["alert"]
    _write(bumps_path(), {"repos": {}})
    advisories_scan(pack)
    # The page: ack with a note hides the row and keeps it; unack brings it back; one analyst card while it is open.
    client = _client()
    assert (
        client.post("/advisory-ack", json={"id": critical["id"], "note": f"patched by hand ({pack['name']})"})
        .json()["advisory"]["acknowledged"]["note"]
        .endswith(f"({pack['name']})")
    )
    listed = {row["id"]: row for row in client.get("/advisories").json()["advisories"]}
    assert not listed[critical["id"]]["alert"] and listed[critical["id"]]["status"] == "acknowledged"
    advisories_scan(pack)
    assert next(row for row in state()["advisories"] if row["id"] == critical["id"])[
        "acknowledged"
    ]  # survives a rescan
    assert client.post("/advisory-unack", json={"id": critical["id"]}).json()["advisory"]["alert"]
    assert client.post("/advisory-ack", json={"id": "nope"}).status_code == 404
    assert client.post("/advisory-ack", json={"id": "../x"}).status_code == 400
    card = client.post("/advisory-card", json={"id": critical["id"]}).json()
    assert card["ok"] and card["card_id"]
    assert client.post("/advisory-card", json={"id": critical["id"]}).status_code == 409
    assert client.post("/advisory-card", json={"id": "OSV-none"}).status_code == 400
    from cockpitlib.kanban import board_cards

    row = next(found for found in board_cards(pack["board"]) if found["id"] == card["card_id"])
    assert row["assignee"].startswith("analyst") and critical["id"] in row["title"]
    page = client.get("/advisories").json()
    assert page["manifest"]["components"]["package"] >= 2 and page["sources"]
    # The command line.
    assert main(["advisories", "list"]) == 0 and "ALERT critical" in capsys.readouterr().out
    assert (
        main(["advisories", "ack", critical["id"], "--note", "seen"]) == 0 and "acknowledged" in capsys.readouterr().out
    )
    assert main(["advisories", "unack", critical["id"]]) == 0 and "back in the Inbox" in capsys.readouterr().out
    assert main(["advisories", "ack", "OSV-none"]) == 1
    assert (
        main(["advisories"]) == 2
        and main(["advisories", "scan", "x"]) == 2
        and main(["advisories", "ack"]) == 2
        and main(["advisories", "list", "x"]) == 2
    )
    monkeypatch.setenv("COCKPIT_LANE", "worker-1")
    assert main(["advisories", "ack", critical["id"]]) == 2
    monkeypatch.delenv("COCKPIT_LANE")
    assert main(["advisories", "scan"]) == 0
    capsys.readouterr()
    # A failed source is recorded and the watch stays green; every source failing turns it red.
    fetch, _ids = feeds(pack, fail=(named[0],))
    monkeypatch.setattr(sources, "http", fetch)
    assert f"failed {named[0]}: OSError" in advisories_scan(pack)
    assert json.load(open(os.path.join(watch_dir(), "advisories.json"), encoding="utf-8"))["ok"]
    fetch, _ids = feeds(pack, fail=tuple(sources.NAMES))
    monkeypatch.setattr(sources, "http", fetch)
    advisories_scan(pack)
    assert not json.load(open(os.path.join(watch_dir(), "advisories.json"), encoding="utf-8"))["ok"]
    assert any(row["id"] == critical["id"] for row in state()["advisories"])  # kept while it still hits
    # A pack without the block: off. A repo that does not ship: not read.
    assert advisories_scan({**pack, "advisories": None}).startswith("off")
    from cockpitlib.advisories.manifest import repos

    pack["repos"]["repos"][0]["shipped"] = False
    assert made["repo"] not in [name for name, _path in repos(pack)]
    assert _other(pack)["name"] not in json.dumps(state())


@pytest.mark.parametrize("pack_file", PACKS)
def test_a_card_shows_its_own_pull_requests_and_the_ticket_groups_them(env, pack_file, monkeypatch):
    from cockpitlib.acts import _write, bumps_path, describe_ticket
    from cockpitlib.kanban import place_card
    from cockpitlib.kickoff import batch_key
    from cockpitlib.pr_watch import card_prs, record_path

    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    pack = load(pack_file)
    mine, other = (repo["name"] for repo in pack["repos"]["repos"][:2])
    batch = batch_key(pack)

    def watched(ticket, repo, number, **over):
        path = record_path(ticket, repo, number)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        json.dump(
            {
                "repo": repo,
                "number": number,
                "url": f"https://git.example.test/{repo}/pull/{number}",
                "state": "open",
                "merged": False,
                "title": f"{pack['name']} {repo} {number}",
                **over,
            },
            open(path, "w", encoding="utf-8"),
        )

    for repo, number, over in (
        (mine, 11, {}),
        (mine, 12, {}),
        (mine, 9, {"merged": True, "state": "closed"}),
        (other, 21, {}),
    ):
        watched(batch, repo, number, **over)
    bump = place_card(
        pack["board"], f"{batch}: bumps on {mine}", "reviewer", "ready", kind="bumps", ticket=batch, key=mine
    )
    _write(
        bumps_path(),
        {
            "repos": {mine: [{"number": 13, "title": "bump only listed", "sha": "s"}]},
            "started": {
                f"{mine}#11": {"card": bump, "sha": "s"},
                f"{mine}#9": {"card": bump},
                f"{mine}#13": {"card": bump},
                f"{mine}#14": {"card": bump},
                f"{mine}#12": {"card": "t_other"},
                f"{other}#21": {"card": "t_other"},
            },
        },
    )
    shown = card_prs(pack, bump, batch)
    assert [(row["repo"], str(row["number"]), row["closed"]) for row in shown] == [
        (mine, "11", False),
        (mine, "13", False),
        (mine, "14", False),
        (mine, "9", True),
    ]
    ticket = f"{pack['tracker']['project']}-1501"
    watched(ticket, mine, 31)
    watched(ticket, other, 41, merged=True)
    watched(ticket, other, 42)
    work = place_card(pack["board"], f"{ticket}: work", "worker-1", "ready", kind="work", ticket=ticket, repos=[other])
    assert [(row["repo"], row["number"], row["closed"]) for row in card_prs(pack, work, ticket)] == [
        (other, 42, False),
        (other, 41, True),
    ]
    loose = place_card(
        pack["board"], f"{ticket}: review", "reviewer", "ready"
    )  # no kind recorded: every PR of the ticket
    assert {row["number"] for row in card_prs(pack, loose, ticket)} == {31, 41, 42}
    detail = _client().get(f"/card-detail?id={work}").json()
    assert [row["number"] for row in detail["prs"]] == [42, 41]
    assert [(row["repo"], row["number"]) for row in describe_ticket(pack, ticket)["prs"]] == sorted(
        [(mine, 31), (other, 42)]
    ) + [(other, 41)]
    assert _other(pack)["name"] not in json.dumps(detail["prs"])
