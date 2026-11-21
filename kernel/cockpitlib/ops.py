# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Commands the page and the watchers run. Each one writes its record."""

import datetime
import json
import os
import time

from .intents import all_intents
from .pack import forge_org
from .paths import platform_dir, qa_of, watch_dir
from .store import dump_json, write_text
from .worktree import add, list_worktrees, repo_source


def _write(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if isinstance(data, str):
        write_text(path, data)
        return
    dump_json(path, data)


def _health(name, detail):
    record = {
        "name": name,
        "ok": True,
        "last_run": int(time.time()),
        "last_ok": int(time.time()),
        "detail": detail,
        "summary": "ok",
        "fails": 0,
    }
    _write(os.path.join(watch_dir(), f"{name}.json"), record)
    return record


def record_crash(name: str) -> None:
    """A watcher that raised is a red row. The sentence is plain. The traceback stays behind it."""
    import traceback

    record = _health_hold(name, "the watcher crashed")
    record["trace"] = True
    record["output"] = traceback.format_exc()
    _write(os.path.join(watch_dir(), f"{name}.json"), record)


def _health_hold(name, detail):
    """A watcher that ran and refused its act. The Inbox shows it as a fix watcher until the next ok run."""
    path = os.path.join(watch_dir(), f"{name}.json")
    previous = _read_json(path)
    now = int(time.time())
    record = {
        "name": name,
        "ok": False,
        "last_run": now,
        "last_error": now,
        "last_ok": previous.get("last_ok"),
        "detail": detail,
        "summary": detail,
        "output": detail,
        "fails": int(previous.get("fails") or 0) + 1,
    }
    _write(path, record)
    return record


def _repos(pack):
    return [repo for repo in pack["repos"]["repos"] if repo.get("name")]


def watch_pr(pack=None, now=None):
    """The PR watch (cockpitlib.pr_watch), and the tickets that ended without a PR acknowledged."""
    from .acts import acknowledge_closed
    from .pack import load
    from .paths import pack_path
    from .pr_watch import SpecUnreadable, watch

    if pack is None:
        pack = load(pack_path())
    try:
        done = watch(pack, now=now)
    except SpecUnreadable as exc:  # no pass ran: health says why, and the next pass runs once the file reads
        _health_hold("pr-watch", f"pr-watch did not run: {exc}")
        return f"pr-watch did not run: {exc}"
    done["acknowledged"] = acknowledge_closed(pack)
    _write(os.path.join(platform_dir(), "pr-watch.json"), done)
    if done["errors"]:
        return _finish("pr-watch", "forge " + "; ".join(done["errors"]))
    return _finish("pr-watch", f"pr-watch {len(done['rows'])}")


def watch_ci(pack=None, now=None):
    """The CI watch (cockpitlib.ci_watch), then housekeeping, which the same cron runs."""
    from .ci_watch import watch

    done = watch(pack, now=now)
    _write(os.path.join(platform_dir(), "ci-watch.json"), done)
    from .housekeeping import run as house

    house(pack)
    record = _read_json(os.path.join(watch_dir(), "housekeeping.json"))
    house_failed = record.get("summary") or "housekeeping failed" if record.get("ok") is False else ""
    if done["errors"] or house_failed:
        detail = "; ".join(
            ([f"forge {'; '.join(done['errors'])}"] if done["errors"] else [])
            + ([house_failed] if house_failed else [])
        )
        _health_hold("ci-watch", detail)
        return detail
    detail = f"{len(done['failed'])} failures" + (
        f" announced {' '.join(sha[:9] for sha in done['green'])}" if done["green"] else ""
    )
    _health("ci-watch", detail)
    return f"ci-watch {len(done['failed'])}"


def _once(action, pack=None):
    """A timeout or a 5xx gets one more try, after the pack's hours.retry_seconds (default at once). Any other result is
    returned as it is."""
    from .health import transient

    message = action()
    if transient(str(message)):
        import time as _time

        _time.sleep(float(((pack or {}).get("hours") or {}).get("retry_seconds") or 0))
        return action()
    return message


def _finish(name, message) -> str:
    from .health import transient

    if str(message).startswith("forge ") or transient(str(message)):
        _health_hold(name, message)
        return message
    _health(name, message)
    return message


def watch_base(pack):
    from .acts import scan_base

    return _finish("base-watch", _once(lambda: scan_base(pack), pack))


def bumps_scan(pack):
    from .acts import scan_bumps

    return _finish("bumps", _once(lambda: scan_bumps(pack), pack))


def advisories_scan(pack, fetch=None) -> str:
    """The stack watch: off without the pack's advisories block; red only when every source failed. A new alert is
    announced once (notify.advisory)."""
    from .advisories.scan import config, run
    from .notify import notify

    if not config(pack):
        _health("advisories", "off: the pack has no advisories block")
        return "off: the pack has no advisories block"
    result = run(pack, fetch=fetch)
    output = result["output"]
    for line in result["new"]:
        notify(pack, "advisory", line.split(":", 1)[0].replace("NEW ALERT ", ""), line + "\n", ticket="")
    sources = output["sources"]
    failed = [f"{name}: {row['error']}" for name, row in sources.items() if not row["ok"]]
    message = (
        f"advisories {len(output['advisories'])} · alerts {sum(1 for row in output['advisories'] if row['alert'])} · "
        f"sources ok {len(sources) - len(failed)} of {len(sources)}"
        + (f" · failed {'; '.join(failed)}" if failed else "")
    )
    if result["failed"]:
        _health_hold("advisories", "every advisory source failed: " + "; ".join(failed))
        return message
    _health("advisories", message)
    return message


def _stamp(text: str):
    """An ISO moment named in the text. None when the text has no moment."""
    import datetime
    import re

    match = re.search(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:Z|[+-]\d{2}:\d{2})", str(text or ""))
    if not match:
        return None
    return datetime.datetime.fromisoformat(match.group(0).replace("Z", "+00:00"))


def _since(moment, start) -> bool:
    if moment is None:
        return False
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=datetime.UTC)
    return moment.astimezone() >= start.astimezone()


