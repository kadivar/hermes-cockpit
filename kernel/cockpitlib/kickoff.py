# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Start a card for a kickoff mode: the policy the Kick off page and other plugins share.

Halt and twin checks, the mode's preflight steps (registry.KICKOFF_MODES), seat capacity, the lane the pack picks,
a slot for the ticket, the browser loan, then the card. policy="release" is a scope that runs without the human's
go: the go is recorded on the plan, and the intake wait is passed, both saying so, instead of being skipped quietly.
A review or a test of work the pipeline never planned (a colleague's pull request, a ticket that never went through
intake: no plan file at all) records that on a new plan instead of waiting for a go nobody will give.
"""

import os

from .errors import CockpitError, Conflict
from .kanban import one_at_a_time
from .paths import qa_of
from .store import write_text

RELEASE_GO = "go: release scope (recorded by the release policy)"
OUTSIDE_GO = "go: outside work, no intake plan (recorded by the kickoff)"
OUTSIDE_MODES = ("review", "test")


def _decide_for_release(ticket: str, mode: str) -> None:
    from .plan import decided, init

    if not decided(ticket):
        init(ticket, f"{mode} card started in release scope", RELEASE_GO)


def _decide_for_outside(ticket: str, mode: str) -> None:
    """A review or a test of work this pipeline never planned: no plan file, so no intake to wait for. A plan that
    exists without a decision is still an intake waiting for the human's go, and stays refused."""
    from .plan import init, plan_path

    if mode not in OUTSIDE_MODES or not ticket or os.path.isfile(plan_path(ticket)):
        return
    init(
        ticket,
        f"# Plan {ticket}\n\nOutside work: this {mode} was kicked off for a ticket the pipeline did not plan. "
        "The ticket and its pull requests are the scope.",
        OUTSIDE_GO,
    )


def _outside(ticket: str) -> bool:
    """The ticket's plan was recorded by a kickoff of work the pipeline never planned (OUTSIDE_GO)."""
    from .plan import plan_path

    path = plan_path(ticket) if ticket else ""
    return bool(path) and os.path.isfile(path) and OUTSIDE_GO in open(path, encoding="utf-8").read()


def own_idle_slot(pack, ticket: str, count: int, steps) -> int:
    """1 when the ticket already holds a lane slot nobody is working in and the mode takes no slot of its own: the card
    works in that ticket's worktree, so the slot is its seat. Without this, a ticket whose slot an open card of its own
    keeps from slot-gc (a blocked question, say) could never start its own next step."""
    if not ticket or not count or "slot" in steps:
        return 0
    from .slots import read_owner, slot_of

    number = slot_of(ticket, count)
    if not number or read_owner(number) == "human":
        return 0
    from .acts import RUNNING
    from .kanban import board_cards

    if any(card["ticket"] == ticket and card["status"] in RUNNING for card in board_cards(pack["board"])):
        return 0
    return 1


def _release_takes_slot(policy: str, entry: dict, ticket: str, seats: dict, steps) -> bool:
    """A release starts a ticket's worker cards without an intake, so its first worker card claims the slot intake
    would have: one slot then runs one ticket's worker cards at a time. A ticket that holds its slot is seated by it
    (own_idle_slot); a mode with its own slot step, other lanes and human kickoffs are unchanged."""
    if policy != "release" or not ticket or not seats.get("slots") or "slot" in steps:
        return False
    if entry["lane_kind"] != "worker" or entry["capacity_bucket"] != "dev":
        return False
    from .slots import slot_of

    return not slot_of(ticket, seats["slots"])


# A worker card in these states works the slot now, or will as soon as Hermes dispatches it (ready, or parked by the
# quota guard until its provider resets). A blocked card waits on an answer and does no work, as before.
SLOT_WORK = ("ready", "claimed", "in_progress", "running", "scheduled")


def _slot_worked(pack, ticket: str, count: int, steps, policy: str, entry: dict) -> bool:
    """One slot runs one worker card at a time (the owner's rule): a release worker card of a ticket that holds a slot
    waits while another worker card works that slot, whatever its ticket. The ticket holding its slot (the release
    claim) let every worker card of a ticket with several units start together; this is the per-card half of the cap.
    Kickoff policy, other lanes and modes with their own slot step are unchanged."""
    if policy != "release" or not ticket or not count or "slot" in steps:
        return False
    if entry["lane_kind"] != "worker" or entry["capacity_bucket"] != "dev":
        return False
    import re

    from .kanban import board_cards
    from .slots import slot_of

    held = slot_of(ticket, count)
    if not held:
        return False  # it claims a free slot of its own, which no card works yet
    by_slot = bool(((pack or {}).get("lanes") or {}).get("by_slot"))
    slots = {}
    for card in board_cards(pack["board"]):
        lane = str(card.get("assignee") or "")
        if card.get("status") not in SLOT_WORK or not re.fullmatch(r"worker(-\d+)?", lane):
            continue
        if card["ticket"] not in slots:
            slots[card["ticket"]] = slot_of(card["ticket"], count)
        if slots[card["ticket"]] == held or (by_slot and lane == f"worker-{held}"):
            return True
    return False


