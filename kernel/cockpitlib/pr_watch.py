# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The pull-request watch: every PR a ticket's intents name, read from the forge as the human, one record per PR.

New comments are counted on a stable id per comment (conversation comments, inline review comments and reviews). The
human's own comments and the pack's bots are left out, unless a bot names one of the pack's mention tags. On a PR the
human wrote, new comments are an Inbox row and one message. On a PR the human reviews, a re-review card goes to a
reviewer once per head: after the human's threads are resolved, the head moved or the author asked again, and the PR
has been quiet. A PR quiet for too long is pinged once per head; a ticket whose PRs all merged and has nothing open
gets its ticket-done row.
"""

import json
import os
import re
import time

from . import pack_local
from .errors import CockpitError, PackError
from .intents import OPEN_STATUSES, all_intents
from .kanban import one_at_a_time
from .paths import qa_of
from .record_write import Checks, write_record
from .time_util import iso

QUIET_SECONDS = 2 * 3600
STALE_HOURS = 72
PRAISE = ("lgtm", "looks good", "nice", "thanks", "thank you")
# A comment asks for work only the team's way: a finding tag at the start of a line (one of the pack's finding_labels
# followed by a colon, bold or not, in a list or a quote) or a suggestion block. A pack that names no tags is asked for
# work by a suggestion block only. A verdict's own body without either is informational: "looks good to me", "a few
# questions there" point at the inline comments, which are counted on their own. An acknowledgement closes a thread.
SUGGESTION = re.compile(r"```suggestion\b")
ACK = re.compile(
    r"^\s*(`?@[\w-]+`?[,:]?\s*)?(thanks|thank you|thx|got it|acknowledged|noted|lgtm|resolved|sounds good|makes sense)\b|learnings added|<summary>.{0,10}learnings",
    re.I | re.S,
)
# The kinds of comment id a watch record holds. An earlier pipeline's own prefix for one is named by the pack
# (migrate.yaml's records.watch_id_prefixes) and read as that kind.
ID_KINDS = ("inline:", "issue:", "review:")
_PREFIXES = {}  # migrate.yaml path -> (its stamp, the mapping read from it)


class SpecUnreadable(CockpitError):
    """migrate.yaml is there and its watch id prefixes cannot be read: no pass may run as if there were none."""


def _prefix_map(given) -> bool:
    """True for a mapping of a prefix of letters to one of ID_KINDS."""
    return isinstance(given, dict) and all(
        isinstance(old, str) and old.isalpha() and ours in ID_KINDS for old, ours in given.items()
    )


def watch_id_prefixes(pack) -> tuple:
    """((prefix, this watch's prefix), …) for the comment ids an earlier pipeline wrote: migrate.yaml's
    records.watch_id_prefixes, none for a pack that names none. Read once per change of the file. A file that is there and
    cannot be read, or whose mapping is not one, raises: read as "no mapping", every comment such a record knows
    would be announced again as new."""
    folder = (pack or {}).get("_dir")
    if not folder:
        return ()
    path = os.path.join(folder, "migrate.yaml")
    try:
        seen = os.stat(path)
    except FileNotFoundError:
        return ()
    except OSError as exc:
        raise SpecUnreadable(
            f"{path} cannot be read ({exc}), so the watch id prefixes it may give are unknown"
        ) from exc
    stamp = (seen.st_mtime_ns, seen.st_size, seen.st_ino, pack_local.stamp(folder))
    kept = _PREFIXES.get(path)
    if kept is not None and kept[0] == stamp:
        return kept[1]
    import yaml

    try:
        raw = pack_local.read(path, fill_home=False) or {}
    except (OSError, yaml.YAMLError, UnicodeDecodeError, PackError) as exc:
        raise SpecUnreadable(
            f"{path} cannot be read ({str(exc).splitlines()[0]}), so the watch id prefixes it may give are unknown"
        ) from exc
    records = raw.get("records") if isinstance(raw, dict) else None
    given = records.get("watch_id_prefixes") if isinstance(records, dict) else None
    if not isinstance(raw, dict) or (records is not None and not isinstance(records, dict)):
        raise SpecUnreadable(
            f"{path} is not a mapping with a records block, so the watch id prefixes it may give are unknown"
        )
    if given is not None and not _prefix_map(given):
        raise SpecUnreadable(
            f"{path} records.watch_id_prefixes maps a prefix of letters to one of {', '.join(ID_KINDS)}"
        )
    found = tuple((given or {}).items())
    _PREFIXES[path] = (stamp, found)
    return found


def _tag_pattern(pack) -> "re.Pattern":
    labels = (pack or {}).get("finding_labels")
    tags = [str(label) for label in labels] if isinstance(labels, (list, tuple)) else []
    if not tags:
        return NO_TAG
    return re.compile(
        r"(?m)^[ \t]*(?:[-*>][ \t]*)?(?:\*\*)?[ \t]*(?:"
        + "|".join(re.escape(tag) for tag in tags)
        + r")[ \t]*(?:\*\*)?[ \t]*:"
    )


NO_TAG = re.compile(r"(?!)")  # what a pack with no finding_labels is read by: no line is a tagged finding
TAG_MAX = 16  # a tag is a few letters before a colon; a longer one is a sentence that slipped in


def finding_labels_problem(pack) -> str:
    """What is wrong with the pack's finding_labels, as the words after the key's name, or "": it is a list of short texts. An empty list, like no key,
    means no tags. A value of another shape still loads and is read as written (no list: no tags; an item that is
    no text: its text), so this says what the pack probably meant."""
    labels = (pack or {}).get("finding_labels")
    if labels is None or labels == []:
        return ""
    if not isinstance(labels, list):
        return (
            f"is {type(labels).__name__} {str(labels)[:40]!r}, not a list, so no tag marks a finding "
            "(only a suggestion block asks for work)"
        )
    odd = [
        label
        for label in labels
        if not isinstance(label, str) or not label.strip() or label != label.strip() or len(label) > TAG_MAX
    ]
    if odd:
        return (
            f"has an item that is not a tag: {str(odd[0])[:40]!r} (a tag is a text of 1 to {TAG_MAX} characters with no space "
            f"around it, written before a colon); it is matched as written"
        )
    return ""


def own_id(value: str, prefixes=()) -> str:
    """A comment id an earlier pipeline wrote under one of the pack's prefixes (watch_id_prefixes), in this watch's
    form; every other id unchanged."""
    text = str(value or "")
    for prefix, ours in prefixes:
        if text.startswith(prefix) and text[len(prefix) :].isdigit():
            return ours + text[len(prefix) :]
    return text


def known_ids(previous: dict, prefixes=()) -> set:
    """Every comment id the record already knows: its ids and the baseline an earlier pipeline kept, in this watch's form."""
    found = set()
    for key in ("ids", "baseline"):
        for value in previous.get(key) or []:
            found.add(own_id(value, prefixes))
    return found


def closed_thread_ids(threads) -> set:
    """The inline comment ids that are not a thread's open question: every comment of a resolved thread, and every
    comment of an open thread but its latest (a thread speaks through its last comment; an answered question is not
    asked again)."""
    found = set()
    for thread in threads or []:
        if not isinstance(thread, dict):
            continue
        nodes = [
            comment
            for comment in ((thread.get("comments") or {}).get("nodes") or [])
            if isinstance(comment, dict) and comment.get("databaseId") is not None
        ]
        if thread.get("isResolved"):
            found.update(f"inline:{comment['databaseId']}" for comment in nodes)
        else:
            found.update(f"inline:{comment['databaseId']}" for comment in nodes[:-1])
    return found


def record_path(ticket: str, repo: str, number) -> str:
    """A ticket's PR lives with the ticket; a graduated bump PR, which has none, with the platform records."""
    from .paths import platform_dir, segment, within

    name = f"{repo}-{number}.json"
    if not ticket:
        return within(os.path.join(platform_dir(), "pr"), name, "repo")
    return within(qa_of(segment(ticket, "ticket"), "pr"), name, "repo")


def _read(path: str) -> dict:
    try:
        data = json.load(open(path, encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _write(path: str, data: dict) -> None:
    write_record(path, data)


def _settled(ticket: str, repo: str, number) -> bool:
    """Whether this PR's record says the PR is merged — the one state it can never come back from.

    Merged, not merely closed: GitHub reopens a closed PR, and nothing re-reads a record once its PR
    has left the watch, so a closed one that leaves would be missed for good. A PR with no record yet
    has not been read, so it is not settled either.
    """
    return bool(_read(record_path(ticket, repo, number)).get("merged"))


def watched() -> list:
    """(ticket, repo, number) for every PR an intent names, and every PR record still open.

    A ticket leaves the watch once its PRs are merged AND it has its ticket-done intent: the
    lifecycle the intent marks is over. Watching past that read the forge forever and rewrote the
    record on every pass to move `last_check`, which — at a pass every five minutes against a five
    minute quiet gate — kept `workspace-watch` from ever finding that ticket's records quiet enough
    to commit. An intent is kept forever, so without this every ticket that ever opened a PR was
    watched for good.
    """
    found = {}
    intents = all_intents()
    acked = {intent["ticket"] for intent in intents if intent.get("type") == "ticket-done"}
    for intent in intents:
        payload = intent.get("payload") or {}
        if payload.get("repo") and payload.get("number") and intent.get("type") != "ticket-done":
            key = (intent["ticket"], payload["repo"], int(payload["number"]))
            if intent["ticket"] in acked and _settled(*key):
                continue
            found[key] = True
    from .paths import qa

    root = qa()
    for ticket in sorted(os.listdir(root)) if os.path.isdir(root) else []:
        folder = qa_of(ticket, "pr")
        for name in sorted(os.listdir(folder)) if os.path.isdir(folder) else []:
            record = _read(os.path.join(folder, name)) if name.endswith(".json") else {}
            if record.get("repo") and record.get("number") and record.get("state", "open") == "open":
                found[(ticket, record["repo"], int(record["number"]))] = True
    from .owners import registered_prs

    for item in registered_prs():  # a plugin's tickets' PRs (a release's): followed until merged, like the ones above
        if item.get("ticket") and item.get("repo") and item.get("number"):
            key = (item["ticket"], item["repo"], int(item["number"]))
            if not (item["ticket"] in acked and _settled(*key)):
                found[key] = True
    from .paths import platform_dir

    for item in _read(os.path.join(platform_dir(), "graduated-prs.json")).get("prs") or []:
        if isinstance(item, dict) and item.get("repo") and item.get("number"):
            found.setdefault(("", item["repo"], int(item["number"])), True)
    return sorted(found)


def merge_ready() -> list:
    """A plugin's PRs it is done with and the watch still sees open: one row per PR, with every ticket it carries."""
    from .owners import registered_prs

    rows = {}
    for item in registered_prs():
        if not item.get("ready"):
            continue
        record = _read(record_path(item["ticket"], item["repo"], item["number"]))
        if record.get("merged") or record.get("state", "open") != "open":
            continue
        row = rows.setdefault(
            (item["repo"], int(item["number"])),
            {
                "repo": item["repo"],
                "number": int(item["number"]),
                "url": item.get("url") or record.get("url") or "",
                "title": record.get("title") or "",
                "plugin": item["plugin"],
                "tickets": [],
            },
        )
        if item["ticket"] not in row["tickets"]:
            row["tickets"].append(item["ticket"])
    return sorted(rows.values(), key=lambda row: (row["repo"], row["number"]))


def open_pr_tickets() -> set:
    """Tickets with a PR the watch last saw open: still waiting for its merge."""
    from .paths import qa

    root = qa()
    found = set()
    for ticket in sorted(os.listdir(root)) if os.path.isdir(root) else []:
        folder = qa_of(ticket, "pr")
        for name in sorted(os.listdir(folder)) if os.path.isdir(folder) else []:
            record = _read(os.path.join(folder, name)) if name.endswith(".json") else {}
            if record.get("repo") and record.get("number") and record.get("state", "open") == "open":
                found.add(ticket)
    return found


def _comments(forge, repo: str, number) -> list:
    """Every comment on the PR, oldest first: {id, kind, author, body, path, url, at, in_reply_to, review_state}."""
    from .forges import seam

    return seam(forge).comments(repo, number)


# A folded section of a review's body that its own writer files as an aside: a review bot's "Nitpick comments: 1".
ASIDES = ("nitpick comment",)
_FOLD = re.compile(r"<(/?)details\b[^>]*>", re.I)
_SUMMARY = re.compile(r"<summary\b[^>]*>(.*?)</summary>", re.I | re.S)


def without_asides(body: str) -> str:
    """The body without its outermost folded sections (`<details>`) whose summary names an aside. What such a section
    holds is not asked of anyone: read with the rest, a review made of one alone counts as new work when the aside
    inside carries a finding tag, and comes to the human as comments to treat."""
    kept, depth, start, last = [], 0, 0, 0
    for mark in _FOLD.finditer(body or ""):
        if not mark.group(1):
            if depth == 0:
                start = mark.start()
            depth += 1
        elif depth:
            depth -= 1
            if depth == 0:
                block = body[start : mark.end()]
                summary = _SUMMARY.search(block)
                if summary and any(word in re.sub(r"<[^>]+>", " ", summary.group(1)).lower() for word in ASIDES):
                    kept.append(body[last:start])
                    last = mark.end()
    kept.append((body or "")[last:])
    return "".join(kept)


def _skip(pack, me: str, comment: dict, closed=None) -> str:
    """Why a comment is not work for the human: their own, a bot's (unless it names a mention tag), bare praise or an
    acknowledgement, an approval (it feeds the merge row), a verdict whose body carries no finding tag and no suggestion
    (its inline comments are counted on their own), or an inline comment in a thread that is resolved."""
    forge = (pack or {}).get("forge") or {}
    body = comment.get("body") or ""
    kind = comment.get("kind") or ""
    if comment["author"] == me:
        return "yours"
    if comment["author"] in (forge.get("bots") or []) and not any(
        tag in body for tag in forge.get("mention_tags") or []
    ):
        return "a bot's"
    if kind == "review" and comment.get("review_state") == "APPROVED":
        return "an approval: the merge row has it"
    if kind == "review":
        if not body.strip():
            return "a verdict without a body: its inline comments are counted"
        if not _tag_pattern(pack).search(body) and not SUGGESTION.search(body):
            return "no finding tag and no suggestion: informational, its inline comments are counted"
        asked = without_asides(body)
        if not _tag_pattern(pack).search(asked) and not SUGGESTION.search(asked):
            return "only nitpicks in its body: nothing is asked"
        return ""
    if closed and comment.get("id") in closed:
        if comment.get("id") in getattr(closed, "outdated", ()):
            return "in an outdated thread (the code it points at changed)"
        return "in a resolved thread" if closed_reason(comment, closed) else "answered in its thread"
    if (
        kind == "comment"
        and forge.get("tagged_comments_only")
        and not _tag_pattern(pack).search(body)
        and not SUGGESTION.search(body)
        and not any(tag in body for tag in forge.get("mention_tags") or [])
    ):
        return "a conversation comment without a finding tag (forge.tagged_comments_only)"
    if body.strip().lower().rstrip("!. ") in PRAISE:
        return "praise"
    if ACK.search(body[:400]) and len(body) < 2500:
        return "an acknowledgement"
    return ""


def closed_reason(comment: dict, closed) -> bool:
    """Whether the comment sits in a resolved thread (closed marks those with the thread's every comment); a thread
    answered but open marks all but its latest."""
    return getattr(closed, "resolved", set()) and comment.get("id") in getattr(closed, "resolved", set())


class ThreadMarks(set):
    """The inline ids that are no open question, with the resolved ones apart so the reason can say which."""

    def __init__(self, resolved=(), answered=(), outdated=()):
        super().__init__(set(resolved) | set(answered) | set(outdated))
        self.resolved = set(resolved)
        self.outdated = set(outdated)


def thread_marks(threads, skip_outdated: bool = False) -> "ThreadMarks":
    """`skip_outdated` (the pack's forge.skip_outdated): a thread the code moved away from (isOutdated) is no open question."""
    resolved, answered, outdated = set(), set(), set()
    for thread in threads or []:
        if not isinstance(thread, dict):
            continue
        nodes = [
            comment
            for comment in ((thread.get("comments") or {}).get("nodes") or [])
            if isinstance(comment, dict) and comment.get("databaseId") is not None
        ]
        ids = [f"inline:{comment['databaseId']}" for comment in nodes]
        if thread.get("isResolved"):
            resolved.update(ids)
        elif skip_outdated and thread.get("isOutdated"):
            outdated.update(ids)
        else:
            answered.update(ids[:-1])
    return ThreadMarks(resolved, answered, outdated)


def _stamp(text: str) -> float:
    import datetime

    try:
        return datetime.datetime.fromisoformat(str(text).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return 0.0


def iso_of(stamp: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(stamp))


def _epoch(value) -> float:
    """A time as seconds: a number, or the ISO text an earlier pipeline's records kept."""
    if value in (None, "", False):
        return 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        return _stamp(value)


def _yes(value) -> bool:
    """A flag as a bool: an earlier pipeline kept "" and "yes" where a bool goes."""
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes", "ready")
    return bool(value)


def normal(record: dict) -> dict:
    """A PR record with the field shapes the pages read, whatever pipeline wrote it: times as seconds, flags as bools,
    the thread and since-review summaries as dicts."""
    out = dict(record)
    out["last_activity"] = _epoch(record.get("last_activity")) or None
    out["rereview_ready"] = _yes(record.get("rereview_ready"))
    out["re_requested"] = _yes(record.get("re_requested"))
    out["merged"] = bool(record.get("merged"))
    for key in ("my_threads", "since_review"):
        if not isinstance(out.get(key), dict):
            out[key] = {}
    for key in ("approvals", "new", "replies"):
        if not isinstance(out.get(key), list):
            out[key] = []
    out["new_count"] = int(record.get("new_count") or len(out["new"]))
    from .render import forge_markdown

    for key in ("new", "replies", "skipped"):  # the pages render a comment; its raw body stays beside it
        if isinstance(out.get(key), list):
            out[key] = [
                {**item, "html": forge_markdown(item.get("body") or item.get("text") or "")}
                if isinstance(item, dict)
                else item
                for item in out[key]
            ]
    return out


def _since_review(forge, repo: str, record: dict, previous: dict) -> dict:
    """What the author pushed since my review: commits and changed files, from the forge's compare of the reviewed sha and
    the head. It is read once per head; without a review, or at the reviewed head, there is nothing."""
    reviewed, head = record.get("reviewed_sha") or "", record.get("head_sha") or ""
    if not reviewed or not head or head == reviewed:
        return {"commits": 0, "files": 0}
    kept = previous.get("since_review") if isinstance(previous.get("since_review"), dict) else {}
    if kept.get("head") == head and kept.get("reviewed") == reviewed:
        return kept
    found = {"commits": 1, "files": 0, "head": head, "reviewed": reviewed}
    try:
        from .forges import seam

        compared = seam(forge).compare(repo, reviewed, head)
        found["commits"] = int(compared.get("total_commits") or 1)
        found["files"] = len(compared.get("files") or [])
    except Exception:  # noqa: BLE001, S110 - a history rewritten since the review compares to nothing: still one push to look at
        pass
    return found


HEAL_SECONDS = 86400


def opened_here(ticket: str, repo: str, number) -> bool:
    """This pipeline opened the PR: an open-pr intent of the ticket went out and its receipt is this PR."""
    from .intents import all_intents

    for intent in all_intents(ticket):
        url = str((intent.get("receipt") or {}).get("url") or "")
        if (
            intent.get("type") == "open-pr"
            and str(intent.get("status")).startswith("published")
            and (intent.get("payload") or {}).get("repo") == repo
            and url.endswith(f"/pull/{number}")
        ):
            return True
    return False


def first_baseline(previous: dict, ids: list, opened: bool, created: float, now: float, prefixes=()) -> set:
    """The comment ids that are not news on this read.

    At first sight of a PR someone else opened, or the human opened by hand, what is on it is what the pipeline worked
    from. On a PR this pipeline opened nothing is: a review bot answers within minutes, before the watch's next pass,
    and findings taken for the baseline would never become a "treat comments" row. A record such a first read
    already wrote is read once more from nothing while the PR is a day old."""
    known = "ids" in previous or "baseline" in previous
    if not known:
        return set() if opened else set(ids)
    if (
        opened
        and not previous.get("first_sight")
        and not (previous.get("new") or [])
        and created
        and now - created < HEAL_SECONDS
    ):
        return set()
    return known_ids(previous, prefixes)


def read(pack, forge, ticket: str, repo: str, number, now: float) -> dict:
    """Read one PR and merge it into its record."""
    from .forges import seam

    forge = seam(forge)
    prefixes = watch_id_prefixes(pack)
    path = record_path(ticket, repo, number)
    previous = _read(path)
    pull = forge.pr(repo, number)
    me = forge.me()
    comments = _comments(forge, repo, number)
    record = {
        **previous,
        "ticket": ticket,
        "repo": repo,
        "number": int(number),
        "url": pull.get("html_url") or "",
        "title": pull.get("title") or "",
        "head": (pull.get("head") or {}).get("ref") or "",
        "head_sha": (pull.get("head") or {}).get("sha") or "",
        "base": (pull.get("base") or {}).get("ref") or "",
        "author": (pull.get("user") or {}).get("login") or previous.get("author") or "",
        "merged": bool(pull.get("merged") or pull.get("merged_at")),
        "last_check": iso(),
    }
    record["state"] = "merged" if record["merged"] else str(pull.get("state") or "open").lower()
    record["role"] = previous.get("role") or ("author" if record["author"] in ("", me) else "reviewer")
    ids = [comment["id"] for comment in comments]
    baseline = first_baseline(
        previous, ids, opened_here(ticket, repo, number), _epoch(pull.get("created_at")), now, prefixes
    )
    record["first_sight"] = previous.get("first_sight") or iso()
    threads = forge.threads(repo, number)
    closed = thread_marks(threads, bool(((pack or {}).get("forge") or {}).get("skip_outdated")))
    news = [comment for comment in comments if comment["id"] not in baseline]
    # the comments kept as new so far are read again by today's rules: a thread resolved since, an approval, a verdict
    # without a tag leave; a comment the human has seen (seen/treat emptied the list) does not come back
    kept = []
    seen_ids = set()
    for comment in [*(previous.get("new") or []), *news]:
        if not isinstance(comment, dict):
            continue
        cid = own_id(comment.get("id"), prefixes)
        if cid in seen_ids:
            continue
        seen_ids.add(cid)
        current = next((row for row in comments if row["id"] == cid), None)
        if current is None:
            current = {
                **comment,
                "id": cid,
                "kind": {"review-comment": "inline"}.get(
                    str(comment.get("kind") or ""), str(comment.get("kind") or "comment").split(":")[0]
                ),
            }
        if _skip(pack, me, current, closed):
            continue
        kept.append(current)
    record["new"] = kept
    record["skipped"] = [
        *(previous.get("skipped") or []),
        *[
            {**comment, "reason": _skip(pack, me, comment, closed)}
            for comment in news
            if _skip(pack, me, comment, closed)
        ],
    ][-20:]
    record["new_count"] = len(record["new"])
    record["ids"] = sorted(set(ids) | baseline)
    record["approvals"] = [
        {"author": row["author"], "at": row["at"]}
        for row in comments
        if row["kind"] == "review" and row.get("review_state") == "APPROVED" and row["author"] != me
    ]
    mine = [row for row in comments if row["kind"] == "review" and row["author"] == me]
    record["my_review_state"] = mine[-1]["review_state"] if mine else ""
    record["reviewed_sha"] = (mine[-1].get("commit") if mine else "") or previous.get("reviewed_sha") or ""
    record["re_requested"] = me in [row.get("login") for row in pull.get("requested_reviewers") or []] and bool(mine)
    owned = [
        thread for thread in threads if (thread["comments"]["nodes"] or [{}])[0].get("author", {}).get("login") == me
    ]
    record["my_threads"] = {
        "total": len(owned),
        "resolved": sum(1 for thread in owned if thread["isResolved"]),
        "replied": sum(
            1 for thread in owned if any(row["author"]["login"] != me for row in thread["comments"]["nodes"][1:])
        ),
    }
    record["replies"] = [row for row in comments if row.get("in_reply_to") and row["author"] != me][-12:]
    activity = max([_stamp(row["at"]) for row in comments if row["at"]] or [0])
    if previous and record["head_sha"] != previous.get("head_sha"):
        activity = max(activity, now)  # a push is activity too, and the forge gives no time for it here
    record["last_activity"] = max(activity, _epoch(previous.get("last_activity")))
    record["since_review"] = _since_review(forge, repo, record, previous)
    _write(path, record)
    return record


def _review_alive(ticket: str, record: dict) -> bool:
    """A review of mine for a head newer than the one I reviewed is already written, at the gate, posted or published:
    nothing to re-review yet."""
    head = record.get("head_sha") or ""
    if head == record.get("reviewed_sha"):
        return False
    return any(
        row.get("type") == "pr-review-submit"
        and row.get("status") in OPEN_STATUSES + ("published",)
        and (row.get("payload") or {}).get("sha") == head
        and str((row.get("payload") or {}).get("number")) == str(record.get("number"))
        for row in all_intents(ticket)
    )


# The "Your job" text of a re-review card; a pack names its own review skills with forge.rereview_job (same fields).
REREVIEW_JOB = (
    "Refresh the checkout to the PR head (`cockpit worktree add {ticket} {repo} --from {head_ref}`).\n"
    "1. For each of YOUR threads: is the patch or the reply sufficient? Say so per thread, with a "
    "one-clause reason where it is not.\n"
    "2. Review ONLY what changed since your review: `git diff {since}..{head}`. New findings only for "
    "new code; never re-judge what you already accepted.\n"
    "3. Post the table and the new findings as a comment on this card, then write ONE pr-review-submit "
    "intent (`cockpit outbox new {ticket} pr-review-submit --repo {repo} --number {number} --sha "
    "{head_sha} --event ... --body-file ... --threads-file ...`, with `--review-id <your pending review "
    "id>` to append to a pending review).\n"
)


@one_at_a_time
def _rereview(pack, record, now: float, force: bool = False, note: str = "") -> str:
    """One re-review card per head, to a reviewer, once the human's part is answered and the PR has been quiet. `force`:
    the human asked for it now (the Inbox's Re-review), quiet or not. Not while the PR is approved, merged or closed, the ticket
    is halted, or a review of mine for this head is alive. `hours.rereview_quiet_minutes` sets the quiet time (default two hours);
    `forge.rereview_at_once: true` starts it at once when the author re-requested the review or every thread of mine is resolved."""
    from .halt import halted
    from .kanban import card_title, open_cards, open_twin, place_card
    from .lanes import free_lane

    if record["role"] != "reviewer" or record["state"] != "open" or not record.get("reviewed_sha"):
        return ""
    if not force and (
        record.get("my_review_state") == "APPROVED"
        or halted(record["ticket"])
        or _review_alive(record["ticket"], record)
    ):
        record["rereview_ready"] = False
        return ""
    threads = record.get("my_threads") or {}
    resolved = bool(threads.get("total") and threads.get("resolved") == threads.get("total"))
    moved = record["head_sha"] != record["reviewed_sha"] or bool(threads.get("replied"))
    answered = resolved or moved or record.get("re_requested")
    quiet = float(((pack or {}).get("hours") or {}).get("rereview_quiet_minutes") or QUIET_SECONDS / 60) * 60
    at_once = bool(((pack or {}).get("forge") or {}).get("rereview_at_once")) and (
        resolved or record.get("re_requested")
    )
    record["rereview_ready"] = bool(answered) and (at_once or now - _epoch(record.get("last_activity")) >= quiet)
    done = record.get("rereview") or {}
    if not force and (not record["rereview_ready"] or done.get("head") == record["head_sha"]):
        return ""
    key = f"{record['repo']}#{record['number']}@{record['head_sha'][:12]}"
    title = card_title("review", record["ticket"], pack=pack)
    card = open_twin(pack["board"], "review", record["ticket"], key, title)
    if not card:
        since, head = record["reviewed_sha"][:9], record["head_sha"][:9]
        counts = record.get("since_review") or {}
        body = (
            f"PR: {record['url']}\n\nRe-review request on {record['repo']}#{record['number']} (author {record.get('author') or '?'}). "
            f"Your last review stood at {since}; the head is now {head}: {counts.get('commits', '?')} commit(s), "
            f"{counts.get('files', '?')} file(s) since.\nYour threads: {threads.get('total', 0)} total, {threads.get('resolved', 0)} resolved, "
            f"{threads.get('replied', 0)} replied.\n"
        )
        if note:
            body += f"\n## The human's note\n\n{note}\n"
        fields = {
            "ticket": record["ticket"],
            "repo": record["repo"],
            "number": record["number"],
            "since": since,
            "head": head,
            "head_ref": record.get("head") or head,
            "head_sha": record["head_sha"],
        }
        job = ((pack or {}).get("forge") or {}).get("rereview_job") or REREVIEW_JOB
        body += "\n## Your job\n\n" + str(job).format(**fields).rstrip("\n") + "\n"
        lane = free_lane("reviewer", pack, open_cards(pack["board"]))
        card = place_card(
            pack["board"],
            title,
            lane,
            "ready",
            body=body,
            kind="review",
            ticket=record["ticket"],
            key=key,
            pack=pack,
            repos=[record["repo"]],
        )
    record["rereview"] = {"head": record["head_sha"], "card": card, "time": iso()}
    # the re-review covers every comment so far: only what arrives after it counts as new on a PR you review
    record["new"] = []
    record["new_count"] = 0
    return card


def request_rereview(pack, ticket: str, repo: str, number, note: str = "", supersede: str = "") -> dict:
    """The human's Re-review. On a PR the human reviewed, a reviewer re-reviews what changed since that review (the review
    intent it replaces is dropped); on the human's own PR it is the author's side: the new comments are treated."""
    record = _read(record_path(ticket, repo, number))
    if record.get("role") != "reviewer":
        from .acts import treat_pr

        return treat_pr(pack, ticket, repo, number, note or "re-review")
    record = normal(record)
    card = _rereview(pack, record, time.time(), force=True, note=note)
    _write(record_path(ticket, repo, number), record)
    if not card:
        # nothing replaces the human's review intent: it stays, and the page says why no card started
        why = (
            "the PR is not open" if record.get("state") != "open" else "no review of mine on this PR to re-review from"
        )
        return {"ok": False, "card_id": "", "dropped": [], "out": f"no re-review of {repo}#{number}: {why}"}
    dropped = []
    if supersede:
        from .outbox import drop

        drop(supersede, note=f"superseded by the re-review on {card}")
        dropped.append(supersede)
    return {
        "ok": True,
        "card_id": card,
        "dropped": dropped,
        "out": f"re-review of {repo}#{number} on {card}" + (f"; {', '.join(dropped)} dropped" if dropped else ""),
    }


def _owes_done(ticket: str) -> bool:
    """Every author PR of the ticket merged and no ticket-done row covers them yet."""
    folder = qa_of(ticket, "pr")
    records = (
        [_read(os.path.join(folder, name)) for name in sorted(os.listdir(folder)) if name.endswith(".json")]
        if os.path.isdir(folder)
        else []
    )
    records = [row for row in records if row.get("number") and row.get("role", "author") == "author"]
    if not records or not all(row.get("merged") for row in records):
        return False
    return not _covered(all_intents(ticket), {str(row["number"]) for row in records})


def _covered(intents, numbers) -> bool:
    """A ticket-done row covers these PRs: one still waiting for the ack covers what is merged now, one written before rows
    named their PRs covers everything it saw, and any other covers the PRs it names. A `reopened` row covers nothing: the
    ticket was reopened or reworked after it, so the next time every PR is merged and nothing is open, a fresh row asks for
    the ack, whether that merge is a new PR or the same numbers."""
    return any(
        row["type"] == "ticket-done"
        and row.get("status") != "reopened"
        and (
            row.get("status") in OPEN_STATUSES
            or not (row.get("payload") or {}).get("numbers")
            or set(numbers) <= set((row.get("payload") or {}).get("numbers") or ())
        )
        for row in intents
    )


def _ticket_done(pack, ticket: str) -> str:
    """Every PR of the ticket merged and nothing of it open: one ticket-done row for the human's ack."""
    from .gate import _ticket_cards
    from .kanban import OPEN
    from .outbox import create

    folder = qa_of(ticket, "pr")
    records = (
        [_read(os.path.join(folder, name)) for name in sorted(os.listdir(folder)) if name.endswith(".json")]
        if os.path.isdir(folder)
        else []
    )
    records = [row for row in records if row.get("number") and row.get("role", "author") == "author"]
    if not records or not all(row.get("merged") for row in records):
        return ""
    intents = all_intents(ticket)
    numbers = sorted({str(row["number"]) for row in records})
    # a ticket-done row covers the PRs it names (`numbers`); one written before that field covers everything it saw, and one
    # still waiting for the ack covers what is merged now. A PR merged after the human's ack (a reopened ticket) gets a new row.
    if _covered(intents, numbers):
        return ""
    if any(row.get("status") in OPEN_STATUSES for row in intents) or any(
        status in OPEN for _card, status, _done in _ticket_cards(pack, ticket)
    ):
        return ""
    from .acts import developed, done_rows_developed

    if done_rows_developed(pack) and not developed(pack, ticket):
        return ""
    made = create(
        pack,
        ticket,
        "ticket-done",
        "pr-watch",
        "every PR merged and nothing is open",
        {
            "repo": records[0]["repo"],
            "number": records[0]["number"],
            "url": records[0].get("url") or "",
            "numbers": numbers,
        },
    )
    return made["id"]


def _has_branch_record(ticket: str, repo: str, branch: str) -> bool:
    """The ticket already has an open record of a PR of this repo opened from this branch (the pipeline's, or one found
    before). A closed or merged one does not count: a new PR from the same branch is still found."""
    folder = qa_of(ticket, "pr")
    pattern = re.compile(rf"^{re.escape(repo)}-\d+\.json$")
    for name in sorted(os.listdir(folder)) if os.path.isdir(folder) else []:
        record = _read(os.path.join(folder, name)) if pattern.match(name) else {}
        if record.get("head") == branch and record.get("state", "open") == "open":
            return True
    return False


def discover(pack, forge) -> list:
    """With the pack's forge.discover_prs: the open pull requests the human opened by hand on a branch the pipeline pushed (a
    published push-branch), each given a record so the watch follows it like one the pipeline opened. [(ticket, repo, number)]."""
    if not ((pack or {}).get("forge") or {}).get("discover_prs"):
        return []
    found = []
    intents = all_intents()
    acked = {}  # ticket -> when its newest acknowledged ticket-done was made (a dropped one ends nothing)
    for intent in intents:
        if intent.get("type") == "ticket-done" and intent.get("status") == "acknowledged":
            acked[intent["ticket"]] = max(acked.get(intent["ticket"], 0.0), _stamp(intent.get("created_at")))
    asked = set()
    for intent in intents:
        payload = intent.get("payload") or {}
        if (
            intent.get("type") != "push-branch"
            or not str(intent.get("status") or "").startswith("published")
            or not payload.get("repo")
        ):
            continue
        branch = payload.get("publish_as") or payload.get("branch") or ""
        # one forge call per branch; none for a push the human's acknowledged ticket-done came after (its lifecycle is over),
        # nor for a branch whose PR is already recorded
        over = acked.get(intent["ticket"], -1.0) > _stamp(intent.get("created_at"))
        if (
            not branch
            or over
            or (intent["ticket"], payload["repo"], branch) in asked
            or _has_branch_record(intent["ticket"], payload["repo"], branch)
        ):
            continue
        asked.add((intent["ticket"], payload["repo"], branch))
        try:
            from .forges import seam

            listed = seam(forge).open_prs_for_branch(payload["repo"], branch)
        except CockpitError:
            continue
        for pull in listed:
            number = pull.get("number")
            path = record_path(intent["ticket"], payload["repo"], number)
            if number and not os.path.isfile(path):
                _write(
                    path,
                    {
                        "ticket": intent["ticket"],
                        "repo": payload["repo"],
                        "number": int(number),
                        "role": "author",
                        "state": "open",
                        "url": pull.get("html_url") or "",
                    },
                )
                found.append((intent["ticket"], payload["repo"], int(number)))
    return found


def watch(pack, now=None) -> dict:
    """One pass over every watched PR. {rows, cards, done, errors}."""
    from .notify import notify
    from .publish import forge_for

    watch_id_prefixes(
        pack
    )  # a migrate.yaml that cannot be read stops the pass here, before any record is read by a wrong mapping
    forge = forge_for(pack)
    moment = time.time() if now is None else now
    stale = float(((pack or {}).get("hours") or {}).get("pr_stale_hours") or STALE_HOURS) * 3600
    result = {"rows": [], "cards": [], "done": [], "errors": []}
    tickets = set()
    checks = Checks(
        "pr"
    )  # when each PR was read: watch/pr-checked.json, so a pass that finds nothing new writes no record
    discover(pack, forge)  # the PRs the human opened by hand on a pushed branch, when the pack asks
    for ticket, repo, number in watched():
        try:
            record = read(pack, forge, ticket, repo, number, moment)
        except CockpitError as exc:
            result["errors"].append(f"{repo}#{number}: {exc}")
            continue
        checks.mark(record_path(ticket, repo, number))
        tickets.add(ticket)
        if record["role"] == "author" and record["new"]:
            result["rows"].append({"ticket": ticket, "repo": repo, "number": number, "new": len(record["new"])})
            last = record["new"][-1]["id"]
            notify(
                pack,
                "pr_comments",
                f"{repo}#{number}:{last}",
                f"{len(record['new'])} new comment(s) on {repo}#{number}\n{record['url']}\n",
                ticket=ticket,
            )
        card = _rereview(pack, record, moment)
        if card:
            result["cards"].append(card)
            notify(
                pack,
                "rereview",
                f"{repo}#{number}@{record['head_sha'][:12]}",
                f"{repo}#{number}: re-review started (card {card})\n{record['url']}\n",
                ticket=ticket,
            )
        if (
            record["role"] == "author"
            and record["state"] == "open"
            and record["last_activity"]
            and moment - record["last_activity"] >= stale
        ):
            notify(
                pack,
                "pr_stale",
                f"{repo}#{number}@{record['head_sha'][:12]}",
                f"{repo}#{number} has been quiet since {iso_of(record['last_activity'])}\n{record['url']}\n",
                ticket=ticket,
            )
        if (
            record["role"] == "reviewer"
            and record["state"] == "open"
            and record.get("my_review_state") == "CHANGES_REQUESTED"
            and record["last_activity"]
            and moment - record["last_activity"] >= stale
        ):  # silent unless the pack names the event
            notify(
                pack,
                "pr_stale_review",
                f"{repo}#{number}@{record['head_sha'][:12]}",
                f"{repo}#{number} (you asked for changes) has been quiet since {iso_of(record['last_activity'])}\n{record['url']}\n",
                ticket=ticket,
            )
        _write(record_path(ticket, repo, number), record)
    # a ticket whose last PR merged while something of it was still open is owed its row: asked again on later passes,
    # after the merged PR has left the watch
    from .paths import watch_dir  # runtime state, not a record: it never makes the records folder change

    owed_path = os.path.join(watch_dir(), "ticket-done-owed.json")
    owed = set(_read(owed_path).get("tickets") or [])
    was = set(owed)
    for ticket in sorted(tickets | owed):
        made = _ticket_done(pack, ticket)
        if made or not _owes_done(ticket):
            owed.discard(ticket)
        else:
            owed.add(ticket)
        if made:
            result["done"].append(made)
            notify(
                pack,
                "ticket_done",
                ticket,
                f"{ticket}: every PR is merged and nothing is open; its acknowledgement waits for you ({made})\n",
                ticket=ticket,
            )
    if owed != was:
        _write(owed_path, {"tickets": sorted(owed)})
    checks.save()
    return result


def seen(ticket: str, repo: str, number) -> dict:
    """The human has seen the new comments (treated them, or chose not to): they leave the Inbox."""
    path = record_path(ticket, repo, number)
    record = _read(path)
    if not record:
        raise CockpitError(f"no watch record for {repo}#{number}")
    record["new"] = []
    record["new_count"] = 0
    record["treated_at"] = iso()
    _write(path, record)
    return record


def treated(ticket: str, repo: str, number, entry: dict) -> None:
    """Keep which comments a treat card was made for, so a later batch can fold them into one plan."""
    path = record_path(ticket, repo, number)
    record = _read(path)
    if not record:
        return
    record.setdefault("treatments", []).append(entry)
    _write(path, record)


def treatment_of(ticket: str, repo: str, number, card: str) -> dict:
    found = [row for row in _read(record_path(ticket, repo, number)).get("treatments") or [] if row.get("card") == card]
    return found[-1] if found else {}


def card_prs(pack, card: str, ticket: str) -> list:
    """A card's own pull requests, open ones first: a bump card the PRs pinned to it; any other card the ticket's PRs of
    the card's repos (every repo of the ticket when it names none). A merged or closed one carries closed: true."""
    from .acts import _read, bumps_path
    from .kanban import card_entry

    entry = card_entry((pack or {}).get("board") or "", card)
    known = prs_of(ticket)
    if entry.get("kind") == "bumps":
        data = _read(bumps_path()) or {}
        pinned = [
            key for key, row in (data.get("started") or {}).items() if isinstance(row, dict) and row.get("card") == card
        ]
        rows = {f"{row['repo']}#{row['number']}": row for row in known}
        listed = {
            f"{name}#{row.get('number')}": dict(row, repo=name)
            for name, prs in (data.get("repos") or {}).items()
            for row in prs or []
            if isinstance(row, dict)
        }
        found = [
            rows.get(key) or listed.get(key) or {"repo": key.partition("#")[0], "number": key.partition("#")[2]}
            for key in pinned
        ]
    else:
        repos = set(entry.get("repos") or [])
        found = [row for row in known if not repos or row.get("repo") in repos]
    for row in found:
        row["closed"] = bool(row.get("merged")) or str(row.get("state") or "open").lower() != "open"
    return sorted(found, key=lambda row: (row["closed"], str(row.get("repo") or ""), str(row.get("number") or "")))


def prs_of(ticket: str) -> list:
    """Every PR the watch knows for the ticket, for the Tickets page and the Inbox."""
    folder = qa_of(ticket, "pr")
    found = []
    for name in sorted(os.listdir(folder)) if os.path.isdir(folder) else []:
        record = _read(os.path.join(folder, name)) if name.endswith(".json") else {}
        if record.get("number") and record.get("repo"):
            record = normal(record)
            found.append(
                {
                    key: record.get(key)
                    for key in (
                        "repo",
                        "number",
                        "url",
                        "state",
                        "merged",
                        "head",
                        "title",
                        "role",
                        "base",
                        "approvals",
                        "new_count",
                        "my_threads",
                        "my_review_state",
                        "since_review",
                        "re_requested",
                        "last_activity",
                        "rereview",
                        "rereview_ready",
                        "replies",
                    )
                }
            )
    return found


def inbox_rows() -> list:
    """One row per PR with comments the human has not seen: a ticket's PR, or a graduated bump PR that is in no ticket."""
    from .paths import platform_dir, qa

    folders = [(ticket, qa_of(ticket, "pr")) for ticket in (sorted(os.listdir(qa())) if os.path.isdir(qa()) else [])]
    folders.append(("", os.path.join(platform_dir(), "pr")))
    found = {}
    for ticket, folder in folders:
        for name in sorted(os.listdir(folder)) if os.path.isdir(folder) else []:
            record = _read(os.path.join(folder, name)) if name.endswith(".json") else {}
            if not record.get("repo") or not record.get("number") or not record.get("new"):
                continue
            key = (record["repo"], str(record["number"]))
            if ticket or key not in found:
                found[key] = {
                    "ticket": ticket,
                    "repo": record["repo"],
                    "number": record["number"],
                    "new": record["new"],
                }
    return list(found.values())
