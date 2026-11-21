# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""With signers named (COCKPIT_UPDATE_SIGNERS, or a tracked UPDATE-SIGNERS in the installed tree), an update is a tag one
of them signed and nothing else: the check offers only such a tag, the update moves to the furthest one or to the one
named, and an unsigned head, a plain tag and a tag signed with another key are refused with the reason. With no signers
named, nothing here applies and an update is the branch's head, as before."""

import importlib.util
import json
import os
import shutil
import subprocess

import pytest

from cockpitlib import self_update
from cockpitlib.cli import main
from cockpitlib.errors import CockpitError


def _beside(name):
    spec = importlib.util.spec_from_file_location(
        f"cockpit_tests_{name}", os.path.join(os.path.dirname(os.path.abspath(__file__)), "support", f"{name}.py")
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


git, install = _beside("update_kit").git, _beside("update_kit").install


def _key(folder, name) -> str:
    """A throwaway ssh signing key; the path of its private half."""
    path = os.path.join(str(folder), name)
    subprocess.run(
        ["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-C", f"{name}@example.test", "-f", path],
        check=True,
        capture_output=True,
    )
    return path


def _allowed(key: str, who: str = "release@example.test") -> str:
    return f"{who} {open(key + '.pub', encoding='utf-8').read().strip()}\n"


@pytest.fixture
def made(tmp_path, monkeypatch):
    if not shutil.which("ssh-keygen"):
        pytest.skip("ssh-keygen is not installed: the signed-update tests sign with real ssh keys")
    found = install(tmp_path)
    monkeypatch.setenv("COCKPIT_PLUGIN_ROOT", found["plugin"])
    monkeypatch.setattr(self_update, "_record_hermes_revision", lambda name, revision: "")
    keys = tmp_path / "keys"
    keys.mkdir()
    ours, theirs = _key(keys, "release"), _key(keys, "someone")
    signers = tmp_path / "allowed-signers"
    signers.write_text(_allowed(ours), encoding="utf-8")

    def tag(name, key=ours, commit="HEAD", sign=True) -> str:
        words = (
            ["-c", "gpg.format=ssh", "-c", f"user.signingkey={key}.pub", "tag", "-s", "-m", name, name, commit]
            if sign
            else ["tag", name, commit]
        )
        done = subprocess.run(
            ["git", "-C", found["seed"], *words],
            capture_output=True,
            text=True,
            check=False,
            env={**os.environ, "GIT_COMMITTER_NAME": "Dev", "GIT_COMMITTER_EMAIL": "dev@example.test"},
        )
        if done.returncode != 0:
            pytest.skip(f"this git cannot sign a tag with an ssh key: {done.stderr.strip()[-120:]}")
        git(found["seed"], "push", "-q", "origin", name)
        return git(found["seed"], "rev-parse", f"{name}^{{commit}}")

    return {**found, "tag": tag, "ours": ours, "theirs": theirs, "signers": str(signers), "tmp": tmp_path}


def _head(made) -> str:
    return git(made["plugin"], "rev-parse", "HEAD")


def _record() -> dict:
    return json.load(open(self_update._check_path(), encoding="utf-8"))


def test_a_tag_signed_by_an_allowed_signer_is_offered_and_applied_and_the_unsigned_head_beyond_it_is_not(
    env, made, monkeypatch
):
    monkeypatch.setenv("COCKPIT_UPDATE_SIGNERS", made["signers"])
    made["commit"]("one")
    release = made["commit"]("the release")
    assert made["tag"]("v1") == release
    beyond = made["commit"]("not released yet")
    seen = self_update.check(made["plugin"])["remote"]
    assert (seen["sha"], seen["behind"], seen["tag"], seen["unsigned_ahead"]) == (release, 2, "v1", 1)
    assert seen["signers"] == f"COCKPIT_UPDATE_SIGNERS={made['signers']}"
    assert "2 commit(s) behind" in self_update.inbox_row()["reason"]
    done = self_update.apply(made["plugin"], restart=False)
    assert done["changed"] is True and _head(made) == release != beyond
    record = _record()
    assert (record["sha"], record["behind"], record["tag"], record["unsigned_ahead"], record["previous"]) == (
        release,
        0,
        "",
        1,
        made["first"],
    )
    assert self_update.inbox_row() == {}
    # nothing signed is ahead now: an update is refused with the reason, and the checkout stays
    with pytest.raises(
        CockpitError,
        match="origin/master is 1 commit\\(s\\) ahead and none of them carries a tag signed by an allowed signer",
    ):
        self_update.apply(made["plugin"], restart=False)
    assert _head(made) == release and self_update.check(made["plugin"])["remote"]["behind"] == 0


def test_an_unsigned_head_a_plain_tag_and_a_tag_signed_with_another_key_are_not_offered_and_are_refused(
    env, made, monkeypatch, capsys
):
    monkeypatch.setenv("COCKPIT_UPDATE_SIGNERS", made["signers"])
    made["commit"]("one")
    made["tag"]("plain", sign=False)
    made["commit"]("two")
    made["tag"]("forged", key=made["theirs"])
    seen = self_update.check(made["plugin"])["remote"]
    assert (seen["sha"], seen["behind"], seen["tag"], seen["unsigned_ahead"]) == (
        made["first"],
        0,
        "",
        2,
    ) and self_update.inbox_row() == {}
    with pytest.raises(CockpitError) as refused:
        self_update.apply(made["plugin"], restart=False)
    said = str(refused.value)
    assert "2 commit(s) ahead and none of them carries a tag signed by an allowed signer" in said
    assert "forged: its signature is not one of an allowed signer" in said and "plain: it is not a signed tag" in said
    for name, why in (
        ("forged", "its signature is not one of an allowed signer"),
        ("plain", "it is not a signed tag"),
        ("absent", "it is not a signed tag"),
        (git(made["seed"], "rev-parse", "HEAD"), "it is not a signed tag"),
    ):
        assert main(["update", "apply", "--to", name, "--no-restart"]) == 1
        assert f"--to {name}: update refused, {why}" in capsys.readouterr().err
    assert _head(made) == made["first"]


def test_a_named_signed_tag_is_where_the_update_stops_and_the_record_counts_the_signed_tag_beyond(
    env, made, monkeypatch, capsys
):
    monkeypatch.setenv("COCKPIT_UPDATE_SIGNERS", made["signers"])
    first_release = made["commit"]("one")
    made["tag"]("v1")
    made["commit"]("two")
    second_release = made["commit"]("three")
    made["tag"]("v2")
    assert self_update.check(made["plugin"])["remote"]["tag"] == "v2"
    assert main(["update", "apply", "--to", "v1", "--no-restart"]) == 0
    assert json.loads(capsys.readouterr().out)["to"] == first_release[:7] and _head(made) == first_release
    seen = self_update.status(made["plugin"])["remote"]
    assert (seen["sha"], seen["behind"], seen["tag"], seen["unsigned_ahead"]) == (second_release, 2, "v2", 0)
    assert self_update.apply(made["plugin"], restart=False)["changed"] is True and _head(made) == second_release
    # nothing ahead at all: already up to date, as without signers
    again = self_update.apply(made["plugin"], restart=False)
    assert again["changed"] is False and again["out"] == "already up to date"


def test_the_installed_trees_own_signers_file_counts_and_a_candidate_cannot_vouch_for_itself(env, made):
    plugin = made["plugin"]
    assert self_update._signers(plugin) is None
    made["commit"]("signers are named from here on", {"UPDATE-SIGNERS": _allowed(made["ours"])})
    self_update.apply(plugin, restart=False)  # no signers yet: the head, as it always was
    signers = self_update._signers(plugin)
    assert signers["kind"] == "ssh" and signers["source"] == "UPDATE-SIGNERS of the installed commit"
    assert (
        signers["path"] == os.path.join(plugin, ".git", "cockpit-update-signers")
        and git(plugin, "status", "--porcelain") == ""
    )
    installed = _head(made)
    # a commit that swaps the signers for its author's key and signs itself with it
    made["commit"]("mine now", {"UPDATE-SIGNERS": _allowed(made["theirs"], "someone@example.test")})
    made["tag"]("takeover", key=made["theirs"])
    assert self_update.check(plugin)["remote"]["behind"] == 0
    with pytest.raises(CockpitError, match="takeover: its signature is not one of an allowed signer"):
        self_update.apply(plugin, restart=False)
    assert _head(made) == installed
    # the same change signed by the signer the installed tree names is an update; from then on the new file counts
    handed_over = made["tag"]("handover")
    assert self_update.apply(plugin, restart=False)["changed"] is True and _head(made) == handed_over
    made["commit"]("their release")
    theirs = made["tag"]("v9", key=made["theirs"])
    assert self_update.apply(plugin, restart=False)["changed"] is True and _head(made) == theirs


def test_signers_named_in_the_environment_that_are_not_there_refuse_every_update(env, made, monkeypatch):
    made["commit"]("one")
    monkeypatch.setenv("COCKPIT_UPDATE_SIGNERS", str(made["tmp"] / "no-such-file"))
    for act in (lambda: self_update.check(made["plugin"]), lambda: self_update.apply(made["plugin"], restart=False)):
        with pytest.raises(
            CockpitError,
            match="neither a file of allowed signers nor a keyring folder: no update is offered or applied",
        ):
            act()
    assert _head(made) == made["first"]


def test_a_keyring_folder_admits_a_tag_signed_with_one_of_its_keys_and_no_ssh_signature(env, made, monkeypatch):
    if not shutil.which("gpg"):
        pytest.skip("gpg is not installed: the keyring mode signs with a real key")
    home = made["tmp"] / "g"
    home.mkdir(mode=0o700)
    monkeypatch.setenv("GNUPGHOME", str(home))
    made_key = subprocess.run(
        [
            "gpg",
            "--batch",
            "--pinentry-mode",
            "loopback",
            "--passphrase",
            "",
            "--quick-generate-key",
            "Release <release@example.test>",
            "ed25519",
            "sign",
            "never",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if made_key.returncode != 0:
        pytest.skip(f"gpg could not make a key here: {made_key.stderr.strip()[-120:]}")
    monkeypatch.setenv("COCKPIT_UPDATE_SIGNERS", str(home))
    made["commit"]("one")
    made["tag"]("ssh-signed")  # a good ssh signature is no PGP signature
    release = made["commit"]("two")
    git(made["seed"], "-c", "user.signingkey=release@example.test", "tag", "-s", "-m", "v1", "v1")
    git(made["seed"], "push", "-q", "origin", "v1")
    assert self_update._signers(made["plugin"])["kind"] == "gpg"
    seen = self_update.check(made["plugin"])["remote"]
    assert (seen["sha"], seen["tag"]) == (release, "v1")
    assert self_update._verify_tag(made["plugin"], "ssh-signed", self_update._signers(made["plugin"])).startswith(
        "its signature is not one of an allowed signer"
    )
    assert self_update.apply(made["plugin"], restart=False)["changed"] is True and _head(made) == release
    # and the other way round: with ssh signers, the PGP-signed tag verifies against nothing
    monkeypatch.setenv("COCKPIT_UPDATE_SIGNERS", made["signers"])
    assert self_update._verify_tag(made["plugin"], "v1", self_update._signers(made["plugin"])).startswith(
        "its signature is not one of an allowed signer"
    )
    assert self_update._verify_tag(made["plugin"], "ssh-signed", self_update._signers(made["plugin"])) == ""


def test_with_no_signers_named_an_update_is_the_branchs_head_and_the_record_says_nothing_of_tags(env, made):
    made["commit"]("one")
    made["tag"]("forged", key=made["theirs"])
    head = made["commit"]("two")
    seen = self_update.check(made["plugin"])["remote"]
    assert (seen["sha"], seen["behind"]) == (head, 2) and not {"tag", "unsigned_ahead", "signers"} & set(seen)
    assert self_update.apply(made["plugin"], restart=False)["changed"] is True and _head(made) == head
    assert not {"tag", "unsigned_ahead", "signers"} & set(_record())