def _standup_sent() -> dict:
    return _read_json(os.path.join(platform_dir(), "standup-sent.json"))


def standup_draft(pack, after_send: str = "refuse"):
    """The note since the window opened: what was tested, developed, reviewed, bumped, created and closed, and what
    waits on colleagues (standup_note). Once this window's note went out a new draft is refused, or, for the cron
    (after_send="skip"), not made."""
    import time as _time

    from .errors import CockpitError
    from .setup import standup_enabled
    from .standup_note import draft
    from .window import pack_standup, window_start

    if not standup_enabled(pack):
        if after_send == "skip":
            return "the standup note is off (standup_enabled: false)"
        raise CockpitError("the standup note is off for this pack (standup_enabled: false)")
    hour, days, minute = pack_standup(pack)
    start = window_start(hour=hour, working=days, minute=minute)
    day = start.date().isoformat()
    sent = _standup_sent()
    # A note sent on the day its window opened (an afternoon send, hours into the window) is not the next morning's
    # standup: the morning's draft covers the whole window and is made. Read as "already sent", the morning after
    # would have no note at all.
    if sent.get("day") == day and str(sent.get("sent_on") or _time.strftime("%Y-%m-%d")) == _time.strftime("%Y-%m-%d"):
        if after_send == "skip":
            _health("standup", f"sent for {day}")
            return f"standup for {day} already sent"
        raise CockpitError(f"the standup for {day} was already sent")
    now = _time.time()
    built = draft(pack, start.timestamp(), now)
    folder = platform_dir()
    os.makedirs(folder, exist_ok=True)
    write_text(os.path.join(folder, "standup.md"), built["markdown"])
    from .standup_note import chat_file

    write_text(os.path.join(folder, chat_file(pack)), built["slack"])
    import datetime as _datetime

    _write(
        os.path.join(folder, "standup.json"),
        {
            "day": _datetime.date.fromtimestamp(now).isoformat(),
            "since": built["since"],
            "until": built["until"],
            "items": built["items"],
            "drafted_at": _datetime.datetime.fromtimestamp(now).astimezone().isoformat(timespec="minutes"),
            "titles": built["titles"],
            "waiting": built["waiting"],
        },
    )
    _health("standup", f"draft: {built['items']} item(s)")
    return f"standup draft: {built['items']} item(s) since {built['since']}"


