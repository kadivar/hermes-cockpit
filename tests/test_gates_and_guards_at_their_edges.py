# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Gates and guards at their edges: the write check keeps its old floor, the plan gate counts only the human's
go after the plan, an outside go covers only outside work, a re-review that starts no card keeps the human's review, the bump
guard reads the batch the way the sequence does, and the smaller fixes beside them. Both fixture packs."""

import base64
import os
import shutil
import sqlite3
import subprocess
import time

import pytest
import yaml

from cockpitlib.errors import CockpitError, PackError
from cockpitlib.pack import load

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PACKS = (os.path.join(ROOT, "packs", "acme", "pack.yaml"), os.path.join(ROOT, "packs", "bravo", "pack.yaml"))


def _copy_pack(pack_file, tmp_path, change) -> str:
    copied = tmp_path / "packs" / os.path.basename(os.path.dirname(pack_file))
    shutil.copytree(os.path.dirname(pack_file), copied)
    data = yaml.safe_load((copied / "pack.yaml").read_text(encoding="utf-8"))
    change(data, copied)
    (copied / "pack.yaml").write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    return str(copied / "pack.yaml")


def _client():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from dashboard.cockpit.router import router

    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def _comment(board, card, author, body, at=None):
    from cockpitlib.kanban import BoardWrites

    writes = BoardWrites(board)
    writes.comment(card, author, body)
    writes.flush()
    if at is not None:
        from tests.support.boards import raw

        connection = raw(board)
        connection.execute(
            "update task_comments set created_at = ? where task_id = ? and body = ?", (int(at), card, body)
        )
        connection.commit()
        connection.close()


@pytest.mark.parametrize("pack_file", PACKS)
def test_a_read_only_seat_cannot_write_outside_its_roots_by_any_shell_form(env, pack_file, monkeypatch):
    from cockpitlib import egress
    from cockpitlib.paths import qa

    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    monkeypatch.setenv("COCKPIT_LANE", "reviewer-1")
    pack = load(pack_file)
    mine = os.path.join(qa(), "T-1")
    os.makedirs(mine, exist_ok=True)
    refused = [
        "cd /tmp\necho x > /etc/f",
        "cd /tmp & echo x > /etc/f",
        "cd . > /etc/f",
        "echo x | timeout 5 tee /etc/f",
        "echo x | xargs tee /etc/f",
        f"cd {mine}; cd; echo x >> .bashrc",
        f"cd {mine}; pushd /etc; echo x > f",
        f"cd {mine} | cat; echo x > f",
        f"false && cd {mine}; echo x > f",
        f"cd {mine}; cd -P /etc; echo x > f",
        "export COCKPIT_TEST_ROOT=/etc; echo x > $COCKPIT_TEST_ROOT/f",
        f"(cd {mine} && echo x > f)",
        "cmd 2>/etc/e",
        "cmd &> /etc/h",
        "echo x >/etc/g",
    ]
    for command in refused:
        assert egress._readonly_write(command, pack) == "blocked", command
        assert egress.explained("blocked").startswith("blocked: a write"), command
    allowed = [
        f"cd {mine} && npm test > out.log",
        f"cd {mine} && a | tee -a log.txt",
        f"echo ok > {mine}/out.log",
        f"cd {mine} && a | b > r.txt",
        f"cmd > {mine}/o 2>&1",
        # a cd that runs into a folder that exists holds for every later command, as the shell does
        f"cd {mine}; npm test > out.log",
        f"cd {mine}\nnpm test > out.log",
        f"cd {mine} || exit 1; cmd > out",
        # a cockpit-only pack's own forms: quoted > and tee are data, here-documents are data, $VAR and mkdir -p folders are followed
        "docker exec app-1 php cli.php --execute='echo App\\Models\\Order::find(5)->title;'",
        f"jq '.[] | select(.n>0)' {mine}/x.json",
        "awk 'NR>1' report.csv | wc -l",
        "grep -rn tee src/",
        "echo '<b>x</b>'",
        f"cat > {mine}/notes.md <<'EOF'\n# Notes\n> a quote\ncd app && npm test > out.txt\nEOF",
        "cd $COCKPIT_TEST_QA; cp /tmp/m.png evidences/1.png",
        f"mkdir -p {mine}/run_2/evidences; cd {mine}/run_2; cp /tmp/m.png evidences/1.png",
        f"cd {mine} && echo $(date) > stamp.txt",
        f"git log | tee {mine}/log.txt",
    ]
    monkeypatch.setenv("COCKPIT_TEST_QA", mine)
    assert (
        egress._readonly_write(f"cd {mine}-missing && a > o; b > p", pack) == "blocked"
    )  # past a failed chain: unknown
    for command in allowed:
        assert egress._readonly_write(command, pack) == "", command
    # code is no shell line: read as before (a > with no space in it is no redirect); a file tool's path is checked whole
    assert egress.check_tool("execute_code", {"code": "print([r for r in [1, 2] if r>1])"}) == ""
    assert egress.check_tool("browser_console", {"expression": "[...rows].filter(r=>r.cells.length>2)"}) == ""
    assert (
        egress.check_tool("write_file", {"path": f"{mine}/a(/../../../../../../../../tmp/evil", "content": "x"})
        == "blocked"
    )


@pytest.mark.parametrize("pack_file", PACKS)
def test_code_redirects_count_only_when_they_name_a_path(bare, pack_file, monkeypatch):
    from cockpitlib import egress

    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    monkeypatch.setenv("COCKPIT_LANE", "tester-1")
    pack = load(pack_file)
    cleared = [
        'js("(() => { x })()")',
        "rows.map(r => r.id)",
        "rows.map(r => /a/.test(r))",
        "ptr -> x",
        "if a > 0:",
        "ul > li",
        "<div> text</div>",
        "y > rect.top)",
        "a > b.size)",
        "x > $(el)",
        "Promise<void> {",
        "a > ...)",
        "a >> b",
        "x >> 2",
        'print("a => { b")',
        "(a) =>> /x",
    ]
    for code in cleared:
        assert egress._readonly_write(code, pack, shell=False) == "", code
        assert egress.check_bound(code, shell=False) == "", code
    assert egress.check_tool("browser_console", {"expression": 'js("(() => { x })()")'}) == ""
    # a real redirect in code names a path, and every other write form reads as it did
    refused = [
        'os.system("echo x > /etc/p")',
        'os.system("echo x >> /a/b")',
        'os.system("cmd 2> /a")',
        'run("echo x > ~/p")',
        'run("echo x > ../p")',
        'run("echo x > ./p")',
        'run("echo x > $HOME/p")',
        'run("echo x > ${HOME}/p")',
        'run("cd /repo && echo x > app/Foo.php")',
        'run("echo x > Foo.php")',
        'run("echo x >> .env")',
        'run(f"echo x > {path}")',
        'run("echo x > $OUT")',
        'run("cat > /etc/p<<EOF")',
        'run("cat > app/F.php<<EOF")',
        'run("sort > /etc/p</etc/q")',
        'run("echo x > app.module.ts")',
        'run("echo x > foo.test.ts")',
        'run("cd /repo && echo x > Makefile")',
        "run('echo x > \"$OUT\"')",
        "run(\"echo x > '/etc/p'\")",
        'run("echo x > \\"/etc/p\\"")',
        "tee /etc/x",
        "cp a /etc/x",
        "mv a /etc/x",
        "install a /etc/x",
        "rsync a /etc/x",
        "ln -s a /etc/x",
        "sed -i s/a/b/ /etc/x",
        "perl -pi -e s/a/b/ /etc/x",
        "dd if=/dev/zero of=/etc/x",
        "truncate -s 0 /etc/x",
    ]
    for code in refused:
        assert egress._readonly_write(code, pack, shell=False) == "blocked", code
        assert egress.explained("blocked").startswith("blocked: a write"), code
    assert egress._write_targets('os.system("echo x > /etc/p")', shell=False)[0].startswith("/etc/p")
    # what code never read before stays unread: a file API is the file tools' fence, not this one
    assert egress._readonly_write("open('/etc/x', 'w').write('y')", pack, shell=False) == ""
    # a shell line, and a shell line too broken to read, keep the reader they had
    assert egress._legacy_targets("rows.map(r => { x })") == ["{"]
    assert egress._legacy_targets("a > 0") == ["0"]
    assert egress._legacy_targets("rows.map(r => { x })", code=True) == []
    assert egress._write_targets("a => { x") == ["{"]
    assert egress._write_targets("a > 0") == ["0"]
    assert egress._write_targets("echo 'a => { x") == ["{"]
    assert egress._readonly_write("a => { x", pack) == "blocked"
    assert egress._readonly_write("echo 'a => { x", pack) == "blocked"
    assert egress._readonly_write("echo x > /etc/p", pack) == "blocked"


@pytest.mark.parametrize("pack_file", PACKS)
def test_a_quoted_operator_is_data_and_an_inner_shell_line_is_read(env, pack_file, monkeypatch):
    from cockpitlib import egress
    from cockpitlib.paths import qa

    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    monkeypatch.setenv("COCKPIT_LANE", "reviewer-1")
    pack = load(pack_file)
    mine = os.path.join(qa(), "T-2")
    os.makedirs(mine, exist_ok=True)
    refused = [
        "sh -c 'echo x > /etc/p'",
        "bash -lc 'echo x > /etc/p'",
        "sudo bash -c 'echo x > /etc/p'",
        "eval 'echo x > /etc/p'",
        'echo "$(echo x > /etc/p)"',
        "echo '<<EOF'\necho x > /etc/p",
        "# <<EOF\necho x > /etc/p",
        "exec 3<> /etc/x",
        "echo a#b > /etc/x",
        "echo x \\\n  > /etc/x",
        "cp -t /etc a b",
        "cp --target-directory=/etc a",
        "echo x | timeout -s KILL 5 tee /etc/x",
        "echo x | sudo -u root tee /etc/x",
        "echo x | sudo -E tee /etc/x",
        f"cd {mine} && sh -c 'cd /etc && echo x > f'",
        # read as bash reads them: a # after $( ) is in the word, 1<<2 is a shift, a quoted here-document keeps its
        # backslash, >& names a file, the command behind sudo or X=1, an unquoted $( ), a nest too deep to read
        "echo $(true)#x > /etc/x",
        "x=$((1<<2))\necho hi > /etc/x",
        "cat <<'EOF'\nx\\\nEOF\necho hi > /etc/x",
        "echo hi >& /etc/x",
        "sudo cp a /etc/x",
        "X=1 cp a /etc/x",
        "sudo sed -i s/a/b/ /etc/x",
        "bash -c -- 'echo > /etc/x'",
        "X=1 cd /etc; echo > x",
        "echo $(cp a /etc/x)",
        'echo "$(echo $(cp a /etc/x))"',
        "eval " * 50 + "echo hi > /etc/x",
    ]
    for command in refused:
        assert egress._readonly_write(command, pack) == "blocked", command
    allowed = [
        "grep -n '>' src/a.ts",
        'rg -c ">" src',
        f"tr -d '>' < a > {mine}/b",
        f"printf '%s\\n' '>' > {mine}/o",
        "git log --format='%h > %s' | head",
        "xargs grep tee notes.txt",
        "echo x # > /etc/x",
        f"echo ${{#x}} > {mine}/n",
        f"cd {mine} && mkdir out && cd out && echo x > y",
        f"cd {mine} && mkdir -pv a/b; cd a/b; echo > z",
        f"cd {mine} && bash -c 'npm test > out.log'",
        f"cat <<-EOF > {mine}/f\n\tbad > /etc/no\n\tEOF",
        # a single-quoted $( ) or backtick never runs; a write to /dev/null changes no file; >&2 is a descriptor
        "rg -n '$(cat > /etc/hosts)' src",
        "git commit -m 'Silence `make >/dev/null` noise'",
        "grep -rn foo . 2>/dev/null",
        "gh pr comment 1 --body 'Run `npm test > /tmp/log`'",
        "echo hi >&2",
        f"echo $((1 << 4))\ncat > {mine}/n <<EOF\nx > /etc/no\nEOF",
    ]
    for command in allowed:
        assert egress._readonly_write(command, pack) == "", command


@pytest.mark.parametrize("pack_file", PACKS)
def test_the_plan_gate_opens_only_on_the_human_s_go_after_the_plan(env, pack_file, monkeypatch):
    from cockpitlib import advise, plan_gate
    from cockpitlib.kanban import place_card

    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    pack = load(pack_file)
    ticket = f"{pack['tracker']['project']}-901"
    card = place_card(pack["board"], f"{ticket}: work", "worker-1", "ready", body="Plan gate: human\n")
    now = time.time()
    _comment(pack["board"], card, "human", "Human: go", at=now - 600)  # an earlier, unrelated question
    advise._record(
        ticket,
        {
            "time": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now - 300)),
            "checkpoint": "C0",
            "verdict": "CHANGES",
            "card": card,
            "reason": "",
            "query": "",
        },
    )
    assert plan_gate.waits(pack, card)
    _comment(pack["board"], card, "worker-1", "Human: go")  # a lane writing the human's words
    assert plan_gate.waits(pack, card)
    _comment(pack["board"], card, "human", "Human: go with changes: keep the endpoint name")
    assert plan_gate.waits(pack, card) == ""


@pytest.mark.parametrize("pack_file", PACKS)
def test_an_in_tool_advisor_line_recorded_after_the_go_does_not_hold_the_plan(env, pack_file, monkeypatch):
    """A cockpit-only pack's advisor runs in the coding tool; its C0 line may be recorded (`advise --said`) after the human answered the plan."""
    from cockpitlib import advise, plan_gate
    from cockpitlib.kanban import BoardWrites, place_card

    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    pack = load(pack_file)
    ticket = f"{pack['tracker']['project']}-912"
    card = place_card(pack["board"], f"{ticket}: work", "worker-1", "ready", body="Plan gate: human\n")
    writes = BoardWrites(pack["board"])
    writes.block(card, "plan ready: the outline is in the plan, waiting for plan ok")
    writes.flush()
    _comment(pack["board"], card, "human", "Human: go")
    advise._record(
        ticket,
        {
            "time": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() + 120)),
            "checkpoint": "C0",
            "verdict": "DEVIATES",
            "card": card,
            "reason": "",
            "query": "",
        },
    )
    assert plan_gate.waits(pack, card) == ""
    worded = place_card(pack["board"], f"{ticket}: work", "worker-1", "ready", body="Plan gate: human\n")
    writes = BoardWrites(pack["board"])
    writes.block(worded, "C0 DEVIATES from the outline: ok?")  # a block that names C0 is the plan's stop too
    writes.flush()
    _comment(pack["board"], worded, "human", "Human: go")
    assert plan_gate.waits(pack, worded) == ""


