# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The plugin's version is written once, in the manifest Hermes reads; every other file that must state it literally
states the same, and `scripts/bump` writes them all and cuts the changelog."""

import importlib.machinery
import importlib.util
import json
import os

import pytest
import yaml

pytestmark = pytest.mark.structure

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _bump():
    loader = importlib.machinery.SourceFileLoader("cockpit_bump_script", os.path.join(ROOT, "scripts", "bump"))
    module = importlib.util.module_from_spec(importlib.util.spec_from_loader(loader.name, loader))
    loader.exec_module(module)
    return module


bump = _bump()
MANIFEST = yaml.safe_load(open(os.path.join(ROOT, "plugin.yaml"), encoding="utf-8"))


def _tree(tmp_path, version="1.2.3", elsewhere="1.2.3"):
    (tmp_path / "kernel" / "cockpitlib").mkdir(parents=True)
    (tmp_path / "plugin.yaml").write_text(f"name: x\nversion: {version}\nauthor: someone\n", encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text(
        f'[project]\nname = "x"\nversion = "{elsewhere}"\n[tool.x]\nversion = "9.9.9"\n', encoding="utf-8"
    )
    (tmp_path / "kernel" / "cockpitlib" / "__init__.py").write_text(
        f'"""x"""\n__version__ = "{elsewhere}"\n', encoding="utf-8"
    )
    return tmp_path


def test_every_file_that_states_the_version_states_the_manifests():
    assert bump.differing(ROOT) == [] and bump.main(["--check"]) == 0
    assert bump.source(ROOT) == str(MANIFEST["version"])
    from cockpitlib import __version__
    from cockpitlib.describe import describe

    assert __version__ == describe()["version"] == str(MANIFEST["version"])
    # every literal the script knows is a file of this repository: one that moved would be checked no more
    assert [name for name, _pattern in bump.LITERALS if not os.path.isfile(os.path.join(ROOT, name))] == []
    # and no other package manifest states a version of its own
    for name in ("desktop/package.json", "dashboard/package.json"):
        assert "version" not in json.load(open(os.path.join(ROOT, name), encoding="utf-8")), name


def test_a_literal_that_differs_is_named_and_the_check_fails(tmp_path, capsys):
    root = str(_tree(tmp_path, elsewhere="1.2.2"))
    assert bump.differing(root) == [
        "pyproject.toml: states 1.2.2, plugin.yaml states 1.2.3",
        "kernel/cockpitlib/__init__.py: states 1.2.2, plugin.yaml states 1.2.3",
    ]
    assert bump.main(["--check"], root) == 1
    said = capsys.readouterr()
    assert "pyproject.toml: states 1.2.2" in said.err and "the literals differ: scripts/bump <version>" in said.out
    (tmp_path / "pyproject.toml").write_text("[project]\nname = 'x'\n", encoding="utf-8")
    assert bump.differing(root)[0] == "pyproject.toml: states no version, plugin.yaml states 1.2.3"
    (tmp_path / "plugin.yaml").write_text("name: x\n", encoding="utf-8")
    with pytest.raises(SystemExit, match="plugin.yaml states no version"):
        bump.differing(root)


def test_a_bump_writes_every_literal_and_moves_the_unreleased_entries_under_the_version(tmp_path, capsys):
    root = str(_tree(tmp_path))
    (tmp_path / "CHANGELOG.md").write_text(
        "# Changelog\n\nIntro.\n\n## [Unreleased]\n\n### Added\n\n- one thing\n\n## [1.2.3] - 2020-01-01\n\n- older\n",
        encoding="utf-8",
    )
    assert bump.write(root, "1.3.0", "2030-02-03") == [
        "plugin.yaml",
        "pyproject.toml",
        "kernel/cockpitlib/__init__.py",
        "CHANGELOG.md",
    ]
    assert bump.differing(root) == [] and bump.source(root) == "1.3.0"
    assert 'version = "9.9.9"' in (tmp_path / "pyproject.toml").read_text(
        encoding="utf-8"
    )  # another table's key is not the version
    assert (tmp_path / "plugin.yaml").read_text(encoding="utf-8") == "name: x\nversion: 1.3.0\nauthor: someone\n"
    assert (tmp_path / "CHANGELOG.md").read_text(encoding="utf-8") == (
        "# Changelog\n\nIntro.\n\n## [Unreleased]\n\n## [1.3.0] - 2030-02-03\n\n### Added\n\n- one thing\n\n## [1.2.3] - 2020-01-01\n\n- older\n"
    )
    # nothing under Unreleased: the changelog stays; the same version again changes nothing
    assert bump.write(root, "1.3.0", "2030-02-04") == []
    assert (
        bump.main(["1.3.1"], root) == 0
        and "version 1.3.1: plugin.yaml, pyproject.toml, kernel/cockpitlib/__init__.py" in capsys.readouterr().out
    )
    assert bump.main(["1.3.1"], root) == 0 and "nothing to change" in capsys.readouterr().out


def test_a_changelog_whose_unreleased_section_is_the_last_one_is_cut_too():
    assert (
        bump.released("# C\n\n## [Unreleased]\n\n- a\n", "2.0.0", "2030-01-01")
        == "# C\n\n## [Unreleased]\n\n## [2.0.0] - 2030-01-01\n\n- a\n"
    )
    assert bump.released("# C\n\n- no heading\n", "2.0.0", "2030-01-01") == "# C\n\n- no heading\n"


def test_a_word_that_is_no_version_and_a_wrong_command_line_are_refused(tmp_path, capsys):
    root = str(_tree(tmp_path))
    with pytest.raises(SystemExit, match="latest is no version: scripts/bump 1.2.3"):
        bump.main(["latest"], root)
    assert bump.main([], root) == 2 and bump.main(["1.0.0", "extra"], root) == 2 and bump.main(["--help"], root) == 2
    assert "scripts/bump --check" in capsys.readouterr().err
    assert bump.source(root) == "1.2.3"
