# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""An older install moves to this kernel and back: planned, applied, verified, rolled back."""

import io
import json
import os
import re
import sys

import pytest

from cockpitlib.cli import main
from cockpitlib.errors import CockpitError
from cockpitlib.pack import load
from tests.support.both_packs import PACKS, _other


@pytest.mark.parametrize("pack_file", PACKS)
def test_rollback_restores_the_board_and_keeps_hermes_records(env, pack_file):
    pack = load(pack_file)
    other = load(PACKS[0] if pack["name"] == "bravo" else PACKS[1])
    assert pack["board"] != other["board"]
    from cockpitlib.migrate import rollback

    home = env["home"]
    snap = env["root"] / f"snap-{pack['name']}"
    board = snap / "kanban" / "boards" / pack["board"]
    board.mkdir(parents=True)
    (board / "board.json").write_text(pack["name"] + "\n", encoding="utf-8")
    (snap / "cockpit.yaml").write_text(f"pack: {pack['name']}\n", encoding="utf-8")
    live = home / "kanban" / "boards" / pack["board"]
    live.mkdir(parents=True)
    (live / "board.json").write_text("changed\n", encoding="utf-8")
    (home / "cockpit.yaml").write_text("pack: changed\n", encoding="utf-8")
    from cockpitlib.paths import records_name

    records = env["workspace"] / records_name() / "qa"
    records.mkdir(parents=True)
    kept = records / "stay.txt"
    kept.write_text(pack["name"] + "\n", encoding="utf-8")
    restored = rollback(str(snap), str(home))
    assert str(home / "kanban") in restored
    assert (live / "board.json").read_text(encoding="utf-8") == pack["name"] + "\n"
    assert other["name"] not in (live / "board.json").read_text(encoding="utf-8")
    assert (home / "cockpit.yaml").read_text(encoding="utf-8") == f"pack: {pack['name']}\n"
    assert kept.read_text(encoding="utf-8") == pack["name"] + "\n"
    assert (env["workspace"] / records_name()).is_dir()


