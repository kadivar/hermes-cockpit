# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Create every seat, the board, the crons, and the local gateway marker. Idempotent."""

import json
import os
import shutil
import subprocess
import time
from datetime import UTC, datetime

from .errors import CockpitError
from .lanes import profile_dir, role_provider, seats_from
from .pack import check_known_providers, extra_plugins_for, mcp_config, plugin_root, seat_env, seat_skills_for
from .paths import hermes_home
from .store import write_text

# Schedules match the watcher table. --no-agent: the script is the job.
CRON_JOBS = (
    ("ci-watch", "1m", "ci-watch.sh"),
    ("pr-watch", "5m", "pr-watch.sh"),
    ("workspace-watch", "10m", "workspace-watch.sh"),
    ("slot-gc", "1h", "slot-gc.sh"),
    ("base-watch", "2h", "base-watch.sh"),
    ("standup", "0 0 * * *", "standup.sh"),
    ("bumps", "0 0 * * 1-5", "bumps.sh"),
    ("export", "0 0 * * 5", "export.sh"),
    ("morning-digest", "0 0 * * 1-5", "morning-digest.sh"),
    ("perf-sync", "0 0 * * 1-5", "perf-sync.sh"),
    ("advisories", "30m", "advisories.sh"),
)


HOUR_KEYS = {
    "morning-digest": ("digest",),
    "perf-sync": ("perf",),
}

# Jobs that run on a seat. Hermes reads the script and records the job in that seat's home.
SEAT_JOBS = ("morning-digest",)


def _analyst_seat(pack) -> str:
    """The pack's first analyst seat. A missing pack still names the analyst profile."""
    from .lanes import seats_from

    names = []
    if pack:
        try:
            names = seats_from(pack).get("analyst") or []
        except (KeyError, TypeError):
            names = []
    if names:
        return names[0]
    return "analyst"


def _profile_args(pack, name: str) -> list:
    if name in SEAT_JOBS:
        return ["--profile", _analyst_seat(pack)]
    return []


def cron_home(pack, name: str) -> str:
    """The Hermes home that holds this job's script and records the job."""
    if name in SEAT_JOBS:
        return profile_dir(_analyst_seat(pack))
    return hermes_home()


def cron_create_argv(hermes: str, pack, name: str, schedule: str, script: str) -> list:
    """Morning digest is the analyst seat and stays read-only. Every other job is the script."""
    argv = [hermes, *_profile_args(pack, name)]
    argv.extend(["cron", "create", schedule])
    if name == "morning-digest":
        argv.append("Read the morning digest. Report it. Do not edit files and do not publish.")
    argv.extend(["--name", name, "--script", script, "--deliver", "local"])
    if name != "morning-digest":
        argv.append("--no-agent")
    return argv


def cron_schedule(pack, name: str, default: str) -> str:
    """Hours and working days come from the pack. The kernel does not hardcode an adopter hour."""
    if name == "advisories" and ((pack or {}).get("advisories") or {}).get("minutes"):
        return f"{pack['advisories']['minutes']}m"
    if name == "slot-gc" and ((pack or {}).get("slots") or {}).get(
        "gc_minutes"
    ):  # how soon a finished ticket's slot is freed
        return f"{pack['slots']['gc_minutes']}m"
    hours = (pack or {}).get("hours") or {}
    hour = None
    for key in (name, *HOUR_KEYS.get(name, ())):
        if key in hours and hours.get(key) is not None:
            hour = hours.get(key)
            break
    if hour is None:
        return default
    days = (pack or {}).get("working_days")
    if not isinstance(days, list) or not days:
        return default
    from .window import clock

    span = ",".join(str((int(day) + 1) % 7) for day in days)
    hour, minute = clock(hour)
    if name == "standup":
        return f"{minute} {hour} * * *"
    if name == "export":
        return f"{minute} {hour} * * 5"
    return f"{minute} {hour} * * {span}"


def _seat_ready(lane: str) -> bool:
    return os.path.isfile(os.path.join(profile_dir(lane), "config.yaml"))


def _ensure_profile(pack, lane: str, kind: str) -> str:
    """A second setup leaves an existing seat. A failed render names the seat and stops."""
    if _seat_ready(lane):
        return profile_dir(lane)
    try:
        return _profile(pack, lane, kind)
    except CockpitError:
        raise
    except Exception as exc:
        raise CockpitError(f"seat render failed {lane}: {exc}") from exc


def desktop_refresh(root: str = "") -> bool:
    """The Desktop copies this plugin's UI half (desktop/) and re-copies it only when desktop/plugin.js is newer than its
    copy. A change under desktop/src alone would never reach the Desktop: setup bumps plugin.js when any file beside
    it is newer. True when it did; the Desktop picks the change up at its next start."""
    from .paths import PLUGIN_ROOT

    base = os.path.join(root or PLUGIN_ROOT, "desktop")
    entry = os.path.join(base, "plugin.js")
    if not os.path.isfile(entry):
        return False
    newest = 0.0
    for folder, dirs, names in os.walk(base):
        dirs[:] = [name for name in dirs if name not in ("node_modules", "test", ".git")]
        for name in names:
            path = os.path.join(folder, name)
            if path != entry:
                try:
                    newest = max(newest, os.path.getmtime(path))
                except OSError:
                    continue
    if newest > os.path.getmtime(entry):
        os.utime(entry, None)
        return True
    return False


def _same_bytes(one: str, other: str) -> bool:
    try:
        with open(one, "rb") as first, open(other, "rb") as second:
            return first.read() == second.read()
    except OSError:
        return False


