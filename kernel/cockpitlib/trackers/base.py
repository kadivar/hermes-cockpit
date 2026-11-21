# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The tracker protocol: what the kernel asks of the place tickets live, as operations and never as one tracker's URLs.

An implementation subclasses `Tracker` and answers the operations its tracker has; the rest stay as they are here and
refuse by the name of the capability they need. `capabilities()` says which it answers, so an intent that needs one the
pack's tracker lacks is refused when it is made (outbox rules), never at publish.

A write takes the intent it publishes ({ticket, payload, ...}) and the steps a part-published intent already took, and
answers (url, what happened in words, what was made): the publisher keeps the three on the receipt. Every write is kept
in `writes`; in a dry run it is kept and not sent, and the reads still happen.

Shapes (each a plain dict; a tracker may carry more keys, the kernel reads only these):

- comment row (`comments`): {id, account (the writer's id on the tracker, "" when it has none), author (a name to show),
  created, updated, text}, in the tracker's order
- made (`comment`): {"comment": <id>}; (`create`): {"key": <the new ticket's key>}
"""

import datetime

from ..errors import CockpitError

# what a tracker may or may not have; an intent names the ones it needs (needs)
# fmt: off
SUMMARY = "summary"                       # a ticket's title, read
STATUS = "status"                         # a ticket's status, read
COMMENTS = "comments"                     # a ticket's comments, read: the comment watch needs it
IDENTITY = "identity"                     # who the pack writes as, so its own comments are not news
COMMENT = "comment"                       # a new comment
EDIT_COMMENT = "edit-comment"             # an existing comment gets a new text, and one is found by its title
ATTACHMENTS = "attachments"               # files attached to a ticket with a comment
CREATE = "create"                         # a new ticket
TRANSITION = "transition"                 # a ticket moves to another status
TRANSITION_THROUGH = "transition-through"   # the tracker says which moves a status has: a move with no direct route goes through
ASSIGNEE = "assignee"                     # a ticket is assigned to someone
SPRINT = "sprint"                         # a new ticket is put in a sprint
COMPONENT = "component"                   # a new ticket is given a component
# fmt: on
CAPABILITIES = (
    SUMMARY,
    STATUS,
    COMMENTS,
    IDENTITY,
    COMMENT,
    EDIT_COMMENT,
    ATTACHMENTS,
    CREATE,
    TRANSITION,
    TRANSITION_THROUGH,
    ASSIGNEE,
    SPRINT,
    COMPONENT,
)

BROWSE_URL = "{url}/browse/{key}"  # a ticket's page when the pack gives no tracker.browse_url
BROWSE_FIELDS = ("url", "key", "project", "number")
PAGE = 100  # comments read per ticket


class Unsupported(CockpitError):
    """The pack's tracker does not have what was asked: the message names the capability."""


def needs(intent_type: str, payload: dict) -> list:
    """The capabilities an intent of that type (its stored name) and payload needs of the tracker it is published to."""
    payload = payload or {}
    if intent_type == "tracker-comment":
        return [
            COMMENT,
            *([ATTACHMENTS] if payload.get("attach") else []),
            *(
                [EDIT_COMMENT]
                if payload.get("comment_id") or payload.get("comment_from") or payload.get("probe_title")
                else []
            ),
        ]
    if intent_type == "tracker-create":
        return [
            CREATE,
            *([COMPONENT] if payload.get("component") else []),
            *([SPRINT] if payload.get("sprint") else []),
            *([ASSIGNEE] if payload.get("assignee") else []),
            *([TRANSITION] if payload.get("transition") else []),
        ]
    if intent_type == "tracker-transition":
        return [TRANSITION, *([ASSIGNEE] if payload.get("assignee") else [])]
    return []


def missing(have, intent_type: str, payload: dict) -> list:
    """The capabilities that intent needs and a tracker with those lacks, in the order they are needed."""
    return [name for name in needs(intent_type, payload) if name not in have]


def link(config: dict, key: str) -> str:
    """A ticket's page: tracker.browse_url with {url}, {key}, {project} and {number} (the key's last part) filled, or <url>/browse/<key>."""
    key = str(key)
    project = key.rsplit("-", 1)[0] if "-" in key else str(config.get("project") or "")
    number = key.rsplit("-", 1)[1] if "-" in key else ""
    said = str(config.get("browse_url") or BROWSE_URL)
    for name, value in (
        ("url", str(config.get("url") or "").rstrip("/")),
        ("key", key),
        ("project", project),
        ("number", number),
    ):
        said = said.replace("{" + name + "}", value)
    return said


def unspelled(config: dict) -> bool:
    """Whether the page `link` spells needs the tracker's address and the pack gives none: such a page is on no host."""
    return "{url}" in str(config.get("browse_url") or BROWSE_URL) and not str(config.get("url") or "").strip("/ ")


def moment(value):
    """A point in time as seconds: a number is one already, a text is read as an ISO moment; None when it is neither."""
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        pass
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    elif len(text) > 5 and text[-5] in "+-" and text[-4:].isdigit():  # +0000, as some trackers write an offset
        text = text[:-2] + ":" + text[-2:]
    try:
        found = datetime.datetime.fromisoformat(text)
    except ValueError:
        return None
    if found.tzinfo is None:
        found = found.replace(tzinfo=datetime.UTC)
    return found.timestamp()


def since_then(rows: list, since) -> list:
    """The comment rows written or edited at or after that moment; a row whose time cannot be read is kept, never dropped."""
    floor = moment(since)
    if floor is None:
        return rows
    kept = []
    for row in rows:
        at = moment(row.get("updated") or row.get("created"))
        if at is None or at >= floor:
            kept.append(row)
    return kept


class Tracker:
    """One tracker, as the human: reads at once, writes kept in `writes` and, in a dry run, not sent."""

    kind = ""
    noun = "tracker"  # what a note to the human calls a comment's home
    over_forge = False  # whether its tickets live on the pack's forge: such a tracker is made with the pack, not its tracker section alone
    HAS = ()

    def __init__(self, config, dry_run: bool = False):
        self.config = config or {}
        self.dry_run = dry_run
        self.writes = []

    def _no(self, capability: str):
        raise Unsupported(f"the {self.kind or 'pack'} tracker has no {capability}")

    # ---- identity
    @classmethod
    def offers(cls, config) -> frozenset:
        """The capability names a tracker of this kind with that configuration answers: known before one is made."""
        return frozenset(cls.HAS)

    def capabilities(self) -> frozenset:
        """The capability names this tracker answers."""
        return type(self).offers(self.config)

    def me(self) -> str:
        """The id of the account the pack writes as, as `comments` names a writer; empty when the tracker cannot say."""
        return ""

    def browse_url(self, key: str) -> str:
        """The page of a ticket."""
        return link(self.config, key)

    def comment_url(self, key: str, comment_id) -> str:
        """The page of one comment of a ticket: the ticket's own page when the tracker has none per comment."""
        return self.browse_url(key)

    # ---- reads
    def summary(self, key: str) -> str:
        """The ticket's title."""
        self._no(SUMMARY)

    def status(self, key: str) -> str:
        """The name of the ticket's status."""
        self._no(STATUS)

    def statuses(self, keys) -> dict:
        """{key: status} for the tickets the tracker answers for; one it cannot read is left out."""
        found = {}
        for key in keys:
            try:
                found[key] = self.status(key)
            except Exception:  # noqa: BLE001, S112 - a ticket that cannot be read is one without a status, whatever went wrong
                continue
        return found

    def comments(self, key: str, since=None) -> list:
        """The ticket's comments as comment rows; with since (seconds or an ISO moment), those written or edited from then on."""
        self._no(COMMENTS)

    def find_comment(self, key: str, title: str) -> str:
        """The id of the ticket's comment that starts with that title, or empty."""
        self._no(EDIT_COMMENT)

    def reachable(self, key: str, to: str) -> tuple:
        """(the move that takes the ticket to that status from where it is, or None; every move it has now)."""
        self._no(TRANSITION_THROUGH)

    # ---- writes
    def comment(self, intent: dict, steps: dict) -> tuple:
        """A comment on the ticket (payload: issue, body or body_file, attach, comment_id to update one in place)."""
        self._no(COMMENT)

    def create(self, intent: dict, steps: dict) -> tuple:
        """A new ticket (payload: summary, body or body_file, project, issue_type, labels, component, sprint, assignee, transition)."""
        self._no(CREATE)

    def transition(self, intent: dict, steps: dict, key: str) -> tuple:
        """The ticket moves to payload.to, through another status when the tracker has no direct move and can say the way."""
        self._no(TRANSITION)


class Wrapped(Tracker):
    """The reads of an object from before the protocol, which answers Jira's REST paths (`_request`) and maybe `_status`
    and `_myself`: what the watch and the standup note ask is made of those, as it was."""

    kind = "jira"
    noun = "Jira"

    def __init__(self, reader, config=None):
        super().__init__(config)
        self.reader = reader

    def capabilities(self) -> frozenset:
        return frozenset(
            name
            for name, told in (
                (COMMENTS, "_request"),
                (STATUS, "_status"),
                (IDENTITY, "_myself"),
                (TRANSITION_THROUGH, "reachable"),
            )
            if hasattr(self.reader, told)
        )

    def me(self) -> str:
        return self.reader._myself() if hasattr(self.reader, "_myself") else ""

    def comment_url(self, key: str, comment_id) -> str:
        return self.browse_url(key) + f"?focusedCommentId={comment_id}"

    def status(self, key: str) -> str:
        return self.reader._status(key)

    def comments(self, key: str, since=None) -> list:
        if not hasattr(self.reader, "_request"):
            raise Unsupported("the pack's tracker command has no read for comments")
        from .jira import comment_rows

        return since_then(
            comment_rows(
                (self.reader._request("GET", f"/rest/api/3/issue/{key}/comment?maxResults={PAGE}") or {}).get(
                    "comments"
                )
            ),
            since,
        )
