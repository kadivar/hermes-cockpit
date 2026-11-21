// SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
// SPDX-License-Identifier: AGPL-3.0-or-later
import { useState, useEffect } from 'react'
import { host, haptic, useQuery, useQueryClient, CTX, OPEN, POLL_MS, h, sub, mono, stroke, ClearableTextarea, btn, seg, ago, post, openIde, openFile, trow, Section, prButtons, openWeb } from '../lib/sdk.js'
import { RichMd } from '../lib/markdown.js'
import { DiffPanel } from '../lib/diff.js'
import { Evidence } from './qa.js'
import { TicketTools, intentCard } from './demo.js'
import { copyBtn } from '../lib/secret.js'
import { gateOf, endorserOf } from '../lib/sdk.js'
import { DecidePanel } from './decide.js'

// a stage of a sequence (payload.waits_for): endorsed, but offered only once the stage before it is out
const waitsText = (w) => w.id === 'CI' ? `CI ${w.status}` : `${String(w.id).split('/').pop()} (${w.status})`
function statusMark(r) {
  if (r.status === 'endorsed' && r.waits) return { text: `⋯ next after ${waitsText(r.waits)}`, color: 'var(--ui-text-tertiary)' }
  if (r.status === 'endorsed') return { text: '✓ endorsed', color: 'var(--ui-success, #2a9d5c)' }
  if (r.status === 'held') return { text: '⏸ held', color: 'var(--ui-warning, #c98a00)' }
  if (r.type === 'ticket-done' && r.status === 'pending') return { text: '🏁 awaiting your ack', color: 'var(--ui-accent)' }
  if (r.status === 'pending') return { text: `· waiting for ${gateOf(r)}`, color: 'var(--ui-text-tertiary)' }
  if (r.status === 'returned') return { text: '↩ back in the pipeline', color: 'var(--ui-accent)' }
  if (r.status === 'posted') return { text: '◔ posted · check on the forge', color: 'var(--ui-warning, #c98a00)' }
  if (r.status === 'acknowledged') return { text: '🏁 done, acknowledged', color: 'var(--ui-text-quaternary)' }
  if (r.status === 'reopened') return { text: '↻ reopened', color: 'var(--ui-text-quaternary)' }
  if (r.status.startsWith('published')) return { text: '↗ published', color: 'var(--ui-text-quaternary)' }
  return { text: r.status, color: 'var(--ui-text-quaternary)' }
}
const rebaseBadge = (r) => r.type === 'push-branch' && r.payload && r.payload.rebase_only ? h('span',
  { className: 'ml-1 rounded px-1 text-[0.6875rem] font-medium align-middle whitespace-nowrap',
  style: { background: 'rgba(56,139,253,.18)', color: 'var(--ui-accent)', border: '1px solid var(--ui-accent)' },
  title: 'rebase only: same patches, new base — CI watch ignores it; publish it before the content push' },
  '⟳ rebase') : (r.type === 'push-branch' && r.payload && r.payload.after ? h('span',
  { className: 'ml-1 rounded px-1 text-[0.6875rem] align-middle whitespace-nowrap',
  style: { background: 'rgba(56,139,253,.12)', color: 'var(--ui-accent)' },
  title: 'two steps in one publish: ' + r.payload.after + ' (rebase only) then this change' + (r.chain ? ' · step 1 is ' + r.chain.step1_status : '') },
  '⟳ rebase + change' + (r.chain && r.chain.step1_status !== 'endorsed' && !String(r.chain.step1_status).startsWith('published') ? ' · step 1 ' + r.chain.step1_status : '')) : null)
