# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""A finished question card's answer, as the Inbox lists it.

A question kickoff (a mode whose capacity bucket is `question`: the analyst) ends with the board's complete call, and
the Inbox lists open cards only, so the answer sat in the Board's Done stack, where nobody saw it. Here each done
question card is a row until the human uses it (a reopen, a rework, a kickoff that cites it) or dismisses it: the
lane's summary, the files it wrote under qa/<ticket>/ as references, the first report rendered. The state is a file
(watch/answers.json), so the row survives a restart and holds no seat; the Board's card is unchanged.
"""

import os
import re
import sqlite3
import time
from datetime import UTC

from .errors import CockpitError
from .paths import qa_of, watch_dir, workspace
from .store import read_db, read_json, write_json

KERNEL_FOLDERS = ("human", "skills", "advisor", "pr")  # written by cockpit around a card, never by the lane
SLACK = 120  # seconds either side of the card's run: a file written just before the claim or at the complete call
REFERENCES = 40  # a card that wrote more is listed by its newest files
SUMMARY = 4000


def _path() -> str:
    return os.path.join(watch_dir(), "answers.json")


def _state() -> dict:
    loaded = read_json(_path())
    return loaded if isinstance(loaded, dict) else {}


def question_kinds(pack) -> dict:
    """{title_kind: mode} for every kickoff mode that asks a question (capacity bucket `question`)."""
    from .registry import kickoff_modes

    return {
        entry["title_kind"]: name
        for name, entry in kickoff_modes(pack).items()
        if entry.get("capacity_bucket") == "question"
    }


def _done_cards(pack, kinds) -> list:
    """The done cards cockpit made for a question mode, newest first, with when they ran and what they ended with."""
    from .kanban import _index, block_reason, completion_summary, db_path, ticket_of

    path = db_path(pack["board"])
    if not os.path.isfile(path) or not kinds:
        return []
    entries = _index().get(pack["board"]) or {}
    wanted = {card for card, entry in entries.items() if isinstance(entry, dict) and entry.get("kind") in kinds}
    if not wanted:
        return []
    connection = read_db(path)
    connection.row_factory = sqlite3.Row
    found = []
    try:
        columns = {row[1] for row in connection.execute("pragma table_info(tasks)")}
        if not {"id", "title", "status"} <= columns:
            return []
        for row in connection.execute("select * from tasks where status = 'done'").fetchall():
            if row["id"] not in wanted:
                continue
            entry = entries[row["id"]]
            title = row["title"] or ""
            found.append(
                {
                    "card": row["id"],
                    "title": title,
                    "kind": entry.get("kind"),
                    "ticket": entry.get("ticket") or ticket_of(title),
                    "lane": (row["assignee"] if "assignee" in columns else "") or "",
                    "created": row["created_at"] if "created_at" in columns else None,
                    "started": row["started_at"] if "started_at" in columns else None,
                    "completed": row["completed_at"] if "completed_at" in columns else None,
                    # a card the human closed with `stop` carries the human's words in result: the lane's last block (its
                    # verdict, the paths it named) is the answer then
                    "summary": (block_reason(connection, row["id"]) if entry.get("ended_by") == "owner" else "")
                    or completion_summary(connection, row["id"]),
                    "follows": str(entry.get("follows") or ""),
                }
            )
    except sqlite3.Error:
        return []
    finally:
        connection.close()
    found.sort(key=lambda card: float(card["completed"] or card["created"] or 0), reverse=True)
    return found


def _epoch(value) -> float:
    try:
        stamp = float(value)
    except (TypeError, ValueError):
        return 0.0
    return stamp / 1000 if stamp > 1e12 else stamp


def references(ticket: str, started, completed, summary: str = "") -> list:
    """The files under qa/<ticket>/ the card wrote: those whose mtime falls in its run (started … completed, with a little
    slack), plus any the summary names. Cockpit's own folders are left out. Each: {name, rel, path, size, mtime}; the
    ones the summary names come first, then markdown, then the rest, newest first."""
    folder = qa_of(ticket)
    if not ticket or not os.path.isdir(folder):
        return []
    low = _epoch(started) - SLACK if started else 0.0
    high = (_epoch(completed) + SLACK) if completed else time.time() + SLACK
    named = set()
    for token in re.findall(r"[\w./-]*qa/" + re.escape(ticket) + r"/[\w./-]+", summary or ""):
        tail = token.split(f"qa/{ticket}/", 1)[1].rstrip(".,;:)")
        candidate = os.path.normpath(os.path.join(folder, tail))
        if candidate.startswith(folder + os.sep) and os.path.isfile(candidate):
            named.add(candidate)
    found = {}
    for root, dirs, files in os.walk(folder):
        top = os.path.relpath(root, folder).split(os.sep)[0]
        if top in KERNEL_FOLDERS:
            dirs[:] = []
            continue
        dirs[:] = sorted(name for name in dirs if not name.startswith("."))
        for name in sorted(files):
            if name.startswith("."):
                continue
            path = os.path.join(root, name)
            try:
                stat = os.stat(path)
            except OSError:
                continue
            if path in named or (low and low <= stat.st_mtime <= high):
                found[path] = stat
    root = os.path.realpath(workspace())

    def key(item):
        path, stat = item
        return (0 if path in named else 1, 0 if path.endswith(".md") else 1, -stat.st_mtime, path)

    rows = []
    for path, stat in sorted(found.items(), key=key)[:REFERENCES]:
        rows.append(
            {
                "name": os.path.basename(path),
                "rel": os.path.relpath(os.path.realpath(path), root),
                "path": path,
                "size": stat.st_size,
                "mtime": int(stat.st_mtime),
            }
        )
    return rows


def shared_files(ticket: str, kind: str) -> list:
    """The ticket's own files of this question kind (`<kind>-*.md` at the top of qa/<ticket>/), for a card that wrote
    none of its own in its run: a later card of the kind rewrote them (a ticket's second analyst card can rewrite the
    first's findings). Marked `shared`, so the pane says they are the ticket's, not this card's."""
    folder = qa_of(ticket)
    if not ticket or not kind or not os.path.isdir(folder):
        return []
    root = os.path.realpath(workspace())
    rows = []
    for name in sorted(os.listdir(folder)):
        path = os.path.join(folder, name)
        if not (name.startswith(f"{kind}-") and name.endswith(".md") and os.path.isfile(path)):
            continue
        stat = os.stat(path)
        rows.append(
            {
                "name": name,
                "rel": os.path.relpath(os.path.realpath(path), root),
                "path": path,
                "size": stat.st_size,
                "mtime": int(stat.st_mtime),
                "shared": True,
            }
        )
    return rows


def _report(refs) -> tuple:
    """The first markdown reference, rendered, and its name."""
    from .render import markdown

    for item in refs:
        if item["name"].endswith(".md"):
            try:
                text = open(item["path"], encoding="utf-8").read()
            except (OSError, UnicodeDecodeError):
                continue
            return markdown(text), item["name"]
    return "", ""


def _rework_repos(pack, ticket: str) -> list:
    """The repos a rework can go to: those with an author PR record, else the ticket's checkouts."""
    from .acts import _ticket_repos

    folder = qa_of(ticket, "pr")
    delivered = []
    for name in sorted(os.listdir(folder)) if os.path.isdir(folder) else []:
        record = read_json(os.path.join(folder, name)) if name.endswith(".json") else None
        if (
            isinstance(record, dict)
            and record.get("role", "author") == "author"
            and record.get("repo")
            and record["repo"] not in delivered
        ):
            delivered.append(record["repo"])
    return delivered or _ticket_repos(pack, ticket)


def followup_text(card: str, ticket: str, mode: str, refs) -> str:
    """The preset of the follow-up box: a patch plan from the answer, no second investigation."""
    read = ", ".join(item["rel"] for item in refs) or "the card's summary"
    return (
        f"Follow-up to card {card} on {ticket}. Read {read}. Do not redo the investigation. Write a patch plan at "
        f"qa/{ticket}/{mode}-patch-plan.md in the plan-format shape: the one-line change, the impacted areas, the files, "
        "the tests, what is not touched. Complete with every file you wrote named in your summary."
    )


def reopen_prompt(summary: str, refs) -> str:
    """What a one-click reopen, rework or kickoff hands the next lane: the answer, then its files."""
    text = (summary or "").strip() or "See the referenced files."
    if refs:
        text += "\n\nReferences:\n" + "\n".join(f"- {item['rel']}" for item in refs)
    return text


def rows(pack, include_used: bool = False) -> list:
    """The Inbox's answer rows: every done question card not yet used or dismissed, newest first."""
    from .render import markdown

    kinds = question_kinds(pack)
    state = _state()
    found = []
    for card in _done_cards(pack, set(kinds)):
        mark = state.get(card["card"]) if isinstance(state.get(card["card"]), dict) else {}
        if not include_used and (mark.get("dismissed") or mark.get("used_by")):
            continue
        refs = references(
            card["ticket"], card["started"] or card["created"], card["completed"], card["summary"]
        ) or shared_files(card["ticket"], card["kind"])
        report_html, report_name = _report(refs)
        mode = kinds.get(card["kind"]) or card["kind"]
        summary = (card["summary"] or "")[:SUMMARY]
        found.append(
            {
                "card": card["card"],
                "ticket": card["ticket"],
                "title": card["title"],
                "lane": card["lane"],
                "mode": mode,
                "kind": card["kind"],
                "completed": _iso(card["completed"]),
                "summary": summary,
                "summary_html": markdown(summary) if summary else "",
                "references": refs,
                "report_html": report_html,
                "report_name": report_name,
                "follows": card["follows"],
                "followup_text": followup_text(card["card"], card["ticket"], mode, refs),
                "reopen_prompt": reopen_prompt(summary, refs),
                "rework_repos": _rework_repos(pack, card["ticket"]),
                "used_by": list(mark.get("used_by") or []),
                "dismissed": mark.get("dismissed") or "",
            }
        )
    return found


def _iso(value) -> str:
    stamp = _epoch(value)
    if not stamp:
        return ""
    from datetime import datetime

    return datetime.fromtimestamp(stamp, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _row(pack, card: str) -> dict:
    card = (card or "").strip()
    found = next((row for row in rows(pack, include_used=True) if row["card"] == card), None) if card else None
    if found is None:
        raise CockpitError(f"no answer row for card {card or '?'}")
    return found


def dismiss(pack, card: str) -> dict:
    """The human read it: the row leaves. The card stays on the Board."""
    row = _row(pack, card)
    from .time_util import iso

    state = _state()
    state[row["card"]] = {**(state.get(row["card"]) or {}), "dismissed": iso()}
    write_json(_path(), state)
    return {"ok": True, "card": row["card"], "out": f"{row['ticket']}: answer of {row['card']} dismissed"}


def use(card: str, kind: str, by: str) -> bool:
    """A reopen, rework or kickoff cited this answer: the row records it and leaves. False when the card is not an
    answer row (nothing to record)."""
    card = (card or "").strip()
    if not card:
        return False
    from .time_util import iso

    state = _state()
    mark = state.get(card) if isinstance(state.get(card), dict) else {}
    mark["used_by"] = [*(mark.get("used_by") or []), {"kind": kind, "card": by, "time": iso()}]
    state[card] = mark
    write_json(_path(), state)
    return True


def followup(pack, card: str, prompt: str = "") -> dict:
    """A new card of the same question mode on the same ticket, with the answer's files as its evidence and the follow-up
    text (the patch-plan preset unless the human wrote their own). Its answer comes back as a row that `follows` this one;
    this row stays until dismissed."""
    row = _row(pack, card)
    from .kanban import mark_card
    from .kickoff import start

    text = (prompt or "").strip() or row["followup_text"]
    made = start(pack, row["mode"], row["ticket"], prompt=text, evidence=[item["rel"] for item in row["references"]])
    mark_card(pack["board"], made["card_id"], follows=row["card"])
    made["out"] = (
        f"{row['ticket']}: follow-up on {made['card_id']} for {made.get('lane') or 'a lane'}; its answer comes back here"
    )
    return made
