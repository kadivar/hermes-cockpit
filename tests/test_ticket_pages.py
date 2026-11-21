# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""What the dashboard reads back: a ticket's page, its diff, the live page, activity, usage and rendered documents."""

import json
import os
import sys

import pytest

from cockpitlib.pack import load
from dashboard.cockpit.router import router
from tests.support.both_packs import PACKS, _client, _other


@pytest.mark.parametrize("pack_file", PACKS)
def test_usage_shows_one_row_per_provider(env, pack_file, monkeypatch):
    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    pack = load(pack_file)
    other = load(PACKS[0] if pack["name"] == "bravo" else PACKS[1])
    assert pack["name"] != other["name"]
    rows = _client().get("/usage").json()["providers"]
    assert {row["provider"] for row in rows} == {"fixture-a", "fixture-b"}
    assert len(rows) == 2
    assert all("turns" in row and "time" in row and "plan_window" not in row for row in rows)
    assert other["name"] not in json.dumps(rows)


@pytest.mark.parametrize("pack_file", PACKS)
def test_the_diff_route_returns_the_pull_request_diff(env, pack_file):
    pack = load(pack_file)
    other = load(PACKS[0] if pack["name"] == "bravo" else PACKS[1])
    repo = pack["repos"]["repos"][0]["name"]
    assert repo != other["repos"]["repos"][0]["name"]
    from cockpitlib.acts import _write
    from cockpitlib.paths import platform_dir, qa

    ticket = "TASK-881"
    body = f"diff --git a/{pack['name']} b/{pack['name']}\n"
    path = os.path.join(platform_dir(), f"pr-{repo}-8.diff")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    open(path, "w", encoding="utf-8").write(body)
    state = {"ticket": ticket, "repo": repo, "number": 8, "head_sha": "eee", "reviewed_sha": "eee"}
    _write(os.path.join(qa(), ticket, "pr", f"{repo}-8.json"), state)
    client = _client()
    same = client.get("/pr-diff", params={"ticket": ticket, "repo": repo, "number": 8, "mode": "since"}).json()
    assert same["diff"] == "" and same["commits"] == []
    state["head_sha"] = "fff"
    _write(os.path.join(qa(), ticket, "pr", f"{repo}-8.json"), state)
    moved = client.get("/pr-diff", params={"ticket": ticket, "repo": repo, "number": 8, "mode": "since"}).json()
    assert body in moved["diff"]
    assert moved["commits"]
    assert other["name"] not in moved["diff"]
    full = client.get("/pr-diff", params={"ticket": ticket, "repo": repo, "number": 8, "mode": "full"}).json()
    assert body in full["diff"]