def desktop_copy_stale(root: str = "") -> str:
    """The Desktop's copy of the UI half is older than the source: the finding, or empty."""
    import json

    from .paths import PLUGIN_ROOT, hermes_home

    base = root or PLUGIN_ROOT
    entry = os.path.join(base, "desktop", "plugin.js")
    marker = os.path.join(hermes_home(), "desktop-plugins", os.path.basename(base), ".hermes-package.json")
    if not os.path.isfile(entry) or not os.path.isfile(marker):
        return ""
    try:
        noted = json.load(open(marker, encoding="utf-8"))
        stamp = float(noted.get("sourceMtimeMs") or 0)
    except (OSError, ValueError, TypeError, AttributeError):
        return ""
    if noted.get("linked") and _same_bytes(entry, os.path.join(os.path.dirname(marker), "plugin.js")):
        # the Desktop keeps the copy of a linked checkout while the entry's bytes are the same, and leaves the stamp
        # as it was: a newer time alone (setup's bump, a checkout) is not a stale copy
        return ""
    if stamp and os.path.getmtime(entry) * 1000 > stamp + 1:
        return "Desktop runs a stale copy of the plugin UI (restart the Desktop; it re-copies on start)"
    return ""


def setup(pack, rerender=False, seat="") -> list:
    """Create every seat, the board, the crons, and the gateway. A second run only fills what is missing.

    rerender backs a seat up to ~/.hermes/backups/profiles/<stamp>/ and writes it again from the pack: every seat,
    or the one named.
    """
    home = hermes_home()
    os.makedirs(home, exist_ok=True)
    check_known_providers(pack, home)
    # The counts in force, not the pack's: the Settings page writes the owner's number to the
    # settings and dispatch has always read it from there (`free_lane`). Provisioning read the pack,
    # so raising a seat put cards on a lane that was never given a profile or its plugins — and the
    # provider a card needs lives in that lane's plugins/, so every one of them crashed before the
    # agent existed. A seat cockpit will dispatch to is a seat cockpit sets up.
    from .settings import load as _settings

    seats = [(kind, lane) for kind, names in seats_from(pack, _settings(pack)["seats"]).items() for lane in names]
    if seat and seat not in [lane for _kind, lane in seats]:
        raise CockpitError(f"no seat {seat}")
    stamp = time.strftime("%Y%m%dT%H%M%S")
    written = []
    for kind, lane in seats:
        if rerender and (not seat or seat == lane) and _seat_ready(lane):
            _back_up_seat(lane, stamp)
            written.append(_profile(pack, lane, kind))
        else:
            written.append(_ensure_profile(pack, lane, kind))
        _seat_plugin(lane, pack, kind)
    _root_soul(pack)
    written.append(_board_flags(pack))
    if calls_tools(hermes_home()):
        _link_plugin(hermes_home())
    _root_plugins(pack)
    written.append(_crons(pack))
    written.append(_gateway_marker())
    written.append(_allow_hook(pack))
    hooked = _cursor_hook(pack)
    if hooked:
        written.append(hooked)
    _bin_link(_linked_lanes(pack, [lane for _kind, lane in seats]))
    _register_crons(pack)
    _reload_gateway()
    desktop_refresh()
    return written


# Keys cockpit sets on every seat. A pack's seat_config may add to the lists here and may not change the rest.
UNIONED = (("approvals", "deny"), ("plugins", "enabled"), ("hooks", "pre_tool_call"))


def _merged(base, top, path=()) -> dict:
    """top over base, one level at a time. A list under UNIONED keeps top's items first and adds base's others."""
    merged = dict(base)
    for key, value in top.items():
        here = path + (key,)
        current = merged.get(key)
        if isinstance(current, dict) and isinstance(value, dict):
            merged[key] = _merged(current, value, here)
            continue
        if here in UNIONED and isinstance(current, list) and isinstance(value, list):
            merged[key] = list(value) + [item for item in current if item not in value]
            continue
        merged[key] = value
    return merged


def _seat_overlay(pack, kind: str) -> dict:
    """The pack's seat_config hermes keys for this kind: _common first, then the kind's own."""
    config = pack.get("seat_config") or {}
    common = ((config.get("_common") or {}).get("hermes")) or {}
    own = ((config.get(kind) or {}).get("hermes")) or {}
    return _merged(common, own)


def _seat_settings(pack, lane: str, kind: str) -> dict:
    """The profile a seat gets: the pack's overlay, then the keys cockpit owns. A missing model is an error."""
    provider = role_provider(pack, kind)
    if not isinstance(provider, dict) or not provider.get("model") or not provider.get("hermes_provider"):
        raise ValueError(f"missing model for {lane}")
    model = {"default": provider["model"], "provider": provider["hermes_provider"]}
    if provider.get("context_length"):
        model["context_length"] = int(provider["context_length"])
    owned = {
        "model": model,
        "kanban": {"auto_decompose": False, "review_dispatch": False},
        "hooks": {
            "pre_tool_call": [{"command": os.path.join(plugin_root(), "hooks", "egress.py"), "fail_closed": True}]
        },
        "hooks_auto_accept": False,
        "approvals": {
            "deny": ["git push*", "cockpit publish*"],
            "unattended_mode": "deny",
            "cron_mode": "deny",
            "single_query_mode": "deny",
        },
        "plugins": {"enabled": enabled_plugins(pack, kind)},
    }
    if provider.get("reasoning_effort"):
        owned["agent"] = {"reasoning_effort": provider["reasoning_effort"]}
    servers = mcp_config(pack, kind)
    if servers:
        owned["mcp_servers"] = servers
    from .egress import DELEGATE_SEATS, MAX_DELEGATES

    if kind in DELEGATE_SEATS:
        owned["delegation"] = {"max_concurrent_children": MAX_DELEGATES, "inherit_mcp_toolsets": False}
    if kind == "advisor":
        owned["platform_toolsets"] = {"cli": []}  # a saved empty list: the advisor answers and calls no tool
    return _merged(_seat_overlay(pack, kind), owned)


def _config_text(pack, lane: str, kind: str) -> str:
    import yaml

    return yaml.safe_dump(_seat_settings(pack, lane, kind), sort_keys=False)


SEAT_FILES = ("config.yaml", "SOUL.md", ".env", os.path.join("memories", "MEMORY.md"))
ROOT_SOUL_BEGIN = "<!-- cockpit: the pack's root soul begins -->"
ROOT_SOUL_END = "<!-- cockpit: the pack's root soul ends -->"


