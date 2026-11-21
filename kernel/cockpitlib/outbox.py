# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Create and move intents. Lanes write. The gatekeeper endorses. The human publishes."""

import os
import re

from .errors import CockpitError
from .intents import (
    OPEN_STATUSES,
    PUSHES,
    TYPES,
    advance,
    all_intents,
    check_ticket,
    load,
    release_seq,
    reserve_seq,
    save,
)
from .local_refs import find_local_refs
from .paths import outbox_of, qa_of
from .refusals import record
from .store import append_line, copy_file, log, write_text
from .time_util import iso


def _payload_text(payload) -> str:
    """The words a lane wrote into the payload. The paths of its drafts are this machine's by nature and never leave,
    and the git facts cockpit records beside them (commits, probe errors) are not sent either."""
    from .intents import FIELDS

    parts = []
    for key, value in (payload or {}).items():
        if isinstance(value, str) and FIELDS.get(key) not in (None, "file", "files"):
            parts.append(value)
    return "\n".join(parts)


CHAINABLE = ("open-pr", "pr-comment", "pr-edit", "tracker-transition")
CLAIMS_FIX = re.compile(r"^\s*(fixed|done|addressed|resolved)\b", re.I)


def _body_text(payload) -> str:
    from .paths import workspace

    text = str(payload.get("body") or "")
    path = payload.get("body_file")
    if path:
        full = path if os.path.isabs(path) else os.path.join(workspace(), path)
        if os.path.isfile(full):
            text += "\n" + open(full, encoding="utf-8", errors="replace").read()
    return text


def implied_after(ticket: str, kind: str, payload, self_id: str = "") -> str:
    """The open intent this one cannot go out without, when the lane did not name it: the push of the branch an open-pr
    opens; a push whose commit a reply or edit names; a push before a reply that claims a fix; the same issue's earlier
    move (a workflow walks one status at a time). A stage of a sequence names the one before it and is never paired."""
    if payload.get("waits_for"):
        return ""
    if payload.get("after"):
        return payload["after"]
    if kind not in CHAINABLE:
        return ""
    rows = [row for row in all_intents(ticket) if row["id"] != self_id and row.get("status") in OPEN_STATUSES]
    if kind == "tracker-transition":
        names = {payload.get("issue"), payload.get("issue_from")} - {None, ""}
        earlier = [
            row
            for row in rows
            if (
                row.get("type") == "tracker-transition"
                and ((row.get("payload") or {}).get("issue") or (row.get("payload") or {}).get("issue_from")) in names
            )
            or (row.get("type") == "tracker-create" and row["id"] == payload.get("issue_from"))
        ]
        return earlier[-1]["id"] if earlier else ""
    pushes = [
        row
        for row in rows
        if row.get("type") in PUSHES
        and (row.get("payload") or {}).get("repo") == payload.get("repo")
        and not (row.get("payload") or {}).get("rebase_only")
        and (row.get("payload") or {}).get("sha")
    ]
    if not pushes:
        return ""
    if kind == "open-pr":
        head = payload.get("head") or payload.get("publish_as") or payload.get("branch")
        same = [row for row in pushes if (row["payload"].get("publish_as") or row["payload"].get("branch")) == head]
        return same[-1]["id"] if same else ""
    text = _body_text(payload) + " " + str(payload.get("title") or "") + " " + str(payload.get("title_append") or "")
    for row in reversed(pushes):
        sha = row["payload"]["sha"]
        if len(sha) >= 7 and re.search(rf"\b{re.escape(sha[:7])}", text):
            return row["id"]
    if kind == "pr-comment" and (payload.get("resolve") or CLAIMS_FIX.match(text.strip())):
        return pushes[-1]["id"]
    return ""


def _copy_files(payload, ticket: str, seq: str) -> None:
    """Drafts the lane names are copied beside the intent, so a later edit of the draft does not change what leaves.
    Attachments stay where they are, under the workspace."""

    from .intents import FIELDS
    from .paths import workspace

    folder = outbox_of(ticket)
    os.makedirs(folder, exist_ok=True)
    home = os.path.realpath(workspace())
    for field, shape in FIELDS.items():
        value = payload.get(field)
        if not value or shape not in ("file", "files"):
            continue
        flag = "--" + field.replace("_", "-")
        if shape == "files":
            kept = []
            for item in value:
                full = os.path.realpath(item if os.path.isabs(item) else os.path.join(home, item))
                if not os.path.isfile(full):
                    raise CockpitError(f"{flag} {item}: no such file")
                if not full.startswith(home + os.sep):
                    raise CockpitError(f"{flag} {item}: an attachment lives under the workspace")
                kept.append(os.path.relpath(full, home))
            payload[field] = sorted(set(kept))
            continue
        full = os.path.realpath(value if os.path.isabs(value) else os.path.join(home, value))
        if not os.path.isfile(full):
            raise CockpitError(f"{flag} {value}: no such file")
        if full.startswith(os.path.realpath(folder) + os.sep):
            payload[field] = os.path.relpath(full, home)
            continue
        ext = os.path.splitext(full)[1] or ".md"
        target = os.path.join(folder, f"{seq}-{field.replace('_file', '').replace('_', '-')}{ext}")
        copy_file(full, target)
        payload[field] = os.path.relpath(target, home)


def _pr_state(ticket: str, repo: str, number) -> dict:
    """What the pull-request watch recorded about this PR, or nothing."""
    from .store import read_json

    if not (ticket and repo and number):
        return {}
    from .record_write import with_checked

    path = qa_of(ticket, "pr", f"{repo}-{number}.json")
    data = read_json(path)
    return with_checked("pr", path, data) if isinstance(data, dict) else {}


