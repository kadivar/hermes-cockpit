# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Intent types, status table, and files. The registry is the source of truth."""

import contextlib
import functools
import json
import os
import re

from .errors import CockpitError, Conflict, UsageError
from .paths import outbox, outbox_of
from .store import claim, locked, log, read_json, refuse_claimed, unclaim, write_bytes, write_json

TYPES = [
    "push-branch",
    "open-pr",
    "pr-edit",
    "pr-patch-apply",
    "pr-comment",
    "pr-review-submit",
    "tracker-comment",
    "tracker-create",
    "tracker-transition",
    "infra-note",
    "ci-rerun",
    "ticket-done",
]
ORDER = {
    name: index
    for index, name in enumerate(
        [
            "push-branch",
            "pr-edit",
            "open-pr",
            "pr-patch-apply",
            "pr-comment",
            "pr-review-submit",
            "tracker-create",
            "tracker-comment",
            "tracker-transition",
            "ci-rerun",
            "infra-note",
            "ticket-done",
        ]
    )
}
MANUAL_TYPES = ("infra-note", "ticket-done")
PUSHES = ("push-branch", "pr-patch-apply")
OPEN_STATUSES = ("pending", "endorsed", "held", "returned", "posted")
PUBLISHED = ("published", "published-manually")
TRANSITIONS = {
    "pending": {"endorsed", "held", "returned", "dropped", "pending", "published-manually", "acknowledged", "reopened"},
    "endorsed": {"published", "posted", "returned", "held", "dropped", "pending", "published-manually"},
    "held": {"pending", "endorsed", "returned", "dropped", "held"},
    "returned": {"pending", "endorsed", "dropped", "returned"},
    "posted": {"published", "endorsed"},
    "published": {"endorsed", "pending"},
    "published-manually": {"endorsed", "pending"},
    "acknowledged": {"reopened"},
    "reopened": set(),
    "dropped": {"pending"},
}
# Each payload field an intent may carry, by the shape a flag gives it. Files are copied beside the intent.
FIELDS = {
    "repo": "text",
    "branch": "text",
    "publish_as": "text",
    "head": "text",
    "sha": "text",
    "base": "text",
    "title": "text",
    "number": "int",
    "issue": "text",
    "event": "event",
    "to": "text",
    "workflow": "text",
    "run_id": "int",
    "project": "text",
    "in_reply_to": "int",
    "thread": "text",
    "comment_id": "text",
    "comment_from": "intent",
    "probe_title": "text",
    "review_id": "int",
    "title_append": "text",
    "assignee": "text",
    "component": "text",
    "sprint": "text",
    "transition": "text",
    "issue_from": "intent",
    "issue_type": "text",
    "summary": "text",
    "labels": "list",
    "add_labels": "list",
    "remove_labels": "list",
    "related": "list",
    "body": "text",
    "body_file": "file",
    "threads_file": "file",
    "patch_file": "file",
    "patch_comments": "file",
    "review_body_update": "file",
    "attach": "files",
    "after": "intent",
    "rebase_only": "bool",
    "react": "bool",
    "resolve": "bool",
    "ready": "bool",
    "url": "text",
    "merged_at": "text",
    "waits_for": "intent",
    "numbers": "list",
    "run": "text",
}
EVENTS = ("REQUEST_CHANGES", "COMMENT", "APPROVE")
# type: (required fields, optional fields, one of these must be given). A body is a file, or inline text from cockpit itself.
SCHEMAS = {
    "push-branch": (("repo", "branch"), ("publish_as", "sha", "base", "rebase_only", "after"), ()),
    "open-pr": (
        ("repo", "title"),
        ("branch", "publish_as", "head", "base", "body", "body_file", "labels", "related", "after", "ready", "sha"),
        ("branch", "head", "publish_as"),
    ),
    "pr-edit": (
        ("repo", "number"),
        (
            "base",
            "title",
            "title_append",
            "body",
            "body_file",
            "labels",
            "add_labels",
            "remove_labels",
            "assignee",
            "after",
            "sha",
            "ready",
            "issue_from",
        ),
        (
            "base",
            "title",
            "title_append",
            "body",
            "body_file",
            "labels",
            "add_labels",
            "remove_labels",
            "assignee",
            "ready",
        ),
    ),
    "pr-patch-apply": (("repo", "number", "branch", "threads_file"), ("publish_as", "sha", "base"), ()),
    "pr-comment": (
        ("repo", "number"),
        ("body", "body_file", "in_reply_to", "thread", "react", "resolve", "after", "sha"),
        (),
    ),
    "pr-review-submit": (
        ("repo", "number", "sha"),
        ("event", "body", "body_file", "threads_file", "review_id", "patch_comments", "review_body_update", "after"),
        (),
    ),
    "tracker-comment": (
        (),
        ("issue", "body", "body_file", "comment_id", "comment_from", "probe_title", "attach", "run"),
        ("body", "body_file"),
    ),
    "tracker-create": (
        ("summary",),
        ("project", "issue_type", "body", "body_file", "labels", "component", "sprint", "assignee", "transition"),
        (),
    ),
    "tracker-transition": (("to",), ("issue", "issue_from", "assignee", "after"), ()),
    # with repo, branch and patch_file the note is a change the human applies (cockpitlib.infra_note)
    "infra-note": ((), ("repo", "body", "body_file", "branch", "patch_file", "number"), ()),
    "ci-rerun": (("repo", "run_id"), ("workflow", "sha"), ()),
    "ticket-done": ((), ("repo", "number", "merged_at", "url", "numbers"), ()),
}
EXAMPLES = {
    "push-branch": "--repo api --branch work/TASK-1",
    "open-pr": "--repo api --branch work/TASK-1 --title 'TASK-1: export' --body-file pr.md --labels 'needs review'",
    "pr-edit": "--repo api --number 12 --add-labels ready",
    "pr-patch-apply": "--repo api --number 12 --branch work/TASK-1 --threads-file plan.json",
    "pr-comment": "--repo api --number 12 --in-reply-to 4001 --thread PRRT_1 --body-file reply.md --resolve",
    "pr-review-submit": "--repo api --number 12 --sha <reviewed head> --threads-file review.json --body-file summary.md",
    "tracker-comment": "--issue TASK-1 --body-file run.md --attach evidence/row-1.mp4",
    "tracker-create": "--summary 'Bump the parser' --labels deps --transition 'In Progress'",
    "tracker-transition": "--issue TASK-1 --to 'In Review'",
    "infra-note": "--body-file note.md",
    "ci-rerun": "--repo api --run-id 42",
    "ticket-done": "",
}
ID_RE = re.compile(r"^[A-Z][A-Z0-9]*(?:-[A-Z0-9]+)+/[0-9]{3}-[a-z-]+$")
TICKET_RE = re.compile(r"^[A-Z][A-Z0-9]*(?:-[A-Z0-9]+)+$")
FILE_KEYS = ("body_file", "threads_file", "patch_file", "patch_comments", "review_body_update")