def _back_up_seat(lane: str, stamp: str) -> str:
    """Copy the files a rerender rewrites. Sessions and memories beyond the seed stay where they are."""
    dest = os.path.join(hermes_home(), "backups", "profiles", stamp, lane)
    for name in SEAT_FILES:
        source = os.path.join(profile_dir(lane), name)
        if os.path.isfile(source):
            os.makedirs(os.path.dirname(os.path.join(dest, name)), exist_ok=True)
            shutil.copy2(source, os.path.join(dest, name))
    return dest


def _root_soul(pack) -> str:
    """The pack's root soul between cockpit's markers in ~/.hermes/SOUL.md. No root soul removes the block."""
    path = os.path.join(hermes_home(), "SOUL.md")
    text = open(path, encoding="utf-8").read() if os.path.isfile(path) else ""
    if ROOT_SOUL_BEGIN in text and ROOT_SOUL_END in text:
        before, rest = text.split(ROOT_SOUL_BEGIN, 1)
        text = before.rstrip("\n") + rest.split(ROOT_SOUL_END, 1)[1]
    soul = (((pack or {}).get("seat_config") or {}).get("root") or {}).get("soul")
    if soul:
        block = open(soul, encoding="utf-8").read().strip()
        text = (text.rstrip("\n") + "\n\n" if text.strip() else "") + f"{ROOT_SOUL_BEGIN}\n{block}\n{ROOT_SOUL_END}\n"
    if text or os.path.isfile(path):
        _write(path, text)
    return path


KERNEL_SEED = "Cockpit lane.\n§\nKeep lessons short.\n"


def _seed_memory(pack, folder: str, kind: str) -> None:
    """MEMORY.md gets the pack's seed (the kind's, else _common's, else cockpit's). A memory the lane wrote stays.

    The seed cockpit wrote is fingerprinted beside it, so a later seed replaces only a memory nobody has touched.
    """
    import hashlib

    config = (pack or {}).get("seat_config") or {}
    path = next(
        (
            block.get("memory_seed")
            for block in (config.get(kind) or {}, config.get("_common") or {})
            if block.get("memory_seed")
        ),
        "",
    )
    seed = open(path, encoding="utf-8").read() if path else KERNEL_SEED
    memory = os.path.join(folder, "memories", "MEMORY.md")
    marker = os.path.join(folder, "memories", ".cockpit-seed")
    if os.path.isfile(memory):
        current = open(memory, encoding="utf-8").read()
        written = open(marker, encoding="utf-8").read().strip() if os.path.isfile(marker) else ""
        untouched = current == KERNEL_SEED or hashlib.sha256(current.encode()).hexdigest() == written
        if not untouched:
            return
    _write(memory, seed)
    _write(marker, hashlib.sha256(seed.encode()).hexdigest() + "\n")


def _profile(pack, lane, kind) -> str:
    folder = profile_dir(lane)
    os.makedirs(os.path.join(folder, "memories"), exist_ok=True)
    os.makedirs(os.path.join(folder, "skills"), exist_ok=True)
    config = _config_text(pack, lane, kind)
    _write(os.path.join(folder, "config.yaml"), config)
    _write(os.path.join(folder, "SOUL.md"), _soul(pack, lane, kind))
    env_path = os.path.join(folder, ".env")
    _write_seat_env(pack, lane, env_path, kind)
    _seed_memory(pack, folder, kind)
    link = os.path.join(folder, "skills", "workspace")
    if not os.path.islink(link):
        target = pack["skills_dir"][0]
        if os.path.lexists(link):
            os.remove(link)
        os.symlink(target, link)
    return folder


ENV_BEGIN = "# cockpit: the pack's env begins"
ENV_END = "# cockpit: the pack's env ends"


def _pack_env_names(text: str) -> list:
    """The names inside the pack's block of a seat .env."""
    names = []
    inside = False
    for line in text.splitlines():
        if line == ENV_BEGIN:
            inside = True
            continue
        if line == ENV_END:
            inside = False
            continue
        if inside and "=" in line:
            names.append(line.split("=", 1)[0])
    return names


def seat_harness_home(pack, env_path) -> str:
    """The `BH_HOME=` line a seat's .env gets under `lanes.browser_session`: the browser harness's daemons, sockets and
    screenshots live under the seat's own folder, not the machine-wide one every profile shares; or empty."""
    if not ((pack or {}).get("lanes") or {}).get("browser_session"):
        return ""
    return "BH_HOME=" + os.path.join(os.path.dirname(os.path.abspath(env_path)), "browser-harness")


def _write_seat_env(pack, lane, env_path, kind="") -> None:
    """COCKPIT_LANE, the agent's arguments, and the pack's block (seat_config env and env_files). Lines a person
    added stay. The file is 0600: env files carry secrets."""
    import shlex

    from .pack import agent_launch

    text = open(env_path, encoding="utf-8").read() if os.path.isfile(env_path) else ""
    kept = []
    inside = False
    harness = seat_harness_home(pack, env_path)
    for line in text.splitlines():
        if line in (ENV_BEGIN, ENV_END):
            inside = line == ENV_BEGIN
            continue
        if (
            inside
            or line.startswith("COCKPIT_LANE=")
            or line.startswith("HERMES_CURSOR_AGENT_ARGS=")
            or (harness and line == harness)
        ):
            continue
        kept.append(line)
    kept.append(f"COCKPIT_LANE={lane}")
    args = agent_launch(pack)["args"]
    if args:
        kept.append("HERMES_CURSOR_AGENT_ARGS=" + shlex.join(args))
    values = seat_env(pack, kind)
    if harness and "BH_HOME" not in values and not any(line.startswith("BH_HOME=") for line in kept):
        kept.append(harness)  # a person's own BH_HOME line, or the pack's, stands
    if values:
        kept += [ENV_BEGIN, *[f"{key}={value}" for key, value in values.items()], ENV_END]
    _write(env_path, "\n".join(kept) + "\n")
    os.chmod(env_path, 0o600)


def _config_data(home) -> dict:
    import yaml

    path = os.path.join(home, "config.yaml")
    if not os.path.isfile(path):
        return {}
    try:
        data = yaml.safe_load(open(path, encoding="utf-8"))
    except yaml.YAMLError:
        return {}
    return data if isinstance(data, dict) else {}