@pytest.mark.parametrize("pack_file", PACKS)
def test_an_outside_review_s_go_never_starts_a_rework(env, pack_file, monkeypatch):
    from cockpitlib import plugin_api
    from cockpitlib.acts import archive_card
    from cockpitlib.kickoff import OUTSIDE_GO
    from cockpitlib.plan import show

    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    pack = load(pack_file)
    ticket = f"{pack['tracker']['project']}-902"
    started = plugin_api.start_card("review", ticket, pack=pack)
    assert OUTSIDE_GO in show(ticket)
    archive_card(pack, started["card_id"])
    with pytest.raises(CockpitError, match="plan has no decision: the plan was recorded for outside work"):
        plugin_api.start_card("rework", ticket, pack=pack)
    from cockpitlib.plan import init

    init(ticket, "the intake proposal", "go")  # the human's go on an intake plan replaces the outside go
    assert OUTSIDE_GO not in show(ticket)
    assert plugin_api.start_card("rework", ticket, pack=pack)["card_id"]


@pytest.mark.parametrize("pack_file", PACKS)
def test_a_re_review_that_starts_no_card_keeps_the_human_s_review(bare, pack_file, monkeypatch):
    from cockpitlib import outbox, pr_watch
    from cockpitlib.intents import load as load_intent

    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    pack = load(pack_file)
    ticket = f"{pack['tracker']['project']}-903"
    record = {
        "ticket": ticket,
        "repo": "api",
        "number": 8,
        "role": "reviewer",
        "state": "open",
        "head_sha": "b" * 40,
        "url": "",
    }
    pr_watch._write(pr_watch.record_path(ticket, "api", 8), record)
    review = outbox.create(
        pack,
        ticket,
        "pr-review-submit",
        "reviewer-1",
        "my review",
        {"repo": "api", "number": 8, "sha": "a" * 40, "event": "COMMENT", "body": "x"},
    )
    answer = pr_watch.request_rereview(pack, ticket, "api", 8, supersede=review["id"])
    assert answer["ok"] is False and answer["dropped"] == [] and "no review of mine" in answer["out"]
    assert load_intent(review["id"])["status"] != "dropped"


