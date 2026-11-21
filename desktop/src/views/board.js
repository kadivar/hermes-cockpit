// SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
// SPDX-License-Identifier: AGPL-3.0-or-later
import { useState, useEffect, useMemo, useRef } from 'react'
import { host, useQuery, useQueryClient, CTX, h, sub, mono, stroke, btn, ago, Pane } from '../lib/sdk.js'
import { CardView, BlockedCard } from './inbox.js'

// ---------- Board: the kanban as the Cockpit reads it. Same look as the host's Kanban page (apps/desktop/src/plugins/kanban/board.tsx),
// built with h() on GET /board; a reading board: click a card for its Brief (or the answer form when it is blocked), no drag, no edits ----------
// column tones: the native COLUMN_META (kanban/types.ts); claimed/in_progress ride the running tone, cancelled the archived one
const TONE = { triage: 'var(--ui-text-tertiary)', todo: 'var(--ui-text-secondary)', ready: '#60a5fa', claimed: '#34d399', in_progress: '#34d399', running: '#34d399', review: '#fbbf24', blocked: '#f87171', done: 'var(--ui-text-tertiary)', archived: 'var(--ui-text-quaternary)', cancelled: 'var(--ui-text-quaternary)' }
const tone = (status) => TONE[status] || 'var(--ui-text-secondary)'
const STATUS_LABEL = { in_progress: 'in progress' }
const statusLabel = (s) => STATUS_LABEL[s] || (s || '').replace(/_/g, ' ')
// the pipeline left→right; "Running" merges the three worked states, "Done" the three closed ones (collapsed by default)
const COLUMNS = [
  { id: 'triage', title: 'Triage', statuses: ['triage'] },
  { id: 'todo', title: 'To do', statuses: ['todo'] },
  { id: 'ready', title: 'Ready', statuses: ['ready'] },
  { id: 'running', title: 'Running', statuses: ['claimed', 'in_progress', 'running'] },
  { id: 'review', title: 'Review', statuses: ['review'] },
  { id: 'blocked', title: 'Blocked', statuses: ['blocked'] },
  { id: 'done', title: 'Done', statuses: ['done', 'archived', 'cancelled'], closed: true },
]
// one hue per lane family (the native board colours identities with profileColor; the lanes are a fixed roster, so fixed tasteful hues)
const LANE_HUES = [[/^intake/, '#a78bfa'], [/^worker/, '#60a5fa'], [/^tester/, '#34d399'], [/^reviewer/, '#fbbf24'], [/^gatekeeper/, '#f87171'], [/^analyst/, '#22d3ee']]
const laneHue = (lane) => (LANE_HUES.find(([re]) => re.test(lane || '')) || [null, 'var(--ui-text-secondary)'])[1]
const initials = (name) => { const p = String(name || '').trim().split(/[\s_\-./]+/).filter(Boolean); return `${(p[0] || '?')[0]}${p[1] ? p[1][0] : ''}`.toUpperCase() }
const WARN = 'var(--ui-warning, #c98a00)'; const DANGER = 'var(--ui-danger, #d33)'; const NONE = []
const ts = (iso) => (iso ? new Date(iso).getTime() : 0)
// "TASK-137: Fix the total" → "Fix the total" (the ticket is its own chip)
const bareTitle = (c) => { const t = (c.title || '').trim(); const k = c.ticket; if (!k) return t || c.id; const m = t.match(new RegExp('^' + k.replace(/[.*+?^${}()|[\]\\]/g, '\\$&') + '\\s*[:\\-–—]?\\s*', 'i')); return (m ? t.slice(m[0].length) : t) || t || c.id }
const firstLine = (s) => (String(s || '').split('\n').find((l) => l.trim()) || '').trim()
// compact run duration like the native RunClock (ui.tsx coarseElapsed + ELAPSED_SUFFIX): 42s · 3m · 2h · 1d, ticking every 5 s while mounted
const elapsed = (iso) => { const s = Math.max(0, (Date.now() - ts(iso)) / 1000); return s < 60 ? `${Math.round(s)}s` : s < 3600 ? `${Math.round(s / 60)}m` : s < 86400 ? `${Math.round(s / 3600)}h` : `${Math.round(s / 86400)}d` }
function useTick(on) { const [, force] = useState(0); useEffect(() => { if (!on) return; const id = window.setInterval(() => force((n) => n + 1), 5000); return () => window.clearInterval(id) }, [on]) }
// cards that just left a column linger ~200 ms with the leave animation (each ghost removes itself; a card that is back before then wins)
function useLeaving(cards) {
  const prev = useRef(new Map()); const [ghosts, setGhosts] = useState([])
  useEffect(() => {
    const now = new Map(cards.map((c) => [c.id, c])); const gone = [...prev.current.values()].filter((c) => !now.has(c.id)); prev.current = now
    if (!gone.length) return
    setGhosts((g) => [...g.filter((x) => !gone.some((c) => c.id === x.id)), ...gone])
    window.setTimeout(() => setGhosts((g) => g.filter((x) => !gone.some((c) => c.id === x.id))), 220)
  }, [cards])
  return ghosts.filter((g) => !cards.some((c) => c.id === g.id))
}

