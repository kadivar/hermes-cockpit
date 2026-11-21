# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The quiet branches of the kernel's commands and the dashboard's routes: a wrong shape that is refused, a record that
cannot be read, a board that is not there, a helper that fails. Each one has an outcome a human or a lane sees."""

import io
import json
import os
import sqlite3
import sys
import time

import pytest

from cockpitlib.errors import CockpitError, Conflict, NeedMigrate
from cockpitlib.pack import load

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _pack():
    return load(os.environ["COCKPIT_PACK"])


def _stdin(monkeypatch, text: str) -> None:
    monkeypatch.setattr(sys, "stdin", io.StringIO(text))


def _board_status(board, card) -> str:
    from cockpitlib.kanban import board_cards

    return {item["id"]: item["status"] for item in board_cards(board)}[card]


def _comments(board, card) -> list:
    from cockpitlib.kanban import db_path

    connection = sqlite3.connect(f"file:{db_path(board)}?mode=ro", uri=True)
    rows = [
        row[0]
        for row in connection.execute("select body from task_comments where task_id = ? order by created_at", (card,))
    ]
    connection.close()
    return rows


def _qa(ticket: str) -> str:
    from cockpitlib.paths import qa

    folder = os.path.join(qa(), ticket)
    os.makedirs(folder, exist_ok=True)
    return folder


# ---------------------------------------------------------------------------------------------------------------- cli


def test_parse_command_refuses_an_unknown_name():
    from cockpitlib.cli import parse_command

    assert parse_command(["doctor"]) == "doctor"
    with pytest.raises(CockpitError, match="unknown nope"):
        parse_command(["nope"])
    with pytest.raises(CockpitError, match="unknown $"):
        parse_command([])


def test_a_command_that_needs_a_migration_exits_with_its_own_code(bare, monkeypatch, capsys):
    from cockpitlib import cli

    def needs(_argv):
        raise NeedMigrate()

    monkeypatch.setitem(cli.COMMANDS, "doctor", needs)
    code = cli.main(["doctor"])
    assert code == NeedMigrate.exit_code == 2
    assert (
        'cockpit: no workspace is bound: run "cockpit init" (replacing an older pipeline: skill cockpit-migrate)'
        in capsys.readouterr().err
    )


def test_setup_command_prints_the_doctor_problems_and_fails(bare, monkeypatch, capsys):
    from cockpitlib import cli

    ran = []
    monkeypatch.setattr(cli, "do_setup", lambda data, rerender, seat: ran.append(("setup", rerender, seat)))
    monkeypatch.setattr(cli, "gateway_up", lambda: ran.append(("up",)))
    monkeypatch.setattr("cockpitlib.vault.init_vault", lambda: True)
    failed = [{"severity": "error", "message": line, "fix": ""} for line in ("FAIL gateway is down", "FAIL no board")]
    monkeypatch.setattr(cli, "doctor_report", lambda data: {"findings": failed})
    assert cli.cmd_setup(["--rerender"]) == 1
    assert ran == [("setup", True, ""), ("up",)]
    assert capsys.readouterr().err.strip().splitlines() == ["FAIL gateway is down", "FAIL no board"]


def test_plan_init_refuses_a_decision_passed_twice(capsys):
    from cockpitlib.cli import _plan_words

    assert _plan_words(["init", "TASK-1", "the plan", "go", "--decision", "wait"]) is None
    assert "pass the decision once" in capsys.readouterr().err
    assert _plan_words(["init", "TASK-1", "the plan", "--decision", "wait"]) == ["init", "TASK-1", "the plan", "wait"]


def test_migrate_plan_refuses_a_stray_argument(capsys):
    from cockpitlib.cli import cmd_migrate

    assert cmd_migrate(["plan", "extra"]) == 2
    assert "stray argument" in capsys.readouterr().err


def test_migrate_rollback_of_a_draft_name_uses_the_draft_rollback(bare, monkeypatch, capsys):
    from cockpitlib.cli import cmd_migrate

    monkeypatch.setattr("cockpitlib.migrate.rollback", lambda name: [f"removed {name}", "kept the legacy files"])
    assert cmd_migrate(["rollback", "draft-7"]) == 0
    assert capsys.readouterr().out.splitlines() == ["removed draft-7", "kept the legacy files"]


def test_resume_context_without_a_transcript_prints_nothing(bare, monkeypatch, capsys):
    from cockpitlib.cli import cmd_resume

    _stdin(monkeypatch, "  \n")
    monkeypatch.setattr("cockpitlib.resume.latest_transcript", lambda: "")
    assert cmd_resume([]) == 0
    assert capsys.readouterr().out == ""


def test_vault_import_refuses_a_stray_argument(capsys):
    from cockpitlib.cli import cmd_vault

    assert cmd_vault(["import", "extra"]) == 2
    assert "stray argument" in capsys.readouterr().err


def test_guard_without_a_readable_pack_still_judges_the_command(bare, monkeypatch):
    from cockpitlib import cli

    _stdin(monkeypatch, json.dumps({"command": "ls -la", "cwd": "/"}))
    monkeypatch.setattr("cockpitlib.fence.outside", lambda cwd=None: True)
    seen = []
    monkeypatch.setattr("cockpitlib.fence.guard_reason", lambda text, pack: seen.append(pack) or "")

    def missing():
        raise FileNotFoundError("no pack here")

    monkeypatch.setattr(cli, "_pack", missing)
    assert cli.cmd_guard([]) == 0
    assert seen and all(pack == {} for pack in seen)


def test_gate_in_the_background_prints_the_run_it_started(bare, monkeypatch, capsys):
    from cockpitlib.cli import cmd_gate

    asked = []
    monkeypatch.setattr(
        "cockpitlib.repo_gates.start_background",
        lambda pack, repo, baseline: asked.append((repo, baseline)) or "run-42",
    )
    assert cmd_gate(["api", "--background", "--baseline"]) == 0
    assert capsys.readouterr().out.strip() == "run-42" and asked == [("api", True)]


def test_record_refuses_a_flag_without_its_value(capsys):
    from cockpitlib.cli import cmd_record

    assert cmd_record(["start", "--session"]) == 2
    assert "--session takes a value" in capsys.readouterr().err
    assert cmd_record(["start", "--session", "--out"]) == 2


def test_record_start_passes_every_value_to_the_recorder(bare, monkeypatch, capsys):
    from cockpitlib import record
    from cockpitlib.cli import cmd_record

    seen = []

    def start(pack, session, out, record_id, on_screen, seconds, url):
        seen.append((session, out, record_id, on_screen, seconds, url))
        return {"ok": True, "pid": 7}

    monkeypatch.setattr(record, "start", start)
    code = cmd_record(
        [
            "start",
            "--session",
            "s1",
            "--out",
            "/tmp/x.webm",
            "--record-id",
            "r9",
            "--on-screen",
            "the total",
            "--max-seconds",
            "30",
            "--url-contains",
            "/report",
        ]
    )
    assert code == 0 and json.loads(capsys.readouterr().out) == {"ok": True, "pid": 7}
    assert seen == [("s1", "/tmp/x.webm", "r9", "the total", 30, "/report")]
    cmd_record(["start", "--session", "s1", "--out", "/tmp/x.webm"])
    assert seen[-1] == ("s1", "/tmp/x.webm", "", "", record.MAX_SECONDS, "")


def test_pace_reports_a_wrong_shape_in_its_error_and_exits_zero(bare, capsys):
    from cockpitlib.cli import cmd_pace

    assert cmd_pace(["--days", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["error"] == "--days takes a value"
    assert cmd_pace(["--json", "sometime"]) == 0
    assert json.loads(capsys.readouterr().out)["error"] == "stray argument sometime"


def test_pace_without_a_pack_says_so_and_exits_zero(bare, monkeypatch, capsys):
    from cockpitlib import cli

    def broken():
        raise RuntimeError("pack.yaml is not there")

    monkeypatch.setattr(cli, "_pack", broken)
    assert cli.cmd_pace(["--json"]) == 0
    assert json.loads(capsys.readouterr().out)["error"] == "pack: pack.yaml is not there"


def test_pace_without_json_prints_one_line_per_window(bare, monkeypatch, capsys):
    from cockpitlib.cli import cmd_pace

    window = {
        "name": "week",
        "used": 40,
        "ideal": 50,
        "verdict": "under",
        "projected": 80,
        "budget_per_hour": 1.5,
        "active_hours_left": 40,
    }
    monkeypatch.setattr(
        "cockpitlib.pace.pace", lambda pack, **kw: {"error": "the plan is a day old", "windows": [window]}
    )
    assert cmd_pace([]) == 0
    assert capsys.readouterr().out.splitlines() == [
        "pace: the plan is a day old",
        "week: 40% used, ideal 50%, under, 80% at reset, 1.5%/h for 40 h",
    ]


# --------------------------------------------------------------------------------------------------------------- acts


def test_blocking_a_scheduled_card_goes_through_ready_and_lands_blocked(bare):
    from cockpitlib import acts
    from cockpitlib.kanban import BoardWrites, place_card

    pack = _pack()
    card = place_card(pack["board"], "TASK-310: work", "worker-1", "ready")
    writes = BoardWrites(pack["board"])
    writes.schedule(card, "quota resets at noon")
    writes.flush()
    assert _board_status(pack["board"], card) == "scheduled"
    connection = acts._open(pack["board"])
    try:
        acts._status(connection, card, "blocked", "the login failed")
        connection.commit()
    finally:
        connection.close()
    assert _board_status(pack["board"], card) == "blocked"


def test_fail_login_survives_an_unreadable_record_and_a_missing_board(bare):
    from cockpitlib.acts import fail_login
    from cockpitlib.paths import watch_dir

    pack = _pack()
    os.makedirs(watch_dir(), exist_ok=True)
    path = os.path.join(watch_dir(), "login-blocks.json")
    open(path, "w", encoding="utf-8").write("{not json")
    result = fail_login(dict(pack, board="no-such-board"), "card-1", "the login page did not open")
    assert result == {"ok": True, "blocked": False, "reason": "the login page did not open", "card": "card-1"}
    assert json.loads(open(path, encoding="utf-8").read()) == ["card-1"]


def test_a_fail_mark_without_a_numbered_row_needs_a_recording(bare):
    from cockpitlib.acts import _require_fail_recordings

    folder = _qa("TASK-311")
    open(os.path.join(folder, "test-results.md"), "w", encoding="utf-8").write("the run ended ❌ somewhere\n")
    with pytest.raises(CockpitError, match="a fail needs one recording"):
        _require_fail_recordings("TASK-311")


def test_attach_evidence_skips_files_that_are_not_evidence(bare, monkeypatch):
    from cockpitlib import acts

    pack = _pack()
    folder = _qa("TASK-312")
    os.makedirs(os.path.join(folder, "evidences"))
    os.makedirs(os.path.join(folder, "created"))
    open(os.path.join(folder, "evidences", "notes.txt"), "w").write("not a picture")
    open(os.path.join(folder, "evidences", "1-total.png"), "wb").write(b"png")
    open(os.path.join(folder, "created", "README.md"), "w").write("not a record")
    open(os.path.join(folder, "created", "a.json"), "w").write(
        json.dumps({"link": "https://public.example.test/video/1"})
    )
    monkeypatch.setattr(acts, "_public_origin", lambda pack: "https://public.example.test")
    links = acts.attach_evidence(pack, "TASK-312")
    assert links == ["https://public.example.test/evidence/TASK-312/1-total.png", "https://public.example.test/video/1"]


@pytest.mark.parametrize("stored", ["{broken", "[1, 2]"])
def test_cleanup_settings_restores_nothing_from_an_unusable_snapshot(bare, stored):
    from cockpitlib.acts import cleanup_settings

    folder = _qa("TASK-313")
    open(os.path.join(folder, "settings-before.json"), "w", encoding="utf-8").write(stored)
    cleanup_settings("TASK-313")
    assert json.loads(open(os.path.join(folder, "settings.json"), encoding="utf-8").read()) == {}


def test_finish_intake_without_a_board_names_the_card(bare):
    from cockpitlib.acts import finish_intake

    with pytest.raises(CockpitError, match="no card card-9"):
        finish_intake(dict(_pack(), board="no-such-board"), "card-9", "the proposal")


def test_continue_needs_a_ticket_and_takes_one_evidence_path_as_text(env):
    from cockpitlib.acts import continue_ticket

    pack = _pack()
    with pytest.raises(CockpitError, match="no ticket"):
        continue_ticket(pack, "  ", "again")
    made = continue_ticket(pack, "TASK-314", "the divider is still white", evidence="/shots/page-2.png")
    assert made["ok"] is True
    assert "evidence: /shots/page-2.png" in open(made["path"], encoding="utf-8").read()


def test_a_lanes_rework_is_queued_when_the_board_is_closed_to_it(env, monkeypatch):
    from cockpitlib import acts
    from cockpitlib.store import read_json

    pack = _pack()

    def closed(*_args):
        raise CockpitError("kanban helper failed: child contexts cannot mutate tasks")

    monkeypatch.setattr(acts, "_rework_per_repo", closed)
    with pytest.raises(CockpitError, match="helper failed"):  # the human's own command sees the failure
        acts.continue_ticket(pack, "TASK-315", "CS: early returns", kind="rework", repos=["api"])
    monkeypatch.setenv("COCKPIT_LANE", "reviewer-1")
    made = acts.continue_ticket(pack, "TASK-315", "CS: early returns", kind="rework", repos=["api"], chain=False)
    assert made["queued"] is True and made["cards"] == [] and "is queued" in made["out"]
    waiting = read_json(acts._rework_queue_path())
    assert [(row["ticket"], row["repos"], row["chain"], row["instruction"]) for row in waiting] == [
        ("TASK-315", ["api"], False, "CS: early returns")
    ]


def test_grooming_is_proved_only_by_an_intent_with_the_rules_field_and_event(bare, monkeypatch):
    from cockpitlib import acts

    pack = dict(
        _pack(),
        grooming_rules=[
            {"name": "labelled", "intent": "pr-label", "field": "labels", "event": ""},
            {"name": "approved", "intent": "pr-review", "field": "", "event": "APPROVE"},
        ],
    )
    os.makedirs(os.path.dirname(acts.bumps_path()), exist_ok=True)
    acts._write(acts.bumps_path(), {"started": {"api#7": {"acts": []}, "api#8": {"acts": []}}})
    intents = [
        {"id": "i1", "type": "pr-label", "status": "published", "payload": {"repo": "api", "number": 7, "labels": []}},
        {
            "id": "i2",
            "type": "pr-review",
            "status": "published",
            "payload": {"repo": "api", "number": 7, "event": "COMMENT"},
        },
        {
            "id": "i3",
            "type": "pr-label",
            "status": "published",
            "payload": {"repo": "api", "number": 8, "labels": ["dependencies"]},
        },
        {
            "id": "i4",
            "type": "pr-review",
            "status": "published",
            "payload": {"repo": "api", "number": 8, "event": "APPROVE"},
        },
    ]
    monkeypatch.setattr("cockpitlib.intents.all_intents", lambda *a: intents)
    assert acts.derive_grooming(pack) == [("api#8", "labelled"), ("api#8", "approved")]
    stored = acts._read(acts.bumps_path())["started"]
    assert stored["api#7"]["acts"] == [] and stored["api#8"]["proved_by"] == {"labelled": "i3", "approved": "i4"}


def test_ordered_changes_reads_only_the_change_records(bare):
    from cockpitlib import acts

    folder = acts.changes_dir()
    os.makedirs(folder, exist_ok=True)
    open(os.path.join(folder, "notes.txt"), "w").write("not a record")
    acts._write(os.path.join(folder, "a.json"), {"repo": "api", "status": "relevant", "sha": "abc"})
    assert [row["sha"] for row in acts.ordered_changes()] == ["abc"]


def test_acknowledge_closed_skips_intents_without_a_ticket_and_other_kinds(bare, monkeypatch):
    from cockpitlib import acts

    intents = [
        {"id": "i1", "ticket": "", "type": "ticket-done", "status": "published", "payload": {}},
        {"id": "i2", "ticket": "TASK-316", "type": "tracker-comment", "status": "published", "payload": {}},
        {"id": "i3", "ticket": "TASK-316", "type": "ticket-done", "status": "published", "payload": {}},
    ]
    acked = []
    monkeypatch.setattr("cockpitlib.intents.all_intents", lambda *a: intents)
    monkeypatch.setattr("cockpitlib.outbox.ack", acked.append)
    assert acts.acknowledge_closed(_pack()) == ["i3"] and acked == ["i3"]
    assert acts._read(os.path.join(_qa("TASK-316"), "acknowledged.json"))["why"] == "ended without a pull request"


def test_a_blocked_treat_card_with_an_intent_is_past_its_plan(bare, monkeypatch):
    from cockpitlib import acts
    from cockpitlib.kanban import place_card

    pack = _pack()
    card = place_card(pack["board"], "TASK-317: treat api#4", "worker-1", "blocked")
    monkeypatch.setattr("cockpitlib.intents.all_intents", lambda *a: [{"id": "i1", "card_id": card}])
    assert acts._at_its_plan(pack, card) is False
    monkeypatch.setattr("cockpitlib.intents.all_intents", lambda *a: [])
    assert acts._at_its_plan(pack, card) is True


def test_folding_a_treat_card_that_cannot_be_closed_is_a_conflict(bare, monkeypatch):
    from cockpitlib import acts
    from cockpitlib.kanban import BoardWrites, place_card

    pack = _pack()
    card = place_card(pack["board"], "TASK-318: treat api#4", "worker-1", "blocked")
    monkeypatch.setattr(BoardWrites, "flush", lambda self: [False])
    with pytest.raises(Conflict, match=f"already open: card {card}"):
        acts._fold_treat(pack, "TASK-318", "api", 4, card, [{"id": 1, "body": "nit"}])
    assert _board_status(pack["board"], card) == "blocked"


def test_went_is_false_without_a_board_or_a_comments_table(bare, monkeypatch):
    from cockpitlib import acts

    pack = _pack()
    assert acts._went(dict(pack, board="no-such-board"), "card-1") is False

    class Broken:
        closed = False

        def execute(self, *_a):
            raise sqlite3.OperationalError("no such table: task_comments")

        def close(self):
            self.closed = True

    board = Broken()
    monkeypatch.setattr(acts, "_open", lambda slug: board)
    assert acts._went(pack, "card-1") is False and board.closed is True


def test_diagnosis_cards_keep_an_order_when_the_board_cannot_be_read(bare, monkeypatch):
    from cockpitlib import acts

    pack = dict(_pack(), board="no-such-board")
    index = {
        "no-such-board": {
            "c-a": {"kind": "ci", "ticket": "TASK-319", "key": "abcdef123:build"},
            "c-b": {"kind": "ci", "ticket": "TASK-319", "key": "abcdef123:lint"},
            "c-c": {"kind": "ci", "ticket": "TASK-999", "key": "abcdef123:lint"},
        }
    }
    monkeypatch.setattr("cockpitlib.kanban._index", lambda: index)
    assert acts._diagnosis_cards(pack, "TASK-319", "abcdef1234567") == ["c-b", "c-a"]


def test_a_failed_session_command_of_the_pack_is_an_error(bare, monkeypatch):
    from cockpitlib import acts, slots

    class Provider:
        def __init__(self, pack):
            pass

        def run(self, name, slot, ticket, words=None):
            return {"state": "failed", "tail": "browser did not stop"}

    monkeypatch.setattr(slots, "CommandProvider", Provider)
    pack = dict(_pack(), slots={"session": {"close": ["stop-browser"]}})
    with pytest.raises(CockpitError, match="session close failed: browser did not stop"):
        acts._session_command(pack, "close", 1, "TASK-320")


def test_handoff_stops_the_humans_browser_and_gives_the_slot_to_the_named_lane(bare, monkeypatch):
    from cockpitlib import acts, slots

    stopped = []
    monkeypatch.setattr(slots, "read_owner", lambda number: "human")
    monkeypatch.setattr(slots, "read_ticket", lambda number: "")
    monkeypatch.setattr(slots, "_read_runtime", lambda number: {"browser": 4321})
    monkeypatch.setattr(slots, "_stop_pid", stopped.append)
    owners = []
    monkeypatch.setattr(slots, "write_owner", lambda number, owner: owners.append((number, owner)))
    monkeypatch.setattr(slots, "clear_release_claim", lambda number: None)
    assert acts.session_handoff(_pack(), "2", "lane:worker-2") == "handoff 2 lane:worker-2"
    assert stopped == [4321] and owners == [(2, "lane:worker-2")]


# --------------------------------------------------------------------------------------------------------------- chat


def test_a_coding_provider_that_is_not_a_table_or_climbs_out_gives_no_transcripts(bare, monkeypatch):
    from cockpitlib import chat

    monkeypatch.setattr(chat, "_providers", lambda: {"coding": "claude -p"})
    assert chat._coding_spec() == ([], "")
    monkeypatch.setattr(
        chat,
        "_providers",
        lambda: {"coding": {"command": ["claude", "-p"], "transcript_glob": "{root}/../elsewhere/*.jsonl"}},
    )
    assert chat._coding_spec() == (["claude", "-p"], "")
    monkeypatch.setattr(
        chat, "_providers", lambda: {"coding": {"command": ["claude"], "transcript_glob": "runs/{ticket}/*.jsonl"}}
    )
    assert chat._pattern("TASK-1") == ""  # a glob that does not start at the root or at / names no folder


def test_the_chat_runs_the_command_the_environment_names(monkeypatch):
    from cockpitlib import chat

    monkeypatch.setenv("COCKPIT_CHAT_ARGV", "talk  --model big")
    assert chat._argv("TASK-1") == ["talk", "--model", "big"]


def test_the_chat_child_says_why_its_command_did_not_start_and_exits_127(monkeypatch, tmp_path, capfd):
    """The forked side of a terminal: in its folder, with the fork's name, and an exec that fails is told on its stderr."""
    import pty

    from cockpitlib import chat

    class Exited(Exception):
        pass

    def leave(code):
        raise Exited(code)

    def no_such(name, argv):
        raise FileNotFoundError(2, "No such file or directory", name)

    with monkeypatch.context() as patch:
        patch.chdir(os.getcwd())
        patch.setenv("TERM", "dumb")
        patch.setenv("COCKPIT_FORK_FROM", "")
        patch.setenv("CHAT_EXTRA", "")
        patch.setattr(pty, "fork", lambda: (0, -1))
        patch.setattr(os, "execvp", no_such)
        patch.setattr(os, "_exit", leave)
        with pytest.raises(Exited) as left:
            chat.Term(["no-such-tool", "--chat"], str(tmp_path), 80, 24, fork="session-1", env={"CHAT_EXTRA": "yes"})
        assert left.value.args == (127,)
        assert os.path.realpath(os.getcwd()) == os.path.realpath(str(tmp_path))
        assert (os.environ["TERM"], os.environ["COCKPIT_FORK_FROM"], os.environ["CHAT_EXTRA"]) == (
            "xterm-256color",
            "session-1",
            "yes",
        )
    assert "No such file or directory" in capfd.readouterr().err