const riskColor = (risk) => ({ low: 'var(--ui-success, #2a9d5c)', medium: 'var(--ui-warning, #c98a00)', high: 'var(--ui-danger, #d33)' }[risk] || 'var(--ui-text-tertiary)')
const publishLine = (r) => `cockpit publish --id ${r.id}`
const uploadFiles = async (ticket, fileList, setFiles) => {
  for (const f of Array.from(fileList || [])) {
    try {
      const b64 = await new Promise((res, rej) => { const r = new FileReader(); r.onload = () => res(String(r.result).split(',')[1] || ''); r.onerror = rej; r.readAsDataURL(f) })
      const out = await post('/upload', { ticket, name: f.name || ('pasted-' + Date.now() + '.png'), b64 })
      setFiles((xs) => [...xs, { name: f.name || out.path.split('/').pop(), path: out.path, size: out.size }])
    } catch (e) { host.notifyError(e, 'upload failed: ' + (f.name || 'file')) }
  }
}
function Attach({ ticket, files, setFiles }) {
  return h('div', { className: 'flex flex-wrap items-center gap-1 text-xs' },
    h('label', { className: 'rounded border px-2 py-0.5 cursor-pointer', style: { borderColor: stroke, color: 'var(--ui-text-secondary)' } }, '📎 Attach files',
      h('input', { type: 'file', multiple: true, style: { display: 'none' }, onChange: (e) => { uploadFiles(ticket, e.target.files, setFiles); e.target.value = '' } })),
    h('span', { style: sub }, files.length ? '' : 'screenshots, recordings, logs — or paste an image into the text box'),
    ...files.map((f) => h('span', { key: f.path, className: 'rounded border px-1', style: { borderColor: stroke }, title: f.path }, f.name, ' ', h('button', { type: 'button', onClick: () => setFiles(files.filter((x) => x.path !== f.path)), style: sub, 'aria-label': `remove ${f.name}` }, '✕'))))
}
const onPasteImages = (ticket, setFiles) => (e) => { const items = Array.from(e.clipboardData?.items || []).filter((i) => i.kind === 'file'); if (items.length) { e.preventDefault(); uploadFiles(ticket, items.map((i) => i.getAsFile()), setFiles) } }
// what you found missing on a delivered PR: straight to the worker on the branch (tester and reviewer behind it); the push updates the PR
// repos: every repo of the ticket; delivered: the ones with an open PR or commits of their own (a worktree made for reproduction is neither)
function ReworkForm({ ticket, repos, delivered, onDone }) {
  const can = delivered || repos
  const [prompt, setPrompt] = useState(''); const [chosen, setChosen] = useState(can); const [busy, setBusy] = useState(false)
  const qc = useQueryClient()
  const go = async () => {
    if (!prompt.trim() || !chosen.length || busy) return; setBusy(true)
    try { const r = await post('/kickoff', { ticket, mode: 'rework', prompt, repos: chosen }); host.notify({ kind: 'success', title: `${ticket} rework queued`, message: r.out }); qc.invalidateQueries({ queryKey: ['cockpit'] }); onDone && onDone() }
    catch (e) { host.notifyError(e, 'rework failed') } finally { setBusy(false) }
  }
  return h('div', { className: 'flex flex-col gap-2 rounded border p-2 text-xs', style: { borderColor: 'var(--ui-warning, #c98a00)' } },
    h('div', { className: 'font-medium' }, `Rework ${ticket}: what is missing`),
    h('div', { style: sub }, 'Goes straight to the worker on the branch, with a tester and a reviewer behind it; the push comes back as an Outbox row and updates the PR. For a change of plan use Reopen instead.'),
    repos.length > 1 ? h('div', { className: 'flex flex-wrap gap-2' },
      ...repos.map((r) => h('label', { key: r, className: 'flex items-center gap-1', style: can.includes(r) ? {} : sub,
      title: can.includes(r) ? '' : 'nothing delivered here: no PR, no commits of its own' },
      h('input', { type: 'checkbox', disabled: !can.includes(r), checked: chosen.includes(r),
      onChange: (e) => setChosen(e.target.checked ? [...chosen, r] : chosen.filter((x) => x !== r)) }),
      can.includes(r) ? r : `${r} (nothing delivered)`))) : null,
    h(ClearableTextarea, { value: prompt, onChange: (e) => setPrompt(e.target.value), rows: 4, autoFocus: true, placeholder: 'e.g. CS: slides.js:1045 uses if/else — the code-style rule asks for early returns and guard clauses', className: 'rounded border bg-transparent px-1.5 py-1', style: { borderColor: stroke } }),
    h('div', { className: 'flex gap-1.5' }, h('button', { type: 'button', disabled: busy || !prompt.trim() || !chosen.length, onClick: go, className: 'rounded px-2.5 py-0.5 text-xs font-medium disabled:opacity-40', style: { background: 'var(--ui-warning, #c98a00)', color: '#fff' } }, busy ? 'working' : `Rework ${chosen.join(', ') || '…'}`), btn('Cancel', () => onDone && onDone())))
}
// initial: an answer row's "edit first" opens it prefilled ({ prompt, files, from_answer }); the ticket-done row opens it empty
function ReopenForm({ ticket, onDone, title, initial }) {
  const [prompt, setPrompt] = useState((initial && initial.prompt) || ''); const [files, setFiles] = useState((initial && initial.files) || []); const [busy, setBusy] = useState(false)
  const qc = useQueryClient()
  const go = async () => {
    if (!prompt.trim() || busy) return; setBusy(true)
    try { const r = await post('/reopen-flow', { ticket, prompt, evidence: files.map((f) => f.path), title, ...(initial && initial.from_answer ? { from_answer: initial.from_answer } : {}) }); host.notify({ kind: 'success', title: `${ticket} reopened`, message: r.out }); qc.invalidateQueries({ queryKey: ['cockpit'] }); onDone && onDone() }
    catch (e) { host.notifyError(e, 'reopen failed') } finally { setBusy(false) }
  }
  return h('div', { className: 'flex flex-col gap-2 rounded border p-2 text-xs', style: { borderColor: 'var(--ui-accent)' } },
    h('div', { className: 'font-medium' }, `Reopen ${ticket} with new details`),
    h('div', { style: sub }, 'What is wrong or what should happen now. Intake reads the existing evidence and receipts, reproduces, proposes a plan on a card and waits for your go. Nothing starts before that.'),
    h(ClearableTextarea, { value: prompt, onChange: (e) => setPrompt(e.target.value), rows: 5, autoFocus: true, placeholder: 'e.g. After the release the divider is still white on page 2 when the page background is an image. Steps: <how to see it>. Expected: <what should happen>', onPaste: onPasteImages(ticket, setFiles),
      className: 'rounded border bg-transparent px-1.5 py-1', style: { borderColor: stroke } }),
    h(Attach, { ticket, files, setFiles }),
    h('div', { className: 'flex gap-1.5' }, h('button', { type: 'button', disabled: busy || !prompt.trim(), onClick: go, className: 'rounded px-2.5 py-0.5 text-xs font-medium disabled:opacity-40', style: { background: 'var(--ui-accent)', color: '#fff' } }, busy ? 'working' : 'Reopen → intake proposes, I confirm'), btn('Cancel', () => onDone && onDone())))
}
const ciMark = (ci) => !ci ? null : ci.state === 'none' ? { t: 'no CI', c: 'var(--ui-text-tertiary)' } : ci.state === 'green' ? { t: '✓ green',
  c: 'var(--ui-success, #2a9d5c)' } : ci.state === 'failed' ? { t: ci.handled ? '✗ failed · analysed' : ci.analysing ? '✗ failed · analysing' : '✗ failed',
  c: ci.handled ? 'var(--ui-text-tertiary)' : ci.analysing ? 'var(--ui-warning, #c98a00)' : 'var(--ui-danger, #d33)' } : { t: '● running',
  c: 'var(--ui-warning, #c98a00)' }

// ---------- PR watch box (cockpit watch-pr state for the PR behind an intent) ----------
function PrBox({ pr, ticket, repo, refresh }) {
  const [busy, setBusy] = useState(false)
  const treat = async () => {
    setBusy(true)
    try { const res = await post('/pr-treat', { ticket, repo, number: pr.number }); host.notify({ kind: 'success', title: `${ticket} ${repo}#${pr.number}`, message: `comments sent to a worker (card ${res.card_id})` }); refresh() }
    catch (e) { host.notifyError(e, 'treat failed') } finally { setBusy(false) }
  }
  const color = pr.new_count ? 'var(--ui-warning, #c98a00)' : stroke
  return h('div', { className: 'rounded border p-2 text-xs flex flex-col gap-1', style: { borderColor: color } },
    h('div', { className: 'flex items-center gap-2' },
      h('div', { className: 'font-medium' }, pr.role === 'reviewer'
        ? `PR #${pr.number} by ${pr.author} · you reviewed it · ${pr.my_threads ? `${pr.my_threads.resolved}/${pr.my_threads.total} of your threads resolved, ${pr.my_threads.replied} replied` : ''} · ${pr.merged ? 'merged: your review is closed' : pr.state} · checked ${ago(pr.last_check)} ago`
        : `PR #${pr.number} · ${pr.merged ? 'merged' : pr.state} · ${pr.total} comment(s) on the PR · checked ${ago(pr.last_check)} ago`),
      h('a', { href: pr.url, onClick: (e) => { e.preventDefault(); openWeb(pr.url) }, style: { color: 'var(--ui-accent)' } }, 'open on the forge'),
      copyBtn(pr.url, 'PR link'),
      pr.new_count && pr.role !== 'reviewer' ? h('div', { className: 'ml-auto flex gap-1' }, btn(busy ? 'working' : `Treat ${pr.new_count} new comment(s) in the pipeline`, treat, { accent: true, title: 'a card for the ticket\'s lane: same worktree/branch, everything done so far is kept; the lane fixes or replies and amends the intents' }),
        btn('Mark as seen', async () => { setBusy(true); try { const res = await post('/pr-seen', { ticket, repo, number: pr.number }); host.notify({ kind: 'info', message: res.out }); refresh() } catch (e) { host.notifyError(e, 'failed') } finally { setBusy(false) } }, { title: 'you handled them yourself on the forge: advance the baseline, no card' }),
        btn('Forget', async () => { setBusy(true); try { await post('/pr-forget',
          { ticket, repo, number: pr.number }); host.notify({ kind: 'info', message: 'watch file removed' }); refresh() } catch (e) { host.notifyError(e,
          'failed') } finally { setBusy(false) } }, { title: 'delete this pull request\'s watch file' })) : (pr.role === 'reviewer' && !pr.merged ? h('div',
          { className: 'ml-auto' }, btn('Re-review what changed', async () => { setBusy(true); try { const res = await post('/pr-rereview',
          { ticket, repo, number: pr.number }); host.notify({ kind: 'success', message: res.out }); refresh() } catch (e) { host.notifyError(e,
          'failed') } finally { setBusy(false) } }, { accent: true, title: 'the author says it is addressed: verify your threads and review only the diff since your last review' })) : null)),
    pr.new_count ? h('div', { style: { color } }, pr.role === 'reviewer' ? 'The author moved on your threads:' : `${pr.new_count} comment(s) arrived after the pipeline's last pass:`) : h('div', { style: sub }, pr.role === 'reviewer' ? 'No answers to your review yet.' : 'Nothing new since the pipeline last worked on it.'),
    ...(pr.new || []).map((c) => h('div', { key: c.id, className: 'rounded border p-1.5', style: { borderColor: stroke } },
      h('div', { className: 'flex gap-2', style: sub }, h('span', { className: 'font-medium', style: { color: 'var(--ui-text-secondary)' } }, c.author), h('span', null, c.kind), c.path ? h('span', { style: mono }, `${c.path}:${c.line || ''}`) : null, h('span', { className: 'ml-auto' }, ago(c.at) + ' ago')),
      c.html ? h(RichMd, { html: c.html }) : h('div', { className: 'whitespace-pre-wrap' }, (c.body || '').slice(0, 600)))),
    // comments that ask for nothing the team's way (no tag, no suggestion, no change requested): not work, still visible
    (pr.skipped || []).length && pr.role !== 'reviewer' ? h(Section, { title: `Skipped · ${pr.skipped.length} comment(s) that ask for nothing (no tag, no change requested)` },
      ...pr.skipped.map((c) => h('div', { key: c.id, className: 'cockpit-skipped rounded border p-1.5', style: { borderColor: stroke } },
        h('div', { className: 'flex gap-2', style: sub }, h('span', { className: 'font-medium' }, c.author), h('span', null, c.kind), h('span', null, c.why)),
        c.html ? h(RichMd, { html: c.html, style: sub }) : c.body ? h('div', { className: 'whitespace-pre-wrap', style: sub }, c.body) : null))) : null)
}