@pytest.mark.parametrize("pack_file", PACKS)
def test_the_bump_guard_reads_the_batch_as_the_sequence_does(env, pack_file):
    from cockpitlib.outbox import _bump_push_problems as problems

    pack = load(pack_file)
    project = pack["tracker"]["project"]
    weekly = {
        **pack,
        "forge": {**(pack.get("forge") or {}), "bump_push_prefix": "dependabot/", "bump_batch": "{project}-{week}"},
    }
    assert problems(weekly, {"ticket": f"{project}-123", "payload": {"branch": "work/x"}}) == []
    assert problems(weekly, {"ticket": f"{project}-2026W44", "payload": {"branch": "work/x"}})
    assert problems(weekly, {"ticket": f"{project}-2026W44", "payload": {"branch": "dependabot/npm/x"}}) == []
    default = {**pack, "forge": {**(pack.get("forge") or {}), "bump_push_prefix": "dependabot/"}}
    default["forge"].pop("bump_batch", None)
    assert problems(default, {"ticket": f"{project}-BUMPS", "payload": {"branch": "work/mine"}})


@pytest.mark.parametrize("pack_file", PACKS)
def test_a_pack_writes_its_own_re_review_job(env, pack_file, monkeypatch, tmp_path):
    from cockpitlib import pr_watch

    path = _copy_pack(
        pack_file,
        tmp_path,
        lambda data, _c: data.setdefault("forge", {}).update(
            rereview_job="Load `local-review`; diff {since}..{head} on {repo}#{number} for {ticket}."
        ),
    )
    monkeypatch.setenv("COCKPIT_PACK", path)
    pack = load(path)
    ticket = f"{pack['tracker']['project']}-904"
    record = pr_watch.normal(
        {
            "ticket": ticket,
            "repo": "api",
            "number": 9,
            "role": "reviewer",
            "state": "open",
            "head_sha": "c" * 40,
            "reviewed_sha": "d" * 40,
            "url": "u",
            "head": "work/x",
        }
    )
    card = pr_watch._rereview(pack, record, time.time(), force=True)
    from cockpitlib.kanban import board_cards

    body = next(item for item in board_cards(pack["board"]) if item["id"] == card)["body"]
    assert "Load `local-review`; diff ddddddddd..ccccccccc on api#9" in body and "pr-review" not in body
    assert "skill" not in pr_watch.REREVIEW_JOB and "git diff {since}..{head}" in pr_watch.REREVIEW_JOB
    with pytest.raises(PackError, match="rereview_job"):
        load(
            _copy_pack(
                pack_file, tmp_path / "bad", lambda data, _c: data.setdefault("forge", {}).update(rereview_job="{nope}")
            )
        )


