// SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
// SPDX-License-Identifier: AGPL-3.0-or-later
import { useState, useEffect } from 'react'
import { host, useQuery, useQueryClient, CTX, OPEN, POLL_MS, h, sub, mono, stroke, ClearableTextarea, btn, seg, ago, toMs, post, openFile, openIde, trow, SplitList, detailHead, BriefGrid, Section, prButtons, prList, openWeb } from '../lib/sdk.js'
import { RichMd } from '../lib/markdown.js'
import { hintsOf, trackerWord } from '../lib/packwords.js'
import { DiffView, DiffPanel } from '../lib/diff.js'
import { ReworkForm, ReopenForm, Row, Detail, typeCell, prCell, ciCell, typeColor, riskColor, OUTBOX_COLS, COMPACT_COLS, LABELS, pickCells } from './outbox.js'
import { Viewer, fmtSize } from './qa.js'
import { TicketTools, ticketOf, intentCard } from './demo.js'
import { copyBtn } from '../lib/secret.js'
import { NextLine } from './settings.js'
import { endorserOf } from '../lib/sdk.js'
import { DecidePanel } from './decide.js'
import { AdvisoryPanel, AdvisoryRow, advisoryWhat, severityColor, alertable } from './advisories.js'

// ---------- needs you: blocked cards (answer here), final acks, CI failures, PR comments ----------
// media and text files of an evidence folder: a button each, the viewer inline under them
function FileButtons({ files }) {
  const [file, setFile] = useState(null)
  const media = files.filter((f) => f.kind === 'image' || f.kind === 'video' || f.kind === 'pdf'); const rest = files.filter((f) => !(f.kind === 'image' || f.kind === 'video' || f.kind === 'pdf'))
  const fileBtn = (f) => h('button', { key: f.path, type: 'button', onClick: () => setFile(file && file.path === f.path ? null : f), title: `${f.rel} · ${fmtSize(f.size || 0)}`, className: 'rounded border px-1 text-[0.6875rem]',
    style: { borderColor: file && file.path === f.path ? 'var(--ui-accent)' : stroke, color: f.kind === 'image' ? 'var(--ui-accent)' : f.kind === 'video' ? 'var(--ui-success, #2a9d5c)' : 'var(--ui-text-secondary)' } }, (f.kind === 'image' ? '🖼 ' : f.kind === 'video' ? '▶ ' : f.kind === 'pdf' ? '📄 ' : '') + f.rel.split('/').pop())
  return h('div', { className: 'flex flex-col gap-1' }, h('div', { className: 'flex flex-wrap gap-1' }, ...media.map(fileBtn), ...rest.map(fileBtn)), file ? h(Viewer, { file, onClose: () => setFile(null) }) : null)
}
function CardView({ c }) {
  const a = c.attachments || { docs: [], dirs: [], files: [], brief: null }
  const docs = a.docs || []
  const dirs = a.dirs || []
  const files = a.files || []
  const comments = c.comments || []
  const events = c.events || []
  return h('div', { className: 'flex flex-col gap-2 text-xs' },
    h('div', { className: 'flex flex-wrap items-center gap-2' }, (c.prs || []).length ? h('span', { className: 'flex items-center gap-2' }, h('span', { style: sub }, 'PRs:'), prList(c.prs)) : null),
    h('div', { className: 'flex flex-wrap gap-2', style: sub }, h('span', null, c.status), h('span', null, c.assignee), c.created ? h('span', null, 'created ' + ago(c.created) + ' ago') : null, c.skills ? h('span', null, 'skills ' + (Array.isArray(c.skills) ? c.skills.join(', ') : c.skills)) : null, c.workspace ? h('span', { style: mono }, c.workspace) : null),
    // the only section open by default: issue · fix · ruled out · changes, in platform words
    h(TicketTools, { ticket: ticketOf(c.title), card: c.id, part: 'chat' }),
    h(Section, { title: 'Brief', open: true, color: 'var(--ui-accent)' }, a.brief ? h(RichMd, { html: a.brief }) : h('div', { style: sub }, 'no Brief on this card yet (the plan format asks the lane for one: issue · fix · ruled out · changes)')),
    h(TicketTools, { ticket: ticketOf(c.title), card: c.id, part: 'demo' }),
    // a card that works in a ticket worktree: the patch to review, uncommitted changes included, and the IDE on it
    c.worktree ? h(Section, { title: `Diff · ${c.worktree.repo} worktree (vs origin, the uncommitted patch included)`, extra: btn('Open IDE', () => openIde({ ticket: c.worktree.ticket }), { title: 'VS Code on the ticket workspace' }) }, h(DiffPanel, { params: { ticket: c.worktree.ticket, repo: c.worktree.repo }, defaultMode: 'origin' })) : null,
    ...docs.map((d) => h(Section, { key: d.path, title: `Plan · ${(d.rel || '').split('/').slice(-2).join('/')}`, extra: btn('Open', () => openFile(d.path)) }, h(RichMd, { html: d.html }))),
    ...dirs.map((d) => h(Section, { key: d.path, title: `Evidence · ${(d.rel || '').split('/').slice(-2).join('/')} (${(d.files || []).length} files)`, extra: btn('Reveal', () => CTX.os.revealPath(d.path)) }, h(FileButtons, { files: d.files || [] }))),
    files.length ? h(Section, { title: `Files (${files.length})` }, h(FileButtons, { files })) : null,
    h(Section, { title: 'Card body' }, h(RichMd, { html: c.body_html })),
    c.result_html ? h(Section, { title: 'Result', color: 'var(--ui-success, #2a9d5c)' }, h(RichMd, { html: c.result_html })) : null,
    c.error ? h('div', { className: 'rounded border px-2 py-1', style: { borderColor: 'var(--ui-danger, #d33)', color: 'var(--ui-danger, #d33)' } }, String(c.error).slice(0, 600)) : null,
    comments.length ? h(Section, { title: `Comments (${comments.length})` }, ...comments.map((m, i) => h('div', { key: i, className: 'rounded border px-2.5 py-1.5', style: { borderColor: stroke } }, h('div', { style: sub }, `${m.author} · ${m.ts ? ago(m.ts) + ' ago' : ''}`), h(RichMd, { className: '', html: m.html })))) : null,
    events.length ? h('div', { style: sub }, 'events: ' + events.map((e) => `${e.kind} ${ago(e.ts)}`).join(' · ')) : null)
}
// a lane that cannot log in blocks with "CREDENTIALS NEEDED · <environment> · <email> · <why>" (cockpitlib.vault.block_text)
const CRED = /^CREDENTIALS NEEDED\s*·\s*(\S+)\s*·\s*([^\s·]+)\s*(?:·\s*([\s\S]*))?$/
const credentialAsk = (q) => {
  const m = CRED.exec((q || '').trim())
  if (!m || !String(m[2]).includes('@')) return null
  return { email: m[2], why: (m[3] || '').trim() }
}

// the masked form: the login goes into the tester lanes' Hermes vaults (model-blind autofill), never onto the board
function CredentialsForm({ c, ask, refresh }) {
  const [email, setEmail] = useState(ask.email); const [pw, setPw] = useState(''); const [key, setKey] = useState(''); const [busy, setBusy] = useState(false)
  const twoFactor = /^2FA\b/i.test(ask.why || '')   // the lane met a code step: the authenticator key is what it needs
  const ok = Boolean(email.trim() && pw)
  const save = async () => {
    if (!ok || busy) return; setBusy(true)
    try { const r = await post('/staging-credentials', { id: c.id, email: email.trim(), password: pw, otp: key.replace(/\s+/g, '') || undefined }); host.notify({ kind: 'success', title: `${c.ticket || c.id}: staging login stored`, message: r.out }); refresh() }
    catch (e) { host.notifyError(e, 'storing the login failed') } finally { setPw(''); setKey(''); setBusy(false) }
  }
  const field = (props) => h('input', { ...props, className: 'w-full rounded border bg-transparent px-2 py-1 text-xs', style: { borderColor: stroke } })
  return h('div', { className: 'cockpit-creds mt-2 flex flex-col gap-2 rounded-md border px-3 py-2 text-xs', style: { borderColor: 'var(--ui-warning, #c98a00)', background: 'rgba(201,138,0,.07)' } },
    h('div', { className: 'cockpit-head', style: { color: 'var(--ui-warning, #c98a00)' } }, 'staging login needed'),
    ask.why ? h('div', null, ask.why) : null,
    h('label', { className: 'flex flex-col gap-0.5' }, h('span', { style: sub }, 'test account (email)'), field({ type: 'email', value: email, onChange: (e) => setEmail(e.target.value), autoComplete: 'off', spellCheck: false })),
    h('label', { className: 'flex flex-col gap-0.5' }, h('span', { style: sub }, 'password'), field({ type: 'password', value: pw, onChange: (e) => setPw(e.target.value), autoComplete: 'new-password', autoFocus: true, onKeyDown: (e) => { if (e.key === 'Enter') save() } })),
    h('label', { className: 'flex flex-col gap-0.5' }, h('span', { style: sub }, twoFactor ? 'authenticator key (the 2FA secret, not a code)' : 'authenticator key (optional: only for a login with 2FA)'),
      field({ type: 'password', value: key, onChange: (e) => setKey(e.target.value), autoComplete: 'off', spellCheck: false, autoFocus: twoFactor })),
    h('div', { style: sub }, `Stored only in this lane's Hermes vault, bound to ${ask.origin || 'the origin in the pack'}. The lane fills it without seeing it; it never reaches the board or a log. Use a staging test account only.`),
    h('div', { className: 'flex items-center gap-2' },
      h('button', { type: 'button', disabled: !ok || busy, onClick: save, className: 'rounded px-3 py-1 text-xs font-medium disabled:opacity-40', style: { background: 'var(--ui-accent)', color: '#fff' } }, busy ? 'working' : 'Save to vault & resume'),
      btn('Stop', async () => { try { await post('/answer', { id: c.id, text: 'stop: no staging login; I will take it from here.' }); refresh() } catch (e) { host.notifyError(e, 'stop failed') } }, { danger: true, title: 'closes the card; nothing re-runs' })))
}

// one of the pack's own approvals (pack.yaml asks): Approve runs the pack's command as you and resumes the card; Deny answers it
function PackAskForm({ c, refresh }) {
  const ask = c.pack_ask; const [busy, setBusy] = useState(false); const [reason, setReason] = useState('')
  const act = async (fn, done) => { if (busy) return; setBusy(true); try { const r = await fn(); host.notify({ kind: 'success', title: `${c.ticket || c.id}: ${done}`, message: r.out }); refresh() } catch (e) { host.notifyError(e, `${ask.name} failed`) } finally { setBusy(false) } }
  return h('div', { className: 'mt-2 flex flex-col gap-2 rounded-md border px-3 py-2 text-xs', style: { borderColor: 'var(--ui-warning, #c98a00)', background: 'rgba(201,138,0,.07)' } },
    h('div', { className: 'cockpit-head', style: { color: 'var(--ui-warning, #c98a00)' } }, `${c.assignee || 'the lane'} asks: ${ask.name}`),
    h('input', { value: reason, onChange: (e) => setReason(e.target.value), placeholder: 'reason for a denial (optional)', className: 'w-full rounded border bg-transparent px-2 py-1 text-xs', style: { borderColor: stroke } }),
    h('div', { className: 'flex items-center gap-2' },
      h('button', { type: 'button', disabled: busy, onClick: () => act(() => post('/ask-approve', { id: c.id }), 'approved'), className: 'rounded px-3 py-1 text-xs font-medium disabled:opacity-40', style: { background: 'var(--ui-warning, #c98a00)', color: '#fff' } }, busy ? 'working' : ask.label),
      btn('Deny', () => act(() => post('/answer', { id: c.id, text: ask.deny + (reason.trim() ? ' — ' + reason.trim() : '') }), 'denied'), { disabled: busy })))
}

