# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The functions another plugin may call. Their signatures are pinned (tests/contract/cockpit-api.json); a change
raises API_VERSION, so a plugin can check the version it was built for before it calls anything. A version this
kernel still serves stays at or above API_MIN_SUPPORTED: a plugin built for an older API keeps working on a newer
kernel until that floor passes it.

Everything here goes through cockpit's own policy: start_card runs the same checks the Kick off page runs, card
writes go through Hermes's board functions, and outbox writes through the outbox.
"""

from . import halt  # noqa: F401  halt.write(ticket, note) and halt.clear(ticket)
from .errors import CockpitError

API_VERSION = 1
API_MIN_SUPPORTED = 1  # the oldest API version a plugin may have been built for


def _pack(pack=None) -> dict:
    if pack is not None:
        return pack
    from .pack import load
    from .paths import pack_path

    return load(pack_path())


def records_root() -> str:
    """The workspace folder the bound pack keeps its records in."""
    from .paths import records

    return records()


def plugin_block(name: str, pack=None) -> dict:
    """The block the bound pack gives this plugin, as the plugin's own validator returned it."""
    from .pack import plugin_block as block

    return block(_pack(pack), name)


def start_card(
    mode: str,
    ticket: str,
    body: str = "",
    policy: str = "kickoff",
    pack=None,
    prompt: str = "",
    idempotency_key: str = "",
    model_override: str = "",
    max_runtime_seconds: int = 0,
    repos=(),
) -> dict:
    """Start a card for a kickoff mode with the Kick off page's own checks: halt, twin, capacity, the lane the pack
    picks, a slot, the tester's slot, the browser loan. policy="release" records the go instead of asking for it.
    max_runtime_seconds: Hermes ends and re-queues the card's run past this many seconds (0: no limit, as before); it
    is carried by the one card a mode starts, not by the per-repo rework cards a repo list makes.
    repos: the repos this one card works in, recorded on it (its own PRs and its repos' skills). Each is a repos.yaml name, or a short name that resolves to one (_resolve_repos); one that
    resolves to none or to several is refused with CockpitError and no card starts. They never fan the card out: a rework
    still starts one card, with its time limit; a bumps card stays keyed by its repo. Given repos, the result carries the
    resolved names as `repos`. Empty (the default): the card records no repos and the result is as before."""
    from .kickoff import start

    if isinstance(max_runtime_seconds, bool) or not isinstance(max_runtime_seconds, int) or max_runtime_seconds < 0:
        raise CockpitError(
            f"max_runtime_seconds is a whole number of seconds, 0 for no limit, not {max_runtime_seconds!r}"
        )
    if isinstance(repos, (str, bytes, dict)):
        raise CockpitError(f"repos is a list of repo names, not {repos!r}")
    try:
        given = list(repos or ())  # read once: a generator is spent by its first pass
    except TypeError:
        raise CockpitError(f"repos is a list of repo names, not {repos!r}") from None
    if not all(isinstance(item, str) for item in given):
        raise CockpitError(f"repos is a list of repo names, not {given!r}")
    data = _pack(pack)
    named = _resolve_repos(given, data)
    started = start(
        data,
        mode,
        ticket=ticket,
        prompt=prompt,
        body=body,
        policy=policy,
        idempotency_key=idempotency_key,
        model_override=model_override,
        max_runtime_seconds=max_runtime_seconds,
        card_repos=named,
    )
    return {**started, "repos": named} if given else started


def _resolve_repos(names: list, pack=None) -> list:
    """The repos.yaml names these stand for, in order, once each: a repos.yaml name as it is; else the repo whose
    repos.yaml `label` it is; else the one repo whose name starts with it and a dot (core: core.shop.example.test).
    A blank name is skipped. A name that matches none, or several, raises CockpitError naming it: a dropped name would
    leave the card fence open."""
    repos = [
        repo
        for repo in ((_pack(pack).get("repos") or {}).get("repos") or [])
        if isinstance(repo, dict) and repo.get("name")
    ]
    found = []
    for raw in names or ():
        name = str(raw or "").strip()
        if not name:
            continue
        exact = [str(repo["name"]) for repo in repos if str(repo["name"]) == name]
        labelled = [str(repo["name"]) for repo in repos if str(repo.get("label") or "") == name]
        prefixed = [str(repo["name"]) for repo in repos if str(repo["name"]).startswith(name + ".")]
        match = exact or labelled or prefixed
        if not match:
            raise CockpitError(f"{name} is not a repo of this pack")
        if len(match) > 1:
            raise CockpitError(f"{name} is ambiguous ({', '.join(match)})")
        if match[0] not in found:
            found.append(match[0])
    return found