def _bare_term(fd, pid=999999):
    from cockpitlib import chat

    term = object.__new__(chat.Term)
    term.alive, term.fd, term.pid = True, fd, pid
    return term


def _closed_fd() -> int:
    read, write = os.pipe()
    os.close(read)
    os.close(write)
    return read


def test_resizing_a_terminal_whose_descriptor_is_gone_does_not_raise():
    term = _bare_term(_closed_fd())
    assert term.resize(120, 40) is None and term.alive is True


def test_killing_a_terminal_whose_process_cannot_be_signalled_still_ends_it(monkeypatch):
    signals = []

    def refuse(pid, sig):
        signals.append(sig)
        raise ProcessLookupError()

    clock = iter(range(0, 1000, 3))
    term = _bare_term(_closed_fd())
    with monkeypatch.context() as patch:
        patch.setattr(os, "kill", refuse)
        patch.setattr(time, "time", lambda: next(clock))
        patch.setattr(time, "sleep", lambda _s: None)
        patch.setattr(type(term), "_still_running", lambda self: True)
        term.kill()
    import signal

    assert signals == [signal.SIGHUP, signal.SIGTERM, signal.SIGKILL] and term.alive is False


def test_a_transcripts_ticket_is_its_folder_when_no_key_stands_there(bare, monkeypatch):
    from cockpitlib import chat
    from cockpitlib.paths import root

    monkeypatch.setattr(
        chat,
        "_providers",
        lambda: {"coding": {"command": ["claude"], "transcript_glob": "{root}/runs/{ticket}/*.jsonl"}},
    )
    base = os.path.join(root(), "runs")
    assert chat.ticket_of_transcript(os.path.join(base, "TASK-12-api", "a.jsonl")) == "TASK-12"
    assert chat.ticket_of_transcript(os.path.join(base, "scratch", "a.jsonl")) == "scratch"
    assert chat.ticket_of_transcript("/elsewhere/notes/a.jsonl") == "notes"