def is_intent_file(name: str) -> bool:
    return re.match(r"^\d{3}-(" + "|".join(TYPES) + r")\.json$", name) is not None


def path_of(iid: str) -> str:
    """The intent's file: <ticket>/<name>, each one path segment. An id that names another place is no intent."""
    from .errors import CockpitError
    from .paths import segment

    ticket, name = iid.split("/", 1)
    try:
        return outbox_of(segment(ticket), segment(name) + ".json")
    except CockpitError as exc:
        raise FileNotFoundError(f"no intent {iid}") from exc


class Intent(dict):
    """An intent as its file said it. The bytes it was read from go with it (never into the file), so a save can tell
    a record that was changed underneath from the one that was decided on."""

    __slots__ = ("seen",)


def _raw(path: str):
    try:
        with open(path, "rb") as handle:
            return handle.read()
    except OSError:
        return None


def _read(path: str):
    """The record in a file with the bytes it came from, or None: a missing file, a number only reserved, not JSON."""
    raw = _raw(path)
    try:
        data = json.loads(raw.decode("utf-8")) if raw else None
    except json.JSONDecodeError:
        return None
    if isinstance(data, dict):
        data = Intent(data)
        data.seen = raw
    return data


def load(iid: str):
    data = _read(path_of(iid))
    if data is None:
        raise FileNotFoundError(f"no intent {iid}")
    return data


def _changed(iid: str, path: str) -> Conflict:
    now = (read_json(path) or {}).get("status") or "gone"
    return Conflict(
        f"{iid} was changed by someone else while this was being decided (it is {now} now): nothing was "
        "written, read it again and decide on what it says"
    )


