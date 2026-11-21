# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The tracker under watch while a ticket's "done, confirm?" row is in the Inbox.

A ticket whose `ticket-done` is pending is finished for the pipeline but not yet for the human: the tracker's issue
can still move (a reporter answers the results post, a reviewer edits a note). While the row waits, housekeeping
reads the issue's comments every few minutes; a comment that is new since the watch began, or one whose text was
edited, becomes one Inbox row for the human to read and dismiss. Nothing follows from it: no card, no intent. The
watch ends with the row (acknowledged, dropped, or retired by a reopen); the notes already made stay until dismissed.
Comments the pack's own tracker account wrote (the pipeline's posts, the human's own words) are not news.

State: watch/tracker-comments.json = {me, tickets: {ticket: {checked, seen: {comment id: updated}}}, notes: [...]}.
"""

import os
import time

from .errors import CockpitError
from .paths import watch_dir
from .store import log, read_json, write_json

INTERVAL = 300  # seconds between two reads of one ticket's comments
TEXT = 1200  # characters of a comment kept on the note


def _path() -> str:
    return os.path.join(watch_dir(), "tracker-comments.json")


def _state() -> dict:
    loaded = read_json(_path())
    state = loaded if isinstance(loaded, dict) else {}
    state.setdefault("tickets", {})
    state.setdefault("notes", [])
    return state


def watched() -> list:
    """The tickets whose done row waits for the human: a pending ticket-done."""
    from .intents import all_intents

    found = []
    for intent in all_intents():
        if (
            intent.get("type") == "ticket-done"
            and intent.get("status") == "pending"
            and intent.get("ticket") not in found
        ):
            found.append(intent["ticket"])
    return found


def _comments(reader, ticket: str) -> list:
    """The issue's comments, each {id, account, author, updated, created, text}. A tracker without a read for them (a
    pack's command that does not name one) cannot be watched."""
    return reader.comments(ticket)


def _me(reader, state) -> str:
    """The account the pack posts as, read once; a tracker that cannot say leaves it empty (nothing is skipped then)."""
    if "me" in state:
        return str(state["me"] or "")
    try:
        state["me"] = reader.me()
    except CockpitError:
        return ""
    return str(state["me"] or "")


def watch(pack, now=None) -> dict:
    """One pass: every watched ticket due for a read is read; the first read of a ticket is its baseline (what was there
    before the watch is not news); later reads note a new comment or an edited one. {read, notes, errors}."""
    from .tracker import reader_for

    moment = time.time() if now is None else now
    state = _state()
    tickets = watched()
    out = {"read": [], "notes": [], "errors": []}
    for gone in [ticket for ticket in state["tickets"] if ticket not in tickets]:
        state["tickets"].pop(gone, None)  # the row left: the watch ends; its notes stay until dismissed
    due = [
        ticket
        for ticket in tickets
        if moment - float((state["tickets"].get(ticket) or {}).get("checked") or 0) >= INTERVAL
    ]
    reader = reader_for(pack) if due else None
    for ticket in due:
        entry = state["tickets"].get(ticket) or {}
        try:
            comments = _comments(reader, ticket)
        except CockpitError as exc:
            out["errors"].append(f"{ticket}: {exc}")
            state["tickets"][ticket] = {**entry, "checked": moment, "error": str(exc)}
            continue
        me = _me(reader, state)
        seen = entry.get("seen") if isinstance(entry.get("seen"), dict) else None
        current = {row["id"]: row["updated"] for row in comments}
        if seen is not None:
            for row in comments:
                if row["account"] and row["account"] == me:
                    continue
                kind = "new" if row["id"] not in seen else ("edited" if seen[row["id"]] != row["updated"] else "")
                if not kind:
                    continue
                note = {
                    "id": f"{ticket}-{row['id']}-{kind}-{int(moment)}",
                    "ticket": ticket,
                    "comment": row["id"],
                    "kind": kind,
                    "author": row["author"],
                    "at": row["updated"],
                    "text": row["text"][:TEXT],
                    "url": reader.comment_url(ticket, row["id"]),
                    "seen_at": moment,
                }
                state["notes"] = [
                    item
                    for item in state["notes"]
                    if not (item.get("comment") == row["id"] and item.get("ticket") == ticket)
                ] + [note]
                out["notes"].append(note["id"])
                log(f"TRACKER-NOTE {ticket} comment {row['id']} {kind} by {row['author']}")
                from .notify import notify

                notify(
                    pack,
                    "tracker_comment",
                    note["id"],
                    f"{ticket}: {reader.noun} comment {kind} by {row['author']}\n{row['text'][:400]}\n{note['url']}\n",
                    ticket=ticket,
                )
        state["tickets"][ticket] = {"checked": moment, "seen": current}
        out["read"].append(ticket)
    write_json(_path(), state)
    out["out"] = f"{len(out['read'])} read, {len(out['notes'])} noted" + (
        f", {len(out['errors'])} failed" if out["errors"] else ""
    )
    return out


def rows() -> list:
    """The notes the human has not dismissed, newest first, each with its text rendered."""
    from .render import markdown

    found = []
    for note in reversed(_state()["notes"]):
        found.append({**note, "text_html": markdown(note.get("text") or "")})
    return found


def dismiss(note_id: str) -> dict:
    """Read: the note leaves. Nothing else happens."""
    note_id = (note_id or "").strip()
    state = _state()
    kept = [item for item in state["notes"] if item.get("id") != note_id]
    if len(kept) == len(state["notes"]):
        raise CockpitError(f"no tracker note {note_id or '?'}")
    state["notes"] = kept
    write_json(_path(), state)
    return {"ok": True, "id": note_id, "out": f"note {note_id} dismissed"}