def test_lane_sessions_come_from_the_boards_cards_and_a_failure_shows_none(bare, monkeypatch):
    from cockpitlib import chat

    assert chat._lane_sessions() == []  # the pack names no lane transcripts
    monkeypatch.setattr(chat, "_lane_glob", lambda: "/somewhere/{card}/*.jsonl")
    seen = []
    monkeypatch.setattr(
        "cockpitlib.lane_transcripts.sessions", lambda cards: seen.append(cards) or [{"id": "lane-1", "mtime": 5}]
    )
    assert chat._lane_sessions() == [{"id": "lane-1", "mtime": 5}] and isinstance(seen[0], list)

    def broken(cards):
        raise RuntimeError("the tool moved its folder")

    monkeypatch.setattr("cockpitlib.lane_transcripts.sessions", broken)
    assert chat._lane_sessions() == []


def test_a_message_block_that_is_not_a_table_is_skipped():
    from cockpitlib.chat import _message_entries

    found = _message_entries(
        {"timestamp": "t1", "message": {"content": ["loose text", {"type": "thinking", "thinking": "weigh it"}]}}
    )
    assert [(row["kind"], row["text"]) for row in found] == [("thinking", "weigh it")]


# ------------------------------------------------------------------------------------------------------------- egress


def test_the_legacy_reading_follows_a_cd_and_skips_an_empty_segment():
    from cockpitlib.egress import _legacy_targets

    assert _legacy_targets("cd /srv/app ; ; echo x > out.txt") == ["/srv/app/out.txt"]


def test_an_escaped_operator_is_masked_like_a_quoted_one():
    from cockpitlib.egress import _mask

    assert ">" not in _mask(r"echo a\>b") and ">" in _mask("echo a > b")


def test_a_line_continued_past_the_end_of_the_text_is_still_read():
    from cockpitlib.egress import _read_lines

    entries = _read_lines("echo one \\")
    assert [tokens for tokens, _raw, _inner in entries] == [["echo", "one"]]


def test_git_is_found_behind_a_wrapper():
    from cockpitlib.egress import _git_verb

    verb, rest = _git_verb(["exec", "nohup", "git", "push", "origin", "main"])
    assert verb == "push" and rest[-2:] == ["origin", "main"]


def test_a_variable_the_line_sets_itself_is_not_expanded(monkeypatch):
    from cockpitlib.egress import _expand

    monkeypatch.setenv("TARGET", "/srv/data")
    assert _expand("$TARGET/file", redefined=("TARGET",)) == "$TARGET/file"
    assert _expand("$TARGET/file") == "/srv/data/file"


def test_an_unresolved_write_is_inside_no_root_and_refused_for_a_worker(bare, monkeypatch):
    from cockpitlib import egress

    target = egress.UNRESOLVED + "$OUT/report.txt"
    assert egress._inside(target, ["/"]) is False
    monkeypatch.setenv("COCKPIT_LANE", "worker-1")
    assert egress._worker_write("echo x > $OUT/report.txt", _pack(), targets=[target]) == "blocked"
    assert "a write whose folder or variable this line changes ($OUT/report.txt)" in egress._WHY.text


def test_a_reviewers_write_is_not_noted_as_a_read(bare, monkeypatch):
    from cockpitlib import egress

    noted = []
    monkeypatch.setenv("COCKPIT_LANE", "reviewer-1")
    monkeypatch.setattr("cockpitlib.skill_log.current_ticket", lambda: "TASK-330")
    monkeypatch.setattr("cockpitlib.outbox.note_read", lambda ticket, where: noted.append((ticket, where)))
    egress._note_review_read("write_file", {"path": "src/a.py", "line": 4})
    assert noted == []
    egress._note_review_read("read_file", {"path": "src/a.py", "line": 4})
    assert noted == [("TASK-330", "src/a.py:4")]


