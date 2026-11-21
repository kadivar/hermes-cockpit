# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Nobody asked, nothing prompts: the older vault readers (masking, the demo card, the seat audit, account renewal,
lends, upload scanning) never ask for a passphrase or wait for a security key; a human act may."""

import pytest

from cockpitlib import vault
from cockpitlib.errors import CockpitError
from cockpitlib.vault_key import VaultKey, VaultLocked, at_terminal, forget_state, human_present, is_human, quiet_gate
from tests.test_vaultkey import PASSPHRASE, locked_book  # noqa: F401  (the fixture)


def spy(monkeypatch):
    calls = []
    real = vault._gpg

    def recording(args, data=b""):
        calls.append(list(args))
        return real(args, data)

    monkeypatch.setattr(vault, "_gpg", recording)
    return calls


def decrypts(calls):
    return [args for args in calls if "--decrypt" in args]


def test_a_locked_passphrase_key_is_never_used_by_what_nobody_asked_for(locked_book, monkeypatch):  # noqa: F811
    from cockpitlib import scrub
    from cockpitlib.housekeeping import _locked
    from cockpitlib.lend import take_back
    from cockpitlib.vault import _items, human_secret, store_login
    from dashboard.cockpit.routes.pages import _vault_secret

    store_login(
        "https://lab.test", "qa@lab.test", "lane-pass-1", pack=locked_book.pack
    )  # a write needs only the public key
    forget_state()
    calls = spy(monkeypatch)
    index = scrub.rebuild()
    gpg = next(source for source in index["sources"] if source["source"] == "gpg")
    assert gpg["locked"] is True and gpg["entries"], "masking keeps what it learned at the write and says it is locked"
    assert human_secret("https://lab.test", "qa@lab.test", pack=locked_book.pack) == ""
    assert take_back() == [] and _vault_secret("lane-pass-1 in a file") is False
    with pytest.raises(VaultLocked, match="unlock it on the Vault page") as stopped:
        _items()
    assert stopped.value.needs == "passphrase" and _locked(stopped.value)
    assert decrypts(calls) == [], "gpg never ran a decrypt nobody asked for"
    # a human act lets gpg-agent ask (here the agent's pinentry is /bin/false, so it fails at once)
    path = vault._entry_paths()[0]
    with human_present():
        assert is_human()
        with pytest.raises(CockpitError):
            vault._decrypt(path)
    assert not is_human() and decrypts(calls) == [["--decrypt", path]]
    # unlocked, the same quiet readers work and never start a pinentry
    VaultKey().unlock(PASSPHRASE)
    calls.clear()
    assert _items()[0]["secret"] == "lane-pass-1"
    assert human_secret("https://lab.test", "qa@lab.test", pack=locked_book.pack) == "lane-pass-1"
    assert decrypts(calls) and all(args[:3] == ["--pinentry-mode", "error", "--decrypt"] for args in decrypts(calls))
    VaultKey().lock()
    with pytest.raises(VaultLocked):
        _items()


def test_a_security_key_is_left_alone_unless_a_human_asks(env, monkeypatch):
    from tests.test_vault import seal_ephemeral

    seal_ephemeral(monkeypatch, str(env["home"]))
    vault.store_login("https://lab.test", "qa@lab.test", "lane-pass-1")
    monkeypatch.setattr(
        "cockpitlib.vault_key._cached_state", lambda: {"secret": "card", "protected": False, "cached": False}
    )
    calls = spy(monkeypatch)
    with pytest.raises(VaultLocked, match="security key") as stopped:
        vault._items()
    assert stopped.value.needs == "card" and decrypts(calls) == []
    assert vault.human_secret("https://lab.test", "qa@lab.test") == ""
    with human_present():
        assert vault._items()[0]["secret"] == "lane-pass-1"  # a human act may wait for the touch
    assert decrypts(calls) and decrypts(calls)[0][0] == "--decrypt"


def test_the_gate_asks_gpg_agent_at_most_every_few_seconds_and_forgets_on_unlock_and_lock(env, monkeypatch):
    from cockpitlib import vault_key
    from tests.test_vault import seal_ephemeral

    seal_ephemeral(monkeypatch, str(env["home"]))
    asked = []
    monkeypatch.setattr(
        VaultKey, "state", lambda self: asked.append(1) or {"secret": "disk", "protected": False, "cached": False}
    )
    clock = [100.0]
    monkeypatch.setattr(vault_key.time, "monotonic", lambda: clock[0])
    forget_state()
    quiet_gate()
    quiet_gate()
    assert len(asked) == 1
    clock[0] += vault_key.STATE_SECONDS + 1
    quiet_gate()
    assert len(asked) == 2
    forget_state()
    quiet_gate()
    assert len(asked) == 3
    monkeypatch.setattr(VaultKey, "state", lambda self: (_ for _ in ()).throw(ValueError("odd output")))
    forget_state()
    quiet_gate()  # a state it cannot read never blocks: gpg answers for itself, as before


def test_a_person_at_a_terminal_counts_as_present_a_lane_or_a_cron_never(bare, monkeypatch, capsys):
    from cockpitlib.cli import main

    monkeypatch.setattr("cockpitlib.vault_key.os.isatty", lambda fd: True)
    monkeypatch.delenv("COCKPIT_LANE", raising=False)
    assert at_terminal()
    monkeypatch.setenv("COCKPIT_LANE", "tester-1")
    assert not at_terminal()
    monkeypatch.delenv("COCKPIT_LANE")
    seen = []
    monkeypatch.setattr(
        "cockpitlib.vault_book.VaultBook.state",
        lambda self: (
            seen.append(is_human())
            or {
                "sealed": False,
                "locked": True,
                "reason": "",
                "key": {"secret": "none", "protected": False, "cached": False},
            }
        ),
    )
    assert main(["vault", "status"]) == 0
    monkeypatch.setattr("cockpitlib.vault_key.os.isatty", lambda fd: (_ for _ in ()).throw(OSError("closed")))
    assert not at_terminal()
    assert main(["vault", "status"]) == 0
    assert seen == [True, False] and not is_human()


def test_the_human_acts_on_the_page_may_ask_for_the_key(bare, monkeypatch):
    from tests.test_routes import _client

    seen = []
    monkeypatch.setattr("cockpitlib.lend.approve", lambda *a, **k: seen.append(("approve", is_human())) or "lent")
    monkeypatch.setattr(
        "cockpitlib.ops.vault_put", lambda *a, **k: seen.append(("login", is_human())) or "vault stored"
    )
    client = _client()
    assert client.post("/privileged-approve", json={"card": "t_1", "lane": "tester-1"}).json()["out"] == "lent"
    assert (
        client.post(
            "/staging-credentials", json={"email": "qa@acme.test", "password": "pw-123456", "lane": "tester-1"}
        ).status_code
        == 200
    )
    assert seen == [("approve", True), ("login", True)] and not is_human()