// a tester asking for the review of a Test run that is not finished (rows blocked, not run or waiting for the human): the minute
// housekeeping (cockpit board unfinished-runs) sends it back; it is yours only when parked (unblock does not reach triage) or still here after that
const notReady = (c) => (c.not_ready || []).length > 0
const onlyShots = (c) => notReady(c) && c.not_ready.every((r) => String(r).endsWith('·screenshot'))   // a green run whose rows only miss their screenshots: the human may waive them
const rowsOf = (c) => c.not_ready.map((r) => String(r).replace(/·.*$/, ''))
const SEND_BACK_GRACE_S = 120
const ROW_TONE = { info: 'var(--ui-accent)', ok: 'var(--ui-success, #2a9d5c)', warn: 'var(--ui-warning, #c98a00)', danger: 'var(--ui-danger, #d33)' }   // a plugin's Inbox row (cockpitlib.inbox TONES)
function BlockedCard({ c, refresh }) {
  const [text, setText] = useState(''); const [busy, setBusy] = useState(false)
  const cq = useQuery({ queryKey: ['cockpit', 'card-detail', c.id], queryFn: () => CTX.rest('/card-detail?id=' + c.id), retry: 0 })
  const send = async (t) => {
    const msg = (t || text).trim(); if (!msg || busy) return; setBusy(true)
    try { const r = await post('/answer', { id: c.id, text: msg }); host.notify({ kind: 'success', title: `${c.ticket || c.id} answered`, message: r.out }); setText(''); refresh() }
    catch (e) { host.notifyError(e, 'answer failed') } finally { setBusy(false) }
  }
  const primary = (label, onClick, extra = {}) => h('button', { type: 'button', disabled: busy || extra.disabled, onClick, title: extra.title || '', className: 'rounded px-3 py-1 text-xs font-medium disabled:opacity-40', style: { background: extra.bg || 'var(--ui-accent)', color: '#fff' } }, label)
  return h('div', { className: 'flex h-full min-h-0 flex-col' },
    // scrolling part: the question, then the card
    h('div', { className: 'min-h-0 flex-1 overflow-auto flex flex-col gap-3 pr-1' },
      c.question ? h('div', { className: 'rounded-md border px-3 py-2 text-xs', style: { borderColor: 'var(--ui-warning, #c98a00)', background: 'rgba(201,138,0,.07)' } },
        h('div', { className: 'cockpit-head mb-1', style: { color: 'var(--ui-warning, #c98a00)' } }, `${c.assignee} asks`),
        // the short question when the backend found one; a backend without it sends the block reason as before
        c.ask_html ? h(RichMd, { html: c.ask_html, className: 'leading-relaxed' })
          : c.question_html ? h(RichMd, { html: c.question_html, className: 'leading-relaxed' })
            : h('div', { className: 'whitespace-pre-wrap leading-relaxed' }, c.question)) : null,
      // What the answer decides: the lane's report, open and rendered, right under its question — not folded into
      // the card's comments, where the reader had to go and find the plan they were approving.
      // the platform's card: a Section, open, the way the card view's Brief and Plan read
      c.report_html ? h('div', { 'data-report': '1', className: 'text-xs' },
        h(Section, { title: `${c.assignee} reports`, open: true, color: 'var(--ui-accent)' }, h(RichMd, { html: c.report_html, className: 'leading-relaxed' }))) : null,
      notReady(c) ? h('div', { className: 'rounded-md border px-3 py-2 text-xs', style: { borderColor: 'var(--ui-danger, #d33)' } },
        h('div', { className: 'cockpit-head mb-1', style: { color: 'var(--ui-danger, #d33)' } }, 'not ready for your review'),
        h('div', { className: 'mb-2' }, c.not_ready.includes('(no results table)') ? 'No results table was found for this run (a table with a Result column).' : onlyShots(c) ? `Rows ${rowsOf(c).join(', ')} passed but link no screenshot of the verified state (text evidence only).` : `Rows ${rowsOf(c).join(', ')} are still blocked, not run or waiting for your result, so the run is not finished.`),
        h('div', { className: 'flex flex-wrap items-center gap-2' },
          primary(onlyShots(c) ? 'Send back: take the screenshots' : 'Send back: finish those rows',
            () => send(onlyShots(c) ? `take the screenshots of rows ${rowsOf(c).join(', ')} first (a screenshot from your browser_exec session, copied to the run's evidence folder), then ask for the review again` : `finish rows ${rowsOf(c).join(', ')} first: a run with blocked or not-run rows is not finished, so it is not ready for review`),
            { bg: 'var(--ui-danger, #d33)' }),
          onlyShots(c) ? primary('go without screenshots', () => send('go without screenshots: the text evidence is accepted for this run'), { title: 'accept this run as it is: the text evidence stands for these rows, the results post may follow', bg: 'var(--ui-success, #2a9d5c)' }) : null)) : null,
      h('div', { className: 'rounded-md border px-3 py-2', style: { borderColor: stroke } }, h('div', { className: 'cockpit-head mb-1' }, 'the card'), cq.data ? h(CardView, { c: cq.data }) : h('div', { className: 'text-xs', style: sub }, 'loading the card'))),
    // answer bar: pinned to the bottom of the pane (a staging login request gets the masked form instead)
    credentialAsk(c.question) ? h(CredentialsForm, { c, ask: credentialAsk(c.question), refresh }) : c.pack_ask && c.pack_ask.name ? h(PackAskForm, { c, refresh }) : h('div', { className: 'mt-2 flex flex-col gap-2 rounded-md border px-3 py-2', style: { borderColor: 'var(--ui-accent)', background: 'rgba(56,139,253,.06)' } },
      h('div', { className: 'cockpit-head' }, 'your answer'),
      h(ClearableTextarea, { value: text, onChange: (e) => setText(e.target.value), rows: 3,
        placeholder: 'go · go with changes: <what to change> · the information the lane asked for · stop (closes the card)',
        className: 'w-full rounded border bg-transparent px-2 py-1.5 text-xs', style: { borderColor: stroke, resize: 'vertical' },
        onKeyDown: (e) => { if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) send() } }),
      h('div', { className: 'flex items-center gap-2' },
        notReady(c) ? null : primary('go', () => send('go'), { title: 'the plan is approved: start', bg: 'var(--ui-success, #2a9d5c)' }),   // an unfinished run cannot be accepted
        primary('stop', () => send('stop: do not continue; I will take it from here.'), { title: 'closes the card; nothing re-runs', bg: 'var(--ui-danger, #d33)' }),
        btn('Archive card', async () => { try { await post('/card-archive', { id: c.id }); host.notify({ kind: 'info', message: `${c.id} archived` }); refresh() } catch (e) { host.notifyError(e, 'archive failed') } }, { title: 'nothing left to do here: drop it from the board' }),
        h('span', { className: 'ml-auto text-[0.6875rem]', style: sub }, '⌘↵'),
        primary(busy ? 'working' : 'Answer & resume', () => send(), { disabled: !text.trim() }))))
}
function PrDiffPanel({ ticket, pr }) {
  // same two-level look as the outbox Diff tab: a bordered mode toggle, then the diff view
  const [mode, setMode] = useState('since')
  const qs = `ticket=${encodeURIComponent(ticket)}&repo=${encodeURIComponent(pr.repo)}&number=${pr.number}&mode=${mode}`
  const q = useQuery({ queryKey: ['cockpit', 'pr-diff', qs], queryFn: () => CTX.rest('/pr-diff?' + qs), staleTime: 60000, retry: 0 })
  const sr = pr.since_review || {}
  const toggle = h('div', { className: 'flex items-center gap-1 self-start rounded border p-0.5', style: { borderColor: stroke } },
    seg(mode, 'since', `since your review (what the author pushed${sr.commits ? `, ${sr.commits} commit(s)` : ''})`, setMode),
    seg(mode, 'full', `vs ${pr.base || 'the base branch'} (what the whole PR changes)`, setMode))
  if (q.isLoading) return h('div', { className: 'flex flex-col gap-2' }, toggle, h('div', { className: 'text-xs', style: sub }, 'reading the diff from the forge…'))
  if (q.error) return h('div', { className: 'flex flex-col gap-2' }, toggle, h('div', { className: 'text-xs', style: { color: 'var(--ui-danger, #d33)' } }, String(q.error.message || q.error)))
  return h('div', { className: 'flex flex-col gap-2' }, toggle,
    q.data && q.data.note ? h('div', { className: 'rounded border px-2 py-1 text-xs', style: { borderColor: 'var(--ui-warning, #c98a00)' } }, q.data.note) : null,
    q.data && mode === 'since' && !(q.data.commits || []).length && !(q.data.diff || '').trim() ? h('div', { className: 'text-xs', style: sub }, 'Nothing pushed since your review: the head is still what you reviewed.') : null,
    q.data ? h(DiffView, { data: q.data }) : null)
}
// the pages' help texts in the pack's words: the /repos route's hints (the query the kickoff form already makes)
// the tracker's name for a row or a pane that names it: the same query's tracker_kind
const useTrackerWord = () => trackerWord((useQuery({ queryKey: ['cockpit', 'repos'], queryFn: () => CTX.rest('/repos'), refetchInterval: POLL_MS * 6, retry: 0 }).data || {}).tracker_kind)
const useHints = () => hintsOf((useQuery({ queryKey: ['cockpit', 'repos'], queryFn: () => CTX.rest('/repos'), refetchInterval: POLL_MS * 6, retry: 0 }).data || {}).hints)
function ReReviewPanel({ ticket, pr, onDone }) {
  const hints = useHints()
  const [note, setNote] = useState(''); const [busy, setBusy] = useState(false); const [tab, setTab] = useState('review')
  useEffect(() => { setTab('review') }, [ticket, pr.repo, pr.number])
  const mt = pr.my_threads || {}; const sr = pr.since_review || {}
  const go = async () => { setBusy(true); try { const r = await post('/pr-rereview', { ticket, repo: pr.repo, number: pr.number, note }); host.notify({ kind: 'success', title: `${ticket} re-review started`, message: r.out }); onDone() } catch (e) { host.notifyError(e, 're-review failed') } finally { setBusy(false) } }
  return h('div', { className: 'flex flex-col gap-3 p-3 text-xs' },
    detailHead(`${ticket} · ${pr.repo} #${pr.number}`, { text: 'you review · still open', color: 'var(--ui-accent)' }, pr.my_review_state && pr.my_review_state !== 'none' ? 'your last review: ' + pr.my_review_state.toLowerCase().replace('_', ' ') : 'no review submitted yet'),
    h('div', { className: 'flex items-center gap-2' }, prButtons([pr])),
    h('div', { className: 'flex items-center gap-1 self-start rounded border p-0.5', style: { borderColor: stroke } }, seg(tab, 'review', 'Review', setTab), seg(tab, 'diff', 'Diff (the PR since your review / vs the base branch)', setTab)),
    tab === 'diff' ? h(PrDiffPanel, { ticket, pr }) : h('div', { className: 'flex flex-col gap-3' },
    h(TicketTools, { ticket, part: 'chat' }),
    (() => { const quiet = pr.last_activity ? (Date.now() - toMs(pr.last_activity)) / 60000 : null
      const verdict = pr.re_requested ? ['The author re-requested your review: good time.',
        'var(--ui-success, #2a9d5c)'] : (mt.total && mt.resolved === mt.total) ? ['All your threads are resolved: good time.',
        'var(--ui-success, #2a9d5c)'] : quiet != null && quiet < 60 && (mt.replied || sr.commits) ? ['The author moved in the last hour: probably still patching.',
        'var(--ui-warning, #c98a00)'] : ['No signal that the author is done; re-review when you want a look anyway.', 'var(--ui-text-tertiary)']
      return h(Section, { title: 'Brief', open: true, color: 'var(--ui-accent)' }, h(BriefGrid, { fields: [
        { label: 'Timing', text: verdict[0], color: verdict[1] },
        { label: 'Your threads', text: `${mt.total || 0} opened · ${mt.resolved || 0} resolved · ${mt.replied || 0} replied by the author` },
        { label: 'Since review', text: sr.commits ? `${sr.commits} commit(s), ${sr.files != null ? sr.files : '?'} file(s) changed${sr.last_push ? ', last push ' + ago(sr.last_push) + ' ago' : ''}` : 'nothing pushed' },
        { label: 'Last activity', text: pr.last_activity ? ago(pr.last_activity) + ' ago' : '–' },
        { label: 'Re-review does', text: hints.rereview }] })) })(),
    h(TicketTools, { ticket, part: 'demo' }),
    (pr.replies || []).length ? h(Section, { title: `The author's replies in your threads (${pr.replies.length})` },
      ...pr.replies.map((c, i) => h('div', { key: i, className: 'rounded border px-2 py-1', style: { borderColor: stroke } },
      h('div', { style: sub }, `${c.author || ''} · ${c.at ? ago(c.at) + ' ago' : ''}`),
      (c.html ? h(RichMd, { html: c.html }) : h('div', { className: 'whitespace-pre-wrap' }, (c.body || c.text || '').slice(0, 1200)))))) : null,
    h(ClearableTextarea, { value: note, onChange: (e) => setNote(e.target.value), rows: 3, placeholder: 'optional note for the reviewer, e.g. the author says everything is addressed; focus on thread 2 and the new migration', className: 'rounded border bg-transparent px-2 py-1', style: { borderColor: stroke } }),
    h('div', { className: 'flex gap-1.5' }, h('button', { type: 'button', disabled: busy, onClick: go, className: 'rounded px-2.5 py-0.5 text-xs font-medium', style: { background: 'var(--ui-accent)', color: '#fff' } }, busy ? 'working' : 'Re-review what changed'), btn('Open PR', () => openWeb(pr.url)))))
}