def _claim_for_release(pack, entry: dict, ticket: str, lane: str) -> str:
    """Claim the free slot for the ticket through intake's claim; no ticket read or trace, those are intake's. The
    card's seat is then picked again, so a pack with lanes.by_slot seats it on the slot it claimed, which that seat owns."""
    from .acts import claim_slot
    from .halt import refuse
    from .kanban import open_cards
    from .lanes import free_lane
    from .slots import write_owner

    refuse(ticket)
    claimed = claim_slot(pack, ticket, lane)
    from .errors import Conflict
    from .slots import slot_of

    count = int((pack.get("seats") or {}).get("slots") or 0)
    if slot_of(ticket, count) != claimed["slot"]:
        # warm_slot answers "warming" without claiming when another process holds the slot's lock: the card would run
        # with no slot held and the cap would not hold. Ask again next tick.
        raise Conflict("no free dev seat")
    from .slots import mark_release_claim

    mark_release_claim(claimed["slot"], ticket)
    seated = free_lane(entry["lane_kind"], pack, open_cards(pack["board"]), ticket=ticket)
    if seated != lane:
        write_owner(claimed["slot"], seated)
    return seated


def batch_key(pack, now=None) -> str:
    """The ticket a batch of dependency bumps is under: the pack's forge.bump_batch template ({project}, {week},
    {month}, {date}), else <project>-BUMPS."""
    import time

    from .pack import batch_project

    stamp = time.gmtime(time.time() if now is None else now)
    template = ((pack.get("forge") or {}).get("bump_batch")) or "{project}-BUMPS"
    return template.format(
        project=batch_project(pack),
        week=time.strftime("%GW%V", stamp),
        month=time.strftime("%Y%m", stamp),
        date=time.strftime("%Y%m%d", stamp),
    ).upper()


def _bumps_batch(pack, mode, named, body, prompt) -> dict:
    """Bumps on several repos at once: one card per repo, each with its own twin check."""
    from .acts import kickoff_text
    from .kanban import card_title, open_cards, open_twin, place_card
    from .lanes import free_lane

    batch = batch_key(pack)
    made = []
    for repo_name in named:
        repo_title = card_title("bumps", batch, pack=pack, repo=repo_name)
        twin_card = open_twin(pack["board"], "bumps", batch, repo_name, repo_title)
        if twin_card:
            made.append({"repo": repo_name, "card_id": twin_card, "already": True})
            continue
        repo_lane = free_lane("reviewer", pack, open_cards(pack["board"]))
        text = kickoff_text(pack, batch, "bumps", prompt)
        folder = qa_of(batch, "human")
        os.makedirs(folder, exist_ok=True)
        write_text(os.path.join(folder, f"{repo_name}.md"), text)
        skills = ((pack.get("skills") or {}).get("kickoff") or {}).get("bumps") or []
        repo_card = place_card(
            pack["board"],
            repo_title,
            repo_lane,
            "ready",
            body=text,
            skills=skills,
            kind="bumps",
            ticket=batch,
            key=repo_name,
            pack=pack,
            repos=[repo_name],
        )
        made.append({"repo": repo_name, "card_id": repo_card, "lane": repo_lane, "already": False})
    return {
        "ok": True,
        "cards": made,
        "card_id": made[-1]["card_id"],
        "title": card_title("bumps", batch, pack=pack, repo=named[-1]),
        "lane": made[-1].get("lane") or "",
    }


