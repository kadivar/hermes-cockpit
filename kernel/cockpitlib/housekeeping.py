# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Minute housekeeping. Every step runs. One failed step fails the health record."""

import json
import os
import re
import sqlite3
import time

from .errors import CockpitError
from .gate import auto_publish, base_gone, closeout_returned, recard, resweep_held, sweep, ticket_ready
from .kanban import BoardWrites, block_reason, db_path, ticket_of
from .lend import take_back
from .ops import _health, _health_hold
from .paths import qa_of
from .slots import claim, data_ready, free_slots, warm_slot
from .store import dump_json, read_db, write_text


def _db(pack):
    path = db_path((pack or {}).get("board") or "")
    if not os.path.isfile(path):
        return None
    return read_db(path)  # read-only like every other reader: card writes go through BoardWrites


def _report(connection, columns, card_id, title: str) -> str:
    """The lane's report: the result column, else the ticket's review file when the lane wrote it after the card was
    made. An older review file belongs to an earlier card and settles nothing."""
    if "result" in columns:
        got = connection.execute("select result from tasks where id = ?", (card_id,)).fetchone()
        text = (got[0] or "") if got else ""
        if str(text).strip():
            return str(text)
    ticket = ticket_of(title or "")  # the Jira key: a per-repo card is "<ticket> <repo>: …"
    path = qa_of(ticket, "review.md")
    if not ticket or not os.path.isfile(path):
        return ""
    if "created_at" in columns:
        made = connection.execute("select created_at from tasks where id = ?", (card_id,)).fetchone()
        if made and made[0] and os.path.getmtime(path) < float(made[0]):
            return ""
    return open(path, encoding="utf-8").read()


def _owned_cards(pack) -> dict:
    """card -> the plugin that owns its kind. Housekeeping leaves those cards to that plugin."""
    from .kanban import _index
    from .registry import owned_kinds

    owners = owned_kinds(pack)
    if not owners:
        return {}
    kinds = _index().get(str((pack or {}).get("board") or "")) or {}
    return {
        card: owners[entry["kind"]]
        for card, entry in kinds.items()
        if isinstance(entry, dict) and entry.get("kind") in owners
    }


def _hand_over(owned: dict, card: str) -> bool:
    """A plugin's card: wake that plugin instead of changing the card."""
    plugin = owned.get(str(card))
    if not plugin:
        return False
    from .inbox import wake

    wake(plugin, str(card))
    return True


def settle_reviews(pack) -> str:
    """Complete a review-column card from the lane's last report so the next card can start."""
    connection = _db(pack)
    if connection is None:
        return "0"
    try:
        columns = {row[1] for row in connection.execute("pragma table_info(tasks)")}
        if "id" not in columns or "status" not in columns or "title" not in columns:
            return "0"
        rows = connection.execute("select id, title from tasks where status = 'review'").fetchall()
        writes = BoardWrites(pack["board"])
        owned = _owned_cards(pack)
        for card_id, title in rows:
            if _hand_over(owned, card_id):
                continue
            report = str(_report(connection, columns, card_id, title or "")).strip()
            if not report:
                continue
            writes.complete(card_id, result=report)
    except sqlite3.Error as exc:
        raise RuntimeError(str(exc)) from exc
    finally:
        connection.close()
    return str(sum(1 for done in writes.flush() if done))


def _tester_lane(connection, ticket: str, pack) -> str:
    """The tester already on this ticket, or the next free tester seat."""
    for assignee, title in connection.execute("select assignee, title from tasks"):
        if not str(title or "").startswith(f"{ticket}:"):
            continue
        if str(assignee or "").startswith("tester"):
            return str(assignee)
    from .kanban import open_cards
    from .lanes import free_lane

    return free_lane("tester", pack, open_cards(pack["board"]), ticket=ticket)


def return_unfinished(pack) -> str:
    """Send an unfinished review request back to the tester when a test row is still open."""
    connection = _db(pack)
    if connection is None:
        return "0"
    try:
        columns = {row[1] for row in connection.execute("pragma table_info(tasks)")}
        if "assignee" not in columns:
            connection.close()
            return "0"
        rows = connection.execute("select id, title, assignee from tasks where status = 'blocked'").fetchall()
    except sqlite3.Error as exc:
        connection.close()
        raise RuntimeError(str(exc)) from exc
    writes = BoardWrites(pack["board"])
    owned = _owned_cards(pack)
    from .test_flow import results_file

    results_name = results_file(pack)
    for card_id, title, assignee in rows:
        if _hand_over(owned, card_id):
            continue
        review = str(assignee or "").startswith("reviewer") or ": review" in str(title or "")
        if not review:
            continue
        ticket = ticket_of(title or "")  # the Jira key: a per-repo card is "<ticket> <repo>: …"
        results = qa_of(ticket, results_name)
        if not os.path.isfile(results):
            continue
        text = open(results, encoding="utf-8").read()
        from .test_flow import results_still_open

        if not results_still_open(text):
            continue
        writes.assign(card_id, _tester_lane(connection, ticket, pack))
        writes.unblock(card_id)
    connection.close()
    answers = writes.flush()
    sent = sum(1 for unblocked in answers[1::2] if unblocked)
    return str(sent + _send_back_testers(pack))


