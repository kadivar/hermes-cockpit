# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""How many of each workflow can start. Zero refuses kickoff and names why."""


def compute(
    free_slots, open_cards, seats, budget_over=False, budget_why="", test_needs_slot=True, tests_blocked=""
) -> dict:
    """open_cards maps lane name to a count. seats is the pack seats mapping. `test` is a test that needs no slot of
    this machine (a staging test, when the pack says so), `test_local` one on a slot; `tests_blocked` stops both."""
    if budget_over:
        return {
            "dev": 0,
            "test": 0,
            "test_local": 0,
            "review": 0,
            "question": 0,
            "why": budget_why or "over budget",
            "test_why": "",
        }
    intake_left = _kind_free("intake", seats["intake"], open_cards)
    review_left = _kind_free("reviewer", seats["reviewer"], open_cards)
    analyst_left = _kind_free("analyst", seats["analyst"], open_cards)
    testers = _kind_free("tester", seats["slots"], open_cards)
    if seats["slots"] == 0:
        dev = intake_left
        local = 0
    else:
        dev = min(free_slots, intake_left)
        local = min(free_slots, testers)
    test = local if test_needs_slot else testers
    if tests_blocked:
        test = local = 0
    return {
        "dev": dev,
        "test": test,
        "test_local": local,
        "review": review_left,
        "question": analyst_left,
        "why": "",
        "test_why": tests_blocked,
    }


def _kind_free(kind, count, open_cards) -> int:
    used = 0
    names = (
        [kind] + [f"{kind}-{index}" for index in range(2, count + 1)]
        if kind != "tester"
        else [f"tester-{index}" for index in range(1, count + 1)]
    )
    if kind == "worker":
        names = [f"worker-{index}" for index in range(1, count + 1)]
    for name in names:
        if open_cards.get(name, 0) > 0:
            used += 1
    return max(0, count - used)


def refusal(mode: str, caps: dict) -> str:
    """Why this kickoff mode cannot start now, or ''."""
    from .registry import kickoff_modes

    return refusal_for((kickoff_modes().get(mode) or {}).get("capacity_bucket") or "dev", caps)


def refusal_for(needed: str, caps: dict) -> str:
    """Why a card of this capacity bucket (dev, test, review, question) cannot start now, or ''."""
    if caps.get("why") and caps.get("dev") == 0 and caps.get("review") == 0:
        return caps["why"]
    if needed in ("test", "test_local") and caps.get("test_why"):
        return caps["test_why"]
    if caps.get(needed, 0) > 0:
        return ""
    return f"no free {needed} seat"


def caps_for(pack, seats, free: int, open_cards: dict) -> dict:
    """compute() with the pack's budget, its capacity rules and the last vault audit."""
    from .settings import budget_state

    budget = budget_state(pack)
    rules = (pack or {}).get("capacity") or {}
    if rules.get("waiting_holds_seat") is False:
        # The pack's choice: a card blocked on the human's answer does no work, so it does not keep another card from
        # starting. It runs again once answered, whatever the seats say then.
        from .kanban import OPEN
        from .kanban import open_cards as counted

        open_cards = counted(pack["board"], tuple(status for status in OPEN if status != "blocked"))
    blocked = ""
    if rules.get("audit_blocks_tests"):
        blocked = audit_finding()
    return compute(
        free,
        open_cards,
        seats,
        budget["over"],
        budget["why"],
        test_needs_slot=rules.get("test_needs_slot", True),
        tests_blocked=blocked,
    )


def audit_finding() -> str:
    """The open finding of the last vault audit (housekeeping staging-audit), or empty."""
    import json
    import os

    from .paths import watch_dir

    try:
        record = json.load(open(os.path.join(watch_dir(), "staging-audit.json"), encoding="utf-8"))
    except (OSError, ValueError):
        return ""
    found = record.get("findings") if isinstance(record, dict) else None
    return f"tests wait for the vault audit: {found[0]} (cockpit vault audit --fix)" if found else ""
