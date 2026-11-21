# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Publish an endorsed intent as the human: one publisher per type, each one verify → act → read back.

Each step a publisher finishes is saved on the intent (receipt_steps), so a publish that fails half-way resumes at the
next step instead of posting twice. An intent that follows another (`after`) publishes it first, as one act.
"""

import os
import re

from .errors import CockpitError
from .intents import MANUAL_TYPES, advance, claimed  # what left has left: its record is never refused
from .intents import settle as save
from .store import log
from .time_util import iso

PR_WORK = ("open-pr", "push-branch", "pr-edit", "pr-patch-apply")
REVIEW_STATES = {"REQUEST_CHANGES": "CHANGES_REQUESTED", "COMMENT": "COMMENTED", "APPROVE": "APPROVED"}


def _refuse_lane() -> None:
    if os.environ.get("COCKPIT_LANE"):
        raise CockpitError("a lane cannot publish")


def forge_for(pack, dry_run: bool = False):
    """The pack's forge (forge.kind), as the human: the one place a forge is made."""
    from .forges import make

    return make(pack, dry_run=dry_run)


def _seam(forge):
    from .forges import seam

    return seam(forge)


def _pack(pack):
    if pack is not None:
        return pack
    from .pack import load
    from .paths import pack_path

    return load(pack_path())


def _text(payload) -> str:
    """The intent's body: its draft file, or inline text."""
    from .paths import workspace

    if payload.get("body_file"):
        return open(os.path.join(workspace(), payload["body_file"]), encoding="utf-8").read()
    return str(payload.get("body") or "")


def _json_file(path):
    import json

    from .paths import workspace

    return json.load(open(os.path.join(workspace(), path), encoding="utf-8"))


def _steps(intent) -> dict:
    return intent.setdefault("receipt_steps", {})


def _keep(intent, name: str, value, dry_run: bool, body: str = "") -> None:
    if dry_run:
        return
    _steps(intent)[name] = {"time": iso(), "value": value, **({"body": _digest(body)} if body else {})}
    save(intent)


def _digest(text: str) -> str:
    import hashlib

    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()[:16]


def _done(intent, name: str) -> bool:
    return name in _steps(intent)


def _base(pack, repo: str) -> str:
    from .git_push import repo_entry

    return repo_entry(pack, repo).get("base") or pack.get("base_branch") or "main"


# ---- publishers ----


def _push_branch(pack, intent, forge, dry_run):
    from .git_push import push

    payload = intent["payload"]
    out = push(pack, intent, dry_run=dry_run)
    return _seam(forge).branch_url(payload["repo"], payload.get("publish_as") or payload["branch"]), out


def _verify_pr(forge, repo, number, want) -> None:
    """Never trust a write's own answer: read the PR again and compare each field asked for."""
    forge = _seam(forge)
    found = forge.pr(repo, number)
    labels = forge.labels(repo, number)
    norm = lambda text: str(text or "").replace("\r\n", "\n").strip()  # noqa: E731
    bad = []
    if "base" in want and (found.get("base") or {}).get("ref") != want["base"]:
        bad.append(f"base {(found.get('base') or {}).get('ref')} != {want['base']}")
    if "title" in want and found.get("title") != want["title"]:
        bad.append(f"title {found.get('title')!r}")
    if "body" in want and norm(found.get("body")) != norm(want["body"]):
        bad.append("body differs")
    if "labels" in want and labels != sorted(want["labels"]):
        bad.append(f"labels {labels} != {sorted(want['labels'])}")
    if any(label not in labels for label in want.get("add_labels") or []):
        bad.append(f"labels {labels} miss {want['add_labels']}")
    if any(label in labels for label in want.get("remove_labels") or []):
        bad.append(f"labels {labels} still carry one of {want['remove_labels']}")
    if "assignee" in want and want["assignee"] not in [row.get("login") for row in found.get("assignees") or []]:
        bad.append(f"not assigned to {want['assignee']}")
    if want.get("ready") and found.get("draft"):
        bad.append("still a draft")
    if bad:
        raise CockpitError("read-back after the edit: " + "; ".join(bad))


def _open_pr(pack, intent, forge, dry_run):
    forge = _seam(forge)
    payload = intent["payload"]
    repo, head = payload["repo"], payload["head"]
    base = payload.get("base") or _base(pack, repo)
    body = _text(payload)
    existing = forge.pr_for_head(repo, head, base)
    want = {"title": payload["title"], "body": body}
    if existing:
        number = existing["number"]
        forge.update_pr(repo, number, want)
        out = f"PR #{number} already open for {head} → {base}: title and body edited"
    else:
        made = forge.create_pr(repo, want["title"], want["body"], head, base)
        number = made.get("number")
        out = f"PR #{number} opened" if number else "would open the PR"
        want["base"] = base
    if payload.get("labels") and number:
        forge.add_labels(repo, number, payload["labels"])
        want["add_labels"] = payload["labels"]
    if payload.get("ready") and number:
        forge.mark_ready(repo, number)
        want["ready"] = True
    if dry_run:
        return forge.url(repo, number), out
    _verify_pr(forge, repo, number, want)
    payload["number"] = number
    payload["url"] = forge.url(repo, number)
    return payload["url"], out + " · read back"


