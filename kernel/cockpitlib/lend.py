# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""A privileged login lent to one card. The normal list never shows it."""

import json
import os
import time

from .errors import CockpitError, Conflict
from .paths import watch_dir
from .store import append_line, dump_json

MARK = "PRIVILEGED LOGIN NEEDED"
TWO_FACTOR_MARK = (
    "2FA:"  # how a lane starts the reason of a block on a 2FA step with no stored authenticator key (souls/_common.md)
)
LEND_MINUTES = 30


def _path(name: str) -> str:
    return os.path.join(watch_dir(), name)


def _read(name: str):
    path = _path(name)
    if not os.path.isfile(path):
        return []
    try:
        data = json.loads(open(path, encoding="utf-8").read() or "[]")
    except json.JSONDecodeError:
        return []
    if not isinstance(data, list):
        return []
    return data


def _write(name: str, rows) -> None:
    os.makedirs(watch_dir(), mode=0o700, exist_ok=True)
    path = _path(name)
    dump_json(path, rows, mode=0o600)


def _log(line: str) -> None:
    os.makedirs(watch_dir(), mode=0o700, exist_ok=True)
    append_line(_path("admin-lends.log"), line + "\n")


def request_line(pack, step: str, why: str) -> str:
    """The block line. The environment word comes from the pack."""
    environment = str(((pack or {}).get("privileged") or {}).get("environment") or "")
    return f"{MARK} · {environment} · {step} · {why}"


def ask(text: str):
    """(environment, step, why) when the block is a privileged-login request."""
    parts = [part.strip() for part in (text or "").split("·")]
    if len(parts) < 4 or parts[0] != MARK:
        return None
    return parts[1], parts[2], parts[3]


def note_block(text: str, card: str = "") -> str:
    parsed = ask(text)
    if not parsed:
        return ""
    environment, step, why = parsed
    rows = [row for row in _read("blocks.json") if row.get("card") != card]
    rows.append({"card": card, "text": text, "environment": environment, "step": step, "why": why})
    _write("blocks.json", rows)
    return "asked"


def _asks_on_the_board(pack) -> list:
    """The cards blocked with a privileged-login request: [{card, text, step, why}]. The board is the source, so a lane's
    block shows without any record having been written first."""
    if not pack:
        try:
            from .pack import load
            from .paths import pack_path

            pack = load(pack_path())
        except Exception:  # noqa: BLE001 - no readable pack means nothing to list
            return []
    from .kanban import open_card_rows

    denied = {(row.get("card"), row.get("text")) for row in _read("denies.json") if row.get("text")}
    found = []
    for card in open_card_rows(pack["board"], pack):
        if card.get("status") not in ("blocked", "triage"):
            continue
        if (card["id"], card.get("question") or "") in denied:  # the human denied this request; a new one shows again
            continue
        parsed = ask(card.get("question") or "")
        if parsed:
            found.append(
                {
                    "card": card["id"],
                    "text": card["question"],
                    "environment": parsed[0],
                    "step": parsed[1],
                    "why": parsed[2],
                }
            )
    return found


def inbox_rows(pack=None) -> list:
    rows = []
    seen = set()
    for row in [*_asks_on_the_board(pack), *_read("blocks.json")]:
        if row.get("card") in seen:
            continue
        seen.add(row.get("card"))
        rows.append(
            {
                "name": "privileged",
                "ok": False,
                "reason": row.get("text") or "",
                "summary": row.get("step") or "",
                "card": row.get("card") or "",
                "options": ["Approve this step", "Deny"],
            }
        )
    return rows


def _lent_items(card: str = "") -> list:
    """(lane, item id, card) for every login cockpit lent into a seat's store; one card's when named."""
    from .lane_vault import MARK, items, seats
    from .pack import load
    from .paths import pack_path

    found = []
    for lane in seats(load(pack_path())):
        for item in items(lane):
            tag = str(item.get("label") or "")
            if not tag.startswith(MARK + "lent "):
                continue
            owner = tag[len(MARK + "lent ") :].split(" ", 1)[0]
            if not card or owner == card:
                found.append((lane, item.get("id") or "", owner))
    return found