def test_a_tool_input_that_is_neither_text_nor_a_table_runs_nothing():
    from cockpitlib.egress import _exec_texts

    assert _exec_texts("terminal", 5) == [] and _exec_texts("terminal", "ls") == ["ls"]


def test_the_browser_is_not_lent_when_the_board_cannot_say_so(bare, monkeypatch):
    from cockpitlib import egress
    from cockpitlib.kanban import db_path

    assert egress._card_says_lent({}, "TASK-331") is False and egress._card_says_lent(_pack(), "") is False
    monkeypatch.setattr(
        "cockpitlib.kanban.board_cards", lambda slug: [{"id": "c1", "ticket": "TASK-331", "body": "plain"}]
    )
    assert egress._card_says_lent({"board": "ghost"}, "TASK-331") is False  # no board file
    path = db_path("ghost")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    connection = sqlite3.connect(path)
    connection.execute("create table tasks (id text primary key)")
    connection.commit()
    connection.close()
    assert egress._card_says_lent({"board": "ghost"}, "TASK-331") is False  # an older board: no comments table
    open(path, "wb").write(b"this is not a database, only bytes" * 40)
    assert egress._card_says_lent({"board": "ghost"}, "TASK-331") is False  # an unreadable board


def test_a_loan_falls_back_to_its_own_hours_when_the_setting_is_missing(bare, monkeypatch):
    from cockpitlib import egress

    monkeypatch.setattr("cockpitlib.settings.load", lambda pack: {})
    now = int(time.time())
    assert egress._loan_expired({"at": now - 3600, "hours": 2}, _pack()) is False
    assert egress._loan_expired({"at": now - 3 * 3600, "hours": 2}, _pack()) is True
    assert egress._loan_expired({"at": now}, _pack()) is True  # no duration anywhere: not lent


# ---------------------------------------------------------------------------------------------- routes and the screen


def _client():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from dashboard.cockpit.router import router

    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def test_a_stored_login_in_a_text_is_a_secret_and_an_empty_text_is_not(monkeypatch):
    from dashboard.cockpit.routes import pages as routes

    monkeypatch.setattr("cockpitlib.vault._items", lambda: ["loose", {"secret": "hunter2-long", "otp": ""}])
    assert routes._vault_secret("") is False
    assert routes._vault_secret("nothing stored stands here") is False
    assert routes._vault_secret("password: hunter2-long") is True


def test_a_tickets_chat_record_is_named_after_it(bare):
    from cockpitlib.paths import chat_dir
    from dashboard.cockpit.routes import pages as routes

    assert routes._chat_path("TASK-340") == os.path.join(chat_dir(), "TASK-340.json")


def test_card_detail_is_empty_without_a_board_and_when_the_board_fails(bare, monkeypatch):
    from cockpitlib.kanban import place_card
    from dashboard.cockpit.routes import pages as routes

    pack = _pack()
    assert routes._card_detail(dict(pack, board="no-such-board"), "c1") == routes._empty_card("c1")
    card = place_card(pack["board"], "TASK-341: work", "worker-1", "ready")

    def locked(connection, card_id):
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr("cockpitlib.kanban.completion_summary", locked)
    assert routes._card_detail(pack, card) == routes._empty_card(card)


def test_apply_note_needs_its_id_echoed_and_reports_the_commit(bare, monkeypatch):
    client = _client()
    assert client.post("/apply-note", json={"id": "n1", "confirm": "other"}).status_code == 400
    monkeypatch.setattr(
        "cockpitlib.infra_note.apply",
        lambda pack, note: {"commit": "abcdef1234567890", "files": ["a", "b"], "push": "held"},
    )
    done = client.post("/apply-note", json={"id": "n1", "confirm": "n1"}).json()
    assert done["ok"] is True and done["out"] == "abcdef123 committed (2 file(s)); its push is held"

    def refused(pack, note):
        raise CockpitError("the patch does not apply")

    monkeypatch.setattr("cockpitlib.infra_note.apply", refused)
    answer = client.post("/apply-note", json={"id": "n1", "confirm": "n1"})
    assert answer.status_code == 400 and answer.json()["detail"] == "the patch does not apply"


def test_a_reply_that_stopped_part_way_is_not_ok(bare, monkeypatch):
    client = _client()
    monkeypatch.setattr("cockpitlib.gate.reply", lambda pack, text: ["1 published", "stopped here: 2 is held"])
    assert client.post("/reply", json={"text": "publish all"}).json() == {
        "ok": False,
        "lines": ["1 published", "stopped here: 2 is held"],
    }
    monkeypatch.setattr("cockpitlib.gate.reply", lambda pack, text: ["1 published"])
    assert client.post("/reply", json={"text": "publish 1"}).json()["ok"] is True


def test_an_uploaded_text_over_the_limit_is_refused(bare, monkeypatch):
    from cockpitlib.paths import qa
    from dashboard.cockpit.routes import pages as routes

    monkeypatch.setattr(routes, "MAX_BYTES", 8)
    answer = _client().post("/upload", json={"ticket": "TASK-342", "name": "note.txt", "text": "more than eight bytes"})
    assert answer.status_code == 400 and answer.json()["detail"] == "file is over 40 MB"
    assert not os.path.exists(os.path.join(qa(), "TASK-342", "note.txt"))


def test_reopening_a_halted_ticket_is_a_conflict(bare, monkeypatch):
    def halted(*_a, **_k):
        raise Conflict("TASK-343 is halted")

    monkeypatch.setattr("cockpitlib.acts.continue_ticket", halted)
    answer = _client().post("/reopen-flow", json={"ticket": "TASK-343", "prompt": "again"})
    assert answer.status_code == 409 and answer.json()["detail"] == "TASK-343 is halted"


def test_an_intents_diff_without_a_checkout_says_so_and_another_failure_is_refused(env, monkeypatch):
    from cockpitlib.outbox import create

    row = create(
        _pack(), "TASK-344", "push-branch", "c1", "ship", {"repo": "api", "branch": "work/cov-344", "number": 1}
    )
    client = _client()

    def none_yet(pack, intent, rows, mode):
        raise CockpitError("no worktree for TASK-344 in api")

    monkeypatch.setattr("cockpitlib.diffs.intent_diff", none_yet)
    pane = client.get("/diff", params={"id": row["id"]}).json()
    assert (pane["diff"], pane["note"], pane["ticket"], pane["repo"]) == (
        "",
        "no worktree for TASK-344 in api",
        "TASK-344",
        "api",
    )

    def broken(pack, intent, rows, mode):
        raise CockpitError("the repo has no such commit")

    monkeypatch.setattr("cockpitlib.diffs.intent_diff", broken)
    answer = client.get("/diff", params={"id": row["id"], "mode": "origin"})
    assert answer.status_code == 400 and answer.json()["detail"] == "the repo has no such commit"
    sideways = client.get("/diff", params={"id": row["id"], "mode": "sideways"})
    assert sideways.status_code == 400 and "a diff is asked as one of base, origin" in sideways.json()["detail"]


def test_an_ide_that_does_not_start_is_a_server_error(bare, monkeypatch):
    from cockpitlib.paths import qa

    def no_ide(*_a, **_k):
        raise CockpitError("the pack names no IDE command")

    monkeypatch.setattr("cockpitlib.ops.ide_open", no_ide)
    monkeypatch.setattr("cockpitlib.ops.ide_launch", no_ide)
    client = _client()
    opened = client.post("/open-ide", json={})
    assert opened.status_code == 500 and opened.json()["detail"] == "the pack names no IDE command"
    note = os.path.join(_qa("TASK-345"), "plan.md")
    open(note, "w", encoding="utf-8").write("Brief\n")
    assert note.startswith(qa())
    one = client.post("/open-file", json={"path": note})
    assert one.status_code == 500 and one.json()["detail"] == "the pack names no IDE command"


def test_the_standup_draft_names_the_day_it_counts_from(bare, monkeypatch):
    from cockpitlib.paths import platform_dir

    monkeypatch.setattr("cockpitlib.setup.standup_enabled", lambda pack: True)
    os.makedirs(platform_dir(), exist_ok=True)
    open(os.path.join(platform_dir(), "standup.md"), "w", encoding="utf-8").write(
        "Standup\nSince Monday 09:00 \nSince never\n- merged api#4\n"
    )
    answer = _client().get("/standup").json()
    assert (answer["since"], answer["status"], answer["items"]) == (
        "Monday 09:00",
        "draft",
        1,
    )  # the first Since line counts


def test_lane_runs_skips_a_log_that_cannot_be_read(bare):
    from cockpitlib.kanban import db_path, place_card

    pack = _pack()
    card = place_card(pack["board"], "TASK-346: work", "worker-1", "ready")
    logs = os.path.join(os.path.dirname(db_path(pack["board"])), "logs")
    os.makedirs(logs, exist_ok=True)
    open(os.path.join(logs, f"{card}.log"), "w").write("started\n")
    os.symlink(os.path.join(logs, "gone-target"), os.path.join(logs, "dangling.log"))
    runs = _client().get("/lane-runs").json()
    rows = runs["runs"] if isinstance(runs, dict) else runs
    assert [row["card"] for row in rows] == [card] and rows[0]["title"] == "TASK-346: work"


