# Security policy

## Reporting a vulnerability

Report it privately, through **GitHub private vulnerability reporting** on this repository: the **Security** tab, then
**Report a vulnerability**.

Do not open a public pull request or a public discussion for a vulnerability, and do not put the details in a commit
message. A public report gives everyone who runs cockpit the problem before they have the fix.

Useful in a report: the version or commit, what an agent or a pack can do that it should not, the smallest steps that
show it, and which [invariant](docs/security.md#invariants) it breaks, if one.

## What to expect

- An acknowledgement of your report. This project has one maintainer, so allow a few working days.
- An assessment against the security model in [docs/security.md](docs/security.md), and a fix developed in private.
- A release that carries the fix, with the change described in [CHANGELOG.md](CHANGELOG.md) under *Security*, and credit
  to you unless you prefer none.

## Supported versions

Only the latest release is supported. A fix lands there; there are no backports.

## Scope

[docs/security.md](docs/security.md) states what cockpit protects and where the protection ends. In short: the outbox,
the gatekeeper and the human's click gate every outward act the kernel offers, and the egress hook refuses the known
other paths. Lanes run as the installing user, so the gate and the fence are not a sandbox. A report that a hostile
program running as that user can act as that user describes the documented boundary, not a vulnerability. A report that
a lane can publish, that a pack can remove a kernel deny, that the hook fails open, or that a stored secret reaches a
command line, a log or a tool result, describes one.
