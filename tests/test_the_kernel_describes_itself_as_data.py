# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""`cockpit describe --json`: the kernel's verbs, intent types, kickoff modes, card kinds and marks as data, read from the
tables the kernel runs on, on a machine with no workspace and no pack. Its top-level shape is pinned."""

import json
import os
import subprocess
import sys

import pytest

from cockpitlib import cli, describe, intents, lend, pack, plugin_api, registry, test_flow

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PINNED = json.load(open(os.path.join(ROOT, "tests", "contract", "describe.json"), encoding="utf-8"))


def _described(capsys) -> dict:
    assert cli.main(["describe", "--json"]) == 0
    return json.loads(capsys.readouterr().out)


def test_the_description_matches_its_pinned_shape(capsys):
    found = _described(capsys)
    assert {key: type(value).__name__ for key, value in found.items()} == PINNED["keys"], (
        "a changed shape is a contract change"
    )
    assert all(sorted(entry) == PINNED["verb"] for entry in found["verbs"].values())
    assert all(sorted(entry) == PINNED["kickoff_mode"] for entry in found["kickoff_modes"].values())
    assert all(sorted(entry) == PINNED["card_kind"] for entry in found["card_kinds"].values())
    assert sorted(found["marks"]) == PINNED["marks"]


def test_every_value_is_the_one_the_kernel_runs_on(capsys):
    found = _described(capsys)
    assert found["api_version"] == plugin_api.API_VERSION and found["api_min_supported"] == plugin_api.API_MIN_SUPPORTED
    assert sorted(found["verbs"]) == sorted(cli.COMMANDS)
    for name, entry in found["verbs"].items():
        assert entry["flags"] == sorted(cli.FLAGS.get(name, ())) and entry["zero_args"] is (name in cli.ZERO_ARGS)
        assert entry["self_parsed"] is (name in cli.SELF_PARSED) and entry["example"] == cli.EXAMPLES.get(name, "")
    assert found["intent_types"] == intents.TYPES
    assert found["kickoff_modes"] == registry.KICKOFF_MODES
    assert "verb_aliases" not in found and "kickoff_mode_aliases" not in found
    assert found["card_kinds"] == registry.CARD_KINDS
    assert found["roles"] == list(pack.ROLES) and found["seat_kinds"] == list(registry.ROLES)
    assert found["marks"] == {
        "privileged_login": lend.MARK,
        "two_factor": lend.TWO_FACTOR_MARK,
        "review": test_flow.REVIEW_MARK,
        "no_failure_video": test_flow.NO_VIDEO_MARK,
    }


def test_the_version_is_the_manifests(capsys):
    import yaml

    manifest = yaml.safe_load(open(os.path.join(ROOT, "plugin.yaml"), encoding="utf-8"))
    assert _described(capsys)["version"] == str(manifest["version"]) != ""


def test_a_manifest_that_cannot_be_read_gives_an_empty_version(tmp_path, monkeypatch):
    from cockpitlib import paths

    monkeypatch.setattr(paths, "PLUGIN_ROOT", str(tmp_path))
    assert describe.describe()["version"] == ""  # no manifest
    (tmp_path / "plugin.yaml").write_text("- a list\n", encoding="utf-8")
    assert describe.describe()["version"] == ""  # not a mapping
    (tmp_path / "plugin.yaml").write_text("version: [unclosed\n", encoding="utf-8")
    assert describe.describe()["version"] == ""  # not YAML


def test_the_marks_are_the_words_the_souls_tell_a_lane_to_write():
    common = open(os.path.join(ROOT, "souls", "_common.md"), encoding="utf-8").read()
    tester = open(os.path.join(ROOT, "souls", "tester.md"), encoding="utf-8").read()
    marks = describe.marks()
    assert f"`{marks['privileged_login']} · " in common
    assert f"starts `{marks['two_factor']}`" in common
    assert f"`{marks['no_failure_video']} for row" in tester


def test_a_machine_with_no_workspace_and_no_pack_is_described(tmp_path):
    env = {key: value for key, value in os.environ.items() if not key.startswith("COCKPIT_")}
    env["COCKPIT_HERMES_HOME"] = str(tmp_path / "no-home")  # no binding file, no workspace, no pack
    done = subprocess.run(
        [sys.executable, os.path.join(ROOT, "bin", "cockpit"), "describe", "--json"],
        capture_output=True,
        text=True,
        env=env,
        cwd=str(tmp_path),
        check=False,
    )
    assert done.returncode == 0, done.stderr
    assert json.loads(done.stdout)["intent_types"] == intents.TYPES


def test_describe_refuses_a_stray_argument_and_an_unknown_flag(capsys):
    assert cli.main(["describe", "verbs"]) == 2 and "stray argument" in capsys.readouterr().err
    assert cli.main(["describe", "--yaml"]) == 2 and "unknown option --yaml" in capsys.readouterr().err
    assert cli.main(["describe"]) == 0 and json.loads(capsys.readouterr().out)["api_version"] == plugin_api.API_VERSION


@pytest.mark.parametrize("name", ("watch-rc", "state-commit", "watch_base"))
def test_a_verb_has_one_name_and_any_other_is_an_unknown_command(capsys, name):
    assert name not in cli.COMMANDS and cli.main([name]) == 2
    assert f"unknown command {name}" in capsys.readouterr().err


def test_the_help_line_names_the_verb(capsys):
    assert cli.main(["help"]) == 0
    helped = capsys.readouterr().out
    assert "|describe|" in helped.splitlines()[0] and "cockpit describe --json" in helped