def _send_back_testers(pack) -> int:
    """A tester whose block asks for the review of a run that is not finished is sent back to finish it, once
    `testflow.send_back` seconds have passed (the human should not be asked for a review of rows still open)."""
    wait = (pack.get("testflow") or {}).get("send_back")
    if wait is None:
        return 0
    from .kanban import open_card_rows

    writes = BoardWrites(pack["board"])
    owned = _owned_cards(pack)
    cards = []
    for card in open_card_rows(pack["board"], pack):
        if (
            card.get("status") != "blocked"
            or card.get("parked")
            or not str(card.get("assignee") or "").startswith("tester")
        ):
            continue
        if (
            not card.get("not_ready")
            or time.time() - float(card.get("blocked_at") or 0) < float(wait)
            or _hand_over(owned, card["id"])
        ):
            continue
        rows = ", ".join(str(item).replace("·", " ") for item in card["not_ready"])
        video = ""
        if any(str(item).endswith("·video") for item in card["not_ready"]):
            from .test_flow import video_refusal

            video = " " + video_refusal(pack, card["id"], str(card.get("assignee") or ""))
        writes.comment(
            card["id"],
            "cockpit",
            f"Not ready for the human's review: {rows}. Finish those rows (rerun them once unblocked, make a row only a "
            "person can run a 👤 row, or ask about those rows only), then ask for the review again." + video,
        )
        writes.unblock(card["id"])
        cards.append(card["id"])
    writes.flush()
    return len(cards)


def note_other_session(lane: str, account: str, own: str) -> dict:
    """The lane's own account is cleared once. Any other account stays a question."""
    from .paths import watch_dir

    folder = watch_dir()
    os.makedirs(folder, exist_ok=True)
    if account == own:
        once_path = os.path.join(folder, "own-session-once.json")
        once = []
        if os.path.isfile(once_path):
            try:
                loaded = json.loads(open(once_path, encoding="utf-8").read() or "[]")
            except json.JSONDecodeError:
                loaded = []
            if isinstance(loaded, list):
                once = [str(item) for item in loaded]
        if lane in once:
            return {"question": False, "once": True, "lane": lane}
        write_text(os.path.join(folder, "own-session.json"), json.dumps({"lane": lane, "account": account}))
        return {"question": False, "pending": True, "lane": lane}
    path = os.path.join(folder, "session-questions.json")
    rows = []
    if os.path.isfile(path):
        try:
            loaded = json.loads(open(path, encoding="utf-8").read() or "[]")
        except json.JSONDecodeError:
            loaded = []
        if isinstance(loaded, list):
            rows = loaded
    rows.append({"lane": lane, "account": account})
    write_text(path, json.dumps(rows))
    return {"question": True, "account": account, "lane": lane}


def _clear_noted_session() -> int:
    """A noted own-account session is cleared once. A missing note clears nothing."""
    from .paths import watch_dir

    folder = watch_dir()
    path = os.path.join(folder, "own-session.json")
    if not os.path.isfile(path):
        return 0
    try:
        data = json.loads(open(path, encoding="utf-8").read() or "{}")
    except json.JSONDecodeError:
        data = {}
    if not isinstance(data, dict):
        data = {}
    lane = str(data.get("lane") or "")
    once_path = os.path.join(folder, "own-session-once.json")
    once = []
    if os.path.isfile(once_path):
        try:
            loaded = json.loads(open(once_path, encoding="utf-8").read() or "[]")
        except json.JSONDecodeError:
            loaded = []
        if isinstance(loaded, list):
            once = [str(item) for item in loaded]
    if lane and lane in once:
        return 0
    os.remove(path)
    if lane:
        once.append(lane)
        write_text(once_path, json.dumps(once))
    return 1


_SESSION_PHRASE = "already in another session"
_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")


def _load_list(path) -> list:
    if not os.path.isfile(path):
        return []
    try:
        loaded = json.loads(open(path, encoding="utf-8").read() or "[]")
    except json.JSONDecodeError:
        return []
    if not isinstance(loaded, list):
        return []
    return loaded


def _own_emails(lane: str) -> set:
    """Emails stored for this lane. A shared login is not the lane's own account."""
    from .vault import login_metadata

    found = set()
    for row in login_metadata(lane or ""):
        if str(row.get("lane") or "") != (lane or ""):
            continue
        email = str(row.get("email") or "")
        if email:
            found.add(email)
    return found


