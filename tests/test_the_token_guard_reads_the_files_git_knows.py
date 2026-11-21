# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Every layer of the token guard reads the files git knows: the tracked ones, and the new ones git does not ignore, so
a file is checked before its first commit and a scratch file git ignores never fails the guard. A folder that is no
checkout (an unpacked archive) is still walked whole."""

import importlib.util
import os
import subprocess

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
spec = importlib.util.spec_from_file_location(
    "grep_tokens_by_git", os.path.join(ROOT, "tests", "guards", "grep_tokens.py")
)
guard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(guard)

VENDOR = "Vendor" + "Name"
HOME = "/Users/" + "somebody/work"


def _git(root, *argv):
    subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@example.test", *argv],
        cwd=root,
        check=True,
        capture_output=True,
    )


def _checkout(tmp_path, files: dict, ignore: str = "") -> str:
    root = str(tmp_path)
    for name, text in {
        "tests/guards/forbidden-tokens.txt": "fixturename\n",
        "tests/guards/ui-vendor-names.txt": VENDOR + "\n",
        "tests/guards/process-words.txt": "widgetry\n",
        "tests/guards/token-allow.txt": "",
        ".gitignore": ignore,
        **files,
    }.items():
        path = os.path.join(root, name)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as out:
            out.write(text)
    _git(root, "init", "-q")
    return root


def _scanned(root, **more) -> list:
    return sorted(os.path.relpath(path, root) for path in guard.files(root=root, **more))


def test_a_scratch_file_git_ignores_never_fails_the_guard(tmp_path, monkeypatch):
    monkeypatch.delenv("COCKPIT_EXTRA_TOKENS", raising=False)
    files = {
        "docs/a.md": "fine\n",
        "docs/scratch/notes.md": f"{VENDOR} said so, see {HOME}\n",
        "kernel/out.log": f"{VENDOR}\n",
    }
    root = _checkout(tmp_path, files, ignore="scratch/\n*.log\n")
    _git(root, "add", "-A")
    assert guard.problems(root) == []
    assert _scanned(root) == ["docs/a.md"]
    assert "docs/scratch/notes.md" not in guard.tracked(root)


def test_a_new_file_is_read_before_its_first_commit(tmp_path, monkeypatch):
    monkeypatch.delenv("COCKPIT_EXTRA_TOKENS", raising=False)
    root = _checkout(tmp_path, {"docs/a.md": "fine\n"})
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "first")
    with open(os.path.join(root, "docs", "new.md"), "w", encoding="utf-8") as out:
        out.write(f"ask {VENDOR}, open {HOME}\n")
    assert "docs/new.md" in guard.tracked(root)
    assert guard.problems(root) == [
        f"vendor: {VENDOR} in docs/new.md:1",
        f"home-path: ask {VENDOR}, open {HOME} in docs/new.md:1",
    ]


def test_the_word_lists_keep_their_places_and_their_exemptions_in_a_checkout(tmp_path, monkeypatch):
    monkeypatch.delenv("COCKPIT_EXTRA_TOKENS", raising=False)
    files = {
        "docs/a.md": "ask fixturename\n",
        "packs/p/pack.yaml": "name: fixturename\n",
        "packsaddle/b.md": "fixturename\n",
        "tests/test_a.py": "x = 'fixturename'\n",
        "kernel/fence_markers.txt": "fixturename\n",
        "README.md": "fixturename here\n",
        "notes.md": "fixturename\n",
    }
    root = _checkout(tmp_path, files)
    told = guard.problems(root, [])
    # a fixture name is refused in a scanned place, expected in a fixture home, and not looked for outside both
    assert told == [
        "forbidden-tokens.txt: fixturename in README.md:1",
        "forbidden-tokens.txt: fixturename in docs/a.md:1",
    ]
    assert _scanned(root, also=("tests",)) == [
        "README.md",
        "docs/a.md",
        "packs/p/pack.yaml",
        "tests/test_a.py",
    ]  # the guard's own lists are never read as text to check
    assert _scanned(root, skip=("packs", "README.md")) == ["docs/a.md"]


def test_a_tracked_file_that_is_gone_from_the_folder_is_passed_over(tmp_path, monkeypatch):
    monkeypatch.delenv("COCKPIT_EXTRA_TOKENS", raising=False)
    root = _checkout(tmp_path, {"docs/a.md": "fine\n", "docs/gone.md": f"{VENDOR}\n"})
    _git(root, "add", "-A")
    os.remove(os.path.join(root, "docs", "gone.md"))
    assert "docs/gone.md" in guard.tracked(root) and guard.problems(root) == []


def test_a_folder_that_is_no_checkout_is_walked_whole(tmp_path, monkeypatch):
    monkeypatch.delenv("COCKPIT_EXTRA_TOKENS", raising=False)
    root = str(tmp_path)
    for name, text in {
        "tests/guards/forbidden-tokens.txt": "fixturename\n",
        "tests/guards/ui-vendor-names.txt": VENDOR + "\n",
        "docs/a.md": f"{VENDOR}\n",
    }.items():
        os.makedirs(os.path.dirname(os.path.join(root, name)), exist_ok=True)
        with open(os.path.join(root, name), "w", encoding="utf-8") as out:
            out.write(text)
    assert guard.checkout(root) is None and guard.tracked(root) == []
    assert guard.problems(root, []) == [f"vendor: {VENDOR} in docs/a.md:1"]


def test_this_tree_is_read_from_gits_list_and_passes():
    known = guard.checkout(ROOT)
    assert "tests/guards/grep_tokens.py" in known and not any(name.startswith((".venv/", ".tmp/")) for name in known)
    assert all(os.path.relpath(path, ROOT) in known for path in guard.files())
