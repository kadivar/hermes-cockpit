# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""What the page buttons change. A handler that returns success without one of these is a stub.

Identity (org, base branch, ticket pattern, slot spec) comes from the pack. The board
writes are the same rows `hermes kanban` comment, unblock, complete, and archive leave.
"""

import json
import os
import re
import shutil
import sqlite3
import subprocess
import time

from .chat import end_chat
from .errors import CockpitError, Conflict
from .gh_cli import ForgeError
from .halt import clear, write
from .intents import check_ticket, ticket_folder
from .kanban import (
    BoardWrites,
    archive_ticket_cards,
    board_cards,
    card_title,
    db_path,
    delete_ticket_cards,
    one_at_a_time,
    open_twin,
    ticket_of,
)
from .pack import batch_project, forge_org
from .paths import PLUGIN_ROOT, inside, outbox, platform_dir, qa, qa_of, segment, watch_dir, within, worktree_of, wt
from .store import append_line, dump_json, read_db, write_text
from .worktree import dest, list_worktrees, repo_source

RUNNING = ("in_progress", "running", "claimed")
STOP = re.compile(r"^\s*stop\b", re.I)
BOTS = ("dependabot", "renovate")
# A watcher record that a job of another name writes: the minute housekeeping runs in the ci-watch job.
RECORD_JOBS = {"housekeeping": "ci-watch.sh"}


def watchers() -> dict:
    """What a watcher row's Run now may run: every job cockpit registers (setup.CRON_JOBS), by its own name, and the
    job of a record that another job writes (RECORD_JOBS). Read from the job list, not kept beside it."""
    from .setup import CRON_JOBS

    return {**{name: script for name, _schedule, script in CRON_JOBS}, **RECORD_JOBS}


def _git(folder, args):
    return subprocess.run(["git", "-C", folder, *args], capture_output=True, text=True, check=False)


def _columns(connection, table):
    try:
        return {row[1] for row in connection.execute(f"pragma table_info({table})")}
    except sqlite3.Error:
        return set()


class _Board:
    """The board while an act runs: reads on a read-only connection, writes queued for Hermes until commit."""

    def __init__(self, slug, path):
        self.reader = read_db(path)
        self.reader.row_factory = sqlite3.Row
        self.writes = BoardWrites(slug)

    def execute(self, *args):
        return self.reader.execute(*args)

    def commit(self):
        self.writes.flush()

    def close(self):
        self.reader.close()


def _open(slug):
    path = db_path(slug)
    if not os.path.isfile(path):
        return None
    return _Board(slug, path)


def _comment(connection, card_id, author, body):
    connection.writes.comment(card_id, author, body)


def note_card(pack, card_id: str, author: str, body: str) -> bool:
    """A comment on a card, for the human reading it. False when the board or the card is not there."""
    card_id = (card_id or "").strip()
    connection = _open(pack["board"]) if card_id else None
    if connection is None:
        return False
    try:
        if _task(connection, card_id) is None:
            return False
        _comment(connection, card_id, author, body)
        connection.commit()
    except CockpitError as exc:
        # The note is for the human reading the card; the act it reports is already recorded. Hermes refuses a board
        # write from a lane's own command ("delegate_task child contexts cannot mutate Kanban tasks"). That refusal is
        # logged and never raised: raised, a recorded act would read "failed" to the lane that made it.
        from .store import log

        log(f"NOTE? {card_id}: {str(exc)[-160:]}")
        return False
    finally:
        connection.close()
    return True


def _status(connection, card_id, status, result=""):
    """Move a card the way Hermes moves it. The card's current status decides which move that is."""
    row = connection.execute("select status from tasks where id = ?", (card_id,)).fetchone()
    current = row[0] if row else ""
    writes = connection.writes
    if status == "ready":
        if current == "triage":
            writes.specify(card_id)
            writes.promote(card_id)
            return
        if current in ("blocked", "scheduled"):
            writes.unblock(card_id)
        return
    if status in ("blocked", "failed"):
        if current == "blocked":
            # Already blocked: unblocking and blocking again would read to Hermes as a loop. The new reason is a comment.
            if result:
                writes.comment(card_id, "cockpit", result)
            return
        if current == "scheduled":
            # Hermes blocks only a ready or running card: a card waiting on a quota goes back to ready first, and the
            # block is guarded, so a dispatcher claim in between wins (the worker runs; nothing is orphaned)
            writes.unblock(card_id)
            writes.block(card_id, result or status, guard=True)
            return
        writes.block(card_id, result or status)
        return
    if status == "done":
        if current == "running":
            writes.reclaim(card_id, result or None)
        if current == "triage":
            # Hermes completes no card it parked in triage: release it first, as the answer to a parked card does
            writes.specify(card_id)
            writes.promote(card_id)
        writes.complete(card_id, result=result or None)
        return
    if status == "archived":
        writes.archive(card_id)
        return
    raise CockpitError(f"no board move to {status}")


def _task(connection, card_id):
    if "id" not in _columns(connection, "tasks"):
        return None
    try:
        return connection.execute("select * from tasks where id = ?", (card_id,)).fetchone()
    except sqlite3.Error as exc:
        raise CockpitError("board unreadable") from exc


def _logout_ticket(pack, title: str) -> None:
    """The lane logs out of every slot holding the ticket before a block or a complete. Slot 1 is the fallback."""
    from .vault import logout

    ticket = ticket_of(title or "")
    matched = _slots_holding(ticket)
    if not matched:
        logout(1)
        return
    for slot in matched:
        logout(slot)


def _finish_section(assignee: str, title: str) -> str:
    """The section this lane writes when it finishes. Any other card names the section itself."""
    who = str(assignee or "")
    name = str(title or "")
    if who.startswith("worker"):
        return "Delivered"
    if who.startswith("tester") or ": test" in name:
        return "Tested"
    if who.startswith("reviewer") or ": review" in name:
        return "Reviewed"
    return ""


def _release_waiting_reviewer(connection, ticket: str) -> None:
    """A reviewer card blocked for this ticket can start once the tester has finished."""
    columns = _columns(connection, "tasks")
    assignee_column = "assignee" in columns
    query = "select id, title, status" + (", assignee" if assignee_column else "") + " from tasks"
    for row in connection.execute(query).fetchall():
        card_id = row[0]
        title = row[1] or ""
        card_status = row[2] or ""
        assignee = row[3] if assignee_column else ""
        if not str(title).startswith(f"{ticket}:"):
            continue
        if card_status != "blocked":
            continue
        # only a review card the kickoff blocked to wait for the tester: not the worker's "review the PR", not another question
        from .kanban import block_reason

        if not str(assignee).startswith("reviewer") or block_reason(connection, card_id) != WAITING_FOR_TESTER:
            continue
        _status(connection, card_id, "ready", "")


WAITING_FOR_TESTER = "waiting for the tester"


def release_reviewers(pack) -> str:
    """Housekeeping: a review card waiting for the tester starts once the ticket has no open tester card, whoever finished it."""
    from .kanban import board_cards

    cards = board_cards(pack["board"])
    waiting = {
        card.get("ticket")
        for card in cards
        if str(card.get("assignee") or "").startswith("reviewer") and card.get("status") == "blocked"
    }
    released = 0
    for ticket in sorted(item for item in waiting if item):
        if any(
            card.get("ticket") == ticket
            and str(card.get("assignee") or "").startswith("tester")
            and card.get("status") not in ("done", "archived")
            for card in cards
        ):
            continue
        connection = _open(pack["board"])
        if connection is None:
            return "0"
        try:
            _release_waiting_reviewer(connection, ticket)
            connection.commit()
            released += 1  # tickets whose waiting reviews were looked at
        finally:
            connection.close()
    return str(released)


def proposal_path(ticket: str) -> str:
    """The intake's proposal file for a ticket: qa/<ticket>/proposal.md (what finish_intake writes), else the newest
    qa/<ticket>/intake/proposal*.md (an intake lane that files its proposals by date). Empty when there is none."""
    direct = qa_of(ticket, "proposal.md")
    if os.path.isfile(direct):
        return direct
    folder = qa_of(ticket, "intake")
    found = (
        sorted(
            (
                os.path.join(folder, name)
                for name in os.listdir(folder)
                if name.startswith("proposal") and name.endswith(".md")
            ),
            key=os.path.getmtime,
        )
        if os.path.isdir(folder)
        else []
    )
    return found[-1] if found else ""


def answer_card(pack, card_id, text, unblock=True) -> dict:
    """Comment, then unblock. `stop` completes the card. A card parked in triage is released to ready."""
    card_id = (card_id or "").strip()
    text = (text or "").strip()
    if not card_id or not text:
        raise CockpitError("write the answer")
    rerun = []
    connection = _open(pack["board"])
    if connection is None:
        raise CockpitError(f"no card {card_id}")
    try:
        row = _task(connection, card_id)
        if row is None:
            raise CockpitError(f"no card {card_id}")
        tester_card = str(row["assignee"] if "assignee" in row.keys() else "").startswith("tester")
        # "Block: rows 3, 4 missing …" on a tester's card (its lane, or a Test card by title, as the go path reads it) is the
        # rows-blocked verdict and is checked as one. On any other card an answer that starts with "block" is the human's
        # text ("Block again with exactly: …" to an analyst), commented and resumed like every other word.
        if text.lower().startswith("block") and (
            tester_card or ": test" in str(row["title"] if "title" in row.keys() else "")
        ):
            from .test_flow import accept_block

            accept_block(text)
            _logout_ticket(pack, row["title"] if "title" in row.keys() else "")
        # A go with changes on a tester's card lifts a test rule, and one that names a path reads it back: both restate
        # first. Any other go with changes (intake's plan, a patch plan) is the human's instruction, commented and resumed.
        from .test_flow import named_path

        lifted = (
            text.lower().startswith("go with changes")
            and "rerun" not in text.lower()
            and (tester_card or bool(named_path(text)))
        )
        restated = False
        if lifted:
            from .test_flow import require_restatement

            require_restatement(text, text)
        if text.lower().startswith("complete") and "title" in row.keys():
            from .kanban import ticket_of
            from .plan import append, require_section, sections

            ticket = ticket_of(row["title"] or "")
            assignee_now = row["assignee"] if "assignee" in row.keys() else ""
            title_now = row["title"] or ""
            if str(assignee_now).startswith("tester") or ": test" in str(title_now):
                _require_test_table(ticket)
            if ticket:
                body = text.split(":", 1)[1].strip() if ":" in text else ""
                own = _finish_section(assignee_now, title_now)
                if own:
                    if own not in sections(ticket) and body and body.lower() != own.lower():
                        append(ticket, own, body)
                    require_section(ticket, own)
                else:
                    require_section(ticket, body or "Delivered")
                if str(assignee_now).startswith("worker"):
                    from .kanban import skills_of
                    from .outbox import extra_skills
                    from .skill_log import loaded

                    carried = skills_of(row["skills"]) if "skills" in row.keys() else []
                    if len(extra_skills(pack, "worker", loaded(ticket, str(assignee_now)), carried)) > 1:
                        raise CockpitError("the router chooses one skill")
            _logout_ticket(pack, row["title"] if "title" in row.keys() else "")
        status = row["status"] if "status" in row.keys() else ""
        if status not in ("blocked", "triage"):
            raise Conflict(f"card {card_id} is {status}: not waiting for an answer")
        waived = re.match(r"^\s*go\s+without\s+screenshots\b", text, re.I)
        if (re.match(r"^\s*go\s*[.!]?\s*$", text, re.I) or waived) and str(
            row["assignee"] if "assignee" in row.keys() else ""
        ).startswith("tester"):
            # a plain go accepts a run: only a finished one ("go without screenshots" waives only the missing screenshots)
            from .kanban import block_reason, ticket_of
            from .test_flow import run_not_ready

            still = run_not_ready(
                pack,
                ticket_of(row["title"] if "title" in row.keys() else ""),
                block_reason(connection, card_id),
                card=card_id,
            )
            if waived:
                still = [item for item in still if not item.endswith("·screenshot")]
            if still:
                raise Conflict(
                    "not ready for your go: rows " + ", ".join(still) + " are not finished. Send it back instead."
                )
        if text.lower().startswith("complete"):
            assignee_done = row["assignee"] if "assignee" in row.keys() else ""
            title_done = row["title"] if "title" in row.keys() else ""
            if str(assignee_done).startswith("tester") or ": test" in str(title_done):
                from .kanban import ticket_of

                finished = ticket_of(str(title_done))
                if finished:
                    cleanup_settings(finished)
                    _release_waiting_reviewer(connection, finished)
        if lifted:
            from .lend import note_block, request_line
            from .test_flow import expected_read, lane_reaches, named_path

            target = named_path(text)
            if not lane_reaches(pack, target):
                why = f"no path to {target or 'the value'}"
                line = request_line(pack, "read the value", why)
                _comment(connection, card_id, "human", f"Human: {text}")
                _status(connection, card_id, "blocked", line)
                note_block(line, card_id)
                connection.commit()
                return {"ok": False, "blocked": True, "text": line, "id": card_id}
            wanted = expected_read(text)
            _comment(connection, card_id, "human", f"path: {target} read {wanted}")
            restated = True
            if wanted:
                try:
                    have = open(target, encoding="utf-8").read()
                except OSError:
                    have = ""
                if wanted not in have:
                    line = f"read back {wanted}"
                    _status(connection, card_id, "blocked", line)
                    connection.commit()
                    return {"ok": False, "blocked": True, "text": line, "id": card_id}
        if not restated:
            _comment(connection, card_id, "human", f"Human: {text}")
        if text.lower().startswith("complete") or STOP.match(text):
            _status(connection, card_id, "done", text)
            from .kanban import mark_card

            mark_card(pack["board"], card_id, ended_by="owner")
            out = "completed"
        elif status == "triage":
            _status(connection, card_id, "ready")
            out = "released"
        elif unblock:
            _status(connection, card_id, "ready")
            out = "unblocked"
        else:
            out = "noted"
        published = ""
        title = row["title"] if "title" in row.keys() else ""
        ticket = ""
        if "title" in row.keys():
            from .kanban import ticket_of

            ticket = ticket_of(row["title"] or "")
        from .kanban import _index

        recorded = (_index().get(pack["board"]) or {}).get(card_id) or {}
        kind = recorded.get("kind") if isinstance(recorded, dict) else ""
        # Only a Test kickoff's own cards (its plan, its run) end in the test run's ticket-done: a tester card that follows a
        # worker in the dev chain ("<ticket>: tester") is accepted by the plan's flow, and its plain go makes no intent.
        standalone = kind in ("test", "test-kickoff") if kind else (": test" in title and ": tester" not in title)
        if ticket and standalone and text.strip() == "go":
            from .kanban import block_reason
            from .test_flow import plain_go

            offered = "plan ready" in block_reason(connection, card_id).lower()  # the tester's "Test plan ready … go?"
            kickoff = kind == "test-kickoff" or "test kickoff" in title or offered
            if kickoff and not _plan_accepted(ticket):
                _accept_plan(ticket, pack)
            elif plain_go(text):
                from .outbox import create

                attach_evidence(pack, ticket)
                # under kickoff.done_rows: developed, a test the human only asked for ends with its results post, not a done row
                if not done_rows_developed(pack):
                    published = create(pack, ticket, "ticket-done", card_id, "test run finished", {})["id"]
        if ticket:
            from .test_flow import rerun_rows

            rerun = rerun_rows(text)
            assignee = row["assignee"] if "assignee" in row.keys() else ""
            intake = ": intake" in title or str(assignee).startswith("intake")
            if intake and (text.strip() == "go" or text.lower().startswith("go with changes")):
                from .plan import init

                body = ""
                proposal = proposal_path(ticket)
                if proposal:
                    body = open(proposal, encoding="utf-8").read()
                init(ticket, body, text.strip())
            if rerun:
                folder = qa_of(ticket)
                os.makedirs(folder, exist_ok=True)
                _reset_named_rows(ticket, rerun)
                _write(os.path.join(folder, "rerun.json"), {"rows": rerun, "pack": pack.get("name") or ""})
        connection.commit()
    finally:
        connection.close()
    return {"ok": True, "out": out, "id": card_id, "published": published, "rerun": rerun}


