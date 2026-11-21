# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Compile platform/map.yaml into the tree the Platform page draws.

The file is a conceptual model: areas, the features inside them, and the
cross-cutting components they share. A repository is only where an anchor
points. It is not a node.
"""

import os
import re
from datetime import UTC, datetime

from .errors import CockpitError

MISSING = "no platform/map.yaml. Ask the platform-map skill (cockpit:platform-map) to write one, then cockpit map build"
_SKIP = {"node_modules", "vendor", ".git", "dist", "storage"}


class MapError(CockpitError):
    exit_code = 1


def map_yaml_path(pack) -> str:
    return os.path.join(pack["_dir"], "platform", "map.yaml")


def _n(count, singular) -> str:
    if count == 1:
        return f"1 {singular}"
    return f"{count} {singular}s"


def _anchors(raw):
    found = []
    for item in raw or []:
        found.append(
            {
                "repo": item.get("repo") or "",
                "paths": list(item.get("paths") or []),
                "key": list(item.get("key") or []),
            }
        )
    return found


def compile_document(document) -> dict:
    """areas → features, plus components. Duplicate ids and unknown refs fail."""
    nodes = []
    for area in document.get("areas") or []:
        area_id = area.get("id") or ""
        if not area_id:
            raise MapError("an area has no id")
        nodes.append(
            {
                "id": area_id,
                "kind": "area",
                "title": area.get("title") or area_id,
                "summary": area.get("summary") or "",
                "parent": None,
            }
        )
        for feature in area.get("features") or []:
            feature_id = feature.get("id") or ""
            if not feature_id:
                raise MapError(f"{area_id}: a feature has no id")
            nodes.append(
                {
                    "id": feature_id,
                    "kind": "feature",
                    "title": feature.get("title") or feature_id,
                    "parent": area_id,
                    "user": feature.get("user") or "",
                    "hld": feature.get("hld") or "",
                    "lld": feature.get("lld") or "",
                    "anchors": _anchors(feature.get("anchors")),
                    "depends": list(feature.get("depends") or []),
                    "docs": list(feature.get("docs") or []),
                }
            )
    for component in document.get("components") or []:
        component_id = component.get("id") or ""
        if not component_id:
            raise MapError("a component has no id")
        nodes.append(
            {
                "id": component_id,
                "kind": "component",
                "title": component.get("title") or component_id,
                "parent": "components",
                "summary": component.get("summary") or "",
                "hld": component.get("hld") or "",
                "lld": component.get("lld") or "",
                "anchors": _anchors(component.get("anchors")),
                "used_by": list(component.get("used_by") or []),
                "docs": list(component.get("docs") or []),
            }
        )
    ids = [node["id"] for node in nodes]
    duplicate = sorted({item for item in ids if ids.count(item) > 1})
    if duplicate:
        raise MapError(f"duplicate ids: {duplicate}")
    by_id = {node["id"]: node for node in nodes}
    for node in nodes:
        for ref in list(node.get("depends") or []) + list(node.get("used_by") or []):
            if ref not in by_id:
                raise MapError(f"{node['id']}: unknown reference {ref}")
    for node in nodes:
        if node["kind"] != "component":
            continue
        for feature_id in node.get("used_by") or []:
            feature = by_id[feature_id]
            feature["depends"] = sorted(set(feature.get("depends") or []) | {node["id"]})
    for node in nodes:
        if node["kind"] != "feature":
            continue
        for component_id in node.get("depends") or []:
            component = by_id.get(component_id)
            if component is None or component["kind"] != "component":
                continue
            component["used_by"] = sorted(set(component.get("used_by") or []) | {node["id"]})
    built = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    return {
        "version": document.get("version") or 1,
        "repos": list(document.get("repos") or []),
        "nodes": nodes,
        "built": built,
    }


def load_document(pack):
    path = map_yaml_path(pack)
    if not os.path.isfile(path):
        return None
    from . import pack_local

    return pack_local.read(path, pack["_dir"]) or {}


def compiled_tree(pack):
    document = load_document(pack)
    if document is None:
        return None
    return compile_document(document)


def summary(tree) -> str:
    nodes = tree.get("nodes") or []
    areas = sum(1 for node in nodes if node["kind"] == "area")
    features = sum(1 for node in nodes if node["kind"] == "feature")
    components = sum(1 for node in nodes if node["kind"] == "component")
    return f"platform map: {_n(areas, 'area')}, {_n(features, 'feature')}, {_n(components, 'component')}"


def glob_re(pattern: str) -> str:
    """Repo-relative glob. ** crosses directories, * stays in one segment."""
    out = ""
    index = 0
    while index < len(pattern):
        if pattern.startswith("**/", index):
            out += "(?:.*/)?"
            index += 3
            continue
        if pattern.startswith("**", index):
            out += ".*"
            index += 2
            continue
        char = pattern[index]
        if char == "*":
            out += "[^/]*"
        elif char == "?":
            out += "[^/]"
        else:
            out += re.escape(char)
        index += 1
    return "^" + out + "(?:/.*)?$"


def _repo_dirs(pack) -> dict:
    from .paths import root

    found = {}
    for repo in pack["repos"]["repos"]:
        name = repo.get("name") or ""
        path = repo.get("path") or ""
        if path and not os.path.isabs(path):
            path = os.path.join(root(), path)
        found[name] = path
    return found


def _matches(repo_dir, pattern) -> bool:
    if not os.path.isdir(repo_dir):
        return False
    compiled = re.compile(glob_re(pattern))
    for dirpath, dirnames, filenames in os.walk(repo_dir):
        dirnames[:] = [name for name in dirnames if name not in _SKIP]
        relative = os.path.relpath(dirpath, repo_dir)
        if relative != "." and compiled.match(relative + "/x"):
            return True
        for filename in filenames:
            candidate = filename if relative == "." else os.path.normpath(os.path.join(relative, filename))
            if compiled.match(candidate):
                return True
    return False


def map_check(pack) -> list:
    tree = compiled_tree(pack)
    if tree is None:
        return [MISSING]
    dirs = _repo_dirs(pack)
    misses = []
    for node in tree["nodes"]:
        for anchor in node.get("anchors") or []:
            repo_dir = dirs.get(anchor["repo"]) or ""
            if not os.path.isdir(repo_dir):
                misses.append(f"{node['id']}: no local clone for {anchor['repo']}")
                continue
            for pattern in anchor["paths"]:
                if _matches(repo_dir, pattern):
                    continue
                misses.append(f"{node['id']}: {anchor['repo']}:{pattern} matches nothing")
    return misses


def map_nodes_text(pack) -> str:
    tree = compiled_tree(pack)
    if tree is None:
        return MISSING
    lines = []
    for node in tree["nodes"]:
        parent = ""
        if node["kind"] == "feature" and node.get("parent"):
            parent = f"  (in {node['parent']})"
        lines.append(f"{node['kind']:<10}{node['id']:<32}{node['title']}{parent}")
    return "\n".join(lines)