def vault_put(pack, origin, email, password="", otp=None, lane=""):
    """The credentials form: a login for its owning lane, or for the seats a shared login names."""
    from .vault import store_login

    return store_login(origin, email, password, forge_org(pack) or "", otp=otp, lane=lane, pack=pack)


def session_open(pack, slot, ticket):
    from .acts import session_open as open_session

    return open_session(pack, slot, ticket)


def worktree_add(pack, ticket, repo="", branch_from=""):
    from .halt import refuse

    refuse(ticket)
    names = [repo] if repo else [item["name"] for item in _repos(pack)]
    made = []
    root = os.environ.get("COCKPIT_ROOT") or os.path.dirname(pack["_dir"])
    for name in names:
        source = ""
        setup = {}
        for item in _repos(pack):
            if item["name"] == name:
                setup = item
                source = item.get("path") or ""
                if source and not os.path.isabs(source):
                    beside = os.path.join(root, source)
                    # a pack kept inside the records folder (<workspace>/hermes/pack) is not beside the repos: the
                    # folder above it is the records folder, where no repo is ("no repo at <workspace>/hermes/<repo>").
                    # Every other reader takes a relative repo path from the root (repo_source), so that is where it
                    # is looked for next.
                    source = beside if os.path.exists(os.path.join(beside, ".git")) else repo_source(pack, name)
        if source:
            made.append(
                add(
                    ticket,
                    name,
                    pack.get("branch_prefix") or "work",
                    source,
                    branch_from=branch_from,
                    base=setup.get("base") or pack.get("base_branch") or "",
                    setup=setup,
                )
            )
    return made or list_worktrees(ticket)


def ide_open(pack, ticket, file: str = "", worktrees=None):
    """Record the request (platform/ide-<ticket>.json) and run the pack's IDE command when it names one."""
    record = {"ticket": ticket, "org": forge_org(pack), "repos": [repo["name"] for repo in _repos(pack)]}
    if worktrees is not None:
        record["worktrees"] = list(worktrees)
    if file:
        record["file"] = str(file)
    path = os.path.join(platform_dir(), f"ide-{ticket or 'own'}.json")
    _write(path, record)
    launched = ide_launch(pack, "file_command" if file and not ticket else "command", ticket=ticket, path=file)
    return launched or path


def ide_argv(pack, key: str, **fields) -> list:
    """The pack's ide.<key> with {ticket}, {path}, {workspace} and {root} filled in; a relative first word is a
    file in the pack folder. Empty when the pack names none."""
    from .paths import root, workspace

    argv = ((pack.get("ide") or {}).get(key)) or []
    if not argv:
        return []
    values = {
        "ticket": fields.get("ticket") or "",
        "path": fields.get("path") or "",
        "workspace": workspace(),
        "root": root(),
    }
    out = []
    for part in argv:
        text = part
        for name, value in values.items():
            text = text.replace("{" + name + "}", str(value))
        out.append(text)
    first = out[0]
    if not os.path.isabs(first) and os.sep in first:
        out[0] = os.path.join(pack.get("_dir") or "", first)
    return out


