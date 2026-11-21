# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""A seat's logins live in that seat's own Hermes vault store. The lane fills them with Hermes's browser_vault.

Cockpit places, lists, and removes them through the hermes_bridge vault helper; the password never comes back here.
A login is placed only for an owning lane or for the seats a shared login names as readers, and only for a staging
or slot origin.
"""

import os
import re

from .errors import CockpitError
from .lanes import profile_dir, seats_from

MARK = "cockpit "


def label(kind: str, identifier: str, card: str = "") -> str:
    """lane, shared, or lent <card>: what cockpit placed and why."""
    return f"{MARK}{kind} {card + ' ' if card else ''}{identifier}"


def _run(ops) -> list:
    from .hermes_runtime import run_helper

    results = run_helper("vault", {"ops": ops})["results"]
    for result in results:
        if isinstance(result, dict) and result.get("error"):
            raise CockpitError(f"vault: {result['error']}")
    return results


def items(lane: str) -> list:
    """The lane's store, metadata only. A seat with no store lists nothing."""
    return items_of([lane]).get(lane) or []


def items_of(lanes) -> dict:
    """Several stores in one helper run. A lane with no store lists nothing and starts no helper."""
    lanes = [lane for lane in lanes if os.path.isfile(os.path.join(profile_dir(lane), "vault", "vault.json.enc"))]
    if not lanes:
        return {}
    return dict(zip(lanes, _run([{"op": "list", "home": profile_dir(lane)} for lane in lanes])))


def store_stamps(pack) -> dict:
    """lane -> its store's mtime, for every seat that has one."""
    found = {}
    for lane in seats(pack):
        path = os.path.join(profile_dir(lane), "vault", "vault.json.enc")
        if os.path.isfile(path):
            found[lane] = os.path.getmtime(path)
    return found


def place(
    lane: str, origin: str, identifier: str, password: str, otp: str = "", kind: str = "lane", card: str = ""
) -> str:
    if not password:
        raise CockpitError("a login needs its password")
    return _run(
        [
            {
                "op": "add",
                "home": profile_dir(lane),
                "label": label(kind, identifier, card),
                "origin": origin,
                "identifier": identifier,
                "identifier_type": identifier_type(identifier),
                "password": password,
                "otp_secret": otp or "",
            }
        ]
    )[0]


def remove(lane: str, item_id: str) -> bool:
    return bool(_run([{"op": "remove", "home": profile_dir(lane), "id": item_id}])[0])


def secret_for(pack, origin: str, identifier: str) -> str:
    """The password a seat store holds for the login, for the human's own page (the demo card): the tester seats
    first, then every other seat. Empty when no seat holds it. The caller fences; the value never goes to a lane,
    a log or a tool result."""
    kinds = seats_from(pack)
    order = list(kinds.get("tester") or []) + [lane for lane in seats(pack) if lane not in (kinds.get("tester") or [])]
    lanes = [lane for lane in order if os.path.isfile(os.path.join(profile_dir(lane), "vault", "vault.json.enc"))]
    if not lanes or not identifier:
        return ""
    for result in _run(
        [{"op": "secret", "home": profile_dir(lane), "origin": origin, "identifier": identifier} for lane in lanes]
    ):
        if isinstance(result, str) and result:
            return result
    return ""


def identifier_type(identifier: str) -> str:
    text = str(identifier or "")
    if "@" in text:
        return "email"
    if re.fullmatch(r"\+?[\d\s()-]{7,}", text):
        return "phone"
    return "username"


def seats(pack) -> list:
    return [lane for names in seats_from(pack).values() for lane in names]


def accepted_origins(pack) -> list:
    """The pack's staging origins (staging.yaml), each environment's origins, and any loopback slot origin."""
    from . import pack_local

    found = []
    path = os.path.join((pack or {}).get("_dir") or "", "staging.yaml")
    if os.path.isfile(path):
        data = pack_local.read(path) or {}
        found += [str(value) for value in (data.get("origins") or {}).values() if value]
    for environment in (pack or {}).get("environments") or []:
        found += [str(value) for value in (environment.get("origins") or {}).values() if value]
    return [origin.rstrip("/") for origin in found]


def _origin_of(url: str) -> str:
    from urllib.parse import urlsplit

    parts = urlsplit(str(url or ""))
    if not parts.scheme or not parts.hostname:
        return ""
    port = parts.port
    default = {"http": 80, "https": 443}.get(parts.scheme)
    return f"{parts.scheme}://{parts.hostname}" + (f":{port}" if port and port != default else "")