@pytest.mark.parametrize("pack_file", PACKS)
def test_intake_s_outline_keeps_its_sections_and_plan_words_refuse_what_they_cannot_read(
    bare, pack_file, monkeypatch, tmp_path
):
    from cockpitlib import cli
    from cockpitlib.plan import init, sections, show

    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    pack = load(pack_file)
    ticket = f"{pack['tracker']['project']}-905"
    init(ticket, "", "go")
    init(
        ticket, f"# Plan {ticket}\n\nthe outline\n\n## Scope\n\nthe api\n\n## Steps\n\n1. add it\n", "go", outline=True
    )
    assert {"Scope", "Steps", "Decision"} <= set(sections(ticket)) and "the outline" in show(ticket)
    said = []
    monkeypatch.setattr(cli, "_header", lambda message, _example: said.append(message))
    text = tmp_path / "plan.md"
    text.write_text("# P\n", encoding="utf-8")
    assert cli._plan_words(["init", "T-1", "--decision", "go"]) is None and "needs the plan text" in said[-1]
    assert cli._plan_words(["init", "T-1", "inline", "--file", str(text)]) is None and "not both" in said[-1]
    assert cli._plan_words(["append", "T-1", "S", "--decision", "go"]) is None and "no --decision" in said[-1]
    assert cli._plan_words(["init", "T-1", "--file", str(text), "--decision", "go"]) == ["init", "T-1", "# P\n", "go"]


@pytest.mark.parametrize("pack_file", PACKS)
def test_a_denied_privileged_login_does_not_come_back_until_the_lane_asks_again(env, pack_file, monkeypatch):
    from cockpitlib import lend
    from cockpitlib.kanban import BoardWrites, place_card

    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    pack = load(pack_file)
    pack = {**pack, "privileged": {**(pack.get("privileged") or {}), "environment": "staging"}}
    ticket = f"{pack['tracker']['project']}-906"
    card = place_card(pack["board"], f"{ticket}: test", "tester-1", "ready")
    asked = "PRIVILEGED LOGIN NEEDED · staging · open the admin page · the row needs it"
    assert lend.ask(asked)
    writes = BoardWrites(pack["board"])
    writes.block(card, asked)
    writes.flush()
    assert [row["card"] for row in lend.inbox_rows(pack)] == [card]
    lend.deny(card, pack)
    assert [row for row in lend.inbox_rows(pack) if row["card"] == card] == []
    # with privileged.on_deny: resume (a cockpit-only pack) the card resumes; the same request asked again gets its Approve row
    resumed = {**pack, "privileged": {**pack["privileged"], "on_deny": "resume"}}
    other = place_card(pack["board"], f"{ticket}: tester", "tester-1", "ready")
    writes = BoardWrites(pack["board"])
    writes.block(other, asked)
    writes.flush()
    lend.deny(other, resumed)
    writes = BoardWrites(pack["board"])
    writes.block(other, asked)
    writes.flush()
    assert [row["card"] for row in lend.inbox_rows(resumed) if row["card"] == other] == [other]