// ---------- atoms: ticket chip, status chip, lane badge, run clock ----------
const ticketChip = (ticket) => (ticket ? h('span', { className: 'cockpit-kb-ticket', style: mono }, ticket) : null)
// the flow the card belongs to (the backend reads it from the title and the lane); a test card's pill is just where it tests: local · stg
const ENV = { 'test·local': 'local', 'test·staging': 'stg' }
const flowPill = (flow) => (flow && flow !== 'card' ? h('span', { className: 'cockpit-kb-flow', title: ENV[flow] ? `test on ${flow === 'test·staging' ? 'staging' : 'the local slot'}` : 'flow: ' + flow }, ENV[flow] || flow) : null)
const statusChip = (status) => h('span', { className: 'cockpit-kb-status', style: { color: tone(status), background: `color-mix(in srgb, ${tone(status)} 15%, transparent)` } }, h('span', { className: 'cockpit-kb-dot', style: { background: tone(status) } }), statusLabel(status))
const laneBadge = (lane, size) => { if (!lane) return null; const hue = laneHue(lane); return h('span',
  { className: 'cockpit-kb-lane', title: `lane ${lane}`, style: { color: hue, background: `color-mix(in srgb, ${hue} 14%, transparent)` } },
  h('span', { className: 'cockpit-kb-ava', style: { background: `color-mix(in srgb, ${hue} 22%, transparent)`, width: size || '1rem',
  height: size || '1rem' } }, initials(lane)), h('span', { className: 'truncate' }, lane)) }
function RunClock({ card }) {
  useTick(Boolean(card.alive))
  const since = card.started || card.heartbeat || card.created
  return since ? h('span', { className: 'shrink-0 font-medium', style: { color: TONE.running }, title: `working since ${ago(since)} ago · heartbeat ${card.heartbeat ? ago(card.heartbeat) + ' ago' : 'none'}` }, `working · ${elapsed(since)}`) : null
}

