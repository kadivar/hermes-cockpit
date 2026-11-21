# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""When a test run is finished enough to leave the machine."""

import os
import re

from .paths import qa_of
from .store import read_db

PASS = re.compile(r"✅")
FAIL = re.compile(r"❌")


def row_state(cell: str) -> str:
    text = cell or ""
    if PASS.search(text):
        return "pass"
    if FAIL.search(text):
        return "fail"
    if "Not run" in text or "Blocked" in text or text.strip() == "":
        return "open"
    return "open"  # a result that is neither pass, fail, nor an open marker


HUMAN = "👤"

# What a test report is called, the line it gives its verdict in, and the names of a run's files: each the default of a
# testflow key of the pack, so a pack with its own wording is written and read by it.
TITLE = "Test run"
BANNER_OK, BANNER_NOT_OK, BANNER_IN_PROGRESS = "Passed", "Failed", "In progress"
EVIDENCE_DIR = "evidence"
PLAN_FILE = "test-plan.md"
RESULTS_FILE = "test-results.md"


def bound():
    """The bound pack, for a reader that was handed none; None when no pack is bound or it does not load, which reads
    as the kernel's own names."""
    from .errors import CockpitError

    try:
        from .pack import load
        from .paths import pack_path

        return load(pack_path())
    except (CockpitError, OSError):
        return None


def title(pack) -> str:
    """The heading a test report starts with: the pack's testflow.title."""
    return str(((pack or {}).get("testflow") or {}).get("title") or TITLE)


def banners(pack) -> dict:
    """{ok, not_ok, in_progress}: the verdict line of a test report per outcome, by the pack's testflow.banners."""
    raw = ((pack or {}).get("testflow") or {}).get("banners") or {}
    return {
        "ok": str(raw.get("ok") or BANNER_OK),
        "not_ok": str(raw.get("not_ok") or BANNER_NOT_OK),
        "in_progress": str(raw.get("in_progress") or BANNER_IN_PROGRESS),
    }


def evidence_dir(pack) -> str:
    """The folder of a run its screenshots and videos are kept in: the pack's testflow.evidence_dir."""
    return str(((pack or {}).get("testflow") or {}).get("evidence_dir") or EVIDENCE_DIR)


def plan_file(pack) -> str:
    """The file of a ticket its test plan is written in: the pack's testflow.plan_file."""
    return str(((pack or {}).get("testflow") or {}).get("plan_file") or PLAN_FILE)


def results_file(pack) -> str:
    """The file of a run (or of a ticket) its results are written in: the pack's testflow.results_file."""
    return str(((pack or {}).get("testflow") or {}).get("results_file") or RESULTS_FILE)


def _heading(pack) -> "re.Pattern":
    """A line that starts a test report: the title, as a heading or bare."""
    return re.compile(r"^\s*(?:h[1-3]\.\s*|#{1,3}\s*)?" + re.escape(title(pack)) + r"(?!\w)", re.M)


COVERED = re.compile(r"covered by row\b", re.I)
COVERED_ROW = re.compile(r"covered by row\s*#?(\d+)", re.I)
PROOF = (".png", ".jpg", ".jpeg", ".webp", ".gif", ".mcp.json")  # a screenshot, or the call an API-only row kept


def rows_failed(text: str) -> bool:
    """A row of the results failed. The mark counts in the tables' rows, not in the prose around them: a counts line
    "12 ✅ Pass, 0 ❌ Fail" names the mark with no failure, and a run of passes must still post as passed.
    Results written without a table are read whole."""
    rows = [line for line in (text or "").splitlines() if line.strip().startswith("|")]
    return any(FAIL.search(line) for line in rows) if rows else bool(FAIL.search(text or ""))


def results_still_open(text: str) -> bool:
    """A row is still open, blocked, or waiting on the human. A cleared row is not: a 👤 row the human gave a verdict, a row
    another row covers."""
    for line in (text or "").splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        lowered = stripped.lower()
        if "Not run" in stripped and not COVERED.search(stripped):
            return True
        if HUMAN in stripped and not (PASS.search(stripped) or FAIL.search(stripped)):
            return True
        if "waiting on the human" in lowered and "no longer waiting on the human" not in lowered:
            return True
        if re.search(r"(?<![A-Za-z])Blocked(?![A-Za-z])", stripped):
            return True
    return False


