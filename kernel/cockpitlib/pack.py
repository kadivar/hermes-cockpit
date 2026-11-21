# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Load a pack. Skill directories are absolute or {pack}/<folder>. The shipped fixture may use @anchors."""

import copy
import os
import re
import stat
import threading

import yaml

from .errors import PackError
from .intents import TICKET_RE

KNOWN = {
    "name",
    "board",
    "ticket_pattern",
    "branch_prefix",
    "commit_trailer",
    "base_branch",
    "workspace_branch",
    "human_browser_port",
    "seats",
    "budget",
    "shared_chrome_hours",
    "skills_dir",
    "providers",
    "roles",
    "slot_provider",
    "finding_labels",
    "agent",
    "refused",
    "allowed",
    "stores",
    "privileged",
    "logins",
    "notify",
    "working_days",
    "scratch",
    "hours",
    "standup_enabled",
    "standup",
    "grooming",
    "bump_sequence",
    "advisories",
    "runtime",
    "slot_browser",
    "dev_servers",
    "records_dir",
    "seat_config",
    "extra_plugins",
    "board_workdir",
    "testflow",
    "mcp_servers",
    "slots",
    "plugins",
    "kickoff",
    "helpers",
    "tracker",
    "forge",
    "outbox",
    "watchers",
    "perf",
    "export",
    "environments",
    "capacity",
    "prompts",
    "advisor",
    "awake",
    "ide",
    "desktop",
    "board_done_days",
    "asks",
    "protected_branches",
    "lanes",
    "demo_login_origins",
    "worktree_gc",
}
# Fixes to the Hermes Desktop a pack may opt into by name (desktop.overrides); what each one writes lives in the
# desktop half (desktop/src/lib/overrides.js), so a pack chooses among them and cannot write anything else.
DESKTOP_OVERRIDES = ("opaque-window",)
DESKTOP_KEYS = ("overrides", "mermaid_url", "live_jobs", "done_recent_hours", "diff_held_suffix", "hints")
# Help text of the Desktop pages on how a review and a bump batch go: the default of each desktop.hints key. The page
# prints what the route sends, so a pack names its own skills and steps in its own words.
DESKTOP_HINTS = {
    "bumps_tab": "Bumps → reviewer",
    "review": (
        "The reviewer checks each PR head out in a worktree, reviews it against the real code, leaves the "
        "findings on the card and writes one review intent per PR. You publish them from the Outbox; nothing "
        "reaches the forge before that."
    ),
    "bumps": (
        "Tick the repos. Per repo a reviewer card lists its open dependency-bot pull requests and asks you "
        "which; every write it then prepares comes back here for you to publish. The weekday scan offers the "
        "candidates in the Inbox by itself."
    ),
    "rereview": (
        "the reviewer lane checks whether each of your threads was answered, reviews only the diff since "
        "your last review, and writes one review intent for your publish"
    ),
    "bumps_start": (
        "Nothing has started. Pick the batch and Start: a reviewer card works through it, and every write "
        "comes back here for you to publish. Dismiss what a colleague takes."
    ),
}


def desktop_hints(pack) -> dict:
    """{id: text}: the Desktop's help texts in force, the pack's desktop.hints over the kernel's own."""
    raw = ((pack or {}).get("desktop") or {}).get("hints") or {}
    return {name: str(raw.get(name) or text) for name, text in DESKTOP_HINTS.items()}


ROLES = ("intake", "worker", "tester", "reviewer", "analyst", "gatekeeper", "advisor")
# cockpit's own skills (skills/<name>). Hermes names a plugin's skill <plugin>:<name>, so a pack lists them as cockpit:<name>.
BUNDLED = ("outbox", "cockpit-ops", "cockpit-migrate", "platform-map")
NAMESPACE = "cockpit:"
DEFAULT_TICKET = r"^[A-Z][A-Z0-9]*(?:-[A-Z0-9]+)+$"
LOOSE_SAMPLES = ("task-1", "TASK", "1-2", "not a ticket")
PACK_ANCHOR = "{pack}/"  # skills_dir: a folder of the pack's own, written relative to it


def policy(pack) -> dict:
    """Adopter values the kernel reads. Empty when the pack does not set them."""
    refused = pack.get("refused") or {}
    allowed = pack.get("allowed") or {}
    privileged = pack.get("privileged") or {}
    logins = pack.get("logins") or {}
    notify = pack.get("notify") or {}
    if not isinstance(refused, dict) or not isinstance(allowed, dict) or not isinstance(privileged, dict):
        raise PackError("refused, allowed, and privileged must be mappings")
    if not isinstance(logins, dict) or not isinstance(notify, dict):
        raise PackError("logins and notify must be mappings")
    if privileged.get("on_deny") not in (None, "block", "resume"):
        raise PackError(
            "privileged.on_deny is block (the row stays blocked) or resume (the lane carries on and records the row)"
        )
    from .notify import EVENT

    for event, argv in notify.items():
        if not isinstance(event, str) or not EVENT.match(event):
            raise PackError(f"notify {event}: an event name is lowercase words")
        if not isinstance(argv, list) or not all(isinstance(part, str) and part for part in argv):
            raise PackError(f"notify.{event} must be a command: a list of words")
    days = pack.get("working_days")
    if days is None:
        days = []
    if not isinstance(days, list) or any(not isinstance(day, int) or day < 0 or day > 6 for day in days):
        raise PackError("working_days")
    stores = pack.get("stores") or []
    if not isinstance(stores, list):
        raise PackError("stores")
    return {
        "hosts": [str(item) for item in (refused.get("hosts") or [])],
        "commands": [str(item) for item in (refused.get("commands") or [])],
        "reads": [str(item) for item in (allowed.get("reads") or [])],
        "stores": stores,
        "privileged_env": str(privileged.get("environment") or ""),
        "privileged_label": str(privileged.get("label") or ""),
        "privileged_scope": str(privileged.get("scope") or "human"),
        "login_scope": str(logins.get("scope") or "lane"),
        "standup_command": list(notify.get("standup") or []),
        "working_days": days,
        "scratch": str(pack.get("scratch") or ""),
    }


def _policy(data) -> None:
    parsed = policy(data)
    data["working_days"] = parsed["working_days"]


def plugin_root() -> str:
    from .paths import PLUGIN_ROOT

    return PLUGIN_ROOT


_TRAIL = threading.local()  # .seen: {(path, how)} while a load runs in this thread, so the load knows what it read
_LOADED = {}  # pack path -> (stamp, trail, the loaded pack)
TREE_LIMIT = 2000  # a pack folder with more entries than this is not stamped: its pack is loaded every time


def _note(path, how) -> None:
    seen = getattr(_TRAIL, "seen", None)
    if seen is not None:
        seen.add((os.fspath(path), how))


def consulted(path) -> None:
    """A file a check outside this module reads while a pack loads (accounts, helpers): the loaded pack depends on it."""
    _note(path, "file")


def _isfile(path) -> bool:
    _note(path, "file")
    return os.path.isfile(path)


def _isdir(path) -> bool:
    _note(path, "dir")
    return os.path.isdir(path)


def _listdir(path) -> list:
    _note(path, "list")
    return os.listdir(path)


def _open(path, *args, **kwargs):
    _note(path, "file")
    return open(path, *args, **kwargs)


def _state(path, how):
    try:
        seen = os.stat(path)
    except OSError:
        return None
    if how == "dir":
        return stat.S_ISDIR(seen.st_mode)  # asked only whether it is a folder: what it holds may change freely
    return (seen.st_mtime_ns, seen.st_size, seen.st_ino)


def _tree(folder):
    """Every file under the pack's folder with its stamp, or None when the folder is too large to stamp. Another
    plugin's validator is handed this folder and reads what it likes there, so all of it counts."""
    found = []
    for base, dirs, files in os.walk(folder):
        dirs[:] = sorted(name for name in dirs if name not in (".git", "__pycache__", "node_modules"))
        for name in sorted(files):
            path = os.path.join(base, name)
            found.append((path, _state(path, "file")))
        if len(found) > TREE_LIMIT:
            return None
    return tuple(found)


def _stamp(path: str, trail):
    """What a loaded pack depends on: every file of its folder, every path the load asked about outside it, the
    settings that place the workspace and the home, and the kinds other plugins registered in this process."""
    tree = _tree(os.path.dirname(path))
    if tree is None:
        return None
    from . import registry
    from .paths import binding_file

    places = tuple(
        sorted((key, value) for key, value in os.environ.items() if key.startswith("COCKPIT_") or key == "HOME")
    )
    return (
        tree,
        tuple((item, how, _state(item, how)) for item, how in sorted(trail)),
        _state(binding_file(), "file"),
        places,
        len(registry._kinds),
        len(registry._modes),
    )


def load(path: str) -> dict:
    """The pack at that path, checked. A pack whose files have not changed since the last load in this process is not
    read again (fourteen YAML files and every check, on each of the many loads one page view makes): the caller gets
    its own copy of the kept one. A load that fails is never kept."""
    path = os.path.realpath(path)
    kept = _LOADED.get(path)
    if kept is not None and kept[0] == _stamp(path, kept[1]):
        return copy.deepcopy(kept[2])
    outer = getattr(_TRAIL, "seen", None)
    _TRAIL.seen = set()
    try:
        data = _load(path)
    except Exception as exc:  # noqa: BLE001 - a pack someone else wrote is refused as a pack, whatever shape its damage has
        raise _refusal(exc) from exc
    finally:
        trail, _TRAIL.seen = _TRAIL.seen, outer
    stamp = _stamp(path, trail)
    if stamp is not None:
        _LOADED[path] = (stamp, trail, copy.deepcopy(data))
    else:
        _LOADED.pop(path, None)
    return data


def _refusal(exc: Exception) -> Exception:
    """What a failed load raises: the kernel's own errors as they are; a file that is not YAML and a value whose shape no
    check expected as a PackError that names the file, or the check that met the value. A pack never crashes its reader."""
    from .errors import CockpitError

    if isinstance(exc, CockpitError):
        return exc
    if isinstance(exc, yaml.YAMLError):
        mark = getattr(exc, "problem_mark", None)
        where = f"{os.path.basename(mark.name)}, line {mark.line + 1}: " if mark is not None and mark.name else ""
        return PackError(f"{where}not valid YAML: {getattr(exc, 'problem', None) or ' '.join(str(exc).split())[:160]}")
    step = exc.__traceback__
    inner = None
    while step is not None:  # the innermost check of this package that met the value
        if os.path.dirname(step.tb_frame.f_code.co_filename) == os.path.dirname(os.path.abspath(__file__)):
            inner = step.tb_frame.f_code
        step = step.tb_next
    place = (
        f"{os.path.splitext(os.path.basename(inner.co_filename))[0]}.{inner.co_name.lstrip('_')}"
        if inner is not None
        else "the loader"
    )
    return PackError(
        f"a value in the pack has a shape {place} cannot read ({type(exc).__name__}: {' '.join(str(exc).split())[:160]}): "
        "`cockpit pack explain <key>` shows the shape a key takes"
    )


def _read_raw(path: str, unset=None) -> dict:
    """pack.yaml as written, with the personal values of the file beside it filled in (pack_local): a mapping, or the
    error that says it is not one. The local file is checked whether or not the pack uses it."""
    if not _isfile(path):
        raise PackError(f"missing pack {path}")
    from . import pack_local

    pack_local.values(os.path.dirname(path))
    raw = pack_local.read(path, unset=unset)
    if not isinstance(raw, dict):
        raise PackError("pack.yaml must be a mapping")
    return raw


def _raw_report(path: str) -> tuple:
    """(lines, pack.yaml) for the report of every problem: a name the local file does not set is a line and its token
    stays as written, so the checks still run; a file that cannot be read at all is its one line and no pack."""
    lines: list = []
    try:
        return lines, _read_raw(path, lines)
    except Exception as exc:  # noqa: BLE001 - the report starts with what a load raises, whatever shape the damage has
        return [str(_refusal(exc))], None


def _begin(raw, path: str) -> dict:
    """The pack a load works on: what the file says, with where it is."""
    data = dict(raw)
    data["_path"] = path
    data["_dir"] = os.path.dirname(path)
    return data


def _load(path: str) -> dict:
    raw = _read_raw(path)
    unknown = [key for key in raw if key not in KNOWN]
    if unknown:
        raise PackError(f"unknown key {unknown[0]}")
    data = _begin(raw, path)
    for _name, step in STEPS:
        step(data)
    return data


def problems(path: str) -> list:
    """Every problem of the pack at that path, in the order a load meets them: each check of a load is run by itself,
    so one wrong key does not hide the next. The first line is the error a load raises. A check that reads what an
    earlier, failed check would have settled is not run and says which one it waits for; nothing is loaded or kept. A
    file that is not YAML and a value whose shape no check expected are lines of the report in the words a load refuses
    them with (_refusal): the report never crashes on a pack either."""
    path = os.path.realpath(path)
    found, raw = _raw_report(path)
    if raw is None:
        return found
    found += [f"unknown key {key}" for key in raw if key not in KNOWN]
    data = _begin({key: value for key, value in raw.items() if key in KNOWN}, path)
    failed = []
    for name, step in STEPS:
        waits = [need for need in NEEDS.get(name, ("required",)) if need in failed]
        if waits:
            found.append(f"{name}: not checked: depends on {waits[0]}")
            failed.append(name)
            continue
        try:
            step(data)
        except PackError as exc:
            found += getattr(exc, "lines", [str(exc)])
            failed.append(name)
        except Exception as exc:  # noqa: BLE001 - as a load refuses it
            if failed and isinstance(exc, (TypeError, KeyError, AttributeError, ValueError, IndexError)):
                # a check that met what an earlier failed check left unsettled, with no dependency written for it
                found.append(f"{name}: not checked: depends on {failed[-1]} ({type(exc).__name__})")
            else:
                found.append(
                    str(_refusal(exc))
                )  # with no failed check before it: the line a load raises, naming the check
            failed.append(name)
    return found


