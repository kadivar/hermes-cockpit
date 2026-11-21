# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The tracker through Hermes's Jira connector (tracker.kind connector, the default) beside the REST API (rest, or its
older name jira) and the pack's command. The connector answers with Jira's own JSON, so the REST tracker's logic —
transition matching, read-backs, dry runs — is the one under test; only the transport is the connector's."""

import json
import os
import shutil
import sys
import types

import pytest

from cockpitlib.errors import CockpitError, PackError
from cockpitlib.pack import load
from cockpitlib.tracker import CommandTracker, ConnectorTracker, JiraTracker, tracker_for

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PACK = {"tracker": {"url": "https://acme.atlassian.net", "project": "TASK"}}


class FakeJira:
    """The connector's operations over a tiny Jira: one issue, its status, assignee and comments."""

    def __init__(self):
        self.calls = []
        self.status = "To Plan"
        self.assignee = ""
        self.comments = {}
        self.created = {}

    def __call__(self, connector, tool, arguments):
        self.calls.append((connector, tool, arguments))
        if tool == "GET_TRANSITIONS":
            return {
                "transitions": [
                    {"id": "21", "name": "In Progress", "to": {"name": "In Progress"}},
                    {"id": "31", "name": "Done", "to": {"name": "Done"}},
                ]
            }
        if tool == "TRANSITION_ISSUE":
            self.status = {"21": "In Progress", "31": "Done"}[arguments["transition_id_or_name"]]
            return {}
        if tool == "GET_ISSUE":
            fields = {
                "status": {
                    "name": self.status,
                    "statusCategory": {"key": getattr(self, "STATUSES", {}).get(self.status, "")},
                },
                "summary": "Fix the totals",
                "assignee": {"accountId": self.assignee} if self.assignee else None,
            }
            fields.update(self.created.get(arguments["issue_id_or_key"], {}))
            return {"key": arguments["issue_id_or_key"], "fields": fields}
        if tool == "GET_CURRENT_USER":
            return {"accountId": "acct-me", "emailAddress": "me@example.test"}
        if tool == "ASSIGN_ISSUE":
            self.assignee = arguments["account_id"]
            return {}
        if tool == "ADD_COMMENT":
            made = str(100 + len(self.comments))
            self.comments[made] = arguments
            return {"id": made}
        if tool == "GET_COMMENT":
            return {
                "id": arguments["comment_id"],
                "body": (self.comments[arguments["comment_id"]].get("additional_properties") or {}).get("body"),
            }
        if tool == "CREATE_ISSUE":
            self.created["TASK-9"] = {
                key: value for key, value in json.loads(arguments.get("additional_properties") or "{}").items()
            }
            if arguments.get("assignee"):
                self.created["TASK-9"]["assignee"] = {"accountId": arguments["assignee"]}
            return {"key": "TASK-9", "id": "10009"}
        raise AssertionError(f"unexpected {tool}")


def connector_tracker(fake, dry_run=False):
    return ConnectorTracker({"url": "https://acme.atlassian.net", "project": "TASK"}, dry_run, call=fake)


def tools(fake):
    return [tool for _connector, tool, _arguments in fake.calls]


def test_the_kind_picks_the_tracker_and_the_connector_is_the_default():
    assert isinstance(tracker_for(PACK), ConnectorTracker)
    for kind in ("jira",):
        made = tracker_for({"tracker": {**PACK["tracker"], "kind": kind}})
        assert isinstance(made, JiraTracker) and not isinstance(made, ConnectorTracker), kind
    assert isinstance(tracker_for({"tracker": {**PACK["tracker"], "command": ["tickets"]}}), CommandTracker), (
        "a command alone still means it"
    )
    assert tracker_for({"tracker": {**PACK["tracker"], "connector": "jira_cloud"}}).connector == "jira_cloud"


