# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""QA evidence as the page reads it: each ticket's test runs (qa/<ticket>/<testflow.run_dir>),
the results table of a run, its evidence files, the review files and the test plan. Read-only."""

import base64
import mimetypes
import os
import re

from .paths import qa_of

MEDIA_LIMIT = 40_000_000
IMG = {".png", ".jpg", ".jpeg", ".gif", ".webp"}
VID = {".mp4", ".mov", ".webm", ".m4v"}
TXT = {".md", ".txt", ".log", ".json", ".html", ".csv", ".yaml", ".yml", ".js", ".ts", ".php", ".py", ".sh"}
TICKET = re.compile(r"^[A-Za-z][A-Za-z0-9]*(?:-[0-9A-Za-z]+)+$")


def read_text(path: str, limit: int = 400000) -> str:
    try:
        with open(path, encoding="utf-8", errors="replace") as handle:
            return handle.read(limit)
    except OSError:
        return ""


def _markdown(text: str) -> str:
    from .render import markdown

    return markdown(text or "")


def qa_dir(ticket: str):
    """The ticket's folder, however its case was written; None when there is none."""
    from .paths import qa

    if not TICKET.match(ticket or ""):
        return None
    root = qa()
    if not os.path.isdir(root):
        return None
    direct = qa_of(ticket)
    if os.path.isdir(direct):
        return direct
    for name in os.listdir(root):
        if name.lower() == ticket.lower() and os.path.isdir(qa_of(name)):
            return qa_of(name)
    return None


def kind_of(path: str) -> str:
    ext = os.path.splitext(path)[1].lower()
    if ext in IMG:
        return "image"
    if ext in VID:
        return "video"
    if ext == ".pdf":
        return "pdf"
    if ext in TXT:
        return "text"
    return "other"


def list_files(root: str) -> list:
    files = []
    for folder, dirs, names in os.walk(root):
        dirs[:] = sorted(name for name in dirs if not name.startswith("."))
        for name in sorted(names):
            if name.startswith("."):
                continue
            full = os.path.join(folder, name)
            try:
                size = os.path.getsize(full)
            except OSError:
                size = 0
            files.append({"rel": os.path.relpath(full, root), "path": full, "kind": kind_of(full), "size": size})
    return files


def _verdict(cell: str) -> str:
    if "✅" in cell or re.search(r"\bpass", cell, re.I):
        return "pass"
    if "❌" in cell or re.search(r"\bfail", cell, re.I):
        return "fail"
    if "⚠" in cell or re.search(r"partial|blocked|skip", cell, re.I):
        return "warn"
    return ""


def parse_results(path: str) -> dict:
    """test-results.md: the meta lines, the Summary table's rows with their evidence links, the other sections rendered."""
    text = read_text(path)
    first = (text.splitlines() or [""])[0]
    out = {"path": path, "title": first.lstrip("# ").strip(), "meta": {}, "rows": [], "sections": {}}
    for match in re.finditer(r"^(?:- )?\*\*([A-Za-z ]+?):?\*\*:?\s*(.+)$", text, re.M):
        out["meta"][match.group(1).strip()] = match.group(2).strip()
    section = None
    for line in text.splitlines():
        if line.startswith("## "):
            section = line[3:].strip()
            out["sections"][section] = ""
            continue
        if section is not None:
            out["sections"][section] += line + "\n"
    summary = out["sections"].get("Summary", "")
    cols = None
    seq = 0
    for line in summary.splitlines():
        if not line.startswith("|") or re.match(r"^\|\s*:?-", line):
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        low = [cell.lower() for cell in cells]
        header = (
            cols is None
            and any(word in " ".join(low) for word in ("scenario", "verdict", "result"))
            and not any(re.match(r"^[0-9]+[a-z]?$", cell) for cell in cells[:1])
            and not any(_verdict(cell) for cell in cells)
        )
        if header:

            def find(*names):
                return next(
                    (
                        index
                        for index, cell in enumerate(low)
                        if any(cell == name or cell.startswith(name) for name in names)
                    ),
                    None,
                )

            cols = {
                "id": find("#", "id", "no"),
                "scenario": find("scenario", "case", "test"),
                "area": find("area", "group"),
                "verdict": find("verdict", "result", "status", "outcome"),
                "evidence": find("evidence", "proof", "video", "screenshot"),
                "note": find("note", "comment", "detail", "observation"),
            }
            if cols["scenario"] is None:
                cols["scenario"] = 1 if cols["id"] == 0 else 0
            continue
        if cols is None:
            continue

        def cell_of(key):
            index = cols.get(key)
            return cells[index] if index is not None and index < len(cells) else ""

        seq += 1
        row_id = cell_of("id")
        verdict_cell = cell_of("verdict") or next((cell for cell in cells if _verdict(cell)), "")
        links = [
            {"label": match.group(1), "rel": match.group(2)}
            for cell in cells
            for match in re.finditer(r"\[([^\]]+)\]\(([^)]+)\)", cell)
        ]
        evidence = cell_of("evidence")
        if not links and evidence and re.match(r"^[A-Za-z0-9_./*-]+$", evidence):
            links = [{"label": evidence, "rel": evidence, "glob": True}]
        scenario = cell_of("scenario")
        area = cell_of("area")
        out["rows"].append(
            {
                "n": row_id if re.match(r"^[0-9]+[a-z]?$", row_id or "") else str(seq),
                "scenario": (area + " · " if area and area != scenario else "") + scenario,
                "result": verdict_cell,
                "verdict": _verdict(verdict_cell),
                "evidence": links,
                "note": cell_of("note"),
            }
        )
    head = text.split("\n## ", 1)[0]
    for match in re.finditer(r"^([A-Z][A-Za-z /]{2,30}):\s+(.+)$", head, re.M):
        out["meta"].setdefault(match.group(1).strip(), match.group(2).strip())
    date_src = next(
        (out["meta"][key] for key in ("Date", "Run date", "Run", "Executed", "When") if out["meta"].get(key)), ""
    )
    if not date_src:
        found = re.search(r"\d{4}-\d{2}-\d{2}", head)
        date_src = found.group(0) if found else ""
    found = re.search(r"\d{4}-\d{2}-\d{2}", date_src)
    out["date"] = found.group(0) if found else date_src[:10]
    out["date_detail"] = date_src
    for key in ("Run", "Ticket under test", "Branch/state under test"):
        if key in out["meta"] and "Under test" not in out["meta"] and "under test" in key.lower():
            out["meta"]["Under test"] = out["meta"][key]
    out["sections"].pop("Summary", None)
    out["sections"] = {key: _markdown(value) for key, value in out["sections"].items() if value.strip()}
    return out