def unfinished(rows, pack=None) -> list:
    """rows are dicts with keys n, result, evidence (and optionally scenario, note). A row is open without a verdict (a row
    another row covers is not); a verdict row needs a screenshot or the API call it kept, except a 👤 row, whose proof is the
    human's. The proof is a file in the run's evidence folder, by the pack's name for it."""
    open_rows = []
    kept = evidence_dir(pack) + "/"
    states = {str(row.get("n")): row_state(row.get("result") or "") for row in rows}
    for row in rows:
        result = row.get("result") or ""
        state = row_state(result)
        if state == "open":
            covered = COVERED_ROW.search(f"{result} {row.get('note') or ''}")
            if (
                covered and states.get(covered.group(1), "pass") != "pass"
            ):  # covered by a row that did not pass: still open
                open_rows.append(f"{row.get('n')}·open")
                continue
            if COVERED.search(f"{result} {row.get('note') or ''}"):
                continue
            open_rows.append(f"{row.get('n')}·open")
            continue
        if HUMAN in f"{row.get('scenario') or ''} {result}":
            continue
        evidence = row.get("evidence") or ""
        if not any(kept in part and part.lower().endswith(PROOF) for part in evidence.split()):
            open_rows.append(f"{row.get('n')}·screenshot")
    return open_rows


def banner(rows, pack=None) -> str:
    """The verdict line the rows call for, in the pack's words."""
    said = banners(pack)
    if unfinished(rows, pack):
        return said["in_progress"]
    if any(row_state(row.get("result") or "") == "fail" for row in rows):
        return said["not_ok"]
    return said["ok"]


DEFAULT_RUN_DIR = "run-{n}"


def run_pattern(pack) -> str:
    return str(((pack or {}).get("testflow") or {}).get("run_dir") or DEFAULT_RUN_DIR)


def _numbered(pack, folder: str) -> list:
    pattern = run_pattern(pack)
    regex = re.compile("^" + re.sub(r"\\\{n(:0\d+d)?\\\}", r"(\\d+)", re.escape(pattern)) + "$")
    found = []
    if os.path.isdir(folder):
        for name in os.listdir(folder):
            match = regex.match(name)
            if match and os.path.isdir(os.path.join(folder, name)):
                found.append((int(match.group(1)), name))
    return sorted(found)


def run_folders(pack, folder: str) -> list:
    """A ticket's test-run folders by the pack's testflow.run_dir pattern, oldest first."""
    return [name for _number, name in _numbered(pack, folder)]


def next_run_dir(pack, folder: str) -> str:
    """The next test-run folder for this ticket, by the pack's pattern."""
    numbers = [number for number, _name in _numbered(pack, folder)]
    return os.path.join(folder, run_pattern(pack).format(n=max(numbers, default=0) + 1))


def scripted_line(plan: str, request: str, pack=None) -> str:
    """A scripted write runs only when the accepted plan lists that one line. The kernel's never-write list (a
    delete, a drop or truncate path, a bulk write, a reset) and the pack's testflow.never_write are refused."""
    from .egress import KERNEL_NEVER_WRITE
    from .errors import CockpitError

    text = (request or "").strip()
    lowered = text.lower()
    never = [*KERNEL_NEVER_WRITE, *(((pack or {}).get("testflow") or {}).get("never_write") or [])]
    if (
        "delete" in lowered
        or lowered.startswith("reset")
        or "bulk reset" in lowered
        or any(re.search(item, text) for item in never)
    ):
        raise CockpitError("delete or bulk reset is refused")
    listed = [line.strip() for line in (plan or "").splitlines() if line.strip()]
    if text not in listed:
        raise CockpitError("the accepted plan does not list that request")
    return text


def rerun_rows(decision: str) -> list:
    """`go with changes: rerun` names the only rows that run again."""
    text = (decision or "").strip()
    if not text.startswith("go with changes:"):
        return []
    rest = text.split(":", 1)[1]
    if "rerun" not in rest:
        return []
    return re.findall(r"\d+", rest.split("rerun", 1)[1])


def rows_from_plan(body: str) -> list:
    """A person row is marked. Its links are the public urls on that line."""
    found = []
    for index, line in enumerate((body or "").splitlines(), start=1):
        text = line.strip()
        if not text:
            continue
        human = "👤" in text
        found.append(
            {
                "n": index,
                "human": human,
                "links": re.findall(r"https://\S+", text) if human else [],
                "steps": [text] if human else [],
            }
        )
    return found


