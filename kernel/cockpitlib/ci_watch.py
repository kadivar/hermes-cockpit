# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The CI watch: the forge's workflow runs on each commit the human pushed or authors a PR for, one record per commit.

A failed attempt of a run gets one analyst card, with the failed jobs' log tail and the run's flaky history. A commit
whose runs all passed is announced green once, after the runs have settled; a commit that no CI picks up within the
pack's time is recorded as having none. A dismissed commit, a settled one and a merged or closed PR are not read again,
except a failed commit that is still its branch's newest push: a rerun of it (published from the outbox or started by hand
on the forge) must be seen within a pass, so it is asked every pass with a conditional read, which the forge answers
"unchanged" without counting it. When each record was read, and that read's ETag, live in watch/ci-checked.json.
"""

import json
import os
import re
import time

from .errors import CockpitError
from .intents import all_intents
from .paths import qa_of
from .record_write import Checks, with_checked, write_record
from .time_util import iso, stamp

FAILED = ("failure", "timed_out", "startup_failure")
PASSED = ("success", "skipped", "neutral")
SETTLE_MINUTES = 10
NO_CI_MINUTES = 30
# A settled commit that failed is read again this often when the pack sets no `hours.ci_reread_minutes`: a run started by
# hand on the forge is a new attempt on the same commit, and a failed commit must not be read every pass to catch it.
FAILED_REREAD_MINUTES = 60
TAIL_LINES = 40


def _folder(ticket: str) -> str:
    from .paths import segment

    return qa_of(segment(ticket, "ticket") if ticket else "", "ci")


def record_path(ticket: str, repo: str, sha: str) -> str:
    from .paths import within

    return within(_folder(ticket), f"{repo}-{sha[:12]}.json", "repo")


def _records(folder: str) -> list:
    """The names of a folder's records, in order: a lock or a temp file of store's is no record, and is never read as one."""
    from .store import scratch

    return sorted(name for name in os.listdir(folder) if not scratch(name)) if os.path.isdir(folder) else []


def _read(path: str) -> dict:
    try:
        data = json.load(open(path, encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _write(path: str, data: dict) -> None:
    write_record(path, data)


def failed_states(pack) -> tuple:
    extra = ((((pack or {}).get("watchers") or {}).get("ci") or {}).get("failed_states")) or []
    return (*FAILED, *extra)


def _minutes(pack, name: str, default: int) -> float:
    return float(((pack or {}).get("hours") or {}).get(name) or default)


def commits(pack) -> list:
    """(ticket, repo, sha, branch) to watch: the pushes the human published, and the heads of the human's own open PRs."""
    found = {}
    for intent in all_intents():
        payload = intent.get("payload") or {}
        if (
            intent.get("type") in ("push-branch", "pr-patch-apply")
            and str(intent.get("status")).startswith("published")
            and payload.get("sha")
            and payload.get("repo")
            and not payload.get("rebase_only")
        ):
            found[(payload["repo"], payload["sha"])] = (
                intent["ticket"],
                payload["repo"],
                payload["sha"],
                payload.get("publish_as") or payload.get("branch") or "",
            )
    from .paths import qa

    root = qa()
    for ticket in sorted(os.listdir(root)) if os.path.isdir(root) else []:
        folder = qa_of(ticket, "pr")
        for name in sorted(os.listdir(folder)) if os.path.isdir(folder) else []:
            state = _read(os.path.join(folder, name)) if name.endswith(".json") else {}
            if not state.get("repo") or not state.get("head_sha") or "rows" in state:
                continue
            if (
                state.get("role", "author") != "author"
                or str(state.get("state", "open")).lower() != "open"
                or state.get("merged")
            ):
                continue
            found.setdefault(
                (state["repo"], state["head_sha"]), (ticket, state["repo"], state["head_sha"], state.get("head") or "")
            )
    return list(found.values())


