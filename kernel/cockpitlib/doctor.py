# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Health of a bound workspace. A red doctor is a failed setup."""

import os
import re

from .egress import check
from .lanes import seats_from
from .pack import extra_plugins_for, plugin_root, seat_skills_for
from .paths import hermes_home
from .setup import (
    CRON_JOBS,
    calls_tools,
    cron_home,
    cron_plan,
    gateway_status,
    plugin_enabled,
    plugin_present,
    profile_dir,
    registered_jobs,
)
from .store import read_db

# The Hermes minor versions whose hook, board, delegation, and config shapes this plugin was checked against
# (recorded under tests/contract). A newer Hermes may change them, so doctor asks for a check before trusting it:
# a newer minor is accepted, with a note, only when a live probe of its hooks answers the recorded shapes (hook_probe).
HERMES_VERIFIED = ("0.22", "0.23")


VERSION_TIMEOUT = 180  # a fresh Hermes home prepares its runtime on the first call


def required_hermes() -> tuple:
    """(text, numbers) of the oldest Hermes the manifest asks for: plugin.yaml's `requires_hermes`, the one place that
    says it. ("", ()) when the manifest cannot be read or asks in another form: doctor then has no floor of its own."""
    import yaml

    try:
        with open(os.path.join(plugin_root(), "plugin.yaml"), encoding="utf-8") as handle:
            asked = str((yaml.safe_load(handle) or {}).get("requires_hermes") or "")
    except (OSError, yaml.YAMLError, AttributeError):
        return "", ()
    match = re.fullmatch(r">=\s*(\d+)\.(\d+)(?:\.(\d+))?", asked.strip())
    if not match:
        return "", ()
    numbers = tuple(int(part or 0) for part in match.groups())
    return ".".join(str(part) for part in numbers), numbers


def _hermes() -> dict:
    """{version, problem, note} about the running Hermes. The problem fails doctor: no Hermes, an unreadable version,
    one older than (or between) the versions this plugin was checked against, a newer major, or a newer minor whose
    live hook probe did not pass or could not run. The note does not fail it: a newer minor whose hooks answered the
    recorded shapes is accepted and says so; a probe that did not pass says why."""
    import shutil
    import subprocess

    hermes = shutil.which("hermes")
    if not hermes:
        return {"version": "", "problem": "hermes not found", "note": ""}
    try:
        done = subprocess.run(
            [hermes, "--version"], capture_output=True, text=True, timeout=VERSION_TIMEOUT, check=False
        )
    except subprocess.TimeoutExpired:
        return {"version": "", "problem": f"hermes --version did not answer within {VERSION_TIMEOUT} s", "note": ""}
    match = re.search(r"v(\d+)\.(\d+)\.(\d+)", done.stdout or "")
    if not match:
        return {"version": "", "problem": "hermes version unreadable", "note": ""}
    minor = f"{match.group(1)}.{match.group(2)}"
    version = match.group(0)[1:]
    if minor in HERMES_VERIFIED:
        floor, numbers = required_hermes()
        if numbers and tuple(int(part) for part in match.groups()) < numbers:
            # a checked minor, and a patch release before the one the manifest asks for
            older = f"hermes {version} is older than {floor}, the oldest version this plugin runs on (plugin.yaml requires_hermes)"
            return {"version": version, "problem": older, "note": ""}
        return {"version": version, "problem": "", "note": ""}
    unchecked = f"hermes {version} is not a version this plugin was checked against ({', '.join(HERMES_VERIFIED)})"
    newest = max(tuple(int(part) for part in known.split(".")) for known in HERMES_VERIFIED)
    if int(match.group(1)) != newest[0] or int(match.group(2)) < newest[1]:
        return {
            "version": version,
            "problem": unchecked,
            "note": "",
        }  # older, or another major: no probe makes up for that
    from .hook_probe import probe

    why = probe()
    if why:
        return {
            "version": version,
            "problem": unchecked,
            "note": f"hermes {version}: the live hook probe did not pass, so the version stays unaccepted: {why}",
        }
    return {
        "version": version,
        "problem": "",
        "note": f"hermes {version} is newer than the versions this plugin was checked against ({', '.join(HERMES_VERIFIED)}): "
        "its hooks answered the recorded shapes in a live probe, so doctor accepts it (the board, "
        "delegation and config shapes were not probed)",
    }


def hermes_check() -> dict:
    """{problem, note} about the running Hermes's version: the line that fails doctor, and the line that does not."""
    found = _hermes()
    return {"problem": found["problem"], "note": found["note"]}


def hermes_version_problem() -> str:
    """Empty when the running Hermes is a version this plugin was checked against, or a newer minor whose hooks passed
    the live probe."""
    return hermes_check()["problem"]


def notes(pack) -> list:
    """Lines doctor prints that do not fail it: what it accepted on a live check, or why a live check did not pass."""
    note = hermes_check()["note"]
    return [note] if note else []


COCKPIT = {"name": "cockpit", "provider": False}


