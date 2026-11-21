# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Runs inside the kernel under replay, as its own process: freezes the clock, denies the network, then captures.

Standard library only until the kernel is imported, and the kernel is asked for nothing it does not have already: a
route or a function a kernel version lacks is noted as skipped. One argument: the job file (JSON).
"""

import contextlib
import hashlib
import importlib
import io
import json
import os
import re
import signal
import sys

ADDRESS = re.compile(r"0x[0-9a-fA-F]{6,}")


class Skip(Exception):
    """This kernel has no such read path: noted in the manifest, never compared."""


class Clock:
    """The one moment a replay runs at. A sleep moves it on and takes no time, so a wait that polls the clock ends."""

    def __init__(self, start: float):
        self.start = float(start)
        self.now = float(start)

    def reset(self) -> None:
        self.now = self.start


def freeze(clock: Clock) -> None:
    """time and datetime answer the replay's moment. Before the kernel is imported: a module keeps the names it imported."""
    import datetime
    import time

    real_time = {name: getattr(time, name) for name in ("localtime", "gmtime", "strftime", "ctime")}
    time.time = lambda: clock.now
    time.time_ns = lambda: int(clock.now * 1_000_000_000)
    time.localtime = lambda secs=None: real_time["localtime"](clock.now if secs is None else secs)
    time.gmtime = lambda secs=None: real_time["gmtime"](clock.now if secs is None else secs)
    time.ctime = lambda secs=None: real_time["ctime"](clock.now if secs is None else secs)
    time.strftime = lambda fmt, when=None: real_time["strftime"](fmt, time.localtime() if when is None else when)

    def sleep(seconds) -> None:
        clock.now += max(0.0, float(seconds))

    time.sleep = sleep
    real_datetime, real_date = datetime.datetime, datetime.date

    # plain subclasses, no metaclass: a library may subclass a date with a metaclass of its own
    class FrozenDate(real_date):
        __slots__ = ()

        @classmethod
        def today(cls):
            return cls.fromtimestamp(clock.now)

    class FrozenDatetime(FrozenDate, real_datetime):
        __slots__ = ()

        @classmethod
        def now(cls, tz=None):
            return cls.fromtimestamp(clock.now, tz)

        @classmethod
        def utcnow(cls):
            return cls.fromtimestamp(clock.now, datetime.UTC).replace(tzinfo=None)

        @classmethod
        def today(cls):
            return cls.fromtimestamp(clock.now)

    datetime.datetime = FrozenDatetime
    datetime.date = FrozenDate


def libraries() -> None:
    """The kernel's libraries, imported before the clock is frozen: they keep the real date classes, which the frozen
    ones are subclasses of, so a value of either kind passes their checks."""
    for name in ("yaml", "jsonschema", "pydantic", "fastapi", "httpx"):
        try:
            importlib.import_module(name)
        except Exception:  # noqa: BLE001, S112 - a kernel that does not use one does not need it
            continue


def deny_network(tried: list) -> None:
    """No socket of this process connects and no name is looked up: the attempt is noted and refused."""
    import socket

    def refuse(self, address, *args):
        tried.append(str(address))
        raise ConnectionRefusedError(61, "replay: the network is denied")

    def refuse_quietly(self, address, *args):
        tried.append(str(address))
        return 61

    def no_lookup(host, *args, **kwargs):
        tried.append(str(host))
        raise socket.gaierror(8, "replay: the network is denied")

    socket.socket.connect = refuse
    socket.socket.connect_ex = refuse_quietly
    socket.getaddrinfo = no_lookup
    socket.gethostbyname = no_lookup


def sorted_folders() -> None:
    """A folder is listed in name order: the order a filesystem gives is its own, and two copies need not agree."""
    real_listdir, real_scandir = os.listdir, os.scandir

    class Scan:
        def __init__(self, path):
            with real_scandir(path) as found:
                self.entries = sorted(found, key=lambda entry: entry.name)
            self.rows = iter(self.entries)

        def __iter__(self):
            return self

        def __next__(self):
            return next(self.rows)

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def close(self):
            return None

    os.listdir = lambda path=".": sorted(real_listdir(path))
    os.scandir = lambda path=".": Scan(path)


@contextlib.contextmanager
def limit(seconds: int):
    """One view gets this long: a read path that waits on something a replay does not have is an error, not a hang."""

    def over(signum, frame):
        raise TimeoutError(f"no answer in {seconds} seconds")

    before = signal.signal(signal.SIGALRM, over)
    signal.alarm(seconds)
    try:
        yield
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, before)