@pytest.mark.parametrize("pack_file", PACKS)
def test_the_test_run_go_counts_the_screenshot_waiver_and_never_a_lane_s_word(bare, pack_file, monkeypatch):
    from cockpitlib import test_flow

    assert test_flow.HUMAN_GO.match("Human: go without screenshots") and test_flow.HUMAN_GO.match("go")
    # the Inbox button's own words (desktop/src/views/inbox.js)
    assert test_flow.HUMAN_GO.match("Human: go without screenshots: the text evidence is accepted for this run")
    assert not test_flow.HUMAN_GO.match("Human: gone")


@pytest.mark.parametrize("pack_file", PACKS)
def test_a_tester_is_sent_back_for_every_gap_its_run_still_has(bare, pack_file, monkeypatch):
    """testflow.send_back keeps the old pipeline's rule (its board's unfinished_runs): a row without its screenshot is unfinished."""
    from cockpitlib import housekeeping

    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    pack = {**load(pack_file), "testflow": {"send_back": 0}}
    rows = [
        {"id": "t_a", "status": "blocked", "assignee": "tester-1", "not_ready": ["3·screenshot"], "blocked_at": 0},
        {"id": "t_b", "status": "blocked", "assignee": "tester-1", "not_ready": ["2", "3·screenshot"], "blocked_at": 0},
    ]
    monkeypatch.setattr("cockpitlib.kanban.open_card_rows", lambda *_a, **_k: rows)
    monkeypatch.setattr(housekeeping, "_owned_cards", lambda _p: {})
    monkeypatch.setattr(housekeeping, "_hand_over", lambda _o, _c: False)
    sent = []
    monkeypatch.setattr(housekeeping.BoardWrites, "comment", lambda self, card, author, body: sent.append((card, body)))
    monkeypatch.setattr(housekeeping.BoardWrites, "unblock", lambda self, card: None)
    monkeypatch.setattr(housekeeping.BoardWrites, "flush", lambda self: [])
    assert housekeeping._send_back_testers(pack) == 2
    assert [card for card, _body in sent] == ["t_a", "t_b"] and "3 screenshot" in sent[0][1]


@pytest.mark.parametrize("pack_file", PACKS)
def test_a_refusal_row_without_a_card_is_shown_and_an_amend_settles_only_its_own_intent(bare, pack_file, monkeypatch):
    from cockpitlib import refusals

    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    pack = load(pack_file)
    ticket = f"{pack['tracker']['project']}-907"
    refusals.record(ticket, "tracker-comment", "", "human", "the human's own act")  # no card: shown all the same
    assert [row["type"] for row in refusals.unresolved(pack)] == ["tracker-comment"]
    refusals.record(
        ticket, "pr-comment", "", "reviewer-1", "the body names no thread", intent=f"{ticket}/003-pr-comment"
    )
    stamp = refusals.find(f"{ticket}|pr-comment||{ticket}/003-pr-comment")["at"]
    later = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(stamp + 5))
    other = [
        {
            "id": f"{ticket}/004-pr-comment",
            "ticket": ticket,
            "type": "pr-comment",
            "created_at": stamp - 50,
            "amended_at": later,
        }
    ]
    monkeypatch.setattr("cockpitlib.intents.all_intents", lambda *a: other)
    assert "pr-comment" in [
        row["type"] for row in refusals.unresolved(pack)
    ]  # another intent's amend does not settle it
    own = [{**other[0], "id": f"{ticket}/003-pr-comment"}]
    monkeypatch.setattr("cockpitlib.intents.all_intents", lambda *a: own)
    assert "pr-comment" not in [row["type"] for row in refusals.unresolved(pack)]


@pytest.mark.parametrize("pack_file", PACKS)
def test_a_blocked_card_never_reads_the_human_s_answer_as_its_question(env, pack_file):
    from cockpitlib.kanban import block_reason
    from tests.support.boards import put_card, raw

    pack = load(pack_file)
    card = put_card(pack["board"], f"{pack['tracker']['project']}-908: work", "worker-1", "triage")
    _comment(pack["board"], card, "worker-1", "which repo holds the schema?", at=time.time() - 60)
    _comment(pack["board"], card, "human", "Human: go")
    connection = raw(pack["board"])
    try:
        assert block_reason(connection, card) == "which repo holds the schema?"
    finally:
        connection.close()