def enabled_plugins(pack, kind) -> list:
    """The names a home of this kind lists in plugins.enabled. Provider plugins load without it."""
    return ["cockpit", *[plugin["name"] for plugin in extra_plugins_for(pack, kind) if not plugin["provider"]]]


def plugin_enabled(home, name="cockpit") -> bool:
    """Hermes loads a plugin for this home only when this home's own config lists it."""
    plugins = _config_data(home).get("plugins")
    enabled = plugins.get("enabled") if isinstance(plugins, dict) else None
    return isinstance(enabled, list) and name in enabled


def _plugin_link(home, name="cockpit", provider=False) -> str:
    return os.path.join(home, "plugins", *(["model-providers"] if provider else []), name)


def plugin_present(home, name="cockpit", provider=False) -> bool:
    """Hermes scans this home's own plugins/ folder, not the root one."""
    return os.path.isfile(os.path.join(_plugin_link(home, name, provider), "plugin.yaml"))


def calls_tools(home) -> bool:
    """A saved empty toolset list is no tools. A missing or non-empty one leaves the profile its tools."""
    toolsets = _config_data(home).get("platform_toolsets")
    if not isinstance(toolsets, dict) or not toolsets:
        return True
    return any(value != [] for value in toolsets.values())


def _link(link, target) -> None:
    """Point link at target. A link to somewhere else is replaced; an installed copy is left as it is."""
    if os.path.islink(link) and os.path.realpath(link) != os.path.realpath(target):
        os.remove(link)
    if os.path.lexists(link):
        return
    os.makedirs(os.path.dirname(link), exist_ok=True)
    os.symlink(target, link)


def _link_plugin(home, plugin=None) -> None:
    """Point this home's plugins/<name> at the plugin tree: cockpit's own, or an extra plugin of the pack."""
    if plugin is None:
        _link(_plugin_link(home), plugin_root())
        return
    _link(_plugin_link(home, plugin["name"], plugin["provider"]), plugin["path"])


def _enable(text, names) -> str:
    """Add each name to plugins.enabled: in the parsed config when it parses, else as text."""
    import yaml

    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError:
        data = None
    if not isinstance(data, dict):
        for name in names:
            text = _ensure_plugin(text, name)
        return text
    plugins = data.get("plugins") if isinstance(data.get("plugins"), dict) else {}
    enabled = plugins.get("enabled") if isinstance(plugins.get("enabled"), list) else []
    missing = [name for name in names if name not in enabled]
    if not missing and data.get("plugins") is plugins:
        return text
    data["plugins"] = {**plugins, "enabled": [*enabled, *missing]}
    return yaml.safe_dump(data, sort_keys=False)


def _unlink_dropped_providers(home, pack, kind) -> None:
    """A provider link cockpit made for a plugin the pack no longer gives this kind goes, so it cannot claim the seat.

    Only a symlink to a path some pack extra_plugins entry declares is touched; a provider installed by hand stays.
    """
    folder = os.path.join(home, "plugins", "model-providers")
    if not os.path.isdir(folder):
        return
    declared = {
        os.path.realpath(plugin["path"]) for plugin in (pack or {}).get("extra_plugins") or [] if plugin["provider"]
    }
    kept = {plugin["name"] for plugin in extra_plugins_for(pack, kind) if plugin["provider"]}
    for name in sorted(os.listdir(folder)):
        link = os.path.join(folder, name)
        if name not in kept and os.path.islink(link) and os.path.realpath(link) in declared:
            os.remove(link)


def _seat_plugin(lane, pack=None, kind="") -> None:
    """A seat loads register() only from its own plugins/ and its own plugins.enabled, and skills from its skills/."""
    folder = profile_dir(lane)
    _link_plugin(folder)
    _unlink_bundled_skills(folder)
    _unlink_dropped_providers(folder, pack, kind)
    for plugin in extra_plugins_for(pack, kind):
        _link_plugin(folder, plugin)
    for skill in seat_skills_for(pack, kind):
        _link(os.path.join(folder, "skills", skill["name"]), skill["path"])
    path = os.path.join(folder, "config.yaml")
    text = open(path, encoding="utf-8").read()
    merged = _enable(text, enabled_plugins(pack, kind))
    if merged != text:
        _write(path, merged)


def _root_plugins(pack) -> None:
    """The pack's root plugins, beside cockpit in the root home."""
    plugins = extra_plugins_for(pack, "root")
    if not plugins:
        return
    for plugin in plugins:
        _link_plugin(hermes_home(), plugin)
    path = os.path.join(hermes_home(), "config.yaml")
    text = open(path, encoding="utf-8").read()
    merged = text
    # The root config is the human's file: edited as text, so its comments and layout stay.
    for plugin in plugins:
        if not plugin["provider"]:
            merged = _ensure_plugin(merged, plugin["name"])
    if merged != text:
        _write(path, merged)


def _unlink_bundled_skills(folder) -> None:
    """A seat reaches cockpit's skills as cockpit:<name> through the plugin. An older setup also linked one as a
    local skill, which made a pack skill of the same name ambiguous: that link goes."""
    for name in os.listdir(os.path.join(folder, "skills")) if os.path.isdir(os.path.join(folder, "skills")) else []:
        link = os.path.join(folder, "skills", name)
        if os.path.islink(link) and os.path.dirname(os.path.realpath(link)) == os.path.realpath(
            os.path.join(plugin_root(), "skills")
        ):
            os.remove(link)


def _render_seat(pack, lane: str, kind: str) -> dict:
    """Render one seat from the pack into a temporary file. A broken value raises instead of returning empty."""
    import tempfile

    config = _config_text(pack, lane, kind)
    soul = _soul(pack, lane, kind)
    if not config.strip() or not soul.strip():
        raise ValueError(f"empty render for {lane}")
    handle = tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False)
    try:
        handle.write(config + "\n---\n" + soul)
        handle.close()
        config_text, soul_text = open(handle.name, encoding="utf-8").read().split("\n---\n", 1)
    finally:
        if os.path.isfile(handle.name):
            os.remove(handle.name)
    return {"config": config_text, "soul": soul_text}