def _drop_previous_lend(card: str) -> None:
    """One lend per card. The previous copy is removed before the next approval."""
    from .lane_vault import remove
    from .vault import entry_records

    for lane, item, _owner in _lent_items(card):
        remove(lane, item)
        _log(f"RETURN {card} ← {lane}: replaced")
    for item, path in entry_records():
        if item.get("lent") == card and os.path.isfile(path):
            os.remove(path)


def _restore_own_login(row) -> None:
    """The privileged step is over. The lent login leaves the lane's store; the lane's own logins stay."""
    from .lane_vault import remove

    if row.get("lane") and row.get("item"):
        remove(row["lane"], row["item"])
    from .vault import logout

    logout(int(row.get("slot") or 1))


def _labelled_login(items) -> dict:
    """The pack's labelled privileged login. Another privileged login is not lent in its place."""
    from .pack import load
    from .paths import pack_path

    label = str((load(pack_path()).get("privileged") or {}).get("label") or "")
    privileged = [
        item
        for item in items or []
        if isinstance(item, dict)
        and item.get("privileged")
        and not item.get("lent")
        and (item.get("kind") or "login") == "login"
    ]  # a key or a note in the human's vault is never lent
    if label:
        for item in privileged:
            if str(item.get("email") or "") == label or str(item.get("label") or "") == label:
                return item
    if privileged:
        return privileged[0]
    return {}


def _card_lane(pack, card: str) -> str:
    """The seat on this card. An Inbox approval that omits the lane still lends to that seat."""
    found = ""
    if not pack or not card:
        return found
    from .kanban import board_cards

    for row in board_cards((pack or {}).get("board") or ""):
        if str(row.get("id") or "") != str(card):
            continue
        found = str(row.get("assignee") or "")
        break
    return found


def approve(card: str, lane: str, slot: int = 1, pack=None) -> str:
    """Copy the privileged login into the lane vault for this card. The slot uses it for this step only."""
    if not str(lane or "").strip():
        lane = _card_lane(pack, card)
    from .vault import _items, sealed_to

    if not sealed_to():
        raise CockpitError("vault is not sealed. cockpit vault init --key <fingerprint>")
    source = _labelled_login(_items())
    if not source:
        raise CockpitError("no privileged login stored")
    if not str(lane or "").strip():
        raise CockpitError("no lane holds this card")
    _drop_previous_lend(card)
    from .lane_vault import place
    from .scrub import rebuild

    number = int(slot or 1)
    step = _step_for(card, pack)

    def record(item: str) -> None:
        rows = [row for row in _read("admin-lends.json") if row.get("card") != card]
        rows.append(
            {
                "card": card,
                "lane": lane,
                "email": source.get("email") or "",
                "at": int(time.time()),
                "slot": number,
                "item": item,
                "step": step,
            }
        )
        _write("admin-lends.json", rows)

    # The record first, then the copy: the housekeeping's take_back runs every minute in another process and removes
    # a lent copy it finds no record for. Placed before its record, the copy can be removed in between ("no lend
    # record") and the lane is told a login was lent that its store does not hold.
    record("")
    item = place(
        lane,
        source.get("origin") or "",
        source.get("email") or "",
        source.get("secret") or "",
        source.get("otp") or "",
        kind="lent",
        card=card,
    )
    rebuild()
    record(item)
    _log(f"LEND {card} → {lane}")
    _write("blocks.json", [row for row in _read("blocks.json") if row.get("card") != card])
    if pack and card:  # the card that asked resumes: it is told what was lent and for which step, as its soul describes
        from .acts import answer_card

        try:
            answer_card(
                pack,
                card,
                f"approved: the privileged login is lent to you for this card and this step only: {step or 'the step you asked'}. "
                f"It shows in browser_vault (action list); it is taken back when the card blocks again or ends, or after {LEND_MINUTES} minutes.",
            )
        except (CockpitError, Conflict):
            pass
        # The lend counts from after that answer. The answer is a comment on a card that is still blocked until the
        # board starts it again, and take_back reads a comment newer than the lend on a blocked card as "the card
        # blocked again": the approval itself took the login back within the minute (the same three cards that day).
        record(item)
    return "lent"