def lookup(module: str, name: str):
    try:
        found = importlib.import_module(module)
    except ImportError as exc:
        raise Skip(f"this kernel has no {module}") from exc
    if not hasattr(found, name):
        raise Skip(f"this kernel has no {module}.{name}")
    return getattr(found, name)


class Capture:
    """One kernel's answers, each as a canonical JSON file under the job's output folder."""

    def __init__(self, job: dict, clock: Clock):
        self.job = job
        self.clock = clock
        self.out = job["out"]
        self.skipped = {}
        self.errors = []
        self.written = []
        self.names = set()
        # longest first: the workspace is inside the sandbox, and each is named by what it is
        self.places = sorted(
            ((path, token) for token, paths in job["places"].items() for path in paths if path),
            key=lambda pair: -len(pair[0]),
        )
        self.routes = None
        self.seen = self._stats()

    # ---- canonical form ----

    def scrub(self, text: str) -> str:
        for path, token in self.places:
            text = text.replace(path, token)
        return ADDRESS.sub("0x0", text)

    def plain(self, value):
        """The value as JSON holds it, the same for the same answer: keys sorted when written, a set in order, a path of
        the sandbox or of the kernel's checkout replaced by its name."""
        if isinstance(value, dict):
            return {self.scrub(str(key)): self.plain(item) for key, item in value.items()}
        if isinstance(value, (list, tuple)):
            return [self.plain(item) for item in value]
        if isinstance(value, (set, frozenset)):
            return sorted(
                (self.plain(item) for item in value), key=lambda item: json.dumps(item, sort_keys=True, default=str)
            )
        if isinstance(value, str):
            return self.scrub(value)
        if isinstance(value, bytes):
            return {"bytes": len(value), "sha256": hashlib.sha256(value).hexdigest()}
        if value is None or isinstance(value, (bool, int, float)):
            return value
        if hasattr(value, "pattern") and isinstance(value.pattern, str):
            return {"pattern": self.scrub(value.pattern)}
        return self.scrub(repr(value))

    def file_name(self, name: str) -> str:
        """views/<family>/<item>.json: an item is named by its own id, made safe for a file name."""
        parts = [re.sub(r"[^A-Za-z0-9._-]", "_", part) or "_" for part in name.split("/")]
        safe = "/".join(parts)
        if safe in self.names:
            safe += "-" + hashlib.sha256(name.encode()).hexdigest()[:8]
        self.names.add(safe)
        return os.path.join("views", safe + ".json")

    def write(self, name: str, document: dict) -> None:
        relative = self.file_name(name)
        path = os.path.join(self.out, relative)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(self.plain(document), handle, sort_keys=True, indent=1, ensure_ascii=False)
            handle.write("\n")
        self.written.append(relative)

    def view(self, name: str, make, seconds: int = 0):
        """Capture one answer. What the kernel raises is the answer too: both kernels must raise the same."""
        os.environ["REPLAY_VIEW"] = name
        self.clock.reset()
        value = None
        try:
            with limit(seconds or int(self.job.get("view_seconds") or 120)):
                value = make()
            document = {"result": value}
        except Skip as skip:
            self.skipped[name] = str(skip)
            return None
        except Exception as exc:  # noqa: BLE001 - whatever a read path raises is what the page would have got
            status = getattr(exc, "status_code", None)
            if isinstance(status, int):
                document = {"http": status, "detail": getattr(exc, "detail", "")}
            else:
                document = {"error": f"{type(exc).__name__}: {exc}"}
                self.errors.append(name)
        except SystemExit as exc:
            document = {"exit": exc.code if isinstance(exc.code, int) else str(exc.code)}
        self.write(name, document)
        return value

    # ---- what a phase wrote in the sandbox ----

    def _stats(self) -> dict:
        found = {}
        for token, top in self.job["watched"].items():
            for folder, _dirs, files in os.walk(top):
                for name in files:
                    if name.startswith(".") and name.endswith(
                        (".lock", ".tmp")
                    ):  # a kernel's locks and temp files are no records
                        continue
                    path = os.path.join(folder, name)
                    try:
                        seen = os.lstat(path)
                    except OSError:
                        continue
                    found[path] = (token, seen.st_size, seen.st_mtime_ns)
        return found

    def settle(self) -> dict:
        """The files written since the last call, each by its scrubbed content's hash, and their mtime set to the replay's
        moment: a later view that reads a file's age reads the same one in every capture."""
        now = self._stats()
        changed = {}
        for path, (token, size, mtime) in now.items():
            if self.seen.get(path) == (token, size, mtime):
                continue
            top = self.job["watched"][token]
            relative = token + "/" + os.path.relpath(path, top)
            try:
                raw = open(path, "rb").read()
                os.utime(path, (self.clock.start, self.clock.start))
            except OSError:
                continue
            try:
                digest = hashlib.sha256(self.scrub(raw.decode("utf-8")).encode("utf-8")).hexdigest()
            except UnicodeDecodeError:
                digest = hashlib.sha256(raw).hexdigest()
            changed[relative] = digest
        for path, (token, _size, _mtime) in self.seen.items():
            if path not in now:
                changed[token + "/" + os.path.relpath(path, self.job["watched"][token])] = "removed"
        self.seen = self._stats()
        return changed

    # ---- the routes, as the Desktop calls them ----

    def route(self, path: str):
        if self.routes is None:
            router = lookup("dashboard.cockpit.router", "router")
            origin = os.path.realpath(sys.modules["dashboard.cockpit.router"].__file__)
            if not origin.startswith(os.path.realpath(self.job["kernel"]) + os.sep):
                raise Skip("this interpreter loads the dashboard from another checkout than the kernel asked for")
            self.routes = {
                route.path: route.endpoint
                for route in router.routes
                if "GET" in (getattr(route, "methods", None) or ())
            }
        if path not in self.routes:
            raise Skip(f"this kernel has no route GET {path}")
        return self.routes[path]


