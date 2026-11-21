# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The fence's forge-CLI denies are every built-in forge's own rules together: the forge a pack chooses changes its
hosts and never the commands a lane is refused."""

import pytest

from cockpitlib import egress, forges
from cockpitlib.forges.github import CLI_DENY
from tests.support.both_packs import PACKS

WRITES = (
    'gh pr create --title "TASK-100: the fix" --body done',
    "gh pr merge 7",
    "gh api repos/example/api/pulls/7 --method PATCH",
    "gh api repos/example/api/issues/7/comments -f body=done",
    "gh release create v1",
    "gh issue comment 7 --body done",
    "gh workflow run deploy",
    "gh run rerun 9",
    "gh repo delete example/api",
    "gh label create x",
    "gh secret set TOKEN",
    "gh gist create notes.txt",
    "gh api graphql -f query='mutation { x }'",
)
READS = ("gh api repos/example/api/pulls/7", "gh pr view 7", "gh pr list", "gh pr diff 7", "gh run view 9 --log")


def test_the_kernel_denies_hold_every_built_in_forges_cli_rules_in_their_place():
    assert set(CLI_DENY) <= set(forges.cli_deny()) <= set(egress.KERNEL_DENY)
    for kind in forges.KINDS:
        assert set(forges.implementation(kind).cli_deny()) <= set(egress.KERNEL_DENY), kind
    first = egress.KERNEL_DENY.index(CLI_DENY[0])
    assert (
        egress.KERNEL_DENY[first : first + len(CLI_DENY)] == CLI_DENY
        and egress.KERNEL_DENY[:first] == egress._BEFORE_FORGE_CLI
    )
    assert len(egress.KERNEL_DENY) == len(set(egress.KERNEL_DENY))


@pytest.mark.parametrize("kind", sorted(forges.KINDS))
@pytest.mark.parametrize("pack_file", PACKS)
def test_a_forge_cli_write_is_refused_and_a_read_is_not_whichever_forge_the_pack_chose(
    bare, pack_file, kind, monkeypatch, tmp_path
):
    import os
    import shutil

    import yaml

    folder = tmp_path / "packs" / os.path.basename(os.path.dirname(pack_file))
    shutil.copytree(os.path.dirname(pack_file), folder)
    raw = yaml.safe_load((folder / "pack.yaml").read_text(encoding="utf-8"))
    raw["forge"] = {**(raw.get("forge") or {}), "kind": kind}
    (folder / "pack.yaml").write_text(yaml.safe_dump(raw, sort_keys=False, allow_unicode=True), encoding="utf-8")
    monkeypatch.setenv("COCKPIT_PACK", str(folder / "pack.yaml"))
    monkeypatch.setenv("COCKPIT_LANE", "worker-1")
    monkeypatch.delenv("COCKPIT_HUMAN", raising=False)
    for command in WRITES:
        said = egress.explained(egress.check_tool("terminal", {"command": command}))
        assert said.startswith("blocked: a denied command (rule \\bgh\\s"), (kind, command, said)
    for command in READS:
        assert egress.check_tool("terminal", {"command": command}) == "", (kind, command)
    assert (
        egress.check_tool("terminal", {"command": "curl -X POST https://api.github.com/repos/example/api/pulls -d x"})
        == "blocked"
    )