@pytest.mark.parametrize("pack_file", PACKS)
def test_the_diff_route_returns_the_forge_diff(env, pack_file, monkeypatch):
    import subprocess

    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    pack = load(pack_file)
    other = load(PACKS[0] if pack["name"] == "bravo" else PACKS[1])
    name = pack["repos"]["repos"][0]["name"]
    assert name != other["repos"]["repos"][0]["name"]
    assert pack["forge"]["org"] != other["forge"]["org"]
    from cockpitlib.acts import checkout_diff
    from cockpitlib.ops import worktree_add
    from cockpitlib.paths import platform_dir

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
    worktree_add(pack, "TASK-1007", name)
    checkout = env["root"] / "wt" / "TASK-1007" / name
    git_env = os.environ.copy()
    git_env["GIT_AUTHOR_NAME"] = "Dev"
    git_env["GIT_AUTHOR_EMAIL"] = "dev@example.test"
    git_env["GIT_COMMITTER_NAME"] = "Dev"
    git_env["GIT_COMMITTER_EMAIL"] = "dev@example.test"
    marker = f"line {pack['name']}"
    (checkout / "note.txt").write_text(marker + "\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(checkout), "add", "note.txt"], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(checkout), "commit", "-m", "note"], check=True, capture_output=True, env=git_env)
    body = _client().get("/pr-diff", params={"ticket": "TASK-1007", "repo": name, "number": 4}).json()
    assert marker in body["diff"]
    assert other["name"] not in body["diff"]
    shown = _client().get("/diff", params={"ticket": "TASK-1007", "repo": name}).json()
    assert marker in shown["diff"]
    assert _client().get("/diff", params={"ticket": "TASK-missing", "repo": name}).json()["diff"] == ""
    assert checkout_diff(pack, "TASK-missing", name) == ""
    parent = subprocess.check_output(["git", "-C", str(checkout), "rev-parse", "HEAD~1"], text=True).strip()
    # update-ref, not `branch -f`: git 2.45+ refuses to force a branch that any worktree has checked out (the source checkout holds the base)
    subprocess.run(
        ["git", "-C", str(checkout), "update-ref", f"refs/heads/{pack.get('base_branch') or 'main'}", parent],
        check=True,
        capture_output=True,
    )
    ranged = checkout_diff(pack, "TASK-1007", name)
    assert marker in ranged
    stored = os.path.join(platform_dir(), f"pr-{name}-4.diff")
    os.makedirs(os.path.dirname(stored), exist_ok=True)
    open(stored, "w", encoding="utf-8").write(f"forge {pack['forge']['org']}\n")
    forged = _client().get("/pr-diff", params={"ticket": "TASK-1007", "repo": name, "number": 4}).json()
    assert forged["diff"] == f"forge {pack['forge']['org']}\n"
    empty = env["root"] / "wt" / "TASK-1008" / name  # a checkout with no commit: git has no diff to give
    empty.mkdir(parents=True)
    subprocess.run(["git", "init", str(empty)], check=True, capture_output=True)
    assert checkout_diff(pack, "TASK-1008", name) == ""


@pytest.mark.parametrize("pack_file", PACKS)
def test_the_inbox_reads_an_older_or_broken_board_without_failing(env, pack_file, monkeypatch):
    import sqlite3

    from cockpitlib.kanban import db_path, open_card_rows
    from tests.support.boards import init_db

    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    pack = load(pack_file)
    assert open_card_rows(pack["board"], pack) == []
    path = init_db(pack["board"])
    connection = sqlite3.connect(path)
    connection.execute("alter table tasks rename column status to state")
    connection.commit()
    assert open_card_rows(pack["board"], pack) == []
    connection.execute("alter table tasks rename column state to status")
    connection.execute(
        "insert into tasks values ('old', ?, 'analyst', 'blocked', '')", (f"{pack['tracker']['project']}-508: analyst",)
    )
    connection.commit()
    connection.close()
    [card] = open_card_rows(pack["board"], pack)
    assert (
        card["ticket"] == f"{pack['tracker']['project']}-508"
        and card["block_reason"] == ""
        and card["blocked_at"] is None
    )
    assert db_path(pack["board"]) == path


@pytest.mark.parametrize("pack_file", PACKS)
def test_markdown_and_tracker_documents_render_to_safe_html(env, pack_file):
    from cockpitlib.render import adf, markdown

    pack = load(pack_file)
    assert f"<h2>{pack['name']}</h2>" == markdown(f"## {pack['name']}")
    shown = markdown(
        "# Title\n\nA **bold** and *soft* `x<y` [site](https://example.test/a) [bad](javascript:alert(1))\n\n"
        "- one\n- two\n\n1. first\n2. second\n\n> quote\n\n---\n\n```\n<b>raw</b>\n```\n\n"
        "| a | b |\n|---|---|\n| 1 | <i>2</i> |\n\nsee https://example.test/z now\nnext line\n- after para"
    )
    assert "<h1>Title</h1>" in shown and "<strong>bold</strong>" in shown and "<em>soft</em>" in shown
    assert (
        "<code>x&lt;y</code>" in shown
        and '<a href="https://example.test/a" rel="noopener noreferrer">site</a>' in shown
    )
    assert "javascript" not in shown.split("bad")[0][-40:] and 'href="javascript' not in shown
    assert "<ul><li>one</li><li>two</li></ul>" in shown and "<ol><li>first</li><li>second</li></ol>" in shown
    assert "<blockquote>quote</blockquote>" in shown and "<hr>" in shown and "&lt;b&gt;raw&lt;/b&gt;" in shown
    assert "<th>a</th>" in shown and "<td>&lt;i&gt;2&lt;/i&gt;</td>" in shown and "<br>" in shown
    assert '<a href="https://example.test/z"' in shown and "<li>after para</li>" in shown
    assert markdown("") == "" and markdown(None) == ""
    document = {
        "type": "doc",
        "content": [
            {"type": "heading", "attrs": {"level": 9}, "content": [{"type": "text", "text": "H"}]},
            {
                "type": "paragraph",
                "content": [
                    {"type": "text", "text": "<x>", "marks": [{"type": "strong"}, {"type": "em"}, {"type": "code"}]},
                    {"type": "hardBreak"},
                    {"type": "text", "text": "l", "marks": [{"type": "link", "attrs": {"href": "https://t.test"}}]},
                    {"type": "text", "text": "j", "marks": [{"type": "link", "attrs": {"href": "javascript:x"}}]},
                    {"type": "mention", "attrs": {"text": "@who"}},
                    {"type": "inlineCard", "attrs": {"url": "https://c.test"}},
                    {"type": "inlineCard", "attrs": {"url": "file:///etc"}},
                ],
            },
            {
                "type": "bulletList",
                "content": [
                    {"type": "listItem", "content": [{"type": "paragraph", "content": [{"type": "text", "text": "i"}]}]}
                ],
            },
            {"type": "codeBlock", "content": [{"type": "text", "text": "<c>"}]},
            {"type": "rule"},
            {
                "type": "table",
                "content": [
                    {
                        "type": "tableRow",
                        "content": [{"type": "tableHeader", "content": [{"type": "text", "text": "th"}]}],
                    }
                ],
            },
            {"type": "unknownThing", "content": [{"type": "text", "text": "kept"}]},
            "loose",
        ],
    }
    out = adf(document)
    assert "<h6>H</h6>" in out and "<code><em><strong>&lt;x&gt;</strong></em></code>" in out and "<br>" in out
    assert '<a href="https://t.test" rel="noopener noreferrer">l</a>' in out and ">j<" not in out and "j" in out
    assert "@who" in out and 'href="https://c.test"' in out and "file://" not in out
    assert "<ul><li><p>i</p></li></ul>" in out and "<pre><code>&lt;c&gt;</code></pre>" in out and "<hr>" in out
    assert "<table><tbody><tr><th>th</th></tr></tbody></table>" in out and "kept" in out and "loose" in out


@pytest.mark.parametrize("pack_file", PACKS)
def test_the_live_page_streams_cards_jobs_and_lane_logs(env, pack_file, monkeypatch):
    import sqlite3
    import time

    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    pack = load(pack_file)
    other = _other(pack)
    from cockpitlib.kanban import BoardWrites, db_path, place_card
    from cockpitlib.lane_feed import logs_dir
    from cockpitlib.outbox import create

    ticket = f"{pack['tracker']['project']}-61"
    card = place_card(
        pack["board"], f"{ticket}: work", "worker-1", "ready", body=f"# Do it\n\n- **{pack['name']}** step"
    )
    writes = BoardWrites(pack["board"])
    writes.comment(card, "worker-1", f"progress on `{pack['name']}`")
    writes.flush()
    create(pack, ticket, "tracker-comment", card, "note", {"body": f"tracker {pack['name']}"})
    client = _client()
    shown = client.get(f"/card?id={card}").json()
    assert (
        shown["title"] == f"{ticket}: work"
        and "<h1>Do it</h1>" in shown["body_html"]
        and f"<strong>{pack['name']}</strong>" in shown["body_html"]
    )
    assert shown["comments"][0]["html"] == f"<p>progress on <code>{pack['name']}</code></p>"

    connection = sqlite3.connect(db_path(pack["board"]))
    for moment in (1793500000, 1793500060, 1793500120):
        connection.execute(
            "insert into task_events (task_id, kind, payload, created_at) values (?, 'heartbeat', null, ?)",
            (card, moment),
        )
    connection.commit()
    connection.close()
    lane = client.get(f"/lane-stream?card={card}").json()
    assert lane["running"] is False and any(
        entry["kind"] == "text" and pack["name"] in entry["text"] for entry in lane["entries"]
    )
    assert not [entry for entry in lane["entries"] if entry["kind"] == "heartbeat"], (
        "liveness is on the board, not in Live"
    )
    assert client.get(f"/lane-stream?card={card}&since={lane['last']}").json()["entries"] == []
    job = client.get(f"/job-stream?ticket={ticket}").json()
    kinds = {entry["kind"] for entry in job["entries"]}
    assert {"written", "comment"} <= kinds and all(entry["ticket"] == ticket for entry in job["entries"])
    assert "heartbeat" not in kinds
    assert any(entry["kind"] == "comment" and "<code>" in entry["html"] for entry in job["entries"])
    assert client.get("/job-stream?ticket=all").json()["entries"]
    connection = sqlite3.connect(db_path(pack["board"]))
    connection.execute("update tasks set status = 'running' where id = ?", (card,))
    connection.commit()
    connection.close()
    assert client.get(f"/job-stream?ticket={ticket}").json()["running"] is True
    os.makedirs(logs_dir(pack), exist_ok=True)
    log = os.path.join(logs_dir(pack), f"{card}.log")
    open(log, "w", encoding="utf-8").write(f"line one {pack['name']}\n")
    first = client.get(f"/lane-tail?path={log}&offset=-1").json()
    assert first["text"] == f"line one {pack['name']}\n" and first["running"] is True
    open(log, "a", encoding="utf-8").write("line two\n")
    assert client.get(f"/lane-tail?path={log}&offset={first['offset']}").json()["text"] == "line two\n"
    os.utime(log, (time.time() - 120, time.time() - 120))
    assert client.get(f"/lane-tail?path={log}&offset=0").json()["running"] is False
    outside = os.path.join(os.environ["COCKPIT_ROOT"], f"{other['name']}.log")
    open(outside, "w", encoding="utf-8").write("secret\n")
    assert client.get(f"/lane-tail?path={outside}").status_code == 400
    assert client.get("/card?id=missing").json()["title"] == ""
    from cockpitlib.lane_feed import card as card_view

    assert card_view(pack, "")["comments"] == [] and card_view(pack, "missing")["comments"] == []


@pytest.mark.parametrize("pack_file", PACKS)
def test_a_ticket_shows_its_tracker_title_brief_plan_trail_and_activity(env, pack_file, monkeypatch, jira):
    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    pack = load(pack_file)
    other = _other(pack)
    from cockpitlib.kanban import place_card
    from cockpitlib.ops import workspace_watch
    from cockpitlib.outbox import create, endorse, hold
    from cockpitlib.plan import append, init
    from cockpitlib.tracker import TITLES_FRESH, titles, tracker_for

    ticket = f"{pack['tracker']['project']}-62"
    jira.issue(ticket)["fields"]["summary"] = f"Fix the {pack['name']} export"
    place_card(pack["board"], f"{ticket}: work", "worker-1", "ready")
    init(ticket, f"# Plan\n\n## Brief\n\nissue in {pack['name']} · fix the writer\n\n## Steps\n\n1. write", "go")
    append(ticket, "Delivered", "done **well**")
    intent = create(pack, ticket, "tracker-comment", "c", "note", {"body": "x"})
    endorse(intent["id"], "low", "", "gatekeeper", "fixture-a", "fixture-large")
    hold(intent["id"], f"wait for {pack['name']}")
    client = _client()
    assert (
        client.get("/tickets").json()["tickets"][0]["summary"] == ""
    )  # nothing read yet: the page never waits on the tracker
    workspace_watch(pack)
    rows = {row["ticket"]: row for row in client.get("/tickets").json()["tickets"]}
    assert rows[ticket]["summary"] == f"Fix the {pack['name']} export"
    asked = len(jira.requests)
    assert (
        titles(pack, [ticket], refresh=True)[ticket] == f"Fix the {pack['name']} export" and len(jira.requests) == asked
    )
    import time

    jira.issue(ticket)["fields"]["summary"] = "renamed"
    assert titles(pack, [ticket], refresh=True, now=time.time() + TITLES_FRESH + 1)[ticket] == "renamed"
    assert (
        titles(pack, [f"{pack['tracker']['project']}-404"], refresh=True)[f"{pack['tracker']['project']}-404"] == ""
    )  # unreadable: left out
    shown = client.get(f"/ticket?ticket={ticket}").json()
    assert (
        shown["brief"] == f"<p>issue in {pack['name']} · fix the writer</p>"
        and shown["plan_line"] == f"issue in {pack['name']} · fix the writer"
    )
    assert [part["title"] for part in shown["plan_parts"]] == ["Steps", "Decision", "Delivered"]
    assert "<strong>well</strong>" in shown["plan_parts"][2]["html"]
    steps = [row["kind"] for row in shown["activity"] if row["src"] == "outbox"]
    assert steps == ["written", "held"] and all(other["name"] not in row["text"] for row in shown["activity"])
    assert any(row["src"] == "board" and row["kind"] == "created" for row in shown["activity"])
    plain = client.get(f"/ticket?ticket={pack['tracker']['project']}-63").json()
    assert plain["brief"] is None and plain["plan_parts"] == [] and plain["activity"] == []

    from cockpitlib.tracker import CommandTracker

    script = os.path.join(os.environ["COCKPIT_ROOT"], "title.py")
    open(script, "w", encoding="utf-8").write(
        "import json, os, sys\n"
        "intent = json.load(sys.stdin)\n"
        f"print(json.dumps({{'summary': os.environ['COCKPIT_TRACKER_ACTION'] + ' ' + intent['ticket'] + ' {pack['name']}'}}))\n"
    )
    reader = CommandTracker({"command": [sys.executable, script]})
    assert reader.summary(ticket) == f"summary {ticket} {pack['name']}" and reader.writes == []
    assert tracker_for(pack).summary(ticket) == "renamed"


@pytest.mark.parametrize("pack_file", PACKS)
def test_activity_reads_every_recorded_step_and_survives_a_broken_board(env, pack_file, monkeypatch):
    import sqlite3

    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    pack = load(pack_file)
    from cockpitlib.activity import _stamp, ticket_activity
    from cockpitlib.intents import save
    from cockpitlib.kanban import BoardWrites, db_path, place_card
    from cockpitlib.outbox import create

    ticket = f"{pack['tracker']['project']}-64"
    assert ticket_activity({"board": "no-such-board"}, ticket) == []
    assert _stamp("not a time") == "" and _stamp(0) == "1970-01-01T00:00:00Z"
    row = create(pack, ticket, "tracker-comment", "c", "note", {"body": "x"})
    row.update(
        returned={"time": "2026-10-23T01:00:00Z", "by": "human", "instruction": f"again {pack['name']}"},
        human={"time": "2026-10-23T02:00:00Z", "decision": "drop", "note": "n"},
        receipt={"ok": False, "error": "refused here", "time": "2026-10-23T03:00:00Z"},
        history=[{"time": "2026-10-23T04:00:00Z", "event": "discarded pending review"}, "junk"],
    )
    save(row)
    card = place_card(pack["board"], f"{ticket}: work", "worker-1", "ready")
    writes = BoardWrites(pack["board"])
    writes.block(card, f"waiting {pack['name']}")
    writes.comment(card, "worker-1", f"said {pack['name']}")
    writes.flush()
    connection = sqlite3.connect(db_path(pack["board"]))
    connection.execute(
        "insert into task_events (task_id, kind, payload, created_at) values (?, 'heartbeat', null, 4)", (card,)
    )
    connection.execute(
        "insert into task_events (task_id, kind, payload, created_at) values (?, 'probed', '{bad', 5)", (card,)
    )
    connection.execute(
        "insert into task_events (task_id, kind, payload, created_at) values (?, 'sweep', null, 6)", (card,)
    )
    connection.execute(
        "insert into task_events (task_id, kind, payload, created_at) values (?, 'noted', '[1]', 7)", (card,)
    )
    connection.commit()
    connection.close()
    shown = ticket_activity(pack, ticket)
    kinds = [item["kind"] for item in shown]
    assert {"returned", "drop", "refused", "history", "blocked", "probed", "noted", "comment"} <= set(kinds)
    assert "sweep" not in kinds and "heartbeat" not in kinds, "housekeeping and liveness are not steps"
    assert any(item["kind"] == "blocked" and item["text"] == f"waiting {pack['name']}" for item in shown)
    assert [item["ts"] for item in shown] == sorted(item["ts"] for item in shown)
    assert all(
        item["ts"] > "2026-10-23T02:30:00Z" for item in ticket_activity(pack, ticket, since="2026-10-23T02:30:00Z")
    )
    from cockpitlib import activity

    real = activity.sqlite3.connect
    monkeypatch.setattr(activity.sqlite3, "connect", lambda *a, **k: _Broken(real(*a, **k)))
    assert all(item["src"] == "outbox" for item in ticket_activity(pack, ticket))


class _Broken:
    """A board connection whose queries fail, as a locked or damaged board does."""

    def __init__(self, inner):
        self.inner = inner

    def execute(self, *_args):
        import sqlite3

        raise sqlite3.Error("database is locked")

    def close(self):
        self.inner.close()


@pytest.mark.parametrize("pack_file", PACKS)
def test_the_inbox_asks_for_a_dashboard_restart_when_cockpits_code_changed(env, pack_file, monkeypatch):
    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    import types

    endpoint = next(route.endpoint for route in router.routes if route.path == "/needs-you")
    api = types.SimpleNamespace(
        **{name: endpoint.__globals__[name] for name in ("code_row", "code_stamp")}
    )  # the module the router serves
    assert api.code_row() == {}
    assert all(row["name"] != "dashboard" for row in _client().get("/needs-you").json()["watchers"])
    monkeypatch.setitem(endpoint.__globals__, "LOADED", api.code_stamp() - 1)
    shown = [row for row in _client().get("/needs-you").json()["watchers"] if row["name"] == "dashboard"]
    assert (
        len(shown) == 1 and "hermes dashboard --stop" in shown[0]["reason"] and "this dashboard" in shown[0]["reason"]
    )
    # the gateway serves the pages when its state file names this process: the row says so and names its restart
    import json

    from cockpitlib.paths import hermes_home

    state = os.path.join(hermes_home(), "gateway_state.json")
    os.makedirs(os.path.dirname(state), exist_ok=True)
    for written, name in (
        ('{"pid": %d}' % os.getpid(), "gateway"),
        ('{"pid": 1}', "dashboard"),
        ("not json", "dashboard"),
        ("[]", "dashboard"),
    ):
        with open(state, "w", encoding="utf-8") as handle:
            handle.write(written)
        rows = [row for row in _client().get("/needs-you").json()["watchers"] if row.get("restart")]
        assert [row["name"] for row in rows] == [name], written
        if name == "gateway":
            assert (
                rows[0]["restart"] == "hermes gateway restart" and "the gateway serves these pages" in rows[0]["reason"]
            )
            assert json.loads(written)["pid"] == os.getpid()
    os.remove(state)
    monkeypatch.setattr("cockpitlib.paths.PLUGIN_ROOT", os.path.join(os.environ["COCKPIT_ROOT"], "no-tree"))
    assert api.code_stamp() == 0.0
