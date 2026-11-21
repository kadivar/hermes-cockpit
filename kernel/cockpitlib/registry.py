# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""What cards cockpit makes, what a kickoff starts, and the pages beside cockpit's own: card kinds,
kickoff modes and plugin pages.

Cockpit's own kinds and modes are here. A plugin beside cockpit adds its own, either in its process
(cockpitlib.plugin_api.register_card_kind / register_kickoff_mode) or in the pack block cockpit hands it
(plugins.<name>.card_kinds and plugins.<name>.kickoff_modes), so another process such as the command line sees
them too. A kind a plugin adds is owned by that plugin: housekeeping leaves its cards to it.
"""

from .errors import PackError

# kind: (title template, flow, seat kind). Flow and twin detection read the kind cockpit recorded for a card,
# never the words, so a pack may word a title its own way (skills.yaml cards.titles).
CARD_KINDS = {
    "intake": {"title": "{ticket}: intake", "flow": "intake", "role": "intake"},
    "reopened": {"title": "{ticket}: reopened", "flow": "intake", "role": "intake"},
    "rework": {"title": "{ticket}: rework", "flow": "rework", "role": "worker"},
    "test": {"title": "{ticket}: test", "flow": "test", "role": "tester"},
    "tester": {"title": "{ticket}: tester", "flow": "test", "role": "tester"},
    "test-kickoff": {"title": "{ticket}: test kickoff", "flow": "test", "role": "tester"},
    "review": {"title": "{ticket}: review", "flow": "review", "role": "reviewer"},
    "pr-treat": {"title": "{ticket}: review the PR", "flow": "review", "role": "worker"},
    "analyst": {"title": "{ticket}: analyst", "flow": "analyst", "role": "analyst"},
    "bumps": {"title": "{ticket}: bumps on {repo}", "flow": "bumps", "role": "reviewer"},
    "ci": {"title": "{ticket}: diagnose CI {sha}", "flow": "ci-watch", "role": "analyst"},
    "base": {"title": "{ticket}: base change {change}", "flow": "platform", "role": "analyst"},
    "advisory": {"title": "{ticket}: assess advisory {change}", "flow": "platform", "role": "analyst"},
    "work": {"title": "{ticket}: work", "flow": "card", "role": "worker"},
    "sweep": {"title": "{ticket}: sweep the outbox", "flow": "sweep", "role": "gatekeeper"},
}

# Steps a kickoff runs before its card, in order:
#   bumps         a repo's bumps already started elsewhere refuse the kickoff
#   tester_slot   the ticket's slot is ready and not the human's session
#   intake_go     an intake card still waiting for go refuses the kickoff
#   decision      the ticket's plan has a recorded go
#   reviewer_ready  the tester's run is done; otherwise the card waits blocked for it
#   manual_plan   the cheap gate runs green before a test plan starts
#   slot          a free slot is warmed for the ticket (when the pack has slots)
KICKOFF_MODES = {
    "intake": {
        "lane_kind": "intake",
        "capacity_bucket": "dev",
        "title_kind": "intake",
        "label": "Ticket → intake",
        "preflight": ["slot"],
        "text": "Intake reads the ticket, reproduces it on a free slot, and proposes the plan.",
    },
    "rework": {
        "lane_kind": "worker",
        "capacity_bucket": "dev",
        "title_kind": "rework",
        "label": "Rework → worker",
        "preflight": ["intake_go", "decision"],
        "text": "A worker reworks the ticket's change.",
    },
    "test": {
        "lane_kind": "tester",
        "capacity_bucket": "test",
        "title_kind": "test",
        "label": "Test → tester",
        "preflight": ["tester_slot", "intake_go", "decision", "manual_plan"],
        "text": "A tester plans the run, waits for go, and runs it.",
    },
    "review": {
        "lane_kind": "reviewer",
        "capacity_bucket": "review",
        "title_kind": "review",
        "label": "PR review → reviewer",
        "preflight": ["intake_go", "decision", "reviewer_ready"],
        "text": "A reviewer reviews the pull requests and writes review intents.",
    },
    "bumps": {
        "lane_kind": "reviewer",
        "capacity_bucket": "review",
        "title_kind": "bumps",
        "label": "Bumps → reviewer",
        "preflight": ["bumps"],
        "text": "A reviewer organizes the dependency bumps of a repo.",
    },
    "analyst": {
        "lane_kind": "analyst",
        "capacity_bucket": "question",
        "title_kind": "analyst",
        "label": "Question → analyst",
        "preflight": [],
        "text": "The analyst answers with evidence; the answer and the files it wrote reach the Inbox.",
    },
}
PREFLIGHT = ("bumps", "tester_slot", "intake_go", "decision", "reviewer_ready", "manual_plan", "slot")
BUCKETS = ("dev", "test", "review", "question")
ROLES = ("intake", "worker", "tester", "reviewer", "analyst", "gatekeeper")
# A kickoff starts work on one of these; the gatekeeper's single seat only sweeps the outbox.
KICKOFF_ROLES = ROLES[:-1]

_kinds = {}
_modes = {}


def _check_kind(name, entry, owner) -> dict:
    if (
        not isinstance(entry, dict)
        or set(entry) - {"title", "flow", "role"}
        or not isinstance(entry.get("title"), str)
        or "{ticket}" not in entry["title"]
    ):
        raise PackError(f"card kind {name}: {{title (with {{ticket}}), flow, role}}")
    if entry.get("role", "worker") not in ROLES:
        raise PackError(f"card kind {name}: role is a seat kind ({', '.join(ROLES)})")
    return {
        "title": entry["title"],
        "flow": str(entry.get("flow") or name),
        "role": entry.get("role", "worker"),
        "owner": owner,
    }


def _check_mode(name, entry, owner) -> dict:
    if not isinstance(entry, dict) or set(entry) - {
        "lane_kind",
        "capacity_bucket",
        "title_kind",
        "preflight",
        "text",
        "label",
    }:
        raise PackError(f"kickoff mode {name}: {{lane_kind, capacity_bucket, title_kind, preflight, text, label}}")
    if entry.get("lane_kind") not in KICKOFF_ROLES or entry.get("capacity_bucket", "dev") not in BUCKETS:
        raise PackError(
            f"kickoff mode {name}: lane_kind is one of {', '.join(KICKOFF_ROLES)} and capacity_bucket one of "
            f"{', '.join(BUCKETS)}"
        )
    steps = entry.get("preflight") or []
    if not isinstance(steps, list) or any(step not in PREFLIGHT for step in steps):
        raise PackError(f"kickoff mode {name}: preflight steps are {', '.join(PREFLIGHT)}")
    return {
        "lane_kind": entry["lane_kind"],
        "capacity_bucket": entry.get("capacity_bucket", "dev"),
        "title_kind": entry.get("title_kind") or name,
        "preflight": list(steps),
        "text": str(entry.get("text") or ""),
        "label": str(entry.get("label") or name),
        "owner": owner,
    }


def register_card_kind(name: str, title: str, flow: str = "", role: str = "worker", owner: str = "") -> None:
    """A plugin's card kind, for this process."""
    if name in CARD_KINDS:
        raise PackError(f"card kind {name} is cockpit's own")
    _kinds[name] = _check_kind(name, {"title": title, "flow": flow or name, "role": role}, owner)


