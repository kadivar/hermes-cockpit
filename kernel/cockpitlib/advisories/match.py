# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Pure functions: does an advisory touch a manifest component, what state is it in, is it worth an Inbox row. No network."""

import datetime
import re

SEVERITIES = ("critical", "high", "medium", "low", "unknown")
ALERT_STATUSES = ("confirmed", "patch-scheduled", "fix-available")
DROP_AFTER_DAYS = 30
NAME_ONLY_DAYS = 90  # a name-only advisory older than this names nothing to act on: no hit
# What raises an Inbox row for a production hit (the pack's advisories.alert overrides each).
ALERT = {"critical": True, "exploited": True, "patch_scheduled": True, "high_days": 14}
NAME_ALIASES = {
    "node.js": "node",
    "nodejs": "node",
    "php-fpm": "php",
    "mysql server": "mysql",
    "debian linux": "debian",
    "alpine linux": "alpine",
    "library/php": "php",
    "library/node": "node",
    "library/nginx": "nginx",
}
FAMILY = {"packagist": "composer"}


def canonical(name) -> str:
    name = (name or "").strip().lower()
    return NAME_ALIASES.get(name, name)


def version_tuple(version) -> tuple:
    """Semver-ish: numeric tokens split on . - + _, a v prefix and a tag tail tolerated (8.4-fpm-bookworm → (8, 4))."""
    text = str(version or "").strip().lower()
    text = text[1:] if text.startswith("v") and len(text) > 1 and text[1].isdigit() else text
    found = []
    for token in re.split(r"[.\-+_]", text):
        if token.isdigit():
            found.append(int(token))
            continue
        lead = re.match(r"(\d+)", token)
        if lead:
            found.append(int(lead.group(1)))
        break
    return tuple(found)


def cmp(left, right) -> int:
    a, b = version_tuple(left), version_tuple(right)
    width = max(len(a), len(b))
    a, b = a + (0,) * (width - len(a)), b + (0,) * (width - len(b))
    return (a > b) - (a < b)


def in_range(version, span) -> bool:
    if not version_tuple(version) or cmp(version, span.get("introduced") or "0") < 0:
        return False
    if not span.get("fixed") and span.get("last_affected"):
        return cmp(version, span["last_affected"]) <= 0
    return not span.get("fixed") or cmp(version, span["fixed"]) < 0


def _family(name) -> str:
    name = str(name or "").lower()
    return FAMILY.get(name, name)


def _ecosystem_ok(item, affect) -> bool:
    """No ecosystem on the affects entry (a name-only source) matches by name; otherwise the families agree. An image answers
    only image advisories: a php or node line is checked on the runtime entry its base image also yields."""
    return not affect.get("ecosystem") or _family(affect["ecosystem"]) == _family(item["ecosystem"])


def floating(version) -> bool:
    """At most two numeric parts (php 8.4, node 22): a tag that picks the next patch up at the next pull."""
    return 0 < len(version_tuple(version)) <= 2


def same_line(version, fixed) -> bool:
    """The fix lives on the floating tag's own line (8.4 vs 8.4.5)."""
    mine = version_tuple(version)
    return bool(fixed) and version_tuple(fixed)[: len(mine)] == mine


def name_only(affect) -> bool:
    return not (affect.get("ranges") or affect.get("versions"))


def component_hit(item, affect):
    """None, or {fixed_in, version_checked} when the component is what the affects entry names, in a version it names. A
    floating tag is no hit for a fix on its own line, and never counts as version-checked."""
    if canonical(item["name"]) != canonical(affect.get("name")) or not _ecosystem_ok(item, affect):
        return None
    version = item["version"]
    checked = not floating(version)
    if name_only(affect):
        return {"fixed_in": None, "version_checked": False}
    if any(cmp(version, listed) == 0 for listed in affect.get("versions") or []):
        return {"fixed_in": None, "version_checked": checked}
    fixed = [
        span.get("fixed")
        for span in affect.get("ranges") or []
        if in_range(version, span) and not (floating(version) and same_line(version, span.get("fixed")))
    ]
    if not fixed:
        return None
    known = [value for value in fixed if value]
    return {"fixed_in": min(known, key=version_tuple) if known else None, "version_checked": checked}


def parse_time(text):
    if not text:
        return None
    try:
        moment = datetime.datetime.fromisoformat(str(text).replace("Z", "+00:00"))
    except ValueError:
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=datetime.UTC)


def _age_days(advisory, now, *keys):
    for key in keys:
        moment = parse_time(advisory.get(key))
        if moment:
            return (now - moment).days
    return None


def _now(now):
    return now or datetime.datetime.now(datetime.UTC)


def hits(manifest, advisory, now=None) -> list:
    """The components an advisory touches. A name-only affects entry counts only while the advisory is fresh."""
    age = _age_days(advisory, _now(now), "published", "modified")
    affects = [
        affect
        for affect in advisory.get("affects") or []
        if not name_only(affect) or (age is not None and age <= NAME_ONLY_DAYS)
    ]
    found = []
    for item in (manifest or {}).get("components") or []:
        for affect in affects:
            hit = component_hit(item, affect)
            if hit:
                found.append(
                    {key: item[key] for key in ("kind", "ecosystem", "name", "version", "repo", "where", "production")}
                    | hit
                )
                break
    return found


def status_of(advisory, now=None) -> str:
    """candidate (low-trust sources only) → confirmed (a high-trust one) → patch-scheduled (a fix time ahead) or
    fix-available (fixed versions); acknowledged wins over all of them."""
    if advisory.get("acknowledged"):
        return "acknowledged"
    if advisory.get("trust") != "high":
        return "candidate"
    if not advisory.get("hits") and all(name_only(affect) for affect in advisory.get("affects") or []):
        return "candidate"
    fix = advisory.get("fix") or {}
    moment = parse_time(fix.get("time"))
    if moment and moment > _now(now):
        return "patch-scheduled"
    if fix.get("versions"):
        return "fix-available"
    return "confirmed"


