# The accounts command

## Goal

The staging test accounts the lanes sign in with are declared once, made and renewed by a command of yours, and placed
in the vault of the seat that owns or reads each one. No password is written down or passed on a command line.

## The pack lines

In `pack.yaml`:

```yaml
logins:
  accounts: accounts.yaml        # the manifest, absolute or beside pack.yaml
```

In that manifest:

```yaml
command: [bin/accounts]
verify_command: true             # a verify also asks the command to check each account
accounts:
  - origin: https://app.example.test
    identifier: qa-one@example.test
    owner: tester-1              # the one lane that holds it
    renew_days: 30
  - origin: https://app.example.test
    identifier: reviewer@example.test
    readers: [reviewer]          # the seat kinds or lanes that read it
    totp: true
```

An account has `origin` and `identifier`, and an `owner` or `readers`, not both. `totp` says it needs a one-time-code
secret. `renew_days` is how long a password stands (0, the default, is never). An account listed twice is refused.

## The script contract

Implemented in `kernel/cockpitlib/accounts.py` (`_run_command`).

- **Arguments:** the command as written. Nothing is added: the action is in the environment. A relative first word
  with a `/` is a file beside the manifest.
- **Environment:** the caller's, plus
  - `COCKPIT_ACCOUNT_ACTION`: `create`, `renew` or `verify`;
  - `COCKPIT_ACCOUNT_ORIGIN`, `COCKPIT_ACCOUNT_IDENTIFIER`, and `COCKPIT_ACCOUNT_OWNER` (empty for a shared account).
- **Standard input:** none is written.
- **Standard output:** one JSON object with `password`, and `otp_secret` when the account has `totp: true`. This holds
  for `verify` too. The output is stored in the vault and never printed, logged or echoed in an error.
- **Standard error:** on failure, its last 200 characters are reported. Do not print a secret there.
- **Exit codes:** 0 is success. Anything else fails that account
  (`accounts <action> <identifier> failed: exit <n> ...`). Output without JSON or without a password fails it too.
- **Time limit:** 300 seconds.
- **State:** when each account was made and renewed, in `<records>/watch/accounts.json`. No secret is in it.

## A copy-paste example

`bin/accounts` beside the manifest (make it executable). It only invents a password; a real one
calls your staging environment's own account API, with a credential from its own environment:

```python
#!/usr/bin/env python3
"""Make, renew or check one staging account: the action and the account in the environment, the secret as JSON."""
import json
import os
import secrets
import sys

action = os.environ.get("COCKPIT_ACCOUNT_ACTION", "")
origin = os.environ.get("COCKPIT_ACCOUNT_ORIGIN", "")
identifier = os.environ.get("COCKPIT_ACCOUNT_IDENTIFIER", "")
if action not in ("create", "renew", "verify") or not origin or not identifier:
    print("needs COCKPIT_ACCOUNT_ACTION, COCKPIT_ACCOUNT_ORIGIN and COCKPIT_ACCOUNT_IDENTIFIER", file=sys.stderr)
    sys.exit(1)
# here: call the staging environment to create the account or set its password
answer = {"password": secrets.token_urlsafe(18)}
if os.environ.get("EXAMPLE_ACCOUNT_TOTP"):
    answer["otp_secret"] = "JBSWY3DPEHPK3PXP"
print(json.dumps(answer))
```

## How to test it

Run the script as the kernel would, and look only at the shape of what it prints:

```sh
COCKPIT_ACCOUNT_ACTION=create COCKPIT_ACCOUNT_ORIGIN=https://app.example.test \
  COCKPIT_ACCOUNT_IDENTIFIER=qa-one@example.test bin/accounts | python3 -c 'import json,sys; print(sorted(json.load(sys.stdin)))'
# ['password']
```

Then, in your own terminal (an editor assistant's session is refused vault commands by the editor fence):

```sh
cockpit pack check
cockpit vault accounts plan          # add / place / renew / ok, per account; changes nothing
cockpit vault accounts apply         # makes what is missing and places what moved
cockpit vault accounts verify        # exit 1 when an account is missing, misplaced or fails the command's check
cockpit vault accounts renew         # renews what is due by renew_days; --force renews all
cockpit vault accounts list
```

The vault itself: [operations/vault.md](../operations/vault.md).