def archive(card: str, reason: str, plugin: str, pack=None) -> dict:
    """Archive one of a plugin's own cards: a card of a kind registered with owner=plugin. The reason is commented on it
    first, as the plugin; then Hermes archives it, which ends a running worker. Any other card (cockpit's own kinds,
    another plugin's, the human's) is refused. An archived card is left alone: no error, no second comment.
    {archived, was_running}. An archived card counts in no capacity and no housekeeping step brings it back."""
    from .kanban import BoardWrites, board_cards, card_entry
    from .registry import owned_kinds

    data = _pack(pack)
    board = str(data["board"])
    kind = card_entry(board, card).get("kind") or ""
    if not kind or owned_kinds(data).get(kind) != plugin:
        raise CockpitError(f"card {card} is not {plugin}'s")
    status = next((item["status"] for item in board_cards(board, data) if item["id"] == card), "")
    if status == "archived":
        return {"archived": False, "was_running": False}
    writes = BoardWrites(board)
    writes.comment(card, plugin, reason)
    writes.archive(card)
    results = writes.flush()
    return {"archived": bool(results[-1]), "was_running": status == "running"}


def board_cards(ticket: str = "", pack=None) -> list:
    """The board's cards, or one ticket's: id, title, status, assignee, ticket, flow, kind, skills, body."""
    from .kanban import _index
    from .kanban import board_cards as cards

    data = _pack(pack)
    kinds = _index().get(str(data["board"])) or {}
    found = []
    for card in cards(str(data["board"]), data):
        if ticket and card.get("ticket") != ticket:
            continue
        found.append({**card, "kind": (kinds.get(card["id"]) or {}).get("kind") or ""})
    return found


def runs(card: str, pack=None) -> list:
    """A card's runs, oldest first: {id, status, outcome, error, summary, metadata, profile, started_at, ended_at}. The
    metadata carries the claims a lane put on its closing run; outcome and error are Hermes's own (a run ended for its
    time limit has an error starting `elapsed`)."""
    from .kanban import task_runs

    return task_runs(str(_pack(pack)["board"]), card)


def comment(card: str, text: str, author: str = "cockpit", pack=None) -> None:
    """A comment on a card. On a running card Hermes hands it to the live worker."""
    from .kanban import BoardWrites

    writes = BoardWrites(str(_pack(pack)["board"]))
    writes.comment(card, author, text)
    writes.flush()


def answer(card: str, text: str, pack=None) -> dict:
    """The human's answer on a blocked card, with the same rules the Inbox applies."""
    from .acts import answer_card

    return answer_card(_pack(pack), card, text)


def block(card: str, reason: str, kind: str = "", pack=None) -> None:
    from .kanban import BoardWrites, block_kind

    writes = BoardWrites(str(_pack(pack)["board"]))
    writes.block(card, reason, kind or block_kind(reason))
    writes.flush()


def unblock(card: str, pack=None) -> None:
    from .kanban import BoardWrites

    writes = BoardWrites(str(_pack(pack)["board"]))
    writes.unblock(card)
    writes.flush()


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
    from .registry import register_kickoff_mode as register

    register(name, lane_kind, capacity_bucket, title_kind, preflight, text, label, owner)


def register_card_kind(name: str, title: str, flow: str = "", role: str = "worker", owner: str = "") -> None:
    from .registry import register_card_kind as register

    register(name, title, flow, role, owner)


def inbox_row(plugin: str, row: dict) -> str:
    """A row on the human's Inbox: {id, icon, what, action_label, href, tone}. The same file contract a plugin may
    write itself: <records>/inbox/<plugin>/<id>.json."""
    from .inbox import put_row

    return put_row(plugin, row)


def drop_inbox_row(plugin: str, row_id: str) -> bool:
    from .inbox import drop_row

    return drop_row(plugin, row_id)


def wake_marker(plugin: str) -> str:
    """The file housekeeping touches when a card a plugin owns needs that plugin's attention."""
    from .inbox import wake_path

    return wake_path(plugin)


def helper_run(name: str, verb: str, choice: str = "", background: bool = True, pack=None) -> dict:
    """Run one of the pack's helpers (helpers.yaml): its dependencies first, exit 3 when one is down."""
    from .helpers import run

    return run(_pack(pack), name, verb, choice, background)