def _load_or_refuse(iid: str) -> dict:
    try:
        return load(iid)
    except FileNotFoundError as exc:
        raise CockpitError(f"no intent {iid}") from exc


def _rules(pack, ticket: str, kind: str, payload: dict, self_id: str = "") -> None:
    """What the forge or the tracker would refuse, or would do wrongly, refused now with the reason."""
    from .forges import make, missing, needs

    if needs(kind, payload):  # an act the pack's forge has no operation for is refused here, never at publish
        forge = make(pack)
        lacking = missing(forge, kind, payload)
        if lacking:
            raise CockpitError(
                f"the pack's forge ({forge.kind}) has no {lacking[0]}: a {kind} cannot be published to it"
            )
    from . import trackers

    if trackers.needs(
        kind, payload
    ):  # and the same for the pack's tracker: what it lacks is said when the intent is written
        from .tracker import _config, capabilities

        lacking = trackers.missing(capabilities(pack), kind, payload)
        if lacking:
            raise CockpitError(
                f"the pack's tracker ({trackers.kind_of(_config(pack))}) has no {lacking[0]}: this {kind} cannot be published to it"
            )
    if kind in PUSHES:
        head = payload.get("publish_as") or payload.get("branch")
        twin = [
            row
            for row in all_intents(ticket)
            if row.get("type") in PUSHES
            and row["id"] not in (self_id, payload.get("after"))
            and row.get("status") in OPEN_STATUSES
            and (row.get("payload") or {}).get("repo") == payload.get("repo")
            and ((row.get("payload") or {}).get("publish_as") or (row.get("payload") or {}).get("branch")) == head
        ]
        if twin:
            raise CockpitError(
                f"{twin[-1]['id']} is already an open push of {payload.get('repo')} {head}: amend or drop it"
            )
    if kind == "push-branch" and payload.get("rebase_only") and payload.get("after"):
        raise CockpitError(
            "a rebase-only push is the first of the pair; --after belongs on the content push that follows it"
        )
    if kind == "pr-patch-apply":
        from .patch_apply import rows

        rows(payload["threads_file"])
        if _pr_state(ticket, payload.get("repo"), payload.get("number")).get("role", "author") != "author":
            raise CockpitError(f"{payload['repo']}#{payload['number']} is not your PR: reply with a pr-comment instead")
    if kind == "pr-comment":
        if payload.get("resolve") and not payload.get("thread"):
            raise CockpitError("--resolve needs --thread <the review thread's node id>")
        if (payload.get("react") or payload.get("resolve")) and not payload.get("in_reply_to"):
            raise CockpitError("--react and --resolve are for a thread reply: add --in-reply-to <review comment id>")
        if not payload.get("in_reply_to") and not (payload.get("body_file") or payload.get("body")):
            raise CockpitError("a top-level pr-comment needs --body-file")
        state = _pr_state(ticket, payload.get("repo"), payload.get("number"))
        if (
            payload.get("in_reply_to")
            and state
            and state.get("role", "author") == "author"
            and state.get("state", "open") == "open"
            and not state.get("merged")
        ):
            raise CockpitError(
                f"{payload['repo']}#{payload['number']} is your own open PR: its thread replies go in its pr-patch-apply, with the push"
            )
    if kind == "pr-review-submit":
        if payload.get("review_id") and payload.get("event"):
            raise CockpitError("--review-id appends to your pending review and never submits it: drop --event")
        if (payload.get("patch_comments") or payload.get("review_body_update")) and not payload.get("review_id"):
            raise CockpitError("--patch-comments and --review-body-update need --review-id <pending review id>")
    if kind == "pr-edit" and payload.get("title") and payload.get("title_append"):
        raise CockpitError("--title replaces and --title-append appends: pick one")
    if kind == "tracker-comment":
        payload.setdefault("issue", ticket)
        if payload.get("comment_id"):
            payload.pop("probe_title", None)
        if payload.get("comment_from"):
            source = _load_or_refuse(payload["comment_from"])
            if source["type"] != "tracker-comment" or (source.get("payload") or {}).get("issue") != payload["issue"]:
                raise CockpitError("--comment-from names a tracker-comment intent on the same issue")
    if kind == "tracker-create":
        limit = ((pack or {}).get("tracker") or {}).get("summary_max")
        if limit and len(payload["summary"]) > int(limit):
            raise CockpitError(f"the summary is {len(payload['summary'])} characters; this tracker takes {limit}")
    if kind == "pr-edit" and "{key}" in str(payload.get("title") or "") + str(payload.get("title_append") or ""):
        if not payload.get("issue_from") or _load_or_refuse(payload["issue_from"])["type"] != "tracker-create":
            raise CockpitError(
                "a title with {key} needs --issue-from <the tracker-create intent>: the key is read from its receipt at publish"
            )
    if kind == "tracker-transition":
        if not payload.get("issue") and not payload.get("issue_from"):
            payload["issue"] = ticket
        if payload.get("issue_from") and _load_or_refuse(payload["issue_from"])["type"] != "tracker-create":
            raise CockpitError("--issue-from names the tracker-create intent that makes the ticket")
    if payload.get("after"):
        earlier = _load_or_refuse(payload["after"])
        if kind == "tracker-transition":
            if earlier["type"] not in ("pr-review-submit", "push-branch", "tracker-transition", "tracker-create"):
                raise CockpitError("--after on a tracker-transition names the review, push, create or move it follows")
        elif earlier["type"] not in PUSHES or not (earlier.get("payload") or {}).get("sha"):
            raise CockpitError(f"--after names a push intent with a sha ({payload['after']})")
        elif kind in PUSHES or kind == "open-pr":
            payload["remote_sha"] = earlier["payload"][
                "sha"
            ]  # the lease: the remote's tip once the earlier push is out


