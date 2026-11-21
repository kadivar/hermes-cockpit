# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""A snapshot of a pack that links a folder living elsewhere still loads: the link becomes a folder with its top files."""

import importlib.util
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _tool():
    spec = importlib.util.spec_from_file_location(
        "replay_tool", os.path.join(ROOT, "scripts", "replay_support", "tool.py")
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_a_linked_folder_outside_the_tree_is_copied_as_a_folder_with_its_top_files_only(tmp_path):
    outside = tmp_path / "elsewhere" / "extra"
    (outside / "deep").mkdir(parents=True)
    (outside / "plugin.yaml").write_text("name: extra\n")
    (outside / "deep" / "private.txt").write_text("not copied")
    source = tmp_path / "pack"
    (source / "plugins").mkdir(parents=True)
    os.symlink(str(outside), str(source / "plugins" / "extra"))
    target = tmp_path / "copy"

    counts = _tool().copy_tree(str(source), str(target), 0)

    copied = target / "plugins" / "extra"
    assert copied.is_dir() and not copied.is_symlink()
    assert (copied / "plugin.yaml").read_text() == "name: extra\n"
    assert not (copied / "deep").exists()
    assert counts["links_skipped"] == 1
