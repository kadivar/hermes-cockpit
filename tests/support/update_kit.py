# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""A stand-in plugin repository for the update tests: an "origin", a "seed" that pushes to it, and an "install" cloned
from it. Its `bin/cockpit` is a small script that answers the two commands the update's pre-flight runs, from files in
its own tree, so a commit decides what its own code says about the pack."""

import os
import subprocess

# `pack check` fails with the first line of PACK-CHECK-FAILS when the tree has that file; `pack effective --json` prints
# EFFECTIVE.json when the tree has it and is otherwise unknown, as on a kernel without the command. Each call is logged
# (the command, the pack it was pointed at, the folder it ran from) to the file PREFLIGHT_LOG names.
LAUNCHER = """#!/usr/bin/env python3
import os
import sys

tree = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
words = sys.argv[1:]
log = os.environ.get("PREFLIGHT_LOG")
if log:
    with open(log, "a", encoding="utf-8") as handle:
        handle.write(" ".join(words) + "\\t" + os.environ.get("COCKPIT_PACK", "") + "\\t" + tree + "\\n")
fails = os.path.join(tree, "PACK-CHECK-FAILS")
effective = os.path.join(tree, "EFFECTIVE.json")
if words == ["pack", "check"]:
    if os.path.isfile(fails):
        print("Traceback (most recent call last):", file=sys.stderr)
        print(open(fails, encoding="utf-8").read().splitlines()[0], file=sys.stderr)
        sys.exit(2)
    print("pack ok stand-in")
    sys.exit(0)
if words == ["pack", "effective", "--json"] and os.path.isfile(effective):
    text = open(effective, encoding="utf-8").read()
    if text.startswith("FAIL"):
        print(text.strip(), file=sys.stderr)
        sys.exit(1)
    print(text)
    sys.exit(0)
print("invalid value\\ncockpit pack check\\nExamples:\\n  cockpit pack check", file=sys.stderr)
sys.exit(2)
"""


def git(folder, *args) -> str:
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "Dev",
        "GIT_AUTHOR_EMAIL": "dev@example.test",
        "GIT_COMMITTER_NAME": "Dev",
        "GIT_COMMITTER_EMAIL": "dev@example.test",
    }
    return subprocess.run(
        ["git", "-C", str(folder), *args], check=True, capture_output=True, text=True, env=env
    ).stdout.strip()


def launcher(seed) -> None:
    """The stand-in `bin/cockpit` in a seed's tree (not yet committed)."""
    os.makedirs(os.path.join(str(seed), "bin"), exist_ok=True)
    path = os.path.join(str(seed), "bin", "cockpit")
    open(path, "w", encoding="utf-8").write(LAUNCHER)
    os.chmod(path, 0o755)


def install(tmp_path) -> dict:
    """{plugin, seed, commit, first}: an install on master at the origin's first commit; commit(message, files) adds a
    commit to the origin ({name: text}; a file given as None is removed) and returns its hash."""
    origin = tmp_path / "origin.git"
    subprocess.run(["git", "init", "-q", "--bare", str(origin)], check=True)
    seed = tmp_path / "seed"
    seed.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "master", str(seed)], check=True)
    (seed / "pyproject.toml").write_text("[project]\nname = 'x'\ndependencies = []\n", encoding="utf-8")
    (seed / "desktop").mkdir()
    (seed / "desktop" / "plugin.js").write_text("export {}\n", encoding="utf-8")
    (seed / "kernel" / "cockpitlib").mkdir(parents=True)
    (seed / "kernel" / "cockpitlib" / "a.py").write_text("x = 0\n", encoding="utf-8")
    launcher(seed)
    git(seed, "add", "-A")
    git(seed, "commit", "-q", "-m", "first")
    git(seed, "remote", "add", "origin", str(origin))
    git(seed, "push", "-q", "origin", "master")
    plugin = tmp_path / "plugin"
    subprocess.run(["git", "clone", "-q", "-b", "master", str(origin), str(plugin)], check=True)
    count = [0]

    def commit(message="next", files=None) -> str:
        count[0] += 1
        (seed / "kernel" / "cockpitlib" / "a.py").write_text(f"x = {count[0]}\n", encoding="utf-8")
        for name, text in (files or {}).items():
            path = seed / name
            if text is None:
                os.remove(path)
            else:
                path.write_text(text, encoding="utf-8")
        git(seed, "add", "-A")
        git(seed, "commit", "-q", "-m", message)
        git(seed, "push", "-q", "origin", "master")
        return git(seed, "rev-parse", "HEAD")

    return {"plugin": str(plugin), "seed": str(seed), "commit": commit, "first": git(seed, "rev-parse", "HEAD")}