def register_kickoff_mode(
    name: str,
    lane_kind: str,
    capacity_bucket: str = "dev",
    title_kind: str = "",
    preflight=(),
    text: str = "",
    label: str = "",
    owner: str = "",
) -> None:
    """A plugin's kickoff mode, for this process."""
    if name in KICKOFF_MODES:
        raise PackError(f"kickoff mode {name} is cockpit's own")
    _modes[name] = _check_mode(
        name,
        {
            "lane_kind": lane_kind,
            "capacity_bucket": capacity_bucket,
            "title_kind": title_kind or name,
            "preflight": list(preflight),
            "text": text,
            "label": label or name,
        },
        owner,
    )


def _from_pack(pack, field, check, builtin) -> dict:
    found = {}
    for owner, block in ((pack or {}).get("plugins") or {}).items():
        for name, entry in ((block or {}).get(field) or {}).items() if isinstance(block, dict) else []:
            if name in builtin:
                raise PackError(f"plugins.{owner}.{field}: {name} is cockpit's own")
            found[name] = check(name, entry, owner)
    return found


def card_kinds(pack=None) -> dict:
    return {
        **{name: {**entry, "owner": ""} for name, entry in CARD_KINDS.items()},
        **_kinds,
        **_from_pack(pack, "card_kinds", _check_kind, CARD_KINDS),
    }


