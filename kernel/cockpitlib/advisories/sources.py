# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Free public advisory sources. REGISTRY lists {name, trust: high|low, fetch(manifest, cache) -> [item]}: adding a source
is one entry, and the pack's advisories.sources picks among them. Every request goes through Cache.get and the one http()
(tests replace it with local feeds). An item: {id, aliases, title, severity, cvss, published, modified, url, source,
affects: [{ecosystem, name, ranges: [{introduced, fixed}] | versions: [..]}], fix: {time, versions}, exploited, text}."""

import datetime
import hashlib
import html
import json
import math
import os
import re
import urllib.request
import xml.etree.ElementTree as ET

from ..store import write_text
from .match import canonical

AGENT = "cockpit-advisories/1 (stack watch; read-only)"
TIMEOUT = 20
WATCH_NAMES = (
    "php",
    "nginx",
    "mysql",
    "postgres",
    "redis",
    "node",
    "debian",
    "alpine",
)  # what the name-only sources look for
KEV_NAMES = {
    "php": "php",
    "nginx": "nginx",
    "mysql": "mysql",
    "postgresql": "postgres",
    "redis": "redis",
    "node.js": "node",
    "nodejs": "node",
    "debian": "debian",
    "alpine": "alpine",
}


def http(url, data=None, timeout=TIMEOUT) -> str:
    """The one network call: GET, or a JSON POST when data is given. Raises on any failure."""
    headers = {
        "User-Agent": AGENT,
        "Accept": "*/*",
        **({"Content-Type": "application/json"} if data is not None else {}),
    }
    request = urllib.request.Request(url, data=data, headers=headers, method="POST" if data is not None else "GET")  # noqa: S310 - a source's own address or a link from its feed: the scheme is not narrowed here
    with urllib.request.urlopen(request, timeout=timeout) as answer:  # noqa: S310 - a source's own address or a link from its feed: the scheme is not narrowed here
        return answer.read().decode("utf-8", "replace")


class Cache:
    """Every body lands in <dir>/<source>/<key>. reuse answers from it when present (details that do not change)."""

    def __init__(self, folder, fetch=None):
        self.folder, self.fetch, self.source = folder, fetch or http, "misc"

    def path(self, key) -> str:
        return os.path.join(self.folder, self.source, re.sub(r"[^A-Za-z0-9._-]", "_", key))

    def get(self, key, url, data=None, reuse=False) -> str:
        path = self.path(key)
        if reuse and os.path.exists(path):
            return open(path, encoding="utf-8").read()
        text = self.fetch(url, data)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        write_text(path, text)
        return text


def item(
    id,
    source,
    title="",
    severity="unknown",
    cvss=None,
    published=None,
    modified=None,
    url="",
    affects=None,
    fix=None,
    exploited=False,
    text="",
    aliases=None,
) -> dict:
    return {
        "id": id,
        "aliases": sorted(set(aliases or [])),
        "title": title or id,
        "severity": severity if severity in ("critical", "high", "medium", "low") else "unknown",
        "cvss": cvss,
        "published": published,
        "modified": modified,
        "url": url,
        "source": source,
        "affects": affects or [],
        "fix": {"time": (fix or {}).get("time"), "versions": list((fix or {}).get("versions") or [])},
        "exploited": bool(exploited),
        "text": (text or "")[:600],
    }


def strip_html(text) -> str:
    return html.unescape(re.sub(r"<[^>]+>", " ", text or "")).replace("\xa0", " ")


def squeeze(text) -> str:
    return " ".join((text or "").split())


def severity_of_score(score) -> str:
    if score is None:
        return "unknown"
    return (
        "critical"
        if score >= 9
        else "high"
        if score >= 7
        else "medium"
        if score >= 4
        else "low"
        if score > 0
        else "unknown"
    )


def cvss3_score(vector):
    """The CVSS 3.x base score of a vector string; None when it cannot be read."""
    try:
        metric = dict(part.split(":") for part in vector.split("/")[1:])
        changed = metric["S"] == "C"
        vector_ = {"N": 0.85, "A": 0.62, "L": 0.55, "P": 0.2}[metric["AV"]] * {"L": 0.77, "H": 0.44}[metric["AC"]]
        vector_ *= {"N": 0.85, "L": 0.68 if changed else 0.62, "H": 0.5 if changed else 0.27}[metric["PR"]] * {
            "N": 0.85,
            "R": 0.62,
        }[metric["UI"]]
        c, i, a = ({"H": 0.56, "L": 0.22, "N": 0}[metric[key]] for key in ("C", "I", "A"))
    except (KeyError, ValueError, IndexError):
        return None
    base = 1 - (1 - c) * (1 - i) * (1 - a)
    impact = 7.52 * (base - 0.029) - 3.25 * (base - 0.02) ** 15 if changed else 6.42 * base
    if impact <= 0:
        return 0.0
    return math.ceil(min((1.08 if changed else 1) * (impact + 8.22 * vector_), 10) * 10) / 10


WORDS = {"critical": "critical", "high": "high", "moderate": "medium", "medium": "medium", "low": "low"}


def severity_in_text(text, default="unknown") -> str:
    found = [WORDS[word] for word in re.findall(r"\b(critical|high|moderate|medium|low)\b", (text or "").lower())]
    return min(found, key=("critical", "high", "medium", "low").index) if found else default


MONTHS = {
    name: index
    for index, name in enumerate(
        ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"), 1
    )
}


def _date_in(text):
    found = re.search(r"(\d{4})-(\d{2})-(\d{2})", text)
    if found:
        return datetime.date(int(found.group(1)), int(found.group(2)), int(found.group(3)))
    found = re.search(r"\b(\d{1,2})(?:st|nd|rd|th)?\s+([A-Za-z]{3,9})\.?,?\s+(\d{4})", text)
    if found and found.group(2)[:3].lower() in MONTHS:
        return datetime.date(int(found.group(3)), MONTHS[found.group(2)[:3].lower()], int(found.group(1)))
    found = re.search(r"\b([A-Za-z]{3,9})\.?\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4})", text)
    if found and found.group(1)[:3].lower() in MONTHS:
        return datetime.date(int(found.group(3)), MONTHS[found.group(1)[:3].lower()], int(found.group(2)))
    return None


def fix_time(text, fallback=None):
    """A time like "14:00 UTC" and a date in the text → ISO UTC. The date right after the time wins, else the first date,
    else the fallback (the post's own date)."""
    text = text or ""
    clock = re.search(r"\b(\d{1,2}):(\d{2})\s*UTC\b", text) or re.search(r"\b(\d{1,2})\s*(am|pm)\s*UTC\b", text, re.I)
    date = (_date_in(text[clock.end() : clock.end() + 60]) if clock else None) or _date_in(text) or fallback
    if not date:
        return None
    hour = minute = 0
    if clock and clock.group(2).isdigit():
        hour, minute = int(clock.group(1)), int(clock.group(2))
    if clock and not clock.group(2).isdigit():
        hour = int(clock.group(1)) % 12 + (12 if clock.group(2).lower() == "pm" else 0)
    return datetime.datetime(date.year, date.month, date.day, hour, minute, tzinfo=datetime.UTC).isoformat()


def feed_entries(text) -> list:
    """Atom entries or RSS items as {title, link, updated, content}; namespaces ignored."""
    try:
        root = ET.fromstring(text.strip().encode("utf-8"))  # noqa: S314 - ElementTree fetches no external entity; a hardened parser would be a new runtime dependency
    except ET.ParseError:
        return []
    found = []
    for node in root.iter():
        if node.tag.rsplit("}", 1)[-1] not in ("entry", "item"):
            continue
        entry = {"title": "", "link": "", "updated": "", "content": ""}
        for child in node:
            tag = child.tag.rsplit("}", 1)[-1]
            if tag == "title":
                entry["title"] = squeeze(strip_html(child.text or ""))
            if tag == "link":
                entry["link"] = child.get("href") or (child.text or "").strip()
            if tag in ("updated", "published", "pubDate") and not entry["updated"]:
                entry["updated"] = (child.text or "").strip()
            if tag in ("content", "summary", "description", "encoded"):
                entry["content"] += strip_html("".join(child.itertext())) + " "
        found.append(entry)
    return found


def feed_time(text):
    for shape in ("%a, %d %b %Y %H:%M:%S %z", "%a, %d %b %Y %H:%M:%S %Z"):
        try:
            return datetime.datetime.strptime(text, shape).isoformat()
        except (TypeError, ValueError):
            pass
    try:
        return datetime.datetime.fromisoformat(str(text).replace("Z", "+00:00")).isoformat()
    except ValueError:
        return text or None


def _day(text):
    try:
        return datetime.datetime.fromisoformat(feed_time(text) or "").date()
    except (TypeError, ValueError):
        return None


def cves_in(text) -> list:
    return sorted(set(re.findall(r"\bCVE-\d{4}-\d{4,}\b", text or "")))


def names_in(manifest, kinds=("runtime", "image", "os")) -> list:
    return sorted(
        {canonical(item["name"]) for item in (manifest or {}).get("components") or [] if item["kind"] in kinds}
    )


def _has_runtime(manifest, name) -> bool:
    return any(
        item["ecosystem"] == name and item["kind"] == "runtime" for item in (manifest or {}).get("components") or []
    )


# ---- OSV: composer and npm packages

OSV_BATCH = "https://api.osv.dev/v1/querybatch"
OSV_VULN = "https://api.osv.dev/v1/vulns/"
OSV_ECO = {"composer": "Packagist", "npm": "npm"}
OSV_BACK = {value.lower(): key for key, value in OSV_ECO.items()}


def osv_item(vuln) -> dict:
    affects = []
    for affected in vuln.get("affected") or []:
        package = affected.get("package") or {}
        ecosystem, name = OSV_BACK.get(str(package.get("ecosystem", "")).lower()), package.get("name")
        if not ecosystem or not name:
            continue
        ranges = []
        for span in affected.get("ranges") or []:
            if span.get("type") == "GIT":
                continue
            start = None
            for event in span.get("events") or []:
                if "introduced" in event:
                    start = event["introduced"]
                    continue
                if "fixed" in event or "last_affected" in event:
                    ranges.append(
                        {
                            "introduced": start or "0",
                            "fixed": event.get("fixed"),
                            "last_affected": event.get("last_affected"),
                        }
                    )
                    start = None
            if start is not None:
                ranges.append({"introduced": start, "fixed": None})
        if ranges or affected.get("versions"):
            affects.append(
                {"ecosystem": ecosystem, "name": name, "ranges": ranges, "versions": affected.get("versions") or []}
            )
    score = None
    for rated in vuln.get("severity") or []:
        try:
            score = float(rated.get("score"))
        except (TypeError, ValueError):
            score = cvss3_score(rated.get("score") or "") if str(rated.get("type", "")).startswith("CVSS_V3") else score
    word = str((vuln.get("database_specific") or {}).get("severity") or "").lower()
    return item(
        vuln["id"],
        "osv",
        title=squeeze(vuln.get("summary") or (vuln.get("details") or "")[:120] or vuln["id"]),
        severity=WORDS.get(word) or severity_of_score(score),
        cvss=score,
        published=vuln.get("published"),
        modified=vuln.get("modified"),
        url=f"https://osv.dev/vulnerability/{vuln['id']}",
        affects=affects,
        fix={
            "versions": sorted({span["fixed"] for affect in affects for span in affect["ranges"] if span.get("fixed")})
        },
        text=squeeze(vuln.get("details") or ""),
        aliases=vuln.get("aliases") or [],
    )


def osv_fetch(manifest, cache) -> list:
    wanted = sorted(
        {
            (row["ecosystem"], row["name"], row["version"])
            for row in (manifest or {}).get("components") or []
            if row["kind"] == "package" and row["ecosystem"] in OSV_ECO
        }
    )
    queries = [
        {"package": {"name": name, "ecosystem": OSV_ECO[ecosystem]}, "version": version}
        for ecosystem, name, version in wanted
    ]
    modified = {}
    for start in range(0, len(queries), 1000):
        answer = json.loads(
            cache.get(
                f"batch-{start // 1000}",
                OSV_BATCH,
                data=json.dumps({"queries": queries[start : start + 1000]}).encode(),
            )
        )
        for result in answer.get("results") or []:
            for vuln in result.get("vulns") or []:
                modified[vuln["id"]] = vuln.get("modified")
    found = []
    for vid in sorted(modified):
        vuln = json.loads(cache.get(f"vulns/{vid}", OSV_VULN + vid, reuse=True))
        if modified[vid] and vuln.get("modified") != modified[vid]:
            vuln = json.loads(cache.get(f"vulns/{vid}", OSV_VULN + vid))
        found.append(osv_item(vuln))
    return found


# ---- CISA KEV: exploited in the wild

KEV_URL = "https://www.cisa.gov/sites/default/files/feeds/known_exploited_vulnerabilities.json"


def kev_items(data) -> list:
    """Every KEV entry (exploited); affects by name for the products in the watch list — the rest only lend their CVE."""
    found = []
    for vuln in data.get("vulnerabilities") or []:
        names = {
            KEV_NAMES[key]
            for key in (str(vuln.get("vendorProject", "")).lower(), str(vuln.get("product", "")).lower())
            if key in KEV_NAMES
        }
        found.append(
            item(
                vuln["cveID"],
                "kev",
                title=vuln.get("vulnerabilityName") or vuln["cveID"],
                published=vuln.get("dateAdded"),
                modified=vuln.get("dateAdded"),
                url=f"https://www.cisa.gov/known-exploited-vulnerabilities-catalog?search_api_fulltext={vuln['cveID']}",
                affects=[{"ecosystem": None, "name": name} for name in sorted(names)],
                exploited=True,
                text=squeeze(vuln.get("shortDescription") or ""),
            )
        )
    return found


def kev_fetch(manifest, cache) -> list:
    return kev_items(json.loads(cache.get("kev.json", KEV_URL)))


# ---- php.net: the release feed and the news archive

PHP_FEED = "https://www.php.net/releases/feed.php"
PHP_ARCHIVE = "https://www.php.net/archive/{year}.php"


def php_affects(text, title="") -> tuple:
    """The minor lines a php.net entry names (8.4.2 → the 8.4 line, fixed at 8.4.2 when the entry is a release)."""
    minors = {}
    for minor, patch in re.findall(r"\b(\d\.\d+)\.(\d+)\b", title + " " + text):
        minors.setdefault(minor, []).append(f"{minor}.{patch}")
    for minor in re.findall(r"\b(\d\.\d+)\.x\b", title + " " + text):
        minors.setdefault(minor, [])
    released = bool(re.search(r"\breleased\b", title, re.I)) or bool(
        re.search(r"\b(?:is|are) (?:now )?available\b|\bhas been released\b", text, re.I)
    )
    affects, fixed = [], []
    for minor, patches in sorted(minors.items()):
        top = max(patches, key=version_key) if patches else None
        span = (
            {"introduced": minor + ".0", "fixed": top}
            if released and top
            else {"introduced": minor + ".0", "fixed": None, "last_affected": minor + ".9999"}
        )
        affects.append({"ecosystem": "php", "name": "php", "ranges": [span]})
        if released and top:
            fixed.append(top)
    return affects, fixed


def version_key(text) -> tuple:
    return tuple(int(part) for part in text.split("."))


def php_item(title, link, text, when, id):
    blob = title + " " + text
    if "security" not in blob.lower():
        return None
    affects, fixed = php_affects(text, title)
    if not affects:
        return None
    return item(
        id,
        "php.net",
        title=title,
        severity=severity_in_text(blob, "high"),
        published=feed_time(when) if when else None,
        modified=feed_time(when) if when else None,
        url=link,
        affects=affects,
        fix={"time": None if fixed else fix_time(text, _day(when)), "versions": fixed},
        text=squeeze(text)[:600],
        aliases=cves_in(blob),
    )


def php_archive_items(page, year) -> list:
    """The news archive page: one entry per <h2 class="newstitle">…</h2> up to the next, security ones only."""
    found = []
    for entry in re.finditer(r'<h2 class="newstitle">(.*?)</h2>(.*?)(?=<h2 class="newstitle">|$)', page, re.S):
        head, body = entry.group(1), entry.group(2)
        link = re.search(r'href="([^"]+)"', head)
        title, text = squeeze(strip_html(head)), squeeze(strip_html(body))
        when = re.search(r'datetime="([^"]+)"', body) or re.search(r"(\d{4}-\d{2}-\d{2})", body)
        anchor = re.search(r'id="([^"]+)"', head) or re.search(r'#([\w-]+)"', head)
        url = link.group(1) if link else PHP_ARCHIVE.format(year=year)
        made = php_item(
            title,
            url if url.startswith("http") else "https://www.php.net" + url,
            text,
            when.group(1) if when else "",
            "php.net:"
            + (anchor.group(1) if anchor else hashlib.sha1(title.encode(), usedforsecurity=False).hexdigest()[:10]),
        )
        if made:
            found.append(made)
    return found


def php_fetch(manifest, cache) -> list:
    if not _has_runtime(manifest, "php"):
        return []
    found = [
        made
        for entry in feed_entries(cache.get("releases.xml", PHP_FEED))
        for made in [
            php_item(
                entry["title"],
                entry["link"],
                entry["content"],
                entry["updated"],
                "php.net:" + re.sub(r"\W+", "-", entry["title"].lower()).strip("-"),
            )
        ]
        if made
    ]
    year = datetime.date.today().year
    return found + php_archive_items(cache.get(f"archive-{year}.html", PHP_ARCHIVE.format(year=year)), year)


# ---- the Node.js vulnerability blog

NODE_FEED = "https://nodejs.org/en/feed/vulnerability.xml"
NODE_POSTS = 8  # the feed is title-only: the newest posts are read for their text


def node_item(entry):
    blob = entry["title"] + " " + entry["content"]
    majors = {}
    for major, minor, patch in re.findall(r"\bv?(\d{2})\.(\d+)\.(\d+)\b", blob):
        majors.setdefault(major, []).append(f"{major}.{minor}.{patch}")
    for major in (
        re.findall(r"\b(\d{2})\.x\b", blob)
        + re.findall(r"\bNode\.js\s+v?(\d{2})\b", blob)
        + re.findall(r"\bv(\d{2})\b", blob)
    ):
        majors.setdefault(major, [])
    if not majors:
        return None
    released = (
        bool(
            re.search(
                r"\breleases? (?:are|is) (?:now )?available\b|\bhave been released\b|\bwas released\b", blob, re.I
            )
        )
        or "(Update)" in entry["title"]
    )
    affects, fixed = [], []
    for major, versions in sorted(majors.items()):
        top = max(versions, key=version_key) if versions else None
        span = (
            {"introduced": major + ".0.0", "fixed": top}
            if released and top
            else {"introduced": major + ".0.0", "fixed": None, "last_affected": major + ".9999.9999"}
        )
        affects.append({"ecosystem": "node", "name": "node", "ranges": [span]})
        if released and top:
            fixed.append(top)
    return item(
        "nodejs:" + re.sub(r"\W+", "-", entry["title"].lower()).strip("-"),
        "nodejs",
        title=entry["title"],
        severity=severity_in_text(blob, "high"),
        published=feed_time(entry["updated"]),
        modified=feed_time(entry["updated"]),
        url=entry["link"],
        affects=affects,
        fix={"time": None if fixed else fix_time(entry["content"], _day(entry["updated"])), "versions": fixed},
        text=squeeze(entry["content"])[:600],
        aliases=cves_in(blob),
    )


def node_fetch(manifest, cache) -> list:
    if not _has_runtime(manifest, "node"):
        return []
    found = []
    for entry in feed_entries(cache.get("vulnerability.xml", NODE_FEED))[:NODE_POSTS]:
        if not entry["content"].strip() and entry["link"]:
            slug = re.sub(r"\W+", "-", entry["link"].rsplit("/", 1)[-1])
            try:
                page = cache.get(f"post-{slug}.html", entry["link"], reuse=True)
            except Exception:  # noqa: BLE001, S112 - one unreadable post does not fail the source
                continue
            entry["content"] = squeeze(strip_html(re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", page, flags=re.S)))
        made = node_item(entry)
        if made:
            found.append(made)
    return found


# ---- nginx security advisories

NGINX_URL = "https://nginx.org/en/security_advisories.html"


def nginx_items(page) -> list:
    found = []
    for block in re.findall(r"<li>(.*?)</li>", page, re.S):
        lines = [line for line in (squeeze(strip_html(part)) for part in re.split(r"<br\s*/?>", block)) if line]
        if not lines or "vulnerable" not in block.lower():
            continue
        title = lines[0]
        severity = next((severity_in_text(line) for line in lines if line.lower().startswith("severity")), "unknown")
        link, cves = re.search(r'href="([^"]+)"', block), cves_in(block)
        safe = re.findall(
            r"\d+\.\d+\.\d+", next((line for line in lines if line.lower().startswith("not vulnerable")), "")
        )
        vulnerable = next((line for line in lines if line.lower().startswith("vulnerable")), "")
        ranges = []
        for low, high in re.findall(r"(\d+\.\d+\.\d+)\s*-\s*(\d+\.\d+\.\d+)", vulnerable):
            fixes = sorted((value for value in safe if version_key(value) > version_key(high)), key=version_key)
            ranges.extend({"introduced": low, "fixed": value} for value in fixes)
            if not fixes:
                ranges.append({"introduced": low, "fixed": None})
        if not ranges and vulnerable:
            ranges = [{"introduced": "0", "fixed": min(safe, key=version_key) if safe else None}]
        found.append(
            item(
                cves[0] if cves else "nginx:" + hashlib.sha1(title.encode(), usedforsecurity=False).hexdigest()[:10],
                "nginx",
                title=title,
                severity=severity,
                url=link.group(1) if link else NGINX_URL,
                affects=[{"ecosystem": "docker", "name": "nginx", "ranges": ranges}],
                fix={"versions": sorted(set(safe))},
                text=" · ".join(lines[1:5]),
                aliases=cves,
            )
        )
    return found


def nginx_fetch(manifest, cache) -> list:
    if "nginx" not in names_in(manifest):
        return []
    return nginx_items(cache.get("security_advisories.html", NGINX_URL))


# ---- Hacker News: low trust, candidates only

HN_URL = "https://hn.algolia.com/api/v1/search_by_date?query={q}&tags=story&hitsPerPage=50&numericFilters=created_at_i>{since}"
HN_WORDS = re.compile(r"\b(CVE-\d{4}-\d+|RCE|vulnerab\w*|security)\b", re.I)


def hn_items(data, name) -> list:
    return [
        item(
            f"hn:{story.get('objectID')}",
            "hn",
            title=story.get("title") or "",
            published=story.get("created_at"),
            modified=story.get("created_at"),
            url=story.get("url") or f"https://news.ycombinator.com/item?id={story.get('objectID')}",
            affects=[{"ecosystem": None, "name": name}],
            text=squeeze(strip_html(story.get("story_text") or ""))[:300],
            aliases=cves_in(story.get("title") or ""),
        )
        for story in data.get("hits") or []
        if HN_WORDS.search(story.get("title") or "")
        and re.search(rf"\b{re.escape(name)}(?:\.js)?\b", story.get("title") or "", re.I)
    ]


def hn_fetch(manifest, cache) -> list:
    since = int((datetime.datetime.now(datetime.UTC) - datetime.timedelta(days=7)).timestamp())
    return [
        made
        for name in names_in(manifest)
        if name in WATCH_NAMES
        for made in hn_items(json.loads(cache.get(f"{name}.json", HN_URL.format(q=name, since=since))), name)
    ]


REGISTRY = [
    {"name": "osv", "trust": "high", "fetch": osv_fetch},
    {"name": "php.net", "trust": "high", "fetch": php_fetch},
    {"name": "nodejs", "trust": "high", "fetch": node_fetch},
    {"name": "nginx", "trust": "high", "fetch": nginx_fetch},
    {"name": "kev", "trust": "high", "fetch": kev_fetch},
    {"name": "hn", "trust": "low", "fetch": hn_fetch},
]
NAMES = tuple(source["name"] for source in REGISTRY)