@pytest.mark.parametrize("pack_file", PACKS)
def test_a_pack_ask_is_checked_at_load_and_a_slow_command_is_an_answer(env, pack_file, monkeypatch, tmp_path):
    from cockpitlib import asks

    with pytest.raises(PackError, match="asks.deploy.command"):
        load(
            _copy_pack(
                pack_file,
                tmp_path,
                lambda data, _c: data.update(asks={"deploy": {"mark": "DEPLOY", "command": ["echo", "{nope}"]}}),
            )
        )
    monkeypatch.setattr(
        "cockpitlib.skill_log.card_of",
        lambda _b, _c: {"status": "blocked", "assignee": "worker-1", "title": "T-1: work"},
    )
    monkeypatch.setattr("cockpitlib.kanban.block_reason", lambda _c, _i: "DEPLOY please")
    monkeypatch.setattr("cockpitlib.kanban.db_path", lambda _b: str(tmp_path / "none.db"))
    sqlite3.connect(str(tmp_path / "none.db")).close()

    def slow(*_a, **_k):
        raise subprocess.TimeoutExpired("x", 1)

    monkeypatch.setattr(asks.subprocess, "run", slow)
    pack = {"board": "b", "asks": {"deploy": {"mark": "DEPLOY", "command": ["true"]}}}
    with pytest.raises(CockpitError, match="did not finish within 1s"):
        asks.approve(pack, "t_1", timeout=1)
    assert asks._RUNNING == set()


@pytest.mark.parametrize("pack_file", PACKS)
def test_ci_retries_a_failed_notify_and_an_answered_attempt_is_handled(env, pack_file, monkeypatch):
    from cockpitlib import ci_watch

    monkeypatch.setattr("cockpitlib.notify.notify", lambda *a, **k: {"ok": False, "out": "slack down"})
    assert ci_watch._announce({}, "T-1", "a" * 40, "failed") is False
    monkeypatch.setattr("cockpitlib.notify.notify", lambda *a, **k: {"ok": True, "out": "sent"})
    assert ci_watch._announce({}, "T-1", "a" * 40, "failed") is True
    pack = load(pack_file)
    ticket = f"{pack['tracker']['project']}-909"
    # no card could be made (a halted ticket): the failure stays the human's row
    ci_watch._write(
        ci_watch.record_path(ticket, "api", "b" * 40), {"state": "failed", "cards": {"1-1": ""}, "sha": "b" * 40}
    )
    assert ci_watch.state_for(ticket, "api", "b" * 40, pack)["handled"] is False
    from tests.support.boards import put_card

    finished = put_card(
        pack["board"], f"{ticket}: ci", "analyst-1", "done"
    )  # an earlier diagnosis whose verdict stands
    ci_watch._write(
        ci_watch.record_path(ticket, "api", "c" * 40), {"state": "failed", "cards": {"2-2": finished}, "sha": "c" * 40}
    )
    assert ci_watch.state_for(ticket, "api", "c" * 40, pack)["handled"] is True


@pytest.mark.parametrize("pack_file", PACKS)
def test_an_upload_names_a_ticket_never_a_path_and_keeps_both_files_of_one_name(bare, pack_file, monkeypatch):
    from cockpitlib.paths import qa

    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    pack = load(pack_file)
    client = _client()
    data = base64.b64encode(b"hello").decode()
    assert client.post("/upload", json={"ticket": "../../etc", "name": "x.txt", "b64": data}).status_code == 400
    assert client.post("/upload", json={"ticket": "T-1", "name": "x.txt", "b64": "not base64!"}).status_code == 400
    ticket = f"{pack['tracker']['project']}-910"
    first = client.post("/upload", json={"ticket": ticket, "name": "x.txt", "b64": data}).json()["path"]
    second = client.post("/upload", json={"ticket": ticket, "name": "x.txt", "b64": data}).json()["path"]
    assert first != second and os.path.isfile(first) and os.path.isfile(second) and first.startswith(qa())


@pytest.mark.parametrize("pack_file", PACKS)
def test_a_pack_keeps_demo_logins_to_its_own_origins(bare, pack_file, tmp_path):
    from dashboard.cockpit.routes.pages import _login_origins

    origins = {"app": "http://app.local", "api": "https://api.stg", "portal": "https://portal.stg"}
    assert _login_origins(origins) == ["http://app.local", "https://api.stg", "https://portal.stg"]
    assert _login_origins(origins, {"demo_login_origins": ["app"]}) == ["http://app.local"]
    assert load(_copy_pack(pack_file, tmp_path, lambda data, _c: data.update(demo_login_origins=["app"])))[
        "demo_login_origins"
    ] == ["app"]
    with pytest.raises(PackError, match="demo_login_origins"):
        load(_copy_pack(pack_file, tmp_path / "bad", lambda data, _c: data.update(demo_login_origins="app")))


@pytest.mark.parametrize("pack_file", PACKS)
def test_a_ticket_owed_its_done_row_is_asked_again_and_never_gets_a_second_row(bare, pack_file, monkeypatch):
    from cockpitlib import pr_watch
    from cockpitlib.paths import watch_dir

    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    pack = load(pack_file)
    ticket = f"{pack['tracker']['project']}-911"
    pr_watch._write(
        pr_watch.record_path(ticket, "api", 12),
        {
            "ticket": ticket,
            "repo": "api",
            "number": 12,
            "role": "author",
            "state": "merged",
            "merged": True,
            "head": "work/x",
        },
    )
    assert pr_watch._owes_done(ticket) is True
    waiting = [
        {"type": "ticket-done", "status": "pending", "payload": {"numbers": ["11"]}}
    ]  # a row waiting for the ack
    monkeypatch.setattr(pr_watch, "all_intents", lambda *a: waiting)
    assert pr_watch._owes_done(ticket) is False  # it covers what is merged now: no second row
    monkeypatch.setattr(pr_watch, "all_intents", lambda *a: [])
    monkeypatch.setattr(pr_watch, "watched", lambda: [])
    monkeypatch.setattr(pr_watch, "discover", lambda _p, _f: [])
    monkeypatch.setattr("cockpitlib.publish.forge_for", lambda _p: None)
    asked = []
    monkeypatch.setattr(pr_watch, "_ticket_done", lambda _p, t: asked.append(t) or "")
    owed = os.path.join(watch_dir(), "ticket-done-owed.json")
    pr_watch._write(owed, {"tickets": [ticket]})
    stamp = os.path.getmtime(owed)
    time.sleep(0.01)
    pr_watch.watch(pack)
    assert asked == [ticket] and os.path.getmtime(owed) == stamp  # asked again; an unchanged list is not rewritten