def new_comments(ticket: str, payload) -> str:
    """Why a patch apply must wait: its PR has comments newer than the plan, which the plan has not judged."""
    state = _pr_state(ticket, payload.get("repo"), payload.get("number"))
    count = len(state.get("new") or [])
    if count:
        return f"{payload['repo']}#{payload['number']} has {count} new comment(s) since the plan: judge them, then amend the manifest"
    return ""


def _probe(pack, ticket: str, kind: str, payload: dict) -> list:
    """A push intent's facts from git; the reasons it waits for the human, if any."""
    if kind not in PUSHES or not pack or not payload.get("repo"):
        return []
    from .git_push import WorktreeMismatch, checkout, probe, rebase_proof

    lease = payload.get("remote_sha") if payload.get("after") else None
    payload.pop("probe_error", None)
    try:
        probe(pack, ticket, payload)
    except WorktreeMismatch:  # not the worktree's branch or head: verify and push would refuse it, so refuse it now
        raise
    except CockpitError as exc:  # git unreadable now: verify names it, and the gatekeeper does not endorse
        payload["probe_error"] = str(exc)
    if lease is not None:
        payload["remote_sha"] = lease
    if payload.get("rebase_only"):
        payload["rebase_proof"] = rebase_proof(checkout(pack, ticket, payload["repo"]), payload)
    if payload.get("foreign"):
        return [f"the pushed range has commits by {', '.join(payload['foreign'])}: confirm they belong in this push"]
    return []


def _attach_failed(pack, ticket: str, kind: str, payload: dict, created_by: str = "") -> None:
    """Under the pack's `testflow.attach: failed`, a test report's results post attaches the failed rows' screenshots and videos
    and nothing else: the author reads the failures, not every pass. A lane's own --attach outside that set is refused; the
    human's extra files ride along after them."""
    if kind != "tracker-comment" or str(((pack or {}).get("testflow") or {}).get("attach") or "") != "failed":
        return
    from .test_flow import failed_media, results_post

    if not results_post(payload, pack):
        return
    wanted = failed_media(pack, ticket, str(payload.get("run") or ""))
    given = list(payload.get("attach") or [])
    stray = [item for item in given if item not in wanted]
    if stray and created_by and created_by != "human":
        raise CockpitError(
            f"--attach {stray[0]}: a test report attaches only the failed rows' screenshots and videos "
            "(testflow.attach: failed); the outbox adds them from the run's results"
        )
    payload["attach"] = wanted + stray


def _prepare(pack, ticket: str, kind: str, payload: dict, seq: str, self_id: str = "", created_by: str = "") -> list:
    """Check the payload's shape, copy its drafts, apply the rules, chain it, and probe a push. The reasons it waits."""
    from .git_push import publish_name
    from .intents import check_payload

    payload.update(check_payload(kind, payload))
    named = payload.get("branch") or ""
    if named and pack and kind in ("push-branch", "pr-patch-apply", "open-pr") and not payload.get("publish_as"):
        payload["publish_as"] = publish_name(pack, payload["repo"], named)
    if pack and created_by != "human" and kind in ("push-branch", "pr-patch-apply"):
        # A lane never asks to push a branch only the human writes: refused here, while its card is still running and
        # can push a feature branch and open a PR instead, rather than held for the human to drop.
        from .git_push import protected

        target = payload.get("publish_as") or named
        if target and target in protected(pack, payload.get("repo") or ""):
            raise CockpitError(
                f"{target} is a protected branch of {payload.get('repo')}: a lane pushes a feature branch "
                "and opens a PR into it, never the branch itself"
            )
    if kind == "open-pr" and not payload.get("head"):
        payload["head"] = payload.get("publish_as") or named
    _copy_files(payload, ticket, seq)
    from .sequence import check_order, check_stage

    check_stage(payload, self_id)
    check_order(pack, ticket, kind, payload)
    _rules(pack, ticket, kind, payload, self_id)
    _attach_failed(pack, ticket, kind, payload, created_by)
    hits = find_local_refs(_payload_text(payload) + "\n" + _body_text(payload), pack)
    if hits:
        raise CockpitError(f"local reference: {hits[0]} (say it in words, or attach the file)")
    earlier = implied_after(ticket, kind, payload, self_id)
    if earlier and not payload.get("after"):
        payload["after"] = earlier
        if kind == "open-pr":
            payload["remote_sha"] = (load(earlier).get("payload") or {}).get("sha", "")
    waits = _probe(pack, ticket, kind, payload)
    if pack and kind in ("push-branch", "pr-patch-apply", "open-pr"):
        from .plan_gate import waits as gate_waits
        from .skill_log import current_card

        held = gate_waits(pack, current_card()[1])
        if held:
            waits.append(held)
    if kind == "pr-patch-apply" and new_comments(ticket, payload):
        waits.append(new_comments(ticket, payload))
    if kind == "pr-patch-apply":
        from .patch_apply import body, rows
        from .paths import workspace

        path = outbox_of(ticket, f"{seq}-body.md")
        write_text(path, body(payload, rows(payload["threads_file"])))
        payload["body_file"] = os.path.relpath(path, workspace())
    return waits