// ---------- the human approves despite CI (the pack's outbox.ci_override): one approval, this commit, with a reason ----------
function CiOverride({ r, onDone }) {
  const [open, setOpen] = useState(false); const [reason, setReason] = useState(''); const [busy, setBusy] = useState(false)
  if (!r.ci_override_allowed || !OPEN.has(r.status)) return null
  const given = r.ci_override && r.payload && r.ci_override.sha === (r.payload.sha || '') ? r.ci_override : null
  if (given) return h('div', { className: 'text-xs', 'data-ci-override': 'given', style: { color: 'var(--ui-warning, #c98a00)' } }, `CI overridden by you ${given.time ? ago(given.time) + ' ago' : ''}: ${given.reason}`)
  const go = async () => { setBusy(true); try { await post('/ci-override', { id: r.id, reason }); host.notify({ kind: 'info', message: 'CI overridden for this approval' }); setOpen(false); onDone() } catch (e) { host.notifyError(e, 'override failed') } finally { setBusy(false) } }
  if (!open) return h('div', { className: 'text-xs' }, btn('Approve despite CI…', () => setOpen(true), { title: 'skip the green-CI wait for this approval at this commit; recorded with your reason' }))
  return h('div', { className: 'flex flex-col gap-1 rounded border p-2 text-xs', 'data-ci-override': 'ask', style: { borderColor: 'var(--ui-warning, #c98a00)' } },
    h('div', null, 'This approval will not wait for green CI at this commit. Say why (it is kept on the intent):'),
    h('textarea', { value: reason, onChange: (e) => setReason(e.target.value), rows: 2, className: 'rounded border px-1', style: { borderColor: stroke } }),
    h('div', { className: 'flex gap-1.5' }, btn(busy ? 'working…' : 'Override CI', go, { accent: true, disabled: !reason.trim() || busy }), btn('Cancel', () => setOpen(false))))
}

// ---------- stage 2 of a review: the human confirms the verdict and the summary, then it is submitted ----------
function SubmitReviewForm({ r, busy, setBusy, onDone }) {
  const [event, setEvent] = useState((r.review && r.review.proposed_event) || (r.payload && r.payload.event) || 'COMMENT')
  const [summary, setSummary] = useState((r.file_contents && r.file_contents.body_file) || '')
  const go = async () => {
    if (busy) return; setBusy(true)
    try { const res = await post('/publish', { id: r.id, confirm: r.id, event, summary }); host.notify({ kind: 'success', title: 'Review published', message: res.out.slice(0, 400) }); onDone() }
    catch (e) { host.notifyError(e, 'publish failed') } finally { setBusy(false) }
  }
  const opt = (v, label) => h('label', { className: 'flex items-center gap-1 cursor-pointer' }, h('input', { type: 'radio', name: 'ev', checked: event === v, onChange: () => setEvent(v) }), label)
  return h('div', { className: 'flex flex-col gap-2 rounded border p-2 text-xs', style: { borderColor: 'var(--ui-success, #2a9d5c)' } },
    h('div', { className: 'font-medium' }, `Publish the pending review on ${r.target}`),
    h('div', { style: sub }, 'The inline comments are already on the forge as pending. This submits them with the verdict and the summary below; the author is notified at that moment.'),
    h('div', { className: 'flex gap-4' }, opt('REQUEST_CHANGES', 'Request changes'), opt('COMMENT', 'Comment'), opt('APPROVE', 'Approve')),
    event === 'APPROVE' ? h('div', { style: { color: 'var(--ui-warning, #c98a00)' } }, 'Approve is yours alone: the lane proposed ' + ((r.review && r.review.proposed_event) || (r.payload && r.payload.event) || 'a verdict') + '.') : null,
    h(ClearableTextarea, { value: summary, onChange: (e) => setSummary(e.target.value), rows: 10, className: 'rounded border bg-transparent px-2 py-1', style: { ...mono, borderColor: stroke } }),
    h('div', { className: 'flex gap-1.5' },
      h('button', { type: 'button', disabled: busy, onClick: go, className: 'rounded px-2.5 py-0.5 text-xs font-medium', style: { background: 'var(--ui-success, #2a9d5c)', color: '#fff' } }, busy ? 'working' : `Publish as ${event.replace('_', ' ').toLowerCase()}`),
      btn('Cancel', onDone)))
}

// ---------- outbox list + detail ----------
const OUTBOX_COLS = '6rem 9.5rem minmax(12rem, 1fr) 4.5rem 15.5rem 6.5rem 5.5rem 4rem'   // ticket · status · target · risk · type · PR · CI · age
// while a pane is open the list has half the width: ticket · type · target · status only (risk, PR, CI and age come back when it closes)
const COMPACT_COLS = '5.5rem 8.5rem minmax(8rem, 1fr) 9rem'
const LABELS = { full: ['ticket', 'status', 'target', 'risk', 'type', 'PR', 'CI', '>age'], compact: ['ticket', 'status', 'target', 'type'] }
// cells come in as ticket, type, target, risk, status, PR, CI, age; the table shows the status second and the type fifth
const pickCells = (cells, compact) => { const o = [cells[0], cells[4], cells[2], cells[3], cells[1], cells[5], cells[6], cells[7]]; return compact ? [o[0], o[1], o[2], o[4]] : o }
// one colour per intent family, read like the Inbox actions: what kind of act leaves the machine
const typeColor = (t) => t === 'ticket-done' ? 'var(--ui-success, #2a9d5c)'
  : t === 'push-branch' || t === 'open-pr' || t === 'pr-edit' || t === 'pr-patch-apply' ? 'var(--ui-accent)'
  : t === 'pr-comment' || t === 'pr-review-submit' ? '#a78bfa'
  : t.startsWith('tracker') ? '#22d3ee'
  : t === 'ci-rerun' || t === 'ci-dispatch' ? 'var(--ui-warning, #c98a00)'
  : 'var(--ui-text-secondary)'