def test_new_comments_are_one_inbox_row_per_pull_request(monkeypatch):
    from dashboard.cockpit import payload

    monkeypatch.setattr(
        "cockpitlib.pr_watch.inbox_rows",
        lambda: [{"repo": "api", "number": 4, "ticket": "TASK-347", "new": [{"id": 1}, {"id": 2}]}],
    )
    rows = payload._comment_rows()
    assert [(row["kind"], row["id"], row["ticket"], row["summary"]) for row in rows] == [
        ("new comments", "api#4", "TASK-347", "2 new comments on api#4")
    ]


def test_open_cards_are_counted_per_lane_and_an_unassigned_one_is_left_out(monkeypatch):
    from dashboard.cockpit import payload

    status = sorted(payload.OPEN)[0]
    monkeypatch.setattr(
        payload,
        "_cards",
        lambda slug: [
            {"id": "a", "lane": "worker-1", "status": status},
            {"id": "b", "lane": "", "status": status},
            {"id": "c", "lane": "worker-1", "status": status},
            {"id": "d", "lane": "tester-1", "status": "done"},
        ],
    )
    assert payload._card_counts("any") == {"worker-1": 2}


# -------------------------------------------------------------------------------------------------------------- setup


def test_the_analyst_seat_has_a_name_even_when_the_pack_counts_none(monkeypatch):
    from cockpitlib import setup

    def no_counts(pack):
        raise KeyError("seats")

    monkeypatch.setattr("cockpitlib.lanes.seats_from", no_counts)
    assert setup._analyst_seat({"name": "acme"}) == "analyst"


def test_desktop_refresh_needs_the_entry_and_survives_a_file_it_cannot_stat(tmp_path):
    from cockpitlib.setup import desktop_refresh

    assert desktop_refresh(str(tmp_path / "plugin")) is False
    base = tmp_path / "plugin" / "desktop"
    (base / "src").mkdir(parents=True)
    entry = base / "plugin.js"
    entry.write_text("// bundle\n")
    os.utime(entry, (1000, 1000))
    os.symlink(str(base / "src" / "gone.js"), str(base / "src" / "link.js"))
    assert desktop_refresh(str(tmp_path / "plugin")) is False  # only an unreadable file beside it: nothing newer
    (base / "src" / "panel.js").write_text("// newer\n")
    assert desktop_refresh(str(tmp_path / "plugin")) is True and os.path.getmtime(entry) > 1000


def test_an_unreadable_desktop_marker_is_not_a_stale_copy(bare, tmp_path):
    from cockpitlib.paths import hermes_home
    from cockpitlib.setup import desktop_copy_stale

    root = tmp_path / "cockpit"
    (root / "desktop").mkdir(parents=True)
    (root / "desktop" / "plugin.js").write_text("// bundle\n")
    marker = os.path.join(hermes_home(), "desktop-plugins", "cockpit", ".hermes-package.json")
    os.makedirs(os.path.dirname(marker))
    open(marker, "w").write("{not json")
    assert desktop_copy_stale(str(root)) == ""
    open(marker, "w").write(json.dumps({"sourceMtimeMs": 1}))
    assert "stale copy" in desktop_copy_stale(str(root))


def test_the_resume_hook_is_added_to_a_config_that_does_not_end_in_a_newline(monkeypatch):
    from cockpitlib import setup

    merged = setup._ensure_resume("model: big")
    assert merged.startswith("model: big\nhooks:\n  pre_llm_call:\n    - command: ") and merged.endswith(
        "resume-context.sh\n"
    )
    assert setup._ensure_resume(merged) == merged
    assert setup._ensure_resume(merged.rstrip("\n")) == merged  # registered already: only the newline is put back


def test_the_plugin_is_enabled_before_the_next_key_of_the_plugins_block():
    from cockpitlib.setup import _ensure_plugin

    text = "plugins:\n  enabled:\n    - other\n  disabled:\n    - noisy\nmodel: big\n"
    assert (
        _ensure_plugin(text)
        == "plugins:\n  enabled:\n    - other\n    - cockpit\n  disabled:\n    - noisy\nmodel: big\n"
    )


def test_a_watcher_the_pack_turned_off_is_removed_from_hermes(bare, monkeypatch):
    from cockpitlib import setup

    pack = _pack()
    ran = []

    class Done:
        returncode, stdout, stderr = 0, "", ""

    monkeypatch.setattr(setup.shutil, "which", lambda name: "/opt/hermes/bin/hermes")
    monkeypatch.setattr(setup, "registered_jobs", lambda pack: [])
    monkeypatch.setattr(
        setup,
        "cron_plan",
        lambda jobs, pack: [
            {"op": "remove", "name": "standup", "id": "job-7", "schedule": "0 9 * * *", "script": "standup.sh"}
        ],
    )
    monkeypatch.setattr(setup.subprocess, "run", lambda argv, **kw: ran.append(argv) or Done())
    setup._register_crons(pack)
    assert len(ran) == 1 and ran[0][0] == "/opt/hermes/bin/hermes" and ran[0][-3:] == ["cron", "remove", "job-7"]


def test_a_missing_cursor_hooks_file_means_the_hook_is_not_installed(tmp_path):
    from cockpitlib.setup import cursor_hook_command, cursor_hook_installed

    path = tmp_path / "hooks.json"
    assert cursor_hook_installed(str(path)) is False
    path.write_text("{not json")
    assert cursor_hook_installed(str(path)) is False
    path.write_text(json.dumps({"hooks": {"preToolUse": [{"command": cursor_hook_command()}]}}))
    assert cursor_hook_installed(str(path)) is True


def test_linked_lanes_are_the_seats_in_force_when_the_counts_cannot_be_read(bare, monkeypatch):
    from cockpitlib import setup

    def broken(pack):
        raise RuntimeError("seats is not a table")

    monkeypatch.setattr("cockpitlib.lanes.seats_from", broken)
    assert setup._linked_lanes(_pack(), ["worker-1", "tester-1", "worker-1"]) == ["worker-1", "tester-1"]


# ------------------------------------------------------------------------------------------------------- housekeeping


def _memory_board(*statements):
    connection = sqlite3.connect(":memory:")
    for statement in statements:
        connection.execute(statement)
    connection.commit()
    return connection


def test_a_tester_sent_back_for_a_missing_video_is_told_how_to_record_it(bare, monkeypatch):
    from cockpitlib import housekeeping
    from cockpitlib.kanban import place_card

    pack = dict(_pack(), testflow={"send_back": 0})
    card = place_card(pack["board"], "TASK-350: test", "tester-1", "blocked")
    row = {"id": card, "status": "blocked", "assignee": "tester-1", "not_ready": ["3·video"], "blocked_at": 0}
    monkeypatch.setattr("cockpitlib.kanban.open_card_rows", lambda slug, pack: [row])
    monkeypatch.setattr(housekeeping, "_owned_cards", lambda pack: {})
    monkeypatch.setattr("cockpitlib.test_flow.video_refusal", lambda pack, card, lane: f"Record row 3 again ({lane}).")
    assert housekeeping._send_back_testers(pack) == 1
    said = _comments(pack["board"], card)[-1]
    assert "Not ready for the human's review: 3 video." in said and said.endswith("Record row 3 again (tester-1).")
    assert _board_status(pack["board"], card) in ("ready", "todo")


def test_a_stored_list_that_is_not_a_list_reads_as_empty(tmp_path):
    from cockpitlib.housekeeping import _load_list

    path = tmp_path / "cleared.json"
    path.write_text(json.dumps({"c1": True}))
    assert _load_list(str(path)) == []
    path.write_text(json.dumps(["c1"]))
    assert _load_list(str(path)) == ["c1"]


def test_a_shared_login_is_not_the_lanes_own_account(monkeypatch):
    from cockpitlib import housekeeping

    rows = [
        {"lane": "tester-1", "email": "t1@example.test"},
        {"lane": "", "email": "shared@example.test"},
        {"lane": "tester-2", "email": "t2@example.test"},
    ]
    monkeypatch.setattr("cockpitlib.vault.login_metadata", lambda lane: rows)
    assert housekeeping._own_emails("tester-1") == {"t1@example.test"}


def test_session_text_and_login_blocks_read_an_older_board_without_comment_bodies(monkeypatch):
    from cockpitlib import housekeeping

    monkeypatch.setattr(housekeeping, "block_reason", lambda connection, card: "")
    board = _memory_board(
        "create table tasks (id text, status text, body text)",
        "create table task_comments (id text)",
        "insert into tasks values ('c1', 'blocked', 'already in another session')",
    )
    assert housekeeping._card_session_text(board, "c1", {"id", "status", "body"}) == "already in another session"
    assert housekeeping._credential_cards(board, {"id", "status", "body"}) == []


def test_a_login_block_said_in_a_comment_is_found(monkeypatch):
    from cockpitlib import housekeeping

    monkeypatch.setattr(housekeeping, "block_reason", lambda connection, card: "")
    board = _memory_board(
        "create table tasks (id text, status text)",
        "create table task_comments (task_id text, body text)",
        "insert into tasks values ('c1', 'blocked')",
        "insert into tasks values ('c2', 'ready')",
        "insert into task_comments values ('c1', 'CREDENTIALS NEEDED staging admin')",
        "insert into task_comments values ('c1', 'CREDENTIALS NEEDED staging admin, still')",
        "insert into task_comments values ('c2', 'CREDENTIALS NEEDED earlier')",
    )
    assert housekeeping._credential_cards(board, {"id", "status"}) == ["c1"]


def test_other_session_blocks_are_left_on_a_board_without_lanes(bare, monkeypatch):
    from cockpitlib import housekeeping

    monkeypatch.setattr(housekeeping, "_db", lambda pack: _memory_board("create table tasks (id text, status text)"))
    assert housekeeping._answer_other_session(_pack()) == 0


