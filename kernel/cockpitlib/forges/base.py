# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The forge protocol: what the kernel asks of the place pull requests live, as operations and never as one forge's URLs.

An implementation subclasses `Forge` and answers the operations its forge has; the rest stay as they are here and refuse
by the name of the capability they need. `capabilities()` says which groups it answers, so an intent that needs one the
pack's forge lacks is refused when it is made (outbox rules), never at publish.

Shapes (each a plain dict or list; a forge may carry more keys, the kernel reads only these):

- pull request: {number, title, body, draft, state ("open"|"closed"), merged, html_url, node_id, created_at,
  head: {ref, sha}, base: {ref}, user: {login}, assignees: [{login}], requested_reviewers: [{login}]}
- comment row (`comments`): {id ("issue:<n>"|"inline:<n>"|"review:<n>"), kind ("comment"|"inline"|"review"), author, body,
  url, at, and for an inline one path and in_reply_to, for a review review_state and commit}, oldest first
- thread (`threads`): {id, isResolved, isOutdated, comments: {nodes: [{databaseId, url, createdAt, author: {login}}]}}
- review (`reviews`, `review`): {id, node_id, state ("PENDING"|"COMMENTED"|"CHANGES_REQUESTED"|"APPROVED"|"DISMISSED"),
  body, user: {login}, commit_id, submitted_at}
- review comment (`review_comments`): {id, body, path, line}
- made comment (`add_comment`, `reply`): {id, html_url}
- reaction: {content, user: {login}}
- run (`runs`): {id, name, status, conclusion, run_attempt, html_url}; job (`run_jobs`): {id, name, conclusion}
- comparison (`compare`): {total_commits, files: [...]}
- listed pull request (`list_prs`): {number, title, body, headRefName, headRefOid, baseRefName, url, createdAt, mergedAt,
  author: {login}, files: [{path}]}
- review request (`review_requests`): {repo, number, title}
- issue (`issue`, `create_issue`, `update_issue`): {number, title, body, state ("open"|"closed"), labels: [name, sorted],
  author, assignees: [login], url}
- issue comment (`issue_comments`, `add_issue_comment`, `edit_issue_comment`): {id, author, body, url, created, updated},
  oldest first
"""

from ..errors import CockpitError

# what a forge may or may not have; an intent type names the ones it needs (NEEDS)
# fmt: off
PULL_REQUESTS = "pull-requests"          # open, edit, label, assign, comment
DRAFT = "draft"                          # a PR can be a draft and be marked ready
REVIEW_THREADS = "review-threads"        # inline threads that are replied to and resolved
PENDING_REVIEWS = "pending-reviews"      # a review only its writer sees until it is submitted
REACTIONS = "reactions"                  # a thumbs-up on a review comment
CHECKS = "checks"                        # what is not green on a commit
RUNS = "runs"                            # CI runs of a commit, their jobs and logs
RERUN = "rerun"                          # start a run's failed jobs again
CONDITIONAL_READS = "conditional-reads"  # "unchanged since" answers that cost nothing
SEARCH = "search"                        # the PRs that ask the human for a review
LISTING = "listing"                      # a repo's PRs by state, for the bump and base scans
DIFF = "diff"                            # a PR's diff and the diff between two commits
ISSUES = "issues"                        # a repo's issues: read, made, edited, commented on; a tracker may be made of them
# fmt: on
CAPABILITIES = (
    PULL_REQUESTS,
    DRAFT,
    REVIEW_THREADS,
    PENDING_REVIEWS,
    REACTIONS,
    CHECKS,
    RUNS,
    RERUN,
    CONDITIONAL_READS,
    SEARCH,
    LISTING,
    DIFF,
    ISSUES,
)


class Unsupported(CockpitError):
    """The pack's forge does not have what was asked: the message names the capability."""


def needs(intent_type: str, payload: dict) -> list:
    """The capabilities an intent of that type and payload needs of the forge it is published to."""
    payload = payload or {}
    if intent_type == "open-pr":
        return [PULL_REQUESTS, *([DRAFT] if payload.get("ready") else [])]
    if intent_type == "pr-edit":
        return [PULL_REQUESTS, *([DRAFT] if payload.get("ready") else [])]
    if intent_type == "pr-comment":
        if not payload.get("in_reply_to"):
            return [PULL_REQUESTS]
        return [REVIEW_THREADS, *([REACTIONS] if payload.get("react") else [])]
    if intent_type == "pr-patch-apply":
        return [REVIEW_THREADS]
    if intent_type == "pr-review-submit":
        return [PENDING_REVIEWS, REVIEW_THREADS]
    if intent_type == "ci-rerun":
        return [RERUN]
    return []