// the cells every row of the unified list shares (an intent, or an item that carries one): type, PR, CI
const typeCell = (r, extra) => h('div', { key: 'ty', className: 'whitespace-nowrap overflow-hidden font-medium', style: { color: typeColor(r.type) }, title: r.skills && !r.skills.ok ? 'produced without skill ' + r.skills.missing.join(', ') : '' }, extra || r.type, rebaseBadge(r), r.skills && !r.skills.ok ? h('span', { style: { color: 'var(--ui-danger, #d33)' } }, ' ●') : null)
const prCell = (r) => h('div', { key: 'pr', className: 'flex gap-1 items-center whitespace-nowrap overflow-hidden', title: r && r.pr ? `${r.pr.url} · ${r.pr.new_count} comment(s) ahead of the pipeline` : '' },
  r && r.pr ? h('span', { style: sub }, r.pr.merged ? 'merged' : `#${r.pr.number}`) : h('span', { style: sub }, '–'),
  r && r.pr && !r.pr.merged && r.pr.approvals && r.pr.approvals.length ? h('span', { style: { color: 'var(--ui-success, #2a9d5c)' }, title: 'approved by ' + r.pr.approvals.map((a) => a.author).join(', ') }, '👍') : null,
  r && r.pr && r.pr.new_count ? h('span', { className: 'rounded px-1', style: { background: 'var(--ui-warning, #c98a00)', color: '#fff' } }, `${r.pr.new_count} new`) : null)
const ciCell = (r) => { const ci = ciMark(r && r.ci); return h('div', { key: 'ci', className: 'whitespace-nowrap overflow-hidden', title: r && r.ci ? `CI on ${r.ci.branch} @ ${r.ci.sha}: ${r.ci.summary}` : '' }, ci ? h('span', { style: { color: ci.c } }, ci.t) : h('span', { style: sub }, '–')) }
function Row({ r, selected, onSelect, compact }) {
  const m = statusMark(r)
  return trow(compact ? COMPACT_COLS : OUTBOX_COLS, { key: r.id, onClick: () => onSelect(r.id), selected, title: r.payload && r.payload.rebase_only ? 'rebase only' : undefined, children: pickCells([
    h('div', { key: 't', className: 'truncate font-medium' }, r.ticket),
    typeCell(r),
    h('div', { key: 'tg', className: 'truncate', title: r.summary }, r.target),
    h('div', { key: 'r', style: { color: riskColor(r.risk) } }, r.risk),
    h('div', { key: 's', className: 'truncate', style: { color: m.color } }, m.text),
    prCell(r), ciCell(r),
    h('div', { key: 'a', className: 'truncate text-right', style: sub, title: r.created_by }, ago(r.created_at))], compact) })
}

// what leaves: the rendered preview first (a tracker body as tracker shows it, markdown rendered), the exact source one tab away
const sourceKind = (path) => (/\.json$/i.test(path || '') ? 'JSON' : /\.md$/i.test(path || '') ? 'Markdown' : 'Source')
const prettySource = (source, kind) => { if (kind !== 'JSON') return source; try { return JSON.stringify(JSON.parse(source), null, 2) } catch (e) { return source } }
function LeavesBody({ html, source, path }) {
  const [view, setView] = useState('preview')
  const kind = sourceKind(path)
  const raw = h('pre', { className: 'cockpit-source whitespace-pre-wrap text-xs', style: mono }, prettySource(source, kind))
  if (!html) return raw
  return h('div', { className: 'flex flex-col gap-2' },
    h('div', { className: 'flex items-center gap-1 self-start rounded border p-0.5', style: { borderColor: stroke } }, seg(view, 'preview', 'Preview', setView), seg(view, 'source', kind, setView)),
    view === 'preview' ? h(RichMd, { html }) : raw)
}

