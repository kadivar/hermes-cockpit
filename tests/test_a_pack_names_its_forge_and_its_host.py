# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""forge.kind chooses the forge a pack publishes to and forge.host its own host; a pack that names neither is on
github.com through `gh` with no host at all, exactly as before."""

import json
import os

import pytest
import yaml

from cockpitlib import egress, forges, pack_keys
from cockpitlib.errors import PackError
from cockpitlib.forges.github import GitHubForge
from cockpitlib.pack import load
from tests.support.both_packs import PACKS


class _Done:
    returncode, stderr = 0, ""

    def __init__(self, stdout="{}"):
        self.stdout = stdout


def _copy(tmp_path, pack_file, forge: dict) -> str:
    import shutil

    folder = (
        tmp_path / "packs" / os.path.basename(os.path.dirname(pack_file))
    )  # a fixture pack's @anchors need the folder above to be packs
    shutil.copytree(os.path.dirname(pack_file), folder)
    raw = yaml.safe_load((folder / "pack.yaml").read_text(encoding="utf-8"))
    raw["forge"] = {**(raw.get("forge") or {}), **forge}
    (folder / "pack.yaml").write_text(yaml.safe_dump(raw, sort_keys=False, allow_unicode=True), encoding="utf-8")
    return str(folder / "pack.yaml")


@pytest.mark.parametrize("pack_file", PACKS)
def test_a_pack_that_names_no_forge_is_on_github_with_no_host_in_any_call(pack_file):
    from cockpitlib.publish import forge_for

    pack = load(pack_file)
    asked = []
    forge = forge_for(pack)
    forge.runner = lambda argv, **_kwargs: asked.append(argv) or _Done()
    assert (
        type(forge) is GitHubForge
        and forge.kind == "github"
        and forge.host == "github.com"
        and forges.kind_of(pack) == "github"
    )
    repo = pack["repos"]["repos"][0]["name"]
    forge.pr(repo, 4)
    assert asked == [["gh", "api", f"repos/{forge.org}/{repo}/pulls/4"]]
    assert forge.url(repo, 4) == f"https://github.com/{forge.org}/{repo}/pull/4" and forge.hosts() == ["github.com"]
    assert forge._cli_repo(repo) == f"{forge.org}/{repo}"
    assert (
        egress.forge_hosts(pack)[0] == "github.com" and len(egress.forge_hosts(pack)) == 2
    )  # the forge and the tracker, as before


@pytest.mark.parametrize("pack_file", PACKS)
def test_a_named_host_is_in_every_page_every_call_and_the_fence(pack_file, tmp_path, monkeypatch):
    import subprocess

    pack = load(_copy(tmp_path, pack_file, {"kind": "github", "host": "github.example.test"}))
    asked = []
    forge = forges.make(pack)
    forge.runner = lambda argv, **_kwargs: asked.append(argv) or _Done()
    repo = pack["repos"]["repos"][0]["name"]
    full = f"{forge.org}/{repo}"
    forge.pr(repo, 4)
    forge.update_pr(repo, 4, {"title": "t"})
    forge.get_if_changed(f"repos/{full}/actions/runs")
    assert [argv[:4] for argv in asked] == [["gh", "api", "--hostname", "github.example.test"]] * 3
    assert asked[0][4:] == [f"repos/{full}/pulls/4"] and asked[2][4:] == ["-i", f"repos/{full}/actions/runs"]
    assert forge.url(repo, 4) == f"https://github.example.test/{full}/pull/4"
    monkeypatch.setattr(subprocess, "run", lambda argv, **_kwargs: asked.append(argv) or _Done("diff"))
    assert forge.compare_diff(repo, "a", "b") == "diff" and forge.pr_diff(repo, 4) == "diff"
    assert asked[3][:5] == ["gh", "api", "--hostname", "github.example.test", f"repos/{full}/compare/a...b"]
    assert asked[4] == ["gh", "pr", "diff", "4", "--repo", f"github.example.test/{full}"]
    listed = []
    forge.list_prs(repo, "open", runner=lambda argv: listed.append(argv) or _Done("[]"))
    assert listed[0][3:5] == ["--repo", f"github.example.test/{full}"]
    hosts = egress.forge_hosts(pack)
    assert hosts[:2] == ["github.com", "github.example.test"]  # the pack's host is added; github.com is never taken out
    assert egress._http_write("curl -X POST https://github.example.test/api/v3/repos/x/y/pulls", hosts)
    assert egress._http_write("curl -X POST https://api.github.com/repos/x/y/pulls", hosts)
    assert not egress._http_write("curl https://github.example.test/api/v3/repos/x/y/pulls", hosts)


@pytest.mark.parametrize(
    "forge,said",
    [
        ({"kind": "nowhere"}, "forge.kind is one of"),
        ({"kind": 3}, "forge.kind is one of"),
        ({"host": "https://github.example.test"}, "forge.host is the forge's host name"),
        ({"host": ""}, "forge.host is the forge's host name"),
        ({"host": 4}, "forge.host is the forge's host name"),
    ],
)
def test_a_forge_kind_or_host_the_kernel_cannot_use_is_refused_at_load(tmp_path, forge, said):
    with pytest.raises(PackError, match=said):
        load(_copy(tmp_path, PACKS[0], forge))


def test_the_fence_keeps_the_built_in_hosts_for_a_pack_whose_forge_it_cannot_make():
    assert egress.forge_hosts({"forge": {"kind": "nowhere", "host": "forge.example.test"}}) == [
        "github.com",
        "forge.example.test",
    ]
    assert egress.forge_hosts({"forge": "broken"}) == ["github.com"] and egress.forge_hosts(None) == ["github.com"]
    assert forges.default_hosts() == ["github.com"]


def test_the_registry_knows_both_keys_and_their_defaults():
    assert pack_keys.default_of(pack_keys.find("forge.kind")) == forges.DEFAULT == "github"
    assert pack_keys.default_of(pack_keys.find("forge.host")) == "github.com"
    assert set(pack_keys.find("forge.kind")["enum"]) == set(forges.KINDS)
    assert json.dumps(sorted(forges.KINDS))
