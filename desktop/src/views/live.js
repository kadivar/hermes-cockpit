// SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
// SPDX-License-Identifier: AGPL-3.0-or-later
import { useState, useEffect } from 'react'
import { useQuery, CTX, h, sub, mono, stroke, btn, seg, selectBox, ago, thead, trow, Pane, detailHead } from '../lib/sdk.js'
import { RichMd } from '../lib/markdown.js'
import { sortLanes, MODEL_PREFIX } from '../lib/packwords.js'
import { ChatButton } from './chat.js'

// the time of day of a stamp, on this machine's clock: the backend stamps in UTC (…Z), and cutting the digits out of
// the string showed UTC, an hour or more off the wall clock. A stamp that names no zone is shown as it is written.
const clockOf = (ts, digits = 8) => {
  const text = String(ts || ''); const d = new Date(text)
  if (Number.isNaN(d.getTime()) || !/(Z|[+-]\d\d:?\d\d)$/i.test(text)) return text.slice(11, 11 + digits)
  return [d.getHours(), d.getMinutes(), d.getSeconds()].map((n) => String(n).padStart(2, '0')).join(':').slice(0, digits)
}

// ---------- live view: lane run logs (Hermes side) + coding tool transcripts (what the worker prompts and gets back) ----------
const LIVE_COLS = '1rem 5.5rem 1fr 4rem'
const ENTRY_COLOR = { prompt: 'var(--ui-accent)', text: 'var(--ui-text-primary, inherit)', tool_use: 'var(--ui-text-secondary)', tool_result: 'var(--ui-text-tertiary)', thinking: 'var(--ui-text-quaternary)', result: 'var(--ui-success, #2a9d5c)', system: 'var(--ui-text-quaternary)' }
// a stream whose backend fails keeps retrying; say so in its header instead of looking empty
const errText = (e) => String((e && (e.detail || e.message)) || e || 'request failed').slice(0, 300)
const StreamError = ({ err }) => (err ? h('span', { className: 'truncate', style: { color: 'var(--ui-danger, #d33)', maxWidth: '60%' }, title: err }, '⚠ backend error, retrying: ' + err) : null)