def _card_session_text(connection, card_id, columns) -> str:
    parts = []
    reason = block_reason(connection, card_id)
    if reason:
        parts.append(reason)
    if "body" in columns:
        got = connection.execute("select body from tasks where id = ?", (card_id,)).fetchone()
        if got and got[0]:
            parts.append(str(got[0]))
    tables = {row[0] for row in connection.execute("select name from sqlite_master where type = 'table'")}
    if "task_comments" not in tables:
        return "\n".join(parts)
    comment_columns = {row[1] for row in connection.execute("pragma table_info(task_comments)")}
    if "body" not in comment_columns or "task_id" not in comment_columns:
        return "\n".join(parts)
    rows = connection.execute("select body from task_comments where task_id = ?", (card_id,)).fetchall()
    for row in rows:
        if row and row[0]:
            parts.append(str(row[0]))
    return "\n".join(parts)


def _remember_question(lane: str, account: str) -> None:
    from .paths import watch_dir

    folder = watch_dir()
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, "session-questions.json")
    kept = [row for row in _load_list(path) if isinstance(row, dict)]
    for row in kept:
        if str(row.get("lane") or "") == lane and str(row.get("account") or "") == account:
            return
    kept.append({"lane": lane, "account": account})
    write_text(path, json.dumps(kept))


def _answer_other_session(pack) -> int:
    """Clear a block that names the lane's own account, once. Any other account stays a question."""
    connection = _db(pack)
    if connection is None:
        return 0
    writes = BoardWrites(pack["board"])
    try:
        columns = {row[1] for row in connection.execute("pragma table_info(tasks)")}
        if "id" not in columns or "status" not in columns or "assignee" not in columns:
            return 0
        from .paths import watch_dir

        folder = watch_dir()
        os.makedirs(folder, exist_ok=True)
        cleared_path = os.path.join(folder, "session-cleared.json")
        cleared = {str(item) for item in _load_list(cleared_path)}
        sent = 0
        rows = connection.execute("select id, assignee from tasks where status = 'blocked'").fetchall()
        for card_id, assignee in rows:
            card = str(card_id)
            if card in cleared:
                continue
            text = _card_session_text(connection, card, columns)
            if _SESSION_PHRASE not in text.lower():
                continue
            lane = str(assignee or "")
            own = _own_emails(lane)
            named = _EMAIL.findall(text)
            foreign = []
            for email in named:
                if email in own or email in foreign:
                    continue
                foreign.append(email)
            if foreign:
                for email in foreign:
                    _remember_question(lane, email)
                continue
            if named:
                writes.unblock(card)
                cleared.add(card)
                sent += 1
                continue
            if len(own) != 1:
                continue
            writes.unblock(card)
            cleared.add(card)
            sent += 1
        if sent:
            dump_json(cleared_path, sorted(cleared))
    except sqlite3.Error as exc:
        raise RuntimeError(str(exc)) from exc
    finally:
        connection.close()
    writes.flush()
    return sent


def clear_own_session(pack) -> str:
    """Clear "already in another session" for the lane's own account, once."""
    return str(_clear_noted_session() + _answer_other_session(pack))


STALE_RATE_LIMIT = 900
RATE_LIMITED = "rate-limited"
# Hermes keeps a ready card's last failure. A rate-limit failure that is no longer fresh still holds the card back.
FAILURE_STAMP = re.compile(r"rate[- ]limit|quota", re.I)
SETTLED_RUN = 300


def _rate_path() -> str:
    from .paths import watch_dir

    return os.path.join(watch_dir(), "rate-limits.json")


def _load_rates() -> dict:
    path = _rate_path()
    if not os.path.isfile(path):
        return {}
    try:
        loaded = json.loads(open(path, encoding="utf-8").read() or "{}")
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(loaded, dict):
        return {}
    return loaded


def _save_rates(record: dict) -> None:
    path = _rate_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    dump_json(path, record)


def stamp_rate_limit(pack, card: str, ticket: str = "", now=None) -> dict:
    """Park a card on a rate-limit stamp. Housekeeping releases it once the stamp is stale."""
    import time

    moment = int(time.time() if now is None else now)
    record = _load_rates()
    entry = {"ticket": ticket, "at": moment}
    record[str(card)] = entry
    _save_rates(record)
    connection = _db(pack)
    if connection is None:
        return entry
    connection.close()
    writes = BoardWrites(pack["board"])
    writes.block(str(card), RATE_LIMITED)
    writes.flush()
    return entry


def stamp_from_transcript(pack, path: str, now=None) -> str:
    """A transcript that names a rate limit stamps that card. A finished note with no card does not."""
    if not path or not os.path.isfile(path):
        return ""
    try:
        lines = open(path, encoding="utf-8").read().splitlines()
    except OSError:
        return ""
    for line in lines:
        text = line.strip()
        if not text:
            continue
        try:
            row = json.loads(text)
        except json.JSONDecodeError:
            continue
        if not isinstance(row, dict):
            continue
        note = str(row.get("text") or row.get("note") or row.get("outcome") or "")
        lowered = note.lower()
        if "rate-limited" not in lowered and "rate limit" not in lowered:
            continue
        card = str(row.get("card") or "")
        if not card:
            continue
        stamp_rate_limit(pack, card, str(row.get("ticket") or ""), now=now)
        return card
    return ""


