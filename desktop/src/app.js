// SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
// SPDX-License-Identifier: AGPL-3.0-or-later
import { useState, useEffect } from 'react'
import { host, haptic, useQuery, useQueryClient, CTX, POLL_MS, h, sub, mono, stroke, ClearableTextarea, btn, seg, post, tabs, useList } from './lib/sdk.js'
import { HINTS, hintsOf } from './lib/packwords.js'
import { Inbox } from './views/inbox.js'
import { Attach, onPasteImages } from './views/outbox.js'
import { Tickets } from './views/tickets.js'
import { QaIndex } from './views/qa.js'
import { Live } from './views/live.js'
import { Usage } from './views/usage.js'
import { Settings } from './views/settings.js'
import { Vault } from './views/vault.js'
import { Platform } from './views/platform.js'
import { Board } from './views/board.js'
import { ChatButton } from './views/chat.js'

function useRepoInfo() {
  const q = useQuery({ queryKey: ['cockpit', 'repos'], queryFn: () => CTX.rest('/repos'), refetchInterval: POLL_MS * 6, retry: 0 })
  return q.data || {}
}
// an example key for a ticket the tracker does not have yet, in the pack's own project
const localKey = (project) => `${project || 'KEY'}-LOCAL-7`
// capacity per flow (cockpitlib.capacity): five tiny pills in the toolbar, Dev · Test · Review · Bump · Question, each the number that can start now — green, amber at the last one, red at zero; hover says why
const TONE = { ok: 'var(--ui-success, #2a9d5c)', warn: 'var(--ui-warning, #c98a00)', danger: 'var(--ui-danger, #d33)' }
function useCapacity() { return useQuery({ queryKey: ['cockpit', 'capacity'], queryFn: () => CTX.rest('/capacity'), refetchInterval: POLL_MS, retry: 0 }) }
function CapacityPills() {
  const q = useCapacity(); const flows = (q.data && q.data.flows) || []
  return h('div', { className: 'flex items-center gap-1' },
    ...flows.map((c) => { const color = TONE[c.tone] || 'var(--ui-text-tertiary)'
      return h('span', { key: c.key, className: 'cockpit-cap', title: c.why, style: { color, borderColor: color, background: `color-mix(in srgb, ${color} 12%, transparent)` } }, `${c.label} ${c.free}`) }))
}
// A link per page beside cockpit's own (pack plugins.<name>.page), at the right of the tab row, so
// crossing over does not need the sidebar — which is what full screen takes away. A cockpit with no
// plugin beside it gets an empty list and renders nothing: there is no row, no gap and no mention.
function PluginPages() {
  const q = useQuery({ queryKey: ['cockpit', 'plugin-pages'], queryFn: () => CTX.rest('/plugin-pages'), refetchInterval: POLL_MS * 30, retry: 0 })
  const pages = (q.data && q.data.pages) || []
  if (!pages.length) return null
  return h('span', { className: 'flex items-center gap-1' },
    ...pages.map((page) => h('span', { key: page.plugin, 'data-plugin-page': page.plugin },
      btn(`${page.label} ↗`, () => host.navigate(page.path), { title: `${page.label} (${page.path})` }))))
}

