# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
import os
import re
import shutil
import subprocess

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PACK = os.path.join(ROOT, "packs", "acme", "pack.yaml")


from cockpitlib import sandbox  # noqa: E402 - the workspace every fixture below stands on; `cockpit demo` builds the same

GIT_CONFIG = sandbox.GIT_CONFIG


def _plain_git(monkeypatch) -> None:
    sandbox.plain_git(monkeypatch.setenv)


# gpg-agent listens on a socket inside its GPG home, and a socket path holds about a hundred characters. macOS hands out a
# temp folder that is fifty-odd long already (/var/folders/…/T), so a test's GPG home under it ends past the limit and
# every key generation fails with "can't connect to the gpg-agent: File name too long". The run's temp root is /tmp
# there, and a test's folder has a short name (tmp_path below).
if (
    len(os.path.realpath(__import__("tempfile").gettempdir())) > 24
    and os.path.isdir("/tmp")
    and not os.environ.get("PYTEST_DEBUG_TEMPROOT")
):
    os.environ["PYTEST_DEBUG_TEMPROOT"] = "/tmp"


# The sandbox does not hang on a fixture: the process itself, from the moment this file is read, has an empty Hermes
# home of the run and none of the binding a shell may carry. A test that undoes its monkeypatch (which also undoes the
# fixtures' own) then finds no workspace at all (paths.workspace() raises NeedMigrate), never this machine's. Every
# xdist worker reads this file, and a process a test starts inherits the same.
_REAL_HOME = os.path.realpath(os.path.expanduser("~/.hermes"))
_SANDBOX_HOME = os.path.realpath(
    __import__("tempfile").mkdtemp(prefix="ch-", dir=os.environ.get("PYTEST_DEBUG_TEMPROOT") or None)
)
__import__("atexit").register(shutil.rmtree, _SANDBOX_HOME, ignore_errors=True)
os.environ["COCKPIT_HERMES_HOME"] = _SANDBOX_HOME
for _name in ("COCKPIT_WORKSPACE", "COCKPIT_ROOT", "COCKPIT_PACK", "COCKPIT_LANE"):
    os.environ.pop(_name, None)


def _inside(path: str, folder: str) -> bool:
    path, folder = os.path.realpath(path), os.path.realpath(folder)
    return path == folder or path.startswith(folder + os.sep)


@pytest.fixture(scope="session", autouse=True)
def the_run_never_resolves_the_machines_installation():
    """The run stops before its first test when the kernel would read or write this machine's Hermes home."""
    from cockpitlib import paths

    home = paths.hermes_home()
    assert (
        not _inside(home, _REAL_HOME) and not _inside(home, os.path.expanduser("~")) or _inside(home, _SANDBOX_HOME)
    ), f"the tests would use the real installation at {home}: tests/conftest.py must set COCKPIT_HERMES_HOME first"
    assert not any(os.environ.get(name) for name in ("COCKPIT_WORKSPACE", "COCKPIT_ROOT", "COCKPIT_PACK")), (
        "a real binding is in the environment"
    )
    yield


@pytest.fixture
def tmp_path(tmp_path_factory):
    """pytest names a test's folder after the test (up to thirty characters); `t<n>` keeps a GPG home under it in reach."""
    return tmp_path_factory.mktemp("t")


_RUN = subprocess.run  # the real one: a test may replace subprocess.run or empty PATH before teardown
_GPGCONF = __import__("shutil").which("gpgconf") or ""


def _stop_agent(home: str) -> None:
    """Stop the gpg-agent of a test's GPG home; never fails a test."""
    if not _GPGCONF:
        return
    try:
        _RUN([_GPGCONF, "--homedir", home, "--kill", "gpg-agent"], capture_output=True, check=False, timeout=20)
    except Exception:  # noqa: BLE001 - housekeeping: a test may have replaced subprocess.Popen itself
        pass


@pytest.fixture(autouse=True)
def no_machine_binding(monkeypatch, tmp_path_factory):
    """No test reads this machine's installation: the Hermes home is an empty folder of the run, and the workspace, the
    pack and the lane a shell may carry are dropped. A test that needs a workspace names one (the env fixture, or its
    own setenv); without this a test passed on a machine with a bound workspace and failed on one without."""
    monkeypatch.setenv("COCKPIT_HERMES_HOME", str(tmp_path_factory.mktemp("h")))
    for name in ("COCKPIT_WORKSPACE", "COCKPIT_ROOT", "COCKPIT_PACK", "COCKPIT_LANE"):
        monkeypatch.delenv(name, raising=False)