def _skills_dir(data) -> None:
    data["skills_dir"] = _skills(data)


def _standup_enabled(data) -> None:
    if not isinstance(data.get("standup_enabled", True), bool):
        raise PackError("standup_enabled is true or false")


def _board_done_days(data) -> None:
    if data.get("board_done_days") is not None and (
        not isinstance(data["board_done_days"], int)
        or isinstance(data["board_done_days"], bool)
        or not 0 <= data["board_done_days"] <= 30
    ):
        raise PackError("board_done_days is a whole number of days from 0 to 30")


def _awake(data) -> None:
    if data.get("awake") is not None:
        if not isinstance(data["awake"], dict) or set(data["awake"]) != {"command"}:
            raise PackError("awake takes command")
        _argv(data["awake"]["command"], "awake.command")


def _accounts(data) -> None:
    from .accounts import manifest

    manifest(data)


def _helpers(data) -> None:
    from .helpers import check

    check(data)


def _card_kinds(data) -> None:
    from .registry import card_kinds

    card_kinds(data)


def _kickoff(data) -> None:
    from .registry import check_kickoff

    check_kickoff(data)


def _kickoff_modes(data) -> None:
    from .registry import kickoff_modes

    kickoff_modes(data)


def _plugin_pages(data) -> None:
    from .registry import plugin_pages

    plugin_pages(data)


def _personal(data) -> None:
    """The files of the pack this load does not read ask for no personal value the local file does not set."""
    from . import pack_local

    lines = pack_local.unset_late(data["_dir"])
    if lines:
        raise pack_local.Unset(lines)


def _steps() -> tuple:
    """The checks of a load, in the order a load runs them: (name, check). A check raises PackError and may settle a
    value in the pack it is given, which later checks read."""
    return (
        ("required", _require),
        ("ticket_pattern", _ticket_pattern),
        ("protected_branches", _protected_branches),
        ("skills_dir", _skills_dir),
        ("grooming", _grooming),
        ("bump_sequence", _bump_sequence),
        ("advisories", _advisories),
        ("hours", _hours),
        ("runtime", _runtime),
        ("records_dir", _records_dir),
        ("mcp_servers", _mcp_servers),
        ("seat_config", _seat_config),
        ("extra_plugins", _extra_plugins),
        ("board_workdir", _board_workdir),
        ("testflow", _testflow),
        ("lanes", _lanes),
        ("asks", _asks),
        ("slots", _slots),
        ("providers", _providers),
        ("ide", _ide),
        ("desktop", _desktop),
        ("standup_enabled", _standup_enabled),
        ("standup", _standup),
        ("board_done_days", _board_done_days),
        ("worktree_gc", _worktree_gc),
        ("seats", _seats),
        ("plugins", _plugin_blocks),
        ("tracker", _tracker),
        ("demo_login_origins", _demo_login_origins),
        ("forge", _forge),
        ("outbox", _outbox_policy),
        ("watchers", _watchers),
        ("perf_export", _perf_export),
        ("awake", _awake),
        ("environments", _environments),
        ("prompts", _prompts),
        ("advisor", _advisor),
        ("companions", _companions),
        ("tracker_repo", _tracker_repo),
        ("policy", _policy),
        ("accounts", _accounts),
        ("helpers", _helpers),
        ("card_kinds", _card_kinds),
        ("kickoff", _kickoff),
        ("kickoff_modes", _kickoff_modes),
        ("plugin_pages", _plugin_pages),
        ("personal", _personal),
    )


# What a check reads that an earlier one settles, where it is more than the required keys: a failed check named here
# leaves the one that waits for it unrun. Every check but the first waits for the required keys.
NEEDS = {
    "required": (),
    "accounts": ("required", "companions"),
    "helpers": ("required", "companions"),
    "tracker_repo": ("required", "tracker", "companions"),
    "card_kinds": ("required", "companions", "plugins"),
    "kickoff": ("required", "companions", "plugins"),
    "kickoff_modes": ("required", "companions", "plugins"),
    "plugin_pages": ("required", "plugins"),
}


def forge_org(pack):
    """The forge organisation the pack's repos live under."""
    return ((pack or {}).get("forge") or {}).get("org") or ""


def tracker_url(pack):
    """The tracker's base URL as the pack wrote it."""
    return ((pack or {}).get("tracker") or {}).get("url") or ""


def tracker_project(pack):
    """The tracker project key."""
    return ((pack or {}).get("tracker") or {}).get("project") or ""


def batch_project(pack) -> str:
    """The project a batch ticket and a platform ticket are named under: the tracker project, BATCH for a pack with none."""
    return str(tracker_project(pack) or "BATCH")


# A required value inside a block: (the block, the block's key).
REQUIRED_IN_A_BLOCK = (("forge", "org"), ("tracker", "url"), ("tracker", "project"))


def _require(data) -> None:
    for key in ("name", "board", "seats", "providers", "roles", "skills_dir"):
        if key not in data:
            raise PackError(f"missing {key}")
    tracker = data.get("tracker")
    for block, field in REQUIRED_IN_A_BLOCK:
        if (block, field) == ("tracker", "url") and isinstance(tracker, dict):
            if tracker.get("kind") in TRACKER_KINDS_ON_THE_FORGE:
                continue  # its tickets are pages of the forge: there is no other URL to give
        inner = data.get(block)
        if inner is None or (isinstance(inner, dict) and field not in inner):  # a block of another shape: its own check
            raise PackError(f"missing {block}.{field}")


def _ticket_pattern(data) -> None:
    pattern = data.get("ticket_pattern") or DEFAULT_TICKET
    try:
        compiled = re.compile(pattern)
    except re.error as exc:
        raise PackError(f"ticket_pattern: {exc}") from exc
    if not compiled.match("TASK-100"):
        raise PackError("ticket_pattern rejects TASK-100")
    for sample in LOOSE_SAMPLES:
        if compiled.match(sample) and not TICKET_RE.match(sample):
            raise PackError(f"ticket_pattern is looser than the kernel ({sample})")
    data["ticket_pattern"] = pattern
    data["workspace_branch"] = str(data.get("workspace_branch") or "").strip()


def _protected_branches(data) -> None:
    """Branches only the human writes, in every repo that has them (beside each repo's own base)."""
    raw = data.get("protected_branches")
    if raw is None:
        data["protected_branches"] = []
        return
    if not isinstance(raw, list) or not all(isinstance(item, str) and item.strip() for item in raw):
        raise PackError("protected_branches must be a list of branch names")
    data["protected_branches"] = [item.strip() for item in raw]


def _runtime(data) -> None:
    """runtime: worktree, or absent, which means the same: a ticket's code is checked out under wt/<ticket>/<repo>."""
    raw = data.get("runtime") or ""
    if raw not in ("", "worktree"):
        raise PackError("runtime")
    if raw:
        data["runtime"] = raw


SEAT_KINDS = ("_common", "root", "intake", "reviewer", "analyst", "worker", "tester", "gatekeeper", "advisor")
SEAT_FIELDS = ("hermes", "soul", "memory_seed", "skills", "mcp", "env", "env_files")
ROOT_FIELDS = ("soul",)
# Settings cockpit owns on every seat (setup._seat_settings). An overlay may not set them.
KERNEL_OWNED = (
    ("model", "default"),
    ("model", "provider"),
    ("hooks_auto_accept",),
    ("kanban", "auto_decompose"),
    ("kanban", "review_dispatch"),
    ("approvals", "unattended_mode"),
    ("approvals", "cron_mode"),
    ("approvals", "single_query_mode"),
    ("delegation", "max_concurrent_children"),
    ("delegation", "inherit_mcp_toolsets"),
    ("mcp_servers",),
)


def _seat_config(data) -> None:
    raw = data.get("seat_config")
    if raw is None:
        return
    if not isinstance(raw, dict):
        raise PackError("seat_config must be a mapping")
    for kind, block in raw.items():
        if kind not in SEAT_KINDS:
            raise PackError(f"seat_config {kind}: not a seat kind")
        if not isinstance(block, dict):
            raise PackError(f"seat_config {kind} must be a mapping")
        for field in block:
            if field not in (ROOT_FIELDS if kind == "root" else SEAT_FIELDS):
                raise PackError(f"seat_config {kind}: {field} is not a seat field")
        for field in ("soul", "memory_seed"):
            if field in block:
                block[field] = _pack_file(data, block[field], f"seat_config {kind}.{field}")
        if "skills" in block:
            block["skills"] = _seat_skills(data, block["skills"], f"seat_config {kind}.skills")
        mcp = block.get("mcp") or []
        if not isinstance(mcp, list) or any(name not in (data.get("mcp_servers") or {}) for name in mcp):
            raise PackError(f"seat_config {kind}.mcp names servers from mcp_servers")
        _seat_env(block, f"seat_config {kind}")
        overlay = block.get("hermes") or {}
        if not isinstance(overlay, dict):
            raise PackError(f"seat_config {kind}.hermes must be a mapping")
        for owned in KERNEL_OWNED:
            node = overlay
            for part in owned:
                node = node.get(part) if isinstance(node, dict) else None
            if node is not None:
                raise PackError(f"seat_config {kind}.hermes: {'.'.join(owned)} is set by cockpit")


PLUGIN_NAME = re.compile(r"^[a-z0-9][a-z0-9_-]*$")
ENV_NAME = re.compile(r"^[A-Z_][A-Z0-9_]*$")
MCP_FIELDS = {"command", "url", "env_keys", "headers_env", "include_tools", "exclude_tools"}


def _mcp_servers(data) -> None:
    """mcp_servers: {name: {command | url, env_keys, headers_env, include_tools, exclude_tools}}. A secret is named by
    its environment key, which Hermes fills from the seat's own environment; the pack holds no value."""
    raw = data.get("mcp_servers")
    if raw is None:
        return
    if not isinstance(raw, dict):
        raise PackError("mcp_servers must be a mapping")
    for name, server in raw.items():
        label = f"mcp_servers {name}"
        if (
            not isinstance(name, str)
            or not PLUGIN_NAME.match(name)
            or not isinstance(server, dict)
            or set(server) - MCP_FIELDS
        ):
            raise PackError(
                f"{label}: a name and {{command | url, env_keys, headers_env, include_tools, exclude_tools}}"
            )
        if bool(server.get("command")) == bool(server.get("url")):
            raise PackError(f"{label}: a command or a url, not both")
        command = server.get("command") or []
        if command and (not isinstance(command, list) or not all(isinstance(word, str) and word for word in command)):
            raise PackError(f"{label}.command must be a list of words")
        for field in ("env_keys", "include_tools", "exclude_tools"):
            value = server.get(field) or []
            if not isinstance(value, list) or not all(isinstance(item, str) and item for item in value):
                raise PackError(f"{label}.{field} must be a list")
        if any(not ENV_NAME.match(key) for key in server.get("env_keys") or []):
            raise PackError(f"{label}.env_keys are environment names")
        headers = server.get("headers_env") or {}
        if not isinstance(headers, dict) or any(
            not isinstance(value, str) or not ENV_NAME.match(value) for value in headers.values()
        ):
            raise PackError(f"{label}.headers_env maps a header to an environment name")


SECRET_NAME = re.compile(r"TOKEN|SECRET|PASSWORD|PASSWD|API_KEY|PRIVATE|CREDENTIAL", re.IGNORECASE)


def _seat_env(block, label) -> None:
    """env: plain values a seat's .env carries; env_files: absolute files (mode 600, outside any git tree) for the
    secrets. A name that reads like a secret belongs in an env file."""
    env = block.get("env") or {}
    if not isinstance(env, dict) or any(
        not isinstance(key, str) or not ENV_NAME.match(key) or not isinstance(value, (str, int, float))
        for key, value in env.items()
    ):
        raise PackError(f"{label}.env maps environment names to plain values")
    secret = next((key for key in env if SECRET_NAME.search(key)), "")
    if secret:
        raise PackError(f"{label}.env: {secret} reads like a secret; put it in an env_files file")
    files = block.get("env_files") or []
    if not isinstance(files, list) or not all(isinstance(item, str) and os.path.isabs(item) for item in files):
        raise PackError(f"{label}.env_files lists absolute paths")


def seat_env(data, kind: str) -> dict:
    """The .env values the pack gives a seat of this kind: _common's, the kind's own, then each env file's."""
    config = (data or {}).get("seat_config") or {}
    values = {}
    files = []
    for block in (config.get("_common") or {}, config.get(kind) or {}):
        values.update({key: str(value) for key, value in (block.get("env") or {}).items()})
        files += block.get("env_files") or []
    for path in files:
        if not _isfile(path):
            continue
        for line in _open(path, encoding="utf-8"):
            text = line.strip()
            if text and not text.startswith("#") and "=" in text:
                key, value = text.split("=", 1)
                values[key.strip()] = value.strip()
    return values


def seat_env_files(data, kind: str) -> list:
    config = (data or {}).get("seat_config") or {}
    return list(
        dict.fromkeys(
            [
                *((config.get("_common") or {}).get("env_files") or []),
                *((config.get(kind) or {}).get("env_files") or []),
            ]
        )
    )