def _plugin_problems(name, home, plugins=(COCKPIT,)) -> list:
    """register() runs for a profile only when its plugins/ holds the plugin and its plugins.enabled lists it.

    A provider plugin of the pack needs only its plugins/model-providers/ link.
    """
    problems = []
    for plugin in plugins:
        if not plugin_present(home, plugin["name"], plugin["provider"]):
            problems.append(f"{name} plugins/ lacks {plugin['name']}")
        if not plugin["provider"] and not plugin_enabled(home, plugin["name"]):
            problems.append(f"{name} plugins.enabled lacks {plugin['name']}")
    return problems


def _skill_problems(name, home, skills) -> list:
    return [
        f"{name} skills/ lacks {skill['name']}"
        for skill in skills
        if not os.path.isfile(os.path.join(home, "skills", skill["name"], "SKILL.md"))
    ]


def _env_file_problems(pack) -> list:
    """A seat env file holds secrets: it exists, only its owner reads it, and it is outside every git tree."""
    import subprocess

    from .pack import seat_env_files

    problems = []
    for kind in seats_from(pack):
        for path in seat_env_files(pack, kind):
            if not os.path.isfile(path):
                problems.append(f"env file missing {path}")
                continue
            if os.stat(path).st_mode & 0o077:
                problems.append(f"env file {path} is readable by others (chmod 600)")
            done = subprocess.run(
                ["git", "-C", os.path.dirname(path), "rev-parse", "--is-inside-work-tree"],
                capture_output=True,
                text=True,
                check=False,
            )
            if done.stdout.strip() == "true":
                problems.append(f"env file {path} is inside a git tree")
    return sorted(set(problems))


def _harness_problems(pack, lane, folder, env: str) -> list:
    """Under lanes.browser_session a seat's .env names its own browser-harness home; a seat rendered before the setting
    still shares the machine-wide one until it is re-rendered."""
    from .setup import seat_harness_home

    if seat_harness_home(pack, os.path.join(folder, ".env")) and not any(
        line.startswith("BH_HOME=") for line in env.splitlines()
    ):
        return [f"{lane} env lacks BH_HOME (lanes.browser_session): cockpit setup --rerender --seat {lane}"]
    return []


def last_providers(home, count: int = 2) -> list:
    """[(provider, started_at)] of this home's latest root sessions, newest first: a delegated child may run elsewhere.

    Empty when there are none or the database is unreadable. A `custom` provider is stored without its name, so it
    says nothing about which plugin ran.
    """
    import sqlite3

    path = os.path.join(home, "state.db")
    if not os.path.isfile(path):
        return []
    try:
        connection = read_db(path)
        try:
            columns = {row[1] for row in connection.execute("pragma table_info(sessions)")}
            if not {"billing_provider", "started_at"} <= columns:
                return []
            root = " and parent_session_id is null" if "parent_session_id" in columns else ""
            rows = connection.execute(
                "select billing_provider, started_at from sessions where started_at is not null "
                f"and billing_provider is not null and billing_provider != ''{root} order by started_at desc limit ?",
                (count,),
            ).fetchall()
        finally:
            connection.close()
    except sqlite3.Error:
        return []
    return [(str(provider), float(started or 0)) for provider, started in rows]


def provider_drift(home, configured: str):
    """The provider this home's last two root sessions both ran on when it is not the configured one, else "".

    Two plugins can claim one provider id; the loser's seats then run on the other plugin with no error anywhere. One
    session on another provider is a fallback or a /model switch, so it takes two in a row since the config was written.
    """
    config = os.path.join(home, "config.yaml")
    want = str(configured or "").strip().lower()
    if not want or want.startswith("custom") or not os.path.isfile(config):
        return ""
    rows = last_providers(home)
    if len(rows) < 2 or any(started <= os.path.getmtime(config) for _provider, started in rows):
        return ""
    used = {provider.strip().lower() for provider, _started in rows}
    if len(used) != 1 or want in used or any(name.startswith("custom") for name in used):
        return ""
    return rows[0][0]