// the form's own check: a Ticket needs Dev, a Test needs Test (on a local slot: a slot too)
const capFree = (flows, mode, slotted) => { const f = (flows || []).find((x) => x.key === (mode === 'intake' || mode === 'rework' ? 'dev' : mode === 'test' ? 'test' : '')); if (!f) return null; const n = mode === 'test' && slotted ? f.local : f.free; return n <= 0 ? { label: f.label + (mode === 'test' && slotted ? ' on a local slot' : ''), why: f.why } : null }
// cockpit's own modes, worded for this form; GET /kickoff-modes adds the ones plugins register
const KICKOFF_TABS = [['intake', 'Ticket → intake (plan, then your go)'], ['test', 'Test → tester (plan, your go, run, your review, post)'], ['review', 'PR review → reviewer (review intents to publish)'], ['bumps', HINTS.bumps_tab], ['analyst', 'Question → analyst']]
// the tabs with the pack's own word for the one that names a skill (the /repos route's hints)
const kickoffTabs = (hints) => KICKOFF_TABS.map(([mode, label]) => [mode, mode === 'bumps' ? hintsOf(hints).bumps_tab : label])
function KickoffForm({ onDone, initialMode = 'intake' }) {
  const info = useRepoInfo(); const REPOS = info.repos || []; const PROJECT = info.project
  const [ticket, setTicket] = useState(''); const [prompt, setPrompt] = useState(''); const [files, setFiles] = useState([]); const [busy, setBusy] = useState(false); const [mode, setMode] = useState(initialMode)
  const [pickedEnv, setEnv] = useState('')   // Test only: where it runs, from the pack's environments (GET /capacity)
  const [chrome, setChrome] = useState(false)   // Test only: the external browser (the human's or the agents' own-CDP Chrome) for this test kickoff (cockpitlib.browser_card)
  const scq = useQuery({ queryKey: ['cockpit', 'shared-chrome'], queryFn: () => CTX.rest('/shared-chrome'), refetchInterval: POLL_MS * 2, retry: 0 }); const lent = (scq.data && scq.data.ticket) ? scq.data : null
  const [repos, setRepos] = useState([])      // Bumps only: one card per repo, under the week's batch key
  const qc = useQueryClient(); const key = ticket.trim().toUpperCase()
  const mq = useQuery({ queryKey: ['cockpit', 'kickoff-modes'], queryFn: () => CTX.rest('/kickoff-modes'), staleTime: POLL_MS * 6, retry: 0 })
  const added = ((mq.data && mq.data.modes) || []).filter((m) => m.owner)   // modes a plugin beside cockpit registered (cockpitlib.registry)
  const plugged = added.find((m) => m.mode === mode)
  const cq = useCapacity(); const envs = (cq.data && cq.data.environments) || []; const env = pickedEnv || (envs.find((e) => !e.slot) || envs[0] || { name: '' }).name
  const slotted = Boolean((envs.find((e) => e.name === env) || {}).slot)
  const full = capFree(cq.data && cq.data.flows, mode, slotted)   // no capacity: the form says why instead of a button
  const ok = (mode === 'bumps' ? repos.length > 0 : /^[A-Z][A-Z0-9]*(-[A-Z0-9]+)+$/.test(key)) && !full
  const go = async () => {
    if (!ok || busy) return; setBusy(true)
    try { const r = await post('/kickoff', mode === 'bumps' ? { mode, repos, prompt } : { ticket: key, prompt, mode,
      evidence: files.map((f) => f.path), ...(mode === 'test' ? { env } : {}),
      ...(mode === 'test' && chrome ? { chrome: true } : {}) }); host.notify({ kind: 'success',
      title: `${mode === 'bumps' ? repos.join(', ') : key} → ${mode}${mode === 'test' ? ' on ' + env : ''}`,
      message: r.out }); qc.invalidateQueries({ queryKey: ['cockpit'] }); onDone() }
    catch (e) { host.notifyError(e, 'kickoff failed') } finally { setBusy(false) }
  }
  return h('div', { className: 'flex flex-col gap-2 border-b px-3 py-2 text-xs', style: { borderColor: 'var(--ui-accent)' } },
    h('div', { className: 'flex items-center gap-2' }, h('div', { className: 'font-medium' }, 'Kick off'), tabs(mode, setMode, [...kickoffTabs(info.hints), ...added.map((m) => [m.mode, m.label])])),
    mode === 'test' ? h('div', { className: 'flex items-center gap-2' }, h('span', { style: sub }, 'where'), tabs(env, setEnv, envs.map((e) => [e.name, e.slot ? `${e.name} (a slot of this machine)` : `${e.name} (test accounts)`]))) : null,
    h('div', { style: sub }, mode === 'intake' ? 'A tracker key is enough: intake reads the ticket, reproduces on a free slot, proposes the plan on a card and asks you "go?" here. For an issue without a ticket, pick a key like ' + localKey(PROJECT) + ' and describe it; intake proposes the ticket too.'
      : mode === 'test' ? (!slotted
        ? 'A tester stakes out the test report comment (init), writes the plan and asks you "go?". After your go it runs on staging with the test accounts in its vault (it never sees ' +
          'a password; a failed login asks you here in a masked form). Every run comes back for your review with its results and evidence (failures recorded on video); only after ' +
          'you accept does the post wait in the Outbox for you to publish. Nothing destructive, nothing outside the test accounts; the test data it creates is kept as the reference and the evidence.'
        : 'A tester stakes out the test report comment (init), writes the plan and asks you "go?". After your go it runs on its local slot (the ticket\'s worktree branches when there ' +
          'are any, else the base branch). Every run comes back for your review with its results and evidence (failures recorded on video); only after you accept does the post wait ' +
          'in the Outbox for you to publish. The test data it creates is kept as the reference and the evidence.')
      : mode === 'review' ? hintsOf(info.hints).review
      : mode === 'bumps' ? hintsOf(info.hints).bumps
      : plugged ? plugged.text || plugged.label
      : 'The analyst answers with evidence from code, staging and logs (read-only). Its answer and the files it wrote come to the Inbox as a row: reopen, rework or kick off with them in one click, ask for a patch plan, or dismiss.'),
    h('div', { className: 'flex gap-2' },
      mode === 'bumps' ? h('div', { className: 'flex flex-wrap items-center gap-2 text-xs' }, ...REPOS.map((r) => h('label', { key: r, className: 'flex items-center gap-1' }, h('input', { type: 'checkbox', checked: repos.includes(r), onChange: (e) => setRepos(e.target.checked ? [...repos, r] : repos.filter((x) => x !== r)) }), r))) :
      h('input', { value: ticket, onChange: (e) => setTicket(e.target.value), placeholder: 'TASK-100', autoFocus: true, className: 'w-32 rounded border bg-transparent px-1.5 py-0.5', style: { ...mono, borderColor: ok || !ticket ? stroke : 'var(--ui-danger, #d33)' } }),
      h(ClearableTextarea, { value: prompt, onChange: (e) => setPrompt(e.target.value), rows: 2,
        placeholder: mode === 'intake' ? 'optional: what you already know, constraints, where to look, what not to touch' : mode === 'test' ? 'optional: scope, ACs to cover, test data to use, what not to touch' : mode === 'review' ? 'optional note for the reviewer (e.g. focus on the PDF path; "findings only" to skip the intents)' : 'your question',
        onPaste: ok ? onPasteImages(key, setFiles) : undefined, className: 'min-w-0 flex-1 rounded border bg-transparent px-1.5 py-0.5',
        style: { borderColor: stroke } })),
    mode === 'test' ? h('label', { className: 'flex items-center gap-1.5', title: 'this test kickoff drives the external browser (Chrome on its DevTools port, through Chrome MCP) for a few hours (Settings) instead of the built-in one; every other flow, and every supervisor card, runs on the built-in browser' },
      h('input', { type: 'checkbox', checked: chrome, disabled: Boolean(lent && lent.ticket !== key), onChange: (e) => setChrome(e.target.checked) }), 'use the external browser (my Chrome) for this test',
      lent ? h('span', { style: sub }, ` · lent to ${lent.ticket} until ${new Date(lent.until * 1000).toTimeString().slice(0, 5)} `, h('a', { href: '#', onClick: async (e) => { e.preventDefault(); try { await post('/shared-chrome-release', {}); scq.refetch && scq.refetch() } catch (err) { host.notifyError(err, 'release failed') } } }, 'release')) : null) : null,
    ok && mode !== 'bumps' ? h(Attach, { ticket: key, files, setFiles }) : null,
    full ? h('div', { className: 'rounded border px-2 py-1 text-xs', style: { borderColor: 'var(--ui-danger, #d33)', color: 'var(--ui-danger, #d33)' }, title: full.why }, `No capacity for ${full.label} right now: ${full.why}`) : null,
    h('div', { className: 'flex gap-1.5' }, h('button', { type: 'button', disabled: busy || !ok || (mode === 'analyst' && !prompt.trim()),
      onClick: go, className: 'rounded px-2.5 py-0.5 text-xs font-medium disabled:opacity-40', style: { background: 'var(--ui-accent)', color: '#fff' } },
      busy ? 'working' : mode === 'intake' ? 'Hand to intake' : mode === 'test' ? `Hand to a tester (${env})` : mode === 'review' ? 'Ask for the review' : 'Ask the analyst'),
      btn('Cancel', onDone)))
}