def mcp_config(data, kind: str) -> dict:
    """The Hermes mcp_servers block for a seat of this kind: _common's servers and the kind's own."""
    config = (data or {}).get("seat_config") or {}
    names = list(
        dict.fromkeys([*((config.get("_common") or {}).get("mcp") or []), *((config.get(kind) or {}).get("mcp") or [])])
    )
    rendered = {}
    for name in names:
        server = data["mcp_servers"][name]
        entry = {}
        if server.get("command"):
            entry["command"] = server["command"][0]
            entry["args"] = list(server["command"][1:])
            if server.get("env_keys"):
                entry["env"] = {key: "${" + key + "}" for key in server["env_keys"]}
        else:
            entry["url"] = server["url"]
            if server.get("headers_env"):
                entry["headers"] = {header: "${" + key + "}" for header, key in server["headers_env"].items()}
        tools = {}
        if "include_tools" in server:
            tools["include"] = list(server["include_tools"] or [])
        if server.get("exclude_tools"):
            tools["exclude"] = list(server["exclude_tools"])
        if tools:
            entry["tools"] = tools
        rendered[name] = entry
    return rendered


def _seat_skills(data, raw, label) -> list:
    """[{name, path}]: a skill folder holding SKILL.md, linked into the seat's own skills/."""
    if not isinstance(raw, list):
        raise PackError(f"{label} must be a list")
    skills = []
    for item in raw:
        if not isinstance(item, dict) or set(item) != {"name", "path"}:
            raise PackError(f"{label}: each entry is {{name, path}}")
        name = item["name"]
        if not isinstance(name, str) or not PLUGIN_NAME.match(name) or name in [skill["name"] for skill in skills]:
            raise PackError(f"{label}: {name} is not a new skill name")
        path = _pack_folder(data, item["path"], f"{label} {name}")
        if not _isfile(os.path.join(path, "SKILL.md")):
            raise PackError(f"{label} {name}: {path} has no SKILL.md")
        skills.append({"name": name, "path": path})
    return skills


def _extra_plugins(data) -> None:
    """[{name, path, where}]: a Hermes plugin cockpit links beside itself. where is root, seats, or a list of kinds.

    A plugin whose plugin.yaml says kind: model-provider goes under plugins/model-providers/, which Hermes loads
    without plugins.enabled. Any other plugin is also added to that home's plugins.enabled.
    """
    raw = data.get("extra_plugins")
    data["extra_plugins"] = []
    if raw is None:
        return
    if not isinstance(raw, list):
        raise PackError("extra_plugins must be a list")
    seats = [kind for kind in SEAT_KINDS if kind not in ("_common", "root")]
    for item in raw:
        if not isinstance(item, dict) or set(item) != {"name", "path", "where"}:
            raise PackError("extra_plugins: each entry is {name, path, where}")
        name = item["name"]
        taken = ["cockpit", *[plugin["name"] for plugin in data["extra_plugins"]]]
        if not isinstance(name, str) or not PLUGIN_NAME.match(name) or name in taken:
            raise PackError(f"extra_plugins: {name} is not a new plugin name")
        path = _pack_folder(data, item["path"], f"extra_plugins {name}")
        manifest = os.path.join(path, "plugin.yaml")
        if not _isfile(manifest):
            raise PackError(f"extra_plugins {name}: {path} has no plugin.yaml")
        where = item["where"]
        if where == "seats":
            where = seats
        if where == "root":
            where = ["root"]
        if not isinstance(where, list) or not where or any(kind not in ["root", *seats] for kind in where):
            raise PackError(f"extra_plugins {name}: where is root, seats, or a list of seat kinds")
        meta = yaml.safe_load(_open(manifest, encoding="utf-8"))
        provider = isinstance(meta, dict) and str(meta.get("kind") or "").strip() == "model-provider"
        data["extra_plugins"].append({"name": name, "path": path, "where": list(where), "provider": provider})


def extra_plugins_for(data, kind) -> list:
    """The extra plugins a home of this kind carries: root, or a seat kind."""
    return [plugin for plugin in (data or {}).get("extra_plugins") or [] if kind in plugin["where"]]


def seat_skills_for(data, kind) -> list:
    """The pack's skill links for a seat kind: _common's, then the kind's own, which win by name."""
    config = (data or {}).get("seat_config") or {}
    own = (config.get(kind) or {}).get("skills") or []
    common = [
        skill
        for skill in (config.get("_common") or {}).get("skills") or []
        if skill["name"] not in [s["name"] for s in own]
    ]
    return [*common, *own]


def _pack_folder(data, value, label) -> str:
    """A folder the pack names: absolute, or beside pack.yaml. It must exist."""
    if not isinstance(value, str) or not value.strip():
        raise PackError(f"{label} must be a path")
    path = value if os.path.isabs(value) else os.path.join(data["_dir"], value)
    if not _isdir(path):
        raise PackError(f"{label}: missing {path}")
    return os.path.realpath(path)


def _pack_file(data, value, label) -> str:
    """A file the pack names: absolute, or beside pack.yaml. It must exist."""
    if not isinstance(value, str) or not value.strip():
        raise PackError(f"{label} must be a path")
    path = value if os.path.isabs(value) else os.path.join(data["_dir"], value)
    if not _isfile(path):
        raise PackError(f"{label}: missing {path}")
    return os.path.realpath(path)


def _board_workdir(data) -> None:
    """The folder Hermes anchors a worktree card in when the card names none: {workspace} or {root} and a path."""
    raw = data.get("board_workdir")
    if raw is None:
        return
    if not isinstance(raw, str) or not (raw.startswith("{workspace}") or raw.startswith("{root}")):
        raise PackError("board_workdir must start with {workspace} or {root}")
    try:
        raw.format(workspace="/w", root="/r")
    except (KeyError, IndexError, ValueError) as exc:
        raise PackError(f"board_workdir: {exc}") from exc


# Verbs the kernel gives a meaning; any other verb a pack names runs through `cockpit slot run`.
SLOT_VERBS = (
    "up",
    "down",
    "reset",
    "warm",
    "ready",
    "status",
    "exec",
    "login",
    "frontend_start",
    "frontend_stop",
    "browser_start",
    "browser_stop",
    "test",
    "gc_probe",
)
SLOT_KEYS = {
    "provider",
    "max",
    "ports",
    "state_dir",
    "data_dir",
    "lock_wait_seconds",
    "idle_minutes",
    "gc_minutes",
    "commands",
    "exec_refuse",
    "toggles",
    "session",
    "stores",
    "close",
    "start_repo",
    "session_card",
}


def _lanes(data) -> None:
    """lanes: {by_slot: true, browser_session: true}. by_slot: a worker or tester card of a ticket that holds a slot goes to
    that slot's seat. browser_session: a lane's browser_exec names its own session, and each seat's browser harness lives
    under the seat (the default session is one browser shared by every profile on the machine)."""
    raw = data.get("lanes")
    if raw is None:
        return
    if (
        not isinstance(raw, dict)
        or set(raw) - {"by_slot", "browser_session"}
        or not all(isinstance(raw.get(key, False), bool) for key in ("by_slot", "browser_session"))
    ):
        raise PackError("lanes takes by_slot and browser_session: true or false")


def _asks(data) -> None:
    """asks: {name: {mark, label, command, deny}}. A lane's block that starts with `mark` gets an Approve button in the Inbox,
    which runs `command` as the human ({pack}, {lane}, {card}, {ticket} filled) and resumes the card with its output;
    Deny answers the card with `deny`. The pack's own approvals, beside the kernel's (credentials, a privileged login)."""
    raw = data.get("asks")
    if raw is None:
        return
    if not isinstance(raw, dict):
        raise PackError("asks maps a name to {mark, label, command, deny}")
    for name, entry in raw.items():
        if (
            not isinstance(entry, dict)
            or set(entry) - {"mark", "label", "command", "deny"}
            or not str(entry.get("mark") or "").strip()
        ):
            raise PackError(f"asks.{name} is {{mark, label, command, deny}} with a mark")
        _argv(entry.get("command"), f"asks.{name}.command")
        try:
            [word.format(pack="", lane="", card="", ticket="") for word in entry["command"]]
        except (KeyError, IndexError, ValueError) as exc:
            raise PackError(
                f"asks.{name}.command: {exc} (fields: pack, lane, card, ticket; a literal brace is {{{{ or }}}})"
            ) from exc


def _argv(value, label) -> None:
    if not isinstance(value, list) or not value or not all(isinstance(word, str) and word for word in value):
        raise PackError(f"{label} must be a command: a list of words")


def _slots(data) -> None:
    """slots: the runtime behind each slot. The kernel owns the binding (owner, ticket, lock, activity); the pack's
    commands own the runtime. A port is base + slot."""
    raw = data.get("slots")
    if raw is None:
        return
    if not isinstance(raw, dict) or set(raw) - SLOT_KEYS:
        raise PackError(f"slots takes {', '.join(sorted(SLOT_KEYS))}")
    if raw.get("provider", "command") not in ("none", "command"):
        raise PackError("slots.provider is none or command")
    ports = {} if raw.get("ports") is None else raw["ports"]
    if not isinstance(ports, dict) or any(
        not PLUGIN_NAME.match(str(name)) or not isinstance(base, int) or base < 1 for name, base in ports.items()
    ):
        raise PackError("slots.ports maps a name to a base port")
    for field in ("max", "lock_wait_seconds", "idle_minutes", "gc_minutes"):
        if field in raw and (not isinstance(raw[field], int) or raw[field] < 0):
            raise PackError(f"slots.{field} must be a whole number")
    if raw.get("gc_minutes") is not None and not 1 <= int(raw["gc_minutes"]) <= 1440:
        raise PackError("slots.gc_minutes is 1 to 1440: how often the slot cleanup runs")
    for field in ("state_dir", "data_dir"):
        if field in raw and (not isinstance(raw[field], str) or "{slot}" not in raw[field]):
            raise PackError(f"slots.{field} must name {{slot}}")
    commands = {} if raw.get("commands") is None else raw["commands"]
    if not isinstance(commands, dict):
        raise PackError("slots.commands maps a verb to {argv, who, passthrough}")
    for verb, entry in commands.items():
        if (
            not isinstance(entry, dict)
            or set(entry) - {"argv", "who", "passthrough"}
            or not PLUGIN_NAME.match(str(verb).replace("_", "-"))
        ):
            raise PackError(f"slots.commands.{verb} is {{argv, who, passthrough}}")
        _argv(entry.get("argv"), f"slots.commands.{verb}.argv")
        if entry.get("who", "both") not in ("human", "lane", "both"):
            raise PackError(f"slots.commands.{verb}.who is human, lane, or both")
        if "{args...}" in entry["argv"] and not entry.get("passthrough"):
            raise PackError(f"slots.commands.{verb}: {{args...}} needs passthrough: true")
    _patterns_list([] if raw.get("exec_refuse") is None else raw["exec_refuse"], "slots.exec_refuse")
    toggles = {} if raw.get("toggles") is None else raw["toggles"]
    if not isinstance(toggles, dict):
        raise PackError("slots.toggles maps a name to {on, off, status}")
    for name, entry in toggles.items():
        if isinstance(entry, dict):
            # YAML 1.1 reads a bare on and off as true and false.
            entry = {{True: "on", False: "off"}.get(key, key): value for key, value in entry.items()}
            toggles[name] = entry
        if not isinstance(entry, dict) or set(entry) != {"on", "off", "status"}:
            raise PackError(f"slots.toggles.{name} is {{on, off, status}}")
        for action, argv in entry.items():
            _argv(argv, f"slots.toggles.{name}.{action}")
    if raw.get("start_repo") is not None:
        _argv(
            raw["start_repo"], "slots.start_repo"
        )  # the Demo card's Start on one app: {slot}, {ticket} and {repo} are filled in
    _session_card(raw.get("session_card"))
    close = {} if raw.get("close") is None else raw["close"]
    if (
        not isinstance(close, dict)
        or set(close) - {"human_only", "keep_stack", "keep_runs"}
        or any(not isinstance(value, bool) for value in close.values())
    ):
        raise PackError(
            "slots.close takes human_only, keep_stack and keep_runs, each true or false (human_only: only a manual session closes; "
            "keep_stack: the slot's stack stays up for the cleanup; keep_runs: the tester runs of the ticket are not failed)"
        )
    session = {} if raw.get("session") is None else raw["session"]
    if not isinstance(session, dict) or set(session) - {"open", "close", "handoff"}:
        raise PackError("slots.session takes open and close (and handoff)")
    for action, argv in session.items():
        _argv(argv, f"slots.session.{action}")
    stores = [] if raw.get("stores") is None else raw["stores"]
    if not isinstance(stores, list):
        raise PackError("slots.stores is a list")
    for store in stores:
        if (
            not isinstance(store, dict)
            or not store.get("name")
            or set(store) - {"name", "probe", "capacity", "minimum", "names"}
        ):
            raise PackError("slots.stores entries are {name, probe, capacity, minimum, names}")
        _argv(store.get("probe"), f"slots.stores {store['name']}.probe")
        if "capacity" in store:
            _argv(store["capacity"], f"slots.stores {store['name']}.capacity")