DEAD_WORKER_GRACE = 600  # seconds past its claim before a running card with no worker is handed back


def _alive(pid) -> bool:
    try:
        os.kill(int(pid), 0)
    except (OSError, ValueError, TypeError, OverflowError):
        return False
    return True


def reclaim_dead(pack, now=None) -> str:
    """A card the board calls running whose worker is gone goes back to be started again.

    A gateway restart or an interrupted session ends the worker; the card keeps `running`, its claim expires and
    nothing starts it again, and the cards behind it wait for a card nobody works on. Handed back are cards whose claim
    ran out more than ten minutes ago, with no heartbeat since, and whose worker process is not there. A card a plugin
    owns is its plugin's."""
    import time

    moment = float(time.time() if now is None else now)
    connection = _db(pack)
    if connection is None:
        return "0"
    owned = _owned_cards(pack)
    found = []
    try:
        columns = {row[1] for row in connection.execute("pragma table_info(tasks)")}
        if not {"id", "status", "claim_expires", "worker_pid"} <= columns:
            return "0"
        beat = "last_heartbeat_at" if "last_heartbeat_at" in columns else "null"
        for card, expires, pid, heartbeat in connection.execute(
            f"select id, claim_expires, worker_pid, {beat} from tasks where status = 'running'"
        ):
            try:
                expired, last = float(expires or 0), float(heartbeat or 0)
            except (TypeError, ValueError):
                continue
            if not expired or moment - expired < DEAD_WORKER_GRACE or moment - last < DEAD_WORKER_GRACE:
                continue
            if (pid and _alive(pid)) or _hand_over(owned, str(card)):
                continue
            found.append(str(card))
    except sqlite3.Error:
        return "0"
    finally:
        connection.close()
    if not found:
        return "0"
    writes = BoardWrites(pack["board"])
    for card in found:
        writes.reclaim(
            card, "cockpit: the worker is gone (a restart or an interruption) and the claim ran out; started again"
        )
    writes.flush()
    from .store import log

    log(f"RECLAIM-DEAD {' '.join(found)}")
    return str(len(found))


def unstrand(pack, now=None) -> str:
    """A card parked on a stale rate-limit stamp becomes ready again. A fresh stamp stays."""
    import time

    moment = int(time.time() if now is None else now)
    cleared = set()
    connection = _db(pack)
    owned = _owned_cards(pack)
    if connection is not None:
        writes = BoardWrites(pack["board"])
        try:
            columns = {row[1] for row in connection.execute("pragma table_info(tasks)")}
            record = _load_rates()
            if "id" in columns and "status" in columns:
                rows = connection.execute("select id from tasks where status = 'blocked'").fetchall()
                for row in rows:
                    card = str(row[0])
                    if RATE_LIMITED not in block_reason(connection, card) or _hand_over(owned, card):
                        continue
                    entry = record.get(card)
                    stale = (
                        isinstance(entry, dict)
                        and isinstance(entry.get("at"), int)
                        and moment - entry["at"] >= STALE_RATE_LIMIT
                    )
                    if not stale:
                        continue
                    writes.unblock(card)
                    cleared.add(card)
            kept = {}
            for card, entry in record.items():
                if not isinstance(entry, dict) or not isinstance(entry.get("at"), int):
                    kept[card] = entry
                    continue
                if moment - entry["at"] < STALE_RATE_LIMIT:
                    kept[card] = entry
                    continue
                if str(card) in owned:  # the plugin was woken for it above, if it still waits
                    continue
                if "id" in columns and str(card) not in cleared:
                    writes.unblock(str(card))
                cleared.add(str(card))
            if record != kept:
                _save_rates(kept)
            for card in _stale_failures(connection, columns, moment):
                if card in cleared or _hand_over(owned, card):
                    continue
                writes.block(card, RATE_LIMITED, kind="transient")
                writes.unblock(card)
                cleared.add(card)
        except sqlite3.Error as exc:
            raise RuntimeError(str(exc)) from exc
        finally:
            connection.close()
        writes.flush()
    return str(len(cleared))


def _stale_failures(connection, columns, moment: int) -> list:
    """Ready, unclaimed cards whose last failure is a rate limit, when the card's latest run was not itself rate
    limited or crashed and ended more than five minutes ago."""
    if not {"id", "status", "last_failure_error"} <= columns:
        return []
    claim = " and claim_lock is null" if "claim_lock" in columns else ""
    rows = connection.execute(
        f"select id, last_failure_error from tasks where status = 'ready'{claim} "
        "and coalesce(last_failure_error, '') != ''"
    ).fetchall()
    tables = {row[0] for row in connection.execute("select name from sqlite_master where type = 'table'")}
    found = []
    for card, error in rows:
        if not FAILURE_STAMP.search(str(error)):
            continue
        if "task_runs" in tables:
            run = connection.execute(
                "select outcome, ended_at from task_runs where task_id = ? order by id desc limit 1", (card,)
            ).fetchone()
            if run and (
                str(run[0] or "") in ("rate_limited", "crashed") or not run[1] or moment - int(run[1]) < SETTLED_RUN
            ):
                continue
        found.append(str(card))
    return found


