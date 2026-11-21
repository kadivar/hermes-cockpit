# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""A pack's verify command gets the changed files as arguments. A committed file whose name starts with a dash is
passed as ./name, so the tool reads it as a file and never as one of its options."""

import json
import os
import subprocess
import sys

import pytest

from cockpitlib.outbox import _run_verify
from cockpitlib.pack import load

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PACKS = (os.path.join(ROOT, "packs", "acme", "pack.yaml"), os.path.join(ROOT, "packs", "bravo", "pack.yaml"))
NAMES = ("--fix", "-rf", "--config=evil.cfg", "-", "plain.py", "src/-inner.py", "src/ok.py")


def _repo(tmp_path) -> tuple:
    """A real repository whose one commit holds files named like options; (folder, sha)."""
    folder = tmp_path / "checkout"
    (folder / "src").mkdir(parents=True)
    for name in NAMES:
        (folder / name).write_text("x = 1\n", encoding="utf-8")
    run = lambda *words: subprocess.run(["git", "-C", str(folder), *words], check=True, capture_output=True, text=True)  # noqa: E731
    subprocess.run(["git", "init", "-q", str(folder)], check=True, capture_output=True)
    run("add", "--", *NAMES)
    run(
        "-c",
        "user.name=fixture",
        "-c",
        "user.email=fixture@example.test",
        "commit",
        "-q",
        "-m",
        "files named like options",
    )
    return str(folder), run("rev-parse", "HEAD").stdout.strip()


@pytest.mark.parametrize("pack_file", PACKS)
def test_a_file_named_like_an_option_reaches_the_tool_as_a_path(env, pack_file, monkeypatch, tmp_path):
    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    pack = load(pack_file)
    folder, sha = _repo(tmp_path)
    seen = tmp_path / "argv.json"
    record = "import json, sys; json.dump(sys.argv[1:], open(sys.argv[1], 'w'))"
    repo = {"verify": [[sys.executable, "-c", record, str(seen), "--strict", "{files}", "{sha}"]]}
    payload = {"repo": pack["repos"]["repos"][0]["name"], "sha": sha, "files": [*NAMES, "gone.py"]}
    assert _run_verify(pack, repo, payload, folder) == []
    assert json.load(open(seen, encoding="utf-8")) == [
        str(seen),
        "--strict",
        "./--fix",
        "./-rf",
        "./--config=evil.cfg",
        "./-",
        "plain.py",
        "src/-inner.py",
        "src/ok.py",
        sha,
    ]


@pytest.mark.parametrize("pack_file", PACKS)
def test_a_real_tool_reads_the_dashed_names_as_files(env, pack_file, monkeypatch, tmp_path):
    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    pack = load(pack_file)
    folder, sha = _repo(tmp_path)
    payload = {"repo": pack["repos"]["repos"][0]["name"], "sha": sha, "files": list(NAMES)}
    # wc would take --fix and -rf for options and fail; read as paths, it counts all seven files
    assert _run_verify(pack, {"verify": [["wc", "-l", "{files}"]]}, payload, folder) == []
    counted = subprocess.run(
        ["wc", "-l", *[name if not name.startswith("-") else "./" + name for name in NAMES]],
        cwd=folder,
        capture_output=True,
        text=True,
        check=False,
    )
    assert counted.returncode == 0 and "7 total" in counted.stdout
    assert subprocess.run(["wc", "-l", *NAMES], cwd=folder, capture_output=True, text=True, check=False).returncode != 0


@pytest.mark.parametrize("pack_file", PACKS)
def test_a_command_with_no_changed_file_to_name_is_still_skipped_and_a_failure_is_still_said(
    env, pack_file, monkeypatch, tmp_path
):
    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    pack = load(pack_file)
    folder, sha = _repo(tmp_path)
    name = pack["repos"]["repos"][0]["name"]
    assert (
        _run_verify(pack, {"verify": [["false", "{files}"]]}, {"repo": name, "sha": sha, "files": ["gone.py"]}, folder)
        == []
    )
    said = _run_verify(pack, {"verify": [["false", "{files}"]]}, {"repo": name, "sha": sha, "files": ["--fix"]}, folder)
    assert said == ["verify false failed on the pushed range: exit 1"]