function OutboxPage({ initialView, openGroups } = {}) {   // initialView / openGroups: tests only; the page keeps reading the stored view
  const q = useList()
  // A plugin page can send the reader to one of its own Inbox rows: `/cockpit#plugin=<plugin>/<id>`.
  // The Inbox is a view of this page, not a route of its own, so the page has to be on it before the
  // list can select anything — a link that landed on whatever view was last open selected nothing.
  // Read at the first render rather than in an effect, so the asked-for view is the one drawn.
  const asksInbox = () => { try { return /(?:^|[#&])plugin=/.test((window.location || {}).hash || '') } catch { return false } }
  const [view, setViewRaw] = useState(() => { if (asksInbox()) return 'inbox'; const v = initialView ?? CTX.storage.get('view3', 'inbox'); return v === 'outbox' ? 'inbox' : v })   // the Outbox lives under the Inbox now
  const setView = (v) => { setViewRaw(v); CTX.storage.set('view3', v) }
  const [kick, setKick] = useState(false); const [tools, setTools] = useState(false)
  // and again while the page is open, for a second link followed from the other page
  useEffect(() => {
    if (typeof window === 'undefined' || !window.addEventListener) return undefined
    const follow = () => { if (asksInbox()) setView('inbox') }
    window.addEventListener('hashchange', follow)
    return () => window.removeEventListener('hashchange', follow)
  }, [])
  const qc = useQueryClient()
  const allRows = (q.data && q.data.rows) || []
  const refresh = () => qc.invalidateQueries({ queryKey: ['cockpit'] })
  const renumber = async () => { try { await post('/digest'); host.notify({ kind: 'info', message: 'Digest renumbered' }); refresh() } catch (e) { host.notifyError(e, 'renumber failed') } }
  const sweep = async () => { try { const r = await post('/sweep'); host.notify({ kind: 'info', title: 'Gatekeeper', message: r.out }) } catch (e) { host.notifyError(e, 'sweep failed') } }
  const toolbar = h('div', { className: 'flex items-center gap-3 px-3 py-2 border-b', style: { borderColor: stroke } },
    h('div', { className: 'flex items-center gap-1 rounded border p-0.5', style: { borderColor: stroke } }, seg(view, 'inbox', 'Inbox', setView),
      seg(view, 'board', 'Board', setView), seg(view, 'live', 'Live', setView), seg(view, 'worktrees', 'Tickets', setView),
      seg(view, 'qa', 'QA evidence', setView), seg(view, 'platform', 'Platform', setView), seg(view, 'usage', 'Usage', setView),
      seg(view, 'vault', 'Vault', setView), seg(view, 'settings', 'Settings', setView)),
    h(PluginPages, {}),
    view === 'inbox' || view === 'board' ? null : view === 'qa' ? h('div', { className: 'text-xs', style: sub },
      'every ticket with test runs under qa/') : view === 'live' ? h('div', { className: 'text-xs', style: sub },
      'the bots at work: lane run logs and coding tool transcripts, following the tail') : view === 'usage' ? h('div', { className: 'text-xs', style: sub },
      'tokens and estimated cost: every lane and every coding tool run, against the plan windows') : view === 'platform' ? h('div',
      { className: 'text-xs', style: sub }, 'what the platform does, down to the code; what landed on the base branch per area, explained') : view === 'vault' ? h('div',
      { className: 'text-xs', style: sub }, 'vaults and the logins, keys and notes they hold; values open only when you ask') : h('div',
      { className: 'text-xs', style: sub }, 'every ticket this machine holds'),
    h('div', { className: 'ml-auto flex items-center gap-1.5' },
      h(CapacityPills, {}),
      btn(kick ? 'Close' : '+ Kick off', () => setKick(!kick), { accent: !kick, title: 'a ticket key (or a described issue) → intake proposes a plan and asks you "go?" here' }),
      h(ChatButton, { ticket: 'own', label: 'Chat' }),   // your own coding tool: the workspace, outside every flow
      view === 'inbox' ? btn(tools ? 'Gate tools ▾' : 'Gate tools ▸', () => setTools(!tools), { title: 'sweep, renumber, rescan' }) : null,
      view === 'inbox' && tools ? btn('Sweep now', sweep, { title: 'ask the gatekeeper to endorse or hold the pending intents now (sweeps also start by themselves when an intent is written)' }) : null,
      view === 'inbox' && tools ? btn('Renumber', renumber, { title: 'cockpit outbox digest: refreshes the #-numbers that "publish 1-3" uses' }) : null,
      view === 'inbox' && tools ? btn('Rescan PRs', async () => { try { await post('/pr-scan'); host.notify({ kind: 'info', message: 'PRs rescanned' }); refresh() } catch (e) { host.notifyError(e, 'rescan failed') } }, { title: 'cockpit watch-pr scan now (the cron does it every 5 min)' }) : null))
  return h('div', { className: 'flex h-full flex-col text-sm', 'data-selectable-text': 'true', 'data-plugin-root': 'cockpit' },
    toolbar,
    kick ? h(KickoffForm, { onDone: () => setKick(false) }) : null,
    // Hermes's gateway sometimes stops answering for a few seconds (busy starting lane workers): that is not a plugin
    // that is missing, so it reads as a quiet retry over the last data, not as a red setup hint.
    q.error ? (q.data || /ticket bootstrap|Timed out connecting|ECONNREFUSED|ECONNRESET/i.test(String(q.error.message || q.error))
      ? h('div', { className: 'px-3 py-1 text-[0.6875rem]', 'data-reconnecting': '1', style: { color: 'var(--ui-text-tertiary)' } }, 'Hermes did not answer for a moment — retrying' + (q.data ? '; the last data is shown' : ''))
      : h('div', { className: 'p-3 text-xs', style: { color: 'var(--ui-danger, #d33)' } }, 'Backend not reachable: ', String(q.error.message || q.error), ' — is cockpit in plugins.enabled (~/.hermes/config.yaml)? cockpit setup apply does that.')) : null,
    view === 'usage' ? h(Usage, {}) : view === 'vault' ? h(Vault, {}) : view === 'settings' ? h(Settings, {}) : view === 'platform' ? h(Platform, {}) : view === 'live' ? h(Live, {}) : view === 'qa' ? h(QaIndex, {}) : view === 'board' ? h(Board, {}) : view === 'worktrees' ? h(Tickets, {}) : h(Inbox, { rows: allRows, refresh, openAll: openGroups }),
    h('div', { className: 'border-t px-3 py-1 text-[0.6875rem]', style: { ...sub, borderColor: stroke } },
      'Inbox = your to-do, then the gate under it (in flight · published · dropped: the gatekeeper endorses, you publish) · Live = the bots at work · Kanban page = the big picture.'))
}

function Chip() {
  const q = useList()
  const nq = useQuery({ queryKey: ['cockpit', 'needs-you'], queryFn: () => CTX.rest('/needs-you'), refetchInterval: POLL_MS, retry: 1 })
  const aq = useQuery({ queryKey: ['cockpit', 'advisories'], queryFn: () => CTX.rest('/advisories'), refetchInterval: POLL_MS * 6, retry: 0 })
  const rows = (q.data && q.data.rows) || []
  const endorsedIds = rows.filter((r) => r.status === 'endorsed' && r.type !== 'ticket-done' && !r.waits).map((r) => r.id)
  const prNew = rows.filter((r) => r.pr && r.pr.new_count && r.pr.role !== 'reviewer').map((r) => `${r.ticket}#${r.pr.number}:${r.pr.new.map((c) => c.id).join('+')}`)
  const reReq = [...new Set(rows.flatMap((r) => (r.prs || []).filter((p) => p.role === 'reviewer' && !p.merged && (p.re_requested || (p.my_threads && p.my_threads.total && p.my_threads.resolved === p.my_threads.total))).map((p) => `${r.ticket}#${p.number}:${p.re_requested ? 'req' : 'resolved'}`)))]
  const ciFail = rows.filter((r) => r.ci && r.ci.state === 'failed' && !r.ci.handled && !r.ci.analysing).map((r) => `${r.ticket}:${r.ci.sha}`)
  const acks = rows.filter((r) => r.type === 'ticket-done' && r.status === 'pending').map((r) => r.id)
  const posted = rows.filter((r) => r.status === 'posted').map((r) => r.id)
  const approved = [...new Set(rows.filter((r) => r.pr && !r.pr.merged && r.pr.approvals && r.pr.approvals.length).map((r) => `${r.ticket}#${r.pr.number}`))]
  const watchersBad = ((nq.data && nq.data.watchers) || []).filter((w) => !w.ok).map((w) => w.name)
  const blocked = ((nq.data && nq.data.cards) || []).filter((c) => c.status === 'blocked' || c.status === 'triage').map((c) => c.id)
  const advisories = CTX.storage.get('showSecurity', false) ? ((aq.data && aq.data.advisories) || []).filter((a) => a.alert && !a.acknowledged).map((a) => a.id) : []   // hidden with the Inbox's security box   // once per newly alertable advisory; an acknowledged one never
  const watch = (key, ids, title, body) => useEffect(() => {
    if (!q.data) return
    const seen = new Set(CTX.storage.get(key, [])); const fresh = ids.filter((x) => !seen.has(x))
    if (fresh.length) CTX.os.notify({ title, body: body(fresh), activate: true, onActivate: () => host.navigate('/cockpit') })
    CTX.storage.set(key, ids)
  }, [ids.join(',')])
  watch('seenEndorsed', endorsedIds, 'Outbox: endorsed, waiting for you', (f) => f.join(', '))
  watch('seenPrNew', prNew, 'PR comments ahead of the pipeline', (f) => f.map((k) => k.split(':')[0]).join(', '))
  watch('seenCiFail', ciFail, 'CI failed', (f) => f.map((k) => k.split(':')[0]).join(', ') + ' — the analyst is diagnosing')
  watch('seenAcks', acks, 'Ticket done: your final ack', (f) => f.join(', '))
  watch('seenPosted', posted, 'Pending review posted: check it on the forge, then publish', (f) => f.join(', '))
  watch('seenApproved', approved, 'PR approved: merge when ready', (f) => f.join(', '))
  watch('seenReReq', reReq, 'A PR you review is ready for re-review', (f) => f.map((k) => k.split(':')[0]).join(', '))
  watch('seenWatchers', watchersBad, 'A watcher is failing', (f) => f.join(', '))
  watch('seenBlocked', blocked, 'A lane needs your answer', (f) => `${f.length} blocked card(s) — answer in the Outbox`)
  watch('seenAdvisories', advisories, 'Stack advisory: a component we run is vulnerable', (f) => f.join(', '))
  const open = (q.data && q.data.counts) ? ((q.data.counts.pending || 0) + (q.data.counts.endorsed || 0) + (q.data.counts.held || 0) + (q.data.counts.returned || 0)) : 0
  const needs = endorsedIds.length + blocked.length + acks.length + ciFail.length + prNew.length + posted.length + approved.length + watchersBad.length + reReq.length + advisories.length
  if (!q.data) return null
  return h('button', { type: 'button', onClick: () => { haptic('tap'); host.navigate('/cockpit') }, className: 'px-1.5 text-[0.6875rem]', title: `outbox: ${open} open · needs you: ${endorsedIds.length} to publish, ${blocked.length} questions, ${acks.length} acks, ${ciFail.length} CI failures, ${prNew.length} PRs with new comments, ${advisories.length} advisories`,
    style: { color: needs ? (blocked.length || ciFail.length ? 'var(--ui-warning, #c98a00)' : 'var(--ui-success, #2a9d5c)') : 'var(--ui-text-tertiary)' } }, needs ? `cockpit · ${needs} need you` : `cockpit · ${open} at the gate`)
}

export { OutboxPage, KickoffForm, Chip }
