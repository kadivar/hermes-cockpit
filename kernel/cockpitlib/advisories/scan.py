# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""One scan: the manifest (rebuilt when its inputs changed), every source the pack names (a failure is recorded, never
fatal), items merged by id and alias, matched against the manifest, state carried over, advisories.json written whole."""

import datetime

from ..store import read_json, write_json
from ..time_util import iso
from . import acks_path, cache_dir, manifest_path, match, sources, state_path
from . import manifest as stack

TRUST_RANK = {"high": 0, "low": 1}


def config(pack) -> dict:
    """The pack's advisories block: sources (names from the registry), alert (the urgencies that raise a row), minutes."""
    return (pack or {}).get("advisories") or {}


def fetch_all(manifest, cache, registry) -> tuple:
    """({source: {ok, checked, error, items}}, [items]): every source runs; an exception becomes its error."""
    status, items = {}, []
    for source in registry:
        cache.source = source["name"]
        checked = iso()
        try:
            found = source["fetch"](manifest, cache) or []
        except Exception as exc:  # noqa: BLE001 - one source failing is its own status line; the others are still read
            status[source["name"]] = {
                "ok": False,
                "checked": checked,
                "error": f"{type(exc).__name__}: {exc}"[:500],
                "items": 0,
            }
            continue
        for row in found:
            row["trust"] = source["trust"]
        items.extend(found)
        status[source["name"]] = {"ok": True, "checked": checked, "error": None, "items": len(found)}
    return status, items


def merge_keys(row) -> set:
    """An item merges on its id and aliases — unless it is a bulletin naming several CVEs (a release post), which merges on
    its own id only, or every post citing an earlier CVE would chain into one advisory."""
    cves = [alias for alias in row.get("aliases") or [] if alias.startswith("CVE-")]
    return {row["id"], *row.get("aliases", [])} if len(cves) <= 1 else {row["id"]}


def canonical_id(row) -> str:
    return next((key for key in sorted(merge_keys(row)) if key.startswith("CVE-")), row["id"])


def merge(items) -> list:
    """One advisory per id or alias family: a KEV entry lends exploited, the highest trust wins, affects and aliases are
    unioned. A KEV entry nothing else names and nothing of the stack matches by name is dropped."""
    by_key, merged = {}, []
    for row in items:
        keys = merge_keys(row) | {canonical_id(row)}
        found = next((by_key[key] for key in keys if key in by_key), None)
        if found is None:
            found = dict(
                row,
                id=canonical_id(row),
                via=[row["source"]],
                aliases=sorted((keys | set(row.get("aliases", []))) - {canonical_id(row)}),
            )
            merged.append(found)
        else:
            _fold(found, row, keys)
        for key in keys:
            by_key[key] = found
    return [row for row in merged if row["affects"] or row["source"] != "kev"]


def _fold(found, row, keys) -> None:
    found["aliases"] = sorted((set(found["aliases"]) | keys | set(row.get("aliases", []))) - {found["id"]})
    found["via"] = sorted(set(found["via"]) | {row["source"]})
    found["exploited"] = found["exploited"] or row["exploited"]
    better = TRUST_RANK[row["trust"]] < TRUST_RANK[found["trust"]] or (
        row["trust"] == found["trust"] and row["source"] != "kev" and found["source"] == "kev"
    )
    if better:
        for key in ("title", "severity", "cvss", "published", "url", "source", "text", "trust"):
            found[key] = row[key] if row.get(key) not in (None, "", "unknown") else found[key]
    if not better and found.get("severity") in (None, "unknown") and row.get("severity") not in (None, "unknown"):
        found["severity"], found["cvss"] = row["severity"], row.get("cvss")
    shapes = {
        (affect.get("ecosystem"), affect.get("name"), bool(affect.get("ranges") or affect.get("versions")))
        for affect in found["affects"]
    }
    found["affects"] += [
        affect
        for affect in row["affects"]
        if (affect.get("ecosystem"), affect.get("name"), bool(affect.get("ranges") or affect.get("versions")))
        not in shapes
    ]
    fix = found["fix"]
    fix["versions"] = sorted(set(fix["versions"]) | set(row["fix"]["versions"]), key=match.version_tuple)
    fix["time"] = fix["time"] or row["fix"]["time"]
    found["modified"] = max(filter(None, (found.get("modified"), row.get("modified"))), default=None)