def _step_for(card: str, pack=None) -> str:
    """The step named on this card's privileged-login request. Empty when there is none."""
    for row in [*_read("blocks.json"), *_asks_on_the_board(pack)]:
        if row.get("card") == card:
            return str(row.get("step") or "")
    return ""


def use_step(card: str, step: str) -> str:
    """The lane may perform the approved step once. Any other step is refused, and the slot then returns to the lane's own login."""
    rows = _read("admin-lends.json")
    match = None
    for row in rows:
        if row.get("card") == card:
            match = row
    if not match:
        raise CockpitError("no privileged lend")
    if match.get("used"):
        raise CockpitError("that step is already done")
    allowed = str(match.get("step") or "")
    if not allowed:
        raise CockpitError("that step is not allowed")
    if str(step or "").strip() != allowed:
        raise CockpitError("that step is not allowed")
    match["used"] = True
    _write("admin-lends.json", rows)
    _restore_own_login(match)
    _log(f"STEP {card} {allowed}")
    return "done"


def deny(card: str, pack=None) -> str:
    """Deny leaves the row blocked. Undoing that denial is a new request."""
    from .test_flow import accept_block

    asked = next((row.get("text") for row in _asks_on_the_board(pack) if row.get("card") == card), "") if card else ""
    _write("blocks.json", [row for row in _read("blocks.json") if row.get("card") != card])
    environment = ""
    if pack:
        environment = str((pack.get("privileged") or {}).get("environment") or "")
    text = f"missing the privileged step in {environment}. who: the human".strip()
    accept_block(text)
    resume = bool(pack) and str((pack.get("privileged") or {}).get("on_deny") or "block") == "resume"
    if pack and card:
        from .acts import answer_card

        try:
            if resume:  # the lane carries on and records the row as blocked, as its soul says for a denial
                answer_card(
                    pack,
                    card,
                    f"denied: no privileged login for {environment}. Record the row that needed it as blocked and carry on.",
                )
            else:
                answer_card(pack, card, f"block {text}", unblock=False)
        except (CockpitError, Conflict):
            pass
    rows = _read("denies.json")
    # a resumed card leaves the Inbox by itself; only a card left blocked keeps its denied request out of it
    rows.append(
        {
            "card": card,
            "undo": "a new request",
            "environment": environment,
            **({"text": asked} if asked and not resume else {}),
        }
    )
    _write("denies.json", rows)
    _log(f"DENY {card}")
    return "denied"


def take_back(now=None, status_of=None) -> list:
    """Return lends whose card ended, blocked again, or aged out. A lend with no record is dropped."""
    from .vault import entry_records

    moment = int(now or time.time())
    keep = []
    returned = []
    for row in _read("admin-lends.json"):
        reason = ""
        if status_of:
            status, blocked_at = status_of(row.get("card") or "")
            if moment - int(row.get("at") or 0) > LEND_MINUTES * 60:
                reason = f"{LEND_MINUTES} minutes passed"
            elif status in (None, "done", "archived"):
                reason = f"the card is {status or 'gone'}"
            elif status in ("blocked", "triage") and int(blocked_at or 0) > int(row.get("at") or 0):
                reason = "the card blocked again"
        if reason:
            returned.append((row.get("card"), row.get("lane"), reason))
            _restore_own_login(row)
            _log(f"RETURN {row.get('card')} ← {row.get('lane')}: {reason}")
            continue
        keep.append(row)
    if returned:
        _write("admin-lends.json", keep)
    held = {row.get("card") for row in keep}
    from .lane_vault import remove

    for lane, item, card in _lent_items():
        if card not in held:
            remove(lane, item)
            returned.append((card, lane, "no lend record"))
            _log(f"RETURN {card} ← {lane}: no lend record")
    try:
        records = entry_records()
    except CockpitError:  # the key is locked here: the sealed lent copies wait for the next run that can read them
        records = []
    for item, path in records:
        if item.get("lent") and item.get("lent") not in held and os.path.isfile(path):
            os.remove(path)
    return returned
