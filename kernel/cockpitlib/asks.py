# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""A pack's own approvals (pack.yaml `asks`): a lane blocks with a line that starts with an ask's mark, the Inbox offers
Approve and Deny. Approve runs the pack's command as the human and resumes the card with what the command printed; the
kernel knows nothing of what the command does. Deny answers the card with the pack's words."""

import os
import subprocess
import threading

from .errors import CockpitError
from .store import read_db

_RUNNING = set()  # cards whose approval command runs now: a second Approve is refused, never run twice
_LOCK = threading.Lock()


def entries(pack) -> dict:
    return dict((pack or {}).get("asks") or {})


def match(pack, question: str):
    """(name, entry) of the ask a block question makes, else (None, None)."""
    text = (question or "").strip()
    for name, entry in entries(pack).items():
        if text.startswith(str(entry.get("mark") or "").strip()):
            return name, entry
    return None, None


def row(pack, question: str) -> dict:
    """What the Inbox needs to offer the ask: its name, button label and denial words."""
    name, entry = match(pack, question)
    if not name:
        return {}
    return {"name": name, "label": str(entry.get("label") or "Approve"), "deny": str(entry.get("deny") or "no")}


def approve(pack, card_id: str, timeout: int = 600) -> dict:
    """Run the ask's command for the card that made it, then resume the card with the command's last lines."""

    from .acts import answer_card
    from .kanban import block_reason, db_path, ticket_of
    from .skill_log import card_of

    card = card_of(str(pack["board"]), card_id)
    if not card:
        raise CockpitError(f"no card {card_id}")
    if card.get("status") not in ("blocked", "triage"):
        raise CockpitError(f"card {card_id} is {card.get('status')}: not waiting for an approval")
    connection = read_db(db_path(pack["board"]))
    try:
        question = block_reason(connection, card_id)
    finally:
        connection.close()
    name, entry = match(pack, question)
    if not name:
        raise CockpitError(f"card {card_id} is not asking for any of the pack's approvals")
    values = {
        "pack": pack.get("_dir") or "",
        "lane": card.get("assignee") or "",
        "card": card_id,
        "ticket": ticket_of(card.get("title") or ""),
    }
    argv = [str(word).format(**values) for word in entry["command"]]
    env = {**os.environ, "COCKPIT_HUMAN": "1", "COCKPIT_ASK_QUESTION": question}
    with _LOCK:
        if card_id in _RUNNING:
            raise CockpitError(f"{name}: the approval for {card_id} is already running")
        _RUNNING.add(card_id)
    try:
        done = subprocess.run(
            argv, capture_output=True, text=True, timeout=timeout, check=False, env=env, cwd=pack.get("_dir") or None
        )
    except subprocess.TimeoutExpired as exc:
        raise CockpitError(f"{name}: the approval command did not finish within {timeout}s") from exc
    except OSError as exc:
        raise CockpitError(f"{name}: the approval command could not start: {exc}") from exc
    finally:
        with _LOCK:
            _RUNNING.discard(card_id)
    said = (done.stdout or "").strip()
    if done.returncode != 0:
        tail = ((done.stderr or "") + "\n" + said).strip().splitlines()[-4:]
        raise CockpitError(f"{name}: the approval failed: " + " ".join(tail)[:400])
    answered = answer_card(pack, card_id, "approved: " + (said[-1500:] or name))
    return {
        "ok": True,
        "name": name,
        "out": f"{name} approved for {values['lane'] or card_id}; {answered.get('out') or 'resumed'}",
    }