def _held_keys(home: str) -> bool:
    """A GPG home something was kept in: gpg makes these the first time it is used there, and only then is there an
    agent to stop. The env fixture's own home stays empty in most tests, and stopping nothing cost a process each."""
    return any(os.path.exists(os.path.join(home, name)) for name in ("pubring.kbx", "private-keys-v1.d", "trustdb.gpg"))


@pytest.fixture(autouse=True)
def plain_git(monkeypatch, tmp_path_factory):
    """Every test's git, the env fixture's or not, uses GIT_CONFIG above over the machine's global config. A test that
    points GNUPGHOME into its temp folder has its gpg-agent stopped afterwards (they were left running, dozens a run)."""
    _plain_git(monkeypatch)
    before = os.environ.get("GNUPGHOME", "")
    yield
    home = os.environ.get("GNUPGHOME", "")
    base = str(tmp_path_factory.getbasetemp())
    if home and home != before and os.path.realpath(home).startswith(os.path.realpath(base)) and _held_keys(home):
        _stop_agent(home)


@pytest.fixture(autouse=True)
def forge_transcript(request, monkeypatch):
    """With FORGE_TRANSCRIPT_DIR set, each test's forge calls, tracker requests and watcher records are kept there (tests/support/forge_transcript.py)."""
    if not os.environ.get(
        "FORGE_TRANSCRIPT_DIR"
    ):  # not recording: nothing to load, in this suite or in a copy of this file
        yield
        return
    from tests.support import forge_transcript as recorder

    started = __import__("time").time()
    stem = recorder.begin(request.node.nodeid, monkeypatch.setenv)
    if stem:
        recorder.watch_commands(monkeypatch.setattr)
    yield
    if stem:
        recorder.end(stem, started)


REPOS = ("api", "web", "ledger", "site")  # acme's repos and bravo's


@pytest.fixture(scope="session")
def repos_template(tmp_path_factory):
    """The fixture repos, made once a worker: each with one commit on main and a bare origin it has pushed to and
    fetched from, as a forge would be, so pushes and their read-backs are real git. A test gets its own copy
    (_copy_repos): making them anew took some thirty git calls and over a second of every test."""
    root = tmp_path_factory.mktemp("repos-template")
    sandbox.repos(str(root), REPOS)
    return root


def _copy_repos(template: str, root: str) -> None:
    """A test's own repos and origins under root, copied from the template; each origin is the copy's, not the template's."""
    sandbox.copy_repos(template, root, REPOS)


def _workspace(tmp_path, monkeypatch) -> dict:
    """A test's workspace, Hermes home, pack and PATH, named in its shell: all of the env fixture but the repos."""
    made = sandbox.shell(
        str(tmp_path),
        monkeypatch.setenv,
        lambda name: monkeypatch.delenv(name, raising=False),
        PACK,
        homes=("acme", "bravo"),
        path=os.path.join(ROOT, "tests", "bin"),
    )
    return {name: tmp_path / os.path.basename(value) for name, value in made.items()}


@pytest.fixture
def env(tmp_path, monkeypatch, repos_template):
    made = _workspace(tmp_path, monkeypatch)
    _copy_repos(str(repos_template), str(made["root"]))
    return made


@pytest.fixture
def bare(tmp_path, monkeypatch):
    """`env` without its four git repos: the same workspace, Hermes home, pack and PATH, over an empty root, for a
    test that reads records, the board, the pack or pure functions and never a checkout, a worktree or a remote."""
    made = _workspace(tmp_path, monkeypatch)
    made["root"].mkdir()
    return made


@pytest.fixture
def jira(monkeypatch):
    """The tracker stand-in on a local port; the pack's tracker reads it with credentials from this shell."""
    from tests.support.fake_jira import Jira, serve

    found = Jira()
    url, stop = serve(found)
    found.url = url
    from cockpitlib import tracker

    real = tracker._config
    monkeypatch.setattr(tracker, "_config", lambda pack: {**real(pack), "url": url})
    for name in ("ACME_TRACKER_EMAIL", "NORTH_TICKETS_USER"):
        monkeypatch.setenv(name, "human@example.test")
    for name in ("ACME_TRACKER_TOKEN", "NORTH_TICKETS_KEY"):
        monkeypatch.setenv(name, "token-1")
    yield found
    stop()