def _registry(pack) -> list:
    named = config(pack).get("sources")
    return [source for source in sources.REGISTRY if named is None or source["name"] in named]


def run(pack, fetch=None, when=None) -> dict:
    """{output, failed, new}: the record written, whether every source failed, and the alerts not announced before."""
    from ..acts import bumps_path

    manifest, rebuilt = stack.load_or_build(pack, manifest_path())
    previous = read_json(state_path()) or {}
    acks = read_json(acks_path()) or {}
    bumps = read_json(bumps_path()) or {}
    by_id = {}
    for row in previous.get("advisories") or []:
        by_id[row["id"]] = row
        for alias in row.get("aliases") or []:
            by_id.setdefault(alias, row)
    alert = config(pack).get("alert") or {}
    status, items = fetch_all(manifest, sources.Cache(cache_dir(), fetch), _registry(pack))
    moment = when or datetime.datetime.now(datetime.UTC)
    stamp = moment.isoformat()
    found = []
    for advisory in merge(items):
        advisory["hits"] = match.hits(manifest, advisory, moment)
        advisory["bump_prs"] = match.bump_prs_for(advisory, bumps)
        match.carry_state(by_id, advisory, stamp, acks)
        found.append(match.finish(advisory, alert, moment))
    present = {row["id"] for row in found} | {alias for row in found for alias in row["aliases"]}
    for row in (
        previous.get("advisories") or []
    ):  # gone from every source: re-matched (an upgrade clears its hits), kept until stale
        if row["id"] in present:
            continue
        row["hits"] = match.hits(manifest, row, moment)
        row["bump_prs"] = match.bump_prs_for(row, bumps)
        row["acknowledged"] = match.ack_of(acks, row)
        if not match.stale(row, moment):
            found.append(match.finish(row, alert, moment))
    unique = {}
    for row in found:
        unique.setdefault(row["id"], row)
    advisories = sorted(unique.values(), key=match.sort_key)
    notified = [key for key in previous.get("notified") or [] if key in unique]
    new = []
    for row in advisories:
        if row["alert"] and row["id"] not in notified:
            notified.append(row["id"])
            new.append(f"NEW ALERT {row['id']}: {row['summary']}")
    output = {
        "time": iso(),
        "manifest_time": manifest.get("time"),
        "manifest_rebuilt": rebuilt,
        "manifest_errors": manifest.get("errors") or [],
        "sources": status,
        "advisories": advisories,
        "notified": notified,
    }
    write_json(state_path(), output)
    return {"output": output, "failed": bool(status) and not any(row["ok"] for row in status.values()), "new": new}


def state() -> dict:
    """The record in its contract shape; empty shapes before the first scan."""
    data = read_json(state_path()) or {}
    return {
        "time": data.get("time"),
        "manifest_time": data.get("manifest_time"),
        "sources": data.get("sources") or {},
        "advisories": [row for row in data.get("advisories") or [] if isinstance(row, dict)],
        "notified": data.get("notified") or [],
    }


def find(advisory_id: str):
    return next(
        (
            row
            for row in state()["advisories"]
            if row.get("id") == advisory_id or advisory_id in (row.get("aliases") or [])
        ),
        None,
    )


def ack(pack, advisory_id: str, note: str = "", on: bool = True):
    """The ack is kept in the acks file (by the advisory's id) and applied to the record at once, so its row leaves without
    waiting for the next scan. None when no advisory carries that id or alias."""
    data = read_json(state_path()) or {}
    acks = read_json(acks_path()) or {}
    hit = None
    for row in data.get("advisories") or []:
        if row["id"] != advisory_id and advisory_id not in (row.get("aliases") or []):
            continue
        if on:
            acks[row["id"]] = {"time": iso(), "note": note or ""}
        for key in (row["id"], *(row.get("aliases") or [])) if not on else ():
            acks.pop(key, None)
        row["acknowledged"] = acks.get(row["id"])
        match.finish(row, config(pack).get("alert") or {})
        hit = row
    if hit:
        data["advisories"] = sorted(data["advisories"], key=match.sort_key)
        write_json(state_path(), data)
        write_json(acks_path(), acks)
    return hit