# The Desktop's reads that take no argument: (view, route). Each is the function behind that route, called as the page calls it.
PAGES = (
    ("outbox/list", "/list"),
    ("inbox/needs-you", "/needs-you"),
    ("standup/stored", "/standup"),
    ("board/board", "/board"),
    ("board/lane-runs", "/lane-runs"),
    ("tickets/index", "/tickets"),
    ("qa/index", "/qa"),
    ("platform/map", "/platform"),
    ("platform/advisories", "/advisories"),
    ("platform/bumps", "/bumps"),
    ("inbox/refusals", "/refusals"),
    ("settings/settings", "/settings"),
    ("settings/capacity", "/capacity"),
    ("settings/screen", "/screen"),
    ("settings/repos", "/repos"),
    ("settings/intent-types", "/intent-types"),
    ("settings/kickoff-modes", "/kickoff-modes"),
    ("settings/desktop-overrides", "/desktop-overrides"),
    ("settings/plugin-pages", "/plugin-pages"),
    ("settings/sweep-state", "/sweep-state"),
    ("settings/shared-chrome", "/shared-chrome"),
    ("settings/worktrees", "/worktrees"),
)
# Routes a replay leaves alone, and why: named in the manifest so nobody reads their absence as a pass.
LEFT_OUT = {
    "/update": "it describes the kernel's own checkout, which differs between two kernels by definition",
    "/usage": "it reads the installation's session databases and the coding tool's transcripts, not the records",
    "/pace": "it reads the installation's sessions and asks the provider for the plan windows",
    "/slots": "it asks the slot provider (containers on this machine), not the records",
    "/helpers": "it runs the pack's own status scripts against the live stack, not the records",
    "/demo": "it reads live demo sessions",
    "/session-card": "it reads a live session",
    "/chat-read": "it reads a live terminal",
    "/chat-state": "it reads a live terminal",
    "/coding-sessions": "it reads the coding tool's transcripts",
    "/coding-tail": "it reads the coding tool's transcripts",
    "/lane-tail": "it reads a live lane's log",
    "/jobs": "it reads this process's own background jobs",
    "/job-stream": "it streams a live job",
    "/lane-stream": "it streams a live lane",
    "/diff": "it reads git checkouts, which are not in the sandbox",
    "/pr-diff": "it asks the forge for a diff",
    "/platform-change": "it asks the forge for one change",
    "/platform-node-diff": "it reads git checkouts, which are not in the sandbox",
    "/qa-file": "it serves one evidence file's bytes; the QA views list every file with its size",
    "/sweep-log": "it reads the gatekeeper's live log",
}


