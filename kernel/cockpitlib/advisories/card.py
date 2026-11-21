# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The analyst card that assesses one advisory against the stack: one per advisory while it is open."""

import re

from ..errors import CockpitError, Conflict
from ..kanban import one_at_a_time
from .scan import find

ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/@+-]{0,120}$")


def checked(advisory_id: str) -> str:
    advisory_id = str(advisory_id or "").strip()
    if not ID.match(advisory_id) or ".." in advisory_id:
        raise CockpitError("bad advisory id")
    return advisory_id


def text(advisory) -> str:
    """The card's body: what to decide, the advisory, its summary, the stack's hits as a table, the fix, the sources."""
    fix = advisory.get("fix") or {}
    fixed = (
        f"fix available since {fix['time']}"
        if fix.get("time")
        else f"fixed in {', '.join(map(str, fix['versions']))}"
        if fix.get("versions")
        else "no fix known yet"
    )
    hits = advisory.get("hits") or []
    lines = [
        f"Assess advisory {advisory['id']} against the stack. Treat its claims as hypotheses: is the vulnerable path reachable in",
        "the way the stack uses the component, on production, and what is the fix (a bump, a configuration change, nothing).",
        "Read only: the code, the lockfiles, the advisory pages. Post the verdict as a comment on this card; write no outbox",
        "intent unless the human asks for one.",
        "",
        "## The advisory",
        f"- id: {advisory['id']}"
        + (f" (aliases: {', '.join(advisory['aliases'])})" if advisory.get("aliases") else ""),
        f"- title: {advisory.get('title') or ''}",
        f"- severity: {advisory.get('severity') or 'unknown'}"
        + (f" · cvss {advisory['cvss']}" if advisory.get("cvss") is not None else "")
        + (" · EXPLOITED IN THE WILD" if advisory.get("exploited") else ""),
        f"- status: {advisory.get('status') or ''} · trust {advisory.get('trust') or ''} · published {advisory.get('published') or '?'}",
        f"- fix: {fixed}",
        "",
        "## Summary",
        (advisory.get("summary") or "(none)").strip(),
        "",
        "## Hits",
        "| component | version | repo | where | production | fixed in | version checked |",
        "|---|---|---|---|---|---|---|",
        *[
            f"| {hit.get('ecosystem') or hit.get('kind') or ''} {hit.get('name') or ''} | {hit.get('version') or ''} | {hit.get('repo') or ''} | "
            f"{hit.get('where') or ''} | {'yes' if hit.get('production') else 'no'} | {hit.get('fixed_in') or ''} | "
            f"{'yes' if hit.get('version_checked') else 'no'} |"
            for hit in hits
        ],
        *([] if hits else ["| (no component matched) | | | | | | |"]),
        "",
        "## Sources",
        *[f"- {name}" for name in advisory.get("via") or [advisory.get("source") or "source"]],
        f"- {advisory.get('url') or '(no page recorded)'}",
    ]
    return "\n".join(lines) + "\n"


@one_at_a_time
def make(pack, advisory_id: str) -> dict:
    """An analyst card for this advisory, with the pack's advisory skills; refused while one is open."""
    from ..acts import open_analyst
    from ..gate import _platform_ticket
    from ..kanban import card_title, open_twin

    advisory = find(checked(advisory_id))
    if not advisory:
        raise CockpitError(f"no advisory {advisory_id}")
    ticket = _platform_ticket(pack, "ADVISORIES")
    title = card_title("advisory", ticket, pack=pack, change=advisory["id"])
    twin = open_twin(pack["board"], "advisory", ticket, advisory["id"], title)
    if twin:
        raise Conflict(f"already open: card {twin}")
    repos = sorted({hit["repo"] for hit in advisory.get("hits") or [] if hit.get("repo")})
    made = open_analyst(pack, "advisory", ticket=ticket, repos=repos, body=text(advisory), change=advisory["id"])
    return {"ok": True, "card_id": made, "out": f"card {made} → analyst ({advisory['id']})"}