# Keys Hermes writes into a profile itself. They are not drift.
HERMES_STAMPED = ("_config_version",)


def _settings_of(text: str):
    """A profile's settings as data, without the keys Hermes stamps. Unreadable text is itself, so it drifts."""
    import yaml

    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError:
        return text
    if not isinstance(data, dict):
        return data
    return {key: value for key, value in data.items() if key not in HERMES_STAMPED}


def seat_drift(pack) -> list:
    """Render every seat into a temporary file. A failed render is an error. Every drift is listed."""
    from .lanes import profile_dir, seats_from

    problems = []
    try:
        seats = seats_from(pack)
    except Exception as exc:  # noqa: BLE001 - the failure is the problem reported
        return [f"seat render failed: {exc}"]
    for kind, names in seats.items():
        for lane in names:
            try:
                rendered = _render_seat(pack, lane, kind)
            except Exception as exc:  # noqa: BLE001 - the failure is the problem reported
                problems.append(f"seat render failed {lane}: {exc}")
                continue
            folder = profile_dir(lane)
            soul_path = os.path.join(folder, "SOUL.md")
            config_path = os.path.join(folder, "config.yaml")
            if os.path.isfile(soul_path) and open(soul_path, encoding="utf-8").read() != rendered["soul"]:
                problems.append(f"seat drift {lane} (cockpit setup --rerender --seat {lane})")
                continue
            if os.path.isfile(config_path) and _settings_of(open(config_path, encoding="utf-8").read()) != _settings_of(
                rendered["config"]
            ):
                problems.append(f"seat drift {lane} (cockpit setup --rerender --seat {lane})")
                continue
            if os.path.isfile(config_path) and seat_cockpit(lane):
                problems.append(f"seat drift {seat_cockpit(lane)} (cockpit setup)")
                continue
            env_path = os.path.join(folder, ".env")
            # Only names are compared: a secret's value is not drift.
            current = _pack_env_names(open(env_path, encoding="utf-8").read()) if os.path.isfile(env_path) else []
            if os.path.isfile(config_path) and sorted(current) != sorted(seat_env(pack, kind)):
                problems.append(f"seat drift {lane} (cockpit setup --rerender --seat {lane})")
    return problems


def _soul(pack, lane, kind) -> str:
    """Cockpit's soul for the kind, the pack's additions (_common, then the kind's), then cockpit's common rules."""
    root = plugin_root()
    parts = []
    template = os.path.join(root, "souls", f"{kind}.md")
    if not os.path.isfile(template):
        template = os.path.join(root, "souls", "worker.md")
    parts.append(open(template, encoding="utf-8").read())
    config = (pack or {}).get("seat_config") or {}
    for block in (config.get("_common") or {}, config.get(kind) or {}):
        if block.get("soul"):
            parts.append(open(block["soul"], encoding="utf-8").read())
    common = os.path.join(root, "souls", "_common.md")
    if os.path.isfile(common):
        parts.append(open(common, encoding="utf-8").read())
    slot = lane.rsplit("-", 1)[1] if kind in ("worker", "tester") and "-" in lane else ""
    from .pack_local import home
    from .paths import records_name
    from .prompts import resolve
    from .test_flow import evidence_dir

    text = "\n".join(parts).replace("{{LANE}}", lane).replace("{{SLOT}}", slot).replace("{{RECORDS}}", records_name())
    return resolve(pack, text.replace("{{EVIDENCE}}", evidence_dir(pack)).replace("{{HOME}}", home()))


def _board_flags(pack) -> str:
    path = os.path.join(hermes_home(), "config.yaml")
    text = ""
    if os.path.isfile(path):
        text = open(path, encoding="utf-8").read()
    text = _ensure_resume(_ensure_plugin(_merge_kanban(text)))
    _write(path, text)
    _ensure_board(pack)
    return path


def _top_level_spans(lines) -> list:
    starts = []
    for index, line in enumerate(lines):
        if not line or line[0] in " \t#":
            continue
        name = line.split(":", 1)[0]
        if name and all(char.isalnum() or char in "_-" for char in name):
            starts.append((name, index))
    spans = []
    for index, (name, start) in enumerate(starts):
        end = starts[index + 1][1] if index + 1 < len(starts) else len(lines)
        spans.append((name, start, end))
    return spans


def _set_child(block, key, value) -> None:
    for index, line in enumerate(block):
        if index and line.startswith(f"  {key}:") and not line.startswith("   "):
            block[index] = f"  {key}: {value}"
            return
    block.insert(1, f"  {key}: {value}")


def _merge_kanban(text) -> str:
    """One top-level kanban key. Later copies are illegal to Hermes and are folded in."""
    lines = text.splitlines()
    spans = [span for span in _top_level_spans(lines) if span[0] == "kanban"]
    if not spans:
        if text and not text.endswith("\n"):
            text += "\n"
        return text + "kanban:\n  auto_decompose: false\n  review_dispatch: false\n"
    extras = []
    for _name, start, end in spans[1:]:
        for line in lines[start + 1 : end]:
            stripped = line.strip()
            if (
                line.startswith("  ")
                and not line.startswith("   ")
                and ":" in stripped
                and not stripped.startswith("#")
            ):
                extras.append((stripped.split(":", 1)[0], line))
    for _name, start, end in reversed(spans[1:]):
        del lines[start:end]
    spans = [span for span in _top_level_spans(lines) if span[0] == "kanban"]
    _name, start, end = spans[0]
    block = lines[start:end]
    present = set()
    for line in block[1:]:
        stripped = line.strip()
        if line.startswith("  ") and not line.startswith("   ") and ":" in stripped:
            present.add(stripped.split(":", 1)[0])
    for key, line in extras:
        if key in ("auto_decompose", "review_dispatch") or key in present:
            continue
        block.append(line)
        present.add(key)
    _set_child(block, "auto_decompose", "false")
    _set_child(block, "review_dispatch", "false")
    lines[start:end] = block
    merged = "\n".join(lines)
    if not merged.endswith("\n"):
        merged += "\n"
    return merged