// ---------- card: the native card chrome (border-left in the column tone, elevated surface, hover wash + lift, arc while alive) ----------
function Card({ c, column, selected, onOpen, leaving }) {
  const t = tone(c.status)
  const working = ['claimed', 'in_progress', 'running'].includes(c.status)
  const arc = working && c.alive ? 'live' : working && c.heartbeat && !c.alive ? 'stale' : null
  const last = c.last_comment && firstLine(c.last_comment.text)
  return h('div', { className: 'cockpit-kb-card' + (selected ? ' sel' : '') + (leaving ? ' out' : '') + (column.closed ? ' closed' : ''), onClick: () => onOpen(c.id), title: c.title || c.id, style: { '--cockpit-kb-tone': t, borderLeftColor: t } },
    arc && !selected ? h('span', { 'aria-hidden': true, className: 'cockpit-kb-arc' + (arc === 'stale' ? ' stale' : '') }) : null,
    h('div', { className: 'flex items-center gap-1.5 min-w-0' }, ticketChip(c.ticket), flowPill(c.flow), column.statuses.length > 1 ? h('span', { className: 'cockpit-kb-sub', style: { color: t } }, statusLabel(c.status)) : null, h('span', { className: 'ml-auto cockpit-kb-age' }, c.created ? ago(c.created) : '')),
    h('div', { className: 'cockpit-kb-title' }, bareTitle(c)),
    c.status === 'blocked' && c.question ? h('div', { className: 'cockpit-kb-sum', style: { color: WARN } }, c.question) : null,
    c.error ? h('div', { className: 'cockpit-kb-line', style: { color: DANGER } }, c.error) : null,
    last ? h('div', { className: 'cockpit-kb-line', style: sub }, `${c.last_comment.author}: ${last}`) : null,
    h('div', { className: 'cockpit-kb-foot' },
      laneBadge(c.lane),
      arc === 'live' ? h(RunClock, { card: c }) : arc === 'stale' ? h('span', { className: 'shrink-0 font-medium', style: { color: '#fbbf24' }, title: `last heartbeat ${ago(c.heartbeat)} ago` }, 'no heartbeat') : null,
      h('div', { className: 'ml-auto flex min-w-0 shrink items-center gap-2' },
        c.runs > 1 ? h('span', { title: `${c.runs} runs` }, `↻ ${c.runs}`) : null,
        c.completed && column.closed ? h('span', { className: 'cockpit-kb-age', title: 'completed' }, ago(c.completed)) : null,
        h('span', { className: 'cockpit-kb-id truncate', style: mono }, String(c.id).replace(/^t_/, '').slice(0, 6)))))
}

// Done keeps a card in view while its ticket saw flow activity in the last RECENT_HOURS (the backend's ticket_activity: lanes,
// gatekeeper, human; cron housekeeping excluded); the rest stays behind "show N done", in the same order as today
// A live ticket (the backend's `live`: work, publish, merge or your confirm still to come) stays in view whatever its age.
const RECENT_HOURS = 24
const splitDone = (cards, activity, now = Date.now(), hours = RECENT_HOURS, live = {}) => {
  const recent = (c) => { if ((live || {})[c.ticket]) return true; const at = ts((activity || {})[c.ticket]); return at > 0 && now - at < hours * 3600e3 }
  return { recent: cards.filter(recent), hidden: cards.filter((c) => !recent(c)) }
}
// what a live ticket still waits for, as its group says it
const WAITS = { work: 'in work', publish: 'awaiting publish', merge: 'awaiting merge', confirm: 'awaiting your confirm', release: 'in a running release' }
const waitsLine = (whys) => (whys || []).map((w) => WAITS[w] || w).join(' · ')
// Done shows one stacked card per ticket, a single card included: units in the cards' order (newest completion first); only a
// card without a ticket stays plain. Each unit has an id, so the leave animation (useLeaving) works on stacks too.
const stackByTicket = (cards) => {
  const units = []; const byTicket = new Map()
  for (const c of cards) {
    if (!c.ticket) { units.push(c); continue }
    if (!byTicket.has(c.ticket)) { const u = { id: 'stack:' + c.ticket, stack: true, ticket: c.ticket, cards: [] }; byTicket.set(c.ticket, u); units.push(u) }
    byTicket.get(c.ticket).cards.push(c)
  }
  return units
}

