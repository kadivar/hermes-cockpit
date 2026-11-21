# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The stack watch's readers, matching, merging and sources, one function at a time. The flow on both packs is in
test_bumps_and_pr_cards (test_the_stack_watch_raises_one_row_per_uncovered_production_alert)."""

import datetime
import http.server
import json
import os
import threading

import pytest

from cockpitlib.advisories import manifest, match, scan, sources

NOW = datetime.datetime(2026, 10, 23, 12, 0, tzinfo=datetime.UTC)


def test_each_reader_finds_its_components():
    lock = json.dumps(
        {
            "packages": [{"name": "acme/kit", "version": "v2.1.0"}],
            "packages-dev": [{"name": "acme/probe", "version": "1.0"}],
        }
    )
    found = manifest.composer_lock(lock, "api", "composer.lock")
    assert [(row["name"], row["version"], row["production"]) for row in found] == [
        ("acme/kit", "2.1.0", True),
        ("acme/probe", "1.0", False),
    ]
    old = json.dumps(
        {
            "dependencies": {
                "left-pad": {"version": "1.3.0", "dependencies": {"tiny": {"version": "0.1.0", "dev": True}}},
                "broken": "x",
            }
        }
    )
    assert [(row["name"], row["dev"]) for row in manifest.package_lock(old, "web", "package-lock.json")] == [
        ("left-pad", False),
        ("tiny", True),
    ]
    yarn = '# yarn\n"@scope/pkg@^1.0.0", "@scope/pkg@^1.1.0":\n  version "1.2.3"\n\nplain@~2:\n  version "2.0.1"\nlonely:\n  resolved "x"\n'
    assert [(row["name"], row["version"], row["where"]) for row in manifest.yarn_lock(yarn, "web", "yarn.lock")] == [
        ("@scope/pkg", "1.2.3", "yarn.lock:2"),
        ("plain", "2.0.1", "yarn.lock:5"),
    ]
    pnpm = "lockfileVersion: '9.0'\npackages:\n  /left-pad@1.3.0:\n    dev: true\n  '@scope/pkg@2.0.0(react@18.0.0)': {}\n  noversion: {}\n"
    assert [(row["name"], row["version"], row["dev"]) for row in manifest.pnpm_lock(pnpm, "web", "pnpm-lock.yaml")] == [
        ("left-pad", "1.3.0", True),
        ("@scope/pkg", "2.0.0", False),
    ]
    assert manifest.pnpm_lock("", "web", "pnpm-lock.yaml") == []
    images = manifest.dockerfile(
        "FROM --platform=linux/amd64 docker.io/library/php:8.4-cli AS base\nRUN make\nFROM scratch\nFROM base\nFROM redis\n",
        "api",
        "Dockerfile",
    )
    assert [(row["kind"], row["name"], row["version"]) for row in images] == [
        ("image", "php", "8.4-cli"),
        ("runtime", "php", "8.4"),
        ("image", "redis", "latest"),
    ]
    flows = manifest.workflow(
        "steps:\n  - uses: x\n    with:\n      node-version: [18, 20.11]\n    container: 'node:20-bookworm'\n",
        "web",
        ".github/workflows/ci.yml",
    )
    assert {(row["kind"], row["name"], row["version"]) for row in flows} == {
        ("runtime", "node", "18"),
        ("runtime", "node", "20.11"),
        ("image", "node", "20-bookworm"),
        ("runtime", "node", "20"),
        ("os", "debian", "bookworm"),
    }
    assert not any(row["production"] for row in flows)
    assert manifest.composer_json(json.dumps({"require": {"php": "*"}}), "api", "composer.json") == []
    assert manifest._tag_version("latest") == "latest" and manifest._tag_version("") == "latest"


def test_the_walk_skips_vendor_trees_reports_a_broken_file_and_rebuilds_only_on_change(tmp_path):
    top = tmp_path / "api"
    (top / "node_modules" / "x").mkdir(parents=True)
    (top / "node_modules" / "x" / "package-lock.json").write_text("{}", encoding="utf-8")
    (top / "a" / "b" / "c" / "d" / "e").mkdir(parents=True)
    (top / "a" / "b" / "c" / "d" / "e" / "Dockerfile").write_text("FROM too-deep:1\n", encoding="utf-8")
    (top / ".hidden").mkdir()
    (top / ".hidden" / "Dockerfile").write_text("FROM hidden:1\n", encoding="utf-8")
    (top / "composer.lock").write_text("not json", encoding="utf-8")
    (top / "Dockerfile").write_text("FROM node:22\n", encoding="utf-8")
    pack = {
        "repos": {
            "repos": [{"name": "api", "path": str(top)}, {"name": "gone", "path": str(tmp_path / "gone")}, {"name": ""}]
        }
    }
    files = manifest.input_files(pack)
    assert sorted(rel for _repo, _top, rel, _reader in files) == ["Dockerfile", "composer.lock"]
    built = manifest.build(pack)
    assert built["repos"] == ["api"] and built["errors"][0].startswith("api/composer.lock: JSONDecodeError")
    assert manifest.fingerprint([*files, ("api", str(top), "missing.lock", None)]) == manifest.fingerprint(files)
    path = str(tmp_path / "m.json")
    first, rebuilt = manifest.load_or_build(pack, path)
    assert rebuilt and manifest.load_or_build(pack, path) == (first, False)
    (top / "Dockerfile").write_text("FROM node:24\n", encoding="utf-8")
    assert manifest.load_or_build(pack, path)[1] is True
    assert manifest.counts(first) == {"image": 1, "runtime": 1} and manifest.counts(None) == {}
    dupe = manifest.build(
        {"repos": {"repos": [{"name": "api", "path": str(top)}]}},
        files=[
            ("api", str(top), "Dockerfile", manifest.READERS[5]),
            ("api", str(top), "Dockerfile", manifest.READERS[5]),
        ],
    )
    assert len(dupe["components"]) == 2


def test_a_dev_mention_gives_way_to_a_production_one(tmp_path):
    top = tmp_path / "web"
    (top / ".github" / "workflows").mkdir(parents=True)
    (top / ".github" / "workflows" / "ci.yml").write_text("    container: node:20\n", encoding="utf-8")
    (top / "Dockerfile").write_text("FROM node:20\n", encoding="utf-8")
    pack = {"repos": {"repos": [{"name": "web", "path": str(top)}]}}
    files = sorted(
        manifest.input_files(pack), key=lambda row: row[2] != ".github/workflows/ci.yml"
    )  # the dev mention read first
    built = manifest.build(pack, files=files)
    assert {(row["kind"], row["where"], row["production"]) for row in built["components"]} == {
        ("image", "Dockerfile:1", True),
        ("runtime", "Dockerfile:1", True),
    }


def test_versions_ranges_and_floating_tags():
    assert (
        match.version_tuple("v8.4.1-rc2") == (8, 4, 1)
        and match.version_tuple("1.2a") == (1, 2)
        and match.version_tuple("x") == ()
    )
    assert match.cmp("1.2", "1.2.0") == 0 and match.cmp("1.10", "1.9") == 1
    assert not match.in_range("abc", {"introduced": "0"}) and match.in_range(
        "2.0", {"introduced": "1.0", "last_affected": "2.0"}
    )
    package = {
        "kind": "package",
        "ecosystem": "npm",
        "name": "x",
        "version": "1.0.0",
        "repo": "r",
        "where": "w",
        "production": True,
    }
    assert match.component_hit(package, {"ecosystem": "npm", "name": "x", "versions": ["1.0.0"]}) == {
        "fixed_in": None,
        "version_checked": True,
    }
    assert match.component_hit(package, {"ecosystem": "npm", "name": "x", "ranges": [{"introduced": "2.0"}]}) is None
    assert match.component_hit(package, {"ecosystem": "composer", "name": "x", "ranges": [{"introduced": "0"}]}) is None
    assert match.component_hit(
        package, {"ecosystem": "npm", "name": "x", "ranges": [{"introduced": "0", "fixed": None}]}
    ) == {"fixed_in": None, "version_checked": True}
    line = {**package, "kind": "runtime", "ecosystem": "php", "name": "php", "version": "8.4"}
    assert (
        match.component_hit(
            line, {"ecosystem": "php", "name": "php", "ranges": [{"introduced": "8.4.0", "fixed": "8.4.5"}]}
        )
        is None
    )  # the tag picks 8.4.5 up
    assert (
        match.component_hit(
            line, {"ecosystem": "php", "name": "php", "ranges": [{"introduced": "8.0.0", "fixed": "9.0.0"}]}
        )["version_checked"]
        is False
    )
    assert match.parse_time("not a date") is None and match.parse_time("2026-10-01T00:00:00").tzinfo
    old = {"published": "2020-01-01", "affects": [{"name": "php"}], "trust": "high"}
    assert match.hits({"components": [line]}, old, NOW) == [] and match.status_of(old, NOW) == "candidate"
    assert (
        match.status_of({"trust": "high", "hits": [1], "fix": {"time": "2099-01-01T00:00:00+00:00"}}, NOW)
        == "patch-scheduled"
    )
    assert match.status_of({"trust": "high", "hits": [1], "fix": {}}, NOW) == "confirmed"
    assert match.severity_rank("nope") == len(match.SEVERITIES)
    assert match.summary({"id": "X", "fix": {"time": "soon"}}).endswith("fix expected soon") and match.summary(
        {"id": "X"}
    ).endswith("no fix known")


def test_the_alert_gate_follows_the_packs_urgencies():
    hit = [{"production": True, "repo": "r", "name": "x"}]
    high = {
        "status": "confirmed",
        "severity": "high",
        "hits": hit,
        "published": (NOW - datetime.timedelta(days=3)).isoformat(),
    }
    assert (
        match.alertable(high, {}, NOW)
        and not match.alertable(high, {"high_days": 2}, NOW)
        and not match.alertable(high, {"high_days": 0}, NOW)
    )
    assert match.alertable({**high, "severity": "low", "exploited": True}, {}, NOW) and not match.alertable(
        {**high, "severity": "low", "exploited": True}, {"exploited": False}, NOW
    )
    assert match.alertable({**high, "severity": "critical"}, {}, NOW) and not match.alertable(
        {**high, "severity": "critical"}, {"critical": False, "high_days": 0}, NOW
    )
    assert match.alertable({**high, "severity": "low", "status": "patch-scheduled"}, {}, NOW)
    assert not match.alertable({**high, "status": "candidate"}, {}, NOW) and not match.alertable(
        {**high, "acknowledged": {"note": ""}}, {}, NOW
    )
    assert (
        match.bump_names({"title": "chore(deps): bump a, b and c in /web"}) == {"a", "b", "c"}
        and match.bump_names({"title": "Update the docs"}) == set()
    )
    assert (
        match.bump_prs_for(
            {"hits": [{"kind": "runtime", "repo": "r", "name": "php"}]}, {"repos": {"r": [{"title": "Bump php to 9"}]}}
        )
        == []
    )
    assert not match.stale({"last_seen": NOW.isoformat()}, NOW) and match.stale(
        {"last_seen": "2026-01-01T00:00:00+00:00"}, NOW
    )


def test_merging_keeps_one_advisory_per_family():
    osv = sources.item(
        "OSV-1",
        "osv",
        title="real",
        severity="unknown",
        affects=[{"ecosystem": "npm", "name": "x", "ranges": [{"introduced": "0", "fixed": "2"}]}],
        fix={"versions": ["2"]},
        aliases=["CVE-2026-1"],
    )
    osv["trust"] = "high"
    kev = sources.item("CVE-2026-1", "kev", exploited=True, affects=[{"ecosystem": None, "name": "x"}])
    kev["trust"] = "high"
    low = sources.item(
        "hn:1", "hn", severity="high", aliases=["CVE-2026-1"], affects=[{"ecosystem": None, "name": "x"}]
    )
    low["trust"] = "low"
    bulletin = sources.item(
        "php.net:x",
        "php.net",
        aliases=["CVE-2026-1", "CVE-2026-2"],
        affects=[{"ecosystem": "php", "name": "php", "ranges": []}],
    )
    bulletin["trust"] = "high"
    lone = sources.item("CVE-2019-9", "kev", exploited=True)
    lone["trust"] = "high"
    merged = {row["id"]: row for row in scan.merge([kev, osv, low, bulletin, lone])}
    family = merged["CVE-2026-1"]
    assert (
        family["exploited"] and family["title"] == "real" and family["source"] == "osv" and family["severity"] == "high"
    )
    assert (
        sorted(family["via"]) == ["hn", "kev", "osv"]
        and "OSV-1" in family["aliases"]
        and "php.net:x" in merged
        and "CVE-2019-9" not in merged
    )
    assert len(family["affects"]) == 2


def test_sources_parse_their_pages():
    assert (
        sources.cvss3_score("CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:C/C:H/I:H/A:H") == 10.0
        and sources.cvss3_score("CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:N/I:N/A:N") == 0.0
    )
    assert (
        sources.cvss3_score("garbage") is None
        and sources.severity_of_score(None) == "unknown"
        and sources.severity_of_score(5) == "medium"
    )
    assert sources.severity_of_score(1) == "low" and sources.severity_of_score(0) == "unknown"
    assert sources.fix_time("released 5th March 2026 at 3pm UTC") == "2026-03-05T15:00:00+00:00"
    assert sources.fix_time("out on Mar 7, 2026") == "2026-03-07T00:00:00+00:00" and sources.fix_time("no date") is None
    assert (
        sources.feed_entries("<not xml") == []
        and sources.feed_time("") is None
        and sources.feed_time("Fri, 23 Oct 2026 10:00:00 GMT").startswith("2026-10-23")
    )
    assert sources.feed_time("whenever") == "whenever"
    vuln = {
        "id": "OSV-x",
        "affected": [
            {"package": {"ecosystem": "PyPI", "name": "p"}},
            {
                "package": {"ecosystem": "npm", "name": "n"},
                "ranges": [
                    {"type": "GIT"},
                    {"type": "SEMVER", "events": [{"introduced": "1"}, {"last_affected": "1.5"}, {"introduced": "2"}]},
                ],
            },
        ],
        "severity": [
            {"type": "CVSS_V3", "score": "CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H"},
            {"type": "OTHER", "score": "bad"},
        ],
    }
    made = sources.osv_item(vuln)
    assert (
        made["affects"][0]["ranges"]
        == [{"introduced": "1", "fixed": None, "last_affected": "1.5"}, {"introduced": "2", "fixed": None}]
        and made["severity"] == "critical"
    )
    assert sources.php_item("PHP 8.4.1 Released", "u", "no word of it", "", "id") is None
    assert sources.php_item("Security notes", "u", "nothing versioned here", "", "id") is None
    announced = sources.php_item("PHP security", "u", "fixes for 8.3.x come 2026-11-01", "2026-10-20", "id")
    assert (
        announced["fix"]["time"] == "2026-11-01T00:00:00+00:00"
        and announced["affects"][0]["ranges"][0]["last_affected"] == "8.3.9999"
    )
    assert sources.node_item({"title": "Release notes", "content": "nothing", "link": "", "updated": ""}) is None
    pending = sources.node_item(
        {"title": "Node.js 22 security", "content": "upcoming fixes for 22.x", "link": "l", "updated": "bad"}
    )
    assert pending["affects"][0]["ranges"][0]["last_affected"] == "22.9999.9999"
    page = "<li>Bug<br>Vulnerable: 1.20.0-1.21.0<br>Not vulnerable: none</li><li>Old<br>Vulnerable: all<br>Not vulnerable: 1.2.3</li>"
    assert [row["affects"][0]["ranges"] for row in sources.nginx_items(page)] == [
        [{"introduced": "1.20.0", "fixed": None}],
        [{"introduced": "0", "fixed": "1.2.3"}],
    ]
    assert (
        sources.nginx_fetch({"components": []}, None) == []
        and sources.php_fetch({"components": []}, None) == []
        and sources.node_fetch({"components": []}, None) == []
    )


def test_the_network_call_and_its_cache(tmp_path):
    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            self._answer(b"got " + self.path.encode())

        def do_POST(self):
            self._answer(b"posted " + self.rfile.read(int(self.headers["Content-Length"])))

        def _answer(self, body):
            self.send_response(200)
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        base = f"http://127.0.0.1:{server.server_port}"
        assert sources.http(base + "/a") == "got /a" and sources.http(base + "/b", data=b"{}") == "posted {}"
        cache = sources.Cache(str(tmp_path))
        cache.source = "osv"
        assert cache.get("k/1", base + "/c") == "got /c" and os.path.exists(cache.path("k/1"))
        assert cache.get("k/1", base + "/other", reuse=True) == "got /c"
    finally:
        server.shutdown()


def test_a_node_post_that_cannot_be_read_is_skipped(tmp_path):
    def fetch(url, data=None):
        if url == sources.NODE_FEED:
            return "<rss><item><title>Node.js 20 security</title><link>https://nodejs.org/post</link></item></rss>"
        raise OSError("down")

    cache = sources.Cache(str(tmp_path), fetch)
    assert sources.node_fetch({"components": [{"kind": "runtime", "ecosystem": "node", "name": "node"}]}, cache) == []


def test_ack_of_an_unknown_advisory_changes_nothing(bare):
    from conftest import PACK

    from cockpitlib.advisories import acks_path
    from cockpitlib.pack import load

    assert scan.ack(load(PACK), "OSV-none") is None and not os.path.exists(acks_path())
    with pytest.raises(Exception, match="bad advisory id"):
        from cockpitlib.advisories.card import make

        make(load(PACK), "")


def test_an_osv_detail_is_read_again_when_its_modified_stamp_moved(tmp_path):
    asked = []

    def fetch(url, data=None):
        asked.append(url)
        if url == sources.OSV_BATCH:
            return json.dumps({"results": [{"vulns": [{"id": "OSV-m", "modified": "new"}]}]})
        return json.dumps({"id": "OSV-m", "modified": "new", "affected": []})

    cache = sources.Cache(str(tmp_path), fetch)
    cache.source = "osv"
    os.makedirs(os.path.dirname(cache.path("vulns/OSV-m")), exist_ok=True)
    open(cache.path("vulns/OSV-m"), "w", encoding="utf-8").write(
        json.dumps({"id": "OSV-m", "modified": "old", "affected": []})
    )
    found = sources.osv_fetch(
        {"components": [{"kind": "package", "ecosystem": "npm", "name": "x", "version": "1"}]}, cache
    )
    assert [row["id"] for row in found] == ["OSV-m"] and asked == [sources.OSV_BATCH, sources.OSV_VULN + "OSV-m"]
