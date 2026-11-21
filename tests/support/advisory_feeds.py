# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Local stand-ins for the public advisory feeds and a fixture stack, for the advisories tests. Nothing here touches the
network: `feeds(pack)` answers each source's URL the way that source would, with values made from the pack's name."""

import datetime
import json
import os

from cockpitlib.advisories import sources


def stamp(days=0) -> str:
    return (datetime.datetime.now(datetime.UTC) - datetime.timedelta(days=days)).isoformat()


def stack(root, pack) -> dict:
    """Lockfiles, a Dockerfile, a compose file and a workflow in the pack's first repo; the names it used."""
    repo = pack["repos"]["repos"][0]
    top = os.path.join(str(root), repo["path"])
    os.makedirs(os.path.join(top, ".github", "workflows"), exist_ok=True)
    parser, tool = f"{pack['name']}-parser", f"{pack['name']}-devtool"
    lock = {
        "lockfileVersion": 3,
        "packages": {
            "": {"name": "app"},
            f"node_modules/{parser}": {"version": "1.2.0"},
            f"node_modules/{tool}": {"version": "0.1.0", "dev": True},
        },
    }
    open(os.path.join(top, "package-lock.json"), "w", encoding="utf-8").write(json.dumps(lock, indent=1))
    open(os.path.join(top, "composer.json"), "w", encoding="utf-8").write(
        json.dumps({"require": {"php": "^8.3"}, "config": {"platform": {"php": "8.3.4"}}})
    )
    open(os.path.join(top, "Dockerfile"), "w", encoding="utf-8").write(
        "FROM node:22-alpine3.20 AS build\nFROM build\nFROM php:8.3-fpm-bookworm\n"
    )
    open(os.path.join(top, "docker-compose.yml"), "w", encoding="utf-8").write(
        "services:\n  web:\n    image: nginx:1.25.3\n  x:\n    image: ${IMAGE}\n"
    )
    open(os.path.join(top, ".github", "workflows", "ci.yml"), "w", encoding="utf-8").write(
        "jobs:\n  t:\n    container: node:20.10.0\n    steps:\n      - with:\n          node-version: 20.10.0\n"
    )
    return {"repo": repo["name"], "parser": parser, "tool": tool}


def feeds(pack, fail=()):
    """fetch(url, data) for every source, values from the pack's name; a source named in fail raises."""
    name = pack["name"]
    parser, tool = f"{name}-parser", f"{name}-devtool"
    critical, high = f"OSV-{name[:4]}-crit-0001", f"OSV-{name[:4]}-high-0002"

    def fetch(url, data=None):
        for source, prefix in (
            ("osv", "https://api.osv.dev"),
            ("kev", "https://www.cisa.gov"),
            ("nodejs", "https://nodejs.org"),
            ("php.net", "https://www.php.net"),
            ("nginx", "https://nginx.org"),
            ("hn", "https://hn.algolia.com"),
        ):
            if url.startswith(prefix) and source in fail:
                raise OSError(f"{source} unreachable")
        if url == sources.OSV_BATCH:
            asked = json.loads(data)["queries"]
            return json.dumps(
                {
                    "results": [
                        {"vulns": [{"id": critical, "modified": "m1"}]}
                        if query["package"]["name"] == parser
                        else {"vulns": [{"id": high, "modified": "m2"}]}
                        if query["package"]["name"] == tool
                        else {}
                        for query in asked
                    ]
                }
            )
        if url == sources.OSV_VULN + critical:
            return json.dumps(
                {
                    "id": critical,
                    "modified": "m1",
                    "published": stamp(2),
                    "summary": f"prototype pollution in {parser}",
                    "aliases": [f"CVE-2026-{len(name)}001"],
                    "database_specific": {"severity": "CRITICAL"},
                    "affected": [
                        {
                            "package": {"ecosystem": "npm", "name": parser},
                            "ranges": [{"type": "SEMVER", "events": [{"introduced": "0"}, {"fixed": "1.2.4"}]}],
                        }
                    ],
                }
            )
        if url == sources.OSV_VULN + high:
            return json.dumps(
                {
                    "id": high,
                    "modified": "m2",
                    "published": stamp(1),
                    "summary": f"redos in {tool}",
                    "severity": [{"type": "CVSS_V3", "score": "CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:N/A:N"}],
                    "affected": [{"package": {"ecosystem": "npm", "name": tool}, "versions": ["0.1.0"]}],
                }
            )
        if url == sources.KEV_URL:
            return json.dumps(
                {
                    "vulnerabilities": [
                        {
                            "cveID": "CVE-2026-7001",
                            "vendorProject": "Node.js",
                            "product": "Node.js",
                            "vulnerabilityName": f"node flaw {name}",
                            "dateAdded": stamp(3)[:10],
                            "shortDescription": "exploited",
                        },
                        {
                            "cveID": f"CVE-2026-{len(name)}001",
                            "vendorProject": "Other",
                            "product": "Other",
                            "dateAdded": stamp(3)[:10],
                        },
                        {
                            "cveID": "CVE-2019-0001",
                            "vendorProject": "Nobody",
                            "product": "Nothing",
                            "dateAdded": "2019-01-01",
                        },
                    ]
                }
            )
        if url == sources.NODE_FEED:
            return (
                f"<rss><channel><item><title>Node.js 22 security release ({name})</title><link>https://nodejs.org/en/blog/{name}</link>"
                f"<pubDate>{datetime.datetime.now(datetime.UTC).strftime('%a, %d %b %Y %H:%M:%S +0000')}</pubDate></item></channel></rss>"
            )
        if url == f"https://nodejs.org/en/blog/{name}":
            return "<html><script>x</script><p>Node.js v22.9.1 releases are now available. Severity high. CVE-2026-2222</p></html>"
        if url == sources.PHP_FEED:
            return (
                f"<feed><entry><title>PHP 8.3.12 Released</title><link href='https://www.php.net/{name}'/><updated>{stamp(1)}</updated>"
                "<content>A security release: PHP 8.3.12 fixes CVE-2026-3333 (high).</content></entry></feed>"
            )
        if url.startswith("https://www.php.net/archive/"):
            return (
                f'<h2 class="newstitle"><a href="/archive/{name}" id="{name}-sec">PHP 8.2.x security update</a></h2>'
                f'<time datetime="{stamp(2)[:10]}"></time><p>Security fixes are coming on 2026-10-30 at 14:00 UTC.</p>'
                '<h2 class="newstitle"><a href="/x">Conference</a></h2><p>nothing</p>'
            )
        if url == sources.NGINX_URL:
            return (
                "<ul><li>Memory disclosure in the proxy<br>Severity: medium<br><a href='https://nginx.org/patch'>Advisory</a><br>"
                "CVE-2026-4444<br>Not vulnerable: 1.25.4+, 1.24.1+<br>Vulnerable: 1.25.0-1.25.3</li><li>Unrelated text</li></ul>"
            )
        if url.startswith("https://hn.algolia.com"):
            return json.dumps(
                {
                    "hits": [
                        {"objectID": f"{name}1", "title": "nginx security hole found", "created_at": stamp(1)},
                        {"objectID": f"{name}2", "title": "nginx tips", "created_at": stamp(1)},
                    ]
                }
            )
        raise AssertionError(f"no stub for {url}")

    return fetch, {"critical": critical, "high": high}
