# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The forge transcript: what the forge stand-in (tests/bin/gh) was asked, test by test, and the watcher records each test left.

It proves a change to the forge seam kept every call: record before, record after, compare.

    FORGE_TRANSCRIPT_DIR=/some/folder/before TEST_WORKERS=1 scripts/test -p no:cacheprovider -q tests/test_watchers.py ...
    (change the kernel)
    FORGE_TRANSCRIPT_DIR=/some/folder/after  TEST_WORKERS=1 scripts/test -p no:cacheprovider -q tests/test_watchers.py ...
    .venv/bin/python tests/support/forge_transcript.py compare /some/folder/before /some/folder/after

Each test writes `<node id>.calls.jsonl` (one line per call the stand-in received: its argv and the body file's content)
and `<node id>.records.json` (the watch folder, the platform folder and each ticket's pr/ and ci/ records, as text;
never the store's own lock and temp files, which name a process).
The files are raw; `compare` reads them through `canonical`, which names what differs between two runs of the same
code (the test's temp folder, commit ids, the moment of the run) so that only a real difference is left. `--calls`
compares the calls alone, `--records` the records alone. Exit 0: identical. Exit 1: the first differences are printed.
Keep the folders outside the repository.

The tracker has the same proof. While a run records, each test also writes `<node id>.tracker.jsonl`: one line per
request the Jira stand-in (tests/support/fake_jira.py) received (method, path, query, the credentials header, a canonical body:
an upload is its file name, size and digest, never its boundary) and one per run of a pack's tracker command (its argv,
the action, what it was given on stdin). `compare` holds them to the same rule; `--tracker` compares them alone. The
files a change to the tracker seam is proven on: tests/test_publish_read_back.py tests/test_tracker_connector.py
tests/test_outbox_rules.py tests/test_test_flow.py tests/test_panes.py tests/test_gatekeeper.py tests/test_watchers.py
tests/test_bumps_and_pr_cards.py tests/test_question_flow.py tests/test_ticket_pages.py tests/test_session_card.py
tests/test_starter_pack.py tests/test_kernel.py tests/test_missing_files_and_silent_tools.py tests/test_read_only_view_edges.py
tests/test_a_tracker_intent_type_has_one_name.py
tests/test_the_rest_tracker_is_named_jira_and_still_answers_to_rest.py
"""

import hashlib
import json
import os
import re
import sys
import time
import urllib.parse

DIR = "FORGE_TRANSCRIPT_DIR"  # set by the person recording: the folder a run writes into
FILE = "COCKPIT_FORGE_TRANSCRIPT"  # set per test by the fixture: the file the stand-in appends to
RECORDED = ("watch", "platform")  # folders of the records folder kept whole
PER_TICKET = ("pr", "ci")  # folders of qa/<ticket>/ kept whole
SUFFIXES = (".calls.jsonl", ".tracker.jsonl", ".records.json")
TRACKER_ACTION = "COCKPIT_TRACKER_ACTION"  # what a pack's tracker command is run with: the mark of such a run


def node_file(node_id: str) -> str:
    """A test's node id as one file name: readable, and the same on every run."""
    return re.sub(r"[^A-Za-z0-9_.\[\]-]+", "_", node_id.replace("::", "..")).strip("_")[:230]


def call(argv: list) -> None:
    """The stand-in's side: append this call, with the content of its --input file, to the test's transcript."""
    path = os.environ.get(FILE)
    if not path:
        return
    body = None
    if "--input" in argv[:-1]:
        try:
            body = json.load(open(argv[argv.index("--input") + 1], encoding="utf-8"))
        except (OSError, ValueError):
            body = "<unreadable>"
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(json.dumps({"argv": argv, "body": body}, sort_keys=True) + "\n")


def _tracker_line(row: dict) -> None:
    path = os.environ.get(FILE)
    if not path:
        return
    with open(path[: -len(".calls.jsonl")] + ".tracker.jsonl", "a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, sort_keys=True, default=str) + "\n")


def tracker_request(method: str, path: str, body, raw: bytes, headers: dict) -> None:
    """The Jira stand-in's side: append this request to the test's tracker transcript."""
    if not os.environ.get(FILE):
        return
    parts = urllib.parse.urlsplit(path)
    if body is None and raw:
        name = re.search(rb'filename="([^"]+)"', raw)
        content = raw.split(b"\r\n\r\n", 1)[-1].rsplit(b"\r\n--", 1)[0]
        body = {
            "<upload>": {
                "filename": name.group(1).decode() if name else "",
                "size": len(content),
                "sha256": "sha256:" + hashlib.sha256(content).hexdigest()[:32],
            }
        }
    _tracker_line(
        {
            "via": "rest",
            "method": method,
            "path": parts.path,
            "query": urllib.parse.parse_qsl(parts.query, keep_blank_values=True),
            "body": body,
            "headers": headers,
        }
    )


def watch_commands(setattr_) -> None:
    """The fixture's side: every run of a pack's tracker command (a child given COCKPIT_TRACKER_ACTION) is kept too."""
    import subprocess

    real = subprocess.run

    def run(*args, **kwargs):
        action = (kwargs.get("env") or {}).get(TRACKER_ACTION)
        if action:
            given = kwargs.get("input")
            try:
                given = json.loads(given)
            except (TypeError, ValueError):
                pass
            _tracker_line({"via": "command", "action": action, "argv": list(args[0]) if args else [], "stdin": given})
        return real(*args, **kwargs)

    setattr_(subprocess, "run", run)


def scratch(name: str) -> bool:
    """Whether a file is the store's own (a lock, a temp file) and no record: store.scratch, the one rule for that. A
    lock holds the id of the process that took it, so two runs of the same code never write the same one."""
    from cockpitlib.store import scratch as stores_own

    return stores_own(name)


def _kept(relative: str) -> bool:
    if scratch(relative):
        return False
    parts = relative.split(os.sep)
    for index, part in enumerate(parts[:-1]):
        if part in RECORDED and index <= 1:
            return True
        if part == "qa" and len(parts) > index + 3 and parts[index + 2] in PER_TICKET:
            return True
    return False


def records(workspace: str) -> dict:
    """Every kept record under the workspace, as {relative path: text}."""
    found = {}
    for folder, dirs, files in os.walk(workspace):
        dirs[:] = sorted(name for name in dirs if name not in (".git", "homes", "node_modules"))
        for name in sorted(files):
            full = os.path.join(folder, name)
            relative = os.path.relpath(full, workspace)
            if not _kept(relative):
                continue
            try:
                found[relative] = open(full, encoding="utf-8").read()
            except (OSError, ValueError):
                found[relative] = "<unreadable>"
    return found


def begin(node_id: str, setenv) -> str:
    """The fixture's start: name the test's transcript in its shell. The stem its files share, or empty when not recording."""
    folder = os.environ.get(DIR)
    if not folder:
        return ""
    os.makedirs(folder, exist_ok=True)
    stem = os.path.join(folder, node_file(node_id))
    for suffix in SUFFIXES:
        if os.path.exists(stem + suffix):
            os.remove(stem + suffix)
    setenv(FILE, stem + ".calls.jsonl")
    return stem


def end(stem: str, started: float) -> None:
    """The fixture's end: keep the records the test left, and what a comparison must not mistake for a difference."""
    workspace = os.environ.get("COCKPIT_WORKSPACE") or ""
    root = os.environ.get("COCKPIT_ROOT") or ""
    kept = records(workspace) if workspace and os.path.isdir(workspace) else {}
    if not kept and not os.path.exists(stem + ".calls.jsonl") and not os.path.exists(stem + ".tracker.jsonl"):
        return
    meta = {
        "tmp": os.path.dirname(workspace) if workspace else "",
        "root": root,
        "started": started,
        "ended": time.time(),
        "plugin": os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    }
    with open(stem + ".records.json", "w", encoding="utf-8") as handle:
        json.dump({"meta": meta, "records": kept}, handle, sort_keys=True, indent=1)


# ---- comparing

SHA = re.compile(r"\b[0-9a-f]{40}\b")
SHORT = re.compile(r"\b[0-9a-f]{7,12}\b")
STAMP = re.compile(r"\b(20\d\d)-(\d\d)-(\d\d)[T ](\d\d):(\d\d)(?::(\d\d))?(?:\.\d+)?(Z|[+-]\d\d:?\d\d)?")
EPOCH = re.compile(r"\b1[6-9]\d{8}(?:\.\d+)?\b")
CARD = re.compile(r"\bt_[0-9a-f]{8}\b")
DIGEST = re.compile(r"\b[0-9a-f]{64}\b")
MAILDATE = re.compile(r"\b[A-Z][a-z]{2}, \d\d [A-Z][a-z]{2} 20\d\d \d\d:\d\d:\d\d [+-]\d{4}")
PORT = re.compile(r"\b(127\.0\.0\.1|localhost):\d{2,5}\b")
CLOCK = re.compile(r"\b\d\d:\d\d(?::\d\d)?\b")
TMPDIRS = re.compile(
    r"(?:/private)?(?:/tmp|/var/folders/[^/\s\"]+/[^/\s\"]+/T)/pytest-of-[^/\s\"]+/pytest-\d+/[A-Za-z0-9_-]+?\d+"
)
TMPFILE = re.compile(r"(?:/private)?(?:/tmp|/var/folders/[^/\s\"]+/[^/\s\"]+/T)/tmp[A-Za-z0-9_]{6,12}(\.[a-z]+)?")


class Canon:
    """One test's names for what changes from run to run: the same commit is the same <sha:n> wherever it appears."""

    def __init__(self, meta: dict, numbered: bool = True):
        self.meta = meta or {}
        self.numbered = (
            numbered  # calls come in one order, so a commit keeps its number; records are keyed by what changes
        )
        self.shas = {}
        self.cards = {}
        started = float(self.meta.get("started") or 0)
        ended = float(self.meta.get("ended") or started)
        self.window = (started - 172800, ended + 172800)
        days = (
            {
                time.strftime("%Y-%m-%d", moment(at))
                for at in (started - 86400, started, ended, ended + 86400)
                for moment in (time.gmtime, time.localtime)
            }
            if started
            else set()
        )
        self.days = days
        self.seconds = (started - 5, ended + 5)

    def _sha(self, match) -> str:
        if not self.numbered:
            self.shas.setdefault(match.group(0), "<sha>")
            return "<sha>"
        return self.shas.setdefault(match.group(0), f"<sha:{len(self.shas) + 1}>")

    def _short(self, match) -> str:
        text = match.group(0)
        for full, name in list(self.shas.items()):
            if full.startswith(text):
                return name.replace("sha", "short")
        return text

    def _card(self, match) -> str:
        return self.cards.setdefault(match.group(0), f"<card:{len(self.cards) + 1}>") if self.numbered else "<card>"

    def _stamp(self, match) -> str:
        """A moment of the run itself, or one counted back from it by whole days (the same time of day, another date)."""
        if match.group(0)[:10] in self.days:
            return "<now>"
        if not self.meta.get("started") or match.group(6) is None:
            return match.group(0)
        of_day = int(match.group(4)) * 3600 + int(match.group(5)) * 60 + int(match.group(6))
        for zone in (time.gmtime, time.localtime):
            first, last = (
                moment.tm_hour * 3600 + moment.tm_min * 60 + moment.tm_sec for moment in map(zone, self.seconds)
            )
            if first <= of_day <= last or (first > last and (of_day >= first or of_day <= last)):
                return "<now>"
        return match.group(0)

    def _epoch(self, match) -> str:
        return "<now>" if self.window[0] <= float(match.group(0)) <= self.window[1] else match.group(0)

    def text(self, text: str) -> str:
        for key in ("tmp", "root"):
            value = self.meta.get(key) or ""
            for spelled in {value, os.path.realpath(value)} if value else ():
                text = text.replace(spelled, f"<{key}>")
        plugin = self.meta.get("plugin") or ""
        if plugin:
            text = text.replace(plugin, "<plugin>")
        text = TMPDIRS.sub("<tmp>", text)
        text = TMPFILE.sub("<tmpfile>", text)
        text = DIGEST.sub("<digest>", text)
        text = MAILDATE.sub("<now>", text)
        text = PORT.sub(r"\1:<port>", text)
        text = SHA.sub(self._sha, text)
        text = CARD.sub(self._card, text)
        text = SHORT.sub(self._short, text)
        text = STAMP.sub(self._stamp, text)
        text = EPOCH.sub(self._epoch, text)
        return text


def canonical_calls(lines: list, canon: Canon) -> list:
    """The calls as comparable lines: the body file is its content, never its path."""
    out = []
    for line in lines:
        row = json.loads(line)
        argv = list(row.get("argv") or [])
        if "--input" in argv[:-1]:
            argv[argv.index("--input") + 1] = "<body>"
        out.append(canon.text(json.dumps({"argv": argv, "body": row.get("body")}, sort_keys=True)))
    return out


def canonical_tracker(lines: list, meta: dict) -> list:
    """The tracker's requests as comparable lines, named apart from the forge's calls: a commit's number is this list's own."""
    canon = Canon(meta)
    return [canon.text(json.dumps(json.loads(line), sort_keys=True)) for line in lines]


def _ordered(value, canon: Canon):
    """A JSON value with every name canonical and every dict as its pairs in the order of their canonical text: a record
    keyed by a card id or a commit reads the same whichever id the run drew."""
    if isinstance(value, dict):
        pairs = [[canon.text(str(key)), _ordered(item, canon)] for key, item in value.items()]
        return {"<pairs>": sorted(pairs, key=lambda pair: json.dumps(pair, sort_keys=True))}
    if isinstance(value, list):
        return [_ordered(item, canon) for item in value]
    if isinstance(value, str):
        said = canon.text(value)
        return CLOCK.sub("<clock>", said) if "<now>" in said else said
    if isinstance(value, float) or (isinstance(value, int) and not isinstance(value, bool)):
        return canon.text(json.dumps(value))
    return value


def canonical_records(kept: dict, canon: Canon) -> list:
    """The records as [canonical name, canonical text], in the order of those: two commits' files may share a name."""
    names = Canon(canon.meta, numbered=False)
    names.shas = canon.shas
    out = []
    for name, text in (kept or {}).items():
        try:
            said = json.dumps(_ordered(json.loads(text), names), sort_keys=True, indent=1)
        except ValueError:
            said = names.text(text)
            if "<now>" in said:
                said = CLOCK.sub("<clock>", said)
        out.append([names.text(name), said])
    return sorted(out)


def load(folder: str) -> dict:
    """A recorded run as {test: {"calls": [...], "tracker": [...], "records": {...}}}, canonical."""
    tests = {}
    for name in sorted(os.listdir(folder)):
        for suffix in SUFFIXES:
            if name.endswith(suffix):
                tests.setdefault(name[: -len(suffix)], {})
    for stem, held in tests.items():
        meta, kept = {}, {}
        path = os.path.join(folder, stem + ".records.json")
        if os.path.isfile(path):
            data = json.load(open(path, encoding="utf-8"))
            meta, kept = data.get("meta") or {}, data.get("records") or {}
            # a run recorded before the recorder left them out still compares
            kept = {name: text for name, text in kept.items() if not scratch(name)}
        canon = Canon(meta)
        path = os.path.join(folder, stem + ".calls.jsonl")
        lines = [line for line in open(path, encoding="utf-8") if line.strip()] if os.path.isfile(path) else []
        held["calls"] = canonical_calls(lines, canon)
        path = os.path.join(folder, stem + ".tracker.jsonl")
        asked = [line for line in open(path, encoding="utf-8") if line.strip()] if os.path.isfile(path) else []
        held["tracker"] = canonical_tracker(asked, meta)
        held["records"] = canonical_records(kept, canon)
    return tests


def compare(
    before: dict, after: dict, calls: bool = True, kept: bool = True, limit: int = 20, tracker: bool = True
) -> list:
    """Every difference between two runs, as lines a person can read: an empty list is the proof."""
    said = []
    for stem in sorted(set(before) | set(after)):
        one, two = before.get(stem), after.get(stem)
        for wanted, channel, label in ((calls, "calls", "CALLS"), (tracker, "tracker", "TRACKER")):
            if not wanted:
                continue
            first, second = (one or {}).get(channel) or [], (two or {}).get(channel) or []
            if first != second:
                at = next(
                    (index for index, (left, right) in enumerate(zip(first, second)) if left != right),
                    min(len(first), len(second)),
                )
                said.append(
                    f"{label} {stem}: {len(first)} before, {len(second)} after; first difference at call {at + 1}\n"
                    f"  before: {first[at] if at < len(first) else '(none)'}\n  after:  {second[at] if at < len(second) else '(none)'}"
                )
        if kept:
            first, second = (one or {}).get("records") or [], (two or {}).get("records") or []
            for index in range(max(len(first), len(second))):
                mine, theirs = (
                    (first[index] if index < len(first) else ["(none)", "(none)"]),
                    (second[index] if index < len(second) else ["(none)", "(none)"]),
                )
                name = mine[0] if mine[0] == theirs[0] else f"{mine[0]} / {theirs[0]}"
                if mine != theirs:
                    left, right = mine[1].splitlines(), theirs[1].splitlines()
                    at = next(
                        (index for index, (a, b) in enumerate(zip(left, right)) if a != b), min(len(left), len(right))
                    )
                    said.append(
                        f"RECORD {stem}: {name} line {at + 1}\n  before: {left[at] if at < len(left) else '(none)'}\n"
                        f"  after:  {right[at] if at < len(right) else '(none)'}"
                    )
    return said[:limit] + ([f"... and {len(said) - limit} more"] if len(said) > limit else [])


def main(argv: list) -> int:
    if len(argv) < 3 or argv[0] != "compare":
        print(
            "usage: forge_transcript.py compare <before folder> <after folder> [--calls|--tracker|--records]",
            file=sys.stderr,
        )
        return 2
    before, after = load(argv[1]), load(argv[2])
    only = [flag for flag in ("--calls", "--tracker", "--records") if flag in argv]
    differences = compare(
        before,
        after,
        calls=not only or "--calls" in only,
        kept=not only or "--records" in only,
        tracker=not only or "--tracker" in only,
        limit=10**6 if "--all" in argv else 20,
    )
    tests = len(set(before) | set(after))
    count = sum(len(held["calls"]) for held in before.values())
    asked = sum(len(held["tracker"]) for held in before.values())
    files = sum(len(held["records"]) for held in before.values())
    if differences:
        print("\n".join(differences))
        print(
            f"DIFFERENT: {len(differences)} difference(s) over {tests} tests ({count} calls, {asked} tracker requests, {files} record files before)"
        )
        return 1
    print(f"identical: {tests} tests, {count} calls, {asked} tracker requests, {files} record files")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
