# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The Python dependencies: what the code imports at run time is what pyproject.toml declares, what only the tests import
is in the `test` extra, both sets are locked with a hash for every file, and CI, the release and the self-update
install from the lock."""

import ast
import importlib.machinery
import importlib.util
import os
import sys
import tomllib

import pytest

from cockpitlib import self_update

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# the distribution each imported module comes from, and the modules Hermes's own interpreter provides
DISTRIBUTION = {
    "yaml": "pyyaml",
    "fastapi": "fastapi",
    "jsonschema": "jsonschema",
    "httpx": "httpx",
    "pytest": "pytest",
    "packaging": "packaging",
}
HERMES = {"agent", "hermes_cli", "hermes_bootstrap"}
LOCAL = {
    "cockpitlib",
    "dashboard",
    "tests",
    "hooks",
    "hermes_bridge",
    "_boot",
    "replay_support",
    "driver",
    "forge_transcript",
    "boards",
    "conftest",
    "kernel",
    "scripts",
}
RUNTIME = ("kernel", "dashboard/cockpit", "dashboard/plugin_api.py", "hooks", "bin", "scripts", "cron", "__init__.py")


def _script(name: str):
    loader = importlib.machinery.SourceFileLoader(f"cockpit_{name}_script", os.path.join(ROOT, "scripts", name))
    module = importlib.util.module_from_spec(importlib.util.spec_from_loader(loader.name, loader))
    loader.exec_module(module)
    return module


lock = _script("lock")
PROJECT = tomllib.load(open(os.path.join(ROOT, "pyproject.toml"), "rb"))["project"]


def _python_files(place: str) -> list:
    path = os.path.join(ROOT, place)
    if os.path.isfile(path):
        return [path]
    found = []
    for folder, names, files in os.walk(path):
        names[:] = [name for name in names if name not in ("__pycache__", "node_modules", "dist", "src")]
        for name in files:
            full = os.path.join(folder, name)
            if name.endswith(".py") or (
                os.access(full, os.X_OK) and open(full, "rb").read(64).startswith(b"#!/usr/bin/env python")
            ):
                found.append(full)
    return found


def _third_party(places) -> dict:
    """{module: [files]} for every imported top-level module that is neither the standard library's nor this repository's."""
    found = {}
    for place in places:
        for path in _python_files(place):
            for node in ast.walk(ast.parse(open(path, encoding="utf-8").read(), path)):
                names = (
                    [alias.name for alias in node.names]
                    if isinstance(node, ast.Import)
                    else ([node.module] if isinstance(node, ast.ImportFrom) and node.level == 0 and node.module else [])
                )
                for name in names:
                    top = name.split(".")[0]
                    if top not in sys.stdlib_module_names and top not in LOCAL:
                        found.setdefault(top, []).append(os.path.relpath(path, ROOT))
    return found


@pytest.mark.structure
def test_what_the_code_imports_at_run_time_is_what_the_project_declares():
    imported = _third_party(RUNTIME)
    # pip is the tool the lock script drives, in whatever environment runs it, and no dependency of the plugin
    assert imported.pop("pip") == ["scripts/lock"]
    assert set(imported) - HERMES == {"yaml", "fastapi"}, imported
    assert sorted(lock.required(line) for line in PROJECT["dependencies"]) == ["fastapi", "pyyaml"]
    # every declared requirement keeps a lower and an upper bound
    assert all(">=" in line and "<" in line for line in PROJECT["dependencies"])


@pytest.mark.structure
def test_what_only_the_tests_import_is_in_the_test_extra():
    only_tests = set(_third_party(("tests",))) - set(_third_party(RUNTIME)) - HERMES
    assert {"pytest", "jsonschema"} <= only_tests <= {"pytest", "jsonschema"}, only_tests
    extra = {lock.required(line) for line in PROJECT["optional-dependencies"]["test"]}
    assert extra == {"pytest", "pytest-cov", "pytest-xdist", "httpx", "jsonschema"}
    # httpx is imported by fastapi's test client, not by a file of this repository
    import fastapi.testclient  # noqa: F401

    assert "httpx" in sys.modules and "httpx" not in _third_party(RUNTIME) and "jsonschema" not in _third_party(RUNTIME)


@pytest.mark.structure
def test_the_helper_that_runs_in_hermes_works_without_packaging_so_it_is_not_declared():
    imported = _third_party(("hermes_bridge",))
    assert set(imported) - HERMES == {"packaging"} and set(imported["packaging"]) == {"hermes_bridge/plugins.py"}
    tree = ast.parse(open(os.path.join(ROOT, "hermes_bridge", "plugins.py"), encoding="utf-8").read())
    guarded = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Try)
        and any(
            isinstance(inner, ast.ImportFrom) and (inner.module or "").startswith("packaging") for inner in node.body
        )
        and any(getattr(handler.type, "id", "") == "ImportError" for handler in node.handlers)
    ]
    assert len(guarded) == 1
    assert "packaging" not in {lock.required(line) for line in PROJECT["dependencies"]}


@pytest.mark.structure
def test_both_lock_files_are_well_formed_and_cover_what_is_declared():
    assert lock.problems(ROOT) == [] and lock.main(["--check"], ROOT) == 0
    runtime = lock.parse(open(os.path.join(ROOT, "requirements.lock"), encoding="utf-8").read())
    test = lock.parse(open(os.path.join(ROOT, "requirements-test.lock"), encoding="utf-8").read())
    assert {"pyyaml", "fastapi", "starlette", "pydantic"} <= set(runtime) and not {
        "httpx",
        "jsonschema",
        "pytest",
    } & set(runtime)
    assert {"pytest", "pytest-cov", "pytest-xdist", "httpx", "jsonschema"} <= set(test) and set(runtime) <= set(test)
    for pins in (runtime, test):
        assert all(pin["hashes"] and all(len(digest) == 64 for digest in pin["hashes"]) for pin in pins.values())


def test_a_lock_file_is_read_back_as_it_was_written_markers_included():
    pins = {"alpha": ("1.0", ""), "beta-gamma": ("2.1.0", 'python_version == "3.11"')}
    digests = {("alpha", "1.0"): ["a" * 64], ("beta-gamma", "2.1.0"): ["b" * 64, "c" * 64]}
    text = lock.render(pins, digests, "What it needs")
    assert text.splitlines()[0] == "# What it needs. Written by scripts/lock from pyproject.toml: do not edit by hand."
    assert (
        'beta-gamma==2.1.0 ; python_version == "3.11" \\\n    --hash=sha256:'
        + "b" * 64
        + " \\\n    --hash=sha256:"
        + "c" * 64
        + "\n"
        in text
    )
    assert lock.parse(text) == {
        "alpha": {"version": "1.0", "marker": "", "hashes": ["a" * 64]},
        "beta-gamma": {"version": "2.1.0", "marker": 'python_version == "3.11"', "hashes": ["b" * 64, "c" * 64]},
    }
    with pytest.raises(ValueError, match="line 2 is neither a pinned requirement nor a hash: alpha>=1"):
        lock.parse("# x\nalpha>=1\n")
    with pytest.raises(ValueError, match="line 1 is neither"):
        lock.parse("    --hash=sha256:" + "a" * 64 + "\n")


def test_a_package_only_some_environments_need_gets_the_marker_that_says_which():
    every = {(python, system) for python in lock.PYTHONS for system, _platforms in lock.PLATFORMS}
    assert lock.marker(every, every) == ""
    assert lock.marker({("3.11", "linux"), ("3.11", "darwin")}, every) == 'python_version == "3.11"'
    assert lock.marker({(python, "linux") for python in lock.PYTHONS}, every) == 'sys_platform == "linux"'
    assert (
        lock.marker({("3.11", "linux"), ("3.12", "linux")}, every)
        == '(python_version == "3.11" or python_version == "3.12") and sys_platform == "linux"'
    )
    assert lock.canonical("Typing_Extensions") == "typing-extensions" and lock.required("PyYAML>=6,<7") == "pyyaml"
    assert lock.required("pkg[extra]>=1 ; python_version < '3.12'") == "pkg"


def test_one_resolution_per_environment_is_merged_and_two_versions_of_a_package_are_refused(monkeypatch):
    answers = {"3.11": {"alpha": "1.0", "old-only": "0.5"}, "3.12": {"alpha": "1.0"}, "3.13": {"alpha": "1.0"}}
    monkeypatch.setattr(lock, "resolve", lambda requirements, python, platforms: dict(answers[python]))
    assert lock.resolved(["alpha"]) == {"alpha": ("1.0", ""), "old-only": ("0.5", 'python_version == "3.11"')}
    answers["3.13"] = {"alpha": "2.0"}
    with pytest.raises(
        SystemExit, match="alpha resolves to several versions \\(1.0, 2.0\\): bound it in pyproject.toml"
    ):
        lock.resolved(["alpha"])


def test_writing_the_locks_gives_the_runtime_set_the_versions_the_test_set_chose(tmp_path, monkeypatch, capsys):
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "x"\ndependencies = ["alpha>=1"]\n[project.optional-dependencies]\ntest = ["tool"]\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(
        lock,
        "resolved",
        lambda requirements: (
            {"alpha": ("1.0", ""), "tool": ("3.0", ""), "under": ("0.1", "")}
            if "tool" in requirements
            else {"alpha": ("1.1", ""), "under": ("0.1", "")}
        ),
    )
    monkeypatch.setattr(lock, "hashes", lambda name, version: ["d" * 64])
    assert lock.main([], str(tmp_path)) == 0 and "requirements.lock: 2 packages" in capsys.readouterr().out
    assert lock.parse((tmp_path / "requirements.lock").read_text(encoding="utf-8"))["alpha"]["version"] == "1.0"
    assert set(lock.parse((tmp_path / "requirements-test.lock").read_text(encoding="utf-8"))) == {
        "alpha",
        "tool",
        "under",
    }
    assert lock.problems(str(tmp_path)) == []
    assert lock.main(["--help"], str(tmp_path)) == 2 and "scripts/lock --check" in capsys.readouterr().err


def test_a_lock_that_is_missing_malformed_or_behind_the_declaration_is_named(tmp_path, capsys):
    root = str(tmp_path)
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "x"\ndependencies = ["alpha>=1", "beta"]\n[project.optional-dependencies]\ntest = ["tool"]\n',
        encoding="utf-8",
    )
    assert lock.problems(root) == [
        "requirements.lock is missing: scripts/lock writes it",
        "requirements-test.lock is missing: scripts/lock writes it",
    ]
    (tmp_path / "requirements.lock").write_text(
        "alpha==1.0 \\\n    --hash=sha256:"
        + "a" * 64
        + "\nhermes-cockpit==0.1 \\\n    --hash=sha256:"
        + "a" * 64
        + "\n",
        encoding="utf-8",
    )
    (tmp_path / "requirements-test.lock").write_text("alpha>=1\n", encoding="utf-8")
    assert lock.problems(root) == [
        "requirements-test.lock: line 1 is neither a pinned requirement nor a hash: alpha>=1"
    ]
    (tmp_path / "requirements-test.lock").write_text(
        "alpha==1.1 \\\n    --hash=sha256:" + "a" * 64 + "\ntool==2\n", encoding="utf-8"
    )
    assert lock.problems(root) == [
        "requirements.lock: the plugin itself is not a dependency",
        "requirements-test.lock: tool has no hash",
        "requirements.lock: beta is declared in pyproject.toml and not locked",
        "requirements-test.lock: beta is declared in pyproject.toml and not locked",
        "requirements-test.lock: alpha is 1.1, and requirements.lock has 1.0",
        "requirements-test.lock: hermes-cockpit is absent, and requirements.lock has 0.1",
    ]
    assert (
        lock.main(["--check"], root) == 1 and "6 problem(s): scripts/lock writes them again" in capsys.readouterr().out
    )


@pytest.mark.structure
def test_ci_and_the_release_install_from_the_lock_with_hashes_and_then_the_plugin_alone():
    wanted = "pip install --require-hashes -r requirements-test.lock && pip install --no-deps -e ."
    for name in ("ci.yml", "release.yml"):
        text = open(os.path.join(ROOT, ".github", "workflows", name), encoding="utf-8").read()
        assert f"- run: {wanted}" in text and "pip install -e" not in text, name
    assert (
        "requirements.lock" in open(os.path.join(ROOT, ".github", "workflows", "release.yml"), encoding="utf-8").read()
    )


def test_the_check_says_how_far_the_environment_is_from_the_lock_without_failing(tmp_path, monkeypatch):
    check = _script("check")
    assert check.locked("Alpha_One==1.0 \\\n    --hash=sha256:x\nbeta==2 ; python_version < '4' \\\n") == {
        "alpha-one": "1.0",
        "beta": "2",
    }
    monkeypatch.setattr(check, "ROOT", str(tmp_path))
    assert check.lock_drift(sys.executable) == []  # no lock file: nothing to compare
    (tmp_path / "requirements-test.lock").write_text(
        "pytest==0.0.1 \\\n    --hash=sha256:x\nno-such-dist-x==1 \\\n    --hash=sha256:x\n", encoding="utf-8"
    )
    import pytest as installed

    assert check.lock_drift(sys.executable) == ["no-such-dist-x 1/absent", f"pytest 0.0.1/{installed.__version__}"]
    assert check.lock_drift("/nonexistent/python") == [] if os.name == "nt" else True
    quiet = tmp_path / "python"
    quiet.write_text("#!/bin/sh\necho not json\n", encoding="utf-8")
    quiet.chmod(0o755)
    assert check.lock_drift(str(quiet)) == []
    quiet.write_text("#!/bin/sh\nexit 3\n", encoding="utf-8")
    assert check.lock_drift(str(quiet)) == []


def _beside(name):
    spec = importlib.util.spec_from_file_location(
        f"cockpit_tests_{name}", os.path.join(os.path.dirname(os.path.abspath(__file__)), "support", f"{name}.py")
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def made(tmp_path, monkeypatch):
    found = _beside("update_kit").install(tmp_path)
    monkeypatch.setenv("COCKPIT_PLUGIN_ROOT", found["plugin"])
    monkeypatch.setattr(self_update, "_record_hermes_revision", lambda name, revision: "")
    log = tmp_path / "pip.log"
    tool = os.path.join(found["plugin"], ".venv", "bin", "pip")
    os.makedirs(os.path.dirname(tool))

    def pip(fails_on: str = "") -> None:
        open(tool, "w", encoding="utf-8").write(
            f'#!/bin/sh\necho "$@" >> {log}\n'
            + (f'case "$*" in *{fails_on}*) echo "ERROR: hashes do not match" >&2; exit 1;; esac\n' if fails_on else "")
        )
        os.chmod(tool, 0o755)

    pip()
    return {**found, "pip": pip, "calls": lambda: log.read_text(encoding="utf-8").splitlines() if log.exists() else []}


def test_an_update_whose_tree_has_a_lock_installs_from_it_with_hashes_and_then_the_plugin_alone(made):
    made["commit"](
        "a lock arrives",
        {"pyproject.toml": "[project]\nname = 'x'\ndependencies = ['alpha']\n", "requirements.lock": "alpha==1.0\n"},
    )
    done = self_update.apply(made["plugin"], restart=False)
    assert done["pip"] == "dependencies refreshed"
    assert made["calls"]() == ["install -q --require-hashes -r requirements.lock", "install -q --no-deps -e ."]
    # a change of the lock alone refreshes too; a change of neither file asks pip for nothing
    made["commit"]("a newer pin", {"requirements.lock": "alpha==1.1\n"})
    assert (
        self_update.apply(made["plugin"], restart=False)["pip"] == "dependencies refreshed"
        and len(made["calls"]()) == 4
    )
    made["commit"]("code only")
    assert self_update.apply(made["plugin"], restart=False)["pip"] == "" and len(made["calls"]()) == 4


def test_a_locked_install_that_fails_is_said_and_the_plugin_is_not_installed_over_it(made):
    made["pip"](fails_on="require-hashes")
    made["commit"]("a lock whose hashes are wrong", {"requirements.lock": "alpha==1.0\n"})
    done = self_update.apply(made["plugin"], restart=False)
    assert done["pip"] == "pip failed: ERROR: hashes do not match" and done["changed"] is True
    assert made["calls"]() == ["install -q --require-hashes -r requirements.lock"]


def test_an_update_whose_tree_has_no_lock_installs_as_it_always_did(made):
    made["commit"]("dependencies change", {"pyproject.toml": "[project]\nname = 'x'\ndependencies = ['alpha']\n"})
    assert self_update.apply(made["plugin"], restart=False)["pip"] == "dependencies refreshed"
    assert made["calls"]() == ["install -q -e ."]