def kickoff_modes(pack=None) -> dict:
    """Every mode a kickoff may start, with the seat kind the pack picks for it (pack.yaml kickoff.lanes)."""
    modes = {
        **{name: {**entry, "owner": ""} for name, entry in KICKOFF_MODES.items()},
        **_modes,
        **_from_pack(pack, "kickoff_modes", _check_mode, KICKOFF_MODES),
    }
    lanes = (((pack or {}).get("kickoff") or {}).get("lanes")) or {}
    for name, kind in lanes.items():
        if name in modes:
            modes[name] = {**modes[name], "lane_kind": kind}
    for name, steps in ((((pack or {}).get("kickoff") or {}).get("preflight")) or {}).items():
        if name in modes and isinstance(steps, list):
            modes[name] = {**modes[name], "preflight": list(steps)}
    return modes


def plugin_pages(pack=None) -> list:
    """The pages of the plugins beside cockpit, as `plugins.<name>.page: {label, path}`.

    Cockpit offers a link to each so the human can cross over without the sidebar, which matters in
    full screen. It learns nothing about the plugin by doing it: the label and the route are the
    plugin's own words, from the pack block cockpit hands it. A pack that declares none — every
    cockpit without a plugin beside it — gets an empty list and no links, and notices nothing.
    """
    found = []
    for owner, block in ((pack or {}).get("plugins") or {}).items():
        page = (block or {}).get("page") if isinstance(block, dict) else None
        if page is None:
            continue
        label = str((page or {}).get("label") or "").strip() if isinstance(page, dict) else ""
        path = str((page or {}).get("path") or "").strip() if isinstance(page, dict) else ""
        if not isinstance(page, dict) or set(page) - {"label", "path"} or not label or not path.startswith("/"):
            raise PackError(f"plugins.{owner}.page takes label and path, and the path starts with /")
        found.append({"plugin": owner, "label": label, "path": path})
    return sorted(found, key=lambda item: item["label"])


def owned_kinds(pack=None) -> dict:
    """kind -> the plugin that owns its cards."""
    return {name: entry["owner"] for name, entry in card_kinds(pack).items() if entry.get("owner")}


def check_kickoff(data) -> None:
    """pack.yaml kickoff: {lanes: {mode: seat kind}, preflight: {mode: [steps]}}. preflight replaces a mode's own checks
    before its card starts (PREFLIGHT); a mode the pack does not name keeps cockpit's."""
    raw = data.get("kickoff")
    if raw is None:
        return
    lanes = raw.get("lanes") if isinstance(raw, dict) else None
    if not isinstance(raw, dict) or set(raw) - {"lanes", "preflight", "done_rows"} or not isinstance(lanes or {}, dict):
        raise PackError("kickoff takes lanes: {mode: seat kind}, preflight: {mode: [steps]} and done_rows: developed")
    if raw.get("done_rows") not in (None, "developed"):
        raise PackError(
            "kickoff.done_rows is developed (the Inbox's done row only for a ticket the human develops: a dev kickoff, "
            "a session, an author PR, or a plugin's ticket; never a test, review or question alone)"
        )
    known = kickoff_modes({**data, "kickoff": None})
    preflight = raw.get("preflight") or {}
    if not isinstance(preflight, dict):
        raise PackError("kickoff.preflight maps a mode to its steps")
    for mode, steps in preflight.items():
        if mode not in known:
            raise PackError(f"kickoff.preflight.{mode}: no such kickoff mode")
        if not isinstance(steps, list) or any(step not in PREFLIGHT for step in steps):
            raise PackError(f"kickoff.preflight.{mode}: steps are {', '.join(PREFLIGHT)}")
    for mode, kind in (lanes or {}).items():
        if kind not in KICKOFF_ROLES:
            raise PackError(f"kickoff.lanes.{mode}: {kind} is not a seat a kickoff starts ({', '.join(KICKOFF_ROLES)})")
        if mode not in known:
            raise PackError(f"kickoff.lanes.{mode}: no such kickoff mode")