def _session_card(card) -> None:
    """slots.session_card: the ticket pane's card while a manual session is open. apps maps a name to a URL template ({slot},
    {ticket}, {port.<name>} filled in); logins lists {label, user} for the credential picker; default names the preselected label."""
    if card is None:
        return
    if not isinstance(card, dict) or set(card) - {"apps", "logins", "default"}:
        raise PackError("slots.session_card takes apps, logins and default")
    apps = card.get("apps") or {}

    def app_ok(spec) -> bool:
        url = spec.get("url") if isinstance(spec, dict) else spec
        if isinstance(spec, dict) and (
            set(spec) - {"url", "repo"} or (spec.get("repo") is not None and not isinstance(spec["repo"], str))
        ):
            return False
        return isinstance(url, str) and url.startswith(("http://", "https://"))

    if not isinstance(apps, dict) or not all(isinstance(name, str) and app_ok(spec) for name, spec in apps.items()):
        raise PackError("slots.session_card.apps maps a name to an http(s) URL template, or to {url, repo}")
    logins = card.get("logins") or []
    if not isinstance(logins, list) or not all(
        isinstance(row, dict)
        and set(row) == {"label", "user"}
        and all(isinstance(value, str) and value for value in row.values())
        for row in logins
    ):
        raise PackError("slots.session_card.logins lists {label, user}")
    if card.get("default") is not None and card["default"] not in [row["label"] for row in logins]:
        raise PackError("slots.session_card.default is one of the logins' labels")


def compiles(pattern: str) -> None:
    """Compile a pack's pattern to see that it is one; `re.error` when it is not. A pattern Python reads today and warns
    it may read otherwise one day (a `[` inside a set, "possible nested set") loads as it always did: that warning is
    about a future Python, and a load prints nothing."""
    import warnings

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", FutureWarning)
        re.compile(pattern)


def _patterns_list(value, label) -> None:
    if not isinstance(value, list) or not all(isinstance(item, str) and item for item in value):
        raise PackError(f"{label} must be a list of patterns")
    for item in value:
        try:
            compiles(item)
        except re.error as exc:
            raise PackError(f"{label}: {exc}") from exc


TESTFLOW_KEYS = {
    "never_write",
    "run_dir",
    "review_mark",
    "send_back",
    "test_run_posts",
    "attach",
    "title",
    "banners",
    "evidence_dir",
    "plan_file",
    "results_file",
}
BANNER_KEYS = ("ok", "not_ok", "in_progress")
FILE_NAME = re.compile(r"[\w-][\w.-]*")  # one name inside a folder: no separator, no leading dot


def _testflow_words(raw) -> None:
    """testflow.title and testflow.banners {ok, not_ok, in_progress}: what a test report is called and the line it gives
    its verdict in. Each is one line of text; the banners differ, since a report is read back by them."""
    line = lambda value: isinstance(value, str) and bool(value.strip()) and "\n" not in value and value == value.strip()
    if "title" in raw and raw["title"] is not None and not line(raw["title"]):
        raise PackError("testflow.title is the heading of a test report: one line of text")
    banners = raw.get("banners")
    if banners is None:
        return
    if not isinstance(banners, dict) or set(banners) - set(BANNER_KEYS):
        raise PackError("testflow.banners takes ok, not_ok and in_progress")
    given = [banners[key] for key in BANNER_KEYS if banners.get(key) is not None]
    if not all(line(value) for value in given):
        raise PackError("testflow.banners: each of ok, not_ok and in_progress is one line of text")
    from .test_flow import banners as in_force

    words = list(in_force({"testflow": {"banners": banners}}).values())
    if len(set(words)) != len(words):
        raise PackError(
            f"testflow.banners: the three lines must differ ({', '.join(words)}): a report is read back by them"
        )


def _testflow(data) -> None:
    """testflow: {never_write: [patterns], run_dir, review_mark}. A pattern is matched against "METHOD URL"; review_mark is the
    words a tester's block uses to ask for the review of its run (default "ready for review"). title, banners,
    evidence_dir, plan_file and results_file name a test report and a run's files (defaults: the kernel's own)."""
    raw = data.get("testflow")
    if raw is None:
        return
    if not isinstance(raw, dict) or set(raw) - TESTFLOW_KEYS:
        raise PackError(
            "testflow takes never_write, run_dir and review_mark (and, optionally, send_back, test_run_posts, attach, title, "
            "banners, evidence_dir, plan_file and results_file)"
        )
    _testflow_words(raw)
    for key in ("evidence_dir", "plan_file", "results_file"):
        if raw.get(key) is not None and (not isinstance(raw[key], str) or not FILE_NAME.fullmatch(raw[key])):
            raise PackError(
                f"testflow.{key} is one file or folder name inside a run's folder (letters, digits, dot, dash, underscore)"
            )
    from .test_flow import evidence_dir, plan_file, results_file

    names = [reader({"testflow": raw}) for reader in (evidence_dir, plan_file, results_file)]
    if len(set(names)) != len(names):
        raise PackError(f"testflow.evidence_dir, plan_file and results_file must be three names ({', '.join(names)})")
    if raw.get("attach") not in (None, "failed"):
        raise PackError(
            "testflow.attach is failed (a test report's results post attaches the failed rows' screenshots and videos, those only)"
        )
    if raw.get("test_run_posts") not in (None, "kickoff"):
        raise PackError("testflow.test_run_posts is kickoff (a test report needs a test kickoff and the human's go)")
    if "send_back" in raw and not isinstance(raw["send_back"], int):
        raise PackError(
            "testflow.send_back is the seconds a tester's review request of an unfinished run waits before housekeeping sends it back"
        )
    if "review_mark" in raw and (not isinstance(raw["review_mark"], str) or not raw["review_mark"].strip()):
        raise PackError("testflow.review_mark is the words of a tester's review request")
    if "run_dir" in raw and (
        not isinstance(raw["run_dir"], str) or not re.fullmatch(r"[\w.-]*\{n(:0\d+d)?\}[\w.-]*", raw["run_dir"])
    ):
        raise PackError("testflow.run_dir is a folder name with {n} (or {n:03d})")
    never = raw.get("never_write") or []
    if not isinstance(never, list) or not all(isinstance(item, str) and item for item in never):
        raise PackError("testflow.never_write must be a list of patterns")
    for item in never:
        try:
            re.compile(item)
        except re.error as exc:
            raise PackError(f"testflow.never_write: {exc}") from exc


def board_workdir(data) -> str:
    """The pack's board_workdir as an absolute path, or empty."""
    from .paths import root, workspace

    raw = (data or {}).get("board_workdir") or ""
    return os.path.normpath(raw.format(workspace=workspace(), root=root())) if raw else ""


def _records_dir(data) -> None:
    """A folder inside the workspace. Absent means hermes."""
    raw = data.get("records_dir")
    if raw is None:
        return
    if not isinstance(raw, str) or not raw.strip() or os.path.isabs(raw) or ".." in raw.split("/"):
        raise PackError("records_dir must be a folder inside the workspace")
    data["records_dir"] = os.path.normpath(raw.strip())


def _hours(data) -> None:
    """hours: each job's time, a whole hour or "HH:MM"; the *_minutes, *_hours and *_seconds keys are counts."""
    from .window import clock

    for name, value in (data.get("hours") or {}).items():
        if name.endswith(("_minutes", "_hours", "_seconds")):
            if not isinstance(value, (int, float)) or value <= 0:
                raise PackError(f"hours.{name} is a number above zero")
            continue
        try:
            clock(value)
        except PackError as exc:
            raise PackError(f"hours.{name}: {exc}") from exc


def _grooming(data) -> None:
    """grooming: the acts a dependency bump needs before it leaves the bump flow. A name the human ticks, or
    {name, intent, field, event}: done once an intent of that type for the PR is published (with that payload field,
    with that review event)."""
    from .intents import FIELDS, TYPES

    raw = data.get("grooming") or []
    if not isinstance(raw, list):
        raise PackError("grooming")
    names, rules = [], []
    for item in raw:
        if isinstance(item, str) and item.strip():
            names.append(item.strip())
            continue
        if (
            not isinstance(item, dict)
            or set(item) - {"name", "intent", "field", "event"}
            or not str(item.get("name") or "").strip()
            or item.get("intent") not in TYPES
            or (item.get("field") and item["field"] not in FIELDS)
        ):
            raise PackError(
                "grooming lists act names, or {name, intent, field, event} with an intent type and a payload field"
            )
        names.append(item["name"].strip())
        rules.append(
            {
                "name": item["name"].strip(),
                "intent": item["intent"],
                "field": item.get("field") or "",
                "event": item.get("event") or "",
            }
        )
    data["grooming"] = names
    data["grooming_rules"] = rules


def _bump_sequence(data) -> None:
    """bump_sequence: the order a bump batch's acts reach the forge and tracker, one stage at a time per PR.
    {stages: [{name, intent, field, event, after}], barrier: <stage name>}. A stage is the intent type that performs it
    (a pr-edit stage names the payload fields that make it, an approval its review event); each stage waits for the one
    before it, or for one of `after`. The stages after the barrier wait until every PR of the repo's batch is through it."""
    from .intents import EVENTS, FIELDS, TYPES

    raw = data.get("bump_sequence")
    if raw is None:
        return
    if (
        not isinstance(raw, dict)
        or set(raw) - {"stages", "barrier"}
        or not isinstance(raw.get("stages"), list)
        or not raw["stages"]
    ):
        raise PackError("bump_sequence takes stages: [{name, intent, field, event, after}] and barrier: <stage>")
    stages = []
    for item in raw["stages"]:
        if (
            not isinstance(item, dict)
            or set(item) - {"name", "intent", "field", "event", "after"}
            or not str(item.get("name") or "").strip()
            or item.get("intent") not in TYPES
        ):
            raise PackError("bump_sequence stage: {name, intent, field, event, after} with an intent type")
        fields = item.get("field") or []
        fields = [fields] if isinstance(fields, str) else fields
        if not isinstance(fields, list) or any(field not in FIELDS for field in fields):
            raise PackError(f"bump_sequence stage {item['name']}: field names payload fields")
        if item.get("event") and item["event"] not in EVENTS:
            raise PackError(f"bump_sequence stage {item['name']}: event is one of {', '.join(EVENTS)}")
        known = [stage["name"] for stage in stages]
        after = item.get("after") or ([known[-1]] if known else [])
        after = [after] if isinstance(after, str) else after
        if not isinstance(after, list) or any(name not in known for name in after):
            raise PackError(f"bump_sequence stage {item['name']}: after names earlier stages")
        if item["name"] in known:
            raise PackError(f"bump_sequence stage {item['name']} is named twice")
        stages.append(
            {
                "name": item["name"],
                "intent": item["intent"],
                "fields": fields,
                "event": item.get("event") or "",
                "after": after,
            }
        )
    barrier = raw.get("barrier") or ""
    if barrier and barrier not in [stage["name"] for stage in stages]:
        raise PackError(f"bump_sequence barrier {barrier} is not a stage")
    data["bump_sequence"] = {"stages": stages, "barrier": barrier}


def _advisories(data) -> None:
    """advisories: the stack watch. {sources: [names from the registry], alert: {critical, exploited, patch_scheduled,
    high_days}, minutes}. Without the block the watch is off."""
    from .advisories.match import ALERT
    from .advisories.sources import NAMES

    raw = data.get("advisories")
    if raw is None:
        return
    if not isinstance(raw, dict) or set(raw) - {"sources", "alert", "minutes"}:
        raise PackError("advisories takes sources, alert and minutes")
    named = raw.get("sources")
    if named is not None and (not isinstance(named, list) or not named or any(name not in NAMES for name in named)):
        raise PackError(f"advisories.sources names sources from {', '.join(NAMES)}")
    alert = raw.get("alert") or {}
    if (
        not isinstance(alert, dict)
        or set(alert) - set(ALERT)
        or any(not isinstance(alert[key], bool) for key in ("critical", "exploited", "patch_scheduled") if key in alert)
        or (
            "high_days" in alert
            and (
                isinstance(alert["high_days"], bool)
                or not isinstance(alert["high_days"], int)
                or alert["high_days"] < 0
            )
        )
    ):
        raise PackError(
            "advisories.alert takes critical, exploited, patch_scheduled (true or false) and high_days (days, 0 for never)"
        )
    minutes = raw.get("minutes")
    if minutes is not None and (isinstance(minutes, bool) or not isinstance(minutes, int) or not 5 <= minutes <= 1440):
        raise PackError("advisories.minutes is how often the watch runs, 5 to 1440")


def _fixture(data) -> bool:
    return os.path.basename(os.path.dirname(data["_dir"])) == "packs"


def _skills(data) -> list:
    raw = data["skills_dir"]
    if isinstance(raw, str):
        raw = [raw]
    if not isinstance(raw, list) or len(raw) == 0:
        raise PackError("skills_dir: absolute path required")
    found = []
    for item in raw:
        if not isinstance(item, str) or item == "":
            raise PackError("skills_dir: absolute path required")
        if item.startswith("@"):
            if not _fixture(data):
                raise PackError(f"skills_dir {item}: must be absolute")
            name = item[1:]
            if re.fullmatch(r"[A-Za-z0-9_-]+", name) is None:
                raise PackError(f"skills_dir {item}: must be absolute")
            path = os.path.realpath(os.path.join(data["_dir"], name))
        elif item.startswith(PACK_ANCHOR):
            # a folder of the pack itself, so a pack names its own skills without this machine's path
            inner = item[len(PACK_ANCHOR) :]
            path = os.path.realpath(os.path.join(data["_dir"], inner))
            if (
                not inner
                or os.path.isabs(inner)
                or ".." in inner.split("/")
                or not (path + os.sep).startswith(os.path.realpath(data["_dir"]) + os.sep)
            ):
                raise PackError(f"skills_dir {item}: {PACK_ANCHOR}<folder> names a folder inside the pack")
        else:
            if (not os.path.isabs(item)) or (".." in item.split(os.sep)):
                raise PackError(f"skills_dir {item}: must be absolute")
            path = os.path.realpath(item)
        if not _isdir(path):
            raise PackError(f"skills_dir {path}: missing directory")
        found.append(path)
    return found


