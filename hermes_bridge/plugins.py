# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Hermes's own plugin bookkeeping, from inside Hermes's environment (see cockpitlib.hermes_runtime): the install record's
revision after cockpit updated itself (and its source after the checkout moved to another repository), so `hermes plugins check-updates` and the Plugins page agree with the checkout;
and the live activation nudge after an update; whether a provider plugin's requirements are installed; what a provider name resolves to.
stdin: {"ops": [{"op": name, ...}]}. stdout: {"results": [...]}, one result per op, in order.
"""

import json
import sys


def _record_revision(op):
    from hermes_cli.plugins_cmd_git import _update_install_record

    revision = str(op.get("revision") or "")
    if len(revision) != 40:
        raise ValueError("revision must be a 40-character commit")

    def update(record):
        if record is None:
            return None  # a plugin Hermes never installed keeps no record: nothing to say
        return {**record, "revision": revision}

    _update_install_record(str(op["name"]), update)
    return True


SNAPSHOT = ".before-rehome"  # the sidecar as it was before the checkout moved to another repository, beside itself


def _without_credentials(url):
    """A URL as a record may keep it: no user and password part."""
    import re

    return re.sub(r"^([a-z][a-z0-9+.-]*://)[^/@]*@", r"\1", str(url), flags=re.IGNORECASE)


def _rehome(op):
    """The record's source and revision after the checkout moved to another repository. The sidecar is first copied
    beside itself, which is the way back; a plugin Hermes never installed keeps no record and gets none."""
    import shutil

    from hermes_cli.plugins_cmd_git import _install_metadata_path, _update_install_record

    revision, source = str(op.get("revision") or ""), _without_credentials(op.get("source") or "")
    if len(revision) != 40 or not source:
        raise ValueError("a source and a 40-character commit are both required")
    path = str(_install_metadata_path())
    kept = {}

    def update(record):
        if record is None:
            return None
        shutil.copy2(path, path + SNAPSHOT)  # under the sidecar's own lock, of what was just read
        kept["snapshot"] = path + SNAPSHOT
        old = str(record.get("source") or "")
        return {**record, "source": source + ("#" + old.split("#", 1)[1] if "#" in old else ""), "revision": revision}

    _update_install_record(str(op["name"]), update)
    return {"recorded": bool(kept), "snapshot": kept.get("snapshot", "")}


def _restore_record(op):
    """The plugin's record as the snapshot has it: only that plugin's, since the others may have changed since."""
    import os

    from hermes_cli.plugins_cmd_git import _install_metadata_path, _update_install_record

    snapshot = str(_install_metadata_path()) + SNAPSHOT
    if not os.path.isfile(snapshot):
        return {"restored": False}
    old = json.load(open(snapshot, encoding="utf-8-sig")).get(str(op["name"]))
    if not isinstance(old, dict):
        return {"restored": False}
    _update_install_record(str(op["name"]), lambda record: old)
    return {"restored": True}


def _activate(op):
    from hermes_cli.plugins_activation import activate_plugin_now

    return activate_plugin_now(str(op["name"]), in_process=False)


def _installed(op):
    """Whether each requirement is installed in Hermes's own environment, where a provider plugin's dependencies live: the
    distribution by its name (not a guessed import name), at a version the requirement accepts when `packaging` is there
    to say. A requirement whose environment marker does not apply here answers None."""
    import re
    from importlib.metadata import PackageNotFoundError, version

    try:
        from packaging.requirements import Requirement
    except ImportError:
        Requirement = None
    found = {}
    for text in op.get("requirements") or []:
        if Requirement is not None:
            requirement = Requirement(str(text))
            name, specifier, marker = requirement.name, requirement.specifier, requirement.marker
        else:
            name, specifier, marker = re.split(r"[\s<>=!~;\[@(]", str(text).strip(), maxsplit=1)[0], None, None
            if ";" in str(text):  # an environment marker this interpreter cannot read without packaging
                found[text] = None
                continue
        if marker is not None and not marker.evaluate():
            found[text] = None
            continue
        try:
            have = version(name)
        except PackageNotFoundError:
            found[text] = False
            continue
        found[text] = not specifier or specifier.contains(have, prereleases=True)
    return found


def _canonical(op):
    """Each provider name as Hermes resolves it: an alias (and a plugin provider's alias) to the canonical id."""
    from hermes_cli.providers import normalize_provider

    try:
        from hermes_cli.auth import _plugin_aliases

        plugin = _plugin_aliases()
    except Exception:  # noqa: BLE001 - aliases that cannot be read are no aliases
        plugin = {}
    found = {}
    for name in op.get("names") or []:
        key = normalize_provider(str(name))
        found[name] = plugin.get(key, key)
    return found


OPS = {
    "record_revision": _record_revision,
    "rehome": _rehome,
    "restore_record": _restore_record,
    "activate": _activate,
    "installed": _installed,
    "canonical": _canonical,
}


def main() -> int:
    request = json.load(sys.stdin)
    results = []
    for op in request.get("ops") or []:
        try:
            results.append(OPS[op["op"]](op))
        except Exception as exc:  # noqa: BLE001 - the op answers, the batch goes on
            results.append({"error": str(exc)})
    print(json.dumps({"results": results}, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