function TranscriptEntry({ e, showThinking }) {
    const [open, setOpen] = useState(false)
    if (e.kind === 'thinking' && !showThinking) return null
    const lane = e.src === 'hermes' && e.who ? e.who + ' ' : ''
    const head = lane + (e.kind === 'prompt' ? '› prompt' : e.kind === 'text' ? '◆ ' + (e.model ? e.model.replace(MODEL_PREFIX, '') : 'says') : e.kind === 'tool_use' ? '⚙ ' + (e.name || 'tool') : e.kind === 'tool_result' ? (e.error ? '✗ ' : '↳ ') + (e.name || 'result') : e.kind === 'result' ? '■ result' : e.kind === 'thinking' ? '∴ thinking' : '· ' + e.kind)
    const long = (e.text || '').length > 700 || e.kind === 'tool_result' || e.kind === 'tool_use'
    const rendered = (e.kind === 'text' || e.kind === 'prompt' || e.kind === 'result') && e.html
    const body = e.kind === 'tool_use' ? (open ? e.input : e.summary) : (long && !open ? (e.text || '').slice(0, e.kind === 'tool_result' ? 240 : 700) + (e.text && e.text.length > 240 ? ' [more]' : '') : e.text)
    const meta = e.kind === 'result' ? h('div', { className: 'text-[0.6875rem]', style: sub }, `${e.turns || '?'} turns${e.cost != null ? ' · $' + Number(e.cost).toFixed(3) : ''}${e.duration ? ' · ' + Math.round(e.duration / 1000) + 's' : ''}`) : null
    return h('div', { className: 'grid gap-2 py-1 border-b', style: { gridTemplateColumns: '7.5rem 1fr', borderColor: 'rgba(127,127,127,.12)', opacity: e.side ? .85 : 1 } },
      h('div', { className: 'text-[0.6875rem] truncate', style: { color: ENTRY_COLOR[e.kind] || sub.color, paddingLeft: e.side ? '.75rem' : 0 }, title: (e.agent ? 'subagent ' + e.agent + ' · ' : '') + (e.ts || '') }, (e.side ? '↳ ' : '') + head, e.ts ? h('div', { style: { color: 'var(--ui-text-quaternary)' } }, (e.ticket ? e.ticket + ' · ' : '') + clockOf(e.ts)) : null),
      rendered && (!long || open || e.kind !== 'prompt') ? h('div', { className: 'min-w-0' }, h(RichMd, { className: 'rounded px-2', style: { background: e.kind === 'prompt' ? 'rgba(56,139,253,.08)' : 'transparent', borderLeft: e.kind === 'prompt' ? '2px solid var(--ui-accent)' : 'none' }, html: e.html }), meta)
      : h('div', { className: 'min-w-0' }, h('pre', { className: 'whitespace-pre-wrap text-xs cursor-pointer rounded px-2', style: { ...mono, color: ENTRY_COLOR[e.kind] || 'inherit', margin: 0, background: e.kind === 'tool_result' ? 'rgba(127,127,127,.06)' : 'transparent' }, onClick: () => setOpen(!open), title: long ? 'click to expand / collapse' : '' }, body), meta))
}
function Transcript({ path }) {
  const [err, setErr] = useState('')
  const [entries, setEntries] = useState([]); const [off, setOff] = useState(-1); const [running, setRunning] = useState(false); const [follow, setFollow] = useState(true); const [showThinking, setShowThinking] = useState(false)
  const boxRef = { current: null }
  useEffect(() => { setEntries([]); setOff(-1); setRunning(true) }, [path])
  useEffect(() => {
    let stop = false; let timer = null
    const tick = async () => {
      try { const r = await CTX.rest(`/coding-tail?path=${encodeURIComponent(path)}&offset=${off}`); if (stop) return; setErr('')
        if (r.entries.length) setEntries((xs) => [...xs, ...r.entries].slice(-2500)); setOff(r.offset); setRunning(r.running)
        timer = setTimeout(tick, r.running ? 2000 : 8000)
      } catch (e) { if (!stop) { setErr(errText(e)); timer = setTimeout(tick, 8000) } }
    }
    tick(); return () => { stop = true; if (timer) clearTimeout(timer) }
  }, [path, off])
  useEffect(() => { if (follow && boxRef.current) boxRef.current.scrollTop = boxRef.current.scrollHeight })
  return h('div', { className: 'flex h-full flex-col gap-1' },
    h('div', { className: 'flex items-center gap-2 text-xs' }, h('span', { style: { color: running ? 'var(--ui-success, #2a9d5c)' : sub.color } }, running ? '● live' : '○ finished'), h(StreamError, { err }), h('span', { style: sub }, `${entries.length} entries`),
      h('label', { className: 'ml-auto flex items-center gap-1 cursor-pointer', style: sub }, h('input', { type: 'checkbox', checked: follow, onChange: (e) => setFollow(e.target.checked) }), 'follow'),
      h('label', { className: 'flex items-center gap-1 cursor-pointer', style: sub }, h('input', { type: 'checkbox', checked: showThinking, onChange: (e) => setShowThinking(e.target.checked) }), 'thinking'),
      btn('Reveal', () => CTX.os.revealPath(path))),
    h('div', { ref: (el) => { boxRef.current = el }, className: 'flex-1 overflow-auto rounded border px-2', style: { borderColor: stroke, minHeight: 0 }, onScroll: (e) => { const el = e.target; const atBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 40; if (!atBottom && follow) setFollow(false) } },
      ...entries.map((e, i) => h(TranscriptEntry, { key: i, e, showThinking })), !entries.length ? h('div', { className: 'p-3 text-xs', style: sub }, 'waiting for the first lines') : null))
}
function LaneStream({ card }) {
  const [err, setErr] = useState('')
  const [entries, setEntries] = useState([]); const [last, setLast] = useState(''); const [running, setRunning] = useState(false); const [follow, setFollow] = useState(true)
  const boxRef = { current: null }
  useEffect(() => { setEntries([]); setLast('') }, [card])
  useEffect(() => {
    let stop = false; let timer = null
    const tick = async () => { try { const r = await CTX.rest(`/lane-stream?card=${encodeURIComponent(card)}&since=${encodeURIComponent(last)}`); if (stop) return; setErr('')
        if (r.entries.length) { setEntries((xs) => [...xs, ...r.entries].slice(-1500)); setLast(r.last || last) } setRunning(r.running); timer = setTimeout(tick, r.running ? 2500 : 10000) } catch (e) { if (!stop) { setErr(errText(e)); timer = setTimeout(tick, 10000) } } }
    tick(); return () => { stop = true; if (timer) clearTimeout(timer) }
  }, [card, last])
  useEffect(() => { if (follow && boxRef.current) boxRef.current.scrollTop = boxRef.current.scrollHeight })
  return h('div', { className: 'flex h-full flex-col gap-1' },
    h('div', { className: 'flex items-center gap-2 text-xs' },
      h('span', { style: { color: running ? 'var(--ui-success, #2a9d5c)' : sub.color } }, running ? '● live' : '○ finished'), h(StreamError, { err }),
      h('span', { style: sub }, `${entries.length} entries`), h('label', { className: 'ml-auto flex items-center gap-1 cursor-pointer', style: sub },
      h('input', { type: 'checkbox', checked: follow, onChange: (e) => setFollow(e.target.checked) }), 'follow')),
    h('div', { ref: (el) => { boxRef.current = el }, className: 'flex-1 overflow-auto rounded border px-2', style: { borderColor: stroke, minHeight: 0 }, onScroll: (e) => { const el = e.target; if (el.scrollHeight - el.scrollTop - el.clientHeight > 40 && follow) setFollow(false) } },
      ...entries.map((e, i) => h(TranscriptEntry, { key: i, e, showThinking: false })), !entries.length ? h('div', { className: 'p-3 text-xs', style: sub }, 'no conversation recorded for this card yet') : null))
}
function LaneLog({ path }) {
  const [err, setErr] = useState('')
  const [text, setText] = useState(''); const [off, setOff] = useState(-1); const [running, setRunning] = useState(true); const [follow, setFollow] = useState(true)
  const boxRef = { current: null }
  useEffect(() => { setText(''); setOff(-1); setRunning(true) }, [path])
  useEffect(() => {
    let stop = false; let timer = null
    const tick = async () => { try { const r = await CTX.rest(`/lane-tail?path=${encodeURIComponent(path)}&offset=${off}`); if (stop) return; setErr(''); if (r.text) setText((t) => (t + r.text).slice(-400000)); setOff(r.offset); setRunning(r.running); timer = setTimeout(tick, r.running ? 2000 : 8000) } catch (e) { if (!stop) { setErr(errText(e)); timer = setTimeout(tick, 8000) } } }
    tick(); return () => { stop = true; if (timer) clearTimeout(timer) }
  }, [path, off])
  useEffect(() => { if (follow && boxRef.current) boxRef.current.scrollTop = boxRef.current.scrollHeight })
  return h('div', { className: 'flex h-full flex-col gap-1' },
    h('div', { className: 'flex items-center gap-2 text-xs' },
      h('span', { style: { color: running ? 'var(--ui-success, #2a9d5c)' : sub.color } }, running ? '● live' : '○ finished'), h(StreamError, { err }),
      h('label', { className: 'ml-auto flex items-center gap-1 cursor-pointer', style: sub },
      h('input', { type: 'checkbox', checked: follow, onChange: (e) => setFollow(e.target.checked) }), 'follow'),
      btn('Reveal', () => CTX.os.revealPath(path))),
    h('pre', { ref: (el) => { boxRef.current = el }, className: 'flex-1 overflow-auto whitespace-pre-wrap rounded border p-2 text-xs', style: { ...mono, borderColor: stroke, minHeight: 0 }, onScroll: (e) => { const el = e.target; if (el.scrollHeight - el.scrollTop - el.clientHeight > 40 && follow) setFollow(false) } }, text || 'waiting'))
}
// the newest `n` rows of each lane, in order: one busy lane never pushes the others out of the stream (lane_feed.per_lane)
const perLane = (entries, n) => { const seen = {}; const kept = []; for (let i = entries.length - 1; i >= 0; i--) { const w = entries[i].who || ''; seen[w] = (seen[w] || 0) + 1; if (seen[w] <= n) kept.push(entries[i]) } return kept.reverse() }
function JobStream({ ticket }) {
  const [err, setErr] = useState('')
  const [entries, setEntries] = useState([]); const [last, setLast] = useState(''); const [running, setRunning] = useState(false); const [follow, setFollow] = useState(true); const [who, setWho] = useState('all'); const [offered, setOffered] = useState([]); const [seats, setSeats] = useState(null)
  const boxRef = { current: null }
  useEffect(() => { setEntries([]); setLast(''); setOffered([]) }, [ticket])
  useEffect(() => {
    let stop = false; let timer = null
    const tick = async () => { try { const r = await CTX.rest(`/job-stream?ticket=${encodeURIComponent(ticket)}&since=${encodeURIComponent(last)}`); if (stop) return; setErr('')
        if (r.entries.length) { setEntries((xs) => perLane([...xs, ...r.entries], r.per_lane || 300)); setLast(r.last || last) } if (r.lanes) setOffered(r.lanes); if (r.lane_order) setSeats(r.lane_order); setRunning(r.running); timer = setTimeout(tick, r.running ? 3000 : 10000) } catch (e) { if (!stop) { setErr(errText(e)); timer = setTimeout(tick, 10000) } } }
    tick(); return () => { stop = true; if (timer) clearTimeout(timer) }
  }, [ticket, last])
  useEffect(() => { if (follow && boxRef.current) boxRef.current.scrollTop = boxRef.current.scrollHeight })
  const lanes = sortLanes([...new Set([...offered, ...entries.map((e) => e.who)].filter(Boolean))], seats)
  const shown = entries.filter((e) => who === 'all' || e.who === who)
  const kindColor = (e) => e.src === 'board' ? (e.kind === 'blocked' || e.kind === 'gave_up' || e.kind === 'protocol_violation' ? 'var(--ui-danger, #d33)' : e.kind === 'completed' || e.kind === 'review_requested' ? 'var(--ui-success, #2a9d5c)' : 'var(--ui-text-secondary)') : (ENTRY_COLOR[e.kind] || sub.color)
  return h('div', { className: 'flex h-full flex-col gap-1' },
    h('div', { className: 'flex flex-wrap items-center gap-2 text-xs' }, h('span', { style: { color: running ? 'var(--ui-success, #2a9d5c)' : sub.color } }, running ? '● a lane is working' : '○ idle'), h(StreamError, { err }), h('span', { style: sub }, `${shown.length} events`),
      h('div', { className: 'flex items-center gap-1 rounded border p-0.5', style: { borderColor: stroke } }, seg(who, 'all', 'all lanes', setWho), ...lanes.map((l) => seg(who, l, l, setWho))),
      h('label', { className: 'ml-auto flex items-center gap-1 cursor-pointer', style: sub }, h('input', { type: 'checkbox', checked: follow, onChange: (e) => setFollow(e.target.checked) }), 'follow')),
    h('div', { ref: (el) => { boxRef.current = el }, className: 'flex-1 overflow-auto rounded border px-2', style: { borderColor: stroke, minHeight: 0 }, onScroll: (e) => { const el = e.target; if (el.scrollHeight - el.scrollTop - el.clientHeight > 40 && follow) setFollow(false) } },
      ...shown.map((e, i) => e.src !== 'board' ? h(TranscriptEntry, { key: i, e, showThinking: false })
        : h('div', { key: i, className: 'grid gap-2 py-1 border-b', style: { gridTemplateColumns: '7.5rem 1fr', borderColor: 'rgba(127,127,127,.12)' } },
            h('div', { className: 'text-[0.6875rem]', style: { color: kindColor(e) }, title: e.card }, `▣ ${e.who || 'board'}`, h('div', { style: { color: 'var(--ui-text-quaternary)' } }, (e.ticket ? e.ticket + ' · ' : '') + clockOf(e.ts))),
            h('div', { className: 'min-w-0 text-xs' }, h('span', { style: { color: kindColor(e) } }, e.kind.replace(/_/g, ' ')), h('span', { style: sub }, ` · ${e.title}`), e.html ? h(RichMd, { className: 'rounded px-2', html: e.html }) : null))),
      !shown.length ? h('div', { className: 'p-3 text-xs', style: sub }, 'nothing yet for this job') : null))
}
function Live() {
  const [sub2, setSub2] = useState('all'); const [scope, setScope] = useState('pipeline')
  const jobs = useQuery({ queryKey: ['cockpit', 'jobs'], queryFn: () => CTX.rest('/jobs'), refetchInterval: 10000, retry: 1 })
  const lanes = useQuery({ queryKey: ['cockpit', 'lane-runs'], queryFn: () => CTX.rest('/lane-runs'), refetchInterval: 5000, retry: 1, enabled: sub2 === 'hermes' })
  const cc = useQuery({ queryKey: ['cockpit', 'coding-sessions', scope], queryFn: () => CTX.rest('/coding-sessions?scope=' + scope), refetchInterval: 5000, retry: 1, enabled: sub2 === 'coding' })
  const [job, setJob] = useState('all'); const [sel, setSel] = useState(null)
  const jobList = (jobs.data && jobs.data.jobs) || []; const activeJob = job
  const dot = (on) => h('span', { style: { color: on ? 'var(--ui-success, #2a9d5c)' : 'var(--ui-text-quaternary)' } }, on ? '●' : '○')
  const whenOf = (mtime) => { const n = Number(mtime); if (!Number.isFinite(n) || n <= 0) return ''; const d = new Date(n * 1000); if (Number.isNaN(d.getTime())) return ''; return ago(d.toISOString()) }
  const row = (key, on, who, what, when, item) => trow(LIVE_COLS,
    { key, onClick: () => setSel(sel && sel.path === item.path ? null : item), selected: sel && sel.path === item.path,
    children: [h('div', { key: 'd' }, dot(on)), h('div', { key: 'w', className: 'truncate', style: mono }, who),
    h('div', { key: 't', className: 'truncate', title: what }, what), h('div', { key: 'a', className: 'text-right truncate', style: sub }, when)] })
  const bar = h('div', { className: 'flex items-center gap-3 px-3 py-1.5 border-b text-xs', style: { borderColor: stroke } },
    h('div', { className: 'flex items-center gap-1 rounded border p-0.5', style: { borderColor: stroke } }, seg(sub2, 'all', 'All (one job, every lane)', setSub2), seg(sub2, 'hermes', 'Hermes (lane runs)', setSub2), seg(sub2, 'coding', 'coding tool (transcripts)', setSub2)),
    sub2 === 'all' ? h('div', { className: 'flex items-center gap-1' }, h('span', { style: sub }, 'job:'), selectBox(activeJob || 'all', setJob, [['all', `all jobs (${jobList.length})`], ...jobList.map((j) => [j.ticket, `${j.ticket} · ${ago(j.last)} ago`])], { style: mono })) : null,
    sub2 === 'coding' ? h('div', { className: 'ml-auto flex items-center gap-1 rounded border p-0.5', style: { borderColor: stroke } }, seg(scope, 'pipeline', 'pipeline', setScope), seg(scope, 'all', 'all sessions', setScope)) : null)
  if (sub2 === 'all') return h('div', { className: 'flex min-h-0 flex-1 flex-col' }, bar, jobList.length || activeJob !== 'all' ? h('div', { className: 'min-h-0 flex-1 p-3' }, h(JobStream, { ticket: activeJob })) : h('div', { className: 'p-6 text-center text-xs', style: sub }, 'No job on the board yet. Kick one off from the Inbox.'))
  const laneRows = (lanes.data && lanes.data.runs) || []; const ccRows = (cc.data && cc.data.sessions) || []
  const list = sub2 === 'hermes'
    ? h('div', { className: 'cockpit-scroll flex min-w-0 flex-col overflow-auto', style: { flex: sel ? '0 0 40%' : '1 1 auto', borderRight: sel ? `1px solid ${stroke}` : 'none' } }, thead(LIVE_COLS, ['', 'lane', 'card (run log)', '>age']),
        ...laneRows.map((r) => row('l' + (r.card || r.lane || ''), r.running, r.assignee || r.lane || '?', `${r.title || r.card || ''} · ${r.status || ''}`, whenOf(r.mtime), { kind: 'lane', path: r.path || '', card: r.card || '', label: r.title || r.card || '', transcript: r.transcript || '' })), !laneRows.length ? h('div', { className: 'p-3 text-xs', style: sub }, 'no lane runs yet') : null)
    : h('div', { className: 'cockpit-scroll flex min-w-0 flex-col overflow-auto', style: { flex: sel ? '0 0 40%' : '1 1 auto', borderRight: sel ? `1px solid ${stroke}` : 'none' } }, thead(LIVE_COLS, ['', 'ticket', 'session (first prompt)', '>age']),
        ...ccRows.flatMap((s) => [row('c' + s.id, s.running, s.ticket || (s.dir || '').split('-').slice(-2).join('-'), (s.prompt || '(no prompt yet)').replace(/\s+/g, ' '), whenOf(s.mtime), { kind: 'coding', path: s.path, label: s.id, ticket: s.ticket || '', session: s.id }),
          ...(s.subagents || []).map((a) => trow(LIVE_COLS, { key: 'a' + a.name,
            onClick: () => setSel(sel && sel.path === a.path ? null : { kind: 'coding', path: a.path, label: a.name }), selected: sel && sel.path === a.path,
            children: [h('div', { key: 'd' }, ''), h('div', { key: 'w', style: { ...mono, ...sub } }, '↳ advisor'),
            h('div', { key: 't', className: 'truncate', style: sub }, a.name),
            h('div', { key: 'a', className: 'text-right', style: sub }, whenOf(a.mtime))] }))]),
        !ccRows.length ? h('div', { className: 'p-3 text-xs', style: sub }, scope === 'pipeline' ? 'No coding tool sessions in the worktrees yet (worker runs persist them from now on).' : 'No sessions.') : null)
  return h('div', { className: 'flex min-h-0 flex-1 flex-col' }, bar, h('div', { className: 'flex min-h-0 flex-1' }, list,
    sel ? h(Pane, { onClose: () => setSel(null) }, h(LaneDetail, { sel })) : null))
}
function LaneDetail({ sel }) {
  // a lane whose coding tool keeps its own transcript (providers.coding.lane_transcript_glob) opens on that session
  const [raw, setRaw] = useState(null)
  useEffect(() => setRaw(null), [sel.card])
  const mode = raw === 'transcript' || (raw === null && sel.transcript) ? 'transcript' : raw === true ? 'raw' : 'conv'
  if (sel.kind !== 'lane') return h('div', { className: 'min-w-0 flex-1 flex flex-col gap-2 p-3', style: { minHeight: 0 } }, detailHead(sel.label, null, 'coding tool transcript'),
    sel.ticket && sel.session ? h('div', { className: 'flex items-center gap-2 text-xs' }, h(ChatButton, { ticket: sel.ticket, from: sel.session }), h('span', { style: sub }, 'an interactive coding tool with this run\'s context; one chat per ticket, kept until the flow ends')) : null,
    h(Transcript, { path: sel.path }))
  return h('div', { className: 'min-w-0 flex-1 flex flex-col gap-2 p-3', style: { minHeight: 0 } },
    h('div', { className: 'flex items-baseline gap-2' }, h('div', { className: 'font-medium text-sm' }, sel.label),
      h('div', { className: 'ml-auto flex items-center gap-1 rounded border p-0.5', style: { borderColor: stroke } },
      sel.transcript ? seg(mode, 'transcript', 'agent session', () => setRaw('transcript')) : null, seg(mode, 'conv', 'conversation', () => setRaw(false)),
      seg(mode, 'raw', 'raw run log', () => setRaw(true)))),
    mode === 'transcript' ? h(Transcript, { path: sel.transcript }) : mode === 'raw' ? h(LaneLog, { path: sel.path }) : h(LaneStream, { card: sel.card }))
}

export { clockOf, Live, perLane, Transcript, TranscriptEntry, LaneStream, LaneLog, JobStream, LaneDetail, LIVE_COLS, ENTRY_COLOR }