def fail_login(pack, card: str, reason: str) -> dict:
    """Block the card once and record the reason. A second failure does not block again."""
    from .paths import watch_dir

    folder = watch_dir()
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, "login-blocks.json")
    seen = []
    if os.path.isfile(path):
        try:
            loaded = json.loads(open(path, encoding="utf-8").read() or "[]")
        except json.JSONDecodeError:
            loaded = []
        if isinstance(loaded, list):
            seen = [str(item) for item in loaded]
    if card in seen:
        return {"ok": True, "blocked": False, "reason": reason, "card": card}
    seen.append(card)
    dump_json(path, seen, mode=0o600)
    connection = _open(pack["board"])
    if connection is None:
        return {"ok": True, "blocked": False, "reason": reason, "card": card}
    try:
        row = _task(connection, card)
        title = row["title"] if row is not None and "title" in row.keys() else ""
        _logout_ticket(pack, title)
        _status(connection, card, "blocked", reason)
        _comment(connection, card, "cockpit", reason)
        connection.commit()
    finally:
        connection.close()
    return {"ok": True, "blocked": True, "reason": reason, "card": card}


def _results_path(ticket: str) -> str:
    """The ticket's own results file, by the bound pack's name for it."""
    from .test_flow import bound, results_file

    return qa_of(ticket, results_file(bound()))


def missing_plan_rows(ticket: str) -> list:
    """Plan rows that never appear in the run. No plan means nothing is missing."""
    folder = qa_of(ticket)
    sources = [os.path.join(folder, name) for name in ("plan.md", "test-kickoff.md")]
    sources = [path for path in sources if os.path.isfile(path)]
    if not sources:
        return []
    lines = []
    seen = set()
    for path in sources:
        for raw in open(path, encoding="utf-8"):
            text = raw.strip()
            if not text or text in seen:
                continue
            seen.add(text)
            lines.append(text)
    results_path = _results_path(ticket)
    results = open(results_path, encoding="utf-8").read() if os.path.isfile(results_path) else ""
    missing = []
    for index, line in enumerate(lines, 1):
        if _plan_line_present(line, results):
            continue
        missing.append(str(index))
    return missing


def _reset_named_rows(ticket: str, rows) -> list:
    """Put only the named rows back to Not run. Every other row stays as it was."""
    path = _results_path(ticket)
    if not os.path.isfile(path):
        return []
    wanted = {str(row) for row in rows}
    changed = []
    kept = []
    for line in open(path, encoding="utf-8"):
        stripped = line.strip()
        number = ""
        if stripped:
            token = stripped.split()[0]
            if token.isdigit():
                number = token
        if number and number in wanted:
            kept.append(f"{number} Not run\n")
            changed.append(number)
            continue
        kept.append(line if line.endswith("\n") else line + "\n")
    write_text(path, "".join(kept))
    return changed


def _plan_line_present(line: str, results: str) -> bool:
    """The plan row appears as its own text. A longer word that merely contains it does not count."""
    needle = f" {line} "
    for row in results.splitlines():
        padded = f" {row.strip()} "
        if needle in padded:
            return True
    return False


def _fail_rows(text: str) -> list:
    rows = []
    for line in (text or "").splitlines():
        if "❌" not in line:
            continue
        number = ""
        for token in line.split():
            if token.isdigit():
                number = token
                break
        if number and number not in rows:
            rows.append(number)
    return rows


def _require_fail_recordings(ticket: str) -> None:
    """Each failed row has exactly one recording."""
    path = _results_path(ticket)
    text = open(path, encoding="utf-8").read() if os.path.isfile(path) else ""
    folder = qa_of(ticket, "recordings")
    names = os.listdir(folder) if os.path.isdir(folder) else []
    if "❌" in text and not _fail_rows(text):
        raise CockpitError("a fail needs one recording")
    for number in _fail_rows(text):
        kept = [name for name in names if name == f"{number}.txt" or name.startswith(f"{number}-")]
        if len(kept) != 1:
            raise CockpitError("a fail needs one recording")


def _shot_path(ticket: str, token: str) -> str:
    """The screenshot a results row names, under the ticket's records (or, as qa/<ticket>/…, under the records). A
    name that leads anywhere else is no screenshot: "" is no file."""
    name = token.strip("`,")
    try:
        return qa_of("", name[3:]) if name.startswith("qa/") else qa_of(ticket, name)
    except CockpitError:
        return ""


def _missing_shots(ticket: str, text: str) -> list:
    """Pass and fail rows whose screenshot file is not in the ticket record."""
    missing = []
    for line in (text or "").splitlines():
        if "✅" not in line and "❌" not in line:
            continue
        for token in line.split():
            if not token.strip("`,").endswith(".png"):
                continue
            if os.path.isfile(_shot_path(ticket, token)):
                continue
            if token not in missing:
                missing.append(token)
    return missing


def _require_test_table(ticket: str) -> None:
    """A tester complete needs every plan row, plus a pass or fail and a screenshot."""
    missing = missing_plan_rows(ticket)
    if missing:
        raise CockpitError("missing plan row " + ",".join(missing))
    path = _results_path(ticket)
    text = open(path, encoding="utf-8").read() if os.path.isfile(path) else ""
    from .test_flow import results_still_open

    bare = [line for line in text.splitlines() if ("✅" in line or "❌" in line) and ".png" not in line]
    if bare or ".png" not in text or results_still_open(text):
        raise CockpitError("unfinished screenshot")
    _require_fail_recordings(ticket)
    shots = _missing_shots(ticket, text)
    if shots:
        raise CockpitError("unfinished screenshot")


def start_manual_plan(pack, ticket: str) -> dict:
    """The slot must be ready. A human session stops it. Then the cheap gate runs, and red does not start the plan."""
    from .halt import refuse
    from .slots import tester_slot

    refuse(ticket)
    tester_slot(pack, ticket)
    from .repo_gates import run_gates

    code, lines = run_gates(pack, ticket=ticket)
    if code != 0:
        from .slots import _tester_slot_for
        from .vault import logout

        logout(_tester_slot_for(pack, ticket))
        raise CockpitError("gate is red: " + "; ".join(lines))
    folder = qa_of(ticket)
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, "manual-plan.md")
    write_text(path, "\n".join(lines) + "\n")
    current = {}
    settings_path = os.path.join(folder, "settings.json")
    if os.path.isfile(settings_path):
        try:
            loaded = json.loads(open(settings_path, encoding="utf-8").read() or "{}")
        except json.JSONDecodeError:
            loaded = None
        if isinstance(loaded, dict):
            current = loaded
    snapshot_settings(ticket, current)
    return {"path": path, "started": True}


def _plan_marker(ticket: str) -> str:
    return qa_of(ticket, "plan-accepted.json")


def _plan_accepted(ticket: str) -> bool:
    return os.path.isfile(_plan_marker(ticket))


def _accept_plan(ticket: str, pack) -> None:
    """The first human stop accepts the posted plan. It does not publish the run."""
    folder = qa_of(ticket)
    os.makedirs(folder, exist_ok=True)
    _write(_plan_marker(ticket), {"ticket": ticket, "pack": (pack or {}).get("name") or ""})


def post_test_plan(pack, ticket: str, body: str) -> dict:
    """A test kickoff has no cheap gate. The plan is posted on the card and the lane blocks."""
    from .halt import refuse

    refuse(ticket)
    from .local_refs import find_local_refs

    hits = find_local_refs(body or "", pack)
    if hits:
        raise CockpitError(f"local reference: {hits[0]}")
    from .kanban import open_cards, place_card
    from .lanes import free_lane
    from .outbox import create

    folder = qa_of(ticket)
    os.makedirs(folder, exist_ok=True)
    write_text(os.path.join(folder, "test-kickoff.md"), body or "")
    from .test_flow import rows_from_plan

    rows = rows_from_plan(body or "")
    if any(row.get("human") for row in rows):
        handover_human_rows(ticket, rows)
    lane = free_lane("tester", pack, open_cards(pack["board"]), ticket=ticket)
    card = place_card(
        pack["board"],
        card_title("test-kickoff", ticket, pack=pack),
        lane,
        "blocked",
        body=body or None,
        reason="waiting for go on the test plan",
        kind="test-kickoff",
        ticket=ticket,
        pack=pack,
    )
    from .browser_card import run_card_for_plan

    run_card = run_card_for_plan(pack, ticket)
    if run_card:
        from .kanban import mark_card

        mark_card(pack["board"], card, run_card=run_card)  # the browser choice follows this run card only
    intent = create(pack, ticket, "tracker-comment", card, "tracker", {"body": "test kickoff started"})
    return {"card": card, "intent": intent["id"], "blocked": True}


def _public_origin(pack) -> str:
    """The pack's public app origin. A missing staging file has none."""
    folder = (pack or {}).get("_dir") or ""
    path = os.path.join(folder, "staging.yaml")
    if not os.path.isfile(path):
        return ""
    from . import pack_local

    data = pack_local.read(path) or {}
    if not isinstance(data, dict):
        return ""
    origins = data.get("origins") or {}
    if not isinstance(origins, dict):
        return ""
    return str(origins.get("app") or "").rstrip("/")


def done_rows_developed(pack) -> bool:
    """The pack's `kickoff.done_rows: developed`: the Inbox's "done, confirm?" row only for a ticket the human develops."""
    return str(((pack or {}).get("kickoff") or {}).get("done_rows") or "") == "developed"


def developed(pack, ticket: str) -> bool:
    """The human develops this ticket: a dev card (intake, a rework, a session's work card), a session on a slot, an author
    pull request or a push of its own, or a plugin that runs it. A test, a review or a question kicked off on its own is
    none of these."""
    from .intents import PUSHES, all_intents
    from .kanban import board_cards
    from .owners import owner_of

    if any(
        card["flow"] in ("intake", "rework", "card")
        for card in board_cards(pack["board"], pack)
        if card["ticket"] == ticket
    ):
        return True
    if os.path.isfile(qa_of(ticket, "session.json")):
        return True
    folder = qa_of(ticket, "pr")
    for name in sorted(os.listdir(folder)) if os.path.isdir(folder) else []:
        if name.endswith(".json") and _read(os.path.join(folder, name)).get("role", "author") == "author":
            return True
    if any(row.get("type") in (*PUSHES, "open-pr") for row in all_intents(ticket)):
        return True
    return bool(owner_of(ticket))


def attach_evidence(pack, ticket: str) -> list:
    """Store public evidence links on the tracker comment. A local path is refused."""
    from .intents import all_intents, save
    from .local_refs import find_local_refs

    origin = _public_origin(pack)
    links = []
    from .test_flow import evidence_dir

    shots = qa_of(ticket, evidence_dir(pack))
    if os.path.isdir(shots):
        for name in sorted(os.listdir(shots)):
            if not name.endswith(".png"):
                continue
            link = f"{origin}/evidence/{ticket}/{name}" if origin else name
            hits = find_local_refs(link, pack)
            if hits:
                raise CockpitError(f"local reference: {hits[0]}")
            if link not in links:
                links.append(link)
    created = qa_of(ticket, "created")
    if os.path.isdir(created):
        for name in sorted(os.listdir(created)):
            if not name.endswith(".json"):
                continue
            try:
                row = json.loads(open(os.path.join(created, name), encoding="utf-8").read() or "{}")
            except json.JSONDecodeError:
                continue
            if not isinstance(row, dict):
                continue
            link = str(row.get("link") or "")
            if not link:
                continue
            hits = find_local_refs(link, pack)
            if hits:
                raise CockpitError(f"local reference: {hits[0]}")
            if link not in links:
                links.append(link)
    for intent in all_intents(ticket):
        if intent.get("type") != "tracker-comment":
            continue
        payload = dict(intent.get("payload") or {})
        hits = find_local_refs(str(payload.get("body") or ""), pack)
        if hits:
            raise CockpitError(f"local reference: {hits[0]}")
        payload["evidence"] = list(links)
        intent["payload"] = payload
        save(intent)
    return links