function Detail({ id }) {
  const qc = useQueryClient()
  const q = useQuery({ queryKey: ['cockpit', 'intent', id], queryFn: () => CTX.rest('/intent?id=' + encodeURIComponent(id)), refetchInterval: POLL_MS, retry: 1 })
  const [tab, setTab] = useState('intent')
  const [ask, setAsk] = useState(null); const [toWorker, setToWorker] = useState(false)
  const [reason, setReason] = useState('')
  const [busy, setBusy] = useState(false)
  const [files, setFiles] = useState([])
  useEffect(() => { setAsk(null); setReason(''); setTab('intent') }, [id])
  useEffect(() => { setFiles([]) }, [id, ask])
  if (q.isLoading) return h('div', { className: 'p-3 text-xs', style: sub }, 'loading')
  if (q.error) return h('div', { className: 'p-3 text-xs', style: { color: 'var(--ui-danger, #d33)' } }, String(q.error.message || q.error))
  const r = q.data; const p = r.payload || {}; const m = statusMark(r)
  const refresh = () => qc.invalidateQueries({ queryKey: ['cockpit'] })
  const act = async (path, body, okMsg) => {
    setBusy(true)
    try { const res = await post(path, body); host.notify({ kind: 'success', message: okMsg || (res && res.out) || 'done' }); setAsk(null); setReason(''); refresh() }
    catch (e) { host.notifyError(e, 'cockpit outbox: action failed') } finally { setBusy(false) }
  }
  const copy = async () => { await CTX.os.writeClipboard(publishLine(r)); host.notify({ kind: 'info', message: 'Copied for your shell: ' + publishLine(r) }) }
  const kv = (k, v) => v ? h('div', { className: 'flex gap-2 text-xs' }, h('div', { className: 'w-20 shrink-0', style: sub }, k), h('div', { className: 'min-w-0 break-words', style: mono }, v)) : null
  const canAct = OPEN.has(r.status) && r.type !== 'ticket-done'
  const note = r.type === 'infra-note' && Boolean(r.payload) && Boolean(r.payload.repo && r.payload.branch && r.payload.patch_file)
  const proposesApprove = r.type === 'pr-review-submit' && r.status !== 'posted' && Boolean(r.payload) && r.payload.event === 'APPROVE'
  const confirmable = canAct && r.status === 'held' && Boolean(r.hold) && r.hold.waits === 'human' && !r.hold.ask
  const hasRepo = Boolean(p.repo)
  const isDone = r.type === 'ticket-done'
  return h('div', { className: 'flex h-full flex-col gap-3 overflow-auto p-3' },
    h('div', { className: 'flex items-baseline gap-2' },
      h('div', { className: 'font-medium text-sm' }, r.digest_no ? `#${r.digest_no} · ` : '', r.ticket, ' · ', r.type, rebaseBadge(r)),
      h('div', { className: 'text-xs', style: { color: m.color } }, m.text),
      h('div', { className: 'ml-auto text-xs', style: sub }, `${r.created_by || ''} · ${ago(r.created_at)} ago`)),
    h('div', { className: 'text-xs' }, r.summary),
    r.chain && r.chain.role === 'content' ? h('div', { className: 'rounded border px-2 py-1 text-xs flex flex-col gap-0.5', style: { borderColor: 'var(--ui-accent)' } },
      h('div', { className: 'font-medium' }, 'Two steps, one publish'),
      h('div', null, h('span', { style: { color: String(r.chain.step1_status).startsWith('published') || r.chain.step1_status === 'endorsed' ? 'var(--ui-success, #2a9d5c)' : 'var(--ui-warning, #c98a00)' } },
        `1 · ${r.chain.step1_status}`), h('span', { style: sub }, r.chain.step1_rebase === false ? ` ${r.chain.step1_type} · ${r.chain.step1}` : ` ⟳ rebase only · ${r.chain.step1} · ${r.chain.step1_proof || ''}`)),
      h('div', null, h('span', { style: { color: r.status === 'endorsed' ? 'var(--ui-success, #2a9d5c)' : 'var(--ui-warning, #c98a00)' } }, `2 · ${r.status}`), h('span', { style: sub }, ` → the change (this intent): ${r.target}`)),
      !(String(r.chain.step1_status).startsWith('published') || r.chain.step1_status === 'endorsed') ? h('div', { style: { color: 'var(--ui-warning, #c98a00)' } }, 'step 1 is not endorsed yet: the gatekeeper must endorse both before Publish') : null) : null,
    r.waits ? h('div', { className: 'rounded border px-2 py-1 text-xs', style: { borderColor: 'var(--ui-warning, #c98a00)' }, 'data-waits': r.waits.id },
      h('span', { className: 'font-medium' }, 'A stage of a sequence: '),
      r.waits.id === 'CI' ? `offered once CI at its commit is green (CI ${r.waits.status}).` : `offered once ${r.waits.id} (${r.waits.type}) is out; it is ${r.waits.status}.`) : null,
    r.stale_days ? h('div', { className: 'rounded border px-2 py-1.5 text-xs', style: { borderColor: 'var(--ui-warning, #c98a00)' } },
      h('span', { className: 'font-medium', style: { color: 'var(--ui-warning, #c98a00)' } }, 'Stale'), ` pending for ${r.stale_days} days and nothing has touched it. It has no card on the Board: drop it if nobody will act on it.`) : null,
    r.stale_head ? h('div', { className: 'flex flex-wrap items-center gap-2 rounded border px-2 py-1.5 text-xs', style: { borderColor: 'var(--ui-warning, #c98a00)' } },
      h('span', null, h('span', { className: 'font-medium', style: { color: 'var(--ui-warning, #c98a00)' } }, 'PR head moved'), ` after this review was written: reviewed ${r.stale_head.reviewed}, now ${r.stale_head.now}. cockpit publish refuses it because line comments would mis-anchor.`),
      h('button', { type: 'button', disabled: busy, onClick: () => { haptic('tap'); setBusy(true); post('/pr-rereview',
        { ticket: r.ticket, repo: p.repo, number: p.number, supersede: r.id }).then((res) => { host.notify({ kind: 'success',
        title: `${r.ticket} re-review at ${r.stale_head.now}`, message: res.out }); refresh() }).catch((e) => host.notifyError(e,
        're-review failed')).finally(() => setBusy(false)) }, className: 'rounded px-2.5 py-0.5 text-xs font-medium',
        style: { background: 'var(--ui-accent)', color: '#fff' }, title: 'the reviewer lane re-verifies this review\'s findings at the new head and writes a fresh review intent; this one is dropped as superseded' },
        busy ? 'working' : '↻ Re-review at the new head'),
      btn('Diff since the reviewed head', () => setTab('diff'), { title: 'what the author pushed after the review' })) : null,
    r.status === 'held' && r.hold && r.hold.ask ? h(DecidePanel, { r, onDone: refresh }) : null,
    isDone ? h('div', { className: 'flex flex-wrap items-center gap-1.5' },
      r.status === 'pending' ? h('button', { type: 'button', disabled: busy, onClick: () => { haptic('tap'); setAsk(ask === 'ack' ? null : 'ack') },
        className: 'rounded px-2.5 py-0.5 text-xs font-medium', style: { background: 'var(--ui-success, #2a9d5c)', color: '#fff' },
        title: 'Only you can do this: the ticket is merged, released and really done in dev. Nothing is published.' }, '🏁 Confirm done') : null,
      r.status !== 'reopened' ? btn('Reopen with details', () => setAsk(ask === 'reopen' ? null : 'reopen'), { accent: true, title: 'restart the flow on this ticket with your prompt and evidence; intake proposes and waits for your go' }) : null,
      r.pr ? h('a', { href: r.pr.url, onClick: (e) => { e.preventDefault(); openWeb(r.pr.url) }, className: 'text-xs', style: { color: 'var(--ui-accent)' } }, 'PR on the forge') : null,
      r.pr ? copyBtn(r.pr.url, 'PR link') : null,
      btn('Reveal', () => CTX.os.revealPath(r.path))) : null,
    ask === 'ack' ? h('div', { className: 'flex items-center gap-2 rounded border p-2 text-xs', style: { borderColor: 'var(--ui-success, #2a9d5c)' } },
      h('span', null, `Confirm ${r.ticket} is done in dev? This only records your acknowledgement locally.`),
      h('button', { type: 'button', disabled: busy, onClick: () => act('/ack', { id: r.id, confirm: r.id }, 'Acknowledged ' + r.ticket), className: 'rounded px-2.5 py-0.5 text-xs font-medium', style: { background: 'var(--ui-success, #2a9d5c)', color: '#fff' } }, busy ? 'working' : 'Yes, done'), btn('Cancel', () => setAsk(null))) : null,
    ask === 'reopen' ? h(ReopenForm, { ticket: r.ticket, onDone: () => setAsk(null) }) : null,
    !isDone ? h('div', { className: 'flex flex-wrap items-center gap-1.5' },
      r.type === 'pr-review-submit' && r.status === 'posted' ? h('button',
        { type: 'button', disabled: busy, onClick: () => { haptic('tap'); setAsk(ask === 'submit' ? null : 'submit') },
        className: 'rounded px-2.5 py-0.5 text-xs font-medium', style: { background: 'var(--ui-success, #2a9d5c)', color: '#fff' },
        title: 'stage 2: submit the pending review with the verdict and a summary you confirm' }, '✓ Publish review') : null,
      r.type === 'pr-review-submit' && r.status === 'posted' && r.review ? h('a', { href: r.review.url, onClick: (e) => { e.preventDefault(); openWeb(r.review.url) }, className: 'text-xs', style: { color: 'var(--ui-accent)' } }, 'check it on the forge') : null,
      r.type === 'pr-review-submit' && r.status === 'posted' ? btn('Discard pending review', () => setAsk(ask === 'discard' ? null : 'discard'), { danger: true, title: 'delete the pending review on the forge; the intent goes back to endorsed (send it back with notes, or post again)' }) : null,
      // a hold that asks nothing is yours to confirm: that is the pane's first button, where Publish is once it is confirmed
      // (a greyed Publish beside a small Confirm read as "nothing to do here")
      confirmable ? h('button', { type: 'button', disabled: busy, 'data-step': 'confirm', onClick: () => act('/confirm', { id: r.id }, 'Confirmed ' + r.id + ' — publish it when you are ready'),
        className: 'rounded px-2.5 py-0.5 text-xs font-medium disabled:opacity-40', style: { background: 'var(--ui-success, #2a9d5c)', color: '#fff' },
        title: `You checked it: ${r.hold.reason || 'what the gatekeeper held it for'}. Endorse it as yours; Publish is the next step.` }, 'Confirm') : null,
      // an infrastructure note with a patch: applying it is yours (it becomes your commit and a push for the gate)
      canAct && note ? h('button', { type: 'button', disabled: busy, 'data-step': 'apply-note', onClick: () => { haptic('tap'); setAsk(ask === 'apply' ? null : 'apply') },
        className: 'rounded px-2.5 py-0.5 text-xs font-medium disabled:opacity-40', style: { background: 'var(--ui-success, #2a9d5c)', color: '#fff' },
        title: 'commit this patch on the ticket\'s checkout as yours and file its push' }, 'Apply patch') : null,
      canAct && r.status !== 'posted' && !confirmable && r.type !== 'infra-note' ? h('button', { type: 'button', disabled: r.status !== 'endorsed' || busy || Boolean(r.stale_head) || Boolean(r.waits) || (r.chain && r.chain.role === 'content' && !(r.chain.step1_status === 'endorsed' || String(r.chain.step1_status).startsWith('published'))), onClick: () => { haptic('tap'); setAsk('publish') },
        className: 'rounded px-2.5 py-0.5 text-xs font-medium disabled:opacity-40',
        style: { background: 'var(--ui-success, #2a9d5c)', color: '#fff' },
        title: r.waits ? 'A later stage: it is offered once the stage before it is out' : r.status === 'endorsed' ? 'Publish this intent now (cockpit publish --id <intent>). You confirm on the next step.' : 'Needs the gatekeeper\'s endorsement first (Inbox → Gate tools → Sweep now)' },
          r.chain && r.chain.role === 'content' ? (r.chain.step1_rebase === false ? `✓ Publish both (${r.chain.step1_type}, then ${r.type})` : '✓ Publish both (rebase, then change)') : r.type === 'pr-review-submit' ? '✓ Post as pending review' : '✓ Publish') : null,
      canAct ? btn('Copy publish line', copy, { title: publishLine(r) + '  — the same thing from your own shell' }) : null,
      btn('Open intent file', () => openIde({ id: r.id, file: r.path }), { title: r.path }),
      btn('Reveal', () => CTX.os.revealPath(r.path), { title: 'show in Finder' }),
      canAct ? h('span', { className: 'mx-1', style: sub }, '|') : null,
      canAct ? btn('Verify sha', async () => { setBusy(true); try { const res = await post('/verify',
        { id: r.id }); if (res && res.ok === false) host.notifyError(new Error((res.problems || ['not verified']).join(' · ')),
        'verify: not ok'); else host.notify({ kind: 'success', message: (res && res.out) || 'verified' }) } catch (e) { host.notifyError(e,
        'cockpit outbox: action failed') } finally { setBusy(false) } }, { title: 'cockpit outbox verify: intent sha vs the worktree HEAD' }) : null,
      // git could not be read when the intent was written: read it again, with what goes out left as it is
      canAct && r.payload && r.payload.probe_error && ['pending', 'held', 'endorsed'].includes(r.status)
        ? btn('Re-probe', () => act('/reprobe', { id: r.id }, 'Git read again for ' + r.id + ' — it is back with the gatekeeper'), { accent: true, title: `git could not be read when this intent was written (${r.payload.probe_error}): read it again; what goes out is not changed` }) : null,
      canAct && r.status !== 'returned' ? btn('Send back', () => { setAsk('return'); if (r.hold && r.hold.rework) setReason((r.hold.ask ? `Decision: \n\n` : '') + r.hold.rework) }, { accent: true, title: 'tell the lane what to change; it reworks on the same branch and amends this intent' }) : null,
      // a hold that waits on you and asks nothing (commits by another author, say): you check it, then confirm it as yours;
      // Publish is then your next step, and nothing publishes it for you
      canAct && r.status !== 'held' ? btn('Hold', () => setAsk('hold')) : null,
      canAct ? btn('Drop', () => setAsk('drop'), { danger: true }) : null) : null,
    h(CiOverride, { r, onDone: refresh }),
    ask === 'submit' ? h(SubmitReviewForm, { r, busy, setBusy, onDone: () => { setAsk(null); refresh() } }) : null,
    ask === 'discard' ? h('div', { className: 'flex items-center gap-2 rounded border p-2 text-xs', style: { borderColor: 'var(--ui-danger, #d33)' } },
      h('span', null, 'Delete the pending review on the forge? The findings stay in the intent; you can send it back with notes and post again.'),
      h('button', { type: 'button', disabled: busy, onClick: () => act('/review-discard', { id: r.id, confirm: r.id }, 'pending review discarded'), className: 'rounded px-2.5 py-0.5 text-xs font-medium', style: { background: 'var(--ui-danger, #d33)', color: '#fff' } }, busy ? 'working' : 'Discard'), btn('Cancel', () => setAsk(null))) : null,
    ask === 'apply' ? h('div', { className: 'flex flex-col gap-2 rounded border p-2 text-xs', style: { borderColor: 'var(--ui-success, #2a9d5c)' } },
      h('div', { className: 'font-medium' }, `Apply ${r.payload.patch_file} in ${r.payload.repo} on ${r.payload.branch}?`),
      h('div', { style: sub }, `It is committed there as your commit, and its push is filed for the gatekeeper and your Publish. ${r.created_by || 'The lane'} wrote the patch and could not write these files itself. Read the patch first: this is the approval of that one diff.`),
      h('div', { className: 'flex items-center gap-1.5' },
        h('button', { type: 'button', disabled: busy, onClick: () => { haptic('tap'); act('/apply-note', { id: r.id, confirm: r.id }, 'Applied ' + r.id + ' — its push comes to the Inbox') }, className: 'rounded px-2.5 py-0.5 text-xs font-medium', style: { background: 'var(--ui-success, #2a9d5c)', color: '#fff' } }, busy ? 'working' : 'Apply now'),
        btn('Open the patch', () => openIde({ id: r.id, file: r.payload.patch_file }), { title: r.payload.patch_file }),
        btn('Cancel', () => setAsk(null)))) : null,
    ask === 'publish' ? h('div', { className: 'flex flex-col gap-2 rounded border p-2 text-xs', style: { borderColor: 'var(--ui-success, #2a9d5c)' } },
      h('div', { className: 'font-medium' }, r.chain && r.chain.role === 'content'
        ? (r.chain.step1_rebase === false
          ? `Publish the pair: 1 · ${r.chain.step1_type} (${r.chain.step1}) then 2 · ${r.type} ${r.target}?`
          : `Publish the pair: 1 · rebase only (${r.chain.step1}) then 2 · ${r.target}?`)
        : r.type === 'pr-review-submit' ? (proposesApprove
          ? `Post the review on ${r.target} as PENDING, with the verdict the lane proposed: APPROVE? Approving is yours alone: you confirm the verdict when you publish it (stage 2). Only you can see it until then.`
          : `Post the review on ${r.target} as PENDING? Only you can see it there; nobody is notified until you publish it (stage 2).`)
        : `Publish ${r.type} → ${r.target}?`),
      h('div', { style: sub }, `Runs as you: ${publishLine(r)}. Endorsed by ${endorserOf(r)} ${r.endorsed ? ago(r.endorsed.time) + ' ago, risk ' + r.endorsed.risk : ''}. cockpit publish re-checks the sha against the worktree before anything leaves.`),
      r.pr && r.pr.new_count ? h('div', { style: { color: 'var(--ui-warning, #c98a00)' } }, `Note: ${r.pr.new_count} PR comment(s) arrived after the pipeline's pass — treat them first if they change this.`) : null,
      h('div', { className: 'flex items-center gap-1.5' },
        h('button', { type: 'button', disabled: busy, onClick: () => { haptic('tap'); act('/publish', proposesApprove ? { id: r.id, confirm: r.id, approve: true } : { id: r.id, confirm: r.id }, 'Published ' + r.id) }, className: 'rounded px-2.5 py-0.5 text-xs font-medium', style: { background: 'var(--ui-success, #2a9d5c)', color: '#fff' } }, busy ? 'working' : 'Publish now'),
        btn('Dry run', async () => { setBusy(true); try { const res = await post('/publish', { id: r.id, dry_run: true }); host.notify({ kind: 'info', message: res.out, title: 'Dry run' }) } catch (e) { host.notifyError(e, 'dry run failed') } finally { setBusy(false) } }, { title: 'cockpit publish --dry-run: shows what would happen, nothing leaves' }),
        btn('Cancel', () => setAsk(null)))) : null,
    ask && ask !== 'publish' && ask !== 'apply' ? h('div', { className: 'flex items-center gap-2 rounded border p-2 text-xs', style: { borderColor: stroke } },
      h('span', null, ask === 'hold' ? 'Hold — why?' : ask === 'return' ? `Send back to ${r.created_by || 'the lane'} — what should change?` : 'Drop this intent (the lane keeps its work; nothing is deleted). Note:'),
      ask === 'return'
        ? h('div', { className: 'flex min-w-0 flex-1 flex-col gap-1' }, h(ClearableTextarea, { value: reason, onChange: (e) => setReason(e.target.value), autoFocus: true, rows: 3, placeholder: 'e.g. make the comment more concise: two sentences, no restating the diff', onPaste: onPasteImages(r.ticket, setFiles),
            className: 'min-w-0 rounded border bg-transparent px-1.5 py-0.5', style: { borderColor: stroke },
              onKeyDown: (e) => { if (e.key === 'Escape') setAsk(null); if (e.key === 'Enter' && (e.metaKey || e.ctrlKey) && reason.trim()) act('/return',
              { id: r.id, instruction: reason, evidence: files.map((f) => f.path), ...(toWorker ? { assignee: 'worker' } : {}) }) } }),
              h(Attach, { ticket: r.ticket, files, setFiles }),
            // a lane that does not write code (a reviewer, the gatekeeper) cannot make a code change: a worker takes the card
            h('label', { className: 'flex items-center gap-1.5', style: sub, title: 'a free worker makes the change on the ticket\'s checkout and files its push; the lane that wrote this intent then redoes it' },
              h('input', { type: 'checkbox', checked: toWorker, onChange: (e) => setToWorker(e.target.checked) }), 'it needs a code change: send it to a worker'))
        : h('input', { value: reason, onChange: (e) => setReason(e.target.value), autoFocus: true, placeholder: ask === 'hold' ? 'reason (required)' : 'optional note',
            className: 'min-w-0 flex-1 rounded border bg-transparent px-1.5 py-0.5', style: { borderColor: stroke }, onKeyDown: (e) => { if (e.key === 'Escape') setAsk(null) } }),
      btn(busy ? 'working' : (ask === 'hold' ? 'Hold' : ask === 'return' ? 'Send back (⌘↵)' : 'Drop'), () => {
        if (busy) return
        if (ask === 'return') { if (!reason.trim()) return; act('/return', { id: r.id, instruction: reason, evidence: files.map((f) => f.path), ...(toWorker ? { assignee: 'worker' } : {}) }); return }
        if (ask === 'hold' && !reason.trim()) return
        act(ask === 'hold' ? '/hold' : '/drop', ask === 'hold' ? { id: r.id, reason } : { id: r.id, note: reason }) }, { danger: ask === 'drop', accent: ask === 'return' }),
      btn('Cancel', () => setAsk(null))) : null,
    // the busy reader's version, always open: what leaves · why · checked · touches
    // a held intent with a question has its chat inside the decision form, above the question: one chat per pane
    r.status === 'held' && r.hold && r.hold.ask ? null : h(TicketTools, { ticket: r.ticket, card: intentCard(r), part: 'chat' }),
    h(Section, { title: 'Brief', open: true, color: 'var(--ui-accent)' }, h(RichMd, { html: r.brief || '' })),
    h(TicketTools, { ticket: r.ticket, card: intentCard(r), part: 'demo' }),
    // what leaves the machine is never collapsed: the exact text the publish sends
    r.outgoing && r.file_contents && r.file_contents[r.outgoing] != null ? h(Section, { title: `What leaves · ${(r.files[r.outgoing] || '').split('/').slice(-2).join('/')}`, open: true, color: 'var(--ui-success, #2a9d5c)', extra: btn('open', () => openFile(r.files[r.outgoing]), { title: r.files[r.outgoing] }) },
      (r.file_truncated || []).includes(r.outgoing) ? h('div', { className: 'text-xs', style: { color: 'var(--ui-danger, #d33)' } }, 'This body is larger than the Cockpit shows (2 MB): open the file to read all of it.') : null,
      h(LeavesBody, { html: r.file_html && r.file_html[r.outgoing], source: r.file_contents[r.outgoing], path: r.files[r.outgoing] })) : null,
    h('div', { className: 'flex flex-wrap items-center gap-2' },
      h('div', { className: 'flex items-center gap-1 rounded border p-0.5', style: { borderColor: stroke } }, seg(tab, 'intent', 'Intent', setTab), hasRepo ? seg(tab, 'diff', r.type === 'pr-patch-apply' ? 'Diff (what gets pushed)' : r.type === 'push-branch' ? 'Diff (what gets pushed)' : 'Diff (worktree vs the base branch)', setTab) : null, seg(tab, 'evidence', 'Evidence (QA runs)', setTab)),
      prButtons(r.prs)),
    tab === 'evidence' ? h(Evidence, { ticket: r.ticket }) :
    tab === 'diff' ? h(DiffPanel, { params: { id: r.id }, defaultMode: r.type === 'pr-patch-apply' ? 'origin' : r.type === 'push-branch' ? (r.chain && r.chain.role === 'content' ? 'change' : 'origin') : 'base', chained: Boolean(r.chain && r.chain.role === 'content'), rebaseOnly: Boolean(p.rebase_only) }) : h('div', { className: 'flex flex-col gap-2' },
      // PR and CI stay open only while something there needs you (new comments, a failed run)
      r.pr || r.ci ? h(Section, { title: 'PR · CI' + (r.pr && r.pr.new_count ? ` · ${r.pr.new_count} new comment(s)` : '') + (r.ci ? ` · CI ${r.ci.state}` : ''), open: Boolean((r.pr && r.pr.new_count) || (r.ci && r.ci.state === 'failed' && !r.ci.handled)), color: (r.pr && r.pr.new_count) || (r.ci && r.ci.state === 'failed' && !r.ci.handled) ? 'var(--ui-warning, #c98a00)' : undefined },
        r.pr ? h(PrBox, { pr: r.pr, ticket: r.ticket, repo: p.repo, refresh }) : null,
        r.ci ? h('div', { className: 'rounded border p-2 text-xs flex flex-col gap-1', style: { borderColor: ciMark(r.ci).c } },
          h('div', { className: 'flex items-center gap-2' }, h('div', { className: 'font-medium' }, `CI on ${r.ci.branch || ''} @ ${r.ci.sha}: ${r.ci.summary} · checked ${ago(r.ci.last_check)} ago`),
            r.ci.state === 'failed' ? h('span', { className: 'ml-auto flex items-center gap-1' }, r.ci.handled ? h('span', { style: sub }, r.ci.dismissed ? 'dismissed' : 'analysed') : btn('Dismiss', () => act('/ci-dismiss', { ticket: r.ticket, repo: r.ci.repo || p.repo, sha: r.ci.sha }, 'CI failure dismissed'), { title: 'drop it from the Inbox (you dealt with it, or it does not matter)' }),
            btn('Forget', () => act('/ci-forget', { ticket: r.ticket, sha: r.ci.sha }, 'CI state forgotten'), { title: 'delete this sha\'s check-watch state' })) : null),
          ...r.ci.runs.map((x) => h('div', { key: x.id, className: 'flex gap-2' },
            h('span', { style: { color: x.conclusion === 'success' ? 'var(--ui-success, #2a9d5c)' : x.status !== 'completed' ? 'var(--ui-warning, #c98a00)' : 'var(--ui-danger, #d33)' } },
            x.conclusion || x.status), h('a', { href: x.url, onClick: (e) => { e.preventDefault(); openWeb(x.url) }, style: { color: 'var(--ui-accent)' } },
            `${x.workflow} / ${x.name}`), r.ci.cards[String(x.id)] ? h('span', { style: sub },
            `→ analyst card ${r.ci.cards[String(x.id)]}`) : null))) : null) : null,
      h(Section, { title: `${(r.endorsed && r.endorsed.by) || 'gatekeeper'} check · ` + (r.endorsed ? `endorsed, risk ${r.endorsed.risk}` : r.hold ? 'held' : r.status), color: r.hold ? 'var(--ui-warning, #c98a00)' : undefined },
      // the gatekeeper's notes, its hold and the return's instruction are markdown; the backend renders them (*_html), older rows show the text
      r.endorsed ? h('div', { className: 'rounded border p-2 text-xs', style: { borderColor: 'var(--ui-success, #2a9d5c)' } }, h('div', { className: 'font-medium' }, `${endorserOf(r)} endorsed · risk ${r.endorsed.risk} · ${ago(r.endorsed.time)} ago`), r.endorsed_html && r.endorsed_html.notes ? h(RichMd, { html: r.endorsed_html.notes }) : h('div', null, r.endorsed.notes || '')) : null,
      r.hold ? h('div', { className: 'rounded border p-2 text-xs', style: { borderColor: 'var(--ui-warning, #c98a00)' } }, h('div', { className: 'font-medium' }, 'Held'), r.hold_html && r.hold_html.reason ? h(RichMd, { html: r.hold_html.reason }) : h('div', null, r.hold.reason)) : null,
      r.receipt ? h('div', { className: 'rounded border p-2 text-xs', style: { borderColor: stroke } },
        h('div', { className: 'font-medium' }, `Published ${ago(r.receipt.time)} ago`),
        r.receipt.url ? h('a', { href: r.receipt.url, onClick: (e) => { e.preventDefault(); openWeb(r.receipt.url) }, style: { color: 'var(--ui-accent)' } }, r.receipt.url) : null,
        r.receipt.output ? h('pre', { className: 'whitespace-pre-wrap', style: { ...mono, ...sub } }, String(r.receipt.output).slice(0, 600)) : null) : null,
      r.returned ? h('div', { className: 'rounded border p-2 text-xs', style: { borderColor: 'var(--ui-accent)' } },
        h('div', { className: 'font-medium' }, `Sent back to ${r.returned.lane} · ${ago(r.returned.time)} ago${r.returned.card ? ' · card ' + r.returned.card : ''}${r.returned.resolved ? ' · reworked ' + ago(r.returned.resolved) + ' ago' : ' · rework pending'}`),
        r.returned_html && r.returned_html.instruction ? h(RichMd, { html: r.returned_html.instruction }) : h('div', { className: 'whitespace-pre-wrap' }, r.returned.instruction)) : null,
      r.skills && r.skills.required && r.skills.required.length ? h('div', { className: 'text-xs flex gap-2 items-center' },
        h('span', { style: sub }, 'produced with skills:'),
        h('span', { style: mono }, r.skills.loaded ? r.skills.loaded.join(', ') || '(none)' : '(no run log)'),
        r.skills.ok ? h('span', { style: { color: 'var(--ui-success, #2a9d5c)' } }, '✓ ' + r.skills.required.join(', ')) : h('span', { className: 'rounded px-1', style: { background: 'var(--ui-danger, #d33)', color: '#fff' } }, 'missing ' + r.skills.missing.join(', ') + ' — hold / send back')) : null,
      !r.endorsed && !r.hold && !r.receipt && !r.returned && !(r.skills && r.skills.required && r.skills.required.length) ? h('div', { style: sub }, 'nothing recorded yet') : null),
      h(Section, { title: 'Details' + (p.commits && p.commits.length ? ` · ${p.commits.length} commit(s)` : '') + (p.files && p.files.length ? ` · ${p.files.length} file(s)` : '') },
      h('div', { className: 'flex flex-col gap-1' },
        kv('intent', r.id), kv('card', r.card_id), kv('repo', p.repo), kv('branch', p.branch ? `${p.branch}${p.publish_as && p.publish_as !== p.branch ? ' → ' + p.publish_as : ''}` : null),
        kv('base', p.base), kv('sha', p.sha), p.rebase_only ? kv('rebase', `only — ${p.rebase_proof || ''}`) : null,
          p.after ? kv('after', p.after + ' (lease = its sha)') : null, kv('PR', p.number ? `#${p.number} ${p.event || ''}` : null),
          r.type === 'pr-comment' ? kv('posts as', p.in_reply_to ? `reply in review thread ${p.in_reply_to}${p.react ? ' · 👍' : ''}${p.resolve ? ' · resolves ' + (p.thread || '?') : ''}` : 'top-level PR comment') : null,
          kv('issue', p.issue), kv('title', p.title), kv('diff', p.diffstat)),
      p.commits && p.commits.length ? h('div', null, h('div', { className: 'text-xs font-medium' }, 'Commits'), h('pre', { className: 'whitespace-pre-wrap text-xs', style: mono }, p.commits.join('\n'))) : null,
      p.files && p.files.length ? h('div', null, h('div', { className: 'text-xs font-medium' }, `Files (${p.files.length})`), h('pre', { className: 'whitespace-pre-wrap text-xs', style: mono }, p.files.join('\n'))) : null),
      ...Object.entries(r.file_contents || {}).filter(([k]) => k !== r.outgoing).map(([k, text]) => h(Section, { key: k, title: `${k.replace('_file', '')} · ${r.files[k].split('/').slice(-2).join('/')}`, extra: btn('open', () => openFile(r.files[k]), { title: r.files[k] }) },
        (r.file_html && r.file_html[k]) ? h(RichMd, { html: r.file_html[k] }) : h('pre', { className: 'whitespace-pre-wrap text-xs', style: mono }, text))),
      (r.history && r.history.length) || (r.log && r.log.length) ? h(Section, { title: 'History · log' },
        r.history && r.history.length ? h('div', { className: 'text-xs', style: sub }, r.history.map((x) => `${x.event} ${ago(x.time)} ago${x.card ? ' (' + x.card + ')' : ''}`).join(' · ')) : null,
        r.log && r.log.length ? h('pre', { className: 'whitespace-pre-wrap text-xs', style: { ...mono, ...sub } }, r.log.join('\n')) : null) : null))
}

export { typeColor, typeCell, prCell, ciCell, Detail, Row, SubmitReviewForm, CiOverride, ReopenForm, ReworkForm, Attach, onPasteImages, uploadFiles, statusMark, rebaseBadge, riskColor, publishLine, ciMark, PrBox, OUTBOX_COLS, COMPACT_COLS, LABELS, pickCells }