def _pr_edit(pack, intent, forge, dry_run):
    forge = _seam(forge)
    payload = intent["payload"]
    repo, number = payload["repo"], payload["number"]
    current = forge.pr(repo, number)
    patch, want, out = {}, {}, []

    def keyed(text: str) -> str:  # {key}: the ticket the --issue-from create made, once it is out
        return text.replace("{key}", _issue_of(intent)) if "{key}" in text else text

    for field in ("base", "title"):
        if payload.get(field):
            patch[field] = keyed(payload[field])
    if payload.get("title_append"):
        title = current.get("title") or ""
        append = keyed(payload["title_append"])
        patch["title"] = title if append in title else f"{title} {append}".strip()
    if payload.get("body_file") or payload.get("body"):
        patch["body"] = _text(payload)
    if patch:
        forge.update_pr(repo, number, patch)
        want.update(patch)
        out.append(f"patched {', '.join(patch)}")
    if payload.get("labels"):
        forge.set_labels(repo, number, payload["labels"])
        want["labels"] = payload["labels"]
    if payload.get("add_labels"):
        forge.add_labels(repo, number, payload["add_labels"])
        want["add_labels"] = payload["add_labels"]
    for label in payload.get("remove_labels") or []:
        if label in forge.labels(repo, number):
            forge.remove_label(repo, number, label)
    if payload.get("remove_labels"):
        want["remove_labels"] = payload["remove_labels"]
    if payload.get("labels") and (payload.get("add_labels") or payload.get("remove_labels")):
        want["labels"] = sorted(
            (set(payload["labels"]) | set(payload.get("add_labels") or [])) - set(payload.get("remove_labels") or [])
        )
    if payload.get("assignee"):
        login = forge.me() if payload["assignee"] == "me" else payload["assignee"]
        forge.assign(repo, number, [login])
        want["assignee"] = login
    if payload.get("ready"):
        forge.mark_ready(repo, number)
        want["ready"] = True
    out += [
        name.replace("_", " ")
        for name in ("labels", "add_labels", "remove_labels", "assignee", "ready")
        if payload.get(name)
    ]
    if not dry_run:
        _verify_pr(forge, repo, number, want)
        out.append("read back")
    return forge.url(repo, number), "; ".join(out)


def _thread(forge, intent, repo, number, comment_id, thread_id, reply, react, resolve, key, dry_run):
    """One review thread: reply (when there is text), thumbs-up, resolve, then read the end state back. A newer comment by
    someone else since the plan leaves the thread open: the human has not seen it."""
    forge = _seam(forge)
    me = forge.me()

    def find(threads):
        return next(
            (row for row in threads if any(c["databaseId"] == comment_id for c in row["comments"]["nodes"])), None
        )

    found = find(forge.threads(repo, number))
    if found is None:
        raise CockpitError(f"review comment {comment_id} is in no thread of {repo}#{number}")
    if thread_id and thread_id != found["id"]:
        raise CockpitError(f"the intent says thread {thread_id}, but comment {comment_id} is in {found['id']}")
    comments = found["comments"]["nodes"]
    at = next(index for index, row in enumerate(comments) if row["databaseId"] == comment_id)
    others = [row for row in comments[at + 1 :] if row["author"]["login"] != me]
    last_other = max((index for index, row in enumerate(comments) if row["author"]["login"] != me), default=at)
    mine = [row for row in comments[last_other + 1 :] if row["author"]["login"] == me]
    out = []
    if reply:
        name = f"{key}reply"
        sent = _steps(intent).get(name) or {}
        revised = bool(sent.get("body")) and sent["body"] != _digest(
            reply
        )  # the draft changed after its reply went: the new text goes
        if _done(intent, name) and not revised:
            out.append("reply already sent")
        elif mine and not revised:
            out.append("reply skipped: you already replied")
        else:
            made = forge.reply(repo, number, comment_id, reply)
            _keep(intent, name, made.get("html_url") or "", dry_run, body=reply)
            out.append("replied again with the revised text" if revised else "replied")
    if others and (react or resolve):
        out.append(f"left open: {others[-1]['author']['login']} wrote after the plan")
        react = resolve = False
    if react and not _done(intent, f"{key}react"):
        reactions = forge.reactions(repo, comment_id)
        if not any(row.get("user", {}).get("login") == me and row.get("content") == "+1" for row in reactions):
            forge.react(repo, comment_id, "+1")
        _keep(intent, f"{key}react", "+1", dry_run)
        out.append("thumbs-up")
    if resolve and not _done(intent, f"{key}resolve"):
        if not found["isResolved"]:
            forge.resolve_thread(found["id"])
        _keep(intent, f"{key}resolve", found["id"], dry_run)
        out.append("resolved")
    if not dry_run:
        after = find(forge.threads(repo, number)) or {}
        nodes = (after.get("comments") or {}).get("nodes") or []
        since = max((index for index, row in enumerate(nodes) if row["author"]["login"] != me), default=-1)
        if reply and not any(row["author"]["login"] == me for row in nodes[since + 1 :]):
            raise CockpitError(f"read-back: no reply of yours in the thread of comment {comment_id}")
        if resolve and not after.get("isResolved"):
            raise CockpitError(f"read-back: the thread of comment {comment_id} is not resolved")
        if not resolve and after.get("isResolved") and not found["isResolved"]:
            raise CockpitError(
                f"read-back: the thread of comment {comment_id} was resolved although the row only replies"
            )
        out.append("read back")
    return comments[0].get("url") or forge.url(repo, number), "; ".join(out)