def _homes_with_keys(base: str) -> list:
    """Every GPG home under base that something was kept in, found by walking it: the slow way, for a machine without ps."""
    return [
        folder
        for folder, dirs, files in os.walk(base)
        if "pubring.kbx" in files or "private-keys-v1.d" in dirs or "trustdb.gpg" in files
    ]


def _running_agent_homes(base: str):
    """The GPG homes under base whose gpg-agent is still running, read from the process list; None when it cannot be read."""
    try:
        listed = _RUN(["ps", "-axo", "command="], capture_output=True, text=True, check=False, timeout=20)
    except Exception:  # noqa: BLE001 - no ps here: the caller walks instead
        return None
    if listed.returncode != 0:
        return None
    real = os.path.realpath(base)
    homes = []
    for line in listed.stdout.splitlines():
        match = re.search(r"gpg-agent --homedir (.+?) (?:--use-standard-socket )?--daemon", line)
        if match and os.path.realpath(match.group(1)).startswith(real + os.sep):
            homes.append(match.group(1))
    return homes


@pytest.fixture(autouse=True, scope="session")
def _stop_test_gpg_agents(tmp_path_factory):
    """Tests that switch GNUPGHOME between several homes start an agent in each: stop every one still running under
    this run's temp folder when the run ends, so no gpg-agent outlives the suite. Only those: asking every home that
    ever held a key cost a third of a second each, an agent or not, after a walk of every test's folders."""
    yield
    base = str(tmp_path_factory.getbasetemp())
    homes = _running_agent_homes(base)
    for home in _homes_with_keys(base) if homes is None else homes:
        _stop_agent(home)


# ---------- bug reports ----------
# A report is one test under tests/reports/ that states the rule the code breaks today:
#     @pytest.mark.known_bug("kernel/cockpitlib/window.py:40", "a day without records crashes the note")
# While its assertion fails the run stays green and the report is listed. Once it passes the run fails and asks for the
# marker to be dropped. Anything but a failed assertion in the test's own body (an import, a fixture, a typo) is an
# ordinary failure: a report that cannot run reports nothing.
KNOWN_BUG = "known_bug"
FIXED = (
    "the bug this report describes is fixed ({where}: {what}). Remove the known_bug marker and move the file from "
    "tests/reports/ into tests/: it is a plain test now."
)


def _known_bug(item):
    """(where, what) of a report's marker, or None; a marker without both texts is a usage error, not a report."""
    mark = item.get_closest_marker(KNOWN_BUG)
    if mark is None:
        return None
    if len(mark.args) != 2 or mark.kwargs or not all(isinstance(text, str) and text.strip() for text in mark.args):
        raise pytest.UsageError(
            f"{item.nodeid}: known_bug takes two texts, e.g. "
            '@pytest.mark.known_bug("kernel/cockpitlib/window.py:40", "an empty day crashes the note")'
        )
    return mark.args[0].strip(), mark.args[1].strip()


def pytest_collection_modifyitems(items):
    for item in items:
        _known_bug(item)


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    """A report's own failed assertion is the expected outcome and its pass fails the run; every other outcome stands."""
    outcome = yield
    report = outcome.get_result()
    told = _known_bug(item)
    if told is None or call.when != "call":
        return
    where, what = told
    if call.excinfo is None:
        report.outcome = "failed"
        report.longrepr = "FIXED: " + FIXED.format(where=where, what=what)
    elif isinstance(call.excinfo.value, AssertionError):
        report.outcome = "skipped"
        report.wasxfail = f"{KNOWN_BUG} ({where}): {what}"


def pytest_terminal_summary(terminalreporter):
    """One line per open report, so a run's output is also the list of known bugs."""
    for report in terminalreporter.stats.get("xfailed", []):
        told = str(getattr(report, "wasxfail", ""))
        if told.startswith(KNOWN_BUG + " ("):
            terminalreporter.write_line(f"BUG {report.nodeid} {told[len(KNOWN_BUG) + 1 :]}")