def _providers(data) -> None:
    providers = data["providers"]
    if not isinstance(providers, dict) or "coding" not in providers:
        raise PackError("providers.coding required")
    coding = providers["coding"]
    command = coding.get("command") if isinstance(coding, dict) else None
    if not isinstance(command, list) or len(command) == 0 or not all(isinstance(part, str) for part in command):
        raise PackError("providers.coding.command required")
    coding.setdefault("display_name", "Chat")
    lane_glob = coding.get("lane_transcript_glob")
    if lane_glob is not None and (
        not isinstance(lane_glob, str) or not ("{card}" in lane_glob or "{card_slug}" in lane_glob)
    ):
        raise PackError("providers.coding.lane_transcript_glob must name {card} or {card_slug}")
    if "chat" in providers:
        chat = providers["chat"]
        if not isinstance(chat, dict):
            raise PackError("providers.chat must be a mapping")
        for key in ("command", "resume", "fork"):
            argv = chat.get(key)
            if argv is None and key != "command":
                continue
            if not isinstance(argv, list) or len(argv) == 0 or not all(isinstance(part, str) and part for part in argv):
                raise PackError(f"providers.chat.{key} must be a list of strings")
        glob_text = chat.get("session_glob")
        if glob_text is not None and (not isinstance(glob_text, str) or "{session}" not in glob_text):
            raise PackError("providers.chat.session_glob must name {session}")
        unknown = [
            key
            for key in chat
            if key not in ("command", "resume", "fork", "session_glob", "display_name", "cwd", "env")
        ]
        if unknown:
            raise PackError(f"providers.chat: unknown key {unknown[0]}")
        if chat.get("cwd") is not None and (not isinstance(chat["cwd"], str) or not chat["cwd"]):
            raise PackError("providers.chat.cwd is a folder: {ticket}, {wt}, {workspace} and {root} are filled in")
        chat_env = chat.get("env")
        if chat_env is not None and (
            not isinstance(chat_env, dict)
            or not all(isinstance(key, str) and key and isinstance(value, str) for key, value in chat_env.items())
        ):
            raise PackError("providers.chat.env maps a variable to a text ({PATH} is the current PATH)")
    roles = data["roles"]
    if not isinstance(roles, dict):
        raise PackError("roles must be a mapping")
    for role in ROLES:
        name = roles.get(role)
        if name not in providers:
            raise PackError(f"roles.{role}: unknown provider {name}")
        if name in ("coding", "chat"):
            raise PackError(f"roles.{role}: {name} is not a lane provider")
        entry = providers[name]
        if not isinstance(entry, dict) or not entry.get("hermes_provider") or not entry.get("model"):
            raise PackError(f"providers.{name}: hermes_provider and model required")


def _ide(data) -> None:
    """ide.command opens the IDE on a ticket ({ticket}); ide.file_command opens one file ({path}). A relative
    first word is a file in the pack folder."""
    raw = data.get("ide") or {}
    if not isinstance(raw, dict):
        raise PackError("ide must be a mapping")
    for key in ("command", "file_command"):
        argv = raw.get(key)
        if argv is None:
            continue
        if not isinstance(argv, list) or len(argv) == 0 or not all(isinstance(part, str) and part for part in argv):
            raise PackError(f"ide.{key} must be a list of strings")
    unknown = [key for key in raw if key not in ("command", "file_command")]
    if unknown:
        raise PackError(f"ide: unknown key {unknown[0]}")
    data["ide"] = dict(raw)


def _desktop(data) -> None:
    """desktop.overrides: names from DESKTOP_OVERRIDES, the Desktop fixes this machine needs. desktop.mermaid_url: the ES module
    the diagram frame loads mermaid from (none: a diagram shows its source). desktop.live_jobs: how many of the newest jobs Live's
    "all" stream merges (none: every ticket)."""
    raw = data.get("desktop") or {}
    if not isinstance(raw, dict) or [key for key in raw if key not in DESKTOP_KEYS]:
        raise PackError(
            "desktop takes overrides (and mermaid_url, live_jobs, done_recent_hours, diff_held_suffix, hints)"
        )
    hints = raw.get("hints")
    if hints is not None:
        if not isinstance(hints, dict) or set(hints) - set(DESKTOP_HINTS):
            raise PackError(f"desktop.hints takes {', '.join(DESKTOP_HINTS)}, each a help text of the pages")
        for name, text in hints.items():
            if text is not None and (not isinstance(text, str) or "\n" in text or len(text) > 600):
                raise PackError(f"desktop.hints.{name} is one line of text of at most 600 characters")
    suffix = raw.get("diff_held_suffix")
    if suffix is not None and (not isinstance(suffix, str) or not re.fullmatch(r"[\w.-]*", suffix)):
        raise PackError(
            "desktop.diff_held_suffix is the end of a branch name (letters, digits, dot, dash, underscore), or empty for none"
        )
    recent = raw.get("done_recent_hours")
    if recent is not None and (not isinstance(recent, int) or isinstance(recent, bool) or not 1 <= recent <= 24 * 30):
        raise PackError(
            "desktop.done_recent_hours is a whole number of hours from 1 to 720 (the Board's Done keeps a ticket in view this long)"
        )
    url = raw.get("mermaid_url")
    if url is not None and (
        not isinstance(url, str) or not url.startswith("https://") or any(ch in url for ch in "'\"<> ")
    ):
        raise PackError("desktop.mermaid_url is an https URL of the mermaid ES module")
    jobs = raw.get("live_jobs")
    if jobs is not None and (not isinstance(jobs, int) or isinstance(jobs, bool) or jobs < 1):
        raise PackError("desktop.live_jobs is a whole number above zero")
    names = raw.get("overrides") or []
    if not isinstance(names, list) or not all(isinstance(name, str) for name in names):
        raise PackError("desktop.overrides must be a list of names")
    unknown = [name for name in names if name not in DESKTOP_OVERRIDES]
    if unknown:
        raise PackError(f"desktop.overrides: no override {unknown[0]} (known: {', '.join(DESKTOP_OVERRIDES)})")
    data["desktop"] = {
        "overrides": list(dict.fromkeys(names)),
        **({"mermaid_url": url} if url else {}),
        **({"live_jobs": jobs} if jobs else {}),
        **({"done_recent_hours": recent} if recent else {}),
        **({"diff_held_suffix": suffix} if suffix is not None else {}),
        **({"hints": dict(hints)} if hints else {}),
    }


def _standup(data) -> None:
    """standup: {sections: {<id>: <heading>}, order: [<id>, …], chat_file}: the standup note's headings (an empty one
    hides its section), the order of its sections, and the file its chat-formatted twin is written to. Beside
    standup_enabled and hours.standup, which say whether and when the note is drafted."""
    raw = data.get("standup")
    if raw is None:
        return
    from .standup_note import LABELS, ORDER

    if not isinstance(raw, dict) or set(raw) - {"sections", "order", "chat_file"}:
        raise PackError("standup takes sections, order and chat_file")
    sections = raw.get("sections")
    if sections is not None:
        if not isinstance(sections, dict) or set(sections) - set(LABELS):
            raise PackError(f"standup.sections names sections of the note ({', '.join(LABELS)}), each with its heading")
        for name, text in sections.items():
            if text is not None and (not isinstance(text, str) or "\n" in text):
                raise PackError(f"standup.sections.{name} is a heading: one line of text, or empty to hide the section")
    order = raw.get("order")
    if order is not None and (
        not isinstance(order, list)
        or set(order) - set(ORDER)
        or len(set(order)) != len(order)
        or not all(isinstance(name, str) for name in order)
    ):
        raise PackError(f"standup.order lists sections of the note, each once ({', '.join(ORDER)})")
    name = raw.get("chat_file")
    if name is not None and (
        not isinstance(name, str) or not FILE_NAME.fullmatch(name) or name in ("standup.md", "standup.json")
    ):
        raise PackError("standup.chat_file is one file name beside standup.md (letters, digits, dot, dash, underscore)")


def _seats(data) -> None:
    seats = data["seats"]
    if not isinstance(seats, dict):
        raise PackError("seats must be a mapping")
    for key, low, high in (("slots", 0, 8), ("intake", 1, 8), ("reviewer", 1, 8), ("analyst", 1, 8)):
        value = seats.get(key)
        if not isinstance(value, int) or value < low or value > high:
            raise PackError(f"seats.{key} out of range")
    data.setdefault("slot_provider", "none" if seats["slots"] == 0 else "pack")


def _companion_files(folder: str, names) -> list:
    """Each of those files of the pack's folder, personal values filled in; every name the local file does not set, in
    any of them, in the one error."""
    from . import pack_local

    lines: list = []
    found = [pack_local.read(os.path.join(folder, name), unset=lines) for name in names]
    if lines:
        raise pack_local.Unset(lines)
    return found


def _companions(data) -> None:
    folder = data["_dir"]
    for name in ("repos.yaml", "skills.yaml", "egress.yaml"):
        path = os.path.join(folder, name)
        if not _isfile(path):
            raise PackError(f"missing {name}")
    repos, skills, egress = _companion_files(folder, ("repos.yaml", "skills.yaml", "egress.yaml"))
    data["repos"] = repos or {}
    data["skills"] = skills or {}
    data["egress"] = {} if egress is None else egress
    _egress(data["egress"])
    _agent(data)
    _router(data)
    if not isinstance(data["repos"].get("repos"), list):
        raise PackError("repos.yaml: repos list required")
    _cards(data)
    for skill in _skill_names(data):
        if find_skill(data, skill) is None and skill in BUNDLED:
            raise PackError(f"skill {skill} not found (cockpit's own is {NAMESPACE}{skill})")
        if find_skill(data, skill) is None:
            raise PackError(f"skill {skill} not found")


def _patterns(value, label) -> None:
    if not isinstance(value, list) or not all(isinstance(item, str) and item for item in value):
        raise PackError(f"egress.yaml {label} must be a list of patterns")
    for item in value:
        try:
            compiles(item)
        except re.error as exc:
            raise PackError(f"egress.yaml {label}: {exc}") from exc


def _egress(egress) -> None:
    """The per-seat keys: role_deny, git_deny and write_roots by seat kind, and the MCP tools that may write."""
    if not isinstance(egress, dict):
        raise PackError("egress.yaml must be a mapping")
    allowed = egress.get("mcp_allow") or []
    if not isinstance(allowed, list) or not all(isinstance(item, str) and item.startswith("mcp__") for item in allowed):
        raise PackError("egress.yaml mcp_allow must list MCP tool names (mcp__<server>__<tool>)")
    for field in ("local_domains", "destructive_http"):
        _patterns(egress.get(field) or [], field)
    denied = egress.get("deny_tools") or []
    if not isinstance(denied, list) or not all(isinstance(item, str) and item for item in denied):
        raise PackError("egress.yaml deny_tools must list tool names")
    probes = egress.get("host_probes") or {}
    if (
        not isinstance(probes, dict)
        or set(probes) - {"refused", "allowed"}
        or not all(
            isinstance(value, list) and all(isinstance(item, str) and item for item in value)
            for value in probes.values()
        )
    ):
        raise PackError("egress.yaml host_probes is {refused: [commands], allowed: [commands]}")
    declared = egress.get("no_production_hosts")
    if declared is not None and not isinstance(declared, bool):
        raise PackError("egress.yaml no_production_hosts is true or false")
    if declared is True and egress.get("production_hosts"):
        raise PackError(
            "egress.yaml no_production_hosts: true says this project has no production, yet production_hosts lists hosts: keep one"
        )
    if "card_repos_only" in egress:
        raise PackError(
            "egress.yaml: unknown key card_repos_only: it was removed; a worker writes only in its ticket's worktrees"
        )
    seats = [kind for kind in SEAT_KINDS if kind not in ("_common", "root")]
    for field in ("role_deny", "write_roots"):
        block = egress.get(field) or {}
        if not isinstance(block, dict) or any(kind not in seats for kind in block):
            raise PackError(f"egress.yaml {field} is keyed by seat kind")
        for kind, value in block.items():
            if field == "role_deny":
                _patterns(value, f"role_deny.{kind}")
                continue
            if not isinstance(value, list) or not all(
                isinstance(item, str) and (os.path.isabs(item) or item.startswith(("{workspace}", "{root}")))
                for item in value
            ):
                raise PackError(
                    f"egress.yaml write_roots.{kind}: each is absolute or starts at {{workspace}} or {{root}}"
                )
    moves = egress.get("git_deny") or {}
    if not isinstance(moves, dict) or any(kind not in seats for kind in moves):
        raise PackError("egress.yaml git_deny is keyed by seat kind")
    for kind, value in moves.items():
        if not isinstance(value, list) or not all(
            isinstance(item, str) and re.fullmatch(r"[a-z][a-z-]*(?:\s+--?[A-Za-z][\w-]*)*", item.strip())
            for item in value
        ):
            raise PackError(
                f"egress.yaml git_deny.{kind} lists git verbs, each with the flags that make it a move (`commit`, `checkout -b`)"
            )