def _ensure_resume(text) -> str:
    """Register the resume hook on the pre-model call. A mention anywhere else is not registration."""
    from .resume import resume_registered

    if resume_registered(text):
        if text and not text.endswith("\n"):
            return text + "\n"
        return text
    hook = os.path.join(plugin_root(), "hooks", "resume-context.sh")
    lines = text.splitlines()
    spans = [span for span in _top_level_spans(lines) if span[0] == "hooks"]
    entry = ["  pre_llm_call:", f"    - command: {hook}"]
    if not spans:
        if text and not text.endswith("\n"):
            text += "\n"
        return text + "hooks:\n" + "\n".join(entry) + "\n"
    _name, start, end = spans[0]
    block = lines[start:end]
    block.extend(entry)
    lines[start:end] = block
    merged = "\n".join(lines)
    if not merged.endswith("\n"):
        merged += "\n"
    return merged


def _ensure_plugin(text, name="cockpit") -> str:
    lines = text.splitlines()
    spans = [span for span in _top_level_spans(lines) if span[0] == "plugins"]
    if not spans:
        if text and not text.endswith("\n"):
            text += "\n"
        return text + f"plugins:\n  enabled:\n    - {name}\n"
    _name, start, end = spans[0]
    block = lines[start:end]
    enabled_at = None
    for index, line in enumerate(block):
        if index and line.startswith("  enabled:") and not line.startswith("   "):
            enabled_at = index
            break
    if enabled_at is None:
        block.insert(1, "  enabled:")
        block.insert(2, f"    - {name}")
        lines[start:end] = block
        merged = "\n".join(lines)
        if not merged.endswith("\n"):
            merged += "\n"
        return merged
    has = False
    insert_at = enabled_at + 1
    # A YAML dump writes the items at the key's own indent ("  - x"); a hand-written file often indents them.
    item = "    - "
    for index in range(enabled_at + 1, len(block)):
        line = block[index]
        if not line.strip() or line.strip().startswith("#"):
            insert_at = index + 1
            continue
        if line.startswith("    - ") or line.startswith("  - "):
            item = line[: line.index("-") + 2]
            insert_at = index + 1
            if line.strip() == f"- {name}":
                has = True
            continue
        break
    if not has:
        block.insert(insert_at, f"{item}{name}")
    lines[start:end] = block
    merged = "\n".join(lines)
    if not merged.endswith("\n"):
        merged += "\n"
    return merged


def _ensure_board(pack) -> str:
    slug = str(pack["board"])
    board = os.path.join(hermes_home(), "kanban", "boards", slug)
    os.makedirs(board, exist_ok=True)
    marker = os.path.join(board, "board.json")
    if not os.path.isfile(marker):
        name = " ".join(part.capitalize() for part in slug.replace("_", "-").split("-") if part) or slug
        payload = {
            "slug": slug,
            "name": name,
            "description": "",
            "icon": "",
            "color": "",
            "default_workdir": None,
            "project_id": None,
            "created_at": int(time.time()),
            "archived": False,
        }
        _write(marker, json.dumps(payload, indent=2) + "\n")
    _init_board_db(slug)
    _set_board_workdir(pack, marker)
    return board


def _set_board_workdir(pack, marker) -> None:
    """Hermes's own command sets the board's default workdir; it is only run when the pack's value differs."""
    from .pack import board_workdir

    wanted = board_workdir(pack)
    try:
        current = json.load(open(marker, encoding="utf-8")).get("default_workdir") or ""
    except (OSError, ValueError):
        current = ""
    if not wanted or current == wanted:
        return
    hermes = shutil.which("hermes")
    if not hermes:
        raise CockpitError("board_workdir needs the hermes command")
    done = subprocess.run(
        [hermes, "kanban", "boards", "set-default-workdir", str(pack["board"]), wanted],
        env={**os.environ, "HERMES_HOME": hermes_home()},
        capture_output=True,
        text=True,
        check=False,
    )
    if done.returncode != 0:
        raise CockpitError(f"board_workdir: {(done.stderr or done.stdout).strip()}")


def _init_board_db(slug) -> None:
    db = os.path.join(hermes_home(), "kanban", "boards", slug, "kanban.db")
    if os.path.isfile(db):
        return
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return
    hermes = shutil.which("hermes")
    if not hermes:
        return
    env = os.environ.copy()
    env["HERMES_HOME"] = hermes_home()
    subprocess.run(
        [hermes, "kanban", "boards", "create", slug],
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )


def _copy_script(source, dest, name) -> None:
    src = os.path.join(source, name)
    os.makedirs(dest, exist_ok=True)
    copied = os.path.join(dest, name)
    shutil.copy(src, copied)
    if os.access(src, os.X_OK):
        os.chmod(copied, os.stat(copied).st_mode | 0o111)  # noqa: S103 - the copy keeps the source's executable bit


def _crons(pack=None) -> str:
    """Every script goes to the root home. A seat job's script and the runner also go to that seat."""
    source = os.path.join(plugin_root(), "cron")
    dest = os.path.join(hermes_home(), "scripts")
    os.makedirs(dest, exist_ok=True)
    if os.path.isdir(source):
        for name in os.listdir(source):
            if os.path.isfile(os.path.join(source, name)):
                _copy_script(source, dest, name)
    for name, _schedule, script in CRON_JOBS:
        if name not in SEAT_JOBS or not os.path.isdir(cron_home(pack, name)):
            continue
        seat_scripts = os.path.join(cron_home(pack, name), "scripts")
        _copy_script(source, seat_scripts, "run")
        _copy_script(source, seat_scripts, script)
    return dest


def _reload_gateway() -> None:
    """A gateway that is already up read the allowlist at start. Setup loads the new one."""
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return
    if os.path.realpath(hermes_home()) != os.path.realpath(os.path.expanduser("~/.hermes")):
        return
    hermes = shutil.which("hermes")
    if not hermes:
        return
    status = subprocess.run([hermes, "gateway", "status"], check=False, capture_output=True, text=True)
    blob = (status.stdout or "") + (status.stderr or "")
    if "active (running)" not in blob and "service is running" not in blob:
        return
    subprocess.run([hermes, "gateway", "restart"], check=False, capture_output=True, text=True)


