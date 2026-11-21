# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The tools that read the code (the `dev` extra) are pinned and locked with hashes in a file of their own: they are
run, never shipped, and a package they share with the test set has the version the test set has."""

import importlib.machinery
import importlib.util
import os
import tomllib

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HASH = "    --hash=sha256:" + "a" * 64 + "\n"
PROJECT_WITH_TOOLS = (
    '[project]\nname = "x"\ndependencies = ["alpha"]\n[project.optional-dependencies]\ntest = ["tool"]\n'
    'dev = ["linter==2.0", "typer"]\n'
)


def _script(name: str):
    loader = importlib.machinery.SourceFileLoader(f"cockpit_{name}_script", os.path.join(ROOT, "scripts", name))
    module = importlib.util.module_from_spec(importlib.util.spec_from_loader(loader.name, loader))
    loader.exec_module(module)
    return module


lock = _script("lock")


def _locks(tmp_path, dev=None):
    (tmp_path / "pyproject.toml").write_text(PROJECT_WITH_TOOLS, encoding="utf-8")
    (tmp_path / "requirements.lock").write_text("alpha==1.0 \\\n" + HASH, encoding="utf-8")
    (tmp_path / "requirements-test.lock").write_text(
        "alpha==1.0 \\\n" + HASH + "tool==3.0 \\\n" + HASH + "under==0.1 \\\n" + HASH, encoding="utf-8"
    )
    if dev is not None:
        (tmp_path / "requirements-dev.lock").write_text(dev, encoding="utf-8")
    return str(tmp_path)


def test_the_project_pins_its_tools_and_their_lock_covers_them_at_the_test_sets_versions():
    project = tomllib.load(open(os.path.join(ROOT, "pyproject.toml"), "rb"))["project"]
    tools = project["optional-dependencies"]["dev"]
    assert {lock.required(line) for line in tools} >= {"ruff", "mypy"}
    # a newer release of a tool could change the verdict, so the two that give one are named with their version
    assert all("==" in line for line in tools if lock.required(line) in ("ruff", "mypy"))
    assert lock.tools(ROOT) == tools and lock.problems(ROOT) == []
    locked = lock.parse(open(os.path.join(ROOT, "requirements-dev.lock"), encoding="utf-8").read())
    test = lock.parse(open(os.path.join(ROOT, "requirements-test.lock"), encoding="utf-8").read())
    assert all(pin["hashes"] for pin in locked.values())
    assert {name: pin["version"] for name, pin in locked.items() if name in test} == {
        name: test[name]["version"] for name in locked if name in test
    }
    # no tool is a dependency of the plugin or of its tests
    runtime = {lock.required(line) for line in project["dependencies"]}
    assert not (
        {"ruff", "mypy"} & (runtime | {lock.required(line) for line in project["optional-dependencies"]["test"]})
    )


def test_a_project_without_tools_has_no_third_lock_to_miss(tmp_path):
    root = _locks(tmp_path)
    (tmp_path / "pyproject.toml").write_text(PROJECT_WITH_TOOLS.split("dev = ", maxsplit=1)[0], encoding="utf-8")
    assert lock.tools(root) == [] and lock.problems(root) == []
    assert lock.write_dev(root, {"alpha": "1.0"}) == [] and not (tmp_path / "requirements-dev.lock").exists()


def test_a_tools_lock_that_is_missing_malformed_or_behind_is_named(tmp_path):
    root = _locks(tmp_path)
    assert lock.problems(root) == ["requirements-dev.lock is missing: scripts/lock --dev writes it"]
    _locks(tmp_path, dev="linter>=2\n")
    assert lock.problems(root) == [
        "requirements-dev.lock: line 1 is neither a pinned requirement nor a hash: linter>=2"
    ]
    _locks(tmp_path, dev="linter==2.0\nunder==0.2 \\\n" + HASH)
    assert lock.problems(root) == [
        "requirements-dev.lock: linter has no hash",
        "requirements-dev.lock: typer is declared in pyproject.toml and not locked",
        "requirements-dev.lock: under is 0.2, and requirements-test.lock has 0.1",
    ]


def test_writing_the_tools_lock_asks_for_the_shared_packages_at_the_test_sets_versions(tmp_path, monkeypatch, capsys):
    root = _locks(tmp_path)
    asked = []

    def resolved(requirements):
        asked.append(list(requirements))
        return {
            "linter": ("2.0", ""),
            "typer": ("1.4", ""),
            "under": ("0.1" if "under==0.1" in requirements else "0.2", ""),
        }

    monkeypatch.setattr(lock, "resolved", resolved)
    monkeypatch.setattr(lock, "hashes", lambda name, version: ["d" * 64])
    assert lock.main(["--dev"], root) == 0 and capsys.readouterr().out == "requirements-dev.lock: 3 packages\n"
    assert asked == [["linter==2.0", "typer"], ["linter==2.0", "typer", "under==0.1"]]
    written = (tmp_path / "requirements-dev.lock").read_text(encoding="utf-8")
    assert written.startswith("# What the lint and type checks need: tools that are run on the code, never shipped.")
    assert lock.parse(written)["under"]["version"] == "0.1" and lock.problems(root) == []
    # the two other files are left as they were
    assert (tmp_path / "requirements.lock").read_text(encoding="utf-8") == "alpha==1.0 \\\n" + HASH


def test_the_tools_lock_alone_is_not_written_against_a_test_lock_that_cannot_be_read(tmp_path, capsys):
    root = _locks(tmp_path)
    os.remove(tmp_path / "requirements-test.lock")
    assert lock.main(["--dev"], root) == 1 and "scripts/lock writes every file" in capsys.readouterr().err


def test_writing_every_lock_writes_the_tools_lock_too(tmp_path, monkeypatch, capsys):
    root = _locks(tmp_path)
    monkeypatch.setattr(
        lock,
        "resolved",
        lambda requirements: (
            {"linter": ("2.0", ""), "typer": ("1.4", "")}
            if "typer" in requirements
            else {"alpha": ("1.0", ""), **({"tool": ("3.0", "")} if "tool" in requirements else {})}
        ),
    )
    monkeypatch.setattr(lock, "hashes", lambda name, version: ["d" * 64])
    assert lock.main([], root) == 0
    assert capsys.readouterr().out.splitlines() == [
        "requirements.lock: 1 packages",
        "requirements-test.lock: 2 packages",
        "requirements-dev.lock: 2 packages",
    ]
    assert lock.problems(root) == []
