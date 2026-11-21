# The browser and failure videos

## The browser model

Every lane drives Hermes's built-in browser (Hermes 0.23's core `browser` toolset: `browser_exec` with its helpers
`new_tab`, `goto_url`, `fill_input`, `js`, `capture_screenshot`; `browser_vault`; `browser_cdp`; `browser_dialog`). The
0.22 tools (`browser_navigate`, `browser_snapshot`, `browser_click`, `browser_type`, `browser_vision`,
`browser_console`) left core in 0.23 and no soul names them; the fence still reads their inputs, for a seat on 0.22 or on
a browser plugin that keeps them. Under `lanes.browser_session` a lane's `browser_exec` must pass
`session: "<lane>-<ticket>"`. Sign-in is `new_tab` to the login page, the email typed with `fill_input`,
`browser_vault fill` with the handle, then the signed-in identity confirmed in the page.

## The external browser

The external browser (a browser on its DevTools port: the human's own, `human_browser_port`, or the agents' own, driven
through a DevTools MCP server) is one option of a **test kickoff**, and only of it: the Kick off page shows the checkbox
on the Test flow, and `POST /kickoff` and `kickoff.start` refuse `chrome` on every other mode and on `policy="release"`.

A test kickoff started with it lends the browser for `shared_chrome_hours`, says `browser lent for <n>h` and
`browser: external` on its card, and records `browser: external` in `watch/cards.json`. The fence then refuses every
`mcp__chrome*__` tool (whatever the pack named the server) and every reach of the human browser port on a lane card that
is not that card: a tester card inside a dev or another flow, any card of another flow, and every supervisor card (scope
`release`, or `policy: release` in its body) run on the built-in browser. The human's own sessions are not fenced. A pack
with no such MCP server and no `human_browser_port` sees no change.

What cockpit knows about a card (`cockpitlib.browser_card.facts`): the kind it recorded (`test`, `test-kickoff`, `tester`,
a plugin's kind), the ticket, the scope (`release` for a supervisor card), and the browser choice: `browser: external` in
`watch/cards.json`, or `browser lent for` / `browser: external` in the body the kickoff wrote. A comment never counts (a
lane can write one). The plan card a test kickoff posts records the run card it was posted from (`run_card`) and is
external only while that run card is open and external, never because an older test card of the ticket was.

## Failure videos: `cockpit record`

On a test kickoff card a failed scenario gets one reproduction video:

```sh
cockpit record start --session tester-1-TASK-100 \
  --out hermes/qa/TASK-100/run-1/evidence/videos/s3-save-button-repro.mp4 \
  [--record-id "order 4711"] [--on-screen "the saved order, form open"] [--max-seconds 180] [--url-contains /orders]
cockpit record stop --session tester-1-TASK-100      # encodes, checks it plays, appends README.md; JSON out
cockpit record status [--session tester-1-TASK-100]
```

`start` finds the session's browser: the local browser Hermes 0.23 launched for that `browser_exec` session (its
`DevToolsActivePort` under the seat's `cache/browser/chromium/`), else the seat's `browser.cdp_url`; on an
external-option card, the external browser's port. It picks the page (`--url-contains`, else the most recent real tab),
and a detached recorder keeps `Page.startScreencast` frames (a screenshot when the tab paints nothing for a second) under
`watch/record/` until `stop` or the time cap (5–600 s).

`stop` encodes them with ffmpeg to H.264 `.mp4` (yuv420p, `+faststart`, a constant 8 fps by holding each frame until the
next), keeps the file only when ffprobe reads h264/yuv420p/8 fps with a duration and a full decode has no error, and
appends a section to `evidence/videos/README.md` (scenario, test record, what was on screen at start, tab, duration).
`--record-id` and `--on-screen` are recommended, not required: a clip without them says `(not given)` on those lines.

The file is `qa/<ticket>/<run>/evidence/videos/<scenario>-<slug>-repro.mp4` in a run folder of the card's own ticket; a
taken name becomes `-take2`, `-take3`, never overwritten. `evidence` and `test-results.md` are the kernel's names for a
run's evidence folder and results file; a pack may name its own (`testflow.evidence_dir`, `testflow.results_file`).

Who may record:

- a lane records only on a test kickoff card (`<ticket>: test` or its plan card) and only its own session (exactly
  `<lane>-<ticket>` of its card: `tester-1-TASK-1` is not `tester`'s);
- on an external-option card, only while the kickoff's loan for the ticket runs;
- a tester card inside another flow and every supervisor card are refused;
- arguments holding a stored secret are refused.

The hourly slot-gc stops the recorder of a card that ended and removes its `watch/record/<session>.frames`, and any
frames folder older than a day. The standard (one clip per Fail, a new test record per clip named
`QA <TICKET> run NNN · #<scenario> · clip`) is in `souls/tester.md`.

## The video is mandatory on a failed run

The video is mandatory on a test kickoff's run card (kind `test`; not its plan card, not a `<ticket>: tester` phase inside
a dev flow, never a supervisor card). The lane's `kanban_complete` is refused (the card stays with its lane) until every
Fail row of the run's `test-results.md` (the newest run folder with results) has a file in `<run>/evidence/videos/` named
for its scenario (`<n>-…` or `s<n>-…`, `.mp4`, or `.mov`) that plays: `cockpit record`'s own check
(h264/yuv420p/8 fps and a full decode; a `.mov` needs any video stream with a duration that decodes), cached by mtime and
size in `watch/record-playable.json`. The refusal names the rows and the `cockpit record start`/`stop` lines.

The human's go on the run's review is refused the same way (`3·video`), and with `testflow.send_back` housekeeping sends
the card back to record. A run without a Fail row needs no video. When `cockpit record` itself refused (the loan expired,
no browser target), the lane writes `video: not possible — <reason>` in that row's note; the card then closes only after
it blocked with `no failure video for row N (<reason>): …` (a row on the Inbox) and the human answered go.