def order_human_rows(rows) -> list:
    """A row only a person can run is marked and placed after every lane row."""
    lane = []
    human = []
    for row in rows or []:
        if row.get("human"):
            human.append(
                {
                    "n": row.get("n"),
                    "human": True,
                    "links": list(row.get("links") or []),
                    "steps": list(row.get("steps") or []),
                    "logged_out": True,
                }
            )
            continue
        lane.append({"n": row.get("n"), "human": False})
    return lane + human


def plain_go(decision: str) -> bool:
    """Only a plain go creates the publish intent. A go with changes does not."""
    return (decision or "").strip() == "go"


def complete(rows, pack=None) -> str:
    """Complete is refused while a row is open or a pass/fail has no screenshot."""
    from .errors import CockpitError

    left = unfinished(rows, pack)
    if left:
        raise CockpitError("unfinished " + ", ".join(left))
    return banner(rows, pack)


def expected_read(text: str) -> str:
    """The value a lifted rule says it will read back."""
    match = re.search(r"\bread\s+(\S+)", text or "", re.I)
    if match:
        return match.group(1)
    return ""


def named_path(text: str) -> str:
    """The path a lifted rule says it will read."""
    match = re.search(r"\bpath:\s*(\S+)", text or "", re.I)
    if match:
        return match.group(1)
    match = re.search(r"\bpath\s+(\S+)", text or "", re.I)
    if match:
        return match.group(1)
    return ""


def lane_reaches(pack, target: str) -> bool:
    """True when the path sits in the lane's record tree, scratch, or ticket checkout."""
    if not target:
        return False
    from .paths import outbox, qa, workspace, wt

    roots = [qa(), outbox(), wt()]
    scratch = str((pack or {}).get("scratch") or "")
    if scratch:
        roots.append(scratch)
    candidate = target if os.path.isabs(target) else os.path.join(workspace(), target)
    real = os.path.realpath(candidate)
    for root in roots:
        base = os.path.realpath(root)
        if real == base or real.startswith(base + os.sep):
            return True
    return False


def accept_block(text: str) -> str:
    """A block names what is missing and who can supply it. One unblocking step also names the undo."""
    from .errors import CockpitError

    body = text or ""
    lowered = body.lower()
    if "missing" not in lowered or "who:" not in lowered:
        raise CockpitError("a block must name what is missing and who can supply it")
    if "step:" in lowered and "undo:" not in lowered:
        raise CockpitError("a block must name the step and how to undo it")
    return body


def keep_finding(line: str, read: set) -> str:
    """A finding that cites an unread line is refused."""
    from .errors import CockpitError

    if line not in read:
        raise CockpitError("finding cites an unread line")
    return line


def require_restatement(decision: str, comment: str) -> str:
    """A go that lifts a rule names the path and the value it expects to read back before it acts."""
    from .errors import CockpitError

    text = (decision or "").strip()
    if not text.lower().startswith("go with changes"):
        return comment or ""
    if "rerun" in text.lower():
        return comment or ""
    body = (comment or text).lower()
    if "path" not in body or "read" not in body:
        raise CockpitError("restatement comment")
    return comment or text


BANNERS = (BANNER_NOT_OK, BANNER_OK, BANNER_IN_PROGRESS)  # the kernel's own three, for a reader with no pack


def results_text(pack, ticket: str) -> str:
    """The ticket's latest test results: the newest run folder's, else the ticket's own file."""
    folder = qa_of(ticket)
    name = results_file(pack)
    for run in reversed(run_folders(pack, folder)):
        path = os.path.join(folder, run, name)
        if os.path.isfile(path):
            return open(path, encoding="utf-8").read()
    path = os.path.join(folder, name)
    return open(path, encoding="utf-8").read() if os.path.isfile(path) else ""


MEDIA = tuple(ext for ext in PROOF if ext != ".mcp.json") + (
    ".mp4",
    ".mov",
    ".webm",
)  # what the author looks at: a screenshot, a recording


