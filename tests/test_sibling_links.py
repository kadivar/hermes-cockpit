# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""A ticket's PRs name each other whichever way the second one went out: one row at a time links them as the digest does."""

from cockpitlib import publish
from cockpitlib.errors import CockpitError


class _Forge:
    dry_run = False

    def __init__(self, bodies):
        self.bodies = bodies
        self.writes = []

    def repo(self, name):
        return f"acme/{name}"

    def pr(self, repo, number):
        return {"body": self.bodies[repo]}

    def write(self, method, path, data):
        self.writes.append((method, path))
        self.bodies[path.split("/")[2]] = data["body"]


def _opened(repo, number, status="published"):
    return {
        "id": f"TASK-9/00{number}-open-pr",
        "ticket": "TASK-9",
        "type": "open-pr",
        "status": status,
        "payload": {"repo": repo},
        "receipt": {"ok": True, "url": f"https://github.test/acme/{repo}/pull/{number}"},
    }


def test_the_second_pr_published_by_itself_fills_the_related_links_of_both(monkeypatch):
    from cockpitlib import intents

    api, web = _opened("api", 4), _opened("web", 7)
    monkeypatch.setattr(intents, "all_intents", lambda ticket=None: [api, web])
    lines = []
    monkeypatch.setattr(publish, "log", lines.append)
    forge = _Forge({"api": "Related PRs:\n- (web) TBD\n", "web": "Related PRs:\n- (api) TBD\n"})
    receipt = {"ok": True, "url": web["receipt"]["url"]}
    publish.link_siblings(forge, web, receipt)
    assert receipt["related"] == ["api#4", "web#7"]
    assert forge.bodies == {
        "api": "Related PRs:\n- (web) https://github.test/acme/web/pull/7\n",
        "web": "Related PRs:\n- (api) https://github.test/acme/api/pull/4\n",
    }
    assert lines == ["BACKFILL TASK-9 api#4", "BACKFILL TASK-9 web#7"]
    again = {"ok": True}
    publish.link_siblings(forge, web, again)
    assert again["related"] == [] and len(forge.writes) == 2  # nothing left to fill: nothing written


def test_the_first_pr_alone_keeps_its_placeholder_and_other_publishes_fill_nothing(monkeypatch):
    from cockpitlib import intents

    web = _opened("web", 7)
    monkeypatch.setattr(intents, "all_intents", lambda ticket=None: [web, _opened("api", 4, status="endorsed")])
    forge = _Forge({"web": "Related PRs:\n- (api) TBD\n"})
    receipt = {"ok": True}
    publish.link_siblings(forge, web, receipt)
    assert receipt["related"] == [] and forge.writes == [] and "TBD" in forge.bodies["web"]
    for intent, said in (
        ({**web, "type": "push-branch"}, {"ok": True}),
        (web, {"ok": False}),
        (web, {"ok": True, "dry_run": True}),
    ):
        publish.link_siblings(forge, intent, said)
        assert "related" not in said and forge.writes == []


def test_a_fill_that_fails_is_said_on_the_receipt_and_never_fails_the_publish(monkeypatch):
    lines = []
    monkeypatch.setattr(publish, "log", lines.append)

    def refuse(_forge, _ticket):
        raise CockpitError("read-back: api#4 still shows TBD for ['web']")

    monkeypatch.setattr(publish, "backfill_related", refuse)
    receipt = {"ok": True}
    publish.link_siblings(_Forge({}), _opened("web", 7), receipt)
    assert receipt == {"ok": True, "related_error": "read-back: api#4 still shows TBD for ['web']"}
    assert lines == ["BACKFILL FAIL TASK-9 :: read-back: api#4 still shows TBD for ['web']"]