def awake(pack) -> str:
    """While a lane card runs, the pack's `awake` command holds the machine awake (a sleep ends every running lane's turn
    lease). It runs detached once per tick and is meant to outlive a tick by a little; nothing running, nothing held."""
    import subprocess

    argv = list(((pack or {}).get("awake") or {}).get("command") or [])
    if not argv:
        return "0"
    connection = _db(pack)
    if connection is None:
        return "0"
    try:
        running = connection.execute(
            "select count(*) from tasks where status in ('running', 'in_progress', 'claimed')"
        ).fetchone()[0]
    except sqlite3.Error as exc:
        raise RuntimeError(str(exc)) from exc
    finally:
        connection.close()
    if not running:
        return "0"
    if "/" in argv[0] and not os.path.isabs(argv[0]):
        argv[0] = os.path.join(pack["_dir"], argv[0])
    try:
        subprocess.Popen(
            argv, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True
        )
    except OSError as exc:
        raise RuntimeError(f"awake: {exc}") from exc
    return str(running)


GUARD_SECONDS = 120


def unguard(pack, now=None) -> str:
    """A ready card Hermes's respawn guard holds for a PR link in a comment (`active_pr`) never runs again: the guard reads
    the link as a worker who already opened a PR. Its own exemption is a handoff to another profile after that comment, so
    a card guarded for two minutes goes to another seat of its kind and straight back. A kind with one seat cannot be
    handed off; its card stays and the human sees it."""
    import time

    from .lanes import seats_from

    moment = int(time.time() if now is None else now)
    connection = _db(pack)
    if connection is None:
        return "0"
    found = []
    try:
        tables = {row[0] for row in connection.execute("select name from sqlite_master where type = 'table'")}
        columns = {row[1] for row in connection.execute("pragma table_info(tasks)")}
        if "task_events" not in tables or "assignee" not in columns:
            return "0"
        claim = " and claim_lock is null" if "claim_lock" in columns else ""
        for card, lane in connection.execute(
            f"select id, assignee from tasks where status = 'ready'{claim}"
        ).fetchall():
            last = connection.execute(
                "select kind, payload from task_events where task_id = ? and kind in "
                "('respawn_guarded', 'unblocked', 'assigned', 'spawned') order by id desc limit 1",
                (card,),
            ).fetchone()
            if not last or last[0] != "respawn_guarded" or "active_pr" not in str(last[1] or ""):
                continue
            since = connection.execute(
                "select min(created_at) from task_events where task_id = ? and kind = 'respawn_guarded' and id > "
                "coalesce((select max(id) from task_events where task_id = ? and kind in ('unblocked', 'assigned', 'spawned')), 0)",
                (card, card),
            ).fetchone()[0]
            if since is None or moment - int(since) < GUARD_SECONDS:
                continue
            found.append((str(card), str(lane or "")))
    except sqlite3.Error as exc:
        raise RuntimeError(str(exc)) from exc
    finally:
        connection.close()
    from .settings import load as load_settings

    seats = seats_from(dict(pack, seats=load_settings(pack)["seats"]))
    owned = _owned_cards(pack)
    writes = BoardWrites(pack["board"])
    handed = 0
    for card, lane in found:
        if _hand_over(owned, card):
            continue
        kind = next((name for name, lanes in seats.items() if lane in lanes), "")
        other = next((name for name in seats.get(kind) or [] if name != lane), "")
        if not other:
            continue
        writes.assign(card, other)
        writes.assign(card, lane)
        writes.comment(
            card,
            "cockpit",
            f"unguarded: a PR link in a comment made Hermes's respawn guard hold this card (active_pr); "
            f"handed to {other} and back so it runs",
        )
        handed += 1
    writes.flush()
    return str(handed)


def _blocked_at(connection, card: str) -> int:
    """The latest block comment. A comment from before the lend is not a new block."""
    tables = {row[0] for row in connection.execute("select name from sqlite_master where type = 'table'")}
    if "task_comments" not in tables:
        return 0
    columns = {row[1] for row in connection.execute("pragma table_info(task_comments)")}
    if "created_at" not in columns or "task_id" not in columns:
        return 0
    latest = connection.execute(
        "select created_at from task_comments where task_id = ? order by created_at desc limit 1",
        (card,),
    ).fetchone()
    if not latest:
        return 0
    text = str(latest[0] or "")
    if not text.isdigit():
        return 0
    return int(text)