def keep_created(ticket: str, name: str, body, pack=None) -> dict:
    """Created test data stays, named, and linked on the pack's public origin."""
    label = (name or "").strip()
    if not label:
        raise CockpitError("created data needs a name")
    folder = os.path.join(ticket_folder(qa(), ticket, pack), "created")
    os.makedirs(folder, exist_ok=True)
    safe = "".join(ch if ch.isalnum() or ch in "-_" else "-" for ch in label)
    origin = _public_origin(pack)
    link = f"{origin}/data/{safe}" if origin else ""
    path = os.path.join(folder, safe + ".json")
    write_text(path, json.dumps({"name": label, "body": body, "link": link}))
    return {"name": label, "path": path, "link": link}


def snapshot_settings(ticket: str, settings: dict) -> dict:
    """Remember the settings that already existed before the run."""
    folder = ticket_folder(qa(), ticket)
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, "settings-before.json")
    write_text(path, json.dumps(settings or {}))
    return dict(settings or {})


def cleanup_settings(ticket: str) -> dict:
    """Put back only settings that already existed. Created data is left in place."""
    path = os.path.join(ticket_folder(qa(), ticket), "settings-before.json")
    if not os.path.isfile(path):
        return {}
    try:
        before = json.loads(open(path, encoding="utf-8").read() or "{}")
    except json.JSONDecodeError:
        before = {}
    if not isinstance(before, dict):
        before = {}
    restored = dict(before)
    write_text(qa_of(ticket, "settings.json"), json.dumps(restored))
    return restored


def record_fail(ticket: str, n, note: str) -> dict:
    """A failed row keeps exactly one recording. A later note replaces it."""
    text = (note or "").strip()
    if not text:
        raise CockpitError("a fail needs one recording")
    folder = qa_of(ticket, "recordings")
    os.makedirs(folder, exist_ok=True)
    prefix = f"{n}"
    for name in os.listdir(folder):
        if name == f"{prefix}.txt" or name.startswith(prefix + "-"):
            os.remove(os.path.join(folder, name))
    path = os.path.join(folder, f"{prefix}.txt")
    write_text(path, text + "\n")
    kept = [name for name in os.listdir(folder) if name == f"{prefix}.txt" or name.startswith(prefix + "-")]
    return {"n": n, "recordings": len(kept), "path": path}


def _slots_holding(ticket: str) -> list:
    """Slot numbers whose ticket file is this ticket."""
    from .paths import volumes
    from .slots import read_ticket

    found = []
    root = volumes()
    if not ticket or not os.path.isdir(root):
        return found
    for name in sorted(os.listdir(root)):
        if not name.startswith("slot-") or not name[5:].isdigit():
            continue
        number = int(name[5:])
        if read_ticket(number) == ticket:
            found.append(number)
    return found


def handover_human_rows(ticket: str, rows, slot: int = 1) -> dict:
    """Prepare human-only rows last, after the ticket's slot has logged out."""
    from .test_flow import order_human_rows
    from .vault import logout

    matched = _slots_holding(ticket)
    if not matched:
        matched = [int(slot or 1)]
    for number in matched:
        logout(number)
    ordered = order_human_rows(rows)
    folder = qa_of(ticket)
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, "human-rows.json")
    write_text(path, json.dumps(ordered))
    return {"logged_out": True, "path": path, "rows": ordered}


def run_listed(ticket: str, request: str, pack=None) -> str:
    """A scripted write runs only when the accepted plan lists that one line."""
    from .test_flow import scripted_line

    if not _plan_accepted(ticket):
        raise CockpitError("the plan is not accepted")
    path = qa_of(ticket, "test-kickoff.md")
    plan = open(path, encoding="utf-8").read() if os.path.isfile(path) else ""
    return scripted_line(plan, request, pack)


def open_test_rows(ticket: str) -> None:
    """Review waits while a posted run still has an open, blocked, or human row."""
    folder = qa_of(ticket)
    path = _results_path(ticket)
    text = open(path, encoding="utf-8").read() if os.path.isfile(path) else ""
    from .test_flow import results_still_open

    if results_still_open(text):
        raise CockpitError("review waits for open rows")
    _require_fail_recordings(ticket)
    human = os.path.join(folder, "human-rows.json")
    if not os.path.isfile(human):
        return
    try:
        rows = json.loads(open(human, encoding="utf-8").read() or "[]")
    except json.JSONDecodeError:
        return
    if not isinstance(rows, list):
        return
    for row in rows:
        if not isinstance(row, dict) or not row.get("human"):
            continue
        mark = str(row.get("n") or "")
        if mark and (f"{mark} ✅" in text or f"{mark} ❌" in text):
            continue
        raise CockpitError("review waits for open rows")


def reviewer_ready(pack, ticket: str) -> None:
    """A reviewer card waits while this ticket still has an open tester card."""
    from .kanban import board_cards

    for card in board_cards(pack["board"]):
        if card.get("ticket") != ticket:
            continue
        if not str(card.get("assignee") or "").startswith("tester"):
            continue
        if card.get("status") in ("done", "archived"):
            continue
        raise CockpitError("reviewer waits for the tester")


def archive_card(pack, card_id) -> dict:
    card_id = (card_id or "").strip()
    connection = _open(pack["board"])
    if connection is None:
        raise CockpitError(f"no card {card_id}")
    try:
        row = _task(connection, card_id)
        if row is None:
            raise CockpitError(f"no card {card_id}")
        _status(connection, card_id, "archived")
        connection.commit()
    finally:
        connection.close()
    return {"ok": True, "id": card_id, "out": f"archived {card_id}"}


def begin_change(pack, ticket: str, text: str, lane: str) -> dict:
    """Read the ticket, warm one free slot, then start the trace."""
    ticket = (ticket or "").strip()
    if not ticket:
        raise CockpitError("no ticket")
    from .halt import refuse

    refuse(ticket)
    folder = qa_of(ticket)
    os.makedirs(folder, exist_ok=True)
    read = os.path.join(folder, "ticket.md")
    write_text(read, (text or ticket).strip() + "\n")
    claimed = claim_slot(pack, ticket, lane)
    trace = os.path.join(folder, "trace.md")
    write_text(trace, f"trace after slot {claimed['slot']}\n")
    return {"read": read, "slot": claimed["slot"], "warm": claimed["warm"], "trace": trace}


def claim_slot(pack, ticket: str, lane: str) -> dict:
    """Warm the first free slot whose data is ready for the ticket, owned by the lane: intake's claim, and a release
    worker card's when its ticket holds no slot yet."""
    from .slots import data_ready, free_slots, warm_slot

    count = int((pack.get("seats") or {}).get("slots") or 0)
    open_slots = free_slots(count)
    if not open_slots:
        raise CockpitError("no free slot")
    free = [slot for slot in open_slots if data_ready(pack, slot) == "ready"]
    if not free:
        raise CockpitError(data_ready(pack, open_slots[0]))
    slot = free[0]
    return {"slot": slot, "warm": warm_slot(slot, ticket, lane, pack)}


def finish_intake(pack, card_id, proposal) -> dict:
    """Write the proposal and block the intake card for go. Product files and publish stay untouched."""
    text = (proposal or "").strip()
    if not text:
        raise CockpitError("the proposal is empty")
    card_id = (card_id or "").strip()
    connection = _open(pack["board"])
    if connection is None:
        raise CockpitError(f"no card {card_id}")
    try:
        row = _task(connection, card_id)
        if row is None:
            raise CockpitError(f"no card {card_id}")
        title = row["title"] if "title" in row.keys() else ""
        assignee = row["assignee"] if "assignee" in row.keys() else ""
        if not str(assignee).startswith("intake") and ": intake" not in str(title):
            raise CockpitError("not an intake card")
        from .kanban import ticket_of

        ticket = ticket_of(title or "")
        if not ticket:
            raise CockpitError("no ticket")
        from .halt import refuse

        refuse(ticket)
        folder = qa_of(ticket)
        os.makedirs(folder, exist_ok=True)
        path = os.path.join(folder, "proposal.md")
        write_text(path, text + "\n")
        _comment(connection, card_id, "intake", "waiting for go")
        _status(connection, card_id, "blocked", "waiting for go")
        connection.commit()
    finally:
        connection.close()
    return {"ok": True, "blocked": True, "proposal": path, "published": ""}


def halt_ticket(pack, ticket, note="") -> list:
    """Marker first. Open cards close, a bound slot is reclaimed, and pending intents are held. The checkout stays until archive."""
    from .intents import all_intents
    from .outbox import hold

    write(ticket, note)
    lines = [f"halted {ticket}" + (f" ({note})" if note else "")]
    reason = f"Human: halted {ticket}" + (f" — {note}" if note else "")
    connection = _open(pack["board"])
    if connection is not None:
        try:
            for card in board_cards(pack["board"]):
                if card["ticket"] != ticket or card["status"] in ("done", "archived"):
                    continue
                _comment(connection, card["id"], "human", reason)
                _status(connection, card["id"], "done", reason)
                from .kanban import mark_card

                mark_card(pack["board"], card["id"], ended_by="owner")
                lines.append(f"closed {card['id']}")
            connection.commit()
        finally:
            connection.close()
    for intent in all_intents(ticket):
        if intent.get("status") not in ("pending", "endorsed"):
            continue
        hold(intent["id"], "halted by the human: decide drop or return")
        lines.append(f"held {intent['id']}")
    for slot in free_ticket_slots(pack, ticket):
        lines.append(f"reclaimed slot {slot}")
    from .repo_gates import stop_gate

    stopped = stop_gate(ticket)
    if stopped:
        lines.append(f"reclaimed gate {stopped}")
    from .chat import end_chat

    if end_chat(ticket):
        lines.append("reclaimed chat")
    return lines


def resume_ticket(ticket) -> str:
    """Lift the halt. Closed cards stay closed. Continue is a separate new card."""
    if clear(ticket):
        return f"resumed {ticket}"
    return f"{ticket} was not halted"


@one_at_a_time
def continue_ticket(
    pack, ticket: str, prompt: str, evidence=None, kind: str = "reopen", repos=None, chain: bool = True
) -> dict:
    """A new Reopen card, or Rework cards: one per repo (the named ones, else those the ticket has a checkout of), each
    with a tester and a reviewer behind it. It does not reopen a card that already closed."""
    from .halt import describe, halted
    from .kanban import board_cards, open_cards
    from .lanes import free_lane

    ticket = (ticket or "").strip()
    if not ticket:
        raise CockpitError("no ticket")
    marker = halted(ticket)
    if marker:
        raise Conflict(describe(ticket, marker))
    text = (prompt or "").strip()
    if not text:
        raise CockpitError("continue needs the new details")
    paths = evidence or []
    if isinstance(paths, str):
        paths = [paths]
    if not isinstance(paths, list):
        raise CockpitError("evidence must be a list")
    mode = "rework" if kind == "rework" else "reopen"
    closed = [
        card["id"]
        for card in board_cards(pack["board"])
        if card.get("ticket") == ticket and card.get("status") in ("done", "archived")
    ]
    if mode == "rework":
        title = card_title("rework", ticket, pack=pack)
        lane = free_lane("worker", pack, open_cards(pack["board"]), ticket=ticket)
        status = "ready"
    else:
        title = card_title("reopened", ticket, pack=pack)
        lane = free_lane("intake", pack, open_cards(pack["board"]))
        status = "ready"  # intake proposes first, then blocks for go
    folder = qa_of(ticket)
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, f"{mode}.md")
    body = text + "\n"
    if paths:
        body += "\n".join(f"evidence: {item}" for item in paths) + "\n"
    write_text(path, body)
    card_body = REOPEN_BODY[mode].format(
        ticket=ticket, text=text, path=path, evidence="\n".join(f"- {item}" for item in paths) or "- none attached"
    )
    made = []
    if mode == "rework":
        try:
            made = _rework_per_repo(pack, ticket, title, card_body, text, repos, chain)
        except CockpitError as exc:
            # Hermes closes the board to a command a lane runs itself, so the cards cannot be made from here. The
            # request is kept and the housekeeping makes them on its next pass (rework_queued), as it does for a
            # returned intent's card; the lane is told so instead of "failed".
            if not os.environ.get("COCKPIT_LANE") or "helper failed" not in str(exc):
                raise
            _queue_rework(
                {
                    "ticket": ticket,
                    "title": title,
                    "body": card_body,
                    "instruction": text,
                    "repos": list(repos or []),
                    "chain": bool(chain),
                }
            )
            return {
                "ok": True,
                "queued": True,
                "card_id": "",
                "title": title,
                "status": status,
                "lane": "",
                "path": path,
                "closed": closed,
                "cards": [],
                "reopened": [],
                "out": f"rework {ticket} is queued: the board is closed to a lane's own command, the housekeeping makes the "
                "card(s) within a minute",
            }
        card_id, lane = made[0]["card"], made[0]["lane"]
    else:
        card_id = _reopen_card(pack, ticket, title, lane, status, card_body)
    stayed = [
        card["id"]
        for card in board_cards(pack["board"])
        if card["id"] in closed and card.get("status") in ("done", "archived")
    ]
    retired = _retire_done_rows(pack, ticket, card_id, mode)
    return {
        "ok": True,
        "card_id": card_id,
        "title": title,
        "status": status,
        "lane": lane,
        "path": path,
        "closed": stayed,
        "cards": made,
        "reopened": retired,
        "out": f"{mode} {ticket}" + (f"; {', '.join(retired)} reopened" if retired else ""),
    }


def _retire_done_rows(pack, ticket: str, card: str, kind: str) -> list:
    """A reopen or a rework ends the wait for the human's "done" ack: every ticket-done of the ticket still pending or
    acknowledged moves to `reopened` (the state the intents table already had for it, which nothing set), so its Inbox row
    leaves with the work that reopened it. The PR watch writes a fresh row once the reopened work is merged and nothing is
    open (pr_watch._covered reads a reopened row as covering nothing)."""
    from .intents import advance, all_intents, save
    from .store import log
    from .time_util import iso

    moved = []
    for intent in all_intents(ticket):
        if intent.get("type") != "ticket-done" or intent.get("status") not in ("pending", "acknowledged"):
            continue
        advance(intent, "reopened", f"{kind} card {card}")
        intent["reopened"] = {"card": card, "kind": kind, "time": iso()}
        save(intent)
        log(f"REOPENED {intent['id']} by {kind} card {card}")
        if (pack.get("outbox") or {}).get("comment_card") and intent.get("card_id"):
            note_card(
                pack,
                intent["card_id"],
                "cockpit",
                f"{intent['id']}: {ticket} was {'reworked' if kind == 'rework' else 'reopened'} "
                f"on card {card}; a new done row follows the next merge",
            )
        moved.append(intent["id"])
    return moved


