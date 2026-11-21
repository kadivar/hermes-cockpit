# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""What the pack's shipped repos build and run, read off their checkouts — never the network. Each reader in READERS is
{name, globs, parse(text, repo, rel) -> [component]}; the walk, the production rule, the dedupe and the fingerprint are
shared. A component: {kind: runtime|package|image|os, ecosystem, name, version, repo, where: "path:line", production,
dev}."""

import fnmatch
import hashlib
import json
import os
import re

from ..store import read_json, write_json
from ..time_util import iso

SKIP_DIRS = {".git", "node_modules", "vendor", "dist", "build", "storage", "coverage", ".venv", "__pycache__", "public"}
MAX_DEPTH = 4
OS_SUFFIXES = {"bookworm": "debian", "bullseye": "debian", "buster": "debian", "trixie": "debian", "alpine": "alpine"}
RUNTIME_IMAGES = {"php": "php", "node": "node"}  # a base image that names its runtime line: php:8.4-fpm is php 8.4
DEV_PATH_MARKERS = (".github/workflows/", "/ci/", "tests/", "test/", ".example")


def repos(pack) -> list:
    """(name, checkout) of every shipped repo whose checkout is on disk."""
    from ..pack import shipped
    from ..worktree import repo_source

    found = []
    for repo in pack["repos"]["repos"]:
        if not repo.get("name") or not shipped(repo):
            continue
        path = repo_source(pack, repo["name"])
        if os.path.isdir(path):
            found.append((repo["name"], path))
    return found


def is_production(rel: str, dev=False) -> bool:
    """Everything ships unless the reader knows better: a dev dependency, a CI workflow, a test or example path."""
    return not dev and not any(marker in "/" + rel for marker in DEV_PATH_MARKERS)


def component(kind, ecosystem, name, version, repo, where, dev=False) -> dict:
    return {
        "kind": kind,
        "ecosystem": ecosystem,
        "name": name,
        "version": str(version),
        "repo": repo,
        "where": where,
        "production": is_production(where.split(":")[0], dev),
        "dev": bool(dev),
    }


def _line_of(text: str, needle: str) -> int:
    index = text.find(needle)
    return text.count("\n", 0, index) + 1 if index >= 0 else 1


def _clean(version) -> str:
    version = str(version or "").strip()
    return version[1:] if re.match(r"^v\d", version) else version


def _tag_version(tag: str) -> str:
    """8.4-fpm-bookworm → 8.4; 22-alpine3.20 → 22; latest → latest."""
    found = re.match(r"v?(\d+(?:\.\d+)*)", tag or "")
    return found.group(1) if found else (tag or "latest")


def composer_lock(text, repo, rel) -> list:
    data = json.loads(text)
    return [
        component(
            "package",
            "composer",
            item["name"],
            _clean(item.get("version")),
            repo,
            f"{rel}:{_line_of(text, json.dumps(item['name']))}",
            dev,
        )
        for key, dev in (("packages", False), ("packages-dev", True))
        for item in data.get(key) or []
    ]


def composer_json(text, repo, rel) -> list:
    data = json.loads(text)
    found = []
    wanted = (data.get("require") or {}).get("php")
    version = re.search(r"\d+(?:\.\d+)*", wanted or "")
    if version:
        found.append(
            component("runtime", "php", "php", version.group(0), repo, f"{rel}:{_line_of(text, json.dumps('php'))}")
        )
    platform = ((data.get("config") or {}).get("platform") or {}).get("php")
    if platform:
        found.append(
            component(
                "runtime", "php", "php", _clean(platform), repo, f"{rel}:{_line_of(text, json.dumps('platform'))}"
            )
        )
    return found


def package_lock(text, repo, rel) -> list:
    data = json.loads(text)
    found = []
    packages = data.get("packages")
    if isinstance(packages, dict):
        for key, item in packages.items():
            if "node_modules/" not in key or not isinstance(item, dict) or not item.get("version"):
                continue
            found.append(
                component(
                    "package",
                    "npm",
                    key.rsplit("node_modules/", 1)[1],
                    _clean(item["version"]),
                    repo,
                    f"{rel}:{_line_of(text, json.dumps(key))}",
                    bool(item.get("dev")),
                )
            )
        return found

    def walk(deps):  # lockfile v1
        for name, item in (deps or {}).items():
            if isinstance(item, dict) and item.get("version"):
                found.append(
                    component(
                        "package",
                        "npm",
                        name,
                        _clean(item["version"]),
                        repo,
                        f"{rel}:{_line_of(text, json.dumps(name))}",
                        bool(item.get("dev")),
                    )
                )
                walk(item.get("dependencies"))

    walk(data.get("dependencies"))
    return found


def yarn_lock(text, repo, rel) -> list:
    """Yarn v1: a block per `name@range[, name@range]:` line, its `version "x"` below."""
    found = []
    name, line = "", 0
    for number, row in enumerate(text.splitlines(), 1):
        if row and not row.startswith((" ", "#")) and row.rstrip().endswith(":"):
            first = row.strip().rstrip(":").split(",")[0].strip().strip('"')
            name, line = first.rsplit("@", 1)[0] if first.rfind("@") > 0 else first, number
            continue
        version = re.match(r'^\s+version:?\s+"?([^"\s]+)"?', row)
        if version and name:
            found.append(component("package", "npm", name, _clean(version.group(1)), repo, f"{rel}:{line}"))
            name = ""
    return found


def pnpm_lock(text, repo, rel) -> list:
    """pnpm: `packages:` keys `/name@version` (v6) or `name@version` (v9), scoped names included."""
    import yaml

    data = yaml.safe_load(text) or {}
    found = []
    for key, item in (data.get("packages") or {}).items():
        spec = str(key).lstrip("/").split("(")[0]
        at = spec.rfind("@")
        if at <= 0:
            continue
        found.append(
            component(
                "package",
                "npm",
                spec[:at],
                _clean(spec[at + 1 :]),
                repo,
                f"{rel}:{_line_of(text, str(key))}",
                bool((item or {}).get("dev")) if isinstance(item, dict) else False,
            )
        )
    return found


def _images(image: str, repo: str, where: str) -> list:
    """name[:tag] → an image component, plus a runtime (php or node base) and an os (bookworm or alpine tag) one."""
    image = image.split("@", maxsplit=1)[0]
    name, _, tag = image.rpartition(":") if re.search(r":[^/]+$", image) else (image, "", "")
    for prefix in ("docker.io/", "library/"):
        name = name[len(prefix) :] if name.startswith(prefix) else name
    tag = tag or "latest"
    found = [component("image", "docker", name, tag, repo, where)]
    if name in RUNTIME_IMAGES and tag != "latest":
        found.append(component("runtime", RUNTIME_IMAGES[name], RUNTIME_IMAGES[name], _tag_version(tag), repo, where))
    for suffix, family in OS_SUFFIXES.items():
        version = re.search(rf"(?:^|-){suffix}(\d+(?:\.\d+)*)?(?:-|$)", tag)
        if version:
            found.append(component("os", family, family, version.group(1) or suffix, repo, where))
            break
    return found


def dockerfile(text, repo, rel) -> list:
    found, stages = [], set()
    for number, row in enumerate(text.splitlines(), 1):
        line = re.match(r"^\s*FROM\s+(?:--platform=\S+\s+)?(\S+)(?:\s+[Aa][Ss]\s+(\S+))?", row)
        if not line:
            continue
        image, alias = line.group(1), line.group(2)
        if alias:
            stages.add(alias.lower())
        if image.lower() in stages or image == "scratch":
            continue
        found.extend(_images(image, repo, f"{rel}:{number}"))
    return found


def compose(text, repo, rel) -> list:
    found = []
    for number, row in enumerate(text.splitlines(), 1):
        line = re.match(r"^\s*image:\s*[\"']?([^\"'\s#]+)", row)
        if line and "${" not in line.group(1):
            found.extend(_images(line.group(1), repo, f"{rel}:{number}"))
    return found


def workflow(text, repo, rel) -> list:
    """A CI workflow's container images and its node-version lines (never production: CI runs them, customers do not)."""
    found = []
    for number, row in enumerate(text.splitlines(), 1):
        node = re.match(r"^\s*node-version:\s*(.+?)\s*(#.*)?$", row)
        if node:
            found.extend(
                component("runtime", "node", "node", version, repo, f"{rel}:{number}")
                for version in re.findall(r"\d+(?:\.\d+)*", node.group(1))
            )
        image = re.match(r"^\s*(?:image|container):\s*[\"']?([a-z0-9][^\"'\s#{}]*:[^\"'\s#{}]+)", row)
        if image:
            found.extend(_images(image.group(1), repo, f"{rel}:{number}"))
    return found