def ide_launch(pack, key: str, **fields) -> str:
    """Start the IDE command detached. The command line when it started, empty when the pack names none."""
    import subprocess

    from .paths import workspace

    argv = ide_argv(pack, key, **fields)
    if not argv:
        return ""
    try:
        subprocess.Popen(
            argv,
            cwd=workspace(),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except OSError as exc:
        from .errors import CockpitError

        raise CockpitError(f"ide.{key} did not start: {exc}") from exc
    return " ".join(argv)


def map_build(pack):
    from .map_build import MISSING, compiled_tree, summary

    path = os.path.join(platform_dir(), "map.json")
    record = _read_json(path)
    tree = compiled_tree(pack)
    message = MISSING
    if tree is not None:
        message = summary(tree)
    record["root"] = pack["name"]
    record["map"] = tree or {"nodes": [], "built": None, "repos": []}
    record["base"] = pack.get("base_branch") or "main"
    if not isinstance(record.get("counts"), dict):
        record["counts"] = {}
    if not isinstance(record.get("inherited"), dict):
        record["inherited"] = {}
    if not isinstance(record.get("changes"), list):
        record["changes"] = []
    if not isinstance(record.get("state"), dict):
        record["state"] = {}
    _write(path, record)
    return message


def _read_json(path):
    if not os.path.isfile(path):
        return {}
    try:
        data = json.load(open(path, encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    if not isinstance(data, dict):
        return {}
    return data


def workspace_watch(pack):
    from .kanban import OPEN_STATUSES, board_cards
    from .state_commit import state_commit as commit_state
    from .tracker import titles

    titles(
        pack,
        sorted(
            {
                card["ticket"]
                for card in board_cards(pack["board"])
                if card.get("ticket") and card.get("status") in OPEN_STATUSES
            }
        ),
        refresh=True,
    )
    message = commit_state(pack)
    if message.startswith("HOLD "):
        text = message[5:]
        _health_hold("workspace-watch", text)
        return text
    _health("workspace-watch", message)
    return message


def state_commit(pack):
    return workspace_watch(pack)


def require_record(name, path, message) -> str:
    """A script that exits 0 without its expected record is a failure."""
    if not os.path.isfile(path):
        _health_hold(name, "exit 0 with no record")
        return "failed"
    _health(name, message)
    return message


def with_retry(action):
    """A weekly job retries once on a timeout or a 5xx. The second result is returned as it is."""
    import subprocess

    from .health import should_retry, transient

    try:
        message = action()
    except (OSError, subprocess.TimeoutExpired) as exc:
        if not should_retry(str(exc), 0):
            raise
        return action()
    if transient(str(message)):
        return action()
    return message


def morning_digest(pack) -> str:
    """One screen: pending outbox, blocked cards, and the review column."""
    from .kanban import board_cards

    pending = [
        row for row in all_intents() if row.get("status") in ("pending", "endorsed", "held", "returned", "posted")
    ]
    cards = board_cards(pack["board"])
    blocked = [card for card in cards if card.get("status") == "blocked"]
    review = [card for card in cards if card.get("status") == "review"]
    lines = [
        f"# Digest {pack['name']}",
        "",
        f"Pending outbox: {len(pending)}",
        f"Blocked: {len(blocked)}",
        f"Review: {len(review)}",
        "",
    ]
    for card in blocked[:8]:
        lines.append(f"- blocked {card.get('ticket') or ''} {card.get('title') or ''}".rstrip())
    for card in review[:8]:
        lines.append(f"- review {card.get('ticket') or ''} {card.get('title') or ''}".rstrip())
    for row in pending[:8]:
        lines.append(f"- outbox {row.get('ticket') or ''} {row.get('type') or ''} {row.get('status') or ''}".rstrip())
    requested, replies = _review_news(pack)
    if requested:
        lines += ["", f"Review requested: {len(requested)}", *requested[:8]]
    if replies:
        lines += ["", f"Replies in your threads: {len(replies)}", *replies[:8]]
    path = os.path.join(platform_dir(), "digest.md")
    _write(path, "\n".join(lines).rstrip() + "\n")
    return require_record("morning-digest", path, "digest")


def _review_news(pack) -> tuple:
    """(PRs that ask the human for a review, replies others wrote in the human's threads). A forge that does not answer
    leaves the first list empty; the digest still goes out."""
    from .errors import CockpitError
    from .forges import seam
    from .publish import forge_for

    forge = seam(forge_for(pack))
    requested = []
    try:
        for item in forge.review_requests():
            requested.append(f"- review {item['repo']}#{item['number']} {item['title']}".rstrip())
    except CockpitError:
        requested = []
    replies = []
    from .paths import qa
    from .pr_watch import prs_of

    for ticket in sorted(os.listdir(qa())) if os.path.isdir(qa()) else []:
        for pr in prs_of(ticket):
            for reply in pr.get("replies") or []:
                replies.append(
                    f"- reply {pr['repo']}#{pr['number']} by {reply.get('author')}: {str(reply.get('body') or '')[:80]}"
                )
    return requested, replies


def _approvals() -> list:
    from .paths import qa

    found = []
    root = qa()
    if not os.path.isdir(root):
        return found
    for ticket in sorted(os.listdir(root)):
        folder = qa_of(ticket, "pr")
        if not os.path.isdir(folder):
            continue
        for name in sorted(os.listdir(folder)):
            if not name.endswith(".json"):
                continue
            record = _read_json(os.path.join(folder, name))
            sha = str(record.get("reviewed_sha") or "")
            if not sha:
                continue
            found.append(
                {
                    "ticket": ticket,
                    "repo": record.get("repo") or "",
                    "number": record.get("number") or 0,
                    "sha": sha,
                }
            )
    return found


def perf_sync(pack) -> str:
    """Tracker writes, pull requests, and approvals already on this machine."""
    tracker = []
    pull_requests = []
    for row in all_intents():
        payload = row.get("payload") or {}
        kind = str(row.get("type") or "")
        if kind.startswith("tracker-"):
            tracker.append({"ticket": row.get("ticket") or "", "type": kind})
        if kind == "open-pr":
            pull_requests.append(
                {
                    "ticket": row.get("ticket") or "",
                    "repo": payload.get("repo") or "",
                    "number": payload.get("number") or 0,
                }
            )
    path = os.path.join(platform_dir(), "perf.json")
    _write(
        path,
        {
            "name": pack["name"],
            "tracker": tracker[:20],
            "pull_requests": pull_requests[:20],
            "approvals": _approvals()[:20],
        },
    )
    command = ((pack.get("perf") or {}).get("command")) or []
    if command:
        failed = _pack_command(pack, command, path)
        if failed:
            _health_hold("perf-sync", f"perf command failed: {failed}")
            return "perf"
    return require_record("perf-sync", path, "perf")


def _pack_command(pack, argv, record_path="") -> str:
    """Run one of the pack's commands ({records} and {record} filled; a relative program is beside pack.yaml). The
    reason it failed, or empty."""
    import subprocess

    from .paths import records

    words = [str(word).replace("{records}", records()).replace("{record}", record_path) for word in argv]
    if "/" in words[0] and not os.path.isabs(words[0]):
        words[0] = os.path.join(pack["_dir"], words[0])
    try:
        done = subprocess.run(words, capture_output=True, text=True, check=False, timeout=600)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return str(exc)
    if done.returncode != 0:
        return ((done.stderr or done.stdout).strip().splitlines()[-1:] or [f"exit {done.returncode}"])[0]
    return ""


def export_keep(pack, keep=None):
    from .vault import backup_vault, needs_seal

    keep = keep if keep is not None else int(((pack.get("export") or {}).get("keep")) or 4)

    def go():
        record = {"keep": keep, "name": pack["name"], "org": forge_org(pack)}
        _write(os.path.join(platform_dir(), "export.json"), record)
        return backup_vault(keep)

    import subprocess

    try:
        copied = with_retry(go)
    except (OSError, subprocess.TimeoutExpired) as exc:
        _health_hold("export", str(exc))
        return "export"
    from .health import transient

    if transient(str(copied)):
        _health_hold("export", str(copied))
        return "export"
    if needs_seal():
        _health_hold("export", "vault key not sealed")
        return "export"
    if str(copied).strip() == "vault backup 0":
        _health_hold("export", "exit 0 with no record")
        return "failed"
    failures = []
    for argv in ((pack.get("export") or {}).get("commands")) or []:
        failed = _pack_command(pack, argv)
        if failed:
            failures.append(f"{os.path.basename(argv[0])}: {failed}")
    if failures:
        _health_hold("export", "export commands failed: " + "; ".join(failures))
        return "export"
    _health("export", f"keep {keep}")
    return "export"


def slot_gc(pack):
    from .slots import provider_for

    provider = provider_for(pack.get("slot_provider"), pack)
    idle = (pack.get("slots") or {}).get("idle_minutes")
    collected = provider.gc(60 if idle is None else idle, max(1, pack["seats"]["slots"]))
    from . import record

    try:
        record.sweep(pack)  # recorders of ended cards, frames older than a day
    except OSError:
        pass
    _health("slot-gc", f"{len(collected)} collected")
    return f"slot-gc {len(collected)}"