def save(data) -> None:
    """The intent's file says this, written under the ticket's lock. An intent that was loaded is written only when
    its file still says what was loaded: one changed underneath is a Conflict and nothing is written, so no change is
    ever lost to a later writer. One being published by another process is not written under it."""
    iid = data["id"]
    path = path_of(iid)
    with locked(iid.split("/", 1)[0]):
        refuse_claimed(iid.split("/", 1)[0], iid)
        seen = getattr(data, "seen", None)
        if seen is not None and _raw(path) != seen:
            raise _changed(iid, path)
        written = write_json(path, data)
        if isinstance(data, Intent):
            data.seen = written


@contextlib.contextmanager
def publishing(intent):
    """The intent is this caller's while it goes out: claimed under the ticket's lock only if its file still says what
    the caller read, and no other process writes it or publishes it until the block ends. The lock itself is not held
    while the act runs."""
    iid = intent["id"]
    ticket = iid.split("/", 1)[0]
    with locked(ticket):
        seen = getattr(intent, "seen", None)
        if seen is not None and _raw(path_of(iid)) != seen:
            raise _changed(iid, path_of(iid))
        claim(ticket, iid)
    try:
        yield intent
    finally:
        unclaim(ticket, iid)


def claimed(execute):
    """A publisher that holds its intent's claim for as long as it runs. A dry run changes nothing and claims nothing."""
    import inspect

    shape = inspect.signature(execute)

    @functools.wraps(execute)
    def run(intent, *args, **kwargs):
        if shape.bind(intent, *args, **kwargs).arguments.get("dry_run"):
            return execute(intent, *args, **kwargs)
        with publishing(intent):
            return execute(intent, *args, **kwargs)

    return run


def settle(data) -> None:
    """The record of an act that has left: written whatever the file says now, because what went out went out. The
    publisher holds the intent's claim, so no other process wrote under it; a file that differs all the same is said in
    the receipt log, and the record says what left."""
    iid = data["id"]
    path = path_of(iid)
    with locked(iid.split("/", 1)[0]):
        seen = getattr(data, "seen", None)
        if seen is not None and _raw(path) != seen:
            log(f"OVERWRITE? {iid} changed underneath while it went out: the record says what left")
        written = write_json(path, data)
        if isinstance(data, Intent):
            data.seen = written


def all_intents(ticket=None):
    root = outbox()
    found = []
    if not os.path.isdir(root):
        return found
    for name in sorted(os.listdir(root)):
        if name.startswith("_"):
            continue
        if ticket and name != ticket:
            continue
        folder = outbox_of(name)
        if not os.path.isdir(folder):
            continue
        for filename in sorted(os.listdir(folder)):
            if is_intent_file(filename):
                record = _read(os.path.join(folder, filename))
                if record is not None:
                    found.append(record)
    return found


def can_move(status: str, to: str) -> bool:
    return to in TRANSITIONS.get(status, set())


def advance(data, to: str, actor: str = "") -> None:
    current = data.get("status")
    if not can_move(current, to):
        log(f"TRANSITION? {data.get('id')} {current} → {to}" + (f" by {actor}" if actor else ""))
    data["status"] = to


def next_seq(ticket: str) -> str:
    folder = outbox_of(ticket)
    highest = 0
    if os.path.isdir(folder):
        for filename in os.listdir(folder):
            match = re.match(r"^(\d{3})-", filename)
            if match:
                highest = max(highest, int(match.group(1)))
    if highest >= 999:
        raise CockpitError(f"{ticket}: intent sequence exhausted")
    return f"{highest + 1:03d}"


def reserve_seq(ticket: str, kind: str) -> str:
    """The next number of the ticket, taken: under the ticket's lock the intent's file is created empty and
    exclusively, so two creators never share a number however long each then takes to fill its own. An empty file is
    no intent to any reader."""
    with locked(ticket):
        seq = next_seq(ticket)
        os.makedirs(outbox_of(ticket), exist_ok=True)
        write_bytes(outbox_of(ticket, f"{seq}-{kind}.json"), b"", 0o600, exclusive=True)
    return seq


def release_seq(ticket: str, seq: str, kind: str) -> None:
    """A number that was reserved and never filled is given back: the empty file goes, a written intent stays."""
    path = outbox_of(ticket, f"{seq}-{kind}.json")
    with locked(ticket):
        try:
            if os.path.getsize(path) == 0:
                os.remove(path)
        except OSError:
            pass