def results_post(payload: dict, pack=None) -> bool:
    """A test report's results comment: a test report (its probe title, the init it updates, or its heading) with a final
    banner. An init says In progress and is not one. The title and the banners are the pack's."""
    from .outbox import _body_text

    body = _body_text(payload or {})
    said = banners(pack)
    test_run = (
        (payload or {}).get("probe_title") == title(pack)
        or bool((payload or {}).get("comment_from"))
        or bool(_heading(pack).search(body))
    )
    return test_run and any(phrase in body for phrase in (said["ok"], said["not_ok"]))


def failed_media(pack, ticket: str, run: str = "") -> list:
    """The failed rows' screenshots and videos of a test run, in row order, as workspace paths: what a results post
    attaches under `testflow.attach: failed`. The run named, else the newest with results. A failed row without a
    screenshot or video is refused: the author has nothing to look at."""
    from .errors import CockpitError
    from .paths import workspace
    from .qa_view import parse_results

    folder = qa_of(ticket)
    runs = run_folders(pack, folder)
    if run:
        if run not in runs:
            raise CockpitError(f"no test run {run} on {ticket} (runs: {', '.join(runs) or 'none'})")
        base = os.path.join(folder, run)
    else:
        with_results = [name for name in runs if os.path.isfile(os.path.join(folder, name, results_file(pack)))]
        base = os.path.join(folder, with_results[-1]) if with_results else folder
    path = os.path.join(base, results_file(pack))
    if not os.path.isfile(path):
        raise CockpitError(f"{ticket} has no {results_file(pack)} to read the failed rows from")
    shown = os.path.relpath(base, workspace())
    found = []
    for row in parse_results(path)["rows"]:
        if row_state(row.get("result") or "") != "fail":
            continue
        media = []
        for link in row.get("evidence") or []:
            rel = str(link.get("rel") or "")
            if not rel.lower().endswith(MEDIA):
                continue
            for root in (base, folder, workspace()):
                full = os.path.normpath(os.path.join(root, rel))
                if os.path.isfile(full):
                    media.append(os.path.relpath(full, workspace()))
                    break
        if not media:
            raise CockpitError(
                f"row {row.get('n')} failed without a screenshot or video in {shown}: record it before the results post"
            )
        found += [item for item in media if item not in found]
    return found


def _test_cards(pack, ticket: str, tester_only: bool = False) -> list:
    """The ticket's board cards [(id, title, assignee, created_at)]: its Test kickoff cards (`<ticket>: test`, `<ticket>: test kickoff`)
    or, with tester_only, every card of a tester lane."""
    import sqlite3

    from .kanban import db_path

    try:
        connection = read_db(db_path(pack["board"]))
        rows = connection.execute(
            "select id, title, assignee, created_at from tasks where title like ?", (f"{ticket}:%",)
        ).fetchall()
        connection.close()
    except sqlite3.Error:
        return []
    if tester_only:
        return [row for row in rows if str(row[2] or "").startswith("tester")]
    from .kanban import card_title

    titles = {
        f"{ticket}: test",
        f"{ticket}: test kickoff",
        card_title("test", ticket, pack=pack),
        card_title("test-kickoff", ticket, pack=pack),
    }
    return [row for row in rows if (row[1] or "") in titles or (row[1] or "").startswith(f"{ticket}: test kickoff")]


def human_go_after_review(pack, ticket: str, mark: str = "") -> bool:
    """The human answered "go" after the newest block of a tester card that asked for the review of a run (or, with
    mark, the newest block that says it)."""
    import sqlite3

    from .kanban import db_path

    mark = str(mark or ((pack or {}).get("testflow") or {}).get("review_mark") or REVIEW_MARK).lower()
    ids = [row[0] for row in _test_cards(pack, ticket, tester_only=True)]
    if not ids:
        return False
    try:
        connection = read_db(db_path(pack["board"]))
        marks = ",".join("?" * len(ids))
        blocks = [
            at
            for at, payload in connection.execute(
                f"select created_at, payload from task_events where task_id in ({marks}) and kind like '%block%' and kind not like '%unblock%' order by created_at",
                ids,
            )
            if mark in str(payload or "").lower()
        ]
        if not blocks:
            return False
        # the human's go, or the go that waives only the screenshots; never a lane's own comment
        gos = [
            at
            for at, author, body in connection.execute(
                f"select created_at, author, body from task_comments where task_id in ({marks}) and created_at >= ?",
                (*ids, blocks[-1]),
            )
            if author == "human" and HUMAN_GO.match(str(body or ""))
        ]
        connection.close()
    except sqlite3.Error:
        return False
    return bool(gos)


