# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""plugin.yaml's `requires_hermes` is the one place that says which Hermes is the oldest this plugin runs on. Doctor
reads it: a patch release of a checked minor that is older than that is an error, exactly as an older minor is."""

import pytest
import yaml

from cockpitlib import doctor
from cockpitlib.pack import load
from cockpitlib.setup import setup
from tests.support.both_packs import PACKS, ROOT

MANIFEST = yaml.safe_load(open(f"{ROOT}/plugin.yaml", encoding="utf-8"))


def test_the_floor_is_read_from_the_manifest():
    floor, numbers = doctor.required_hermes()
    assert MANIFEST["requires_hermes"] == f">={floor}" and numbers == tuple(int(part) for part in floor.split("."))
    assert ".".join(floor.split(".")[:2]) in doctor.HERMES_VERIFIED


@pytest.mark.parametrize("pack_file", PACKS)
def test_a_patch_release_before_the_manifests_is_an_error_and_the_manifests_own_is_accepted(
    env, pack_file, monkeypatch
):
    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    pack = load(pack_file)
    setup(pack)
    floor, numbers = doctor.required_hermes()
    monkeypatch.setenv("COCKPIT_STUB_VERSION", floor)
    assert doctor._hermes() == {"version": floor, "problem": "", "note": ""}
    assert not [item for item in doctor.findings(pack) if item["id"].startswith("hermes.v")]
    older = ".".join(str(part) for part in (*numbers[:2], numbers[2] - 1))
    monkeypatch.setenv("COCKPIT_STUB_VERSION", older)
    found = [item for item in doctor.findings(pack) if item["id"].startswith("hermes.")]
    assert [(item["id"], item["severity"]) for item in found] == [("hermes.version", "error")]
    assert found[0]["message"] == (
        f"hermes {older} is older than {floor}, the oldest version this plugin runs on (plugin.yaml requires_hermes)"
    )
    assert found[0]["message"] in doctor.run(pack)
    newer = ".".join(str(part) for part in (*numbers[:2], numbers[2] + 5))
    monkeypatch.setenv("COCKPIT_STUB_VERSION", newer)
    assert doctor.hermes_check()["problem"] == ""


@pytest.mark.parametrize(
    "manifest, floor",
    [
        ('requires_hermes: ">=0.22.2"\n', ("0.22.2", (0, 22, 2))),
        ('requires_hermes: ">= 1.4"\n', ("1.4.0", (1, 4, 0))),
        ('requires_hermes: "~=0.22"\n', ("", ())),
        ("name: cockpit\n", ("", ())),
        ("- a list\n", ("", ())),
        ("requires_hermes: [unclosed\n", ("", ())),
        (None, ("", ())),
    ],
)
def test_a_manifest_that_asks_in_another_form_or_cannot_be_read_gives_doctor_no_floor(
    tmp_path, monkeypatch, manifest, floor
):
    if manifest is not None:
        (tmp_path / "plugin.yaml").write_text(manifest, encoding="utf-8")
    monkeypatch.setattr(doctor, "plugin_root", lambda: str(tmp_path))
    assert doctor.required_hermes() == floor


def test_without_a_floor_every_patch_release_of_a_checked_minor_is_accepted_as_before(env, tmp_path, monkeypatch):
    monkeypatch.setattr(doctor, "plugin_root", lambda: str(tmp_path))
    monkeypatch.setenv("COCKPIT_STUB_VERSION", "0.22.0")
    assert doctor.hermes_check()["problem"] == ""
