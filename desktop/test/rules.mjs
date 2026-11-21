// SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
// SPDX-License-Identifier: AGPL-3.0-or-later

// Behaviour tests: the page's decision logic, not just "it renders". Same approach as smoke.mjs (src/ bundled with the SDK
// stubbed, rendered with react-dom/server), but each test sets its own small fixture and asserts what appears and what does
// not: Inbox rows and their actions, the Outbox table, the detail pane's sections, the diff view's file order, the Platform
// window labels and the status-bar Chip's notifications.
// A rule the source breaks today is a `bug(...)` test: its assertion stays, it prints as BUG (with file:line) and does not
// fail the run; once the source is fixed it passes and asks for the marker to be dropped.
import { build } from 'esbuild'
import assert from 'node:assert/strict'
import { readFileSync, readdirSync, writeFileSync, mkdirSync } from 'node:fs'
import path from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'
import { createElement } from 'react'
import { renderToString } from 'react-dom/server'

const here = path.dirname(fileURLToPath(import.meta.url))
const root = path.resolve(here, '..')
const src = (p) => path.join(root, 'src', p)
const BASE = JSON.parse(readFileSync(path.join(here, 'fixtures.json'), 'utf8'))
// the stub reads this object once at import time; every test swaps its contents in place
const FX = structuredClone(BASE)
globalThis.__cockpitFixtures = FX
const setFx = (over = {}) => {
  for (const k of Object.keys(FX)) delete FX[k]
  Object.assign(FX, structuredClone(BASE), structuredClone(over))
}

// ---------- the bundle under test ----------
// one bundle, one copy of every module: the plugin (register() sets CTX) plus the views the tests render directly.
// react is redirected to a shim that records useEffect callbacks instead of dropping them, so the Chip's notification
// effects can be run by hand after a render (react-dom/server never runs effects); everything else is the real React.
const outDir = path.join(root, '.tmp')
mkdirSync(outDir, { recursive: true })
writeFileSync(
  path.join(outDir, 'react-effects.mjs'),
  "export * from 'react'\nexport function useEffect(fn) { (globalThis.__cockpitEffects ||= []).push(fn) }\n",
)
// every element the views make goes through this stand-in for react/jsx-runtime: it keeps each one that has a click
// handler, and each button, with the props it was made with, for the rules at the end of this file
writeFileSync(
  path.join(outDir, 'jsx-record.mjs'),
  "import * as real from 'react/jsx-runtime'\nexport const Fragment = real.Fragment\n" +
  "const seen = (globalThis.__cockpitElements ||= [])\n" +
  "const note = (tag, props) => { if (typeof tag === 'string' && props && (props.onClick || tag === 'button')) seen.push({ tag, props }) }\n" +
  "export const jsx = (tag, props, key) => { note(tag, props); return real.jsx(tag, props, key) }\n" +
  "export const jsxs = (tag, props, key) => { note(tag, props); return real.jsxs(tag, props, key) }\n",
)
const entry = [
  `export { default as plugin } from ${JSON.stringify(src('index.js'))}`,
  `export { OutboxPage, KickoffForm } from ${JSON.stringify(src('app.js'))}`,
  `export { Detail, CiOverride } from ${JSON.stringify(src('views/outbox.js'))}`,
  `export { BlockedCard, ReReviewPanel, credentialAsk, PrGroupPanel, BumpsPanel, StandupPanel, WatcherPanel, RefusalPanel, PluginPanel, AnswerPanel, TrackerNotePanel, MergePanel, PrivilegedPanel } from ${JSON.stringify(src('views/inbox.js'))}`,
  `export { DiffView, DiffPanel, baseCommits } from ${JSON.stringify(src('lib/diff.js'))}`,
  `export { Board, splitDone, stackByTicket, RECENT_HOURS } from ${JSON.stringify(src('views/board.js'))}`,
  `export { clockOf } from ${JSON.stringify(src('views/live.js'))}`,
  `export { DemoSection, SessionCard } from ${JSON.stringify(src('views/demo.js'))}`,
  `export { Usage, PacePanel } from ${JSON.stringify(src('views/usage.js'))}`,
  `export { Settings } from ${JSON.stringify(src('views/settings.js'))}`,
  `export { Tickets } from ${JSON.stringify(src('views/tickets.js'))}`,
  `export { Vault, RecordDetail, Danger, KeyBar } from ${JSON.stringify(src('views/vault.js'))}`,
  `export { RecordForm, KIND_FIELDS } from ${JSON.stringify(src('views/vault-record.js'))}`,
  `export { genPassword, SecretField } from ${JSON.stringify(src('lib/secret.js'))}`,
  `export { DecidePanel, decisionText } from ${JSON.stringify(src('views/decide.js'))}`,
  `export { ReworkForm, ReopenForm, pickCells, LABELS, COMPACT_COLS, OUTBOX_COLS } from ${JSON.stringify(src('views/outbox.js'))}`,
  `export { TerminalModal } from ${JSON.stringify(src('views/chat.js'))}`,
  `export { ChangeModal, MapPopover, changeLabel, fileOf } from ${JSON.stringify(src('views/platform.js'))}`,
  `export { AdvisoryPanel, AdvisoriesTab } from ${JSON.stringify(src('views/advisories.js'))}`,
  `export { perLane } from ${JSON.stringify(src('views/live.js'))}`,
  `export { calls } from ${JSON.stringify(path.join(here, 'sdk-stub.js'))}`,
  `export { post, CSS, openWeb, isWeb } from ${JSON.stringify(src('lib/sdk.js'))}`,
  `export { escapeHtml } from ${JSON.stringify(src('lib/markdown.js'))}`,
  `export { pressable, iconOnly } from ${JSON.stringify(src('lib/a11y.js'))}`,
  `export * as words from ${JSON.stringify(src('lib/packwords.js'))}`,
].join('\n')
const outfile = path.join(outDir, 'rules.test.mjs')
await build({
  stdin: { contents: entry, resolveDir: root, loader: 'js' },
  bundle: true, format: 'esm', outfile, target: 'es2022', logLevel: 'silent',
  alias: { '@hermes/plugin-sdk': path.join(here, 'sdk-stub.js') },
  plugins: [{ name: 'react-effects', setup(b) {
    b.onResolve({ filter: /^react$/ }, () => ({ path: './react-effects.mjs', external: true }))
    b.onResolve({ filter: /^react\/jsx-runtime$/ }, () => ({ path: './jsx-record.mjs', external: true }))
  } }],
})