def origin_accepted(pack, origin: str) -> bool:
    normal = _origin_of(origin)
    if not normal:
        return False
    if re.fullmatch(r"https?://(localhost|127\.0\.0\.1)(:\d+)?", normal):
        return True
    return normal in [_origin_of(item) for item in accepted_origins(pack)]


def check_origin(pack, origin: str) -> None:
    if not origin_accepted(pack, origin):
        raise CockpitError(f"{origin} is not a staging or slot origin of this pack")


def readers(pack, origin: str, identifier: str) -> list:
    """The seats a shared login names (logins.shared[].readers, or an accounts-manifest entry's readers): seat names
    or seat kinds."""
    from .accounts import readers as account_readers

    kinds = seats_from(pack)
    names = []
    for row in ((pack or {}).get("logins") or {}).get("shared") or []:
        if (
            isinstance(row, dict)
            and _origin_of(row.get("origin")) == _origin_of(origin)
            and row.get("email") == identifier
        ):
            names += row.get("readers") or []
    names += account_readers(pack, origin, identifier)
    found = []
    for name in names:
        for lane in kinds.get(name) or [name]:
            if lane in seats(pack) and lane not in found:
                found.append(lane)
    return found


def _expected(pack) -> dict:
    """(lane, origin, identifier) -> kind: what cockpit placed, from its metadata (no key needed) and the pack."""
    from .vault import login_metadata

    expected = {}
    for row in login_metadata():
        if row.get("lane") and row.get("lane") in seats(pack):
            expected[(row["lane"], _origin_of(row["origin"]), row["email"])] = "lane"
        for reader in readers(pack, row.get("origin") or "", row.get("email") or ""):
            expected.setdefault((reader, _origin_of(row["origin"]), row["email"]), "shared")
    return expected


def _lent_cards() -> set:
    import json

    from .paths import watch_dir

    path = os.path.join(watch_dir(), "admin-lends.json")
    try:
        rows = json.load(open(path, encoding="utf-8"))
    except (OSError, ValueError):
        rows = []
    return {str(row.get("card")) for row in rows if isinstance(row, dict)}


def audit(pack, fix: bool = False) -> list:
    """Findings in every seat's store: a foreign origin, a login cockpit did not place there, a lend with no record,
    a duplicate, and a login that should be there and is not. --fix removes the first four and places the last."""
    expected = _expected(pack)
    lent = _lent_cards()
    findings = []
    removals = []
    present = set()
    listed = items_of(seats(pack))
    for lane in seats(pack):
        seen = set()
        for item in listed.get(lane) or []:
            origin = _origin_of(item.get("origin"))
            identifier = item.get("identifier") or ""
            tag = str(item.get("label") or "")
            kind = tag[len(MARK) :].split(" ", 1)[0] if tag.startswith(MARK) else "own"
            key = (lane, origin, identifier)
            problem = ""
            if not origin_accepted(pack, origin):
                problem = "foreign origin"
            elif kind == "lent" and tag[len(MARK + "lent ") :].split(" ", 1)[0] not in lent:
                problem = "lend with no record"
            elif kind in ("lane", "shared") and expected.get(key) != kind:
                problem = "not placed by cockpit"
            elif (origin, identifier, kind) in seen:
                problem = "duplicate"
            seen.add((origin, identifier, kind))
            if kind in ("lane", "shared") and not problem:
                present.add(key)
            if problem:
                findings.append(f"{problem}: {lane} {origin} {identifier}")
                removals.append((lane, item.get("id") or ""))
    missing = [key for key in expected if key not in present]
    findings += [f"missing: {lane} {origin} {identifier}" for lane, origin, identifier in missing]
    if not fix:
        return findings
    for lane, item in removals:
        remove(lane, item)
    from .vault import _previous, _scope_for

    for lane, origin, identifier in missing:
        stored = _previous(origin, identifier, _scope_for(False)) or {}
        if stored.get("secret"):
            place(
                lane,
                stored.get("origin") or origin,
                identifier,
                stored["secret"],
                stored.get("otp") or "",
                kind=expected[(lane, origin, identifier)],
            )
    from .scrub import rebuild

    rebuild()
    return audit(pack)
