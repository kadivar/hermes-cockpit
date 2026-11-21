# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The forges a pack can publish to, by `forge.kind`. Each is one implementation of the protocol in `base`.

`make` is what `publish.forge_for` returns. `seam` is for code that is handed a forge: it gives back the forge itself, or
a GitHub forge over an object from before the protocol. `cli_deny` is every built-in forge's own CLI writes together:
the fence refuses them all, whichever forge the pack chose.
"""

from ..errors import PackError
from .base import Forge, Unsupported, missing, needs  # noqa: F401 - the protocol's names, for the code that uses a forge

DEFAULT = "github"
KINDS = {"github": ("github", "GitHubForge"), "local": ("local", "LocalForge")}


def kind_of(pack) -> str:
    """The pack's forge kind: github unless forge.kind names another."""
    return str(((pack or {}).get("forge") or {}).get("kind") or DEFAULT)


def implementation(kind: str):
    """The class that answers for that kind."""
    if kind not in KINDS:
        raise PackError(f"forge.kind is one of {', '.join(sorted(KINDS))}")
    import importlib

    module, name = KINDS[kind]
    return getattr(importlib.import_module(f"{__name__}.{module}"), name)


def make(pack, dry_run: bool = False) -> Forge:
    """The pack's forge, as the human."""
    return implementation(kind_of(pack))(pack, dry_run=dry_run)


def seam(forge):
    """A forge that answers the protocol: the one given, or a GitHub forge over an older object that answers REST paths."""
    if forge is None or isinstance(forge, Forge):
        return forge
    from .github import Wrapped

    return Wrapped(forge)


def default_hosts() -> list:
    """The hosts the built-in forges are reached at when a pack names none: a write to one goes through the outbox in every pack."""
    found = []
    for kind in KINDS:
        found += [host for host in implementation(kind).default_hosts if host not in found]
    return found


def cli_deny() -> tuple:
    """The command patterns every built-in forge's CLI writes with, in one list: no pack setting takes one out."""
    found = []
    for kind in KINDS:
        for pattern in implementation(kind).cli_deny():
            if pattern not in found:
                found.append(pattern)
    return tuple(found)
