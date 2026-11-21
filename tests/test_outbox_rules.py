# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The outbox is the only door: who may hold, drop and publish, what a chain shows, and what a publish refuses."""

import io
import json
import os

import pytest

from cockpitlib.cli import main
from cockpitlib.errors import CockpitError
from cockpitlib.pack import load
from tests.support.both_packs import PACKS, ROOT, _client


@pytest.mark.parametrize("pack_file", PACKS)
def test_a_lane_cannot_hold_or_drop(env, pack_file, monkeypatch, capsys):
    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    monkeypatch.setenv("COCKPIT_LANE", "worker-1")
    pack = load(pack_file)
    other = load(PACKS[0] if pack["name"] == "bravo" else PACKS[1])
    repo = pack["repos"]["repos"][0]["name"]
    assert repo != other["repos"]["repos"][0]["name"]
    from cockpitlib.intents import load as load_intent
    from cockpitlib.outbox import create

    ticket = "TASK-1018"
    row = create(pack, ticket, "push-branch", "c", "ship", {"repo": repo, "branch": "main"})
    client = _client()
    held = client.post("/hold", json={"id": row["id"], "reason": f"wait {pack['name']}"})
    dropped = client.post("/drop", json={"id": row["id"], "note": "no"})
    assert held.status_code == 400 and "human" in held.text
    assert dropped.status_code == 400 and "human" in dropped.text
    assert other["name"] not in held.text
    assert main(["outbox", "hold", row["id"], "why"]) == 1
    assert "human" in capsys.readouterr().err
    assert main(["outbox", "drop", row["id"]]) == 1
    assert load_intent(row["id"])["status"] == "pending"
    monkeypatch.delenv("COCKPIT_LANE", raising=False)
    assert client.post("/hold", json={"id": row["id"], "reason": f"wait {pack['name']}"}).status_code == 200
    assert load_intent(row["id"])["status"] == "held"
    assert client.post("/drop", json={"id": row["id"], "note": "no"}).status_code == 200
    assert load_intent(row["id"])["status"] == "dropped"


@pytest.mark.parametrize("pack_file", PACKS)
def test_a_lane_cannot_publish_or_discard(env, pack_file, monkeypatch):
    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    monkeypatch.setenv("COCKPIT_LANE", "worker-1")
    pack = load(pack_file)
    other = load(PACKS[0] if pack["name"] == "bravo" else PACKS[1])
    assert pack["name"] != other["name"]
    from cockpitlib.intents import load as load_intent
    from cockpitlib.intents import save
    from cockpitlib.outbox import create, endorse

    ticket = f"{pack['tracker']['project']}-1044"
    repo = pack["repos"]["repos"][0]["name"]
    row = create(pack, ticket, "push-branch", "c", "ship", {"repo": repo, "branch": "main"})
    row = endorse(row["id"], "low", "", "gatekeeper", "fixture-a", "fixture-large")
    refused = _client().post("/publish", json={"id": row["id"], "confirm": row["id"]})
    assert refused.status_code == 400
    assert "lane cannot publish" in refused.text
    assert other["name"] not in refused.text
    assert load_intent(row["id"])["status"] == "endorsed"
    review = create(
        pack,
        ticket,
        "pr-review-submit",
        "c",
        "review",
        {"repo": repo, "number": 4, "sha": "d" * 40, "event": "COMMENT", "body": "note"},
    )
    review = endorse(review["id"], "low", "", "gatekeeper", "fixture-a", "fixture-large")
    review["status"] = "posted"
    save(review)
    discarded = _client().post("/review-discard", json={"id": review["id"], "confirm": review["id"]})
    assert discarded.status_code == 400
    assert "lane cannot publish" in discarded.text
    assert load_intent(review["id"])["status"] == "posted"


@pytest.mark.parametrize("pack_file", PACKS)
def test_publish_stops_when_the_remote_readback_does_not_match(env, pack_file, monkeypatch):
    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    monkeypatch.delenv("COCKPIT_LANE", raising=False)
    pack = load(pack_file)
    other = load(PACKS[0] if pack["name"] == "bravo" else PACKS[1])
    repo = pack["repos"]["repos"][0]["name"]
    assert repo != other["repos"]["repos"][0]["name"]
    from cockpitlib.intents import load as load_intent
    from cockpitlib.outbox import create, endorse
    from tests.support import fake_gh

    ticket = "TASK-1017"
    fake_gh.commit(repo, f"work/{ticket}")
    row = create(pack, ticket, "push-branch", "c", "ship", {"repo": repo, "branch": f"work/{ticket}"})
    row = endorse(row["id"], "low", "", "gatekeeper", "fixture-a", "fixture-large")
    # The remote takes the push, then drops the branch again: what it holds afterwards is not what was sent.
    hook = env["root"] / "remotes" / f"{repo}.git" / "hooks" / "post-receive"
    hook.write_text('#!/bin/sh\nwhile read old new ref; do git update-ref -d "$ref"; done\n', encoding="utf-8")
    hook.chmod(0o755)
    refused = _client().post("/publish", json={"id": row["id"], "confirm": row["id"]})
    assert refused.status_code == 400 and "read-back" in refused.text
    assert other["forge"]["org"] not in refused.text
    stayed = load_intent(row["id"])
    assert stayed["status"] == "endorsed"
    assert stayed.get("receipt", {}).get("ok") is False


