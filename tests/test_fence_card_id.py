# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The fence learns the running card from the hook's own input, not only from the environment.

Hermes removes HERMES_KANBAN_TASK from the environment of every process a worker starts, and the command hook
(hooks/egress.py) is such a process: it never saw the card, so the rules that depend on it (the advisor's report
kinds, a test kickoff's failure videos) silently did not apply. Hermes names the card in the hook's payload instead
(`extra.kanban_task_id`); the in-process hook gets keyword arguments. `running_card` reads the payload first, then
Hermes's own answer when it runs inside Hermes, then the environment. Where a worker may write does not depend on
the card: its ticket worktrees and its write_roots, with or without one."""

import json
import os
import subprocess
import sys

import pytest

from cockpitlib import egress
from cockpitlib.kanban import place_card
from cockpitlib.ops import worktree_add
from cockpitlib.pack import load

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LINKED = os.path.join(ROOT, "packs", "bravo", "pack.yaml")


def _unit(env, monkeypatch, number, kind="worker"):
    """A worker lane as a command hook sees it: the lane is named, the card is NOT in the environment."""
    monkeypatch.setenv("COCKPIT_PACK", LINKED)
    pack = load(LINKED)
    name = pack["repos"]["repos"][0]["name"]
    ticket = f"{pack['tracker']['project']}-{number}"
    made = worktree_add(pack, ticket, name)[0]
    card = place_card(
        pack["board"], f"{ticket}: work", "worker-1", "ready", ticket=ticket, pack=pack, repos=[name], kind=kind
    )
    monkeypatch.setenv("COCKPIT_LANE", "worker-1")
    monkeypatch.delenv("HERMES_KANBAN_TASK", raising=False)
    monkeypatch.setenv("HERMES_KANBAN_BOARD", pack["board"])
    egress._SEEN_SOURCES.clear()
    return pack, name, ticket, made, card


def _patch(path, payload=None) -> str:
    return egress.check_tool("patch", {"path": str(path), "old_string": "a", "new_string": "b"}, payload=payload)


def _card(pack, payload) -> tuple:
    with egress.hook_input(payload):
        return egress.running_card(pack)


def test_the_command_hooks_payload_names_the_card(env, monkeypatch):
    pack, name, ticket, made, card = _unit(env, monkeypatch, 5101)
    assert egress.running_card(pack) == (
        "",
        "",
    )  # what the live lane got: no card in the environment, none looked for elsewhere
    hermes = {
        "hook_event_name": "pre_tool_call",
        "tool_name": "patch",
        "tool_input": {"path": os.path.join(made, "x")},
        "session_id": "s1",
        "extra": {"task_id": "sess-task", "tool_call_id": "c1", "kanban_task_id": card},
    }
    assert _card(pack, hermes) == (card, "hook extra.kanban_task_id")
    assert egress.running_card(pack) == ("", "")  # the payload of one call is not remembered for the next
    assert egress.running_card() == ("", "")


@pytest.mark.parametrize(
    "shape", ("extra.kanban_task_id", "kanban_task_id", "kanban_task", "extra.kanban_task", "task_id", "extra.task_id")
)
def test_every_place_a_hook_may_name_the_card(env, monkeypatch, shape):
    pack, name, ticket, made, card = _unit(env, monkeypatch, 5102)
    key = shape.split(".")[-1]
    payload = {"extra": {key: card}} if shape.startswith("extra.") else {key: card}
    assert _card(pack, payload) == (card, f"hook {shape}")


def test_a_task_id_that_is_no_card_of_the_board_names_no_card(env, monkeypatch):
    pack, name, ticket, made, card = _unit(env, monkeypatch, 5103)
    # Hermes's own task_id is the session's, not the card's: only an id the board's index knows counts
    assert _card(pack, {"task_id": "sess-task", "extra": {"task_id": "20261113_abc"}}) == ("", "")
    assert _card(pack, {"extra": {"kanban_task_id": ""}, "task_id": card}) == (card, "hook task_id")
    assert _card(pack, "not a mapping") == ("", "") and _card(pack, {"extra": "odd"}) == ("", "")


def test_the_payload_wins_over_the_environment_and_the_environment_still_works(env, monkeypatch):
    pack, name, ticket, made, card = _unit(env, monkeypatch, 5104)
    other = place_card(
        pack["board"],
        "TASK-9999: work",
        "worker-1",
        "ready",
        ticket="TASK-9999",
        pack=pack,
        repos=[name],
        kind="worker",
    )
    monkeypatch.setenv("HERMES_KANBAN_TASK", card)
    assert _card(pack, None) == (card, "env HERMES_KANBAN_TASK")  # a process that has the card in its environment
    assert _card(pack, {"extra": {"kanban_task_id": other}}) == (other, "hook extra.kanban_task_id")
    monkeypatch.delenv("COCKPIT_LANE")  # the human's own shell is no lane: no card, whatever is around
    assert _card(pack, {"extra": {"kanban_task_id": card}}) == ("", "")


def test_inside_hermes_its_own_answer_is_used_before_the_environment(env, monkeypatch):
    import types

    pack, name, ticket, made, card = _unit(env, monkeypatch, 5105)
    module = types.ModuleType("agent.delegation_context")
    module.owned_kanban_task = lambda: card
    package = types.ModuleType("agent")
    monkeypatch.setitem(sys.modules, "agent", package)
    monkeypatch.setitem(sys.modules, "agent.delegation_context", module)
    assert _card(pack, {"tool_call_id": "c1"}) == (card, "hermes owned_kanban_task")
    module.owned_kanban_task = lambda: (_ for _ in ()).throw(RuntimeError("not a worker"))
    assert _card(pack, {}) == ("", "")
    monkeypatch.delitem(
        sys.modules, "agent.delegation_context"
    )  # a command hook: Hermes is not loaded, nothing is imported
    assert _card(pack, {}) == ("", "") and "agent.delegation_context" not in sys.modules


def test_the_advisor_rule_reads_the_cards_kind_from_the_hook(env, monkeypatch):
    pack, name, ticket, made, card = _unit(env, monkeypatch, 5107, kind="rework")
    advised = {**pack, "advisor": {"in_tool": True, "report_on": ["worker"]}}
    monkeypatch.setattr("cockpitlib.advise.report_refusal", lambda _pack, _text: "the advisor's line is missing")
    done = {"summary": "done"}
    with egress.hook_input(None):  # no card known: the kind cannot be read, so the report is asked for (as it was)
        assert egress._advisor_report("kanban_complete", done, advised) == "the advisor's line is missing"
    with egress.hook_input({"extra": {"kanban_task_id": card}}):  # a rework card is not among the kinds that report
        assert egress._advisor_report("kanban_complete", done, advised) == ""


def test_a_write_is_decided_the_same_with_or_without_the_card(env, monkeypatch):
    """The fence holds a worker to its ticket worktrees whether or not the call names its card."""
    pack, name, ticket, made, card = _unit(env, monkeypatch, 5108)
    assert pack["runtime"] == "worktree"
    paths = [
        os.path.join(made, "x"),
        env["root"] / "repos" / name / "x",
        env["workspace"] / "x",
        "/tmp/cockpit-nowhere/x",
    ]
    lines = [f"echo hi > {path}" for path in paths]
    without = [_patch(path) for path in paths] + [egress.check_tool("terminal", {"command": line}) for line in lines]
    hermes = {"extra": {"kanban_task_id": card}}
    with_card = [_patch(path, hermes) for path in paths] + [
        egress.check_tool("terminal", {"command": line}, payload=hermes) for line in lines
    ]
    monkeypatch.setenv("HERMES_KANBAN_TASK", card)
    in_env = [_patch(path) for path in paths] + [egress.check_tool("terminal", {"command": line}) for line in lines]
    assert without == with_card == in_env == ["", "blocked", "blocked", "blocked"] * 2


def test_the_source_of_the_card_is_logged_once_per_process(env, monkeypatch):
    pack, name, ticket, made, card = _unit(env, monkeypatch, 5109)
    seen = []
    monkeypatch.setattr("cockpitlib.store.log", lambda line: seen.append(line))
    for _ in range(3):
        _card(pack, {"extra": {"kanban_task_id": card}})
    assert seen == ["FENCE the running card comes from hook extra.kanban_task_id"]
    monkeypatch.setattr("cockpitlib.store.log", lambda line: (_ for _ in ()).throw(OSError("disk full")))
    egress._SEEN_SOURCES.clear()
    assert (
        _card(pack, {"extra": {"kanban_task_id": card}})[0] == card
    )  # a log that cannot be written never refuses a call


def test_the_command_hook_passes_its_payload_and_the_plugin_hook_its_keywords(env, monkeypatch):
    pack, name, ticket, made, card = _unit(env, monkeypatch, 5110)
    hook = os.path.join(ROOT, "hooks", "egress.py")
    text = open(hook, encoding="utf-8").read()
    assert "check_tool(name, tool_input, payload=payload)" in text
    plugin = open(os.path.join(ROOT, "__init__.py"), encoding="utf-8").read()
    assert 'check_tool(tool_name or "", args, payload=_kwargs)' in plugin
    # the command hook as Hermes starts it: the card only in the payload
    child = {key: value for key, value in os.environ.items() if key != "HERMES_KANBAN_TASK"}
    child["PYTHONPATH"] = os.pathsep.join(sys.path)

    def run(target):
        payload = {
            "hook_event_name": "pre_tool_call",
            "tool_name": "patch",
            "tool_input": {"path": str(target), "old_string": "a", "new_string": "b"},
            "session_id": "s1",
            "extra": {"kanban_task_id": card},
        }
        return subprocess.run(
            [sys.executable, hook], input=json.dumps(payload), capture_output=True, text=True, env=child, check=False
        )

    allowed = run(os.path.join(made, "x"))
    assert allowed.returncode == 0, allowed.stdout + allowed.stderr
    refused = run(env["root"] / "repos" / name / "x")
    assert refused.returncode == 2 and "outside your ticket checkouts" in refused.stdout


def test_fence_check_says_the_decision_and_why(env, monkeypatch, capsys):
    from cockpitlib.cli import main

    pack, name, ticket, made, card = _unit(env, monkeypatch, 5111)
    monkeypatch.delenv("COCKPIT_LANE")  # run from the human's shell
    target = os.path.join(made, "app", "x.php")
    assert main(["fence-check", "--card", card, "--path", target]) == 0
    out = capsys.readouterr().out
    assert (
        f"ALLOWED  {target}" in out and f"card {card}: ticket {ticket}, repos {name}" in out and "lane worker-1" in out
    )
    assert "resolved from hook extra.kanban_task_id" in out and f"{name}: worktree {made}" in out
    assert os.environ.get("COCKPIT_LANE") is None  # the check leaves the shell as it was
    source = str(env["root"] / "repos" / name / "x")
    assert main(["fence-check", "--card", card, "--path", source, "--lane", "worker-2"]) == 1
    out = capsys.readouterr().out
    assert f"BLOCKED  {source}" in out and "outside your ticket checkouts" in out and "lane worker-2" in out
    assert (
        main(["fence-check", "--card", "t_unknown", "--path", target]) == 0
    )  # the worktree is a worker's whatever the card
    assert "card t_unknown: not a card cockpit made on this board" in capsys.readouterr().out
    assert main(["fence-check", "--card", card, "--path", source, "--lane", "reviewer"]) == 0
    assert "the worker write fence applies to worker lanes only" in capsys.readouterr().out
    for bad in (
        ["fence-check"],
        ["fence-check", "--card", card],
        ["fence-check", "--path", target],
        ["fence-check", "--card", card, "--path"],
    ):
        assert main(bad) == 2


def test_an_unreadable_index_names_no_card(env, monkeypatch):
    pack, name, ticket, made, card = _unit(env, monkeypatch, 5112)
    monkeypatch.setattr(
        "cockpitlib.kanban.card_entry", lambda *_args: (_ for _ in ()).throw(OSError("index unreadable"))
    )
    assert egress._known_card(pack["board"], card) is False
    assert _card(pack, {"task_id": card}) == ("", "")