def post_problems(pack, intent) -> list:
    """Why a test results comment may not leave yet: a row still open, or a banner the rows do not call for. With the pack's
    `testflow.test_run_posts: kickoff`, a test report also needs a test kickoff card on the ticket (a dev ticket reports on
    its card) and, once rows are done, the human's go on the newest review."""
    if (intent or {}).get("type") != "tracker-comment":
        return []
    from .outbox import _body_text

    body = _body_text(intent.get("payload") or {})
    words, named = banners(pack), title(pack)
    finals = (words["ok"], words["not_ok"])
    if str(((pack or {}).get("testflow") or {}).get("test_run_posts") or "") == "kickoff":
        ticket = intent.get("ticket") or ""
        if _heading(pack).search(body or "") or (intent.get("payload") or {}).get("probe_title") == named:
            if not _test_cards(pack, ticket):
                return [
                    f"a {named} comment belongs to a Test kickoff (a card '{ticket}: test'); {ticket} has none, so its test results stay on the card"
                ]
            if any(phrase in body for phrase in finals) and not human_go_after_review(pack, ticket):
                return [
                    'the newest review has no "go" from the human yet (a results post leaves after the human accepted the run)'
                ]
    # the banner the post gives first; of two that start at the same place (one the other's first words), the longer
    said = min(
        (
            (body.find(phrase), -len(phrase), phrase)
            for phrase in (words["not_ok"], words["ok"], words["in_progress"])
            if phrase in body
        ),
        default=(-1, 0, ""),
    )[2]
    final = any(phrase in body for phrase in finals)
    if not said or (
        said == words["in_progress"] and not final
    ):  # an init says In progress whatever the rows are: only a final banner is held to them
        return []
    text = results_text(pack, intent.get("ticket") or "")
    if not text:
        return ["the ticket has no test results to post"]
    if results_still_open(text):
        return ["a row is still open, blocked or waiting on the human"]
    want = words["not_ok"] if rows_failed(text) else words["ok"]
    if said != want:
        return [f"the post says {said!r} but the rows call for {want!r}"]
    return []


REVIEW_MARK = "ready for review"
HUMAN_GO = re.compile(r"^\s*(?:human:\s*)?go(?:\s+without\s+screenshots\b[^\n]*|\s*[.!]?\s*)$", re.I)


def run_not_ready(pack, ticket: str, question: str, card: str = "") -> list:
    """What keeps a tester's run from the human's review, when its block asks for that review: each open row ("n·open"),
    each row without its screenshot ("n·screenshot"), or "(no results table)". Any other question has nothing to say.
    On a test kickoff's run card (card), each Fail row without a failure video that plays ("n·video") too."""
    mark = str(((pack or {}).get("testflow") or {}).get("review_mark") or REVIEW_MARK).lower()
    if not ticket or mark not in (question or "").lower():
        return []
    from .qa_view import parse_results

    newest = _newest_results(pack, ticket)
    rows = parse_results(newest)["rows"] if newest else []  # the newest run's results, else the ticket's own file
    if not rows:
        return ["(no results table)"]
    left = unfinished(
        [
            {
                "n": row["n"],
                "result": row.get("result") or "",
                "scenario": row.get("scenario") or "",
                "note": row.get("note") or "",
                "evidence": " ".join(link.get("rel") or "" for link in row.get("evidence") or []),
            }
            for row in rows
        ],
        pack,
    )
    if run_card(pack, card):
        left += [f"{number}·video" for number, _why in failure_videos(pack, ticket)["missing"]]
    return left


# ---------- the failure video a test kickoff's run card closes with ----------

VIDEO_EXT = (".mp4", ".mov")  # what `cockpit record` writes, and a screen recording made by hand
NO_VIDEO = re.compile(r"video:\s*not possible\s*(?:—|–|--?|:)\s*([^|]+)", re.I)
NO_VIDEO_MARK = "no failure video"