def _supersede_reviews(pack, intent) -> list:
    """Under the pack's `outbox.supersede_reviews`, a lane's new review of a PR drops the lane-written reviews of the same PR
    that are still here and not on the forge yet (pending, held, returned or endorsed, with no pending review id): the newer
    one says what the older one said and more. A review already posted on the forge, or one the human wrote, stays for the
    human. The ids dropped."""
    if (
        intent.get("type") != "pr-review-submit"
        or intent.get("created_by") == "human"
        or not ((pack or {}).get("outbox") or {}).get("supersede_reviews")
    ):
        return []
    payload = intent.get("payload") or {}
    dropped = []
    for row in all_intents(intent["ticket"]):
        older = row.get("payload") or {}
        if row["id"] == intent["id"] or row.get("type") != "pr-review-submit" or row.get("created_by") == "human":
            continue
        if row.get("status") not in ("pending", "held", "returned", "endorsed") or older.get("review_id"):
            continue
        if older.get("repo") != payload.get("repo") or str(older.get("number")) != str(payload.get("number")):
            continue
        advance(row, "dropped", "cockpit")
        row["dropped"] = {"reason": f"superseded by {intent['id']}", "by": "cockpit", "time": iso()}
        save(row)
        log(f"SUPERSEDE {row['id']} by {intent['id']}")
        dropped.append(row["id"])
    return dropped


def create(pack, ticket, kind, card, summary, payload, created_by="human", risk="", evidence=()) -> dict:
    """A new intent, checked and probed. A refusal is recorded for the Inbox."""
    check_ticket(ticket, (pack or {}).get("ticket_pattern"))
    from .halt import refuse

    refuse(ticket)
    if kind not in TYPES:
        raise CockpitError(f"unknown type {kind}")
    if kind == "pr-review-submit":
        refuse_unread({"type": kind, "ticket": ticket, "payload": payload})
    if kind == "ticket-done":
        # one "done, confirm?" per ticket: a second go on the same card, or a second watcher pass, finds the open one
        waiting = [
            row
            for row in all_intents(ticket)
            if row.get("type") == "ticket-done" and row.get("status") in OPEN_STATUSES
        ]
        if waiting:
            log(f"TICKET-DONE {ticket} already open as {waiting[-1]['id']}")
            return waiting[-1]
    payload = dict(payload or {})
    seq = reserve_seq(ticket, kind)  # the number is this intent's from here: the probes below may take long
    try:
        waits = _prepare(pack, ticket, kind, payload, seq, created_by=created_by)
    except CockpitError as exc:
        release_seq(ticket, seq, kind)
        record(ticket, kind, card, created_by, str(exc))
        raise
    except BaseException:
        release_seq(ticket, seq, kind)
        raise
    payload["after"] = payload.get("after") or ""
    intent = {
        "id": f"{ticket}/{seq}-{kind}",
        "type": kind,
        "card_id": card,
        "ticket": ticket,
        "created_at": iso(),
        "created_by": created_by,
        "status": "pending",
        "risk_hint": risk or ("high" if payload.get("event") == "APPROVE" else "low"),
        "agent_summary": str(summary)[:300],
        "evidence": list(evidence or []),
        "payload": payload,
    }
    save(intent)
    log(f"NEW {intent['id']} by {created_by}")
    _supersede_reviews(pack, intent)
    if waits:
        return hold(intent["id"], "; ".join(waits), waits="human")
    _request_sweep(ticket)
    return _maybe_hold_skills(pack, intent)


def draft_digests(payload) -> dict:
    """The sha256 of each draft kept beside the intent, by payload field ("" for one that is not there): what whoever
    endorses it read. Attachments are not drafts: attachment_digests counts them."""
    import hashlib

    from .intents import FIELDS
    from .paths import workspace

    found = {}
    for field, shape in FIELDS.items():
        value = (payload or {}).get(field)
        if shape != "file" or not value or not isinstance(value, str):
            continue
        try:
            with open(value if os.path.isabs(value) else os.path.join(workspace(), value), "rb") as handle:
                found[field] = hashlib.sha256(handle.read()).hexdigest()
        except OSError:
            found[field] = ""
    return found


def changed_drafts(intent) -> list:
    """The drafts that are no longer what was endorsed, named as the human knows them. An endorsement made before
    digests were kept has none: nothing is compared and the intent publishes as it always did."""
    kept = (intent.get("endorsement") or {}).get("files")
    if not isinstance(kept, dict):
        return []
    now = draft_digests(intent.get("payload"))
    return [
        field.replace("_file", "").replace("_", " ")
        for field in sorted({*kept, *now})
        if now.get(field) != kept.get(field)
    ]


def attachment_digests(payload) -> dict:
    """The sha256 of each attachment, by its path as the payload names it ("" for one that is not there). An attachment
    is not copied beside the intent: it stays in the workspace and is read at publish, so its digest is what binds the
    file that leaves to the one that was endorsed."""
    import hashlib

    from .paths import workspace

    found = {}
    listed = (payload or {}).get("attach")
    for item in listed if isinstance(listed, list) else []:
        digest = hashlib.sha256()
        try:
            with open(item if os.path.isabs(str(item)) else os.path.join(workspace(), str(item)), "rb") as handle:
                for block in iter(lambda: handle.read(1 << 20), b""):
                    digest.update(block)
            found[str(item)] = digest.hexdigest()
        except OSError:
            found[str(item)] = ""
    return found


def changed_attachments(intent) -> list:
    """The attachments that are no longer the files that were endorsed (changed, gone, or not the same list). An
    endorsement made before attachments were digested has none: nothing is compared."""
    kept = (intent.get("endorsement") or {}).get("attachments")
    if not isinstance(kept, dict):
        return []
    now = attachment_digests(intent.get("payload"))
    return [path for path in sorted({*kept, *now}) if now.get(path) != kept.get(path)]


