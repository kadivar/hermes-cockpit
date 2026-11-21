# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""tracker.kind github-issues: a ticket <project>-<n> is issue n of one repo on the forge the pack publishes to. No second
client and no second sign-in: over the GitHub stand-in and over the forge kept in files, the outbox publishes to it and
the comment watch reads it like any tracker."""

import os
import re
import shutil

import pytest
import yaml

from cockpitlib import tracker, trackers
from cockpitlib.errors import CockpitError, PackError
from cockpitlib.forges.local import LocalForge
from cockpitlib.pack import load
from cockpitlib.trackers import base
from cockpitlib.trackers.github_issues import GitHubIssuesTracker
from tests.support import fake_gh
from tests.support.both_packs import PACKS

FORGES = ("github", "local")
LABELS = {"In Progress": "in progress", "In Review": "in review", "Done": "done"}


def _issues_pack(tmp_path, pack_file, forge_kind="local", **settings) -> str:
    """A copy of the fixture pack whose tracker is the issues of its forge."""
    folder = (
        tmp_path / "packs" / os.path.basename(os.path.dirname(pack_file))
    )  # a fixture pack's @anchors need the folder above to be packs
    shutil.copytree(os.path.dirname(pack_file), folder)
    raw = yaml.safe_load((folder / "pack.yaml").read_text(encoding="utf-8"))
    named = {key: raw["tracker"][key] for key in ("url", "project")}
    raw["tracker"] = {**named, "kind": "github-issues", **settings}
    if forge_kind == "local":
        raw["forge"] = {**(raw.get("forge") or {}), "kind": "local"}
    (folder / "pack.yaml").write_text(yaml.safe_dump(raw, sort_keys=False, allow_unicode=True), encoding="utf-8")
    return str(folder / "pack.yaml")


def _made(tmp_path, pack_file, forge_kind, monkeypatch, **settings):
    """(the pack, its tracker): over the stand-in `gh`, or over the forge kept in files."""
    file = _issues_pack(tmp_path, pack_file, forge_kind, **settings)
    monkeypatch.setenv("COCKPIT_PACK", file)
    pack = load(file)
    made = tracker.tracker_for(pack)
    assert type(made) is GitHubIssuesTracker and made.forge.kind == forge_kind
    if forge_kind == "github":
        fake_gh.setup(me=made.forge.human_login, repos=[made.forge.repo(made.repo)])
    return pack, made


def _theirs(made, number: int, body: str, who: str = "reporter") -> str:
    """A comment someone else wrote on the issue. Its id."""
    if made.forge.kind == "local":
        return str(made.forge.add_issue_comment(made.repo, number, body, author=who)["id"])
    return str(fake_gh.issue_comment(made.forge.repo(made.repo), number, who, body))


def _new(made, summary="The export has no header", **more) -> str:
    return made.create({"ticket": "", "payload": {"summary": summary, **more}}, {})[2]["key"]


def _ready(pack, ticket, kind, payload):
    from cockpitlib.outbox import create, endorse

    return endorse(
        create(pack, ticket, kind, "c", "tracker", payload)["id"], "low", "", "gatekeeper", "fixture-a", "fixture-large"
    )


@pytest.mark.parametrize("forge_kind", FORGES)
@pytest.mark.parametrize("pack_file", PACKS)
def test_a_ticket_key_is_the_number_of_an_issue_and_any_other_key_is_refused(
    bare, pack_file, forge_kind, tmp_path, monkeypatch
):
    pack, made = _made(tmp_path, pack_file, forge_kind, monkeypatch)
    project, repo = pack["tracker"]["project"], pack["repos"]["repos"][0]["name"]
    assert (made.kind, made.project, made.repo, made.noun) == (
        "github-issues",
        project,
        repo,
        "issue",
    ) and made.me() == made.forge.me() != ""
    url, out, kept = made.create(
        {"ticket": "", "payload": {"summary": f"The first of {pack['name']}", "project": project}}, {}
    )
    key = kept["key"]
    number = made.number(key)
    assert key == f"{project}-{number}" == made.key(number) and out == f"{key} · read back"
    assert url == made.browse_url(key) == made.forge.issue_url(repo, number) == tracker.browse(pack, key)
    assert (
        url.endswith(f"/{made.forge.org}/{repo}/issues/{number}")
        and made.comment_url(key, 5) == f"{url}#issuecomment-5"
    )
    assert made.summary(key) == f"The first of {pack['name']}" and made.status(key) == "Open"
    assert tracker.titles(pack, [key], refresh=True) == {key: f"The first of {pack['name']}"}
    for bad in (
        f"{project}-0",
        f"{project}-0{number}",
        f"{project}-",
        f"{project}-{number}a",
        f"OTHER-{number}",
        str(number),
        f"{project}-+{number}",
        f"{project}--{number}",
        f"{project.lower()}-{number}",
        "",
    ):
        for ask in (
            lambda: made.summary(bad),
            lambda: made.status(bad),
            lambda: made.comments(bad),
            lambda: made.browse_url(bad),
            lambda: made.comment({"ticket": bad, "payload": {"body": "x"}}, {}),
            lambda: made.transition({"payload": {"to": "Closed"}}, {}, bad),
        ):
            with pytest.raises(
                CockpitError, match=f"is not a ticket of the github-issues tracker: its tickets are {project}-<n>"
            ):
                ask()
    assert made.statuses([key, f"{project}-0", f"{project}-{number + 50}"]) == {key: "Open"}
    for ask in (
        lambda: made.summary(f"{project}-{number + 50}"),
        lambda: made.comment({"ticket": f"{project}-{number + 50}", "payload": {"body": "x"}}, {}),
    ):
        with pytest.raises(CockpitError):  # an issue that is not there is never invented
            ask()
    with pytest.raises(CockpitError, match="it has no project OTHER"):
        made.create({"payload": {"summary": "Elsewhere", "project": "OTHER"}}, {})


@pytest.mark.parametrize("forge_kind", FORGES)
def test_a_pull_request_is_not_a_ticket(env, forge_kind, tmp_path, monkeypatch):
    pack, made = _made(tmp_path, PACKS[0], forge_kind, monkeypatch)
    if forge_kind == "local":
        number = made.forge.create_pr(made.repo, "A change", "", "work/one", "main")["number"]
    else:
        number = fake_gh.pull(made.forge.repo(made.repo), 4, "work/one", "0" * 40, title="A change")["number"]
    key = made.key(number)
    for ask in (
        lambda: made.summary(key),
        lambda: made.comment({"ticket": key, "payload": {"body": "x"}}, {}),
        lambda: made.transition({"payload": {"to": "Closed"}}, {}, key),
    ):
        with pytest.raises(CockpitError, match=f"#{number} is a pull request, not an issue"):
            ask()
    assert made.forge.comments(made.repo, number) == [] and _new(made) == made.key(number + 1), (
        "the two count on together"
    )


@pytest.mark.parametrize("forge_kind", FORGES)
@pytest.mark.parametrize("pack_file", PACKS)
def test_a_status_is_the_issues_state_or_the_first_label_that_goes_with_that_state(
    bare, pack_file, forge_kind, tmp_path, monkeypatch
):
    _pack, plain = _made(tmp_path / "plain", pack_file, forge_kind, monkeypatch)
    key = _new(plain, labels=["in progress", "done"])
    assert plain.known() == ["Open", "Closed"] and plain.status(key) == "Open", (
        "a label is a status only when the pack says so"
    )
    plain.forge.update_issue(plain.repo, plain.number(key), {"state": "closed"})
    assert plain.status(key) == "Closed"
    _pack, made = _made(
        tmp_path / "labelled", pack_file, forge_kind, monkeypatch, status_labels=LABELS, closed_statuses=["Done"]
    )
    assert made.known() == ["In Progress", "In Review", "Done", "Open", "Closed"]
    key = _new(made, labels=["bug", "in review", "in progress"])
    number = made.number(key)
    assert made.status(key) == "In Progress", "the pack's order decides, not the issue's"
    made.forge.set_labels(made.repo, number, ["bug", "In Review"])
    assert made.status(key) == "In Review", "a label is the same in any case"
    made.forge.update_issue(made.repo, number, {"state": "closed"})
    assert made.status(key) == "Closed", "an issue closed on the forge is closed whatever label it still carries"
    made.forge.set_labels(made.repo, number, ["done", "in review"])
    assert made.status(key) == "Done" and made.statuses([key]) == {key: "Done"}
    made.forge.update_issue(made.repo, number, {"state": "open"})
    assert made.status(key) == "In Review", "a closed status is not an open issue's"
    made.forge.set_labels(made.repo, number, ["done"])
    assert made.status(key) == "Open"


@pytest.mark.parametrize("forge_kind", FORGES)
@pytest.mark.parametrize("pack_file", PACKS)
def test_a_move_sets_the_status_label_takes_the_others_off_and_opens_or_closes_the_issue(
    bare, pack_file, forge_kind, tmp_path, monkeypatch
):
    pack, made = _made(tmp_path, pack_file, forge_kind, monkeypatch, status_labels=LABELS, closed_statuses=["Done"])
    me = made.me()
    url, out, kept = made.create(
        {"payload": {"summary": "A report", "labels": ["bug"], "assignee": "me", "transition": "in progress"}}, {}
    )
    key = kept["key"]
    number = made.number(key)

    def seen():
        found = made.forge.issue(made.repo, number)
        return found["state"], found["labels"], made.status(key)

    assert out == f"{key}; in progress → In Progress (status now In Progress) · read back" and url == made.browse_url(
        key
    )
    assert seen() == ("open", ["bug", "in progress"], "In Progress") and made.forge.issue(made.repo, number)[
        "assignees"
    ] == [me]

    def move(to, **more):
        return made.transition({"ticket": key, "payload": {"to": to, **more}}, {}, key)

    assert move("In Review") == (url, "In Review → In Review (status now In Review)", {}) and seen() == (
        "open",
        ["bug", "in review"],
        "In Review",
    )
    assert move("done")[1] == "done → Done (status now Done)" and seen() == ("closed", ["bug", "done"], "Done")
    assert move("Done")[1] == f"{key} is already Done" and seen() == ("closed", ["bug", "done"], "Done")
    assert move("open")[1] == "open → Open (status now Open)" and seen() == ("open", ["bug"], "Open")
    made.forge.add_labels(made.repo, number, ["in review", "done"])
    assert move("Closed")[1] == "Closed → Closed (status now Closed)" and seen() == ("closed", ["bug"], "Closed")
    assert move("In Progress", assignee="ann")[1] == "In Progress → In Progress (status now In Progress); assigned ann"
    assert seen() == ("open", ["bug", "in progress"], "In Progress") and made.forge.issue(made.repo, number)[
        "assignees"
    ] == ["ann"]
    with pytest.raises(
        CockpitError,
        match=re.escape("'Shipped' is not a status; it has ['In Progress', 'In Review', 'Done', 'Open', 'Closed']"),
    ):
        move("Shipped")
    dry = tracker.tracker_for(pack, dry_run=True)
    assert dry.transition({"payload": {"to": "Done", "assignee": "me"}}, {}, key) == (
        url,
        f"would move {key} → Done; assigned me",
        {},
    )
    assert dry.create({"payload": {"summary": "Not made", "body": "x"}}, {}) == (
        "",
        f"would create {made.project} 'Not made'",
        {},
    )
    assert dry.comment({"ticket": key, "payload": {"body": "Not sent."}}, {}) == (url, f"would be posted on {key}", {})
    assert len(dry.writes) == 5 and dry.writes is dry.forge.writes, (
        "the label, the state, the person, the issue and the comment: kept, none sent"
    )
    assert seen() == ("open", ["bug", "in progress"], "In Progress") and made.comments(key) == []


@pytest.mark.parametrize("forge_kind", FORGES)
@pytest.mark.parametrize("pack_file", PACKS)
def test_tracker_intents_are_published_to_the_issues_and_the_ticket_one_makes_is_moved_by_the_next(
    env, pack_file, forge_kind, tmp_path, monkeypatch
):
    from cockpitlib.intents import load as load_intent
    from cockpitlib.outbox import create, endorse
    from cockpitlib.publish import execute

    pack, made = _made(tmp_path, pack_file, forge_kind, monkeypatch, status_labels=LABELS, closed_statuses=["Done"])
    if forge_kind == "local":
        monkeypatch.setenv("PATH", "/usr/bin:/bin")  # no forge CLI is on the path, and none is asked for
    ticket = f"{pack['tracker']['project']}-7401"
    first = _ready(
        pack,
        ticket,
        "tracker-create",
        {"summary": f"Made for {pack['name']}", "body": "What is wrong.", "labels": ["bug"]},
    )
    moved = endorse(
        create(pack, ticket, "tracker-transition", "c", "m", {"to": "In Review", "issue_from": first["id"]})["id"],
        "low",
        "",
        "gatekeeper",
        "fixture-a",
        "fixture-large",
    )
    assert moved["payload"]["after"] == first["id"]
    receipt = execute(load_intent(moved["id"]), pack=pack)
    assert receipt["ok"], receipt
    source = load_intent(first["id"])
    key = source["receipt_steps"]["key"]["value"]
    number = made.number(key)
    assert (
        source["status"] == "published"
        and source["payload"]["key"] == key
        and source["receipt"]["url"] == made.browse_url(key)
    )
    assert (
        source["receipt"]["output"] == f"{key} · read back"
        and receipt["output"] == "In Review → In Review (status now In Review)"
    )
    found = made.forge.issue(made.repo, number)
    assert (found["title"], found["body"], found["labels"], found["state"]) == (
        f"Made for {pack['name']}",
        "What is wrong.",
        ["bug", "in review"],
        "open",
    )
    unmade = _ready(pack, ticket, "tracker-create", {"summary": "later"})
    early = create(pack, ticket, "tracker-transition", "c", "m", {"to": "Done", "issue_from": unmade["id"]})
    early["payload"]["after"] = ""
    early = endorse(early["id"], "low", "", "gatekeeper", "fixture-a", "fixture-large")
    early["payload"]["after"] = ""
    assert "has no key yet" in execute(early, pack=pack)["error"]
    # a comment in Markdown, as written; then the same comment edited in place by the intent that follows it
    note = env["workspace"] / "note.md"
    note.write_text("Run for the first build: **Not Ok**\n\n- [ ] the header\n", encoding="utf-8")
    said = _ready(pack, ticket, "tracker-comment", {"issue": key, "body_file": str(note), "probe_title": "Run for"})
    posted = execute(said, pack=pack)
    made_id = load_intent(said["id"])["receipt_steps"]["comment"]["value"]
    assert (
        posted["ok"]
        and posted["output"] == f"posted on {key} (comment {made_id}, read back)"
        and posted["url"] == made.comment_url(key, made_id)
    )
    assert [row["text"] for row in made.comments(key)] == ["Run for the first build: **Not Ok**\n\n- [ ] the header"]
    twin = execute(
        _ready(pack, ticket, "tracker-comment", {"issue": key, "body": "Run for it again", "probe_title": "run for"}),
        pack=pack,
    )
    assert not twin["ok"] and f"{key} already has a comment starting with 'run for' (id {made_id})" in twin["error"]
    again = execute(
        _ready(
            pack,
            ticket,
            "tracker-comment",
            {"issue": key, "body": "Run for the second build: Ok", "comment_from": said["id"]},
        ),
        pack=pack,
    )
    assert again["ok"] and again["output"] == f"updated on {key} (comment {made_id}, read back)"
    assert [(row["id"], row["text"]) for row in made.comments(key)] == [(made_id, "Run for the second build: Ok")]
    assert made.find_comment(key, "run for") == made_id and made.find_comment(key, "Nothing like it") == ""
    gone = execute(
        _ready(pack, ticket, "tracker-comment", {"issue": key, "body": "x", "comment_id": "999999"}), pack=pack
    )
    assert not gone["ok"] and f"{key} has no comment 999999" in gone["error"]
    dry = execute(_ready(pack, ticket, "tracker-transition", {"issue": key, "to": "Done"}), pack=pack, dry_run=True)
    assert (
        dry["ok"]
        and dry["output"] == f"would move {key} → Done"
        and len(dry["actions"]) == 2
        and made.status(key) == "In Review"
    )


@pytest.mark.parametrize("forge_kind", FORGES)
@pytest.mark.parametrize("pack_file", PACKS)
def test_an_intent_that_needs_what_issues_do_not_have_is_refused_when_it_is_written(
    env, pack_file, forge_kind, tmp_path, monkeypatch
):
    from cockpitlib.intents import all_intents
    from cockpitlib.outbox import create

    pack, made = _made(tmp_path, pack_file, forge_kind, monkeypatch)
    ticket = f"{pack['tracker']['project']}-7402"
    key = _new(made)
    evidence = env["workspace"] / pack["records_dir"] / "qa" / ticket / "row-1.png"
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_bytes(b"picture")
    assert (
        made.capabilities()
        == trackers.offers(pack["tracker"])
        == tracker.capabilities(pack)
        == frozenset(
            {
                base.SUMMARY,
                base.STATUS,
                base.COMMENTS,
                base.IDENTITY,
                base.COMMENT,
                base.EDIT_COMMENT,
                base.CREATE,
                base.TRANSITION,
                base.ASSIGNEE,
            }
        )
    )
    for kind, payload, capability in (
        ("tracker-comment", {"issue": key, "body": "See row-1.png", "attach": [str(evidence)]}, base.ATTACHMENTS),
        ("tracker-create", {"summary": "In a sprint", "sprint": "active"}, base.SPRINT),
        ("tracker-create", {"summary": "Of a component", "component": "export"}, base.COMPONENT),
    ):
        with pytest.raises(
            CockpitError,
            match=re.escape(
                f"the pack's tracker (github-issues) has no {capability}: this {kind} cannot be published to it"
            ),
        ):
            create(pack, ticket, kind, "c", "tracker", payload)
    assert all_intents(ticket) == [], "nothing was written"
    # and the tracker itself refuses by the same name, whoever asks
    for ask, capability in (
        (lambda: made.comment({"ticket": key, "payload": {"body": "x", "attach": ["a.png"]}}, {}), base.ATTACHMENTS),
        (lambda: made.create({"payload": {"summary": "x", "sprint": "active"}}, {}), base.SPRINT),
        (lambda: made.create({"payload": {"summary": "x", "component": "export"}}, {}), base.COMPONENT),
        (lambda: made.create({"payload": {"summary": "x", "attach": ["a.png"]}}, {}), base.ATTACHMENTS),
        (lambda: made.reachable(key, "Closed"), base.TRANSITION_THROUGH),
    ):
        with pytest.raises(base.Unsupported, match=f"the github-issues tracker has no {capability}"):
            ask()
    assert made.comments(key) == [] and made.status(key) == "Open"


@pytest.mark.parametrize("forge_kind", FORGES)
@pytest.mark.parametrize("pack_file", PACKS)
def test_the_comment_watch_notes_someone_elses_comment_on_an_issue_and_not_the_packs_own(
    bare, pack_file, forge_kind, tmp_path, monkeypatch
):
    from cockpitlib import tracker_watch
    from cockpitlib.kanban import place_card
    from cockpitlib.outbox import create

    pack, made = _made(tmp_path, pack_file, forge_kind, monkeypatch)
    ticket = _new(made, "A finished ticket")
    number = made.number(ticket)
    _theirs(made, number, "Before the watch.")
    card = place_card(pack["board"], f"{ticket}: tester", "tester-1", "ready")
    create(pack, ticket, "ticket-done", card, "test run finished", {"numbers": ["3"]})
    assert tracker_watch.watch(pack, now=1000.0)["read"] == [ticket] and tracker_watch.rows() == []
    ours = made.comment({"ticket": ticket, "payload": {"body": "A post of our own."}}, {})[2]["comment"]
    said = _theirs(made, number, "It still fails on the second page.")
    out = tracker_watch.watch(pack, now=1400.0)
    assert out["read"] == [ticket] and len(out["notes"]) == 1 and out["errors"] == []
    row = tracker_watch.rows()[0]
    assert (row["comment"], row["kind"], row["author"], row["text"]) == (
        said,
        "new",
        "reporter",
        "It still fails on the second page.",
    )
    assert row["url"] == f"{made.browse_url(ticket)}#issuecomment-{said}" and tracker_watch._state()["me"] == made.me()
    made.comment({"ticket": ticket, "payload": {"body": "A post of our own, corrected.", "comment_id": ours}}, {})
    assert tracker_watch.watch(pack, now=1800.0)["notes"] == [], "an edit of our own is not news either"
    rows = made.comments(ticket)
    assert [row["account"] for row in rows] == ["reporter", made.me(), "reporter"]
    assert sorted(row["id"] for row in made.comments(ticket, since=rows[2]["created"])) == sorted([said, ours]), (
        "the later one, and the one edited since"
    )
    assert [row["id"] for row in made.comments(ticket, since="not a moment")] == [row["id"] for row in rows]


@pytest.mark.parametrize("pack_file", PACKS)
def test_the_issue_trackers_settings_are_checked_when_the_pack_loads(tmp_path, pack_file):
    first = load(pack_file)["repos"]["repos"]
    good = load(
        _issues_pack(
            tmp_path / "good",
            pack_file,
            repo=first[-1]["name"],
            status_labels=LABELS,
            closed_statuses=["Done"],
            browse_url="https://issues.example.test/{project}/{number}",
        )
    )
    made = tracker.tracker_for(good)
    assert made.repo == first[-1]["name"] and list(made.labels) == list(LABELS) and made.closed == ["Done"]
    assert (
        made.browse_url(f"{made.project}-12")
        == f"https://issues.example.test/{made.project}/12"
        == tracker.browse(good, f"{made.project}-12")
    )
    assert made.comment_url(f"{made.project}-12", 3) == f"https://issues.example.test/{made.project}/12#issuecomment-3"
    assert tracker.tracker_for(load(_issues_pack(tmp_path / "plain", pack_file))).repo == first[0]["name"]
    bad = (
        ({"repo": "no-such-repo"}, "tracker.repo names a repo of repos.yaml"),
        ({"repo": 3}, "tracker.repo names a repo of repos.yaml"),
        ({"repo": ""}, "tracker.repo names a repo of repos.yaml"),
        ({"status_labels": ["in progress"]}, "tracker.status_labels maps a status name to the label"),
        ({"status_labels": {}}, "tracker.status_labels maps a status name to the label"),
        ({"status_labels": {"Doing": ""}}, "tracker.status_labels maps a status name to the label"),
        ({"status_labels": {"Doing": 3}}, "tracker.status_labels maps a status name to the label"),
        ({"status_labels": {"Doing": "wip", "doing": "busy"}}, "tracker.status_labels maps a status name to the label"),
        (
            {"status_labels": {"Doing": "wip", "Checking": "WIP"}},
            "tracker.status_labels maps a status name to the label",
        ),
        ({"status_labels": {"Closed": "done"}}, "tracker.status_labels maps a status name to the label"),
        ({"status_labels": {"open": "todo"}}, "tracker.status_labels maps a status name to the label"),
        ({"closed_statuses": ["Done"]}, "tracker.closed_statuses lists statuses of tracker.status_labels"),
        (
            {"status_labels": LABELS, "closed_statuses": "Done"},
            "tracker.closed_statuses lists statuses of tracker.status_labels",
        ),
        (
            {"status_labels": LABELS, "closed_statuses": ["Shipped"]},
            "tracker.closed_statuses lists statuses of tracker.status_labels",
        ),
        ({"browse_url": "https://issues.example.test/all"}, "tracker.browse_url is a ticket's page"),
    )
    for index, (settings, message) in enumerate(bad):
        with pytest.raises(PackError, match=message):
            load(_issues_pack(tmp_path / f"bad-{index}", pack_file, **settings))
    for index, key in enumerate(
        ("repo", "status_labels", "closed_statuses")
    ):  # a setting of this kind is no other kind's
        file = _issues_pack(
            tmp_path / f"other-{index}",
            pack_file,
            **{key: {"repo": first[0]["name"], "status_labels": LABELS, "closed_statuses": []}[key]},
        )
        raw = yaml.safe_load(open(file, encoding="utf-8"))
        raw["tracker"]["kind"] = "local"
        open(file, "w", encoding="utf-8").write(yaml.safe_dump(raw, sort_keys=False))
        with pytest.raises(PackError, match=f"tracker.{key} is for tracker.kind github-issues"):
            load(file)


@pytest.mark.parametrize("pack_file", PACKS)
def test_a_pack_whose_tickets_are_issues_needs_no_tracker_url_and_fences_no_other_host(tmp_path, pack_file):
    from cockpitlib import egress

    file = _issues_pack(tmp_path, pack_file, "github")
    raw = yaml.safe_load(open(file, encoding="utf-8"))
    url = raw["tracker"].pop("url")
    open(file, "w", encoding="utf-8").write(yaml.safe_dump(raw, sort_keys=False))
    pack = load(file)
    made = tracker.tracker_for(pack)
    assert "url" not in pack["tracker"] and made.browse_url(f"{made.project}-3").startswith("https://github.com/")
    assert egress.forge_hosts(pack) == ["github.com"], (
        "the tracker is on the forge's own host: nothing is added, nothing is taken out"
    )
    assert egress.forge_hosts(load(_issues_pack(tmp_path / "with", pack_file, "github")))[-1] == url.split("//")[1]
    raw["tracker"] = {"kind": "local", "project": raw["tracker"]["project"]}
    open(file, "w", encoding="utf-8").write(yaml.safe_dump(raw, sort_keys=False))
    with pytest.raises(PackError, match=re.escape("missing tracker.url")):
        load(file)
    raw["tracker"] = ["github-issues"]
    open(file, "w", encoding="utf-8").write(yaml.safe_dump(raw, sort_keys=False))
    with pytest.raises(PackError, match="^tracker "):
        load(file)


def test_the_tracker_is_made_with_its_pack_and_says_what_it_is_missing(bare, tmp_path, monkeypatch):
    pack = load(_issues_pack(tmp_path, PACKS[0]))
    config = tracker._config(pack)
    repo = pack["repos"]["repos"][0]["name"]
    assert (
        trackers.kind_of(config) == "github-issues"
        and "github-issues" in trackers.NAMES
        and trackers.implementation("github-issues") is GitHubIssuesTracker
    )
    assert type(trackers.make(config, pack=pack)) is GitHubIssuesTracker and trackers.make(config, True, pack).dry_run
    with pytest.raises(
        CockpitError,
        match="tracker.repo names the repo whose issues are the tickets, one of repos.yaml \\(none listed\\)",
    ):
        trackers.make(config)  # made of its settings alone, it has no repo to look in
    with pytest.raises(CockpitError, match="tracker.repo names the repo whose issues are the tickets"):
        trackers.make({**config, "repo": "elsewhere"}, pack=pack)
    with pytest.raises(CockpitError, match="tracker.kind github-issues needs tracker.project"):
        trackers.make({**config, "project": ""}, pack=pack)
    assert (
        tracker.browse({**pack, "tracker": {**pack["tracker"], "project": ""}}, "TASK-4")
        == f"{config['url']}/browse/TASK-4"
    ), "a tracker that cannot be made still has the page its settings spell"
    forge = LocalForge(pack, root=str(tmp_path / "forge"))
    assert GitHubIssuesTracker(config, pack=pack, forge=forge).forge is forge
    monkeypatch.setattr(LocalForge, "capabilities", lambda self: frozenset({"pull-requests"}))
    with pytest.raises(
        CockpitError,
        match=re.escape(
            "the pack's forge (local) has no issues: tracker.kind github-issues needs a forge that has them"
        ),
    ):
        GitHubIssuesTracker(config, pack=pack, forge=forge)
    assert GitHubIssuesTracker.offers(config) == frozenset(GitHubIssuesTracker.HAS) and repo


def test_a_write_the_forge_does_not_show_afterwards_is_a_failed_read_back(bare, tmp_path, monkeypatch):
    pack = load(_issues_pack(tmp_path, PACKS[0], status_labels=LABELS))
    made = tracker.tracker_for(pack)
    key = _new(made)
    with monkeypatch.context() as patch:
        patch.setattr(
            LocalForge, "add_issue_comment", lambda self, repo, number, body: {"id": 77}
        )  # a forge that takes the write and keeps nothing
        with pytest.raises(CockpitError, match="read-back: the comment is not readable after the post"):
            made.comment({"ticket": key, "payload": {"body": "x"}}, {})
        patch.setattr(LocalForge, "add_issue_comment", lambda self, repo, number, body: {})
        with pytest.raises(CockpitError, match="read-back: the comment is not readable after the post"):
            made.comment({"ticket": key, "payload": {"body": "x"}}, {})
    with monkeypatch.context() as patch:
        patch.setattr(LocalForge, "update_issue", lambda self, repo, number, fields: {})
        with pytest.raises(CockpitError, match=f"read-back: {key} is 'Open' after the move to 'Closed'"):
            made.transition({"payload": {"to": "Closed"}}, {}, key)
        patch.setattr(LocalForge, "assign", lambda self, repo, number, logins: None)
        with pytest.raises(CockpitError, match=f"read-back: {key} is not assigned to ann"):
            made.transition({"payload": {"to": "In Review", "assignee": "ann"}}, {}, key)
    real = LocalForge.create_issue
    with monkeypatch.context() as patch:
        patch.setattr(LocalForge, "create_issue", lambda self, repo, title, body, labels=(), assignees=(): {})
        with pytest.raises(CockpitError, match="the forge made no issue number"):
            made.create({"payload": {"summary": "Two"}}, {})
        patch.setattr(
            LocalForge,
            "create_issue",
            lambda self, repo, title, body, labels=(), assignees=(): real(self, repo, title + "!", body),
        )
        with pytest.raises(
            CockpitError, match="read-back: TASK-[0-9]+ does not carry the summary, labels, assignee it was made with"
        ):
            made.create({"payload": {"summary": "Three", "labels": ["bug"], "assignee": "ann"}}, {})


def test_a_forge_without_issues_refuses_each_issue_operation_by_the_capabilitys_name(bare, tmp_path):
    from cockpitlib import forges
    from cockpitlib.forges import base as forge_base

    class Bare(forge_base.Forge):
        kind = "bare"

        def url(self, repo, number=None):
            return f"https://forge.example.test/{repo}"

    forge = Bare()
    assert (
        forge_base.ISSUES not in forge.capabilities()
        and forge.issue_url("api", 7) == "https://forge.example.test/api/issues/7"
    )
    for ask in (
        lambda: forge.issue("api", 1),
        lambda: forge.create_issue("api", "t", "b"),
        lambda: forge.update_issue("api", 1, {"state": "closed"}),
        lambda: forge.issue_comments("api", 1),
        lambda: forge.add_issue_comment("api", 1, "b"),
        lambda: forge.edit_issue_comment("api", 1, "b"),
    ):
        with pytest.raises(forge_base.Unsupported, match="the bare forge has no issues"):
            ask()

    class Old:
        """A forge from before the protocol: it answers REST paths, and an issue it does not know as an empty answer."""

        org, human_login, dry_run, writes = "old", "dev", False, []

        def get(self, path):
            return {}

    with pytest.raises(CockpitError, match="no issue old/api#3"):
        forges.seam(Old()).issue("api", 3)
    local = LocalForge({"forge": {"org": "example"}}, root=str(tmp_path / "forge"))
    number = local.create_issue("api", "A report", "", author="reporter")["number"]
    said = local.add_issue_comment("api", number, "As it is.", author="reporter")
    assert local.issue("api", number)["author"] == "reporter" == said["author"]
    assert local.issue_comments("api", number, since="not a moment") == [said], (
        "a since that cannot be read leaves no comment out"
    )
    assert local.issue_comments("api", number, since="2999-01-01T00:00:00Z") == []