def check_ticket(ticket: str, pattern: str) -> str:
    """The key, when it is a ticket key of the kernel's shape and of the pack's. The whole key is read: a trailing line
    break or anything that is not text is refused."""
    if not isinstance(ticket, str) or not TICKET_RE.fullmatch(ticket):
        raise CockpitError(f"bad ticket {ticket!r}")
    if pattern and not re.match(pattern, ticket):
        raise CockpitError(f"bad ticket {ticket!r}")
    return ticket


def ticket_folder(root: str, ticket: str, pack=None) -> str:
    """The ticket's folder under that root. The key is checked as the outbox checks it and the folder cannot lie
    outside the root: a path, a dot name or an empty key never names a folder to write or remove."""
    from .paths import inside

    return inside(root, check_ticket(ticket, (pack or {}).get("ticket_pattern")), what="ticket")


def check_payload(kind: str, payload) -> dict:
    """The payload this type takes, in its shapes. A missing or misshapen field is refused with an example."""
    if kind not in SCHEMAS:
        raise CockpitError(f"unknown type {kind}")
    required, optional, one_of = SCHEMAS[kind]
    optional = (*optional, "waits_for")  # any intent may be a stage of a sequence
    payload = dict(payload or {})
    example = f"cockpit outbox new <ticket> {kind} --card <card> --summary <text> {EXAMPLES[kind]}".rstrip()
    missing = [field for field in required if payload.get(field) in (None, "", [])]
    if missing:
        raise UsageError(f"{kind} needs --{missing[0].replace('_', '-')} (e.g. {example})")
    for field in [*required, *optional]:
        value = payload.get(field)
        if value in (None, ""):
            continue
        shape = FIELDS[field]
        if shape == "int":
            if not re.fullmatch(r"\d+", str(value)):
                raise UsageError(f"{kind} --{field.replace('_', '-')} is a number, not {value!r}")
            payload[field] = int(value)
        elif shape in ("list", "files"):
            items = value if isinstance(value, list) else [part.strip() for part in str(value).split(",")]
            payload[field] = [str(item).strip() for item in items if str(item).strip()]
        elif shape == "bool":
            payload[field] = bool(value)
        elif shape == "event":
            if str(value).upper() not in EVENTS:
                raise UsageError(f"--event is one of {', '.join(EVENTS)}, not {value}")
            payload[field] = str(value).upper()
        elif shape == "intent":
            if not ID_RE.match(str(value)):
                raise UsageError(
                    f"--{field.replace('_', '-')} names an intent like TASK-1/001-push-branch, not {value!r}"
                )
        else:
            payload[field] = str(value)
    if one_of and not any(payload.get(field) not in (None, "", []) for field in one_of):
        raise UsageError(
            f"{kind} needs one of {', '.join('--' + field.replace('_', '-') for field in one_of)} (e.g. {example})"
        )
    return payload


# Two ways one intent stands behind another:
#   after      a pair, one act: publishing it publishes the named intent first (a content push after its rebase-only push,
#              an open-pr after its branch push). The human clicks once.
#   waits_for  a sequence, one click per stage: it goes out only once the named intent is published. Until then it is
#              not offered for publishing and publish refuses it; each stage reaches the human when the one before is out.


def waiting_on(intent, loader=None):
    """The stage this intent still waits for, {id, type, status}, or None when it may go out. A missing or dropped stage
    before it counts as waiting: the sequence is broken and the human decides."""
    loader = loader or load
    wid = (intent.get("payload") or {}).get("waits_for")
    if not wid:
        return None
    try:
        earlier = loader(wid)
    except FileNotFoundError:
        return {"id": wid, "type": "?", "status": "missing"}
    if earlier.get("status") in PUBLISHED:
        return None
    return {"id": wid, "type": earlier.get("type"), "status": earlier.get("status")}


def waits_cycle(start: str, wid: str, loader=None) -> bool:
    """Naming `wid` as the stage before `start` would close a loop."""
    loader = loader or load
    seen = {start}
    while wid:
        if wid in seen:
            return True
        seen.add(wid)
        try:
            wid = (loader(wid).get("payload") or {}).get("waits_for")
        except FileNotFoundError:
            return False
    return False
