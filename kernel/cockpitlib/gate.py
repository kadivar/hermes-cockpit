# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The gate between the lanes' intents and the human's publish: the gatekeeper's sweep, holds that wait on the lanes,
intents sent back to their lane, the digest the human answers by number, and the ready-for-review announcement.
"""

import json
import os
import re

from .errors import CockpitError
from .intents import OPEN_STATUSES, ORDER, PUSHES, advance, all_intents, load, save
from .kanban import one_at_a_time
from .paths import outbox_of, qa_of
from .store import append_line, dump_json, log, read_db, write_text
from .time_util import iso

SWEEP_KIND = "sweep"
SWEEP_BODY = """Sweep the outbox. For each pending intent below:

1. `cockpit outbox show <id>` and `cockpit outbox verify <id>`.
2. Endorse it when it is right: `cockpit outbox endorse <id> <low|medium|high> "<why>"`.
3. Otherwise hold it: `cockpit outbox hold <id> --reason "<why>"`, with `--waits lane` when the ticket's cards still
   have to deliver, `--rework "<what to change>"` to send it back to its lane, or `--ask "<one question>"` with
   `--option`s when only the human can decide.

Skip ticket-done intents. Then complete this card with one line per intent.

Pending:
"""


def _outbox_file(name: str) -> str:
    return outbox_of(name)


def request_sweep(ticket: str = "") -> None:
    """An intent changed: ask for a sweep. The housekeeping step starts one gatekeeper card for it."""
    path = _outbox_file("_sweep.requested")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    append_line(path, (ticket or "-") + "\n")


def _platform_ticket(pack, what: str) -> str:
    from .pack import batch_project

    return f"{batch_project(pack)}-{what}"


def _card_status(pack, card: str) -> str:
    from .kanban import board_cards

    return next((row["status"] for row in board_cards(pack["board"], pack) if row["id"] == card), "")


@one_at_a_time
def sweep(pack) -> str:
    """One gatekeeper card at a time serves the sweep requests. A request it did not serve (the card did not finish)
    comes back for the next card."""
    from .kanban import card_title, open_twin, place_card

    requested, serving = _outbox_file("_sweep.requested"), _outbox_file("_sweep.serving")
    ticket = _platform_ticket(pack, "OUTBOX")
    if open_twin(pack["board"], SWEEP_KIND, ticket, title=card_title(SWEEP_KIND, ticket, pack=pack)):
        return "running"
    if os.path.exists(serving):
        card, *listed = [
            line.strip() for line in open(serving, encoding="utf-8").read().splitlines() if line.strip()
        ] or [""]
        if _card_status(pack, card) != "done":  # not finished (archived by hand, failed): the request is still open
            os.replace(serving, requested)
        else:
            os.remove(serving)
            _left_pending(pack, listed)
    _stranded_rows(pack)
    if not os.path.exists(requested):
        return "0"
    pending = [row for row in all_intents() if row.get("status") == "pending" and row.get("type") != "ticket-done"]
    if not pending:
        os.remove(requested)
        return "0"
    os.replace(requested, serving)
    body = SWEEP_BODY + "".join(f"- {row['id']} ({row['type']}, by {row.get('created_by')})\n" for row in pending)
    try:
        card = place_card(
            pack["board"],
            card_title(SWEEP_KIND, ticket, pack=pack),
            "gatekeeper",
            "ready",
            body=body,
            kind=SWEEP_KIND,
            ticket=ticket,
            pack=pack,
            skills=["cockpit:outbox"],
        )
    except CockpitError:
        os.replace(serving, requested)
        raise
    write_text(
        serving, "".join(line + "\n" for line in (card, *(row["id"] for row in pending)))
    )  # the card, then the intents it was asked to decide
    log(f"SWEEP {card} for {len(pending)} pending")
    return "1"


STRANDED_ROW = "stranded-"
SWEEP_PASSES = 2


def sweep_passes(pack) -> int:
    """How many sweeps may end without deciding an intent before it becomes the human's row (outbox.sweep_passes)."""
    return int(((pack or {}).get("outbox") or {}).get("sweep_passes") or SWEEP_PASSES)