def _cockpit_hooks():
    import importlib.util

    class Ctx:
        def __init__(self):
            self.hooks = {}

        def register_skill(self, name, path):
            pass

        def register_hook(self, event, fn):
            self.hooks[event] = fn

    spec = importlib.util.spec_from_file_location("cockpit_plugin_hooks", os.path.join(ROOT, "__init__.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    ctx = Ctx()
    module.register(ctx)
    return ctx.hooks


def _viewed(name, ok=True, **extra):
    return json.dumps({"success": ok, "name": name.split(":")[-1], "content": "x", **extra})


@pytest.mark.parametrize("pack_file", PACKS)
def test_an_intent_counts_only_the_skills_its_own_lane_loaded(env, pack_file, monkeypatch):
    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    monkeypatch.delenv("COCKPIT_LANE", raising=False)
    pack = load(pack_file)
    other = load(PACKS[0] if pack["name"] == "bravo" else PACKS[1])
    repo = pack["repos"]["repos"][0]["name"]
    from cockpitlib.intents import load as load_intent
    from cockpitlib.intents import save
    from cockpitlib.kanban import place_card
    from cockpitlib.outbox import create, endorse
    from cockpitlib.publish import execute
    from cockpitlib.skill_log import loaded, log_path
    from tests.support.boards import raw
    from tests.support.hermes_contract import call

    board = pack["board"]
    ticket = "NORTH-1016" if pack["name"] == "bravo" else "TASK-1016"
    required = pack["skills"]["intent"]["pr-comment"]
    assert required == ["pr-review"]
    choice_type, choice = next(
        (kind, names[0]) for kind, names in pack["skills"]["intent"].items() if names and isinstance(names[0], list)
    )
    other_choice = next(
        kind for kind, names in other["skills"]["intent"].items() if names and isinstance(names[0], list)
    )
    assert choice_type != other_choice

    def note(lane, card="c", text="note"):
        return create(
            pack,
            ticket,
            "pr-comment",
            card,
            text,
            {"repo": repo, "number": 2, "body": f"{text} {pack['name']}"},
            created_by=lane,
        )

    made = note("reviewer")
    assert made["status"] == "held" and made["hold"] == {
        **made["hold"],
        "reason": "missing skill: pr-review",
        "waits": "lane",
    }
    assert note("human")["status"] == "pending"

    # The held intent's publish is refused while the gap stays.
    absent = endorse(made["id"], "low", "", "gatekeeper", "fixture-a", "fixture-large")
    refused = _client().post("/publish", json={"id": absent["id"], "confirm": absent["id"]})
    assert refused.status_code == 400 and "missing skill" in refused.text
    assert load_intent(absent["id"])["status"] == "held"

    # The hook records what Hermes's skill_view loaded, for the lane and the ticket of the card it runs.
    hooks = _cockpit_hooks()
    card = place_card(board, f"{ticket}: review", "reviewer", "ready")
    other_card = place_card(board, f"{ticket}: work", "worker-1", "ready")
    monkeypatch.setenv("HERMES_KANBAN_TASK", other_card)
    monkeypatch.setenv("COCKPIT_LANE", "worker-1")
    result = call(
        hooks["transform_tool_result"],
        "transform_tool_result",
        tool_name="skill_view",
        args={"name": "pr-review"},
        result=_viewed("pr-review"),
    )
    assert result is None
    assert loaded(ticket, "worker-1") == ["pr-review"] and loaded(ticket, "reviewer") == []
    monkeypatch.delenv("COCKPIT_LANE")
    assert note("reviewer")["status"] == "held"
    monkeypatch.setenv("COCKPIT_LANE", "reviewer")
    monkeypatch.setenv("HERMES_KANBAN_TASK", card)
    for args, text in (
        ({"name": "pr-review", "file_path": "references/a.md"}, _viewed("pr-review")),
        ({"name": "pr-review"}, _viewed("pr-review", ok=False)),
        ({"name": "pr-review"}, "not json"),
        ("pr-review", _viewed("pr-review")),
    ):
        call(hooks["transform_tool_result"], "transform_tool_result", tool_name="skill_view", args=args, result=text)
    call(
        hooks["transform_tool_result"],
        "transform_tool_result",
        tool_name="read_file",
        args={"name": "pr-review"},
        result=_viewed("pr-review"),
    )
    assert not os.path.exists(log_path(ticket, "reviewer"))
    call(
        hooks["transform_tool_result"],
        "transform_tool_result",
        tool_name="skill_view",
        args={"name": "workspace/pr-review"},
        result=_viewed("pr-review"),
    )
    call(
        hooks["transform_tool_result"],
        "transform_tool_result",
        tool_name="skill_view",
        args={"name": "cockpit:outbox"},
        result=_viewed("cockpit:outbox"),
    )
    assert loaded(ticket, "reviewer") == ["pr-review", "cockpit:outbox"]
    monkeypatch.setenv("HERMES_KANBAN_TASK", "t_gone")
    call(
        hooks["transform_tool_result"],
        "transform_tool_result",
        tool_name="skill_view",
        args={"name": "jira-tickets"},
        result=_viewed("jira-tickets"),
    )
    assert "jira-tickets" not in loaded(ticket, "reviewer")
    monkeypatch.delenv("COCKPIT_LANE")
    monkeypatch.delenv("HERMES_KANBAN_TASK")
    from tests.support import fake_gh

    fake_gh.pull(f"{pack['forge']['org']}/{repo}", 2, f"work/{ticket}", "a" * 40)
    ready = endorse(note("reviewer", card)["id"], "low", "", "gatekeeper", "fixture-a", "fixture-large", pack=pack)
    assert execute(ready, pack=pack)["ok"] is True
    save(ready)
    assert load_intent(ready["id"])["status"] == "published"

    # A skill the card carries is loaded for the lane the card is assigned to, and only for it.
    carried = place_card(board, f"{ticket}: test", "tester-1", "ready", skills=[choice[-1]])
    assert (
        create(pack, ticket, choice_type, carried, "x", {"body": "x", "summary": "x"}, created_by="tester-1")["status"]
        == "pending"
    )
    assert (
        create(pack, ticket, choice_type, carried, "x", {"body": "x", "summary": "x"}, created_by="tester-2")["status"]
        == "held"
    )

    # While the lane's card still runs, the gap only defers the intent; it is held once the run has ended.
    connection = raw(board)
    connection.execute("update tasks set status = 'running' where id = ?", (other_card,))
    connection.commit()
    waiting = create(pack, ticket, choice_type, other_card, "x", {"body": "x", "summary": "x"}, created_by="worker-1")
    assert waiting["status"] == "pending" and waiting["skills_deferred"] == [" or ".join(choice)]
    with pytest.raises(CockpitError, match="deferred while the lane runs"):
        endorse(waiting["id"], "low", "", "gatekeeper", "fixture-a", "fixture-large", pack=pack)
    from cockpitlib.skill_log import append

    append(ticket, "worker-1", choice[0])
    cleared = endorse(waiting["id"], "low", "", "gatekeeper", "fixture-a", "fixture-large", pack=pack)
    assert cleared["status"] == "endorsed" and "skills_deferred" not in load_intent(waiting["id"])
    late = create(
        pack,
        ticket,
        "pr-edit",
        other_card,
        "x",
        {"repo": repo, "number": 2, "add_labels": ["late"]},
        created_by="worker-1",
    )
    assert late["skills_deferred"]
    connection.execute("update tasks set status = 'done' where id = ?", (other_card,))
    connection.commit()
    connection.close()
    with pytest.raises(CockpitError, match="missing skill: open-prs"):
        endorse(late["id"], "low", "", "gatekeeper", "fixture-a", "fixture-large", pack=pack)
    assert load_intent(late["id"])["status"] == "held"

    # The command line names the lane that ran it.
    monkeypatch.setenv("COCKPIT_LANE", "reviewer")
    import contextlib

    printed = io.StringIO()
    with contextlib.redirect_stdout(printed):
        assert (
            main(
                [
                    "outbox",
                    "new",
                    ticket,
                    "pr-comment",
                    "--card",
                    card,
                    "--summary",
                    "from the lane",
                    "--repo",
                    repo,
                    "--number",
                    "2",
                    "--body",
                    f"from {pack['name']}",
                ]
            )
            == 0
        )
    assert load_intent(printed.getvalue().splitlines()[0])["created_by"] == "reviewer"


# Each fixture's staging origin and never-write path, its human browser port, and its local domain.
STAGING = {
    "acme": {"origin": "staging.acme.test", "never": "/billing/", "domain": "build.acme.internal"},
    "bravo": {"origin": "qa.north.test", "never": "/fleet/", "domain": "box7.north.lan"},
}


@pytest.mark.parametrize("pack_file", PACKS)
def test_staging_writes_the_lent_browser_and_local_references(env, pack_file, monkeypatch):
    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    pack = load(pack_file)
    other_pack = load(PACKS[0] if pack["name"] == "bravo" else PACKS[1])
    own = STAGING[pack["name"]]
    other = STAGING["bravo" if pack["name"] == "acme" else "acme"]
    from cockpitlib.acts import _accept_plan, post_test_plan
    from cockpitlib.egress import check_tool
    from cockpitlib.kanban import place_card
    from cockpitlib.outbox import create, verify
    from cockpitlib.paths import records_name, watch_dir
    from tests.support.boards import set_body

    ticket = f"{pack['tracker']['project']}-90"
    put = f"PUT https://{own['origin']}/api/items/7"
    post_test_plan(pack, ticket, f"rows for {pack['name']}\n{put}\nPOST https://{own['origin']}{own['never']}refund\n")
    monkeypatch.setenv("COCKPIT_LANE", "tester-1")
    monkeypatch.setenv("COCKPIT_TICKET", ticket)

    def shell(line):
        return check_tool("terminal", {"command": line})

    assert shell(f"curl -X PUT https://{own['origin']}/api/items/7 -d @row.json") == "the plan is not accepted: " + put
    _accept_plan(ticket, pack)
    assert shell(f"curl -X PUT https://{own['origin']}/api/items/7 -d @row.json") == ""
    assert (
        check_tool(
            "execute_code", {"code": f"import requests; requests.put('https://{own['origin']}/api/items/7', json={{}})"}
        )
        == ""
    )
    assert shell(f"curl -X PUT https://{own['origin']}/api/items/8 -d x").startswith(
        "the accepted plan does not list that request"
    )
    assert (
        shell(f"curl -X DELETE https://{own['origin']}/api/items/7")
        == f"never written: DELETE https://{own['origin']}/api/items/7"
    )
    assert shell(f"curl -d x https://{own['origin']}{own['never']}refund").startswith("never written")
    assert (
        shell(
            f"curl -X PUT https://{own['origin']}/api/items/7 -d x; curl -X PUT https://{own['origin']}/api/items/7 -d x"
        )
        == "one write to staging per call"
    )
    loose = check_tool(
        "execute_code",
        {"code": f"base = 'https://{own['origin']}'\nimport requests; requests.post(base + '/api/items', json={{}})"},
    )
    assert loose == "a write to staging names one literal URL"
    assert shell(f"curl https://{own['origin']}/api/items/7") == ""
    assert shell(f"curl -X PUT https://{other['origin']}/api/items/7 -d x") == ""
    monkeypatch.delenv("COCKPIT_LANE")
    assert shell(f"curl -X DELETE https://{own['origin']}/api/items/7") == ""

    # The lent browser answers only the ticket it was lent to, by its port, a DevTools call, or a URL, and of that
    # ticket only the test kickoff card started with it: a worker card of the same ticket runs on the built-in browser.
    port = str(pack["human_browser_port"])
    assert port != str(other_pack["human_browser_port"])
    lent = f"{pack['tracker']['project']}-91"
    worker = place_card(pack["board"], f"{lent}: work", "worker-1", "ready")
    set_body(pack["board"], worker, "browser lent for the step\n")
    card = place_card(pack["board"], f"{lent}: test", "tester-1", "ready", kind="test", ticket=lent, pack=pack)
    set_body(pack["board"], card, "browser lent for the step\n")
    os.makedirs(watch_dir(), exist_ok=True)
    open(os.path.join(watch_dir(), "shared-chrome.json"), "w", encoding="utf-8").write(
        json.dumps({"ticket": lent, "until": 9_999_999_999, "tabs": []})
    )
    monkeypatch.setenv("COCKPIT_LANE", "worker-1")
    monkeypatch.delenv("COCKPIT_TICKET")
    monkeypatch.setenv("HERMES_KANBAN_TASK", worker)
    assert shell(f"curl http://127.0.0.1:{port}/json/version") == "blocked"
    monkeypatch.setenv("COCKPIT_LANE", "tester-1")
    monkeypatch.setenv("HERMES_KANBAN_TASK", card)
    assert shell(f"curl http://127.0.0.1:{port}/json/version") == ""
    assert check_tool("browser_navigate", {"url": f"http://127.0.0.1:{port}/json"}) == ""
    stranger = place_card(pack["board"], f"{pack['tracker']['project']}-92: work", "worker-2", "ready")
    monkeypatch.setenv("HERMES_KANBAN_TASK", stranger)
    assert shell(f"curl http://127.0.0.1:{port}/json/version") == "the browser is lent to another ticket"
    assert (
        check_tool("browser_navigate", {"url": f"http://localhost:{port}/devtools/page/1"})
        == "the browser is lent to another ticket"
    )
    assert (
        check_tool("execute_code", {"code": "await puppeteer.connect({browserWSEndpoint: ws})"})
        == "the browser is lent to another ticket"
    )
    assert check_tool("execute_code", {"code": "chrome-remote-interface --port 9500 list"}) == ""
    assert shell(f"curl http://127.0.0.1:{other_pack['human_browser_port']}/json") == ""

    # A local domain, a temp path, and the records folder never reach the tracker or the forge.
    monkeypatch.delenv("COCKPIT_LANE")
    for body, reason in (
        (f"built on {own['domain']}", "a local domain"),
        ("see /tmp/run.log", "a temp path"),
        (f"see {records_name()}/watch/ci.json", "a records path"),
    ):
        with pytest.raises(CockpitError, match=f"local reference: {reason}"):
            create(pack, ticket, "tracker-comment", "c", "x", {"body": body})
    fine = create(pack, ticket, "tracker-comment", "c", "x", {"body": f"built on {other['domain']}"})
    fine["payload"]["body"] = f"built on {own['domain']}"
    assert "local reference: a local domain" in verify(intent=fine)


@pytest.mark.parametrize("pack_file", PACKS)
def test_a_finished_ticket_without_a_pull_request_is_acknowledged(env, pack_file, monkeypatch):
    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    pack = load(pack_file)
    from cockpitlib.intents import load as load_intent
    from cockpitlib.intents import save
    from cockpitlib.outbox import create
    from cockpitlib.paths import platform_dir, qa

    other = load(PACKS[0] if pack["name"] == "bravo" else PACKS[1])
    assert pack["name"] != other["name"]
    ended = create(pack, "TASK-990", "ticket-done", "c", "finished", {})
    ended["status"] = "published"
    save(ended)
    numbered = create(
        pack,
        "TASK-991",
        "pr-comment",
        "c",
        "note",
        {"repo": pack["repos"]["repos"][0]["name"], "number": 4, "body": "hi"},
    )
    numbered["status"] = "published"
    save(numbered)
    kept = create(pack, "TASK-991", "ticket-done", "c", "finished", {})
    kept["status"] = "published"
    save(kept)

    from cockpitlib.ops import watch_pr
    from cockpitlib.paths import watch_dir
    from tests.support import fake_gh

    repo = pack["repos"]["repos"][0]["name"]
    other_repo = other["repos"]["repos"][0]["name"]
    message = watch_pr(pack)
    assert (
        message.startswith("forge")
        and f"{repo}#4" in message
        and f"{other['forge']['org']}/{other_repo}" not in message
    )
    health = json.load(open(os.path.join(watch_dir(), "pr-watch.json"), encoding="utf-8"))
    assert health["ok"] is False and repo in health["summary"]
    acked = load_intent(ended["id"])
    assert acked["status"] == "acknowledged"
    record = json.load(open(os.path.join(qa(), "TASK-990", "acknowledged.json"), encoding="utf-8"))
    assert record["pack"] == pack["name"] and record["why"] == "ended without a pull request"
    assert load_intent(kept["id"])["status"] == "published"
    again = json.load(open(os.path.join(platform_dir(), "pr-watch.json"), encoding="utf-8"))
    assert ended["id"] in again["acknowledged"]
    fake_gh.setup(me=pack["forge"]["human_login"], repos=[f"{pack['forge']['org']}/{repo}"])
    fake_gh.pull(f"{pack['forge']['org']}/{repo}", 4, "work/x", "a" * 40)
    cleared = watch_pr(pack)
    assert cleared.startswith("pr-watch")
    second = json.load(open(os.path.join(platform_dir(), "pr-watch.json"), encoding="utf-8"))
    assert ended["id"] not in second["acknowledged"] and load_intent(ended["id"])["status"] == "acknowledged"
    health = json.load(open(os.path.join(watch_dir(), "pr-watch.json"), encoding="utf-8"))
    assert health["ok"] is True


@pytest.mark.parametrize("pack_file", PACKS)
def test_a_chain_stays_hidden_until_the_next_intent_is_endorsed(env, pack_file, monkeypatch):
    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    pack = load(pack_file)
    other = load(PACKS[0] if pack["name"] == "bravo" else PACKS[1])
    repo = pack["repos"]["repos"][0]["name"]
    assert repo != other["repos"]["repos"][0]["name"]
    from cockpitlib.intents import ORDER
    from cockpitlib.outbox import create, endorse

    ticket = "TASK-9950"
    push = create(pack, ticket, "push-branch", "c", "ship", {"repo": repo, "branch": "main"})
    comment = create(
        pack,
        ticket,
        "pr-comment",
        "c",
        f"note {pack['name']}",
        {"repo": repo, "number": 3, "body": "Fixed in the push"},
        created_by="reviewer",
    )
    assert comment["payload"]["after"] == push["id"]
    assert comment["status"] == "held"
    endorse(push["id"], "low", "", "gatekeeper", "fixture-a", "fixture-large")
    client = _client()
    rows = {row["id"]: row for row in client.get("/list").json()["rows"]}
    assert rows[push["id"]]["order"] == ORDER["push-branch"]
    assert rows[comment["id"]]["order"] == ORDER["pr-comment"]
    assert rows[push["id"]]["order"] < rows[comment["id"]]["order"]
    assert rows[push["id"]]["chain"]["followed_by"] == comment["id"]
    assert rows[comment["id"]]["chain"]["step1_status"] == "endorsed"
    assert other["name"] not in rows[comment["id"]]["summary"]
    inbox = [row["id"] for row in client.get("/screen").json()["inbox"]]
    assert push["id"] not in inbox
    endorse(comment["id"], "low", "", "gatekeeper", "fixture-a", "fixture-large")
    shown = {row["id"]: row for row in client.get("/list").json()["rows"]}
    assert "followed_by" not in shown[push["id"]].get("chain", {})
    inbox = [row["id"] for row in client.get("/screen").json()["inbox"]]
    assert push["id"] in inbox


@pytest.mark.parametrize("pack_file", PACKS)
def test_tracker_evidence_is_attached_as_public_links(env, pack_file, monkeypatch):
    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    pack = load(pack_file)
    other = load(PACKS[0] if pack["name"] == "bravo" else PACKS[1])
    from cockpitlib.acts import _public_origin, attach_evidence, keep_created, post_test_plan
    from cockpitlib.intents import load as load_intent
    from cockpitlib.intents import save
    from cockpitlib.outbox import create
    from cockpitlib.paths import qa
    from cockpitlib.test_flow import evidence_dir

    ticket = "TASK-881"
    posted = post_test_plan(pack, ticket, f"plan {pack['name']}\n")
    repo = pack["repos"]["repos"][0]["name"]
    assert repo != other["repos"]["repos"][0]["name"]
    create(pack, ticket, "push-branch", "c", "ship", {"repo": repo, "branch": "main"})
    shots = os.path.join(qa(), ticket, evidence_dir(pack))
    os.makedirs(shots, exist_ok=True)
    open(os.path.join(shots, "row.png"), "wb").write(pack["name"].encode())
    created = keep_created(ticket, "ada", {"id": 1}, pack)
    created_dir = os.path.join(qa(), ticket, "created")
    open(os.path.join(created_dir, "dup.json"), "w", encoding="utf-8").write(json.dumps({"link": created["link"]}))
    open(os.path.join(created_dir, "empty.json"), "w", encoding="utf-8").write(json.dumps({"link": ""}))
    open(os.path.join(created_dir, "list.json"), "w", encoding="utf-8").write("[]")
    open(os.path.join(created_dir, "zzz.json"), "w", encoding="utf-8").write("{")
    links = attach_evidence(pack, ticket)
    shot = f"{created['link'].split('/data/')[0]}/evidence/{ticket}/row.png"
    assert links[0] == shot
    assert links.count(created["link"]) == 1
    assert _public_origin(other) not in "".join(links)
    tracker = load_intent(posted["intent"])
    assert tracker["payload"]["evidence"] == links
    assert tracker["payload"]["body"] == "test kickoff started"
    assert "qa/" not in json.dumps(tracker["payload"])
    bare = dict(pack)
    bare["_dir"] = str(env["root"] / "no-staging-evidence")
    os.makedirs(bare["_dir"], exist_ok=True)
    named = attach_evidence(bare, ticket)
    assert "row.png" in named
    assert shot not in named
    intent = load_intent(posted["intent"])
    intent["payload"]["body"] = "see qa/local"
    save(intent)
    with pytest.raises(CockpitError, match="local reference"):
        attach_evidence(pack, ticket)
    intent["payload"]["body"] = "test kickoff started"
    save(intent)
    open(os.path.join(created_dir, "local.json"), "w", encoding="utf-8").write(json.dumps({"link": "see localhost"}))
    with pytest.raises(CockpitError, match="local reference"):
        attach_evidence(pack, ticket)
    other_ticket = "TASK-882"
    post_test_plan(pack, other_ticket, f"plan {pack['name']}\n")
    other_shots = os.path.join(qa(), other_ticket, evidence_dir(pack))
    os.makedirs(other_shots, exist_ok=True)
    open(os.path.join(other_shots, "localhost.png"), "wb").write(b"png")
    with pytest.raises(CockpitError, match="local reference"):
        attach_evidence(pack, other_ticket)


@pytest.mark.parametrize("pack_file", PACKS)
def test_a_tracker_body_refuses_loopback_and_home(env, pack_file):
    pack = load(pack_file)
    other = load(PACKS[0] if pack["name"] == "bravo" else PACKS[1])
    from cockpitlib.intents import save
    from cockpitlib.local_refs import find_local_refs
    from cockpitlib.outbox import create, endorse, verify
    from cockpitlib.publish import execute

    loopback = f"open http://[::1]/{pack['name']}"
    home = f"notes ~/{pack['name']}"
    assert find_local_refs(loopback) == ["a loopback host"]
    assert find_local_refs(home) == ["a home path"]
    assert not find_local_refs(f"https://app.{pack['name']}.test/ok")
    assert other["name"] not in loopback
    with pytest.raises(CockpitError, match="local reference"):
        create(pack, "TASK-879", "tracker-comment", "c", "tracker", {"body": loopback})
    with pytest.raises(CockpitError, match="local reference"):
        create(pack, "TASK-879", "tracker-comment", "c", "tracker", {"body": home})
    made = create(pack, "TASK-879", "tracker-comment", "c", "tracker", {"body": f"https://app.{pack['name']}.test/ok"})
    made["payload"]["body"] = loopback
    save(made)
    assert any(item.startswith("local reference") for item in verify(made["id"]))
    endorse(made["id"], "low", "", "gatekeeper", "fixture-a", "fixture-large")
    with pytest.raises(CockpitError, match="local reference"):
        execute(made, pack=pack)


@pytest.mark.parametrize("pack_file", PACKS)
def test_publish_runs_the_parent_before_the_following_step(env, pack_file, monkeypatch):
    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    monkeypatch.delenv("COCKPIT_LANE", raising=False)
    pack = load(pack_file)
    other = load(PACKS[0] if pack["name"] == "bravo" else PACKS[1])
    repo = pack["repos"]["repos"][0]["name"]
    assert repo != other["repos"]["repos"][0]["name"]
    from cockpitlib.intents import load as load_intent
    from cockpitlib.outbox import create, endorse
    from cockpitlib.paths import qa
    from cockpitlib.publish import execute
    from tests.support import fake_gh

    full = f"{pack['forge']['org']}/{repo}"
    ticket = "TASK-1024"
    folder = os.path.join(qa(), ticket)
    os.makedirs(folder, exist_ok=True)
    needed = ((pack.get("skills") or {}).get("intent") or {}).get("open-pr") or []
    open(os.path.join(folder, "skills.log"), "w", encoding="utf-8").write("".join(f"skill:{name}\n" for name in needed))
    branch = f"work/{ticket}"
    sha = fake_gh.commit(repo, branch)
    fake_gh.head(full, branch, sha)
    parent = create(pack, ticket, "push-branch", "c", "ship", {"repo": repo, "branch": branch})
    child = create(
        pack,
        ticket,
        "open-pr",
        "c",
        "open",
        {"repo": repo, "title": pack["name"], "branch": branch, "body": f"for {pack['name']}"},
    )
    assert child["payload"]["after"] == parent["id"] and child["payload"]["remote_sha"] == sha
    parent = endorse(parent["id"], "low", "", "gatekeeper", "fixture-a", "fixture-large")
    child = endorse(child["id"], "low", "", "gatekeeper", "fixture-a", "fixture-large")
    receipt = execute(child, by_id={parent["id"]: parent}, pack=pack)
    assert receipt.get("ok") is True and fake_gh.remote(repo, branch) == sha
    made = fake_gh.state()["repos"][full]["pulls"]["1"]
    assert (made["title"], made["head"]["ref"], made["body"], made["draft"]) == (
        pack["name"],
        branch,
        f"for {pack['name']}",
        False,
    )
    assert load_intent(parent["id"])["status"] == "published"
    assert (
        child["status"] == "published"
        and child["payload"]["number"] == 1
        and child["receipt"]["url"].endswith(f"{full}/pull/1")
    )
    with pytest.raises(CockpitError, match=f"no intent {ticket}/099-push-branch"):
        create(
            pack,
            ticket,
            "open-pr",
            "c",
            "open",
            {"repo": repo, "title": "alone", "branch": branch, "after": f"{ticket}/099-push-branch"},
        )
    later = f"{branch}-b"
    fake_gh.commit(repo, later)
    blocked = create(pack, ticket, "push-branch", "c", "ship", {"repo": repo, "branch": later})
    follow = create(
        pack, ticket, "open-pr", "c", "open", {"repo": repo, "title": "later", "branch": later, "body": "b"}
    )
    assert follow["payload"]["after"] == blocked["id"]
    follow = endorse(follow["id"], "low", "", "gatekeeper", "fixture-a", "fixture-large")
    refused = _client().post("/publish", json={"id": follow["id"], "confirm": follow["id"]})
    assert refused.status_code == 400 and "both steps must be endorsed" in refused.text
    assert load_intent(follow["id"])["status"] == "endorsed"
    assert load_intent(blocked["id"])["status"] == "pending"
    endorse(blocked["id"], "low", "", "gatekeeper", "fixture-a", "fixture-large")
    hook = env["root"] / "remotes" / f"{repo}.git" / "hooks" / "pre-receive"
    hook.write_text(f"#!/bin/sh\necho 'closed for {pack['name']}' >&2\nexit 1\n", encoding="utf-8")
    hook.chmod(0o755)
    stopped = _client().post("/publish", json={"id": follow["id"], "confirm": follow["id"]})
    assert stopped.status_code == 400 and f"closed for {pack['name']}" in stopped.text
    assert load_intent(blocked["id"])["status"] == "endorsed" and load_intent(follow["id"])["status"] == "endorsed"
    assert "2" not in fake_gh.state()["repos"][full]["pulls"]


@pytest.mark.parametrize("pack_file", PACKS)
def test_a_chain_first_step_stays_hidden_until_the_next_is_endorsed(env, pack_file, monkeypatch):
    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    pack = load(pack_file)
    other = load(PACKS[0] if pack["name"] == "bravo" else PACKS[1])
    repo = pack["repos"]["repos"][0]["name"]
    assert repo != other["repos"]["repos"][0]["name"]
    from cockpitlib.outbox import create, endorse
    from dashboard.cockpit.payload import build

    first = create(pack, "TASK-1001", "push-branch", "c", "ship", {"repo": repo, "branch": "main"})
    follow = create(
        pack, "TASK-1001", "pr-comment", "c", "note", {"repo": repo, "number": 3, "body": "hi", "after": first["id"]}
    )
    endorse(first["id"], "low", "", "gatekeeper", "fixture-a", "fixture-large")
    hidden = [row["id"] for row in build(pack, {})["inbox"]]
    assert first["id"] not in hidden
    endorse(follow["id"], "low", "", "gatekeeper", "fixture-a", "fixture-large")
    shown = [row["id"] for row in build(pack, {})["inbox"]]
    assert first["id"] in shown and follow["id"] in shown


@pytest.mark.parametrize("pack_file", PACKS)
def test_a_dry_run_prints_the_full_write_and_sends_nothing(env, pack_file, monkeypatch, jira):
    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    monkeypatch.delenv("COCKPIT_LANE", raising=False)
    pack = load(pack_file)
    other = load(PACKS[0] if pack["name"] == "bravo" else PACKS[1])
    repo = pack["repos"]["repos"][0]["name"]
    assert repo != other["repos"]["repos"][0]["name"]
    from cockpitlib.outbox import create, endorse
    from cockpitlib.publish import execute
    from tests.support import fake_gh

    body = f"ship {pack['name']}"
    row = create(pack, "TASK-1002", "pr-comment", "c", "note", {"repo": repo, "number": 3, "body": body})
    row = endorse(row["id"], "low", "", "gatekeeper", "fixture-a", "fixture-large")
    receipt = execute(row, pack=pack, dry_run=True)
    assert receipt["dry_run"] is True
    assert receipt["actions"] == [
        {"method": "POST", "path": f"repos/{pack['forge']['org']}/{repo}/issues/3/comments", "body": {"body": body}}
    ]
    assert row["status"] == "endorsed" and fake_gh.writes() == []
    sha = fake_gh.commit(repo, "work/TASK-1002")
    push = endorse(
        create(pack, "TASK-1002", "push-branch", "c", "push", {"repo": repo, "branch": "work/TASK-1002"})["id"],
        "low",
        "",
        "gatekeeper",
        "fixture-a",
        "fixture-large",
        pack=pack,
    )
    printed = execute(push, pack=pack, dry_run=True)
    assert printed["output"].startswith("would push (fast-forward)") and fake_gh.remote(repo, "work/TASK-1002") == ""
    assert push["payload"]["sha"] == sha
    tracker = create(pack, "TASK-1002", "tracker-create", "c", "ticket", {"summary": f"open {pack['name']}"})
    tracker = endorse(tracker["id"], "low", "", "gatekeeper", "fixture-a", "fixture-large")
    filed = execute(tracker, pack=pack, dry_run=True)
    assert filed["actions"][0]["body"]["fields"]["summary"] == f"open {pack['name']}"
    assert filed["actions"][0]["body"]["fields"]["issuetype"] == {"name": pack["tracker"]["issue_type"]}
    assert jira.issues == {} and other["name"] not in filed["actions"][0]["body"]["fields"]["summary"]


@pytest.mark.parametrize("pack_file", PACKS)
def test_stage_two_submits_or_discards_a_pending_review(env, pack_file, monkeypatch):
    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    monkeypatch.delenv("COCKPIT_LANE", raising=False)
    pack = load(pack_file)
    other = load(PACKS[0] if pack["name"] == "bravo" else PACKS[1])
    repo = pack["repos"]["repos"][0]["name"]
    assert repo != other["repos"]["repos"][0]["name"]
    from cockpitlib.intents import load as load_intent
    from cockpitlib.intents import save
    from cockpitlib.outbox import create, endorse
    from cockpitlib.paths import workspace
    from cockpitlib.publish import discard_pending, execute, forge_for
    from tests.support import fake_gh

    full = f"{pack['forge']['org']}/{repo}"
    head = "c" * 40
    fake_gh.setup(
        me=pack["forge"]["human_login"],
        labels=["Needs Work", "Needs Review", "Approved", "Changes Wanted"],
        repos=[full],
    )
    fake_gh.pull(full, 7, "work/TASK-1003", head)
    threads = os.path.join(workspace(), "threads.json")
    open(threads, "w", encoding="utf-8").write(
        json.dumps(
            [
                {"path": f"src/{pack['name']}.py", "line": 3, "body": f"guard {pack['name']}"},
                {"path": "src/b.py", "line": 9, "side": "LEFT", "body": "drop this"},
            ]
        )
    )
    verdict = f"hold {pack['name']}"
    made = create(
        pack,
        "TASK-1003",
        "pr-review-submit",
        "c",
        "review",
        {"repo": repo, "number": 7, "sha": head, "event": "COMMENT", "body": "draft", "threads_file": threads},
    )
    row = endorse(made["id"], "low", "", "gatekeeper", "fixture-a", "fixture-large")
    receipt = execute(row, pack=pack)
    save(row)
    assert receipt["stage"] == "pending" and row["status"] == "posted"
    review = fake_gh.state()["repos"][full]["pulls"]["7"]["reviews"][str(row["review"]["id"])]
    assert review["state"] == "PENDING" and review["commit_id"] == head and len(review["comments"]) == 2
    again = create(
        pack, "TASK-1003", "pr-review-submit", "c", "review", {"repo": repo, "number": 7, "sha": head, "body": "more"}
    )
    again = endorse(again["id"], "low", "", "gatekeeper", "fixture-a", "fixture-large")
    with pytest.raises(CockpitError, match=f"pending review {row['review']['id']}"):
        assert not execute(again, pack=pack)["ok"]
        raise CockpitError(again["receipt"]["error"])

    fake_gh.fail("DELETE reviews", f"forge down {pack['name']}")
    with pytest.raises(CockpitError, match=f"forge down {pack['name']}"):
        discard_pending(load_intent(row["id"]), forge_for(pack))
    assert load_intent(row["id"])["status"] == "posted"
    data = fake_gh.state()
    data["fail"] = {}
    fake_gh.save(data)
    monkeypatch.setenv("COCKPIT_LANE", "reviewer")
    with pytest.raises(CockpitError, match="lane"):
        discard_pending(load_intent(row["id"]), forge_for(pack))
    monkeypatch.delenv("COCKPIT_LANE", raising=False)

    client = _client()
    assert client.post("/review-discard", json={"id": row["id"], "confirm": "no"}).status_code == 400
    gone = client.post("/review-discard", json={"id": row["id"], "confirm": row["id"]})
    assert gone.status_code == 200
    body = gone.json()
    assert body["status"] == "endorsed" and body["receipt"]["discarded"] is True
    assert (body["receipt"]["repo"], body["receipt"]["number"]) == (repo, 7)
    assert fake_gh.state()["repos"][full]["pulls"]["7"]["reviews"] == {}
    assert load_intent(row["id"])["payload"]["body"] == "draft"
    assert client.post("/review-discard", json={"id": row["id"], "confirm": row["id"]}).status_code == 400
    comment = endorse(
        create(pack, "TASK-1003", "pr-comment", "c", "note", {"repo": repo, "number": 7, "body": "x"})["id"],
        "low",
        "",
        "gatekeeper",
        "fixture-a",
        "fixture-large",
    )
    comment["status"] = "posted"
    save(comment)
    assert client.post("/review-discard", json={"id": comment["id"], "confirm": comment["id"]}).status_code == 400
    again = load_intent(row["id"])
    assert execute(again, pack=pack)["stage"] == "pending"
    save(again)
    from cockpitlib.paths import qa

    folder = os.path.join(qa(), "TASK-1003")
    os.makedirs(folder, exist_ok=True)
    open(os.path.join(folder, "skills.log"), "w", encoding="utf-8").write("skill:pr-review\n")
    event = "REQUEST_CHANGES" if pack["name"] == "acme" else "APPROVE"
    if event == "APPROVE":
        refused = client.post(
            "/publish", json={"id": row["id"], "confirm": row["id"], "event": event, "summary": verdict}
        )
        assert (
            refused.status_code == 400
            and "APPROVE waits for green checks" in refused.text
            and "no checks reported" in refused.text
        )
        fake_gh.checks(full, head, runs=[{"name": "suite", "status": "completed", "conclusion": "failure"}])
        assert (
            "suite: failure"
            in client.post("/publish", json={"id": row["id"], "confirm": row["id"], "event": event}).text
        )
        fake_gh.checks(full, head, runs=[{"name": "suite", "status": "completed", "conclusion": "success"}])
        data = fake_gh.state()
        data["repos"][full]["pulls"]["7"]["labels"] = ["Changes Wanted"]
        fake_gh.save(data)
    else:
        data = fake_gh.state()
        data["repos"][full]["pulls"]["7"]["labels"] = ["Needs Review"]
        fake_gh.save(data)
    submitted = client.post(
        "/publish", json={"id": row["id"], "confirm": row["id"], "event": event, "summary": verdict}
    )
    assert submitted.status_code == 200, submitted.text
    assert submitted.json()["receipt"]["stage"] == "submit"
    finished = load_intent(row["id"])
    assert finished["status"] == "published"
    assert finished["payload"]["event"] == event and finished["payload"]["body"] == verdict
    pull = fake_gh.state()["repos"][full]["pulls"]["7"]
    shown = next(iter(pull["reviews"].values()))
    assert (
        shown["state"] == {"REQUEST_CHANGES": "CHANGES_REQUESTED", "APPROVE": "APPROVED"}[event]
        and shown["body"] == verdict
    )
    rule = pack["forge"]["review_labels"][event]
    assert pull["labels"] == [label.title() for label in rule["add"]]
    assert other["forge"]["human_login"] not in json.dumps(fake_gh.calls())


@pytest.mark.parametrize("pack_file", PACKS)
def test_a_sha_mismatch_does_not_publish(env, pack_file, monkeypatch):
    import subprocess

    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    monkeypatch.delenv("COCKPIT_LANE", raising=False)
    pack = load(pack_file)
    other = load(PACKS[0] if pack["name"] == "bravo" else PACKS[1])
    name = pack["repos"]["repos"][0]["name"]
    assert name != other["repos"]["repos"][0]["name"]
    from cockpitlib.ops import worktree_add
    from cockpitlib.outbox import amend, create, endorse
    from cockpitlib.publish import execute
    from cockpitlib.worktree import head_of
    from tests.support import fake_gh

    env["root"] / "repos" / name
    worktree_add(pack, "TASK-1004", name)
    checkout = env["root"] / "wt" / "TASK-1004" / name
    branch = subprocess.check_output(["git", "-C", str(checkout), "branch", "--show-current"], text=True).strip()
    row = create(pack, "TASK-1004", "push-branch", "c", "ship", {"repo": name, "branch": branch})
    assert row["payload"]["sha"] == head_of("TASK-1004", name)
    row = endorse(row["id"], "low", "", "gatekeeper", "fixture-a", "fixture-large", pack=pack)
    (checkout / f"{pack['name']}.txt").write_text("more\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(checkout), "add", "."], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(checkout), "commit", "-q", "-m", "more"], check=True, capture_output=True)
    head = subprocess.check_output(["git", "-C", str(checkout), "rev-parse", "HEAD"], text=True).strip()
    assert head_of("TASK-1004", name) == head != row["payload"]["sha"]
    with pytest.raises(CockpitError, match="sha does not match"):
        execute(row, pack=pack)
    assert row["status"] == "endorsed"
    checked = _client().post("/verify", json={"id": row["id"]})
    assert checked.status_code == 200
    assert checked.json()["ok"] is False
    assert "sha does not match" in checked.json()["problems"][0]
    row = amend(row["id"], summary="the branch moved", pack=pack)
    assert row["payload"]["sha"] == head and row["status"] == "pending"
    row = endorse(row["id"], "low", "", "gatekeeper", "fixture-a", "fixture-large", pack=pack)
    receipt = execute(row, pack=pack)
    assert receipt["ok"] is True and row["status"] == "published"
    assert fake_gh.remote(name, row["payload"]["publish_as"]) == head
    empty = env["root"] / "wt" / "TASK-1005" / name  # a checkout with no commit has no head
    empty.mkdir(parents=True)
    subprocess.run(["git", "init", str(empty)], check=True, capture_output=True)
    assert head_of("TASK-1005", name) == ""


@pytest.mark.parametrize("pack_file", PACKS)
def test_publish_refuses_a_finding_that_cites_an_unread_line(env, pack_file, monkeypatch):
    pack = load(pack_file)
    other = load(PACKS[0] if pack["name"] == "bravo" else PACKS[1])
    repo = pack["repos"]["repos"][0]["name"]
    assert repo != other["repos"]["repos"][0]["name"]
    from cockpitlib.egress import check_tool
    from cockpitlib.intents import load as load_intent
    from cockpitlib.outbox import amend, create, endorse, lines_read, note_read
    from cockpitlib.paths import qa
    from cockpitlib.publish import execute
    from tests.support import fake_gh

    ticket = "TASK-884"
    fake_gh.pull(f"{pack['forge']['org']}/{repo}", 3, f"work/{ticket}", "e" * 40)
    folder = os.path.join(qa(), ticket)
    os.makedirs(folder, exist_ok=True)
    open(os.path.join(folder, "skills.log"), "w", encoding="utf-8").write("skill:pr-review\n")
    seen = f"src/{pack['name']}.py:4"
    unread = f"src/{other['name']}.py:9"
    assert seen != unread
    claimed = {"repo": repo, "number": 3, "sha": "e" * 40, "event": "COMMENT", "cites": [seen], "read": [seen]}
    with pytest.raises(CockpitError, match="unread"):
        create(pack, ticket, "pr-review-submit", "c", "review", claimed)
    monkeypatch.setenv("COCKPIT_LANE", "worker-1")
    monkeypatch.setenv("COCKPIT_TICKET", ticket)
    assert check_tool("read_file", {"path": f"src/{pack['name']}.py", "line": 4}) == ""
    assert seen not in lines_read(ticket)
    assert note_read("", seen) == ""
    assert note_read(ticket, seen) == seen
    assert note_read(ticket, seen) == seen
    monkeypatch.setenv("COCKPIT_LANE", "reviewer")
    assert check_tool("read_file", {"path": f"src/{pack['name']}.py"}) == ""
    tool_line = f"src/{pack['name']}.py:8"
    assert check_tool("read_file", {"path": f"src/{pack['name']}.py", "line": 8}) == ""
    assert tool_line in lines_read(ticket)
    monkeypatch.delenv("COCKPIT_LANE", raising=False)
    made = create(pack, ticket, "pr-review-submit", "c", "review", claimed)
    assert made["status"] == "pending"
    endorse(made["id"], "low", "", "gatekeeper", "fixture-a", "fixture-large")
    amend(made["id"], payload={"cites": [unread]})
    endorse(made["id"], "low", "", "gatekeeper", "fixture-a", "fixture-large")
    with pytest.raises(CockpitError, match="unread"):
        execute(load_intent(made["id"]), pack=pack)
    amend(made["id"], payload={"cites": [seen], "read": [seen]})
    endorse(made["id"], "low", "", "gatekeeper", "fixture-a", "fixture-large")
    receipt = execute(load_intent(made["id"]), pack=pack)
    assert receipt["ok"] is True and receipt["stage"] == "pending"
    assert unread not in json.dumps(receipt)


@pytest.mark.parametrize("pack_file", PACKS)
def test_the_forge_speaks_as_the_human_and_a_dry_run_sends_nothing(env, pack_file, monkeypatch):
    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    pack = load(pack_file)
    other = load(PACKS[0] if pack["name"] == "bravo" else PACKS[1])
    org = pack["forge"]["org"]
    repo = pack["repos"]["repos"][0]["name"]
    assert org != other["forge"]["org"] and repo != other["repos"]["repos"][0]["name"]
    from cockpitlib.forge import Forge
    from cockpitlib.publish import forge_for
    from tests.support import fake_gh

    forge = forge_for(pack)
    assert forge.org == org and forge.repo(repo) == f"{org}/{repo}" and forge.repo("else/where") == "else/where"
    assert forge.me() == pack["forge"]["human_login"]
    fake_gh.setup(me=f"gh-{pack['name']}")
    assert Forge({"forge": {"org": org}}).me() == f"gh-{pack['name']}"
    assert Forge({"forge": {"org": f"{pack['name']}-mirror"}}).org == f"{pack['name']}-mirror"
    fake_gh.pull(f"{org}/{repo}", 4, "work/x", "f" * 40)
    dry = forge_for(pack, dry_run=True)
    assert dry.write("PATCH", f"repos/{org}/{repo}/pulls/4", {"title": pack["name"]}) == {"dry_run": True}
    assert dry.graphql("mutation{x}", {}, write=True) == {"dry_run": True}
    assert dry.pr(repo, 4)["title"] == "" and [row["method"] for row in dry.writes] == ["PATCH", "GRAPHQL"]
    assert fake_gh.writes() == []
    with pytest.raises(CockpitError, match="no pull request 99"):
        forge.pr(repo, 99)
    with pytest.raises(CockpitError, match="graphql: unknown query"):
        forge.graphql("query{nothing}", {})
    assert forge.checks(repo, "f" * 40) == ["no checks reported"]
    fake_gh.checks(
        f"{org}/{repo}",
        "f" * 40,
        runs=[{"name": "lint", "status": "in_progress"}],
        statuses=[{"context": f"{pack['name']}/ci", "state": "pending"}],
    )
    assert forge.checks(repo, "f" * 40) == ["lint: in_progress", f"{pack['name']}/ci: pending"]

    class Text:
        returncode, stdout, stderr = 0, "plain words", ""

    assert Forge(pack, runner=lambda argv, **_kwargs: Text()).get("user") == "plain words"

    def missing(argv, **_kwargs):
        raise FileNotFoundError("gh")

    with pytest.raises(CockpitError, match="gh: gh"):
        Forge(pack, runner=missing).get("user")
    assert other["forge"]["human_login"] not in json.dumps(fake_gh.calls())


@pytest.mark.parametrize("pack_file", PACKS)
def test_treat_keeps_the_checkout_and_amends_existing_intents(env, pack_file, monkeypatch):
    import subprocess

    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    pack = load(pack_file)
    other = load(PACKS[0] if pack["name"] == "bravo" else PACKS[1])
    name = pack["repos"]["repos"][0]["name"]
    assert name != other["repos"]["repos"][0]["name"]
    from cockpitlib.acts import treat_pr
    from cockpitlib.intents import all_intents
    from cockpitlib.intents import load as load_intent
    from cockpitlib.outbox import create, endorse

    source = env["root"] / "repos" / name
    if not (source / ".git").exists():
        source.mkdir(parents=True)
        subprocess.run(["git", "init", str(source)], check=True, capture_output=True)
        git_env = os.environ.copy()
        git_env["GIT_AUTHOR_NAME"] = "Dev"
        git_env["GIT_AUTHOR_EMAIL"] = "dev@example.test"
        git_env["GIT_COMMITTER_NAME"] = "Dev"
        git_env["GIT_COMMITTER_EMAIL"] = "dev@example.test"
        (source / "README").write_text("hello\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(source), "add", "README"], check=True, capture_output=True)
        subprocess.run(["git", "-C", str(source), "commit", "-m", "init"], check=True, capture_output=True, env=git_env)
    made = create(pack, "TASK-1010", "pr-comment", "c", "note", {"repo": name, "number": 8, "body": "first"})
    made = endorse(made["id"], "low", "", "gatekeeper", "fixture-a", "fixture-large")
    before = len(all_intents("TASK-1010"))
    treated = treat_pr(pack, "TASK-1010", name, 8, f"comment from {pack['name']}")
    assert made["id"] in treated["amended"]
    assert "Amend the existing intents" in treated["out"]
    assert f"comment from {pack['name']}" in treated["out"]
    assert other["name"] not in treated["out"]
    assert len(all_intents("TASK-1010")) == before
    amended = load_intent(made["id"])
    assert amended["status"] == "pending"
    assert f"amend for {name}#8" in amended["agent_summary"]
    checkout = env["root"] / "wt" / "TASK-1010" / name
    assert os.path.isdir(checkout)
    assert str(checkout) in treated["checkout"]
    branch = subprocess.check_output(["git", "-C", str(checkout), "branch", "--show-current"], text=True).strip()
    assert branch == f"{pack['branch_prefix']}/TASK-1010"