def test_a_transition_goes_through_the_connector_and_is_read_back():
    fake = FakeJira()
    url, out, _made = connector_tracker(fake).transition(
        {"payload": {"to": "In Progress", "assignee": "me"}}, {}, "TASK-1"
    )
    assert url == "https://acme.atlassian.net/browse/TASK-1"
    assert out == "In Progress → In Progress (status now In Progress); assigned me"
    assert tools(fake) == [
        "GET_TRANSITIONS",
        "TRANSITION_ISSUE",
        "GET_ISSUE",
        "GET_CURRENT_USER",
        "ASSIGN_ISSUE",
        "GET_ISSUE",
    ]
    assert fake.calls[1][2] == {"issue_id_or_key": "TASK-1", "transition_id_or_name": "21"}
    assert fake.calls[4][2] == {"issue_id_or_key": "TASK-1", "account_id": "acct-me"}
    assert all(connector == "jira" for connector, _tool, _arguments in fake.calls)


def test_a_read_back_that_disagrees_is_refused():
    fake = FakeJira()
    original = fake.__call__

    def stuck(connector, tool, arguments):
        if tool == "TRANSITION_ISSUE":
            fake.calls.append((connector, tool, arguments))
            return {}  # Jira took the call and the issue did not move
        return original(connector, tool, arguments)

    with pytest.raises(CockpitError, match="read-back: TASK-1 is 'To Plan'"):
        connector_tracker(stuck).transition({"payload": {"to": "Done"}}, {}, "TASK-1")


def test_a_dry_run_reads_and_records_the_writes_without_making_them():
    fake = FakeJira()
    tracker = connector_tracker(fake, dry_run=True)
    _url, out, _made = tracker.transition({"payload": {"to": "In Progress"}}, {}, "TASK-1")
    assert out == "would move TASK-1 → In Progress"
    assert tools(fake) == ["GET_TRANSITIONS"], "only reads reached the connector"
    assert [write["path"] for write in tracker.writes] == ["/rest/api/3/issue/TASK-1/transitions"]


def test_a_comment_is_posted_as_text_or_as_its_document_and_read_back(bare):
    fake = FakeJira()
    url, out, made = connector_tracker(fake).comment(
        {"ticket": "TASK-1", "payload": {"issue": "TASK-1", "body": "Progress: done"}}, {}
    )
    assert fake.calls[0][1:] == ("ADD_COMMENT", {"issue_id_or_key": "TASK-1", "comment": "Progress: done"})
    assert made == {"comment": "100"} and "read back" in out
    document = {
        "type": "doc",
        "version": 1,
        "content": [{"type": "paragraph", "content": [{"type": "text", "text": "Hi"}]}],
    }
    draft = bare["workspace"] / "note.json"
    draft.write_text(json.dumps(document), encoding="utf-8")
    connector_tracker(fake).comment({"ticket": "TASK-1", "payload": {"issue": "TASK-1", "body_file": "note.json"}}, {})
    posted = fake.calls[-2][2]
    assert posted["additional_properties"] == {"body": document} and posted["comment"] == "Hi"


def test_an_issue_is_created_with_jiras_own_field_shapes_for_what_the_connector_has_no_argument_for():
    fake = FakeJira()
    tracker = connector_tracker(fake)
    tracker._meta = lambda project, kind: {
        "components": {"fieldId": "components", "allowedValues": [{"name": "Billing"}]}
    }
    _url, out, made = tracker.create(
        {"payload": {"summary": "Totals", "component": "billing", "assignee": "me", "labels": ["qa"]}}, {}
    )
    created = next(arguments for _c, tool, arguments in fake.calls if tool == "CREATE_ISSUE")
    assert created["project_key"] == "TASK" and created["issue_type"] == "Task" and created["labels"] == ["qa"]
    assert created["assignee"] == "acct-me"
    assert json.loads(created["additional_properties"]) == {"components": [{"name": "Billing"}]}
    assert made == {"key": "TASK-9"} and out.startswith("TASK-9")


def test_a_rest_call_the_connector_has_no_operation_for_is_refused_not_guessed():
    with pytest.raises(CockpitError, match="no operation for DELETE /rest/api/3/issue/TASK-1/watchers"):
        connector_tracker(FakeJira())._request("DELETE", "/rest/api/3/issue/TASK-1/watchers")