def _records(folder: str) -> list:
    """Every JSON record of a folder, read plainly: (file name, record)."""
    found = []
    for name in os.listdir(folder) if os.path.isdir(folder) else []:
        if not name.endswith(".json"):
            continue
        try:
            record = json.load(open(os.path.join(folder, name), encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(record, dict):
            found.append((name, record))
    return found


def views(capture: Capture) -> None:
    """Every read path that matters, in a fixed order; then the passes that write, last, so no view reads what they left."""
    job = capture.job
    effects = {}
    load_pack = lookup("cockpitlib.pack", "load")
    pack = load_pack(job["pack"])
    paths = importlib.import_module("cockpitlib.paths")
    capture.view("pack/loaded", lambda: load_pack(job["pack"]))
    capture.view("pack/effective", lambda: effective())
    effects["pack"] = capture.settle()

    listed = {}
    for name, path in PAGES:
        listed[name] = capture.view(name, lambda path=path: capture.route(path)())
        effects[name] = capture.settle()
    for path, why in LEFT_OUT.items():
        capture.skipped[f"route {path}"] = why

    # each intent as its pane reads it: the list row, enriched (the function behind GET /intent)
    rows = (listed.get("outbox/list") or {}).get("rows") or [] if isinstance(listed.get("outbox/list"), dict) else []
    for row in rows:
        iid = str(row.get("id") or "")
        capture.view(
            f"outbox/intent/{iid}",
            lambda row=row: lookup("cockpitlib.intent_view", "enrich")(json.loads(json.dumps(row, default=str)), pack),
        )
    effects["outbox/intent"] = capture.settle()

    # the skills each intent type and each card kind requires, as the gate and the list look them up
    def required():
        types = list(lookup("cockpitlib.intents", "TYPES"))
        declared = (pack.get("skills") or {}).get("intent") or {}
        kinds = sorted(set(types) | {str(key) for key in declared})
        by_type = {kind: lookup("cockpitlib.gate", "_required_skills")(pack, kind) for kind in kinds}
        cards = {
            kind: lookup("cockpitlib.kanban", "card_skills")(pack, kind)
            for kind in sorted(lookup("cockpitlib.registry", "card_kinds")(pack))
        }
        return {"intent": by_type, "declared": {kind: declared.get(kind) for kind in kinds}, "card": cards}

    capture.view("skills/required", required)

    def missing():
        intents = lookup("cockpitlib.intents", "all_intents")()
        return {str(item.get("id")): lookup("cockpitlib.skill_log", "missing")(pack, item) for item in intents}

    capture.view("skills/missing", missing)
    effects["skills"] = capture.settle()

    # tickets: the Tickets page's row, and the QA page, per ticket
    tickets = set()
    index = listed.get("tickets/index")
    for row in (index.get("tickets") or []) if isinstance(index, dict) else []:
        tickets.add(str(row.get("ticket") or ""))
    qa_root = paths.qa()
    folders = (
        [name for name in os.listdir(qa_root) if os.path.isdir(os.path.join(qa_root, name))]
        if os.path.isdir(qa_root)
        else []
    )
    for ticket in sorted(tickets | set(folders)):
        if not ticket:
            continue
        capture.view(f"tickets/ticket/{ticket}", lambda ticket=ticket: capture.route("/ticket")(ticket=ticket))
    effects["tickets/ticket"] = capture.settle()
    for ticket in sorted(folders):
        capture.view(f"qa/ticket/{ticket}", lambda ticket=ticket: capture.route("/qa")(ticket=ticket))
    effects["qa/ticket"] = capture.settle()

    # pull requests: what the watch follows, its Inbox rows, and each record as the page reads it
    capture.view("pr/watched", lambda: lookup("cockpitlib.pr_watch", "watched")())
    capture.view("pr/inbox-rows", lambda: lookup("cockpitlib.pr_watch", "inbox_rows")())
    capture.view("pr/merge-ready", lambda: lookup("cockpitlib.pr_watch", "merge_ready")())
    known = []
    for ticket in [*sorted(folders), ""]:
        folder = os.path.join(qa_root, ticket, "pr") if ticket else os.path.join(paths.platform_dir(), "pr")
        for _name, record in _records(folder):
            if record.get("repo") and record.get("number"):
                known.append((ticket, str(record["repo"]), record["number"]))
    for ticket, repo, number in known:
        capture.view(
            f"pr/state/{ticket or '_platform'}/{repo}-{number}",
            lambda ticket=ticket, repo=repo, number=number: capture.route("/pr")(
                repo=repo, number=number, ticket=ticket
            ),
        )
    for ticket in sorted(folders):
        capture.view(f"pr/of-ticket/{ticket}", lambda ticket=ticket: lookup("cockpitlib.pr_watch", "prs_of")(ticket))
    effects["pr"] = capture.settle()

    # CI: each commit's record as the Inbox shows it
    for ticket in sorted(folders):
        for name, record in _records(os.path.join(qa_root, ticket, "ci")):
            repo, sha = str(record.get("repo") or ""), str(record.get("sha") or "")
            if not repo or not sha:
                continue
            capture.view(
                f"ci/state/{ticket}/{name[:-5]}",
                lambda ticket=ticket, repo=repo, sha=sha: lookup("cockpitlib.ci_watch", "state_for")(
                    ticket, repo, sha, pack
                ),
            )
    capture.view("ci/commits", lambda: lookup("cockpitlib.ci_watch", "commits")(pack))
    effects["ci"] = capture.settle()

    # the board's cards, each as its pane reads it
    board = listed.get("board/board")
    cards = []
    if isinstance(board, dict):
        for value in board.values():
            for card in value if isinstance(value, list) else []:
                if isinstance(card, dict) and card.get("id"):
                    cards.append(str(card["id"]))
    for card in sorted(set(cards)):
        capture.view(f"board/card/{card}", lambda card=card: capture.route("/card-detail")(id=card))
    effects["board/card"] = capture.settle()

    # the Inbox's other rows and the standup, built now
    capture.view("inbox/plugin-rows", lambda: lookup("cockpitlib.inbox", "rows")(pack))
    capture.view("inbox/tracker-notes", lambda: lookup("cockpitlib.tracker_watch", "rows")())
    capture.view("inbox/open-cards", lambda: lookup("cockpitlib.kanban", "open_card_rows")(pack["board"], pack))
    capture.view(
        "standup/draft",
        lambda: lookup("cockpitlib.standup_note", "draft")(pack, capture.clock.start - 86400, capture.clock.start),
    )
    effects["inbox"] = capture.settle()

    # last, the passes that write: the numbered digest, the morning digest, and one read of every watched PR
    capture.view("digest/numbered", lambda: lookup("cockpitlib.gate", "digest")(pack))
    effects["digest/numbered"] = capture.settle()

    def morning():
        said = lookup("cockpitlib.ops", "morning_digest")(pack)
        path = os.path.join(paths.platform_dir(), "digest.md")
        return {"said": said, "digest": open(path, encoding="utf-8").read() if os.path.isfile(path) else None}

    capture.view("digest/morning", morning)
    effects["digest/morning"] = capture.settle()

    def read_pr(ticket, repo, number):
        pr_watch = importlib.import_module("cockpitlib.pr_watch")
        forge = lookup("cockpitlib.publish", "forge_for")(pack)
        lookup("cockpitlib.pr_watch", "read")(pack, forge, ticket, repo, number, capture.clock.start)
        path = pr_watch.record_path(ticket, repo, number)
        return json.load(open(path, encoding="utf-8"))  # the record the pass wrote, not what it returned

    try:
        watched = [tuple(item) for item in lookup("cockpitlib.pr_watch", "watched")()]
    except Exception:  # noqa: BLE001 - pr/watched above already holds what it raised
        watched = []
    for ticket, repo, number in watched:
        capture.view(
            f"pr_watch/read/{ticket or '_platform'}/{repo}-{number}",
            lambda ticket=ticket, repo=repo, number=number: read_pr(ticket, repo, number),
        )
    effects["pr_watch/read"] = capture.settle()
    capture.write("effects/written", {"result": effects})


def effective():
    """`cockpit pack effective --json --sources` of this kernel, when it has the verb."""
    main = lookup("cockpitlib.cli", "main")
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            status = main(["pack", "effective", "--json", "--sources"])
        except SystemExit as exc:
            status = exc.code if isinstance(exc.code, int) else 1
    if status == 2:
        raise Skip("this kernel has no `cockpit pack effective`")
    try:
        said = json.loads(out.getvalue())
    except ValueError:
        said = out.getvalue()
    return {"exit": status, "effective": said}


def literal_host(pattern: str) -> str:
    """A host a production pattern matches: the pattern without its regular-expression marks."""
    text = re.sub(r"\\b|\\B|^\^|\$$", "", str(pattern))
    return re.sub(r"\\(.)", r"\1", text)


def pack_file(path: str):
    """One YAML file of the pack as this kernel reads it: personal values filled in where the kernel knows them, a name
    that is not set left as written. An older kernel reads the file as it is."""
    import yaml

    try:
        return lookup("cockpitlib.pack_local", "read")(path, unset=[])
    except Skip:
        with open(path, encoding="utf-8") as handle:
            return yaml.safe_load(handle)


def corpus(job: dict) -> list:
    """The fixed command corpus with its places filled in: (key, command). A line that names a production host is asked
    once for each host the pack's own egress.yaml lists."""

    folder = os.path.dirname(job["pack"])

    def read(name: str) -> dict:
        try:
            data = pack_file(os.path.join(folder, name)) or {}
        except Exception:  # noqa: BLE001 - a pack file this kernel cannot read names no host of its own
            return {}
        return data if isinstance(data, dict) else {}

    hosts = [literal_host(item) for item in read("egress.yaml").get("production_hosts") or [] if str(item)] or [
        "production.example.test"
    ]
    head = read("pack.yaml")
    fills = {
        "org": str((head.get("forge") or {}).get("org") or "example"),
        "workspace": job["env"]["COCKPIT_WORKSPACE"],
        "home": job["env"]["COCKPIT_HERMES_HOME"],
        "wt": job["env"]["COCKPIT_WT"],
        "volumes": job["env"]["COCKPIT_VOLUMES"],
    }
    found = []
    number = 0
    for line in open(job["commands"], encoding="utf-8"):
        text = line.rstrip("\n")
        if not text.strip() or text.lstrip().startswith("#"):
            continue
        number += 1
        for name, value in fills.items():
            text = text.replace("{" + name + "}", value)
        if "{host}" in text:
            found += [(f"{number:03d}.{index}", text.replace("{host}", host)) for index, host in enumerate(hosts, 1)]
        else:
            found.append((f"{number:03d}", text))
    return found


def fence(capture: Capture) -> None:
    """The decision string for each command of the corpus, as this process's seat gets it (COCKPIT_LANE is the job's)."""
    job = capture.job
    commands = corpus(job)

    def decide():
        if job["seat"] == "editor":  # an editor session outside the lanes: the guard its shell hook asks
            guard = lookup("cockpitlib.fence", "guard_reason")
            pack = lookup("cockpitlib.pack", "load")(job["pack"])
            return [{"key": key, "command": command, "decision": guard(command, pack)} for key, command in commands]
        check = lookup("cockpitlib.egress", "check_tool")
        explained = lookup("cockpitlib.egress", "explained")
        return [
            {"key": key, "command": command, "decision": explained(check("terminal", {"command": command}))}
            for key, command in commands
        ]

    capture.view(f"fence/{job['seat']}", decide, seconds=600)
    capture.write(f"effects/fence-{job['seat']}", {"result": capture.settle()})


def describe(capture: Capture) -> dict:
    """What the tool needs from the pack to cut a snapshot: the records folder's name and the board's slug."""
    import yaml

    paths = importlib.import_module("cockpitlib.paths")
    try:
        board = str(lookup("cockpitlib.pack", "load")(capture.job["pack"])["board"])
    except Exception:  # noqa: BLE001 - a pack that does not load away from its workspace still names its board
        head = yaml.safe_load(open(capture.job["pack"], encoding="utf-8")) or {}
        board = str(head.get("board") or "") if isinstance(head, dict) else ""
    # asked of the kernel's own path, not of a name it may not have: an older kernel keeps its records where it always did
    return {"records": os.path.relpath(paths.records(), paths.workspace()), "board": board}


def main(argv: list) -> int:
    job = json.load(open(argv[0], encoding="utf-8"))
    clock = Clock(job["clock"])
    tried = []
    libraries()
    freeze(clock)
    deny_network(tried)
    sorted_folders()
    kernel = job["kernel"]
    sys.path[:0] = [os.path.join(kernel, "kernel"), kernel]
    import cockpitlib

    home = os.path.realpath(os.path.dirname(os.path.dirname(os.path.abspath(cockpitlib.__file__))))
    if home != os.path.realpath(os.path.join(kernel, "kernel")):
        print(f"replay: this interpreter loads cockpitlib from {home}, not from the kernel asked for", file=sys.stderr)
        return 3
    capture = Capture(job, clock)
    answer = {}
    if job["mode"] == "describe":
        answer = describe(capture)
    elif job["mode"] == "fence":
        fence(capture)
    else:
        views(capture)
    answer.update(
        {
            "written": capture.written,
            "skipped": capture.skipped,
            "errors": capture.errors,
            "network": sorted(set(tried)),
        }
    )
    with open(job["answer"], "w", encoding="utf-8") as handle:
        json.dump(answer, handle, sort_keys=True, indent=1)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