def return_lends(pack) -> str:
    """Take back a lend whose card ended, disappeared, blocked again, or aged out."""

    def status_of(card):
        connection = _db(pack)
        if connection is None:
            return None, 0
        try:
            columns = {row[1] for row in connection.execute("pragma table_info(tasks)")}
            if "id" not in columns or "status" not in columns:
                return None, 0
            row = connection.execute("select status from tasks where id = ?", (card,)).fetchone()
            if not row:
                return None, 0
            status = row[0]
            when = 0
            if status in ("blocked", "triage"):
                when = _blocked_at(connection, card)
            return status, when
        except sqlite3.Error:
            return None, 0
        finally:
            connection.close()

    return str(len(take_back(status_of=status_of)))


def _seen_logins() -> set:
    from .paths import watch_dir

    path = os.path.join(watch_dir(), "login-unblocked.json")
    if not os.path.isfile(path):
        return set()
    try:
        loaded = json.loads(open(path, encoding="utf-8").read() or "[]")
    except json.JSONDecodeError:
        return set()
    if not isinstance(loaded, list):
        return set()
    return {str(item) for item in loaded}


def _save_logins(seen) -> None:
    from .paths import watch_dir

    folder = watch_dir()
    os.makedirs(folder, exist_ok=True)
    dump_json(os.path.join(folder, "login-unblocked.json"), sorted(seen))


def _credential_cards(connection, columns) -> list:
    """Cards blocked for a login. The reason may be the result column or the card comment."""
    found = []
    if "id" in columns and "status" in columns:
        rows = connection.execute("select id from tasks where status = 'blocked'").fetchall()
        found.extend(
            str(row[0]) for row in rows if block_reason(connection, str(row[0])).startswith("CREDENTIALS NEEDED")
        )
    tables = {row[0] for row in connection.execute("select name from sqlite_master where type = 'table'")}
    if "task_comments" not in tables or "id" not in columns or "status" not in columns:
        return found
    comment_columns = {row[1] for row in connection.execute("pragma table_info(task_comments)")}
    if "body" not in comment_columns or "task_id" not in comment_columns:
        return found
    rows = connection.execute(
        "select tasks.id from tasks join task_comments on task_comments.task_id = tasks.id "
        "where tasks.status = 'blocked' and task_comments.body like 'CREDENTIALS NEEDED%'"
    ).fetchall()
    for row in rows:
        card = str(row[0])
        if card not in found:
            found.append(card)
    return found


def _block_key(connection, card: str) -> str:
    """One block of one card: its latest comment and its latest Hermes block event.

    A block made through a comment changes the first; a lane that blocks itself through Hermes changes the second.
    """
    tables = {row[0] for row in connection.execute("select name from sqlite_master where type = 'table'")}
    comment = None
    if "task_comments" in tables:
        comment = connection.execute("select max(id) from task_comments where task_id = ?", (card,)).fetchone()[0]
    event = None
    if "task_events" in tables:
        event = connection.execute(
            "select max(id) from task_events where task_id = ? and kind in ('blocked', 'block_loop_detected')", (card,)
        ).fetchone()[0]
    return f"{card}#{comment or 0}#e{event or 0}"


def unblock_logins(pack) -> str:
    """Answer each credentials block once. A new block on the same card is answered once; a repeat of it is not."""
    connection = _db(pack)
    if connection is None:
        return "0"
    writes = BoardWrites(pack["board"])
    try:
        columns = {row[1] for row in connection.execute("pragma table_info(tasks)")}
        seen = _seen_logins()
        sent = 0
        for card_id in _credential_cards(connection, columns):
            key = _block_key(connection, card_id)
            if key in seen:
                continue
            earlier = key.rsplit("#e", 1)[0]
            if earlier in seen:
                # Answered before the key named Hermes's block event: the same block, now under its full key.
                seen.discard(earlier)
                seen.add(key)
                continue
            writes.unblock(card_id)
            seen.add(key)
            sent += 1
    except sqlite3.Error as exc:
        raise RuntimeError(str(exc)) from exc
    finally:
        connection.close()
    writes.flush()
    _save_logins(seen)
    return str(sent)


def retry_sweeps(pack) -> str:
    """A gatekeeper sweep that blocked is run again once: its work is mechanical (check, endorse, hold, send back), and
    what it needs of the human it asks through an intent's hold, never through its own card. A block there is a command
    that failed or a context that changed, and the next run usually passes. A second block of the same card stays
    blocked and is the human's row, so a real fault is still seen."""
    from .gate import SWEEP_KIND
    from .kanban import _index
    from .paths import watch_dir
    from .store import read_json, write_json

    connection = _db(pack)
    if connection is None:
        return "0"
    kinds = _index().get(pack["board"]) or {}
    path = os.path.join(watch_dir(), "sweep-retried.json")
    seen = set(read_json(path) or [])
    writes = BoardWrites(pack["board"])
    sent = 0
    try:
        for (card_id,) in connection.execute("select id from tasks where status = 'blocked'").fetchall():
            entry = kinds.get(str(card_id)) if isinstance(kinds.get(str(card_id)), dict) else {}
            if entry.get("kind") != SWEEP_KIND or str(card_id) in seen:
                continue
            writes.comment(
                str(card_id),
                "cockpit",
                "Run again: check the outbox as it is now. An intent already held or sent "
                "back is done; what is still pending is yours. A command that fails twice is the human's: block again and say which.",
            )
            writes.unblock(str(card_id))
            seen.add(str(card_id))
            sent += 1
    except sqlite3.Error as exc:
        raise RuntimeError(str(exc)) from exc
    finally:
        connection.close()
    writes.flush()
    if sent:
        write_json(path, sorted(seen))
    return str(sent)