def _request_sweep(ticket: str) -> None:
    from .gate import request_sweep

    request_sweep(ticket)


def endorse(iid, risk, notes, lane, provider, model, pack=None) -> dict:
    """The gatekeeper's pass on a pending (or held) intent whose checks are clean. A held intent drops its hold."""
    intent = load(iid)
    if intent["status"] not in ("pending", "held"):
        raise CockpitError(f"{iid} is {intent['status']}; only a pending or held intent is endorsed")
    problems = verify(intent=intent, pack=pack) if pack else []
    if problems:
        raise CockpitError(f"{iid} does not verify: " + "; ".join(problems))
    if pack and intent.get("skills_deferred"):
        refuse_skill_gap(pack, intent)
        intent = load(iid)
    advance(intent, "endorsed", lane or "gatekeeper")
    drafts = draft_digests(intent.get("payload"))
    attached = attachment_digests(intent.get("payload"))
    intent["endorsement"] = {
        "sha": (intent.get("payload") or {}).get("sha") or "",
        "time": iso(),
        "risk": risk,
        "notes": notes,
        "by": lane or "gatekeeper",
        "provider": provider,
        "model": model,
        **({"files": drafts} if drafts else {}),  # what was read is what may leave: publish compares
        **({"attachments": attached} if attached else {}),
    }
    intent.pop("hold", None)  # the pass replaces a hold; the record is not endorsed and held at once
    save(intent)
    return intent


def confirm(iid, pack=None) -> dict:
    """The human confirms what the gatekeeper held an intent for (a hold that waits on them and asks nothing, such as
    commits by another author): it is endorsed as theirs, and publishing it stays their next step."""
    human_gate()
    intent = load(iid)
    held = intent.get("hold") or {}
    if intent["status"] != "held" or held.get("waits") != "human":
        raise CockpitError(f"{iid} is {intent['status']}: only a hold that waits for you is confirmed")
    if held.get("ask"):
        raise CockpitError(f"{iid} asks a question: answer it in its decision form")
    return endorse(
        iid,
        intent.get("risk_hint") or "low",
        f"confirmed by the owner: {held.get('reason') or 'held'}",
        OWNER,
        "",
        "",
        pack=pack,
    )


# Who an intent the human confirmed is endorsed by: auto-publish leaves those to the human's own Publish.
OWNER = "owner"


def human_gate(what: str = "hold and drop") -> None:
    """Hold, drop and ack are human acts. A lane does not take them."""
    if os.environ.get("COCKPIT_LANE"):
        from .errors import CockpitError

        raise CockpitError(f"{what} stay with the human")


REDO_WITH_SKILL = re.compile(r"(?i)^\s*redo with skills? ([a-z0-9_:, -]+?) loaded")


def hold(iid, reason, waits="human", rework="", ask="", options=None, chain=False, pack=None, skills=()) -> dict:
    """The gatekeeper's hold. --waits lane: the ticket's cards still deliver (re-checked when one completes). --rework with no
    --ask: nothing to decide, so the intent goes straight back to its lane. --ask: one question only the human answers.
    "redo with skill X loaded": back to the lane with that skill on its card."""
    intent = load(iid)
    if intent["status"] not in (
        "pending",
        "endorsed",
        "held",
    ):  # a returned intent is its lane's; one that left is not held
        raise CockpitError(f"{iid} is {intent['status']}; only a pending, endorsed or held intent is held")
    if waits == "lane" and not ask and pack is not None:
        from .gate import _ticket_cards
        from .kanban import OPEN

        if not any(status in OPEN for _card, status, _done in _ticket_cards(pack, intent["ticket"])):
            waits = "human"
    advance(intent, "held", "gatekeeper")
    intent["hold"] = {
        "time": iso(),
        "reason": reason,
        "waits": "human" if ask else waits,
        "rework": rework,
        "ask": ask,
        "options": options or [],
    }
    intent.pop("endorsement", None)
    save(intent)
    if pack is not None and (pack.get("outbox") or {}).get("comment_card") and intent.get("card_id") and not rework:
        from .acts import note_card

        note_card(
            pack,
            intent["card_id"],
            "gatekeeper",
            f"{iid} is held ({'waits for ' + intent['hold']['waits']}): {reason[:600]}",
        )
    redo = REDO_WITH_SKILL.match(reason or "")
    named = [name for name in re.split(r"[ ,]+(?:and )?", redo.group(1)) if name and name != "and"] if redo else []
    if pack is not None and rework and not ask:
        from .gate import return_intent

        # the card carries the skills the hold names (a missing skill, a "redo with skill X loaded" reason)
        return return_intent(
            pack,
            iid,
            f"{rework}\n\n(The gatekeeper held it: {reason[:600]})",
            chain=chain,
            actor="gatekeeper (rework)",
            extra_skills=list(dict.fromkeys([*(skills or ()), *named])),
        )
    if pack is not None and redo and not ask:
        from .gate import return_intent

        names = named
        return return_intent(
            pack,
            iid,
            f"Redo this draft with {', '.join(names)} loaded (the gatekeeper held it: {reason[:300]}), then amend.",
            chain=False,
            actor="gatekeeper (redo with skill)",
            extra_skills=names,
        )
    if rework and not ask:
        return amend(iid, summary=rework, created_by=intent.get("created_by") or "lane")
    return intent


REPLY_KEYS = ("in_reply_to", "thread", "react", "resolve")