def _newest_results(pack, ticket: str) -> str:
    """The results file of the ticket's newest run that has one, else the ticket's own, else ""."""
    folder = qa_of(ticket)
    name = results_file(pack)
    runs = [os.path.join(folder, run, name) for run in run_folders(pack, folder)]
    runs = [path for path in runs if os.path.isfile(path)] or [
        path for path in (os.path.join(folder, name),) if os.path.isfile(path)
    ]
    return runs[-1] if runs else ""


def run_card(pack, card: str) -> bool:
    """A test kickoff's run card (browser_card kind `test`, the card the human started): not its plan card, not a tester
    phase inside a dev or another flow, never a supervisor card (policy release)."""
    if not card:
        return False
    from .browser_card import facts

    try:
        here = facts(pack, card)
    except Exception:  # noqa: BLE001 - no board, no index: not a card this gate knows
        return False
    return bool(here.get("test_kickoff")) and here.get("kind") != "test-kickoff"


def failure_videos(pack, ticket: str) -> dict:
    """{run, missing: [(row, why)], waived: [(row, reason)]} of the newest run's Fail rows. A row has its video when a
    file in <run>/<testflow.evidence_dir>/videos/ named for its scenario (<n>- or s<n>-, .mp4 or .mov) plays; a row whose
    note says `video: not possible — <reason>` is waived (the human decides it)."""
    from .paths import workspace
    from .qa_view import parse_results
    from .record import accepted

    path = _newest_results(pack, ticket)
    out = {"run": "", "missing": [], "waived": []}
    if not path:
        return out
    base = os.path.dirname(path)
    out["run"] = os.path.relpath(base, workspace())
    folder = os.path.join(base, evidence_dir(pack), "videos")
    names = sorted(os.listdir(folder)) if os.path.isdir(folder) else []
    for row in parse_results(path)["rows"]:
        if row_state(row.get("result") or "") != "fail":
            continue
        number = str(row.get("n") or "")
        prefix = re.compile(rf"^s?0*{re.escape(number.lower().lstrip('0') or '0')}-")
        tried = [
            (name, accepted(os.path.join(folder, name)))
            for name in names
            if name.lower().endswith(VIDEO_EXT) and prefix.match(name.lower())
        ]
        if any(not why for _name, why in tried):
            continue
        waiver = NO_VIDEO.search(f"{row.get('result') or ''} {row.get('note') or ''}")
        if waiver:
            out["waived"].append((number, waiver.group(1).strip().rstrip(".")))
            continue
        out["missing"].append((number, f"{tried[-1][0]} does not play ({tried[-1][1]})" if tried else "no video"))
    return out


def video_refusal(pack, card: str = "", lane: str = "") -> str:
    """Why a test kickoff's run card may not close as done yet ("" when it may): a Fail row without a failure video that
    plays, or a `video: not possible` row the human has not said go to. card: the card named, else this process's; lane:
    the lane whose browser session records, else this process's."""
    from .browser_card import current, facts

    here = facts(pack, card) if card else current(pack)
    if not here or not run_card(pack, here.get("card") or ""):
        return ""
    ticket = here.get("ticket") or ""
    state = failure_videos(pack, ticket)
    if state["missing"]:
        session = f"{lane or os.environ.get('COCKPIT_LANE') or '<lane>'}-{ticket}"
        rows = "; ".join(f"row {number}: {why}" for number, why in state["missing"])
        first = state["missing"][0][0]
        return (
            f"this test kickoff's run card closes as done only when every Fail row of {state['run']} has a failure video that "
            f'plays ({rows}). For each row: cockpit record start --session "{session}" --out {state["run"]}/{evidence_dir(pack)}/videos/'
            f's{first}-<slug>-repro.mp4 --record-id "<a new test record>" --on-screen "<what is on screen now>"; drive the '
            f'failing steps until the wrong result is on screen; cockpit record stop --session "{session}"; link the video '
            f"from the row. If cockpit record refuses (the loan expired, no browser target), write `video: not possible — "
            f"<its reason>` in that row's note instead: the human then decides."
        )
    if state["waived"] and not human_go_after_review(pack, ticket, NO_VIDEO_MARK):
        rows = "; ".join(f"row {number} ({why})" for number, why in state["waived"])
        return (
            f'{NO_VIDEO_MARK} for {rows}: the human decides that, not the lane. Block the card with "{NO_VIDEO_MARK} for '
            f"{rows}: go to close the run without it\" and close after the human's go."
        )
    return ""