# name, globs (basename patterns; a pattern with a / is matched against the repo-relative path), parse
READERS = [
    {"name": "composer.lock", "globs": ["composer.lock"], "parse": composer_lock},
    {"name": "composer.json", "globs": ["composer.json"], "parse": composer_json},
    {"name": "package-lock.json", "globs": ["package-lock.json"], "parse": package_lock},
    {"name": "yarn.lock", "globs": ["yarn.lock"], "parse": yarn_lock},
    {"name": "pnpm-lock.yaml", "globs": ["pnpm-lock.yaml"], "parse": pnpm_lock},
    {
        "name": "dockerfile",
        "globs": ["Dockerfile", "Dockerfile.*", "Dockerfile-*", "*.Dockerfile"],
        "parse": dockerfile,
    },
    {
        "name": "compose",
        "globs": ["docker-compose*.yml", "docker-compose*.yaml", "compose.yml", "compose.yaml"],
        "parse": compose,
    },
    {"name": "workflow", "globs": [".github/workflows/*.yml", ".github/workflows/*.yaml"], "parse": workflow},
]


def _claims(rel: str, globs) -> bool:
    base = os.path.basename(rel)
    return any(fnmatch.fnmatch(rel if "/" in glob else base, glob) for glob in globs)


def input_files(pack) -> list:
    """(repo, checkout, rel, reader) for every file a reader claims, pruned of vendor trees."""
    found = []
    for repo, top in repos(pack):
        for folder, dirs, files in os.walk(top):
            depth = 0 if folder == top else os.path.relpath(folder, top).count(os.sep) + 1
            dirs[:] = (
                sorted(
                    name for name in dirs if name not in SKIP_DIRS and (not name.startswith(".") or name == ".github")
                )
                if depth < MAX_DEPTH
                else []
            )
            for name in sorted(files):
                rel = os.path.relpath(os.path.join(folder, name), top)
                reader = next((reader for reader in READERS if _claims(rel, reader["globs"])), None)
                if reader:
                    found.append((repo, top, rel, reader))
    return found


