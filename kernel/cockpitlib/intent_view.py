# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""An intent as the Inbox and Outbox panes read it: the list row plus what leaves (the drafted files, rendered), its
receipt log lines, and the Brief: four fields derived from what the lane and the gatekeeper already wrote."""

import json
import os
import re

BODY_LIMIT = 2_000_000
FILE_LIMIT = 40_000
OUTGOING = ("pr-comment", "pr-review-submit", "tracker-comment", "tracker-create", "pr-edit", "pr-patch-apply")
PUSHES = ("push-branch", "pr-patch-apply")


def read_text(path: str, limit: int) -> str:
    try:
        with open(path, encoding="utf-8", errors="replace") as handle:
            return handle.read(limit)
    except OSError as exc:
        return f"(unreadable: {exc})"


def adf_of(text: str):
    """The parsed document when a file holds the tracker's document format, else None."""
    try:
        data = json.loads(text)
    except (TypeError, ValueError):
        return None
    return data if isinstance(data, dict) and data.get("type") == "doc" else None


def plan_one_liner(ticket: str) -> tuple:
    """(the plan's one-line change or its Brief's first line, the plan's section names)."""
    from .plan import brief_of, show

    text = show(ticket)
    if not text:
        return "", []
    match = re.search(r"\*\*Change in one line:\*\*\s*(.+)", text)
    line = (
        match.group(1).strip()
        if match
        else next((row.strip() for row in brief_of(text).splitlines() if row.strip()), "")
    )
    return line, [row[3:].strip() for row in text.splitlines() if row.startswith("## ")]


def push_shape(row: dict, pack=None) -> tuple:
    """(commits, files, diffstat) of a push: what the payload recorded, else read from the checkout (base..sha)."""
    payload = row.get("payload") or {}
    commits = list(payload.get("commits") or [])
    files = list(payload.get("files") or [])
    stat = str(payload.get("diffstat") or "")
    if commits or files or payload.get("rebase_only"):
        return commits, files, stat
    sha = str(payload.get("sha") or "")
    repo = payload.get("repo") or ""
    if not re.match(r"^[0-9a-f]{7,40}$", sha) or not repo:
        return commits, files, stat
    try:
        from .diffs import checkout_of, git, ref_ok

        folder = checkout_of(row.get("ticket") or "", repo, pack)
        from .git_push import repo_branch

        base = payload.get("base") if ref_ok(str(payload.get("base") or "")) else "origin/" + repo_branch(pack, repo)
        try:
            merge_base = git(folder, "merge-base", base, sha).strip()
        except Exception:  # noqa: BLE001 - no merge base: the base itself is compared
            merge_base = base
        rng = f"{merge_base}..{sha}"
        commits = git(folder, "log", "--no-decorate", "--format=%h %s", rng).strip().splitlines()
        files = git(folder, "diff", "--name-only", rng).split()
        stat = git(folder, "diff", "--shortstat", rng).strip()
    except Exception:  # noqa: BLE001 - the stat line is optional
        return commits, files, stat
    return commits, files, stat


