# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Loading a pack reads its plugin validator. It does not leave a bytecode file beside that source."""

import os
import shutil

from cockpitlib.pack import load

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_loading_a_pack_writes_no_bytecode_beside_its_plugin(tmp_path):
    copied = tmp_path / "packs" / "acme"
    shutil.copytree(os.path.join(ROOT, "packs", "acme"), copied)
    for folder, dirs, _files in os.walk(copied):
        for name in list(dirs):
            if name == "__pycache__":
                shutil.rmtree(os.path.join(folder, name))
                dirs.remove(name)
    load(str(copied / "pack.yaml"))
    written = []
    for folder, _dirs, files in os.walk(copied):
        written += [os.path.join(folder, name) for name in files if name.endswith(".pyc")]
    assert written == []
