# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Sequences of intents: what an open stage still waits for before it is offered for publishing."""

import re

from .errors import CockpitError
from .intents import OPEN_STATUSES, PUBLISHED, PUSHES, all_intents, load, waiting_on, waits_cycle

CI_PASSED = ("success", "none")  # every run passed, or no CI picks the commit up


def _ci(intent, pack) -> dict:
    """An approval that is a stage of a sequence goes out on green CI at the commit it reviewed (the CI watch's record)."""
    payload = intent.get("payload") or {}
    if intent.get("type") != "pr-review-submit" or payload.get("event") != "APPROVE" or not payload.get("waits_for"):
        return {}
    from .outbox import ci_overridden

    if ci_overridden(intent, pack):  # the human approved despite CI
        return {}
    from .ci_watch import state_for

    state = (
        state_for(intent.get("ticket") or "", payload.get("repo") or "", payload.get("sha") or "", pack) or {}
    ).get("state")
    if state in CI_PASSED:
        return {}
    return {"id": "CI", "type": "ci", "status": state or "not seen yet"}


def is_batch(pack, ticket: str) -> bool:
    """The ticket is a bump batch: the pack's forge.bump_batch template ({project}, {week}, {month}, {date})."""
    template = (((pack or {}).get("forge") or {}).get("bump_batch")) or "{project}-BUMPS"
    from .pack import batch_project

    shapes = {"project": re.escape(batch_project(pack)), "week": r"\d{4}W\d{2}", "month": r"\d{6}", "date": r"\d{8}"}
    pattern = "".join(
        shapes.get(part[1:-1], re.escape(part)) if part.startswith("{") else re.escape(part)
        for part in re.split(r"(\{\w+\})", template)
    )
    return re.fullmatch(pattern, str(ticket or ""), re.I) is not None


def _sequence(pack, ticket: str) -> dict:
    found = (pack or {}).get("bump_sequence") or {}
    return found if found.get("stages") and is_batch(pack, ticket) else {}


def stages_of(sequence: dict, kind: str, payload) -> list:
    """The stages of the bump sequence this intent performs, in order."""
    payload = payload or {}
    return [
        stage
        for stage in sequence.get("stages") or []
        if stage["intent"] == kind
        and (not stage["fields"] or any(payload.get(field) not in (None, "", [], False) for field in stage["fields"]))
        and (not stage["event"] or payload.get("event") == stage["event"])
    ]


def order_text(sequence: dict) -> str:
    names = [stage["name"] for stage in sequence["stages"]]
    if sequence.get("barrier"):
        index = names.index(sequence["barrier"]) + 1
        names[index:index] = ["[the repo's whole batch]"]
    return "the batch's order, one stage per intent, each filed with --waits-for <the stage before it>: " + " → ".join(
        names
    )


def check_order(pack, ticket: str, kind: str, payload: dict) -> None:
    """A bump batch states its order (the pack's bump_sequence): an intent is one stage, and every stage after the first
    names the stage before it on the same PR."""
    sequence = _sequence(pack, ticket)
    stages = stages_of(sequence, kind, payload)
    if not stages:
        return
    if len(stages) > 1:
        raise CockpitError(
            f"{' and '.join(stage['name'] for stage in stages)} are separate stages: file them as separate intents. {order_text(sequence)}"
        )
    stage = stages[0]
    if not stage["after"]:
        return
    wid = payload.get("waits_for")
    if not wid:
        raise CockpitError(f"the {stage['name']} stage needs --waits-for <the stage before it>. {order_text(sequence)}")
    earlier = load(wid)
    named = [found["name"] for found in stages_of(sequence, earlier["type"], earlier.get("payload"))]
    if not set(named) & set(stage["after"]):
        raise CockpitError(
            f"the {stage['name']} stage waits for a {' or '.join(stage['after'])} stage, not {wid} "
            f"({'+'.join(named) or earlier['type']}). {order_text(sequence)}"
        )
    before = earlier.get("payload") or {}
    for key in ("repo", "number"):
        if payload.get(key) and before.get(key) and str(payload[key]) != str(before[key]):
            raise CockpitError(
                f"{wid} is another PR's stage ({before.get('repo')}#{before.get('number')}): a sequence stays on one PR"
            )


