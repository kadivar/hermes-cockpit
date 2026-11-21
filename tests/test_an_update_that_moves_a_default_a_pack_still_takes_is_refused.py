# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""An update whose kernel gives a pack key another default is refused, with the key named, while the live pack still
takes that key from the default, and lands once the pack wrote the value out (`cockpit pack pin --all`). Both kernels
are real ones: this repository's own, and a copy of it with one default moved and nothing declared. A different list of
pending defaults alone changes nothing."""

import importlib.util
import json
import os
import shutil
import sys

import pytest
import yaml

from cockpitlib import pack_keys, self_update
from cockpitlib.cli import main
from cockpitlib.errors import CockpitError
from cockpitlib.pack import load

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PACKS = (os.path.join(ROOT, "packs", "acme", "pack.yaml"), os.path.join(ROOT, "packs", "bravo", "pack.yaml"))
KEY = "testflow.results_file"


def _beside(name):
    spec = importlib.util.spec_from_file_location(
        f"cockpit_tests_{name}", os.path.join(os.path.dirname(os.path.abspath(__file__)), "support", f"{name}.py")
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


git, install = _beside("update_kit").git, _beside("update_kit").install


@pytest.fixture
def made(tmp_path, monkeypatch):
    """An installation whose checkout runs this repository's own kernel, and a way to give its origin a next commit."""
    found = install(tmp_path)
    monkeypatch.setenv("COCKPIT_PLUGIN_ROOT", found["plugin"])
    monkeypatch.setattr(self_update, "_record_hermes_revision", lambda name, revision: "")
    monkeypatch.setattr(self_update, "_python", lambda root: sys.executable)
    for name in [name for name in os.environ if name.startswith(("COVERAGE_", "COV_CORE_"))]:
        monkeypatch.delenv(name)  # the copies are not the code under test: a coverage run must not measure them
    seed = found["seed"]
    shutil.copy(os.path.join(ROOT, "bin", "cockpit"), os.path.join(seed, "bin", "cockpit"))
    for name in ("kernel", "skills"):  # the code, and the bundled skills a pack check looks for
        shutil.copytree(
            os.path.join(ROOT, name),
            os.path.join(seed, name),
            dirs_exist_ok=True,
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
        )
    ours = found["commit"]("this repository's kernel")
    assert (
        self_update.apply(found["plugin"], restart=False)["changed"] is True
    )  # the stand-in before it prints no values: not compared
    assert git(found["plugin"], "rev-parse", "HEAD") == ours
    return found


def _moved(made, extra=None) -> str:
    """A next commit whose kernel names another results file where a pack names none, and declares no change."""
    path = os.path.join(made["seed"], "kernel", "cockpitlib", "test_flow.py")
    text = open(path, encoding="utf-8").read()
    assert text.count('RESULTS_FILE = "test-results.md"') == 1
    return made["commit"](
        "moves a default",
        {
            "kernel/cockpitlib/test_flow.py": text.replace(
                'RESULTS_FILE = "test-results.md"', 'RESULTS_FILE = "results.md"'
            ),
            **(extra or {}),
        },
    )


def _pinned(pack_file, tmp_path, monkeypatch, capsys) -> str:
    """A copy of the pack with the lines `cockpit pack pin --all` prints for it added."""
    folder = tmp_path / "packs" / os.path.basename(os.path.dirname(pack_file))
    shutil.copytree(os.path.dirname(pack_file), folder)
    monkeypatch.setenv("COCKPIT_PACK", str(folder / "pack.yaml"))
    capsys.readouterr()
    assert main(["pack", "pin", "--all"]) == 0
    text = capsys.readouterr().out
    files = [
        line[2:].split(":")[0]
        for line in text.splitlines()
        if line.startswith("# ") and line.endswith("the keys printed under it")
    ]
    documents = list(yaml.safe_load_all(text))
    assert "pack.yaml" in files and len(files) == len(documents)

    def merge(into, more):
        for key, value in more.items():
            if isinstance(value, dict) and isinstance(into.get(key), dict):
                merge(into[key], value)
            else:
                into[key] = value

    for name, document in zip(files, documents):  # each document goes into the file its first line names
        if not document:
            continue  # nothing printed as a line for that file
        data = yaml.safe_load((folder / name).read_text(encoding="utf-8"))
        merge(data, document)
        (folder / name).write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8")
    return str(folder / "pack.yaml")


@pytest.mark.parametrize("pack_file", PACKS)
def test_a_moved_default_is_refused_for_a_pack_that_takes_it_and_lands_for_one_that_pinned_it(
    env, made, pack_file, tmp_path, monkeypatch, capsys
):
    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    assert KEY.split(".")[1] not in (load(pack_file).get("testflow") or {}), (
        "the fixture takes the results file from the default"
    )
    assert pack_keys.default_of(pack_keys.find(KEY)) == "test-results.md"
    assert not os.path.exists(os.path.join(made["seed"], self_update.CHANGES_FILE)), "the next commit declares nothing"
    here = git(made["plugin"], "rev-parse", "HEAD")
    newest = _moved(made)
    with pytest.raises(CockpitError) as refused:
        self_update.apply(made["plugin"], restart=False)
    assert f"changes what the live pack means without declaring it ({KEY})" in str(refused.value)
    assert git(made["plugin"], "rev-parse", "HEAD") == here and not git(made["plugin"], "status", "--porcelain")
    # the same pack with its defaults written out: the new kernel means the same to it
    monkeypatch.setenv("COCKPIT_PACK", _pinned(pack_file, tmp_path, monkeypatch, capsys))
    done = self_update.apply(made["plugin"], restart=False)
    assert done["changed"] is True and git(made["plugin"], "rev-parse", "HEAD") == newest
    assert done["preflight"] == {
        "ran": True,
        "checks": ["pack check", "pack effective"],
        "effective_changes": [],
        "notes": [],
    }


def test_another_list_of_pending_defaults_alone_changes_no_value_and_lands(env, made, monkeypatch):
    monkeypatch.setenv("COCKPIT_PACK", PACKS[0])
    path = os.path.join(made["seed"], "kernel", "cockpitlib", "pending_defaults.json")
    listed = json.load(open(path, encoding="utf-8"))
    assert listed == {"pending": []}
    listed["pending"] = [{"key": KEY, "planned": "results.md", "reason": "a shorter name"}]
    newest = made["commit"]("lists other defaults", {"kernel/cockpitlib/pending_defaults.json": json.dumps(listed)})
    done = self_update.apply(made["plugin"], restart=False)
    assert done["changed"] is True and git(made["plugin"], "rev-parse", "HEAD") == newest
    assert (
        done["preflight"]["checks"] == ["pack check", "pack effective"] and done["preflight"]["effective_changes"] == []
    )
