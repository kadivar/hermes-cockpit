# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The Desktop loads desktop/plugin.js, a committed bundle of desktop/src. A change to the sources that is not built
into the bundle never reaches the Desktop, however often it restarts: this test rebuilds the bundle and compares."""

import os
import shutil
import subprocess

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DESKTOP = os.path.join(ROOT, "desktop")


def _esbuild() -> str:
    local = os.path.join(DESKTOP, "node_modules", ".bin", "esbuild")
    if os.access(local, os.X_OK):
        return local
    return shutil.which("esbuild") or ""


def test_the_desktop_bundle_is_built_from_its_sources(tmp_path):
    esbuild = _esbuild()
    if not esbuild:
        pytest.skip("esbuild is not installed beside desktop/")
    built = tmp_path / "plugin.js"
    done = subprocess.run(
        [
            esbuild,
            "src/index.js",
            "--bundle",
            "--format=esm",
            f"--outfile={built}",
            "--external:@hermes/plugin-sdk",
            "--external:react",
            "--external:react/jsx-runtime",
            "--target=es2022",
            "--log-level=error",
        ],
        cwd=DESKTOP,
        capture_output=True,
        text=True,
        check=False,
    )
    assert done.returncode == 0, done.stderr
    committed = open(os.path.join(DESKTOP, "plugin.js"), encoding="utf-8").read()
    fresh = built.read_text(encoding="utf-8")
    assert committed == fresh, (
        "desktop/plugin.js is not the bundle of desktop/src: run `npm run build` in desktop/ and commit plugin.js"
    )
