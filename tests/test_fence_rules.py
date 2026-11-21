# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The egress fence: what a lane's tool call may write, reach and read, by each pack's own rules."""

import io
import json
import os
import sys

import pytest

from cockpitlib.cli import main
from cockpitlib.errors import CockpitError
from cockpitlib.pack import load
from tests.support.both_packs import PACKS, ROOT, _client


@pytest.mark.parametrize("pack_file", PACKS)
def test_a_refused_host_is_literal(env, pack_file, monkeypatch):
    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    pack = load(pack_file)
    other = load(PACKS[0] if pack["name"] == "bravo" else PACKS[1])
    from cockpitlib.egress import check_bound

    host = pack["refused"]["hosts"][0]
    assert host != other["refused"]["hosts"][0]
    assert check_bound(f"curl https://{host}/x") == "blocked"
    assert check_bound(f"curl https://{host.replace('.', 'X', 1)}/x") == ""
    assert check_bound(f"curl https://{other['refused']['hosts'][0]}/x") == ""
    assert check_bound(pack["allowed"]["reads"][0]) == ""


@pytest.mark.parametrize("pack_file", PACKS)
def test_the_egress_hook_refuses_a_write_outside_the_lane_tree(env, pack_file, monkeypatch):
    import importlib.util

    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    pack = load(pack_file)
    other = load(PACKS[0] if pack["name"] == "bravo" else PACKS[1])
    assert pack["name"] != other["name"]
    spec = importlib.util.spec_from_file_location(
        "cockpit_plugin_writes",
        os.path.join(os.path.dirname(os.path.dirname(__file__)), "__init__.py"),
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    class Ctx:
        def __init__(self):
            self.hooks = {}

        def register_skill(self, _name, _path):
            return None

        def register_hook(self, event, fn):
            self.hooks[event] = fn

    ctx = Ctx()
    module.register(ctx)
    from tests.support.hermes_contract import call

    def hook(name, args):
        return call(ctx.hooks["pre_tool_call"], "pre_tool_call", tool_name=name, args=args)

    from cockpitlib.paths import qa

    inside = os.path.join(qa(), f"{pack['tracker']['project']}-1045", "note.md")
    monkeypatch.setenv("COCKPIT_LANE", "worker-1")
    blocked = hook("write_file", {"file_path": "/tmp/outside.txt", "contents": pack["name"]})
    assert blocked["action"] == "block"
    assert other["name"] not in blocked["message"]
    monkeypatch.setenv("COCKPIT_LANE", "intake")
    assert hook("write_file", {"path": "/tmp/outside.txt", "contents": "x"})["action"] == "block"
    assert hook("write_file", {"path": inside, "contents": pack["name"]}) is None
    assert hook("patch", {"path": "/tmp/outside.txt", "patch": pack["name"]})["action"] == "block"
    assert hook("patch", {"path": inside, "patch": pack["name"]}) is None
    monkeypatch.setenv("COCKPIT_LANE", "reviewer")
    assert hook("write_file", {"path": "/tmp/outside.txt", "contents": "x"})["action"] == "block"
    assert hook("write_file", {"path": inside, "contents": pack["name"]}) is None


@pytest.mark.parametrize("pack_file", PACKS)
def test_the_browser_stays_closed_until_the_card_says_so(env, pack_file, monkeypatch):
    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    monkeypatch.setenv("COCKPIT_LANE", "worker-1")
    monkeypatch.setenv("COCKPIT_TICKET", "TASK-880")
    pack = load(pack_file)
    other = load(PACKS[0] if pack["name"] == "bravo" else PACKS[1])
    assert int(pack["shared_chrome_hours"]) != int(other["shared_chrome_hours"])
    from cockpitlib.acts import _comment, _open
    from cockpitlib.egress import check_bound
    from cockpitlib.kanban import place_card
    from cockpitlib.paths import watch_dir
    from cockpitlib.settings import lend_chrome
    from tests.support.boards import set_body

    port = pack["human_browser_port"]
    command = f"curl http://127.0.0.1:{port}"
    loan = lend_chrome(pack, "TASK-880")
    assert loan["hours"] == float(pack["shared_chrome_hours"])
    assert check_bound(command) == "blocked"
    card = place_card(pack["board"], "TASK-880: work", "worker-1", "ready")
    set_body(pack["board"], card, "edit the checkout\n")
    assert check_bound(command) == "blocked"
    set_body(pack["board"], card, "browser lent for the step\n")
    assert check_bound(command) == ""
    set_body(pack["board"], card, "edit the checkout\n")
    assert check_bound(command) == "blocked"
    connection = _open(pack["board"])
    _comment(connection, card, "human", "chrome: shared")
    connection.commit()
    connection.close()
    assert check_bound(command) == ""
    monkeypatch.setenv("COCKPIT_TICKET", "TASK-881")
    assert check_bound(command) == "the browser is lent to another ticket"
    monkeypatch.setenv("COCKPIT_TICKET", "TASK-880")
    path = os.path.join(watch_dir(), "shared-chrome.json")
    record = json.load(open(path, encoding="utf-8"))
    record["at"] = 1
    record["until"] = 1
    json.dump(record, open(path, "w", encoding="utf-8"))
    assert check_bound(command) == "blocked"


@pytest.mark.parametrize("pack_file", PACKS)
def test_a_worker_edit_stays_in_the_ticket_checkout(env, pack_file, monkeypatch):

    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    monkeypatch.setenv("COCKPIT_LANE", "worker-1")
    pack = load(pack_file)
    other = load(PACKS[0] if pack["name"] == "bravo" else PACKS[1])
    repo = pack["repos"]["repos"][0]["name"]
    assert repo != other["repos"]["repos"][0]["name"]
    from cockpitlib.egress import check_tool

    ticket = "TASK-8900"
    checkout = os.path.join(os.environ["COCKPIT_WT"], ticket, repo)
    os.makedirs(checkout, exist_ok=True)
    inside = os.path.join(checkout, "note.txt")
    assert check_tool("write", {"path": inside, "contents": pack["name"]}) == ""
    assert check_tool("write_file", {"file_path": "/tmp/outside.txt", "contents": "x"}) == "blocked"
    assert check_tool("read_file", {"path": "/tmp/outside.txt"}) == ""
    assert check_tool("bash", {"command": f"echo hi > {inside}"}) == ""
    assert check_tool("bash", {"command": f"cp /tmp/outside.txt {inside}"}) == ""
    assert check_tool("bash", {"command": f"mv {inside} /tmp/outside.txt"}) == "blocked"
    assert check_tool("bash", {"command": f"rsync -a /tmp/outside.txt {inside}"}) == ""
    assert check_tool("bash", {"command": f"rsync -a {inside} /tmp/outside.txt"}) == "blocked"
    assert check_tool("bash", {"command": f"ln -s {inside} /tmp/outside.txt"}) == "blocked"
    assert check_tool("bash", {"command": f"sed -i s/a/b/ {inside}"}) == ""
    assert check_tool("bash", {"command": "sed -i s/a/b/ /tmp/outside.txt"}) == "blocked"
    assert check_tool("bash", {"command": "sed s/a/b/ /tmp/outside.txt"}) == ""
    assert check_tool("bash", {"command": "sed -i -n"}) == ""
    assert check_tool("bash", {"command": f"perl -pi -e s/a/b/ {inside}"}) == ""
    assert check_tool("bash", {"command": "perl -i.bak -e s/a/b/ /tmp/outside.txt"}) == "blocked"
    assert check_tool("bash", {"command": "perl -pe s/a/b/ /tmp/outside.txt"}) == ""
    assert check_tool("bash", {"command": "perl --version"}) == ""
    assert check_tool("bash", {"command": f"dd of={inside} if=/tmp/outside.txt"}) == ""
    assert check_tool("bash", {"command": "dd of=/tmp/outside.txt"}) == "blocked"
    assert check_tool("bash", {"command": "dd if=/tmp/outside.txt"}) == ""
    assert check_tool("bash", {"command": "truncate -s 0 /tmp/outside.txt"}) == "blocked"
    assert check_tool("bash", {"command": "truncate -s"}) == ""
    assert check_tool("write", "echo hi") == ""
    assert check_tool("write", {"contents": "x"}) == ""
    from cockpitlib.pack import policy as real_policy
    from cockpitlib.paths import qa

    def with_scratch(loaded):
        parsed = real_policy(loaded)
        parsed["scratch"] = str(env["workspace"] / f"scratch-{loaded.get('name') or pack['name']}")
        return parsed

    monkeypatch.setattr("cockpitlib.pack.policy", with_scratch)
    record = os.path.join(qa(), ticket, "finding.md")
    own_scratch = env["workspace"] / f"scratch-{pack['name']}"
    other_scratch = env["workspace"] / f"scratch-{other['name']}"
    os.makedirs(own_scratch, exist_ok=True)
    for lane in ("reviewer", "intake", "analyst"):
        monkeypatch.setenv("COCKPIT_LANE", lane)
        assert check_tool("write", {"path": "/tmp/outside.txt", "contents": "x"}) == "blocked"
        assert check_tool("write", {"path": record, "contents": pack["name"]}) == ""
        assert check_tool("write", {"path": str(own_scratch / "note.txt"), "contents": pack["name"]}) == ""
        assert check_tool("bash", {"command": f"cp {record} {own_scratch / 'note.txt'}"}) == ""
        assert check_tool("bash", {"command": f"install {record} /tmp/outside.txt"}) == "blocked"
        assert check_tool("bash", {"command": f"ln -s {record} {own_scratch / 'note.txt'}"}) == ""
        assert check_tool("bash", {"command": f"rsync -a {record} /tmp/outside.txt"}) == "blocked"
        assert check_tool("bash", {"command": f"sed --in-place s/a/b/ {record}"}) == ""
        assert check_tool("bash", {"command": "sed --in-place s/a/b/ /tmp/outside.txt"}) == "blocked"
        assert check_tool("write_file", {"file_path": str(other_scratch / "note.txt"), "contents": "x"}) == "blocked"
    monkeypatch.setenv("COCKPIT_LANE", "worker-1")
    monkeypatch.setattr(
        "cockpitlib.pack.load", lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("no pack"))
    )
    assert check_tool("write", {"path": "/tmp/outside.txt", "contents": "x"}).startswith(
        "pack unreadable"
    )  # G-5: still refused
    monkeypatch.setenv("COCKPIT_LANE", "reviewer")
    assert check_tool("write", {"path": "/tmp/outside.txt", "contents": "x"}).startswith("pack unreadable")


