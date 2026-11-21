# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""An infrastructure change a lane may not write: the lane leaves it as a patch, the human applies it.

The pack's egress keeps the infrastructure paths (CI workflows, Dockerfiles, deploy files) closed to every lane. A lane
whose work needs such a change files an `infra-note` with the patch (`--repo`, `--branch`, `--patch-file`). Applying it
is the human's act on that one diff: the patch is committed on the ticket's checkout as the human's commit and its
push is filed like any other, so it passes the gatekeeper and the human's Publish. No lane gains a path it lacked.
"""

import os
import subprocess

from .errors import CockpitError
from .intents import OPEN_STATUSES, advance, load, save
from .store import log
from .time_util import iso


def _git(folder: str, *args) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", folder, *args], capture_output=True, text=True, check=False)


def _said(done) -> str:
    return (done.stderr or done.stdout or "git failed").strip()[-300:]


def patch_of(intent) -> dict:
    """{repo, branch, patch} of a note that carries a patch to apply, else {}."""
    payload = intent.get("payload") or {}
    if intent.get("type") != "infra-note" or not all(payload.get(key) for key in ("repo", "branch", "patch_file")):
        return {}
    return {"repo": payload["repo"], "branch": payload["branch"], "patch": payload["patch_file"]}


def apply(pack, iid: str) -> dict:
    """Commit the note's patch on the ticket's checkout as the human, and file its push. {commit, files, push}."""
    from .outbox import create, human_gate
    from .paths import workspace
    from .worktree import _checkout

    human_gate("applying an infrastructure patch")
    intent = load(iid)
    found = patch_of(intent)
    if not found:
        raise CockpitError(f"{iid} carries no patch to apply: an infra-note names --repo, --branch and --patch-file")
    if intent.get("status") not in OPEN_STATUSES:
        raise CockpitError(f"{iid} is {intent.get('status')}: only an open note is applied")
    patch = found["patch"] if os.path.isabs(found["patch"]) else os.path.join(workspace(), found["patch"])
    if not os.path.isfile(patch):
        raise CockpitError(f"no patch file {found['patch']}")
    folder = _checkout(intent["ticket"], found["repo"], pack)
    if _git(folder, "status", "--porcelain").stdout.strip():
        raise CockpitError(f"{folder} has changes that are not committed: the patch is applied on a clean checkout")
    before = _git(folder, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
    if before != found["branch"]:
        moved = _git(folder, "switch", "--quiet", found["branch"])
        if moved.returncode != 0:
            raise CockpitError(f"{found['branch']} cannot be checked out in {folder}: {_said(moved)}")
    try:
        checked = _git(folder, "apply", "--check", "--index", patch)
        if checked.returncode != 0:
            raise CockpitError(f"the patch does not apply on {found['branch']}: {_said(checked)}")
        _git(folder, "apply", "--index", patch)
        files = [line for line in _git(folder, "diff", "--cached", "--name-only").stdout.splitlines() if line]
        summary = str(
            intent.get("agent_summary") or (intent.get("payload") or {}).get("summary") or "infrastructure change"
        ).strip()
        title = summary.splitlines()[0][:100]
        done = _git(
            folder,
            "commit",
            "--quiet",
            "-m",
            title,
            "-m",
            f"Applied by the human from the note {iid} ({intent.get('created_by') or 'a lane'} wrote the patch).",
        )
        if done.returncode != 0:
            raise CockpitError(f"the commit was refused: {_said(done)}")
    except CockpitError:
        _git(folder, "reset", "--quiet", "--hard", "HEAD")  # the checkout was clean before: nothing of anyone's is lost
        if before != found["branch"]:
            _git(folder, "switch", "--quiet", before)
        raise
    commit = _git(folder, "rev-parse", "HEAD").stdout.strip()
    payload = {"repo": found["repo"], "branch": found["branch"]}
    if (intent.get("payload") or {}).get("waits_for"):
        payload["waits_for"] = intent["payload"]["waits_for"]
    push = create(
        pack,
        intent["ticket"],
        "push-branch",
        intent.get("card_id") or "",
        f"Push the applied note {iid}: {title}",
        payload,
        created_by="human",
    )
    intent.setdefault("history", []).append(
        {"time": iso(), "event": "patch applied by the human", "commit": commit, "push": push["id"]}
    )
    advance(intent, "published-manually", "human")
    save(intent)
    # what waited for the note now waits for the push that carries it: the note is done, its commit is not out yet
    from .intents import OPEN_STATUSES as still_open
    from .intents import all_intents as every

    for other in every(intent["ticket"]):
        if (
            other["id"] != push["id"]
            and other.get("status") in still_open
            and (other.get("payload") or {}).get("waits_for") == iid
        ):
            other["payload"]["waits_for"] = push["id"]
            other.setdefault("history", []).append(
                {"time": iso(), "event": f"waits for {push['id']}: the note {iid} was applied and that push carries it"}
            )
            save(other)
    log(f"APPLY-NOTE {iid} {commit[:9]} → {push['id']}")
    return {"commit": commit, "files": files, "push": push["id"]}
