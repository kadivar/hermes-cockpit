# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The repository's automation as files: every action a workflow uses is pinned to a commit, every workflow states the
permissions it holds, none runs a pull request's code with the repository's own token, a release starts from a pushed
tag only, and the updater configuration covers the three ecosystems the repository has."""

import importlib.machinery
import importlib.util
import os
import re

import pytest
import yaml

pytestmark = pytest.mark.structure

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WORKFLOWS = os.path.join(ROOT, ".github", "workflows")
NAMES = sorted(name for name in os.listdir(WORKFLOWS) if name.endswith((".yml", ".yaml")))
PINNED = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+(/[A-Za-z0-9_./-]+)?@[0-9a-f]{40} # v\d+(\.\d+){0,2}$")
WRITES = {
    "release.yml": {"publish": {"contents", "id-token", "attestations"}},
    "codeql.yml": {"analyze": {"security-events"}},
    "scorecard.yml": {"analysis": {"security-events", "id-token"}},
    "respond.yml": {"respond": {"pull-requests"}},
    "ci.yml": {},
}


def _text(name: str) -> str:
    return open(os.path.join(WORKFLOWS, name), encoding="utf-8").read()


def _data(name: str) -> dict:
    data = yaml.safe_load(_text(name))
    data["on"] = data.pop(True) if True in data else data.get("on")  # YAML reads a bare `on` as the boolean
    return data


def _bump():
    loader = importlib.machinery.SourceFileLoader("cockpit_bump_script", os.path.join(ROOT, "scripts", "bump"))
    module = importlib.util.module_from_spec(importlib.util.spec_from_loader(loader.name, loader))
    loader.exec_module(module)
    return module


def test_the_workflows_are_the_ones_this_file_knows():
    assert NAMES == sorted(WRITES), "a new workflow states here which of its jobs may write, and what"


@pytest.mark.parametrize("name", NAMES)
def test_every_action_is_pinned_to_a_commit_with_its_version_beside_it(name):
    used = [line.split("uses:", 1)[1].strip() for line in _text(name).splitlines() if re.match(r"^\s*(- )?uses:", line)]
    assert used, name
    assert [use for use in used if not PINNED.match(use)] == []


def test_an_action_has_one_pin_across_every_workflow():
    # two pins of one action are two things to review
    pins = {}
    for name in NAMES:
        for line in _text(name).splitlines():
            if re.match(r"^\s*(- )?uses:", line):
                action, commit = line.split("uses:", 1)[1].split("#")[0].strip().split("@")
                pins.setdefault("/".join(action.split("/")[:2]), set()).add(commit)
    assert {action: sorted(commits) for action, commits in pins.items() if len(commits) > 1} == {}


@pytest.mark.parametrize("name", NAMES)
def test_every_workflow_states_its_permissions_and_only_the_known_jobs_write(name):
    data = _data(name)
    assert "permissions" in data, f"{name} states no permissions: it would hold the repository's default"
    top = data["permissions"]
    assert top == {} or (isinstance(top, dict) and set(top.values()) <= {"read", "none"}), (
        f"{name}: a workflow-wide permission writes"
    )
    for job, body in data["jobs"].items():
        held = body.get("permissions", top) or {}
        writes = {key for key, value in held.items() if value == "write"}
        assert writes == WRITES[name].get(job, set()), f"{name}: job {job} writes {sorted(writes)}"


@pytest.mark.parametrize("name", NAMES)
def test_no_workflow_runs_on_pull_request_target(name):
    assert "pull_request_target" not in _text(name)
    triggers = _data(name)["on"]
    assert "pull_request_target" not in (triggers if isinstance(triggers, (dict, list)) else [triggers])


def test_a_release_starts_from_a_pushed_version_tag_and_nothing_else():
    data = _data("release.yml")
    assert data["on"] == {"push": {"tags": ["v*"]}}
    jobs = data["jobs"]
    assert (
        list(jobs) == ["verify", "build", "publish"]
        and jobs["build"]["needs"] == "verify"
        and jobs["publish"]["needs"] == "build"
    )
    text = _text("release.yml")
    assert "git verify-tag" in text and "scripts/check --json" in text and "scripts/bump --notes" in text
    assert (
        "npm sbom --sbom-format cyclonedx" in text
        and "gh-python-generate-sbom@" in text
        and "attest-build-provenance@" in text
    )
    # the job that can write runs no step of the repository's own: it never checks the code out
    assert not [step for step in jobs["publish"]["steps"] if "checkout" in str(step.get("uses", ""))]
    assert "run: gh release create" in text and "--notes-file release-notes.md" in text


def test_the_analysis_workflows_run_on_the_release_channel_on_a_schedule_and_codeql_on_pull_requests():
    codeql, scorecard = _data("codeql.yml"), _data("scorecard.yml")
    assert set(codeql["on"]) == {"push", "pull_request", "schedule"} and codeql["on"]["push"] == {"branches": ["main"]}
    assert codeql["jobs"]["analyze"]["strategy"]["matrix"]["language"] == ["python", "javascript-typescript"]
    assert set(scorecard["on"]) == {"push", "schedule", "branch_protection_rule"} and scorecard["on"]["push"] == {
        "branches": ["main"]
    }
    step = [step for step in scorecard["jobs"]["analysis"]["steps"] if "scorecard-action" in step.get("uses", "")][0]
    assert step["with"]["publish_results"] is True


def test_the_updater_covers_python_the_desktop_and_the_actions_weekly_and_grouped():
    data = yaml.safe_load(open(os.path.join(ROOT, ".github", "dependabot.yml"), encoding="utf-8"))
    assert data["version"] == 2
    found = {(entry["package-ecosystem"], entry["directory"]): entry for entry in data["updates"]}
    assert sorted(found) == [("github-actions", "/"), ("npm", "/desktop"), ("pip", "/")]
    for entry in found.values():
        assert entry["schedule"] == {"interval": "weekly"}
        assert [group["update-types"] for group in entry["groups"].values()] == [["minor", "patch"]]
    assert os.path.isfile(os.path.join(ROOT, "desktop", "package-lock.json"))


def test_every_change_has_one_code_owner_and_the_issue_links_lead_to_this_repository():
    lines = open(os.path.join(ROOT, ".github", "CODEOWNERS"), encoding="utf-8").read().splitlines()
    assert [line for line in lines if line and not line.startswith("#")] == ["* @kadivar"]
    config = open(os.path.join(ROOT, ".github", "ISSUE_TEMPLATE", "config.yml"), encoding="utf-8").read()
    assert config.count("https://github.com/kadivar/hermes-cockpit/") == 2 and "OWNER" not in config


def test_a_releases_notes_are_the_changelogs_section_for_its_version(tmp_path, capsys):
    bump = _bump()
    (tmp_path / "plugin.yaml").write_text("name: x\nversion: 1.3.0\n", encoding="utf-8")
    with pytest.raises(SystemExit, match="CHANGELOG.md has no section for 1.3.0: scripts/bump 1.3.0 cuts one"):
        bump.notes(str(tmp_path), "1.3.0")
    (tmp_path / "CHANGELOG.md").write_text(
        "# C\n\n## [Unreleased]\n\n## [1.3.0] - 2030-02-03\n\n### Added\n\n- one thing\n\n## [1.2.3] - 2020-01-01\n\n- older\n",
        encoding="utf-8",
    )
    assert bump.main(["--notes", "1.3.0"], str(tmp_path)) == 0
    assert capsys.readouterr().out == "### Added\n\n- one thing\n"
    with pytest.raises(SystemExit, match="the tree states version 1.3.0, not 1.2.3"):
        bump.notes(str(tmp_path), "1.2.3")
    (tmp_path / "plugin.yaml").write_text("name: x\nversion: 1.2.3\n", encoding="utf-8")
    assert bump.notes(str(tmp_path), "1.2.3") == "- older"  # the last section ends with the file
    (tmp_path / "CHANGELOG.md").write_text(
        "# C\n\n## [1.2.3] - 2020-01-01\n\n## [1.2.2] - 2019-01-01\n\n- x\n", encoding="utf-8"
    )
    with pytest.raises(SystemExit, match="no section for 1.2.3"):
        bump.notes(str(tmp_path), "1.2.3")