@pytest.mark.parametrize("pack_file", PACKS)
def test_each_pack_refuses_only_its_own_hosts(env, pack_file, monkeypatch):
    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    monkeypatch.setenv("COCKPIT_LANE", "worker-1")
    pack = load(pack_file)
    other = load(PACKS[0] if pack["name"] == "bravo" else PACKS[1])
    from cockpitlib.egress import check_bound

    mine = pack["egress"]["production_hosts"][0].replace("\\.", ".")
    theirs = other["egress"]["production_hosts"][0].replace("\\.", ".")
    assert mine != theirs
    assert check_bound(f"curl https://{mine}") == "blocked"
    assert check_bound(f"curl https://{theirs}") == ""
    refused = pack["refused"]["hosts"][0]
    other_refused = other["refused"]["hosts"][0]
    assert refused != other_refused
    assert check_bound(f"curl https://{refused}") == "blocked"
    assert check_bound(f"curl https://{other_refused}") == ""


@pytest.mark.parametrize("pack_file", PACKS)
def test_a_lane_closes_only_a_tab_it_opened(env, pack_file, monkeypatch):
    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    monkeypatch.setenv("COCKPIT_LANE", "worker-1")
    monkeypatch.setenv("COCKPIT_TICKET", "TASK-9966")
    pack = load(pack_file)
    other = load(PACKS[0] if pack["name"] == "bravo" else PACKS[1])
    port = str(pack["human_browser_port"])
    assert port
    from cockpitlib.egress import check_bound
    from cockpitlib.kanban import place_card
    from cockpitlib.paths import watch_dir
    from tests.support.boards import set_body

    ticket = "TASK-9966"
    card = place_card(pack["board"], f"{ticket}: work", "worker-1", "ready")
    set_body(pack["board"], card, "browser lent\n")
    mine = f"mine-{pack['name']}"
    theirs = f"mine-{other['name']}"
    assert mine != theirs
    loan = {"ticket": ticket, "until": 9_999_999_999, "tabs": []}
    os.makedirs(watch_dir(), exist_ok=True)
    open(os.path.join(watch_dir(), "shared-chrome.json"), "w", encoding="utf-8").write(json.dumps(loan))
    assert check_bound(f"close-tab {theirs}") == "blocked"
    assert check_bound(f"curl http://127.0.0.1:{port} open-tab {mine}") == ""
    assert check_bound(f"close-tab {mine}") == ""
    plain = f"plain-{pack['name']}"
    assert check_bound(f"open-tab {plain}") == ""
    assert check_bound(f"close-tab {plain}") == ""
    assert other["name"] not in plain
    assert check_bound(f"close-tab {mine} && close-tab {theirs}") == "blocked"
    assert check_bound(f"close-tab {theirs}") == "blocked"