// ---------- one row per PR: a push and the replies that ride on it are one decision for you (the Outbox keeps them apart) ----------
const GOOD = 'var(--ui-success, #2a9d5c)'
const prKey = (r) => { const p = (r && r.payload) || {}; const n = p.number || (r && r.pr && r.pr.number); return p.repo && n ? `${p.repo}#${n}` : '' }
function afterShort(after) {
  const parts = String(after || '').split('/')
  const tail = parts.length > 1 ? parts[1] : parts[0]
  return String(tail || '').slice(0, 3)
}
function groupByPr(items) {
  const groups = new Map(); const out = []
  for (const it of items) {
    const k = it.row ? prKey(it.row) : ''
    if (!k) { out.push(it); continue }
    if (!groups.has(k)) { const g = { pr: k, ticket: it.ticket, members: [] }; groups.set(k, g); out.push(g) }
    groups.get(k).members.push(it)
  }
  return out.map((g) => {
    if (!g.members) return g
    if (g.members.length === 1) return g.members[0]
    const m = g.members; const lead = m.find((x) => x.color !== GOOD) || m[0]
    const counts = m.reduce((a, x) => ({ ...a, [x.row.type]: (a[x.row.type] || 0) + 1 }), {})
    const types = Object.entries(counts).map(([t, n]) => (n > 1 ? `${n} ${t}` : t)).join(', ')
    return { key: 'g' + g.ticket + g.pr, icon: lead.icon, ticket: g.ticket, what: `${g.pr} — ${m.length} items (${types}) — ${lead.what.split(' — ').slice(1).join(' — ')}`,
      action: [...new Set(m.flatMap((x) => x.action.split(' / ')))].join(' / '), ts: m.map((x) => x.ts || '').sort().pop(), color: lead.color, group: { pr: g.pr, members: m } }
  })
}
// the items of one PR in publish order (cockpitlib.intents.ORDER, sent as row.order); "Publish all" sends the ready ones in turn
function PrGroupPanel({ g, ticket, goOutbox, onDone }) {
  const [busy, setBusy] = useState(false); const [ask, setAsk] = useState(false); const [rework, setRework] = useState(false)
  const members = [...g.members].sort((a, b) => (a.row.order ?? 99) - (b.row.order ?? 99))
  const ready = members.filter((x) => x.action === 'publish' && x.row.status === 'endorsed' && !x.row.stale_head)
  const publishAll = async () => {
    setBusy(true); let done = 0
    try { for (const x of ready) { const r = await post('/publish', { id: x.row.id, confirm: x.row.id }); if (r && r.receipt && r.receipt.ok === false) throw new Error(r.receipt.error || 'refused'); done += 1; host.notify({ kind: 'success', title: `Published ${x.row.id}`, message: r.out }) } onDone() }
    catch (e) { host.notifyError(e, `publishing stopped after ${done} of ${ready.length}`) } finally { setBusy(false); setAsk(false) }
  }
  return h('div', { className: 'cockpit-prgroup flex h-full min-h-0 flex-col gap-2 overflow-auto p-3' },
    detailHead(`${ticket} · ${g.pr}`, { text: `${members.length} items on this PR`, color: 'var(--ui-accent)' }, ''),
    h(TicketTools, { ticket, part: 'chat' }),
    h('div', { className: 'flex items-center gap-2' }, btn(rework ? 'Close' : 'Rework', () => setRework(!rework), { title: 'something is missing on this PR: tell the worker; tester and reviewer follow, the push updates the PR' })),
    rework ? h(ReworkForm, { ticket, repos: [String(g.pr).split('#')[0]], onDone: () => setRework(false) }) : null,
    // each item carries its own next step, so a group never looks like it has nothing to do: a posted review is published
    // (or discarded) from its own pane, a held item is decided there, an endorsed one goes with "Publish in order"
    ...members.map((x) => h('div', { key: x.key, className: 'rounded border px-2.5 py-1.5 text-xs flex flex-col gap-1', style: { borderColor: stroke } },
      h('div', { className: 'flex items-center gap-2' }, h('span', { className: 'font-medium', style: { color: x.color } }, x.action), h('span', { style: mono }, x.row.id),
        h('span', { className: 'ml-auto flex items-center gap-1.5' },
          memberStep(x) ? h('button', { type: 'button', 'data-step': memberStep(x).step, onClick: () => goOutbox(x.row.id), className: 'rounded px-2.5 py-0.5 text-xs font-medium', style: { background: memberStep(x).color, color: '#fff' }, title: memberStep(x).title }, memberStep(x).label) : null,
          btn('Open the intent', () => goOutbox(x.row.id), { title: 'the intent with its Brief, what leaves, the gatekeeper check and the diffs' }))),
      h('div', { style: sub }, x.what.split(' — ').slice(1).join(' — ')))),
    ready.length ? (ask
      ? h('div', { className: 'flex flex-col gap-2 rounded border p-2 text-xs', style: { borderColor: GOOD } },
          h('div', { className: 'font-medium' }, `Publish ${ready.length} item(s) in this order: ${ready.map((x) => x.row.id).join(' → ')}?`),
          h('div', { style: sub }, 'Each runs cockpit publish as you, one after the other; it stops at the first refusal. The sha is re-checked before anything leaves.'),
          h('div', { className: 'flex items-center gap-1.5' }, h('button', { type: 'button', disabled: busy, onClick: publishAll, className: 'rounded px-2.5 py-0.5 text-xs font-medium', style: { background: GOOD, color: '#fff' } }, busy ? 'working' : 'Publish now'), btn('Cancel', () => setAsk(false))))
      : h('div', null, h('button', { type: 'button', onClick: () => setAsk(true), className: 'rounded px-2.5 py-0.5 text-xs font-medium', style: { background: GOOD, color: '#fff' } }, `✓ Publish ${ready.length} in order (${ready.map((x) => x.row.type).join(' → ')})`)))
      : h('div', { style: sub }, 'Nothing on this PR is ready to publish yet: open an item for its own action.'),
    h(TicketTools, { ticket, part: 'demo' }))
}
// the one step an item of a PR group offers on its own line: the posted review's publish, a held item's decision
function memberStep(x) {
  const r = x.row || {}
  if (r.type === 'pr-review-submit' && r.status === 'posted') return { step: 'publish-review', label: '✓ Publish review…', color: GOOD, title: 'stage 2: submit the pending review with the verdict and a summary you confirm (or discard it) on its own pane' }
  if (r.status === 'held') return { step: 'decide', label: 'Decide…', color: 'var(--ui-warning, #c98a00)', title: 'the gatekeeper holds it with one question for you: answer it on its own pane' }
  return null
}
// "Open" = waiting at the gate, plus a published push whose CI is still running or failed and not yet handled (it is not over until CI is)
const stillOpen = (r) => OPEN.has(r.status) || (r.status === 'published' && (r.type === 'push-branch' || r.type === 'pr-patch-apply') && r.ci && (r.ci.state === 'running' || (r.ci.state === 'failed' && !r.ci.handled)))
const DAY = 86400000
const GROUPS = [['flight', 'In flight', 'at the gate or in the pipeline: the gatekeeper\'s, a lane\'s, or publishing with the row it follows — not yours yet'],
  ['advisories', 'Advisories', 'every advisory the stack watch knows, the backlog included — the alerts are your rows above; a 🤖 pill means a bump PR already covers it'],
  ['published', 'Published today', 'what left the machine in the last 24 h; search for older ones'], ['dropped', 'Dropped', '']]