def test_a_plugins_stale_rate_limited_card_is_left_to_the_plugin(bare, monkeypatch):
    from cockpitlib import housekeeping
    from cockpitlib.kanban import place_card

    pack = _pack()
    card = place_card(pack["board"], "TASK-351: work", "worker-1", "ready")
    monkeypatch.setattr(housekeeping, "_stale_failures", lambda connection, columns, moment: [card])
    monkeypatch.setattr(housekeeping, "_hand_over", lambda owned, found: True)
    assert housekeeping.unstrand(pack) == "0" and _board_status(pack["board"], card) in ("ready", "todo")


def test_a_plugins_guarded_card_is_left_to_the_plugin(bare, monkeypatch):
    from cockpitlib import housekeeping

    board = _memory_board(
        "create table tasks (id text, assignee text, status text)",
        "create table task_events (id integer primary key, task_id text, kind text, payload text, created_at integer)",
        "insert into tasks values ('c1', 'worker-1', 'ready')",
        "insert into task_events (task_id, kind, payload, created_at) values ('c1', 'respawn_guarded', 'active_pr', 100)",
    )
    monkeypatch.setattr(housekeeping, "_db", lambda pack: board)
    woken = []
    monkeypatch.setattr(housekeeping, "_hand_over", lambda owned, card: woken.append(card) or True)
    assert housekeeping.unguard(_pack(), now=100 + housekeeping.GUARD_SECONDS + 1) == "0" and woken == ["c1"]


def test_a_card_that_waited_for_a_push_carries_on_once_when_it_is_out(bare, monkeypatch):
    from cockpitlib import housekeeping
    from cockpitlib.kanban import place_card

    pack = _pack()
    card = place_card(pack["board"], "TASK-352: work", "worker-1", "blocked")
    monkeypatch.setattr(
        "cockpitlib.gate.publish_wait", lambda reason, card_id: {"open": [], "out": ["push api work/352"]}
    )
    assert housekeeping.unblock_published(pack) == "1"
    assert _comments(pack["board"], card)[-1] == "Published: push api work/352. Carry on with what waited for it."
    assert _board_status(pack["board"], card) in ("ready", "todo")
    assert len(housekeeping.published_seen()) == 1


# ---------------------------------------------------------------------------------------------------------------- ops


def test_a_moment_in_a_text_is_read_and_compared_in_utc():
    import datetime

    from cockpitlib import ops

    assert ops._stamp("nothing dated here") is None
    found = ops._stamp("merged at 2026-11-01T10:00:00Z by a human")
    assert found == datetime.datetime(2026, 11, 1, 10, 0, tzinfo=datetime.UTC)
    assert ops._since(None, found) is False
    assert ops._since(datetime.datetime(2026, 11, 1, 10, 0), found) is True  # a moment without a zone is UTC
    assert ops._since(datetime.datetime(2026, 11, 1, 9, 59), found) is False


def test_the_collection_reports_its_count_even_when_the_recorder_sweep_fails(bare, monkeypatch):
    from cockpitlib import ops, record, slots

    class Provider:
        def gc(self, idle, count):
            return [2]

    def no_folder(pack):
        raise OSError("recordings folder is gone")

    monkeypatch.setattr(slots, "provider_for", lambda name, pack: Provider())
    monkeypatch.setattr(record, "sweep", no_folder)
    assert ops.slot_gc(_pack()) == "slot-gc 1"


# -------------------------------------------------------------------------------------------------------------- gates


def test_a_gate_running_elsewhere_is_found_through_proc(monkeypatch, tmp_path):
    """A machine with /proc: the gate command counts only when its process works inside one of the checkouts."""
    from cockpitlib import repo_gates

    checkout = tmp_path / "wt" / "api"
    checkout.mkdir(parents=True)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    me = str(os.getpid())
    table = {
        "self": None,
        me: (b"make\0test\0", str(checkout)),
        "11": None,
        "12": (b"make\0test\0", str(elsewhere)),
        "13": (b"vim\0Makefile\0", str(checkout)),
    }
    real_isdir, real_listdir = os.path.isdir, os.listdir

    class Cmdline:
        def __init__(self, raw):
            self.raw = raw

        def read(self):
            return self.raw

    def opened(path, mode="r"):
        row = table[path.split(os.sep)[2]]
        if row is None:
            raise FileNotFoundError(path)
        return Cmdline(row[0])

    with monkeypatch.context() as patch:
        patch.setattr(os.path, "isdir", lambda path: True if path == "/proc" else real_isdir(path))
        patch.setattr(os, "listdir", lambda path: list(table) if path == "/proc" else real_listdir(path))
        patch.setattr(os, "readlink", lambda path: table[path.split(os.sep)[2]][1])
        patch.setattr(repo_gates, "open", opened, raising=False)
        assert (
            repo_gates._outside("make test", [str(checkout)]) is False
        )  # this process itself, another folder, another command
        table["14"] = (b"bash\0-c\0make test\0", str(checkout / "."))
        assert repo_gates._outside("make test", [str(checkout)]) is True


def test_ps_lines_without_a_pid_are_not_processes(monkeypatch):
    from cockpitlib import repo_gates

    class Done:
        stdout = "  41 make test\nUSER COMMAND\n42\n  43 bash -c make  test all\n"

    monkeypatch.setattr(repo_gates.subprocess, "run", lambda *a, **k: Done())
    assert repo_gates._ps_processes() == [(41, ["make", "test"]), (43, ["bash", "-c", "make  test all"])]


# -------------------------------------------------------------------------------------------------------------- slots


def test_reap_counts_a_process_that_is_gone_without_being_its_child(monkeypatch):
    from cockpitlib import slots

    with monkeypatch.context() as patch:
        patch.setattr(slots.os, "waitpid", lambda pid, flags: (0, 0))
        patch.setattr(slots, "_pid_alive", lambda pid: False)
        assert slots._reap(4242, 0.2) is True


def test_stop_pid_gives_up_quietly_when_the_process_ends_between_the_signals(monkeypatch):
    import signal

    from cockpitlib import slots

    sent = []

    def kill(pid, sig):
        sent.append(sig)
        if sig == signal.SIGKILL:
            raise ProcessLookupError()

    reaped = []
    with monkeypatch.context() as patch:
        patch.setattr(slots.os, "kill", kill)
        patch.setattr(slots, "_reap", lambda pid, timeout: reaped.append(pid) or False)
        assert slots._stop_pid("4242") is None
    assert sent == [signal.SIGTERM, signal.SIGKILL] and reaped == [4242]


def test_a_dev_server_whose_command_comes_out_empty_is_not_started(monkeypatch):
    from cockpitlib import slots

    class Provider:
        def __init__(self, pack):
            pass

        def argv(self, words, slot):
            return []

    started = []
    monkeypatch.setattr(slots, "CommandProvider", Provider)
    monkeypatch.setattr(slots.subprocess, "Popen", lambda *a, **k: started.append(a))
    record = slots.start_slot_runtime({"dev_servers": [["npm", "run", "dev"]]}, 1)
    assert started == [] and record["servers"] == [] and record["browser"] is None


def test_a_bringup_whose_command_is_refused_ends_failed_with_the_reason_in_its_log(bare, monkeypatch):
    from cockpitlib import slots

    class Provider:
        def has(self, verb):
            return verb == "up"

        def run(self, verb, slot, ticket=""):
            raise CockpitError("the pack's up command is not executable")

    monkeypatch.setattr(slots, "provider_for", lambda name, pack: Provider())
    os.makedirs(slots.state_dir(1), exist_ok=True)
    assert slots.bringup(1, _pack()) == "failed"
    assert (
        "the pack's up command is not executable"
        in open(os.path.join(slots.state_dir(1), "bringup.log"), encoding="utf-8").read()
    )


def test_a_dead_holders_lock_is_cleared_and_taken(bare, monkeypatch):
    from cockpitlib import slots

    path = slots._lock_path(2)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    open(path, "w").write("0:1")
    assert slots._acquire(2) is True  # the dead holder's lock went, this one took it
    assert open(path).read() == slots._lock_token()
    open(path, "w").write("0:1")
    real_remove = os.remove

    def stuck(target):
        raise PermissionError(target)

    with monkeypatch.context() as patch:
        patch.setattr(slots.os, "remove", stuck)
        assert slots._holder(2) is None  # a lock that cannot be removed still has no live holder
    assert os.remove is real_remove


def test_a_release_claim_that_changed_under_the_lock_frees_nothing(bare, monkeypatch):
    import contextlib

    from cockpitlib import slots

    freed = []

    class Provider:
        def free(self, slot):
            freed.append(slot)

    claims = iter(["TASK-360", ""])
    monkeypatch.setattr(slots, "free_slots", lambda count: [])
    monkeypatch.setattr(slots, "provider_for", lambda name, pack: Provider())
    monkeypatch.setattr(slots, "_open_card_tickets", lambda pack: set())
    monkeypatch.setattr(slots, "read_ticket", lambda slot: "TASK-360")
    monkeypatch.setattr(slots, "release_claim_of", lambda slot: next(claims))
    monkeypatch.setattr(slots, "read_owner", lambda slot: "lane:worker-1")
    monkeypatch.setattr(slots, "last_active", lambda slot: 0)
    monkeypatch.setattr(slots, "_held", lambda slot: contextlib.nullcontext())
    assert slots.hand_over_release_slots(_pack(), 1, "TASK-361") == [] and freed == []


# ------------------------------------------------------------------------------------------------------------- doctor