def _pr_comment(pack, intent, forge, dry_run):
    payload = intent["payload"]
    if payload.get("in_reply_to"):
        return _thread(
            forge,
            intent,
            payload["repo"],
            payload["number"],
            int(payload["in_reply_to"]),
            payload.get("thread"),
            _text(payload) if (payload.get("body_file") or payload.get("body")) else "",
            bool(payload.get("react")),
            bool(payload.get("resolve")),
            "",
            dry_run,
        )
    forge = _seam(forge)
    made = forge.add_comment(payload["repo"], payload["number"], _text(payload))
    return made.get("html_url") or forge.url(payload["repo"], payload["number"]), "commented"


def _pr_patch_apply(pack, intent, forge, dry_run):
    from .patch_apply import pushes, rows

    payload = intent["payload"]
    done = []
    if pushes(payload):
        name = f"push:{payload['sha'][:12]}"
        if _done(intent, name):
            done.append("push: already done")
        else:
            _url, out = _push_branch(pack, intent, forge, dry_run)
            _keep(intent, name, out, dry_run)
            done.append("push: " + out)
    else:
        done.append("push: nothing (the remote has the branch as it is)")
    for row in rows(payload["threads_file"]):
        _url, out = _thread(
            forge,
            intent,
            payload["repo"],
            payload["number"],
            row["comment_id"],
            row.get("thread"),
            row["reply"],
            row["react"],
            row["resolve"],
            f"{row['comment_id']}:",
            dry_run,
        )
        done.append(f"#{row['n']} {out}")
    return _seam(forge).url(payload["repo"], payload["number"]), " · ".join(done)


def _review_threads(payload) -> list:
    rows = _json_file(payload["threads_file"]) if payload.get("threads_file") else []
    found = []
    for row in rows:
        item = {"path": row["path"], "line": int(row["line"]), "side": row.get("side", "RIGHT"), "body": row["body"]}
        if row.get("start_line"):
            item.update(start_line=int(row["start_line"]), start_side=row.get("start_side", item["side"]))
        found.append(item)
    return found