def _dismissed(ticket: str, repo: str, sha: str) -> bool:
    from .paths import platform_dir

    items = _read(os.path.join(platform_dir(), "ci-dismissed.json")).get("items") or []
    return any(item.get("ticket") == ticket and item.get("repo") == repo and item.get("sha") == sha for item in items)


def _tail(forge, repo: str, run: dict) -> str:
    """The last lines of each failed job's log."""
    from .forges import seam

    forge = seam(forge)
    lines = []
    jobs = forge.run_jobs(repo, run["id"])
    for job in jobs:
        if job.get("conclusion") not in ("failure", "timed_out"):
            continue
        try:
            text = forge.job_log(repo, job["id"])
        except CockpitError as exc:
            text = f"(log unreadable: {exc})"
        tail = str(text if isinstance(text, str) else json.dumps(text)).splitlines()[-TAIL_LINES:]
        from .quoted import external

        lines += [f"### {job.get('name')}", external("\n".join(tail))]  # a log is whatever the run printed: quoted
    return "\n".join(lines)


def _flaky(ticket: str, repo: str, name: str) -> int:
    """How often this run name failed on an earlier commit of the ticket and then passed on a rerun."""
    count = 0
    folder = _folder(ticket)
    for file in _records(folder):
        record = _read(os.path.join(folder, file))
        if record.get("repo") != repo:
            continue
        for run in record.get("runs") or []:
            if run.get("name") == name and run.get("passed_after_rerun"):
                count += 1
    return count


def _repo_flaky(repo: str, name: str) -> list:
    """The repo's other tickets where this run name failed and then passed on a rerun: [(ticket, count)], most first."""
    from .paths import qa

    root = qa()
    found = {}
    for ticket in os.listdir(root) if os.path.isdir(root) else []:
        folder = qa_of(ticket, "ci")
        for file in _records(folder):
            record = _read(os.path.join(folder, file))
            if record.get("repo") != repo:
                continue
            count = sum(
                1 for run in record.get("runs") or [] if run.get("name") == name and run.get("passed_after_rerun")
            )
            if count:
                found[ticket] = found.get(ticket, 0) + count
    return sorted(found.items(), key=lambda item: (-item[1], item[0]))


def _repo_line(repo: str, name: str, ticket: str) -> str:
    others = [(name_, count) for name_, count in _repo_flaky(repo, name) if name_ != ticket]
    if not others:
        return "Flaky history of this run on the repo's other tickets: none."
    shown = ", ".join(f"{name_} ({count})" for name_, count in others[:8])
    return f"Flaky history of this run on the repo's other tickets: {sum(count for _name, count in others)} time(s): {shown}."


AGAIN = """A rerun failed after this diagnosis was finished: attempt {attempt}. A test already called flaky once is not flaky twice:
treat this failure as real unless the log shows an infrastructure cause.

"""
CARD_BODY = """CI failed on {repo} at {sha} ({branch}): {name}, attempt {attempt}.
{url}

Diagnose it from the code, the log and the history; read-only. Then decide:
- flaky (unrelated to the change): `cockpit ci flaky {ticket} {sha} --run-id {run}` writes the rerun intent.
- real: say what breaks and why on this card; intake is reopened for a plan.

Flaky history of this run on the ticket: {flaky} time(s).
{repo_flaky}

## Failed jobs, last lines
{tail}
"""