// ---------- stack: the ticket's tracker title (else the newest card's) over two offset layers; click opens it in place ----------
function Stack({ s, title, waits, column, selected, onOpen, leaving }) {
  const holds = s.cards.some((c) => c.id === selected)
  const [open, setOpen] = useState(false)
  const top = s.cards[0]; const lanes = [...new Set(s.cards.map((c) => c.lane).filter(Boolean))]
  const t = tone('done')
  return h('div', { className: 'cockpit-kb-stackwrap' + (leaving ? ' out' : '') },
    h('div', { className: 'cockpit-kb-card closed cockpit-kb-stack' + (open || holds ? ' open' : ''), onClick: () => setOpen(!open), title: `${s.ticket}: ${title || bareTitle(top)} · ${s.cards.length} done card${s.cards.length === 1 ? '' : 's'}, newest: ${bareTitle(top)} — click to ${open ? 'fold' : 'open'}`, style: { '--cockpit-kb-tone': t, borderLeftColor: t } },
      h('div', { className: 'flex items-center gap-1.5 min-w-0' }, ticketChip(s.ticket), h('span', { className: 'cockpit-kb-stackn' }, `${s.cards.length} card${s.cards.length === 1 ? '' : 's'}`), h('span', { className: 'ml-auto cockpit-kb-age' }, top.completed ? ago(top.completed) : '')),
      h('div', { className: 'cockpit-kb-title' }, title || bareTitle(top)),
      waits ? h('div', { className: 'cockpit-kb-sub', 'data-waits': waits, style: { color: 'var(--ui-warning, #c98a00)' } }, waits) : null,
      h('div', { className: 'cockpit-kb-foot' }, ...lanes.slice(0, 4).map((l) => h('span', { key: l }, laneBadge(l))), lanes.length > 4 ? h('span', { style: sub }, `+${lanes.length - 4}`) : null,
        h('span', { className: 'ml-auto cockpit-kb-age' }, open || holds ? '▾ fold' : '▸ open'))),
    open || holds ? h('div', { className: 'cockpit-kb-stackbody' }, ...s.cards.map((c) => h(Card, { key: c.id, c, column, selected: c.id === selected, onOpen }))) : null)
}
const Unit = ({ u, titles, live, column, selected, onOpen, leaving }) => (u.stack ? h(Stack, { s: u, title: (titles || {})[u.ticket], waits: waitsLine((live || {})[u.ticket]), column, selected, onOpen, leaving }) : h(Card, { c: u, column, selected: !leaving && u.id === selected, onOpen, leaving }))

// ---------- column: header dot · label · count; body with the empty hint; Done shows one stack per ticket and hides the quiet
// ones behind "show N done" at the bottom ----------
function Column({ column, cards, activity, titles, live, selected, onOpen, recentHours }) {
  const [showDone, setShowDone] = useState(false)
  const { recent, hidden } = column.closed ? splitDone(cards, activity, Date.now(), recentHours || RECENT_HOURS, live) : { recent: cards, hidden: NONE }
  const visible = !column.closed || showDone ? cards : recent
  const shown = useMemo(() => (column.closed ? stackByTicket(visible) : visible), [column.closed, visible])
  const hiddenUnits = column.closed ? stackByTicket(hidden).length : 0
  const ghosts = useLeaving(shown)
  const t = tone(column.id === 'done' ? 'done' : column.statuses[0])
  return h('div', { className: 'cockpit-kb-col' },
    h('header', { className: 'cockpit-kb-colhead' }, h('span', { className: 'cockpit-kb-dot', style: { background: t } }), h('span', { className: 'cockpit-kb-collabel' }, column.title), h('span', { className: 'cockpit-kb-count' }, cards.length)),
    h('div', { className: 'cockpit-kb-body' },
      ...shown.map((u) => h(Unit, { key: u.id, u, titles, live, column, selected, onOpen })),
      ...ghosts.map((u) => h(Unit, { key: u.id, u, titles, live, column, selected, onOpen, leaving: true })),
      !cards.length ? h('div', { className: 'cockpit-kb-empty' }, 'empty') : null,
      column.closed && hiddenUnits ? h('button', { type: 'button', className: 'cockpit-kb-more', onClick: () => setShowDone(!showDone) }, showDone ? 'hide done' : `show ${hiddenUnits} done`) : null))
}