def _pr_review_submit(pack, intent, forge, dry_run):
    """Stage 1: a pending review only the human sees, with the threads; or more threads on the human's pending review."""
    forge = _seam(forge)
    payload = intent["payload"]
    repo, number = payload["repo"], payload["number"]
    head = ((forge.pr(repo, number).get("head") or {}).get("sha")) or ""
    if not head.startswith(payload["sha"]) and not dry_run:
        raise CockpitError(
            f"the PR head moved: reviewed {payload['sha'][:10]}, now {head[:10]}; re-review at the new head"
        )
    me = forge.me()
    pending = [
        row
        for row in forge.reviews(repo, number)
        if row.get("state") == "PENDING" and (row.get("user") or {}).get("login") == me
    ]
    threads = _review_threads(payload)
    url = forge.url(repo, number)
    if payload.get("review_id"):
        review = int(payload["review_id"])
        if review not in [row["id"] for row in pending]:
            raise CockpitError(f"review {review} is not a pending review of yours on {repo}#{number}")
        mine = next(row for row in pending if row["id"] == review)
        before = len(forge.review_comments(repo, number, review))
        added = 0
        for index, row in enumerate(threads):
            if _done(intent, f"append:{index}"):
                continue
            forge.add_review_thread(repo, number, mine, row)
            _keep(intent, f"append:{index}", row["path"], dry_run)
            added += 1
        patches = _json_file(payload["patch_comments"]) if payload.get("patch_comments") else []
        for row in patches:
            if not _done(intent, f"patch:{row['id']}"):
                forge.edit_review_comment(repo, row["id"], row["body"])
                _keep(intent, f"patch:{row['id']}", "patched", dry_run)
        summary = _text({"body_file": payload["review_body_update"]}) if payload.get("review_body_update") else None
        if summary is not None and not _done(intent, "summary"):
            forge.update_review(repo, number, review, summary)
            _keep(intent, "summary", "updated", dry_run)
        if dry_run:
            return url, f"would add {added} thread(s) to pending review {review}"
        got = forge.review_comments(repo, number, review)
        if len(got) < before + added:
            raise CockpitError(f"read-back: review {review} shows {len(got)} comments, not {before + added}")
        by_id = {row["id"]: row.get("body") for row in got}
        if [row["id"] for row in patches if str(by_id.get(int(row["id"])) or "").strip() != row["body"].strip()]:
            raise CockpitError("read-back: a patched comment does not show its new text")
        state = forge.review(repo, number, review)
        if state.get("state") != "PENDING":
            raise CockpitError(f"read-back: review {review} is {state.get('state')}; it stays pending")
        if summary is not None and str(state.get("body") or "").strip() != summary.strip():
            raise CockpitError("read-back: the review summary did not change")
        return forge.review_url(
            repo, number, review
        ), f"pending review {review}: +{added} thread(s), {len(patches)} patched"
    if pending:
        raise CockpitError(
            f"you already have pending review {pending[0]['id']} on {repo}#{number}: amend the intent with "
            f"--review-id {pending[0]['id']} to add to it, or finish or discard it on the forge"
        )
    made = forge.create_review(repo, number, head or payload["sha"], threads)
    if dry_run:
        return url, f"would post a pending review with {len(threads)} thread(s)"
    review = made["id"]
    got = forge.review_comments(repo, number, review)
    if len(got) != len(threads) or sorted(row.get("path") for row in got) != sorted(row["path"] for row in threads):
        raise CockpitError(f"read-back: sent {len(threads)} thread(s), the forge shows {len(got)} on review {review}")
    intent["review"] = {
        "id": review,
        "url": forge.review_url(repo, number, review),
        "posted_at": iso(),
        "proposed_event": payload.get("event") or "COMMENT",
    }
    return intent["review"][
        "url"
    ], f"pending review {review} with {len(got)} thread(s): check it on the forge, then submit"


def _comment_source(intent) -> str:
    """The comment an earlier tracker-comment intent made, which this one updates."""
    from .intents import load

    payload = intent["payload"]
    if not payload.get("comment_from") or payload.get("comment_id"):
        return ""
    source = load(payload["comment_from"])
    if source["status"] == "dropped":
        return ""
    if not str(source["status"]).startswith("published"):
        raise CockpitError(
            f"{source['id']} is {source['status']}: publish or drop it first (this comment updates the one it makes)"
        )
    made = ((source.get("receipt_steps") or {}).get("comment") or {}).get("value")
    if not made:
        raise CockpitError(f"{source['id']} recorded no comment id: amend this intent with --comment-id <id>")
    return str(made)


def _tracker_comment(pack, intent, forge, dry_run, tracker):
    from .test_flow import post_problems

    problems = post_problems(pack, intent)
    if problems:
        raise CockpitError("a test results post that is not ready: " + "; ".join(problems))
    steps = {key: value.get("value") if isinstance(value, dict) else value for key, value in _steps(intent).items()}
    source = _comment_source(intent)
    if source:
        steps["from_comment"] = source
    url, out, made = tracker.comment(intent, steps)
    for key, value in steps.items():
        if key.startswith("attach:"):
            _keep(intent, key, value, dry_run)
    for key, value in made.items():
        _keep(intent, key, value, dry_run)
    return url, out


def _tracker_create(pack, intent, forge, dry_run, tracker):
    steps = {}
    url, out, made = tracker.create(intent, steps)
    for key, value in made.items():
        _keep(intent, key, value, dry_run)
        intent["payload"][key] = value
    return url, out


def _issue_of(intent) -> str:
    from .intents import load

    payload = intent["payload"]
    if payload.get("issue"):
        return payload["issue"]
    source = load(payload["issue_from"])
    key = ((source.get("receipt_steps") or {}).get("key") or {}).get("value") or (source.get("payload") or {}).get(
        "key"
    )
    if not str(source["status"]).startswith("published") or not key:
        raise CockpitError(
            f"{payload['issue_from']} is {source['status']}: the ticket it makes has no key yet; publish it first"
        )
    return str(key)