def _card(pack, ticket, repo, sha, branch, run, forge) -> str:
    from .acts import open_analyst

    body = CARD_BODY.format(
        repo=repo,
        sha=sha[:9],
        branch=branch or "?",
        name=run.get("name"),
        attempt=run.get("run_attempt") or 1,
        url=run.get("html_url") or "",
        ticket=ticket,
        run=run["id"],
        flaky=_flaky(ticket, repo, run.get("name")),
        repo_flaky=_repo_line(repo, run.get("name"), ticket),
        tail=_tail(forge, repo, run) or "(no failed job log)",
    )
    # One card per commit and workflow, not per attempt: a rerun that fails again belongs to the diagnosis already made
    # (open: it hears about the attempt; done: its verdict stands, the flaky rerun or intake's plan carries on).
    key = f"{sha[:9]} {run.get('name')}"
    from .kanban import BoardWrites, _index, board_cards

    known = {
        card_id
        for card_id, entry in ((_index().get(pack["board"]) or {}).items())
        if isinstance(entry, dict)
        and entry.get("kind") == "ci"
        and entry.get("ticket") == ticket
        and entry.get("key") == key
    }
    if known:
        cards = {card["id"]: card for card in board_cards(pack["board"]) if card["id"] in known}
        live = [card_id for card_id, card in cards.items() if card.get("status") not in ("done", "archived")]
        per_attempt = bool((((pack or {}).get("watchers") or {}).get("ci") or {}).get("card_per_attempt"))
        if not live and cards and per_attempt and int(run.get("run_attempt") or 1) > 1:
            # the pack asks for a card per attempt: the diagnosis was finished, the rerun failed again, so it is looked at again
            again = open_analyst(
                pack,
                "ci",
                ticket,
                repos=[repo],
                sha=f"{key} attempt {run.get('run_attempt')}",
                body=AGAIN.format(attempt=run.get("run_attempt")) + body,
            )
            _announce(pack, ticket, sha, "failed")
            return again
        if not live and cards:
            return sorted(cards)[0]  # its verdict stands: the attempt is handled by that finished card
        if live:  # the open diagnosis hears about the attempt that failed again
            writes = BoardWrites(pack["board"])
            writes.comment(
                live[0],
                "cockpit",
                f"{run.get('name')} failed again: attempt {run.get('run_attempt') or 1} of run {run['id']}. {run.get('html_url') or ''}",
            )
            writes.flush()
    return open_analyst(pack, "ci", ticket, repos=[repo], sha=key, body=body)


def _announce(pack, ticket: str, sha: str, what: str) -> bool:
    """Notify the pack's ci_<what>. False when the notify command failed: the next pass tries again (the ledger keeps a
    sent one from going twice)."""
    from .notify import notify

    return bool(
        notify(pack, f"ci_{what}", f"{ticket}@{sha}", f"{ticket}: CI is {what} on {sha[:9]}\n", ticket=ticket, sha=sha)[
            "ok"
        ]
    )


def _newest(watched, records) -> dict:
    """The newest watched commit of each (repo, branch), by when the watch first saw it: a rerun matters on a branch's head."""
    best = {}
    for _ticket, repo, sha, branch in watched:
        seen = _epoch(records[(repo, sha)].get("first_seen"), float("inf"))
        if (repo, branch) not in best or seen >= best[(repo, branch)][0]:
            best[(repo, branch)] = (seen, sha)
    return {key: sha for key, (_seen, sha) in best.items()}


def _runs(forge, repo: str, sha: str, path: str, checks):
    """The commit's runs from the forge, or None when they are the same as at the last read (a conditional read)."""
    if not _conditional(forge):
        checks.mark(path)
        return forge.runs(repo, sha)
    found = forge.runs_if_changed(repo, sha, checks.get(path).get("etag") or "")
    checks.mark(path, found["etag"])
    return found["runs"] if found["changed"] else None


def _conditional(forge) -> bool:
    """The forge answers "unchanged since" for free."""
    from .forges.base import CONDITIONAL_READS

    return CONDITIONAL_READS in forge.capabilities()