@pytest.mark.parametrize("pack_file", PACKS)
def test_only_read_only_seats_delegate_and_at_most_three_at_once(env, pack_file, monkeypatch, capsys):
    import io

    import yaml

    from cockpitlib.egress import check_delegate, delegate_tasks
    from cockpitlib.setup import _profile
    from tests.support.hermes_contract import block_message, call

    pack = load(pack_file)
    intake = yaml.safe_load(open(os.path.join(_profile(pack, "intake", "intake"), "config.yaml"), encoding="utf-8"))
    assert intake["delegation"] == {"max_concurrent_children": 3, "inherit_mcp_toolsets": False}
    known = json.load(open(os.path.join(ROOT, "tests", "contract", "hermes-config.json"), encoding="utf-8"))
    for seat in (
        intake,
        yaml.safe_load(open(os.path.join(_profile(pack, "reviewer", "reviewer"), "config.yaml"), encoding="utf-8")),
    ):
        assert set(seat) <= set(known["top_level"])
        assert set(seat["delegation"]) <= set(known["delegation"])
        assert not isinstance(seat.get("tools"), list)
    worker = yaml.safe_load(open(os.path.join(_profile(pack, "worker-1", "worker"), "config.yaml"), encoding="utf-8"))
    assert "delegation" not in worker

    three = {"tasks": [{"goal": f"who calls src/{name}.py:{line}"} for name, line in (("a", 1), ("b", 2), ("c", 3))]}
    monkeypatch.setenv("COCKPIT_LANE", "intake")
    assert check_delegate(three) == ""
    assert check_delegate({"tasks": three["tasks"] + [{"goal": "one more"}]}) == "at most three delegates"
    assert check_delegate({"goal": "the legacy single goal"}) == ""
    assert check_delegate({"tasks": [{"goal": "  "}]}) == "a delegate needs a goal"
    assert check_delegate({"tasks": ["not a task"]}) == "a delegate needs a goal"
    assert check_delegate({}) == "a delegate needs a goal"
    assert check_delegate("src/app.py:1") == "a delegate needs a goal"
    assert delegate_tasks(None) == []
    monkeypatch.setenv("COCKPIT_LANE", "worker-1")
    assert check_delegate(three) == "this seat does not delegate"
    assert check_delegate({"action": "list"}) == ""
    assert check_delegate({"action": "stop"}) == ""
    assert check_delegate(three, kind="reviewer") == ""

    monkeypatch.setenv("COCKPIT_LANE", "reviewer")
    import importlib.util

    spec = importlib.util.spec_from_file_location("egress_hook_delegates", os.path.join(ROOT, "hooks", "egress.py"))
    hook = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(hook)
    monkeypatch.setattr(
        sys, "stdin", io.StringIO(json.dumps({"tool_name": "delegate_task", "tool_input": {"tasks": [{"goal": " "}]}}))
    )
    assert hook.main() == 2
    assert "needs a goal" in json.loads(capsys.readouterr().out)["message"]
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps({"tool_name": "delegate_task", "tool_input": three})))
    assert hook.main() == 0
    pre = _plugin_hooks("cockpit_plugin_delegates")["pre_tool_call"]
    four = {"tasks": three["tasks"] + [{"goal": "src/d.py:4"}]}
    assert "three delegates" in block_message(call(pre, "pre_tool_call", tool_name="delegate_task", args=four))
    assert call(pre, "pre_tool_call", tool_name="delegate_task", args=three) is None
    monkeypatch.setenv("COCKPIT_LANE", "tester-1")
    assert "does not delegate" in block_message(call(pre, "pre_tool_call", tool_name="delegate_task", args=three))
    assert call(pre, "pre_tool_call", tool_name="terminal", args={"command": "git status"}) is None


@pytest.mark.parametrize(
    "pack_file,hours,seat_key,missing",
    (
        (PACKS[0], 6, "slots", "worker-2"),
        (PACKS[1], 3, "reviewer", "reviewer-2"),
    ),
)
def test_the_page_loan_duration_is_the_browser_timer(env, pack_file, hours, seat_key, missing, monkeypatch):
    import time

    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    pack = load(pack_file)
    from cockpitlib.egress import check_bound
    from cockpitlib.paths import qa, watch_dir
    from cockpitlib.setup import setup

    setup(pack)
    other = load(PACKS[0] if pack["name"] == "bravo" else PACKS[1])
    assert hours != int(pack["shared_chrome_hours"])
    assert hours != int(other["shared_chrome_hours"])
    seats = {"slots": 1, "intake": 1, "reviewer": 1, "analyst": 1}
    seats[seat_key] = 2
    client = _client()
    saved = client.post(
        "/settings",
        json={
            "settings": {
                "seats": seats,
                "budget": {"monthly_usd": 12, "plan_window_max_pct": 70},
                "shared_chrome_hours": hours,
            }
        },
    ).json()
    assert saved["out"] == "saved"
    assert saved["seats"][seat_key] == 2
    shown = client.get("/settings").json()
    from cockpitlib.paths import records_name

    assert shown["path"] == f"{records_name()}/watch/settings.json"
    assert os.path.isfile(os.path.join(os.environ["COCKPIT_WORKSPACE"], records_name(), "watch", "settings.json"))
    assert not os.path.isfile(
        os.path.join(os.environ["COCKPIT_WORKSPACE"], records_name(), "platform", "settings.json")
    )
    assert shown["settings"]["shared_chrome_hours"] == hours
    assert shown["settings"]["budget"]["monthly_usd"] == 12
    assert missing in shown["missing_lanes"]
    assert "intake" not in shown["missing_lanes"]
    caps = client.get("/capacity").json()
    if seat_key == "slots":
        assert caps["test"] == 2
    if seat_key == "reviewer":
        assert caps["review"] == 2
    refused = client.post("/kickoff", json={"ticket": "TASK-100", "mode": "analyst", "prompt": "why", "chrome": True})
    assert (
        refused.status_code == 409 and "test kickoff's option only" in refused.text
    )  # the external browser is a test's
    from cockpitlib.environments import environments
    from cockpitlib.plan import init

    init("TASK-100", "plan", "go")
    remote = next(item["name"] for item in environments(pack) if not item["slot"])
    kicked = client.post(
        "/kickoff", json={"ticket": "TASK-100", "mode": "test", "prompt": "why", "chrome": True, "env": remote}
    )
    assert kicked.status_code == 200, kicked.text
    note = open(os.path.join(qa(), "TASK-100", "human", "test.md"), encoding="utf-8").read()
    assert f"browser lent for {hours}" in note
    record = json.load(open(os.path.join(watch_dir(), "shared-chrome.json"), encoding="utf-8"))
    assert record["ticket"] == "TASK-100"
    assert record["hours"] == hours
    assert abs(record["until"] - time.time() - hours * 3600) < 5
    monkeypatch.setenv("COCKPIT_LANE", "analyst")
    monkeypatch.setenv("COCKPIT_TICKET", "TASK-100")
    port = pack["human_browser_port"]
    assert check_bound(f"curl http://127.0.0.1:{port}") == ""
    client.post(
        "/settings",
        json={
            "settings": {
                "seats": seats,
                "budget": {"monthly_usd": 12, "plan_window_max_pct": 70},
                "shared_chrome_hours": 0,
            }
        },
    )
    assert check_bound(f"curl http://127.0.0.1:{port}") == "blocked"
    client.post(
        "/settings",
        json={
            "settings": {
                "seats": seats,
                "budget": {"monthly_usd": 12, "plan_window_max_pct": 70},
                "shared_chrome_hours": hours,
            }
        },
    )
    assert check_bound(f"curl http://127.0.0.1:{port}") == ""
    record = json.load(open(os.path.join(watch_dir(), "shared-chrome.json"), encoding="utf-8"))
    record["at"] = 1
    json.dump(record, open(os.path.join(watch_dir(), "shared-chrome.json"), "w", encoding="utf-8"))
    assert check_bound(f"curl http://127.0.0.1:{port}") == "blocked"