def _barrier(intent, pack) -> dict:
    """A stage after the barrier waits until no PR of the repo's batch still has a stage up to the barrier to go out
    (dropped ones leave the batch)."""
    sequence = _sequence(pack, intent.get("ticket"))
    if not sequence.get("barrier"):
        return {}
    names = [stage["name"] for stage in sequence["stages"]]
    limit = names.index(sequence["barrier"])
    mine = stages_of(sequence, intent["type"], intent.get("payload"))
    if not mine or names.index(mine[0]["name"]) <= limit:
        return {}
    repo = (intent.get("payload") or {}).get("repo")
    left = [
        row
        for row in all_intents(intent["ticket"])
        if row["id"] != intent["id"]
        and row.get("status") not in (*PUBLISHED, "dropped")
        and (row.get("payload") or {}).get("repo") == repo
        and any(names.index(stage["name"]) <= limit for stage in stages_of(sequence, row["type"], row.get("payload")))
    ]
    if not left:
        return {}
    first = sorted(left, key=lambda row: row["id"])[0]
    return {
        "id": first["id"],
        "type": "batch",
        "status": f"{len(left)} stage(s) of the {repo} batch up to {sequence['barrier']} not out yet, first {first['id']} ({first['status']})",
    }


def _own_push(intent) -> dict:
    """A pull request waits for the push of its own branch while that push is still to go out, however the two were
    linked. Its branch is not on the forge before: the forge answers "Validation Failed (HTTP 422)" and nothing more.
    A PR paired with its push (--after) is sent with it and does not wait here. The case this closes: a PR waits for
    an infrastructure note, applying the note files the push, the note is done, and the PR would be offered while
    the push is still with the gatekeeper."""
    payload = intent.get("payload") or {}
    if intent.get("type") != "open-pr" or payload.get("after"):
        return {}
    head = str(payload.get("head") or payload.get("publish_as") or payload.get("branch") or "")
    if not head or not payload.get("repo"):
        return {}
    for row in sorted(all_intents(intent.get("ticket")), key=lambda row: row["id"]):
        other = row.get("payload") or {}
        if (
            row.get("type") not in PUSHES
            or row.get("status") not in OPEN_STATUSES
            or other.get("repo") != payload["repo"]
        ):
            continue
        if str(other.get("publish_as") or other.get("branch") or "") == head:
            return {"id": row["id"], "type": row["type"], "status": row["status"]}
    return {}


def waits(intent, pack=None):
    """{id, type, status} of what this open intent waits for before it is offered — the stage before it, the batch
    barrier, then CI for an approval — or None when it may go."""
    if intent.get("status") not in OPEN_STATUSES:
        return None
    return waiting_on(intent) or _own_push(intent) or _barrier(intent, pack) or _ci(intent, pack) or None


def said(intent, wait) -> str:
    if wait["type"] == "batch":
        return f"{intent['id']} is past the batch barrier: {wait['status']} — publish those first"
    if wait["id"] == "CI":
        return f"{intent['id']} is an approval and CI at its commit is {wait['status']}: it is offered once CI is green"
    return (
        f"{intent['id']} waits for {wait['id']} ({wait['type']}), which is {wait['status']}: publish that stage first — "
        "the next one is offered once it is out"
    )


def check_stage(payload: dict, self_id: str = "") -> None:
    """--waits-for names an intent that will go out, and closes no loop. A stage is not a pair: --after goes."""
    wid = str(payload.get("waits_for") or "").strip()
    if not wid:
        payload.pop("waits_for", None)
        return
    try:
        earlier = load(wid)
    except FileNotFoundError as exc:
        raise CockpitError(f"--waits-for: no intent {wid}") from exc
    if earlier.get("status") == "dropped":
        raise CockpitError(f"--waits-for: {wid} is dropped; name the stage that will go out")
    if self_id and (wid == self_id or waits_cycle(self_id, wid)):
        raise CockpitError(f"--waits-for {wid} would close a loop back to {self_id}")
    payload["waits_for"] = wid
    payload["after"] = ""