def _rework_queue_path() -> str:
    from .paths import watch_dir

    return os.path.join(watch_dir(), "rework-queue.json")


def _queue_rework(request: dict) -> None:
    from .store import read_json, write_json

    waiting = [row for row in (read_json(_rework_queue_path()) or []) if isinstance(row, dict)]
    waiting.append(request)
    write_json(_rework_queue_path(), waiting)


def rework_queued(pack) -> str:
    """Make the rework cards a lane asked for while the board was closed to its command. A request that fails again
    stays queued, with what the board said, and is tried on the next pass."""
    from .store import log, read_json, write_json

    waiting = [row for row in (read_json(_rework_queue_path()) or []) if isinstance(row, dict)]
    if not waiting:
        return "0"
    left, made = [], 0
    for row in waiting:
        try:
            cards = _rework_per_repo(
                pack,
                row["ticket"],
                row["title"],
                row["body"],
                row["instruction"],
                row.get("repos") or None,
                bool(row.get("chain", True)),
            )
            _retire_done_rows(pack, row["ticket"], cards[0]["card"], "rework")
            log(f"REWORK-QUEUED {row['ticket']} → {' '.join(card['card'] for card in cards)}")
            made += 1
        except (CockpitError, KeyError) as exc:
            left.append({**row, "error": str(exc)[-200:]})
    write_json(_rework_queue_path(), left)
    return str(made)


def _ticket_repos(pack, ticket: str) -> list:
    """The pack's repos the ticket has a checkout of, in the pack's order."""
    folder = worktree_of(ticket)
    present = set(os.listdir(folder)) if os.path.isdir(folder) else set()
    return [repo["name"] for repo in pack["repos"]["repos"] if repo.get("name") in present]


def _reopen_card(pack, ticket: str, title: str, lane: str, status: str, body: str) -> str:
    """The card a reopened ticket starts on. One still open is the answer: a reopen sent twice makes one card."""
    from .kanban import open_twin, place_card

    twin = open_twin(pack["board"], "reopened", ticket, title=title)
    if twin:
        raise Conflict(f"already open: card {twin}")
    return place_card(pack["board"], title, lane, status, body=body, kind="reopened", ticket=ticket, pack=pack)


@one_at_a_time
def _rework_per_repo(
    pack, ticket: str, title: str, body: str, instruction: str, repos=None, chain: bool = True
) -> list:
    """One worker card per repo with the pack's rework skills and the repo's, then its tester and reviewer. The same
    instruction for the same repo, asked again while its card is open, gets that card and its chain back: a request sent
    twice starts the work once. Another instruction is another card, as a lane's own rework beside a CI rework is."""
    import hashlib

    from .gate import _chain
    from .kanban import card_skills, open_cards, place_card
    from .lanes import free_lane

    known = {repo["name"] for repo in pack["repos"]["repos"]}
    named = [str(repo) for repo in (repos or []) if str(repo).strip()]
    unknown = [repo for repo in named if repo not in known]
    if unknown:
        raise CockpitError(f"{unknown[0]} is not a repo of this pack")
    chosen = named or _ticket_repos(pack, ticket) or [""]
    asked = hashlib.sha256(f"{instruction}\0{body}".encode()).hexdigest()[:16]
    made = []
    for repo in chosen:
        lane = free_lane("worker", pack, open_cards(pack["board"]), ticket=ticket)
        named_title = f"{title} ({repo})" if repo and len(chosen) > 1 else title
        card = place_card(
            pack["board"],
            named_title,
            lane,
            "ready",
            body=body + (f"\nRepo: {repo}\n" if repo else ""),
            skills=card_skills(pack, "rework", repos=[repo] if repo else []),
            kind="rework",
            ticket=ticket,
            pack=pack,
            repos=[repo] if repo else [],
            idempotency_key=f"rework-{ticket}-{repo}-{asked}",
        )
        behind = _chain(pack, {"ticket": ticket, "payload": {"repo": repo}}, card, instruction) if chain else []
        made.append({"repo": repo, "card": card, "lane": lane, "chain": behind})
    return made


REOPEN_BODY = {
    "rework": "Rework {ticket}.\n\n## Instruction\n{text}\n\n## Evidence\n{evidence}\n\nThe same text is in {path}.\n",
    "reopen": "{ticket} is reopened.\n\n## What changed\n{text}\n\n## Evidence\n{evidence}\n\nThe same text is in {path}. Read the "
    "plan, propose what changes, then block for go.\n",
}
CI_REAL_BODY = """CI failed for a real reason on {ticket}{where}.

Read the analyst's card and the failed run, propose the fix as a plan change, then block for go.
"""


def _provider(pack):
    from .slots import provider_for

    return provider_for(pack.get("slot_provider"), pack)


def refuse_busy(pack, ticket) -> None:
    provider = _provider(pack)
    for row in provider.status(count=max(1, pack["seats"]["slots"])):
        if row.get("ticket") == ticket and row.get("owner") == "human":
            raise Conflict(f"slot {row['slot']} is a manual session on {ticket}: close it first")
    for card in board_cards(pack["board"]):
        if card["ticket"] == ticket and card["status"] in RUNNING:
            raise Conflict(f"card {card['id']} is {card['status']}: wait for it or block it first")


def free_ticket_slots(pack, ticket) -> list:
    from .slots import clear_release_claim, stop_slot_runtime, write_owner, write_ticket

    provider = _provider(pack)
    freed = []
    for row in provider.status(count=max(1, pack["seats"]["slots"])):
        if row.get("ticket") != ticket:
            continue
        stop_slot_runtime(row["slot"])
        provider.down(row["slot"])
        write_owner(row["slot"], "free")
        write_ticket(row["slot"], "")
        clear_release_claim(row["slot"])
        freed.append(row["slot"])
    return freed


def snapshot(pack, ticket) -> list:
    found = []
    prefix = pack.get("branch_prefix") or "work"
    for path in list_worktrees(ticket):
        branch = _git(path, ["rev-parse", "--abbrev-ref", "HEAD"]).stdout.strip() or "HEAD"
        count = _git(path, ["rev-list", "--count", "HEAD", "--not", "--remotes"]).stdout.strip()
        dirty = _git(path, ["status", "--porcelain"]).stdout
        repo = os.path.basename(path)
        try:
            source = repo_source(pack, repo)
        except CockpitError:
            source = path
        found.append(
            {
                "repo": repo,
                "path": path,
                "branch": branch,
                "unpushed": int(count) if count.isdigit() else 0,
                "dirty": len([line for line in dirty.splitlines() if line.strip()]),
                "source": source,
                "inplace": False,
            }
        )
    for repo in pack["repos"]["repos"]:
        name = repo.get("name") or ""
        if not name:
            continue
        try:
            source = repo_source(pack, name)
        except CockpitError:
            continue
        branch = f"{prefix}/{ticket}"
        if _git(source, ["rev-parse", "--verify", "--quiet", branch]).returncode != 0:
            continue
        count = _git(source, ["rev-list", "--count", branch, "--not", "--remotes"]).stdout.strip()
        found.append(
            {
                "repo": name,
                "path": source,
                "branch": branch,
                "unpushed": int(count) if count.isdigit() else 0,
                "dirty": 0,
                "source": source,
                "inplace": True,
            }
        )
    return found


def remove_worktrees(pack, ticket) -> list:
    """Every checkout of the ticket, then its folder. The name is one folder under the worktree root (the collector
    passes whatever folder it listed), never a path out of it."""
    base = inside(wt(), ticket, what="ticket")
    removed = []
    for path in list_worktrees(ticket):
        repo = os.path.basename(path)
        try:
            source = repo_source(pack, repo)
        except CockpitError:
            source = ""
        if source:
            _git(source, ["worktree", "remove", "--force", path])
        if os.path.isdir(path):
            shutil.rmtree(path)
        removed.append(path)
    if os.path.isdir(base):
        try:
            os.rmdir(base)
        except OSError:
            shutil.rmtree(base, ignore_errors=True)
    return removed


def drop_branches(snap, force) -> tuple:
    kept = []
    deleted = []
    for item in snap:
        branch = item["branch"]
        source = item.get("source") or item["path"]
        if branch in ("", "HEAD"):
            kept.append(f"{item['repo']}: detached")
            continue
        if item["unpushed"] and not force:
            kept.append(branch)
            continue
        current = _git(source, ["rev-parse", "--abbrev-ref", "HEAD"]).stdout.strip()
        if current == branch and not force:
            kept.append(branch)
            continue
        if current == branch:
            _git(source, ["checkout", "--detach"])
        result = _git(source, ["branch", "-D", branch])
        if result.returncode == 0:
            deleted.append(branch)
            continue
        kept.append(branch)
    return kept, deleted


def archive_ticket(pack, ticket) -> dict:
    check_ticket(ticket, (pack or {}).get("ticket_pattern"))
    refuse_busy(pack, ticket)
    ids = archive_ticket_cards(pack["board"], ticket)
    removed = remove_worktrees(pack, ticket)
    freed = free_ticket_slots(pack, ticket)
    end_chat(ticket)
    return {
        "ok": True,
        "out": f"archived {ticket}",
        "cards": ids,
        "worktrees": removed,
        "slots": freed,
        "kept": ["outbox", "qa", "branches"],
    }


def delete_ticket(pack, ticket, force=False) -> dict:
    """The ticket's checkouts, branches, cards and records go. Only a ticket key names what goes: the two record
    folders are the key's own, under the records, before anything is touched."""
    folders = (ticket_folder(qa(), ticket, pack), ticket_folder(outbox(), ticket, pack))
    snap = snapshot(pack, ticket)
    refuse_busy(pack, ticket)
    remove_worktrees(pack, ticket)
    kept, deleted = drop_branches(snap, force)
    ids = delete_ticket_cards(pack["board"], ticket)
    for folder in folders:
        if os.path.isdir(folder):
            shutil.rmtree(folder)
    end_chat(ticket)
    free_ticket_slots(pack, ticket)
    return {"ok": True, "out": f"deleted {ticket}", "cards": ids, "kept": kept, "deleted": deleted}