@pytest.mark.parametrize("pack_file", PACKS)
def test_a_legacy_install_is_planned_applied_verified_and_rolled_back(env, pack_file, monkeypatch, tmp_path, capsys):
    import shutil
    import sqlite3

    import yaml

    from cockpitlib.errors import PackError

    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    pack = load(pack_file)
    other = _other(pack)
    from cockpitlib import pack_migration
    from cockpitlib.intents import load as load_intent
    from cockpitlib.kanban import board_cards, db_path
    from cockpitlib.lane_vault import items
    from cockpitlib.paths import hermes_home, workspace
    from cockpitlib.slots import read_owner, read_ticket
    from tests.support.earlier_install import build
    from tests.test_vault import seal_ephemeral

    seal_ephemeral(monkeypatch, str(env["home"]))
    spec = pack_migration.load_spec(pack)
    assert spec["legacy"]["crons"] != pack_migration.load_spec(other)["legacy"]["crons"]
    origin = yaml.safe_load(open(os.path.join(pack["_dir"], "staging.yaml"), encoding="utf-8"))["origins"]["app"]
    built = build(pack, spec, origin)
    home = hermes_home()
    before = {
        name: open(os.path.join(home, name), encoding="utf-8").read()
        for name in ("config.yaml", "SOUL.md", ".env", "cron/jobs.json")
    }
    planned = pack_migration.plan(pack)
    counts = planned["actions"]
    assert counts["profiles_remove"] == len(spec["legacy"]["profiles"]["remove"]) and counts["crons"] == len(
        spec["legacy"]["crons"]["retire"]
    ) + len(spec["legacy"]["crons"]["replace"])
    assert (
        counts["plugins"] == 1
        and counts["shell_hooks"] == 1
        and counts["records"] == len(spec["records"]["map"])
        and counts["cards"] == 1
    )
    assert counts["vault_logins"] == built["logins"] and planned["ready"] == []
    assert not any("pw-one" in json.dumps(value) for value in planned.values())  # the plan reads no secret
    lines = {line: ok for ok, line, _evidence in pack_migration.verify(pack, expected_logins=built["logins"])}
    assert lines["no legacy cron is registered"] is False and lines["the old record locations are empty"] is False
    connection = sqlite3.connect(db_path(pack["board"]))
    connection.execute("update tasks set status = 'running' where id = ?", (built["card"],))
    connection.commit()
    with pytest.raises(CockpitError, match="still running"):
        pack_migration.apply(pack)
    connection.execute("update tasks set status = 'ready' where id = ?", (built["card"],))
    connection.commit()
    connection.close()
    open(os.path.join(home, "gateway.state"), "w", encoding="utf-8").write(
        "running\n"
    )  # cockpit's switch, not the process
    assert pack_migration._gateway_running() is False
    pidfile = os.path.join(home, "gateway.pid")
    json.dump({"pid": os.getpid(), "kind": "hermes-gateway", "hermes_home": home}, open(pidfile, "w", encoding="utf-8"))
    with pytest.raises(CockpitError, match="gateway is running"):
        pack_migration.apply(pack)  # Hermes's own pid file for this home, a live process
    for stale in ({"pid": 2**22 + 12345}, {"pid": "x"}, "{bad"):
        open(pidfile, "w", encoding="utf-8").write(stale if isinstance(stale, str) else json.dumps(stale))
        assert pack_migration._gateway_running() is False
    import errno

    real_kill = os.kill
    monkeypatch.setattr(
        "cockpitlib.pack_migration.os.kill", lambda *a: (_ for _ in ()).throw(PermissionError(errno.EPERM, "not ours"))
    )
    open(pidfile, "w", encoding="utf-8").write(json.dumps({"pid": 1}))
    assert pack_migration._gateway_running() is True  # alive, owned by someone else
    monkeypatch.setattr("cockpitlib.pack_migration.os.kill", real_kill)
    os.remove(pidfile)
    applied = pack_migration.apply(pack)
    assert (
        applied["vault"] == {"imported": 2, "kept": 0}
        and applied["replace_profiles"] == spec["legacy"]["profiles"]["replace"]
    )
    journal = open(applied["journal"], encoding="utf-8").read()
    assert "pw-one" not in journal and "pw-two" not in journal
    lines = {
        line: (ok, evidence) for ok, line, evidence in pack_migration.verify(pack, expected_logins=built["logins"])
    }
    for line in (
        "no legacy cron is registered",
        "no legacy plugin is enabled",
        "no legacy shell hook is registered",
        "no legacy profile remains",
        "the root holds no legacy soul block, env key or config key",
        "the old record locations are empty",
        "no open card body calls a legacy command",
        "every intent loads with a cockpit type",
        "every open card maps to a flow",
        "the seat stores hold every exported login",
    ):
        assert lines[line][0], (line, lines[line])
    config = yaml.safe_load(open(os.path.join(home, "config.yaml"), encoding="utf-8"))
    assert config["plugins"]["enabled"] == [*spec["legacy"]["plugins"]["keep"], "cockpit"]
    assert [entry["command"] for entry in next(iter(config["hooks"].values()))] == ["/usr/bin/true"]
    soul = open(os.path.join(home, "SOUL.md"), encoding="utf-8").read()
    assert "legacy concierge" not in soul and "kept before" in soul and "kept after" in soul
    assert open(os.path.join(home, ".env"), encoding="utf-8").read() == "KEEP_ME=1\n"
    left = [job["name"] for job in json.load(open(os.path.join(home, "cron", "jobs.json"), encoding="utf-8"))["jobs"]]
    assert left == [
        "someone-elses-job",
        *spec["legacy"]["crons"]["replace"],
    ]  # cockpit's own job of a replaced name stays
    ticket = f"{pack['tracker']['project']}-501"
    kept = load_intent(f"{ticket}/001-tracker-comment")
    assert kept["payload"] == {"body": "kept"} and kept["legacy"] == {
        "lane_mood": "calm",
        "payload.legacy_channel": "x",
    }
    parked = load_intent(f"{ticket}/002-infra-note")  # renamed with its type, so the lister and the page see it
    assert (
        parked["type"] == "infra-note"
        and parked["status"] == "held"
        and parked["legacy"] == {"type": "deploy-now", "id": f"{ticket}/002-deploy"}
    )
    assert not os.path.exists(os.path.join(workspace(), spec["records"]["map"][0]["to"], ticket, "002-deploy.json"))
    shipped = load_intent(
        f"{ticket}/003-infra-note"
    )  # closed: history keeps its status, old field names land on the page's
    assert (
        shipped["status"] == "published"
        and "hold" not in shipped
        and shipped["summary"] == "shipped the log"
        and shipped["risk"] == "low"
    )
    assert shipped["receipt"] == {"url": "https://relay.test/log/3"} and shipped["legacy"] == {
        "type": "ship-log",
        "id": f"{ticket}/003-ship-log",
    }
    body_path = os.path.join(workspace(), spec["records"]["map"][0]["to"], ticket, "001-body.json")
    assert (
        "legacy_converted" not in json.load(open(body_path, encoding="utf-8"))
        and "kept body" in open(body_path, encoding="utf-8").read()
    )
    assert '"skipped": 1' in journal.replace(" ", "") or '"skipped":1' in journal.replace(" ", "")
    from cockpitlib.intents import all_intents

    assert {row["id"] for row in all_intents(ticket)} == {
        f"{ticket}/001-tracker-comment",
        f"{ticket}/002-infra-note",
        f"{ticket}/003-infra-note",
    }
    body = next(card["body"] for card in board_cards(pack["board"]) if card["id"] == built["card"])
    assert re.search(spec["board"]["rewrite"][0]["pattern"], body) is None and "cockpit" in body
    binding = spec["slots"]["bindings"][0]
    assert (
        (read_ticket(1) == f"{pack['tracker']['project']}-503")
        if binding["to"] == "ticket"
        else (read_owner(1) == "lane:worker-1")
    )
    assert {item["identifier"] for item in items("tester-1")} >= {
        f"qa1@{pack['name']}.test",
        f"qa2@{pack['name']}.test",
    }
    assert all(
        not os.path.exists(os.path.join(home, "profiles", name)) for name in spec["legacy"]["profiles"]["remove"]
    )
    if pack["name"] == "acme":
        assert os.path.isfile(os.path.join(os.environ["COCKPIT_ROOT"], "relay-archived"))
    restored = pack_migration.rollback(pack, applied["snapshot"])
    assert restored
    for name, text in before.items():
        assert open(os.path.join(home, name), encoding="utf-8").read() == text, name
    assert all(os.path.exists(os.path.join(workspace(), row["from"])) for row in spec["records"]["map"])
    assert all(os.path.isdir(os.path.join(home, "profiles", name)) for name in spec["legacy"]["profiles"]["remove"])
    body = next(card["body"] for card in board_cards(pack["board"]) if card["id"] == built["card"])
    assert re.search(spec["board"]["rewrite"][0]["pattern"], body)
    again = pack_migration.apply(pack)  # a second apply after the rollback succeeds
    assert again["vault"] == {"imported": 2, "kept": 0}  # the rollback took the seat stores back too
    from cockpitlib.vault import import_logins

    exported = open(
        os.path.join(
            os.environ["COCKPIT_ROOT"], "relay-logins.jsonl" if pack["name"] == "acme" else "tide-logins.jsonl"
        ),
        encoding="utf-8",
    ).read()
    assert import_logins(exported, pack) == {"imported": 0, "kept": 2}  # what the seat store holds is kept
    with pytest.raises(CockpitError, match="no snapshot nope"):
        pack_migration.rollback(pack, "nope")
    assert main(["migrate", "plan"]) == 0 and '"actions"' in capsys.readouterr().out
    assert main(["migrate", "verify"]) in (0, 1) and "no legacy cron is registered" in capsys.readouterr().out
    assert main(["migrate", "rollback", again["snapshot"]]) == 0
    assert main(["migrate", "apply"]) == 0 and '"snapshot"' in capsys.readouterr().out
    login = json.dumps({"lane": "tester-1", "origin": origin, "email": f"cli@{pack['name']}.test", "secret": "pw-cli"})
    monkeypatch.setattr("sys.stdin", io.StringIO(login + "\n\n"))
    assert main(["vault", "import"]) == 0 and '"imported": 1' in capsys.readouterr().out
    with pytest.raises(CockpitError, match="line 1 is not JSON"):
        import_logins("{bad")
    with pytest.raises(CockpitError, match="a login is"):
        import_logins(json.dumps({"origin": origin}))
    name = os.path.basename(os.path.dirname(pack_file))
    copied = tmp_path / "packs" / name
    shutil.copytree(os.path.dirname(pack_file), copied)
    bare = load(str(copied / "pack.yaml"))
    (copied / "migrate.yaml").unlink()
    assert pack_migration.load_spec(load(str(copied / "pack.yaml"))) == {}
    with pytest.raises(CockpitError, match="nothing to migrate"):
        pack_migration.apply(load(str(copied / "pack.yaml")))
    raw = spec
    for change, message in (
        (("legacy", {"nope": 1}), "legacy takes"),
        (("legacy", {"profiles": {"remove": "x"}}), "legacy.profiles takes"),
        (("legacy", {"plugins": {"keep": ["ghost"]}}), "keeps plugin ghost"),
        (("legacy", {"shell_hooks": [{"event": "x"}]}), "shell_hooks lists"),
        (("legacy", {"root": {"soul_blocks": [{"start": "a"}]}}), "soul_blocks lists"),
        (("legacy", {"root": {"x": 1}}), "legacy.root takes"),
        (("records", {"map": [{"from": "/abs", "to": "x"}]}), "stay inside it"),
        (("records", {"map": [{"from": "a", "to": "b", "kind": "zip"}]}), "records.map lists"),
        (("board", {"rewrite": [{"pattern": "(", "replace": ""}]}), "board.rewrite ("),
        (("board", {"flows": [{"pattern": "x"}]}), "board.flows lists"),
        (("slots", {"bindings": [{"from": "x", "to": "ticket", "format": ""}]}), "slots.bindings lists"),
        (("exporters", {"vault": {"argv": []}}), "exporters.vault is"),
        (("exporters", {"extra": [{"name": "x"}]}), "exporters.extra lists"),
        (("other", 1), "migrate.yaml takes"),
    ):
        (copied / "migrate.yaml").write_text(
            yaml.safe_dump({**raw, change[0]: change[1]}, sort_keys=False), encoding="utf-8"
        )
        with pytest.raises(PackError, match=re.escape(message)):
            pack_migration.load_spec(bare)