def published_seen() -> set:
    """The blocks unblock_published has answered (card and block key): each is answered once."""
    from .paths import watch_dir
    from .store import read_json

    return set(read_json(os.path.join(watch_dir(), "publish-unblocked.json")) or [])


def unblock_published(pack) -> str:
    """A card blocked until the human publishes an intent carries on when that intent is out: each block is answered
    once, with a comment naming what left. While a named intent has not left, the card waits."""
    from .gate import publish_wait
    from .paths import watch_dir
    from .store import write_json

    connection = _db(pack)
    if connection is None:
        return "0"
    path = os.path.join(watch_dir(), "publish-unblocked.json")
    seen = published_seen()
    writes = BoardWrites(pack["board"])
    sent = 0
    try:
        for (card_id,) in connection.execute("select id from tasks where status = 'blocked'").fetchall():
            wait = publish_wait(block_reason(connection, str(card_id)), str(card_id))
            key = _block_key(connection, str(card_id))
            if wait["open"] or not wait["out"] or key in seen:
                continue
            writes.comment(
                str(card_id), "cockpit", f"Published: {', '.join(wait['out'])}. Carry on with what waited for it."
            )
            writes.unblock(str(card_id))
            seen.add(key)
            sent += 1
    except sqlite3.Error as exc:
        raise RuntimeError(str(exc)) from exc
    finally:
        connection.close()
    writes.flush()
    if sent:
        write_json(path, sorted(seen))
    return str(sent)


def _has_slot(ticket: str, count: int) -> bool:
    from .slots import read_ticket

    if not ticket:
        return False
    for slot in range(1, count + 1):
        if read_ticket(slot) == ticket:
            return True
    return False


def _unbound(count: int) -> list:
    """A free slot with no ticket. A bound slot is left."""
    from .slots import read_ticket

    found = []
    for slot in free_slots(count):
        if read_ticket(slot):
            continue
        found.append(slot)
    return found


def _no_slot(title, body) -> bool:
    """A card whose environment needs no slot of this machine: the Test kickoff wrote "Environment: <name> (no slot)"."""
    return bool(
        re.search(r":\s*test on staging\b", title or "", re.I)
        or re.search(r"^Environment: .*\(no slot\)", body or "", re.M)
    )


def warm_waiting(pack) -> str:
    """A waiting worker or tester with no slot gets one cold unbound slot. A ticket that already has a slot is left."""
    if data_ready(pack) != "ready":
        return "0"
    slots = (pack.get("seats") or {}).get("slots") or 0
    free = [slot for slot in _unbound(slots) if data_ready(pack, slot) == "ready"]
    if not free:
        return "0"
    connection = _db(pack)
    if connection is None:
        return "0"
    try:
        rows = connection.execute("select title, assignee, body from tasks where status = 'ready'").fetchall()
    except sqlite3.Error as exc:
        connection.close()
        raise RuntimeError(str(exc)) from exc
    connection.close()
    pool = list(free)
    warmed = 0
    for title, assignee, body in rows:
        kind = (assignee or "").split("-")[0]
        if kind not in ("worker", "tester"):
            continue
        ticket = ticket_of(title or "")  # the Jira key: a per-repo card is "<ticket> <repo>: …"
        if _no_slot(title, body):  # a staging run needs nothing of this machine
            continue
        if _has_slot(ticket, slots):
            continue
        if not pool:
            break
        slot = pool.pop(0)
        owner = str(assignee or kind)
        if not owner.startswith("lane:"):
            owner = f"lane:{owner}"
        warm_slot(slot, ticket, owner, pack)
        claim(slot)
        warmed += 1
    return str(warmed)