# Each fixture's own refused values: a production host, a deny pattern it adds, a refused host, its tracker.
GUARDS = {
    "acme": {
        "prod": "app.acme.example",
        "deny": "vaultctl destroy x",
        "refused": "secret.acme.test",
        "tracker": "jira.acme.test",
    },
    "bravo": {
        "prod": "app.north.example",
        "deny": "fleet drain all",
        "refused": "secret.north.test",
        "tracker": "jira.north.test",
    },
}


@pytest.mark.parametrize("pack_file", PACKS)
def test_every_tool_input_is_guarded_not_only_the_shell_line(env, pack_file, monkeypatch):
    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    monkeypatch.setenv("COCKPIT_LANE", "worker-1")
    pack = load(pack_file)
    own = GUARDS[pack["name"]]
    other = GUARDS["bravo" if pack["name"] == "acme" else "acme"]
    from cockpitlib.egress import check_tool

    home = str(env["home"])

    def blocked(name, args):
        return bool(check_tool(name, args))

    # What runs, what is fetched, and any other tool's arguments.
    assert blocked("browser_navigate", {"url": f"https://{own['prod']}/admin"})
    assert not blocked("browser_navigate", {"url": f"https://{other['prod']}/admin"})
    assert blocked("execute_code", {"code": f"import os; os.system('{own['deny']}')"})
    assert not blocked("execute_code", {"code": f"print('{other['deny']}')"})
    assert blocked("browser_exec", {"code": "git push origin main"})
    assert blocked("browser_console", {"expression": "fetch('https://" + own["prod"] + "/x')"})
    assert blocked("mcp_fixture_fetch", {"query": {"links": [f"see https://{own['refused']}/x"]}})
    assert not blocked("mcp_fixture_fetch", {"query": "see https://example.test/x"})
    assert blocked("mcp_shell_run", {"command": "git push"})
    assert blocked("web_extract", {"urls": ["https://example.test", f"https://{own['prod']}"]})

    # Forge and tracker writes that skip the outbox; reads still run.
    tracker = own["tracker"]
    for line in (
        "gh issue create -t x",
        "gh issue comment 3 -b hi",
        "gh workflow run ci.yml",
        "gh run rerun 9",
        "gh repo edit --visibility public",
        "gh label create bug",
        "gh release upload v1 a.tgz",
        "gh secret set TOKEN",
        "gh api repos/o/r/issues -f title=x",
        "gh api graphql -F query='mutation { x }'",
        "gh api graphql --raw-field query=@q",
        "git commit -n -m x",
        "git commit -anm x",
        "git -c core.hooksPath=/dev/null commit -m x",
        "HUSKY_SKIP_HOOKS=1 git commit -m x",
        f"curl -X POST https://{tracker}/rest/api/2/issue",
        f"curl -d @body.json https://{tracker}/rest/api/2/issue/X-1/comment",
        "curl --json '{}' https://api.github.com/repos/o/r/issues",
        f"wget --post-data=x https://{tracker}/x",
        f"http POST https://{tracker}/rest/api/2/issue",
        f"http https://{tracker}/rest/api/2/issue summary=x",
        "hermes cron create 5m x",
        "hermes --profile analyst cron edit abc --schedule 1m",
    ):
        assert blocked("terminal", {"command": line}), line
    for line in (
        "gh issue view 3",
        "gh run view 9",
        "gh api repos/o/r/pulls",
        "git commit -m 'note -n here'",
        f"curl https://{tracker}/rest/api/2/issue/X-1",
        "http GET https://api.github.com/repos/o/r",
        "hermes cron list",
    ):
        assert not blocked("terminal", {"command": line}), line
    assert not blocked("terminal", {"command": f"curl -X POST https://{other['tracker']}/x"})

    # A search over the machine or a home folder.
    for line in (
        "find $HOME -name x",
        "find /home/someone -name x",
        "cd ~ && find . -name x",
        "ls -R /",
        "ls -lR ~",
        "rg secret ~",
        f"grep -r x {os.path.expanduser('~')}",
        "du -sh /Users/x",
    ):
        assert blocked("terminal", {"command": line}), line
    for line in ("find . -name x", "rg secret .", "ls -la ~", "cd /tmp && find . -name x"):
        assert not blocked("terminal", {"command": line}), line
    assert blocked("search_files", {"pattern": "x", "path": "~"}) and blocked(
        "search_files", {"pattern": "x", "path": "/"}
    )
    assert not blocked("search_files", {"pattern": "x", "path": str(env["workspace"])})

    # Every vault, Hermes's credentials, the keychain, and the board stay out of reach.
    seat_vault = os.path.join(home, "profiles", "worker-1", "vault", "vault.key")
    for args in (
        {"command": f"cat {seat_vault}"},
        {"command": f"cp {home}/profiles/worker-2/vault/vault.json.enc /tmp/x"},
        {"command": f"cat {home}/.env"},
        {"command": f"less {home}/profiles/tester-1/.env"},
        {"command": "security find-generic-password -s x -w"},
        {"command": "secret-tool lookup service x"},
        {"command": "hermes --profile worker-1 vault add --kind login"},
        {"command": "hermes vault rm vault_1"},
        {"command": f"sqlite3 {home}/kanban/boards/{pack['board']}/kanban.db 'update tasks set status=1'"},
        {"command": "HERMES_DELEGATED_CHILD_CONTEXT=1 hermes kanban complete t_1"},
        {"command": "hermes kanban comment t_1 --author human 'go'"},
    ):
        assert blocked("terminal", args), args
    assert blocked("read_file", {"path": seat_vault}) and blocked("read_file", {"path": f"{home}/auth.json"})
    assert blocked("write_file", {"path": f"{home}/kanban/boards/{pack['board']}/kanban.db-wal", "content": "x"})
    for line in ("hermes vault list", "hermes kanban show t_1", "hermes kanban comment t_1 'done'"):
        assert not blocked("terminal", {"command": line}), line

    # A lane does not schedule jobs; the human may.
    assert check_tool("cronjob_manage", {"action": "create", "schedule": "5m"}) == "a lane does not schedule jobs"
    assert not blocked("cronjob_manage", {"action": "list"})
    monkeypatch.delenv("COCKPIT_LANE")
    assert not blocked("cronjob_manage", {"action": "create", "schedule": "5m"})


# Each fixture's per-seat rules: an MCP write it allows, a pattern refused for one seat kind, an extra write root.
SEAT_RULES = {
    "acme": {
        "allowed": "mcp__ledger__create_note",
        "denied_kind": "tester",
        "denied": "vaultctl read ops",
        "root_kind": "tester",
        "root": "{workspace}/acme-evidence",
    },
    "bravo": {
        "allowed": "mcp__fleet__deploy_web",
        "denied_kind": "reviewer",
        "denied": "fleet status web",
        "root_kind": "gatekeeper",
        "root": "{root}/north-notes",
    },
}