def amend(iid, summary="", payload=None, created_by="lane", pack=None, top_level=False) -> dict:
    """Change an open intent; it goes back to pending for the gatekeeper. A push is probed again (its branch moved)."""
    intent = load(iid)
    if intent["status"] == "posted":
        raise CockpitError(f"{iid} is a pending review on the forge: discard it first")
    if intent["status"] not in ("pending", "endorsed", "held", "returned"):
        raise CockpitError(f"{iid} is {intent['status']}; only an open intent is amended")
    merged = {**(intent.get("payload") or {}), **(payload or {})}
    if top_level:
        for key in REPLY_KEYS:
            merged.pop(key, None)
    if intent["type"] in PUSHES and "sha" not in (payload or {}):
        merged.pop("sha", None)
    seq = os.path.basename(intent["id"].split("/", 1)[1])[:3]
    try:
        waits = (
            _prepare(pack, intent["ticket"], intent["type"], merged, seq, self_id=iid, created_by=created_by)
            if pack
            else []
        )
    except CockpitError as exc:
        record(intent["ticket"], intent["type"], intent.get("card_id") or "", created_by, str(exc), iid)
        raise
    intent["payload"] = merged
    if summary:
        intent["agent_summary"] = summary[:300]
    if intent["status"] == "returned":
        intent.setdefault("returned", {})["resolved"] = iso()
    intent.pop("endorsement", None)
    intent.pop("hold", None)
    advance(intent, "pending", created_by)
    intent["amended_at"] = iso()  # a refusal of this ticket and type made before is settled by it
    save(intent)
    log(f"AMEND {iid} by {created_by}")
    if waits:
        return hold(iid, "; ".join(waits), waits="human")
    _request_sweep(intent["ticket"])
    return intent


def reprobe(iid: str, pack=None, actor: str = "human") -> dict:
    """Read git again for a push intent whose probe failed when it was written (`probe_error`): only that error made it
    unverifiable, and Send back or Drop were the only ways out. The payload is not changed; the facts git gives are
    filled in through the amend path, so the intent goes back to pending for the gatekeeper. Git still unreadable is
    said, and the intent stays as it is."""
    intent = load(iid)
    if intent["status"] not in ("pending", "held", "endorsed"):
        raise CockpitError(f"{iid} is {intent['status']}; only a pending, held or endorsed intent is probed again")
    if not (intent.get("payload") or {}).get("probe_error"):
        raise CockpitError(f"{iid} has no probe error: its git was read when it was written")
    trial = dict(intent["payload"])
    trial.pop("sha", None)
    _probe(pack, intent["ticket"], intent["type"], trial)
    if trial.get("probe_error"):
        raise CockpitError(f"git still cannot be read: {trial['probe_error']}")
    amend(iid, created_by=intent.get("created_by") or "lane", pack=pack)
    intent = load(iid)
    intent.setdefault("history", []).append({"time": iso(), "event": "git read again (re-probe)", "by": actor})
    save(intent)
    log(f"REPROBE {iid} by {actor}")
    return intent


def staged_pair_refusal(iid: str, payload: dict) -> str:
    """Why an amend with --after is not taken: the intent is a stage (it waits for another intent), and a stage is not
    also a pair. Said aloud, because an amend that answers "amended" and drops --after without a word leaves a worker
    asked to pair a staged pull request with its push looking at a link that stays empty."""
    after = str((payload or {}).get("after") or "").strip()
    if not after:
        return ""
    try:
        intent = load(iid)
    except FileNotFoundError:
        return ""
    stage = str(
        payload["waits_for"] if "waits_for" in payload else (intent.get("payload") or {}).get("waits_for") or ""
    ).strip()
    if not stage:
        return ""
    same = " That is the order asked for: nothing to change." if stage == after else ""
    return (
        f"{iid} is a stage: it waits for {stage} and goes out only once that is out. A stage is not also paired, so --after "
        f"{after} is not taken.{same} To pair it instead (publish both as one act), amend with --waits-for '' --after {after}."
    )


def relink(iid: str, waits_for: str, pack=None) -> dict:
    """Put an open intent into its sequence after the fact: it waits for `waits_for` and is no longer paired (--after).
    Only the order changes, never what goes out, so an endorsement stays. The human's act, or the gatekeeper's; a lane
    amends its own intent with --waits-for."""
    from .sequence import check_order, check_stage

    lane = os.environ.get("COCKPIT_LANE") or ""
    if lane and lane != "gatekeeper":
        raise CockpitError("relink is the human's (or the gatekeeper's); a lane amends its own intent with --waits-for")
    intent = load(iid)
    if intent["status"] not in OPEN_STATUSES:
        raise CockpitError(f"{iid} is {intent['status']}: only an open intent waits for another")
    payload = dict(intent.get("payload") or {})
    before = {"after": payload.get("after") or "", "waits_for": payload.get("waits_for") or ""}
    payload["waits_for"] = waits_for
    check_stage(payload, iid)
    check_order(pack, intent["ticket"], intent["type"], payload)
    intent["payload"] = payload
    event = f"relinked: waits for {payload['waits_for']}"
    if before["after"]:
        event += f" (was paired after {before['after']})"
    if before["waits_for"]:
        event += f" (was waiting for {before['waits_for']})"
    intent.setdefault("history", []).append({"time": iso(), "event": event, "by": lane or "human"})
    save(intent)
    log(f"RELINK {iid} waits-for {payload['waits_for']}")
    return intent


def drop(iid, note="") -> dict:
    """The human drops an open intent: nothing leaves. One that already left, or was dropped, is not open; a pending
    review on the forge is discarded there first."""
    intent = load(iid)
    if intent["status"] == "posted":
        raise CockpitError(f"{iid} is a pending review on the forge: discard it first")
    if intent["status"] not in ("pending", "endorsed", "held", "returned"):
        raise CockpitError(f"{iid} is {intent['status']}; only an open intent is dropped")
    advance(intent, "dropped", "human")
    intent["human"] = {"decision": "drop", "note": note, "time": iso()}
    save(intent)
    return intent