def _agent(data) -> None:
    raw = data.get("agent") or {}
    if not isinstance(raw, dict):
        raise PackError("agent must be a mapping")
    args = raw.get("args") or []
    add_dirs = raw.get("add_dirs") or []
    if not isinstance(args, list) or not all(isinstance(item, str) for item in args):
        raise PackError("agent.args must be a list of strings")
    if not isinstance(add_dirs, list) or not all(isinstance(item, str) for item in add_dirs):
        raise PackError("agent.add_dirs must be a list of strings")
    home = raw.get("home") or ""
    if not isinstance(home, str):
        raise PackError("agent.home must be a path")
    if not isinstance(raw.get("cursor_hooks", False), bool):
        raise PackError("agent.cursor_hooks is true or false")
    data["agent"] = {
        "home": home,
        "add_dirs": list(add_dirs),
        "args": list(args),
        "cursor_hooks": bool(raw.get("cursor_hooks")),
    }


def _router(data) -> None:
    router = (data.get("skills") or {}).get("router") or ""
    if router and not isinstance(router, str):
        raise PackError("skills.yaml router must be a path")


def agent_launch(pack) -> dict:
    """Where the coding CLI starts, the args it receives, and the optional skill router file."""
    agent = pack.get("agent") or {}
    home = agent.get("home") or ""
    if home and not os.path.isabs(home):
        from .paths import workspace

        home = os.path.join(workspace(), home)
    if home:
        home = os.path.realpath(home)
    add_dirs = []
    for item in agent.get("add_dirs") or []:
        path = item if os.path.isabs(item) else os.path.join(home or ".", item)
        add_dirs.append(os.path.realpath(path))
    args = list(agent.get("args") or [])
    if home and "--workspace" not in args:
        args.extend(["--workspace", home])
    for path in add_dirs:
        args.extend(["--add-dir", path])
    router = (pack.get("skills") or {}).get("router") or ""
    router_path = ""
    if isinstance(router, str) and router:
        if os.path.isabs(router):
            router_path = os.path.realpath(router)
        else:
            beside = os.path.join(pack.get("_dir") or ".", router)
            if _isfile(beside):
                router_path = os.path.realpath(beside)
            else:
                router_path = os.path.realpath(os.path.join(home or pack.get("_dir") or ".", router))
    return {"home": home, "add_dirs": add_dirs, "args": args, "router": router_path}


def shipped(repo) -> bool:
    """A repo that ships to customers (repos.yaml shipped, default true): the advisories read it."""
    return repo.get("shipped", True) is not False


def bump_scanned(repo) -> bool:
    """A repo the bump scan reads: repos.yaml bumps when it says, else the watches' rule (watched)."""
    return repo["bumps"] if isinstance(repo.get("bumps"), bool) else watched(repo)


def watched(repo) -> bool:
    """A repo the watches read (repos.yaml watched, default true): the base-branch change scan and the bump scan. A
    repo a ticket may still check out but whose forge home is not the pack's (a personal tool, a repo of another
    organisation) is watched: false."""
    return repo.get("watched", True) is not False


def _repo_setup(data, repo) -> None:
    """A repo's worktree setup: copy (paths from the repo), hooks_path, worktree_files ({source beside the pack,
    target in the checkout}), after_add (commands run in the new checkout), branch_suffix_when_held, and shipped."""
    if not isinstance(repo, dict):
        return
    label = f"repos.yaml {repo.get('name')}"
    copied = [] if repo.get("copy") is None else repo["copy"]
    if not isinstance(copied, list) or not all(
        isinstance(item, str) and item and not os.path.isabs(item) for item in copied
    ):
        raise PackError(f"{label}: copy lists paths inside the repo")
    if "hooks_path" in repo and (not isinstance(repo["hooks_path"], str) or not repo["hooks_path"]):
        raise PackError(f"{label}: hooks_path is a folder")
    if "branch_suffix_when_held" in repo and (
        not isinstance(repo["branch_suffix_when_held"], str) or not repo["branch_suffix_when_held"]
    ):
        raise PackError(f"{label}: branch_suffix_when_held is a suffix")
    if "label" in repo and (not isinstance(repo["label"], str) or not repo["label"].strip()):
        raise PackError(f"{label}: label is the repo's short name (a plugin may name the repo by it)")
    if "shipped" in repo and not isinstance(repo["shipped"], bool):
        raise PackError(f"{label}: shipped is true or false (false: not a product, its advisories are not read)")
    if "watched" in repo and not isinstance(repo["watched"], bool):
        raise PackError(f"{label}: watched is true or false (false: the base scan and the bump scan leave it out)")
    if "bumps" in repo and not isinstance(repo["bumps"], bool):
        raise PackError(f"{label}: bumps is true or false (the bump scan reads the repo; default: as watched says)")
    if "watch_base" in repo and (not isinstance(repo["watch_base"], str) or not repo["watch_base"]):
        raise PackError(f"{label}: watch_base is the branch the base watch reads (default: the repo's base)")
    files = [] if repo.get("worktree_files") is None else repo["worktree_files"]
    if not isinstance(files, list):
        raise PackError(f"{label}: worktree_files lists {{source, target}}")
    for item in files:
        if not isinstance(item, dict) or set(item) != {"source", "target"} or os.path.isabs(str(item.get("target"))):
            raise PackError(f"{label}: worktree_files lists {{source, target}}")
        item["source"] = _pack_file(data, item["source"], f"{label} worktree_files")
    _patterns_list([] if repo.get("failures") is None else repo["failures"], f"{label} failures")
    after = [] if repo.get("after_add") is None else repo["after_add"]
    if not isinstance(after, list):
        raise PackError(f"{label}: after_add lists commands")
    for argv in after:
        _argv(argv, f"{label} after_add")
    checks = [] if repo.get("verify") is None else repo["verify"]
    if not isinstance(checks, list):
        raise PackError(
            f"{label}: verify lists commands run on a pushed range ({{base}}, {{sha}}, {{files}}, {{worktree}}, {{pack}})"
        )
    for argv in checks:
        _argv(argv, f"{label} verify")


VALIDATOR = "cockpit_pack.py"


TRACKER_KEYS = {
    "kind",
    "url",
    "project",
    "auth_env",
    "issue_type",
    "command",
    "summary_max",
    "connector",
    "browse_url",
    "reads",
    "local",
    "repo",
    "status_labels",
    "closed_statuses",
}
TRACKER_KINDS = (
    "connector",
    "jira",
    "command",
    "local",
    "github-issues",
)  # the trackers package's NAMES, spelled here so a load imports none
TRACKER_KINDS_ON_THE_FORGE = ("github-issues",)  # the kinds whose tickets are the forge's issues
TRACKER_ISSUE_KEYS = ("repo", "status_labels", "closed_statuses")  # the settings of those kinds alone
TRACKER_ISSUE_STATES = ("open", "closed")  # the two statuses an issue has with no label: they take none
TRACKER_READS = ("comments", "me", "status")
TRACKER_PAGE_FIELDS = ("url", "key", "project", "number")
TRACKER_LOCAL_STATUSES = (
    "To Do",
    "In Progress",
    "In Review",
    "Done",
)  # the local tracker's STATUSES, for the same reason
FORGE_KEYS = {
    "kind",
    "host",
    "local",
    "org",
    "human_login",
    "human_emails",
    "bots",
    "mention_tags",
    "review_labels",
    "ready_labels",
    "bump_batch",
    "skip_outdated",
    "rereview_at_once",
    "discover_prs",
    "bumps_shipped_only",
    "bump_push_prefix",
    "rereview_job",
    "tagged_comments_only",
}
FORGE_HOST = r"[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?(?::\d{1,5})?"
REREVIEW_FIELDS = {
    "ticket": "T-1",
    "repo": "api",
    "number": 1,
    "since": "abc",
    "head": "def",
    "head_ref": "work/x",
    "head_sha": "def0",
}


def _tracker(data) -> None:
    """tracker: the tracker cockpit writes to. kind connector (the default): Hermes's hosted connector (tracker.connector,
    default jira), signed in with `hermes connectors connect`. kind jira (rest is accepted as another name for it):
    Jira's REST API with the credentials the named environment variables hold. kind command: the pack's own command
    (argv, {pack} filled), which then receives each intent. kind local: tickets kept in files. kind github-issues: the
    issues of one repo on the pack's forge, <project>-<n> being issue n."""
    raw = data.get("tracker")
    if raw is None:
        return
    if not isinstance(raw, dict) or set(raw) - TRACKER_KEYS:
        raise PackError(f"tracker takes {', '.join(sorted(TRACKER_KEYS))}")
    if raw.get("kind", "connector") not in TRACKER_KINDS:
        raise PackError(f"tracker.kind is one of {', '.join(TRACKER_KINDS)}")
    connector = raw.get("connector")
    if connector is not None and not (isinstance(connector, str) and re.fullmatch(r"[a-z0-9_]+", connector)):
        raise PackError("tracker.connector names a Hermes connector, e.g. jira")
    names = raw.get("auth_env")
    if names is not None and (
        not isinstance(names, list) or len(names) != 2 or not all(isinstance(name, str) and name for name in names)
    ):
        raise PackError("tracker.auth_env names two environment variables: the email and the API token")
    command = raw.get("command")
    if command is not None:
        if not isinstance(command, list) or not command or not all(isinstance(word, str) and word for word in command):
            raise PackError("tracker.command is an argv list")
        raw["command"] = [word.replace("{pack}", data["_dir"]) for word in command]
    if raw.get("kind") == "command" and not raw.get("command"):
        raise PackError("tracker.kind command needs tracker.command")
    if raw.get("summary_max") is not None and (not isinstance(raw["summary_max"], int) or raw["summary_max"] < 1):
        raise PackError("tracker.summary_max is a positive whole number")
    # browse_url: a ticket's page as a template, for a tracker whose pages are not <url>/browse/<key>
    page = raw.get("browse_url")
    if page is not None and not (
        isinstance(page, str)
        and ("{key}" in page or "{number}" in page)
        and set(re.findall(r"\{([^{}]*)\}", page)) <= set(TRACKER_PAGE_FIELDS)
    ):
        raise PackError(
            "tracker.browse_url is a ticket's page with {key} in it (or {number}, the number the key ends with), and {url} or "
            "{project} where they go, e.g. '{url}/issues/{key}'"
        )
    # reads: the read actions the pack's command answers besides summary; one it does not name is never run
    reads = raw.get("reads")
    if reads is not None:
        if (
            not isinstance(reads, list)
            or not reads
            or set(map(str, reads)) - set(TRACKER_READS)
            or not all(isinstance(name, str) for name in reads)
        ):
            raise PackError(
                f"tracker.reads lists the read actions the tracker command answers: {', '.join(TRACKER_READS)}"
            )
        if not raw.get("command") or raw.get("kind", "command") != "command":
            raise PackError("tracker.reads is for a tracker by command (tracker.command)")
    local = raw.get("local")
    if local is not None:
        if (
            not isinstance(local, dict)
            or set(local) - {"root", "statuses", "transitions"}
            or ("root" in local and not (isinstance(local["root"], str) and local["root"]))
        ):
            raise PackError(
                "tracker.local takes root (the folder the local tracker keeps its tickets in), statuses and transitions"
            )
        names = local.get("statuses")
        if names is not None and (
            not isinstance(names, list)
            or not names
            or not all(isinstance(name, str) and name.strip() for name in names)
            or len({name.lower() for name in names}) != len(names)
        ):
            raise PackError(
                "tracker.local.statuses is a list of status names, the first a new ticket's, e.g. [To Do, Doing, Done]"
            )
        moves = local.get("transitions")
        known = names or TRACKER_LOCAL_STATUSES
        if moves is not None and (
            not isinstance(moves, dict)
            or not all(
                name in known and isinstance(to, list) and all(item in known for item in to)
                for name, to in moves.items()
            )
        ):
            raise PackError(
                "tracker.local.transitions maps a status to the statuses it may move to, each one of tracker.local.statuses, "
                "e.g. {To Do: [Doing], Doing: [Done]}"
            )
    # repo, status_labels, closed_statuses: the issues of the forge as tickets, and the labels that carry a status
    for key in TRACKER_ISSUE_KEYS:
        if key in raw and raw.get("kind") not in TRACKER_KINDS_ON_THE_FORGE:
            raise PackError(f"tracker.{key} is for tracker.kind {TRACKER_KINDS_ON_THE_FORGE[0]}")
    if "repo" in raw and not (isinstance(raw["repo"], str) and raw["repo"]):
        raise PackError("tracker.repo names a repo of repos.yaml: the one whose issues are the tickets")
    labels = raw.get("status_labels")
    if "status_labels" in raw and not (
        isinstance(labels, dict)
        and labels
        and all(isinstance(text, str) and text.strip() for pair in labels.items() for text in pair)
        and len({name.strip().lower() for name in labels})
        == len(labels)
        == len({label.strip().lower() for label in labels.values()})
        and not {name.strip().lower() for name in labels} & set(TRACKER_ISSUE_STATES)
    ):
        raise PackError(
            "tracker.status_labels maps a status name to the label that carries it, each name and each label once; Open and "
            "Closed are an issue's own and take none, e.g. {In Progress: in progress, Done: done}"
        )
    closed = raw.get("closed_statuses")
    if "closed_statuses" in raw and not (
        isinstance(closed, list) and all(isinstance(name, str) and name in (labels or {}) for name in closed)
    ):
        raise PackError(
            "tracker.closed_statuses lists statuses of tracker.status_labels: the ones a closed issue has, e.g. [Done]"
        )