def test_the_connectors_answer_says_what_went_wrong_in_its_words():
    from cockpitlib.connector import answer_data

    assert answer_data("jira", "GET_ISSUE", {"response": {"successful": True, "data": {"key": "X-1"}}}) == {
        "key": "X-1"
    }
    with pytest.raises(CockpitError, match="not connected: run `hermes connectors connect jira`"):
        answer_data("jira", "GET_ISSUE", {"error": {"code": "CONNECTION_REQUIRED", "message": "connect first"}})
    with pytest.raises(CockpitError, match=r"\(GET_ISSUE\): This tool does not exist. \[TOOL_NOT_FOUND\]"):
        answer_data("jira", "GET_ISSUE", {"error": {"code": "TOOL_NOT_FOUND", "message": "This tool does not exist."}})
    with pytest.raises(CockpitError, match="no transition"):
        answer_data("jira", "TRANSITION_ISSUE", {"response": {"successful": False, "error": "no transition"}})


def test_cockpit_finds_hermess_interpreter_from_what_the_plugin_recorded(bare, monkeypatch, tmp_path):
    from cockpitlib import connector

    monkeypatch.delenv("COCKPIT_HERMES_PYTHON", raising=False)
    monkeypatch.delenv("COCKPIT_HERMES_ROOT", raising=False)
    with pytest.raises(CockpitError, match="cannot find Hermes"):
        connector.runtime()
    hermes_root = tmp_path / "hermes-agent"
    hermes_root.mkdir()
    (hermes_root / "hermes_bootstrap.py").write_text("", encoding="utf-8")
    monkeypatch.setitem(
        sys.modules, "hermes_bootstrap", types.SimpleNamespace(__file__=str(hermes_root / "hermes_bootstrap.py"))
    )
    connector.record_runtime()
    assert connector.runtime() == (sys.executable, str(hermes_root))
    recorded = os.path.join(str(bare["home"]), "cockpit", "hermes-runtime.json")
    stamp = os.path.getmtime(recorded)
    connector.record_runtime()
    assert os.path.getmtime(recorded) == stamp, "unchanged: not rewritten"
    monkeypatch.setenv("COCKPIT_HERMES_PYTHON", sys.executable)
    monkeypatch.setenv("COCKPIT_HERMES_ROOT", str(hermes_root))
    assert connector.runtime() == (sys.executable, str(hermes_root))