def _cron_jobs(home=None) -> list:
    path = os.path.join(home or hermes_home(), "cron", "jobs.json")
    if not os.path.isfile(path):
        return []
    try:
        data = json.loads(open(path, encoding="utf-8").read())
    except json.JSONDecodeError:
        return []
    jobs = data.get("jobs") if isinstance(data, dict) else data
    if not isinstance(jobs, list):
        return []
    return jobs


def registered_jobs(pack) -> list:
    """Root jobs, plus each seat job from the seat home that records it."""
    jobs = [job for job in _cron_jobs() if not (isinstance(job, dict) and job.get("name") in SEAT_JOBS)]
    for name in SEAT_JOBS:
        jobs.extend(
            job for job in _cron_jobs(cron_home(pack, name)) if isinstance(job, dict) and job.get("name") == name
        )
    return jobs


def job_schedule(job) -> str:
    """The schedule string a later setup compares. Empty means the file did not record one."""
    schedule = job.get("schedule") if isinstance(job, dict) else None
    if not isinstance(schedule, dict):
        return ""
    minutes = schedule.get("minutes")
    if schedule.get("kind") == "interval" and minutes:
        count = int(minutes)
        if count % 60 == 0 and count >= 60:
            return f"{count // 60}h"
        return f"{count}m"
    if schedule.get("expr"):
        return str(schedule["expr"])
    return str(schedule.get("display") or "")


def cron_plan(jobs, pack) -> list:
    """Missing jobs are created. A recorded schedule that differs is updated."""
    by_name = {}
    if isinstance(jobs, list):
        for job in jobs:
            if isinstance(job, dict) and job.get("name"):
                by_name[str(job["name"])] = job
    planned = []
    for name, default, script in CRON_JOBS:
        schedule = cron_schedule(pack, name, default)
        current = by_name.get(name)
        if name == "standup" and not standup_enabled(pack):
            # the pack turned the daily standup note off: no job, and one a setup made before goes
            if current is not None and current.get("id"):
                planned.append(
                    {"op": "remove", "name": name, "schedule": "", "script": script, "id": str(current["id"])}
                )
            continue
        if current is None:
            planned.append({"op": "create", "name": name, "schedule": schedule, "script": script, "id": ""})
            continue
        recorded = job_schedule(current)
        if recorded and recorded != schedule:
            planned.append(
                {
                    "op": "update",
                    "name": name,
                    "schedule": schedule,
                    "script": script,
                    "id": str(current.get("id") or ""),
                }
            )
    return planned


def standup_enabled(pack) -> bool:
    """The daily standup note (its cron and its Inbox row): on unless the pack says standup_enabled: false."""
    return (pack or {}).get("standup_enabled", True) is not False


def _register_crons(pack=None) -> None:
    """Create a missing watcher. Update one whose recorded schedule no longer matches the pack."""
    hermes = shutil.which("hermes")
    if not hermes:
        raise CockpitError("hermes not found: watchers not registered")
    env = os.environ.copy()
    env["HERMES_HOME"] = hermes_home()
    for action in cron_plan(registered_jobs(pack), pack):
        name = action["name"]
        if action["op"] == "update" and not action["id"]:
            raise CockpitError(f"{name}: schedule changed and the job has no id")
        argv = cron_create_argv(hermes, pack, name, action["schedule"], action["script"])
        if action["op"] == "remove":
            argv = [hermes, *_profile_args(pack, name), "cron", "remove", action["id"]]
        if action["op"] == "update":
            argv = [hermes, *_profile_args(pack, name), "cron", "edit", action["id"], "--schedule", action["schedule"]]
        completed = subprocess.run(
            argv,
            env=env,
            check=False,
            capture_output=True,
            text=True,
        )
        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout or "cron create failed").strip()
            raise CockpitError(f"{name}: {detail}")


def _gateway_marker() -> str:
    path = os.path.join(hermes_home(), "gateway.state")
    if not os.path.isfile(path):
        _write(path, "stopped\n")
    return path


def cursor_hooks_path() -> str:
    return os.environ.get("COCKPIT_CURSOR_HOOKS") or os.path.join(os.path.expanduser("~"), ".cursor", "hooks.json")


def cursor_hook_command() -> str:
    return os.path.join(plugin_root(), "hooks", "cursor.py")


def cursor_hook_installed(path: str = "") -> bool:
    """Cursor's own hooks file runs cockpit's fence before each tool call of a Cursor agent."""
    path = path or cursor_hooks_path()
    try:
        data = json.loads(open(path, encoding="utf-8").read())
    except (OSError, json.JSONDecodeError):
        return False
    entries = ((data.get("hooks") or {}).get("preToolUse") or []) if isinstance(data, dict) else []
    return any(
        isinstance(item, dict) and item.get("command") == cursor_hook_command() and not item.get("matcher")
        for item in entries
    )


def _cursor_hook(pack) -> str:
    """agent.cursor_hooks puts cockpit's fence in Cursor's hooks file, for the lanes whose model is Cursor's own agent: Hermes
    sees none of that agent's tool calls. The hook allows every call outside a lane, so a person's Cursor is untouched. Other
    hooks in the file stay; turning the key off takes cockpit's entry out again."""
    wanted = bool((pack.get("agent") or {}).get("cursor_hooks"))
    path = cursor_hooks_path()
    if not wanted and not os.path.isfile(path):
        return ""
    try:
        data = json.loads(open(path, encoding="utf-8").read()) if os.path.isfile(path) else {}
    except (OSError, json.JSONDecodeError) as exc:
        if not wanted:
            return (
                ""  # a file cockpit cannot read holds no entry of cockpit's: a pack that did not opt in is not stopped
            )
        raise CockpitError(f"{path} is not JSON, so cockpit cannot add its hook: {exc}") from exc
    if not isinstance(data, dict):
        if not wanted:
            return ""
        raise CockpitError(f"{path} is not a hooks file")
    hooks = data.get("hooks") if isinstance(data.get("hooks"), dict) else {}
    entries = [
        item
        for item in hooks.get("preToolUse") or []
        if not (isinstance(item, dict) and item.get("command") == cursor_hook_command())
    ]
    if wanted:
        entries.insert(0, {"command": cursor_hook_command()})
    if entries == (hooks.get("preToolUse") or []):
        return ""
    data = {
        "version": data.get("version", 1),
        **{k: v for k, v in data.items() if k not in ("version", "hooks")},
        "hooks": {**hooks, "preToolUse": entries},
    }
    _write(path, json.dumps(data, indent=2) + "\n")
    return path