@pytest.mark.parametrize("pack_file", PACKS)
def test_migration_moves_tracked_records_with_git_and_stops_on_a_failed_exporter(env, pack_file, monkeypatch, tmp_path):
    import shutil
    import subprocess

    import yaml

    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    pack = load(pack_file)
    from cockpitlib import pack_migration
    from cockpitlib.paths import hermes_home, workspace

    name = os.path.basename(os.path.dirname(pack_file))
    copied = tmp_path / "packs" / name
    shutil.copytree(os.path.dirname(pack_file), copied)
    repo = os.path.join(workspace(), f"legacy-{pack['name']}")
    os.makedirs(os.path.join(repo, "old"), exist_ok=True)
    os.makedirs(os.path.join(repo, "new", "keep"), exist_ok=True)
    open(os.path.join(repo, "old", "a.md"), "w", encoding="utf-8").write("tracked\n")
    open(os.path.join(repo, "new", "keep", "b.md"), "w", encoding="utf-8").write("already here\n")
    for argv in (["init", "-q"], ["add", "-A"], ["-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "x"]):
        subprocess.run(["git", "-C", repo, *argv], check=True, capture_output=True)
    script = tmp_path / "export.sh"
    script.write_text(
        '#!/bin/sh\n[ "$1" = count ] && { [ -n "$BAD_COUNT" ] && { echo nope; exit 0; }; [ -n "$FAIL_COUNT" ] && exit 2; echo 0; exit 0; }\n'
        '[ -n "$FAIL_DUMP" ] && exit 3\nexit 0\n',
        encoding="utf-8",
    )
    script.chmod(0o755)
    spec = {
        "records": {"map": [{"from": f"legacy-{pack['name']}/old", "to": f"legacy-{pack['name']}/new", "kind": "dir"}]},
        "exporters": {
            "vault": {"argv": [str(script), "dump"], "count_argv": [str(script), "count"]},
            "extra": [{"name": "last", "argv": [str(script), "extra"]}],
        },
    }
    (copied / "migrate.yaml").write_text(yaml.safe_dump(spec), encoding="utf-8")
    moved = load(str(copied / "pack.yaml"))
    monkeypatch.setenv("FAIL_COUNT", "1")
    with pytest.raises(CockpitError, match="vault exporter count failed"):
        pack_migration.plan(moved)
    monkeypatch.delenv("FAIL_COUNT")
    monkeypatch.setenv("BAD_COUNT", "1")
    with pytest.raises(CockpitError, match="answered no number"):
        pack_migration.plan(moved)
    monkeypatch.delenv("BAD_COUNT")
    open(os.path.join(hermes_home(), "config.yaml"), "w", encoding="utf-8").write("{ broken")
    assert pack_migration.plan(moved)["actions"]["records"] == 1  # an unreadable config is read as empty
    monkeypatch.setenv("FAIL_DUMP", "1")
    with pytest.raises(CockpitError, match="vault exporter failed"):
        pack_migration.apply(moved)
    monkeypatch.delenv("FAIL_DUMP")
    stamp = sorted(os.listdir(pack_migration.snapshots_dir()))[-1]
    pack_migration.rollback(moved, stamp)
    assert os.path.isfile(os.path.join(repo, "old", "a.md"))
    applied = pack_migration.apply(moved)
    assert os.path.isfile(os.path.join(repo, "new", "a.md")) and os.path.isfile(
        os.path.join(repo, "new", "keep", "b.md")
    )
    status = subprocess.run(
        ["git", "-C", repo, "status", "--porcelain"], capture_output=True, text=True, check=True
    ).stdout
    assert "R  old/a.md -> new/a.md" in status  # moved inside one repository: a git mv
    pack_migration.rollback(moved, applied["snapshot"])
    assert os.path.isfile(os.path.join(repo, "old", "a.md")) and not os.path.exists(os.path.join(repo, "new", "a.md"))
    assert (
        subprocess.run(["git", "-C", repo, "status", "--porcelain"], capture_output=True, text=True, check=True).stdout
        == ""
    )
    spec["exporters"]["extra"] = [
        {"name": "last", "argv": [sys.executable, "-c", "raise SystemExit(1)"]}
    ]  # macOS has no /bin/false
    (copied / "migrate.yaml").write_text(yaml.safe_dump(spec), encoding="utf-8")
    with pytest.raises(CockpitError, match="exporter last failed"):
        pack_migration.apply(load(str(copied / "pack.yaml")))