def test_the_child_runs_the_connector_dispatch_on_hermess_interpreter(env, monkeypatch, tmp_path):
    """The real child, with a stand-in Hermes checkout: the bootstrap is imported first and the dispatch answers."""
    from cockpitlib import connector

    hermes_root = tmp_path / "hermes-agent"
    (hermes_root / "tools" / "connectors").mkdir(parents=True)
    (hermes_root / "hermes_bootstrap.py").write_text("import os\nos.environ['BOOTED'] = '1'\n", encoding="utf-8")
    for package in ("tools", "tools/connectors"):
        (hermes_root / package / "__init__.py").write_text("", encoding="utf-8")
    (hermes_root / "tools" / "connectors" / "dispatch.py").write_text(
        "import json, os\n"
        "def dispatch_connector_call(name, arguments, call_id):\n"
        "    return json.dumps({'response': {'successful': True, 'data': {'name': name, 'arguments': arguments,\n"
        "                                   'booted': os.environ.get('BOOTED')}}})\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("COCKPIT_HERMES_PYTHON", sys.executable)
    monkeypatch.setenv("COCKPIT_HERMES_ROOT", str(hermes_root))
    data = connector.call("jira", "GET_ISSUE", {"issue_id_or_key": "TASK-1"})
    assert data == {"name": "connectors__jira__GET_ISSUE", "arguments": {"issue_id_or_key": "TASK-1"}, "booted": "1"}


def acme_copy(folder, line):
    """The acme pack with its tracker's `kind: jira` line replaced by `line` (empty: the default kind)."""
    folder = folder / "packs" / "acme"  # where the pack's @skills resolves, as the fixtures' copies do
    shutil.copytree(os.path.join(ROOT, "packs", "acme"), folder)
    path = folder / "pack.yaml"
    text = path.read_text(encoding="utf-8")
    kind = next(row for row in text.splitlines(keepends=True) if row.startswith("  kind: jira"))
    path.write_text(text.replace(kind, line, 1), encoding="utf-8")
    return path


def test_the_pack_says_which_tracker_and_connector(bare, tmp_path):
    for line, message in (
        ("  kind: carrier-pigeon\n", "tracker.kind is one of connector, jira, command"),
        ("  connector: Jira Cloud!\n", "tracker.connector names a Hermes connector"),
    ):
        path = acme_copy(tmp_path / f"p{len(message)}", line)
        with pytest.raises(PackError, match=message):
            load(str(path))


def test_a_card_cannot_write_to_jira_through_the_connector_the_outbox_publishes_through(bare, monkeypatch, tmp_path):
    from cockpitlib.egress import check_tool

    path = acme_copy(tmp_path / "acme", "")  # no kind: the default, Hermes's connector
    monkeypatch.setenv("COCKPIT_PACK", str(path))
    monkeypatch.setenv("COCKPIT_LANE", "worker-1")
    assert (
        check_tool("connectors__jira__TRANSITION_ISSUE", {"issue_id_or_key": "TASK-1"})
        == "an MCP write goes through the outbox"
    )
    assert check_tool("connectors__jira__ADD_COMMENT", {"issue_id_or_key": "TASK-1", "comment": "x"}) != ""
    assert check_tool("connectors__jira__GET_ISSUE", {"issue_id_or_key": "TASK-1"}) == "", "reading is fine"
    assert check_tool("connectors__gmail__SEND_EMAIL", {"to": "a@example.test"}) == "", "not the tracker's connector"
    monkeypatch.delenv("COCKPIT_LANE")
    assert check_tool("connectors__jira__TRANSITION_ISSUE", {"issue_id_or_key": "TASK-1"}) == "", (
        "the owner's own session"
    )
    monkeypatch.setenv("COCKPIT_LANE", "worker-1")
    monkeypatch.setenv("COCKPIT_PACK", os.path.join(ROOT, "packs", "acme", "pack.yaml"))  # kind rest
    assert check_tool("connectors__jira__TRANSITION_ISSUE", {"issue_id_or_key": "TASK-1"}) == "", (
        "a REST pack leaves it alone"
    )


class Workflow(FakeJira):
    """Transitions that depend on where the issue is, like a real workflow: To Plan → To Do → In Progress, with
    released and archived (done) reachable from anywhere, and a Blocked side status that leads nowhere."""

    STATUSES = {
        "To Plan": "new",
        "To Do": "new",
        "Blocked": "indeterminate",
        "In Progress": "indeterminate",
        "RELEASED": "done",
        "Archived": "done",
    }
    MOVES = {
        "To Plan": [("Plan", "To Do"), ("Hold", "Blocked")],
        "To Do": [("Start", "In Progress"), ("Back to plan", "To Plan")],
        "Blocked": [("Unblock", "To Plan")],
        "In Progress": [("Back to plan", "To Plan")],
    }

    def __init__(self, status="To Plan", moves=None):
        super().__init__()
        self.status = status
        self.moves = moves or self.MOVES

    def _row(self, name, to, index):
        return {"id": f"{to}-{index}", "name": name, "to": {"name": to, "statusCategory": {"key": self.STATUSES[to]}}}

    def __call__(self, connector, tool, arguments):
        if tool == "GET_TRANSITIONS":
            self.calls.append((connector, tool, arguments))
            rows = [("RELEASED", "RELEASED"), ("Archived", "Archived")] + list(self.moves.get(self.status, []))
            return {"transitions": [self._row(name, to, index) for index, (name, to) in enumerate(rows)]}
        if tool == "TRANSITION_ISSUE":
            self.calls.append((connector, tool, arguments))
            self.status = arguments["transition_id_or_name"].rsplit("-", 1)[0]
            return {}
        return super().__call__(connector, tool, arguments)


def path(fake):
    return [
        arguments["transition_id_or_name"].rsplit("-", 1)[0]
        for _c, tool, arguments in fake.calls
        if tool == "TRANSITION_ISSUE"
    ]


def test_a_status_two_steps_away_is_reached_through_the_one_between():
    fake = Workflow()
    _url, out, _made = connector_tracker(fake).transition({"payload": {"to": "In Progress"}}, {}, "ACME-930")
    assert path(fake) == ["To Do", "In Progress"], "never through RELEASED or Archived"
    assert out == "from To Plan through To Do: In Progress → Start (status now In Progress)"
    assert fake.status == "In Progress"


def test_a_step_that_leads_nowhere_is_undone_before_the_next_is_tried():
    moves = {**Workflow.MOVES, "To Plan": [("Hold", "Blocked"), ("Plan", "To Do")]}
    moves["Blocked"] = [("Unblock", "To Plan")]
    fake = Workflow(moves=moves)
    fake.STATUSES = {**Workflow.STATUSES, "Blocked": "new"}  # tried first, as a not-started status would be
    connector_tracker(fake).transition({"payload": {"to": "In Progress"}}, {}, "ACME-930")
    assert path(fake) == ["Blocked", "To Plan", "To Do", "In Progress"]


def test_no_route_leaves_the_issue_where_it_started_and_says_what_was_tried():
    fake = Workflow(moves={"To Plan": [("Hold", "Blocked")], "Blocked": [("Unblock", "To Plan")]})
    with pytest.raises(
        CockpitError,
        match=r"no transition means 'In Progress' from 'To Plan', nor from \['Blocked'\].*back at 'To Plan'",
    ):
        connector_tracker(fake).transition({"payload": {"to": "In Progress"}}, {}, "ACME-930")
    assert fake.status == "To Plan" and path(fake) == ["Blocked", "To Plan"]


def test_a_step_with_no_way_back_says_where_the_issue_is():
    fake = Workflow(moves={"To Plan": [("Hold", "Blocked")], "Blocked": []})
    with pytest.raises(CockpitError, match="no way back: ACME-930 is at 'Blocked'"):
        connector_tracker(fake).transition({"payload": {"to": "In Progress"}}, {}, "ACME-930")


def test_only_done_statuses_on_offer_is_no_route_at_all():
    fake = Workflow(moves={"To Plan": []})
    with pytest.raises(CockpitError, match="no transition means 'In Progress' from 'To Plan'; available"):
        connector_tracker(fake).transition({"payload": {"to": "In Progress"}}, {}, "ACME-930")
    assert path(fake) == []


def test_a_dry_run_says_the_route_it_would_try_and_moves_nothing():
    fake = Workflow()
    _url, out, _made = connector_tracker(fake, dry_run=True).transition(
        {"payload": {"to": "In Progress"}}, {}, "ACME-930"
    )
    assert out == "would move ACME-930 → Plan, then → In Progress if the workflow allows it from there"
    assert path(fake) == []


def test_a_status_jira_does_not_categorise_is_never_a_way_through():
    """A transition without a status category could be anything, a Done included: no step is taken through it."""
    fake = Workflow()
    original = fake._row
    fake._row = lambda name, to, index: {**original(name, to, index), "to": {"name": to}}
    with pytest.raises(CockpitError, match="no transition means 'In Progress' from 'To Plan'; available"):
        connector_tracker(fake).transition({"payload": {"to": "In Progress"}}, {}, "ACME-930")
    assert path(fake) == []


def test_an_issue_already_where_it_is_asked_to_go_is_not_walked_away_and_back():
    """Two cards on one ticket each ask to start it; the second finds it In Progress with no In Progress transition."""
    fake = Workflow(status="In Progress")
    _url, out, _made = connector_tracker(fake).transition({"payload": {"to": "In Progress"}}, {}, "ACME-930")
    assert out == "ACME-930 is already In Progress" and path(fake) == []


def test_the_route_never_steps_backwards():
    """From In Progress, asked for In Review with no direct move: To Plan is a way round, but backwards — not taken."""
    statuses = {**Workflow.STATUSES, "In Review": "indeterminate"}
    fake = Workflow(
        status="In Progress", moves={"In Progress": [("Back to plan", "To Plan")], "To Plan": [("Review", "In Review")]}
    )
    fake.STATUSES = statuses
    with pytest.raises(CockpitError, match="no transition means 'In Review' from 'In Progress'; available"):
        connector_tracker(fake).transition({"payload": {"to": "In Review"}}, {}, "ACME-930")
    assert path(fake) == [] and fake.status == "In Progress"