@pytest.mark.parametrize("pack_file", PACKS)
def test_mcp_writes_seat_denies_and_write_roots_follow_the_pack(env, pack_file, monkeypatch):
    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    pack = load(pack_file)
    own = SEAT_RULES[pack["name"]]
    other = SEAT_RULES["bravo" if pack["name"] == "acme" else "acme"]
    from cockpitlib.egress import check_tool
    from cockpitlib.paths import outbox, qa

    monkeypatch.setenv("COCKPIT_LANE", "reviewer")
    assert check_tool("mcp__tracker__create_issue", {"title": "x"}) == "an MCP write goes through the outbox"
    assert check_tool("mcp__docs__search", {"q": "x"}) == "" and check_tool("mcp__docs__get_page", {"id": 1}) == ""
    assert check_tool(own["allowed"], {"x": 1}) == "" and check_tool(other["allowed"], {"x": 1}) != ""

    lane = {"tester": "tester-1", "worker": "worker-1"}.get(own["denied_kind"], own["denied_kind"])
    monkeypatch.setenv("COCKPIT_LANE", lane)
    assert check_tool("terminal", {"command": own["denied"]})
    monkeypatch.setenv("COCKPIT_LANE", "intake" if own["denied_kind"] != "intake" else "analyst")
    assert not check_tool("terminal", {"command": own["denied"]})

    root = own["root"].format(workspace=str(env["workspace"]), root=str(env["root"]))
    lane = {"tester": "tester-1"}.get(own["root_kind"], own["root_kind"])
    monkeypatch.setenv("COCKPIT_LANE", lane)
    assert check_tool("write_file", {"path": os.path.join(root, "note.md"), "content": "x"}) == ""
    assert check_tool("terminal", {"command": f"echo x > {os.path.join(root, 'note.md')}"}) == ""
    assert (
        check_tool("write_file", {"path": os.path.join(str(env["workspace"]), "elsewhere.md"), "content": "x"})
        == "blocked"
    )
    other_root = other["root"].format(workspace=str(env["workspace"]), root=str(env["root"]))
    assert check_tool("write_file", {"path": os.path.join(other_root, "note.md"), "content": "x"}) == "blocked"
    # Every non-worker seat kind is fenced, including the tester and the gatekeeper.
    for kind, allowed in (("tester-1", qa()), ("gatekeeper", outbox())):
        monkeypatch.setenv("COCKPIT_LANE", kind)
        assert check_tool("write_file", {"path": os.path.join(allowed, "TASK-1", "x.md"), "content": "x"}) == ""
        assert check_tool("write_file", {"path": "/etc/cockpit-test", "content": "x"}) == "blocked"
    monkeypatch.setenv("COCKPIT_LANE", "gatekeeper")
    assert check_tool("write_file", {"path": os.path.join(qa(), "TASK-1", "x.md"), "content": "x"}) == "blocked"


def test_a_pack_refuses_named_tools_on_lanes_and_proves_its_host_rule(env, monkeypatch):
    acme = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "packs", "acme", "pack.yaml")
    monkeypatch.setenv("COCKPIT_PACK", acme)
    from cockpitlib.doctor import host_problems
    from cockpitlib.egress import check_tool, explained

    monkeypatch.setenv("COCKPIT_LANE", "tester-1")
    assert check_tool("browser_cdp", {"method": "Page.navigate"}) == "blocked"
    assert "browser_cdp" in explained("blocked")
    assert check_tool("mcp__ledger__get_note", {"id": 1}) == ""
    monkeypatch.delenv("COCKPIT_LANE")
    assert check_tool("browser_cdp", {"method": "Page.navigate"}) == ""

    pack = load(acme)
    assert host_problems(pack) == []
    pack["egress"]["host_probes"] = {
        "refused": ["curl https://elsewhere.example"],
        "allowed": ["curl app.acme.example"],
    }
    assert host_problems(pack) == [
        "production host NOT blocked: curl https://elsewhere.example",
        "production_hosts refuses a command it must allow: curl app.acme.example",
    ]
    pack["egress"].pop("host_probes")
    assert host_problems(pack) == []
    pack["egress"]["production_hosts"] = []
    assert host_problems(pack) == ["egress production_hosts is empty"]
    for bad in ({"refused": "curl x"}, {"later": []}, ["curl x"]):
        with pytest.raises(Exception, match="host_probes"):
            from cockpitlib.pack import _egress

            _egress({"host_probes": bad})
    with pytest.raises(Exception, match="deny_tools"):
        from cockpitlib.pack import _egress

        _egress({"deny_tools": "browser_cdp"})


@pytest.mark.parametrize("pack_file", PACKS)
def test_a_refusal_keeps_its_verdict_and_tells_the_lane_the_rule(env, pack_file, monkeypatch):
    """The verdict callers compare stays `blocked`; the lane reads which rule refused it, through the shell hook and the
    plugin alike, so it takes the allowed route instead of retrying variants. A write target's $VARIABLES are expanded."""
    import subprocess

    from cockpitlib.egress import check_tool, explained
    from cockpitlib.paths import qa
    from tests.support.hermes_contract import block_message, call

    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    monkeypatch.setenv("COCKPIT_LANE", "gatekeeper")
    assert check_tool("write_file", {"path": "/etc/cockpit-test", "content": "x"}) == "blocked"
    told = explained("blocked")
    assert told.startswith("blocked: a write outside your roots (/etc/cockpit-test); a gatekeeper writes under: ")
    assert check_tool("write_file", {"path": os.path.join(qa(), "TASK-1", "x.md"), "content": "x"}) == "blocked"
    assert check_tool("terminal", {"command": "ls"}) == "" and explained("") == ""  # a pass leaves no stale rule behind
    assert explained("the browser is lent to another ticket") == "the browser is lent to another ticket"

    monkeypatch.setenv("COCKPIT_LANE", "reviewer")
    monkeypatch.setenv("COCKPIT_TEST_ROOT", qa())
    assert check_tool("terminal", {"command": "echo x > $COCKPIT_TEST_ROOT/TASK-1/x.md"}) == ""
    assert check_tool("terminal", {"command": "echo x > ${COCKPIT_TEST_ROOT}/TASK-1/x.md"}) == ""
    assert check_tool("terminal", {"command": "echo x > $COCKPIT_NOT_SET/x.md"}) == "blocked"
    # A relative target is read from the folder an earlier `cd` moved to; a segment's own punctuation is not part of it.
    assert (
        check_tool("terminal", {"command": f"cd {qa()}/TASK-1 && gh run view 1 --log > job.log 2>&1; wc -l job.log"})
        == ""
    )
    assert check_tool("terminal", {"command": "cd /etc && echo x > cockpit-test"}) == "blocked"
    assert explained("blocked").startswith("blocked: a write outside your roots (/etc/cockpit-test)")
    assert check_tool("terminal", {"command": f"echo x | tee -a {qa()}/TASK-1/x.md"}) == ""
    assert check_tool("terminal", {"command": "echo x | tee -a /etc/cockpit-test"}) == "blocked"
    assert check_tool("terminal", {"command": "echo guarantee done"}) == ""  # "tee" inside a word is no tee

    pre = _plugin_hooks("cockpit_plugin_reasons")["pre_tool_call"]
    monkeypatch.setenv("COCKPIT_LANE", "gatekeeper")
    message = block_message(
        call(pre, "pre_tool_call", tool_name="write_file", args={"path": "/etc/cockpit-test", "content": "x"})
    )
    assert message and message.startswith("blocked: a write outside your roots (/etc/cockpit-test)")

    shell = os.path.join(ROOT, "hooks", "egress.py")
    done = subprocess.run(
        [sys.executable, shell],
        check=False,
        input=json.dumps({"tool_name": "write_file", "tool_input": {"path": "/etc/cockpit-test", "content": "x"}}),
        capture_output=True,
        text=True,
        env={**os.environ},
    )
    assert done.returncode == 2
    answer = json.loads(done.stdout)
    assert (
        answer["action"] == "block"
        and answer["message"].startswith("blocked: a write outside your roots")
        and answer["reason"] == answer["message"]
    )


