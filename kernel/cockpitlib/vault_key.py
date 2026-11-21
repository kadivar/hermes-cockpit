# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The private key that opens cockpit's vault, as the human's vault book sees it.

The book never prompts: every decrypt it makes runs with ``--pinentry-mode error`` and a timeout, and only when the
key opens without anyone at the keyboard (no passphrase, or one gpg-agent already caches). Opening it is an explicit
human act: the Desktop's Unlock (the passphrase or the card's PIN, handed to gpg once over loopback), or
``cockpit vault unlock`` in a terminal (gpg-agent's own pinentry: pinentry-mac, a card's PIN entry, its touch).
gpg-agent keeps the passphrase under the user's own cache times; cockpit never stores it. Lock clears that cache.

The older read path (``vault._decrypt``: secret masking, the demo card, the seat audit, account renewal, lends) is
quiet too unless a human asked for it (``human_present``): a key that would ask for a passphrase or a security key is
not used there, and the caller sees ``VaultLocked`` at once instead of a dialog or a blinking key. A key without a
passphrase, or one gpg-agent caches, reads exactly as before.
"""

import contextlib
import contextvars
import os
import secrets
import subprocess
import time

from .errors import CockpitError

TIMEOUT = 45  # seconds a decrypt may wait, a card's touch included
CODES = {  # gpg-error codes (low 16 bits of pkdecrypt_failed) -> what the human reads, and what it needs
    11: ("wrong passphrase", "passphrase"),
    85: ("the vault key is locked: unlock it first", "unlock"),
    62: ("the security key was not touched in time", "touch"),
    87: ("wrong PIN", "pin"),
    99: ("cancelled", "unlock"),
    108: ("the security key answered with an error", "card"),
    110: ("the security key was removed", "card"),
    112: ("the security key is not plugged in", "card"),
    60: (
        "gpg-agent does not accept a passphrase from cockpit (no-allow-loopback-pinentry): run cockpit vault unlock in a terminal",
        "terminal",
    ),
}


class VaultLocked(CockpitError):
    """The key did not open. `needs` says what would open it."""

    def __init__(self, message: str, needs: str = "unlock"):
        super().__init__(message)
        self.needs = needs


_HUMAN = contextvars.ContextVar("cockpit_vault_human", default=False)
_STATE = {}  # (GNUPGHOME, fingerprint) -> (when, state): the gate asks gpg-agent at most every few seconds
STATE_SECONDS = 5


@contextlib.contextmanager
def human_present(present: bool = True):
    """A human asked for this act (a Desktop button, a terminal): the key may ask them for its passphrase or touch."""
    token = _HUMAN.set(bool(present))
    try:
        yield
    finally:
        _HUMAN.reset(token)


def is_human() -> bool:
    return _HUMAN.get()


def at_terminal() -> bool:
    """A person at a terminal, not a lane: stdin is a TTY and no lane runs this process."""
    try:
        return bool(os.isatty(0)) and not os.environ.get("COCKPIT_LANE")
    except OSError:
        return False


def _cached_state() -> dict:
    from .vault import sealed_to

    key = (os.environ.get("GNUPGHOME", ""), sealed_to())
    found = _STATE.get(key)
    if found and time.monotonic() - found[0] < STATE_SECONDS:
        return found[1]
    state = VaultKey().state()
    _STATE[key] = (time.monotonic(), state)
    return state


def forget_state() -> None:
    _STATE.clear()


def quiet_gate() -> None:
    """Before a decrypt nobody asked for: refuse a key that would prompt for its passphrase or wait for a security key.
    A missing key or an unsealed vault passes: gpg fails at once there, as it always did. So does a key whose state
    cannot be read: the gate refuses only what it knows would prompt, and never adds a failure of its own."""
    try:
        state = _cached_state()
    except (OSError, ValueError):
        return
    if state["secret"] == "card":
        raise VaultLocked(
            "the vault key is on a security key: it is used only when you ask (the Vault page, or cockpit vault unlock)",
            "card",
        )
    if state["secret"] == "disk" and state["protected"] and not state["cached"]:
        raise VaultLocked(
            "the vault key is locked: unlock it on the Vault page or with cockpit vault unlock", "passphrase"
        )


class VaultKey:
    """The recipient's secret key: where it lives, whether it is cached, and the three acts on it."""

    def __init__(self, runner=None):
        self.runner = runner or self._run

    # --- the processes

    @staticmethod
    def _run(args, data: bytes = b"", timeout: float = 20) -> subprocess.CompletedProcess:
        try:
            return subprocess.run(args, input=data, capture_output=True, check=False, timeout=timeout)
        except subprocess.TimeoutExpired:
            return subprocess.CompletedProcess(args, 124, b"", b"[GNUPG:] ERROR pkdecrypt_failed 62\n")
        except OSError as exc:
            return subprocess.CompletedProcess(args, 127, b"", str(exc).encode())

    def _gpg(self, args, data: bytes = b"", timeout: float = 20):
        return self.runner(["gpg", "--batch", "--yes", "--trust-model", "always", *args], data, timeout)

    def _agent(self, command: str) -> str:
        result = self.runner(["gpg-connect-agent", command, "/bye"], b"", 10)
        return _text(result.stdout)

    # --- what the key is

    def fingerprint(self) -> str:
        from .vault import sealed_to

        return sealed_to()

    def _secret_subkey(self, fingerprint: str):
        """(keygrip, where) of the key that decrypts: the encryption subkey, else the primary. where: disk, card, none."""
        result = self._gpg(["--with-colons", "--with-keygrip", "--list-secret-keys", fingerprint])
        if result.returncode != 0:
            return "", "none"
        found, last = [], None
        for line in _text(result.stdout).splitlines():
            parts = line.split(":")
            if parts[0] in ("sec", "ssb"):
                last = {
                    "caps": parts[11] if len(parts) > 11 else "",
                    "token": parts[14] if len(parts) > 14 else "",
                    "kind": parts[0],
                }
                found.append(last)
            elif parts[0] == "grp" and last is not None and len(parts) > 9:
                last["grip"] = parts[9]
        usable = [key for key in found if key.get("grip") and key["token"] not in ("", "#")]
        chosen = next((key for key in usable if "e" in key["caps"].lower() and key["kind"] == "ssb"), None) or next(
            (key for key in usable if "e" in key["caps"].lower()), None
        )
        if chosen is None:
            return "", "none"
        return chosen["grip"], "disk" if chosen["token"] == "+" else "card"

    def ttl(self) -> dict:
        """gpg-agent's cache times, seconds: how long an unlock lasts without use, and at most."""
        found = {"idle": 600, "max": 7200}
        out = _text(self.runner(["gpgconf", "--list-options", "gpg-agent"], b"", 10).stdout)
        for line in out.splitlines():
            parts = line.split(":")
            if parts[0] in ("default-cache-ttl", "max-cache-ttl") and len(parts) > 9:
                value = parts[9] or parts[7]
                if value.isdigit():
                    found["idle" if parts[0] == "default-cache-ttl" else "max"] = int(value)
        return found

    def state(self) -> dict:
        """sealed, secret (none|disk|card), protected, cached, quiet (opens with nobody at the keyboard), needs."""
        fingerprint = self.fingerprint()
        state = {
            "sealed": bool(fingerprint),
            "fingerprint": fingerprint,
            "secret": "none",
            "protected": False,
            "cached": False,
            "quiet": False,
            "needs": "unsealed" if not fingerprint else "elsewhere",
        }
        if not fingerprint:
            return state
        grip, where = self._secret_subkey(fingerprint)
        state["secret"] = where
        if where == "none":
            return state
        info = self._agent(f"KEYINFO {grip}").split()
        # S KEYINFO <grip> <type> <serial> <idstr> <cached> <protection> ...
        cached = len(info) > 6 and info[6] == "1"
        protected = len(info) > 7 and info[7] == "P"
        state.update({"protected": protected, "cached": cached, "grip": grip})
        if where == "card":
            state["needs"] = "card"  # a card may want its PIN or a touch at any decrypt: never in the background
            return state
        state["quiet"] = not protected or cached
        state["needs"] = "" if state["quiet"] else "passphrase"
        return state

    # --- the acts

    def open(self, path: str, timeout: float = TIMEOUT) -> bytes:
        """Decrypt one file without ever prompting. A locked key raises VaultLocked."""
        result = self._gpg(["--status-fd", "2", "--pinentry-mode", "error", "--decrypt", path], b"", timeout)
        if result.returncode == 0:
            return result.stdout if isinstance(result.stdout, bytes) else _text(result.stdout).encode()
        raise _failure(_text(result.stderr))

    def probe(self) -> str:
        """A small sealed file with no secret in it: what unlock decrypts, so no record is opened to unlock."""
        from .vault import _encrypt, vault_dir

        path = os.path.join(vault_dir(), "probe.gpg")
        if not os.path.isfile(path):
            fingerprint = self.fingerprint()
            if not fingerprint:
                raise VaultLocked("the vault is not sealed. cockpit vault init --key <fingerprint>", "unsealed")
            _encrypt(fingerprint, ("cockpit probe " + secrets.token_hex(8)).encode(), path)
        return path

    def unlock(self, secret: str, timeout: float = TIMEOUT) -> str:
        """Hand the passphrase (or the card's PIN) to gpg once, over loopback; gpg-agent caches it. Nothing is kept here."""
        if not secret:
            raise VaultLocked("type the passphrase or the PIN", "passphrase")
        path = self.probe()
        # the probe's text goes to stdout and is dropped: GnuPG 2.5 writes --output through "<name>.part", and
        # "/dev/null.part" cannot be made ("error creating '/dev/null.part': Operation not permitted"), so no unlock worked
        result = self._gpg(
            ["--status-fd", "2", "--pinentry-mode", "loopback", "--passphrase-fd", "0", "--decrypt", path],
            (secret + "\n").encode(),
            timeout,
        )
        if result.returncode != 0:
            raise _failure(_text(result.stderr))
        forget_state()
        return "vault unlocked"

    def unlock_here(self) -> str:
        """The terminal's unlock: gpg-agent's own pinentry asks (passphrase, PIN, touch). For a machine where the Desktop
        cannot hand a passphrase over (loopback refused) or the human prefers the system prompt."""
        path = self.probe()
        result = subprocess.run(["gpg", "--yes", "--decrypt", path], stdout=subprocess.DEVNULL, check=False)
        if result.returncode != 0:
            raise VaultLocked("the vault key did not open", "unlock")
        forget_state()
        return "vault unlocked"

    def lock(self) -> str:
        """Forget the cached passphrase (a disk key) or the card's verified PIN."""
        forget_state()
        state = self.state()
        if state["secret"] == "card":
            self._agent("SCD RESET")
            return "vault locked: the security key asks for its PIN again"
        if state["secret"] == "disk" and state.get("grip"):
            self._agent(f"CLEAR_PASSPHRASE --mode=normal {state['grip']}")
            return (
                "vault locked" if state["protected"] else "vault key has no passphrase: it stays open on this machine"
            )
        return "nothing to lock: the private key is not on this machine"


def _text(value) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8", "replace")
    return value or ""


def _failure(status: str) -> VaultLocked:
    """What gpg's status lines say went wrong."""
    if "NO_SECKEY" in status and "pkdecrypt_failed" not in status:
        return VaultLocked("the private key is not on this machine: values stay closed here", "elsewhere")
    for line in status.splitlines():
        if "ERROR pkdecrypt_failed" in line:
            code = line.rsplit(" ", 1)[-1]
            if code.isdigit():
                message, needs = CODES.get(
                    int(code) & 0xFFFF, (f"the vault key did not open (gpg error {int(code) & 0xFFFF})", "unlock")
                )
                return VaultLocked(message, needs)
    if "NO_SECKEY" in status:
        return VaultLocked("the private key is not on this machine: values stay closed here", "elsewhere")
    return VaultLocked("the vault file could not be opened", "unlock")