def _routes(tracker) -> bool:
    """Whether the tracker says which moves a status has (an object from before the tracker protocol: whether it answers `reachable`)."""
    from .trackers import base, has

    return has(tracker, base.TRANSITION_THROUGH)


def _tracker_transition(pack, intent, forge, dry_run, tracker):
    issue = _issue_of(intent)
    out = ""
    if _routes(tracker) and not dry_run and tracker.reachable(issue, intent["payload"]["to"])[0] is None:
        from .intents import all_intents

        first = [
            row
            for row in all_intents(intent["ticket"])
            if row["type"] == "tracker-transition"
            and row["id"] != intent["id"]
            and row["status"] == "endorsed"
            and (row.get("payload") or {}).get("issue") == issue
            and tracker.reachable(issue, row["payload"]["to"])[0] is not None
        ]
        if first:
            earlier = execute(first[0], forge, pack=pack, tracker=tracker)
            save(first[0])
            if not earlier.get("ok"):
                raise CockpitError(f"{first[0]['id']} (the move before this one): {earlier.get('error')}")
            out = f"after {first[0]['id']}: "
    url, moved, _made = tracker.transition(intent, {}, issue)
    return url, out + moved


def _ci_rerun(pack, intent, forge, dry_run):
    forge = _seam(forge)
    payload = intent["payload"]
    forge.rerun_failed(payload["repo"], payload["run_id"])
    out = "failed jobs started again"
    if not dry_run:
        from .ci_watch import rearm

        if rearm(intent["ticket"], payload["repo"], payload["run_id"]):
            out += "; the CI watch reads the commit again"
    return forge.run_url(payload["repo"], payload["run_id"]), out


FORGE = {
    "push-branch": _push_branch,
    "open-pr": _open_pr,
    "pr-edit": _pr_edit,
    "pr-comment": _pr_comment,
    "pr-patch-apply": _pr_patch_apply,
    "pr-review-submit": _pr_review_submit,
    "ci-rerun": _ci_rerun,
}
TRACKER = {
    "tracker-comment": _tracker_comment,
    "tracker-create": _tracker_create,
    "tracker-transition": _tracker_transition,
}


def _first(intent, by_id) -> dict:
    """The intent this one follows. The batch wins; otherwise it is loaded."""
    after = (intent.get("payload") or {}).get("after")
    if not after:
        return {}
    found = (by_id or {}).get(after)
    if found:
        return found
    from .intents import load

    try:
        return load(str(after))
    except FileNotFoundError:
        return {}


def _refuse(intent, pack, explicit_approve) -> None:
    from .local_refs import find_local_refs
    from .outbox import _body_text, _payload_text, refuse_unread, verify

    payload = intent.get("payload") or {}
    texts = _payload_text(payload) + "\n" + _body_text(payload)
    hits = find_local_refs(texts, pack)
    if hits:
        raise CockpitError(f"local reference: {hits[0]}")
    if intent["type"] in MANUAL_TYPES:
        raise CockpitError(f"{intent['type']} is not executed")
    if intent.get("status") not in ("endorsed", "posted"):
        raise CockpitError(f"{intent['id']} is {intent.get('status')}, not endorsed")
    if not intent.get("endorsement") and intent.get("status") == "endorsed":
        raise CockpitError(f"{intent['id']} has no endorsement from the gatekeeper")
    if intent.get("status") == "endorsed":
        from .outbox import changed_drafts

        changed = changed_drafts(intent)
        if changed:
            raise CockpitError(
                f"{intent['id']}: the {' and the '.join(changed)} changed after it was endorsed: endorse it again"
            )
        from .outbox import changed_attachments

        moved = changed_attachments(intent)
        if moved:
            raise CockpitError(
                f"{intent['id']}: an attachment changed after it was endorsed: endorse it again ({', '.join(moved)})"
            )
    from .sequence import said, waits

    wait = waits(intent, pack)
    if wait:
        raise CockpitError(said(intent, wait))
    if pack:
        from .outbox import refuse_skill_gap

        refuse_skill_gap(pack, intent)
    refuse_unread(intent)
    mismatch = [item for item in verify(intent=intent) if item.startswith("sha does not match")]
    if mismatch:
        raise CockpitError(mismatch[0])
    if intent["type"] == "pr-review-submit" and payload.get("event") == "APPROVE" and not explicit_approve:
        raise CockpitError("APPROVE must be named by the human")
    if intent["type"] == "pr-patch-apply":
        from .outbox import new_comments

        waiting = new_comments(intent["ticket"], payload)
        if waiting:
            raise CockpitError(waiting)