@pytest.mark.parametrize("pack_file", PACKS)
def test_an_editor_agent_outside_the_lanes_meets_closed_slots_and_vaults(env, pack_file, monkeypatch, capsys):
    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    pack = load(pack_file)
    other = load(PACKS[0] if pack["name"] == "bravo" else PACKS[1])
    from cockpitlib.accounts import manifest
    from cockpitlib.paths import volumes, wt
    from cockpitlib.vault import login_metadata

    account = manifest(pack)["accounts"][0]["identifier"]
    foreign = manifest(other)["accounts"][0]["identifier"]
    monkeypatch.delenv("COCKPIT_HUMAN")
    monkeypatch.setenv("CLAUDECODE", "1")
    outside = str(env["workspace"])

    def guard(payload):
        monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(payload)))
        code = main(["guard"])
        return code, capsys.readouterr()

    for payload in (
        {"tool_name": "Bash", "tool_input": {"command": "cockpit vault list"}, "cwd": outside},
        {"command": "hermes --profile tester-1 vault list", "cwd": outside},
        {
            "tool_name": "Read",
            "tool_input": {"file_path": f"{env['home']}/profiles/tester-1/vault/vault.key"},
            "cwd": outside,
        },
        {"tool_name": "Bash", "tool_input": {"command": f"ls {volumes()}"}, "cwd": outside},
        {"tool_name": "Bash", "tool_input": {"command": f"open https://app.test/login?u={account}"}, "cwd": outside},
        {"tool_name": "Bash", "tool_input": {"command": "cockpit slot up 1"}, "cwd": outside},
    ):
        code, shown = guard(payload)
        assert code == 2 and shown.err.startswith("outside the lanes"), payload
        answer = json.loads(shown.out)
        assert (
            answer["decision"] == "block" and answer["permission"] == "deny" and answer["reason"] == shown.err.strip()
        )
    assert guard({"tool_name": "Bash", "tool_input": {"command": "git status"}, "cwd": outside})[0] == 0
    assert guard({"tool_name": "Bash", "tool_input": {"command": f"echo {foreign}"}, "cwd": outside})[0] == 0
    os.makedirs(os.path.join(wt(), "TASK-1", "api"), exist_ok=True)
    assert (
        guard(
            {
                "tool_name": "Bash",
                "tool_input": {"command": "cockpit vault list"},
                "cwd": os.path.join(wt(), "TASK-1", "api"),
            }
        )[0]
        == 0
    )
    monkeypatch.setattr(sys, "stdin", io.StringIO("not json"))
    assert main(["guard"]) == 2 and "unreadable" in capsys.readouterr().err
    assert main(["guard", "extra"]) == 2
    monkeypatch.chdir(outside)
    with pytest.raises(CockpitError, match="outside the lanes: the vaults stay closed"):
        login_metadata()
    monkeypatch.setenv("COCKPIT_HUMAN", "1")
    assert guard({"tool_name": "Bash", "tool_input": {"command": "cockpit vault list"}, "cwd": outside})[0] == 0