globalThis.document = { head: { appendChild() {} }, createElement: () => ({ setAttribute() {}, remove() {}, textContent: '' }) }
const notes = []
const opened = []   // every address the page handed to the system (CTX.os.openExternal)
const STORE = {}   // what the page keeps per viewer (CTX.storage) during the tests
const ctx = {
  rest: (p) => { globalThis.__cockpitLastRest = p; return Promise.resolve(FX[p.replace(/^\//, '').split('?')[0]] ?? {}) },
  storage: { get: (k, d) => (k in STORE ? STORE[k] : d), set: (k, v) => { STORE[k] = v } },
  os: { openExternal: (u) => opened.push(u), revealPath() {}, notify: (n) => notes.push(n), writeClipboard() {} },
  onDispose() {},
  registered: [],
  registerMany(items) { this.registered.push(...items) },
}
const mod = await import(pathToFileURL(outfile).href)
const { clockOf, OutboxPage, KickoffForm, DemoSection, SessionCard, CiOverride, PrGroupPanel, Board, splitDone, stackByTicket, RECENT_HOURS, Detail, BlockedCard, ReReviewPanel, DiffView, DecidePanel, decisionText, TerminalModal, ChangeModal, MapPopover, changeLabel, fileOf, ReworkForm, pickCells, LABELS, COMPACT_COLS, OUTBOX_COLS, BumpsPanel, StandupPanel, WatcherPanel, RefusalPanel, PluginPanel, AnswerPanel, TrackerNotePanel, MergePanel, Usage, PacePanel, Settings, Tickets, Vault, RecordDetail, Danger, KeyBar, RecordForm, KIND_FIELDS, genPassword, SecretField, credentialAsk, calls, AdvisoryPanel, AdvisoriesTab, escapeHtml, PrivilegedPanel, CSS, perLane, openWeb, isWeb, DiffPanel, baseCommits } = mod
mod.plugin.register(ctx)
const chip = ctx.registered.find((x) => x.id === 'chip')

const consoleError = console.error
console.error = (...a) => { if (String(a[0]).includes('containing a "key" prop is being spread')) return; consoleError(...a) }
const render = (el) => { globalThis.__cockpitEffects = []; return renderToString(el) }

// ---------- a small reader for react-dom/server output ----------
const VOID = new Set(['area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input', 'link', 'meta', 'source', 'track', 'wbr'])
const ENT = { amp: '&', lt: '<', gt: '>', quot: '"', '#x27': "'", '#39': "'", nbsp: ' ' }
const decode = (s) => s.replace(/&(amp|lt|gt|quot|#x27|#39|nbsp);/g, (m, e) => ENT[e])
function parse(html) {
  const top = { tag: '#root', attrs: {}, children: [] }; const stack = [top]
  const re = /<!--[\s\S]*?-->|<(\/?)([a-zA-Z][a-zA-Z0-9-]*)((?:\s+[^\s=>/]+(?:="[^"]*")?)*)\s*(\/?)>|([^<]+)/g
  for (const m of html.matchAll(re)) {
    if (m[0].startsWith('<!--')) continue
    if (m[5] != null) { stack[stack.length - 1].children.push({ text: decode(m[5]) }); continue }
    const [, close, tag, rawAttrs, selfClose] = m
    if (close) { while (stack.length > 1 && stack.pop().tag !== tag); continue }
    const attrs = {}
    for (const a of rawAttrs.matchAll(/([^\s=>/]+)(?:="([^"]*)")?/g)) attrs[a[1]] = a[2] == null ? '' : decode(a[2])
    const node = { tag, attrs, children: [] }
    stack[stack.length - 1].children.push(node)
    if (!selfClose && !VOID.has(tag)) stack.push(node)
  }
  return top
}
const text = (n) => (n.text != null ? n.text : n.children.map(text).join(''))
const elems = (n) => n.children.filter((c) => c.tag)
const all = (n, pred, out = []) => { for (const c of elems(n)) { if (pred(c)) out.push(c); all(c, pred, out) } return out }
const cls = (n) => n.attrs.class || ''
const colorOf = (n) => ((n.attrs.style || '').match(/(?:^|;)color:([^;]+)/) || [])[1]
// SplitList: header labels and one array of cells per row
function table(html) {
  const t = parse(html)
  const head = all(t, (n) => /^cockpit-head grid\b/.test(cls(n)))[0]
  const rows = all(t, (n) => /^cockpit-row grid\b/.test(cls(n)))
  return { labels: head ? elems(head).map((c) => text(c)) : [], rows: rows.map((r) => elems(r).map((c) => ({ text: text(c).trim(), color: colorOf(c) }))) }
}
// Section headers in document order: { title, open }
const sections = (html) => all(parse(html), (n) => /cursor-pointer select-none/.test(cls(n))).map((hd) => { const s = elems(hd); return { title: text(s[1]), open: text(s[0]) === '▾' } })
const buttons = (html, label) => all(parse(html), (n) => n.tag === 'button' && (label instanceof RegExp ? label.test(text(n)) : text(n).trim() === label))

// ---------- fixtures ----------
const WARN = 'var(--ui-warning, #c98a00)', GOOD = 'var(--ui-success, #2a9d5c)', ACCENT = 'var(--ui-accent)', DANGER = 'var(--ui-danger, #d33)'
const MODEL = /opus|sonnet|haiku|claude-|gpt-|gemini/i
const ago = (min) => new Date(Date.now() - min * 60000).toISOString()
let seq = 0
const intent = (over = {}) => {
  const ticket = over.ticket || `TASK-${100 + ++seq}`; seq++
  return { id: `${ticket}/${over.type || 'push-branch'}-${seq}`, ticket, type: 'push-branch', status: 'published', digest_no: seq, target: 'api feature/x', summary: 'a change', risk: 'low',
    created_by: 'worker-1', created_at: ago(300), path: `/ws/outbox/${ticket}/${seq}.json`, payload: { repo: 'api' }, pr: null, ci: null, prs: [], ...over }
}
const endorsed = (min = 20) => ({ time: ago(min), risk: 'low', notes: 'small, covered by a unit test', model: 'opus-4-5' })
const authorPr = (over = {}) => ({ number: 21, url: 'https://git.acme.test/acme/api/pull/21', merged: false, state: 'open', author: 'review-bot', role: 'author', new_count: 0, new: [], approvals: [], total: 0, last_check: ago(5), ...over })
const ci = (over = {}) => ({ state: 'failed', branch: 'feature/x', sha: 'abc1234', summary: '1/3 failed', last_check: ago(5), handled: false, analysing: false, runs: [], cards: {}, ...over })
const revPr = (over = {}) => ({ repo: 'web', number: 90, url: 'https://git.acme.test/acme/web/pull/90', role: 'reviewer', state: 'open', merged: false, my_review_state: 'CHANGES_REQUESTED',
  re_requested: false, my_threads: { total: 3, resolved: 1, replied: 0 }, since_review: { commits: 0, files: 0 }, last_activity: ago(10), ...over })
// the ticket row that carries a reviewer PR: your earlier review, already published
const revRow = (pr, over = {}) => intent({ ticket: 'TASK-900', type: 'pr-review-submit', status: 'published', payload: { repo: 'web', number: 90 }, prs: [pr], ...over })
const card = (over = {}) => ({ id: 'c-1', ticket: 'TASK-700', status: 'blocked', assignee: 'intake', title: 'TASK-700 intake plan', question: 'Follow the page background?', created_at: Math.floor(Date.now() / 1000) - 600, ...over })

function inbox(rows, { cards = [], watchers = [], privileged = [] } = {}) {
  setFx({ list: { counts: {}, rows }, 'needs-you': { cards, watchers, privileged }, 'sweep-state': { running: false, requested: false } })
  const t = table(render(createElement(OutboxPage, { initialView: 'inbox' })))   // the groups under the to-do stay collapsed: only your rows render
  return { labels: t.labels, rows: t.rows.map(([tk, a, w, risk, ty]) => ({ ticket: tk.text, type: ty.text, action: a.text.replace(/^\S*\s/, ''), color: a.color, what: w.text })) }
}
const only = (res) => { assert.equal(res.rows.length, 1, `expected one Inbox row, got ${JSON.stringify(res.rows)}`); return res.rows[0] }
const none = (res) => assert.deepEqual(res.rows, [], 'expected no Inbox row')
function outbox(rows) {
  setFx({ list: { counts: { pending: rows.filter((r) => r.status === 'pending').length }, rows }, 'needs-you': { cards: [], watchers: [] }, 'sweep-state': { running: false, requested: false } })
  const html = render(createElement(OutboxPage, { initialView: 'inbox', openGroups: true }))   // every group open: the whole gate
  return { html, ...table(html) }
}
const DEMO = { slot: 3, apps: [{ name: 'Web', up: true, url: 'http://web.slot3.test' }], login: null }
function detail(r) {
  setFx({ intent: r, demo: DEMO })
  return render(createElement(Detail, { id: r.id }))
}
// an intent as /intent returns it: brief, the outgoing file, the other files, history
const full = (over = {}) => intent({
  ticket: 'TASK-500', type: 'pr-comment', status: 'endorsed', endorsed: endorsed(), card_id: 't_abc123', brief: '<p>the brief body</p>', outgoing: 'body_file',
  payload: { repo: 'web', number: 77, body_file: 'b' },
  files: { body_file: '/ws/outbox/TASK-500/001-body.md', threads_file: '/ws/outbox/TASK-500/001-threads.json' },
  file_contents: { body_file: 'Thanks, fixed in abc1234.', threads_file: '[]' },
  history: [{ event: 'created', time: ago(60) }], log: ['created by worker-1'], ...over })

// ---------- runner ----------
const results = []
const test = (name, fn) => { try { fn(); results.push(['ok  ', name]) } catch (e) { results.push(['FAIL', name, e.message]) } }
const bug = (name, where, fn) => {
  try { fn(); results.push(['ok  ', `${name} (was marked BUG at ${where} and passes now: turn it into a plain test)`]) }
  catch (e) { results.push(['BUG ', name, `${where} · ${e.message.split('\n')[0]} (skipped: the rule stands, the source breaks it)`]) }
}

// ================= Inbox =================
test('inbox: the Outbox table\'s columns for every row; a row starts with its ticket and action (the status cell), the type fifth', () => {
  const res = inbox([intent({ ticket: 'TASK-201', status: 'endorsed', endorsed: endorsed() })])
  assert.deepEqual(res.labels, ['ticket', 'status', 'target', 'risk', 'type', 'PR', 'CI', 'age'])
  assert.deepEqual([only(res).ticket, only(res).type, only(res).action], ['TASK-201', 'push-branch', 'publish'])
})
test('inbox: blocked card → answer (warning), open cards that are not blocked → no row', () => {
  const r = only(inbox([], { cards: [card({ ticket: 'TASK-701' }), card({ id: 'c-2', ticket: 'TASK-702', status: 'in_progress' })] }))
  assert.deepEqual([r.ticket, r.action, r.color], ['TASK-701', 'answer', WARN])
  assert.match(r.what, /intake asks: Follow the page background\?/)
})
test('inbox: an endorsed push and the pull request that follows it are one row, the pull request\'s; the push is a row when the pull request is not offered', () => {
  const push = intent({ id: 'TASK-801/001-push-branch', ticket: 'TASK-801', type: 'push-branch', status: 'endorsed', endorsed: endorsed(), chain: { pair: 'TASK-801/002-open-pr' } })
  const pr = intent({ id: 'TASK-801/002-open-pr', ticket: 'TASK-801', type: 'open-pr', status: 'endorsed', endorsed: endorsed(), payload: { repo: 'api', after: push.id }, chain: { role: 'content', step1_status: 'endorsed' } })
  assert.equal(only(inbox([push, pr])).type, 'open-pr')
  const waiting = { ...pr, waits: { id: 'TASK-801/000-pr-edit', type: 'pr-edit', status: 'endorsed' } }
  assert.equal(only(inbox([push, waiting])).type, 'push-branch')
  const held = { ...push, status: 'held', hold: { waits: 'human', reason: 'check it', time: ago(5) } }
  assert.ok(inbox([held, pr]).rows.some((x) => x.type === 'push-branch'), 'a push that needs you is still your row')
})
test('inbox: a card blocked until you publish an intent is no row of its own: the Publish row of that intent is the act', () => {
  none(inbox([], { cards: [card({ ticket: 'TASK-703', waits_publish: 'TASK-703/002-push-branch' })] }))
  assert.equal(only(inbox([], { cards: [card({ ticket: 'TASK-703', waits_publish: '' })] })).action, 'answer')
})
test('inbox: a review asked for a Test run that is not finished is no row while the housekeeping sends it back; parked, or still there after 2 min → "send back"', () => {
  const now = Math.floor(Date.now() / 1000)
  const early = { ticket: 'TASK-704', assignee: 'tester-2', question: 'Run test_run_001 ready for your review: 15 pass, 1 blocked. go?', not_ready: ['16', '18'] }
  none(inbox([], { cards: [card({ ...early, blocked_at: now - 30 })] }))
  assert.deepEqual([only(inbox([], { cards: [card({ ...early, blocked_at: now - 30, parked: true })] })).action], ['send back'])
  assert.deepEqual([only(inbox([], { cards: [card({ ...early, blocked_at: now - 600 })] })).action], ['send back'])
  assert.deepEqual([only(inbox([], { cards: [card({ ...early, not_ready: [], blocked_at: now - 30 })] })).action], ['answer'])   // a finished run is your review
  const html = render(createElement(BlockedCard, { c: card({ ...early, parked: true }), refresh() {} }))
  assert.ok(html.includes('not ready for your review') && html.includes('Rows 16, 18 are still blocked, not run or waiting for your result'))
  assert.equal(buttons(html, 'Send back: finish those rows').length, 1)
  assert.equal(buttons(html, 'go').length, 0, 'a go button on an unfinished run')
  assert.ok(!render(createElement(BlockedCard, { c: card(), refresh() {} })).includes('not ready for your review'))
  // a green run whose rows only miss their screenshots: the human may send it back for them, or accept it without them
  const shots = render(createElement(BlockedCard, { c: card({ ...early, parked: true, not_ready: ['1·screenshot', '2·screenshot'] }), refresh() {} }))
  assert.ok(shots.includes('Rows 1, 2 passed but link no screenshot of the verified state') && buttons(shots, 'Send back: take the screenshots').length === 1 && buttons(shots, 'go without screenshots').length === 1, shots)
  assert.equal(buttons(render(createElement(BlockedCard, { c: card({ ...early, parked: true, not_ready: ['1·screenshot', '16'] }), refresh() {} })), 'go without screenshots').length, 0, 'a blocked row too: no waiver')
})
test('inbox: a lane that cannot log in to staging → "staging login", and its pane is a masked form, not the answer box', () => {
  const q = 'CREDENTIALS NEEDED · staging · qa+admin@acme.test · login rejected: invalid credentials'
  assert.deepEqual(credentialAsk(q), { email: 'qa+admin@acme.test', why: 'login rejected: invalid credentials' })
  assert.deepEqual(credentialAsk('CREDENTIALS NEEDED · staging · qa@acme.test'), { email: 'qa@acme.test', why: '' })
  assert.deepEqual(credentialAsk('CREDENTIALS NEEDED · web · lane@acme.test · login rejected'), { email: 'lane@acme.test', why: 'login rejected' })
  assert.deepEqual(credentialAsk('CREDENTIALS NEEDED · desk · lane@north.test · login rejected'), { email: 'lane@north.test', why: 'login rejected' })
  assert.equal(credentialAsk('CREDENTIALS NEEDED · web'), null)
  assert.equal(credentialAsk('Follow the page background?'), null)
  const r = only(inbox([], { cards: [card({ ticket: 'TASK-703', assignee: 'tester-2', question: q })] }))
  assert.deepEqual([r.ticket, r.action], ['TASK-703', 'staging login'])
  const html = render(createElement(BlockedCard, { c: card({ question: q }), refresh() {} }))
  assert.match(html, /staging login needed/); assert.match(html, /type="password"/); assert.match(html, /autoComplete="new-password"|autocomplete="new-password"/)
  assert.match(html, /value="qa\+admin@acme.test"/); assert.match(html, /<button[^>]*disabled=""[^>]*>Save to vault &amp; resume/)
  assert.doesNotMatch(html, /your answer/)
  assert.match(render(createElement(BlockedCard, { c: card(), refresh() {} })), /your answer/)
})
test('kickoff: Test → tester, staging by default with a local choice; dev tickets stay intake', () => {
  const t = render(createElement(KickoffForm, { onDone() {}, initialMode: 'test' }))
  for (const s of ['Ticket → intake', 'Test → tester (plan, your go, run, your review, post)', 'PR review → reviewer', 'Question → analyst', 'staging (test accounts)', 'local (a slot of this machine)']) assert.ok(t.includes(s), s)
  assert.match(t, /it never sees a password/); assert.match(t, /Nothing destructive, nothing outside the test accounts/); assert.match(t, /Hand to a tester \(staging\)/)
  const i = render(createElement(KickoffForm, { onDone() {} }))
  assert.doesNotMatch(i, /staging \(test accounts\)/); assert.match(i, /Hand to intake/)
})
test('board: Done keeps the cards of tickets active in the last 24 h in view, in order; the rest stay behind "show N done"', () => {
  const now = Date.parse('2026-10-13T12:00:00Z'); const hAgo = (h) => new Date(now - h * 3600e3).toISOString()
  const cards = [{ id: 'a', ticket: 'TASK-1' }, { id: 'b', ticket: 'TASK-2' }, { id: 'c', ticket: 'TASK-1' }, { id: 'd', ticket: 'TASK-3' }, { id: 'e', ticket: '' }, { id: 'f', ticket: 'TASK-4' }]
  const { recent, hidden } = splitDone(cards, { 'TASK-1': hAgo(2), 'TASK-2': hAgo(30), 'TASK-4': hAgo(RECENT_HOURS) }, now)
  assert.deepEqual(recent.map((c) => c.id), ['a', 'c']); assert.deepEqual(hidden.map((c) => c.id), ['b', 'd', 'e', 'f'])
  assert.deepEqual(splitDone(cards, undefined, now).recent, [])
  const board = structuredClone(BASE.board); board.ticket_activity = { 'TASK-135': new Date(Date.now() - 3600e3).toISOString(), 'TASK-134': new Date(Date.now() - 40 * 3600e3).toISOString() }
  setFx({ board }); const html = render(createElement(Board))
  assert.match(html, /Webhook retries double-fire/); assert.doesNotMatch(html, /Review PR api#20/); assert.match(html, /show 1 done/)
  setFx({ board: { ...board, ticket_activity: {} } }); const quiet = render(createElement(Board))
  assert.doesNotMatch(quiet, /Webhook retries double-fire/); assert.match(quiet, /show 2 done/)
})
test('board: Done stacks every ticket, a single card included (newest on top); only cards without a ticket stay plain', () => {
  const units = stackByTicket([{ id: 'a', ticket: 'TASK-1' }, { id: 'b', ticket: 'TASK-2' }, { id: 'c', ticket: 'TASK-1' }, { id: 'd', ticket: '' }, { id: 'e', ticket: 'TASK-1' }])
  assert.deepEqual(units.map((u) => (u.stack ? `${u.id}[${u.cards.map((c) => c.id)}]` : u.id)), ['stack:TASK-1[a,c,e]', 'stack:TASK-2[b]', 'd'])
  assert.deepEqual(stackByTicket([]), [])
})
test('board: a Done stack shows the ticket\'s tracker title (else the newest card\'s), its count, and "show N done" sits at the bottom', () => {
  const board = structuredClone(BASE.board)
  const extra = { ...board.cards.find((c) => c.id === 't_c104'), id: 't_c106', title: 'TASK-135: Webhook retries: test the fix', completed: '2026-10-11T09:00:00Z', lane: 'tester-2' }
  board.cards.push(extra); board.cards.push({ ...extra, id: 't_c107', ticket: 'TASK-133', title: 'TASK-133: Quiet one', completed: '2026-10-08T09:00:00Z' })
  board.ticket_activity = { 'TASK-135': new Date(Date.now() - 3600e3).toISOString() }; board.ticket_titles = { 'TASK-135': '[Hooks] Webhook deliveries fire twice on retry' }
  setFx({ board }); const html = render(createElement(Board))
  assert.match(html, /cockpit-kb-stack/); assert.match(html, />2 cards</)
  assert.match(html, /class="cockpit-kb-title">\[Hooks\] Webhook deliveries fire twice on retry</)   // the tracker title is the stack's face
  assert.match(html, /newest: Webhook retries: test the fix/)                          // the newest card in the stack's tooltip
  setFx({ board: { ...board, ticket_titles: {} } })
  assert.match(render(createElement(Board)), /class="cockpit-kb-title">Webhook retries: test the fix</)   // no tracker title yet: the newest card's
  board.ticket_activity['TASK-134'] = board.ticket_activity['TASK-135']; setFx({ board })
  assert.match(render(createElement(Board)), />1 card</)                               // a single card is a stack too
  assert.doesNotMatch(html, /Webhook retries double-fire/)                            // the older card waits inside the folded stack
  assert.doesNotMatch(html, /Quiet one/); assert.match(html, /show 2 done/)           // two quiet tickets, one unit each
  const done = html.slice(html.lastIndexOf('cockpit-kb-col'))
  assert.ok(done.indexOf('show 2 done') > done.indexOf('Webhook retries: test the fix'), 'the show button comes after the cards')
})
test('outbox: What leaves shows the rendered preview first and the source (JSON / Markdown) as a second tab', () => {
  const adf = '{"type":"doc","version":1,"content":[]}'
  const jc = detail(full({ type: 'tracker-comment', payload: { issue: 'TASK-500', body_file: 'b' }, files: { body_file: '/ws/outbox/TASK-500/002-body.json' },
    file_contents: { body_file: adf }, file_html: { body_file: '<div class="cockpit-doc"><div class="cockpit-doc-panel cockpit-doc-success"><p>Tested and Ok</p></div></div>' } }))
  const leaves = jc.slice(jc.indexOf('What leaves'))
  assert.match(leaves, />Preview</); assert.match(leaves, />JSON</); assert.match(leaves, /cockpit-doc-panel cockpit-doc-success/)
  assert.doesNotMatch(leaves.slice(0, leaves.indexOf('Intent')), /&quot;type&quot;: &quot;doc&quot;/)       // the JSON waits in its tab
  const md = detail(full({ file_html: { body_file: '<p>Thanks, fixed in abc1234.</p>' } }))
  assert.match(md.slice(md.indexOf('What leaves')), />Markdown</)
  const raw = detail(full()); const rl = raw.slice(raw.indexOf('What leaves'))
  assert.doesNotMatch(rl.slice(0, rl.indexOf('Intent')), />Preview</); assert.match(rl, /Thanks, fixed in abc1234\./)   // nothing to render: the text itself
})
test('outbox: a PR\'s skipped comments (no tag, no change requested) are listed apart from the new work', () => {
  const pr = { number: 44, role: 'author', state: 'open', url: 'https://git.acme.test/x/44', total: 7, last_check: ago(1), new_count: 1,
    new: [{ id: 'rv306', author: 'hamadalidev', kind: 'review:commented', body: 'Q: are the inactive questions excluded?' }],
    skipped: [{ id: 'rv304', author: 'bob', kind: 'review:commented', why: 'no tag (B:, CS:, Q:, PP:, NTH:) and no change asked', body: 'Nice work, did not find any more remarks.' }] }
  const html = detail(full({ pr }))
  assert.match(html, /Treat 1 new comment\(s\) in the pipeline/); assert.match(html, /Skipped · 1 comment\(s\) that ask for nothing \(no tag, no change requested\)/)
  assert.doesNotMatch(detail(full({ pr: { ...pr, skipped: [] } })), /Skipped ·/)
})
test('ci override: offered on an open approval the pack allows; a given override shows its reason; otherwise nothing', () => {
  const base = { id: 'TASK-1/001-pr-review-submit', type: 'pr-review-submit', status: 'endorsed', payload: { sha: 'a1', event: 'APPROVE' } }
  assert.match(render(createElement(CiOverride, { r: { ...base, ci_override_allowed: true }, onDone() {} })), /Approve despite CI…/)
  assert.equal(render(createElement(CiOverride, { r: { ...base, ci_override_allowed: false }, onDone() {} })), '')
  assert.equal(render(createElement(CiOverride, { r: { ...base, ci_override_allowed: true, status: 'published' }, onDone() {} })), '')
  const given = render(createElement(CiOverride, { r: { ...base, ci_override_allowed: true, ci_override: { sha: 'a1', reason: 'flaky e2e', time: '2026-10-27T10:00:00Z' } }, onDone() {} }))
  assert.match(given, /CI overridden by you/)
  assert.match(given, /flaky e2e/)
  const moved = render(createElement(CiOverride, { r: { ...base, ci_override_allowed: true, ci_override: { sha: 'old', reason: 'x' } }, onDone() {} }))
  assert.match(moved, /Approve despite CI…/)
})
test('session card: an open manual session shows the slot apps as links and the pack default login preselected; closed shows nothing', () => {
  setFx({ 'session-card': { open: true, ticket: 'TASK-1', slot: 2, default: 'admin', current: { username: 'a@x.test', password: 'pw-1' },
    apps: [{ name: 'Admin', url: 'https://app.example.test:8101' }, { name: 'Web', url: 'https://web.example.test:8102' }],
    logins: [{ label: 'admin', user: 'a@x.test' }, { label: 'member', user: 'm@x.test' }] } })
  const html = render(createElement(SessionCard, { ticket: 'TASK-1' }))
  assert.match(html, /Manual session · slot 2/)
  assert.match(html, /href="https:\/\/app\.example\.test:8101"/)
  assert.match(html, /href="https:\/\/web\.example\.test:8102"/)
  assert.match(html, /<option[^>]*value="admin"[^>]*>admin · a@x\.test/)
  assert.match(html, /a@x\.test/)
  assert.match(html, /Get password/)
  setFx({ 'session-card': { open: false, ticket: 'TASK-1' } })
  assert.equal(render(createElement(SessionCard, { ticket: 'TASK-1' })), '')
})
test('demo: a staging Test run shows its prepared record, your steps and the test account (password masked); a slot demo is unchanged', () => {
  setFx({ demo: { env: 'staging', ticket: 'TASK-1', links: [{ label: 'QA TASK-1 run 001 · #11 · voiceover', url: 'https://staging.example.test/abc123' }],
    apps: [{ name: 'app', url: 'https://app.example.test', up: true }, { name: 'api', url: 'https://api.example.test', up: false }],
    steps: ['Open the order with VoiceOver on', 'Swipe to the total'], notes: 'Reply with what VoiceOver read', login: { username: 'qa+admin@acme.test', password: 's3cret' }, login_error: '' } })
  const html = render(createElement(DemoSection, { ticket: 'TASK-1' }))
  assert.match(html, /Demo · staging/); assert.match(html, /https:\/\/staging\.example\.test\/abc123/); assert.match(html, /your steps/)
  assert.match(html, /●/); assert.match(html, /○/); assert.match(html, />app</); assert.match(html, />api</)
  assert.match(html, /<li>Open the order with VoiceOver on<\/li><li>Swipe to the total<\/li>/); assert.match(html, /qa\+admin@acme\.test/)
  assert.doesNotMatch(html, /s3cret/); assert.match(html, /••••••••••••/)                       // masked until "show"
  setFx({ demo: { env: 'staging', links: [], steps: ['Open it'], login: null, login_error: 'no stored staging login for x@acme.test' } })
  const none = render(createElement(DemoSection, { ticket: 'TASK-1' })); assert.match(none, /no stored staging login for x@acme\.test/); assert.match(none, /no link recorded yet/)
  setFx({ demo: { env: 'staging', links: [], steps: [], login: null, login_error: '' } })
  const quiet = render(createElement(DemoSection, { ticket: 'TASK-1' })); assert.match(quiet, /Demo · staging/); assert.doesNotMatch(quiet, /your steps/)   // nothing for you to do: folded
  setFx({ demo: DEMO }); assert.match(render(createElement(DemoSection, { ticket: 'TASK-1' })), /Demo · slot 3/)
})
test('inbox: one row per PR — three held replies on api#44 are one row; another PR and a lone item stay their own', () => {
  const held = (n) => intent({ ticket: 'TASK-167', type: 'pr-comment', status: 'held', payload: { repo: 'api', number: 44 }, hold: { waits: 'human', reason: `reply ${n} waits for the push`, time: ago(30 + n) } })
  const other = intent({ ticket: 'TASK-167', type: 'pr-comment', status: 'held', payload: { repo: 'admin', number: 73 }, hold: { waits: 'human', reason: 'admin reply', time: ago(40) } })
  const res = inbox([held(1), held(2), held(3), other])
  assert.equal(res.rows.length, 2)
  const g = res.rows.find((r) => /api#44/.test(r.what))
  assert.equal(g.action, 'resolve hold'); assert.match(g.what, /api#44 — 3 items \(3 pr-comment\) — /); assert.equal(g.ticket, 'TASK-167')
  assert.ok(res.rows.some((r) => r.type === 'pr-comment' && /admin reply/.test(r.what)))
})
test('inbox: a push and its replies on one PR are one publish row, the push first in the panel; nothing ready says so', () => {
  const push = intent({ ticket: 'TASK-168', type: 'push-branch', status: 'endorsed', endorsed: endorsed(), order: 0, payload: { repo: 'api' }, pr: authorPr({ number: 44 }) })
  const rep = (n) => intent({ ticket: 'TASK-168', type: 'pr-comment', status: 'endorsed', endorsed: endorsed(), order: 3, payload: { repo: 'api', number: 44, in_reply_to: n } })
  const r = only(inbox([rep(1), push, rep(2)]))
  assert.equal(r.action, 'publish'); assert.match(r.what, /api#44 — 3 items \(2 pr-comment, push-branch\)|api#44 — 3 items \(push-branch, 2 pr-comment\)/)
  const members = [rep(1), push, rep(2)].map((x, i) => ({ key: 'm' + i, action: 'publish', color: GOOD, what: `${x.type} · t — endorsed`, row: x }))
  const html = render(createElement(PrGroupPanel, { g: { pr: 'api#44', members }, ticket: 'TASK-168', goOutbox() {}, onDone() {} }))
  assert.match(html, /TASK-168 · api#44/); assert.match(html, /3 items on this PR/)
  assert.match(html, /✓ Publish 3 in order \(push-branch → pr-comment → pr-comment\)/)
  assert.ok(html.indexOf(push.id) < html.indexOf(members[0].row.id), 'the push is listed first')
  assert.equal((html.match(/Open the intent/g) || []).length, 3)
  const waiting = members.map((m) => ({ ...m, action: 'resolve hold', row: { ...m.row, status: 'held' } }))
  assert.match(render(createElement(PrGroupPanel, { g: { pr: 'api#44', members: waiting }, ticket: 'TASK-168', goOutbox() {}, onDone() {} })), /Nothing on this PR is ready to publish yet/)
})
test('inbox: a chain marker without a slash still renders, and a slash shows the following id', () => {
  const plain = intent({ ticket: 'TASK-501', type: 'pr-comment', status: 'endorsed', endorsed: endorsed(), payload: { repo: 'api', number: 1, after: 'noslash' } })
  const slashed = intent({ ticket: 'TASK-502', type: 'pr-comment', status: 'endorsed', endorsed: endorsed(), payload: { repo: 'api', number: 2, after: 'TASK-502/001-push' } })
  const rows = inbox([plain, slashed]).rows
  assert.ok(rows.some((r) => r.ticket === 'TASK-501' && r.what.includes('→ after nos')), JSON.stringify(rows))
  assert.ok(rows.some((r) => r.ticket === 'TASK-502' && r.what.includes('→ after 001')), JSON.stringify(rows))
})
test('chains: a push followed by its open-pr is one Inbox row; the open-pr publishes only with its push endorsed; the Outbox says both', () => {
  const push = intent({ ticket: 'TASK-145', type: 'push-branch', status: 'endorsed', endorsed: endorsed(), payload: { repo: 'acme' }, chain: { role: 'step1', followed_by: 'TASK-145/open-pr', followed_status: 'endorsed', followers: ['TASK-145/open-pr'] } })
  const chain = { role: 'content', step1: push.id, step1_type: 'push-branch', step1_rebase: false, step1_status: 'endorsed', step1_proof: '', step1_sha: 'dcce7a01b' }
  const openPr = intent({ ticket: 'TASK-145', type: 'open-pr', status: 'endorsed', endorsed: endorsed(), payload: { repo: 'acme', after: push.id }, chain })
  const r = only(inbox([push, openPr])); assert.equal(r.action, 'publish'); assert.equal(r.type, 'open-pr')
  none(inbox([{ ...push, status: 'held', hold: { waits: 'lane', reason: 'rework', time: ago(3) } }, { ...openPr, chain: { ...chain, step1_status: 'returned' } }]))   // step 1 not ready: no publish row
  const html = detail(full({ type: 'open-pr', payload: { repo: 'acme', after: push.id, body_file: 'b' }, chain }))
  assert.match(html, /Two steps, one publish/); assert.match(html, /push-branch · TASK-145\/push-branch/); assert.match(html, /✓ Publish both \(push-branch, then open-pr\)/)
})
test('inbox: endorsed intent → publish (success), "endorsed by gatekeeper", never the model', () => {
  const r = only(inbox([intent({ ticket: 'TASK-202', status: 'endorsed', endorsed: endorsed() })]))
  assert.deepEqual([r.ticket, r.action, r.color], ['TASK-202', 'publish', GOOD])
  assert.match(r.what, /endorsed by gatekeeper/)
  assert.doesNotMatch(r.what, MODEL)
})
test('inbox: posted review → publish review (warning)', () => {
  const r = only(inbox([intent({ ticket: 'TASK-203', type: 'pr-review-submit', status: 'posted', review: { proposed_event: 'REQUEST_CHANGES', posted_at: ago(15) } })]))
  assert.deepEqual([r.action, r.color], ['publish review', WARN])
  assert.match(r.what, /pending review on the forge \(REQUEST_CHANGES\)/)
})
test('inbox: stale_head → re-review (warning), not publish, even when endorsed', () => {
  const r = only(inbox([intent({ ticket: 'TASK-204', type: 'pr-review-submit', status: 'endorsed', endorsed: endorsed(), stale_head: { reviewed: 'aaa111', now: 'bbb222' } })]))
  assert.deepEqual([r.action, r.color], ['re-review', WARN])
  assert.match(r.what, /aaa111 → bbb222/)
})
test('inbox: an endorsed later stage of a sequence is no publish row until the stage before is out', () => {
  none(inbox([intent({ ticket: 'TASK-206', status: 'endorsed', endorsed: endorsed(), waits: { id: 'TASK-206/001-push-branch', type: 'push-branch', status: 'endorsed' } })]))
  assert.equal(only(inbox([intent({ ticket: 'TASK-206', status: 'endorsed', endorsed: endorsed() })])).action, 'publish')
})
test('inbox: held, waits human → resolve hold (warning)', () => {
  const r = only(inbox([intent({ ticket: 'TASK-205', status: 'held', hold: { waits: 'human', reason: 'needs a product call', time: ago(30) } })]))
  assert.deepEqual([r.action, r.color], ['resolve hold', WARN])
  assert.match(r.what, /needs a product call/)
})
test('inbox: a confirm-only hold on a later stage waits its turn; a question is offered whenever it is asked', () => {
  const waits = { id: 'TASK-208/001-pr-edit', type: 'pr-edit', status: 'endorsed' }
  none(inbox([intent({ ticket: 'TASK-208', status: 'held', waits, hold: { waits: 'human', reason: 'the pushed range has commits by a bot', time: ago(30) } })]))
  assert.equal(only(inbox([intent({ ticket: 'TASK-208', status: 'held', waits, hold: { waits: 'human', ask: 'Which base?', reason: 'a product call', time: ago(30) } })])).action, 'decide')
})
test('inbox: held with a question → decide, and the row shows the question', () => {
  const r = only(inbox([intent({ ticket: 'TASK-207', status: 'held', hold: { waits: 'human', ask: 'Fix the group schedule mail now, or a follow-up?', rework: 'set after to 007', reason: 'Q3 is a product call', time: ago(30) } })]))
  assert.deepEqual([r.action, r.color], ['decide', WARN])
  assert.match(r.what, /the gatekeeper asks: Fix the group schedule mail now/)
})
test('decide: the decision sent back is the answer first, then the gatekeeper\'s rework', () => {
  const hold = { ask: 'Fix the mail now, or a follow-up?', rework: '1. set after to 007' }
  assert.equal(decisionText(hold, 'Ship; follow-up ticket', ' TASK-999 '), 'Decision on "Fix the mail now, or a follow-up?": Ship; follow-up ticket — TASK-999\n\nAlso, from the gatekeeper\'s hold:\n1. set after to 007')
  assert.equal(decisionText({ ask: 'Q?' }, '', 'yes'), 'Decision on "Q?": yes')
})
test('decide: the form shows the question, one choice per option, the rework collapsed, and Send decision disabled until answered', () => {
  const r = intent({ ticket: 'TASK-207', type: 'open-pr', status: 'held', created_by: 'worker-3', hold: { waits: 'human', ask: 'Fix the group schedule mail now, or a follow-up?', options: ['Fix it in this PR', 'Ship; follow-up ticket'], rework: '1. set after to 007', reason: 'Q3 is a product call', time: ago(30) } })
  const html = render(createElement(DecidePanel, { r }))
  assert.match(html, /Your decision/); assert.match(html, /Fix the group schedule mail now, or a follow-up\?/)
  assert.equal((html.match(/type="radio"/g) || []).length, 2); assert.match(html, /Fix it in this PR/); assert.match(html, /Ship; follow-up ticket/)
  assert.match(html, /What the lane also does after your answer/); assert.match(html, /a tester and a reviewer check the result/)
  assert.match(html, /<button[^>]*disabled=""[^>]*>Send decision/)
  assert.ok(html.indexOf('Chat') > -1 && html.indexOf('Chat') < html.indexOf('Your decision'), 'the chat sits above the question')
  const free = render(createElement(DecidePanel, { r: { ...r, hold: { ...r.hold, options: [] } } }))
  assert.equal((free.match(/type="radio"/g) || []).length, 0); assert.match(free, /your answer, in a line/)
})
test('decide: the Outbox detail of a held intent with a question carries the same form', () => {
  const html = detail(full({ status: 'held', hold: { waits: 'human', ask: 'Ship it as is?', options: ['Yes', 'No'], rework: 'r', reason: 'x', time: ago(5) } }))
  assert.match(html, /Your decision/); assert.match(html, /Ship it as is\?/); assert.doesNotMatch(html, /write your decision on the first line/)
  assert.equal((html.match(/Chat/g) || []).length, 1, 'one chat button per pane: the one in the decision form')
  assert.ok(html.indexOf('Chat') < html.indexOf('Your decision'))
})
test('inbox: held, waits lane → no row', () => {
  none(inbox([intent({ ticket: 'TASK-206', status: 'held', hold: { waits: 'lane', reason: 'lane is fixing the test', time: ago(30) } })]))
})
test('inbox: pending intent → no row (it is the gatekeeper\'s, shown in the Outbox)', () => {
  none(inbox([intent({ ticket: 'TASK-207', status: 'pending' })]))
})
test('inbox: ticket-done pending → confirm done (accent), sorted first even when it is the oldest', () => {
  const res = inbox([
    intent({ ticket: 'TASK-208', status: 'endorsed', endorsed: endorsed(10) }),
    intent({ ticket: 'TASK-209', type: 'ticket-done', status: 'pending', created_at: ago(5000) }),
    intent({ ticket: 'TASK-210', status: 'posted', type: 'pr-review-submit', review: { posted_at: ago(2) } }),
  ])
  assert.deepEqual(res.rows.map((r) => r.action), ['confirm done', 'publish review', 'publish'])
  assert.deepEqual([res.rows[0].ticket, res.rows[0].color], ['TASK-209', ACCENT])
})
test('inbox: CI failed and unhandled → diagnose (danger), once per ticket+sha; handled or analysing → no row', () => {
  const res = inbox([
    intent({ ticket: 'TASK-211', ci: ci() }), intent({ ticket: 'TASK-211', ci: ci() }),
    intent({ ticket: 'TASK-212', ci: ci({ handled: true }) }), intent({ ticket: 'TASK-213', ci: ci({ analysing: true }) }), intent({ ticket: 'TASK-214', ci: ci({ state: 'green' }) }),
  ])
  const r = only(res)
  assert.deepEqual([r.ticket, r.action, r.color], ['TASK-211', 'diagnose', DANGER])
})
test('inbox: author-role PR approved → merge (success); merged → no row', () => {
  const r = only(inbox([
    intent({ ticket: 'TASK-215', pr: authorPr({ approvals: [{ author: 'dev-a', at: ago(30) }] }) }),
    intent({ ticket: 'TASK-216', pr: authorPr({ merged: true, approvals: [{ author: 'dev-a', at: ago(30) }] }) }),
  ]))
  assert.deepEqual([r.ticket, r.action, r.color], ['TASK-215', 'merge', GOOD])
  assert.match(r.what, /approved by dev-a/)
})
test('inbox: author-role new PR comments → treat comments (warning)', () => {
  const r = only(inbox([intent({ ticket: 'TASK-217', pr: authorPr({ new_count: 2, new: [{ id: 1, at: ago(12) }, { id: 2, at: ago(8) }] }) })]))
  assert.deepEqual([r.action, r.color], ['treat comments', WARN])
})
test('inbox: reviewer-role PR with new comments → no treat-comments row', () => {
  none(inbox([intent({ ticket: 'TASK-218', pr: authorPr({ role: 'reviewer', new_count: 2, new: [{ id: 1, at: ago(12) }] }) })]))
})
test('inbox: reviewer PR not ready (author still on it), approved by you, merged or closed → no row', () => {
  none(inbox([revRow(revPr())]))
  none(inbox([revRow(revPr({ re_requested: true, my_review_state: 'APPROVED' }))]))
  none(inbox([revRow(revPr({ re_requested: true, merged: true }))]))
  none(inbox([revRow(revPr({ re_requested: true, state: 'closed' }))]))
})
test('inbox: reviewer PR re-requested → re-review (accent)', () => {
  const r = only(inbox([revRow(revPr({ re_requested: true }))]))
  assert.deepEqual([r.ticket, r.action, r.color], ['TASK-900', 're-review', ACCENT])
  assert.match(r.what, /AUTHOR RE-REQUESTED YOUR REVIEW/)
})
test('inbox: reviewer PR with all your threads resolved → re-review', () => {
  assert.equal(only(inbox([revRow(revPr({ my_threads: { total: 3, resolved: 3, replied: 0 } }))])).action, 're-review')
})
test('inbox: reviewer PR quiet > 120 min after a reply or a commit → re-review; nothing moved → no row; moved < 120 min ago → the row, marked still on it', () => {
  assert.equal(only(inbox([revRow(revPr({ last_activity: ago(150), my_threads: { total: 3, resolved: 1, replied: 1 } }))])).action, 're-review')
  assert.equal(only(inbox([revRow(revPr({ last_activity: ago(150), since_review: { commits: 2, files: 3 } }))])).action, 're-review')
  none(inbox([revRow(revPr({ last_activity: ago(150) }))]))
  const early = only(inbox([revRow(revPr({ last_activity: ago(100), my_threads: { total: 3, resolved: 1, replied: 2 }, since_review: { commits: 1, files: 1 } }))]))
  assert.equal(early.action, 're-review'); assert.ok(early.what.includes('the author is still on it: the re-review starts by itself after two quiet hours'))
  assert.ok(!only(inbox([revRow(revPr({ last_activity: ago(150), since_review: { commits: 2, files: 3 } }))])).what.includes('still on it'))
})
test('inbox: reviewer PR hidden while its re-review card is open, back once the card is gone', () => {
  const pr = revPr({ re_requested: true, rereview: { card: 'c-77' } })
  none(inbox([revRow(pr)], { cards: [card({ id: 'c-77', ticket: 'TASK-900', status: 'running', assignee: 'reviewer' })] }))
  assert.equal(only(inbox([revRow(pr)])).action, 're-review')
})
test('inbox: a halted ticket has no standing review row; the same PR on a ticket that is not halted has one', () => {
  const pr = revPr({ re_requested: true })
  none(inbox([{ ...revRow(pr), halted: true }]))
  assert.equal(only(inbox([revRow(pr)])).action, 're-review')
})
test('inbox: reviewer PR hidden while a review intent for that PR is open; other PR numbers or a published intent do not hide it', () => {
  const pr = revPr({ re_requested: true })
  const pending = intent({ ticket: 'TASK-900', type: 'pr-review-submit', status: 'pending', payload: { repo: 'web', number: 90 } })
  none(inbox([revRow(pr), pending]))
  const atGate = intent({ ticket: 'TASK-900', type: 'pr-review-submit', status: 'endorsed', endorsed: endorsed(), payload: { repo: 'web', number: 90 } })
  assert.deepEqual(inbox([revRow(pr), atGate]).rows.map((r) => r.action), ['publish'])
  const otherPr = intent({ ticket: 'TASK-900', type: 'pr-review-submit', status: 'pending', payload: { repo: 'web', number: 91 } })
  assert.equal(only(inbox([revRow(pr), otherPr])).action, 're-review')
  const published = intent({ ticket: 'TASK-900', type: 'pr-review-submit', status: 'published', payload: { repo: 'web', number: 90 } })
  assert.equal(only(inbox([revRow(pr), published])).action, 're-review')
})
test('inbox: failing watcher → fix watcher (danger, ticket "platform"); a healthy watcher → no row', () => {
  const r = only(inbox([], { watchers: [{ name: 'pr-watch', ok: false, fails: 3, last_ok: ago(90), reason: 'the the forge CLI login is gone: run gh auth login', error: 'gh: HTTP 401: Bad credentials' }, { name: 'ci-watch', ok: true, fails: 0, last_ok: ago(1) }] }))
  assert.deepEqual([r.ticket, r.action, r.color], ['platform', 'fix watcher', DANGER])
  assert.match(r.what, /^watcher pr-watch: the the forge CLI login is gone: run gh auth login — 3 failure\(s\) in a row, last success/)   // the sentence, never the raw output
  assert.ok(!r.what.includes('HTTP 401'))
  const bare = only(inbox([], { watchers: [{ name: 'perf', ok: false, fails: 1, last_ok: ago(90), error: 'x' }] }))   // an older record without a reason
  assert.match(bare.what, /^watcher perf: is not running properly — 1 failure\(s\)/)
})

// ================= Outbox table =================
const OUTBOX_LABELS = ['ticket', 'status', 'target', 'risk', 'type', 'PR', 'CI', 'age']
test('outbox: no "#" column: header is ticket, status, target, risk, type, PR, CI, age; rows have exactly those cells', () => {
  const t = outbox([intent({ ticket: 'TASK-301', status: 'pending', digest_no: 7 }), intent({ ticket: 'TASK-302', status: 'endorsed', endorsed: endorsed(), digest_no: 8 })])
  assert.deepEqual(t.labels, OUTBOX_LABELS)
  assert.ok(!t.labels.some((l) => l.includes('#')), 'a "#" column header')
  assert.equal(t.rows.length, 2, JSON.stringify(t.rows.map((r) => r.map((c) => c.text))))
  for (const row of t.rows) {
    assert.equal(row.length, OUTBOX_LABELS.length)
    assert.ok(!row.some((c) => /^#?[78]$/.test(c.text)), `digest number shown in a row: ${row.map((c) => c.text).join(' | ')}`)
  }
  assert.deepEqual(t.rows.map((r) => r[0].text), ['TASK-302', 'TASK-301'])   // yours (endorsed) first, then the gate's
})
test('outbox: ticket-done rows first, then by digest number', () => {
  const t = outbox([
    intent({ ticket: 'TASK-303', status: 'pending', digest_no: 1 }), intent({ ticket: 'TASK-304', status: 'endorsed', endorsed: endorsed(), digest_no: 2 }),
    intent({ ticket: 'TASK-305', type: 'ticket-done', status: 'pending', digest_no: 9 }),
  ])
  assert.deepEqual(t.rows.map((r) => [r[0].text, r[4].text]), [['TASK-305', 'ticket-done'], ['TASK-304', 'push-branch'], ['TASK-303', 'push-branch']])   // yours: the ack, then the endorsed one; in flight: the pending one
})
test('outbox: the type cell is coloured by family', () => {
  const fam = { 'ticket-done': GOOD, 'push-branch': ACCENT, 'open-pr': ACCENT, 'pr-edit': ACCENT, 'pr-comment': '#a78bfa', 'pr-review-submit': '#a78bfa',
    'tracker-comment': '#22d3ee', 'tracker-create': '#22d3ee', 'tracker-transition': '#22d3ee', 'ci-rerun': WARN, 'ci-dispatch': WARN, 'infra-change': 'var(--ui-text-secondary)' }
  const t = outbox(Object.keys(fam).map((type) => intent({ type, status: 'pending' })))
  const got = Object.fromEntries(t.rows.map((r) => [r[4].text, r[4].color]))
  assert.deepEqual(got, fam, JSON.stringify(t.rows.map((r) => r.map((c) => c.text))))
})
test('outbox: status text names the lane ("waiting for gatekeeper"), never a model, even when the record carries one', () => {
  const t = outbox([
    intent({ ticket: 'TASK-306', status: 'pending', model: 'sonnet-4-5' }),
    intent({ ticket: 'TASK-307', status: 'endorsed', endorsed: endorsed() }),
    intent({ ticket: 'TASK-308', status: 'held', hold: { reason: 'x', waits: 'human', model: 'opus-4-5' } }),
  ])
  const status = Object.fromEntries(t.rows.map((r) => [r[0].text, r[1].text]))
  assert.equal(status['TASK-306'], '· waiting for gatekeeper')   // in flight: the gate's words
  assert.match(status['TASK-307'], /publish/)                      // yours: the action
  assert.equal(status['TASK-308'], '⏸ resolve hold')
  assert.doesNotMatch(Object.values(status).join(' '), MODEL)
  assert.doesNotMatch(t.html, MODEL)
})
bug('outbox: a ticket-done awaiting your ack does not read "waiting for gatekeeper"', 'desktop/src/views/outbox.js:12 (the pending branch runs before the ticket-done branch on :15, which is unreachable)', () => {
  const t = outbox([intent({ ticket: 'TASK-309', type: 'ticket-done', status: 'pending' })])
  const status = t.rows[0][1].text
  assert.match(status, /confirm done/, `the status cell reads "${status}"`)
})

// ================= The gate under the to-do =================
const groupHeads = (html) => all(parse(html), (n) => /^cockpit-group\b/.test(cls(n))).map((n) => text(n).replace(/\s+/g, ' ').trim())
test('gate: under your rows, four collapsed groups with counts — In flight (the gate\'s and the pipeline\'s), Advisories, Published today, Dropped; closed by default, nothing of theirs renders', () => {
  STORE.showSecurity = true   // the Advisories group shows with the security box ticked
  const rows = [intent({ ticket: 'TASK-401', status: 'endorsed', endorsed: endorsed() }), intent({ ticket: 'TASK-402', status: 'pending' }),
    intent({ ticket: 'TASK-403', status: 'held', hold: { waits: 'lane', reason: 'tests first', time: ago(5) } }), intent({ ticket: 'TASK-404', status: 'returned' }),
    intent({ ticket: 'TASK-405', status: 'published', receipt: { time: ago(60), url: 'u' } }), intent({ ticket: 'TASK-406', status: 'published', receipt: { time: ago(3000), url: 'u' } }),
    intent({ ticket: 'TASK-407', status: 'dropped' }), intent({ ticket: 'TASK-408', status: 'published', type: 'push-branch', ci: ci({ state: 'running' }) })]
  setFx({ list: { counts: {}, rows }, 'needs-you': { cards: [], watchers: [] }, 'sweep-state': { running: false, requested: false } })
  const html = render(createElement(OutboxPage, { initialView: 'inbox' }))
  const heads = groupHeads(html)
  assert.ok(/^▸In flight · 4/.test(heads[0]) && /^▸Advisories · 0/.test(heads[1]) && /^▸Published today · 1 today · 2 in all/.test(heads[2]) && /^▸Dropped · 1/.test(heads[3]), heads.join(' | '))
  assert.deepEqual(table(html).rows.map((r) => r[0].text), ['TASK-401'], 'only your row renders while the groups are closed')
  const open = table(render(createElement(OutboxPage, { initialView: 'inbox', openGroups: true }))).rows.map((r) => [r[0].text, r[1].text])
  assert.deepEqual(open, [['TASK-401', '✓ publish'], ['TASK-402', '· waiting for gatekeeper'], ['TASK-403', '⏸ held'], ['TASK-404', '↩ back in the pipeline'], ['TASK-408', '↗ published'], ['TASK-405', '↗ published'], ['TASK-407', 'dropped']])
})
test('gate: the toolbar hides the tools (sweep, renumber, rescan) behind a toggle; the stored "outbox" view opens the Inbox', () => {
  setFx({ list: { counts: { endorsed: 1, held: 0, pending: 2 }, rows: [] }, 'needs-you': { cards: [], watchers: [] }, 'sweep-state': { running: false, requested: false } })
  const html = render(createElement(OutboxPage, { initialView: 'outbox' }))
  assert.ok(!html.includes('your to-do first, then the gate:'))
  assert.equal(buttons(html, 'Gate tools ▸').length, 1); assert.equal(buttons(html, 'Sweep now').length, 0)
  assert.equal(buttons(html, 'Outbox').length, 0, 'an Outbox tab')
})
test('gate: a row of yours appears once — a published intent with new PR comments is your "treat comments" row, not a Published row too; the gate sits in the list\'s footer', () => {
  STORE.showSecurity = true   // the Advisories group shows with the security box ticked
  const rows = [intent({ ticket: 'TASK-410', type: 'pr-patch-apply', status: 'published', receipt: { time: ago(30), url: 'u' }, payload: { repo: 'api', number: 44 }, pr: authorPr({ number: 44, new_count: 2, new: [{ id: 1, at: ago(3) }] }) })]
  setFx({ list: { counts: {}, rows }, 'needs-you': { cards: [], watchers: [] }, 'sweep-state': { running: false, requested: false } })
  const html = render(createElement(OutboxPage, { initialView: 'inbox', openGroups: true }))
  const t = table(html)
  assert.deepEqual(t.rows.map((r) => [r[0].text, r[1].text]), [['TASK-410', '💬 treat comments']])
  assert.ok(/Published today · 0 today · 0 in all/.test(groupHeads(html)[2]), groupHeads(html)[2])
  assert.ok(all(parse(html), (n) => /^cockpit-footer\b/.test(cls(n))).length === 1, 'the gate is not the list footer')
})
test('gate: a pane open narrows the list to ticket · status · target · type; closed, every column is back', () => {
  assert.deepEqual(pickCells(['t', 'ty', 'tg', 'r', 's', 'pr', 'ci', 'a'], true), ['t', 's', 'tg', 'ty'])
  assert.deepEqual(pickCells(['t', 'ty', 'tg', 'r', 's', 'pr', 'ci', 'a'], false), ['t', 's', 'tg', 'r', 'ty', 'pr', 'ci', 'a'])
  assert.deepEqual(LABELS.compact, ['ticket', 'status', 'target', 'type']); assert.equal(LABELS.full.length, 8)
  const tracks = (s) => s.replace(/\([^)]*\)/g, 'x').split(/\s+/).length   // a minmax(…) is one track
  assert.equal(tracks(COMPACT_COLS), 4); assert.equal(tracks(OUTBOX_COLS), 8)
})
test('bumps: the scan\'s candidates are an Inbox row per repo ("start bumps"); its pane picks the batch, Start or Dismiss; nothing runs before that', () => {
  setFx({ list: { counts: {}, rows: [] }, 'needs-you': { cards: [], watchers: [] }, 'sweep-state': { running: false, requested: false },
    bumps: { time: ago(60), repos: { 'api': [{ number: 82, title: 'Bump axios from 1.13.4 to 1.13.5', head: 'dependabot/npm_and_yarn/axios-1.13.5', url: 'u' }, { number: 79, title: 'Bump monolog', head: 'dependabot/composer/monolog', url: 'u' }], 'repo-web': [{ number: 9, title: 'Bump leftpad', head: 'renovate/leftpad', url: 'u' }] } } })
  const res = table(render(createElement(OutboxPage, { initialView: 'inbox' })))
  assert.deepEqual(res.rows.map((r) => [r[0].text, r[1].text, r[4].text]), [['bumps', '📦 start bumps', 'dependency'], ['bumps', '📦 start bumps', 'dependency']])
  assert.match(res.rows[0][2].text, /^api: 2 open bump PR\(s\) — #82 Bump axios/)
  assert.ok(!render(createElement(OutboxPage, { initialView: 'inbox' })).includes('#82 ↗'), 'the row stays narrow: the links live in the pane')
  const pane = render(createElement(BumpsPanel, { repo: 'api', prs: [{ number: 82, title: 'Bump axios', head: 'dependabot/x', url: 'u' }], onDone() {} }))
  assert.equal(buttons(pane, 'Start 1 PR(s)').length, 1); assert.equal(buttons(pane, 'Dismiss selected').length, 1); assert.ok(pane.includes('Nothing has started'))
  assert.ok(pane.includes('#82 ↗ ') && pane.includes('>Bump axios<'), 'the pane opens each PR from a button under its head')
  setFx({ bumps: { time: null, repos: {} } })
})
test('kickoff: the Bumps type takes repos by checkbox, not a ticket', () => {
  setFx({ repos: { repos: ['api', 'admin', 'shop', 'portal', 'acme'] } })
  const html = render(createElement(KickoffForm, { onDone() {}, initialMode: 'bumps' }))
  assert.equal((html.match(/type="checkbox"/g) || []).length, 5, 'one checkbox per watched repo')
  assert.ok(html.includes('shop') && html.includes('Bumps → reviewer') && html.includes('dependency-bot') && !html.includes('dependabot') && !html.includes('placeholder="TASK-136"'))
})
test('gate: a published push whose repo ran no CI is not in flight, and its CI cell says so', () => {
  const rows = [intent({ ticket: 'TASK-411', status: 'published', type: 'push-branch', receipt: { time: ago(90), url: 'u' }, ci: ci({ state: 'none', summary: 'no CI runs for this push' }) })]
  setFx({ list: { counts: {}, rows }, 'needs-you': { cards: [], watchers: [] }, 'sweep-state': { running: false, requested: false } })
  const html = render(createElement(OutboxPage, { initialView: 'inbox', openGroups: true }))
  assert.ok(/^▸?In flight · 0/.test(groupHeads(html)[0]) || /In flight · 0/.test(groupHeads(html)[0]), groupHeads(html)[0])
  const row = table(html).rows.find((r) => r[0].text === 'TASK-411'); assert.ok(row && row[6].text === 'no CI', JSON.stringify(row && row.map((c) => c.text)))
})

// ================= Detail pane =================
const OPEN_BY_DEFAULT = /^(Brief|What leaves · )/
const assertSections = (html, mustHave) => {
  const s = sections(html)
  for (const want of mustHave) assert.ok(s.some((x) => x.title.startsWith(want)), `no section "${want}" in ${JSON.stringify(s)}`)
  for (const x of s) assert.equal(x.open, OPEN_BY_DEFAULT.test(x.title), `section "${x.title}" is ${x.open ? 'open' : 'collapsed'}`)
  return s
}
for (const [type, payload] of [['pr-comment', { repo: 'web', number: 77, body_file: 'b' }], ['pr-review-submit', { repo: 'web', number: 77, event: 'COMMENT', body_file: 'b' }], ['tracker-comment', { issue: 'TASK-500', body_file: 'b' }], ['pr-patch-apply', { repo: 'web', number: 77, branch: 'feature/x', sha: 'abc1234', threads_file: 't', body_file: 'b' }]]) {
  test(`detail (${type}): Brief and What leaves open, every other section collapsed`, () => {
    const html = detail(full({ type, payload }))
    const s = assertSections(html, ['Brief', 'What leaves · TASK-500/001-body.md', 'gatekeeper check', 'Details', 'threads · TASK-500/001-threads.json', 'History · log', 'Demo · slot 3'])
    assert.equal(s.filter((x) => x.open).length, 2)
    assert.ok(html.includes('Thanks, fixed in abc1234.'), 'the outgoing text is on the page')
    assert.doesNotMatch(html, MODEL)
  })
}
test('detail (pr-patch-apply): the Diff tab names what gets pushed', () => {
  assert.ok(detail(full({ type: 'pr-patch-apply', payload: { repo: 'web', number: 77, branch: 'feature/x', sha: 'abc1234', body_file: 'b' } })).includes('Diff (what gets pushed)'))
})
test('detail (push-branch): no What leaves; Brief open; PR · CI collapsed while nothing needs you, open on new comments', () => {
  const quiet = detail(full({ type: 'push-branch', outgoing: undefined, payload: { repo: 'api', branch: 'feature/x', sha: 'abc1234' }, pr: authorPr(), ci: ci({ state: 'green' }) }))
  const s = assertSections(quiet, ['Brief', 'PR · CI', 'Details'])
  assert.ok(!s.some((x) => x.title.startsWith('What leaves')), 'What leaves without an outgoing file')
  const loud = sections(detail(full({ type: 'push-branch', outgoing: undefined, payload: { repo: 'api' }, pr: authorPr({ new_count: 1, new: [{ id: 1, at: ago(3), author: 'dev-a', kind: 'review', body: 'nit' }] }) })))
  assert.equal(loud.find((x) => x.title.startsWith('PR · CI')).open, true)
})
const assertToolsOrder = (html, where) => {
  const chat = html.indexOf('Chat'); const brief = html.indexOf('>Brief<'); const demo = html.indexOf('Demo · slot 3')
  assert.ok(chat >= 0 && brief >= 0 && demo >= 0, `${where}: chat ${chat}, Brief ${brief}, demo ${demo}`)
  assert.ok(chat < brief && brief < demo, `${where}: expected chat < Brief < Demo, got ${chat} / ${brief} / ${demo}`)
}
test('detail: every pane of a ticket has one Open IDE beside the chat (outbox detail, blocked card, re-review panel, decision)', () => {
  const one = (html, where) => { assert.equal(buttons(html, 'Open IDE').length, 1, where); assert.ok(html.indexOf('Chat') < html.indexOf('Open IDE'), `${where}: Open IDE before the chat`) }
  one(detail(full()), 'outbox Detail')
  setFx({ demo: DEMO, 'card-detail': { id: 'c-1', title: 'TASK-700 intake plan', status: 'blocked', assignee: 'intake', attachments: { docs: [], dirs: [], files: [], brief: '<p>b</p>' }, body_html: '', comments: [], events: [], prs: [] } })
  one(render(createElement(BlockedCard, { c: card(), refresh() {} })), 'Inbox blocked card')
  setFx({ demo: DEMO })
  one(render(createElement(ReReviewPanel, { ticket: 'TASK-900', pr: revPr({ re_requested: true }), onDone() {} })), 'Inbox re-review panel')
})
test('detail: TicketTools chat sits above the Brief, the Demo right under it (outbox detail, blocked card, re-review panel)', () => {
  assertToolsOrder(detail(full()), 'outbox Detail')
  setFx({ demo: DEMO, 'card-detail': { id: 'c-1', title: 'TASK-700 intake plan', status: 'blocked', assignee: 'intake', attachments: { docs: [], dirs: [], files: [], brief: '<p>b</p>' }, body_html: '', comments: [], events: [], prs: [] } })
  assertToolsOrder(render(createElement(BlockedCard, { c: card(), refresh() {} })), 'Inbox blocked card')
  setFx({ demo: DEMO })
  assertToolsOrder(render(createElement(ReReviewPanel, { ticket: 'TASK-900', pr: revPr({ re_requested: true }), onDone() {} })), 'Inbox re-review panel')
})
test('detail: stale_head shows the re-review warning and disables Publish; without it Publish is enabled', () => {
  const stale = detail(full({ type: 'pr-review-submit', payload: { repo: 'web', number: 77, event: 'COMMENT', body_file: 'b' }, stale_head: { reviewed: 'aaa111', now: 'bbb222' } }))
  assert.ok(stale.includes('PR head moved'), 'no stale-head warning')
  assert.equal(buttons(stale, '↻ Re-review at the new head').length, 1)
  const pub = buttons(stale, /^✓ (Publish|Post as pending review)/)
  assert.equal(pub.length, 1)
  assert.ok('disabled' in pub[0].attrs, 'Publish is enabled on a stale head')
  const fresh = detail(full({ type: 'pr-review-submit', payload: { repo: 'web', number: 77, event: 'COMMENT', body_file: 'b' } }))
  assert.ok(!fresh.includes('PR head moved'))
  assert.ok(!('disabled' in buttons(fresh, /^✓ (Publish|Post as pending review)/)[0].attrs), 'Publish disabled without a stale head')
})
test('detail: a stage that waits names what it waits for and disables Publish (a stage, or CI for an approval)', () => {
  const staged = detail(full({ status: 'endorsed', endorsed: endorsed(), waits: { id: 'TASK-1/002-pr-edit', type: 'pr-edit', status: 'endorsed' } }))
  assert.ok(staged.includes('offered once TASK-1/002-pr-edit (pr-edit) is out; it is endorsed.'), 'no stage line')
  assert.ok('disabled' in buttons(staged, /^✓ Publish/)[0].attrs, 'Publish enabled on a waiting stage')
  const ci = detail(full({ status: 'endorsed', endorsed: endorsed(), waits: { id: 'CI', type: 'ci', status: 'running' } }))
  assert.ok(ci.includes('offered once CI at its commit is green (CI running).'), 'no CI line')
  const free = detail(full({ status: 'endorsed', endorsed: endorsed() }))
  assert.ok(!free.includes('A stage of a sequence'))
  assert.ok(!('disabled' in buttons(free, /^✓ Publish/)[0].attrs), 'Publish disabled without a wait')
})
test('detail: a blocked card working in a ticket worktree shows that worktree\'s diff (vs origin, the uncommitted patch included) with Open IDE; other cards do not', () => {
  const cd = (over) => ({ id: 'c-1', title: 'TASK-700 patch api#10', status: 'blocked', assignee: 'worker-1', attachments: { docs: [], dirs: [], files: [], brief: '<p>b</p>' }, body_html: '', comments: [], events: [], prs: [], ...over })
  const view = (over) => { setFx({ demo: DEMO, 'card-detail': cd(over) }); return render(createElement(BlockedCard, { c: card({ assignee: 'worker-1', title: 'TASK-700 patch api#10' }), refresh() {} })) }
  const wt = view({ worktree: { ticket: 'TASK-700', repo: 'api' } }); const none = view({})
  assert.ok(wt.includes('Diff · api worktree (vs origin, the uncommitted patch included)'), 'no worktree diff section')
  assert.ok(!none.includes('worktree (vs origin'), 'a worktree diff section on a card without a worktree')
  assert.equal(buttons(wt, 'Open IDE').length, buttons(none, 'Open IDE').length + 1)
  setFx({ demo: DEMO })
})
test('header: a "Chat" next to + Kick off opens your own coding tool (ticket "own"), outside every flow', () => {
  setFx({ 'chat-state': { exists: false, running: false, best: null } })
  const html = render(createElement(OutboxPage, { initialView: 'inbox' }))
  const kick = buttons(html, '+ Kick off'); const chat = buttons(html, 'Chat')
  assert.equal(kick.length, 1); assert.equal(chat.length, 1)
  assert.ok(html.indexOf('+ Kick off') < html.indexOf('Chat'), 'the chat sits right after Kick off')
  assert.match(chat[0].attrs.title || '', /outside every flow/)
  const modal = render(createElement(TerminalModal, { ticket: 'own', onClose() {} }))
  assert.ok(modal.includes('coding tool · yours') && !modal.includes('own · coding tool'))
})
test('chat: the terminal widget is part of the bundle, so the frame\'s page loads nothing from the network', () => {
  const modal = render(createElement(TerminalModal, { ticket: 'TASK-700', onClose() {} }))
  const frame = modal.match(/<iframe[^>]*\ssrc="([^"]*)"/)
  assert.ok(frame, 'the frame is given its page as an address of its own')
  const page = decodeURIComponent(decode(frame[1]).replace(/^data:text\/html;charset=utf-8,/, ''))
  assert.ok(page.length > 250000 && page.includes('e.Terminal=') && page.includes('FitAddon') && page.includes('.xterm-viewport'), 'the widget, its fit addon and its styles are inline')
  assert.deepEqual(page.match(/<(script|link|img|iframe)[^>]*\s(src|href)=/g), null, 'no element of the page names an address')
  assert.ok(!/cdn\.|jsdelivr|unpkg|sourceMappingURL/.test(page), 'no content network and no source map is asked for')
  assert.equal((page.match(/<\/script>/g) || []).length, 3, 'three scripts, each closed once: the widget, the addon, the wiring')
})
test('tickets and PR rows: a "Rework" opens the form that sends what is missing to the worker (tester and reviewer behind)', () => {
  const html = render(createElement(ReworkForm, { ticket: 'TASK-700', repos: ['api', 'shop'], onDone() {} }))
  assert.ok(html.includes('Rework TASK-700: what is missing') && html.includes('For a change of plan use Reopen instead'))
  assert.equal((html.match(/type="checkbox"/g) || []).length, 2, 'one checkbox per repo when there are several')
  assert.equal(buttons(html, /^Rework api, shop/).length, 1)
  const part = render(createElement(ReworkForm, { ticket: 'TASK-700', repos: ['acme', 'api'], delivered: ['acme'], onDone() {} }))
  assert.ok(part.includes('api (nothing delivered)') && buttons(part, /^Rework acme$/).length === 1, 'a reproduction-only worktree is offered unchecked and named so')
  assert.equal((part.match(/disabled=""/g) || []).length >= 1, true)
  setFx({ 'card-detail': null })
  const grp = { pr: 'api#44', members: [{ key: 'k', action: 'publish', color: '#000', what: 'x — y', row: { id: 'TASK-700/001-push-branch', status: 'endorsed', order: 1 } }] }
  const panel = render(createElement(PrGroupPanel, { g: grp, ticket: 'TASK-700', goOutbox() {}, onDone() {} }))
  assert.equal(buttons(panel, 'Rework').length, 1)
})

// ================= Diff view =================
const fileDiff = (p) => `diff --git a/${p} b/${p}\nindex 1111111..2222222 100644\n--- a/${p}\n+++ b/${p}\n@@ -1,1 +1,2 @@\n context\n+added\n`
function diffItems(paths) {
  const html = render(createElement(DiffView, { data: { diff: paths.map(fileDiff).join(''), repo: 'api', range: 'rc..HEAD', mode: 'rc' } }))
  const box = all(parse(html), (n) => /^cockpit-diff\b/.test(cls(n)))[0]
  return elems(box).flatMap((n) => {
    if (cls(n) === 'f') { const s = elems(elems(n)[0]); return [{ file: text(s[1]).replace(/ · test$/, ''), test: text(s[1]).endsWith(' · test'), open: text(s[0]) === '▾' }] }
    return /^tests \(/.test(text(n)) ? [{ divider: text(n) }] : []
  })
}
test('diff: code files first (in diff order), then the tests behind a "tests (N file(s), collapsed)" divider; tests collapsed, code open', () => {
  const items = diffItems(['tests/Unit/AFooTest.php', 'src/orders/totals.php', 'src/__tests__/b.js', 'src/orders/lines.php'])
  assert.deepEqual(items, [
    { file: 'src/orders/totals.php', test: false, open: true },
    { file: 'src/orders/lines.php', test: false, open: true },
    { divider: 'tests (2 file(s), collapsed)' },
    { file: 'tests/Unit/AFooTest.php', test: true, open: false },
    { file: 'src/__tests__/b.js', test: true, open: false },
  ])
  assert.ok(!diffItems(['src/a.php', 'src/b.php']).some((x) => x.divider), 'a divider without test files')
})
test('diff: what counts as a test file', () => {
  const cases = {
    'tests/Unit/Foo.php': true, 'test/helpers.js': true, 'src/__tests__/foo.js': true, 'src/order.spec.ts': true, 'src/widget.cy.js': true,
    'app/Services/BarTest.php': true, 'database/factories/UserFactory.php': true,
    'src/orders/Test/Service.php': false, 'src/contest/entry.js': false, 'app/Services/Testing.php': false, 'src/order.ts': false,
  }
  const got = Object.fromEntries(diffItems(Object.keys(cases)).filter((x) => x.file).map((x) => [x.file, x.test]))
  assert.deepEqual(got, cases)
})
test('diff: a worktree\'s uncommitted changes (no intent) are the patch under review, labelled so and open; under an intent they stay "not part of the intent", collapsed', () => {
  const unc = (intent) => {
    const html = render(createElement(DiffView, { data: { diff: '', repo: 'api', range: 'origin/b..HEAD', mode: 'origin', remote_exists: true, fast_forward: true, commits: [], uncommitted_status: 'M src/a.php', uncommitted_diff: fileDiff('src/a.php'), ...(intent ? { intent } : {}) } }))
    const label = html.includes('not committed or pushed yet') ? 'patch' : html.includes('not part of the intent') ? 'intent' : '?'
    return { label, open: all(parse(html), (n) => cls(n) === 'f').map((n) => text(elems(elems(n)[0])[0]) === '▾') }
  }
  assert.deepEqual(unc(null), { label: 'patch', open: [true] })
  assert.deepEqual(unc('TASK-1/004-pr-patch-apply'), { label: 'intent', open: [false] })
})

// ================= Advisories =================
const advisory = (over = {}) => ({ id: 'OSV-aaaa-bbbb-cccc', title: 'prototype pollution in a parser', severity: 'critical', status: 'fix-available', trust: 'high', exploited: false, alert: true, acknowledged: null, last_seen: ago(10),
  hits: [{ kind: 'package', ecosystem: 'npm', name: 'tiny-parser', version: '1.2.0', repo: 'api', where: 'package-lock.json:9', production: true, fixed_in: '1.2.4', version_checked: true }],
  fix: { time: null, versions: ['1.2.4'] }, via: ['osv'], url: 'https://osv.example/OSV-aaaa-bbbb-cccc', summary: 'prototype pollution — critical — hits: api tiny-parser 1.2.0 — fixed in 1.2.4', bump_prs: [], ...over })
test('inbox: step 1 of a chain that the gatekeeper holds with a question is your decide row, not hidden behind its pair in In flight', () => {
  const step1 = intent({ id: 'TASK-501/002-push-branch', ticket: 'TASK-501', type: 'push-branch', status: 'held', chain: { followed_by: 'TASK-501/003-open-pr' },
    hold: { waits: 'human', ask: 'May the rework also cover the invoice?', options: ['Yes', 'No'], reason: 'scope', time: ago(5) } })
  const step2 = intent({ id: 'TASK-501/003-open-pr', ticket: 'TASK-501', type: 'open-pr', status: 'pending', payload: { repo: 'api', after: 'TASK-501/002-push-branch' }, chain: { role: 'content', step1_status: 'held' } })
  setFx({ list: { counts: { held: 1, pending: 1 }, rows: [step1, step2] }, 'needs-you': { cards: [], watchers: [] }, 'sweep-state': { running: false, requested: false } })
  const html = render(createElement(OutboxPage, { initialView: 'inbox', openGroups: true }))
  const rows = table(html).rows.map((cells) => cells.map((c) => c.text).join(' | '))
  assert.ok(rows.some((r) => /the gatekeeper asks: May the rework also cover the invoice\?/.test(r) && /decide/.test(r)), rows.join('\n'))
  const flight = groupHeads(html).find((g) => /In flight/.test(g))
  assert.match(flight, /In flight · 1/)                                                             // only step 2 is the gate's
  const quiet = intent({ ...step1, status: 'held', hold: { waits: 'lane', reason: 'the tester still runs', time: ago(5) } })
  setFx({ list: { counts: { held: 1, pending: 1 }, rows: [quiet, step2] }, 'needs-you': { cards: [], watchers: [] }, 'sweep-state': { running: false, requested: false } })
  const lane = table(render(createElement(OutboxPage, { initialView: 'inbox', openGroups: true }))).rows.map((cells) => cells.map((c) => c.text).join(' | '))
  assert.ok(!lane.some((r) => /the gatekeeper asks/.test(r)))                                        // a hold that waits on a lane stays paired
})
test('inbox summary: one line over your rows counts them by what they ask; with none it says so', () => {
  const rows = [intent({ ticket: 'TASK-601', status: 'endorsed', endorsed: endorsed() }), intent({ ticket: 'TASK-602', status: 'endorsed', endorsed: endorsed() }),
    intent({ ticket: 'TASK-603', status: 'held', hold: { waits: 'human', ask: 'scope?', options: ['a', 'b'], reason: 'r', time: ago(3) } })]
  setFx({ list: { counts: {}, rows }, 'needs-you': { cards: [], watchers: [] }, 'sweep-state': { running: false, requested: false } })
  const html = render(createElement(OutboxPage, { initialView: 'inbox' }))
  assert.match(html, /data-inbox-summary="3"/)
  assert.match(html, /3 for you: 2 publish · 1 decide/)
  setFx({ list: { counts: {}, rows: [] }, 'needs-you': { cards: [], watchers: [] }, 'sweep-state': { running: false, requested: false } })
  assert.match(render(createElement(OutboxPage, { initialView: 'inbox' })), /nothing for you/)
})
test('security box: unticked by default, advisory rows and the Advisories group are hidden and the chip leaves them out; ticked, they show', () => {
  const fx = { list: { counts: {}, rows: [] }, 'needs-you': { cards: [], watchers: [] }, 'sweep-state': { running: false, requested: false }, advisories: { advisories: [advisory()], sources: {} } }
  delete STORE.showSecurity
  setFx(fx)
  const off = render(createElement(OutboxPage, { initialView: 'inbox' }))
  assert.match(off, /data-security-toggle="off"/)
  assert.match(off, /Show security advisories \(1 alert\)/)
  assert.doesNotMatch(off, /critical advisory/)
  assert.ok(!groupHeads(off).some((g) => /Advisories/.test(g)))
  assert.doesNotMatch(render(chip.render()), /need you/)
  STORE.showSecurity = true
  const on = render(createElement(OutboxPage, { initialView: 'inbox' }))
  assert.match(on, /data-security-toggle="on"/)
  assert.match(on, /critical advisory/)
  assert.ok(groupHeads(on).some((g) => /Advisories/.test(g)))
  delete STORE.showSecurity
})
test('advisories: an alert is an Inbox row (danger for a critical); an acknowledged one or the backlog is not', () => {
  STORE.showSecurity = true
  const rows = (advs) => { setFx({ list: { counts: {}, rows: [] }, 'needs-you': { cards: [], watchers: [] }, 'sweep-state': { running: false, requested: false }, advisories: { advisories: advs, sources: {} } })
    return table(render(createElement(OutboxPage, { initialView: 'inbox' }))).rows.map(([tk, a, w]) => ({ ticket: tk.text, action: a.text.replace(/^\S*\s/, ''), color: a.color, what: w.text })) }
  const one = rows([advisory()])
  assert.deepEqual(one.map((r) => [r.ticket, r.action, r.color]), [['platform', 'advisory', DANGER]])
  assert.match(one[0].what, /^critical advisory: prototype pollution in a parser — hits tiny-parser 1\.2\.0 · fixed in 1\.2\.4/)
  assert.deepEqual(rows([advisory({ acknowledged: { time: ago(5), note: 'not reachable' } }), advisory({ id: 'CVE-2026-1', alert: false, severity: 'medium' })]), [])
})
test('advisories: the Inbox footer has an Advisories group with every advisory, the backlog included', () => {
  STORE.showSecurity = true
  setFx({ list: { counts: {}, rows: [] }, 'needs-you': { cards: [], watchers: [] }, 'sweep-state': { running: false, requested: false },
    advisories: { advisories: [advisory(), advisory({ id: 'CVE-2026-1', alert: false, severity: 'medium', bump_prs: [{ repo: 'api', number: 31, covers: ['tiny-parser'] }] })], sources: {} } })
  const closed = render(createElement(OutboxPage, { initialView: 'inbox' }))
  assert.ok(groupHeads(closed).some((g) => /^▸Advisories · 2/.test(g)), groupHeads(closed).join(' | '))
  const open = render(createElement(OutboxPage, { initialView: 'inbox', openGroups: true }))
  assert.equal(all(parse(open), (n) => n.attrs && n.attrs['data-advisory']).length, 2)
  assert.match(open, /🤖 #31/)
})
test('advisories: the pane acknowledges with a note or makes an analyst card; an acknowledged one offers Unacknowledge', () => {
  const fresh = render(createElement(AdvisoryPanel, { a: advisory(), onDone() {} }))
  assert.equal(buttons(fresh, 'Acknowledge').length, 1)
  assert.equal(buttons(fresh, 'Make an analyst card').length, 1)
  assert.match(fresh, /tiny-parser/)
  assert.match(fresh, /fixed in 1\.2\.4/)
  const acked = render(createElement(AdvisoryPanel, { a: advisory({ acknowledged: { time: ago(5), note: 'not reachable here' } }), onDone() {} }))
  assert.equal(buttons(acked, 'Unacknowledge').length, 1)
  assert.equal(buttons(acked, 'Acknowledge').length, 0)
  assert.match(acked, /not reachable here/)
})
test('live: a stamp is shown on this machine\'s clock; one that names no zone is shown as written', () => {
  const at = new Date('2026-11-17T13:30:31Z'); const local = [at.getHours(), at.getMinutes(), at.getSeconds()].map((n) => String(n).padStart(2, '0')).join(':')
  assert.equal(clockOf('2026-11-17T13:30:31Z'), local)
  assert.equal(clockOf('2026-11-17T13:30:31Z', 5), local.slice(0, 5))
  assert.equal(clockOf('2026-11-17 13:30:31'), '13:30:31')
  assert.equal(clockOf(''), '')
})
test('advisories: the Platform tab lists every advisory with the sources\' health; its seg counts the open alerts', () => {
  const data = { time: ago(3), advisories: [advisory(), advisory({ id: 'CVE-2026-2', alert: false, acknowledged: { time: ago(1), note: 'ok' } })],
    sources: { osv: { ok: true, checked: '2026-10-23T09:30:00+00:00' }, kev: { ok: false, error: 'timeout' } }, manifest: { components: { package: 12, runtime: 2 } } }
  const tab = render(createElement(AdvisoriesTab, { data, onDone() {} }))
  assert.equal(all(parse(tab), (n) => n.attrs && n.attrs['data-advisory']).length, 2)
  // the time of day is this machine's, not the stamp's UTC digits
  const checkedAt = new Date('2026-10-23T09:30:00+00:00'); const local = [checkedAt.getHours(), checkedAt.getMinutes()].map((n) => String(n).padStart(2, '0')).join(':')
  assert.ok(tab.includes(`osv ok ${local} · kev failed: timeout`), tab.slice(0, 400))
  assert.match(tab, /12 package · 2 runtime/)
  setFx({ advisories: data })
  const page = render(createElement(OutboxPage, { initialView: 'platform' }))
  assert.equal(buttons(page, 'Advisories · 1 alert(s)').length, 1)
})

test('card: the pane lists the card\'s own open PRs; merged and closed ones sit under a collapsed "closed" line', () => {
  const pr = (number, over = {}) => ({ repo: 'api', number, url: 'https://git.acme.test/acme/api/pull/' + number, title: 'bump', state: 'open', merged: false, closed: false, ...over })
  setFx({ demo: DEMO, 'card-detail': { id: 'c-1', title: 'TASK-700 bumps on api', status: 'blocked', assignee: 'reviewer', attachments: { docs: [], dirs: [], files: [], brief: null }, body_html: '', comments: [], events: [],
    prs: [pr(11), pr(9, { merged: true, closed: true })] } })
  const html = render(createElement(BlockedCard, { c: card({ assignee: 'reviewer', title: 'TASK-700 bumps on api' }), refresh() {} }))
  assert.equal(buttons(html, 'api #11 ↗').length, 1)
  assert.match(html, /<details[^>]*><summary[^>]*>closed \(1\)<\/summary>/)
  assert.ok(html.indexOf('api #11') < html.indexOf('closed (1)'), 'the open PR comes first')
})

// ================= Platform =================
test('platform: a stored verdict is text the analyst can replace, and an object verdict still reads as a brief', () => {
  const change = { title: 'landed', author: 'dev', merged_at: 1, status: 'relevant', nodes: [], files: ['src/app.ts'], functional: ['src/app.ts'], seen: false }
  setFx({ 'platform-change': { ...change, verdict: 'real flow on the pack' } })
  const html = render(createElement(ChangeModal, { repo: 'api', number: 6, byId: {}, onClose() {}, onSeen() {}, onUnseen() {} }))
  assert.match(html, /Analyst verdict/)
  assert.match(html, /real flow on the pack/)
  assert.match(html, /Files by area \(1 functional of 1\)/)
  assert.doesNotMatch(html, /undefined/)
  assert.match(html, /Save verdict/)
  assert.doesNotMatch(html, /User change/)
  assert.equal(changeLabel({ title: 'landed', verdict: 'real flow on the pack' }), 'real flow on the pack')
  assert.equal(changeLabel({ title: 'landed', verdict: { user_change: 'the button moved' } }), 'the button moved')
  assert.equal(changeLabel({ title: 'landed' }), 'landed')
  assert.equal(fileOf('src/app.ts'), 'src/app.ts')
  assert.equal(fileOf({ path: 'src/web.ts', add: 1, del_: 2 }), 'src/web.ts')
  const pop = render(createElement(MapPopover, { node: { id: 'n', title: 'Area', kind: 'feature', user: 'opens it' }, byId: {}, changes: [{ repo: 'api', number: 6, title: 'landed', status: 'relevant', seen: false, verdict: 'real flow on the pack' }], onDetails() {}, onClose() {}, onOpenChange() {}, onRead() {} }))
  assert.match(pop, /real flow on the pack/)
  setFx({ 'platform-change': { ...change, verdict: { user_change: 'the button moved', flow_changed: true, risk: 'low', why_it_matters: 'clicks', notes: [] } } })
  const objectHtml = render(createElement(ChangeModal, { repo: 'api', number: 6, byId: {}, onClose() {}, onSeen() {}, onUnseen() {} }))
  assert.match(objectHtml, /User change/)
  assert.match(objectHtml, /the button moved/)
  assert.match(objectHtml, /Save verdict/)
})
test('platform: the time window reads 24 h · 1 week · 2 weeks · 1 month, 24 h selected by default', () => {
  setFx()
  const html = render(createElement(OutboxPage, { initialView: 'platform' }))
  const win = buttons(html, /^(24 h|1 week|2 weeks|1 month|\d+ days?)$/)
  assert.deepEqual(win.map(text), ['24 h', '1 week', '2 weeks', '1 month'])
  assert.match(win[0].attrs.style, /background:var\(--ui-accent\)/)
})
test('chip: an alertable advisory counts as a need and notifies once; an acknowledged one does not', () => {
  STORE.showSecurity = true
  const run = (advs) => {
    setFx({ list: { counts: {}, rows: [] }, 'needs-you': { cards: [], watchers: [] }, advisories: { advisories: advs, sources: {} } })
    notes.length = 0
    const html = render(chip.render())
    for (const fn of globalThis.__cockpitEffects.splice(0)) fn()
    return { html, notes: [...notes] }
  }
  const alerting = run([advisory()])
  assert.match(alerting.html, /cockpit · 1 need you/)
  assert.match(alerting.html, /1 advisories/)
  assert.ok(alerting.notes.some((n) => n.title === 'Stack advisory: a component we run is vulnerable' && /OSV-aaaa-bbbb-cccc/.test(n.body)))
  const quiet = run([advisory({ acknowledged: { time: ago(5), note: 'not reachable' } }), advisory({ id: 'CVE-2026-1', alert: false })])
  assert.doesNotMatch(quiet.html, /need you/)
  assert.ok(!quiet.notes.some((n) => /advisory/.test(n.title)))
})
test('advisories: the pane links every source the advisory names', () => {
  const html = render(createElement(AdvisoryPanel, { a: advisory({ sources: [{ name: 'osv.dev', url: 'https://osv.example/a' }, { name: 'nvd', url: 'https://nvd.example/a' }, { name: 'no link' }] }), onDone() {} }))
  assert.match(html, /osv\.dev/)
  assert.match(html, /href="https:\/\/nvd\.example\/a"/)
  assert.doesNotMatch(html, /no link/)
})
test('outbox: an endorsed stage that waits for the one before it says so in its row', () => {
  const rows = [intent({ ticket: 'TASK-402', type: 'open-pr', status: 'endorsed', endorsed: endorsed(), waits: { id: 'TASK-402/001-push-branch', type: 'push-branch', status: 'pending' } }),
    intent({ ticket: 'TASK-403', type: 'push-branch', status: 'endorsed', endorsed: endorsed(), waits: { id: 'CI', status: 'running' } })]
  setFx({ list: { counts: { endorsed: 2 }, rows }, 'needs-you': { cards: [], watchers: [] }, 'sweep-state': { running: false, requested: false } })
  const html = render(createElement(OutboxPage, { initialView: 'inbox', openGroups: true }))
  assert.match(html, /next after 001-push-branch \(pending\)/)
  assert.match(html, /next after CI running/)
})
test('chip: no notification for rc changes (the platform feed), while the outbox ones still fire', () => {
  const run = (withPlatform) => {
    const fx = { list: { counts: { endorsed: 1 }, rows: [intent({ ticket: 'TASK-401', status: 'endorsed', endorsed: endorsed() })] }, 'needs-you': { cards: [], watchers: [] } }
    if (withPlatform) fx.platform = { ...BASE.platform, changes: [1, 2, 3].map((n) => ({ repo: 'api', number: 4400 + n, title: 'rc change ' + n, author: 'dev-a', merged_at: ago(30 * n), status: 'explained', seen: false, nodes: ['checkout'] })) }
    setFx(fx); if (!withPlatform) delete FX.platform
    notes.length = 0; calls.queries.length = 0
    const html = render(chip.render())
    for (const fn of globalThis.__cockpitEffects.splice(0)) fn()
    return { html, notes: [...notes], queries: calls.queries.map((k) => String(k[1])) }
  }
  const a = run(true); const b = run(false)
  assert.ok(a.notes.some((n) => n.title === 'Outbox: endorsed, waiting for you'), 'control: the endorsed notification did not fire')
  for (const n of a.notes) assert.doesNotMatch(`${n.title} ${n.body}`, /\brc\b|platform|merged|landed|rc change/i)
  assert.ok(!a.queries.some((k) => k.startsWith('platform')), `the Chip reads ${a.queries.join(', ')}`)
  assert.equal(a.html, b.html, 'unread rc changes change the Chip')
  assert.deepEqual(a.notes.map((n) => n.title), b.notes.map((n) => n.title))
})

// ---------- post(): one dispatch at a time ----------
await (async () => {
  const name = 'post: the same dispatch is refused while one is in flight (and right after it returns); repeatable calls are not'
  try {
    const { post } = mod; const saved = ctx.rest; const pending = []   // [path, body, resolve] per call that reached the backend
    ctx.rest = (p, o) => new Promise((r) => { pending.push([p, o && o.body, r]) })
    const a = post('/kickoff', { ticket: 'TASK-1', mode: 'review' }); let refused = ''
    await post('/kickoff', { ticket: 'TASK-1', mode: 'review' }).catch((e) => { refused = e.message })
    assert.equal(refused, 'kickoff: already running — wait for it to finish'); assert.equal(pending.length, 1, 'the second click never reached the backend')
    post('/kickoff', { ticket: 'TASK-2', mode: 'review' }).catch(() => {}); assert.equal(pending.length, 2, 'a different dispatch goes through')
    post('/chat-write', { data: 'x' }); post('/chat-write', { data: 'x' }); assert.equal(pending.length, 4, 'repeatable calls are never held')
    pending[0][2]({ ok: true }); await a
    await post('/kickoff', { ticket: 'TASK-1', mode: 'review' }).catch((e) => { refused = e.message }); assert.equal(pending.length, 4, 'the cooldown after a success still refuses it')
    ctx.rest = (p) => Promise.reject(new Error('409 nope')); await post('/answer', { id: 't_1', text: 'go' }).catch(() => {})
    ctx.rest = (p, o) => { pending.push([p, o && o.body]); return Promise.resolve({}) }; await post('/answer', { id: 't_1', text: 'go' }); assert.equal(pending.length, 5, 'a failure frees the key at once: the corrected retry goes through')
    ctx.rest = saved; results.push(['ok  ', name])
  } catch (e) { results.push(['FAIL', name, e.message]) }
})()


test('tables and panes: a visible, styled horizontal scrollbar — the CSS draws it for .cockpit-table/.cockpit-scroll and the table wrappers carry the class', () => {
  const css = readFileSync(src('lib/sdk.js'), 'utf8')
  assert.ok(css.includes('.cockpit-table::-webkit-scrollbar,.cockpit-scroll::-webkit-scrollbar') && css.includes('::-webkit-scrollbar-thumb{background:color-mix') && css.includes('.cockpit-scroll{overflow-x:auto}'))
  assert.ok(!/scrollbar-(width|color)\s*:/.test(css), 'the standard scrollbar-* properties switch the ::-webkit-scrollbar styling off in Chromium')
  for (const f of ['views/usage.js', 'views/live.js']) assert.ok(readFileSync(src(f), 'utf8').includes("'cockpit-scroll "), f)
  assert.ok(/className: 'cockpit-scroll flex min-w-0 flex-col overflow-auto'/.test(css) && /className: 'cockpit-scroll min-h-0 flex-1 overflow-auto flex flex-col'/.test(css), 'the list column and the pane scroll with the styled bar')
})


test('inbox: the standup draft is a row with Confirm; its pane previews the note, keeps the text editable, and offers Update and Confirm & send', () => {
  const draft = { day: '2026-10-16', status: 'draft', items: 3, since: '2026-10-15T11:00+02:00', drafted_at: new Date().toISOString(), markdown: '**Standup**\n- we tested [TASK-1](https://j/browse/TASK-1)\n', markdown_html: '<p><strong>Standup</strong></p>', note: '*Standup*\n- we tested <https://j/browse/TASK-1|TASK-1>\n' }
  setFx({ list: { counts: {}, rows: [] }, 'needs-you': { cards: [], watchers: [] }, 'sweep-state': { running: false, requested: false }, standup: draft })
  const t = table(render(createElement(OutboxPage, { initialView: 'inbox' })))
  assert.equal(t.rows.length, 1); const [tk, a, w] = t.rows[0]; assert.equal(tk.text, 'standup'); assert.ok(a.text.endsWith('confirm standup') && w.text.includes('standup note for 2026-10-16: 3 item(s) since 10-15 11:00'), a.text + ' | ' + w.text)
  setFx({ list: { counts: {}, rows: [] }, 'needs-you': { cards: [], watchers: [] }, 'sweep-state': { running: false, requested: false }, standup: { ...draft, status: 'sent' } })
  assert.equal(table(render(createElement(OutboxPage, { initialView: 'inbox' }))).rows.length, 0, 'a sent note is no row')
  const pane = render(createElement(StandupPanel, { d: draft, onDone() {} }))
  assert.ok(pane.includes('standup · 2026-10-16') && pane.includes('<strong>Standup</strong>') && pane.includes('we tested &lt;https://j/browse/TASK-1|TASK-1&gt;'), pane)
  assert.equal(buttons(pane, 'Confirm &amp; send').length + buttons(pane, 'Confirm & send').length, 1); assert.equal(buttons(pane, 'Update').length, 1)
})
test('tickets and usage: a duration column — the ticket\'s span since its first card, the sessions\' running time', () => {
  setFx(); const html = render(createElement(Tickets, {}))
  assert.ok(html.includes('duration') && html.includes('1h 30m'), 'the Tickets tab shows 5400 s as 1h 30m')
  const u = render(createElement(Usage, {}))
  assert.ok(u.includes('>time<') && u.includes('1h 02m') && u.includes('>1m<'), 'the Usage tables show the sessions\' running time (3725 s → 1h 02m, 61 s → 1m)')
  assert.ok(u.includes('provider plan windows') && u.includes('42% used') && !u.includes('Team subscription'), u)
  setFx({ usage: { ...BASE.usage, windows: [], providers: [{ provider: 'fixture-a', turns: 3, time: 90, plan_window: '5h' }, { provider: 'fixture-b', turns: 1, time: 10 }] } })
  const named = render(createElement(Usage, {}))
  assert.ok(!named.includes('provider plan windows') && named.includes('window 5h') && named.includes('fixture-a') && named.includes('fixture-b'), named)
  assert.equal(named.split('window ').length - 1, 1)
})

test('usage: the Pace panel shows one bar per window (used, the ideal marker, the target line), one sentence, the inputs and the efficiency in plain words, and a Recalculate button', () => {
  const pace = { provider: 'plan-subscription-x', target_pct: 90, read_at: '2026-11-06T10:00:00+00:00', stale: false, error: '', binding: 'Current week', verdict: 'ahead',
    windows: [{ name: 'Current session', used: 21, ideal: 30.5, verdict: 'behind', projected: 40, budget_per_hour: 23.1, active_hours_left: 3, scope: 'account', sentence: 'Current session: 21% used, behind the 30% ideal by now; 23.1% per active hour is left to spend before the reset.' },
      { name: 'Current week', used: 60, ideal: 45, verdict: 'ahead', projected: 120, budget_per_hour: 0.4, active_hours_left: 84, scope: 'account', sentence: 'Current week: 60% used, ahead of the 45% ideal by now; at this pace 120% by the reset against a 90% target.' }],
    inputs: { target_pct: 90, schedule: 'Mon,Tue,Wed,Thu,Fri 09:00-19:00', peak: true, peak_hours: 'weekdays 05:00-11:00 America/Los_Angeles, left out of the spendable hours', band: 3 },
    efficiency: { tokens: 2400000, tokens_per_run: 120000, wasted_share: 0.25, opus_share: 0.7, cache_read_share: 0.615 } }
  setFx({ pace }); const html = render(createElement(PacePanel, {}))
  assert.ok(html.includes('plan pace · plan-subscription-x') && html.includes('insight only'), html)
  assert.equal((html.match(/cockpit-pace-ideal/g) || []).length, 2, 'one ideal marker per window'); assert.equal((html.match(/cockpit-pace-target/g) || []).length, 2, 'one target line per window')
  assert.ok(html.includes('left:30.5%') && html.includes('left:90%') && html.includes('width:60%'), 'the marker at the ideal, the line at the target, the bar at the used %')
  assert.ok(html.includes('ahead of the 45% ideal by now') && html.includes('Current week binds: ahead of pace'))
  for (const s of ['target (quota ceiling)', '90%', 'Mon,Tue,Wed,Thu,Fri 09:00-19:00', 'left out of the spendable hours', '±3 points', 'tokens per card run', '120.0k', 'card runs that failed or were retried', '25%', 'Opus share of tokens', '70%', 'cache reads in input', '62%']) assert.ok(html.includes(s), s)
  assert.equal(buttons(html, 'Recalculate').length, 1)
  const u = render(createElement(Usage, {})); assert.ok(u.includes('plan pace · plan-subscription-x'), 'the Usage page carries the panel')
  setFx({ pace: { ...pace, windows: [], binding: '', error: 'no plan window read', stale: true } }); const blind = render(createElement(PacePanel, {}))
  assert.ok(blind.includes('last good reading shown; no plan window read') && !blind.includes('binds'), blind)
  setFx(); assert.ok(!render(createElement(Usage, {})).includes('plan pace'), 'no pace answer, no panel')
})

test('board: a test card\'s pill is its environment only — local or stg — and other cards keep their flow', () => {
  setFx(); const b = structuredClone(BASE.board); const c0 = b.cards.find((c) => c.id === 't_c101'); const extra = [{ ...c0, id: 't_c901', title: 'TASK-136: test on staging — plan, then your go', flow: 'test·staging', status: c0.status }, { ...c0, id: 't_c902', title: 'TASK-136: test it on slot 2 (tester)', flow: 'test·local', status: c0.status }]
  b.cards.push(...extra); for (const k of Object.keys(b.by_status || {})) if (b.by_status[k].some((c) => c.id === 't_c101')) b.by_status[k].push(...extra)
  setFx({ board: b }); const html = render(createElement(Board, {}))
  assert.ok(html.includes('class="cockpit-kb-flow" title="test on staging">stg<') && html.includes('title="test on the local slot">local<') && html.includes('title="flow: intake">intake<'), html.match(/cockpit-kb-flow[^<]*</g))
})

test('toolbar: five capacity pills in order — Dev · Test · Review · Bump · Question — the number that can start now; the Kick off form refuses at zero and says why', () => {
  setFx(); const html = render(createElement(OutboxPage, { initialView: 'inbox' }))
  const pills = [...html.matchAll(/class="cockpit-cap"[^>]*>([^<]*)<\/span>/g)].map((m) => m[1])
  assert.deepEqual(pills, ['Dev 2', 'Test 1', 'Review 0', 'Bump 0', 'Question 1'], pills)
  assert.ok(html.includes('title="reviewer on TASK-1" style="color:var(--ui-danger'), 'a lane with a card is red') && assert.ok(html.includes('title="one tester lane free; on a local slot 0" style="color:var(--ui-warning'), 'the last tester lane is amber')
  assert.ok(!render(createElement(KickoffForm, { onDone() {}, initialMode: 'intake' })).includes('No capacity'), 'Dev has room')
  assert.ok(!render(createElement(KickoffForm, { onDone() {}, initialMode: 'test' })).includes('No capacity'), 'a staging test has one lane left')
})


test('settings: the seats per flow, the budget with this month and the fullest plan window, the Chrome loan; Apply profiles when a seat has none', () => {
  setFx(); const html = render(createElement(Settings, {})); const t = html.replace(/<[^>]+>/g, ' ').replace(/&#x27;/g, "'").replace(/&amp;/g, '&').replace(/\s+/g, ' ')
  assert.ok(t.includes('Agent slots') && t.includes('Intake seats') && t.includes('Reviewer seats') && t.includes('Analyst seats') && t.includes('1–3') && t.includes('1–5'), t.slice(0, 500))
  assert.ok(t.includes('≈$42.50 of $100.00') && t.includes('Weekly (all models) 45% used, resets in 3d 4h') && t.includes('Lend it for, hours') && t.includes('not counted: Fable week — no Hermes lane runs that model (the lanes run opus, sonnet)'), t)
  assert.ok(t.includes('no profile yet for reviewer-3') && buttons(html, 'Apply profiles').length === 1 && buttons(html, 'Save').length === 1, 'save and apply')
  setFx({ settings: { ...BASE.settings, budget: { ...BASE.settings.budget, over: true, why: 'the cap is $100' }, missing_lanes: [] } })
  const over = render(createElement(Settings, {})).replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' '); assert.ok(over.includes('Over budget: no new kickoff starts — the cap is $100') && !over.includes('Apply profiles'))
  setFx(); assert.ok(render(createElement(OutboxPage, { initialView: 'inbox' })).includes('>Settings<'), 'the Settings tab')
})
test('vault: the Vault tab sits right before Settings; the page lists the vaults and the records without any value', () => {
  setFx(); const page = render(createElement(OutboxPage, { initialView: 'vault' }))
  assert.ok(page.indexOf('>Vault<') > 0 && page.indexOf('>Vault<') < page.indexOf('>Settings<'), 'Vault before Settings')
  const t = page.replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' ')
  assert.ok(t.includes('Lane logins') && t.includes('Human only') && t.includes('Staging admin') && t.includes('CI token') && t.includes('New vault') && t.includes('New record'), t.slice(0, 600))
  assert.ok(FX['vault-records'].records.every((r) => !['secret', 'otp', 'notes'].some((k) => k in r) && r.history.every((x) => !('secret' in x))), 'a list row carries no value')
  assert.equal(buttons(page, 'Rename vault').length, 0, 'a built-in vault has no rename'); assert.equal(buttons(page, 'Delete vault').length, 0, 'and no delete')
})
test('vault: a record opens closed: values behind show and copy, seats and old passwords listed, delete asks first', () => {
  setFx(); const html = render(createElement(RecordDetail, { vault: 'lane', id: 'a1b2c3d4e5f6', state: FX.vaults, vaults: FX.vaults.vaults, placed: true, onEdit() {}, onGone() {} }))
  const t = html.replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' ')
  assert.ok(t.includes('Staging admin') && t.includes('qa@example.test') && t.includes('••••••••••••') && t.includes('On seats (1)') && t.includes('tester-1'), t.slice(0, 600))
  assert.ok(t.includes('2FA code') && t.includes('notes') && t.includes('password'), 'one closed field for each stored value')
  assert.equal(buttons(html, 'show').length >= 4, true, 'show buttons'); assert.equal(buttons(html, 'Edit').length, 1); assert.equal(buttons(html, 'Delete').length, 1)
  assert.ok(!html.includes('Delete Staging admin now'), 'delete waits for its confirmation')
  const locked = render(createElement(RecordDetail, { vault: 'lane', id: 'a1b2c3d4e5f6', state: { ...FX.vaults, locked: true, reason: 'the private key is not on this machine' }, vaults: FX.vaults.vaults, placed: true, onEdit() {}, onGone() {} }))
  assert.ok(locked.includes('the private key is not on this machine') && /<button[^>]*disabled=""[^>]*>show/.test(locked), 'locked: reveal disabled with the reason')
})
test('vault: the form follows the record kind; a password is a masked input with a generator; an edit keeps what is blank', () => {
  assert.deepEqual(Object.keys(KIND_FIELDS), ['login', 'key', 'note'])
  const add = render(createElement(RecordForm, { vault: 'lane', kinds: FX.vaults.kinds, placed: true, onDone() {}, onCancel() {} }))
  assert.match(add, /type="password"/); assert.match(add, /autoComplete="new-password"|autocomplete="new-password"/); assert.ok(add.includes('Website (URL)') && add.includes('Lane that fills it') && add.includes('Add to vault'))
  assert.equal(buttons(add, 'Generate').length, 1); assert.ok(/<button[^>]*disabled=""[^>]*>Add to vault/.test(add), 'nothing to add yet')
  const human = render(createElement(RecordForm, { vault: 'human', kinds: FX.vaults.kinds, placed: false, onDone() {}, onCancel() {} }))
  assert.ok(!human.includes('Lane that fills it'), 'only the lane vault places logins on seats')
  const edit = render(createElement(RecordForm, { vault: 'lane', kinds: FX.vaults.kinds, record: FX['vault-records'].records[0], placed: true, onDone() {}, onCancel() {} }))
  assert.ok(edit.includes('blank keeps it') && edit.includes('Save changes') && edit.includes('value="qa@example.test"') && buttons(edit, 'Load current notes').length === 1, edit.slice(0, 400))
  const pw = genPassword(24); assert.equal(pw.length, 24); assert.ok(/[a-z]/.test(pw) && /[A-Z]/.test(pw) && /[0-9]/.test(pw) && /[^A-Za-z0-9]/.test(pw), pw.replace(/./g, '*'))
  assert.ok(/^[A-Za-z0-9]{20}$/.test(genPassword(20, false)), 'no symbols when asked')
  assert.notEqual(genPassword(20), genPassword(20))
})
test('vault: the key bar says what opens the vault — open, locked with Unlock, a security key with Enter PIN and its touch — and never keeps the passphrase', () => {
  const bar = (key, extra = {}) => render(createElement(KeyBar, { state: { ...FX.vaults, key: { ttl: {}, ...key }, ...extra }, refresh() {} }))
  const open = bar({ secret: 'disk', needs: '', protected: false, quiet: true })
  assert.ok(open.includes('vault key open on this machine') && buttons(open, 'Re-read vault').length === 1 && buttons(open, 'Unlock').length === 0 && buttons(open, 'Lock').length === 0)
  const locked = bar({ secret: 'disk', needs: 'passphrase', protected: true, cached: false, ttl: { idle: 600, max: 7200 } }, { locked: true, reason: 'the vault key is locked: unlock it with its passphrase' })
  assert.ok(locked.includes('vault key locked') && locked.includes('10 min after last use, 120 min at most') && buttons(locked, 'Unlock').length === 1 && buttons(locked, 'Re-read vault').length === 0)
  const cached = bar({ secret: 'disk', needs: '', protected: true, cached: true, quiet: true, ttl: { idle: 600, max: 7200 } })
  assert.ok(cached.includes('vault key unlocked') && buttons(cached, 'Lock').length === 1)
  const card = bar({ secret: 'card', needs: 'card' }, { reason: 'the vault key is on a security key' })
  assert.ok(card.includes('vault key on a security key') && buttons(card, 'Enter PIN').length === 1 && buttons(card, 'Lock').length === 1)
  assert.ok(bar({ secret: 'none', needs: 'elsewhere' }).includes('private key not on this machine'))
  setFx({ vaults: { ...BASE.vaults, legacy: true }, 'vault-records': { ...BASE['vault-records'], unread: 2 } })
  const page = render(createElement(OutboxPage, { initialView: 'vault' }))
  assert.ok(page.includes('older single-file store') && page.includes('2 files in this vault not read yet'), 'legacy and unread hints')
  setFx()
})
test('dropdowns: every select on the page is one cockpit-input, and its open list takes the theme colours (dark mode: no white list under white text)', () => {
  assert.match(CSS, /select\.cockpit-input\{color-scheme:light dark\}/)
  assert.match(CSS, /select\.cockpit-input option\{background:var\(--ui-bg-elevated,Canvas\);color:var\(--ui-text-primary,CanvasText\)\}/)
  setFx()
  const html = [render(createElement(RecordDetail, { vault: 'lane', id: 'a1b2c3d4e5f6', state: FX.vaults, vaults: FX.vaults.vaults, placed: true, onEdit() {}, onGone() {} })),
    render(createElement(OutboxPage, { initialView: 'vault' })), render(createElement(Tickets, {}))].join('')
  const selects = all(parse(html), (n) => n.tag === 'select')
  assert.ok(selects.length >= 2, 'the Move to and tag pickers render')
  assert.ok(selects.every((n) => cls(n) === 'cockpit-input' && !/bg-transparent/.test(cls(n))), selects.map(cls).join(' | '))
  assert.ok(html.includes('Move to…'))
})
test('live: a job stream keeps the newest rows of each lane, so one busy lane never pushes the others out', () => {
  const row = (who, n) => ({ who, ts: `2026-10-31T10:00:${String(n).padStart(2, '0')}Z` })
  const rows = [row('tester-1', 1), row('analyst', 2), row('tester-1', 3), row('analyst', 4), row('analyst', 5), row('analyst', 6), row('', 7), row('brain', 8)]
  assert.deepEqual(perLane(rows, 2).map((r) => `${r.who || '-'}${r.ts.slice(-3, -1)}`), ['tester-101', 'tester-103', 'analyst05', 'analyst06', '-07', 'brain08'])
  assert.equal(perLane([], 3).length, 0)
})
test('vault: delete asks inline and names what goes; the reveal route may repeat', () => {
  const html = render(createElement(Danger, { label: 'Delete', what: 'Staging admin', explain: 'x', run() {} }))
  assert.equal(buttons(html, 'Delete').length, 1)
})
test('kick off: the external browser is a test kickoff option only; a loan to another ticket shows and greys it', () => {
  setFx(); const f = render(createElement(KickoffForm, { onDone() {}, initialMode: 'test' })); assert.ok(f.includes('use the external browser (my Chrome) for this test'))
  for (const mode of ['intake', 'analyst', 'review', 'rework']) assert.ok(!render(createElement(KickoffForm, { onDone() {}, initialMode: mode })).includes('external browser'), mode)
  setFx({ 'shared-chrome': { ticket: 'TASK-9', since: 1, until: 1792200000 } }); const lent = render(createElement(KickoffForm, { onDone() {}, initialMode: 'test' }))
  assert.ok(lent.includes('lent to TASK-9 until') && lent.includes('>release<') && /type="checkbox" disabled=""/.test(lent), 'a loan to another ticket')
})

test('inbox: a failing watcher\'s pane says why and offers Run now', () => {
  const w = { name: 'perf', ok: false, fails: 1, last_ok: '2026-10-15T11:32:53+02:00', last_error: '2026-10-16T09:06:00+02:00', reason: 'tracker did not answer within 75 s', error: 'trace' }
  setFx({ list: { counts: {}, rows: [] }, 'needs-you': { cards: [], watchers: [w] }, 'sweep-state': { running: false, requested: false } })
  const t = table(render(createElement(OutboxPage, { initialView: 'inbox' }))); assert.equal(t.rows.length, 1); assert.ok(t.rows[0][2].text.includes('watcher perf: tracker did not answer within 75 s'))
  const pane = render(createElement(WatcherPanel, { w })); assert.equal(buttons(pane, 'Run now').length, 1); assert.ok(pane.includes('tried again after two minutes by itself'))
})

test('inbox: a refusal nothing fixed is a red row; its pane shows the gate\'s reason and offers Send back and Dismiss', () => {
  const r = { key: 'TASK-130|tracker-comment|t_81|', ticket: 'TASK-130', type: 'tracker-comment', card: 't_81', card_title: 'TASK-130: test on staging', card_lane: 'tester-3', card_status: 'done', lane: 'tester-3', intent: '', reason: 'a staging Test results post waits for the human: rows 1-16 are blocked', time: '2026-10-16T12:14:17+02:00' }
  setFx({ list: { counts: {}, rows: [] }, 'needs-you': { cards: [], watchers: [] }, 'sweep-state': { running: false, requested: false }, refusals: { refusals: [r] } })
  const t = table(render(createElement(OutboxPage, { initialView: 'inbox' }))); assert.equal(t.rows.length, 1)
  const [tk, a, w] = t.rows[0]; assert.ok(tk.text === 'TASK-130' && a.text.endsWith('refused') && w.text.startsWith('tracker-comment refused for TASK-130 and nothing fixed it: a staging Test results post'), a.text + ' | ' + w.text)
  const pane = render(createElement(RefusalPanel, { r, onDone() {} }))
  assert.ok(pane.includes('rows 1-16 are blocked') && pane.includes('ended done without fixing it') && pane.includes('Nothing reached the forge or tracker'))
  assert.equal(buttons(pane, 'Send back to the lane').length, 1); assert.equal(buttons(pane, 'Dismiss').length, 1)
})
test('inbox: a PR group gives each item its own step — Publish review… for a posted review, Decide… for a held one — and still says nothing is ready', () => {
  const posted = intent({ ticket: 'TASK-169', type: 'pr-review-submit', status: 'posted', order: 1, payload: { repo: 'api', number: 55 } })
  const held = intent({ ticket: 'TASK-169', type: 'pr-review-submit', status: 'held', order: 1, hold: { ask: 'Drop 002?' }, payload: { repo: 'api', number: 55 } })
  const members = [held, posted].map((x, i) => ({ key: 'g' + i, action: x.status === 'held' ? 'resolve hold' : 'publish review', color: GOOD, what: `${x.type} · t — ${x.status}`, row: x }))
  const html = render(createElement(PrGroupPanel, { g: { pr: 'api#55', members }, ticket: 'TASK-169', goOutbox() {}, onDone() {} }))
  assert.equal(all(parse(html), (n) => n.tag === 'button' && n.attrs['data-step'] === 'publish-review').length, 1)
  assert.equal(all(parse(html), (n) => n.tag === 'button' && n.attrs['data-step'] === 'decide').length, 1)
  assert.match(html, /✓ Publish review…/); assert.match(html, /Decide…/); assert.match(html, /Nothing on this PR is ready to publish yet/)
  assert.equal((html.match(/Open the intent/g) || []).length, 2)
})
test('decide: the gatekeeper\'s ask, reason and rework render as markdown when the backend sends hold_html; the text stands otherwise', () => {
  const r = intent({ ticket: 'TASK-208', type: 'open-pr', status: 'held', hold: { ask: 'Keep `row 3`?', reason: 'two **gaps**', rework: '1. fix', options: [] },
    hold_html: { ask: '<p>Keep <code>row 3</code>?</p>', reason: '<p>two <strong>gaps</strong></p>', rework: '<ol><li>fix</li></ol>' } })
  const html = render(createElement(DecidePanel, { r }))
  assert.match(html, /<code>row 3<\/code>/); assert.match(html, /<strong>gaps<\/strong>/)   // the rework sits in a collapsed section
  const plain = render(createElement(DecidePanel, { r: { ...r, hold_html: undefined } }))
  assert.ok(plain.includes('Keep `row 3`?') && !plain.includes('<code>row 3</code>'))
})
test('inbox: a finished question card is a row (use answer) with the lane\'s summary; its pane has the one-click Reopen with this, Rework only with repos, Kick off, Dismiss, the references and the follow-up preset', () => {
  const answer = { card: 't_00000001', ticket: 'TASK-139', title: 'TASK-139: analysis', lane: 'analyst-2', mode: 'analyst', kind: 'analyst', completed: ago(30), follows: '',
    summary: 'The total is stale because `page.css` ignores the background. See qa/TASK-139/analyst-findings.md', summary_html: '<p>The total is stale because <code>page.css</code> ignores the background.</p>',
    references: [{ name: 'analyst-findings.md', rel: 'hermes/qa/TASK-139/analyst-findings.md', path: '/ws/hermes/qa/TASK-139/analyst-findings.md', size: 1200, mtime: 1 }, { name: 'before-A4.png', rel: 'hermes/qa/TASK-139/evidences/before-A4.png', path: '/ws/hermes/qa/TASK-139/evidences/before-A4.png', size: 90000, mtime: 2 }],
    report_html: '<h2>Findings</h2><p>the report body</p>', report_name: 'analyst-findings.md', followup_text: 'Follow-up to card t_00000001 on TASK-139. Read hermes/qa/TASK-139/analyst-findings.md. Do not redo the investigation.',
    reopen_prompt: 'The divider is white…\n\nReferences:\n- hermes/qa/TASK-139/analyst-findings.md', rework_repos: [], used_by: [], dismissed: '' }
  // the row: after the blocked cards, before the intents; action "use answer"
  setFx({ list: { counts: {}, rows: [] }, 'needs-you': { cards: [], watchers: [], answers: [answer] }, 'sweep-state': { running: false, requested: false } })
  const t = table(render(createElement(OutboxPage, { initialView: 'inbox' }))); assert.equal(t.rows.length, 1)
  const [tk, a, w] = t.rows[0]; assert.deepEqual([tk.text, a.text.replace(/^\S*\s/, ''), a.color], ['TASK-139', 'use answer', ACCENT])
  assert.match(w.text, /^analyst-2 answered: The total is stale because/)
  // the pane
  const pane = render(createElement(AnswerPanel, { a: answer, onDone() {} }))
  assert.match(pane, /TASK-139 · analyst-2 answered/); assert.match(pane, /<code>page.css<\/code>/)
  assert.equal(buttons(pane, 'Reopen with this').length, 1); assert.equal(buttons(pane, 'Dismiss').length, 1); assert.equal(buttons(pane, 'Kick off with this').length, 1)
  assert.equal(buttons(pane, 'Ask for a patch plan').length, 1); assert.equal(buttons(pane, 'Rework with this').length, 0, 'no delivered repo: no rework')
  assert.match(pane, /edit first/); assert.match(pane, /References \(2\)/); assert.match(pane, /analyst-findings\.md/); assert.match(pane, /before-A4\.png/)
  assert.deepEqual(sections(pane).map((x) => x.title), ['Report · analyst-findings.md']); assert.equal(sections(pane)[0].open, false, 'the report is folded; the summary is open')
  assert.match(pane, /Follow-up to card t_00000001 on TASK-139/)   // the follow-up box carries the preset
  assert.equal(all(parse(pane), (n) => n.tag === 'input' && n.attrs.value === 'TASK-139').length, 1, 'the kick-off ticket box is prefilled with the answer\'s ticket')
  // delivered repos: the rework button appears; a follow-up row names the card it follows
  const more = render(createElement(AnswerPanel, { a: { ...answer, rework_repos: ['api'], follows: 't_00000002' }, onDone() {} }))
  assert.equal(buttons(more, 'Rework with this').length, 1); assert.match(more, /follow-up to card t_00000002/)
  // a reference a later card rewrote is the ticket's, marked shared
  const shared = render(createElement(AnswerPanel, { a: { ...answer, references: [{ ...answer.references[0], shared: true }] }, onDone() {} }))
  assert.equal(all(parse(shared), (n) => n.attrs['data-shared'] === '1').length, 1); assert.match(shared, /a later card rewrote it/)
  assert.equal(all(parse(pane), (n) => n.attrs['data-shared'] === '1').length, 0)
  // a card that ended without a summary and wrote no file still shows, with its files line saying so
  const bare = render(createElement(AnswerPanel, { a: { ...answer, summary: '', summary_html: '', references: [], report_html: '' }, onDone() {} }))
  assert.match(bare, /ended without a summary/); assert.match(bare, /no file under qa\/ was written/)
  // the "edit first" form is the Reopen form prefilled: ReopenForm takes `initial`
  const form = render(createElement(mod.ReopenForm, { ticket: 'TASK-139', initial: { prompt: answer.reopen_prompt, files: [{ name: 'analyst-findings.md', path: 'hermes/qa/TASK-139/analyst-findings.md' }], from_answer: 't_00000001' }, onDone() {} }))
  assert.match(form, /References:/); assert.match(form, /analyst-findings\.md/); assert.equal(buttons(form, /Reopen → intake proposes/).length, 1)
  // an older backend without the key renders the Inbox as before
  setFx({ list: { counts: {}, rows: [] }, 'needs-you': { cards: [], watchers: [] }, 'sweep-state': { running: false, requested: false } })
  assert.equal(table(render(createElement(OutboxPage, { initialView: 'inbox' }))).rows.length, 0)
})
test('inbox: on a pack whose tracker is Jira, a comment added or edited while the done row waits is a read row; its pane renders the comment, opens Jira and has only Dismiss', () => {
  const note = { id: 'TASK-139-9001-new-1', ticket: 'TASK-139', comment: '9001', kind: 'new', author: 'Ann Reader', at: ago(12), text: 'Still wrong on **page 2** after the release.', text_html: '<p>Still wrong on <strong>page 2</strong> after the release.</p>', url: 'https://acme.atlassian.net/browse/TASK-139?focusedCommentId=9001' }
  setFx({ list: { counts: {}, rows: [] }, 'needs-you': { cards: [], watchers: [], tracker_notes: [note] }, 'sweep-state': { running: false, requested: false }, repos: { tracker_kind: 'connector' } })
  const t = table(render(createElement(OutboxPage, { initialView: 'inbox' }))); assert.equal(t.rows.length, 1)
  const [tk, a, w] = t.rows[0]; assert.deepEqual([tk.text, a.text.replace(/^\S*\s/, ''), a.color], ['TASK-139', 'read', ACCENT])
  assert.match(w.text, /^Jira comment added by Ann Reader while the done row waits: Still wrong/)
  const pane = render(createElement(TrackerNotePanel, { n: note, onDone() {} }))
  assert.match(pane, /TASK-139 · Jira comment added/); assert.match(pane, /<strong>page 2<\/strong>/); assert.match(pane, /Nothing runs on it/)
  assert.equal(buttons(pane, 'Dismiss').length, 1); assert.equal(buttons(pane, 'Open in Jira').length, 1)
  // no other action: a one-time note (Open in Jira's link can also be copied, for a desktop that cannot open a browser)
  assert.equal(all(parse(pane), (n) => n.tag === 'button').length, 3, 'no other action: a one-time note')
  assert.match(pane, /title="copy Jira link"/)
  const edited = render(createElement(TrackerNotePanel, { n: { ...note, kind: 'edited', text_html: '' }, onDone() {} }))
  assert.match(edited, /Jira comment edited/); assert.match(edited, /An existing comment was edited/); assert.match(edited, /Still wrong on \*\*page 2\*\*/)
  assert.equal(buttons(render(createElement(TrackerNotePanel, { n: { ...note, url: '' }, onDone() {} })), 'Open in Jira').length, 0)
})
test('inbox: a tracker note names the tracker only when the pack\'s tracker is Jira; any other kind, or none sent, reads "Tracker"', () => {
  const { trackerWord } = mod.words
  for (const kind of ['jira', 'connector']) assert.equal(trackerWord(kind), 'Jira')
  for (const kind of ['command', 'local', 'issues', 'rest', '', undefined, null]) assert.equal(trackerWord(kind), 'Tracker')
  const note = { id: 'TASK-139-7-new-1', ticket: 'TASK-139', comment: '7', kind: 'new', author: 'Ann Reader', at: ago(12), text: 'Still wrong.', url: 'https://tracker.example.test/TASK-139#7' }
  for (const repos of [{ tracker_kind: 'command' }, {}]) {
    setFx({ list: { counts: {}, rows: [] }, 'needs-you': { cards: [], watchers: [], tracker_notes: [note] }, 'sweep-state': { running: false, requested: false }, repos })
    const row = table(render(createElement(OutboxPage, { initialView: 'inbox' }))).rows[0]
    assert.match(row[2].text, /^Tracker comment added by Ann Reader while the done row waits: Still wrong/)
    const pane = render(createElement(TrackerNotePanel, { n: note, onDone() {} }))
    assert.match(pane, /TASK-139 · Tracker comment added/); assert.doesNotMatch(pane, /Jira/)
    assert.equal(buttons(pane, 'Open in tracker').length, 1); assert.match(pane, /title="copy tracker link"/)
  }
})
test('inbox: a refusal\'s reason renders as markdown when the backend sends reason_html', () => {
  const r = { key: 'TASK-131|tracker-comment|t_82|', ticket: 'TASK-131', type: 'tracker-comment', card: 't_82', card_title: 'TASK-131: test', card_lane: 'tester-3', card_status: 'done', lane: 'tester-3', intent: '', reason: 'no `Summary` table', reason_html: '<p>no <code>Summary</code> table</p>', time: '2026-10-28T12:14:17+02:00' }
  const pane = render(createElement(RefusalPanel, { r, onDone() {} }))
  assert.match(pane, /no <code>Summary<\/code> table/); assert.equal(buttons(pane, 'Send back to the lane').length, 1)
})
test('markdown: a file the backend did not render goes into the page as text, never as markup', () => {
  assert.equal(escapeHtml('<script>x</script> & "q"'), '&lt;script&gt;x&lt;/script&gt; &amp; &quot;q&quot;')
})
test('inbox: a card blocked on a privileged-login request is one row, the 🔑 one; its pane leads back to the card; without the request row the card row stands', () => {
  // the tester blocked with PRIVILEGED LOGIN NEEDED and the Inbox showed two rows for one decision,
  // "tester-1 asks: PRIVILEGED LOGIN NEEDED …" (answer) and the 🔑 row (approve or deny). One decision, one row.
  const ask = 'PRIVILEGED LOGIN NEEDED · staging · refund the order as its owner · the test account is not in that organization'
  const asked = card({ id: 't_00000003', ticket: 'TASK-124', assignee: 'tester-1', title: 'TASK-124: test', question: ask, block_reason: ask })
  const other = card({ id: 't_other', ticket: 'TASK-125', assignee: 'intake', question: 'Follow the page background?' })
  const p = { name: 'privileged', ok: false, reason: ask, summary: 'refund the order as its owner', card: 't_00000003', options: ['Approve this step', 'Deny'] }
  const res = inbox([], { cards: [asked, other], privileged: [p] })
  assert.equal(res.rows.length, 2, JSON.stringify(res.rows))
  const key = res.rows.find((r) => r.action === 'approve or deny'); assert.ok(key, JSON.stringify(res.rows))
  assert.deepEqual([key.ticket, key.color], ['TASK-124', WARN])
  assert.match(key.what, /^tester-1 asks: PRIVILEGED LOGIN NEEDED · staging · refund the order as its owner/)
  assert.ok(!res.rows.some((r) => r.action === 'answer' && /TASK-124/.test(r.ticket)), 'the card row is folded into the 🔑 row: ' + JSON.stringify(res.rows))
  assert.deepEqual([res.rows.find((r) => r.ticket === 'TASK-125').action], ['answer'])
  // denied, or a backend without the privileged rows: the card's own row is back, as before
  assert.deepEqual([only(inbox([], { cards: [asked] })).action], ['answer'])
  // the pane: approve, deny, and the card's own pane for anything else; without a known card only the two decisions
  const pane = render(createElement(PrivilegedPanel, { row: p, card: asked, openCard() {}, onDone() {} }))
  assert.equal(buttons(pane, 'Approve this step').length, 1); assert.equal(buttons(pane, 'Deny').length, 1); assert.equal(buttons(pane, 'Answer the card instead').length, 1)
  assert.match(pane, /TASK-124 · tester-1/); assert.match(pane, /The card t_00000003 is blocked on this request/)
  const bare = render(createElement(PrivilegedPanel, { row: p, onDone() {} }))
  assert.equal(buttons(bare, 'Answer the card instead').length, 0); assert.equal(buttons(bare, 'Approve this step').length, 1)
})
test('inbox: a triage card (asked twice) is answered like a blocked one, and a plugin\'s row names that plugin', () => {
  const c = { id: 't_9', title: 'TASK-77: analyst', status: 'triage', assignee: 'analyst-1', ticket: 'TASK-77', block_reason: 'which window should the plan use?', question: 'which window should the plan use?', created_at: 1792200000, blocked_at: 1 }
  const p = { id: 'r1', plugin: 'ledger-view', icon: '📒', what: 'ledger closed for the week', action_label: 'open ledger', href: '/ledger', tone: 'warn', at: 1792200000 }
  setFx({ list: { counts: {}, rows: [] }, 'needs-you': { cards: [c], watchers: [], plugins: [p] }, 'sweep-state': { running: false, requested: false } })
  const t = table(render(createElement(OutboxPage, { initialView: 'inbox' }))); assert.equal(t.rows.length, 2)
  const texts = t.rows.map((r) => r.map((x) => x.text).join(' | '))
  assert.ok(texts.some((x) => x.includes('analyst-1 (asked twice) asks: which window should the plan use?')), texts.join('\n'))
  assert.ok(texts.some((x) => x.includes('ledger-view') && x.includes('ledger closed for the week') && x.includes('open ledger')), texts.join('\n'))
})

test('inbox: what the analyst asks is rendered, not shown as its own source', () => {
  // An analyst asks in markdown — options as a list, a table, a fenced diff — and this was the one
  // place showing the source of it. A card from before the backend rendered it still reads.
  const card = { id: 'c1', ticket: 'ACME-1', assignee: 'analyst', status: 'blocked',
    question: '- option **one**\n- option two', question_html: '<ul><li>option <strong>one</strong></li><li>option two</li></ul>' }
  setFx({ list: { counts: {}, rows: [] }, 'needs-you': { cards: [], watchers: [], plugins: [] },
    'sweep-state': { running: false, requested: false }, 'card-detail?id=c1': { body_html: '', result_html: '' } })
  const html = render(createElement(BlockedCard, { c: card, refresh() {} }))
  assert.ok(html.includes('<strong>one</strong>'), `the ask is rendered: ${html.slice(0, 220)}`)
  assert.equal(html.includes('- option **one**'), false, 'and not shown as source')

  const old = render(createElement(BlockedCard, { c: { ...card, question_html: undefined }, refresh() {} }))
  assert.ok(old.includes('- option **one**'), 'a card with no rendered ask still shows the text')
})
test('inbox: a plugin row with a detail opens a pane; one without it still only navigates', () => {
  // the row every plugin has written until now: no detail, so the old path must be untouched
  const plain = { id: 'r1', plugin: 'ledger-view', icon: '📒', what: 'ledger closed for the week', action_label: 'open ledger', href: '/ledger', tone: 'warn', at: 1792200000 }
  setFx({ list: { counts: {}, rows: [] }, 'needs-you': { cards: [], watchers: [], plugins: [plain] }, 'sweep-state': { running: false, requested: false } })
  assert.equal(render(createElement(OutboxPage, { initialView: 'inbox' })).includes('data-plugin-detail'), false,
    'a row with no detail opens no pane')

  const rich = { ...plain, id: 'r2', action_label: '', detail: {
    title: 'check is stuck on U1', status: { text: 'needs you', color: 'var(--ui-danger, #d33)' },
    brief: 'check on U1 stopped after 3 attempt(s).',
    fields: [{ label: 'the card said', text: 'totals wrong' }, { label: 'controls', items: ['fix — a fresh card'] }],
    actions: [{ label: 'Open the release', href: '/supervisor#V1-4-0', hint: 'where a control names its release' }],
    footer: 'Nothing runs from here.' } }
  setFx({ list: { counts: {}, rows: [] }, 'needs-you': { cards: [], watchers: [], plugins: [rich] }, 'sweep-state': { running: false, requested: false } })
  const html = render(createElement(OutboxPage, { initialView: 'inbox' }))
  // the row offers to be read rather than followed away
  assert.ok(html.includes('read'), 'the action reads, it does not navigate away')
  // the pane opens on a click, so it is rendered on its own: cockpit builds it from the detail alone,
  // knowing nothing about the plugin that wrote it
  const pane = render(createElement(PluginPanel, { row: { ...rich, color: 'var(--ui-warning, #c98a00)' } }))
  for (const want of ['check is stuck on U1', 'needs you', 'stopped after 3 attempt(s)', 'totals wrong',
                      'fix — a fresh card', 'Open the release', 'Nothing runs from here.', 'ledger-view'])
    assert.ok(pane.includes(want), `${want} is in the pane: ${pane.slice(0, 200)}`)
})

test('inbox: a pane button acts, and a row that names its ticket gets Chat and Open IDE', () => {
  // an `act` is a button that answers the plugin; an `href` still only navigates. Both are buttons,
  // so the human decides from the card instead of reading a list of what could be done.
  const row = { id: 'r3', plugin: 'supervisor', icon: '⛔', what: 'check is stuck on U1', tone: 'danger',
    at: 1792200000, ticket: 'ACME-1', pticket: 'ACME-1', color: 'var(--ui-danger, #d33)',
    detail: { title: 'check is stuck on U1', brief: 'it stopped',
      fields: [{ label: 'root cause', text: 'the grant is missing on that route' }],
      actions: [{ label: 'Ask for a fix', act: { release: 'V1-0-0', action: 'fix' }, hint: 'carries the prompt' },
                { label: 'Requeue', act: { release: 'V1-0-0', action: 'requeue' } },
                { label: 'Open the release', href: '/supervisor#V1-0-0' }] } }
  setFx({ list: { counts: {}, rows: [] }, 'needs-you': { cards: [], watchers: [], plugins: [row] },
    'sweep-state': { running: false, requested: false }, 'chat-state': { exists: false, best: {} } })
  const pane = render(createElement(PluginPanel, { row }))
  for (const want of ['root cause', 'the grant is missing on that route', 'Ask for a fix', 'Requeue',
                      'Open the release', 'Chat', 'Open IDE', 'ACME-1'])
    assert.ok(pane.includes(want), `${want} is in the pane: ${pane.slice(0, 300)}`)
  assert.ok(pane.includes('data-act="0"') && pane.includes('data-act="1"'), 'the two acts are marked')
  // what came of the last press is readable here; a refusal that is only in a log looks like nothing
  assert.equal(pane.includes('data-said'), false, 'nothing pressed yet, nothing to say')
  const answered = render(createElement(PluginPanel, { row: { ...row, detail: { ...row.detail, said: 'refused: no control explode' } } }))
  assert.ok(answered.includes('data-said') && answered.includes('refused: no control explode'), answered.slice(0, 200))
  assert.equal((pane.match(/data-act="2"/g) || []).length, 0, 'a link is not an act')

  // a row with no ticket keeps the pane, without cockpit's ticket doors
  const bare = render(createElement(PluginPanel, { row: { ...row, ticket: '', pticket: '' } }))
  assert.ok(bare.includes('Ask for a fix') && !bare.includes('Open IDE'), 'no ticket, no ticket tools')
})

test('inbox: a button pressed on one message is not pressed on the next one opened', () => {
  // React reuses this component when the selection moves to another plugin row, so what was pressed
  // has to be remembered per row — otherwise the reader sees a control queued on a message they
  // never touched, which is exactly the one thing a button like this must never get wrong.
  const rows = ['r1', 'r2'].map((id) => ({ id, plugin: 'supervisor', what: 'stuck', tone: 'danger', at: 1,
    detail: { title: `message ${id}`, actions: [{ label: 'Requeue', act: { release: 'V1-0-0', action: 'requeue' } }] } }))
  setFx({ list: { counts: {}, rows: [] }, 'needs-you': { cards: [], watchers: [], plugins: rows },
    'sweep-state': { running: false, requested: false } })

  // r1's button has been pressed. The same state reaching r2 must leave r2's button alone: it is
  // the one record both rows would share if it were not kept per row id.
  const was = { r1: [0] }
  const first = render(createElement(PluginPanel, { row: rows[0], initialDone: was }))
  const second = render(createElement(PluginPanel, { row: rows[1], initialDone: was }))
  assert.ok(first.includes('Requeue · queued'), 'the row that was pressed says so')
  assert.ok(!second.includes('· queued') && second.includes('Requeue'), 'the other row still offers its button')
})

test('a press the server holds stays pressed however the pane is drawn again: no second press, no double run', () => {
  // The pane remembered a press only in its own state, so closing and reopening it (or the Inbox redrawing it)
  // offered the button again and the plugin ran the request twice. The row now says what is queued: cockpit's
  // waiting request file (queued) and the plugin's own record of a press it took (detail.pressed).
  const row = { id: 'r1', plugin: 'supervisor', what: 'stuck', tone: 'danger', at: 1,
    detail: { title: 'message', actions: [{ label: 'Requeue', act: { release: 'V1-0-0', action: 'requeue' } },
                                          { label: 'Waive', act: { release: 'V1-0-0', action: 'waive' } },
                                          { label: 'Open', href: '/supervisor' }] } }
  setFx({ list: { counts: {}, rows: [] }, 'needs-you': { cards: [], watchers: [], plugins: [row] }, 'sweep-state': { running: false, requested: false } })
  const fresh = render(createElement(PluginPanel, { row: { ...row, queued: [0] } }))
  assert.ok(fresh.includes('Requeue · queued') && !fresh.includes('Waive · queued'), 'waiting on the server: queued in a pane that never pressed it')
  const taken = render(createElement(PluginPanel, { row: { ...row, queued: [], detail: { ...row.detail, pressed: [1] } } }))
  assert.ok(taken.includes('Waive · queued') && !taken.includes('Requeue · queued'), 'taken by the plugin: still not offered again')
  const clean = render(createElement(PluginPanel, { row }))
  assert.ok(!clean.includes('· queued'), 'nothing pressed: every button offered')
})

test('a plugin page can send the reader to one of its rows: the hash opens the Inbox on it', () => {
  // The Inbox is a view of this page, not a route, so a link that only navigated landed on whatever
  // view was last open and selected nothing — which is what the supervisor's stuck cell did.
  const row = { id: 'stuck-step_U1_check', plugin: 'supervisor', icon: '⛔', what: 'check is stuck on U1',
    tone: 'danger', at: 1792200000, detail: { title: 'check is stuck on U1', brief: 'it stopped', fields: [] } }
  setFx({ list: { counts: {}, rows: [] }, 'needs-you': { cards: [], watchers: [], plugins: [row] },
    'sweep-state': { running: false, requested: false }, 'plugin-pages': { pages: [] } })
  const was = globalThis.window
  try {
    globalThis.window = { location: { hash: '#plugin=supervisor/stuck-step_U1_check' }, addEventListener() {}, removeEventListener() {} }
    // the page was left on the Board; the hash puts it on the Inbox so the row can be selected
    const html = render(createElement(OutboxPage, { initialView: 'board' }))
    assert.ok(html.includes('check is stuck on U1'), `the Inbox opened: ${html.slice(0, 200)}`)

    globalThis.window = { location: { hash: '' }, addEventListener() {}, removeEventListener() {} }
    const board = render(createElement(OutboxPage, { initialView: 'board' }))
    assert.equal(board.includes('check is stuck on U1'), false, 'with no hash the page stays where it was')
  } finally { globalThis.window = was }
})
test('toolbar: a page beside cockpit is a link at the right of the tabs; alone, cockpit says nothing', () => {
  // The link is pack data (plugins.<name>.page), so cockpit learns nothing about the plugin and an
  // install with none renders no link, no row and no gap — it cannot tell the feature exists.
  const base = { list: { counts: {}, rows: [] }, 'needs-you': { cards: [], watchers: [], plugins: [] },
    'sweep-state': { running: false, requested: false } }
  setFx({ ...base, 'plugin-pages': { pages: [] } })
  const alone = render(createElement(OutboxPage, { initialView: 'board' }))
  assert.equal(alone.includes('data-plugin-page'), false, 'no plugin, no link')
  // and the Board stopped explaining itself at the top of the page
  assert.equal(alone.includes('the kanban as the Cockpit reads it'), false, 'the board hint is gone')

  setFx({ ...base, 'plugin-pages': { pages: [{ plugin: 'supervisor', label: 'Supervisor', path: '/supervisor' }] } })
  const t = parse(render(createElement(OutboxPage, { initialView: 'board' })))
  const link = all(t, (n) => n.attrs['data-plugin-page'])[0]
  assert.ok(link, 'the page beside cockpit is offered')
  assert.equal(link.attrs['data-plugin-page'], 'supervisor')
  assert.ok(text(link).includes('Supervisor'), text(link))
})
test('kick off: a mode a plugin registered is a tab with its own text; cockpit\'s modes keep theirs', () => {
  setFx({ 'kickoff-modes': { modes: [{ mode: 'intake', label: 'intake', text: '', lane_kind: 'intake', owner: '' }, { mode: 'ledger-close', label: 'Close → analyst', text: 'Closes the week in the ledger.', lane_kind: 'analyst', owner: 'ledger-view' }] } })
  const f = render(createElement(KickoffForm, { onDone() {}, initialMode: 'ledger-close' }))
  assert.ok(f.includes('Close → analyst') && f.includes('Closes the week in the ledger.') && f.includes('Ticket → intake'), 'plugin tab and text')
  assert.equal((f.match(/>intake</g) || []).length, 0, 'cockpit\'s own mode is not listed twice')
})

test('outbox: a pending intent nothing has touched for days says it is stale and has no Board card; a fresh one does not', () => {
  const old = detail(full({ status: 'pending', endorsed: null, stale_days: 9 }))
  assert.ok(old.includes('Stale') && old.includes('pending for 9 days') && old.includes('no card on the Board'), 'the stale line')
  const fresh = detail(full({ status: 'pending', endorsed: null, stale_days: 0 }))
  assert.ok(!fresh.includes('no card on the Board'), 'a fresh pending intent has no such line')
})

test('outbox: the rows the page renders carry exactly the fields /list supplies (tests/contract/outbox-list-fields.json)', () => {
  const contract = JSON.parse(readFileSync(path.join(here, '..', '..', 'tests', 'contract', 'outbox-list-fields.json'), 'utf8'))
  const known = new Set(contract.row_fields)
  for (const row of BASE.list.rows) {
    const extra = Object.keys(row).filter((key) => !known.has(key))
    const absent = contract.row_fields.filter((key) => !contract.optional.includes(key) && !(key in row))
    assert.deepEqual([extra, absent], [[], []], `fixture row ${row.id}: not supplied by /list ${extra}; missing ${absent}`)
  }
})

test('outbox: a hold that waits on you and asks nothing offers Confirm beside Send back and Drop; Publish waits for it', () => {
  const held = detail(full({ status: 'held', hold: { waits: 'human', reason: 'the pushed range has commits by me@work: confirm they belong in this push', ask: '' } }))
  assert.equal(buttons(held, 'Confirm').length, 1, held)
  assert.equal(buttons(held, 'Drop').length, 1)
  assert.ok(buttons(held, 'Send back').length >= 1)
  const asks = detail(full({ status: 'held', hold: { waits: 'human', reason: 'which way?', ask: 'Keep the old name?', options: ['yes', 'no'] } }))
  assert.equal(buttons(asks, 'Confirm').length, 0, 'a hold with a question is answered in its form')
  const lane = detail(full({ status: 'held', hold: { waits: 'lane', reason: 'cards still deliver' } }))
  assert.equal(buttons(lane, 'Confirm').length, 0, 'a hold that waits on the lane is not yours to confirm')
})

test('outbox: an infrastructure note with a patch offers Apply patch and no Publish; a note without one offers neither', () => {
  const patched = detail(full({ type: 'infra-note', status: 'pending', payload: { repo: 'web', branch: 'bump/x', patch_file: 'records/qa/TASK-500/node.patch' } }))
  assert.equal(buttons(patched, 'Apply patch').length, 1, patched)
  assert.equal(buttons(patched, /Publish/).length, 0)
  const plain = detail(full({ type: 'infra-note', status: 'pending', payload: { repo: 'web' } }))
  assert.equal(buttons(plain, 'Apply patch').length, 0)
  assert.equal(buttons(plain, /Publish/).length, 0)
})
test('inbox: a note with a patch is a row to apply, pending or endorsed; a note without one is no row', () => {
  const payload = { repo: 'web', branch: 'bump/x', patch_file: 'records/qa/TASK-501/node.patch' }
  assert.equal(only(inbox([intent({ ticket: 'TASK-501', type: 'infra-note', status: 'pending', payload })])).action, 'apply patch')
  assert.equal(only(inbox([intent({ ticket: 'TASK-501', type: 'infra-note', status: 'endorsed', endorsed: endorsed(), payload })])).action, 'apply patch')
  for (const status of ['published-manually', 'dropped', 'published']) none(inbox([intent({ ticket: 'TASK-501', type: 'infra-note', status, payload })]))   // applied or dropped: it has left
  none(inbox([intent({ ticket: 'TASK-501', type: 'infra-note', status: 'endorsed', endorsed: endorsed(), payload: { repo: 'web' } })]))
})
test('board: a live ticket\'s done group stays in view whatever its age, and says what it waits for', () => {
  const old = new Date(Date.now() - 9 * 86400e3).toISOString()
  const cards = [{ id: 'a', ticket: 'TASK-201', completed: old }, { id: 'b', ticket: 'TASK-204', completed: old }]
  const { recent, hidden } = splitDone(cards, {}, Date.now(), RECENT_HOURS, { 'TASK-201': ['merge', 'confirm'] })
  assert.deepEqual([recent.map((c) => c.id), hidden.map((c) => c.id)], [['a'], ['b']], 'live stays, finished goes behind "show N done"')
  setFx({ board: { cards: cards.map((c) => ({ ...c, title: `${c.ticket}: x`, status: 'done', lane: 'worker-1' })), lanes: ['worker-1'], ticket_activity: {}, ticket_titles: {}, live: { 'TASK-201': ['merge', 'confirm'] } } })
  const html = render(createElement(OutboxPage, { initialView: 'board' }))
  assert.match(html, /awaiting merge · awaiting your confirm/)
  assert.match(html, /show 1 done/)
})

test('inbox: a plugin PR ready to merge is one row naming every ticket it carries, and its pane opens the PR', () => {
  setFx({ list: { counts: {}, rows: [] }, 'needs-you': { cards: [], watchers: [], merge_ready: [{ repo: 'orders.shop.example.test', number: 19, url: 'https://x/pull/19', title: 'Reduce reloads', plugin: 'supervisor', tickets: ['ACME-745', 'ACME-930'] }] }, 'sweep-state': { running: false, requested: false } })
  const html = render(createElement(OutboxPage, { initialView: 'inbox' }))
  assert.match(html, /orders #19 is ready to merge \(ACME-745, ACME-930\)/)
  assert.match(html, /the final ack follows the merge/)
})

test('inbox: the merge pane copies the PR link beside Open the PR, for a desktop that cannot open a browser', () => {
  const html = render(createElement(MergePanel, { m: { repo: 'orders.shop.example.test', number: 19, url: 'https://x/pull/19', title: 'Reduce reloads', plugin: 'supervisor', tickets: ['ACME-745'] } }))
  assert.match(html, /Open the PR/)
  assert.match(html, /title="copy PR link"/)
})

// ---------- desktop overrides ----------
const { OVERRIDES, applyOverrides, startOverrides } = await import(pathToFileURL(path.join(here, '..', 'src', 'lib', 'overrides.js')).href)
const fakeStore = (initial = {}, refuse = false) => { const data = { ...initial }
  return { data, getItem: (k) => (k in data ? data[k] : null), setItem: (k, v) => { if (refuse) throw new Error('blocked'); data[k] = String(v) } } }
const fakeWindow = (local = fakeStore(), session = fakeStore()) => { const w = { localStorage: local, sessionStorage: session, reloads: 0 }; w.location = { reload: () => { w.reloads++ } }; return w }
const opaque = JSON.stringify(OVERRIDES['opaque-window'].value)
const fresh = fakeWindow(); const freshReloaded = await startOverrides(async () => ({ overrides: ['opaque-window'] }), fresh, 1, 0)
const again = fakeWindow(fakeStore({ [OVERRIDES['opaque-window'].key]: opaque })); const againReloaded = await startOverrides(async () => ({ overrides: ['opaque-window'] }), again, 1, 0)
const once = fakeWindow(fakeStore(), fakeStore({ 'cockpit.desktop-overrides.reloaded': '1' })); await startOverrides(async () => ({ overrides: ['opaque-window'] }), once, 1, 0)
const unnamed = fakeWindow(); const noneReloaded = await startOverrides(async () => ({ overrides: [] }), unnamed, 1, 0)
let asked = 0; const late = fakeWindow(); await startOverrides(async () => { asked++; if (asked < 3) throw new Error('gateway not up'); return { overrides: ['opaque-window'] } }, late, 5, 0)
test('desktop overrides: a named override is written and the window reloads once; already there, none named or reloaded this session — no reload', () => {
  assert.equal(fresh.localStorage.data['hermes.desktop.translucency.v2'], opaque)
  assert.deepEqual(JSON.parse(opaque).base, { intensity: 0 }, 'opaque-window turns the see-through window off')
  assert.deepEqual([freshReloaded, fresh.reloads], [true, 1])
  assert.deepEqual([againReloaded, again.reloads], [false, 0], 'already written: no reload, so no loop')
  assert.equal(once.reloads, 0, 'at most one reload per window session')
  assert.deepEqual([noneReloaded, unnamed.reloads, Object.keys(unnamed.localStorage.data)], [false, 0, []], 'a pack that names none changes nothing')
  assert.deepEqual([asked, late.reloads], [3, 1], 'the gateway not up yet: it asks again')
  assert.equal(applyOverrides(['no-such-override'], fakeStore()), false, 'an unknown name writes nothing')
  assert.equal(applyOverrides(['opaque-window'], fakeStore({}, true)), false, 'storage refused: nothing to reload for')
})

test('outbox: an intent whose git could not be read offers Re-probe; one whose git was read, or that left, does not', () => {
  const unread = (over = {}) => detail(full({ type: 'push-branch', status: 'held', hold: { waits: 'human', reason: 'git could not be read', ask: '' },
    payload: { repo: 'web', branch: 'work/TASK-500', probe_error: 'index.lock exists' }, ...over }))
  const held = unread()
  assert.equal(buttons(held, 'Re-probe').length, 1)
  assert.ok(held.includes('index.lock exists'), 'the button says what git answered')
  assert.equal(buttons(unread({ status: 'pending', hold: null }), 'Re-probe').length, 1, 'a pending one too: the gatekeeper cannot endorse it')
  assert.equal(buttons(unread({ status: 'dropped', hold: null }), 'Re-probe').length, 0, 'an intent that left has nothing to probe')
  assert.equal(buttons(unread({ status: 'returned', hold: null }), 'Re-probe').length, 0, 'a returned one is its lane\'s to amend')
  assert.equal(buttons(detail(full({ status: 'held', hold: { waits: 'human', reason: 'x', ask: '' } })), 'Re-probe').length, 0, 'git was read: no button')
})

test('inbox: a plugin row with neither a page nor a detail still opens a pane; a row whose plugin is gone offers Dismiss', () => {
  const bare = { key: 'plledger-viewr9', plugin: 'ledger-view', id: 'r9', what: 'ledger closed for the week', href: '', detail: null, color: WARN }
  const pane = render(createElement(PluginPanel, { row: bare }))
  assert.ok(pane.includes('data-plugin-detail="ledger-view"') && pane.includes('ledger closed for the week'), 'the pane says what the row says')
  assert.ok(pane.includes('data-row-plain'), 'and that the row has nothing more to open')
  assert.equal(buttons(pane, 'Dismiss').length, 0, 'an installed plugin ends its own rows')
  const orphan = render(createElement(PluginPanel, { row: { ...bare, orphan: true } }))
  assert.equal(buttons(orphan, 'Dismiss').length, 1, 'nothing else would ever take the row away')
  assert.ok(orphan.includes('data-row-orphan'), 'the pane says the plugin is not installed')
  // a row with a detail keeps its pane as it was, and gets Dismiss only when its plugin is gone
  const rich = { ...bare, detail: { title: 'stuck', fields: [{ label: 'why', text: 'x' }], actions: [{ label: 'Retry', act: { do: 'retry' } }] } }
  const kept = render(createElement(PluginPanel, { row: rich }))
  assert.equal(buttons(kept, 'Retry').length, 1); assert.equal(buttons(kept, 'Dismiss').length, 0); assert.equal(kept.includes('data-row-plain'), false)
  assert.equal(buttons(render(createElement(PluginPanel, { row: { ...rich, orphan: true } })), 'Dismiss').length, 1)
})

// ================= Links =================
test('links: only an http(s) address is handed to the system; a file, a script, another scheme or a relative address is not opened', () => {
  const web = ['https://git.acme.test/acme/api/pull/21', 'http://web.slot3.test', 'HTTPS://git.acme.test/a?b=1#c', 'http://127.0.0.1:8080/x']
  const not = ['file:///etc/passwd', 'file://localhost/Applications/Calculator.app', 'javascript:alert(1)', ' javascript:alert(1)', 'JaVaScRiPt:alert(1)',
    'data:text/html,<script>alert(1)</script>', 'vbscript:msgbox(1)', 'smb://host/share', 'ssh://host', 'ms-msdt:/id', 'x-apple.systempreferences:', 'tel:112',
    'mailto:a@acme.test', '//git.acme.test/x', '/Applications/Calculator.app', '../x', 'u', 'git.acme.test/x', 'https:', 'http://', '', null, undefined, 0, {}, []]
  for (const u of web) assert.equal(isWeb(u), true, String(u))
  for (const u of not) assert.equal(isWeb(u), false, String(u))
  opened.length = 0
  for (const u of web) assert.equal(openWeb(u), true, String(u))
  assert.deepEqual(opened, web)
  opened.length = 0
  for (const u of not) assert.equal(openWeb(u), false, String(u))
  assert.deepEqual(opened, [], 'nothing but a web address reaches the system')
})

test('links: every view opens an address through the one checked helper, never through the system call itself', () => {
  const files = readdirSync(src(''), { recursive: true }).map(String).filter((f) => f.endsWith('.js') && f !== path.join('lib', 'sdk.js'))
  assert.ok(files.length > 15, 'the views are read')
  for (const f of files) assert.equal(readFileSync(src(f), 'utf8').includes('openExternal'), false, f)
  assert.equal(readFileSync(src('lib/sdk.js'), 'utf8').split('openExternal').length - 1, 1, 'lib/sdk.js calls it once, inside openWeb')
})

test('links: a demo record whose link is not a web address renders, and its button opens nothing', () => {
  setFx({ demo: { ticket: 'TASK-1', env: 'staging', account: 'x@acme.test', links: [{ label: 'the order', url: 'file:///etc/passwd' }, { label: 'the app', url: 'https://app.acme.test/s/1' }], steps: ['look'], apps: [] } })
  const html = render(createElement(DemoSection, { ticket: 'TASK-1' }))
  assert.match(html, /the order/); assert.match(html, /the app/)
  opened.length = 0
  assert.equal(openWeb('file:///etc/passwd'), false); assert.equal(openWeb('https://app.acme.test/s/1'), true)
  assert.deepEqual(opened, ['https://app.acme.test/s/1'])
})

test('diff: the pane asks for the base diff as `base` unless a view names another mode', () => {
  setFx({ diff: { diff: '', repo: 'api', range: 'origin/main..HEAD' } })
  calls.queries.length = 0
  render(createElement(DiffPanel, { params: { id: 'TASK-1/001-push-branch' } }))
  assert.deepEqual(calls.queries.map((k) => String(k[2])), ['id=TASK-1%2F001-push-branch&mode=base'])
  calls.queries.length = 0
  render(createElement(DiffPanel, { params: { id: 'TASK-1/001-push-branch' }, defaultMode: 'origin' }))
  assert.deepEqual(calls.queries.map((k) => String(k[2])), ['id=TASK-1%2F001-push-branch&mode=origin'])
  setFx()
})
test('diff: the commits a rebase brings are read from commits_base and from no other field', () => {
  assert.deepEqual(baseCommits({ commits_base: ['a1 Move the base'], commits_rc: ['old'] }), ['a1 Move the base'])
  assert.deepEqual(baseCommits({ commits_rc: ['a1 Move the base'] }), [])
  assert.deepEqual(baseCommits({}), [])
  const pane = (extra) => render(createElement(DiffView, { data: { diff: '', repo: 'api', range: 'origin/b..HEAD', mode: 'origin', remote_exists: true, fast_forward: true, commits: [], ...extra } }))
  for (const extra of [{ commits_base: ['a1 Move the base'] }]) {
    const html = pane(extra)
    assert.ok(html.includes('from the base branch through the rebase (1)') && html.includes('a1 Move the base'), JSON.stringify(extra))
  }
  assert.ok(!pane({}).includes('through the rebase'))
  assert.ok(!pane({ commits_base: [] }).includes('through the rebase'))
})

// ---------- what a pack words its own way ----------
test('qa: a run is named by the words the route sends, and by the kernel\'s own where it sends none', () => {
  const { runNames, evidenceRel, RUN_NAMES } = mod.words
  assert.deepEqual(RUN_NAMES, { title: 'Test run', results: 'test-results.md', evidence: 'evidence', plan: 'test-plan.md' })
  for (const none of [undefined, null, {}, { title: '', results: 7, other: 'x' }]) assert.deepEqual(runNames(none), RUN_NAMES)
  assert.deepEqual(runNames({ title: 'Check', results: 'results.md', evidence: 'proof', plan: 'plan.md', other: 'x' }),
    { title: 'Check', results: 'results.md', evidence: 'proof', plan: 'plan.md' })
  assert.deepEqual(runNames({ evidence: 'proof' }), { ...RUN_NAMES, evidence: 'proof' })
  // a row's link loses the evidence folder, written the three ways a results file writes it; any other link stays whole
  for (const rel of ['evidences/1-a.png', './evidences/1-a.png', '/evidences/1-a.png']) assert.equal(evidenceRel(rel, 'evidences'), '1-a.png')
  assert.equal(evidenceRel('./other/1-a.png', 'evidences'), './other/1-a.png')
  assert.equal(evidenceRel('evidences/1-a.png', 'proof'), 'evidences/1-a.png')
  assert.equal(evidenceRel('pr.of/videos/s1.mp4', 'pr.of'), 'videos/s1.mp4')
  assert.equal(evidenceRel('prXof/s1.mp4', 'pr.of'), 'prXof/s1.mp4')   // the folder's name is read as a name, not as a pattern
})

const plain = (html) => html.replace(/&#x27;/g, "'").replace(/&quot;/g, '"').replace(/&gt;/g, '>').replace(/&lt;/g, '<').replace(/&amp;/g, '&')
test('hints: a help text is the pack\'s where the route sends one, and the page\'s own where it sends none or an empty one', () => {
  const { hintsOf, HINTS } = mod.words
  assert.deepEqual(Object.keys(HINTS), ['bumps_tab', 'review', 'bumps', 'rereview', 'bumps_start'])
  for (const none of [undefined, null, {}, { review: '', bumps: 7, other: 'x' }]) assert.deepEqual(hintsOf(none), HINTS)
  assert.deepEqual(hintsOf({ review: 'Mine.' }), { ...HINTS, review: 'Mine.' })
})
test('kickoff: the form prints its own words where the route sends no hints, and the pack\'s where it sends them', () => {
  const { HINTS } = mod.words
  const form = (hints, mode) => { setFx({ repos: { ...BASE.repos, ...(hints ? { hints } : {}) } }); return plain(render(createElement(KickoffForm, { onDone() {}, initialMode: mode }))) }
  const said = (html, text) => html.includes(text)
  assert.ok(said(form(null, 'review'), HINTS.review) && said(form(null, 'review'), HINTS.bumps_tab), 'the page\'s own words')
  assert.ok(said(form(null, 'bumps'), HINTS.bumps))
  const own = { review: 'The reviewer reviews each pull request.', bumps: 'Tick the repos.', bumps_tab: 'Bumps → reviewer' }
  const html = form(own, 'review')
  assert.ok(html.includes('The reviewer reviews each pull request.') && !said(html, HINTS.review) && !html.includes('organize-bumps'), html.slice(0, 300))
  assert.ok(form(own, 'bumps').includes('Tick the repos.') && !said(form(own, 'bumps'), HINTS.bumps))
})
test('inbox: the re-review and bumps panels print the pack\'s words for what their button starts', () => {
  const { HINTS } = mod.words
  const said = (html, text) => html.includes(text)
  const pr = revPr({})
  const panels = () => [plain(render(createElement(ReReviewPanel, { ticket: 'TASK-900', pr, onDone() {} }))),
    plain(render(createElement(BumpsPanel, { repo: 'api', prs: [{ number: 82, title: 'Bump axios', head: 'dependabot/x', url: 'u' }], onDone() {} })))]
  setFx({})
  let [review, bumps] = panels()
  assert.ok(said(review, HINTS.rereview), review.slice(0, 300)); assert.ok(said(bumps, HINTS.bumps_start), bumps.slice(0, 300))
  setFx({ repos: { ...BASE.repos, hints: { rereview: 'the reviewer looks again', bumps_start: 'Pick the batch and Start.' } } });
  [review, bumps] = panels()
  assert.ok(review.includes('the reviewer looks again') && !said(review, HINTS.rereview))
  assert.ok(bumps.includes('Pick the batch and Start.') && !said(bumps, HINTS.bumps_start))
})
test('live: the lanes are listed in the order of the pack\'s seats, and in the page\'s own order where none is sent', () => {
  const { laneOrder, sortLanes, LANES_BEFORE, TOOL_PROFILE } = mod.words
  const once = ['intake', 'worker-1', 'worker-2', 'worker-3', 'tester-1', 'tester-2', 'tester-3', 'reviewer', 'gatekeeper', 'analyst', 'advisor']
  assert.deepEqual(laneOrder(once), LANES_BEFORE)                       // the kernel's seats plus the three names that are no seat
  for (const none of [undefined, null, [], 'x']) assert.deepEqual(laneOrder(none), LANES_BEFORE)   // no order sent
  const shuffled = [...LANES_BEFORE, 'zeta', 'alpha'].reverse()
  assert.deepEqual(sortLanes(shuffled, once), [...LANES_BEFORE, 'alpha', 'zeta'])
  assert.deepEqual(sortLanes(shuffled, null), [...LANES_BEFORE, 'alpha', 'zeta'])
  // more seats than the page once knew: each beside its kind, where they used to fall to the end
  const big = ['intake', 'intake-2', 'worker-1', 'worker-2', 'worker-3', 'worker-4', 'tester-1', 'tester-2', 'tester-3', 'tester-4', 'reviewer', 'reviewer-2', 'gatekeeper', 'analyst', 'analyst-2', 'advisor']
  assert.deepEqual(laneOrder(big), ['intake', 'intake-2', 'orchestrator', 'worker-1', 'worker-2', 'worker-3', 'worker-4', 'tester-1', 'tester-2', 'tester-3', 'tester-4', 'reviewer', 'reviewer-2', 'gatekeeper', 'analyst', 'analyst-2', TOOL_PROFILE, 'advisor', 'default'])
  assert.deepEqual(sortLanes(['worker-4', 'default', 'tester-1', 'intake-2', 'worker-1', 'other'], big), ['intake-2', 'worker-1', 'worker-4', 'tester-1', 'default', 'other'])
  assert.deepEqual(sortLanes(['worker-4', 'tester-1'], null), ['tester-1', 'worker-4'])   // what the fixed list did with a fourth worker
  // a pack with no advisor seat, and one with no analyst: the names that are no seat still have a place
  assert.deepEqual(laneOrder(['intake', 'reviewer', 'gatekeeper', 'analyst']), ['intake', 'orchestrator', 'reviewer', 'gatekeeper', 'analyst', TOOL_PROFILE, 'default'])
  assert.deepEqual(laneOrder(['reviewer', 'gatekeeper', 'advisor']), ['orchestrator', 'reviewer', 'gatekeeper', TOOL_PROFILE, 'advisor', 'default'])
})

// ---------- a page that can be used without a mouse ----------
// Every test above rendered views through the recording jsx: these rules read what those renders made.
const NATIVE = new Set(['button', 'a', 'input', 'select', 'textarea', 'summary', 'label', 'option'])
const shown = (e) => `<${e.tag}> ${e.props.title || e.props.className || JSON.stringify(e.props.style || {})}`.slice(0, 120)
test('keys: every element with a click handler is a native control, or has a role, a tab stop and a key handler', () => {
  const made = globalThis.__cockpitElements.filter((e) => e.props.onClick && !NATIVE.has(e.tag))
  // the rule is not about nothing: the rows, groups, tiles and cards of the views were made
  assert.ok(new Set(made.map(shown)).size >= 12, `only ${new Set(made.map(shown)).size} kinds of clickable element were rendered`)
  const bare = made.filter((e) => e.props.role !== 'presentation' &&
    !(e.props.role && typeof e.props.onKeyDown === 'function' && e.props.tabIndex === 0))
  assert.deepEqual([...new Set(bare.map(shown))], [])
  // what only catches a click (a dialog's body, its backdrop) is no control and takes no tab stop
  const caught = made.filter((e) => e.props.role === 'presentation')
  assert.ok(caught.length > 0 && caught.every((e) => e.props.tabIndex == null))
})
test('keys: Enter and Space press a clickable element; another key, a handled key and a key from inside it do not', () => {
  const { pressable } = mod
  let pressed = 0; const keys = []
  const row = pressable('div', { onClick: () => { pressed += 1 }, onKeyDown: (e) => keys.push(e.key), className: 'x' }, [])
  assert.equal(row.role, 'button'); assert.equal(row.tabIndex, 0); assert.equal(row.className, 'x')
  const key = (k, over = {}) => { const e = { key: k, target: row, currentTarget: row, defaultPrevented: false, preventDefault() { this.defaultPrevented = true }, ...over }; row.onKeyDown(e); return e }
  assert.ok(key('Enter').defaultPrevented); assert.ok(key(' ').defaultPrevented); assert.equal(pressed, 2)
  key('a'); key('Escape'); key('Enter', { defaultPrevented: true }); key(' ', { target: {} })
  assert.equal(pressed, 2); assert.deepEqual(keys, ['Enter', ' ', 'a', 'Escape', 'Enter', ' '])   // the element's own handler hears every key
  // what is left as it was written: a native control, an element that names its own role, one without a handler, a component
  const own = { onClick() {}, role: 'presentation' }
  assert.equal(pressable('div', own, []), own)
  for (const tag of NATIVE) { if (tag === 'button') continue; const p = { onClick() {} }; assert.equal(pressable(tag, p, []), p) }
  const plain = { className: 'x' }; assert.equal(pressable('div', plain, []), plain); assert.equal(pressable('div', null, []), null)
  const part = { onClick() {} }; assert.equal(pressable(() => null, part, []), part)
  assert.equal(pressable('span', { onClick() {}, tabIndex: -1 }, []).tabIndex, -1)   // a tab stop the view chose is kept
})
test('keys: a button that shows only a sign is named', () => {
  const { pressable, iconOnly } = mod
  assert.ok(iconOnly('✕') && iconOnly(['▾', null, false]) && iconOnly(undefined) && !iconOnly('✕ close') && !iconOnly(['▸ ', 7]))
  assert.ok(!iconOnly(createElement('span', null, 'open')) && iconOnly(createElement('span', null, '⟳')))
  assert.equal(pressable('button', { title: 'clear' }, ['✕'])['aria-label'], 'clear')
  assert.equal(pressable('button', { title: 'clear', 'aria-label': 'empty the field' }, ['✕'])['aria-label'], 'empty the field')
  const worded = { title: 'close (Esc)' }; assert.equal(pressable('button', worded, ['✕ close']), worded)
  const untitled = { type: 'button' }; assert.equal(pressable('button', untitled, ['✕']), untitled)
  const unnamed = globalThis.__cockpitElements.filter((e) => e.tag === 'button' && iconOnly(e.props.children) && !e.props['aria-label'])
  assert.deepEqual([...new Set(unnamed.map(shown))], [])
})

// ---------- report ----------
for (const [mark, name, msg] of results) console.log(`${mark} ${name}${msg ? '\n       ' + msg.split('\n').join('\n       ') : ''}`)
const n = (m) => results.filter((r) => r[0].trim() === m).length
console.log(`\nrules: ${results.length} tests · ${n('ok')} passed · ${n('BUG')} BUG (skipped, listed above) · ${n('FAIL')} failed`)
if (n('FAIL')) process.exit(1)
