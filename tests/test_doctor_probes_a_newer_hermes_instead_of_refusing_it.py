# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Doctor and a Hermes newer than the versions cockpit was checked against: instead of failing on the version alone, it
asks the installed Hermes, live and read-only, whether its hooks still answer the recorded shapes. They do: the version
is accepted with a note. They do not, or the question cannot be asked: the version fails doctor exactly as before. An
older, unreadable or missing Hermes fails without any probe."""

import importlib.util
import json
import os
import subprocess

import pytest

from cockpitlib import cli, doctor, hermes_runtime, hook_probe
from cockpitlib.pack import load


def _beside(name):
    """A helper module of tests/support, loaded by its path: the name `tests` may resolve to another folder on a machine
    whose checkout sits next to one."""
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        f"cockpit_tests_{name}", os.path.join(os.path.dirname(os.path.abspath(__file__)), "support", f"{name}.py")
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_recorded = _beside("hermes_contract")
CONTRACT, as_hermes_process = _recorded.CONTRACT, _recorded.as_hermes_process

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PACKS = (os.path.join(ROOT, "packs", "acme", "pack.yaml"), os.path.join(ROOT, "packs", "bravo", "pack.yaml"))
UNCHECKED = "hermes 0.24.0 is not a version this plugin was checked against (0.22, 0.23)"


@pytest.fixture
def newer(env, monkeypatch):
    """The stand-in Hermes says it is 0.24.0, one minor past the newest verified."""
    monkeypatch.setenv("COCKPIT_STUB_VERSION", "0.24.0")
    monkeypatch.setattr(hermes_runtime, "_published", {})
    return env


def _no_probe(monkeypatch):
    def never():
        raise AssertionError("no probe is run for this version")

    monkeypatch.setattr(hook_probe, "probe", never)


# ---------- the four outcomes ----------


@pytest.mark.parametrize("version", ["0.22.2", "0.23.0", "0.23.9"])
def test_a_verified_hermes_passes_with_no_note_and_no_probe(env, monkeypatch, version):
    monkeypatch.setenv("COCKPIT_STUB_VERSION", version)
    _no_probe(monkeypatch)
    assert doctor.hermes_check() == {"problem": "", "note": ""} and doctor.notes({}) == []


@pytest.mark.parametrize(
    "version, problem",
    [
        ("0.21.9", "hermes 0.21.9 is not a version this plugin was checked against (0.22, 0.23)"),
        ("0.3.0", "hermes 0.3.0 is not a version this plugin was checked against (0.22, 0.23)"),
        ("1.0.0", "hermes 1.0.0 is not a version this plugin was checked against (0.22, 0.23)"),
        ("nope", "hermes version unreadable"),
    ],
)
def test_an_older_unreadable_or_other_major_hermes_fails_without_a_probe(env, monkeypatch, version, problem):
    monkeypatch.setenv("COCKPIT_STUB_VERSION", version)
    _no_probe(monkeypatch)
    assert doctor.hermes_check() == {"problem": problem, "note": ""} and doctor.hermes_version_problem() == problem


def test_a_missing_or_silent_hermes_fails_without_a_probe(env, monkeypatch):
    _no_probe(monkeypatch)
    monkeypatch.setattr(doctor, "VERSION_TIMEOUT", 0.2)
    monkeypatch.setenv("COCKPIT_STUB_VERSION_SLEEP", "2")
    assert doctor.hermes_check() == {"problem": "hermes --version did not answer within 0.2 s", "note": ""}
    monkeypatch.setenv("PATH", "/nonexistent")
    assert doctor.hermes_check() == {"problem": "hermes not found", "note": ""}


def test_a_newer_minor_whose_hooks_answer_the_recorded_shapes_is_accepted_with_a_note(newer):
    before = sorted(os.listdir(newer["home"]))
    found = doctor.hermes_check()
    assert found["problem"] == "" and doctor.hermes_version_problem() == ""
    assert found["note"].startswith(
        "hermes 0.24.0 is newer than the versions this plugin was checked against (0.22, 0.23): its hooks answered"
    )
    assert "were not probed" in found["note"] and doctor.notes({}) == [found["note"]]
    assert hook_probe.probe() == ""
    assert sorted(os.listdir(newer["home"])) == before, "the probe wrote nothing into the Hermes home"


@pytest.mark.parametrize(
    "changed, why",
    [
        ("no-event", "transform_terminal_output is not a hook this Hermes offers"),
        ("drop-kwarg", "pre_tool_call no longer sends tool_call_id"),
        ("no-block", "a pre_tool_call block with a message is not honoured"),
        ("shell", "a shell hook's block is not honoured"),
        ("schema", "the hook payload schema is 'hermes.observer.v2', not 'hermes.observer.v1'"),
        (
            "renamed",
            "pre_tool_call could not be read (AttributeError: module 'hermes_cli.plugins' has no attribute 'get_pre_tool_call_directive')",
        ),
    ],
)
def test_a_newer_minor_whose_hooks_changed_fails_exactly_as_before_and_a_note_says_what_changed(
    newer, monkeypatch, changed, why
):
    monkeypatch.setenv("COCKPIT_STUB_HOOKS", changed)
    found = doctor.hermes_check()
    assert found["problem"] == UNCHECKED == doctor.hermes_version_problem()
    assert (
        found["note"].startswith("hermes 0.24.0: the live hook probe did not pass, so the version stays unaccepted: ")
        and why in found["note"]
    )


def test_several_changes_are_all_named(newer, monkeypatch):
    monkeypatch.setenv("COCKPIT_STUB_HOOKS", "no-event,drop-kwarg,shell")
    assert hook_probe.probe() == (
        "transform_terminal_output is not a hook this Hermes offers; pre_tool_call no longer sends tool_call_id; "
        "a shell hook's block is not honoured"
    )


def test_a_newer_minor_whose_probe_cannot_run_fails_exactly_as_before(newer, monkeypatch):
    monkeypatch.setenv("COCKPIT_STUB_NO_RUNTIME", "1")
    found = doctor.hermes_check()
    assert found["problem"] == UNCHECKED
    assert found["note"].endswith("the probe could not run: hermes did not publish a runtime command")


@pytest.mark.parametrize(
    "text",
    [
        None,
        "not json",
        "[]",
        json.dumps({"events": {}}),
        json.dumps({"events": {"pre_tool_call": {"kwargs": []}}}),
        json.dumps({"events": {"pre_tool_call": {"kwargs": ["tool_name"]}}}),
        json.dumps({"events": [], "telemetry_schema_version": "x"}),
    ],
)
def test_a_newer_minor_fails_when_the_recorded_contract_is_not_there_to_compare_with(
    newer, monkeypatch, tmp_path, text
):
    from cockpitlib import paths

    monkeypatch.setattr(paths, "PLUGIN_ROOT", str(tmp_path))  # an install that does not ship tests/contract
    if text is not None:
        os.makedirs(tmp_path / "tests" / "contract")
        (tmp_path / "tests" / "contract" / "hermes-hooks.json").write_text(text, encoding="utf-8")
    monkeypatch.setattr(
        hook_probe, "_offered", lambda: pytest.fail("nothing is asked when there is nothing to compare with")
    )
    found = doctor.hermes_check()
    assert (
        found["problem"] == UNCHECKED
        and "is missing or unreadable, so there is nothing to compare with" in found["note"]
    )
    assert str(tmp_path / "tests" / "contract" / "hermes-hooks.json") in found["note"]


@pytest.mark.parametrize(
    "answer, why",
    [
        (subprocess.TimeoutExpired(["hermes"], 30), "no answer within 30 s"),
        (OSError("exec format error"), "exec format error"),
        (
            subprocess.CompletedProcess([], 3, "", "Traceback\nImportError: no module named hermes_cli\n"),
            "ImportError: no module named hermes_cli",
        ),
        (subprocess.CompletedProcess([], 1, "", ""), "exit 1"),
        (subprocess.CompletedProcess([], 0, "warming up…\n", ""), "the helper answered no JSON"),
        (subprocess.CompletedProcess([], 0, "[]\n", ""), "the helper answered no JSON object"),
    ],
)
def test_a_helper_that_fails_is_slow_or_answers_something_else_means_the_probe_could_not_run(
    newer, monkeypatch, answer, why
):
    monkeypatch.setattr(hermes_runtime, "runtime_argv", lambda script: ["hermes-python", script])

    def run(argv, **kwargs):
        assert (
            argv[0] == "hermes-python"
            and argv[1].endswith(os.path.join("hermes_bridge", "hook_probe.py"))
            and kwargs["timeout"] == hook_probe.PROBE_TIMEOUT
        )
        if isinstance(answer, Exception):
            raise answer
        return answer

    monkeypatch.setattr(hook_probe.subprocess, "run", run)
    assert hook_probe.probe() == f"the probe could not run: {why}"


# ---------- what is compared ----------


def test_the_shipped_contract_is_where_the_probe_looks_and_is_one_it_can_compare_with():
    assert hook_probe.contract_path() == os.path.join(ROOT, "tests", "contract", "hermes-hooks.json")
    assert hook_probe._contract() == CONTRACT


def test_an_answer_that_is_not_the_helpers_shape_meets_nothing():
    everything = hook_probe.differences(CONTRACT, {})
    assert everything == [
        "the helper's errors could not be read",
        "pre_tool_call is not a hook this Hermes offers",
        "transform_tool_result is not a hook this Hermes offers",
        "transform_terminal_output is not a hook this Hermes offers",
        "the hook payload schema is None, not 'hermes.observer.v1'",
        "a tool call is not dispatched to pre_tool_call",
        "pre_tool_call no longer sends tool_name, args, task_id, session_id, tool_call_id, turn_id, api_request_id, middleware_trace",
        "a pre_tool_call block with a message is not honoured",
        "a shell hook's block is not honoured",
    ]
    wrong_types = {
        "errors": {},
        "hooks": "pre_tool_call",
        "telemetry_schema_version": "hermes.observer.v1",
        "pre_tool_call": ["block"],
        "shell_hook": "block",
    }
    assert len(hook_probe.differences(CONTRACT, wrong_types)) == 7
    truthy = {
        "errors": {},
        "hooks": list(CONTRACT["events"]),
        "telemetry_schema_version": "hermes.observer.v1",
        "pre_tool_call": {"event": "pre_tool_call", "kwargs": "tool_name args", "block": "yes"},
        "shell_hook": {"block": 1},
    }
    assert len(hook_probe.differences(CONTRACT, truthy)) == 3, (
        "a block is honoured only when the helper says exactly true"
    )


def test_a_hermes_that_sends_more_keywords_than_recorded_still_meets_the_contract():
    offered = {
        "errors": {},
        "hooks": [*CONTRACT["events"], "on_stream_start"],
        "telemetry_schema_version": CONTRACT["telemetry_schema_version"],
        "pre_tool_call": {
            "event": "pre_tool_call",
            "block": True,
            "kwargs": [
                key for key in CONTRACT["events"]["pre_tool_call"]["kwargs"] if key != "telemetry_schema_version"
            ]
            + ["conversation_id"],
        },
        "shell_hook": {"block": True},
    }
    assert hook_probe.differences(CONTRACT, offered) == []


def test_the_helper_puts_hermess_own_dispatch_back_and_reports_a_part_it_could_not_ask(monkeypatch, capsys):
    as_hermes_process(monkeypatch)
    spec = importlib.util.spec_from_file_location(
        "hookprobe_helper", os.path.join(ROOT, "hermes_bridge", "hook_probe.py")
    )
    helper = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(helper)
    from hermes_cli import lifecycle

    real = lifecycle.invoke_hook
    found = helper._pre_tool_call()
    assert (
        lifecycle.invoke_hook is real
        and found["block"] is True
        and found["event"] == "pre_tool_call"
        and "tool_call_id" in found["kwargs"]
    )
    monkeypatch.setitem(helper.PARTS, "shell_hook", lambda: 1 / 0)
    assert helper.main() == 0
    answered = json.loads(capsys.readouterr().out)
    assert answered["errors"] == {"shell_hook": "ZeroDivisionError: division by zero"} and "shell_hook" not in answered
    assert answered["hooks"] and answered["telemetry_schema_version"] == CONTRACT["telemetry_schema_version"]


# ---------- doctor ----------


def _told(found) -> dict:
    """What doctor.report answers for those findings: only an error fails it."""
    return {"ok": not any(item["severity"] == "error" for item in found), "findings": found}


@pytest.mark.parametrize("pack_file", PACKS)
def test_doctor_lists_the_version_only_when_the_probe_does_not_pass(newer, monkeypatch, pack_file):
    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    pack = load(pack_file)
    assert UNCHECKED not in doctor.run(pack)
    monkeypatch.setenv("COCKPIT_STUB_HOOKS", "no-block")
    assert UNCHECKED in doctor.run(pack)


def test_the_command_prints_a_note_after_its_verdict_and_the_note_never_changes_the_verdict(newer, monkeypatch, capsys):
    monkeypatch.setattr(
        cli,
        "doctor_report",
        lambda pack, **_how: _told([{"severity": "info", "message": doctor.notes(pack)[0], "fix": ""}]),
    )
    assert cli.main(["doctor"]) == 0
    lines = capsys.readouterr().out.splitlines()
    assert (
        lines[0] == "doctor: OK"
        and len(lines) == 2
        and lines[1].startswith("note: hermes 0.24.0 is newer than the versions")
    )
    monkeypatch.setenv("COCKPIT_STUB_HOOKS", "drop-kwarg")
    monkeypatch.setattr(
        cli,
        "doctor_report",
        lambda pack, **_how: _told(
            [
                {"severity": "error", "message": UNCHECKED, "fix": ""},
                {"severity": "info", "message": doctor.notes(pack)[0], "fix": ""},
            ]
        ),
    )
    assert cli.main(["doctor"]) == 1
    lines = capsys.readouterr().out.splitlines()
    assert (
        lines[0] == UNCHECKED
        and lines[1].startswith("note: hermes 0.24.0: the live hook probe did not pass")
        and "tool_call_id" in lines[1]
    )


def test_a_verified_hermes_prints_no_note(env, monkeypatch, capsys):
    monkeypatch.setattr(cli, "doctor_report", lambda pack, **_how: _told([]))
    assert cli.main(["doctor"]) == 0 and capsys.readouterr().out == "doctor: OK\n"
    monkeypatch.setattr(
        cli,
        "doctor_report",
        lambda pack, **_how: _told([{"severity": "error", "message": "board metadata missing", "fix": ""}]),
    )
    assert cli.main(["doctor"]) == 1 and capsys.readouterr().out == "board metadata missing\n"