def alertable(advisory, alert=None, now=None) -> bool:
    """The one gate for an Inbox row: a production hit no bump PR covers, not acknowledged, a confirmed status, and one of
    the pack's urgencies: critical, exploited, a fix scheduled ahead, or a high within its first days."""
    rule = {**ALERT, **(alert or {})}
    if advisory.get("acknowledged") or advisory.get("status") not in ALERT_STATUSES or not uncovered_hits(advisory):
        return False
    severity = advisory.get("severity")
    age = _age_days(advisory, _now(now), "published", "first_seen")
    return (
        (rule["critical"] and severity == "critical")
        or (rule["exploited"] and bool(advisory.get("exploited")))
        or (rule["patch_scheduled"] and advisory.get("status") == "patch-scheduled")
        or (bool(rule["high_days"]) and severity == "high" and age is not None and age <= int(rule["high_days"]))
    )


def summary(advisory) -> str:
    """The title, what of the stack is hit (with versions), and the fix or its time."""
    fix = advisory.get("fix") or {}
    ours = (
        ", ".join(
            sorted(
                {
                    f"{hit['repo']} {hit['name']} {hit['version']}"
                    + ("" if hit.get("version_checked") else " (by name)")
                    for hit in advisory.get("hits") or []
                }
            )
        )
        or "nothing of the stack matched"
    )
    tail = (
        "fixed in " + ", ".join(fix["versions"][:4])
        if fix.get("versions")
        else f"fix expected {fix['time']}"
        if fix.get("time")
        else "no fix known"
    )
    return (
        f"{advisory.get('title') or advisory.get('id')} — {advisory.get('severity') or 'unknown'}"
        f"{' · exploited' if advisory.get('exploited') else ''} — hits: {ours} — {tail}"
    )


def severity_rank(severity) -> int:
    return SEVERITIES.index(severity) if severity in SEVERITIES else len(SEVERITIES)


def sort_key(advisory):
    seen = parse_time(advisory.get("last_seen")) or datetime.datetime.min.replace(tzinfo=datetime.UTC)
    return (not advisory.get("alert"), severity_rank(advisory.get("severity")), -seen.timestamp())


def ack_of(acks, advisory):
    return (acks or {}).get(advisory["id"]) or next(
        (acks[alias] for alias in advisory.get("aliases") or [] if alias in (acks or {})), None
    )


def carry_state(previous, advisory, now_iso, acks=None) -> dict:
    """first_seen survives a rescan (the earlier record is found by id or alias); the ack comes from the acks file."""
    old = previous.get(advisory["id"]) or next(
        (previous[alias] for alias in advisory.get("aliases") or [] if alias in previous), None
    )
    advisory["first_seen"] = (old or {}).get("first_seen") or now_iso
    advisory["last_seen"] = now_iso
    advisory["acknowledged"] = ack_of(acks, advisory)
    return advisory


def stale(advisory, now=None) -> bool:
    """Gone from every source and hitting nothing: kept DROP_AFTER_DAYS after it was last seen, then dropped."""
    seen = parse_time(advisory.get("last_seen"))
    return bool(seen) and (_now(now) - seen).days >= DROP_AFTER_DAYS and not advisory.get("hits")


def finish(advisory, alert=None, now=None) -> dict:
    advisory["status"] = status_of(advisory, now)
    advisory["alert"] = alertable(advisory, alert, now)
    advisory["summary"] = summary(advisory)
    return advisory


# ---- an open bump PR that already bumps a hit package is the fix in flight, not an alert


def bump_names(pr) -> set:
    """The packages a bump PR's title names ("Bump a from 1 to 2", "Bump a, b and c", "Bump a and b in /dir")."""
    title = re.sub(r"\s+in\s+/\S+$", "", (pr.get("title") or "").strip())
    named = re.match(
        r"^(?:\S+\(\S+\):\s*|\S+:\s*)?bumps?\s+(.+?)(?:\s+from\s+\S+\s+to\s+\S+)?(?:\s+to\s+\S+)?$", title, re.I
    )
    if not named:
        return set()
    return {name.strip().lower() for name in re.split(r",\s*|\s+and\s+", named.group(1)) if name.strip()}


def bump_prs_for(advisory, bumps) -> list:
    """The open bump PRs (the bump scan's record) that bump a package this advisory hits, in the same repo."""
    hit = [
        (row.get("repo"), (row.get("name") or "").lower())
        for row in advisory.get("hits") or []
        if row.get("kind") == "package"
    ]
    found = []
    for repo, prs in ((bumps or {}).get("repos") or {}).items():
        names = {name for where, name in hit if where == repo}
        for pr in prs or [] if names else []:
            covers = sorted(names & bump_names(pr))
            if covers:
                found.append(
                    {
                        "repo": repo,
                        "number": pr.get("number"),
                        "title": pr.get("title"),
                        "url": pr.get("url"),
                        "head": pr.get("head"),
                        "covers": covers,
                    }
                )
    return found


def uncovered_hits(advisory) -> list:
    """The production hits no bump PR covers (a runtime or image hit is never a bump's): what is still the human's."""
    prs = advisory.get("bump_prs") or []
    return [
        row
        for row in advisory.get("hits") or []
        if row.get("production")
        and not any(
            pr.get("repo") == row.get("repo") and (row.get("name") or "").lower() in (pr.get("covers") or [])
            for pr in prs
        )
    ]