def helper_status(group: str = "", pack=None) -> dict:
    """The helper groups' status rows and each helper's last run."""
    from .helpers import status

    return status(_pack(pack), group)


def outbox_create(
    ticket: str, kind: str, card: str, summary: str, payload: dict, created_by: str = "human", pack=None
) -> dict:
    """An intent in the outbox, with the outbox's own checks (ticket pattern, local references, skills)."""
    from .outbox import create

    return create(_pack(pack), ticket, kind, card, summary, payload, created_by=created_by)


def halted(ticket: str) -> str:
    """'' when the ticket takes new cards; otherwise why it does not, in cockpit's words ("TASK-123 is halted ...")."""
    from .halt import describe
    from .halt import halted as record

    found = record(ticket or "")
    return describe(ticket, found) if found else ""


def resume_ticket(ticket: str) -> str:
    """Lift a ticket's halt, as the ticket page's Resume does. Closed cards stay closed."""
    from .acts import resume_ticket as resume

    return resume(ticket)


def own_tickets(plugin: str, tickets) -> int:
    """The tickets this plugin runs itself, the whole list, rewritten on each of its passes. Cockpit's watchers leave
    their follow-up to it: a real CI failure on one of them opens no intake card waiting for the human."""
    from .owners import own

    return own(plugin, tickets)


def ticket_owner(ticket: str) -> str:
    """The plugin that runs this ticket, or ''."""
    from .owners import owner_of

    return owner_of(ticket)


def watch_prs(plugin: str, prs) -> int:
    """The PRs of the tickets this plugin runs, the whole list ([{ticket, repo, number, url, ready}]), rewritten on each
    pass. Cockpit's PR watch follows them like its own: the human gets a merge row once the plugin marks one ready, and a
    ticket's ticket-done ack once every PR of it is merged and nothing of it is open."""
    from .owners import own_prs

    return own_prs(plugin, prs)


def done_waiting(tickets) -> list:
    """The ticket-done items of these tickets still waiting for the human's ack: [{id, ticket}]."""
    from .intents import all_intents

    wanted = set(tickets or ())
    return [
        {"id": row["id"], "ticket": row["ticket"]}
        for row in all_intents()
        if row.get("type") == "ticket-done" and row.get("status") == "pending" and row.get("ticket") in wanted
    ]


def ack_tickets(tickets) -> list:
    """Acknowledge every waiting ticket-done item of these tickets, as the human's Confirm done does one: the ids."""
    from .outbox import ack

    return [ack(row["id"])["id"] for row in done_waiting(tickets)]


def card_thread(card: str, pack=None) -> dict:
    """A card's state and what was said on it, for a plugin answering on the human's behalf: {id, title, status,
    block_kind, blocked_at, comments: [{author, body, at}]}, comments oldest first."""
    from .lane_feed import card as card_view

    shown = card_view(_pack(pack), card)
    # waiting since it blocked, or since Hermes parked a repeated block in triage
    blocked = [
        event["ts"] for event in shown.get("events") or [] if event.get("kind") in ("blocked", "block_loop_detected")
    ]
    events = shown.get("events") or []
    # Hermes keeps declining to restart it (the last thing on it is a respawn guard): an answered card that is not moving
    guarded = bool(events) and events[-1].get("kind") == "respawn_guarded"
    return {
        "id": card,
        "title": shown.get("title") or "",
        "status": shown.get("status") or "",
        "block_kind": shown.get("block_kind") or "",
        "blocked_at": blocked[-1] if blocked else "",
        "guarded": guarded,
        "comments": [
            {"author": item["author"], "body": item["body"], "at": item["ts"]} for item in shown.get("comments") or []
        ],
    }


def hand_over_card(card: str, pack=None) -> str:
    """Move a card to another seat of its kind, the least busy one; the new seat, or '' when it has none. Hermes does
    not restart a card whose recent comments carry a PR link unless another seat takes it over, so an answered
    analyst card that cites PRs resumes this way."""
    import re as _re

    from .kanban import BoardWrites, open_cards
    from .lane_feed import card as card_view
    from .lanes import lanes_of
    from .settings import load as load_settings

    data = _pack(pack)
    current = str(card_view(data, card).get("assignee") or "")
    kind = _re.sub(r"-\d+$", "", current)
    per_slot = kind in ("worker", "tester")
    seats = load_settings(data)["seats"]
    count = seats.get("slots" if per_slot else kind) or 0
    others = [lane for lane in lanes_of(kind, int(count), per_slot) if lane != current]
    if not current or not others:
        return ""
    busy = open_cards(str(data["board"]))
    lane = min(others, key=lambda name: (busy.get(name, 0), others.index(name)))
    writes = BoardWrites(str(data["board"]))
    writes.assign(card, lane)
    writes.flush()
    return lane


