# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The loader has never checked the shape of four egress lists or of a repo's gates, and a pack that loads today keeps
loading. Doctor says what such a pack does: an entry of terminal_deny or production_hosts that is no regular expression
is a security error (the hook raises on it instead of judging the command), and a list written as one text is a warning
that names the key (it is read letter by letter)."""

import re

import pytest

from cockpitlib import doctor, egress
from cockpitlib.pack import load
from cockpitlib.setup import setup
from tests.support.both_packs import PACKS


def _set_up(pack_file, monkeypatch) -> dict:
    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    pack = load(pack_file)
    setup(pack)
    return pack


def _of(pack, check_id) -> list:
    return [item for item in doctor.findings(pack) if item["id"] == check_id]


@pytest.mark.parametrize("pack_file", PACKS)
def test_a_fixture_pack_has_neither_finding(env, pack_file, monkeypatch):
    pack = _set_up(pack_file, monkeypatch)
    assert doctor.egress_pattern_problems(pack) == [] and doctor.text_for_list_problems(pack) == []
    assert not _of(pack, "egress.pattern-invalid") and not _of(pack, "pack.text-for-list")


def test_the_hook_raises_on_a_rule_it_cannot_read_instead_of_letting_the_command_pass():
    # what makes the finding an error: nothing is judged while such a rule stands, and nothing passes in silence
    with pytest.raises(re.error):
        egress.check("ls", production_hosts=["shop(.example"])
    with pytest.raises(re.error):
        egress.check("ls", extra_deny=["rm [ -rf"])


@pytest.mark.parametrize("pack_file", PACKS)
@pytest.mark.parametrize("key", doctor.EGRESS_PATTERNS)
def test_an_entry_that_is_no_regular_expression_is_a_security_error_that_names_its_key(
    env, pack_file, key, monkeypatch
):
    pack = _set_up(pack_file, monkeypatch)
    pack["egress"] = {**pack["egress"], key: [*(pack["egress"].get(key) or []), "shop(.example", 7]}
    found = _of(pack, "egress.pattern-invalid")
    assert [(item["severity"], item["security"], item["subject"]) for item in found] == [
        ("error", True, f"egress.yaml {key}")
    ] * 2
    assert found[0]["message"].startswith(f"egress.yaml {key}: 'shop(.example' is no regular expression (")
    assert found[1]["message"] == f"egress.yaml {key}: '7' is no regular expression (not a text)"
    assert f"correct that entry of egress.yaml {key} in " in found[0]["fix"]
    # doctor says the rest instead of stopping on the rule it cannot run
    assert found[0]["message"] in doctor.run(pack)


@pytest.mark.parametrize("pack_file", PACKS)
def test_a_pattern_python_may_read_otherwise_one_day_is_still_a_pattern(env, pack_file, monkeypatch, recwarn):
    pack = _set_up(pack_file, monkeypatch)
    pack["egress"] = {**pack["egress"], "terminal_deny": ["[[a-z]+"]}
    assert doctor.egress_pattern_problems(pack) == []
    assert not [warning for warning in recwarn.list if issubclass(warning.category, FutureWarning)]


@pytest.mark.parametrize("pack_file", PACKS)
def test_a_list_written_as_one_text_is_a_warning_that_names_the_key_and_never_fails_doctor(env, pack_file, monkeypatch):
    pack = _set_up(pack_file, monkeypatch)
    before, before_hosts = doctor.run(pack), pack["egress"]["production_hosts"]
    repos = [dict(repo) for repo in pack["repos"]["repos"]]
    repos[0]["gates"] = "make test"
    pack["repos"] = {**pack["repos"], "repos": repos}
    pack["egress"] = {
        **pack["egress"],
        "terminal_deny": "rm (x",
        "sacred": "main-db",
        "infra_paths": "/srv/infra",
        "production_hosts": "shop.example.test",
    }
    found = _of(pack, "pack.text-for-list")
    assert [item["subject"] for item in found] == [
        "egress.yaml terminal_deny",
        "egress.yaml production_hosts",
        "egress.yaml sacred",
        "egress.yaml infra_paths",
        f"repos.yaml {repos[0]['name']}.gates",
    ]
    assert all(item["severity"] == "warning" and not item["security"] for item in found)
    assert found[0]["message"] == (
        "egress.yaml terminal_deny is one text where a list is expected: it is read letter by letter, each letter as an entry"
    )
    assert found[-1]["fix"].startswith(f"write repos.yaml {repos[0]['name']}.gates as a list in ")
    # a text is not checked entry by entry; a probe that would run a letter that is no pattern is passed over, and one
    # that runs says what the letters do: the space in that deny refuses every command
    assert not _of(pack, "egress.pattern-invalid")
    assert any("the pack's own rules refuse git " in line for line in doctor.run(pack))
    # the warning itself never fails doctor: with texts that refuse nothing a lane needs, doctor says what it said
    pack["egress"] = {**pack["egress"], "terminal_deny": [], "infra_paths": [], "production_hosts": before_hosts}
    assert [item["subject"] for item in _of(pack, "pack.text-for-list")] == [
        "egress.yaml sacred",
        f"repos.yaml {repos[0]['name']}.gates",
    ]
    assert [line for line in doctor.run(pack) if line not in before] == []


def test_both_checks_are_registered_with_their_tier():
    assert doctor.CHECKS["egress.pattern-invalid"]["severity"] == "error"
    assert doctor.CHECKS["egress.pattern-invalid"]["security"] is True
    assert doctor.CHECKS["pack.text-for-list"]["severity"] == "warning"
    assert doctor.CHECKS["pack.text-for-list"]["security"] is False
