# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""One window's acts that put a line under every section of the standup note, for the tests that hold its text."""

U = "https://forge.example.test/example-org"


def sample(project: str) -> dict:
    """{acts, titles, open, statuses}: tickets of that project that between them fill every section and both waits."""
    a, b, c, d, e, f = (f"{project}-{number}" for number in (101, 102, 103, 104, 105, 106))
    acts = {
        a: {
            "tested": [
                {"what": "test results posted on the tracker", "url": "https://tracker.example.test/c/1", "at": 1.0}
            ]
        },
        b: {
            "developed": [
                {"what": "PR opened (api#7)", "url": f"{U}/api/pull/7", "at": 2.0},
                {"what": "branch pushed", "url": "", "at": 2.5},
            ],
            "tested": [{"what": "test results posted on the tracker", "url": "", "at": 3.0}],
            "merged": [{"what": "api#6 merged (our PR)", "url": f"{U}/api/pull/6", "at": 4.0}],
        },
        c: {
            "reviewed": [{"what": "web#9 changes requested", "url": f"{U}/web/pull/9", "at": 5.0}],
            "merged": [{"what": "web#8 merged (reviewed by us)", "url": f"{U}/web/pull/8", "at": 6.0}],
        },
        "BUMPS-2026W01": {
            "bumps": [
                {"what": "api#11", "url": f"{U}/api/pull/11", "at": 7.0},
                {"what": "api#12 merged", "url": "", "at": 7.5},
            ]
        },
        d: {
            "created": [
                {
                    "what": f"tracker ticket {project}-200 (a follow-up)",
                    "url": "https://tracker.example.test/b/200",
                    "at": 8.0,
                }
            ]
        },
        e: {"done": [{"what": "ticket closed", "url": "", "at": 9.0}]},
        f: {
            "other": [
                {"what": "PR comment", "url": f"{U}/api/pull/13", "at": 10.0},
                {"what": "CI rerun", "url": "", "at": 10.5},
            ]
        },
    }
    titles = {
        a: "The export keeps its header",
        b: "A list can be archived ",
        c: "",
        d: "Follow up the archive",
        f: "A flaky check",
    }
    open_ = [
        {
            "ticket": b,
            "flows": ["dev"],
            "last_card": "",
            "prs": [
                {
                    "repo": "api",
                    "number": 7,
                    "role": "author",
                    "state": "open",
                    "approvals": [],
                    "url": f"{U}/api/pull/7",
                },
                {"repo": "api", "number": 6, "role": "author", "merged": True, "url": f"{U}/api/pull/6"},
            ],
        },
        {
            "ticket": c,
            "flows": ["review"],
            "last_card": "",
            "prs": [
                {
                    "repo": "web",
                    "number": 9,
                    "role": "reviewer",
                    "state": "open",
                    "my_review_state": "CHANGES_REQUESTED",
                    "url": f"{U}/web/pull/9",
                }
            ],
        },
    ]
    return {"acts": acts, "titles": titles, "open": open_, "statuses": {b: "In Test", c: "In Review"}}