// ---------- the pane: status · ticket · title · lane, Chat + Open in Kanban; the answer form when blocked, else the card ----------
// a card that stands for a ticket's outbox items (the backend's waiting_cards): what waits, and the way to the Inbox
function WaitingPane({ card }) {
  const said = { now: 'for you now', later: 'a later stage', gate: 'with the gatekeeper', lane: 'back with a lane', stale: 'stale' }
  return h('div', { className: 'flex min-h-0 flex-1 flex-col gap-2 overflow-auto p-3' },
    h('div', { className: 'flex flex-wrap items-center gap-2' }, statusChip(card.status), ticketChip(card.ticket), h('div', { className: 'font-medium text-sm min-w-0' }, 'outbox items, no lane at work'),
      h('div', { className: 'ml-auto flex items-center gap-1.5' }, btn('Open the Inbox', () => host.navigate('/cockpit'), { accent: true, title: 'publish, confirm or decide them there' }))),
    h('div', { className: 'text-xs', style: sub }, card.question),
    h('div', { className: 'flex flex-col gap-0.5 text-xs' }, ...(card.items || []).map((it) => h('div', { key: it.id, className: 'flex gap-2' },
      h('span', { style: { minWidth: '9rem' } }, said[it.when] || it.when), h('span', { style: sub }, it.status), h('span', null, it.id)))))
}

function CardPane({ card, refresh }) {
  if (card.yours) return h(WaitingPane, { card })
  return h(LaneCardPane, { card, refresh })
}

function LaneCardPane({ card, refresh }) {
  const blocked = card.status === 'blocked'
  const cq = useQuery({ queryKey: ['cockpit', 'card-detail', card.id], queryFn: () => CTX.rest('/card-detail?id=' + card.id), enabled: !blocked, refetchInterval: 15000, retry: 0 })
  return h('div', { className: 'flex min-h-0 flex-1 flex-col gap-2 p-3' },
    h('div', { className: 'flex flex-wrap items-center gap-2' }, statusChip(card.status), ticketChip(card.ticket), flowPill(card.flow), h('div', { className: 'font-medium text-sm min-w-0' }, bareTitle(card)), laneBadge(card.lane),
      h('div', { className: 'ml-auto flex items-center gap-1.5' }, btn('Open in Kanban', () => host.navigate('/kanban'), { title: 'the host Kanban page: drag, assign, edit' }))),
    h('div', { className: 'flex flex-wrap gap-2 text-xs', style: sub },
      card.created ? h('span', null, 'created ' + ago(card.created) + ' ago') : null, card.started ? h('span', null, 'started ' + ago(card.started) + ' ago') : null, card.completed ? h('span', null, 'completed ' + ago(card.completed) + ' ago') : null,
      card.heartbeat ? h('span', { style: { color: card.alive ? TONE.running : 'inherit' } }, (card.alive ? 'alive · heartbeat ' : 'last heartbeat ') + ago(card.heartbeat) + ' ago') : null, card.runs ? h('span', null, `${card.runs} run${card.runs === 1 ? '' : 's'}`) : null, card.skills ? h('span', null, 'skills ' + (Array.isArray(card.skills) ? card.skills.join(', ') : card.skills)) : null),
    h('div', { className: 'min-h-0 flex-1 ' + (blocked ? 'flex flex-col' : 'overflow-auto') },
      blocked ? h(BlockedCard, { c: { ...card, assignee: card.lane }, refresh })
        : cq.data ? h(CardView, { c: cq.data }) : cq.error ? h('div', { className: 'text-xs', style: { color: DANGER } }, String(cq.error.message || cq.error)) : h('div', { className: 'text-xs', style: sub }, 'loading the card')))
}

