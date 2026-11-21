# Dependencies and their licences

The project is distributed under AGPL-3.0-or-later. This page lists every package it depends on, with its licence, and
says which licences a dependency may have. It is a record of what the packages declare, not legal advice.

Two kinds of dependency:

- **Distributed with the project**: code copied into a file of this repository. Today that is the terminal widget
  inside the Desktop bundle, and nothing else. [THIRD-PARTY-NOTICES.md](../../THIRD-PARTY-NOTICES.md) names it with its
  copyright and licence text.
- **Required at install time**: packages the installer fetches from a package index (`requirements.lock`,
  `requirements-test.lock`, `desktop/package-lock.json`). They are not copied here; the lists below name them.
- **Tools that read the code**: the linter and the type checker (`requirements-dev.lock`). `scripts/check` and CI run
  them; the project never imports them and a user of it never installs them.

## Licences a dependency may have

| Licence (SPDX) | May be distributed as part of a work under AGPL-3.0-or-later |
|---|---|
| `MIT`, `ISC`, `0BSD` | yes, keeping the copyright and permission notice |
| `BSD-2-Clause`, `BSD-3-Clause` | yes, keeping the notice |
| `Apache-2.0` | yes (compatible with version 3 of the GNU licences), keeping its notices |
| `PSF-2.0`, `Python-2.0` | yes, keeping the notice |

A package that offers a choice (`Apache-2.0 OR BSD-2-Clause`) passes when one of the choices is on the list.
`tests/test_every_locked_dependency_has_a_licence_the_project_can_ship_with.py` reads the licence of every locked
package from what is installed and fails on one outside the list. Anything else needs the owner's decision and an
entry among the exceptions below, with the reason.

## Exceptions, each reviewed

| Package | Licence | Why it is accepted |
|---|---|---|
| `certifi` | MPL-2.0 | Installed only for the tests (the HTTP client the test client speaks through brings it), never imported by the project and never distributed with it. The Free Software Foundation's licence list names MPL-2.0 as compatible with version 3 of the GNU licences; the owner should confirm this entry. |
| `pathspec` | MPL-2.0 | Installed only with the type checker, which reads ignore patterns through it: a tool that is run on the code, never imported by the project and never distributed with it. The same licence and the same reasoning as `certifi` above; the owner should confirm this entry. |

## Python packages

From `requirements.lock` (run time), `requirements-test.lock` (run time and tests) and `requirements-dev.lock` (the
tools, which also use `typing-extensions`). None is distributed with the
project.

| Package | Licence | Used |
|---|---|---|
| `annotated-doc` | MIT | run time |
| `annotated-types` | MIT | run time |
| `anyio` | MIT | run time |
| `ast-serialize` | MIT | tools only |
| `attrs` | MIT | tests only |
| `certifi` | MPL-2.0 | tests only |
| `coverage` | Apache-2.0 | tests only |
| `execnet` | MIT | tests only |
| `fastapi` | MIT | run time |
| `h11` | MIT | tests only |
| `httpcore` | BSD-3-Clause | tests only |
| `httpx` | BSD-3-Clause | tests only |
| `idna` | BSD-3-Clause | run time |
| `iniconfig` | MIT | tests only |
| `jsonschema` | MIT | tests only |
| `jsonschema-specifications` | MIT | tests only |
| `librt` | MIT | tools only |
| `mypy` | MIT | tools only |
| `mypy-extensions` | MIT | tools only |
| `opentelemetry-api` | Apache-2.0 | run time |
| `packaging` | Apache-2.0 OR BSD-2-Clause | tests only |
| `pathspec` | MPL-2.0 | tools only |
| `pluggy` | MIT | tests only |
| `pydantic` | MIT | run time |
| `pydantic-core` | MIT | run time |
| `pygments` | BSD-2-Clause | tests only |
| `pytest` | MIT | tests only |
| `pytest-cov` | MIT | tests only |
| `pytest-xdist` | MIT | tests only |
| `pyyaml` | MIT | run time |
| `referencing` | MIT | tests only |
| `rpds-py` | MIT | tests only |
| `ruff` | MIT | tools only |
| `starlette` | BSD-3-Clause | run time |
| `typing-extensions` | PSF-2.0 | run time |
| `typing-inspection` | MIT | run time |

## Packages of the Desktop page

From `desktop/package-lock.json`. Only the two bundled packages are distributed; React is provided by the Desktop at
run time and is installed here for the tests.

| Package | Licence | Used |
|---|---|---|
| `@xterm/addon-fit` | MIT | bundled into `desktop/plugin.js` |
| `@xterm/xterm` | MIT | bundled into `desktop/plugin.js` |
| `esbuild` | MIT | build and tests |
| `js-tokens` | MIT | build and tests (transitive) |
| `loose-envify` | MIT | build and tests (transitive) |
| `react` | MIT | build and tests |
| `react-dom` | MIT | build and tests |
| `scheduler` | MIT | build and tests (transitive) |
| `@esbuild/*` (one per platform, optional) | MIT | build (the bundler's program) |

## After a change to a dependency

Run `scripts/lock` (Python; `scripts/lock --dev` writes the tools' lock alone) or `npm install` in `desktop/` (the
page), correct the tables above, and run
`scripts/check --quick`: the structure test names a package whose licence is not on the list or whose row here is
missing or stale. A new dependency also needs a proposal (`docs/proposals/`).