def watch(pack, now=None) -> dict:
    """One pass over every watched commit. {failed, cards, green, errors}."""
    from .forges import seam
    from .publish import forge_for

    forge = seam(forge_for(pack))
    moment = time.time() if now is None else now
    failing = failed_states(pack)
    done = {"failed": [], "cards": [], "green": [], "errors": [], "none": []}
    checks = Checks("ci")
    watched = commits(pack)
    records = {(repo, sha): _read(record_path(ticket, repo, sha)) for ticket, repo, sha, _branch in watched}
    newest = _newest(watched, records)
    for ticket, repo, sha, branch in watched:
        path = record_path(ticket, repo, sha)
        record = records[(repo, sha)] or {
            "ticket": ticket,
            "repo": repo,
            "sha": sha,
            "branch": branch,
            "first_seen": moment,
            "cards": {},
            "announced": [],
            "runs": [],
        }
        if record.get("dismissed") or _dismissed(ticket, repo, sha):
            continue
        # a failed branch head is asked every pass when the forge can answer "unchanged" for free: a rerun shows at once
        hot = record.get("state") == "failed" and newest.get((repo, branch)) == sha and _conditional(forge)
        if record.get("settled") and not hot:
            # a settled commit is read again every `hours.ci_reread_minutes` (a run started by hand on the forge is a new
            # attempt); without the setting a failed one is read every FAILED_REREAD_MINUTES and a green one not again
            again = ((pack or {}).get("hours") or {}).get("ci_reread_minutes") or (
                FAILED_REREAD_MINUTES if record.get("state") == "failed" else None
            )
            if not again or moment - checks.at(path, record) < float(again) * 60:
                continue
        try:
            listed = _runs(forge, repo, sha, path, checks)
        except CockpitError as exc:
            done["errors"].append(f"{forge.repo(repo)}: {exc}")
            continue
        if listed is None and record.get("settled"):
            continue  # nothing new on a settled commit: no write, no card, no notice
        runs = (
            (record.get("runs") or []) if listed is None else listed
        )  # unchanged runs: the clocks below still move on
        previous = {run.get("id"): run for run in record.get("runs") or []}
        record["runs"] = []
        for run in runs:
            seen = previous.get(run["id"]) or {}
            # it failed before when the last read saw it fail, or when one of its attempts has a card: a rerun seen while it
            # was going (no conclusion yet) still passes after a failure
            failed_before = seen.get("conclusion") in failing or any(
                key.startswith(f"{run['id']}-") for key in record.get("cards") or {}
            )
            row = {
                "id": run["id"],
                "name": run.get("name"),
                "status": run.get("status"),
                "conclusion": run.get("conclusion"),
                "run_attempt": run.get("run_attempt") or 1,
                "html_url": run.get("html_url") or "",
                "passed_after_rerun": seen.get("passed_after_rerun")
                or (failed_before and run.get("conclusion") in PASSED),
            }
            record["runs"].append(row)
        record["last_check"] = iso()
        if not runs:
            if moment - _epoch(record.get("first_seen"), moment) >= _minutes(pack, "no_ci_minutes", NO_CI_MINUTES) * 60:
                record.update(state="none", settled=True, summary="no CI picked this commit up")
                done["none"].append(sha)
            else:
                record["state"] = "waiting"
            _write(path, record)
            continue
        failures = [run for run in runs if run.get("status") == "completed" and run.get("conclusion") in failing]
        running = [run for run in runs if run.get("status") != "completed"]
        for run in failures:
            key = f"{run['id']}-{run.get('run_attempt') or 1}"
            if key in record["cards"]:
                continue
            card = _card(pack, ticket, repo, sha, branch, run, forge)
            record["cards"][key] = card
            done["cards"].append(card)
            if "failed" not in record["announced"] and _announce(
                pack, ticket, sha, "failed"
            ):  # the pack's notify.ci_failed
                record["announced"].append("failed")
        if failures:
            record.update(state="failed", summary=", ".join(sorted({str(run.get("name")) for run in failures})))
            done["failed"].append({"ticket": ticket, "sha": sha})
            if running:  # a rerun under way: the commit is watched every pass again until it ends
                record["completed_at"] = None
                record.pop("settled", None)
            else:
                # every run has finished and each failure has its card: the commit settles like a green one does, so it
                # is not read (and its record rewritten) on every pass
                if not record.get("completed_at"):
                    record["completed_at"] = moment
                if moment - float(record["completed_at"]) >= _minutes(pack, "ci_settle_minutes", SETTLE_MINUTES) * 60:
                    record["settled"] = True
        elif running:
            record.update(state="running", summary=f"{len(running)} run(s) still going", completed_at=None)
            record.pop("settled", None)
        else:
            record["state"] = "success"
            record["summary"] = "every run passed"
            if not record.get("completed_at"):
                record["completed_at"] = moment
            if moment - float(record["completed_at"]) >= _minutes(pack, "ci_settle_minutes", SETTLE_MINUTES) * 60:
                if "green" not in record["announced"] and _announce(pack, ticket, sha, "green"):
                    record["announced"].append("green")
                    done["green"].append(sha)
                record["settled"] = True
        _write(path, record)
    checks.save()
    return done


