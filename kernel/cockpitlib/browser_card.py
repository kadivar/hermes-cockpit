# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Which browser a card may drive.

Hermes's built-in browser (browser_exec on the card's own session, browser_vault, browser_cdp, browser_dialog) is every
lane's browser. The external browser (the human's own Chrome, or the agents' own-CDP Chrome on its DevTools port, which
a Chrome DevTools MCP server drives) is one option of a test kickoff: the human ticks it when he starts the test, and only
that test's own cards may then use it. A tester card inside a dev or another flow, and every card the supervisor starts
(policy release), always runs on the built-in browser.

What cockpit knows about a card comes from what it recorded when it made the card (watch/cards.json: kind, ticket,
scope, browser, run_card) and from the body the kickoff wrote ("browser lent for", "browser: external"). A comment never
counts: a lane can write one.
"""

import os
import re

# A Chrome DevTools MCP server's tools, whatever the pack named the server (chrome, chrome-devtools, chrome_mcp):
# Hermes names an MCP tool mcp__<server>__<tool> with every character outside [A-Za-z0-9_] turned into "_".
CHROME_MCP = re.compile(r"^mcp__chrome(?:_[A-Za-z0-9]+)*__")
TEST_KINDS = ("test", "test-kickoff")  # a test kickoff's own cards: the run, and the plan card it posts
EXTERNAL = "external"


def chrome_mcp(name: str) -> bool:
    return bool(CHROME_MCP.match(str(name or "")))


def _lend_phrase(text: str) -> bool:
    """What the kickoff writes on the card it makes (cockpitlib.kickoff): "browser lent for <n>h" and "browser: external".
    A comment never counts: a lane can write one. Neither does text the card quotes from outside."""
    from .quoted import without

    lowered = without(text).lower()
    return "browser lent for" in lowered or "browser: external" in lowered


def _test_kinds(pack) -> tuple:
    try:
        from .registry import kickoff_modes

        kind = str((kickoff_modes(pack).get("test") or {}).get("title_kind") or "test")
    except Exception:  # noqa: BLE001 - a pack that cannot be read keeps the default kind
        kind = "test"
    return tuple(dict.fromkeys(TEST_KINDS + (kind,)))


def facts(pack, card: str) -> dict:
    """{card, ticket, kind, release, test_kickoff, external} of one card. external: the human chose the external browser
    on this test kickoff (recorded in watch/cards.json, or written by the kickoff into the card's body). The plan card a
    test kickoff posts is external only while the run card it was posted from (run_card) is open and external."""
    from .kanban import _index, board_cards

    slug = str((pack or {}).get("board") or "")
    entry = ((_index().get(slug) or {}).get(card) or {}) if slug and card else {}
    entry = entry if isinstance(entry, dict) else {}
    row = next((item for item in board_cards(slug) if item["id"] == card), {}) if slug and card else {}
    from .quoted import without

    body = without(str(row.get("body") or ""))  # the kickoff's own lines: never what the card quotes from outside
    kind = str(entry.get("kind") or "")
    if not kind and row:
        title = str(row.get("title") or "")
        kind = "test-kickoff" if ": test kickoff" in title else "test" if re.search(r":\s*test\s*$", title) else ""
    release = entry.get("scope") == "release" or "policy: release" in body
    test_kickoff = bool(card) and kind in _test_kinds(pack) and not release
    said = entry.get("browser") == EXTERNAL or _lend_phrase(body)
    ticket = str(entry.get("ticket") or row.get("ticket") or "")
    if test_kickoff and not said and kind == "test-kickoff" and entry.get("run_card"):
        said = _run_card_external(pack, slug, str(entry["run_card"]), ticket, card)
    return {
        "card": card,
        "ticket": ticket,
        "kind": kind,
        "release": release,
        "test_kickoff": test_kickoff,
        "external": test_kickoff and said,
    }


def _run_card_external(pack, slug: str, run_card: str, ticket: str, card: str) -> bool:
    """The plan card's own run card (the kickoff's card it was posted from): same ticket, still open, external."""
    if not run_card or run_card == card:
        return False
    from .kanban import OPEN, board_cards

    row = next((item for item in board_cards(slug) if item["id"] == run_card), {})
    if not row or str(row.get("status") or "") not in OPEN:
        return False
    other = facts(pack, run_card)
    return other["ticket"] == ticket and other["kind"] != "test-kickoff" and other["external"]


def run_card_for_plan(pack, ticket: str) -> str:
    """The run card a plan card is posted from: the card this process runs, when it is a test card of that ticket."""
    here = current(pack)
    if here.get("ticket") == ticket and here.get("test_kickoff") and here.get("kind") != "test-kickoff":
        return here["card"]
    return ""


RUNNING = ("running", "claimed", "in_progress")


def _lane_card(pack) -> str:
    """The one card the board says this lane is running, or "". Hermes takes HERMES_KANBAN_TASK out of the environment
    of every process a worker starts, so a command the lane runs in its shell (`cockpit record start`) is not told its
    card: without this read a tester on a test kickoff is refused "runs only on a test kickoff card" and its Fail rows
    get no video. The board is not the lane's to write, and a seat runs one card at a time; two running cards of one
    lane name none."""
    lane = os.environ.get("COCKPIT_LANE") or ""
    slug = str((pack or {}).get("board") or "")
    if not lane or not slug:
        return ""
    from .kanban import board_cards

    mine = [row["id"] for row in board_cards(slug) if row.get("assignee") == lane and row.get("status") in RUNNING]
    return mine[0] if len(mine) == 1 else ""


def current(pack) -> dict:
    """facts() of the card this process runs, or {} outside a card: the one Hermes names in the environment, else
    the one the board says this lane is running."""
    from .skill_log import current_card

    try:
        _board, card = current_card()
    except Exception:  # noqa: BLE001 - no card that can be read is an empty answer
        return {}
    card = card or _lane_card(pack)
    return facts(pack, card) if card else {}


def external_refusal(pack, what: str = "Chrome MCP") -> str:
    """Why a lane may not drive the external browser now, or "" when it may (a test kickoff card started with it, the
    loan still current for its ticket). The human's own calls (no lane) are never refused here."""
    lane = os.environ.get("COCKPIT_LANE") or ""
    if not lane:
        return ""
    here = current(pack)
    ticket = here.get("ticket") or ""
    if here.get("release"):
        return (
            f"{what} is the external browser and a supervisor card never uses it: use the built-in browser "
            f'(browser_exec with session "{lane}-{ticket or "<ticket>"}")'
        )
    if not here.get("external"):
        return (
            f"{what} is the external browser, an option of a test kickoff only (the human ticks it when he starts "
            f'the test); this card runs on the built-in browser: browser_exec with session "{lane}-{ticket or "<ticket>"}"'
        )
    loan = loan_refusal(pack, ticket)
    return f"{what}: {loan}" if loan else ""


def loan_refusal(pack, ticket: str) -> str:
    """The loan record the kickoff wrote (watch/shared-chrome.json) must name this ticket and still run."""
    import json

    from .paths import watch_dir

    path = os.path.join(watch_dir(), "shared-chrome.json")
    try:
        record = json.load(open(path, encoding="utf-8"))
    except (OSError, ValueError):
        record = {}
    if not isinstance(record, dict) or not record.get("ticket"):
        return "the external browser is not lent to a ticket"
    if record.get("ticket") != ticket:
        return "the external browser is lent to another ticket"
    from .egress import _loan_expired

    if _loan_expired(record, pack):
        return "the loan of the external browser has expired"
    return ""