def _tracker_repo(data) -> None:
    """tracker.repo is a repo of repos.yaml: checked once the pack's repos are read."""
    raw = data.get("tracker")
    if not isinstance(raw, dict) or "repo" not in raw:
        return
    known = [repo.get("name") for repo in data["repos"]["repos"] if isinstance(repo, dict)]
    if raw["repo"] not in known:
        raise PackError(
            f"tracker.repo names a repo of repos.yaml ({', '.join(str(name) for name in known)}), not {raw['repo']}"
        )


def _outbox_policy(data) -> None:
    """outbox: {auto: [{scope, types}]}: the intents of cards started in that scope (a release) publish with no click.
    An explicit opt-in; ticket-done and infra-note are never published."""
    raw = data.get("outbox")
    if raw is None:
        return
    from .intents import TYPES

    if (
        not isinstance(raw, dict)
        or set(raw)
        - {
            "auto",
            "amend_on_treat",
            "ci_rework_chain",
            "comment_card",
            "missing_skill",
            "ci_override",
            "supersede_reviews",
            "sweep_passes",
        }
        or not isinstance(raw.get("auto", []), list)
    ):
        raise PackError(
            "outbox takes auto: [{scope, types}], amend_on_treat, ci_rework_chain, comment_card, missing_skill, ci_override, "
            "supersede_reviews and sweep_passes"
        )
    passes = raw.get("sweep_passes")
    if passes is not None and (not isinstance(passes, int) or isinstance(passes, bool) or not 1 <= passes <= 10):
        raise PackError(
            "outbox.sweep_passes is a whole number from 1 to 10 (default 2): the gatekeeper sweeps that may end without "
            "deciding an intent before it becomes an Inbox row"
        )
    for key, meaning in (
        ("ci_rework_chain", "false: a CI rework card is not followed by a tester and a reviewer card"),
        ("comment_card", "true: a hold or a send back comments the card that wrote the intent"),
        (
            "supersede_reviews",
            "true: a lane's new review of a PR drops its older review of that PR that is not on the forge yet",
        ),
        (
            "ci_override",
            "false: the human may not approve despite red or missing CI (default: may, with a reason, on one approval)",
        ),
    ):
        if raw.get(key) is not None and not isinstance(raw[key], bool):
            raise PackError(f"outbox.{key} is true or false ({meaning})")
    if raw.get("missing_skill") not in (None, "hold", "rework"):
        raise PackError(
            "outbox.missing_skill is hold (the intent waits for the lane) or rework (it goes back to the lane with a card)"
        )
    if raw.get("amend_on_treat") is not None and not isinstance(raw["amend_on_treat"], bool):
        raise PackError(
            "outbox.amend_on_treat is true or false (false: new comments leave the open intents as they are, endorsements included)"
        )
    for rule in raw.get("auto") or []:
        if (
            not isinstance(rule, dict)
            or set(rule) != {"scope", "types"}
            or not isinstance(rule["scope"], str)
            or not rule["scope"]
        ):
            raise PackError("outbox.auto lists {scope, types}")
        if not isinstance(rule["types"], list) or any(
            kind not in TYPES or kind in ("ticket-done", "infra-note") for kind in rule["types"]
        ):
            raise PackError(
                f"outbox.auto types are intent types that publish ({', '.join(kind for kind in TYPES if kind not in ('ticket-done', 'infra-note'))})"
            )


def _watchers(data) -> None:
    """watchers: {limits: {name: {stale_minutes}}, base: {noise: [globs]}, ci: {failed_states: [conclusions]}}."""
    raw = data.get("watchers")
    if raw is None:
        return
    if not isinstance(raw, dict) or set(raw) - {"limits", "base", "ci"}:
        raise PackError("watchers takes limits, base and ci")
    for name, limit in (raw.get("limits") or {}).items():
        if (
            not isinstance(limit, dict)
            or set(limit) - {"stale_minutes"}
            or not isinstance(limit.get("stale_minutes"), int)
            or limit["stale_minutes"] < 1
        ):
            raise PackError(f"watchers.limits.{name} is {{stale_minutes: whole minutes}}")
    ci = raw.get("ci") or {}
    if isinstance(ci, dict) and ci.get("card_per_attempt") is not None and not isinstance(ci["card_per_attempt"], bool):
        raise PackError(
            "watchers.ci.card_per_attempt is true or false (true: a rerun that fails after a finished diagnosis gets its own card)"
        )
    for field, key in (("base", "noise"), ("ci", "failed_states")):
        block = raw.get(field) or {}
        if not isinstance(block, dict) or set(block) - {key} - ({"card_per_attempt"} if field == "ci" else set()):
            raise PackError(f"watchers.{field} takes {key}" + (" (and card_per_attempt)" if field == "ci" else ""))
        value = block.get(key, [])
        if not isinstance(value, list) or not all(isinstance(item, str) and item for item in value):
            raise PackError(f"watchers.{field}.{key} is a list")


ADVISOR_KEYS = {"command", "prompt", "max_calls", "checkpoints", "report_line", "in_tool"}
ADVISOR_OPTIONAL = {"report_on"}


def _advisor(data) -> None:
    """advisor: {checkpoints: {C0: {answers: [..]}}, command, prompt, max_calls, report_line, in_tool}."""
    raw = data.get("advisor")
    if raw is None:
        return
    if not isinstance(raw, dict) or set(raw) - ADVISOR_KEYS - ADVISOR_OPTIONAL:
        raise PackError(f"advisor takes {', '.join(sorted(ADVISOR_KEYS))} (and report_on)")
    report_on = raw.get("report_on")
    if report_on is not None and (
        not isinstance(report_on, list) or not all(isinstance(kind, str) and kind for kind in report_on)
    ):
        raise PackError(
            "advisor.report_on lists the card kinds whose finishing report carries the advisor's line (work, rework, ...)"
        )
    checkpoints = raw.get("checkpoints")
    if not isinstance(checkpoints, dict) or not checkpoints:
        raise PackError("advisor.checkpoints names each checkpoint and the answers it may give")
    for name, entry in checkpoints.items():
        answers = (entry or {}).get("answers") if isinstance(entry, dict) else None
        if (
            not isinstance(answers, list)
            or not answers
            or not all(isinstance(item, str) and re.fullmatch(r"[A-Z][A-Z_-]*", item) for item in answers)
        ):
            raise PackError(f"advisor.checkpoints.{name}.answers is a list of upper-case words")
        block_on = entry.get(
            "block_on"
        )  # the answers that hold the worker for the human (default: every answer but the first)
        if block_on is not None and (not isinstance(block_on, list) or not set(block_on) <= set(answers)):
            raise PackError(f"advisor.checkpoints.{name}.block_on lists some of its answers")
    if raw.get("command") is not None:
        _argv(raw["command"], "advisor.command")
    if raw.get("prompt") is not None:
        if not isinstance(raw["prompt"], str) or not raw["prompt"]:
            raise PackError("advisor.prompt is a file path")
        raw["prompt"] = raw["prompt"] if os.path.isabs(raw["prompt"]) else os.path.join(data["_dir"], raw["prompt"])
    if raw.get("max_calls") is not None and (
        not isinstance(raw["max_calls"], int) or isinstance(raw["max_calls"], bool) or raw["max_calls"] < 1
    ):
        raise PackError("advisor.max_calls is a whole number above zero")
    if raw.get("in_tool") is not None and not isinstance(raw["in_tool"], bool):
        raise PackError("advisor.in_tool is true or false")
    if raw.get("in_tool") and not raw.get("report_line"):
        raise PackError(
            "an advisor inside the coding tool needs advisor.report_line, the line the worker's report must carry"
        )
    if raw.get("report_line") is not None:
        try:
            compiles(str(raw["report_line"]))
        except re.error as exc:
            raise PackError(f"advisor.report_line: {exc}") from exc


def _prompts(data) -> None:
    """prompts: {name: path}; a relative path is beside pack.yaml. A missing file is doctor's red line, not a load error."""
    raw = data.get("prompts")
    if raw is None:
        return
    if not isinstance(raw, dict) or not all(
        isinstance(name, str) and re.fullmatch(r"[a-z0-9][a-z0-9_-]*", name) and isinstance(path, str) and path
        for name, path in raw.items()
    ):
        raise PackError("prompts maps a lowercase name to a file path")
    data["prompts"] = {
        name: path if os.path.isabs(path) else os.path.join(data["_dir"], path) for name, path in raw.items()
    }


def _environments(data) -> None:
    """environments: [{name, origins: {name: url}, slot: bool}]; capacity: {test_needs_slot, audit_blocks_tests,
    waiting_holds_seat (default true: a card blocked on the human keeps its seat)}."""
    listed = data.get("environments")
    if listed is not None:
        if not isinstance(listed, list) or not listed:
            raise PackError("environments is a list of {name, origins, slot}")
        names = set()
        for item in listed:
            if (
                not isinstance(item, dict)
                or set(item) - {"name", "origins", "slot"}
                or not re.fullmatch(r"[a-z][a-z0-9-]*", str(item.get("name") or ""))
            ):
                raise PackError("each environment is {name (lowercase), origins, slot}")
            if item["name"] in names:
                raise PackError(f"environment {item['name']} is listed twice")
            names.add(item["name"])
            origins = item.get("origins") or {}
            if not isinstance(origins, dict) or not all(
                isinstance(value, str) and re.match(r"https?://", value) for value in origins.values()
            ):
                raise PackError(f"environments {item['name']}: origins map a name to an http(s) origin")
            if not isinstance(item.get("slot", False), bool):
                raise PackError(f"environments {item['name']}: slot is true or false")
    capacity = data.get("capacity")
    if capacity is None:
        return
    if (
        not isinstance(capacity, dict)
        or set(capacity) - {"test_needs_slot", "audit_blocks_tests", "waiting_holds_seat"}
        or not all(isinstance(value, bool) for value in capacity.values())
    ):
        raise PackError("capacity takes test_needs_slot, audit_blocks_tests and waiting_holds_seat, each true or false")


def _perf_export(data) -> None:
    """perf: {command: argv}; export: {commands: [argv], keep: whole weeks}."""
    perf = data.get("perf")
    if perf is not None:
        if not isinstance(perf, dict) or set(perf) - {"command"}:
            raise PackError("perf takes command")
        _argv(perf.get("command"), "perf.command")
    export = data.get("export")
    if export is None:
        return
    if not isinstance(export, dict) or set(export) - {"commands", "keep"}:
        raise PackError("export takes commands and keep")
    if export.get("keep") is not None and (
        not isinstance(export["keep"], int) or isinstance(export["keep"], bool) or export["keep"] < 1
    ):
        raise PackError("export.keep is a whole number of backups to keep")
    commands = export.get("commands", [])
    if not isinstance(commands, list):
        raise PackError("export.commands is a list of argv")
    for index, argv in enumerate(commands):
        _argv(argv, f"export.commands[{index}]")


def _demo_login_origins(data) -> None:
    """demo_login_origins: the staging.yaml origin names a demo login looks in for the account's password, in order (default:
    the app's, then every other origin, e.g. a portal account). A pack whose origins are different environments lists only its own."""
    raw = data.get("demo_login_origins")
    if raw is not None and (
        not isinstance(raw, list) or not raw or not all(isinstance(name, str) and name for name in raw)
    ):
        raise PackError("demo_login_origins is a list of origin names from staging.yaml, such as [app]")


def _forge(data) -> None:
    """forge: who the human is on the forge, and the labels each review verdict sets."""
    raw = data.get("forge")
    if raw is None:
        return
    if not isinstance(raw, dict) or set(raw) - FORGE_KEYS:
        raise PackError(f"forge takes {', '.join(sorted(FORGE_KEYS))}")
    # kind: which forge the pack publishes to (github when unset); host: that forge's own host, for a GitHub Enterprise server
    from .forges import KINDS

    if raw.get("kind") is not None and raw["kind"] not in KINDS:
        raise PackError(f"forge.kind is one of {', '.join(sorted(KINDS))}")
    if raw.get("host") is not None and not (isinstance(raw["host"], str) and re.fullmatch(FORGE_HOST, raw["host"])):
        raise PackError("forge.host is the forge's host name, e.g. github.example.test")
    local = raw.get("local")
    if local is not None and (
        not isinstance(local, dict)
        or set(local) - {"root"}
        or ("root" in local and not (isinstance(local["root"], str) and local["root"]))
    ):
        raise PackError("forge.local takes root: the folder the local forge keeps its files in")
    # human_emails: the human's own author addresses besides the checkout's; a push with commits by them is not foreign
    for field in ("bots", "mention_tags", "ready_labels", "human_emails"):
        value = raw.get(field)
        if value is not None and (
            not isinstance(value, list) or not all(isinstance(item, str) and item for item in value)
        ):
            raise PackError(f"forge.{field} is a list of names")
    for field in ("skip_outdated", "rereview_at_once", "discover_prs", "bumps_shipped_only", "tagged_comments_only"):
        if raw.get(field) is not None and not isinstance(raw[field], bool):
            raise PackError(f"forge.{field} is true or false")
    if raw.get("rereview_job") is not None:
        # rereview_job: the "Your job" text of a re-review card, the pack's own review skills (the kernel's text otherwise)
        try:
            if not str(raw["rereview_job"]).strip():
                raise ValueError("empty")
            str(raw["rereview_job"]).format(**REREVIEW_FIELDS)
        except (KeyError, IndexError, ValueError) as exc:
            raise PackError(f"forge.rereview_job: {exc} (fields: {', '.join(sorted(REREVIEW_FIELDS))})") from exc
    if raw.get("bump_push_prefix") is not None and (
        not isinstance(raw["bump_push_prefix"], str) or not raw["bump_push_prefix"]
    ):
        raise PackError("forge.bump_push_prefix is a branch prefix such as dependabot/")
    if raw.get("bump_batch") is not None:
        try:
            sample = str(raw["bump_batch"]).format(
                project=batch_project(data), week="2026W01", month="202601", date="20260101"
            )
        except (KeyError, IndexError, ValueError) as exc:
            raise PackError(f"forge.bump_batch: {exc} (fields: project, week, month, date)") from exc
        if not re.fullmatch(r"[A-Z][A-Z0-9]*(?:-[A-Z0-9]+)+", sample.upper()):
            raise PackError(f"forge.bump_batch makes {sample.upper()}, which is not a ticket key")
    labels = raw.get("review_labels")
    if labels is not None:
        if not isinstance(labels, dict) or set(labels) - {"REQUEST_CHANGES", "COMMENT", "APPROVE"}:
            raise PackError("forge.review_labels maps REQUEST_CHANGES, COMMENT or APPROVE to {add, remove}")
        for event, rule in labels.items():
            if (
                not isinstance(rule, dict)
                or set(rule) - {"add", "remove"}
                or not all(isinstance(rule.get(key, []), list) for key in ("add", "remove"))
            ):
                raise PackError(f"forge.review_labels.{event} is {{add: [labels], remove: [labels]}}")