def test_a_provider_plugin_without_a_readable_manifest_declares_no_dependencies(tmp_path):
    from cockpitlib.doctor import _dependencies

    assert _dependencies({"path": str(tmp_path / "missing")}) == []
    (tmp_path / "plugin.yaml").write_text("- just\n- a list\n")
    assert _dependencies({"path": str(tmp_path)}) == []
    (tmp_path / "plugin.yaml").write_text("python_dependencies:\n  - httpx>=0.27\npip_dependencies: [' rich ']\n")
    assert _dependencies({"path": str(tmp_path)}) == ["httpx>=0.27", "rich"]


def test_doctor_names_each_thing_that_is_wrong(bare, monkeypatch):
    from cockpitlib import doctor
    from cockpitlib.lanes import seats_from

    pack = _pack()
    lane = next(name for names in seats_from(pack).values() for name in names)
    folder = doctor.profile_dir(lane)
    os.makedirs(os.path.join(folder, "memories"), exist_ok=True)
    open(os.path.join(folder, "config.yaml"), "w").write("model:\n  provider: fixture-a\n")
    open(os.path.join(folder, "memories", "MEMORY.md"), "w").write("a note the lane can no longer add to. " * 40)
    monkeypatch.setattr(doctor, "check", lambda command, **_kw: True)
    monkeypatch.setattr(doctor, "gateway_status", lambda: "half-open")
    monkeypatch.setattr(doctor, "cron_plan", lambda jobs, pack: [{"op": "remove", "name": "standup"}])
    monkeypatch.setattr(doctor, "hermes_version_problem", lambda: "")
    monkeypatch.setattr("cockpitlib.setup.desktop_copy_stale", lambda: "Desktop runs a stale copy of the plugin UI")
    monkeypatch.setattr(
        "cockpitlib.pack.agent_launch", lambda pack: {"home": "/no/such/agent/home", "router": "/no/such/router.md"}
    )
    problems = doctor.run(pack)
    for expected in (
        "git status blocked",
        f"{lane} MEMORY.md not writable",
        "agent home missing",
        "gateway state unreadable",
        "standup cron is registered but the pack turns it off: run setup",
        "Desktop runs a stale copy of the plugin UI",
    ):
        assert expected in problems
    assert "git push NOT blocked" not in problems


# ---------------------------------------------------------------------------------------------------------------- api


def test_start_card_refuses_repos_that_are_not_a_list():
    from cockpitlib.plugin_api import start_card

    with pytest.raises(CockpitError, match="repos is a list of repo names, not 5"):
        start_card("dev", "TASK-370", repos=5, pack={"name": "acme"})


def test_a_card_without_a_lane_has_no_other_seat_to_go_to(bare, monkeypatch):
    from cockpitlib import plugin_api

    monkeypatch.setattr("cockpitlib.lane_feed.card", lambda pack, card: {})
    assert plugin_api.hand_over_card("c1", pack=_pack()) == ""


def test_a_push_to_a_protected_branch_stays_with_the_human(bare, monkeypatch):
    from cockpitlib import plugin_api

    pack = _pack()
    monkeypatch.setattr("cockpitlib.git_push.protected", lambda pack, repo: ["main", "release"])
    assert (
        plugin_api._protected_target({"type": "push-branch", "payload": {"repo": "api", "branch": "release"}}, pack)
        is True
    )
    assert (
        plugin_api._protected_target(
            {"type": "push-branch", "payload": {"repo": "api", "branch": "work/x", "publish_as": "main"}}, pack
        )
        is True
    )
    assert (
        plugin_api._protected_target({"type": "push-branch", "payload": {"repo": "api", "branch": "work/x"}}, pack)
        is False
    )

    def unreadable(pack=None):
        raise RuntimeError("no pack")

    monkeypatch.setattr(plugin_api, "_pack", unreadable)
    assert (
        plugin_api._protected_target({"type": "tracker-comment", "payload": {}}) is True
    )  # unknown: the human decides


def test_a_held_item_is_sent_back_by_name_and_another_decision_is_refused(bare, monkeypatch):
    from cockpitlib import plugin_api

    held = {"id": "i-1", "status": "held", "type": "tracker-comment", "payload": {}}
    monkeypatch.setattr("cockpitlib.outbox.load", lambda iid: dict(held))
    sent = []
    monkeypatch.setattr(
        "cockpitlib.gate.return_intent",
        lambda pack, iid, note, actor="": sent.append((iid, note, actor)) or {"id": iid, "status": "returned"},
    )
    assert plugin_api.decide_intent("i-1", "send_back", by="bumps", pack=_pack())["status"] == "returned"
    assert plugin_api.decide_intent("i-1", "send_back", note="wrong base", by="bumps", pack=_pack())["id"] == "i-1"
    assert sent == [("i-1", "sent back by bumps", "bumps"), ("i-1", "wrong base", "bumps")]
    with pytest.raises(CockpitError, match="decision is confirm, send_back or drop"):
        plugin_api.decide_intent("i-1", "approve", pack=_pack())


# ------------------------------------------------------------------------------------------------- the smaller modules


def test_a_flag_setting_takes_one_and_zero():
    from cockpitlib.settings import _flag

    assert _flag(1) is True and _flag(0) is False and _flag(True) is True


def test_a_pack_without_a_card_body_uses_the_default_one():
    from cockpitlib import decompose

    assert decompose.body_template({"skills": {"cards": {}}}) == decompose.DEFAULT_BODY


def test_a_pull_request_that_is_not_named_has_no_watch_record():
    from cockpitlib.outbox import _pr_state

    assert _pr_state("TASK-380", "api", 0) == {} and _pr_state("", "api", 4) == {}


def test_a_hold_that_asks_a_question_is_not_confirmed(bare, monkeypatch):
    from cockpitlib import outbox

    held = {
        "id": "i-1",
        "status": "held",
        "hold": {"waits": "human", "ask": "which base branch?", "reason": "two bases"},
    }
    monkeypatch.setattr(outbox, "load", lambda iid: dict(held))
    with pytest.raises(CockpitError, match="i-1 asks a question: answer it in its decision form"):
        outbox.confirm("i-1")


def test_two_presses_of_one_button_landing_together_queue_one_request(bare, monkeypatch):
    from cockpitlib import inbox

    folder = inbox._folder("bumps")
    os.makedirs(folder, exist_ok=True)
    row = {"id": "api-4", "what": "requeue", "detail": {"actions": [{"label": "Requeue", "act": {"do": "requeue"}}]}}
    json.dump(row, open(os.path.join(folder, "api-4.json"), "w", encoding="utf-8"))
    monkeypatch.setattr(
        inbox, "pending_presses", lambda plugin, ident: []
    )  # both presses read "nothing pending" at once
    first = inbox.queue_act("bumps", "api-4", 0)
    second = inbox.queue_act("bumps", "api-4", 0, client={"pane": "inbox"})
    assert first["queued"] and second == {"queued": "", "already": True, "plugin": "bumps", "label": "Requeue"}
    assert os.listdir(inbox.acts_dir("bumps")) == ["api-4-0.json"]


def test_discover_puts_the_editors_skills_first_and_a_planted_secret_removes_the_draft(bare, monkeypatch, tmp_path):
    from cockpitlib import migrate

    workspace = tmp_path / "legacy"
    (workspace / ".cursor" / "skills").mkdir(parents=True)
    found = migrate.discover(str(workspace))
    assert found["skills_dir"] == [os.path.realpath(str(workspace / ".cursor" / "skills"))]
    dest = tmp_path / "draft"
    monkeypatch.setattr(
        migrate, "secrets_scan", lambda text: "token" if "The repositories a ticket may touch" in text else ""
    )
    with pytest.raises(CockpitError, match="secret in draft"):
        migrate.draft(found, str(dest))
    assert not os.path.exists(dest)  # the hit came before the first write: nothing was made


def test_a_forge_pause_that_cannot_be_written_does_not_fail_the_call(monkeypatch):
    from cockpitlib.forge import Forge

    def nowhere():
        raise RuntimeError("no workspace is bound")

    monkeypatch.setattr(Forge, "_pause_file", staticmethod(nowhere))
    forge = object.__new__(Forge)
    assert forge._set_pause(time.time() + 60) is None and forge._pause_until() == 0.0


def test_ci_watches_the_heads_of_open_pull_requests_and_counts_flaky_runs_per_repo(bare):
    from cockpitlib import ci_watch

    folder = os.path.join(_qa("TASK-382"), "pr")
    os.makedirs(folder)
    json.dump({"number": 1}, open(os.path.join(folder, "api-1.json"), "w"))  # no repo, no head
    json.dump(
        {"repo": "api", "head_sha": "abc", "rows": []}, open(os.path.join(folder, "api-2.json"), "w")
    )  # another record kind
    json.dump({"repo": "api", "head_sha": "def", "head": "work/382"}, open(os.path.join(folder, "api-3.json"), "w"))
    assert ci_watch.commits(_pack()) == [("TASK-382", "api", "def", "work/382")]
    runs = ci_watch._folder("TASK-382")
    os.makedirs(runs)
    json.dump(
        {"repo": "web", "runs": [{"name": "build", "passed_after_rerun": True}]},
        open(os.path.join(runs, "web-1.json"), "w"),
    )
    json.dump(
        {
            "repo": "api",
            "runs": [{"name": "build", "passed_after_rerun": True}, {"name": "lint", "passed_after_rerun": True}],
        },
        open(os.path.join(runs, "api-1.json"), "w"),
    )
    assert ci_watch._flaky("TASK-382", "api", "build") == 1