def _reads_path(ticket: str) -> str:
    return qa_of(ticket, "reads.log")


def lines_read(ticket: str) -> set:
    """Lines a reviewer tool actually read for this ticket."""
    path = _reads_path(ticket)
    if not ticket or not os.path.isfile(path):
        return set()
    return {line.strip() for line in open(path, encoding="utf-8") if line.strip()}


def note_read(ticket: str, line: str) -> str:
    """Record one line the reviewer read. A repeated read stays a single line."""
    text = str(line or "").strip()
    if not ticket or not text:
        return ""
    if text in lines_read(ticket):
        return text
    path = _reads_path(ticket)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    append_line(path, text + "\n")
    return text


def refuse_unread(intent) -> None:
    """A finding that cites a line the reviewer did not read is refused."""
    if (intent or {}).get("type") != "pr-review-submit":
        return
    from .test_flow import keep_finding

    payload = (intent or {}).get("payload") or {}
    read = lines_read((intent or {}).get("ticket") or "")
    for line in payload.get("cites") or []:
        keep_finding(str(line), read)


def verify(iid=None, head_sha=None, remote_tip=None, intent=None, pack=None) -> list:
    """Return a list of problems. Empty means the intent may be endorsed."""
    if intent is None:
        intent = load(iid)
    problems = []
    payload = intent.get("payload") or {}
    if head_sha is None and payload.get("sha") and payload.get("repo"):
        from .worktree import head_of

        head_sha = head_of(intent.get("ticket") or "", payload.get("repo") or "", pack)
    if head_sha and payload.get("sha") and payload["sha"] != head_sha and intent.get("type") in PUSHES:
        problems.append("sha does not match worktree HEAD")
    if remote_tip is not None and payload.get("remote_sha") and payload["remote_sha"] != remote_tip:
        problems.append("lease moved")
    problems.extend(
        f"local reference: {hit}" for hit in find_local_refs(_payload_text(payload) + "\n" + _body_text(payload), pack)
    )
    if payload.get("rebase_only") and payload.get("content_changed"):
        problems.append("rebase mixed with content")
    problems.extend(_missing_files(payload))
    if payload.get("probe_error"):
        problems.append(f"git could not be read when the intent was written: {payload['probe_error']}")
    if pack and intent.get("type") in PUSHES and payload.get("repo"):
        problems.extend(_push_problems(pack, intent))
        problems.extend(_bump_push_problems(pack, intent))
    if intent.get("type") == "pr-patch-apply" and payload.get("threads_file"):
        from .patch_apply import rows

        try:
            rows(payload["threads_file"])
        except CockpitError as exc:
            problems.append(f"manifest: {exc}")
    return problems


def _bump_push_problems(pack, intent) -> list:
    """With the pack's forge.bump_push_prefix, a push of a bump batch's ticket goes only to a branch with that prefix (the
    dependabot branch the bump already lives on): a bump never opens a branch of its own."""
    from .sequence import is_batch

    prefix = ((pack or {}).get("forge") or {}).get("bump_push_prefix") or ""
    ticket = intent.get("ticket") or ""
    if not prefix or not is_batch(pack, ticket):
        return []
    target = (intent.get("payload") or {}).get("publish_as") or (intent.get("payload") or {}).get("branch") or ""
    if target and not target.startswith(prefix):
        return [f"a bump pushes only to a `{prefix}` branch, not to {target}"]
    return []


def _missing_files(payload) -> list:
    from .intents import FIELDS
    from .paths import workspace

    missing = []
    for field, shape in FIELDS.items():
        if shape not in ("file", "files") or not payload.get(field):
            continue
        for item in payload[field] if shape == "files" else [payload[field]]:
            if not os.path.isfile(item if os.path.isabs(item) else os.path.join(workspace(), item)):
                missing.append(f"missing {item}")
    return missing


def _run_verify(pack, repo, payload, folder) -> list:
    """The repo's verify commands on the pushed commit: in the checkout when it is at that commit, else in a throwaway
    checkout of it."""
    import subprocess
    import tempfile

    from .git_push import source

    head = subprocess.run(
        ["git", "-C", folder, "rev-parse", "HEAD"], capture_output=True, text=True, check=False
    ).stdout.strip()
    spare = ""
    if head != payload.get("sha"):
        spare = tempfile.mkdtemp(prefix="cockpit-verify-")
        made = subprocess.run(
            ["git", "-C", source(pack, payload["repo"]), "worktree", "add", "-q", "--detach", spare, payload["sha"]],
            capture_output=True,
            text=True,
            check=False,
        )
        if made.returncode != 0:
            return [f"verify: the pushed commit could not be checked out ({made.stderr.strip()[-200:]})"]
        folder = spare
    problems = []
    try:
        files = [name for name in payload.get("files") or [] if os.path.isfile(os.path.join(folder, name))]
        for words in repo["verify"]:
            if "{files}" in words and not files:
                continue
            argv = []
            for word in words:
                if word == "{files}":
                    # a committed file may be named like an option (--fix): as ./--fix it is a path to every tool
                    argv.extend(name if not name.startswith("-") else "./" + name for name in files)
                    continue
                argv.append(
                    word.replace("{base}", str(payload.get("base") or ""))
                    .replace("{sha}", str(payload.get("sha") or ""))
                    .replace("{worktree}", folder)
                    .replace("{pack}", pack["_dir"])
                )
            done = subprocess.run(argv, cwd=folder, capture_output=True, text=True, check=False)
            if done.returncode != 0:
                tail = (done.stdout + done.stderr).strip().splitlines()[-1:] or [f"exit {done.returncode}"]
                problems.append(f"verify {os.path.basename(argv[0])} failed on the pushed range: {tail[0]}")
    finally:
        if spare:
            subprocess.run(
                ["git", "-C", source(pack, payload["repo"]), "worktree", "remove", "--force", spare],
                capture_output=True,
                check=False,
            )
    return problems


