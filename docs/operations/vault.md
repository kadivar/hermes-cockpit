# The vault

Where the lanes' test logins live, how the key is protected, and how to back it up and restore it.

## The key

Lane logins live in the Hermes vault (`hermes vault add`). The browser fill reads that vault. The file it cannot lose is
`~/.hermes/vault/vault.key`: `vault.json.enc` is useless without it. Cockpit does not put that plaintext key in git. It
wraps a copy to a GPG **public** key as `~/.hermes/vault/vault.key.gpg`. The matching **private** key is only for unwrap
and restore. Init, a later wrap, and `cockpit vault put` encrypt with the public key and do not ask for the private key.

`cockpit setup` seals when this machine has one public key, or when `git config --global user.signingkey` names one of
them. It does not invent a key. No public key prints `vault init pending` and setup continues. Several public keys need an
explicit fingerprint. Import the public key (the private key can stay offline), then:

```sh
cockpit vault init --key <fingerprint>
```

The same fingerprint a second time does nothing, except to wrap `vault.key` when Hermes has created or replaced it since
the last wrap. A different fingerprint re-wraps. `cockpit doctor` is red, and the weekly `export` cron posts an Inbox row,
when a public key or a vault file is present and the wrap is missing. That is the reminder before a deleted `vault.key`
becomes unrecoverable.

## Backup and restore

The weekly export (`cockpit export --keep 4`) copies `vault.key.gpg`, `vault.json.enc`, the login entries, and
`recipient` into `~/.hermes/backups/vault/<stamp>/`. That directory is outside the workspace, so `workspace-watch` cannot
commit a credential. The export never copies the plaintext `vault.key`. Each stamp includes `RESTORE.txt`. Restore the
newest stamp, and unwrap when the private key is on this machine:

```sh
cockpit vault restore
```

Passwords are not written into the workspace. `cockpit vault list` prints origin and email and never the secret. The
agent sees those two fields. Reading a stored secret, or unwrapping `vault.key`, needs the private key.

`cockpit vault import` reads logins as neutral JSON lines on standard input and keeps a login the seat store already
holds.

## The Vault page

The Desktop's **Vault** tab, before Settings, is the human's credential manager over the same store.

- **Vaults.** A vault is a folder under `~/.hermes/vault/scopes/`. The pack's `logins.scope` (the lane logins, copied to
  the seats that own or read them) and `privileged.scope` (human only) are built in. Any other vault is the human's own:
  create, rename and delete it freely. Its logins never reach a seat, and the lookups the lanes use never read it.
- **Records.** A record is a login (URL, username, password, an optional 2FA key), an API key, or a secure note. Each has
  a title, tags and notes.
  - A changed secret keeps the last 10 it replaced.
  - Each vault keeps a plaintext `index.json` of what its records are, never a value, so the list opens without the
    private key.
  - A value leaves only through Show or Copy (`POST /vault-reveal`, human only) and hides again after 30 seconds.
  - `vault/audit.log` records every reveal and change, without the value.
- **Deletes.** A deleted record's file becomes a sealed tombstone, so file numbers stay dense for any kernel that counts
  them.
- **Unknown fields.** A field an older kernel wrote (a `label`, say) is kept through every rewrite.
- **Older single-file store.** Logins still in `cockpit-vault.json.gpg` move into the vaults with **Re-read vault**
  (`cockpit vault reindex`).

## The key never prompts on its own

Every read the page makes runs with `--pinentry-mode error`. It reads a file by itself only when the key opens with
nobody at the keyboard: no passphrase, or one gpg-agent already caches. The paths the lanes use are not changed by this.

- **Passphrase key.** **Unlock** hands the passphrase to gpg once over loopback, and gpg-agent caches it for its own
  `default-cache-ttl` / `max-cache-ttl`. Cockpit stores nothing. **Lock** clears the cache. In a terminal,
  `cockpit vault unlock` lets gpg-agent's own pinentry ask instead. Use that when the agent refuses loopback
  (`no-allow-loopback-pinentry`).
- **Security key.** It is never used in the background. **Enter PIN** verifies the PIN once, and Show, Edit, Move or
  Re-read may each wait up to 45 seconds for its touch. **Lock** resets the card.
- **No private key on this machine.** The list, adding and deleting still work. Show and Edit say why they cannot.

`cockpit vault status | unlock | lock | scopes | rm <origin> <email> | reindex` cover the same from a terminal.

## The lanes' own reads never prompt either

Some reads happen without anyone asking: secret masking on a lane's tool call, the demo and session cards' 20-second
refresh, the housekeeping seat audit and lend returns, account renewal, and upload scanning.

- When the key would ask for a passphrase, or is on a security key, those reads are skipped and the caller sees "locked"
  at once. Masking keeps the secrets it learned when each was stored. The demo card falls back to the seat stores.
  Housekeeping reports the step as locked, not failed.
- A key without a passphrase, or one gpg-agent already caches, reads as before (`--pinentry-mode error` only stops a
  prompt that cannot be answered).
- Acts a human starts may let gpg-agent ask: saving a staging login, Approve on a privileged lend, New password on the
  demo card, and any `cockpit` command typed at a terminal (not one run by a lane or a cron).

## The declared accounts

A pack may declare the test accounts the vault should hold and a command that makes and renews them:
[customize/accounts-command.md](../customize/accounts-command.md).

See [security.md](../security.md#secrets) for what the masking does and does not catch.