// ---------- the view: filter row (lane chips, text), the lane strip, the pane ----------
function Board() {
  const q = useQuery({ queryKey: ['cockpit', 'board'], queryFn: () => CTX.rest('/board'), refetchInterval: 5000, retry: 1 })
  const qc = useQueryClient()
  const [lanes, setLanesRaw] = useState(() => { const v = CTX.storage.get('boardLanes', []); return Array.isArray(v) ? v : [] })
  const setLanes = (v) => { setLanesRaw(v); CTX.storage.set('boardLanes', v) }
  const [text, setText] = useState('')
  const [selected, setSelected] = useState(null)
  const cards = (q.data && q.data.cards) || []
  const allLanes = useMemo(() => [...new Set([...((q.data && q.data.lanes) || []), ...lanes])].sort(), [q.data, lanes])
  const needle = text.trim().toLowerCase()
  const keep = (c) => (!lanes.length || lanes.includes(c.lane)) && (!needle || `${c.ticket} ${c.title} ${c.id} ${c.lane} ${c.question || ''} ${c.error || ''}`.toLowerCase().includes(needle))
  // newest first in every column; Done by completion
  const byColumn = useMemo(() => COLUMNS.map((col) => [col, cards.filter((c) => col.statuses.includes(c.status) && keep(c)).sort((a, b) => (col.closed ? ts(b.completed || b.created) - ts(a.completed || a.created) : ts(b.created) - ts(a.created)))]), [cards, lanes, needle])
  const open = byColumn.filter(([col]) => !col.closed).reduce((n, [, cs]) => n + cs.length, 0)
  const closed = byColumn.filter(([col]) => col.closed).reduce((n, [, cs]) => n + cs.length, 0)
  const unmatched = cards.filter((c) => !COLUMNS.some((col) => col.statuses.includes(c.status))).length
  const current = selected ? cards.find((c) => c.id === selected) : null
  useEffect(() => { if (selected && q.data && !current) setSelected(null) }, [selected, q.data, current])  // the card left the board (archived elsewhere)
  const refresh = () => qc.invalidateQueries({ queryKey: ['cockpit'] })
  const toggleLane = (l) => setLanes(lanes.includes(l) ? lanes.filter((x) => x !== l) : [...lanes, l])
  const laneChip = (l) => { const on = lanes.includes(l); const hue = laneHue(l); return h('button', { key: l, type: 'button', onClick: () => toggleLane(l), className: 'cockpit-kb-chip', style: on ? { color: hue, borderColor: hue, background: `color-mix(in srgb, ${hue} 14%, transparent)` } : { color: 'var(--ui-text-secondary)', borderColor: stroke } }, l) }
  const filterRow = h('div', { className: 'cockpit-kb-filter' },
    h('span', { className: 'cockpit-kb-total' }, open), h('span', { className: 'text-xs', style: sub }, `open · ${closed} done`), unmatched ? h('span', { className: 'text-xs', style: sub }, `· ${unmatched} other`) : null,
    h('span', { className: 'mx-1', style: sub }, '|'),
    ...allLanes.map(laneChip), lanes.length ? btn('all lanes', () => setLanes([]), { title: 'clear the lane filter' }) : null,
    h('input', { value: text, onChange: (e) => setText(e.target.value), placeholder: 'filter: ticket, title, lane, question', className: 'cockpit-kb-input ml-auto rounded border bg-transparent px-1.5 py-0.5 text-xs', style: { borderColor: stroke } }))
  const strip = q.error && !q.data ? h('div', { className: 'p-3 text-xs', style: { color: DANGER } }, String(q.error.message || q.error))
    : !q.data ? h('div', { className: 'p-6 text-center text-xs', style: sub }, 'loading the board')
    : h('div', { className: 'cockpit-kb-lanes' }, ...byColumn.map(([col, cs]) => h(Column, { key: col.id, column: col, cards: cs, activity: q.data && q.data.ticket_activity, titles: q.data && q.data.ticket_titles, live: q.data && q.data.live, recentHours: q.data && q.data.recent_hours, selected, onOpen: (id) => setSelected(id === selected ? null : id) })))
  return h('div', { className: 'cockpit-kb flex min-h-0 flex-1' },
    h('div', { className: 'flex min-w-0 flex-col', style: { flex: current ? '0 0 54%' : '1 1 auto', borderRight: current ? `1px solid ${stroke}` : 'none', minHeight: 0 } }, filterRow, strip),
    current ? h(Pane, { onClose: () => setSelected(null) }, h(CardPane, { key: current.id, card: current, refresh })) : null)
}

export { Board, splitDone, stackByTicket, RECENT_HOURS }