def _dependencies(plugin) -> list:
    """The requirement strings a provider plugin declares (python_dependencies, or Hermes's pip_dependencies)."""
    import yaml

    try:
        meta = yaml.safe_load(open(os.path.join(plugin["path"], "plugin.yaml"), encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        return []
    if not isinstance(meta, dict):
        return []
    return [
        str(item).strip()
        for key in ("python_dependencies", "pip_dependencies")
        for item in meta.get(key) or []
        if str(item).strip()
    ]


def _same_provider(configured: str, used: str) -> bool:
    """Hermes resolves an alias (a short name) to its canonical id when it records the session; ask it whether two names are
    one provider. When Hermes cannot answer, they are taken as different."""
    from .hermes_runtime import run_helper

    try:
        found = (
            run_helper("plugins", {"ops": [{"op": "canonical", "names": [configured, used]}]}).get("results") or [{}]
        )[0]
    except Exception:  # noqa: BLE001 - a probe that cannot run answers no
        return False
    return (
        isinstance(found, dict)
        and "error" not in found
        and bool(found.get(configured))
        and found.get(configured) == found.get(used)
    )


def provider_problems(pack) -> list:
    """A seat runs on the provider its config names, and its provider plugins' dependencies are installed where Hermes runs.
    A provider whose dependency is missing fails only when a card first reaches it."""
    from .hermes_runtime import run_helper
    from .setup import _config_data

    problems = []
    for names in seats_from(pack).values():
        for lane in names:
            folder = profile_dir(lane)
            configured = str((_config_data(folder).get("model") or {}).get("provider") or "")
            used = provider_drift(folder, configured)
            if used and _same_provider(configured, used):
                used = ""
            if used:
                problems.append(
                    f"{lane} ran its last two sessions on provider {used}, configured {configured}: "
                    f"another provider plugin may claim {configured}"
                )
    wanted = sorted(
        {
            requirement
            for plugin in (pack.get("extra_plugins") or [])
            if plugin["provider"]
            for requirement in _dependencies(plugin)
        }
    )
    if not wanted:
        return problems
    try:
        found = (run_helper("plugins", {"ops": [{"op": "installed", "requirements": wanted}]}).get("results") or [{}])[
            0
        ]
    except Exception as exc:  # noqa: BLE001 - the failure is itself the finding
        return [*problems, f"provider dependencies not checked: {exc}"]
    if not isinstance(found, dict) or "error" in found:
        return [*problems, f"provider dependencies not checked: {found}"]
    return [
        *problems,
        *(
            f"Hermes's environment lacks {requirement}, a provider plugin's dependency"
            for requirement in wanted
            if found.get(requirement) is False
        ),
    ]


def _with_the_packs_rules(probe):
    """A probe that runs the pack's own patterns finds nothing when one of them cannot be read: that is another check's
    finding (egress.pattern-invalid, pack.text-for-list), and doctor goes on to say the rest instead of stopping."""
    import functools

    @functools.wraps(probe)
    def probed(pack) -> list:
        try:
            return probe(pack)
        except (re.error, TypeError):
            return []

    return probed


@_with_the_packs_rules
def host_problems(pack) -> list:
    """production_hosts refuses a production URL. A pattern anchored to hosts has no sample to derive, so a pack with
    egress host_probes says which commands must be refused and which must pass (a repo folder named like a host)."""
    egress = pack.get("egress") or {}
    hosts = egress.get("production_hosts") or []
    if not hosts:
        return ["egress production_hosts is empty"]
    probes = egress.get("host_probes") or {}
    if not probes:
        sample = str(hosts[0]).replace("\\.", ".")
        return [] if check(f"curl https://{sample}", production_hosts=hosts) else ["production host NOT blocked"]
    problems = [
        f"production host NOT blocked: {command}"
        for command in probes.get("refused") or []
        if not check(command, production_hosts=hosts)
    ]
    problems += [
        f"production_hosts refuses a command it must allow: {command}"
        for command in probes.get("allowed") or []
        if check(command, production_hosts=hosts)
    ]
    return problems


def allowed_read_problems(pack) -> list:
    """The allowed.reads entries the kernel refuses whatever a pack lists (a push, a forge write, a secret file): the
    entry never runs, and a pack that lists one means to let out what only the outbox lets out."""
    from .egress import _secret_read, kernel_refusal
    from .pack import policy

    return [
        f"allowed.reads lists a command the kernel refuses: {entry}"
        for entry in policy(pack)["reads"]
        if kernel_refusal(entry, pack) or _secret_read(entry)
    ]


PLAIN_READS = ("git status", "git diff", "git log")


@_with_the_packs_rules
def pack_read_problems(pack) -> list:
    """The plain reads the pack's own rules refuse to a worker (terminal_deny, refused.commands, the host lists, sacred,
    infra_paths, role_deny.worker, git_deny.worker): a lane that cannot ask git what changed cannot work. What the
    kernel itself refuses is another check's, and a read the pack lists under allowed.reads is past its denies."""
    from .egress import check, explained, git_moves
    from .pack import policy

    egress = pack.get("egress") or {}
    rules = policy(pack)
    deny = [*(egress.get("terminal_deny") or []), *(re.escape(item) for item in rules["commands"] if item)]
    hosts = [*(egress.get("production_hosts") or []), *(re.escape(item) for item in rules["hosts"] if item)]
    role = (egress.get("role_deny") or {}).get("worker") or []
    moves = (egress.get("git_deny") or {}).get("worker") or []
    problems = []
    for command in PLAIN_READS:
        if command in rules["reads"] or check(command):
            continue
        why = explained(check(command, deny, hosts, egress.get("sacred") or [], egress.get("infra_paths") or []))
        if not why:
            pattern = next((pattern for pattern in role if re.search(pattern, command)), "")
            why = f"role_deny.worker {pattern[:80]}" if pattern else ""
        if not why and git_moves(command, moves):
            why = f"git_deny.worker {git_moves(command, moves)}"
        if why:
            problems.append(f"the pack's own rules refuse {command} to a worker ({why}): its lanes cannot work")
    return problems


# What the hook walks entry by entry. The loader has never checked the shape of these four, so a pack that gives one
# as a single text loads, and its text is then walked letter by letter: every letter becomes a rule of its own.
EGRESS_LISTS = ("terminal_deny", "production_hosts", "sacred", "infra_paths")
# The two of them whose entries the hook reads as regular expressions (egress.check).
EGRESS_PATTERNS = ("terminal_deny", "production_hosts")


def _texts_for_lists(pack) -> list:
    """Where each list of the pack that is written as one text stands: the file, then the key."""
    egress = pack.get("egress") or {}
    places = ["egress.yaml " + key for key in EGRESS_LISTS if isinstance(egress.get(key), str)]
    for repo in (pack.get("repos") or {}).get("repos") or []:
        if isinstance(repo, dict) and isinstance(repo.get("gates"), str):
            places.append("repos.yaml " + str(repo.get("name")) + ".gates")
    return places


def text_for_list_problems(pack) -> list:
    """One line for every list of the pack that is written as one text: the four egress lists and a repo's gates. Such
    a pack loads, and has always loaded; what it then does is not what its author wrote."""
    return [
        f"{key} is one text where a list is expected: it is read letter by letter, each letter as an entry"
        for key in _texts_for_lists(pack)
    ]


def egress_pattern_problems(pack) -> list:
    """One line for every entry of terminal_deny and production_hosts that is no regular expression. The hook does not
    skip such a rule: egress.check raises on it, on every command that reaches it, so no call is judged at all."""
    from .pack import compiles

    egress = pack.get("egress") or {}
    found = []
    for key in EGRESS_PATTERNS:
        value = egress.get(key)
        for item in value if isinstance(value, list) else []:
            try:
                if not isinstance(item, str):
                    raise re.error("not a text")
                compiles(item)
            except re.error as exc:
                pattern = repr(str(item)[:80])
                found.append(f"egress.yaml {key}: {pattern} is no regular expression ({exc})")
    return found


def egress_key_problems(pack) -> list:
    """One line for each key of egress.yaml that no kernel code reads, with the known key it most resembles: a misspelt
    list is a rule that does not apply, silently."""
    import difflib

    from .pack_keys import EGRESS, entries, segments

    egress = pack.get("egress")
    if not isinstance(egress, dict):
        return []
    known = sorted({segments(entry["path"])[0] for entry in entries(EGRESS)})
    found = []
    for key in sorted(str(key) for key in egress if str(key) not in known):
        close = difflib.get_close_matches(key, known, n=1, cutoff=0.6)
        found.append(
            f"egress.yaml: unknown key {key}"
            + (f" (did you mean {close[0]}?)" if close else "")
            + ": no kernel code reads it"
        )
    return found


E, W, I = "error", "warning", "info"  # noqa: E741 - the three tiers by their initials


def _c(severity: str, fix: str, security: bool = False, born: bool = False) -> dict:
    """One registered check: its tier, whether it guards a boundary, the line that resolves it, and whether it was born
    with the tiers (a warning born then never failed doctor, so run() leaves it to findings())."""
    return {"severity": severity, "security": security, "fix": fix, "born": born}


SETUP = "cockpit setup"
RERENDER = "cockpit setup --rerender --seat {subject}"
REINSTALL = "the kernel's own deny list is damaged: put the plugin's code back (cockpit update apply)"

# Every line doctor can print, by a stable id. The tier is fixed here and nowhere else: no flag, environment variable or
# pack key reaches it, and tests/contract/doctor-security.json pins which ids guard a boundary. A fix may name {subject},
# {pack} (the pack's folder), {home} (the Hermes home), {plugin} (this plugin's folder) and {verified}.
CHECKS = {
    "prompt.missing": _c(E, "write that file, or correct the prompts entry in {pack}/pack.yaml"),
    "egress.push-blocked": _c(E, REINSTALL, security=True),
    "egress.forge-write-blocked": _c(E, REINSTALL, security=True),
    "egress.read-allowed": _c(E, REINSTALL),
    "egress.allowed-read-denied": _c(
        E,
        "take that line out of allowed.reads in {pack}/pack.yaml: the kernel refuses it whatever a pack "
        "lists, and an outward act goes through the outbox",
        security=True,
    ),
    "egress.pack-refuses-read": _c(
        E,
        "narrow that rule in {pack}/egress.yaml (or refused.commands in {pack}/pack.yaml) until git status, git diff "
        "and git log pass, or list the read under allowed.reads in {pack}/pack.yaml",
    ),
    "egress.unknown-key": _c(
        W, "rename that key in {pack}/egress.yaml to the key it was meant to be, or take it out", born=True
    ),
    "egress.pattern-invalid": _c(
        E,
        "correct that entry of {subject} in {pack}: while it is no regular expression the hook cannot read the rule, and "
        "raises on a command instead of judging it",
        security=True,
    ),
    "pack.text-for-list": _c(W, "write {subject} as a list in {pack}: one entry per line, each after `- `", born=True),
    "hermes.auto-decompose": _c(
        E, SETUP + " (it writes kanban.auto_decompose: false into {home}/config.yaml)", security=True
    ),
    "hermes.review-dispatch": _c(
        E, SETUP + " (it writes kanban.review_dispatch: false into {home}/config.yaml)", security=True
    ),
    "board.metadata": _c(E, SETUP),
    "egress.hook-allowlisted": _c(E, SETUP, security=True),
    "seat.not-applied": _c(E, SETUP),
    "seat.plugin": _c(E, SETUP, security=True),
    "seat.skill": _c(E, RERENDER),
    "seat.env-lane": _c(E, RERENDER, security=True),
    "seat.env-browser-home": _c(E, RERENDER, security=True),
    "seat.memory-full": _c(
        W,
        "shorten {home}/profiles/{subject}/memories/MEMORY.md under 600 characters, or divide its notes with a line holding §",
    ),
    "egress.production-hosts-empty": _c(
        E,
        "list one pattern per production hostname under production_hosts in {pack}/egress.yaml, "
        "or declare no_production_hosts: true when the project has no production",
        security=True,
    ),
    "egress.no-production": _c(I, "", born=True),
    "egress.production-host-blocked": _c(
        E, "correct the pattern under production_hosts in {pack}/egress.yaml until it refuses that host", security=True
    ),
    "egress.host-probe-allowed": _c(
        E,
        "narrow the pattern under production_hosts in {pack}/egress.yaml, or correct host_probes.allowed",
        security=True,
    ),
    "provider.drift": _c(
        W, "hermes --profile {subject} plugins list, then remove the provider plugin that claims the same id"
    ),
    "provider.dependencies-unchecked": _c(
        W, "cockpit doctor again once `hermes` answers: the provider plugins' requirements could not be asked"
    ),
    "provider.dependency-missing": _c(
        E,
        "install that requirement into the environment Hermes runs in (hermes --print-runtime-command names its Python)",
    ),
    "fence.editor-hook": _c(E, SETUP, security=True),
    "staging.missing": _c(
        W, "write {pack}/staging.yaml with an origins map, one name per origin (app: https://staging.example.test)"
    ),
    "staging.origins-empty": _c(W, "name at least one origin with its URL under origins in {pack}/staging.yaml"),
    "repos.no-gates": _c(W, "give one repo its test command under gates in {pack}/repos.yaml"),
    "agent.home-missing": _c(E, "create that folder, or correct agent.home in {pack}/pack.yaml"),
    "skills.router-missing": _c(E, "write that file, or correct router in {pack}/skills.yaml"),
    "env-file.missing": _c(
        E,
        "create {subject} (chmod 600) outside every git tree, or drop it from seat_config env_files in {pack}/pack.yaml",
        security=True,
    ),
    "env-file.readable": _c(E, "chmod 600 {subject}", security=True),
    "env-file.in-git": _c(
        E, "move {subject} out of the git tree and correct seat_config env_files in {pack}/pack.yaml", security=True
    ),
    "helper.program-missing": _c(
        W, "make that program executable or put it on PATH, or correct its argv in {pack}/helpers.yaml"
    ),
    "plugin.block-unchecked": _c(
        W, "install that plugin (extra_plugins in {pack}/pack.yaml), or drop its block under plugins"
    ),
    "vault.locked": _c(E, "cockpit vault index", security=True),
    "vault.key-unsealed": _c(E, "cockpit vault init --key <fingerprint>", security=True),
    "vault.key-unsealed-empty": _c(W, "cockpit vault init --key <fingerprint>"),
    "resume.hook-missing": _c(E, SETUP),
    "resume.hook-unregistered": _c(E, SETUP),
    "seat.drift": _c(E, "cockpit setup --rerender", security=True),
    "gateway.state": _c(E, "hermes gateway status, then cockpit up"),
    "cron.script-missing": _c(E, SETUP),
    "hermes.version": _c(E, "install Hermes {verified} and put `hermes` on PATH"),
    "hermes.newer-unprobed": _c(
        E, "install Hermes {verified}, or a plugin checked against this Hermes (cockpit update check)", security=True
    ),
    "hermes.note": _c(I, ""),
    "cron.not-registered": _c(E, SETUP),
    "cron.turned-off": _c(W, SETUP),
    "cron.schedule-differs": _c(W, SETUP),
    "desktop.stale-copy": _c(W, "restart the Desktop: it copies the plugin's UI again when it starts"),
    "coding.command-missing": _c(
        W, "install that program or put it on PATH, or correct providers.coding.command in {pack}/pack.yaml", born=True
    ),
    "tools.video": _c(W, "install ffmpeg (it brings ffprobe) and put it on PATH", born=True),
    "forge.cli-missing": _c(
        W,
        "install the forge's command line and put `gh` on PATH: nothing is published or watched without it",
        born=True,
    ),
    "forge.cli-login": _c(W, "gh auth login", born=True),
    "notify.unknown-event": _c(
        W,
        "rename that key under notify in {pack}/pack.yaml to an event the kernel sends ({events}, or ci_<state>)",
        born=True,
    ),
    "tracker.auth-env-unset": _c(
        W,
        "export {subject} where cockpit and the seats start, or correct tracker.auth_env in {pack}/pack.yaml",
        born=True,
    ),
    "repos.path-missing": _c(
        W,
        "clone that repository there, or correct its path in {pack}/repos.yaml (a relative path starts at the workspace's parent)",
        born=True,
    ),
    "python.yaml-missing": _c(W, "python3 -m venv .venv && .venv/bin/pip install -e . in {plugin}", born=True),
    "pack.finding-labels": _c(
        W, "write finding_labels in {pack}/pack.yaml as a list of tags, e.g. finding_labels: [B, Q]", born=True
    ),
}

LOGIN_TIMEOUT = 15  # seconds the forge's sign-in question may take; it is asked only with --online
YAML_TIMEOUT = 20


def _finding(check_id: str, message: str, subject: str, places: dict) -> dict:
    spec = CHECKS[check_id]
    return {
        "id": check_id,
        "severity": spec["severity"],
        "security": spec["security"],
        "subject": subject,
        "message": message,
        "fix": spec["fix"].format(subject=subject, **places),
    }


def _host_check(message: str) -> str:
    """Which check a host_problems line belongs to. A line this does not know stays a refused-host failure."""
    if message == "egress production_hosts is empty":
        return "egress.production-hosts-empty"
    if message.startswith("production_hosts refuses a command it must allow"):
        return "egress.host-probe-allowed"
    return "egress.production-host-blocked"


def _provider_check(message: str) -> str:
    if " ran its last two sessions on provider " in message:
        return "provider.drift"
    if message.startswith("provider dependencies not checked"):
        return "provider.dependencies-unchecked"
    return "provider.dependency-missing"


ENV_FILE_TAILS = {" is readable by others (chmod 600)": "env-file.readable", " is inside a git tree": "env-file.in-git"}


def _env_file_check(message: str) -> tuple:
    """(check, path) of an _env_file_problems line; each of the three is a security error."""
    if message.startswith("env file missing "):
        return "env-file.missing", message[len("env file missing ") :]
    for tail, check_id in ENV_FILE_TAILS.items():
        if message.endswith(tail):
            return check_id, message[len("env file ") : -len(tail)]
    return "env-file.in-git", message


def origins_named(origins) -> bool:
    """Whether a staging file names an origin a lane can open: a mapping with at least one value that is not empty. A file
    whose origins are all empty texts names none."""
    return isinstance(origins, dict) and any(str(value or "").strip() for value in origins.values())


def _coding_problems(pack) -> list:
    """providers.coding.command starts the human's coding tool: its program is a file that runs, or is on PATH."""
    import shutil

    command = ((pack.get("providers") or {}).get("coding") or {}).get("command")
    program = str(command[0]) if isinstance(command, list) and command else ""
    if not program:
        return []
    if os.path.isabs(program):
        return (
            []
            if os.path.isfile(program) and os.access(program, os.X_OK)
            else [f"providers.coding.command: {program} is not an executable file"]
        )
    return [] if shutil.which(program) else [f"providers.coding.command: {program} is not on PATH"]


def _video_problems() -> list:
    """The programs a failure video needs and this machine lacks, looked for the way the recorder finds them (PATH, then
    Hermes's own tools)."""
    from .errors import CockpitError
    from .record import _tool

    missing = []
    for name in ("ffmpeg", "ffprobe"):
        try:
            _tool(name)
        except CockpitError:
            missing.append(name)
    return missing


def _forge_problems(online: bool) -> list:
    """[(check, message)] about the forge's command line: it is on PATH and, with online, it is signed in. The sign-in
    question is answered by the forge over the network, so it is asked only when the human asks for network probes."""
    import shutil
    import subprocess

    program = shutil.which("gh")
    if not program:
        return [("forge.cli-missing", "gh is not on PATH")]
    if not online:
        return []
    try:
        done = subprocess.run(
            [program, "auth", "status"],
            capture_output=True,
            text=True,
            timeout=LOGIN_TIMEOUT,
            check=False,
            stdin=subprocess.DEVNULL,
        )
    except subprocess.TimeoutExpired:
        return [("forge.cli-login", f"gh auth status did not answer within {LOGIN_TIMEOUT} s")]
    except OSError as exc:
        return [("forge.cli-login", f"gh auth status could not run: {exc}")]
    return [] if done.returncode == 0 else [("forge.cli-login", "gh is not signed in to the forge")]


def _notify_problems(pack) -> list:
    """The notify keys no kernel code sends: a command under one of them never runs."""
    from .notify import known_event

    return [str(event) for event in (pack.get("notify") or {}) if not known_event(str(event))]


def _tracker_env_problems(pack) -> list:
    """A REST tracker reads its email and token from two named environment variables: the ones that are not set."""
    tracker = pack.get("tracker") or {}
    if not isinstance(tracker, dict) or tracker.get("kind") != "jira":
        return []
    return [str(name) for name in tracker.get("auth_env") or [] if not os.environ.get(str(name))]


def _repo_path_problems(pack) -> list:
    """[(name, path)] of each repo whose folder is not there: a relative path starts at the workspace's parent."""
    from .paths import root

    missing = []
    for repo in (pack.get("repos") or {}).get("repos") or []:
        path = repo.get("path") if isinstance(repo, dict) else None
        if not isinstance(path, str) or not path:
            continue
        full = path if os.path.isabs(path) else os.path.join(root(), path)
        if not os.path.isdir(full):
            missing.append((str(repo.get("name")), full))
    return missing


def _python_problems() -> list:
    """A cron or a hook starts cockpit with a bare PATH: its python3 has PyYAML, or the plugin has a .venv to fall back on."""
    import shutil
    import subprocess

    if os.path.exists(os.path.join(plugin_root(), ".venv", "bin", "python")):
        return []
    program = shutil.which("python3")
    if not program:
        return ["python3 is not on PATH and the plugin has no .venv"]
    try:
        done = subprocess.run([program, "-c", "import yaml"], capture_output=True, timeout=YAML_TIMEOUT, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return [f"{program} could not be asked for PyYAML and the plugin has no .venv"]
    return [] if done.returncode == 0 else [f"{program} lacks PyYAML and the plugin has no .venv"]


def _collect(pack, online: bool) -> tuple:
    """(findings, what the running Hermes said): one pass over every check, in the order doctor has always listed them."""
    from .prompts import problems as prompt_problems

    places = {
        "pack": pack.get("_dir") or "",
        "home": hermes_home(),
        "plugin": plugin_root(),
        "verified": " or ".join(HERMES_VERIFIED),
    }
    found = []

    def add(check_id, message, subject="", **more):
        found.append(_finding(check_id, message, subject, {**places, **more}))

    for line in prompt_problems(pack):
        add("prompt.missing", line, line[len("prompt ") :].split(" missing: ", 1)[0])
    if not check("git push origin x"):
        add("egress.push-blocked", "git push NOT blocked")
    if not check("gh pr create -t x"):
        add("egress.forge-write-blocked", "gh pr create NOT blocked")
    if check("git status"):
        add("egress.read-allowed", "git status blocked")
    for line in allowed_read_problems(pack):
        add("egress.allowed-read-denied", line, line.split(": ", 1)[1])
    for line in pack_read_problems(pack):
        add("egress.pack-refuses-read", line)
    for line in egress_key_problems(pack):
        add("egress.unknown-key", line, line.split("unknown key ", 1)[1].split(" ", 1)[0].rstrip(":"))
    for line in egress_pattern_problems(pack):
        add("egress.pattern-invalid", line, line.split(": ", 1)[0])
    for line in text_for_list_problems(pack):
        add("pack.text-for-list", line, line.split(" is one text ", 1)[0])
    config = os.path.join(hermes_home(), "config.yaml")
    text = open(config, encoding="utf-8").read() if os.path.isfile(config) else ""
    if "auto_decompose: false" not in text:
        add("hermes.auto-decompose", "auto_decompose is not false")
    if "review_dispatch: false" not in text:
        add("hermes.review-dispatch", "review_dispatch is not false")
    board = os.path.join(hermes_home(), "kanban", "boards", pack["board"], "board.json")
    if not os.path.isfile(board):
        add("board.metadata", "board metadata missing", pack["board"])
    hook = os.path.join(plugin_root(), "hooks", "egress.py")
    homes = [hermes_home()]
    for names in seats_from(pack).values():
        for lane in names:
            homes.append(profile_dir(lane))
    for home in homes:
        allow = os.path.join(home, "shell-hooks-allowlist.json")
        listed = open(allow, encoding="utf-8").read() if os.path.isfile(allow) else ""
        if hook not in listed:
            add("egress.hook-allowlisted", "egress hook not allowlisted", home)
            break
    for kind, names in seats_from(pack).items():
        for lane in names:
            folder = profile_dir(lane)
            if not os.path.isfile(os.path.join(folder, "config.yaml")):
                add("seat.not-applied", f"{lane} not applied", lane)
                continue
            for line in _plugin_problems(lane, folder, [COCKPIT, *extra_plugins_for(pack, kind)]):
                add("seat.plugin", line, lane)
            for line in _skill_problems(lane, folder, seat_skills_for(pack, kind)):
                add("seat.skill", line, lane)
            env = (
                open(os.path.join(folder, ".env"), encoding="utf-8").read()
                if os.path.isfile(os.path.join(folder, ".env"))
                else ""
            )
            if f"COCKPIT_LANE={lane}" not in env:
                add("seat.env-lane", f"{lane} env lacks COCKPIT_LANE", lane)
            for line in _harness_problems(pack, lane, folder, env):
                add("seat.env-browser-home", line, lane)
            memory = os.path.join(folder, "memories", "MEMORY.md")
            if os.path.isfile(memory):
                raw = open(memory, encoding="utf-8").read()
                if "§" not in raw and len(raw) > 600:
                    add("seat.memory-full", f"{lane} MEMORY.md not writable", lane)
    if calls_tools(hermes_home()):
        for line in _plugin_problems("root", hermes_home()):
            add("seat.plugin", line, "root")
    for line in _plugin_problems("root", hermes_home(), extra_plugins_for(pack, "root")):
        add("seat.plugin", line, "root")
    declared_none = (pack.get("egress") or {}).get("no_production_hosts") is True
    for line in host_problems(pack):
        if declared_none and _host_check(line) == "egress.production-hosts-empty":
            # the pack answered the question: there is no production to refuse, which is not the same as not saying
            add(
                "egress.no-production",
                "egress no_production_hosts: the pack declares that this project has no production",
            )
            continue
        add(_host_check(line), line)
    for line in provider_problems(pack):
        add(_provider_check(line), line, line.split(" ", 1)[0] if _provider_check(line) == "provider.drift" else "")
    from .setup import cursor_hook_installed, cursor_hooks_path

    if (pack.get("agent") or {}).get("cursor_hooks") and not cursor_hook_installed():
        add(
            "fence.editor-hook",
            f"cockpit's fence is not in {cursor_hooks_path()} (agent.cursor_hooks): run setup",
            cursor_hooks_path(),
        )
    staging = os.path.join(pack["_dir"], "staging.yaml")
    if not os.path.isfile(staging):
        add("staging.missing", "staging.yaml missing", staging)
    if os.path.isfile(staging):
        from . import pack_local

        origins = (pack_local.read(staging) or {}).get("origins") or {}
        if not origins_named(origins):
            add("staging.origins-empty", "staging origins empty", staging)
    repos = (pack.get("repos") or {}).get("repos") or []
    if repos and not any(repo.get("gates") for repo in repos):
        add("repos.no-gates", "no repo gates")
    from .pack import agent_launch

    launch = agent_launch(pack)
    if launch["home"] and not os.path.isdir(launch["home"]):
        add("agent.home-missing", "agent home missing", launch["home"])
    if (pack.get("skills") or {}).get("router") and not os.path.isfile(launch["router"]):
        add("skills.router-missing", "skill router missing", launch["router"])
    for line in _env_file_problems(pack):
        check_id, path = _env_file_check(line)
        add(check_id, line, path)
    from .helpers import problems as helper_problems

    for line in helper_problems(pack):
        add("helper.program-missing", line, line.split(":", 1)[0])
    for name in pack.get("_plugins_unchecked") or []:
        add("plugin.block-unchecked", f"plugins.{name}: the plugin is not installed, so its block is not checked", name)
    from .scrub import locked

    if locked():
        add("vault.locked", "vault locked: the scrub index lacks logins added since (cockpit vault index)")
    from . import vault

    if vault.needs_seal():
        # a public key with nothing to seal yet is a reminder; a key or an entry left unwrapped is an exposure
        add(
            "vault.key-unsealed" if vault.key_needs_wrap() or vault._vault_material() else "vault.key-unsealed-empty",
            "vault key not sealed",
        )
    from .resume import hook_installed, hook_registered

    if not hook_installed():
        add("resume.hook-missing", "resume hook missing")
    if not hook_registered():
        add("resume.hook-unregistered", "resume hook not registered")
    from .setup import seat_drift

    for line in seat_drift(pack):
        add("seat.drift", line)
    if gateway_status() not in ("running", "stopped"):
        add("gateway.state", "gateway state unreadable")
    for name, _schedule, script in CRON_JOBS:
        if not os.path.isfile(os.path.join(cron_home(pack, name), "scripts", script)):
            add("cron.script-missing", f"{name} script missing", name)
    hermes = _hermes()
    if hermes["problem"]:
        # a newer Hermes whose hooks were asked and did not answer the recorded shapes: the fence itself is in doubt
        add("hermes.newer-unprobed" if hermes["note"] else "hermes.version", hermes["problem"])
    for action in cron_plan(registered_jobs(pack), pack):
        if action["op"] == "create":
            add("cron.not-registered", f"{action['name']} cron not registered", action["name"])
            continue
        if action["op"] == "remove":
            add(
                "cron.turned-off",
                f"{action['name']} cron is registered but the pack turns it off: run setup",
                action["name"],
            )
            continue
        add("cron.schedule-differs", f"{action['name']} cron schedule differs", action["name"])
    from .setup import desktop_copy_stale

    stale = desktop_copy_stale()
    if stale:
        add("desktop.stale-copy", stale)
    for line in _coding_problems(pack):
        add("coding.command-missing", line)
    for name in _video_problems():
        add("tools.video", f"{name} not found: a failure video cannot be encoded or checked", name)
    for check_id, line in _forge_problems(online):
        add(check_id, line, "gh")
    from .notify import EVENTS

    for event in _notify_problems(pack):
        add(
            "notify.unknown-event",
            f"notify.{event}: no kernel code sends an event of that name, so its command never runs",
            event,
            events=", ".join(EVENTS),
        )
    for name in _tracker_env_problems(pack):
        add("tracker.auth-env-unset", f"tracker.auth_env: {name} is not set in this environment", name)
    for name, path in _repo_path_problems(pack):
        add("repos.path-missing", f"repo {name}: missing {path}", name)
    for line in _python_problems():
        add("python.yaml-missing", line)
    from .pr_watch import finding_labels_problem

    labels_problem = finding_labels_problem(pack)
    if labels_problem:
        add("pack.finding-labels", f"finding_labels {labels_problem}", "finding_labels")
    if hermes["note"]:
        add("hermes.note", hermes["note"])
    return found, hermes


def findings(pack, online: bool = False) -> list:
    """Every finding about the bound workspace: {id, severity, security, subject, message, fix}. A finding's tier comes
    from CHECKS alone. online adds the probes that need the network."""
    return _collect(pack, online)[0]


def failing(found, strict: bool = False) -> list:
    """The findings that fail doctor: every error, and with strict every warning too."""
    return [item for item in found if item["severity"] == E or (strict and item["severity"] == W)]


def report(pack, online: bool = False, strict: bool = False) -> dict:
    """What `cockpit doctor --json` prints: the verdict, the counts, the pack, the running Hermes and every finding."""
    found, hermes = _collect(pack, online)
    return {
        "ok": not failing(found, strict),
        "errors": sum(item["severity"] == E for item in found),
        "warnings": sum(item["severity"] == W for item in found),
        "pack": pack.get("name") or "",
        "hermes": hermes["version"],
        "findings": found,
    }


def run(pack) -> list:
    """The lines that have always failed doctor, in their order: every error, and every warning that was a failure
    before the tiers existed. Empty means green. A warning born with the tiers is in findings() only."""
    return [
        item["message"]
        for item in findings(pack)
        if item["severity"] == E or (item["severity"] == W and not CHECKS[item["id"]]["born"])
    ]
