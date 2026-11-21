# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The one plan file per ticket: a head, then `## ` sections in any order."""

import os
import re

from .paths import qa_of
from .store import write_text
from .time_util import iso

CHANGES = "Changes (go)"


def plan_path(ticket: str) -> str:
    return qa_of(ticket, "plan.md")


def decided(ticket: str) -> bool:
    return "Decision" in sections(ticket)


def _parse(text: str) -> tuple:
    """(head, [[name, body], ...]). A repeated heading is folded into its first section."""
    head, found, current = [], [], None
    for line in (text or "").splitlines():
        if line.startswith("## "):
            name = line[3:].strip()
            current = next((section for section in found if section[0] == name), None)
            if current is None:
                current = [name, []]
                found.append(current)
            continue
        (current[1] if current is not None else head).append(line)
    return "\n".join(head).strip(), [
        [name, re.sub(r"\n{3,}", "\n\n", "\n".join(lines).strip())] for name, lines in found
    ]


_NESTED_BRIEF = re.compile(r"^(#{3,6})\s*Brief\b[^\n]*$", re.I)


def _nested_brief(body: str) -> str:
    """The text under a `### Brief` (any deeper level) heading, up to the next heading at that level or above."""
    lines = (body or "").splitlines()
    for index, line in enumerate(lines):
        match = _NESTED_BRIEF.match(line)
        if not match:
            continue
        level = len(match.group(1))
        kept = []
        for later in lines[index + 1 :]:
            heading = re.match(r"^(#{1,6})\s", later)
            if heading and len(heading.group(1)) <= level:
                break
            kept.append(later)
        return "\n".join(kept).strip()
    return ""


def brief_of(text: str) -> str:
    """The plan's Brief: its `## Brief` section, else a `### Brief` nested in any section (a plan whose first heading
    names the ticket and keeps the Brief under it), else nothing."""
    head, found = _parse(text)
    for name, body in found:
        if name.lower() == "brief":
            return body
    for _name, body in found:
        nested = _nested_brief(body)
        if nested:
            return nested
    return _nested_brief(head)


def _render(head: str, found: list) -> str:
    parts = [head.strip()] if head.strip() else []
    parts += [f"## {name}\n\n{body}".rstrip() for name, body in found]
    return "\n\n".join(parts).rstrip() + "\n"


def _put(found: list, name: str, body: str, add: bool = False) -> None:
    """Set a section's body, or add to it under the same heading."""
    for section in found:
        if section[0] == name:
            section[1] = f"{section[1]}\n\n{body}".strip() if add else body
            return
    found.append([name, body])


OUTSIDE_MARK = "outside work, no intake plan"  # in kickoff.OUTSIDE_GO, the decision a kickoff of outside work records


def init(ticket: str, body: str, decision: str, outline: bool = False) -> str:
    """Write the plan once. A later go keeps it. A go with changes keeps every section (Delivered, Tested, ...),
    records the changes under their own heading and replaces the decision. `outline`: intake writes the approved outline
    after the go recorded the proposal; while nothing but the decision is recorded, the outline takes the proposal's place."""
    path = plan_path(ticket)
    changes = str(decision).startswith("go with changes")
    # a review or test kickoff of outside work recorded its own go; the human's go on an intake plan replaces it
    outside = decided(ticket) and OUTSIDE_MARK in show(ticket) and OUTSIDE_MARK not in str(decision)
    if decided(ticket) and not changes and not outside:
        if outline and (body or "").strip():
            _head, found = _parse(show(ticket))
            if {name for name, _body in found} <= {"Decision", CHANGES}:
                new_head, sections = _parse(body)
                names = {name for name, _body in sections}
                kept = sections + [
                    section for section in found if section[0] not in names
                ]  # the outline's sections, then the go
                write_text(path, _render(new_head, kept))
        return path
    os.makedirs(os.path.dirname(path), exist_ok=True)
    head, found = _parse(show(ticket)) if os.path.isfile(path) else ("", [])
    if not head and [name for name, _body in found] in ([], ["Decision"]):  # a bare decision is no plan yet
        head, found = _parse(body or f"# Plan {ticket}")
    stamp = iso()
    if changes:
        _put(found, CHANGES, f"{decision.split(':', 1)[-1].strip()} ({stamp})", add=True)
    _put(found, "Decision", f"{decision} ({stamp})")
    write_text(path, _render(head, found))
    return path


def require_decision(ticket: str) -> None:
    from .errors import CockpitError

    if not decided(ticket):
        raise CockpitError("plan has no decision")


def require_section(ticket: str, section: str) -> None:
    from .errors import CockpitError

    if section not in sections(ticket):
        raise CockpitError(f"missing section {section}")


def append(ticket: str, section: str, body: str) -> str:
    """Add a stamped entry to a section of an existing plan. A second entry goes under the same heading."""
    from .errors import CockpitError

    path = plan_path(ticket)
    if not os.path.isfile(path):
        raise CockpitError(f"no plan for {ticket}: intake writes it at go")
    head, found = _parse(show(ticket))
    _put(found, section.strip(), f"{body.rstrip()}\n\n_{iso()}_", add=True)
    write_text(path, _render(head, found))
    return path


def show(ticket: str) -> str:
    path = plan_path(ticket)
    if not os.path.isfile(path):
        return ""
    return open(path, encoding="utf-8").read()


def sections(ticket: str) -> list:
    return [name for name, _body in _parse(show(ticket))[1]]