def fingerprint(files) -> str:
    """The content of every input file and of this module: a reader change rebuilds too."""
    digest = hashlib.sha256(open(__file__, "rb").read())
    for repo, top, rel, _reader in files:
        try:
            body = open(os.path.join(top, rel), "rb").read()
        except OSError:
            continue
        digest.update(f"{repo}/{rel}\0{hashlib.sha256(body).hexdigest()}\n".encode())
    return digest.hexdigest()


def build(pack, files=None) -> dict:
    files = input_files(pack) if files is None else files
    components, seen, errors = [], {}, []
    for repo, top, rel, reader in files:
        text = open(os.path.join(top, rel), encoding="utf-8", errors="replace").read()
        try:
            parsed = reader["parse"](text, repo, rel)
        except Exception as exc:  # noqa: BLE001 - one unreadable file is reported, never the end of the manifest
            errors.append(f"{repo}/{rel}: {type(exc).__name__}: {exc}"[:300])
            continue
        for item in parsed:
            key = (item["kind"], item["name"], item["version"], item["repo"])
            if key in seen:  # the same thing twice in a repo: the production mention wins over a dev one
                if item["production"] and not seen[key]["production"]:
                    seen[key].update(where=item["where"], production=True, dev=item["dev"])
                continue
            seen[key] = item
            components.append(item)
    return {
        "time": iso(),
        "fingerprint": fingerprint(files),
        "repos": [name for name, _top in repos(pack)],
        "components": components,
        "errors": errors,
    }


def load_or_build(pack, path) -> tuple:
    """The manifest at path, rebuilt when its input files changed. (manifest, rebuilt)."""
    previous = read_json(path) or {}
    files = input_files(pack)
    if previous.get("components") is not None and previous.get("fingerprint") == fingerprint(files):
        return previous, False
    made = build(pack, files)
    write_json(path, made)
    return made, True


def counts(manifest) -> dict:
    found = {}
    for item in (manifest or {}).get("components") or []:
        found[item.get("kind") or "other"] = found.get(item.get("kind") or "other", 0) + 1
    return found