def describe_ticket(pack, ticket) -> dict:
    trees = []
    for item in snapshot(pack, ticket):
        trees.append(
            {
                "repo": item["repo"],
                "branch": item["branch"],
                "unpushed": item["unpushed"],
                "dirty": item["dirty"],
                "dir": item["path"],
            }
        )
    slot = None
    for row in _provider(pack).status(count=max(1, pack["seats"]["slots"])):
        if row.get("ticket") == ticket:
            slot = {"slot": row["slot"], "owner": row.get("owner") or ""}
    folder = qa_of(ticket)
    runs = []
    size = 0
    plan = os.path.join(folder, "plan.md")
    sections = []
    if os.path.isdir(folder):
        from .test_flow import run_folders

        runs = run_folders(pack, folder)
        for dirpath, _dirs, files in os.walk(folder):
            for name in files:
                try:
                    size += os.path.getsize(os.path.join(dirpath, name))
                except OSError:
                    continue
        if os.path.isfile(plan):
            sections = [line[3:].strip() for line in open(plan, encoding="utf-8") if line.startswith("## ")]
    prs = []
    pr_dir = os.path.join(folder, "pr")
    if os.path.isdir(pr_dir):
        for name in sorted(os.listdir(pr_dir)):
            if not name.endswith(".json"):
                continue
            try:
                record = json.load(open(os.path.join(pr_dir, name), encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if isinstance(record, dict) and "number" in record:
                prs.append(
                    dict(
                        record,
                        closed=bool(record.get("merged")) or str(record.get("state") or "open").lower() != "open",
                    )
                )
    prs.sort(key=lambda row: (row["closed"], str(row.get("repo") or ""), str(row.get("number"))))  # by repo, open first
    return {
        "worktrees": trees,
        "slot": slot,
        "qa": {
            "runs": len(runs),
            "size": size,
            "dir": folder if os.path.isdir(folder) else None,
            "plan": plan if os.path.isfile(plan) else None,
            "plan_sections": sections,
        },
        "prs": prs,
    }


def fetch_ref(pack, repo_name, branch, ticket="") -> dict:
    folder = ""
    if ticket:
        candidate = dest(ticket, repo_name)
        if os.path.isdir(os.path.join(candidate, ".git")) or os.path.isfile(os.path.join(candidate, ".git")):
            folder = candidate
    if not folder:
        folder = repo_source(pack, repo_name)
    from .git_push import repo_branch

    ref = branch or repo_branch(pack, repo_name)
    remotes = _git(folder, ["remote"]).stdout.split()
    if "origin" not in remotes:
        return {"ok": False, "fetched": False, "out": f"no origin in {folder}", "repo": repo_name}
    result = _git(folder, ["fetch", "origin", ref])
    out = (result.stderr or result.stdout or "").strip()
    return {
        "ok": result.returncode == 0,
        "fetched": result.returncode == 0,
        "out": out or f"fetch {repo_name} {ref}",
        "repo": repo_name,
    }


def _read(path):
    if not os.path.isfile(path):
        return {}
    try:
        data = json.load(open(path, encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _write(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    dump_json(path, data)


def _login(pr) -> str:
    author = pr.get("author") or {}
    if isinstance(author, str):
        return author.lower()
    return (author.get("login") or "").lower()


def _files(pr) -> list:
    found = []
    for item in pr.get("files") or []:
        if isinstance(item, str):
            found.append(item)
            continue
        if isinstance(item, dict):
            found.append(item.get("path") or item.get("filename") or "")
    return [item for item in found if item]


def is_bump(pr) -> bool:
    login = _login(pr)
    head = pr.get("headRefName") or pr.get("head") or ""
    if any(bot in login for bot in BOTS):
        return True
    return head.startswith(("dependabot/", "renovate/"))


def taken_over(pr, pack, repo_default) -> bool:
    """A person already took the bump: the title has a ticket key, or it was retargeted onto the integration branch."""
    title = pr.get("title") or ""
    pattern = pack.get("ticket_pattern") or r"[A-Z][A-Z0-9]*-[0-9A-Z]+"
    loose = pattern[1:] if pattern.startswith("^") else pattern
    if loose.endswith("$"):
        loose = loose[:-1]
    if loose and re.search(loose, title):
        return True
    base = pr.get("baseRefName") or pr.get("base") or ""
    integration = pack.get("base_branch") or ""
    return bool(repo_default and integration and repo_default != integration and base == integration)


def _bound_forge():
    """The bound pack's forge, for a read that is handed an organisation and no pack; GitHub when no pack is bound."""
    from .forges import make

    try:
        from .pack import load
        from .paths import pack_path

        return make(load(pack_path()))
    except Exception:  # noqa: BLE001 - no workspace, or a pack that does not load: the read still names its forge
        return make({})


def list_prs(org, repo, state, runner=None, base="") -> list:
    return _bound_forge().list_prs(f"{org}/{repo}", state, base=base, runner=runner)


def _bump_row(pr) -> dict:
    return {
        "number": pr.get("number"),
        "title": pr.get("title") or "",
        "head": pr.get("headRefName") or "",
        "base": pr.get("baseRefName") or "",
        "sha": pr.get("headRefOid") or "",
        "url": pr.get("url") or "",
    }


def bumps_path() -> str:
    return os.path.join(platform_dir(), "bumps.json")


def scan_bumps(pack, runner=None) -> str:
    previous = _read(bumps_path())
    org = forge_org(pack)
    repos = {}
    errors = []
    from .pack import bump_scanned, shipped

    for repo in pack["repos"]["repos"]:
        name = repo.get("name") or ""
        if not name or not bump_scanned(repo):  # a repo the bump scan leaves out (repos.yaml bumps, else watched)
            continue
        if ((pack.get("forge") or {}).get("bumps_shipped_only")) and not shipped(repo):  # only the products we ship
            continue
        try:
            listed = list_prs(org, name, "open", runner=runner)
        except ForgeError as exc:
            errors.append(f"{name}: {exc}")
            repos[name] = (previous.get("repos") or {}).get(name) or []
            continue
        graduated = set()
        for item in _read(_graduated_path()).get("prs") or []:
            if not isinstance(item, dict):
                continue
            if item.get("repo") and item.get("number"):
                graduated.add((item.get("repo"), item.get("number")))
        found = []
        for pr in listed:
            if (name, pr.get("number")) in graduated:
                continue
            if is_bump(pr) and not taken_over(pr, pack, repo.get("base") or ""):
                found.append(_bump_row(pr))
        repos[name] = found
    record = {
        "time": int(time.time()),
        "repos": repos,
        "dismissed": previous.get("dismissed") or {},
        "started": previous.get("started") or {},
        "errors": errors,
    }
    _write(bumps_path(), record)
    if errors:
        return "forge " + "; ".join(errors)
    graduate_bumps(pack)
    return f"bumps {sum(len(rows) for rows in repos.values())}"


def _open_bump(data, repo, pr) -> bool:
    """A dismissed pull request stays hidden until its head changes."""
    key = f"{repo}#{pr.get('number')}"
    dismissed = (data.get("dismissed") or {}).get(key)
    current = str(pr.get("sha") or "")
    if dismissed == "dismissed" and not current:
        return False
    if dismissed and dismissed != "dismissed" and (not current or dismissed == current):
        return False
    started = (data.get("started") or {}).get(key) or {}
    if started.get("sha") and started.get("sha") == current:
        return False
    return True


def started_bumps(pack=None) -> dict:
    """Pull requests a card is working on right now. Release returns these to the candidates. A card that ended keeps
    its PRs out of the candidates until their head moves (an approved bump waits for the human's merge, not for a
    second card), and makes no row."""
    data = _read(bumps_path()) or {}
    closed_cards = set()
    if pack is not None:
        from .kanban import board_cards

        closed_cards = {
            card["id"]
            for card in board_cards(pack["board"], pack)
            if (card.get("status") or "") in ("done", "archived", "cancelled")
        }
    repos = {}
    for name, rows in (data.get("repos") or {}).items():
        held = []
        for row in rows or []:
            if not isinstance(row, dict):
                continue
            key = f"{name}#{row.get('number')}"
            started = (data.get("started") or {}).get(key) or {}
            if not started.get("card") or str(started.get("sha") or "") != str(row.get("sha") or ""):
                continue
            if started["card"] in closed_cards:
                continue
            held.append(dict(row, card=started.get("card")))
        if held:
            repos[name] = held
    return repos


def visible_bumps(pack=None) -> dict:
    data = _read(bumps_path()) or {"time": None, "repos": {}}
    repos = {}
    for name, rows in (data.get("repos") or {}).items():
        shown = [row for row in rows if _open_bump(data, name, row)]
        if shown:
            repos[name] = shown
    data["repos"] = repos
    return data


def dismiss_bumps(pack, repo, numbers) -> dict:
    if not repo or not numbers:
        raise CockpitError("repo and PR numbers")
    data = _read(bumps_path())
    data.setdefault("repos", {})
    data.setdefault("dismissed", {})
    by_number = {row.get("number"): row for row in data["repos"].get(repo) or []}
    dismissed = []
    for number in numbers:
        try:
            key_number = int(number)
        except (TypeError, ValueError):
            continue
        row = by_number.get(key_number) or {}
        data["dismissed"][f"{repo}#{key_number}"] = row.get("sha") or "dismissed"
        dismissed.append(key_number)
    _write(bumps_path(), data)
    return {"ok": True, "repo": repo, "dismissed": dismissed}


def release_bumps(repo, numbers) -> dict:
    data = _read(bumps_path())
    started = data.get("started") or {}
    for number in numbers:
        started.pop(f"{repo}#{number}", None)
    data["started"] = started
    _write(bumps_path(), data)
    return {"ok": True, "repo": repo}


def record_grooming(pack, repo: str, number, act: str) -> dict:
    """Record one grooming act from this pack. A complete set leaves the bump flow."""
    name = str(repo or "").strip()
    label = str(act or "").strip()
    allowed = [str(item) for item in (pack or {}).get("grooming") or []]
    if not name or label not in allowed:
        raise CockpitError("not a grooming act")
    try:
        parsed = int(number)
    except (TypeError, ValueError):
        raise CockpitError("not a grooming act") from None
    data = _read(bumps_path())
    started = data.get("started") if isinstance(data.get("started"), dict) else {}
    key = f"{name}#{parsed}"
    row = started.get(key)
    if not isinstance(row, dict):
        raise CockpitError("that pull request is not in this flow")
    acts = [str(item) for item in (row.get("acts") or []) if str(item) in allowed]
    if label not in acts:
        acts.append(label)
    row["acts"] = acts
    started[key] = row
    data["started"] = started
    _write(bumps_path(), data)
    left = graduate_bumps(pack)
    return {"ok": True, "repo": name, "number": parsed, "acts": acts, "graduated": key in left}


def derive_grooming(pack) -> list:
    """The grooming acts the published intents prove, per the pack's rules; a human's tick stays. [(pr, act)]."""
    from .intents import all_intents

    rules = (pack or {}).get("grooming_rules") or []
    data = _read(bumps_path())
    started = data.get("started") if isinstance(data.get("started"), dict) else {}
    if not rules or not started:
        return []
    published = [row for row in all_intents() if str(row.get("status")).startswith("published")]
    found = []
    for key, row in started.items():
        repo, _, number = key.partition("#")
        acts = list(row.get("acts") or [])
        for rule in rules:
            if rule["name"] in acts:
                continue
            for intent in published:
                payload = intent.get("payload") or {}
                same = payload.get("repo") == repo and (
                    str(payload.get("number") or "") == number
                    or (row.get("head") and (payload.get("publish_as") or payload.get("head")) == row.get("head"))
                )
                if not same or intent["type"] != rule["intent"]:
                    continue
                if rule["field"] and payload.get(rule["field"]) in (None, "", [], False):
                    continue
                if rule["event"] and payload.get("event") != rule["event"]:
                    continue
                acts.append(rule["name"])
                row.setdefault("proved_by", {})[rule["name"]] = intent["id"]
                found.append((key, rule["name"]))
                break
        row["acts"] = acts
    if found:
        _write(bumps_path(), data)
    return found


def audit_bumps(pack) -> dict:
    """Report grooming acts that are missing. The names come from the pack. This does not open a card."""
    derive_grooming(pack)
    required = list((pack or {}).get("grooming") or [])
    data = _read(bumps_path())
    missing = []
    for key, row in (data.get("started") or {}).items():
        have = set(row.get("acts") or [])
        gap = [name for name in required if name not in have]
        if gap:
            missing.append({"pr": key, "missing": gap})
    report = {"missing": missing}
    _write(os.path.join(platform_dir(), "bumps-audit.json"), report)
    return report


def bump_card(repo, numbers) -> str:
    """The card that already accepted this head. Empty when a new accept may open one."""
    if not repo:
        return ""
    data = _read(bumps_path())
    by_number = {row.get("number"): row for row in (data.get("repos") or {}).get(repo) or []}
    chosen = numbers or list(by_number)
    for number in chosen:
        try:
            key_number = int(number)
        except (TypeError, ValueError):
            continue
        row = by_number.get(key_number) or {}
        previous = ((data.get("started") or {}).get(f"{repo}#{key_number}")) or {}
        if previous.get("card") and previous.get("sha") == (row.get("sha") or ""):
            return str(previous.get("card") or "")
    return ""


def take_bumps(pack, repo, card_id, numbers) -> None:
    if not repo:
        return
    data = _read(bumps_path())
    data.setdefault("started", {})
    data.setdefault("repos", {})
    by_number = {row.get("number"): row for row in data["repos"].get(repo) or []}
    chosen = numbers or list(by_number)
    for number in chosen:
        try:
            key_number = int(number)
        except (TypeError, ValueError):
            continue
        row = by_number.get(key_number) or {}
        key = f"{repo}#{key_number}"
        previous = (data.get("started") or {}).get(key) or {}
        if previous.get("card") and previous.get("card") != card_id and previous.get("sha") == (row.get("sha") or ""):
            raise CockpitError(f"already started on {previous.get('card')}")
        data["started"][key] = {
            "sha": row.get("sha") or "",
            "card": card_id,
            "head": row.get("head") or "",
            "acts": previous.get("acts") or [],
        }
    _write(bumps_path(), data)


def segment_glob(pattern: str):
    """A path glob in which * and ? stay inside one path segment and ** crosses segments."""
    parts = []
    index = 0
    while index < len(pattern):
        if pattern.startswith("**/", index):
            parts.append("(?:.*/)?")
            index += 3
        elif pattern.startswith("**", index):
            parts.append(".*")
            index += 2
        elif pattern[index] in "*?":
            parts.append("[^/]*" if pattern[index] == "*" else "[^/]")
            index += 1
        else:
            parts.append(re.escape(pattern[index]))
            index += 1
    return re.compile("^" + "".join(parts) + "$")


def _anchor_hit(pattern, filename) -> bool:
    """An anchor names a folder (everything under it) or a glob matched segment by segment."""
    stem = pattern.rstrip("/")
    for tail in ("/**", "/*"):
        if stem.endswith(tail):
            stem = stem[: -len(tail)]
            break
    if any(mark in stem for mark in "*?"):
        return bool(segment_glob(pattern.rstrip("/")).match(filename) or segment_glob(stem + "/**").match(filename))
    return filename == stem or filename.startswith(stem + "/")


def attribute(pack, repo_name, files) -> list:
    from .map_build import compiled_tree

    tree = compiled_tree(pack) or {"nodes": []}
    found = []
    for node in tree.get("nodes") or []:
        for anchor in node.get("anchors") or []:
            if anchor.get("repo") != repo_name:
                continue
            for pattern in anchor.get("paths") or []:
                if any(_anchor_hit(pattern, filename) for filename in files):
                    found.append(node["id"])
    return sorted(set(found))


def ordered_changes(fallback=None) -> list:
    """Unseen relevant changes come first. The page reads this order."""
    folder = changes_dir()
    rows = []
    if os.path.isdir(folder):
        for name in sorted(os.listdir(folder)):
            if not name.endswith(".json"):
                continue
            row = _read(os.path.join(folder, name))
            if isinstance(row, dict) and row.get("repo"):
                rows.append(row)
    if not rows:
        rows = [row for row in (fallback or []) if isinstance(row, dict)]

    def rank(row):
        seen = bool(row.get("seen"))
        status = row.get("status") or ""
        if not seen and status == "relevant":
            group = 0
        elif not seen and status != "skipped":
            group = 1
        elif status == "relevant":
            group = 2
        else:
            group = 3
        try:
            number = int(row.get("number") or 0)
        except (TypeError, ValueError):
            number = 0
        return (group, str(row.get("merged_at") or ""), str(row.get("repo") or ""), number)

    return sorted(rows, key=rank)


def changes_dir() -> str:
    return os.path.join(platform_dir(), "changes")


def _cursor_path() -> str:
    return os.path.join(platform_dir(), "base-cursor.json")


def scan_base(pack, runner=None, days=7, now=None) -> str:
    from .pack import watched

    """PRs merged onto the base branch since the last scan of each repo, attributed to map anchors. Bumps, bots and
    noise-only changes are skipped. Each change gets one analyst card, on the platform ticket, so it is on the board."""
    import datetime

    org = forge_org(pack)
    base = pack.get("base_branch") or "main"
    bots = tuple((pack.get("forge") or {}).get("bots") or ())
    moment = datetime.datetime.fromtimestamp(time.time() if now is None else now, datetime.UTC)
    first_since = (moment - datetime.timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")
    cursors = _read(_cursor_path())
    changes = []
    errors = []
    for repo in pack["repos"]["repos"]:
        name = repo.get("name") or ""
        if not name or not watched(repo):  # not this forge's, or not a repo the watches read
            continue
        try:
            listed = list_prs(
                org, name, "merged", runner=runner, base=repo.get("watch_base") or repo.get("base") or base
            )
        except ForgeError as exc:
            errors.append(f"{name}: {exc}")
            continue
        since = cursors.get(name) or first_since
        newest = since
        for pr in listed:
            merged_at = str(pr.get("mergedAt") or pr.get("createdAt") or "")
            if merged_at and merged_at <= since:
                continue
            newest = max(newest, merged_at)
            number = pr.get("number")
            path = os.path.join(changes_dir(), f"{name}-{number}.json")
            previous = _read(path)
            files = _files(pr)
            nodes = attribute(pack, name, files)
            login = _login(pr)
            if is_bump(pr) or login.endswith("[bot]") or login in bots:
                status = "skipped"
            elif _noise_only(files, pack):
                status = "skipped"
            elif nodes:
                status = "relevant"
            else:
                status = "unmapped"
            record = {
                "repo": name,
                "number": number,
                "title": pr.get("title") or "",
                "author": login,
                "url": str(pr.get("url") or ""),
                "body": str(pr.get("body") or ""),
                "merged_at": merged_at,
                "files": files,
                "nodes": nodes,
                "status": status,
                "seen": bool(previous.get("seen")),
                "base": base,
                "days": days,
                "card": previous.get("card") or "",
            }
            if previous.get("verdict") not in (None, "", {}, []):
                record["verdict"] = previous["verdict"]
            if status != "skipped" and not record["seen"] and not record["card"]:
                record["card"] = open_analyst(
                    pack,
                    "base",
                    f"{batch_project(pack)}-PLATFORM",
                    repos=[name],
                    change=f"{name}#{number}",
                    url=record["url"],
                    files="\n".join(f"- {item}" for item in files[:30])
                    + (f"\n- … {len(files) - 30} more" if len(files) > 30 else ""),
                )
            _write(path, record)
            changes.append(record)
        cursors[name] = newest
    _write(_cursor_path(), cursors)
    summary = {
        "repos": [repo.get("name") for repo in pack["repos"]["repos"] if repo.get("name")],
        "changes": changes,
        "errors": errors,
    }
    _write(os.path.join(platform_dir(), "base-watch.json"), summary)
    if errors:
        return "forge " + "; ".join(errors)
    return f"base-watch {len(changes)}"


def _copy_only(name: str) -> bool:
    """User-facing copy: translation files and copy, i18n, or locales trees."""
    low = name.lower()
    if low.endswith((".po", ".pot")):
        return True
    markers = ("/copy/", "/i18n/", "/locales/")
    if any(marker in low for marker in markers):
        return True
    return low.startswith(("copy/", "i18n/", "locales/"))


NOISE = (
    "**/test/**",
    "**/tests/**",
    "test/**",
    "tests/**",
    "docs/**",
    "**/docs/**",
    "*.md",
    "**/*.md",
    "*.txt",
    "**/*.txt",
    "*.rst",
    "**/*.rst",
)


def _noise_only(files, pack=None) -> bool:
    """Every file is noise: tests, docs, prose, copy, or a glob the pack adds (watchers.base.noise)."""
    if not files:
        return False
    globs = [
        segment_glob(glob)
        for glob in (*NOISE, *((((pack or {}).get("watchers") or {}).get("base") or {}).get("noise") or []))
    ]
    for name in files:
        if _copy_only(name.lower()) or any(glob.match(name) for glob in globs):
            continue
        return False
    return True


def write_verdict(repo, number, text: str) -> dict:
    """The analyst's verdict on one change. It does not open a card."""
    body = (text or "").strip()
    if not repo or not number:
        raise CockpitError("repo and number")
    if not body:
        raise CockpitError("verdict")
    path = within(changes_dir(), f"{repo}-{number}.json", "repo")
    record = _read(path)
    if not record:
        raise CockpitError("no change")
    record["verdict"] = body
    _write(path, record)
    return {"ok": True, "repo": repo, "number": number, "verdict": body}


def mark_seen(pack, repo, number, mark_all=False) -> dict:
    folder = changes_dir()
    names = []
    if mark_all and os.path.isdir(folder):
        names = [name for name in os.listdir(folder) if name.endswith(".json")]
    elif repo and number:
        names = [f"{repo}-{number}.json"]
        within(folder, names[0], "repo")
    else:
        raise CockpitError("repo and number")
    marked = []
    for name in names:
        path = os.path.join(folder, name)
        record = _read(path) or {"repo": repo, "number": number}
        record["seen"] = True
        _write(path, record)
        marked.append(name)
    return {"ok": True, "marked": marked, "repo": repo, "number": number}


def mark_unseen(repo, number, mark_all=False) -> dict:
    folder = changes_dir()
    names = []
    if mark_all and os.path.isdir(folder):
        names = [name for name in os.listdir(folder) if name.endswith(".json")]
    elif repo and number:
        names = [f"{repo}-{number}.json"]
        within(folder, names[0], "repo")
    else:
        raise CockpitError("repo and number")
    for name in names:
        path = os.path.join(folder, name)
        record = _read(path) or {"repo": repo, "number": number}
        record["seen"] = False
        _write(path, record)
    return {"ok": True, "repo": repo, "number": number}


def change_detail(repo, number) -> dict:
    path = within(changes_dir(), f"{repo}-{number}.json", "repo")
    record = _read(path)
    if not record:
        return {"repo": repo, "number": number, "diff": "", "seen": False}
    record.setdefault("diff", "")
    if not record.get("body_html") and record.get("body"):
        import html

        record["body_html"] = "<pre>" + html.escape(str(record["body"])[:20000]) + "</pre>"
    current = record.get("diff")
    if not (isinstance(current, dict) and current.get("diff")):
        from .pack import load
        from .paths import pack_path

        org = forge_org(load(pack_path())) or ""
        text = pr_diff_text(org, repo, number) if org else ""
        if text:
            record["diff"] = {"diff": text}
    return record


def diff_repo(source, paths) -> dict:
    if not os.path.isdir(os.path.join(source, ".git")) and not os.path.isfile(os.path.join(source, ".git")):
        return {"error": f"no local clone at {source}", "commits": [], "diff": ""}
    specs = []
    for pattern in paths:
        stem = pattern[:-3] if pattern.endswith("/**") else pattern
        specs.append(stem)
    log = _git(source, ["log", "--oneline", "-n", "20", "--", *specs])
    diff = _git(source, ["diff", "HEAD", "--", *specs])
    commits = (log.stdout if log.returncode == 0 else log.stderr).splitlines()
    text = diff.stdout if diff.returncode == 0 else diff.stderr
    return {"commits": commits, "diff": text, "error": ""}


def node_diff(pack, node_id, days=7) -> dict:
    from .map_build import compiled_tree

    tree = compiled_tree(pack) or {"nodes": []}
    node = next((item for item in tree.get("nodes") or [] if item["id"] == node_id), None)
    if node is None:
        return {"id": node_id, "days": days, "repos": [], "diff": ""}
    repos = []
    for anchor in node.get("anchors") or []:
        try:
            source = repo_source(pack, anchor.get("repo") or "")
        except CockpitError as exc:
            repos.append({"repo": anchor.get("repo") or "", "error": str(exc), "commits": [], "diff": ""})
            continue
        row = diff_repo(source, anchor.get("paths") or [])
        row["repo"] = anchor.get("repo") or ""
        repos.append(row)
    return {"id": node_id, "title": node.get("title") or node_id, "days": days, "repos": repos, "diff": ""}


def _pr_path(ticket, repo, number) -> str:
    """The watch record of that pull request. A ticket or a repository that is a path is refused."""
    return within(qa_of(segment(ticket, "ticket") if ticket else "", "pr"), f"{repo}-{number}.json", "repo")


def acknowledge_closed(pack) -> list:
    """A published end with no pull request is acknowledged once. A ticket that has a pull request is left."""
    from .intents import all_intents
    from .outbox import ack

    grouped = {}
    for intent in all_intents():
        ticket = intent.get("ticket") or ""
        if not ticket:
            continue
        grouped.setdefault(ticket, []).append(intent)
    done = []
    for ticket, intents in grouped.items():
        if any((item.get("payload") or {}).get("number") for item in intents):
            continue
        for intent in intents:
            if intent.get("type") != "ticket-done":
                continue
            if intent.get("status") != "published":
                continue
            ack(intent["id"])
            record = {"id": intent["id"], "pack": pack.get("name") or "", "why": "ended without a pull request"}
            folder = qa_of(ticket)
            os.makedirs(folder, exist_ok=True)
            _write(os.path.join(folder, "acknowledged.json"), record)
            done.append(intent["id"])
    return done


def pr_state(ticket, repo, number) -> dict:
    from .record_write import with_checked

    path = _pr_path(ticket, repo, number)
    return with_checked("pr", path, _read(path)) or {"ticket": ticket, "repo": repo, "number": number, "comments": []}


def forget_pr(ticket, repo, number) -> dict:
    """Delete the pull request's watch files. The ticket copy and the graduated copy both go."""
    if not ticket or not repo or not number:
        raise CockpitError("bad ticket/repo/number")
    removed = []
    for path in (
        _pr_path(ticket, repo, number),
        within(os.path.join(platform_dir(), "pr"), f"{repo}-{number}.json", "repo"),
    ):
        if os.path.isfile(path):
            os.remove(path)
            removed.append(path)
    return {"ok": True, "ticket": ticket, "repo": repo, "number": number, "removed": removed}


def compare_diff_text(org, repo, base, head, runner=None) -> str:
    """What changed between two commits of a repo, as the forge's unified diff: a re-review reads only what the author
    pushed since the review. Empty when the forge cannot compare them (a history rewritten since) or during tests."""
    if runner is not None:
        return runner(org, repo, base, head)
    if os.environ.get("PYTEST_CURRENT_TEST") or not (base and head):
        return ""
    return _bound_forge().compare_diff(f"{org}/{repo}", base, head)


def pr_diff_text(org, repo, number, runner=None) -> str:
    """The forge diff. A missing forge returns an empty body with no network during tests unless a file was stored."""
    stored = os.path.join(platform_dir(), f"pr-{repo}-{number}.diff")
    if os.path.isfile(stored):
        return open(stored, encoding="utf-8").read()
    if runner is not None:
        return runner(org, repo, number)
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return ""
    return _bound_forge().pr_diff(f"{org}/{repo}", number)


def checkout_diff(pack, ticket: str, repo: str) -> str:
    """The diff the forge would show for this checkout. Empty only when there is no checkout."""
    from .worktree import _checkout

    try:
        folder = _checkout(ticket, repo, pack)
    except CockpitError:
        return ""
    from .git_push import repo_branch

    base = repo_branch(pack, repo)
    probe = subprocess.run(
        ["git", "-C", folder, "rev-parse", "--verify", "--quiet", base], check=False, capture_output=True, text=True
    )
    spec = [f"{base}...HEAD"] if probe.returncode == 0 else ["HEAD~1", "HEAD"]
    done = subprocess.run(["git", "-C", folder, "diff", *spec], check=False, capture_output=True, text=True)
    if done.returncode != 0:
        return ""
    return done.stdout or ""


def mark_pr_seen(ticket, repo, number) -> dict:
    if not ticket or not repo or not number:
        raise CockpitError("bad ticket/repo/number")
    from .pr_watch import seen

    seen(ticket, repo, number)
    return {"ok": True, "ticket": ticket, "repo": repo, "number": number, "out": "seen"}


@one_at_a_time
def treat_pr(pack, ticket, repo, number, note="") -> dict:
    from .kanban import open_cards, place_card
    from .lanes import free_lane

    if not ticket:
        raise CockpitError("ticket")
    from .halt import describe, halted

    marker = halted(ticket)
    if marker:
        raise Conflict(describe(ticket, marker))
    state = pr_state(ticket, repo, number)
    comments = state.get("new") or state.get("comments") or []
    title = card_title("pr-treat", ticket, pack=pack)
    twin = open_twin(pack["board"], "pr-treat", ticket, f"{repo}#{number}", title)
    folded = ""
    if twin:
        if not _at_its_plan(pack, twin):
            raise Conflict(f"already open: card {twin}")
        folded, comments = _fold_treat(pack, ticket, repo, number, twin, comments)
    from .ops import worktree_add

    kept = worktree_add(pack, ticket, repo)
    _set_push_mode(pack, ticket, False)
    lane = free_lane("worker", pack, open_cards(pack["board"]), ticket=ticket)
    from .intents import all_intents
    from .outbox import amend

    amended = []
    head = state.get("head") or ""
    for intent in all_intents(ticket):
        if intent.get("type") not in (
            "push-branch",
            "open-pr",
            "pr-edit",
            "pr-comment",
            "pr-patch-apply",
            "pr-review-submit",
        ):
            continue
        if intent.get("status") not in ("pending", "endorsed", "returned"):
            continue
        payload = intent.get("payload") or {}
        this_pr = str(payload.get("number") or "") == str(number) or (
            head and (payload.get("publish_as") or payload.get("head")) == head
        )
        if payload.get("repo") != repo or not this_pr:  # an intent of another PR keeps its endorsement
            continue
        if ((pack or {}).get("outbox") or {}).get("amend_on_treat", True) is False:
            amended.append(intent["id"])  # named on the card; the worker amends one when its change touches it
            continue
        amend(intent["id"], summary=f"amend for {repo}#{number}", created_by=lane)
        amended.append(intent["id"])
    leave = ((pack or {}).get("outbox") or {}).get("amend_on_treat", True) is False
    lines = [
        f"New comments on {repo}#{number}. Keep the checkout. "
        + ("Amend an open intent only when your change touches it. " if leave else "Amend the existing intents. ")
        + "Do not open new ones."
    ]
    if folded:
        lines.append(
            f"Card {folded} was waiting for the human's go on its plan for the earlier of these comments; it is closed "
            f"and nothing of it was patched. One plan here covers all {len(comments)} comment(s)."
        )
    if amended:
        lines.append(
            (
                "Open intents of this PR (amend one when your change touches it; an untouched one keeps its endorsement): "
                if leave
                else "Amend: "
            )
            + ", ".join(amended)
        )
    from .quoted import external

    for comment in comments:  # a reviewer's words are quoted: the card's own lines stay the task
        if isinstance(comment, str):
            lines.append(external(comment))
            continue
        if isinstance(comment, dict):
            where = (
                f" · {comment['path']}" + (f":{comment['line']}" if comment.get("line") else "")
                if comment.get("path")
                else ""
            )
            lines.append(
                f"### {comment.get('author') or '?'}{where} · {comment.get('url') or ''} · id {comment.get('id') or ''}".rstrip(
                    " ·"
                )
            )
            lines.append(external(comment.get("body")))
    if note:
        lines.append(note)
    body = "\n".join(lines)
    folder = qa_of(ticket, "human")
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, f"pr-{repo}-{number}.md")
    write_text(path, body + "\n")
    card_id = place_card(
        pack["board"],
        title,
        lane,
        "ready",
        body=body,
        kind="pr-treat",
        ticket=ticket,
        key=f"{repo}#{number}",
        pack=pack,
        repos=[repo],
    )
    from .pr_watch import seen, treated
    from .time_util import iso

    if state.get("new"):
        seen(ticket, repo, number)
    treated(
        ticket,
        repo,
        number,
        {
            "time": iso(),
            "card": card_id,
            "lane": lane,
            "comments": comments,
            **({"supersedes": folded} if folded else {}),
        },
    )
    if folded:
        writes = BoardWrites(pack["board"])
        writes.comment(folded, "cockpit", f"superseded by {card_id}: its comments are planned there")
        writes.flush()
    return {
        "ok": True,
        "card_id": card_id,
        "out": body,
        "path": path,
        "amended": amended,
        "checkout": kept,
        **({"supersedes": folded} if folded else {}),
    }


def _at_its_plan(pack, card: str) -> bool:
    """A treat card still at its plan: blocked for the human, nothing of it in the outbox, no plan ok said."""
    from .intents import all_intents
    from .kanban import board_cards
    from .plan_gate import said_ok

    if next((row["status"] for row in board_cards(pack["board"]) if row["id"] == card), "") != "blocked":
        return False
    if any(intent.get("card_id") == card for intent in all_intents()):
        return False
    return not said_ok(pack, card)


def _fold_treat(pack, ticket, repo, number, card, comments) -> tuple:
    """Close the plan-stage treat card of this PR as superseded and bring its comments to the new one, so one plan reaches
    the human. (closed card, every comment)."""
    from .pr_watch import treatment_of
    from .store import log

    seen_ids = {comment.get("id") for comment in comments if isinstance(comment, dict)}
    older = [
        comment
        for comment in treatment_of(ticket, repo, number, card).get("comments") or []
        if not (isinstance(comment, dict) and comment.get("id") in seen_ids)
    ]
    writes = BoardWrites(pack["board"])
    writes.complete(
        card,
        result=f"superseded: {len(comments)} newer comment(s) on {repo}#{number} arrived before the go; "
        "one plan covers all of them on the next treat card",
    )
    if not writes.flush()[0]:
        raise Conflict(f"already open: card {card} (it could not be closed)")
    log(f"TREAT {ticket} {repo}#{number}: {card} superseded, its comments fold into the new card")
    return card, [*older, *comments]


def dismiss_ci(pack, ticket, repo, sha) -> dict:
    from .ci_watch import dismiss

    return dismiss(pack, ticket, repo, sha)


@one_at_a_time
def open_analyst(pack, kind, ticket="", repos=(), body="", **fields) -> str:
    """One analyst card per ticket, kind, and change. A second call returns the card already open."""
    from .halt import halted
    from .kanban import open_cards, open_twin, place_card
    from .lanes import free_lane

    if ticket and halted(ticket):
        return ""
    title = card_title(kind, ticket, pack=pack, **fields)
    key = str(fields.get("sha") or fields.get("change") or "")
    existing = open_twin(pack["board"], kind, ticket, key, title)
    if existing:
        return existing
    lane = free_lane("analyst", pack, open_cards(pack["board"]))
    if not body:  # the pack's text for this kind of analyst card, when it has one
        text = ((((pack.get("skills") or {}).get("cards") or {}).get("analyst") or {}).get(kind)) or ""
        body = (
            text.format(
                ticket=ticket,
                repo=(list(repos) or [""])[0],
                change=str(fields.get("change") or ""),
                sha=str(fields.get("sha") or ""),
                id=str(fields.get("change") or fields.get("sha") or ""),
                url=str(fields.get("url") or ""),
                files=str(fields.get("files") or ""),
            )
            if text
            else ""
        )
    return place_card(
        pack["board"],
        title,
        lane,
        "ready",
        body=body or None,
        kind=kind,
        ticket=ticket,
        key=key,
        pack=pack,
        repos=repos,
    )


def intake_waiting(pack, ticket: str) -> str:
    """The wait for go: a blocked intake card, or an open intake or reopened card that is still proposing (no go
    answered on it yet). Work does not start past it."""
    from .kanban import board_cards

    for card in board_cards((pack or {}).get("board") or ""):
        if card.get("ticket") != ticket:
            continue
        title = str(card.get("title") or "")
        if ": intake" not in title and ": reopened" not in title:
            continue
        if card.get("status") == "blocked":
            return card["id"]
        if card.get("status") in ("ready", "running", "todo", "triage", "scheduled") and not _went(pack, card["id"]):
            return card["id"]
    return ""


def _went(pack, card_id: str) -> bool:
    """The human answered go on this card."""
    connection = _open(pack["board"])
    if connection is None:
        return False
    try:
        rows = connection.execute("select body from task_comments where task_id = ?", (card_id,)).fetchall()
    except sqlite3.Error:
        rows = []
    finally:
        connection.close()
    return any(re.match(r"human: go\b", str(row[0] or ""), re.I) for row in rows)


def mark_ci(pack, ticket: str, sha: str, verdict: str, repo: str = "", run_id: str = "") -> dict:
    """Flaky writes one rerun intent for the failed run. Real reopens intake and leaves it waiting for go."""
    ticket = (ticket or "").strip()
    sha = (sha or "").strip()
    verdict = (verdict or "").strip().lower()
    if verdict not in ("flaky", "real"):
        raise CockpitError("mark flaky or real")
    if not ticket or not sha:
        raise CockpitError("ticket and sha")
    if verdict == "flaky":
        return _mark_flaky(pack, ticket, sha, repo, str(run_id or "").strip())
    return _mark_real(pack, ticket, sha, repo)


def _mark_flaky(pack, ticket: str, sha: str, repo: str, run_id: str) -> dict:
    from .intents import all_intents
    from .outbox import create

    for intent in all_intents(ticket):
        payload = intent.get("payload") or {}
        if (
            intent.get("type") == "ci-rerun"
            and payload.get("sha") == sha
            and (not run_id or str(payload.get("run_id")) == run_id)
        ):
            return {"ok": True, "verdict": "flaky", "intent": intent["id"], "created": False}
    if not repo:
        for intent in all_intents(ticket):
            payload = intent.get("payload") or {}
            if payload.get("sha") == sha and payload.get("repo"):
                repo = str(payload["repo"])
                break
    if not repo:
        raise CockpitError("repo")
    if not run_id:
        raise CockpitError("flaky needs the id of the failed run, to start its failed jobs again")
    row = create(
        pack,
        ticket,
        "ci-rerun",
        _diagnosis_card(pack, ticket, sha) or "ci",
        f"rerun {sha[:9]}",
        {"repo": repo, "sha": sha, "run_id": run_id},
    )
    return {"ok": True, "verdict": "flaky", "intent": row["id"], "created": True}


def _diagnosis_cards(pack, ticket: str, sha: str) -> list:
    """The analyst's diagnosis cards of this commit, newest first (card ids are random: the board's creation time orders them)."""
    import sqlite3

    from .kanban import _index, db_path

    cards = [
        cid
        for cid, entry in (_index().get(pack["board"]) or {}).items()
        if isinstance(entry, dict)
        and entry.get("kind") == "ci"
        and entry.get("ticket") == ticket
        and str(entry.get("key") or "").startswith(sha[:9])
    ]
    if len(cards) < 2:
        return cards
    try:
        connection = read_db(db_path(pack["board"]))
        marks = ",".join("?" * len(cards))
        made = dict(connection.execute(f"select id, created_at from tasks where id in ({marks})", cards).fetchall())
        connection.close()
    except sqlite3.Error:
        made = {}
    return sorted(cards, key=lambda card: (float(made.get(card) or 0), card), reverse=True)


def _diagnosis_card(pack, ticket: str, sha: str) -> str:
    """The analyst's newest diagnosis card of this commit, else empty."""
    cards = _diagnosis_cards(pack, ticket, sha)
    return cards[0] if cards else ""


def _diagnosis_of(pack, ticket: str, sha: str) -> str:
    """What the analyst wrote on the diagnosis card of this commit (its last comment), so intake plans the fix from it."""
    if not (ticket and sha):
        return ""
    import sqlite3

    from .kanban import db_path

    cards = _diagnosis_cards(pack, ticket, sha)
    if not cards:
        return ""
    try:
        connection = read_db(db_path(pack["board"]))
        marks = ",".join("?" * len(cards))
        row = connection.execute(
            f"select task_id, body from task_comments where task_id in ({marks}) and author like 'analyst%' order by created_at desc limit 1",
            cards,
        ).fetchone()
        connection.close()
    except sqlite3.Error:
        return ""
    if not row or not (row[1] or "").strip():
        return ""
    return f"\n\nThe analyst's diagnosis (card {row[0]}):\n\n{row[1].strip()[:6000]}\n"


@one_at_a_time
def _mark_real(pack, ticket: str, sha: str = "", repo: str = "") -> dict:
    """Intake gets the failure as a ready card: it proposes the fix, then blocks for go. An intake card already open
    hears about it in a comment and keeps its state."""
    from .halt import refuse

    refuse(ticket)
    from .owners import owner_of

    owner = owner_of(ticket)
    if owner:
        # A plugin runs this ticket (a release's unit): its own CI step fails on this run and sends the fix itself.
        # Intake waiting for the human's go would only hold the intake seat while the release waits on it.
        return {"ok": True, "verdict": "real", "owner": owner, "card_id": "", "waiting": "", "created": False}
    from .kanban import BoardWrites, open_cards, open_twin, place_card
    from .lanes import free_lane

    where = f" at {sha[:9]}" + (f" in {repo}" if repo else "") if sha else ""
    body = CI_REAL_BODY.format(ticket=ticket, where=where) + _diagnosis_of(pack, ticket, sha)
    title = card_title("intake", ticket, pack=pack)
    existing = open_twin(pack["board"], "intake", ticket, title=title)
    if existing:
        writes = BoardWrites(pack["board"])
        writes.comment(existing, "analyst", body.strip())
        writes.flush()
        return {"ok": True, "verdict": "real", "card_id": existing, "waiting": "proposal", "created": False}
    lane = free_lane("intake", pack, open_cards(pack["board"]))
    card_id = place_card(pack["board"], title, lane, "ready", body=body, kind="intake", ticket=ticket, pack=pack)
    return {"ok": True, "verdict": "real", "card_id": card_id, "waiting": "proposal", "created": True}


def forget_ci(ticket, sha) -> dict:
    if not ticket or not sha:
        raise CockpitError("bad ticket/sha")
    from .ci_watch import forget

    return forget(ticket, sha)


def request_sweep() -> str:
    from .gate import request_sweep as ask

    ask("human")
    log = os.path.join(watch_dir(), "sweep.log")
    os.makedirs(os.path.dirname(log), exist_ok=True)
    append_line(log, "sweep\n")
    return "sweep"


def sweep_state() -> dict:
    """A sweep is running while the gatekeeper card that serves the last request is open."""
    requested = os.path.exists(os.path.join(outbox(), "_sweep.requested"))
    serving = os.path.join(outbox(), "_sweep.serving")
    running = os.path.exists(serving)
    since = os.path.getmtime(serving) if running else None
    return {"running": running, "requested": requested, "since": since}


def run_watcher(name) -> dict:
    known = watchers()
    script = known.get(name or "")
    if not script:
        raise CockpitError("watcher: " + " | ".join(sorted(known)))
    path = os.path.join(PLUGIN_ROOT, "cron", script)
    if not os.path.isfile(path):
        raise CockpitError(f"no watcher script {script}")
    env = os.environ.copy()
    env["PATH"] = os.path.join(PLUGIN_ROOT, "bin") + os.pathsep + env.get("PATH", "")
    import fcntl

    os.makedirs(watch_dir(), exist_ok=True)
    # One run of a script at a time from here: a second Run now while the first is going would run it twice.
    with open(os.path.join(watch_dir(), f".run-{script}.lock"), "w", encoding="utf-8") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return {"ok": True, "out": f"{name} is already running", "name": name, "script": script, "already": True}
        result = subprocess.run(["sh", path], capture_output=True, text=True, env=env, timeout=60, check=False)
    out = (result.stdout or result.stderr or "").strip()
    return {"ok": result.returncode == 0, "out": out, "name": name, "script": script}


def resolve_slot(pack, slot):
    from .slots import free_slots

    if str(slot) in ("", "auto", "None"):
        found = free_slots(pack["seats"]["slots"])
        if not found:
            raise Conflict("no free slot")
        return found[0]
    try:
        return int(slot)
    except (TypeError, ValueError) as exc:
        raise CockpitError("slot 1-n or auto") from exc


def _set_push_mode(pack, ticket: str, human: bool) -> None:
    """Lane mode cannot push. Human mode can."""
    from .worktree import mode

    for repo in (pack.get("repos") or {}).get("repos") or []:
        name = repo.get("name") or ""
        if not name:
            continue
        try:
            mode(ticket, name, human)
        except CockpitError:
            continue


def session_open(pack, slot, ticket, repos=()) -> str:
    """Open the human's session on a slot. Named repos are checked out for the ticket before the pack's open command runs."""
    from .halt import refuse

    refuse(ticket)
    known = {repo["name"] for repo in pack["repos"]["repos"]}
    unknown = [name for name in repos if name not in known]
    if unknown:
        raise CockpitError(f"{unknown[0]} is not a repo of this pack")
    from .ops import worktree_add
    from .slots import caller, data_ready, warm_slot

    number = resolve_slot(pack, slot)
    ready = data_ready(pack, number)
    if ready != "ready":
        raise CockpitError(ready)
    who = caller()
    from .slots import read_owner

    owner = read_owner(number)
    if owner.startswith("lane:"):  # a lane works there: the session would take its slot from under it
        raise CockpitError(
            f"slot {number} is busy with the pipeline ({owner}): pick another slot or wait until it is free"
        )
    # The bring-up (a detached `cockpit slot bringup N`) runs the pack's up, the slot browser, and the dev servers.
    warm_slot(number, ticket, who, pack)
    if (pack.get("slot_provider") or "none") in ("none", "", "pack"):
        held = _ticket_repos(
            pack, ticket
        )  # the ticket's own checkouts when it has some (a per-ticket session), else every repo
        for name in held:
            worktree_add(pack, ticket, name)
        if not held:
            worktree_add(pack, ticket)
        _set_push_mode(pack, ticket, who == "human")
    from .slots import capture_baseline, touch

    capture_baseline(pack, number)
    touch(number)
    for name in repos:
        worktree_add(pack, ticket, name)
    _session_command(pack, "open", number, ticket, human_only=True)
    record = {"slot": number, "ticket": ticket, "org": forge_org(pack), "action": "open"}
    _write(qa_of(ticket, "session.json"), record)
    return f"session {ticket}"


def finish_open_runs(pack, ticket: str) -> list:
    """A tester run that ends without complete or block is failed: Hermes blocks it with the failure as its reason.

    A card still waiting on a parent (todo) has not run, so it is left as it is.
    """
    from .kanban import board_cards

    failed = []
    connection = _open(pack["board"])
    if connection is None:
        return failed
    try:
        for card in board_cards(pack["board"]):
            if card.get("ticket") != ticket:
                continue
            assignee = str(card.get("assignee") or "")
            title = str(card.get("title") or "")
            if not assignee.startswith("tester") and ": test" not in title:
                continue
            if card.get("status") not in (
                "ready",
                "running",
                "in_progress",
                "claimed",
                "scheduled",
            ):  # scheduled: waits on a quota
                continue
            if card.get("status") == "scheduled":
                # its own batch, so the guarded block's answer says whether it failed or a worker took it meanwhile
                from .kanban import BoardWrites

                writes = BoardWrites(pack["board"])
                writes.unblock(card["id"])
                writes.block(card["id"], f"failed {pack.get('name') or ''}", guard=True)
                if (writes.flush() or [None])[-1]:
                    failed.append(card["id"])
                continue
            _status(connection, card["id"], "failed", f"failed {pack.get('name') or ''}")
            failed.append(card["id"])
        if failed:
            folder = qa_of(ticket)
            os.makedirs(folder, exist_ok=True)
            _write(os.path.join(folder, "run-ended.json"), {"failed": failed, "pack": pack.get("name") or ""})
        connection.commit()
    finally:
        connection.close()
    return failed


def _session_command(pack, action: str, slot: int, ticket: str, human_only: bool = False) -> None:
    """The pack's slots.session open or close command. Open's extras are the human's session only."""
    from .slots import CommandProvider, caller

    words = (((pack or {}).get("slots") or {}).get("session") or {}).get(action)
    if not words or (human_only and caller() != "human"):
        return
    result = CommandProvider(pack).run(f"session-{action}", slot, ticket, words=words)
    if result["state"] not in ("ok", "working"):
        raise CockpitError(f"session {action} {result['state']}: {result['tail']}".strip(": "))


def session_close(pack, slot) -> str:
    """Stop the runtime, run the pack's close, and put the checkout back in lane mode, which cannot push."""
    from .slots import read_owner, read_ticket, stop_slot_runtime, write_owner, write_ticket

    number = int(slot)
    close = ((pack or {}).get("slots") or {}).get("close") or {}
    if close.get("human_only") and read_owner(number) != "human":
        raise CockpitError(f"slot {number} is not a manual session")
    previous = read_ticket(number) or "free"
    if previous and previous != "free":
        if not close.get("keep_runs"):
            finish_open_runs(pack, previous)
        _session_command(pack, "close", number, previous)
        _set_push_mode(pack, previous, False)
    stopped = stop_slot_runtime(number)
    if not close.get("keep_stack"):
        _provider(pack).down(number)
    else:
        from .slots import keep_stack

        keep_stack(number)  # the cleanup takes it down once idle
    write_owner(number, "free")
    write_ticket(number, "")
    from .slots import clear_release_claim

    clear_release_claim(number)
    return f"closed {number} was {previous} owner {read_owner(number)} stopped {int(bool(stopped.get('browser'))) + len(stopped.get('servers') or [])}"


@one_at_a_time
def session_handoff(pack, slot, lane) -> str:
    """The human hands a slot to the lanes: its browser stops, a worker card takes the ticket, and a tester and a
    reviewer card wait on it. A slot that is not the human's is refused."""
    from .halt import refuse
    from .kanban import place_card
    from .slots import _read_runtime, _stop_pid, clear_release_claim, read_owner, read_ticket, write_owner

    number = int(slot)
    if read_owner(number) not in ("human", "free"):
        raise CockpitError(f"slot {number} is not the human's to hand off ({read_owner(number)})")
    ticket = read_ticket(number)
    if ticket:
        refuse(ticket)
    seat = str(lane or "").strip()
    if seat.startswith("lane:"):
        seat = seat[len("lane:") :]
    if not seat:
        from .kanban import open_cards
        from .lanes import free_lane

        seat = free_lane("worker", pack, open_cards(pack["board"]), ticket=ticket)
    owner = f"lane:{seat}"
    if ticket:
        _session_command(pack, "handoff", number, ticket)  # the pack's hook (stop the human's browser, say)
    record = _read_runtime(number)
    if record.get("browser"):
        _stop_pid(record["browser"])
    write_owner(number, owner)
    clear_release_claim(number)  # the human's session re-owned it: no release claim any more
    if ticket:
        from .kanban import open_cards
        from .lanes import free_lane

        work = place_card(
            pack["board"], card_title("work", ticket, pack=pack), seat, "ready", kind="work", ticket=ticket, pack=pack
        )
        tester = free_lane("tester", pack, open_cards(pack["board"]), ticket=ticket)
        test = place_card(
            pack["board"],
            card_title("tester", ticket, pack=pack),
            tester,
            "ready",
            parents=[work],
            kind="tester",
            ticket=ticket,
            pack=pack,
        )  # the chain's tester, not a Test kickoff
        reviewer = free_lane("reviewer", pack, open_cards(pack["board"]), ticket=ticket)
        place_card(
            pack["board"],
            card_title("review", ticket, pack=pack),
            reviewer,
            "ready",
            parents=[test],
            kind="review",
            ticket=ticket,
            pack=pack,
        )
        _set_push_mode(pack, ticket, False)
    return f"handoff {number} {owner}"


def _origin_probe(url: str) -> bool:
    """True when the origin accepts a connection. A refusal or a bad URL is down."""
    if not url:
        return False
    import socket
    from urllib.parse import urlparse

    parsed = urlparse(url)
    host = parsed.hostname
    if not host:
        return False
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    try:
        connection = socket.create_connection((host, port), 0.2)
    except OSError:
        return False
    connection.close()
    return True


def origins_up(origins, probe=None) -> dict:
    """Whether each origin is up. Tests pass probe. The suite does not dial out."""
    check = probe or _origin_probe
    if probe is None and os.environ.get("PYTEST_CURRENT_TEST"):
        check = lambda _url: False
    found = {}
    for name, url in (origins or {}).items():
        found[str(name)] = bool(check(str(url or "")))
    return found


def save_demo(ticket, record, slot: int = 1) -> dict:
    """The demo file keeps environment, account, links, and steps. The secret goes to the slot copy."""
    from .paths import qa
    from .slots import write_slot_secret

    clean = {}
    secret = {}
    for key, value in (record or {}).items():
        if key in ("password", "secret", "otp", "seed"):
            if value:
                secret[key] = value
            continue
        clean[key] = value
    folder = ticket_folder(qa(), ticket)
    os.makedirs(folder, exist_ok=True)
    _write(os.path.join(folder, "demo.json"), clean)
    if secret:
        write_slot_secret((record or {}).get("slot") or slot, secret)
    return clean


def _graduated_path() -> str:
    return os.path.join(platform_dir(), "graduated-prs.json")


def graduate_bumps(pack) -> list:
    """A pull request whose pack grooming checks all pass leaves this flow and is only under pull-request watch."""
    report = audit_bumps(pack)
    blocked = {row.get("pr") for row in report.get("missing") or []}
    data = _read(bumps_path())
    graduated = _read(_graduated_path())
    graduated.setdefault("prs", [])
    known = {(item.get("repo"), item.get("number")) for item in graduated["prs"] if isinstance(item, dict)}
    left = []
    for key in list((data.get("started") or {}).keys()):
        if key in blocked:
            continue
        left.append(key)
        data["started"].pop(key, None)
        repo, _, number = key.partition("#")
        rows = [item for item in (data.get("repos") or {}).get(repo) or [] if str(item.get("number")) != number]
        if repo in (data.get("repos") or {}):
            data["repos"][repo] = rows
        try:
            parsed = int(number)
        except ValueError:
            parsed = 0
        if parsed and (repo, parsed) not in known:
            graduated["prs"].append({"repo": repo, "number": parsed, "pack": (pack or {}).get("name") or ""})
            known.add((repo, parsed))
    _write(bumps_path(), data)
    _write(_graduated_path(), graduated)
    return left


def _standup_window_day(pack, folder) -> str:
    """The window the note being sent covers: the draft's own start. A note sent after the next window opened (past the
    pack's standup window) still covers the draft's window; marking the window open at send time made the next morning's
    draft read as already sent. A note with no draft covers the window open now."""
    since = str(_read(os.path.join(folder, "standup.json")).get("since") or "")
    if re.match(r"\d{4}-\d{2}-\d{2}T", since):
        return since[:10]
    from .window import pack_standup, window_start

    hour, days, minute = pack_standup(pack)
    return window_start(hour=hour, working=days, minute=minute).date().isoformat()


def standup_send(pack, text) -> dict:
    """Send the note: the text the human edited, else the draft in the channel's own format (the pack's standup.chat_file) when the
    draft was not edited, else the markdown."""
    body = (text or "").strip()
    folder = platform_dir()
    markdown = os.path.join(folder, "standup.md")
    from .standup_note import chat_file

    slack = os.path.join(folder, chat_file(pack))
    drafted = open(markdown, encoding="utf-8").read().strip() if os.path.isfile(markdown) else ""
    channel = open(slack, encoding="utf-8").read().strip() if drafted and os.path.isfile(slack) else ""
    if channel and (not body or body == drafted):
        body = channel  # the draft as drafted goes out in the channel's own format
    elif not body:
        body = drafted
    if not body:
        raise CockpitError("the note is empty")
    from .notify import command, run

    folder = platform_dir()
    os.makedirs(folder, exist_ok=True)
    today = time.strftime("%Y-%m-%d")
    if _read(os.path.join(folder, "standup-sent.json")).get("sent_on") == today:
        raise CockpitError(f"today's standup ({today}) was already sent")
    write_text(os.path.join(folder, "standup.md"), body + "\n")
    sent_path = os.path.join(folder, "standup.sent")
    if not command(pack, "standup"):
        # no channel to send it to: the confirmed note is kept here, and that closes its row (it stayed a draft, so
        # Confirm seemed to do nothing)
        if os.path.isfile(sent_path):
            os.remove(sent_path)
        write_text(os.path.join(folder, "standup.kept"), body + "\n")
        return {"ok": True, "sent": False, "out": "standup kept: the pack has no notify.standup command to send it"}
    # The human sends the standup and sees a failure at once, so it is not kept for the Inbox.
    sent, detail = run(pack, "standup", body, key=time.strftime("%Y-%m-%d"))
    if not sent:
        raise CockpitError(detail)
    write_text(sent_path, body + "\n")
    _write(
        os.path.join(folder, "standup-sent.json"),
        {"day": _standup_window_day(pack, folder), "sent_on": today, "time": time.strftime("%Y-%m-%dT%H:%M:%S")},
    )
    return {"ok": True, "sent": True, "out": detail}


def kickoff_text(pack, ticket, mode, prompt) -> str:
    from .pack import agent_launch
    from .prompts import resolve
    from .registry import kickoff_modes

    skills = ((pack.get("skills") or {}).get("kickoff") or {}).get(mode) or []
    launch = agent_launch(pack)
    # A question's answer is read in the Inbox (cockpitlib.answers): the complete call's summary and the files the lane
    # wrote under qa/<ticket>/ are the row. The other modes' work reaches the human through their intents and cards.
    question = (kickoff_modes(pack).get(mode) or {}).get("capacity_bucket") == "question"
    finish = (
        (
            "Finish with the board's complete call: your summary and every file you wrote under "
            f"{qa_of(ticket)}/ reach the human's Inbox as the answer. Name each file you wrote in the summary; "
            "a question for the human is a block, as always."
        )
        if question
        else "Finish with the board's complete call. The human reads it on the Cockpit page."
    )
    lines = [
        f"{ticket}: {mode}",
        resolve(pack, prompt) if prompt else f"Kick off {ticket}.",
        "Skills for this kickoff: " + (", ".join(skills) if skills else "(none)"),
        finish,
    ]
    if launch["router"]:
        lines.append(f"Follow the skill router at {launch['router']}. It chooses the one skill this task needs.")
    if launch["home"]:
        lines.append(f"Coding tool home: {launch['home']}")
    if mode == "bumps" and (pack.get("bump_sequence") or {}).get("stages"):
        from .sequence import order_text

        lines.append("Each PR goes out as a sequence, " + order_text(pack["bump_sequence"]) + ".")
    checkout = worktree_of(ticket) if ticket else ""
    if checkout and os.path.isdir(checkout):
        lines.append(f"Ticket checkout: {checkout}")
    return "\n".join(lines) + "\n"