@pytest.mark.parametrize("pack_file", PACKS)
def test_discovery_finds_a_hand_opened_pr_unless_its_branch_is_known_or_the_ack_came_after_the_push(
    env, pack_file, monkeypatch
):
    from cockpitlib import pr_watch

    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    pack = load(pack_file)
    pack = {**pack, "forge": {"org": pack["forge"]["org"], "discover_prs": True}}
    ticket = f"{pack['tracker']['project']}-913"
    pr_watch._write(
        pr_watch.record_path(ticket, "api", 40), {"ticket": ticket, "repo": "api", "number": 40, "head": "work/one"}
    )
    push = lambda branch, at: {
        "ticket": ticket,
        "type": "push-branch",
        "status": "published",
        "created_at": at,
        "payload": {"repo": "api", "branch": branch},
    }
    ack = {"ticket": ticket, "type": "ticket-done", "status": "acknowledged", "created_at": "2026-10-20T10:00:00Z"}

    class Forge:
        def repo(self, name):
            return f"org/{name}"

        def get(self, path):
            return [{"number": 41 if "work/two" in path else 40, "html_url": "u"}]

    intents = [ack, push("work/one", "2026-10-21T10:00:00Z"), push("work/two", "2026-10-21T11:00:00Z")]
    monkeypatch.setattr(pr_watch, "all_intents", lambda *a: intents)
    assert pr_watch.discover(pack, Forge()) == [
        (ticket, "api", 41)
    ]  # a second branch of the repo; the push came after the ack
    intents[0] = {**ack, "created_at": "2026-10-22T10:00:00Z"}
    os.remove(pr_watch.record_path(ticket, "api", 41))
    assert pr_watch.discover(pack, Forge()) == []  # acknowledged after that push: its lifecycle is over
    intents[0] = ack
    pr_watch._write(
        pr_watch.record_path(ticket, "api", 40),
        {"ticket": ticket, "repo": "api", "number": 40, "head": "work/one", "state": "merged"},
    )
    Forge.get = lambda self, path: [{"number": 42 if "work/one" in path else 41, "html_url": "u"}]
    assert sorted(pr_watch.discover(pack, Forge())) == [
        (ticket, "api", 41),
        (ticket, "api", 42),
    ]  # a merged record: a new PR


def test_a_kept_stack_stays_marked_for_the_cleanup_and_a_slow_git_is_no_error(env, monkeypatch):
    from cockpitlib import slots, worktree

    slots.write_owner(1, "free")
    slots.keep_stack(1)
    slots.write_owner(1, "worker-1")  # a busy slot is the cleanup's again once it is idle; the mark stays for that
    assert os.path.isfile(os.path.join(slots.state_dir(1), "stack-kept"))

    def slow(*_a, **_k):
        raise subprocess.TimeoutExpired("git", 20)

    monkeypatch.setattr(worktree.subprocess, "run", slow)
    assert worktree._git_out("/tmp", "status") == ""


@pytest.mark.parametrize("pack_file", PACKS)
def test_a_redo_with_skill_hold_with_a_rework_carries_the_skill(bare, pack_file, monkeypatch):
    from cockpitlib import outbox

    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    pack = load(pack_file)
    ticket = f"{pack['tracker']['project']}-914"
    intent = outbox.create(pack, ticket, "ticket-done", "worker-1", "x", {})
    seen = {}
    monkeypatch.setattr("cockpitlib.gate.return_intent", lambda *a, **k: seen.update(k) or {"status": "returned"})
    outbox.hold(
        intent["id"], "redo with skill pr-review loaded", rework="redo it", pack=pack, skills=["finding-moderation"]
    )
    assert seen["extra_skills"] == ["finding-moderation", "pr-review"]


