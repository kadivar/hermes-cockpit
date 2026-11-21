# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The tracker intent types are tracker-comment, tracker-create and tracker-transition, whatever the tracker is. A type
has one name: any other is unknown to the command line, to a plugin, to a pack key that names a type, and to every
listing of the records."""

import json
import os
import shutil

import pytest
import yaml

from cockpitlib import intents
from cockpitlib.cli import main
from cockpitlib.errors import CockpitError, PackError
from cockpitlib.pack import load
from cockpitlib.store import scratch
from tests.support.both_packs import PACKS, _client

TRACKER = ("tracker-comment", "tracker-create", "tracker-transition")
# names no kernel knows: one named after a tracker product, one after nothing
UNKNOWN = ("jira-comment", "jira-create", "jira-transition", "tracker-moved")
FLAGS = {
    "comment": ["--issue", "TASK-1", "--body", "the run passed"],
    "create": ["--summary", "Bump the parser"],
    "transition": ["--issue", "TASK-1", "--to", "In Review"],
}


def _copy(pack_file, tmp_path, folder) -> str:
    """A copy of the fixture, under a folder named packs as its @anchors need."""
    name = os.path.basename(os.path.dirname(pack_file))
    copied = tmp_path / folder / "packs" / name
    shutil.copytree(os.path.dirname(pack_file), copied)
    return str(copied / "pack.yaml")


def test_the_tracker_types_are_named_after_no_tracker_and_a_file_is_an_intent_only_under_a_type():
    assert set(TRACKER) < set(intents.TYPES) and not [name for name in intents.TYPES if "jira" in name]
    assert set(intents.TYPES) == set(intents.SCHEMAS) == set(intents.EXAMPLES) == set(intents.ORDER)
    assert all(intents.is_intent_file(f"001-{kind}.json") for kind in TRACKER)
    assert not any(intents.is_intent_file(f"001-{kind}.json") for kind in UNKNOWN)
    assert not intents.is_intent_file("001-body.md")
    assert not hasattr(intents, "ALIASES") and not hasattr(intents, "canonical")


@pytest.mark.parametrize("pack_file", PACKS)
@pytest.mark.parametrize("kind", TRACKER)
def test_outbox_new_writes_the_intent_under_the_type_it_was_given(env, pack_file, kind, monkeypatch, capsys, jira):
    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    monkeypatch.delenv("COCKPIT_LANE", raising=False)
    from cockpitlib.intents import load as load_intent
    from cockpitlib.intents import path_of

    jira.issues["TASK-1"] = {"key": "TASK-1", "fields": {"summary": "one", "status": {"name": "To Do"}}}
    flags = FLAGS[kind.split("-", 1)[1]]
    assert main(["outbox", "new", "TASK-100", kind, "--card", "c", "--summary", "from the lane", *flags]) == 0
    iid = capsys.readouterr().out.splitlines()[0]
    assert iid == f"TASK-100/001-{kind}" and load_intent(iid)["type"] == kind
    # the folder's lock is no record: it is left out, as every listing of records leaves it out
    assert [name for name in os.listdir(os.path.dirname(path_of(iid))) if not scratch(name)] == [f"001-{kind}.json"]
    assert main(["outbox", "list", "TASK-100"]) == 0 and json.loads(capsys.readouterr().out) == [iid]


@pytest.mark.parametrize("pack_file", PACKS)
@pytest.mark.parametrize("kind", UNKNOWN)
def test_a_name_that_is_no_type_is_refused_by_the_command_line_and_by_a_plugin(
    env, pack_file, kind, monkeypatch, capsys, jira
):
    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    monkeypatch.delenv("COCKPIT_LANE", raising=False)
    from cockpitlib import plugin_api
    from cockpitlib.intents import check_payload
    from cockpitlib.paths import outbox_of

    flags = FLAGS.get(kind.split("-", 1)[1], [])
    assert main(["outbox", "new", "TASK-100", kind, "--card", "c", "--summary", "from the lane", *flags]) == 1
    assert f"unknown type {kind}" in capsys.readouterr().err
    with pytest.raises(CockpitError, match=f"unknown type {kind}"):
        plugin_api.outbox_create("TASK-100", kind, "c", "ticket", {"summary": "Bump the parser"}, pack=load(pack_file))
    with pytest.raises(CockpitError, match=f"unknown type {kind}"):
        check_payload(kind, {"to": "Done", "issue": "TASK-1"})
    folder = outbox_of("TASK-100")
    assert not os.path.isdir(folder) or [name for name in os.listdir(folder) if not scratch(name)] == []
    assert jira.issues == {}


@pytest.mark.parametrize("pack_file", PACKS)
@pytest.mark.parametrize("kind", UNKNOWN)
def test_a_record_of_a_name_that_is_no_type_is_in_no_listing_and_is_never_published(
    env, pack_file, kind, monkeypatch, capsys, jira
):
    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    monkeypatch.delenv("COCKPIT_LANE", raising=False)
    pack = load(pack_file)
    from cockpitlib.intents import all_intents, next_seq, path_of
    from cockpitlib.intents import load as load_intent
    from cockpitlib.publish import execute

    record = {
        "id": f"TASK-100/001-{kind}",
        "ticket": "TASK-100",
        "type": kind,
        "status": "pending",
        "card_id": "c",
        "created_by": "human",
        "agent_summary": "ticket",
        "payload": {"summary": f"open {pack['name']}", "issue": "TASK-1", "to": "Done", "body": "said"},
    }
    os.makedirs(os.path.dirname(path_of(record["id"])), exist_ok=True)
    with open(path_of(record["id"]), "w", encoding="utf-8") as handle:
        json.dump(record, handle)
    assert all_intents("TASK-100") == [] and all_intents() == []
    assert main(["outbox", "list", "TASK-100"]) == 0 and json.loads(capsys.readouterr().out) == []
    assert _client().get("/list").json()["rows"] == []
    assert _client().get("/intent", params={"id": record["id"]}).status_code == 404
    # nothing goes out for it, by the command or by the publisher itself, even endorsed by its id
    assert main(["outbox", "endorse", record["id"], "low"]) == 0 and capsys.readouterr().out == "endorsed\n"
    assert main(["publish", "--id", record["id"]]) == 1
    assert json.loads(capsys.readouterr().out)["error"] == f"no publisher for {kind}"
    refused = execute(load_intent(record["id"]), pack=pack, dry_run=True)
    assert refused["ok"] is False and refused["error"] == f"no publisher for {kind}"
    assert jira.issues == {} and not [call for call in jira.requests if call["method"] != "GET"]
    # its number stays taken: a new intent of the ticket never shares a file prefix with it
    assert next_seq("TASK-100") == "002"


@pytest.mark.parametrize("pack_file", PACKS)
def test_the_fixture_packs_name_tracker_types_and_load(env, pack_file):
    pack = load(pack_file)
    assert set(TRACKER) <= set(pack["skills"]["intent"])
    named = json.dumps([pack.get("grooming_rules"), pack.get("bump_sequence")])
    assert "tracker-" in named and "jira-c" not in named and "jira-t" not in named


@pytest.mark.parametrize("pack_file", PACKS)
def test_outbox_auto_keeps_the_types_as_the_pack_wrote_them(env, pack_file, tmp_path):
    path = _copy(pack_file, tmp_path, "auto")
    raw = yaml.safe_load(open(path, encoding="utf-8"))
    raw["outbox"] = {
        **(raw.get("outbox") or {}),
        "auto": [{"scope": "release", "types": ["tracker-comment", "pr-comment"]}],
    }
    open(path, "w", encoding="utf-8").write(yaml.safe_dump(raw, sort_keys=False, allow_unicode=True))
    assert load(path)["outbox"]["auto"] == [{"scope": "release", "types": ["tracker-comment", "pr-comment"]}]


@pytest.mark.parametrize("kind", UNKNOWN)
@pytest.mark.parametrize(
    "key,shape,message",
    (
        ("grooming", lambda kind: [{"name": "move", "intent": kind}], "grooming lists act names"),
        ("grooming", lambda kind: [{"name": "move", "intent": [kind]}], "grooming lists act names"),
        ("bump_sequence", lambda kind: {"stages": [{"name": "move", "intent": kind}]}, "bump_sequence stage"),
        (
            "outbox",
            lambda kind: {"auto": [{"scope": "release", "types": [kind]}]},
            "outbox.auto types are intent types that publish",
        ),
    ),
)
def test_a_pack_key_that_names_no_type_is_refused(tmp_path, kind, key, shape, message):
    path = _copy(PACKS[0], tmp_path, "bad")
    raw = yaml.safe_load(open(path, encoding="utf-8"))
    raw[key] = shape(kind)
    open(path, "w", encoding="utf-8").write(yaml.safe_dump(raw, sort_keys=False))
    with pytest.raises(PackError, match=message):
        load(path)


@pytest.mark.parametrize("pack_file", PACKS)
@pytest.mark.parametrize("kind", UNKNOWN)
def test_skills_yaml_requires_skills_of_intent_types_only(pack_file, tmp_path, kind):
    path = _copy(pack_file, tmp_path, "skills")
    skills_file = os.path.join(os.path.dirname(path), "skills.yaml")
    skills = yaml.safe_load(open(skills_file, encoding="utf-8"))
    assert load(path)["skills"]["intent"] == skills["intent"]  # as written: each key is a type
    skills["intent"][kind] = skills["intent"]["tracker-comment"]
    open(skills_file, "w", encoding="utf-8").write(yaml.safe_dump(skills, sort_keys=False))
    with pytest.raises(PackError, match=f"skills.yaml intent: '{kind}' is no intent type"):
        load(path)


@pytest.mark.parametrize("pack_file", PACKS)
def test_a_tracker_type_requires_the_skills_the_pack_lists_for_it(env, pack_file):
    from cockpitlib.gate import _required_skills
    from cockpitlib.skill_log import missing
    from dashboard.cockpit.router import _skills

    pack = load(pack_file)
    for kind in TRACKER:
        intent = {
            "id": f"TASK-100/001-{kind}",
            "ticket": "TASK-100",
            "type": kind,
            "created_by": "tester-1",
            "card_id": "c",
        }
        assert _required_skills(pack, kind) != []
        assert missing(pack, intent) != []  # the gate is shut: a lane that loaded nothing is short
        assert _skills(pack, intent)["ok"] is False


def test_the_pages_and_the_description_list_the_types_and_nothing_beside_them(env, monkeypatch):
    monkeypatch.setenv("COCKPIT_PACK", PACKS[0])
    monkeypatch.delenv("COCKPIT_LANE", raising=False)
    from cockpitlib.describe import describe

    assert _client().get("/intent-types").json() == {"types": list(intents.TYPES)}
    found = describe()
    assert found["intent_types"] == intents.TYPES and "intent_type_aliases" not in found


def test_the_outbox_skill_names_each_tracker_type_once():
    from cockpitlib.pack import plugin_root

    text = open(os.path.join(plugin_root(), "skills", "outbox", "SKILL.md"), encoding="utf-8").read()
    for kind in TRACKER:
        assert text.count(f"| `{kind}` |") == 1
    assert "also accepted" not in text and "jira-" not in text