def slot_assign(pack) -> str:
    """A ready worker or tester card whose ticket has no slot of its own (every slot taken, or its slot is the human's
    session) gets one comment saying it waits for a slot. warm-waiting gives it a slot when one frees."""
    from .paths import watch_dir
    from .slots import read_owner, read_ticket, slot_of

    slots = (pack.get("seats") or {}).get("slots") or 0
    path = os.path.join(watch_dir(), "slot-assign.json")
    try:
        told = json.load(open(path, encoding="utf-8"))
    except (OSError, ValueError):
        told = {}
    from .kanban import board_cards

    commented = 0
    writes = BoardWrites(pack["board"])
    for card in board_cards(pack["board"]):
        kind = str(card.get("assignee") or "").split("-")[0]
        if card.get("status") != "ready" or kind not in ("worker", "tester"):
            continue
        if _no_slot(card.get("title"), card.get("body")):
            continue
        ticket = card["ticket"]
        human = next(
            (
                number
                for number in range(1, slots + 1)
                if read_ticket(number) == ticket and read_owner(number) == "human"
            ),
            0,
        )
        if slot_of(ticket, slots) and not human:
            continue
        reason = (
            f"waiting for a slot: slot {human} is the human's session"
            if human
            else "waiting for a slot: every slot is taken"
        )
        if told.get(card["id"]) == reason:
            continue
        writes.comment(card["id"], "cockpit", reason)
        told[card["id"]] = reason
        commented += 1
    writes.flush()
    os.makedirs(watch_dir(), exist_ok=True)
    dump_json(path, told)
    return str(commented)


def staging_audit(pack) -> str:
    """The seat stores hold what cockpit placed and nothing else. A finding turns housekeeping red until fixed."""
    from .lane_vault import audit, store_stamps
    from .paths import watch_dir

    stamps = store_stamps(pack)
    path = os.path.join(watch_dir(), "staging-audit.json")
    try:
        last = json.load(open(path, encoding="utf-8"))
    except (OSError, ValueError):
        last = {}
    if not stamps or last.get("stamps") == stamps:
        return "0"
    findings = audit(pack)
    os.makedirs(watch_dir(), exist_ok=True)
    if findings:
        dump_json(path, {"findings": [str(item) for item in findings]})
        raise CockpitError(f"vault audit: {len(findings)} findings ({findings[0]}); cockpit vault audit --fix")
    dump_json(path, {"stamps": stamps})
    return "0"


STEPS = (
    ("settle-reviews", settle_reviews),
    ("unfinished-runs", return_unfinished),
    ("own-session", clear_own_session),
    ("unstrand", unstrand),
    ("reclaim-dead", reclaim_dead),
    # provider quotas: last good plan readings, provider-limit holds, ready cards wait at the ceiling (cockpitlib.quota)
    ("quota", lambda pack: __import__("cockpitlib.quota", fromlist=["step"]).step(pack)),
    # a card a lane parked as scheduled: ready again at its SCHEDULED_UNTIL, an Inbox row while it waits
    ("wake-scheduled", lambda pack: __import__("cockpitlib.scheduled", fromlist=["step"]).step(pack)),
    ("unguard", unguard),
    ("awake", awake),
    ("return-lends", return_lends),
    ("unblock-logins", unblock_logins),
    ("unblock-published", unblock_published),
    ("retry-sweeps", retry_sweeps),
    ("rework-queued", lambda pack: __import__("cockpitlib.acts", fromlist=["rework_queued"]).rework_queued(pack)),
    (
        "decompose-queued",
        lambda pack: __import__("cockpitlib.decompose", fromlist=["decompose_queued"]).decompose_queued(pack),
    ),
    ("warm-waiting", warm_waiting),
    ("slot-assign", slot_assign),
    ("staging-audit", staging_audit),
    ("auto-publish", auto_publish),
    ("sweep", sweep),
    ("resweep-held", resweep_held),
    ("base-gone", base_gone),
    ("recard", recard),
    ("closeout-returned", closeout_returned),
    ("ticket-ready", ticket_ready),
    (
        "release-reviewers",
        lambda pack: __import__("cockpitlib.acts", fromlist=["release_reviewers"]).release_reviewers(pack),
    ),
    ("update-check", lambda pack: __import__("cockpitlib.self_update", fromlist=["check_if_due"]).check_if_due()),
    ("worktree-gc", lambda pack: __import__("cockpitlib.cleanup", fromlist=["run_if_due"]).run_if_due(pack)),
    # the tracker under watch while a ticket's done row waits for the human's ack (cockpitlib.tracker_watch)
    ("tracker-watch", lambda pack: __import__("cockpitlib.tracker_watch", fromlist=["watch"]).watch(pack)["out"]),
)


LOCKED = "skipped: the vault's private key is not on this machine"


def _locked(exc) -> bool:
    """A step that needed to open a vault entry on a machine that holds only the public key. That is the sealed
    install, not a fault: the step waits for the machine with the key."""
    from .vault_key import VaultLocked

    if isinstance(exc, VaultLocked):  # a passphrase or a security key the step may not use on its own
        return True
    text = str(exc).lower()
    return "no secret key" in text or "decryption failed" in text


def run(pack) -> str:
    lines = []
    failed = False
    for name, step in STEPS:
        try:
            lines.append(f"{name}: {step(pack)}")
        except Exception as exc:  # noqa: BLE001 - one step failing is that step's line; the sweep goes on
            if _locked(exc):
                lines.append(f"{name}: {LOCKED}")
                continue
            failed = True
            lines.append(f"{name}: {exc}")
    detail = "; ".join(lines)
    if failed:
        _health_hold("housekeeping", detail)
        return detail
    _health("housekeeping", detail)
    return detail