def _bound_pack():
    """The bound pack, or None when it does not load: the page then reads the run folders by the kernel's own pattern."""
    try:
        from .plugin_api import _pack

        return _pack()
    except Exception:  # noqa: BLE001 - no readable pack is answered as none
        return None


def _runs_of(folder: str, pack=None) -> list:
    from .test_flow import run_folders

    return run_folders(pack if pack is not None else _bound_pack(), folder)


def _counts(result) -> dict:
    rows = (result or {}).get("rows") or []
    return {key: sum(1 for row in rows if row["verdict"] == key) for key in ("pass", "fail", "warn")}


def index(pack=None) -> dict:
    """Every ticket with a run, newest run date first."""
    from .paths import qa
    from .test_flow import results_file

    pack = pack if pack is not None else _bound_pack()  # once for every ticket, not per folder
    results_name = results_file(pack)
    root = qa()
    tickets = []
    for name in sorted(os.listdir(root)) if os.path.isdir(root) else []:
        folder = qa_of(name)
        if name.startswith("_") or not os.path.isdir(folder):
            continue
        runs = _runs_of(folder, pack)
        if not runs:
            continue
        results = os.path.join(folder, runs[-1], results_name)
        last = (
            parse_results(results)
            if os.path.isfile(results)
            else {"rows": [], "meta": {}, "date": "", "date_detail": ""}
        )
        tickets.append(
            {
                "ticket": name,
                "runs": len(runs),
                "last_run": runs[-1],
                "date": last.get("date") or "",
                "date_detail": last.get("date_detail") or "",
                "counts": _counts(last),
                "scenarios": len(last.get("rows") or []),
                "mtime": max((os.path.getmtime(os.path.join(folder, run)) for run in runs), default=0),
            }
        )
    tickets.sort(key=lambda item: (item["date"] or "0000-00-00", item["mtime"]), reverse=True)
    return {"tickets": tickets}


def ticket(key: str, pack=None) -> dict:
    """One ticket: its runs newest first (results, evidence files, the videos' README), the review files, the plan."""
    folder = qa_dir(key)
    if folder is None:
        return {"ticket": key, "dir": None, "runs": [], "review": [], "scenarios": None}
    pack = pack if pack is not None else _bound_pack()
    from .test_flow import evidence_dir, plan_file, results_file, title

    names = {
        "title": title(pack),
        "results": results_file(pack),
        "evidence": evidence_dir(pack),
        "plan": plan_file(pack),
    }
    runs = []
    for name in _runs_of(folder, pack):
        run_dir = os.path.join(folder, name)
        results = os.path.join(run_dir, names["results"])
        evidence = os.path.join(run_dir, names["evidence"])
        readme = os.path.join(evidence, "videos", "README.md")
        runs.append(
            {
                "name": name,
                "dir": run_dir,
                "results": parse_results(results) if os.path.isfile(results) else None,
                "files": list_files(evidence) if os.path.isdir(evidence) else [],
                "readme": _markdown(read_text(readme)) if os.path.isfile(readme) else None,
            }
        )
    runs.reverse()
    scenarios = os.path.join(folder, names["plan"])
    review = os.path.join(folder, "review")
    return {
        "ticket": key,
        "dir": folder,
        "runs": runs,
        "review": list_files(review) if os.path.isdir(review) else [],
        "scenarios": _markdown(read_text(scenarios)) if os.path.isfile(scenarios) else None,
        "names": names,
    }


def file_record(real: str) -> dict:
    """One evidence file for the viewer: images, videos and PDFs as base64 (the page makes a blob URL), text inline,
    markdown rendered too."""
    ext = os.path.splitext(real)[1].lower()
    size = os.path.getsize(real)
    mime = mimetypes.guess_type(real)[0] or ("video/quicktime" if ext == ".mov" else "application/octet-stream")
    if ext in IMG or ext in VID or ext == ".pdf":
        if size > MEDIA_LIMIT:
            return {
                "kind": "large",
                "mime": mime,
                "size": size,
                "text": f"{size} bytes: open it from the folder instead",
            }
        with open(real, "rb") as handle:
            return {"kind": "media", "mime": mime, "size": size, "b64": base64.b64encode(handle.read()).decode()}
    text = read_text(real)
    return {
        "kind": "markdown" if ext == ".md" else "text",
        "mime": mime,
        "size": size,
        "text": text,
        "html": _markdown(text) if ext == ".md" else None,
    }