@claimed
def execute(
    intent, forge=None, dry_run=False, by_id=None, explicit_approve=False, pack=None, tracker=None, confirm=None
):
    """Publish one intent (its first step too, when it follows another). The receipt; a refusal raises. A caller that
    asked the human passes what the human echoed back as confirm: it must be the intent's own id."""
    _refuse_lane()
    if confirm is not None and confirm != intent.get("id"):
        raise CockpitError("confirm must echo the id")
    pack = _pack(pack)
    forge = _seam(forge or forge_for(pack, dry_run))
    if tracker is None:
        from .tracker import tracker_for

        tracker = tracker_for(pack, dry_run)
    _refuse(intent, pack, explicit_approve)
    first = _first(intent, by_id)
    if first and first.get("id") != intent.get("id") and not str(first.get("status")).startswith("published"):
        if first.get("status") != "endorsed":
            raise CockpitError(
                f"{intent['id']} follows {first['id']}, which is {first.get('status')}: both steps must be endorsed"
            )
        earlier = execute(
            first, forge, dry_run=dry_run, by_id=by_id, explicit_approve=explicit_approve, pack=pack, tracker=tracker
        )
        if not dry_run:
            save(first)
        if not earlier.get("ok"):
            return earlier
    if intent["type"] == "tracker-comment" and intent["payload"].get("comment_from"):
        from .intents import load

        source = (by_id or {}).get(intent["payload"]["comment_from"]) or load(intent["payload"]["comment_from"])
        if source.get("status") == "endorsed":
            earlier = execute(source, forge, dry_run=dry_run, by_id=by_id, pack=pack, tracker=tracker)
            if not dry_run:
                save(source)
            if not earlier.get("ok"):
                return earlier
    if intent["type"] == "pr-review-submit" and intent["status"] == "posted":
        return submit_review(intent, forge, explicit=explicit_approve, pack=pack, dry_run=dry_run)
    try:
        if intent["type"] in TRACKER:
            url, out = TRACKER[intent["type"]](pack, intent, forge, dry_run, tracker)
        elif intent["type"] in FORGE:
            url, out = FORGE[intent["type"]](pack, intent, forge, dry_run)
        else:
            raise CockpitError(f"no publisher for {intent['type']}")
    except CockpitError as exc:
        receipt = {"ok": False, "error": str(exc), "time": iso()}
        if not dry_run:
            intent["receipt"] = receipt
            save(intent)
            log(f"PUBLISH FAIL {intent['id']} :: {exc}")
        return receipt
    if dry_run:
        writes = list(getattr(forge, "writes", [])) + list(getattr(tracker, "writes", []))
        return {"ok": True, "dry_run": True, "id": intent["id"], "url": url, "output": out, "actions": writes}
    if intent["type"] == "pr-review-submit" and intent.get("review") and not intent["payload"].get("review_id"):
        advance(intent, "posted", "human")
        summary = _summary_digest(intent["payload"])
        if summary:
            intent["review"]["files"] = summary  # the summary the human published stage one with: stage two compares
        intent["receipt"] = {"ok": True, "url": url, "output": out, "time": iso(), "stage": "pending"}
        save(intent)
        log(f"POST-PENDING {intent['id']} {url}")
        return intent["receipt"]
    advance(intent, "published", "human")
    intent["human"] = {"decision": "publish", "time": iso()}
    intent["receipt"] = {
        "ok": True,
        "url": url,
        "sha": intent["payload"].get("sha", ""),
        "output": out[-300:],
        "time": iso(),
    }
    save(intent)
    log(f"PUBLISH {intent['id']} {url} {intent['receipt']['time']}")
    _announce(pack, intent, url)
    return intent["receipt"]


def _announce(pack, intent, url: str) -> None:
    """The ticket's PRs all out, or a PR updated after review: told once. A failed message never fails the publish."""
    from .gate import PR_WORK, announce, updated
    from .patch_apply import pushes

    try:
        if intent["type"] == "pr-patch-apply" and pushes(intent["payload"]):
            intent["announced"] = updated(pack, intent["ticket"], url, intent["payload"]["sha"])
        if intent["type"] in PR_WORK:
            intent["ready"] = announce(pack, intent["ticket"])
    except CockpitError as exc:
        intent["announced"] = str(exc)
    save(intent)


def _reread(intent) -> bool:
    """The row says what its file says now. True when the file had changed since the row was read: only a row that was
    read from its file is compared (one built in memory has nothing to differ from)."""
    from .intents import load

    seen = getattr(intent, "seen", None)
    if seen is None:
        return False
    try:
        now = load(intent["id"])
    except FileNotFoundError:
        return False  # gone: the publisher refuses it in its own words
    if now.seen == seen:
        return False
    intent.clear()
    intent.update(now)
    intent.seen = now.seen
    return True