def _allow_hook(pack=None) -> str:
    """Hermes skips a shell hook until its command is on the allowlist. Setup is the approval.

    A multiplexed gateway reads the allowlist from the seat's own home, not only the root.
    """
    path = _allow_hook_at(hermes_home())
    if not pack:
        return path
    for names in seats_from(pack).values():
        for lane in names:
            _allow_hook_at(profile_dir(lane))
    return path


def _allow_hook_at(home) -> str:
    path = os.path.join(home, "shell-hooks-allowlist.json")
    command = os.path.join(plugin_root(), "hooks", "egress.py")
    data = {"approvals": []}
    if os.path.isfile(path):
        try:
            loaded = json.loads(open(path, encoding="utf-8").read())
        except json.JSONDecodeError:
            loaded = None
        if isinstance(loaded, dict) and isinstance(loaded.get("approvals"), list):
            data = loaded
    kept = []
    for item in data.get("approvals", []):
        if isinstance(item, dict) and item.get("event") == "pre_tool_call" and item.get("command") == command:
            continue
        kept.append(item)
    mtime = None
    if os.path.isfile(command):
        stamp = datetime.fromtimestamp(os.path.getmtime(command), tz=UTC)
        mtime = stamp.isoformat().replace("+00:00", "Z")
    kept.append(
        {
            "approved_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            "command": command,
            "event": "pre_tool_call",
            "script_mtime_at_approval": mtime,
        }
    )
    data["approvals"] = kept
    _write(path, json.dumps(data, indent=2, sort_keys=True) + "\n")
    os.chmod(path, 0o600)
    return path


def _bin_link(lanes=()) -> None:
    """`cockpit` where every shell that runs it looks: the Hermes home's bin (the owner's), and each seat's own profile
    bin. Hermes puts `$HERMES_HOME/bin` on a lane's terminal PATH, and a seat's HERMES_HOME is its profile folder, so the
    home's link alone leaves every lane with `cockpit: command not found`."""
    for folder in [hermes_home(), *[profile_dir(lane) for lane in lanes]]:
        try:
            _place_cockpit(os.path.join(folder, "bin"))
        except OSError:
            continue  # a seat it could not reach shows as drift in doctor; setup itself goes on


def _linked_lanes(pack, in_force) -> list:
    """The seats in force, and every seat of the pack's counts that has a profile: doctor checks the second list, so a
    seat left over after the owner lowered a count must get its link too, or it drifts for good."""
    from .lanes import seats_from

    lanes = list(in_force)
    try:
        lanes += [
            lane
            for names in seats_from(pack).values()
            for lane in names
            if os.path.isfile(os.path.join(profile_dir(lane), "config.yaml"))
        ]
    except Exception:  # noqa: BLE001, S110 - lanes that cannot be listed are left out
        pass
    return list(dict.fromkeys(lanes))


def _place_cockpit(dest_dir: str) -> str:
    os.makedirs(dest_dir, exist_ok=True)
    target = os.path.join(plugin_root(), "bin", "cockpit")
    if os.name == "nt":
        # no symlinks without developer mode: shims that run the checkout's script with its venv python — a .cmd for
        # cmd and PowerShell, and an extensionless sh script for the Git Bash Hermes runs lane commands in (no PATHEXT)
        python = os.path.join(plugin_root(), ".venv", "Scripts", "python.exe")
        python = python if os.path.isfile(python) else "py"
        shim = os.path.join(dest_dir, "cockpit.cmd")
        _write(shim, f'@"{python.replace("%", "%%")}" "{target.replace("%", "%%")}" %*\r\n')
        _write(
            os.path.join(dest_dir, "cockpit"),
            f'#!/bin/sh\nexec "{python.replace(os.sep, "/")}" "{target.replace(os.sep, "/")}" "$@"\n',
        )
        return shim
    link = os.path.join(dest_dir, "cockpit")
    if os.path.islink(link) and os.readlink(link) == target:
        return link
    if os.path.lexists(link):
        if not os.path.islink(link):
            return link  # a file someone put there on purpose stays
        os.remove(link)  # a link to an old checkout or a dangling one is replaced
    os.symlink(target, link)
    return link


def seat_cockpit(lane: str) -> str:
    """'' when the seat's shell finds this checkout's `cockpit`, else what is wrong."""
    target = os.path.join(plugin_root(), "bin", "cockpit")
    folder = os.path.join(profile_dir(lane), "bin")
    if os.name == "nt":
        shims = [os.path.join(folder, name) for name in ("cockpit.cmd", "cockpit")]
        if not all(os.path.isfile(shim) for shim in shims):
            return f"{lane}: no bin/cockpit.cmd and bin/cockpit"
        if any(
            target.replace(os.sep, "/") not in open(shim, encoding="utf-8").read().replace(os.sep, "/")
            for shim in shims
        ):
            return f"{lane}: bin/cockpit shims run another checkout"
        return ""
    link = os.path.join(folder, "cockpit")
    if not os.path.lexists(link):
        return f"{lane}: no bin/cockpit, its shell cannot run cockpit"
    if os.path.islink(link) and os.path.realpath(link) != os.path.realpath(target):
        return f"{lane}: bin/cockpit points at {os.readlink(link)}"
    return ""


def _write(path, text) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    write_text(path, text)


def gateway_up() -> str:
    path = os.path.join(hermes_home(), "gateway.state")
    _write(path, "running\n")
    return "running"


def gateway_down() -> str:
    path = os.path.join(hermes_home(), "gateway.state")
    _write(path, "stopped\n")
    return "stopped"


def gateway_status() -> str:
    path = os.path.join(hermes_home(), "gateway.state")
    if not os.path.isfile(path):
        return "stopped"
    return open(path, encoding="utf-8").read().strip() or "stopped"