def _push_problems(pack, intent) -> list:
    """The remote still at the lease, and the repo's verify commands green on the pushed range."""
    from .git_push import checkout, remote_tip, repo_entry, source

    payload = intent["payload"]
    problems = []
    try:
        repo = repo_entry(pack, payload["repo"])
        folder = checkout(pack, intent["ticket"], payload["repo"])
        tip = remote_tip(source(pack, payload["repo"]), payload.get("publish_as") or payload.get("branch") or "")
    except CockpitError as exc:
        return [str(exc)]
    lease = payload.get("remote_sha") or ""
    if tip != lease and not (
        payload.get("after")
        and tip == ((_load_or_refuse(payload["after"]).get("payload") or {}).get("remote_sha") or "")
    ):
        problems.append(
            f"the remote moved since the intent was written ({lease[:10] or 'absent'} → {tip[:10] or 'absent'}): amend it"
        )
    if repo.get("verify") and payload.get("sha"):  # no sha: git was not read when it was written, which verify names
        problems.extend(_run_verify(pack, repo, payload, folder))
    return problems


def _maybe_hold_skills(pack, intent) -> dict:
    """An intent whose lane has not loaded the type's skills is held for that lane. While the lane's card is still
    running the lane may yet load them, so the intent is deferred instead."""
    from .skill_log import missing, still_running

    gaps = missing(pack, intent)
    if not gaps:
        if intent.pop("skills_deferred", None) is not None:
            save(intent)
        return intent
    if still_running(pack, intent):
        intent["skills_deferred"] = gaps
        save(intent)
        return intent
    intent.pop("skills_deferred", None)
    save(intent)
    if (pack.get("outbox") or {}).get("missing_skill") == "rework":
        # back to the lane on a card that carries the missing skills, so the redone draft is not held again for the same gap
        return hold(
            intent["id"],
            "missing skill: " + ", ".join(gaps),
            waits="lane",
            pack=pack,
            chain=False,
            rework=f"Load {', '.join(gaps)} first, then redo this draft and amend it.",
            skills=gaps,
        )
    return hold(intent["id"], "missing skill: " + ", ".join(gaps), waits="lane")


def refuse_skill_gap(pack, intent) -> None:
    """Endorse and publish stop on an intent whose lane still lacks a required skill."""
    checked = _maybe_hold_skills(pack, intent)
    if checked.get("status") == "held":
        raise CockpitError(checked["hold"]["reason"])
    if checked.get("skills_deferred"):
        raise CockpitError("deferred while the lane runs: missing skill " + ", ".join(checked["skills_deferred"]))


def extra_skills(pack, mode: str, names, carried=()) -> list:
    """Skills beyond the mode's kickoff list and the ones the card carries. The router may add one of these."""
    kickoff = ((pack.get("skills") or {}).get("kickoff") or {}).get(mode) or []
    base = {str(item) for item in [*kickoff, *carried]}
    extras = []
    for name in names or []:
        label = str(name or "").strip()
        if not label or label in base or label in extras:
            continue
        extras.append(label)
    return extras


def ci_override(pack, iid, reason: str) -> dict:
    """The human approves despite CI: this approval at this commit no longer waits for green checks. Offered unless the pack
    sets outbox.ci_override: false; recorded on the intent with the reason; an amend to another commit leaves it behind."""
    human_gate("a CI override")
    if not ci_override_allowed(pack):
        raise CockpitError("this pack does not allow a CI override (outbox.ci_override: false)")
    intent = load(iid)
    payload = intent.get("payload") or {}
    if (
        intent["type"] != "pr-review-submit"
        or str(payload.get("event") or (intent.get("review") or {}).get("proposed_event") or "").upper() != "APPROVE"
    ):
        raise CockpitError(f"{iid} is no approval: only an approval waits for CI")
    if intent["status"] not in ("pending", "endorsed", "held", "posted"):
        raise CockpitError(f"{iid} is {intent['status']}; only an open approval is overridden")
    text = (reason or "").strip()
    if not text:
        raise CockpitError("say why CI is overridden")
    intent["ci_override"] = {"by": "human", "time": iso(), "reason": text[:500], "sha": payload.get("sha") or ""}
    save(intent)
    log(f"CI-OVERRIDE {iid} at {(payload.get('sha') or '')[:12]}: {text[:200]}")
    return intent


def ci_override_allowed(pack) -> bool:
    """The human may override CI on an approval unless the pack says outbox.ci_override: false."""
    return ((pack or {}).get("outbox") or {}).get("ci_override") is not False


def ci_overridden(intent, pack=None) -> bool:
    """The human's CI override stands for this intent's current commit, and the pack still allows overrides."""
    given = intent.get("ci_override") or {}
    return (
        bool(given)
        and ci_override_allowed(pack)
        and given.get("sha", "") == ((intent.get("payload") or {}).get("sha") or "")
    )


def ack(iid) -> dict:
    intent = load(iid)
    if intent["type"] != "ticket-done":
        raise CockpitError("ack is for ticket-done")
    advance(intent, "acknowledged", "human")
    save(intent)
    log(f"ACK {iid}")
    return intent