def publish_all(rows, forge, confirms=None, pack=None) -> list:
    """Send ready intents in order, each confirmed by its own id echoed back. Stop at the first refusal. Each row is
    read again just before its turn: publishing one row may publish another of the batch first (the move a later move
    needs), and that one is then not sent a second time; its receipt is the one it was published with."""
    done = []
    echoed = confirms or {}
    by_id = {row["id"]: row for row in rows}
    tickets = []
    for intent in rows:
        if echoed.get(intent["id"]) != intent["id"]:
            raise CockpitError("confirm must echo the id")
        left = (
            _reread(intent)
            and str(intent.get("status")).startswith("published")
            and (intent.get("receipt") or {}).get("ok")
        )
        try:
            receipt = intent["receipt"] if left else execute(intent, forge, by_id=by_id, pack=pack)
        except CockpitError as exc:
            receipt = {"ok": False, "error": str(exc), "id": intent["id"]}
        if receipt.get("ok") and not left:
            save(intent)
        done.append(receipt)
        if not receipt.get("ok"):
            break
        if intent["type"] == "open-pr" and intent["ticket"] not in tickets:
            tickets.append(intent["ticket"])
    for ticket in tickets:
        backfill_related(forge, ticket)
    return done


def _summary_digest(payload) -> dict:
    """The digest of a review's drafted summary ({} when the summary is inline or there is none)."""
    from .outbox import draft_digests

    return draft_digests({"body_file": (payload or {}).get("body_file")})


@claimed
def submit_review(intent, forge, event=None, body=None, explicit=True, pack=None, dry_run=False) -> dict:
    """Stage 2: submit the human's pending review with the verdict and summary the human confirmed. A summary the human
    gives now is theirs; the drafted one is sent only while it is still the file stage one was published with (a review
    posted before that digest was kept has none, and is submitted as it always was)."""
    _refuse_lane()
    pack = _pack(pack)
    forge = _seam(forge)
    review = (intent.get("review") or {}).get("id")
    if intent.get("status") != "posted" or not review:
        raise CockpitError(f"{intent['id']} is {intent.get('status')}; only a posted (pending) review is submitted")
    payload = intent["payload"]
    repo, number = payload["repo"], payload["number"]
    event = str(event or intent["review"].get("proposed_event") or payload.get("event") or "COMMENT").upper()
    if event not in REVIEW_STATES:
        raise CockpitError(f"the verdict is one of {', '.join(REVIEW_STATES)}")
    if event == "APPROVE":
        if not explicit:
            raise CockpitError("APPROVE must be named by the human")
        from .outbox import ci_overridden

        bad = [] if ci_overridden(intent, pack) else forge.checks(repo, payload["sha"])
        if bad:
            raise CockpitError(f"APPROVE waits for green checks on {repo}#{number}: {', '.join(bad[:4])}")
    posted_with = intent["review"].get("files")
    if body is None and isinstance(posted_with, dict) and _summary_digest(payload) != posted_with:
        raise CockpitError(
            f"{intent['id']}: the body changed after its pending review was posted: give the summary you mean when you "
            "submit it, or discard the pending review and endorse it again"
        )
    text = body if body is not None else _text(payload)
    want = REVIEW_STATES[event]
    state = forge.review(repo, number, review).get("state")
    if state not in ("PENDING", want):
        raise CockpitError(f"review {review} is {state}, not pending (submitted or discarded on the forge?)")
    if state == "PENDING":
        forge.submit_review(repo, number, review, event, text)
    if dry_run:
        return {"ok": True, "dry_run": True, "id": intent["id"], "output": f"would submit review {review} as {event}"}
    back = forge.review(repo, number, review).get("state")
    if back != want:
        raise CockpitError(f"read-back: review {review} is {back} after the submit")
    labels = _review_labels(pack, forge, repo, number, event)
    advance(intent, "published", "human")
    intent["review"].update(event=event, submitted_at=iso(), state=back)
    payload.update(event=event, body=text)
    url = intent["review"].get("url") or forge.url(repo, number)
    intent["receipt"] = {
        "ok": True,
        "url": url,
        "sha": payload.get("sha", ""),
        "time": iso(),
        "stage": "submit",
        "output": f"review {review} submitted as {event}" + (f" · labels {labels}" if labels else ""),
    }
    save(intent)
    log(f"PUBLISH {intent['id']} {url} ({event}) {intent['receipt']['time']}")
    return intent["receipt"]