@one_at_a_time
def start(
    pack,
    mode: str,
    ticket: str = "",
    prompt: str = "",
    repos=(),
    repo: str = "",
    prs=(),
    chrome: bool = False,
    policy: str = "kickoff",
    body: str = "",
    idempotency_key: str = "",
    model_override: str = "",
    seats=None,
    environment: str = "",
    evidence=(),
    max_runtime_seconds: int = 0,
    card_repos=(),
) -> dict:
    """Start one card for this mode. A refusal raises Conflict with the reason the page shows. max_runtime_seconds goes
    onto the one card a mode starts (Hermes ends its run past it); the per-repo rework cards a repo list makes carry none.
    card_repos (api.start_card's repos) are only recorded on that one card: unlike repos they never make a card per repo."""
    from .capacity import refusal_for
    from .halt import describe, halted
    from .kanban import card_title, open_cards, open_twin, place_card
    from .lanes import free_lane
    from .registry import kickoff_modes
    from .settings import load as load_settings
    from .slots import free_slots

    if policy not in ("kickoff", "release"):
        raise CockpitError(f"unknown kickoff policy {policy}")
    modes = kickoff_modes(pack)
    if mode not in modes:
        raise Conflict(f"unknown kickoff mode {mode}")
    if chrome and policy == "release":
        raise Conflict("the external browser is never a supervisor card's: its cards run on the built-in browser")
    if chrome and mode != "test":
        raise Conflict(
            "the external browser is a test kickoff's option only: every other flow runs on the built-in browser"
        )
    entry = modes[mode]
    steps = list(entry["preflight"])
    if mode == "bumps" and not ticket and not [str(item).strip() for item in repos or () if str(item).strip()]:
        ticket = batch_key(pack)  # one repo's bumps card belongs to the week's batch, like the cards a repo pick makes
    from .environments import pick

    place = pick(pack, environment) if (environment or entry["capacity_bucket"] == "test") else None
    if place is not None and not place["slot"]:
        steps = [
            step for step in steps if step not in ("tester_slot", "manual_plan", "slot")
        ]  # nothing of this machine
    proofs = _evidence(evidence)
    marker = halted(ticket) if ticket else None
    if marker:
        raise Conflict(describe(ticket, marker))
    one_repo = (
        str(repo or "").strip() if mode == "bumps" else ""
    )  # one repo's bumps: that repo's card in the batch, as a pick makes
    title = (
        card_title(entry["title_kind"], ticket, pack=pack)
        if mode != "bumps"
        else card_title("bumps", ticket, pack=pack, repo=one_repo)
        if one_repo
        else f"{ticket}: {mode}"
    )
    twin = open_twin(pack["board"], entry["title_kind"], ticket, one_repo, title=title)
    if twin:
        raise Conflict(f"already open: card {twin}")
    from .quota import held_refusal

    held = held_refusal(pack, entry["lane_kind"])  # its seats' provider hit its limit: nothing new until it resets
    if held:
        raise Conflict(held)
    if "bumps" in steps:
        from .acts import bump_card

        existing = bump_card(repo, list(prs))
        if existing:
            raise Conflict(f"already started on {existing}")
    if "tester_slot" in steps:
        from .slots import tester_slot

        tester_slot(pack, ticket)
    if "intake_go" in steps and ticket and policy != "release":
        from .acts import intake_waiting

        if intake_waiting(pack, ticket):
            raise Conflict("intake is waiting for go")
    seats = seats or load_settings(pack)["seats"]
    if _slot_worked(pack, ticket, seats["slots"], steps, policy, entry):
        raise Conflict("no free dev seat")  # the refusal the supervisor retries next tick
    from .capacity import caps_for

    if _release_takes_slot(policy, entry, ticket, seats, steps):
        from .slots import hand_over_release_slots

        hand_over_release_slots(pack, seats["slots"], ticket)  # the last release ticket is done with it: no gc wait
    free = len(free_slots(seats["slots"])) + own_idle_slot(pack, ticket, seats["slots"], steps)
    caps = caps_for(pack, seats, free, open_cards(pack["board"]))
    bucket = entry["capacity_bucket"]
    if bucket == "test" and place is not None and place["slot"]:
        bucket = "test_local"
    why = refusal_for(bucket, caps)
    named = [str(item).strip() for item in repos or () if str(item).strip()]
    batch = mode == "bumps" and named and not repo
    if why and not batch:
        raise Conflict(why)
    if why and batch:
        pending = [
            name
            for name in named
            if not open_twin(
                pack["board"],
                "bumps",
                batch_key(pack),
                name,
                card_title("bumps", batch_key(pack), pack=pack, repo=name),
            )
        ]
        if pending:
            raise Conflict(why)
    waiting_for_tester = False
    if "decision" in steps:
        from .plan import require_decision

        if policy == "release":
            _decide_for_release(ticket, mode)
        else:
            _decide_for_outside(ticket, mode)
        require_decision(ticket)
        if policy != "release" and mode not in OUTSIDE_MODES and _outside(ticket):
            # an outside review's or test's recorded go covers that review or test, never work the human did not plan
            raise CockpitError(
                f"plan has no decision: the plan was recorded for outside work; a {mode} needs the human's go on a plan"
            )
    if "reviewer_ready" in steps and not _outside(ticket):  # a teammate's PR has no tester of ours to wait for
        from .acts import open_test_rows, reviewer_ready

        try:
            reviewer_ready(pack, ticket)
        except CockpitError:
            waiting_for_tester = True
        open_test_rows(ticket)
    if "manual_plan" in steps:
        from .acts import start_manual_plan

        start_manual_plan(pack, ticket)
    lane = free_lane(entry["lane_kind"], pack, open_cards(pack["board"]), ticket=ticket)
    if "slot" in steps and seats["slots"]:
        from .acts import begin_change

        begin_change({**pack, "seats": seats}, ticket, prompt, lane)
    elif _release_takes_slot(policy, entry, ticket, seats, steps):
        lane = _claim_for_release({**pack, "seats": seats}, entry, ticket, lane)
    if batch:
        return _bumps_batch(pack, mode, named, body, prompt)
    from .acts import kickoff_text, take_bumps
    from .paths import platform_dir

    text = kickoff_text(pack, ticket, mode, prompt)
    picked = [str(item).strip() for item in prs or () if str(item).strip()]
    if picked:  # the human's own pick: the lane works these and does not ask for the batch again
        text += "Batch (the human's pick; do not ask for it again): " + ", ".join(picked) + "\n"
    if body:
        text += body if body.endswith("\n") else body + "\n"
    if place is not None:
        from .environments import lines

        text += lines(place)
    text += "".join(f"Evidence: {path}\n" for path in proofs)
    if policy == "release":
        text += "policy: release (the go and the intake wait are recorded, not asked)\n"
    if chrome:
        from .settings import lend_chrome

        loan = lend_chrome(pack, ticket)
        text += f"browser lent for {loan['hours']}h\n"
        text += (
            "browser: external (the test kickoff's option: Chrome MCP drives the external browser on this card only; "
            "failure videos come from it)\n"
        )
    folder = qa_of(ticket, "human") if ticket else os.path.join(platform_dir(), "human")
    os.makedirs(folder, exist_ok=True)
    write_text(os.path.join(folder, f"{mode}.md"), text)
    skills = ((pack.get("skills") or {}).get("kickoff") or {}).get(mode) or []
    if mode == "rework" and named:
        from .acts import _rework_per_repo

        made = _rework_per_repo(pack, ticket, title, text, prompt or text, named)
        return {
            "ok": True,
            "title": title,
            "card_id": made[0]["card"],
            "lane": made[0]["lane"],
            "cards": made,
            "display_name": pack["providers"]["coding"].get("display_name") or "Chat",
        }
    card_id = place_card(
        pack["board"],
        title,
        lane,
        "blocked" if waiting_for_tester else "ready",
        body=text,
        skills=skills,
        reason="waiting for the tester" if waiting_for_tester else "",
        kind=entry["title_kind"] if mode != "bumps" else ("bumps" if one_repo else ""),
        key=one_repo,
        ticket=ticket,
        pack=pack,
        repos=_recorded(mode, named, repo, card_repos),
        idempotency_key=idempotency_key,
        model_override=model_override,
        max_runtime_seconds=max_runtime_seconds,
        scope="release" if policy == "release" else "",
    )
    if mode == "bumps":
        take_bumps(pack, repo, card_id, list(prs))
    if chrome:
        from .browser_card import EXTERNAL
        from .kanban import mark_card

        mark_card(pack["board"], card_id, browser=EXTERNAL)  # the fence and `cockpit record` read the choice here
    return {
        "ok": True,
        "title": title,
        "card_id": card_id,
        "lane": lane,
        "display_name": pack["providers"]["coding"].get("display_name") or "Chat",
    }


def _recorded(mode: str, named: list, repo: str, card_repos) -> list:
    """The repos the one card records: a bumps card its repo; any other the page's repo list, else card_repos."""
    if mode == "bumps":
        return [repo]
    return named or [str(item) for item in card_repos or () if str(item).strip()]


def _evidence(paths) -> list:
    """The human's evidence files, as paths under the workspace; one outside it, or missing, is refused."""
    from .paths import workspace

    found = []
    for path in paths or ():
        real = os.path.realpath(os.path.join(workspace(), str(path)))
        if not real.startswith(os.path.realpath(workspace()) + os.sep) or not os.path.isfile(real):
            raise CockpitError(f"evidence {path}: not a file in the workspace")
        found.append(os.path.relpath(real, workspace()))
    return found