def state_for(ticket: str, repo: str, sha: str, pack=None) -> dict:
    """What the Inbox shows for a commit: the record, whether a card is analysing it, and whether it was handled."""
    if not (ticket and repo and sha):
        return {}
    path = record_path(ticket, repo, sha)
    record = with_checked("ci", path, _read(path))
    if not record:
        return {}
    statuses = {}
    if pack is not None and record.get("cards"):
        from .kanban import board_cards

        known = {card["id"]: card["status"] for card in board_cards(pack["board"], pack)}
        statuses = {card: known.get(card, "") for card in record["cards"].values()}
    finished = ("done", "archived")
    # no card ("" : a halted ticket, nothing could be made) is not handled: its row stays for the human
    handled = bool(record.get("dismissed")) or (
        bool(statuses) and all(status in finished for status in statuses.values())
    )
    analysing = any(status and status not in finished for status in statuses.values())
    return {
        **{
            key: record.get(key)
            for key in ("state", "summary", "sha", "branch", "last_check", "runs", "cards", "dismissed", "repo")
        },
        "sha": sha[:12],
        "handled": handled,
        "analysing": analysing,
        "card_status": statuses,
    }


def dismiss(pack, ticket: str, repo: str, sha: str) -> dict:
    """The human looked at a failure and will not act on it: its commit is not read again and leaves the Inbox."""
    if not ticket or not repo or not sha:
        raise CockpitError("bad repo/sha")
    from .paths import platform_dir

    path = os.path.join(platform_dir(), "ci-dismissed.json")
    record = _read(path)
    record.setdefault("items", []).append({"ticket": ticket, "repo": repo, "sha": sha, "time": iso()})
    _write(path, record)
    marked = []
    for found in _records(_folder(ticket)):
        full = os.path.join(_folder(ticket), found)
        data = _read(full)
        if data.get("repo") == repo and str(data.get("sha", "")).startswith(sha):
            data["dismissed"] = True
            _write(full, data)
            marked.append(found)
    return {"ok": True, "ticket": ticket, "sha": sha, "records": marked}


def rearm(ticket: str, repo: str, run_id) -> str:
    """A rerun was published: the commit whose run it is is read again."""
    for name in _records(_folder(ticket)):
        path = os.path.join(_folder(ticket), name)
        record = _read(path)
        if record.get("repo") == repo and any(str(run.get("id")) == str(run_id) for run in record.get("runs") or []):
            record.update(settled=False, state="running", completed_at=None)
            record.setdefault("reruns", []).append({"run": run_id, "time": iso()})
            _write(path, record)
            return name
    return ""


def forget(ticket: str, sha: str) -> dict:
    """Drop a commit's record: the next pass starts it again."""
    removed = []
    for name in _records(_folder(ticket)):
        if re.search(rf"-{re.escape(sha[:12])}", name):
            os.remove(os.path.join(_folder(ticket), name))
            removed.append(name)
    return {"ok": True, "ticket": ticket, "sha": sha, "removed": removed}


def _epoch(value, default: float) -> float:
    """A record's time: a number, or the ISO date an older record kept."""
    if value in (None, ""):
        return float(default)
    try:
        return float(value)
    except (TypeError, ValueError):
        return _stamp(value)


_stamp = stamp