def _passes() -> dict:
    try:
        data = json.load(open(_outbox_file("_sweep.passes.json"), encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _save_passes(state: dict) -> None:
    path = _outbox_file("_sweep.passes.json")
    if not state:
        if os.path.exists(path):
            os.remove(path)
        return
    dump_json(path, state)


def _stamp(intent) -> str:
    """What the gatekeeper was asked about: an amend makes it a new question."""
    return f"{intent.get('created_at') or ''} {intent.get('amended_at') or ''}"


def _left_pending(pack, listed) -> None:
    """A sweep card finished and an intent it listed is still pending: nobody endorsed or held it, and nothing asks for
    another sweep, so it would stay pending for good (and keep its ticket from being done). Ask again; the count of such
    sweeps per intent decides when the human gets the row instead."""
    state = _passes()
    again = False
    for intent in all_intents():
        if intent.get("id") not in listed or intent.get("status") != "pending" or intent.get("type") == "ticket-done":
            continue
        kept = state.get(intent["id"]) if isinstance(state.get(intent["id"]), dict) else {}
        count = (int(kept.get("n") or 0) if kept.get("stamp") == _stamp(intent) else 0) + 1
        state[intent["id"]] = {"n": count, "stamp": _stamp(intent)}
        again = again or count < sweep_passes(pack)
    _save_passes(state)
    if again:
        request_sweep()


def _stranded_rows(pack) -> None:
    """One Inbox row per intent that sweeps keep leaving pending: Sweep now, Send back or Drop. A ticket a plugin runs
    and a halted ticket are left alone; the row leaves once the intent is decided."""
    from . import own_rows
    from .halt import halted
    from .inbox import row_id
    from .owners import owner_of

    state = _passes()
    if not state and not own_rows.ids(STRANDED_ROW):
        return
    keep = set()
    for iid in sorted(state):
        try:
            intent = load(iid)
        except (FileNotFoundError, ValueError):
            intent = {}
        if intent.get("status") != "pending" or state[iid].get("stamp") != _stamp(intent):
            state.pop(iid)
            continue
        count = int(state[iid].get("n") or 0)
        ticket = intent.get("ticket") or ""
        if count < sweep_passes(pack) or owner_of(ticket) or halted(ticket):
            continue
        ident = STRANDED_ROW + row_id(iid)
        keep.add(ident)
        why = f"{count} gatekeeper sweep(s) ended without endorsing or holding it"
        own_rows.raise_row(
            {
                "id": ident,
                "icon": "⏳",
                "tone": "warn",
                "ticket": ticket,
                "action_label": "decide",
                "what": f"{iid} ({intent.get('type')}) is still pending: {why}. Nothing asks for another sweep, and it keeps {ticket} from being done",
                "detail": {
                    "title": f"Pending with no decision: {iid}",
                    "status": {"text": "pending · no decision", "color": "warn"},
                    "fields": [
                        {"label": "intent", "text": iid},
                        {"label": "what", "text": str(intent.get("agent_summary") or "")},
                        {"label": "written by", "text": str(intent.get("created_by") or "")},
                        {"label": "why it is here", "text": why},
                    ],
                    "actions": [
                        {
                            "label": "Sweep now",
                            "hint": "one more gatekeeper sweep for it",
                            "act": {"do": "sweep", "intent": iid},
                        },
                        {
                            "label": "Send back",
                            "hint": "a rework card for the lane that wrote it",
                            "act": {
                                "do": "send-back",
                                "intent": iid,
                                "instruction": "The gatekeeper did not decide on this intent. Check it against the ticket and amend it.",
                            },
                        },
                        {
                            "label": "Drop",
                            "danger": True,
                            "hint": "nothing leaves",
                            "act": {"do": "drop", "intent": iid, "note": "dropped: no sweep decided it"},
                        },
                    ],
                },
            }
        )
    _save_passes(state)
    own_rows.keep_only(STRANDED_ROW, keep)


def sweep_again(iid: str) -> str:
    """The human's Sweep now on a stranded intent: its count starts over and a sweep is asked for."""
    load(iid)
    state = _passes()
    state.pop(iid, None)
    _save_passes(state)
    request_sweep(iid.split("/", 1)[0])
    return f"a sweep is queued for {iid}"


def _since(stamp: str) -> float:
    import datetime

    try:
        return datetime.datetime.fromisoformat(str(stamp).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return 0.0


def _ticket_cards(pack, ticket: str) -> list:
    """(id, status, completed_at) of the ticket's cards."""
    import sqlite3

    from .kanban import db_path, ticket_of

    path = db_path(pack["board"])
    if not os.path.isfile(path):
        return []
    connection = read_db(path)
    try:
        rows = connection.execute("select id, title, status, completed_at from tasks").fetchall()
    except sqlite3.Error:
        return []
    finally:
        connection.close()
    return [(card, status, float(done or 0)) for card, title, status, done in rows if ticket_of(title or "") == ticket]


PROBE_RETRY_S = 600  # a hold over a probe error: git is read again this far apart,
PROBE_RETRIES = 6  # this many times; after that the human's Re-probe is what is left


def _now() -> float:
    import time

    return time.time()


def _retry_probe(pack, intent) -> bool:
    """A held push whose git could not be read when it was written: read it again. True when it went back to pending."""
    from .outbox import reprobe

    tried = (intent.get("hold") or {}).get("probe_retry") or {}
    if int(tried.get("n") or 0) >= PROBE_RETRIES or _now() - float(tried.get("at") or 0) < PROBE_RETRY_S:
        return False
    try:
        reprobe(intent["id"], pack=pack, actor="resweep")
    except CockpitError:
        kept = load(intent["id"])
        kept.setdefault("hold", {})["probe_retry"] = {"n": int(tried.get("n") or 0) + 1, "at": int(_now())}
        save(kept)
        return False
    return True


def publish_wait(reason: str, card: str, intents=None) -> dict:
    """A card blocked until the human publishes: it is the rework card of a returned push, its reason speaks of
    publishing, and the pushes filed before that one for the same repo of the ticket share its worktree and go out
    first. {open: those that have not left yet, nearest first; out: those that are published}; both empty when the block
    is about something else. The human's act is the Publish row of the push that is next, so the card is no row of its
    own, and it is unblocked when every earlier push is out (housekeeping.unblock_published)."""
    found = {"open": [], "out": []}
    if not card or "publish" not in str(reason or "").lower():
        return found
    from .intents import PUBLISHED

    rows = all_intents() if intents is None else intents
    mine = [
        row
        for row in rows
        if row.get("type") == "push-branch"
        and row.get("status") == "returned"
        and (row.get("returned") or {}).get("card") == card
    ]
    for push in mine:
        repo = (push.get("payload") or {}).get("repo")
        earlier = [
            row
            for row in rows
            if row.get("type") == "push-branch"
            and row.get("ticket") == push.get("ticket")
            and (row.get("payload") or {}).get("repo") == repo
            and row["id"] < push["id"]
            and row.get("status") != "dropped"
        ]
        for row in sorted(earlier, key=lambda row: row["id"], reverse=True):
            found["out" if row.get("status") in PUBLISHED else "open"].append(row["id"])
    return found


FOREIGN_HOLD = "the pushed range has commits by "  # outbox._probe's words for a push with another author's commits


def _foreign_declared(pack, intent) -> bool:
    """The hold is the foreign-commit one, asks nothing, and every author it named is in the pack's forge.human_emails now."""
    hold = intent.get("hold") or {}
    foreign = (intent.get("payload") or {}).get("foreign") or []
    mine = set((((pack or {}).get("forge") or {}).get("human_emails")) or [])
    return bool(
        intent.get("type") == "push-branch"
        and hold.get("waits") == "human"
        and not hold.get("ask")
        and str(hold.get("reason") or "").startswith(FOREIGN_HOLD)
        and foreign
        and set(foreign) <= mine
    )


def resweep_held(pack) -> str:
    """A hold that waits on the lanes goes back to pending once a card of its ticket completes after it; with no card
    left to deliver it becomes the human's. A hold over a probe error has its git read again (_retry_probe)."""
    from .kanban import OPEN

    moved = []
    for intent in all_intents():
        hold = intent.get("hold") or {}
        if intent.get("status") == "held" and (intent.get("payload") or {}).get("probe_error"):
            if _retry_probe(pack, intent):
                moved.append(intent["id"])
            continue
        if intent.get("status") == "held" and _foreign_declared(pack, intent):
            # held only for commits by someone the pack has since named as the human's own (forge.human_emails): the
            # hold asks nothing any more, so the intent is the gatekeeper's again instead of a row the human confirms
            intent.setdefault("history", []).append(
                {
                    "time": iso(),
                    "event": "hold re-checked: the pack names those authors as the human's",
                    "previous_hold": hold,
                }
            )
            intent.pop("hold", None)
            intent["payload"]["foreign"] = []
            advance(intent, "pending", "resweep")
            save(intent)
            moved.append(intent["id"])
            continue
        if intent.get("status") != "held" or hold.get("waits") != "lane":
            continue
        since = _since(hold.get("time"))
        cards = _ticket_cards(pack, intent["ticket"])
        delivered = [
            card for card, status, done in cards if status == "done" and done >= since
        ]  # both in whole seconds
        if delivered:
            intent.setdefault("history", []).append(
                {
                    "time": iso(),
                    "event": "hold re-checked: a card of the ticket completed",
                    "card": delivered[0],
                    "previous_hold": hold,
                }
            )
            intent.pop("hold", None)
            advance(intent, "pending", "resweep")
            save(intent)
            moved.append(intent["id"])
            continue
        if not any(status in OPEN for _card, status, _done in cards):
            intent["hold"]["waits"] = "human"
            intent.setdefault("history", []).append(
                {"time": iso(), "event": "hold handed to the human: no card left to deliver"}
            )
            save(intent)
    if moved:
        request_sweep()
        log(f"RESWEEP {' '.join(moved)}")
    return str(len(moved))


RETURN_BODY = """The intent {id} ({type}) was sent back with this instruction:

{instruction}
{evidence}
Rework it on the same checkout and branch, keeping what is already done. Then update the same intent, not a new one:
`cockpit outbox amend {id} --summary "<what changed>"` with the changed flags or drafts. Complete this card with what
you changed and the intent id; the gatekeeper checks the amended intent in its sweep.
"""


CODE_BODY = """The intent {id} ({type}, written by {writer}) was sent back with an instruction that needs a code change:

{instruction}
{evidence}
You did not write {id} and you do not amend it. Make the change on the ticket's own checkout and branch, keeping what is
already there, and file your push (`cockpit outbox new <ticket> push-branch …`; in a batch it waits for the stage before
it, as the batch's order says). A file the guard keeps closed to every lane (a CI workflow, a Dockerfile) is not written:
leave it as a patch under the ticket's records and file `cockpit outbox new <ticket> infra-note --repo <repo>
--branch <branch> --patch-file <path> --summary "<the commit's title>"`; the human applies it. Complete this card with
what you did and the intent ids; {writer} then redoes {id} on the new head.
"""


def _required_skills(pack, kind: str) -> list:
    names = []
    for item in ((pack.get("skills") or {}).get("intent") or {}).get(kind) or []:
        names.append(item[0] if isinstance(item, list) else item)
    return names


def _rework_card(pack, intent, lane: str, body: str, extra_skills=(), stamp: str = "") -> tuple:
    """(card, "") or ("", why): the card that carries a returned intent back to its lane, in the scope of the card that
    wrote it. An open card already carrying the intent gets the instruction as a comment instead of a second owner."""
    from .kanban import card_scope, card_title, place_card

    payload = intent.get("payload") or {}
    skills = list(dict.fromkeys(["cockpit:outbox", *_required_skills(pack, intent["type"]), *extra_skills]))
    try:
        holder = add_to_holder(pack["board"], intent["id"], "cockpit", body)
        if holder:
            return holder, ""
        card = place_card(
            pack["board"],
            card_title("rework", intent["ticket"], pack=pack),
            lane,
            "ready",
            body=body,
            skills=skills,
            kind="rework",
            ticket=intent["ticket"],
            pack=pack,
            repos=[payload["repo"]] if payload.get("repo") else [],
            idempotency_key=f"return-{intent['id']}-{stamp}",
            scope=card_scope(pack["board"], intent.get("card_id") or ""),
            intent=intent["id"],
        )
    except CockpitError as exc:
        return "", str(exc)
    return card, ""


@one_at_a_time
def send_back(pack, kind: str, ticket: str, lane: str, text: str, iid: str = "", refusal: str = "") -> tuple:
    """The card a refused intent goes back on, and whether it was there already: the open card that carries the intent
    gets the instruction; else a new card is made. Asked twice for one refusal, the second gets the first one's card."""
    import hashlib

    from .kanban import card_title, place_card

    holder = add_to_holder(pack["board"], iid, "human", text) if iid else ""
    if holder:
        return holder, True
    key = f"send-back-{hashlib.sha256(refusal.encode()).hexdigest()[:16]}" if refusal else ""
    card = place_card(
        pack["board"],
        card_title(kind, ticket, pack=pack),
        lane,
        "ready",
        body=text,
        kind=kind,
        ticket=ticket,
        pack=pack,
        intent=iid,
        idempotency_key=key,
    )
    return card, False


def add_to_holder(board: str, iid: str, author: str, body: str) -> str:
    """The open card already carrying this intent, with the new instruction commented on it (and unblocked when it was
    waiting), or empty when no card holds it."""
    from .kanban import BoardWrites, board_cards, open_holder

    holder = open_holder(board, iid)
    if not holder:
        return ""
    status = next((card["status"] for card in board_cards(board) if card["id"] == holder), "")
    writes = BoardWrites(board)
    writes.comment(holder, author, body)
    if status in ("blocked", "triage"):
        writes.unblock(holder)
    writes.flush()
    log(f"HOLDER {iid} → {holder}: instruction added")
    return holder


def _chain(pack, intent, after: str, instruction: str) -> list:
    """A rework that changes code is tested and reviewed like the first delivery: a tester card, then a reviewer card."""
    from .kanban import card_scope, card_title, open_cards, place_card
    from .lanes import free_lane

    ticket = intent["ticket"]
    repo = (intent.get("payload") or {}).get("repo") or ""
    scope = card_scope(pack["board"], after)
    made = []
    parent = after
    # `tester`, the chain's own kind: a tester card that follows a worker runs the plan's rows (a Test kickoff is `test`)
    for kind, role, text in (
        ("tester", "tester", "Test what the rework card {after} changed, and what its instruction adds:"),
        ("review", "reviewer", "Review the change the rework card {after} made, against the plan and its instruction:"),
    ):
        lane = free_lane(role, pack, open_cards(pack["board"]), ticket=ticket)
        body = text.format(after=after) + f"\n\n{instruction}\n"
        try:
            parent = place_card(
                pack["board"],
                card_title(kind, ticket, pack=pack),
                lane,
                "ready",
                body=body,
                parents=[parent],
                kind=kind,
                ticket=ticket,
                pack=pack,
                repos=[repo] if repo else [],
                idempotency_key=f"chain-{after}-{kind}",
                scope=scope,
            )
        except CockpitError:
            break
        made.append([lane, parent])
    return made


def return_intent(
    pack,
    iid: str,
    instruction: str,
    assignee: str = "",
    evidence=(),
    chain: bool = True,
    actor: str = "human",
    extra_skills=(),
) -> dict:
    """Send an intent back to the lane that wrote it: it is `returned` (the gatekeeper skips it, publish refuses it) and a
    card carries the instruction. A push or a pull request that changes code also gets a tester and a reviewer behind it.
    A card that could not be made now is made by the housekeeping step recard."""
    from .halt import refuse

    intent = load(iid)
    refuse(intent["ticket"])
    if intent["status"] == "posted":
        if actor != "human":
            raise CockpitError(f"{iid} is a pending review on the forge: only the human discards it")
        from .publish import discard_pending, forge_for

        discard_pending(intent, forge_for(pack))
    if intent["status"] not in ("pending", "endorsed", "held", "returned"):
        raise CockpitError(f"{iid} is {intent['status']}; only an open intent is sent back")
    lane = assignee or intent.get("created_by") or ""
    # "worker": the instruction asks for a code change the lane that wrote the intent cannot make (a reviewer does not
    # write in a checkout). A free worker takes the card; when it ends, the close-out hands the intent back to its writer.
    to_worker = assignee == "worker"
    if not lane or lane == "human" or to_worker:
        from .kanban import open_cards
        from .lanes import free_lane

        lane = free_lane("worker", pack, open_cards(pack["board"]), ticket=intent.get("ticket") or "")
    shown = "".join(f"\nEvidence: {path}\n" for path in evidence or [])
    body = (CODE_BODY if to_worker else RETURN_BODY).format(
        id=iid,
        type=intent["type"],
        instruction=instruction,
        evidence=shown,
        writer=intent.get("created_by") or "its lane",
    )
    seq = iid.split("/", 1)[1][:3]
    path = outbox_of(intent["ticket"], f"{seq}-return.md")
    write_text(path, body)
    stamp = iso()
    card, why = _rework_card(pack, intent, lane, body, extra_skills, stamp)
    chained = (
        _chain(pack, intent, card, instruction) if card and chain and intent["type"] in (*PUSHES, "open-pr") else []
    )
    from .paths import workspace

    intent["returned"] = {
        "time": stamp,
        "instruction": instruction,
        "lane": lane,
        "card": card,
        "previous_status": intent["status"],
        "chain": chained,
        "body_file": os.path.relpath(path, workspace()),
        "extra_skills": list(extra_skills),
        "no_chain": not chain,
        "by": actor,
        **({"card_error": why} if why else {}),
    }
    advance(intent, "returned", actor)
    intent.pop("endorsement", None)
    save(intent)
    log(f"RETURN {iid} → {lane} card={card or '-'}: {instruction}")
    if (pack.get("outbox") or {}).get("comment_card") and intent.get("card_id"):
        from .acts import note_card

        note_card(
            pack,
            intent["card_id"],
            "cockpit",
            f"{iid} was sent back to {lane}" + (f" (card {card})" if card else "") + f": {instruction[:600]}",
        )
    return intent


BASE_GONE = (
    "{base} is no longer on the remote: the PR this one was stacked on has landed (or its branch was removed), so a pull "
    "request into it cannot be opened. Rebase {branch} onto origin/{own} so that only this ticket's commits remain "
    "(a commit of the landed PR is dropped: {own} has it), then amend the push with the new commit and the pull request "
    "with base {own}, taking any line about the stack out of its body. Say in the amend whether the change against "
    "{own} is the same files and lines as before: if it is, no new test or review is needed."
)


def _base_gone_seen() -> str:
    from .paths import watch_dir

    return os.path.join(watch_dir(), "base-gone.json")


def base_gone(pack) -> str:
    """The housekeeping step for a stacked pull request whose base is gone. A PR may be opened into another PR's branch
    (the human's choice, to get a fix that is not on the repo's branch yet). When that PR lands and its branch is
    removed, the open one can no longer be opened and its branch carries commits the repo's branch now has in another
    form: unseen, that surfaces only when the human's Publish fails. Its push, else the pull request itself, goes
    back to its writer with the rebase to do; once per intent and base.

    A base that an open push of the pack is still to send is not gone: it is not there yet."""
    from .git_push import checkout, publish_name, remote_tip, repo_branch
    from .store import read_json, write_json

    rows = all_intents()
    coming = {
        (
            str((row.get("payload") or {}).get("repo")),
            publish_name(
                pack,
                (row.get("payload") or {}).get("repo") or "",
                str((row.get("payload") or {}).get("publish_as") or (row.get("payload") or {}).get("branch") or ""),
            ),
        )
        for row in rows
        if row.get("type") in PUSHES and row.get("status") in OPEN_STATUSES and (row.get("payload") or {}).get("repo")
    }
    seen = set(read_json(_base_gone_seen()) or [])
    sent = 0
    for intent in rows:
        payload = intent.get("payload") or {}
        repo, base = str(payload.get("repo") or ""), str(payload.get("base") or "")
        if (
            intent.get("type") != "open-pr"
            or intent.get("status") not in ("pending", "held", "endorsed")
            or not repo
            or not base
        ):
            continue
        own = repo_branch(pack, repo)
        mark = f"{intent['id']}|{base}"
        if base == own or mark in seen or (repo, base) in coming:
            continue
        try:
            if remote_tip(checkout(pack, intent["ticket"], repo), base):
                continue
            first = load(payload["after"]) if payload.get("after") else None
            target = first if first and first.get("status") in ("pending", "held", "endorsed") else intent
            if first and first.get("status") == "returned":
                continue  # its push is already back with a lane: looked at again when that is over
            return_intent(
                pack,
                target["id"],
                BASE_GONE.format(
                    base=base, own=own, branch=payload.get("head") or payload.get("branch") or "the branch"
                ),
                chain=False,
                actor="cockpit",
            )
        except (CockpitError, FileNotFoundError, OSError) as exc:
            log(f"BASE-GONE? {intent['id']} :: {str(exc)[-200:]}")
            continue
        seen.add(mark)
        sent += 1
        log(f"BASE-GONE {intent['id']} base {base} → {target['id']} returned")
    if sent:
        write_json(_base_gone_seen(), sorted(seen))
    return str(sent)


def recard(pack) -> str:
    """A returned intent whose rework card was never made gets it now, from the instruction the return kept."""
    from .paths import workspace

    made = 0
    for intent in all_intents():
        returned = intent.get("returned") or {}
        if intent.get("status") != "returned" or returned.get("card"):
            continue
        path = os.path.join(workspace(), returned.get("body_file") or "")
        if not os.path.isfile(path):
            continue
        card, why = _rework_card(
            pack,
            intent,
            returned.get("lane") or "worker-1",
            open(path, encoding="utf-8").read(),
            returned.get("extra_skills") or [],
            returned.get("time") or "",
        )
        if not card:
            returned["card_error"] = why
            save(intent)
            continue
        if intent["type"] in (*PUSHES, "open-pr") and not returned.get("no_chain"):
            returned["chain"] = _chain(pack, intent, card, returned.get("instruction") or "")
        returned["card"] = card
        returned.pop("card_error", None)
        save(intent)
        made += 1
        log(f"RECARD {intent['id']} → {card}")
    return str(made)


CLOSEOUT_BODY = """Close out {id} ({type}): its rework card {card} and the cards behind it ({chain}) ended without
`cockpit outbox amend {id}`. Amend it with what they produced (`cockpit outbox amend {id} --summary "<what changed>"` with the
changed flags or drafts), or complete this card saying why the human should drop it.

The instruction of the return:
{instruction}
"""


def closeout_returned(pack) -> str:
    """A returned intent whose rework card and the cards behind it ended without an amend gets one close-out card for its
    writer's kind of seat: nothing stays `returned` with no owner. One card per return; a ticket a plugin runs, a card of a
    plugin's kind, and a halted ticket are left alone."""
    from .halt import halted
    from .housekeeping import _owned_cards
    from .kanban import OPEN_STATUSES, board_cards, card_scope, card_title, open_cards, open_holder, place_card
    from .lanes import free_lane
    from .owners import owner_of

    board = pack["board"]
    cards = {card["id"]: card for card in board_cards(board)}
    owned = _owned_cards(pack)
    kind_of = {"worker": "rework", "tester": "tester", "reviewer": "review", "intake": "reopened", "analyst": "analyst"}
    made = 0
    for intent in all_intents():
        returned = intent.get("returned") or {}
        if (
            intent.get("status") != "returned"
            or not returned.get("card")
            or returned.get("resolved")
            or returned.get("closeout")
        ):
            continue
        ticket = intent["ticket"]
        chain = [pair[1] for pair in returned.get("chain") or [] if isinstance(pair, (list, tuple)) and len(pair) > 1]
        treated = [row.get("card") for row in intent.get("treatments") or [] if isinstance(row, dict)]
        if any((cards.get(card) or {}).get("status") in OPEN_STATUSES for card in (returned["card"], *chain, *treated)):
            continue
        if open_holder(board, intent["id"]) or owner_of(ticket) or halted(ticket):
            continue
        if any(card in owned for card, entry in cards.items() if entry["ticket"] == ticket):
            continue
        role = str(returned.get("lane") or "worker").split("-")[0]
        kind = kind_of.get(role, "rework")
        payload = intent.get("payload") or {}
        try:
            seat = free_lane(role if role in kind_of else "worker", pack, open_cards(board), ticket=ticket)
            body = CLOSEOUT_BODY.format(
                id=intent["id"],
                type=intent["type"],
                card=returned["card"],
                chain=", ".join(chain) or "none",
                instruction=returned.get("instruction") or "",
            )
            skills = list(
                dict.fromkeys(
                    ["cockpit:outbox", *_required_skills(pack, intent["type"]), *(returned.get("extra_skills") or [])]
                )
            )
            card = place_card(
                board,
                card_title(kind, ticket, pack=pack),
                seat,
                "ready",
                body=body,
                skills=skills,
                kind=kind,
                ticket=ticket,
                pack=pack,
                repos=[payload["repo"]] if payload.get("repo") else [],
                idempotency_key=f"closeout-{intent['id']}-{returned.get('time') or ''}",
                scope=card_scope(board, returned["card"]),
                intent=intent["id"],
            )
        except CockpitError as exc:
            returned["closeout_error"] = str(exc)
            save(intent)
            continue
        returned["closeout"] = {"card": card, "time": iso()}
        returned.pop("closeout_error", None)
        save(intent)
        made += 1
        log(f"CLOSEOUT {intent['id']} → {card}")
        if (pack.get("outbox") or {}).get("comment_card") and intent.get("card_id"):
            from .acts import note_card

            note_card(
                pack,
                intent["card_id"],
                "cockpit",
                f"{intent['id']} is still returned: its cards ended without an amend; close-out card {card}",
            )
    _return_rows(pack)
    return str(made)


RETURN_ROW = "returned-"


def _return_rows(pack) -> None:
    """A returned intent nothing can move any more is one Inbox row, written once, with Send back again and Drop: its
    close-out card ended without an amend, the file that kept its instruction is gone (no rework card can be made), or
    its close-out card cannot be placed. A ticket a plugin runs and a halted ticket are left alone; the row leaves
    when the intent is amended, sent back again or dropped."""
    from . import own_rows
    from .halt import halted
    from .inbox import row_id
    from .kanban import OPEN_STATUSES as OPEN_CARDS
    from .kanban import board_cards, open_holder
    from .owners import owner_of
    from .paths import workspace

    keep = set()
    cards = {card["id"]: card for card in board_cards(pack["board"])}  # read now: this pass's close-out cards are on it
    for intent in all_intents():
        returned = intent.get("returned") or {}
        if intent.get("status") != "returned" or returned.get("resolved"):
            continue
        ticket = intent["ticket"]
        closeout = (returned.get("closeout") or {}).get("card") or ""
        if not returned.get("card"):
            if os.path.isfile(os.path.join(workspace(), returned.get("body_file") or "-")):
                continue  # recard makes its card on this pass or the next
            why = "the file that kept its instruction is gone, so no rework card can be made for it"
        elif closeout and (cards.get(closeout) or {}).get("status") not in OPEN_CARDS:
            why = f"its rework card {returned['card']} and its close-out card {closeout} ended without `cockpit outbox amend`"
        elif returned.get("closeout_error"):
            why = f"its rework card {returned['card']} ended without an amend and no close-out card could be placed: {returned['closeout_error']}"
        else:
            continue
        iid = intent["id"]
        if owner_of(ticket) or halted(ticket) or open_holder(pack["board"], iid):
            continue
        ident = RETURN_ROW + row_id(iid)
        keep.add(ident)
        instruction = str(returned.get("instruction") or "")
        own_rows.raise_row(
            {
                "id": ident,
                "icon": "↩",
                "tone": "warn",
                "ticket": ticket,
                "action_label": "decide",
                "what": f"{iid} ({intent.get('type')}) was sent back and nobody owns it: {why}",
                "detail": {
                    "title": f"Sent back, never amended: {iid}",
                    "status": {"text": "returned · no owner", "color": "warn"},
                    "fields": [
                        {"label": "intent", "text": iid},
                        {"label": "sent back to", "text": str(returned.get("lane") or "")},
                        {"label": "the instruction", "text": instruction or "(not kept)"},
                        {"label": "why it is here", "text": why},
                    ],
                    "actions": [
                        {
                            "label": "Send back again",
                            "hint": "a new rework card with the same instruction",
                            "act": {
                                "do": "send-back",
                                "intent": iid,
                                "instruction": instruction or "Redo this intent and amend it.",
                            },
                        },
                        {
                            "label": "Drop",
                            "danger": True,
                            "hint": "nothing leaves",
                            "act": {"do": "drop", "intent": iid, "note": "dropped: sent back and never amended"},
                        },
                    ],
                },
            }
        )
    own_rows.keep_only(RETURN_ROW, keep)


# ---- the digest the human answers by number ----

STATUS_ORDER = {"endorsed": 0, "posted": 0, "pending": 1, "held": 2, "returned": 3}
RISK_ORDER = {"low": 0, "medium": 1, "high": 2}


def digest(pack=None) -> list:
    """Number the open intents: what may leave first, then each ticket in publish order. A rebase step that a content
    push follows publishes with it and gets no number of its own; an endorsed stage whose stage before is not out yet is
    not numbered (one reply never sends two stages of one sequence)."""
    from .sequence import waits

    rows = [row for row in all_intents() if row.get("status") in OPEN_STATUSES]
    rows = [
        row for row in rows if not (row["status"] == "endorsed" and waits(row, pack))
    ]  # a later stage is not offered yet
    followed = {(row.get("payload") or {}).get("after") for row in rows}
    rows = [row for row in rows if not ((row.get("payload") or {}).get("rebase_only") and row["id"] in followed)]
    rows.sort(
        key=lambda row: (
            STATUS_ORDER.get(row["status"], 9),
            row["ticket"],
            ORDER.get(row["type"], 99),
            RISK_ORDER.get((row.get("endorsement") or {}).get("risk") or row.get("risk_hint"), 1),
            row["id"],
        )
    )
    numbered = {str(index): row["id"] for index, row in enumerate(rows, 1)}
    path = _outbox_file("_digest.json")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    dump_json(path, {"time": iso(), "map": numbered}, indent=2)
    return [{"number": int(number), "id": iid} for number, iid in numbered.items()]


def numbers() -> dict:
    """intent id -> its number in the last digest."""
    try:
        found = json.load(open(_outbox_file("_digest.json"), encoding="utf-8")).get("map") or {}
    except (OSError, ValueError):
        return {}
    return {iid: int(number) for number, iid in found.items()}


REPLY = re.compile(r"^(publish|hold|drop|open)\s*(.*)$", re.I | re.S)


def _numbered(spec: str, mapping: dict) -> list:
    """[(intent id, named)]: `all` names none of them explicitly; `1-3,5` names each number it lists."""
    if spec.strip().lower() == "all":
        return [(mapping[key], False) for key in sorted(mapping, key=int)]
    found = []
    for part in re.split(r"[,\s]+", spec.strip()):
        if not part:
            continue
        if not re.fullmatch(r"\d+(-\d+)?", part):
            raise CockpitError(f"publish takes all or digest numbers (1-3,5), not {part!r}")
        low, _, high = part.partition("-")
        for number in range(int(low), int(high or low) + 1):
            if str(number) not in mapping:
                raise CockpitError(f"no intent #{number} in the last digest")
            found.append((mapping[str(number)], "-" not in part))
    return found


def reply(pack, text: str) -> list:
    """The human's answer to the digest: publish all | publish 1-3,5 | hold 4: <why> | drop 5 | open 2."""
    from .outbox import drop, hold

    mapping = {str(number): iid for iid, number in numbers().items()}
    if not mapping:
        raise CockpitError("no digest numbering yet: run `cockpit outbox digest` first")
    match = REPLY.match((text or "").strip())
    if not match:
        raise CockpitError("a reply starts with publish, hold, drop or open")
    verb, rest = match.group(1).lower(), match.group(2).strip()
    if verb == "publish":
        return _publish_numbers(pack, _numbered(rest, mapping))
    number, _, why = rest.partition(":")
    iid = mapping.get(number.strip())
    if not iid:
        raise CockpitError(f"{verb} takes a digest number from the last digest, not {number.strip()!r}")
    if verb == "hold":
        if not why.strip():
            raise CockpitError("hold takes the number and the reason: hold 4: <why>")
        hold(iid, "human: " + why.strip(), waits="human")
        return [f"held {iid}"]
    if verb == "drop":
        drop(iid, why.strip())
        return [f"dropped {iid}"]
    from .intents import path_of

    return [path_of(iid)]


def _publish_numbers(pack, chosen) -> list:
    from .publish import backfill_related, execute, forge_for, submit_review

    forge = forge_for(pack)
    lines = []
    tickets = []
    for iid, named in chosen:
        intent = load(iid)
        try:
            if intent["type"] == "pr-review-submit" and intent["status"] == "posted":
                if not named:
                    lines.append(f"{iid}: a posted review is submitted only when you name its number")
                    continue
                receipt = submit_review(intent, forge, explicit=True, pack=pack)
            else:
                receipt = execute(intent, forge, explicit_approve=named, pack=pack)
        except CockpitError as exc:
            receipt = {"ok": False, "error": str(exc)}
        if not receipt.get("ok"):
            lines.append(f"{iid}: {receipt.get('error')} (stopped here: fix or drop it, then publish again)")
            break
        lines.append(f"{iid}: {receipt.get('url') or 'published'}")
        if intent["type"] == "open-pr" and intent["ticket"] not in tickets:
            tickets.append(intent["ticket"])
    for ticket in tickets:
        backfill_related(forge, ticket)
    return lines


def reconcile(pack, ticket: str = "") -> list:
    """Intents whose act the forge already shows (done by hand, or a publish whose answer was lost) are recorded so."""
    from .forges import seam
    from .git_push import remote_tip, source
    from .publish import forge_for

    forge = seam(forge_for(pack))
    lines = []
    for intent in all_intents(ticket or None):
        payload = intent.get("payload") or {}
        if (
            intent.get("status") in ("pending", "endorsed")
            and intent.get("type") == "push-branch"
            and payload.get("sha")
        ):
            try:
                tip = remote_tip(
                    source(pack, payload["repo"]), payload.get("publish_as") or payload.get("branch") or ""
                )
            except CockpitError as exc:
                lines.append(f"{intent['id']}: {exc}")
                continue
            if tip == payload["sha"]:
                _manual(intent, "", "the remote already has this commit")
                lines.append(f"{intent['id']}: published-manually")
        elif intent.get("status") in ("pending", "endorsed") and intent.get("type") == "open-pr":
            found = forge.pr_for_head(payload["repo"], payload.get("head") or "", payload.get("base") or "")
            if found:
                payload["number"] = found.get("number")
                _manual(
                    intent,
                    found.get("html_url") or forge.url(payload["repo"], found.get("number")),
                    "the PR is already open",
                )
                lines.append(f"{intent['id']}: published-manually")
        elif intent.get("status") == "posted" and (intent.get("review") or {}).get("id"):
            state = forge.review(payload["repo"], payload["number"], intent["review"]["id"]).get("state")
            if state and state != "PENDING":
                intent["review"]["state"] = state
                _manual(intent, intent["review"].get("url") or "", f"the review was submitted on the forge ({state})")
                lines.append(f"{intent['id']}: published-manually")
    return lines


def _manual(intent, url: str, why: str) -> None:
    advance(intent, "published-manually", "reconcile")
    intent["receipt"] = {
        "ok": True,
        "url": url,
        "sha": (intent.get("payload") or {}).get("sha", ""),
        "output": why,
        "time": iso(),
    }
    save(intent)
    log(f"RECONCILE {intent['id']} published-manually: {why}")


# ---- ready for review ----

PR_WORK = ("open-pr", "push-branch", "pr-edit", "pr-patch-apply")


def ready_state(pack, ticket: str) -> dict:
    """{ready, prs, waiting}: at least one PR out, no PR work still open, and no open card of the ticket."""
    from .kanban import OPEN

    intents = all_intents(ticket)
    prs = sorted(
        {
            (row.get("receipt") or {}).get("url")
            for row in intents
            if row["type"] == "open-pr"
            and str(row["status"]).startswith("published")
            and "/pull/" in str((row.get("receipt") or {}).get("url"))
        }
    )
    waiting = [
        f"{row['id']} is {row['status']}"
        for row in intents
        if row["type"] in PR_WORK and row["status"] in OPEN_STATUSES
    ]
    waiting += [f"card {card} is still open" for card, status, _done in _ticket_cards(pack, ticket) if status in OPEN]
    if not prs:
        waiting.insert(0, "no published PR yet")
    return {"ready": not waiting, "prs": prs, "waiting": waiting}


def announce(pack, ticket: str) -> str:
    """The ticket's PRs are all out: one message, once per set of PRs."""
    from .notify import notify
    from .tracker import browse

    state = ready_state(pack, ticket)
    if not state["ready"]:
        return f"{ticket}: not ready ({'; '.join(state['waiting'][:3])})"
    page = browse(pack, ticket)  # empty when the pack's tracker has no page to give: the line is then left out
    body = (
        "The ticket's pull requests are ready for review\n"
        + (page + "\n" if page else "")
        + "\n"
        + "\n".join(state["prs"])
        + "\n"
    )
    sent = notify(pack, "ready_for_review", f"{ticket} " + " ".join(state["prs"]), body, ticket=ticket)
    if sent.get("sent"):
        path = qa_of(ticket, "ready-for-review.json")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        dump_json(path, {"time": iso(), "prs": state["prs"]})
    return f"{ticket}: {sent['out']}"


def updated(pack, ticket: str, url: str, sha: str) -> str:
    """A PR moved after review (a patch apply went out): the reviewers hear it once per PR and commit."""
    from .notify import notify
    from .tracker import browse

    page = browse(pack, ticket)
    body = "The pull request was updated after review\n" + (page + "\n" if page else "") + "\n" + url + "\n"
    return notify(pack, "updated_after_review", f"{url}@{sha}", body, ticket=ticket)["out"]


def ticket_ready(pack) -> str:
    """The housekeeping step: announce each ticket whose PRs went out, for what a publish did not see."""
    tickets = sorted(
        {
            row["ticket"]
            for row in all_intents()
            if row.get("type") == "open-pr" and str(row.get("status")).startswith("published")
        }
    )
    lines = [announce(pack, ticket) for ticket in tickets]
    return str(sum(1 for line in lines if " sent " in line))


# ---- auto-publish, the pack's explicit opt-in ----

NEVER_AUTO = ("ticket-done", "infra-note")
# What the forge says when what an intent acts on is gone for good: retrying it every pass changes nothing, so it is dropped.
GONE = {"ci-rerun": ("cannot be retried",)}


def _auto_refusal(pack, intent) -> str:
    """Why an intent in an auto-publish scope still waits for the human: an approval, a push to a base branch, a secret."""
    payload = intent.get("payload") or {}
    if intent["type"] == "pr-review-submit" and (payload.get("event") == "APPROVE" or intent.get("status") == "posted"):
        return "an approval or a review's verdict is the human's"
    from .sequence import said, waits

    wait = waits(intent, pack)
    if wait:
        return said(intent, wait)
    if intent["type"] in PUSHES:
        from .git_push import protected

        target = payload.get("publish_as") or payload.get("branch") or ""
        if target in protected(pack, payload["repo"]):
            return f"{target} is a protected branch: only the human pushes it"
    if intent["type"] in ("open-pr", "pr-edit") and payload.get("base"):
        from .git_push import repo_branch

        own = repo_branch(pack, payload.get("repo") or "")
        if payload["base"] != own:
            return f"a PR into {payload['base']} is the human's: {payload.get('repo')} works on {own}"
    from .outbox import _body_text, _payload_text
    from .scrub import holds_secret

    if holds_secret([_payload_text(payload), _body_text(payload)]):
        return "it holds a secret"
    return ""


def auto_publish(pack) -> str:
    """Endorse and publish the intents the pack lets go without a click (outbox.auto: [{scope, types}]), with every
    check a publish makes. Never in a lane's environment."""
    from .kanban import card_scope, ticket_scope
    from .outbox import OWNER, endorse
    from .publish import execute

    if os.environ.get("COCKPIT_LANE"):
        return "skipped: a lane does not publish"
    rules = ((pack.get("outbox") or {}).get("auto")) or []
    if not rules:
        return "0"
    published = 0
    for intent in all_intents():
        if intent.get("status") not in ("pending", "endorsed") or intent.get("type") in NEVER_AUTO:
            continue
        if (intent.get("endorsement") or {}).get("by") == OWNER:
            continue  # held for the human and confirmed by them: they publish it themselves
        # An intent no card filed (a CI rerun raised from a failing check) takes its ticket's scope: a release
        # ticket's rerun publishes like its cards' intents do.
        scope = card_scope(pack["board"], intent.get("card_id") or "") or ticket_scope(
            pack["board"], intent.get("ticket") or ""
        )
        if not any(rule["scope"] == scope and intent["type"] in rule["types"] for rule in rules):
            continue
        why = _auto_refusal(pack, intent)
        if why:
            intent["auto"] = {"time": iso(), "waits": why}
            save(intent)
            continue
        try:
            if intent["status"] == "pending":
                endorse(intent["id"], "low", f"auto-publish: {scope} scope", "auto-publish", "", "", pack=pack)
            receipt = execute(load(intent["id"]), pack=pack)
        except CockpitError as exc:
            receipt = {"ok": False, "error": str(exc)}
        shown = load(intent["id"])
        shown["auto"] = {
            "time": iso(),
            "scope": scope,
            "ok": bool(receipt.get("ok")),
            "error": receipt.get("error") or "",
        }
        save(shown)
        error = receipt.get("error") or ""
        if not receipt.get("ok") and any(said in error for said in GONE.get(intent["type"], ())):
            advance(shown, "dropped", "cockpit")
            shown["dropped"] = {"reason": f"what it acts on is gone: {error[-200:]}", "by": "cockpit", "time": iso()}
            save(shown)
            log(f"AUTO-DROP {intent['id']}: {error[-120:]}")
        if receipt.get("ok"):
            published += 1
            log(f"AUTO-PUBLISH {intent['id']} ({scope})")
    return str(published)