// the row of an Inbox item: the Outbox's columns — the type (and its skills mark, PR, CI when an intent is behind it), the action as the status
function itemRow(it, selected, onClick, compact) {
  const r = it.row || (it.group && it.group.members[0].row) || null
  const kind = it.group ? it.group.members.map((x) => x.row.type).filter((v, k, a) => a.indexOf(v) === k).join(' + ') : it.card ? `card · ${it.card.assignee}` : it.rereview ? 'pr-review' : it.watcher ? 'watcher' : it.bumps ? 'dependency' : r ? r.type : ''
  return trow(compact ? COMPACT_COLS : OUTBOX_COLS, { key: it.key, onClick, selected, children: pickCells([
    h('div', { key: 't', className: 'truncate font-medium' }, it.ticket),
    r && !it.group ? typeCell(r) : h('div', { key: 'ty', className: 'whitespace-nowrap overflow-hidden font-medium', style: { color: r ? typeColor(r.type) : it.color } }, kind),
    h('div', { key: 'tg', className: 'truncate', title: it.what }, it.what),
    h('div', { key: 'r', style: { color: riskColor(r && r.risk) } }, r && r.risk ? r.risk : '–'),
    h('div', { key: 's', className: 'truncate font-medium', style: { color: it.color }, title: it.icon + ' ' + it.action }, `${it.icon} ${it.action}`),
    prCell(r), ciCell(r),
    h('div', { key: 'a', className: 'truncate text-right', style: sub }, it.ts ? ago(it.ts) : '')], compact) })
}
// the open dependency-bot PRs cockpit bumps found: pick the batch, Start runs the organize-bumps skill on a reviewer card; Dismiss hides a PR until its head moves
function BumpsPanel({ repo, prs, onDone, release }) {
  const hints = useHints()
  const [chosen, setChosen] = useState(prs.map((p) => p.number)); const [note, setNote] = useState(''); const [busy, setBusy] = useState(false)
  const act = async (path, body, msg) => { setBusy(true); try { const r = await post(path, body); host.notify({ kind: 'success', title: msg, message: r.out }); onDone() } catch (e) { host.notifyError(e, 'failed') } finally { setBusy(false) } }
  return h('div', { className: 'flex flex-col gap-3 p-3 text-xs' },
    detailHead(`${repo} · dependency bumps`, { text: `${prs.length} open bump PR(s)`, color: 'var(--ui-accent)' }, 'found by cockpit bumps, read-only'),
    h('div', { className: 'flex flex-wrap items-center gap-1' }, ...prs.map((p) => h('button', { key: p.number, type: 'button', onClick: () => openWeb(p.url), title: `${p.title}\n${p.url}`, className: 'rounded border px-2 py-0.5 text-xs whitespace-nowrap', style: { borderColor: stroke } }, `#${p.number} ↗ `, h('span', { style: sub }, p.title.length > 48 ? p.title.slice(0, 47) + '…' : p.title)))),
    h('div', { style: sub }, hints.bumps_start),
    h('div', { className: 'flex flex-col gap-1' }, ...prs.map((p) => h('label', { key: p.number, className: 'flex items-center gap-2' },
      h('input', { type: 'checkbox', checked: chosen.includes(p.number), onChange: (e) => setChosen(e.target.checked ? [...chosen, p.number] : chosen.filter((n) => n !== p.number)) }),
      h('a', { href: p.url, onClick: (e) => { e.preventDefault(); openWeb(p.url) }, style: mono }, `#${p.number}`), h('span', null, p.title), h('span', { style: sub }, p.head)))),
    h(ClearableTextarea, { value: note, onChange: (e) => setNote(e.target.value), rows: 2, placeholder: 'optional: a note for the lane (skip the major bump, …)', className: 'rounded border bg-transparent px-1.5 py-1', style: { borderColor: stroke } }),
    h('div', { className: 'flex gap-1.5' },
      release ? btn('Release selected', () => act('/bumps-release', { repo, numbers: chosen }, `${repo}: released`),
        { title: 'return the selected pull requests to the candidates', disabled: busy || !chosen.length }) : h('button',
        { type: 'button', disabled: busy || !chosen.length, onClick: () => act('/kickoff', { mode: 'bumps', repo, prs: chosen, prompt: note },
        `${repo}: bumps started`), className: 'rounded px-2.5 py-0.5 text-xs font-medium disabled:opacity-40',
        style: { background: 'var(--ui-accent)', color: '#fff' } }, busy ? 'working' : `Start ${chosen.length} PR(s)`),
      release ? null : btn('Dismiss selected', () => act('/bumps-dismiss', { repo, numbers: chosen }, `${repo}: dismissed`), { title: 'hidden until the PR\'s head moves (a new bump)', disabled: busy || !chosen.length })))
}
// the day's standup note: the cron's draft, editable; Update drafts again from the records, Confirm sends it (the human's act)
function StandupPanel({ d, onDone }) {
  const [text, setText] = useState(d.note || d.draft || ''); const [busy, setBusy] = useState(false)
  useEffect(() => { setText(d.note || d.draft || '') }, [d.day, d.drafted_at, d.note, d.draft])
  const act = async (path, body, msg) => { setBusy(true); try { const r = await post(path, body); host.notify({ kind: 'success', title: msg, message: r.out }); onDone() } catch (e) { host.notifyError(e, 'standup failed') } finally { setBusy(false) } }
  return h('div', { className: 'flex h-full min-h-0 flex-col gap-2 p-3 text-xs' },
    detailHead(`standup · ${d.day}`, { text: `${d.items} item(s) · draft`, color: 'var(--ui-accent)' }, `since ${(d.since || '').replace('T', ' ').slice(0, 16)} · drafted ${d.drafted_at ? ago(d.drafted_at) + ' ago' : ''}`),
    h('div', { style: sub }, `What left the machine since ${(d.since || '').replace('T', ' ').slice(0, 16) || 'the window start'}, from the outbox receipts, the PR watch and the test runs. Edit freely; Update rebuilds it from the records (your edits go); Confirm sends exactly this text.`),
    h(Section, { title: 'Preview', open: true }, h(RichMd, { html: d.markdown_html || '' })),
    h(ClearableTextarea, { value: text, onChange: (e) => setText(e.target.value), rows: 12, className: 'w-full rounded border bg-transparent px-2 py-1.5 text-xs', style: { borderColor: stroke, resize: 'vertical', fontFamily: 'var(--ui-font-mono, ui-monospace, Menlo, monospace)' } }),
    h('div', { className: 'flex items-center gap-2' },
      h('button', { type: 'button', disabled: busy || !text.trim(), onClick: () => act('/standup-confirm', { day: d.day, text }, 'standup sent'),
        className: 'rounded px-3 py-1 text-xs font-medium disabled:opacity-40', style: { background: 'var(--ui-success, #2a9d5c)', color: '#fff' },
        title: 'sends this text through the pack notify command and closes the row' }, busy ? 'working' : 'Confirm & send'),
      btn('Update', () => act('/standup-update', {}, 'standup drafted again'), { title: 'draft again from the records, up to this minute (edits are lost)', disabled: busy })))
}
// a gate's refusal nobody resolved (cockpitlib.refusals): the reason, the card that ended with it, Send back to its lane or Dismiss
function RefusalPanel({ r, onDone }) {
  const [note, setNote] = useState(''); const [busy, setBusy] = useState(false)
  const act = async (path, msg) => { setBusy(true); try { const x = await post(path, { key: r.key, note }); host.notify({ kind: 'success', title: msg, message: x.out }); onDone() } catch (e) { host.notifyError(e, msg + ' failed') } finally { setBusy(false) } }
  return h('div', { className: 'flex flex-col gap-2 p-3 text-xs' },
    detailHead(`${r.ticket} · ${r.type} refused`, { text: 'refused · nothing went out', color: 'var(--ui-danger, #d33)' }, r.time),
    r.reason_html ? h(RichMd, { className: 'rounded border px-2 py-1.5', style: { borderColor: 'var(--ui-danger, #d33)' }, html: r.reason_html })
      : h('div', { className: 'rounded border px-2 py-1.5 whitespace-pre-wrap', style: { borderColor: 'var(--ui-danger, #d33)' } }, r.reason),
    h('div', { style: sub }, `${r.card_lane || r.lane} tried it on card ${r.card || '?'} (${r.card_title || '?'}), which ended ${r.card_status || ''} without fixing it${r.intent ? `; intent ${r.intent}` : ''}. Nothing reached the forge or tracker.`),
    h(ClearableTextarea, { value: note, onChange: (e) => setNote(e.target.value), rows: 3, placeholder: 'optional: your decision or a hint for the lane', className: 'w-full rounded border bg-transparent px-2 py-1 text-xs', style: { borderColor: stroke } }),
    h('div', { className: 'flex items-center gap-2' },
      h('button', { type: 'button', disabled: busy, onClick: () => act('/refusal-send-back', `${r.ticket}: sent back`),
        className: 'rounded px-3 py-1 text-xs font-medium disabled:opacity-40', style: { background: 'var(--ui-accent)', color: '#fff' },
        title: 'a card to the same kind of lane with the refusal and your note: it fixes the cause and makes the act again, or asks you one question' },
        'Send back to the lane'),
      btn('Dismiss', () => act('/refusal-dismiss', `${r.ticket}: dismissed`), { disabled: busy, title: 'it is fine as it is: the row leaves (a new refusal brings it back)' })))
}
// card: the blocked card that asked, when the board row is known (its ❓ row is folded into this one); openCard opens that
// card's own pane, for an answer that is neither approve nor deny
function PrivilegedPanel({ row, onDone, card = null, openCard = null }) {
  const [busy, setBusy] = useState(false)
  const act = async (path) => {
    if (busy) return
    setBusy(true)
    try {
      const r = await post(path, { card: row.card || '', lane: row.lane || '' })
      host.notify({ kind: 'success', title: row.card || 'privileged login', message: r.out })
      onDone()
    } catch (e) { host.notifyError(e, 'privileged login') } finally { setBusy(false) }
  }
  return h('div', { className: 'flex flex-col gap-2 p-3 text-xs' },
    detailHead(card ? `${card.ticket || row.card} · ${card.assignee}` : row.card || 'privileged login', { text: 'needs a decision', color: 'var(--ui-warning, #c98a00)' }, row.summary || ''),
    h('div', { className: 'whitespace-pre-wrap' }, row.reason || ''),
    card ? h('div', { style: sub }, `The card ${card.id} is blocked on this request. Approve lends the login for the step named and resumes the card; Deny leaves the card blocked with your refusal.`) : null,
    h('div', { className: 'flex flex-wrap items-center gap-2' },
      h('button', { type: 'button', disabled: busy, onClick: () => act('/privileged-approve'), className: 'rounded px-3 py-1 text-xs font-medium disabled:opacity-40', style: { background: 'var(--ui-success, #2a9d5c)', color: '#fff' } }, 'Approve this step'),
      h('button', { type: 'button', disabled: busy, onClick: () => act('/privileged-deny'), className: 'rounded px-3 py-1 text-xs font-medium disabled:opacity-40', style: { background: 'var(--ui-danger, #d33)', color: '#fff' } }, 'Deny'),
      openCard ? btn('Answer the card instead', openCard, { title: 'the card\'s own pane: a free answer, stop, or archive' }) : null))
}
// a finished question card (the analyst): its summary and the files it wrote are the answer, a row until you use it or dismiss it
// (cockpitlib.answers). Reopen with this is one click: the same /reopen-flow the ticket-done row's form posts, with the answer as
// the prompt and its files as the evidence; "edit first" opens that form prefilled instead.
const TICKET_KEY = /^[A-Z][A-Z0-9]*(-[A-Z0-9]+)+$/
// a tracker comment that arrived, or was edited, while the ticket's "done, confirm?" row waited (cockpitlib.tracker_watch):
// one-time information with a Dismiss; nothing follows from it
function TrackerNotePanel({ n, onDone }) {
  const [busy, setBusy] = useState(false)
  const word = useTrackerWord(); const place = word === 'Jira' ? 'Jira' : 'tracker'
  const dismiss = async () => {
    if (busy) return; setBusy(true)
    try { const r = await post('/tracker-note-dismiss', { id: n.id }); host.notify({ kind: 'info', title: `${n.ticket}: note dismissed`, message: r.out || '' }); onDone() }
    catch (e) { host.notifyError(e, 'dismiss failed') } finally { setBusy(false) }
  }
  return h('div', { className: 'flex h-full min-h-0 flex-col gap-2 overflow-auto p-3 text-xs', 'data-tracker-note': n.id },
    detailHead(`${n.ticket} · ${word} comment ${n.kind === 'edited' ? 'edited' : 'added'}`, { text: 'for your information', color: 'var(--ui-accent)' }, `${n.author || 'someone'}${n.at ? ' · ' + ago(n.at) + ' ago' : ''}`),
    h('div', { style: sub }, `${n.kind === 'edited' ? 'An existing comment was edited' : 'A comment was added'} while the ticket's done row waited for you. Nothing runs on it; read it, then dismiss.`),
    h('div', { className: 'rounded-md border px-3 py-2', style: { borderColor: 'var(--ui-accent)', background: 'rgba(56,139,253,.06)' } },
      n.text_html ? h(RichMd, { html: n.text_html, className: 'leading-relaxed' }) : h('div', { className: 'whitespace-pre-wrap' }, n.text || '')),
    h('div', { className: 'flex items-center gap-2' },
      n.url ? btn(`Open in ${place}`, () => openWeb(n.url), { accent: true, title: n.url }) : null,
      n.url ? copyBtn(n.url, `${place} link`) : null,
      h('button', { type: 'button', disabled: busy, onClick: dismiss, className: 'rounded px-3 py-1 text-xs font-medium disabled:opacity-40', style: { background: 'var(--ui-accent)', color: '#fff' } }, busy ? 'working' : 'Dismiss')))
}
function AnswerPanel({ a, onDone }) {
  const [busy, setBusy] = useState(false); const [ask, setAsk] = useState(a.followup_text || ''); const [edit, setEdit] = useState(false); const [kickTicket, setKickTicket] = useState(a.ticket || '')
  const qc = useQueryClient()
  const refs = a.references || []; const paths = refs.map((f) => f.rel || f.path); const prompt = a.reopen_prompt || a.summary || ''
  const act = async (fn, done) => { if (busy) return; setBusy(true); try { const r = await fn(); host.notify({ kind: 'success', title: `${a.ticket}: ${done}`, message: (r && r.out) || '' }); qc.invalidateQueries({ queryKey: ['cockpit'] }); onDone() } catch (e) { host.notifyError(e, `${done} failed`) } finally { setBusy(false) } }
  const primary = (label, onClick, extra = {}) => h('button', { type: 'button', disabled: busy || extra.disabled, onClick, title: extra.title || '', className: 'rounded px-3 py-1 text-xs font-medium disabled:opacity-40', style: { background: extra.bg || 'var(--ui-accent)', color: '#fff' } }, label)
  const key = kickTicket.trim().toUpperCase()
  return h('div', { className: 'flex h-full min-h-0 flex-col gap-2 overflow-auto p-3 text-xs', 'data-answer': a.card },
    detailHead(`${a.ticket} · ${a.lane || a.mode} answered`, { text: 'answer · use it or dismiss', color: 'var(--ui-accent)' }, a.card),
    a.follows ? h('div', { style: sub }, `follow-up to card ${a.follows}`) : null,
    h('div', { className: 'rounded-md border px-3 py-2', style: { borderColor: 'var(--ui-accent)', background: 'rgba(56,139,253,.06)' } },
      h('div', { className: 'cockpit-head mb-1' }, 'the answer'),
      a.summary_html ? h(RichMd, { html: a.summary_html, className: 'leading-relaxed' }) : h('div', { style: sub }, 'the card ended without a summary; the files below are the answer')),
    refs.length ? h('div', { className: 'flex flex-col gap-1' }, h('div', { className: 'cockpit-head' }, `References (${refs.length})`),
      h('div', { className: 'flex flex-wrap gap-1' }, ...refs.map((f) => h('span',
        { key: f.path, className: 'flex items-center gap-1 rounded border px-1',
        style: { borderColor: stroke, ...(f.shared ? { borderStyle: 'dashed' } : {}) },
        title: f.shared ? `${f.rel || f.path} · the ticket's file: a later card rewrote it, so it is listed here as shared` : (f.rel || f.path),
        'data-shared': f.shared ? '1' : undefined },
        h('button', { type: 'button', onClick: () => openFile(f.path), style: { color: 'var(--ui-accent)' } }, f.name), f.shared ? h('span', { style: sub }, 'shared') : null, copyBtn(f.rel || f.path, 'path')))))
      : h('div', { style: sub }, 'no file under qa/ was written by this card'),
    a.report_html ? h(Section, { title: `Report · ${a.report_name || ''}` }, h(RichMd, { html: a.report_html, className: 'leading-relaxed' })) : null,
    h('div', { className: 'flex flex-wrap items-center gap-2' },
      primary('Reopen with this', () => act(() => post('/reopen-flow', { ticket: a.ticket, prompt, evidence: paths, from_answer: a.card }), 'reopened'), { title: 'intake reads the answer and its files, proposes, and waits for your go; the ticket-done row, if any, leaves' }),
      h('a', { href: '#', onClick: (e) => { e.preventDefault(); setEdit(!edit) }, style: sub }, edit ? 'close the form' : 'edit first'),
      (a.rework_repos || []).length ? primary('Rework with this', () => act(() => post('/kickoff', { ticket: a.ticket, mode: 'rework', prompt, repos: a.rework_repos, evidence: paths, from_answer: a.card }), 'rework queued'), { bg: 'var(--ui-warning, #c98a00)', title: `straight to the worker on ${a.rework_repos.join(', ')}, with a tester and a reviewer behind it` }) : null,
      btn('Dismiss', () => act(() => post('/answer-dismiss', { card: a.card }), 'answer dismissed'), { disabled: busy, title: 'read; the row leaves (the card stays on the Board)' })),
    edit ? h(ReopenForm, { ticket: a.ticket, initial: { prompt, files: refs.map((f) => ({ name: f.name, path: f.rel || f.path })), from_answer: a.card }, onDone: () => { setEdit(false); onDone() } }) : null,
    h('div', { className: 'flex items-center gap-2' },
      h('input', { value: kickTicket, onChange: (e) => setKickTicket(e.target.value), placeholder: 'TASK-1', className: 'w-32 rounded border bg-transparent px-1.5 py-0.5', style: { ...mono, borderColor: stroke } }),
      btn('Kick off with this', () => act(() => post('/kickoff', { ticket: key, mode: 'intake', prompt, evidence: paths, from_answer: a.card }), `${key} → intake`), { disabled: busy || !TICKET_KEY.test(key), title: 'intake on this ticket, or another one, with the answer and its files as the evidence' })),
    h('div', { className: 'flex flex-col gap-1 rounded-md border px-3 py-2', style: { borderColor: stroke } },
      h('div', { className: 'cockpit-head' }, 'ask a follow-up (a patch plan is the preset)'),
      h(ClearableTextarea, { value: ask, onChange: (e) => setAsk(e.target.value), rows: 4, className: 'w-full rounded border bg-transparent px-2 py-1 text-xs', style: { borderColor: stroke, resize: 'vertical' } }),
      h('div', { className: 'flex items-center gap-2' }, primary('Ask for a patch plan', () => act(() => post('/answer-followup', { card: a.card, prompt: ask }), 'follow-up asked'), { disabled: !ask.trim(), title: 'a new card of the same lane with the references; its answer comes back here as a row of its own' }))))
}
function Inbox({ rows, refresh, openAll }) {
  const word = useTrackerWord()
  const q = useQuery({ queryKey: ['cockpit', 'needs-you'], queryFn: () => CTX.rest('/needs-you'), refetchInterval: POLL_MS, retry: 1 })
  const bq = useQuery({ queryKey: ['cockpit', 'bumps'], queryFn: () => CTX.rest('/bumps'), refetchInterval: POLL_MS * 6, retry: 0 })
  const rfq = useQuery({ queryKey: ['cockpit', 'refusals'], queryFn: () => CTX.rest('/refusals'), refetchInterval: POLL_MS * 2, retry: 0 })
  const aq = useQuery({ queryKey: ['cockpit', 'advisories'], queryFn: () => CTX.rest('/advisories'), refetchInterval: POLL_MS * 6, retry: 0 })
  const stq = useQuery({ queryKey: ['cockpit', 'standup'], queryFn: () => CTX.rest('/standup'), refetchInterval: POLL_MS * 6, retry: 0 })
  const sq = useQuery({ queryKey: ['cockpit', 'sweep-state'], queryFn: () => CTX.rest('/sweep-state'), refetchInterval: POLL_MS, retry: 1 }); const sweep = sq.data
  const [sel, setSel] = useState(null)
  const [open, setOpenRaw] = useState(() => (openAll ? { flight: true, advisories: true, published: true, dropped: true } : CTX.storage.get('groups1', {})))
  const setOpen = (g, v) => { const n = { ...open, [g]: v }; setOpenRaw(n); CTX.storage.set('groups1', n) }
  const [search, setSearch] = useState('')
  // security advisories are noisy: their rows and their group show only while the box at the top is ticked (kept per viewer)
  const [security, setSecurityRaw] = useState(() => Boolean(CTX.storage.get('showSecurity', false)))
  const setSecurity = (v) => { setSecurityRaw(v); CTX.storage.set('showSecurity', v) }
  const alerts = ((aq.data && aq.data.advisories) || []).filter(alertable)
  const cards = (q.data && q.data.cards) || []
  const items = []
  // a card blocked on a privileged-login request is one row, the 🔑 one below (approve or deny): its ❓ row said the same
  // thing a second time, and the human who only wanted to lend the login had two rows for one decision
  const privileged = (q.data && q.data.privileged) || []
  const lendAsked = new Set(privileged.map((p) => p.card).filter(Boolean))
  for (const c of cards.filter((x) => (x.status === 'blocked' || x.status === 'triage') && !x.waits_publish && !lendAsked.has(x.id) && !(notReady(x) && !x.parked && Date.now() / 1000 - (x.blocked_at || 0) < SEND_BACK_GRACE_S))) items.push({ key: 'b' + c.id,
    icon: '❓', ticket: c.ticket || '', what: `${c.assignee}${c.status === 'triage' ? ' (asked twice)' : ''} asks: ${(c.question || c.block_reason || c.title).replace(/\s+/g, ' ').slice(0, 140)}`,
    action: notReady(c) ? 'send back' : credentialAsk(c.question) ? 'staging login' : 'answer',
    ts: c.created_at ? new Date(c.created_at * 1000).toISOString() : null, color: 'var(--ui-warning, #c98a00)', card: c })
  // a finished question card: the answer and its files, until you use them (reopen, rework, kick off) or dismiss the row
  for (const a of (q.data && q.data.answers) || []) items.push({ key: 'ans' + a.card, icon: '💡', ticket: a.ticket || '', what: `${a.lane || a.mode || 'the analyst'} answered: ${(a.summary || (a.references || []).map((f) => f.name).join(', ') || a.title || '').replace(/\s+/g, ' ').slice(0, 140)}`, action: 'use answer', ts: a.completed || null, color: 'var(--ui-accent)', answer: a })
  // a tracker comment added or edited while a ticket's done row waits: read and dismiss
  for (const n of (q.data && q.data.tracker_notes) || []) items.push({ key: 'tn' + n.id, icon: '💬', ticket: n.ticket || '', what: `${word} comment ${n.kind === 'edited' ? 'edited' : 'added'} by ${n.author || 'someone'} while the done row waits: ${(n.text || '').replace(/\s+/g, ' ').slice(0, 140)}`, action: 'read', ts: n.at || null, color: 'var(--ui-accent)', note: n })
  const seenPr = new Set(); const seenCi = new Set()
  for (const r of rows) {
    // step 1 of a chain publishes with the intent that follows it: one row for the pair, unless step 1 itself waits for you
    // (a hold of yours, a question among them, or a posted review): then it is your row, or its question would only show in In flight
    const stepOneNeedsYou = (r.status === 'held' && !(r.hold && r.hold.waits === 'lane')) || r.status === 'posted'
    if (r.chain && r.chain.followed_by && !stepOneNeedsYou) continue
    // both steps endorsed: the second one's Publish sends both, so step 1 is no row of its own. It stays a row when the
    // second one is not offered itself (a later stage, a head that moved): then step 1 is what can leave.
    const second = r.chain && r.chain.pair ? rows.find((x) => x.id === r.chain.pair) : null
    if (second && second.status === 'endorsed' && !second.waits && !second.stale_head && !stepOneNeedsYou) continue
    const stepReady = !(r.chain && r.chain.role === 'content') || r.chain.step1_status === 'endorsed' || String(r.chain.step1_status).startsWith('published')
    const reasons = []
    if (r.type === 'ticket-done' && r.status === 'pending') reasons.push({ icon: '🏁', text: 'PR merged, nothing open — confirm done or reopen', action: 'confirm done', ts: r.created_at, color: 'var(--ui-accent)' })
    if (r.stale_head) reasons.push({ icon: '↻', text: `PR head moved after this review was written (${r.stale_head.reviewed} → ${r.stale_head.now}): publish would mis-anchor — re-review at the new head`, action: 're-review', ts: r.endorsed ? r.endorsed.time : r.created_at, color: 'var(--ui-warning, #c98a00)' })
    else if (r.type === 'infra-note') {
      // a note with a patch is yours to apply whatever the gate said of it; a note without one is read in its pane.
      // Once applied (or dropped) it has left: it stayed a row with "apply it" after its patch was committed and pushed
      if (OPEN.has(r.status) && r.payload && r.payload.repo && r.payload.branch && r.payload.patch_file) reasons.push({ icon: '🩹', text: `${r.created_by || 'a lane'} left a patch it may not write itself (${r.payload.patch_file.split('/').pop()}) — apply it as your commit`, action: 'apply patch', ts: r.created_at, color: 'var(--ui-accent)' })
    }
    else if (r.status === 'endorsed' && r.type !== 'ticket-done' && stepReady && !r.waits) reasons.push({ icon: '✓', text: `endorsed by ${endorserOf(r)}${r.endorsed && r.endorsed.notes ? ': ' + r.endorsed.notes.slice(0, 90) : ''}`, action: 'publish', ts: r.endorsed ? r.endorsed.time : r.created_at, color: 'var(--ui-success, #2a9d5c)' })
    if (r.status === 'posted') reasons.push({ icon: '◔', text: `pending review on the forge (${r.review && r.review.proposed_event ? r.review.proposed_event : 'verdict'}) — look at the PR page, then publish or discard`, action: 'publish review', ts: r.review && r.review.posted_at, color: 'var(--ui-warning, #c98a00)' })
    // a hold that only asks for your confirmation, on a stage whose stage before is not out yet, is not yours yet either:
    // it arrives in its turn, as an endorsed later stage does (a question is yours whenever it is asked)
    const heldInTurn = !(r.waits && !(r.hold && r.hold.ask))
    if (r.status === 'held' && !(r.hold && r.hold.waits === 'lane') && heldInTurn) reasons.push({ icon: '⏸', text: r.hold && r.hold.ask ? `the gatekeeper asks: ${r.hold.ask.slice(0, 160)}` : `held by the gatekeeper: ${(r.hold && r.hold.reason || '').slice(0, 120)}`, action: r.hold && r.hold.ask ? 'decide' : 'resolve hold', ts: r.hold && r.hold.time, color: 'var(--ui-warning, #c98a00)' })
    // a pending intent is the gatekeeper's work, not yours: it sits under "In flight" and arrives here once endorsed or held
    // PR comments and CI belong to the PR, not to each intent: report them once per PR / sha
    if (r.ci && r.ci.state === 'failed' && !r.ci.handled && !r.ci.analysing && !seenCi.has(r.ticket + r.ci.sha)) { seenCi.add(r.ticket + r.ci.sha); reasons.push({ icon: '✗', text: `CI failed on ${r.ci.branch} @ ${r.ci.sha}: ${r.ci.summary} — no analyst card could be created; dismiss or diagnose by hand`, action: 'diagnose', ts: r.ci.last_check, color: 'var(--ui-danger, #d33)' }) }
    const reviewer = r.pr && r.pr.role === 'reviewer'
    if (r.pr && !reviewer && !r.pr.merged && r.pr.approvals && r.pr.approvals.length && !seenPr.has('appr' + r.ticket + r.pr.number)) { seenPr.add('appr' + r.ticket + r.pr.number); reasons.push({ icon: '👍',
      text: `PR #${r.pr.number} approved by ${r.pr.approvals.map((a) => a.author).join(', ')} — merge when you are ready; the final ack follows the merge`,
      action: 'merge', ts: r.pr.approvals[r.pr.approvals.length - 1].at, color: 'var(--ui-success, #2a9d5c)' }) }
    if (r.pr && r.pr.new_count && !seenPr.has(r.ticket + r.pr.number)) { seenPr.add(r.ticket + r.pr.number)
      if (reviewer) { /* feeds the standing review-in-progress item; no separate row */ }
      else reasons.push({ icon: '💬', text: `${r.pr.new_count} new PR comment(s) on #${r.pr.number} since the pipeline's pass`, action: 'treat comments', ts: r.pr.new[0] && r.pr.new[0].at, color: 'var(--ui-warning, #c98a00)' }) }
    if (!reasons.length) continue
    const first = reasons[0]
    items.push({ key: 'i' + r.id, icon: reasons.map((x) => x.icon).join(''), ticket: r.ticket,
      what: `${r.target}${r.payload && r.payload.rebase_only ? ' ⟳ REBASE ONLY' : r.payload && r.payload.after ? ' → after ' + afterShort(r.payload.after) : ''} — ` + reasons.map((x) => x.text).join(' · '),
      action: reasons.map((x) => x.action).join(' / '), ts: reasons.map((x) => x.ts || '').sort().pop(), color: first.color, intent: r.id, row: r,
      decide: reasons.some((x) => x.action === 'decide') ? r : null })
  }
  const doneFirst = (it) => (/confirm done/.test(it.action || '') ? 0 : 1)   // the final ack always sits on top
  items.splice(0, items.length, ...groupByPr(items))   // one row per PR
  items.sort((a, b) => doneFirst(a) - doneFirst(b) || (b.ts || '').localeCompare(a.ts || ''))
  const running = cards.filter((c) => ['in_progress', 'running', 'claimed', 'review'].includes(c.status))
  // PRs you review that are still open and not approved by you stay in the Inbox as a standing item with a re-review door
  const seenRr = new Set(); const openCards = new Set(cards.map((c) => c.id))   // needs-you lists only cards still open
  for (const r of rows) for (const p of (r.halted ? [] : r.prs || [])) {   // a halted ticket's review is not in progress: its standing row goes with the halt
    if (p.role !== 'reviewer' || p.merged || p.state !== 'open' || p.my_review_state === 'APPROVED' || seenRr.has(r.ticket + p.number)) continue
    if (p.rereview && openCards.has(p.rereview.card)) { seenRr.add(r.ticket + p.number); continue }   // re-review running: its result comes back as a review intent
    if (rows.some((x) => x.ticket === r.ticket && x.type === 'pr-review-submit' && OPEN.has(x.status) && x.payload && String(x.payload.number) === String(p.number))) { seenRr.add(r.ticket + p.number); continue }   // a review of yours for this PR is waiting at the gate: that row is the action
    seenRr.add(r.ticket + p.number)
    const mt = p.my_threads || {}; const sr = p.since_review || {}
    const quiet = p.last_activity ? (Date.now() - toMs(p.last_activity)) / 60000 : null
    const ready = p.rereview_ready !== undefined ? Boolean(p.rereview_ready) : p.re_requested || (mt.total && mt.resolved === mt.total) || (quiet != null && quiet > 120 && (mt.replied || sr.commits))   // cockpit watch-pr.rereview_ready, the one rule; older states: the same rule here
    if (!ready && !(mt.replied || sr.commits || p.re_requested)) continue   // nothing moved since your review: nothing to look at yet
    items.push({ key: 'rr' + r.ticket + p.number, icon: '🔎', ticket: r.ticket,
      what: `review in progress: ${p.repo} #${p.number} by ${r.pr && r.pr.author || 'the author'} — ${mt.resolved || 0}/${mt.total || 0} of your threads resolved, ${mt.replied || 0} replied${
        sr.commits ? `, ${sr.commits} commit(s) since your review` : ', nothing pushed since'}${
        p.last_activity ? ` · last activity ${ago(p.last_activity)} ago` : ''}${
        p.re_requested ? ' · AUTHOR RE-REQUESTED YOUR REVIEW' : ''}${
        ready ? '' : ' · the author is still on it: the re-review starts by itself after two quiet hours'}`,
      action: 're-review', ts: p.last_activity || null, color: ready ? 'var(--ui-accent)' : 'var(--ui-text-tertiary)', rereview: { ticket: r.ticket, pr: p } })
  }
  for (const r of (rfq.data && rfq.data.refusals) || []) items.push({ key: 'rf' + r.key, icon: '⛔', ticket: r.ticket, what: `${r.type} refused for ${r.ticket} and nothing fixed it: ${r.reason}`, action: 'refused', ts: r.time, color: 'var(--ui-danger, #d33)', refusal: r })
  const su = stq.data || {}
  if (su.day && su.status === 'draft') items.push({ key: 'standup' + su.day, icon: '📝', ticket: 'standup', what: `standup note for ${su.day}: ${su.items} item(s) since ${(su.since || '').replace('T', ' ').slice(5, 16)} — review, then Confirm sends it`, action: 'confirm standup', ts: su.drafted_at, color: 'var(--ui-accent)', standup: su })
  for (const [repo, prs] of Object.entries((bq.data && bq.data.repos) || {})) { if (!prs || !prs.length) continue; items.push({ key: 'bumps' + repo, icon: '📦', ticket: 'bumps', what: `${repo}: ${prs.length} open bump PR(s) — ${prs.map((p) => `#${p.number} ${p.title}`).join(' · ')}`, action: 'start bumps', ts: bq.data.time, color: 'var(--ui-accent)', bumps: { repo, prs } }) }
  for (const [repo, prs] of Object.entries((bq.data && bq.data.started) || {})) { if (!prs || !prs.length) continue; items.push({ key: 'bumpheld' + repo, icon: '📦', ticket: 'bumps', what: `${repo}: ${prs.length} bump PR(s) in progress — release returns them to the candidates`, action: 'release bumps', ts: bq.data.time, color: 'var(--ui-accent)', bumps: { repo, prs, release: true } }) }
  // the row says why in plain words (cockpitlib.health reads the run's output); the pane keeps the raw output behind a fold
  // a stack advisory the watch alerts on: an acknowledged one never comes back here; the Platform tab keeps it
  for (const a of security ? alerts : []) items.push({ key: 'adv' + a.id, icon: '🛡', ticket: 'platform', what: advisoryWhat(a), action: 'advisory', ts: a.last_seen, color: severityColor(a), advisory: a })
  // a plugin's PR it is done with (a release that reached handoff): merge it when you are ready, as its approved PR
  // says; its tickets' ticket-done ack follows the merge
  for (const m of ((q.data && q.data.merge_ready) || [])) items.push({ key: `merge:${m.repo}#${m.number}`, icon: '👍', ticket: m.tickets[0] || 'platform',
    what: `${m.repo.split('.')[0]} #${m.number} is ready to merge (${m.tickets.join(', ')}) — merge when you are ready; the final ack follows the merge`,
    action: 'merge', ts: '', color: 'var(--ui-success, #2a9d5c)', merge: m })
  for (const w of ((q.data && q.data.watchers) || []).filter((w) => !w.ok)) items.push(w.update
    ? { key: 'w' + w.name, icon: '⬆', ticket: 'platform', what: w.reason, action: 'update', ts: '', color: 'var(--ui-accent)', watcher: w }
    : w.restart
    ? { key: 'w' + w.name, icon: '↻', ticket: 'platform', what: w.reason, action: 'restart needed', ts: w.last_error || w.last_ok, color: 'var(--ui-accent)', watcher: w }
    : { key: 'w' + w.name, icon: '⚠', ticket: 'platform', what: `watcher ${w.name}: ${w.reason || 'is not running properly'} — ${w.fails} failure(s) in a row, last success ${w.last_ok ? ago(w.last_ok) + ' ago' : 'never'}`, action: 'fix watcher', ts: w.last_error || w.last_ok, color: 'var(--ui-danger, #d33)', watcher: w })
  // the gate behind your rows: what is in flight, what left, what was dropped — the Outbox, under the to-do, collapsed
  const yours = new Set(items.flatMap((it) => it.group ? it.group.members.map((x) => x.row.id) : it.intent ? [it.intent] : []))
  const digestOrder = (a, b) => (a.type === 'ticket-done' ? 0 : 1) - (b.type === 'ticket-done' ? 0 : 1) || (a.digest_no || 999) - (b.digest_no || 999) || a.id.localeCompare(b.id)
  const leftAt = (r) => (r.receipt && r.receipt.time) || r.created_at || ''
  const flight = rows.filter((r) => !yours.has(r.id) && stillOpen(r)).sort(digestOrder)
  const published = rows.filter((r) => !yours.has(r.id) && !stillOpen(r) && r.status !== 'dropped').sort((a, b) => leftAt(b).localeCompare(leftAt(a)))   // a row of yours is only yours: never twice
  const needle = search.trim().toLowerCase()
  const shown = needle ? published.filter((r) => `${r.ticket} ${r.type} ${r.target} ${r.id}`.toLowerCase().includes(needle)) : published.filter((r) => Date.now() - new Date(leftAt(r)).getTime() < DAY)
  const dropped = rows.filter((r) => !yours.has(r.id) && r.status === 'dropped').sort((a, b) => leftAt(b).localeCompare(leftAt(a)))
  const advs = (aq.data && aq.data.advisories) || []
  const groupRows = { flight, advisories: advs, published: shown, dropped }; const counts = { flight: flight.length, advisories: advs.length, published: needle ? `${shown.length} of ${published.length}` : `${shown.length} today · ${published.length} in all`, dropped: dropped.length }
  const openIntent = (id) => setSel(sel && sel.intent === id ? null : { key: 'o' + id, intent: id })   // the detail opens; no group opens for it
  for (const p of (q.data && q.data.plugins) || []) items.push({ key: 'pl' + p.plugin + p.id, icon: p.icon || '•', ticket: p.plugin, what: p.what,
    action: p.action_label || (p.detail ? 'read' : 'open'), ts: p.at ? new Date(p.at * 1000).toISOString() : null,
    color: ROW_TONE[p.tone] || ROW_TONE.info, href: p.href || '', detail: p.detail || null, plugin: p.plugin, id: p.id, pticket: p.ticket || '',
    orphan: Boolean(p.orphan) })
  for (const p of privileged) {
    const c = cards.find((x) => x.id === p.card) || null
    items.push({ key: 'priv' + (p.card || p.reason), icon: '🔑', ticket: (c && c.ticket) || p.card || 'login', what: `${c ? c.assignee + ' asks: ' : ''}${(p.reason || 'privileged login').replace(/\s+/g, ' ').slice(0, 140)}`, action: 'approve or deny',
      ts: c && c.created_at ? new Date(c.created_at * 1000).toISOString() : null, color: 'var(--ui-warning, #c98a00)', privileged: p, lendCard: c })
  }
  // A plugin row carrying a `detail` opens a pane here instead of navigating away. A row without one
  // keeps the old path exactly, so a plugin that never sets it — or an install without that plugin —
  // behaves as it always did.
  // A plugin row can be opened from outside: `/inbox#plugin=<plugin>/<id>` selects it and its pane.
  // That is how the supervisor's grid sends a stuck cell here, instead of keeping its own copy of
  // the message. An id nothing matches leaves the list as it is.
  useEffect(() => {
    if (typeof window === 'undefined' || !window.location) return undefined
    const follow = () => {
      const asked = /(?:^|[#&])plugin=([^&]+)/.exec(window.location.hash || '')
      if (!asked) return
      let want = ''
      try { want = decodeURIComponent(asked[1]) } catch { want = asked[1] }
      const [plugin, ...rest] = want.split('/')
      const id = rest.join('/')
      const found = items.find((it) => it.plugin === plugin && it.id === id)
      if (found) setSel(found)
    }
    follow()
    if (!window.addEventListener) return undefined
    window.addEventListener('hashchange', follow)
    return () => window.removeEventListener('hashchange', follow)
  }, [items.length])
  // a plugin row with a page of its own navigates there; one with neither a page nor a detail still opens a pane (what it
  // says, and Dismiss when its plugin is gone), so no row is a dead end
  const pick = (it) => { if (it.href !== undefined && !it.card && !it.detail) { if (it.href) host.navigate(it.href); else if (it.plugin) setSel(sel && sel.key === it.key ? null : it); return } // every row that carries its own pane opens it; only an intent's row opens the intent (a merge row has none, and opening
  // "the intent" for it showed an empty pane)
  if (it.card || it.detail || it.watcher || it.rereview || it.decide || it.group || it.bumps || it.standup || it.refusal || it.privileged || it.advisory || it.answer || it.note || it.merge) setSel(sel && sel.key === it.key ? null : it); else if (it.intent) openIntent(it.intent) }
  const header = (k, title, hint) => h('div', { key: 'h' + k, onClick: () => setOpen(k, !open[k]), className: 'cockpit-group flex items-center gap-2 px-3 py-1 border-b text-xs cursor-pointer select-none', style: { borderColor: stroke, background: 'rgba(127,127,127,.06)' } },
    h('span', { style: sub }, open[k] ? '▾' : '▸'), h('span', { className: 'font-medium' }, `${title} · ${counts[k]}`), hint ? h('span', { className: 'truncate', style: sub }, hint) : null,
    k === 'published' && open[k] ? h('input', { value: search, onClick: (e) => e.stopPropagation(), onChange: (e) => setSearch(e.target.value), placeholder: 'search all published: ticket, type, target', className: 'ml-auto w-64 rounded border bg-transparent px-1.5 py-0.5', style: { borderColor: stroke } }) : null)
  // the gate sits at the bottom of the list, a gap under your rows: three collapsed groups, their rows only while open
  const compact = Boolean(sel)
  const pickAdvisory = (a) => { const it = { key: 'adv' + a.id, advisory: a }; setSel(sel && sel.key === it.key ? null : it) }
  const gate = GROUPS.filter(([k]) => security || k !== 'advisories').flatMap(([k, title, hint]) => [header(k, title, hint), ...(open[k] ? (k === 'advisories'
    ? groupRows[k].map((a) => h(AdvisoryRow, { key: 'adv' + a.id, a, selected: sel && sel.key === 'adv' + a.id, onClick: () => pickAdvisory(a) }))
    : groupRows[k].map((r) => h(Row, { key: 'o' + r.id, r, selected: sel && sel.intent === r.id, onSelect: openIntent, compact }))) : [])])
  return h('div', { className: 'flex min-h-0 flex-1 flex-col' },
    // one line over your rows: how many and what they ask (the first action of each row), then the security box
    h('div', { className: 'flex items-center gap-3 px-3 py-1 text-xs border-b', 'data-inbox-summary': items.length, style: { ...sub, borderColor: stroke } },
      h('span', null, items.length ? `${items.length} for you: ` + Object.entries(items.reduce((tally, it) => { const what = String(it.action || 'look').split(' / ')[0]; tally[what] = (tally[what] || 0) + 1; return tally }, {}))
        .sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0])).map(([what, n]) => `${n} ${what}`).join(' · ') : 'nothing for you'),
      h('label', { className: 'ml-auto flex items-center gap-1.5 cursor-pointer select-none', 'data-security-toggle': security ? 'on' : 'off' },
        h('input', { type: 'checkbox', checked: security, onChange: (e) => setSecurity(e.target.checked) }),
        `Show security advisories${alerts.length ? ` (${alerts.length} alert${alerts.length === 1 ? '' : 's'})` : ''}`)),
    running.length || (sweep && (sweep.running || sweep.requested)) ? h('div',
      { className: 'px-3 py-1 text-xs border-b', style: { ...sub, borderColor: stroke } },
      'working now: ' + [...running.map((c) => `${c.ticket || ''} ${c.assignee} (${c.status.replace('_', ' ')})`),
      ...(sweep && sweep.running ? ['gatekeeper sweep (endorsing)'] : sweep && sweep.requested ? ['gatekeeper sweep queued'] : [])].join(' · ')) : null,
    h(SplitList, { cols: compact ? COMPACT_COLS : OUTBOX_COLS, labels: compact ? LABELS.compact : LABELS.full, rows: items, selected: sel, onSelect: pick, onClose: () => setSel(null), empty: 'Nothing for you. The lanes are either working or idle.', detailWidth: '46%', footer: gate,
      renderRow: (it) => itemRow(it, sel && sel.key === it.key, () => pick(it), compact),
      detail: sel && sel.group ? h(PrGroupPanel, { g: sel.group, ticket: sel.ticket, goOutbox: openIntent, onDone: () => { refresh(); setSel(null) } })
        : sel && sel.decide ? h('div', { className: 'flex h-full min-h-0 flex-col gap-2 overflow-auto p-3' }, detailHead(`${sel.decide.ticket} · ${sel.decide.type}`, { text: 'held · your decision', color: 'var(--ui-warning, #c98a00)' }, sel.decide.id),
          h(DecidePanel, { r: sel.decide, onDone: () => { refresh(); setSel(null) } }), h(TicketTools, { ticket: sel.decide.ticket, card: intentCard(sel.decide), part: 'demo' }), h('div', null, btn('Open the intent', () => openIntent(sel.decide.id), { title: 'the full intent: Brief, what leaves, the gatekeeper check, diffs' })))
        : sel && sel.bumps ? h(BumpsPanel, { repo: sel.bumps.repo, prs: sel.bumps.prs, release: sel.bumps.release, onDone: () => { refresh(); setSel(null) } })
        : sel && sel.refusal ? h(RefusalPanel, { r: sel.refusal, onDone: () => { rfq.refetch && rfq.refetch(); refresh(); setSel(null) } })
        : sel && sel.standup ? h(StandupPanel, { d: sel.standup, onDone: () => { stq.refetch && stq.refetch(); refresh(); setSel(null) } })
        : sel && sel.rereview ? h(ReReviewPanel, { ticket: sel.rereview.ticket, pr: sel.rereview.pr, onDone: () => { refresh(); setSel(null) } })
        : sel && sel.watcher ? (sel.watcher.update ? h(UpdatePanel, { w: sel.watcher }) : h(WatcherPanel, { w: sel.watcher }))
        : sel && sel.merge ? h(MergePanel, { m: sel.merge })
        : sel && sel.advisory ? h(AdvisoryPanel, { a: sel.advisory, onDone: () => { aq.refetch && aq.refetch(); refresh(); setSel(null) } })
        : sel && sel.privileged ? h(PrivilegedPanel, { row: sel.privileged, card: sel.lendCard || null, openCard: sel.lendCard ? () => setSel({ key: 'b' + sel.lendCard.id, card: sel.lendCard }) : null, onDone: () => { q.refetch && q.refetch(); refresh(); setSel(null) } })
        : sel && sel.answer ? h(AnswerPanel, { a: sel.answer, onDone: () => { q.refetch && q.refetch(); refresh(); setSel(null) } })
        : sel && sel.note ? h(TrackerNotePanel, { n: sel.note, onDone: () => { q.refetch && q.refetch(); refresh(); setSel(null) } })
        : sel && sel.card ? h('div', { className: 'flex h-full min-h-0 flex-col gap-2 p-3' }, detailHead(sel.card.title, { text: 'blocked · needs your answer', color: 'var(--ui-warning, #c98a00)' }, sel.card.id), h(BlockedCard, { c: sel.card, refresh: () => { refresh(); setSel(null) } }))
        : sel && (sel.detail || sel.plugin) ? h(PluginPanel, { row: sel, onDone: () => { q.refetch && q.refetch(); refresh(); setSel(null) } })
        : sel && sel.intent ? h(Detail, { id: sel.intent }) : null }))
}

// a PR ready to merge: where it is, which tickets it carries, and what follows the merge
function MergePanel({ m }) {
  return h('div', { className: 'flex flex-col gap-2 p-3 text-xs' },
    detailHead(`${m.repo} #${m.number}`, { text: 'ready to merge', color: 'var(--ui-success, #2a9d5c)' }, m.plugin ? `from ${m.plugin}` : ''),
    m.title ? h('div', { className: 'font-medium' }, m.title) : null,
    h('div', null, `Tickets: ${m.tickets.join(', ')}`),
    // the link beside its button: where the desktop cannot open a browser (WSL without Windows interop), it can be pasted
    h('div', { className: 'flex items-center gap-2' }, m.url ? btn('Open the PR', () => openWeb(m.url), { accent: true, title: m.url }) : null,
      m.url ? copyBtn(m.url, 'PR link') : null),
    h('div', { style: sub }, 'Merge it on the forge when you are ready. The row leaves once the watch sees it merged; each of its tickets then gets its ticket-done row for your ack.'))
}

// a failing watcher: why, in one sentence, with the counts; the raw output (a stack trace, usually) folded under it, with a copy button
// ---------- a plugin's own message, read here instead of followed away ----------
// Generic on purpose: cockpit knows nothing about the plugin that wrote the row. The `detail` is a
// Brief, and an action is a link to follow or a request handed back to the plugin that wrote it —
// so any plugin can say what happened and offer what answers it without cockpit learning its
// vocabulary. The payload of an act is read off the row file, never taken from this page. Chat and
// Open IDE are cockpit's own doors on the row's ticket, the same ones every other pane gets.
// A row with no detail never reaches this panel.
function PluginPanel({ row, initialDone = {}, onDone = null }) {   // initialDone: tests only
  const d = row.detail || {}
  const fields = (d.fields || []).filter((f) => f && f.label)
  // Which buttons have been pressed, per row: React reuses this component when the selection moves
  // to another plugin row, so a plain list of indexes would follow the reader from one message to
  // the next and mark the same button pressed on a row nobody touched.
  const [done, setDone] = useState(initialDone)
  const [busy, setBusy] = useState(null)   // `${row.id}:${index}` while its request is in flight
  // Pressed is what the server says, not only what this pane remembers: a press still waiting for the plugin
  // (`row.queued`) and one the plugin has taken (`detail.pressed`) stay pressed however often the pane is drawn
  // again — closed and reopened, the Inbox polled — or a second press would run the same thing twice.
  const pressed = [...new Set([...(done[row.id] || []), ...(row.queued || []), ...(d.pressed || [])])]
  const actions = (d.actions || []).filter((a) => a && a.label)
  const act = async (a, i) => {
    const key = `${row.id}:${i}`
    if (busy === key) return
    setBusy(key)
    try {
      const r = await post('/plugin-act', { plugin: row.plugin, id: row.id, index: i })
      setDone((was) => ({ ...was, [row.id]: [...(was[row.id] || []), i] }))
      // a row cockpit wrote itself is applied at once, and the answer says what came of it (`applied`, `out`)
      if (r.applied) { if (r.ok === false) host.notifyError(new Error(r.out || 'refused'), a.label); else host.notify({ kind: 'success', title: a.label, message: r.out || 'done' }); if (onDone) onDone(); return }
      host.notify({ kind: 'info', title: a.label, message: r.already ? `already queued for ${row.plugin}` : `queued for ${row.plugin} — it applies on the next pass` })
    } catch (e) { host.notifyError(e, `${a.label}: not queued`) } finally { setBusy(null) }
  }
  // a row whose plugin is not installed any more: nothing else takes it away
  const dismiss = async () => {
    try { await post('/plugin-row-dismiss', { plugin: row.plugin, id: row.id }); host.notify({ kind: 'success', message: 'row dismissed' }); if (onDone) onDone() } catch (e) { host.notifyError(e, 'Dismiss: not done') }
  }
  return h('div', { className: 'flex h-full min-h-0 flex-col gap-2 overflow-auto p-3 text-xs', 'data-plugin-detail': row.plugin || '' },
    detailHead(d.title || row.what || row.plugin, d.status && d.status.text ? { text: d.status.text, color: d.status.color || row.color } : null, row.plugin || ''),
    row.pticket ? h(TicketTools, { ticket: row.pticket, part: 'chat' }) : null,
    // a plugin writes its brief and what it said in markdown; the backend renders them (brief_html, said_html)
    d.brief ? (d.brief_html ? h(RichMd, { html: d.brief_html }) : h('div', null, d.brief)) : null,
    fields.length ? h(BriefGrid, { fields }) : null,
    // what came of the last press, written by the plugin on the row the button is on: a request it
    // refused has to be readable here, or pressing again is the only way to find out it was refused
    d.said ? h('div', { 'data-said': '1', className: 'rounded px-2 py-1',
      style: { background: 'rgba(127,127,127,.12)', color: /^refused/.test(d.said) ? 'var(--ui-danger, #d33)' : 'var(--ui-text-secondary)' } },
      d.said_html ? h(RichMd, { html: d.said_html }) : d.said) : null,
    actions.length ? h('div', { className: 'flex flex-wrap items-center gap-2' },
      ...actions.map((a, i) => h('span', { key: i, title: a.hint || '', 'data-act': a.act ? String(i) : undefined,
        'data-act-queued': pressed.includes(i) ? String(i) : undefined },
        pressed.includes(i) ? h('span', { style: sub }, `${a.label} · queued`)
          : busy === `${row.id}:${i}` ? h('span', { style: sub }, `${a.label} · sending`)
            : btn(a.label, () => { if (a.act) act(a, i); else if (a.href) host.navigate(a.href) },
              { accent: i === 0, danger: Boolean(a.danger) })))) : null,
    d.footer ? h('div', { style: sub }, d.footer) : null,
    !row.detail && !row.orphan ? h('div', { 'data-row-plain': '1', style: sub }, `${row.plugin || 'The plugin'} gave this row no page and no detail: it takes the row away when the matter is settled.`) : null,
    row.orphan ? h('div', { 'data-row-orphan': '1', className: 'flex flex-wrap items-center gap-2' },
      h('span', { style: sub }, `${row.plugin || 'The plugin'} is not installed any more, so nothing will take this row away.`),
      btn('Dismiss', dismiss, { danger: true, title: 'remove this row from the Inbox' })) : null)
}

function UpdatePanel({ w }) {
  // a newer cockpit in its repository: the same update the Settings page runs (fast-forward, refresh, gateway restart)
  const [busy, setBusy] = useState(false); const [last, setLast] = useState(null)
  const apply = async () => {
    if (busy) return
    setBusy(true)
    try { const r = await post('/update-apply', {}); setLast(r); host.notify({ kind: 'success', title: 'cockpit update', message: r.out || 'updated' }) }
    catch (e) { host.notifyError(e, 'cockpit update failed') } finally { setBusy(false) }
  }
  return h('div', { className: 'flex flex-col gap-2 p-3 text-xs' },
    detailHead('cockpit update', { text: 'update available', color: 'var(--ui-accent)' }, ''),
    h('div', null, w.reason),
    h('div', { className: 'flex items-center gap-2' }, h('button', { type: 'button', disabled: busy, onClick: apply, className: 'rounded px-3 py-1 text-xs font-medium disabled:opacity-40',
      style: { background: 'var(--ui-accent)', color: '#fff' } }, busy ? 'updating' : 'Update now')),
    last ? h('div', { style: { color: 'var(--ui-success, #2a9d5c)' } }, last.out) : null,
    last ? h(NextLine, { next: last.next }) : null)   // the line left to the human, resolved for this machine
}
function WatcherPanel({ w }) {
  const [running, setRunning] = useState(false)   // one run at a time from here; the server refuses a second too
  const run = async () => {
    if (running) return
    setRunning(true)
    try { const r = await post('/watcher-run', { name: w.name }); host.notify({ kind: 'info', title: `watcher ${w.name}`, message: r.out }) }
    catch (e) { host.notifyError(e, `${w.name}: run failed to start`) } finally { setRunning(false) }
  }
  const counts = `${w.fails} failure(s) in a row${w.last_error ? ` · last failed ${ago(w.last_error)} ago` : ''} · last success ${w.last_ok ? ago(w.last_ok) + ' ago' : 'never'}`
  // the code-changed notice is not a watcher: what answers it is a restart, so it offers that command, not Run now
  if (w.restart) return h('div', { className: 'flex flex-col gap-2 p-3 text-xs' },
    detailHead(w.name, { text: 'restart needed', color: 'var(--ui-accent)' }, ''),
    h('div', { className: 'font-medium' }, w.reason),
    h('div', { className: 'flex items-center gap-2' },
      h('code', { className: 'rounded px-1.5 py-0.5', style: { ...mono, background: 'rgba(127,127,127,.12)' } }, w.restart),
      copyBtn(w.restart, 'restart command')),
    h('div', { style: sub }, 'These pages are answered by code loaded before the change, so they may disagree with the files on disk (a pack written for the new code can fail to load here). The row leaves once the restart loads the new code.'))
  return h('div', { className: 'flex flex-col gap-2 p-3 text-xs' },
    detailHead('watcher ' + w.name, { text: 'failing', color: 'var(--ui-danger, #d33)' }, w.last_ok || 'no success yet'),
    h('div', { className: 'font-medium', style: { color: 'var(--ui-danger, #d33)' } }, w.reason || 'not running properly'),
    h('div', { style: sub }, counts),
    h('div', { className: 'flex items-center gap-2' }, running ? h('span', { style: sub }, 'Running…') : btn('Run now', run, { accent: true, title: 'run the watcher\'s cron script now; the row leaves on its next successful run' }),
      h('span', { style: sub }, 'The cron keeps running on its schedule. A network failure is tried again after two minutes by itself; anything else, fix the cause and Run now.')),
    w.error ? h(Section, { title: 'Stack trace', open: false, extra: copyBtn(w.error, 'stack trace') }, h('pre', { className: 'whitespace-pre-wrap', style: mono }, w.error)) : h('div', { style: sub }, '(no output recorded)'))
}

export { Inbox, BlockedCard, credentialAsk, groupByPr, PrGroupPanel, CardView, FileButtons, ReReviewPanel, PrDiffPanel, BumpsPanel, WatcherPanel, StandupPanel, RefusalPanel, PrivilegedPanel, PluginPanel, AnswerPanel, TrackerNotePanel, MergePanel, stillOpen }