def _review_labels(pack, forge, repo, number, event) -> str:
    """The pack's labels for this verdict (forge.review_labels: {event: {add, remove}}), matched by name in any case."""
    rule = ((((pack or {}).get("forge") or {}).get("review_labels") or {}).get(event)) or {}
    if not rule:
        return ""
    forge = _seam(forge)
    names = {name.lower(): name for name in forge.repo_labels(repo)}
    current = set(forge.labels(repo, number))
    changed = []
    for label in rule.get("add") or []:
        real = names.get(label.lower())
        if real and real not in current:
            forge.add_labels(repo, number, [real])
            changed.append("+" + real)
    for label in rule.get("remove") or []:
        real = names.get(label.lower())
        if real and real in current:
            forge.remove_label(repo, number, real)
            changed.append("-" + real)
    after = set(forge.labels(repo, number))
    missing = [
        names[label.lower()]
        for label in rule.get("add") or []
        if label.lower() in names and names[label.lower()] not in after
    ]
    stayed = [
        names[label.lower()]
        for label in rule.get("remove") or []
        if label.lower() in names and names[label.lower()] in after
    ]
    if missing or stayed:
        raise CockpitError(f"read-back: labels {sorted(after)}; missing {missing}, still there {stayed}")
    return ", ".join(changed) or "unchanged"


def discard_pending(intent, forge) -> dict:
    """Delete the pending review on the forge. The intent goes back to endorsed and is not sent again by itself."""
    _refuse_lane()
    if intent.get("type") != "pr-review-submit":
        raise CockpitError("not a review")
    review = (intent.get("review") or {}).get("id")
    if intent.get("status") != "posted" or not review:
        raise CockpitError("not a pending review")
    payload = intent.get("payload") or {}
    try:
        _seam(forge).discard_review(payload["repo"], payload["number"], review)
    except CockpitError as exc:
        log(f"DISCARD FAIL {intent.get('id')} :: {exc}")
        raise
    intent.setdefault("history", []).append(
        {"time": iso(), "event": "discarded pending review", "review": intent.pop("review")}
    )
    advance(intent, "endorsed", "human")
    intent["receipt"] = {
        "ok": True,
        "discarded": True,
        "repo": payload.get("repo"),
        "number": payload.get("number"),
        "time": iso(),
    }
    log(f"DISCARD {intent.get('id')} review {review}")
    return intent


def link_siblings(forge, intent, receipt) -> None:
    """After one intent went out by itself (the Desktop's Publish, the command line's --id): when it opened a PR, the
    ticket's PRs get each other's links, as a digest's reply does. The PRs of a ticket's repos go out one at a time,
    each when its own push is ready, so the first carries `- (<repo>) TBD` until the second exists. A digest fills
    it; the Desktop sends one row at a time, so a single send fills it here.
    A fill that fails never fails what went out: the receipt says so."""
    if intent.get("type") != "open-pr" or not receipt.get("ok") or receipt.get("dry_run"):
        return
    try:
        receipt["related"] = backfill_related(forge, intent["ticket"])
    except CockpitError as exc:
        receipt["related_error"] = str(exc)
        log(f"BACKFILL FAIL {intent['ticket']} :: {exc}")


def backfill_related(forge, ticket: str) -> list:
    """Once a ticket's PRs exist, each body's `- (<repo>) TBD` line gets the sibling PR's link. Read back."""
    from .intents import all_intents

    forge = _seam(forge)
    prs = {}
    for intent in all_intents(ticket):
        url = (intent.get("receipt") or {}).get("url") or ""
        found = re.search(r"/pull/(\d+)", url)
        if intent["type"] == "open-pr" and str(intent["status"]).startswith("published") and found:
            prs[intent["payload"]["repo"]] = (found.group(1), url)
    filled = []
    for repo, (number, _url) in prs.items():
        body = forge.pr(repo, number).get("body") or ""
        new = body
        for other, (_n, link) in prs.items():
            if other != repo:
                new = re.sub(
                    rf"^([ \t]*-[ \t]*\({re.escape(other)}\))[ \t]+TBD[ \t]*$",
                    lambda match: f"{match.group(1)} {link}",
                    new,
                    flags=re.M,
                )
        if new == body:
            continue
        forge.update_pr(repo, number, {"body": new})
        left = [
            name
            for name in re.findall(r"^\s*-\s*\((\S+)\)\s+TBD\s*$", forge.pr(repo, number).get("body") or "", re.M)
            if name in prs and name != repo
        ]
        if left and not forge.dry_run:
            raise CockpitError(f"read-back: {repo}#{number} still shows TBD for {left}")
        filled.append(f"{repo}#{number}")
        log(f"BACKFILL {ticket} {repo}#{number}")
    return filled