def plugin_dir(data, name: str) -> str:
    """Where another plugin lives: an extra_plugins entry, the root home's plugins/<name>, or a folder beside
    cockpit's own tree. Empty when it is not installed."""
    from .paths import hermes_home

    for plugin in (data or {}).get("extra_plugins") or []:
        if plugin["name"] == name:
            return plugin["path"]
    for folder in (os.path.join(hermes_home(), "plugins", name), os.path.join(os.path.dirname(plugin_root()), name)):
        if _isfile(os.path.join(folder, "plugin.yaml")):
            return os.path.realpath(folder)
    return ""


# Keys of a plugin's block that cockpit reads itself (registry): that plugin's validator never sees them.
COCKPIT_PLUGIN_KEYS = ("card_kinds", "kickoff_modes", "page")


def _plugin_blocks(data) -> None:
    """plugins: {name: block}, the settings a pack gives another plugin. That plugin checks its own block: its
    cockpit_pack.py validate(block, pack_dir) returns the block it will use or raises with the reason. A block for a
    plugin that is not installed loads unchecked, and doctor says so."""
    import importlib.util

    raw = data.get("plugins")
    data["_plugins_unchecked"] = []
    if raw is None:
        return
    if not isinstance(raw, dict) or any(
        not isinstance(name, str) or not PLUGIN_NAME.match(name) or name == "cockpit" for name in raw
    ):
        raise PackError("plugins maps another plugin's name to its block")
    for name, block in raw.items():
        if block is not None and not isinstance(block, dict):
            raise PackError(f"plugins.{name} is a mapping")
        block = dict(block or {})
        own = {key: block.pop(key) for key in COCKPIT_PLUGIN_KEYS if key in block}
        folder = plugin_dir(data, name)
        validator = os.path.join(folder, VALIDATOR) if folder else ""
        if not validator or not _isfile(validator):
            data["_plugins_unchecked"].append(name)
            raw[name] = {**block, **own}
            continue
        spec = importlib.util.spec_from_file_location(f"cockpit_pack_{name.replace('-', '_')}", validator)
        module = importlib.util.module_from_spec(spec)
        try:
            spec.loader.exec_module(module)
            checked = module.validate(block, data["_dir"])
        except PackError:
            raise
        except Exception as exc:  # the other plugin's own error, in its words
            raise PackError(f"plugins.{name}: {exc}") from exc
        raw[name] = {**(checked if isinstance(checked, dict) else {}), **own}


def plugin_block(data, name: str) -> dict:
    """The block this pack gives that plugin, as its validator returned it. The keys cockpit reads itself are left out."""
    block = ((data or {}).get("plugins") or {}).get(name) or {}
    return {key: value for key, value in block.items() if key not in COCKPIT_PLUGIN_KEYS}


def _cards(data) -> None:
    """skills.yaml cards: {skills: {kind: [names]}, titles: {kind: template}}. A title must still start with the
    ticket, which is how the board is read."""
    from .kanban import ticket_of
    from .registry import card_kinds

    TITLES = card_kinds(data)
    cards = data["skills"].get("cards")
    if cards is None:
        return
    if not isinstance(cards, dict) or set(cards) - {"skills", "titles", "body", "decompose", "analyst"}:
        raise PackError("skills.yaml cards takes skills, titles, body and decompose (and analyst)")
    analyst = cards.get("analyst")
    if analyst is not None:
        if not isinstance(analyst, dict) or not all(
            isinstance(kind, str) and isinstance(text, str) and text.strip() for kind, text in analyst.items()
        ):
            raise PackError(
                "skills.yaml cards.analyst maps an analyst card kind (base, ci, advisory) to the text of its body"
            )
        for kind, text in analyst.items():
            try:
                text.format(
                    ticket="T-1",
                    repo="r",
                    change="r#1",
                    sha="abc",
                    id="x",
                    url="https://forge.test/pr/1",
                    files="- a.py",
                )
            except (KeyError, IndexError, ValueError) as exc:
                raise PackError(
                    f"skills.yaml cards.analyst.{kind}: {exc} (fields: ticket, repo, change, sha, id, url, files)"
                ) from exc
    chain = cards.get("decompose")
    if chain is not None:
        from .decompose import ROLE_OF

        if (
            not isinstance(chain, list)
            or not chain
            or not all(kind in ROLE_OF for kind in chain)
            or chain[0] not in ("work", "rework")
        ):
            raise PackError(
                f"skills.yaml cards.decompose is the chain per repo, starting with work ({', '.join(ROLE_OF)})"
            )
    if cards.get("body") is not None:
        path = cards["body"] if os.path.isabs(str(cards["body"])) else os.path.join(data["_dir"], str(cards["body"]))
        if not _isfile(path):
            raise PackError(f"skills.yaml cards.body: no file {path}")
        try:
            _open(path, encoding="utf-8").read().format(
                ticket="T-1", role="worker", repo="r", plan="p", slot="1", prs="", plan_gate="auto", note=""
            )
        except (KeyError, IndexError, ValueError) as exc:
            raise PackError(
                f"skills.yaml cards.body: {exc} (fields: ticket, role, repo, plan, slot, prs, plan_gate, note)"
            ) from exc
        cards["body"] = path
    for field, shape in (("skills", list), ("titles", str)):
        block = {} if cards.get(field) is None else cards[field]
        if not isinstance(block, dict):
            raise PackError(f"skills.yaml cards.{field} must be a mapping")
        for kind, value in block.items():
            if kind not in TITLES:
                raise PackError(f"skills.yaml cards.{field}: {kind} is not a card kind")
            if not isinstance(value, shape) or (shape is list and not all(isinstance(item, str) for item in value)):
                raise PackError(f"skills.yaml cards.{field}.{kind} must be a {shape.__name__}")
    for kind, template in (cards.get("titles") or {}).items():
        try:
            sample = template.format(repo="repo", sha="abc", ticket="TASK-1", change="repo#1")
        except (KeyError, IndexError, ValueError) as exc:
            raise PackError(f"skills.yaml cards.titles.{kind}: {exc}") from exc
        if ticket_of(sample) != "TASK-1":
            raise PackError(f"skills.yaml cards.titles.{kind} must start with {{ticket}}")


def _repo_labels(repos) -> None:
    """A repo's label names that repo alone: not two repos', and not another repo's name. Checked only when labels are
    present; a pack without them loads as before."""
    labelled = [repo for repo in repos if isinstance(repo, dict) and "label" in repo]
    if not labelled:
        return
    names = {str(repo.get("name") or "") for repo in repos if isinstance(repo, dict)}
    seen = set()
    for repo in labelled:
        label = repo["label"]
        if label in seen:
            raise PackError(f"repos.yaml: label {label} is on more than one repo")
        seen.add(label)
        if label in names and label != repo.get("name"):
            raise PackError(f"repos.yaml {repo.get('name')}: label {label} is another repo's name")


def _skill_names(data) -> list:
    names = []
    for values in ((data["skills"].get("cards") or {}).get("skills") or {}).values():
        names.extend(values)
    for repo in data["repos"]["repos"]:
        _repo_setup(data, repo)
        listed = repo.get("skills") if isinstance(repo, dict) else None
        if listed is not None and (not isinstance(listed, list) or not all(isinstance(item, str) for item in listed)):
            raise PackError(f"repos.yaml {repo.get('name')}: skills must be a list of names")
        names.extend(listed or [])
    _repo_labels(data["repos"]["repos"])
    skills = data["skills"]
    for group in ("kickoff", "intent"):
        block = skills.get(group)
        if not isinstance(block, dict):
            # Name the file read and how it began, so a file that changed under the loader can be traced.
            path = os.path.join(data["_dir"], "skills.yaml")
            head = _open(path, encoding="utf-8").read(80) if _isfile(path) else "(missing)"
            raise PackError(f"skills.yaml {group} must be a mapping (read {path}: {head!r})")
        for values in block.values():
            if not isinstance(values, list):
                raise PackError("skills.yaml entries must be lists")
            for value in values:
                # An intent type may accept any one of several skills: a list inside the list.
                if (
                    group == "intent"
                    and isinstance(value, list)
                    and value
                    and all(isinstance(item, str) for item in value)
                ):
                    names.extend(value)
                    continue
                if not isinstance(value, str):
                    raise PackError(f"skills.yaml {group}: {value!r} is not a skill name")
                names.append(value)
    _intent_keys(skills["intent"])
    return names


def _intent_keys(block) -> None:
    """skills.yaml intent is keyed by intent type: the readers look a type up by its own name, so a key that is no type
    would require nothing and is refused."""
    from .intents import TYPES

    for name in block:
        if name not in TYPES:
            raise PackError(f"skills.yaml intent: {name!r} is no intent type ({', '.join(TYPES)})")


def find_skill(data, name: str):
    """cockpit:<name> is one of cockpit's own; a bare name is the pack's, never shadowed by a bundled one."""
    if name.startswith(NAMESPACE):
        bundled = os.path.join(plugin_root(), "skills", name[len(NAMESPACE) :], "SKILL.md")
        return bundled if _isfile(bundled) else None
    for folder in data["skills_dir"]:
        path = os.path.join(folder, name, "SKILL.md")
        if _isfile(path):
            return path
    return None


def check_repos(data, root: str) -> None:
    for repo in data["repos"]["repos"]:
        path = repo.get("path") or ""
        if not os.path.isabs(path):
            path = os.path.join(root, path)
        if not _isdir(path):
            raise PackError(f"repo {repo.get('name')}: missing {path}")


def _listed_providers(home: str) -> set:
    """Providers named by an optional list or by config.yaml: Hermes's own, which every home can run."""
    found = set()
    path = os.path.join(home, "known-providers")
    if _isfile(path):
        found.update(
            line.strip() for line in _open(path, encoding="utf-8") if line.strip() and not line.startswith("#")
        )
    config = os.path.join(home, "config.yaml")
    if _isfile(config):
        text = _open(config, encoding="utf-8").read()
        match = re.search(r"(?m)^model:\n(?:  .*\n)*?  provider:\s*['\"]?([^\s'\"]+)", text)
        if match:
            found.add(match.group(1))
    return found


def _plugin_providers(home: str) -> set:
    """Model-provider plugins installed in this home. Hermes loads them for this home only."""
    plugin_dir = os.path.join(home, "plugins", "model-providers")
    if not _isdir(plugin_dir):
        return set()
    return {name for name in _listdir(plugin_dir) if _isdir(os.path.join(plugin_dir, name))}


def check_known_providers(data, home: str) -> None:
    """A seat is a Hermes home of its own and does not load the root's provider plugins: the pack attaches them."""
    listed = _listed_providers(home)
    known = listed | _plugin_providers(home)
    for role in ROLES:
        provider = data["providers"][data["roles"][role]]
        ident = provider["hermes_provider"]
        if role in SEAT_KINDS and ident in [
            plugin["name"] for plugin in extra_plugins_for(data, role) if plugin["provider"]
        ]:
            continue
        if ident not in known:
            raise PackError(f"provider {ident} is not configured in Hermes")
        if role in SEAT_KINDS and ident not in listed:
            raise PackError(
                f"provider {ident} is a plugin of the root home only; attach it to {role} seats with extra_plugins"
            )


def _worktree_gc(data) -> None:
    """worktree_gc: {enabled: true|false, days: 1..365} — the daily pass over stale worktrees (cockpitlib.cleanup);
    the Settings page overlays it, so the pack only sets the start state."""
    given = data.get("worktree_gc")
    if given is None:
        return
    if not isinstance(given, dict) or set(given) - {"enabled", "days"}:
        raise PackError("worktree_gc holds enabled and days only")
    if "enabled" in given and not isinstance(given["enabled"], bool):
        raise PackError("worktree_gc.enabled is true or false")
    days = given.get("days")
    if days is not None and (not isinstance(days, int) or isinstance(days, bool) or not 1 <= days <= 365):
        raise PackError("worktree_gc.days is a whole number of days from 1 to 365")


STEPS = _steps()  # after every check is defined
