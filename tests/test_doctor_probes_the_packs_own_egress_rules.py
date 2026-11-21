# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Doctor asks the pack's own rules what it asks the kernel's: a pack whose denies refuse a plain `git status`, `git
diff` or `git log` to a worker leaves its lanes unable to work, which is an error; and a key in egress.yaml that no
kernel code reads (a typo such as `production_host`) is a warning that names the key it was probably meant to be. The
pack still loads in both cases."""

import shutil

import pytest
import yaml

from cockpitlib import doctor
from cockpitlib.pack import load
from tests.support.both_packs import PACKS

READS = ("git status", "git diff", "git log")


def _copy(pack_file, tmp_path, change) -> str:
    """A copy of the fixture pack with its egress.yaml changed."""
    import os

    copied = tmp_path / "packs" / os.path.basename(os.path.dirname(pack_file))
    shutil.copytree(os.path.dirname(pack_file), copied)
    raw = yaml.safe_load((copied / "egress.yaml").read_text(encoding="utf-8")) or {}
    change(raw)
    (copied / "egress.yaml").write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")
    return str(copied / "pack.yaml")


@pytest.mark.parametrize("pack_file", PACKS)
def test_the_fixture_packs_refuse_no_plain_read_and_hold_no_unknown_key(bare, pack_file, monkeypatch):
    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    pack = load(pack_file)
    assert doctor.pack_read_problems(pack) == [] and doctor.egress_key_problems(pack) == []


@pytest.mark.parametrize("pack_file", PACKS)
@pytest.mark.parametrize(
    "field,rule,refused",
    [
        ("terminal_deny", r"\bgit\s+status\b", ("git status",)),
        ("terminal_deny", r"\bgit\b", READS),
        ("production_hosts", r"git", READS),
        ("role_deny", {"worker": [r"\bgit\s+(diff|log)\b"]}, ("git diff", "git log")),
        ("git_deny", {"worker": ["log"]}, ("git log",)),
    ],
)
def test_a_pack_deny_that_refuses_a_plain_read_to_a_worker_is_an_error(
    bare, pack_file, field, rule, refused, monkeypatch, tmp_path
):
    def change(raw):
        raw[field] = rule if isinstance(rule, dict) else [*(raw.get(field) or []), rule]

    copied = _copy(pack_file, tmp_path, change)
    monkeypatch.setenv("COCKPIT_PACK", copied)
    pack = load(copied)  # the pack still loads
    problems = doctor.pack_read_problems(pack)
    listed = pack["allowed"][
        "reads"
    ]  # each fixture lists one of the three as an allowed read: that one is past its denies
    assert [line.split(" to a worker", 1)[0] for line in problems] == [
        f"the pack's own rules refuse {command}" for command in refused if command not in listed
    ]
    pack["allowed"] = {"reads": []}
    assert [line.split(" to a worker", 1)[0] for line in doctor.pack_read_problems(pack)] == [
        f"the pack's own rules refuse {command}" for command in refused
    ]
    assert all(line.endswith(": its lanes cannot work") for line in problems)
    spec = doctor.CHECKS["egress.pack-refuses-read"]
    assert spec["severity"] == "error" and not spec["security"] and "egress.yaml" in spec["fix"]


@pytest.mark.parametrize("pack_file", PACKS)
def test_a_rule_for_another_seat_and_a_read_the_pack_lists_as_allowed_are_no_error(
    bare, pack_file, monkeypatch, tmp_path
):
    def change(raw):
        raw["role_deny"] = {**(raw.get("role_deny") or {}), "reviewer": [r"\bgit\s+log\b"]}
        raw["git_deny"] = {"reviewer": ["commit", "push"], "worker": ["push", "tag"]}
        raw["terminal_deny"] = [*(raw.get("terminal_deny") or []), r"\bgit\s+status\s+--porcelain\b"]

    copied = _copy(pack_file, tmp_path, change)
    monkeypatch.setenv("COCKPIT_PACK", copied)
    assert doctor.pack_read_problems(load(copied)) == []
    pack = load(pack_file)
    listed = pack["allowed"]["reads"][0]
    pack["egress"] = {**pack["egress"], "terminal_deny": [*pack["egress"]["terminal_deny"], r"\bgit\s+(status|diff)\b"]}
    refused = [
        line.split(" to a worker", 1)[0][len("the pack's own rules refuse ") :]
        for line in doctor.pack_read_problems(pack)
    ]
    assert refused == [command for command in ("git status", "git diff") if command != listed], (
        "an allowed read is past the pack's denies"
    )


@pytest.mark.parametrize("pack_file", PACKS)
def test_an_unknown_key_in_the_egress_file_is_a_warning_that_names_the_closest_key(
    bare, pack_file, monkeypatch, tmp_path
):
    def change(raw):
        raw["production_host"] = ["app\\.example\\.test"]
        raw["terminal_denies"] = []
        raw["zzz"] = True

    copied = _copy(pack_file, tmp_path, change)
    monkeypatch.setenv("COCKPIT_PACK", copied)
    pack = load(copied)  # a typo is not a load failure
    assert doctor.egress_key_problems(pack) == [
        "egress.yaml: unknown key production_host (did you mean production_hosts?): no kernel code reads it",
        "egress.yaml: unknown key terminal_denies (did you mean terminal_deny?): no kernel code reads it",
        "egress.yaml: unknown key zzz: no kernel code reads it",
    ]
    spec = doctor.CHECKS["egress.unknown-key"]
    assert (
        spec["severity"] == "warning"
        and spec["born"]
        and not spec["security"]
        and "{subject}"
        not in doctor._finding(
            "egress.unknown-key", "x", "zzz", {"pack": "/p", "home": "/h", "plugin": "/k", "verified": "0.22"}
        )["fix"]
    )
    assert doctor.egress_key_problems({"egress": "not a table"}) == [] and doctor.egress_key_problems({}) == []


@pytest.mark.parametrize("pack_file", PACKS)
def test_doctor_reports_both_with_their_tiers(env, pack_file, monkeypatch, tmp_path):
    from cockpitlib.setup import setup

    def change(raw):
        raw["production_host"] = ["x"]
        raw["zzz"] = True
        raw["terminal_deny"] = [*(raw.get("terminal_deny") or []), r"\bgit\s+status\b"]

    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    setup(load(pack_file))
    pack = load(pack_file)
    pack["egress"] = load(_copy(pack_file, tmp_path, change))["egress"]
    pack["allowed"] = {"reads": []}
    found = {item["id"]: item for item in doctor.findings(pack)}
    assert found["egress.pack-refuses-read"]["severity"] == "error" and found["egress.pack-refuses-read"]["fix"]
    assert found["egress.unknown-key"]["severity"] == "warning" and found["egress.unknown-key"]["subject"] == "zzz"
    assert [item["subject"] for item in doctor.findings(pack) if item["id"] == "egress.unknown-key"] == [
        "production_host",
        "zzz",
    ]
    lines = doctor.run(pack)
    assert any(line.startswith("the pack's own rules refuse git status") for line in lines)
    assert not any("unknown key" in line for line in lines), (
        "a warning born with the tiers fails nothing that passed before"
    )