def test_the_first_stage_of_a_bump_batch_waits_for_nothing(bare, monkeypatch):
    from cockpitlib import sequence

    stages = {
        "stages": [
            {"name": "rebase", "intent": "push-branch", "fields": [], "event": "", "after": ""},
            {"name": "approve", "intent": "pr-review-submit", "fields": [], "event": "APPROVE", "after": "rebase"},
        ]
    }
    monkeypatch.setattr(sequence, "_sequence", lambda pack, ticket: stages)
    assert sequence.check_order(_pack(), "TASK-383", "push-branch", {"repo": "api"}) is None
    with pytest.raises(CockpitError):
        sequence.check_order(
            _pack(), "TASK-383", "pr-review-submit", {"repo": "api", "event": "APPROVE"}
        )  # names no stage before it


def test_a_release_claim_seated_on_another_lane_gives_that_lane_the_claimed_place(bare, monkeypatch):
    from cockpitlib import kickoff

    owners, marked = [], []
    monkeypatch.setattr("cockpitlib.acts.claim_slot", lambda pack, ticket, lane: {"slot": 2})
    monkeypatch.setattr("cockpitlib.halt.refuse", lambda ticket: None)
    monkeypatch.setattr("cockpitlib.kanban.open_cards", lambda board: {})
    monkeypatch.setattr("cockpitlib.lanes.free_lane", lambda kind, pack, cards, ticket="": "worker-2")
    monkeypatch.setattr("cockpitlib.slots.slot_of", lambda ticket, count: 2)
    monkeypatch.setattr("cockpitlib.slots.mark_release_claim", lambda number, ticket: marked.append((number, ticket)))
    monkeypatch.setattr("cockpitlib.slots.write_owner", lambda number, owner: owners.append((number, owner)))
    assert kickoff._claim_for_release(_pack(), {"lane_kind": "worker"}, "TASK-384", "worker-1") == "worker-2"
    assert owners == [(2, "worker-2")] and marked == [(2, "TASK-384")]


def test_digest_numbers_tolerate_a_trailing_comma():
    from cockpitlib.gate import _numbered

    assert _numbered("1, 3,", {"1": "i-a", "2": "i-b", "3": "i-c"}) == [("i-a", True), ("i-c", True)]


def test_an_auto_send_that_is_refused_is_recorded_on_the_intent(bare, monkeypatch):
    from cockpitlib import gate
    from cockpitlib.intents import load
    from cockpitlib.outbox import create

    pack = dict(_pack(), outbox={"auto": [{"scope": "release", "types": ["tracker-comment"]}]})
    row = create(pack, "TASK-385", "tracker-comment", "c1", "say it", {"body": "Done."})
    monkeypatch.setattr("cockpitlib.kanban.card_scope", lambda board, card: "release")
    monkeypatch.setattr(gate, "_auto_refusal", lambda pack, intent: "")

    def refused(*_a, **_k):
        raise CockpitError("the body cites a local path")

    monkeypatch.setattr("cockpitlib.outbox.endorse", refused)
    assert gate.auto_publish(pack) == "0"
    auto = load(row["id"])["auto"]
    assert (auto["ok"], auto["error"], auto["scope"]) == (False, "the body cites a local path", "release")


def test_a_card_the_board_does_not_know_is_no_test_run_and_no_results_means_no_videos_owed(bare, monkeypatch):
    from cockpitlib import test_flow

    def unknown(pack, card):
        raise RuntimeError("no index")

    monkeypatch.setattr("cockpitlib.browser_card.facts", unknown)
    assert test_flow.run_card(_pack(), "c-unknown") is False
    assert test_flow.failure_videos(_pack(), "TASK-386") == {"run": "", "missing": [], "waived": []}


class _FakeForge:
    """The forge as the pull-request watch reads it: one PR with an issue comment and a review still being written."""

    def repo(self, name):
        return f"acme/{name}"

    def me(self):
        return "dev"

    def pr(self, repo, number):
        return {
            "html_url": "https://forge.example.test/pr/4",
            "title": "A change",
            "head": {"ref": "work/4", "sha": "abc"},
            "base": {"ref": "main"},
            "user": {"login": "dev"},
            "state": "open",
        }

    def threads(self, repo, number):
        return []

    def get(self, url):
        if "/issues/" in url:
            return [
                {"id": 5, "user": {"login": "rev"}, "body": "Why this default?", "created_at": "2026-11-01T10:00:00Z"}
            ]
        if url.endswith("/reviews?per_page=100"):
            return [
                {"id": 7, "state": "PENDING", "user": {"login": "rev"}, "body": "draft"},
                {
                    "id": 8,
                    "state": "COMMENTED",
                    "user": {"login": "rev"},
                    "body": "See inline.",
                    "submitted_at": "2026-11-01T11:00:00Z",
                },
            ]
        return []


def test_a_review_still_being_written_is_not_a_comment_yet():
    from cockpitlib import pr_watch

    rows = pr_watch._comments(_FakeForge(), "api", 4)
    assert [row["id"] for row in rows] == ["issue:5", "review:8"]


def test_kept_comments_are_read_again_once_each_and_one_gone_from_the_forge_keeps_its_text(bare, monkeypatch):
    from cockpitlib import pr_watch

    path = pr_watch.record_path("TASK-387", "api", 4)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    json.dump(
        {
            "ticket": "TASK-387",
            "repo": "api",
            "number": 4,
            "role": "author",
            "ids": ["issue:5", "inline:9", "review:8"],
            "head_sha": "abc",
            "new": [
                "a loose line",
                {"id": "issue:5", "kind": "comment", "body": "old text"},
                {"id": "issue:5", "kind": "comment", "body": "twice"},
                {"id": "inline:9", "kind": "review-comment", "author": "rev", "body": "This line was deleted since."},
            ],
        },
        open(path, "w", encoding="utf-8"),
    )
    monkeypatch.setattr(pr_watch, "_skip", lambda pack, me, comment, closed=None: "")
    monkeypatch.setattr(pr_watch, "_since_review", lambda forge, repo, record, previous: {})
    record = pr_watch.read(_pack(), _FakeForge(), "TASK-387", "api", 4, time.time())
    assert [(row["id"], row["kind"], row["body"]) for row in record["new"]] == [
        ("issue:5", "comment", "Why this default?"),
        ("inline:9", "inline", "This line was deleted since."),
    ]


def test_a_ticket_no_longer_owed_its_done_row_leaves_the_owed_list(bare, monkeypatch):
    from cockpitlib import pr_watch
    from cockpitlib.paths import watch_dir

    os.makedirs(watch_dir(), exist_ok=True)
    owed = os.path.join(watch_dir(), "ticket-done-owed.json")
    json.dump({"tickets": ["TASK-388"]}, open(owed, "w", encoding="utf-8"))
    monkeypatch.setattr("cockpitlib.publish.forge_for", lambda pack: _FakeForge())
    monkeypatch.setattr(pr_watch, "discover", lambda pack, forge: None)
    monkeypatch.setattr(pr_watch, "watched", lambda: [])
    result = pr_watch.watch(_pack(), now=1000.0)
    assert result == {"rows": [], "cards": [], "done": [], "errors": []}
    assert json.load(open(owed, encoding="utf-8"))["tickets"] == []


def test_a_migration_without_a_login_exporter_counts_and_imports_nothing(bare):
    from cockpitlib import pack_migration

    pack = _pack()
    assert pack_migration._count(pack, {"exporters": {}}) == 0
    assert pack_migration._import_vault(pack, {}, None) == {"imported": 0, "kept": 0}


def test_a_move_inside_one_repo_is_seen_even_when_its_source_folder_is_gone(env, tmp_path):
    from cockpitlib import pack_migration

    repo = str(env["root"] / "repos" / "api")
    found = pack_migration._same_repo(
        os.path.join(repo, "gone", "deeper", "note.md"), os.path.join(repo, "qa", "note.md")
    )
    assert found and os.path.samefile(found, repo)
    assert (
        pack_migration._same_repo(
            os.path.join(repo, "gone", "deeper", "note.md"), str(tmp_path / "elsewhere" / "note.md")
        )
        == ""
    )


def test_only_readable_intent_files_are_converted(bare, tmp_path):
    from cockpitlib import pack_migration

    folder = tmp_path / "outbox"
    folder.mkdir()
    (folder / "1-comment.md").write_text("the comment body kept beside its intent\n")
    (folder / "2-broken.json").write_text("{not json")
    journal = pack_migration.Journal(str(tmp_path))
    assert pack_migration._convert_intents(str(folder), journal) == 0
    assert journal.rows == [{"action": "intents", "folder": str(folder), "converted": 0, "skipped": 0}]
    assert (folder / "2-broken.json").read_text() == "{not json"


def test_rolling_back_puts_the_snapshots_board_in_place_without_the_newer_write_log(bare):
    import shutil

    from cockpitlib import pack_migration
    from cockpitlib.kanban import db_path, place_card

    pack = _pack()
    card = place_card(pack["board"], "TASK-389: work", "worker-1", "ready")
    board = db_path(pack["board"])
    folder = os.path.join(pack_migration.snapshots_dir(), "20261117-1200")
    os.makedirs(folder)
    shutil.copy2(board, os.path.join(folder, "board.db"))
    place_card(pack["board"], "TASK-390: later", "worker-1", "ready")
    for suffix in ("-wal", "-shm"):
        open(board + suffix, "wb").write(b"newer pages")
    restored = pack_migration.rollback(pack, "20261117-1200")
    assert board in restored and not os.path.exists(board + "-wal") and not os.path.exists(board + "-shm")
    connection = sqlite3.connect(board)
    titles = [row[0] for row in connection.execute("select title from tasks")]
    connection.close()
    assert "TASK-389: work" in titles and "TASK-390: later" not in titles and card