def _plugin_hooks(name):
    import importlib.util

    spec = importlib.util.spec_from_file_location(name, os.path.join(ROOT, "__init__.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    hooks = {}

    class Ctx:
        def register_skill(self, *_args):
            return None

        def register_hook(self, event, fn):
            hooks[event] = fn

    module.register(Ctx())
    return hooks


@pytest.mark.parametrize("pack_file", PACKS)
def test_plugin_hooks_follow_the_recorded_hermes_contract(env, pack_file, monkeypatch):
    from tests.support.hermes_contract import CONTRACT, block_message, call

    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    pack = load(pack_file)
    other = load(PACKS[0] if pack["name"] == "bravo" else PACKS[1])
    hooks = _plugin_hooks("cockpit_plugin_contract")
    assert set(hooks) == set(CONTRACT["events"])
    for event in CONTRACT["events"]:
        assert call(hooks[event], event) is None
    pre = hooks["pre_tool_call"]
    assert call(pre, "pre_tool_call", tool_name="terminal", args={"command": "git status"}) is None
    assert block_message(call(pre, "pre_tool_call", tool_name="terminal", args={"command": "git push origin x"}))
    own = pack["refused"]["hosts"][0]
    assert block_message(call(pre, "pre_tool_call", tool_name="terminal", args={"command": f"curl https://{own}/"}))
    assert (
        call(
            pre,
            "pre_tool_call",
            tool_name="terminal",
            args={"command": f"curl https://{other['refused']['hosts'][0]}/"},
        )
        is None
    )


@pytest.mark.parametrize("pack_file", PACKS)
def test_each_pack_refuses_its_own_infra_commands(env, pack_file, monkeypatch):
    from tests.support.hermes_contract import block_message, call

    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    pack = load(pack_file)
    pre = _plugin_hooks("cockpit_plugin_infra")["pre_tool_call"]
    own = {"acme": "vaultctl destroy cluster-1", "bravo": "fleet drain node-2"}
    for name, command in own.items():
        answer = call(pre, "pre_tool_call", tool_name="terminal", args={"command": command})
        if name == pack["name"]:
            assert block_message(answer)
            continue
        assert answer is None
    assert (
        call(pre, "pre_tool_call", tool_name="terminal", args={"command": "kubectl delete ns demo"}) is None
    )  # not the kernel's to know


@pytest.mark.parametrize("pack_file", PACKS)
def test_the_hook_still_answers_when_the_bound_pack_is_missing(env, pack_file, monkeypatch):
    import subprocess

    from tests.support.hermes_contract import block_message, call

    monkeypatch.setenv(
        "COCKPIT_PACK",
        os.path.join(str(env["workspace"]), "missing", os.path.basename(os.path.dirname(pack_file)), "pack.yaml"),
    )
    shell = os.path.join(ROOT, "hooks", "egress.py")

    def run(command):
        return subprocess.run(
            [sys.executable, shell],
            check=False,
            input=json.dumps({"tool_name": "terminal", "tool_input": {"command": command}}),
            capture_output=True,
            text=True,
        )

    status = run("git status")  # it answers (G-5: a bound pack that is gone fails closed)
    assert status.returncode == 2 and json.loads(status.stdout)["message"].startswith("pack unreadable")
    pushed = run("git push origin x")
    assert pushed.returncode == 2 and json.loads(pushed.stdout)["message"]
    pre = _plugin_hooks("cockpit_plugin_no_pack")["pre_tool_call"]
    assert block_message(call(pre, "pre_tool_call", tool_name="terminal", args={"command": "git status"})).startswith(
        "pack unreadable"
    )
    assert call(pre, "pre_tool_call", tool_name="read_file", args={"path": "README"}) is None
    assert block_message(call(pre, "pre_tool_call", tool_name="terminal", args={"command": "git push origin x"}))


@pytest.mark.parametrize("pack_file", PACKS)
def test_a_worker_edits_only_the_ticket_checkout(env, pack_file, monkeypatch):
    import subprocess

    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    monkeypatch.setenv("COCKPIT_LANE", "worker-1")
    pack = load(pack_file)
    from cockpitlib.acts import kickoff_text
    from cockpitlib.egress import check_bound
    from cockpitlib.pack import agent_launch

    other = load(PACKS[0] if pack["name"] == "bravo" else PACKS[1])
    assert agent_launch(pack)["router"] != agent_launch(other)["router"]
    text = kickoff_text(pack, "TASK-996", "worker", "")
    assert "one skill" in text and agent_launch(pack)["router"] in text
    assert check_bound("echo hi") == ""
    assert check_bound("echo hi > /tmp/cockpit-not-a-checkout") == "blocked"
    name = pack["repos"]["repos"][0]["name"]
    side = env["root"] / "wt" / "TASK-996" / name
    side.mkdir(parents=True)
    (env["root"] / "wt" / "note").write_text("x", encoding="utf-8")  # a file beside the tickets is no checkout
    assert check_bound(f"echo hi > {side / 'note'}") == ""
    source = env["root"] / "repos" / name
    assert check_bound(f"echo hi > {source / 'note'}") == "blocked"
    subprocess.run(
        ["git", "-C", str(source), "checkout", "-B", f"{pack['branch_prefix']}/TASK-996"],
        check=True,
        capture_output=True,
    )
    assert check_bound(f"echo hi > {source / 'note'}") == "blocked", (
        "a ticket branch in the repo's own checkout is not the worker's"
    )


@pytest.mark.parametrize("pack_file", PACKS)
def test_a_worker_writes_in_ticket_worktrees_whatever_card_runs_and_the_removed_card_rule_is_refused(
    env, pack_file, tmp_path, monkeypatch
):
    """A worker writes in ticket worktrees, whatever repos its card names, and never in a repo's own checkout. The
    egress.yaml key that once narrowed this is refused by name."""
    import shutil
    import subprocess

    import yaml

    from cockpitlib.egress import check_bound, check_tool, explained
    from cockpitlib.errors import PackError
    from cockpitlib.kanban import remember_card

    copied = tmp_path / "packs" / os.path.basename(os.path.dirname(pack_file))
    shutil.copytree(os.path.dirname(pack_file), copied)
    raw = yaml.safe_load((copied / "egress.yaml").read_text(encoding="utf-8"))
    for value in (True, False):
        (copied / "egress.yaml").write_text(
            yaml.safe_dump({**raw, "card_repos_only": value}, sort_keys=False), encoding="utf-8"
        )
        with pytest.raises(
            PackError,
            match="^egress.yaml: unknown key card_repos_only: it was removed; a worker writes only in its ticket's worktrees$",
        ):
            load(str(copied / "pack.yaml"))
    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    pack = load(pack_file)
    ticket = "TASK-1300"
    own, other = [repo["name"] for repo in pack["repos"]["repos"]][:2]
    for name in (own, other):
        subprocess.run(
            ["git", "-C", str(env["root"] / "repos" / name), "checkout", "-B", f"{pack['branch_prefix']}/{ticket}"],
            check=True,
            capture_output=True,
        )
        (env["root"] / "wt" / ticket / name).mkdir(parents=True)
    remember_card(str(pack["board"]), "t_unit", "worker", ticket, repos=[own])
    monkeypatch.setenv("COCKPIT_LANE", "worker-1")
    monkeypatch.delenv("HERMES_KANBAN_BOARD", raising=False)

    def decided() -> list:
        sides = [check_bound(f"echo hi > {env['root'] / 'wt' / ticket / name / 'note'}") for name in (own, other)]
        sources = [check_bound(f"echo hi > {env['root'] / 'repos' / name / 'note'}") for name in (own, other)]
        tools = [
            check_tool("write_file", {"path": str(env["root"] / "repos" / name / "note"), "content": "x"})
            for name in (own, other)
        ]
        return sides + sources + tools

    for card in ("t_unit", "t_gone", ""):
        monkeypatch.setenv("HERMES_KANBAN_TASK", card)
        assert decided() == ["", "", "blocked", "blocked", "blocked", "blocked"]
        assert "outside your ticket checkouts" in explained("blocked")
    monkeypatch.delenv("COCKPIT_LANE")  # the human's own session
    assert decided() == [""] * 6


@pytest.mark.parametrize("pack_file", PACKS)
def test_a_tool_cannot_read_the_slot_secret(env, pack_file, monkeypatch):
    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    monkeypatch.setenv("COCKPIT_LANE", "tester-1")
    pack = load(pack_file)
    other = load(PACKS[0] if pack["name"] == "bravo" else PACKS[1])
    from cockpitlib.egress import check_bound, check_tool
    from cockpitlib.pack import policy
    from cockpitlib.paths import hermes_home
    from cockpitlib.slots import state_dir

    assert pack["privileged"]["label"] != other["privileged"]["label"]
    secret = f"secret-{pack['privileged']['label']}"
    path = os.path.join(state_dir(1), "login.json")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    open(path, "w", encoding="utf-8").write(json.dumps({"secret": secret}))
    allowed = policy(pack)["reads"][0]
    assert allowed != policy(other)["reads"][0]
    assert check_bound(allowed) == ""
    assert check_bound(f"{allowed} {path}") == "blocked"
    assert check_bound(f"cat {path}") == "blocked"
    assert check_tool("terminal", {"command": f"cat {path}"}) == "blocked"
    assert secret not in check_bound(f"cat {path}")
    assert check_tool("read_file", {"path": path}) == "blocked"
    vault = os.path.join(hermes_home(), "vault", "vault.key")
    assert check_bound(f"cat {vault}") == "blocked"
    note = env["root"] / "repos" / "note.txt"
    note.parent.mkdir(parents=True, exist_ok=True)
    note.write_text("plain\n", encoding="utf-8")
    assert check_tool("read_file", {"path": str(note)}) == ""


@pytest.mark.parametrize("pack_file", PACKS)
def test_a_bound_pack_that_cannot_be_read_refuses_network_tools_and_leaves_local_reads(
    env, pack_file, monkeypatch, tmp_path
):
    import shutil
    import subprocess

    from cockpitlib.egress import check_tool

    name = os.path.basename(os.path.dirname(pack_file))
    copied = tmp_path / "packs" / name
    shutil.copytree(os.path.dirname(pack_file), copied)
    monkeypatch.setenv("COCKPIT_PACK", str(copied / "pack.yaml"))
    assert check_tool("terminal", {"command": "git status"}) == ""
    (copied / "pack.yaml").write_text("name: [broken\n", encoding="utf-8")
    for tool, args in (
        ("terminal", {"command": "curl https://example.test/"}),
        ("terminal", {"command": "git status"}),
        ("web_extract", {"urls": ["https://example.test/"]}),
        ("write_file", {"path": "x", "content": "y"}),
    ):
        assert check_tool(tool, args).startswith("pack unreadable"), tool
    for tool, args in (
        ("read_file", {"path": "README"}),
        ("search_files", {"pattern": "x", "path": "."}),
        ("kanban_block", {"reason": "pack"}),
    ):
        assert check_tool(tool, args) == "", tool
    hook = os.path.join(ROOT, "hooks", "egress.py")
    done = subprocess.run(
        [sys.executable, hook],
        check=False,
        input=json.dumps({"tool_name": "terminal", "args": {"command": "curl https://example.test/"}}),
        capture_output=True,
        text=True,
        env=os.environ.copy(),
    )
    assert done.returncode == 2 and "pack unreadable" in done.stdout
    (copied / "pack.yaml").unlink()  # bound, but gone: the same
    assert check_tool("terminal", {"command": "curl https://example.test/"}).startswith("pack unreadable")
    monkeypatch.delenv("COCKPIT_PACK")
    from cockpitlib.paths import binding_file

    assert not os.path.isfile(binding_file())
    assert (
        check_tool("terminal", {"command": "git status"}) == ""
    )  # nothing bound: no adoption, the kernel's checks only
    os.makedirs(os.path.dirname(binding_file()), exist_ok=True)
    open(binding_file(), "w", encoding="utf-8").write(f"pack: {copied / 'pack.yaml'}\n")
    assert check_tool("terminal", {"command": "git status"}).startswith("pack unreadable")
    open(binding_file(), "w", encoding="utf-8").write("pack: [bad\n")
    assert check_tool("terminal", {"command": "git status"}).startswith(
        "pack unreadable"
    )  # an unreadable binding is bound
    os.remove(binding_file())


@pytest.mark.parametrize("pack_file", PACKS)
def test_cursor_hooks_put_the_fence_in_front_of_a_cursor_agent_lane(env, pack_file, monkeypatch, tmp_path):
    # A cursor-agent seat runs Cursor's own tools; Hermes's pre_tool_call never sees them, Cursor's preToolUse does.
    import subprocess

    from cockpitlib.doctor import run as doctor_run
    from cockpitlib.setup import cursor_hook_command, cursor_hook_installed, cursor_hooks_path, setup

    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    pack = load(pack_file)
    path = cursor_hooks_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    theirs = {"command": "/opt/guard.sh", "matcher": "Shell"}
    with open(path, "w", encoding="utf-8") as handle:
        json.dump({"version": 1, "hooks": {"preToolUse": [theirs], "stop": [{"command": "/opt/stop.sh"}]}}, handle)
    setup(pack)
    assert not cursor_hook_installed()
    pack["agent"]["cursor_hooks"] = True
    assert any("agent.cursor_hooks" in item for item in doctor_run(pack))
    setup(pack)
    setup(pack)
    data = json.load(open(path, encoding="utf-8"))
    assert data["hooks"]["preToolUse"] == [{"command": cursor_hook_command()}, theirs]
    assert data["hooks"]["stop"] == [{"command": "/opt/stop.sh"}] and cursor_hook_installed()
    assert not any("agent.cursor_hooks" in item for item in doctor_run(pack))
    pack["agent"]["cursor_hooks"] = False
    setup(pack)
    assert json.load(open(path, encoding="utf-8"))["hooks"]["preToolUse"] == [theirs]
    with open(path, "w", encoding="utf-8") as handle:
        handle.write("{not json")
    setup(pack)  # not opted in: a file cockpit cannot read does not stop setup
    with open(path, "w", encoding="utf-8") as handle:
        handle.write("[1]")
    setup(pack)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write("{not json")
    pack["agent"]["cursor_hooks"] = True
    with pytest.raises(CockpitError, match="is not JSON"):
        setup(pack)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write("[1]")
    with pytest.raises(CockpitError, match="is not a hooks file"):
        setup(pack)
    os.remove(path)
    setup(pack)
    assert cursor_hook_installed()

    def ask(payload, lane="worker-1", raw=None):
        child = {**os.environ, "COCKPIT_PACK": pack_file}
        child.pop("COCKPIT_LANE", None)
        if lane:
            child["COCKPIT_LANE"] = lane
        done = subprocess.run(
            [sys.executable, cursor_hook_command()],
            input=raw if raw is not None else json.dumps(payload),
            capture_output=True,
            text=True,
            env=child,
            check=False,
            timeout=60,
        )
        assert done.returncode == 0, done.stderr
        return json.loads(done.stdout)

    roots = [str(env["workspace"])]
    assert (
        ask(
            {
                "tool_name": "Shell",
                "tool_input": {"command": "git push origin rc", "cwd": roots[0]},
                "workspace_roots": roots,
            }
        )["permission"]
        == "deny"
    )
    refused = ask({"tool_name": "Shell", "tool_input": {"command": "git push origin rc"}, "workspace_roots": roots})
    assert refused["permission"] == "deny" and refused["agent_message"].startswith("blocked")
    assert ask({"tool_name": "Shell", "tool_input": {"command": "git status"}, "workspace_roots": roots}) == {
        "permission": "allow"
    }
    assert (
        ask({"tool_name": "Read", "tool_input": {"file_path": os.path.join(str(env["home"]), "auth.json")}})[
            "permission"
        ]
        == "deny"
    )
    assert (
        ask({"tool_name": "Write", "tool_input": {"file_path": "/etc/cockpit-test", "content": "x"}}, lane="tester-1")[
            "permission"
        ]
        == "deny"
    )
    assert ask({"tool_name": "MCP:create_issue", "tool_input": {"title": "x"}})["permission"] == "deny"
    assert ask({"tool_name": "Shell", "tool_input": {"command": "git push origin rc"}}, lane="") == {
        "permission": "allow"
    }
    assert ask({}, raw="{not json")["permission"] == "deny"
    assert ask({}, raw="{not json", lane="") == {"permission": "allow"}
    # Cursor lets a call through when a hook crashes: in a lane, a failure of the fence itself is a refusal.
    crashed = ask({"tool_name": "Shell", "tool_input": {"command": "ls"}, "workspace_roots": 5})
    assert crashed["permission"] == "deny" and "fence failed" in crashed["agent_message"]
    assert ask({"tool_name": "Shell", "tool_input": {"command": "ls"}, "workspace_roots": 5}, lane="") == {
        "permission": "allow"
    }


def test_the_cursor_hook_maps_cursor_tools_to_the_names_the_fence_knows():
    import runpy

    hook = runpy.run_path(
        os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "hooks", "cursor.py")
    )
    call = hook["hermes_call"]
    assert call("Shell", {"command": "ls"}) == ("terminal", {"command": "ls"})
    assert call("Write", {"file_path": "a", "content": "x"}) == (
        "write_file",
        {"file_path": "a", "content": "x", "contents": "x"},
    )
    assert call("Delete", {"file_path": "a"}) == ("write_file", {"file_path": "a"})
    assert call("Grep", {"file_path": "/", "pattern": "x"}) == ("grep", {"file_path": "/", "pattern": "x"})
    assert call("MCP:list_pages", None) == ("mcp__cursor__list_pages", {})
    assert call("WebFetch", {"url": "https://x"}) == ("WebFetch", {"url": "https://x"})