def held_intents(tickets) -> list:
    """These tickets' outbox items held for the human: what was held and why, with what a push sends."""
    from .intents import all_intents

    wanted = set(tickets or ())
    found = []
    for row in all_intents():
        hold = row.get("hold") or {}
        if row.get("status") != "held" or row.get("ticket") not in wanted or hold.get("waits") != "human":
            continue
        payload = row.get("payload") or {}
        found.append(
            {
                "id": row["id"],
                "ticket": row["ticket"],
                "type": row.get("type") or "",
                "summary": row.get("agent_summary") or "",
                "created_by": row.get("created_by") or "",
                "hold": {key: hold.get(key) for key in ("reason", "ask", "options", "time")},
                "protected": _protected_target(row),
                "payload": {
                    key: payload.get(key)
                    for key in (
                        "repo",
                        "branch",
                        "publish_as",
                        "base",
                        "sha",
                        "commits",
                        "files",
                        "diffstat",
                        "foreign",
                        "fixups",
                        "remote_sha",
                    )
                },
            }
        )
    return found


def _protected_target(row, pack=None) -> bool:
    """The item writes a protected branch, or opens or retargets a PR into a base other than its repo's own: the human's
    decision alone, never a plugin's on their behalf."""
    from .git_push import protected, repo_branch
    from .intents import PUSHES

    payload = row.get("payload") or {}
    try:
        pack = _pack(pack)
    except Exception:  # noqa: BLE001 - a pack that cannot be read leaves the answer with the human
        return True  # unknown means it stays with the human
    repo = payload.get("repo") or ""
    if row.get("type") in PUSHES:
        return (payload.get("publish_as") or payload.get("branch") or "") in protected(pack, repo)
    if row.get("type") in ("open-pr", "pr-edit") and payload.get("base"):
        return payload["base"] != repo_branch(pack, repo)
    return False


def decide_intent(iid: str, decision: str, note: str = "", by: str = "plugin", pack=None) -> dict:
    """A plugin's decision on a held item, on the human's behalf: confirm (endorsed as `by`; its scope's auto-publish
    then sends it), send_back (to its lane with `note`), or drop. The item records who decided and why."""
    from .errors import CockpitError
    from .outbox import drop, endorse, load

    intent = load(iid)
    if intent.get("status") != "held":
        raise CockpitError(f"{iid} is {intent.get('status')}: only a held item is decided")
    data = _pack(pack)
    from .outbox import OWNER

    if decision == "confirm" and by != OWNER and _protected_target(intent, data):
        raise CockpitError(f"{iid} writes a protected branch or picks a PR base: only the human confirms it")
    if decision == "confirm":
        reason = (intent.get("hold") or {}).get("reason") or "held"
        return endorse(
            iid,
            intent.get("risk_hint") or "low",
            f"confirmed by {by}: {reason}" + (f" — {note}" if note else ""),
            by,
            "",
            "",
            pack=data,
        )
    if decision == "send_back":
        from .gate import return_intent

        return return_intent(data, iid, note or f"sent back by {by}", actor=by)
    if decision == "drop":
        return drop(iid, f"dropped by {by}" + (f": {note}" if note else ""))
    raise CockpitError("decision is confirm, send_back or drop")


def require(version: int) -> None:
    """A plugin calls this first with the API version it was built for: any version from API_MIN_SUPPORTED to
    API_VERSION is served; a newer one, or one this kernel no longer carries, refuses and says which side to update."""
    if not isinstance(version, (int, float)):
        raise CockpitError(
            f"cockpit API {API_VERSION}, not {version!r}: the version a plugin was built for is a number"
        )
    if version > API_VERSION:
        raise CockpitError(
            f"cockpit API {API_VERSION}, not {version}: the plugin was built for a newer cockpit (update cockpit)"
        )
    if version < API_MIN_SUPPORTED:
        raise CockpitError(
            f"cockpit API {API_VERSION}, not {version}: this cockpit serves {API_MIN_SUPPORTED} and later "
            "(update the plugin)"
        )