def missing(forge, intent_type: str, payload: dict) -> list:
    """The capabilities that intent needs and this forge lacks, in the order they are needed."""
    have = forge.capabilities()
    return [name for name in needs(intent_type, payload) if name not in have]


class Forge:
    """One forge, as the human: reads at once, writes kept in `writes` and, in a dry run, not sent."""

    kind = ""
    default_hosts = ()  # where this kind of forge lives when a pack names no host
    org = ""
    human_login = ""
    dry_run = False

    def _no(self, capability: str):
        raise Unsupported(f"the {self.kind or 'pack'} forge has no {capability}")

    # ---- identity
    def capabilities(self) -> frozenset:
        """The capability names this forge answers."""
        return frozenset()

    def hosts(self) -> list:
        """The network hosts this forge is reached at: a lane may read them and writes to them go through the outbox."""
        return []

    @classmethod
    def cli_deny(cls) -> tuple:
        """Command patterns of this forge's own CLI that write: refused for every lane, whichever forge the pack chose."""
        return ()

    def me(self) -> str:
        """The human's login on the forge."""
        return self.human_login

    def repo(self, name: str) -> str:
        """The repo's full name on the forge: `<org>/<name>`, or the name itself when it already has an owner."""
        return name if "/" in name else f"{self.org}/{name}"

    def url(self, repo: str, number=None) -> str:
        """The page of the repo, or of its pull request with that number."""
        self._no(PULL_REQUESTS)

    def branch_url(self, repo: str, branch: str) -> str:
        """The page of a branch of the repo."""
        return f"{self.url(repo)}/tree/{branch}"

    def review_url(self, repo: str, number, review) -> str:
        """The page of one review of a pull request."""
        return f"{self.url(repo, number)}#pullrequestreview-{review}"

    def run_url(self, repo: str, run_id) -> str:
        """The page of one CI run."""
        return f"{self.url(repo)}/actions/runs/{run_id}"

    def issue_url(self, repo: str, number) -> str:
        """The page of one issue of the repo."""
        return f"{self.url(repo)}/issues/{number}"

    # ---- pull requests
    def pr(self, repo: str, number) -> dict:
        """One pull request."""
        self._no(PULL_REQUESTS)

    def pr_for_head(self, repo: str, head: str, base: str = "") -> dict:
        """The open pull request of that head branch (onto that base, when named), or an empty dict."""
        self._no(PULL_REQUESTS)

    def open_prs_for_branch(self, repo: str, branch: str) -> list:
        """Every open pull request whose head is that branch."""
        self._no(PULL_REQUESTS)

    def list_prs(self, repo: str, state: str, base: str = "", runner=None) -> list:
        """The repo's pull requests in that state ("open", "merged"), newest first, as listed pull requests."""
        self._no(LISTING)

    def create_pr(self, repo: str, title: str, body: str, head: str, base: str) -> dict:
        """Open a pull request, not a draft. The pull request made (a dry run: {dry_run: True})."""
        self._no(PULL_REQUESTS)

    def update_pr(self, repo: str, number, fields: dict) -> dict:
        """Change a pull request's title, body or base: only the fields named."""
        self._no(PULL_REQUESTS)

    def mark_ready(self, repo: str, number) -> None:
        """A draft pull request becomes ready for review; one that is ready already is left alone."""
        self._no(DRAFT)

    # ---- labels and people
    def labels(self, repo: str, number) -> list:
        """The label names of the pull request, or of the issue, with that number, sorted."""
        self._no(PULL_REQUESTS)

    def repo_labels(self, repo: str) -> list:
        """Every label name the repo has, as the forge spells them."""
        self._no(PULL_REQUESTS)

    def set_labels(self, repo: str, number, labels: list) -> None:
        """The pull request, or the issue, carries exactly these labels."""
        self._no(PULL_REQUESTS)

    def add_labels(self, repo: str, number, labels: list) -> None:
        """The pull request, or the issue, also carries these labels."""
        self._no(PULL_REQUESTS)

    def remove_label(self, repo: str, number, label: str) -> None:
        """The pull request, or the issue, no longer carries that label."""
        self._no(PULL_REQUESTS)

    def assign(self, repo: str, number, logins: list) -> None:
        """Those people are assigned to the pull request, or to the issue."""
        self._no(PULL_REQUESTS)

    # ---- conversation
    def comments(self, repo: str, number) -> list:
        """Every comment on the pull request as comment rows, oldest first: conversation comments, inline comments and
        submitted reviews. A review still being written is not a comment yet."""
        self._no(PULL_REQUESTS)

    def add_comment(self, repo: str, number, body: str) -> dict:
        """A conversation comment on the pull request. The made comment."""
        self._no(PULL_REQUESTS)

    def reply(self, repo: str, number, comment_id, body: str) -> dict:
        """A reply in the review thread that inline comment is in. The made comment."""
        self._no(REVIEW_THREADS)

    def edit_review_comment(self, repo: str, comment_id, body: str) -> None:
        """An inline comment gets a new text."""
        self._no(REVIEW_THREADS)

    def reactions(self, repo: str, comment_id) -> list:
        """The reactions on an inline comment."""
        self._no(REACTIONS)

    def react(self, repo: str, comment_id, content: str = "+1") -> None:
        """The human's reaction on an inline comment."""
        self._no(REACTIONS)

    def threads(self, repo: str, number) -> list:
        """The pull request's review threads."""
        self._no(REVIEW_THREADS)

    def resolve_thread(self, thread_id: str) -> None:
        """That review thread is resolved."""
        self._no(REVIEW_THREADS)

    # ---- reviews
    def reviews(self, repo: str, number) -> list:
        """The pull request's reviews, the human's pending one among them."""
        self._no(PENDING_REVIEWS)

    def review(self, repo: str, number, review) -> dict:
        """One review: its state and body."""
        self._no(PENDING_REVIEWS)

    def review_comments(self, repo: str, number, review) -> list:
        """The inline comments of one review."""
        self._no(PENDING_REVIEWS)

    def create_review(self, repo: str, number, commit: str, threads: list) -> dict:
        """A pending review of that commit with these threads ({path, line, side, body, start_line?, start_side?}). The review."""
        self._no(PENDING_REVIEWS)

    def add_review_thread(self, repo: str, number, review: dict, thread: dict) -> None:
        """One more thread on a pending review (the review as `reviews` gave it)."""
        self._no(PENDING_REVIEWS)

    def update_review(self, repo: str, number, review, body: str) -> None:
        """A pending review gets a new summary."""
        self._no(PENDING_REVIEWS)

    def submit_review(self, repo: str, number, review, event: str, body: str) -> None:
        """A pending review is submitted as REQUEST_CHANGES, COMMENT or APPROVE with that summary."""
        self._no(PENDING_REVIEWS)

    def discard_review(self, repo: str, number, review) -> None:
        """A pending review is deleted."""
        self._no(PENDING_REVIEWS)

    # ---- CI
    def checks(self, repo: str, sha: str) -> list:
        """What is not green on that commit: '<name>: <state>' for each check still running or failed."""
        self._no(CHECKS)

    def runs(self, repo: str, sha: str) -> list:
        """The CI runs of that commit."""
        self._no(RUNS)

    def runs_if_changed(self, repo: str, sha: str, etag: str = "") -> dict:
        """A conditional read of the commit's runs: {changed, etag, runs}; runs is None when nothing changed."""
        self._no(CONDITIONAL_READS)

    def run_jobs(self, repo: str, run_id) -> list:
        """The jobs of one run."""
        self._no(RUNS)

    def job_log(self, repo: str, job_id):
        """The log of one job, as text."""
        self._no(RUNS)

    def rerun_failed(self, repo: str, run_id) -> None:
        """The failed jobs of a run start again."""
        self._no(RERUN)

    # ---- diff
    def compare(self, repo: str, base: str, head: str) -> dict:
        """How two commits of the repo differ, as a comparison."""
        self._no(DIFF)

    def compare_diff(self, repo: str, base: str, head: str) -> str:
        """The unified diff between two commits; empty when the forge cannot compare them."""
        return ""

    def pr_diff(self, repo: str, number) -> str:
        """The pull request's unified diff; empty when the forge does not answer."""
        return ""

    # ---- search
    def review_requests(self) -> list:
        """The open pull requests of the organisation that ask the human for a review."""
        self._no(SEARCH)

    # ---- issues: an issue and a pull request of one repo never share a number
    def issue(self, repo: str, number) -> dict:
        """One issue. A number that is a pull request's is refused, never read as an issue."""
        self._no(ISSUES)

    def create_issue(self, repo: str, title: str, body: str, labels=(), assignees=()) -> dict:
        """A new issue with those labels and people. The issue made (a dry run: {dry_run: True})."""
        self._no(ISSUES)

    def update_issue(self, repo: str, number, fields: dict) -> dict:
        """Change an issue's title, body or state ("open", "closed"): only the fields named."""
        self._no(ISSUES)

    def issue_comments(self, repo: str, number, since=None) -> list:
        """The issue's comments as issue comments, oldest first; with since (an ISO moment), those written or edited from then on."""
        self._no(ISSUES)

    def add_issue_comment(self, repo: str, number, body: str) -> dict:
        """A comment on the issue. The issue comment made (a dry run: {dry_run: True})."""
        self._no(ISSUES)

    def edit_issue_comment(self, repo: str, comment_id, body: str) -> None:
        """An issue's comment gets a new text."""
        self._no(ISSUES)