def test_a_git_move_is_refused_by_verb_in_every_shell_form(env, tmp_path, monkeypatch):
    """egress.git_deny judges git on its argv, not on a regex over the line: options before the verb are skipped, the
    verb is compared exactly (merge-base is not merge), a flagged entry needs its flag, and tag/branch alone mean the
    forms that change the repository. The old regex rule refused `git merge-base` and let `git -C x
    merge` through."""
    from cockpitlib import egress

    copied = tmp_path / "packs" / "acme"
    shutil.copytree(os.path.join(ROOT, "packs", "acme"), copied)
    with open(copied / "egress.yaml", "a", encoding="utf-8") as handle:
        handle.write(
            "git_deny:\n  reviewer: [commit, push, reset, rebase, merge, cherry-pick, revert, tag, branch,"
            ' "checkout -b -B --orphan", "switch -c -C"]\n  tester: [commit, push]\n'
        )
    monkeypatch.setenv("COCKPIT_PACK", str(copied / "pack.yaml"))
    monkeypatch.setenv("COCKPIT_LANE", "reviewer-1")
    pack = load(str(copied / "pack.yaml"))
    entries = pack["egress"]["git_deny"]["reviewer"]
    refused = {
        "git commit -m x": "commit",
        "git -C d commit -m x": "commit",
        "git -Cd commit": "commit",
        "git -c a=b --no-pager push origin x": "push",
        "git --git-dir=.git reset --hard": "reset",
        "git --git-dir .git --work-tree . rebase rc": "rebase",
        "sudo git tag v1": "tag",
        "git tag -a v1 -m x": "tag",
        "git tag -d v1": "tag",
        "git branch new": "branch",
        "git branch -D old": "branch",
        "git branch -m a b": "branch",
        "cd x && git checkout -b y": "checkout -b -B --orphan",
        "git checkout -bqa": "checkout -b -B --orphan",
        "git checkout -qb qa": "checkout -b -B --orphan",
        "git checkout --orphan=x": "checkout -b -B --orphan",
        "git switch -c x": "switch -c -C",
        "bash -c 'git merge rc'": "merge",
        "echo $(git reset --hard)": "reset",
        "GIT_DIR=.git git rebase rc": "rebase",
        "git -C 'a b' push": "push",
        "git -c 'a=b c' commit": "commit",
        "/usr/bin/git cherry-pick abc": "cherry-pick",
        "x=1; git revert abc": "revert",
        "git  commit": "commit",
        "git\tpush": "push",
        "eval 'git commit -m x'": "commit",
        "cat f | git -p merge rc": "merge",
        # the shell's keywords before the command, a wrapper's bare flag before git, bare backticks, a later bad quote
        "{ git push; }": "push",
        "if git push; then :; fi": "push",
        "! git push": "push",
        "while :; do git push; done": "push",
        "true && { git push; }": "push",
        "env -i git push": "push",
        "sudo -E git push": "push",
        "sudo -n git push": "push",
        "xargs -0 git push": "push",
        "xargs -I{} git push {}": "push",
        "stdbuf -oL git push": "push",
        "echo `git push`": "push",
        "x=`git push`": "push",
        "git push\necho '": "push",
        "exec git push": "push",
        # tag/branch: -v, --format, --sort, -i, --abbrev do not list; a name beside them creates the ref
        "git branch -v new": "branch",
        "git branch --abbrev=7 new": "branch",
        "git tag -i v1": "tag",
        "git tag --sort=x v1": "tag",
        "git tag --format=x v1": "tag",
        "git tag --column v1": "tag",
    }
    for command, entry in refused.items():
        assert egress.git_moves(command, entries) == entry, command
    allowed = [
        'echo "git commit"',
        "git merge-base rc HEAD",
        "git -C ../web merge-base origin/rc HEAD",
        "git merge-tree a b",
        "git reset-notes",
        "git commit-tree abc",
        "git tag",
        "git tag -l",
        "git tag -l 'v*'",
        "git tag -n5",
        "git tag --list --sort=-v:refname",
        "git tag --contains abc",
        "git tag --points-at HEAD",
        "git tag -- ",
        "git branch",
        "git branch -a",
        "git branch -vv",
        "git branch --merged rc",
        "git branch --show-current",
        "git --no-pager log -3",
        "git -c color.ui=never diff rc...HEAD",
        "git -C x status",
        "git checkout rc",
        "git checkout -- file",
        "git checkout -- -bfile",
        "git switch rc",
        "git -C x",
        "git",
        "ls",
        "git log --merges",
        "git describe --tags",
        "printf 'git push'",
        "git -c a=b",
        "git stash push",
        "git switch -",
        "git branch -vv",
        "git tag --sort=x",
        "ls 'unbalanced",
        "{ ls; }",
        "if true; then :; fi",
    ]
    for command in allowed:
        assert egress.git_moves(command, entries) == "", command
    # a line the shell may run that the fence cannot read is refused when it names git, not let through
    assert egress.git_moves("git commit 'unbalanced", entries) == egress.UNREADABLE
    assert egress.git_moves("echo 'x; git push", entries) == egress.UNREADABLE
    assert egress.git_moves("cat gitlog 'x", entries) == ""
    # the fence: the verb is named, a code text is not read as a shell line, another seat kind has its own list
    assert egress.check_bound("git -C d commit -m x") == "blocked"
    assert egress.explained("blocked") == "blocked: refused to a reviewer (git commit)"
    assert egress.check_bound("git tag -l") == ""
    assert egress.check_bound("git commit 'unbalanced") == "blocked"
    assert (
        egress.explained("blocked")
        == "blocked: refused to a reviewer (git on a line the fence cannot read: fix the quoting)"
    )
    assert egress.check_bound("subprocess.run(['git', '-C', 'd', 'commit'])", shell=False) == ""
    monkeypatch.setenv("COCKPIT_LANE", "tester-1")
    assert egress.check_bound("git tag v1") == "" and egress.check_bound("git -C d commit -m x") == "blocked"
    assert egress.check_bound('js("(() => { x })()")', shell=False) == ""
    assert egress.check_bound('os.system("echo x > /etc/p")', shell=False) == "blocked"
    monkeypatch.setenv("COCKPIT_LANE", "worker-1")
    assert egress.check_bound("git -C d commit -m x") == ""
    # bounded cost: options are read once each, nesting stops at the depth the write walker uses
    started = time.time()
    assert egress.git_moves("git " + "--opt " * 2000 + "status", entries) == ""
    assert egress.git_moves(("bash -c '" * 10) + "git commit" + ("'" * 10), entries) in ("", "commit")
    assert time.time() - started < 5  # a runaway walk takes minutes; a fifth of a second was a busy machine's flake
    assert egress._argvs("git commit", depth=egress._DEPTH + 1) == []