def brief_fields(row: dict, pack=None) -> list:
    """What leaves, why, what was checked, what it touches: platform words, nothing invented."""
    from .patch_apply import pushes

    payload = row.get("payload") or {}
    kind = row.get("type") or ""
    target = row.get("target") or ""
    commits, files, diffstat = push_shape(row, pack) if kind in PUSHES else ([], [], "")
    if kind == "push-branch":
        what = (
            f"branch `{payload.get('publish_as') or payload.get('branch') or ''}` of {payload.get('repo')} → origin"
            + (
                ": rebase only, no content change"
                if payload.get("rebase_only")
                else f", {len(commits)} commit(s), {len(files)} file(s)"
            )
        )
    elif kind == "open-pr":
        what = f"a new PR on {payload.get('repo')}: {payload.get('title') or ''} ({payload.get('branch') or ''} → {payload.get('base') or 'the base branch'})"
    elif kind == "pr-patch-apply":
        push = (
            f"the push of `{payload.get('publish_as') or payload.get('branch') or ''}` ({len(commits)} commit(s), {len(files)} file(s))"
            if pushes(payload)
            else "no push (nothing new on the branch)"
        )
        what = f"the patch apply on {payload.get('repo')}#{payload.get('number')}, in one go: {push}, then every agreed review-thread action (👍 + resolve, or a reply)"
    elif kind == "pr-comment":
        what = f"a comment on {payload.get('repo')}#{payload.get('number')}" + (
            (" as a reply in a review thread" + (", resolving it" if payload.get("resolve") else ""))
            if payload.get("in_reply_to")
            else ", top level"
        )
    elif kind == "pr-review-submit":
        what = (
            f"a review on {payload.get('repo')}#{payload.get('number')}: {payload.get('event') or 'verdict to confirm'}"
            + (
                " (stage 2 of 2: it is pending on the forge now)"
                if row.get("status") == "posted"
                else " (stage 1: posted as pending first)"
            )
        )
    elif kind == "pr-edit":
        what = f"PR metadata on {target}"
    elif kind == "tracker-comment":
        what = f"a comment on the tracker issue {payload.get('issue') or row.get('ticket')}"
    elif kind == "tracker-create":
        what = f"a new tracker ticket: {payload.get('summary') or ''}"
    elif kind == "tracker-transition":
        what = f"tracker issue {payload.get('issue') or row.get('ticket')} → {payload.get('transition') or payload.get('to') or payload.get('status') or ''}"
    elif kind == "ci-rerun":
        what = f"a rerun of CI run {payload.get('run_id') or ''} on {payload.get('repo')} (flaky verdict)"
    elif kind == "ticket-done":
        what = "nothing. Your acknowledgement that the ticket is done in dev, recorded locally"
    else:
        what = target
    fields = [
        {"label": "What leaves", "text": what, "items": []},
        {"label": "Why", "text": row.get("summary") or "", "items": []},
    ]
    checked = []
    endorsed = row.get("endorsed") or {}
    hold = row.get("hold") or {}
    status = row.get("status")
    if endorsed:
        checked.append(
            f"{endorsed.get('by') or 'gatekeeper'} endorsed, risk {endorsed.get('risk')}: {endorsed.get('notes') or 'no notes'}"
        )
    elif hold:
        checked.append(f"held by the gatekeeper: {hold.get('reason')}")
    elif status == "pending":
        checked.append("waiting for the gatekeeper")
    skills = row.get("skills") or {}
    if skills.get("required"):
        checked.append(
            "skills "
            + (
                "✓ " + ", ".join(skills["required"])
                if skills.get("ok")
                else "missing " + ", ".join(skills.get("missing") or [])
            )
        )
    chain = row.get("chain") or {}
    if chain.get("role") == "content":
        checked.append(f"paired with the rebase step {(payload.get('after') or '')} ({chain.get('step1_status')})")
    returned = row.get("returned") or {}
    if returned:
        checked.append(
            f"sent back once to {returned.get('lane')}: {(returned.get('instruction') or '')[:120]}"
            + (" · reworked" if returned.get("resolved") else " · rework pending")
        )
    pr = row.get("pr") or {}
    if pr.get("new_count"):
        checked.append(f"{pr['new_count']} PR comment(s) arrived after the pipeline's pass")
    ci = row.get("ci") or {}
    if ci.get("state"):
        checked.append(f"CI {ci['state']} @ {ci.get('sha')}: {ci.get('summary')}")
    fields.append({"label": "Checked", "text": "", "items": checked})
    touches = []
    if kind in PUSHES and not payload.get("rebase_only"):
        if diffstat:
            touches.append(diffstat)
        touches += [f"`{name}`" for name in files[:8]]
        if len(files) > 8:
            touches.append(f"… {len(files) - 8} more")
    elif kind == "pr-review-submit":
        body = (row.get("file_contents") or {}).get("body_file") or ""
        counts = {key: len(re.findall(rf"(?m)^\s*(?:\d+\.\s*|[-*]\s*)?\**{key}:", body)) for key in ("B", "CS", "Q")}
        if any(counts.values()):
            touches.append(
                f"findings: {counts['B']} blocking (B), {counts['CS']} code style (CS), {counts['Q']} question (Q)"
            )
        review = row.get("review") or {}
        if review.get("url"):
            touches.append(f"pending review: {review['url']}")
    elif kind == "ticket-done":
        line, sections = plan_one_liner(row.get("ticket") or "")
        if line:
            touches.append(f"shipped: {line}")
        if sections:
            touches.append("trail: " + ", ".join(sections))
        if pr.get("merged") or payload.get("merged_at"):
            touches.append(
                f"PR #{pr.get('number') or payload.get('number')} merged"
                + (
                    f" at {str(payload.get('merged_at') or pr.get('merged_at') or '')[:16]}"
                    if payload.get("merged_at") or pr.get("merged_at")
                    else ""
                )
            )
    elif kind == "ci-rerun":
        touches.append(
            f"run {payload.get('run_id') or ''}"
            + (f" · attempt {payload.get('attempt')}" if payload.get("attempt") else "")
        )
    fields.append({"label": "Touches", "text": "", "items": touches})
    return fields


def enrich(row: dict, pack=None) -> dict:
    """The list row with its files' text (what leaves is shown whole: a test report is easily 50 kB and a cut body
    neither parses nor tells the truth; the other files keep the short read and say when they are cut), the markdown
    and tracker-document renderings, the receipt log lines, the Brief and which file is the outgoing one."""
    from .board_view import brief_html
    from .paths import receipt_log as published_log
    from .render import adf, markdown

    out = dict(row)
    payload = out.get("payload") or {}
    from .outbox import ci_override_allowed

    out["ci_override_allowed"] = (
        ci_override_allowed(pack)
        and out.get("type") == "pr-review-submit"
        and str(payload.get("event") or (out.get("review") or {}).get("proposed_event") or "").upper() == "APPROVE"
    )
    files = out.get("files") or {}
    out["file_contents"] = {
        key: read_text(path, BODY_LIMIT if key == "body_file" else FILE_LIMIT) for key, path in files.items()
    }
    out["file_truncated"] = [
        key
        for key, path in files.items()
        if os.path.exists(path) and os.path.getsize(path) > (BODY_LIMIT if key == "body_file" else FILE_LIMIT)
    ]
    out["file_html"] = {key: markdown(out["file_contents"][key]) for key, path in files.items() if path.endswith(".md")}
    for key, path in files.items():
        document = adf_of(out["file_contents"][key]) if path.endswith(".json") else None
        if document:
            out["file_html"][key] = adf(document)
    log_path = published_log()
    iid = str(out.get("id") or "")
    out["log"] = (
        [line for line in read_text(log_path, 400_000).splitlines() if iid and iid in line][-20:]
        if os.path.isfile(log_path)
        else []
    )
    out["brief"] = brief_html(brief_fields(out, pack))
    out["outgoing"] = "body_file" if out.get("type") in OUTGOING and "body_file" in files else None
    return out
