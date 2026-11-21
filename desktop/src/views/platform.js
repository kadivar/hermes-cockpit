// SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
// SPDX-License-Identifier: AGPL-3.0-or-later
import { useState, useEffect, useMemo, useRef } from 'react'
import { host, useQuery, useQueryClient, CTX, h, sub, mono, stroke, btn, seg, ago, post, closeBtn, Pane, detailHead, BriefGrid, Section, openWeb } from '../lib/sdk.js'
import { RichMd } from '../lib/markdown.js'
import { DiffView } from '../lib/diff.js'
import { AdvisoriesTab } from './advisories.js'

// ---------- Platform: the map of what the platform does (areas → features, cross-cutting components) and what landed on the base branch per node ----------
const RANGE_LABEL = { 1: '24 h', 7: '1 week', 14: '2 weeks', 30: '1 month' }
function changeLabel(c) {
  if (c && typeof c.verdict === 'string' && String(c.verdict).trim()) return c.verdict
  if (c && c.verdict && c.verdict.user_change) return c.verdict.user_change
  return (c && c.title) || ''
}
function fileOf(f) {
  if (typeof f === 'string') return f
  return (f && (f.path || f.filename)) || ''
}
const STATUS_MARK = { explained: ['● changed a user flow', 'var(--ui-accent)'], pending: ['◔ analyst reading', 'var(--ui-warning, #c98a00)'], unmapped: ['? unmapped area', 'var(--ui-warning, #c98a00)'], noise: ['· no flow change', 'var(--ui-text-tertiary)'], skipped: ['· skipped', 'var(--ui-text-quaternary)'] }
function ChangeModal({ repo, number, byId, onClose, onSeen, onUnseen }) {
  useEffect(() => { window.__cockpitModalOpen = true; return () => { window.__cockpitModalOpen = false } }, [])
  const qc = useQueryClient()
  const q = useQuery({ queryKey: ['cockpit', 'platform-change', repo, number], queryFn: () => CTX.rest(`/platform-change?repo=${encodeURIComponent(repo)}&number=${number}`), retry: 0 })
  const c = q.data
  const verdictText = c && typeof c.verdict === 'string' ? c.verdict : ''
  const [text, setText] = useState(verdictText)
  const [busy, setBusy] = useState(false)
  useEffect(() => { const k = (e) => { if (e.key === 'Escape') onClose() }; window.addEventListener('keydown', k); return () => window.removeEventListener('keydown', k) }, [])
  useEffect(() => { setText(verdictText) }, [verdictText])
  const v = (c && c.verdict && typeof c.verdict === 'object') ? c.verdict : {}
  const saveVerdict = async () => {
    setBusy(true)
    try {
      await post('/platform-verdict', { repo, number, text })
      qc.invalidateQueries({ queryKey: ['cockpit', 'platform-change', repo, number] })
      qc.invalidateQueries({ queryKey: ['cockpit', 'platform'] })
    } catch (e) { host.notifyError(e, 'verdict failed') } finally { setBusy(false) }
  }
  const title = (id) => (byId[id] && byId[id].title) || id
  return h('div', { role: 'presentation', onClick: onClose, style: { position: 'fixed', inset: 0, zIndex: 1000, background: 'rgba(0,0,0,.72)', display: 'flex', alignItems: 'center', justifyContent: 'center', padding: '3vh 3vw' } },
    h('div', { role: 'presentation', onClick: (e) => e.stopPropagation(), className: 'rounded-lg border flex flex-col text-xs', style: { borderColor: stroke, background: 'var(--ui-bg-elevated, #1e1e1e)', width: '94vw', height: '94vh', overflow: 'hidden' } },
      h('div', { className: 'flex items-center gap-2 px-3 py-1.5', style: { borderBottom: `1px solid ${stroke}` } },
        h('span', { className: 'font-medium text-sm' }, `${repo} #${number}`), c ? h('span', { className: 'truncate' }, c.title) : null, c ? h('span', { style: sub }, `${c.author} · merged ${ago(c.merged_at)} ago`) : null,
        h('span', { className: 'ml-auto flex items-center gap-1' }, c ? btn('PR on the forge', () => openWeb(c.url)) : null, c && !c.seen ? btn('Mark as seen', onSeen, { accent: true }) : null, c && c.seen ? btn('Undo seen', onUnseen) : null, btn('✕ close', onClose))),
      h('div', { className: 'flex-1 overflow-auto p-3 flex flex-col gap-2' },
        !c ? h('div', { style: sub }, q.error ? String(q.error.message || q.error) : 'loading') : [
          h(Section, { key: 'b', title: 'Brief', open: true, color: 'var(--ui-accent)' }, typeof c.verdict === 'string' ? h(BriefGrid, { fields: [
            { label: 'Verdict', text: c.verdict },
            { label: 'Status', text: (STATUS_MARK[c.status] || [c.status])[0], color: (STATUS_MARK[c.status] || [])[1] },
            { label: 'Areas', items: (c.nodes || []).map(title) }] }) : c.verdict ? h(BriefGrid, { fields: [
            { label: 'User change', text: v.user_change },
            { label: 'Flow changed', text: v.flow_changed ? 'yes' : 'no: behaviour kept (refactor, copy, style or tooling)', color: v.flow_changed ? 'var(--ui-accent)' : 'var(--ui-text-tertiary)' },
            { label: 'Areas', items: (c.nodes || []).map(title) },
            { label: 'Risk', text: v.risk, color: v.risk === 'high' ? 'var(--ui-danger, #d33)' : v.risk === 'medium' ? 'var(--ui-warning, #c98a00)' : undefined },
            { label: 'Why it matters', text: v.why_it_matters },
            { label: 'Look at', items: v.notes || [] }] }) : h(BriefGrid, { fields: [
            { label: 'Status', text: (STATUS_MARK[c.status] || [c.status])[0] + (c.reason ? ' · ' + c.reason : ''), color: (STATUS_MARK[c.status] || [])[1] },
            { label: 'Areas', items: (c.nodes || []).map(title) },
            { label: 'Files', text: `${c.files_n || (c.files || []).length} files · ${(c.functional || []).length} functional` + ((c.unmapped || []).length ? ` · ${c.unmapped.length} unmapped` : '') },
            c.card ? { label: 'Analyst', text: `card ${c.card} is reading the diff` } : { label: '', text: '' }] })),
          h('div', { key: 'verdict', className: 'flex flex-col gap-1' },
            h('div', { className: 'cockpit-head' }, 'Analyst verdict'),
            h('textarea', { value: text, onChange: (e) => setText(e.target.value), rows: 3, className: 'rounded border bg-transparent px-2 py-1', style: { borderColor: stroke, resize: 'vertical' } }),
            h('div', null, h('button', { type: 'button', disabled: busy || !String(text).trim(), onClick: saveVerdict, className: 'rounded px-2.5 py-0.5 text-xs font-medium disabled:opacity-40', style: { background: 'var(--ui-accent)', color: '#fff' } }, busy ? 'saving…' : 'Save verdict'))),
          h(Section, { key: 'f', title: `Files by area (${(c.functional || []).length} functional of ${(c.files || []).length})` }, h('div', { className: 'flex flex-col gap-0.5' }, ...(c.files || []).map((f) => { const path = fileOf(f); const row = typeof f === 'string' ? {} : (f || {}); const ids = (c.attribution || {})[path]; const fn = (c.functional || []).includes(path)
            return h('div', { key: path, className: 'flex gap-2' },
              h('span', { style: { ...mono, color: fn ? undefined : 'var(--ui-text-quaternary)' } }, path),
              row.add == null ? null : h('span', { style: { color: '#2ea043' } }, `+${row.add}`),
              row.del_ == null ? null : h('span', { style: { color: '#f85149' } }, `−${row.del_}`),
              h('span', { style: sub }, fn ? (ids && ids.length ? ids.map(title).join(', ') : 'unmapped') : 'not functional')) }))),
          h(Section, { key: 'd', title: 'PR description' }, h(RichMd, { html: c.body_html })),
          h(Section, { key: 'x', title: 'Diff (from the forge)' }, c.diff && c.diff.diff ? h(DiffView, { data: c.diff }) : h('div', { style: sub }, (c.diff && c.diff.note) || 'no diff'))])))
}
function layoutMap(nodes) {
  const W = 1200, H = 820, cx = W / 2, cy = H / 2
  const areas = nodes.filter((n) => n.kind === 'area'); const comps = nodes.filter((n) => n.kind === 'component'); const pos = {}
  comps.forEach((c, i) => { const a = -Math.PI / 2 + i * 2 * Math.PI / Math.max(1, comps.length); const r = comps.length > 12 ? 150 : 125; pos[c.id] = { x: cx + r * Math.cos(a), y: cy + r * Math.sin(a), a } })
  areas.forEach((ar, i) => { const a = -Math.PI / 2 + i * 2 * Math.PI / Math.max(1, areas.length); const R = 300
    pos[ar.id] = { x: cx + R * Math.cos(a), y: cy + R * Math.sin(a), a }
    const fs = nodes.filter((n) => n.parent === ar.id); const spread = Math.min(0.5, 0.075 * fs.length); const r2 = R + 92
    fs.forEach((f, j) => { const t = fs.length === 1 ? a : a - spread + j * (2 * spread) / (fs.length - 1); pos[f.id] = { x: cx + r2 * Math.cos(t), y: cy + r2 * Math.sin(t), a: t } }) })
  return { W, H, pos }
}
function MapGraph({ nodes, byId, counts, inherited, onPick, picked }) {
  const { W, H, pos } = useMemo(() => layoutMap(nodes), [nodes])
  const [hover, setHover] = useState(null); const [vb, setVb] = useState({ x: 0, y: 0, w: W, h: H }); const drag = useRef(null)
  const unseen = (id) => ((counts[id] || {}).unseen || 0) + ((inherited[id] || {}).unseen || 0)
  const total = (id) => ((counts[id] || {}).total || 0) + ((inherited[id] || {}).total || 0)
  const edges = []
  for (const n of nodes) { if (n.kind === 'feature') { edges.push({ a: n.parent, b: n.id, kind: 'spoke' }); for (const dep of n.depends || []) if (pos[dep]) edges.push({ a: n.id, b: dep, kind: 'dep' }) } }
  const focus = hover || picked
  const related = new Set(focus ? [focus, ...edges.filter((e) => e.a === focus || e.b === focus).flatMap((e) => [e.a, e.b])] : [])
  const lit = (id) => !focus || related.has(id)
  const onWheel = (e) => { e.preventDefault(); const k = e.deltaY > 0 ? 1.12 : 1 / 1.12; const r = e.currentTarget.getBoundingClientRect(); const mx = vb.x + (e.clientX - r.left) / r.width * vb.w, my = vb.y + (e.clientY - r.top) / r.height * vb.h
    const w = Math.min(W * 2, Math.max(W / 4, vb.w * k)), h = w * H / W; setVb({ x: mx - (mx - vb.x) * w / vb.w, y: my - (my - vb.y) * h / vb.h, w, h }) }
  const onDown = (e) => { drag.current = { x: e.clientX, y: e.clientY, vb } }
  const onMove = (e) => { if (!drag.current) return; const r = e.currentTarget.getBoundingClientRect(); const dx = (e.clientX - drag.current.x) / r.width * drag.current.vb.w, dy = (e.clientY - drag.current.y) / r.height * drag.current.vb.h; setVb({ ...drag.current.vb, x: drag.current.vb.x - dx, y: drag.current.vb.y - dy }) }
  const onUp = () => { drag.current = null }
  const zoom = W / vb.w
  const label = (n, p, size, dy, always) => (always || zoom > 1.6 || related.has(n.id)) ? h('text', { x: p.x, y: p.y + dy, textAnchor: 'middle', fontSize: size, fill: 'var(--ui-text-primary, #ddd)', style: { pointerEvents: 'none', opacity: lit(n.id) ? 1 : 0.25 } }, n.title.length > 30 && size < 12 ? n.title.slice(0, 28) + '…' : n.title) : null
  const glow = (p, r, id) => unseen(id) ? [h('circle', { key: 'g' + id, cx: p.x, cy: p.y, r: r + 5, fill: 'none', stroke: 'var(--ui-accent)', strokeWidth: 2, className: 'cockpit-glow' }), h('circle', { key: 'h' + id, cx: p.x, cy: p.y, r: r + 2, fill: 'var(--ui-accent)', opacity: 0.18 })] : null
  const badge = (p, r, id) => unseen(id) ? h('g', { key: 'b' + id }, h('circle', { cx: p.x + r * 0.8, cy: p.y - r * 0.8, r: 8, fill: 'var(--ui-accent)' }), h('text', { x: p.x + r * 0.8, y: p.y - r * 0.8 + 3.5, textAnchor: 'middle', fontSize: 10, fontWeight: 700, fill: '#fff', style: { pointerEvents: 'none' } }, unseen(id))) : null
  const shape = (n) => { const p = pos[n.id]; if (!p) return null; const r = n.kind === 'area' ? 26 : n.kind === 'component' ? 15 : (total(n.id) ? 7 : 5.5)
    const fill = n.kind === 'area' ? 'var(--ui-bg-elevated, #22272e)' : n.kind === 'component' ? 'rgba(201,138,0,.22)' : total(n.id) ? 'var(--ui-accent)' : 'rgba(127,127,127,.45)'
    const stroke = n.kind === 'area' ? 'var(--ui-accent)' : n.kind === 'component' ? 'var(--ui-warning, #c98a00)' : 'rgba(127,127,127,.6)'
    return h('g', { key: n.id, style: { cursor: 'pointer', opacity: lit(n.id) ? 1 : 0.22, transition: 'opacity .15s' }, onMouseEnter: () => setHover(n.id), onMouseLeave: () => setHover(null), onClick: (e) => { e.stopPropagation(); onPick(n.id) } },
      glow(p, r, n.id),
      n.kind === 'component' ? h('rect', { x: p.x - r, y: p.y - r, width: 2 * r, height: 2 * r, rx: 5, fill, stroke, strokeWidth: 1.5, transform: `rotate(45 ${p.x} ${p.y})` }) : h('circle', { cx: p.x, cy: p.y, r, fill, stroke, strokeWidth: n.kind === 'area' ? 2 : 1.2 }),
      n.kind === 'area' ? h('text', { x: p.x, y: p.y + 4, textAnchor: 'middle', fontSize: 11, fontWeight: 600, fill: 'var(--ui-text-primary, #ddd)', style: { pointerEvents: 'none' } }, n.title.split(' (')[0]) : null,
      n.kind === 'component' ? label(n, p, 9.5, r + 12, true) : null,
      n.kind === 'feature' ? label(n, p, 8.5, -(r + 4), total(n.id) > 0) : null,
      badge(p, r, n.id)) }
  return h('div', { className: 'relative h-full w-full', style: { background: 'radial-gradient(ellipse at center, rgba(56,139,253,.07), transparent 60%)' } },
    h('svg', { viewBox: `${vb.x} ${vb.y} ${vb.w} ${vb.h}`, style: { width: '100%', height: '100%', display: 'block', cursor: drag.current ? 'grabbing' : 'grab' }, onWheel, onMouseDown: onDown, onMouseMove: onMove, onMouseUp: onUp, onMouseLeave: onUp, role: 'presentation', onClick: () => onPick(null) },
      h('defs', null, h('filter', { id: 'ppsoft' }, h('feGaussianBlur', { stdDeviation: 1.2 }))),
      h('circle', { cx: W / 2, cy: H / 2, r: 300, fill: 'none', stroke: 'rgba(127,127,127,.15)', strokeDasharray: '3 5' }),
      h('circle', { cx: W / 2, cy: H / 2, r: nodes.filter((n) => n.kind === 'component').length > 12 ? 150 : 125, fill: 'none', stroke: 'rgba(201,138,0,.18)', strokeDasharray: '3 5' }),
      ...edges.map((e, i) => { const a = pos[e.a], b = pos[e.b]; if (!a || !b) return null; const on = focus && (e.a === focus || e.b === focus)
        return h('line', { key: i, x1: a.x, y1: a.y, x2: b.x, y2: b.y, stroke: on ? 'var(--ui-accent)' : e.kind === 'dep' ? 'rgba(201,138,0,.55)' : 'rgba(127,127,127,.5)', strokeWidth: on ? 1.6 : e.kind === 'dep' ? 0.6 : 0.8, opacity: on ? 0.95 : focus ? 0.06 : e.kind === 'dep' ? 0.22 : 0.35 }) }),
      ...nodes.filter((n) => n.kind === 'feature').map(shape), ...nodes.filter((n) => n.kind === 'component').map(shape), ...nodes.filter((n) => n.kind === 'area').map(shape)),
    h('div', { className: 'absolute left-2 bottom-2 flex items-center gap-3 text-[0.6875rem]', style: sub },
      h('span', null, h('span', { style: { color: 'var(--ui-accent)' } }, '●'), ' area'), h('span', null, h('span', { style: { color: 'var(--ui-warning, #c98a00)' } }, '◆'), ' cross-cutting component'), h('span', null, '· feature'), h('span', null, h('span', { style: { color: 'var(--ui-accent)' } }, '◎'), ' unread changes'), h('span', null, 'wheel zooms · drag pans · hover shows relations')))
}
// the in-canvas card: only the Brief of the picked node and its unread changes; "Details" selects it in the column and opens the full pane
function MapPopover({ node, byId, changes, onDetails, onClose, onOpenChange, onRead, base = 'the base branch' }) {
  const title = (id) => (byId[id] && byId[id].title) || id
  const unread = changes.filter((c) => !c.seen && c.status !== 'skipped')
  return h('div', { className: 'absolute rounded-lg border text-xs flex flex-col gap-2 p-3', style: { right: '1rem', top: '1rem', width: '26rem', maxHeight: 'calc(100% - 2rem)', overflow: 'auto', background: 'var(--ui-bg-elevated, #1e1e1e)', borderColor: 'var(--ui-accent)', boxShadow: '0 8px 30px rgba(0,0,0,.45)' }, role: 'presentation', onClick: (e) => e.stopPropagation() },
    h('div', { className: 'flex items-start gap-2' },
      h('div', { className: 'min-w-0 flex-1' }, h('div', { className: 'font-medium text-sm leading-tight' }, node.title), h('div', { className: 'cockpit-head' }, node.kind + (unread.length ? ` · ${unread.length} unread` : ''))),
      h('span', { className: 'flex items-center gap-1 shrink-0' },
        unread.length ? h('button', { type: 'button', onClick: () => onRead(unread), title: `mark the ${unread.length} unread change(s) of this node as read`, className: 'rounded px-1.5 py-0.5 text-xs', style: { border: `1px solid ${stroke}`, color: 'var(--ui-accent)' } }, '✓ read') : null,
        h('button', { type: 'button', onClick: onDetails, title: 'select it in the map column and open the full view', className: 'rounded px-2 py-0.5 text-xs font-medium', style: { background: 'var(--ui-accent)', color: '#fff' } }, 'Details'),
        closeBtn(onClose))),
    h(BriefGrid, { fields: [
      { label: node.kind === 'feature' ? 'User does' : 'Summary', text: node.user || node.summary },
      { label: 'HLD role', text: node.hld },
      { label: node.kind === 'component' ? 'Used by' : 'Depends on', items: (node.kind === 'component' ? node.used_by : node.depends || []).map(title) }] }),
    changes.length ? h('div', { className: 'flex flex-col gap-1' }, h('div', { className: 'cockpit-head' }, `changes on ${base} (${changes.length})`), ...changes.slice(0, 8).map((c) => h('div', { key: c.repo + c.number, className: 'flex items-center gap-2 cockpit-row rounded px-1 cursor-pointer', onClick: () => onOpenChange(c) },
      !c.seen && c.status !== 'skipped' ? h('span', { style: { color: 'var(--ui-accent)' } }, '●') : h('span', { style: sub }, '·'),
        h('span', { style: mono }, `${c.repo} #${c.number}`), h('span', { className: 'truncate', title: c.title }, changeLabel(c)),
        h('span', { className: 'ml-auto whitespace-nowrap', style: { color: (STATUS_MARK[c.status] || [])[1] } }, (STATUS_MARK[c.status] || [c.status])[0]))),
      changes.length > 8 ? h('div', { style: sub }, `… ${changes.length - 8} more in Details`) : null) : h('div', { style: sub }, `no changes on ${base} in this window`))
}
// the anchors card: the anchor list (default) or, on its second tab, what changed on the base branch under those anchors in the window
function AnchorsCard({ node, root, days, base = 'the base branch' }) {
  const [tab, setTab] = useState('anchors')
  return h('div', { className: 'flex flex-col gap-2' },
    h('div', { className: 'flex items-center gap-1 self-start rounded border p-0.5', style: { borderColor: stroke } }, seg(tab, 'anchors', 'Anchors', setTab), seg(tab, 'diff', `Diff on ${base} (${RANGE_LABEL[days] || days + ' days'})`, setTab)),
    tab === 'anchors' ? h('div', { className: 'flex flex-col gap-1' },
      ...node.anchors.map((a, i) => h('div', { key: i }, h('div', { className: 'font-medium', style: mono }, a.repo),
      ...a.paths.map((pth) => h('div', { key: pth, className: 'flex items-center gap-2 pl-2' }, h('span', { style: mono }, pth),
      btn('Reveal', () => CTX.os.revealPath(`${root}/${a.repo}/${pth.replace(/\*.*$/, '')}`)))),
      a.key && a.key.length ? h('div', { className: 'pl-2', style: sub }, 'key: ' + a.key.join(', ')) : null)))
      : h(NodeDiff, { id: node.id, days, base }))
}
function NodeDiff({ id, days, base = 'the base branch' }) {
  const q = useQuery({ queryKey: ['cockpit', 'platform-node-diff', id, days], queryFn: () => CTX.rest(`/platform-node-diff?id=${encodeURIComponent(id)}&days=${days}`), staleTime: 300000, retry: 0 })
  if (q.isLoading) return h('div', { className: 'text-xs', style: sub }, `fetching origin/${base} and reading the diff under the anchors…`)
  if (q.error) return h('div', { className: 'text-xs', style: { color: 'var(--ui-danger, #d33)' } }, String(q.error.message || q.error))
  const repos = (q.data && q.data.repos) || []
  return h('div', { className: 'flex flex-col gap-3' }, ...repos.map((r) => h('div', { key: r.repo, className: 'flex flex-col gap-1' },
    h('div', { className: 'text-xs font-medium', style: mono }, r.repo),
    r.error ? h('div', { className: 'text-xs', style: { color: 'var(--ui-warning, #c98a00)' } }, r.error)
      : (r.commits || []).length || r.diff ? h(DiffView, { data: r }) : h('div', { className: 'text-xs', style: sub }, 'nothing changed under these anchors in the window'))))
}
function Platform() {
  const qc = useQueryClient()
  const [days, setDaysRaw] = useState(() => { try { return Number(CTX.storage.get('platformDays', 1)) || 1 } catch (e) { return 1 } }); const setDays = (v) => { setDaysRaw(v); try { CTX.storage.set('platformDays', v) } catch (e) {} }
  const q = useQuery({ queryKey: ['cockpit', 'platform', days], queryFn: () => CTX.rest('/platform?days=' + days), refetchInterval: 30000, retry: 1 })
  const aq = useQuery({ queryKey: ['cockpit', 'advisories'], queryFn: () => CTX.rest('/advisories'), refetchInterval: 180000, retry: 0 })
  const [sel, setSel] = useState(null); const [picked, setPicked] = useState(null); const [mode, setMode] = useState('tree'); const [showAll, setShowAll] = useState(false); const [openChange, setOpenChange] = useState(null); const [busy, setBusy] = useState(false)
  useEffect(() => { const k = (e) => { if (e.key === 'Escape' && !window.__cockpitModalOpen && picked) setPicked(null) }; window.addEventListener('keydown', k); return () => window.removeEventListener('keydown', k) }, [picked])
  const [collapsed, setCollapsed] = useState(() => { try { return new Set(CTX.storage.get('platformCollapsed', [])) } catch (e) { return new Set() } })
  if (q.isLoading) return h('div', { className: 'p-3 text-xs', style: sub }, 'loading')
  if (q.error) return h('div', { className: 'p-3 text-xs', style: { color: 'var(--ui-danger, #d33)' } }, String(q.error.message || q.error))
  const d = q.data; const base = d.base || 'the base branch'; const map = d.map && !Array.isArray(d.map) ? d.map : { nodes: [] }; const nodes = map.nodes || []; const byId = Object.fromEntries(nodes.map((n) => [n.id, n])); const counts = d.counts || {}; const inh = (d.inherited && !Array.isArray(d.inherited)) ? d.inherited : {}
  const areas = nodes.filter((n) => n.kind === 'area'); const comps = nodes.filter((n) => n.kind === 'component')
  const refresh = () => qc.invalidateQueries({ queryKey: ['cockpit', 'platform'] })
  const toggle = (id) => { const n = new Set(collapsed); n.has(id) ? n.delete(id) : n.add(id); setCollapsed(n); try { CTX.storage.set('platformCollapsed', [...n]) } catch (e) {} }
  const badge = (id) => { const a = counts[id] || { total: 0, unseen: 0 }; const b = inh[id] || { total: 0, unseen: 0 }; const unseen = a.unseen + (b.unseen || 0); const total = a.total + (b.total || 0)
    return total ? h('span', { className: 'ml-auto flex items-center gap-1' }, unseen ? h('span', { className: 'rounded-full px-1.5 text-[0.6875rem] font-medium', style: { background: 'var(--ui-accent)', color: '#fff' } }, unseen) : null, h('span', { className: 'text-[0.6875rem]', style: sub }, `${total}`)) : null }
  const nodeRow = (n, depth) => h('div', { key: n.id, className: 'flex items-center gap-1.5 cockpit-row rounded px-1 py-0.5 cursor-pointer', onClick: () => { setSel(n.id); setMode('tree') }, style: { paddingLeft: `${depth * 1.1 + 0.25}rem`, background: sel === n.id ? 'var(--ui-bg-selected, rgba(127,127,127,.15))' : 'transparent' } },
    n.kind !== 'feature' ? h('span', { onClick: (e) => { e.stopPropagation(); toggle(n.id) }, style: sub }, collapsed.has(n.id) ? '▸' : '▾') : h('span', { style: { color: 'var(--ui-text-quaternary)' } }, '·'),
    h('span', { className: n.kind === 'feature' ? '' : 'font-medium' }, n.title), badge(n.id))
  const tree = h('div', { className: 'flex flex-col text-xs' },
    ...areas.flatMap((a) => [nodeRow(a, 0), ...(collapsed.has(a.id) ? [] : nodes.filter((n) => n.parent === a.id).map((f) => nodeRow(f, 1)))]),
    comps.length ? nodeRow({ id: 'components', kind: 'area', title: 'Cross-cutting components' }, 0) : null,
    ...(collapsed.has('components') ? [] : comps.map((c) => nodeRow(c, 1))))
  const cutoff = new Date(Date.now() - days * 86400000).toISOString()
  const inWindow = (d.changes || []).filter((c) => (c.merged_at || '') >= cutoff)
  const unseenN = inWindow.filter((c) => c.status !== 'skipped' && !c.seen).length
  const relevant = inWindow.filter((c) => showAll || c.status !== 'skipped')
  const changeRow = (c) => { const m = STATUS_MARK[c.status] || [c.status, undefined]
    return h('div', { key: c.repo + c.number, className: 'grid gap-2 cockpit-row rounded px-1 py-0.5 cursor-pointer items-center', style: { gridTemplateColumns: '5.5rem 9rem 1fr 10rem 6rem', opacity: c.seen && c.status !== 'pending' ? 0.75 : 1 }, onClick: () => setOpenChange({ repo: c.repo, number: c.number }) },
      h('span', { style: sub }, (c.merged_at || '').slice(5, 16).replace('T', ' ')), h('span', { style: mono }, `${c.repo} #${c.number}`), h('span', { className: 'truncate', title: c.title }, !c.seen && c.status !== 'skipped' ? h('span', { style: { color: 'var(--ui-accent)' } }, '● ') : null, changeLabel(c)),
      h('span', { className: 'truncate', style: sub }, (c.nodes || []).map((id) => (byId[id] && byId[id].title) || id).join(', ') || c.reason || ''),
        h('span', { className: 'flex items-center gap-1', style: { color: m[1] } }, m[0],
        !c.seen && c.status !== 'skipped' ? h('button', { type: 'button', onClick: (e) => { e.stopPropagation(); markRead([c]) }, title: 'mark as read',
        className: 'rounded px-1 text-[0.6875rem]', style: { border: `1px solid ${stroke}`, color: 'var(--ui-accent)' } }, '✓') : null,
        c.seen ? h('button', { type: 'button', onClick: (e) => { e.stopPropagation(); markUnread([c]) }, title: 'undo seen',
        className: 'rounded px-1 text-[0.6875rem]', style: { border: `1px solid ${stroke}` } }, 'undo') : null)) }
  const markRead = async (cs) => { try { for (const c of cs) await post('/platform-seen', { repo: c.repo, number: c.number }); refresh() } catch (e) { host.notifyError(e, 'failed') } }
  const markUnread = async (cs) => { try { for (const c of cs) await post('/platform-unseen', { repo: c.repo, number: c.number }); refresh() } catch (e) { host.notifyError(e, 'undo seen failed') } }
  const node = sel ? byId[sel] : null
  const changesOf = (n) => n ? inWindow.filter((c) => (c.nodes || []).includes(n.id) || (n.kind === 'feature' && (c.nodes || []).some((id) => (n.depends || []).includes(id))) || (n.kind === 'area' && (c.nodes || []).some((id) => byId[id] && byId[id].parent === n.id))).filter((c) => c.status !== 'skipped') : []
  const nodeChanges = node ? inWindow.filter((c) => (c.nodes || []).includes(node.id) || (node.kind === 'feature' && (c.nodes || []).some((id) => (node.depends || []).includes(id))) || (node.kind === 'area' && (c.nodes || []).some((id) => byId[id] && byId[id].parent === node.id))) : []
  const detail = node ? h('div', { className: 'flex flex-col gap-2 p-3 text-xs' },
      detailHead(node.title, { text: node.kind, color: 'var(--ui-accent)' }, node.parent && byId[node.parent] ? byId[node.parent].title : node.kind === 'component' ? 'cross-cutting' : ''),
      h(Section, { title: 'Brief', open: true, color: 'var(--ui-accent)' }, h(BriefGrid, { fields: [
        { label: node.kind === 'feature' ? 'User does' : 'Summary', text: node.user || node.summary },
        { label: 'HLD role', text: node.hld },
        { label: 'LLD', text: node.lld },
        { label: node.kind === 'component' ? 'Used by' : 'Depends on', items: (node.kind === 'component' ? node.used_by : node.depends || []).map((id) => (byId[id] && byId[id].title) || id) }] })),
      (node.anchors || []).length ? h(Section, { title: `Code anchors (${node.anchors.reduce((n, a) => n + a.paths.length, 0)})`, open: true }, h(AnchorsCard, { node, root: d.root, days, base })) : null,
      node.kind === 'area' ? h(Section, { title: `Features (${nodes.filter((n) => n.parent === node.id).length})`, open: true },
        ...nodes.filter((n) => n.parent === node.id).map((f) => h('div',
        { key: f.id, className: 'flex gap-2 cockpit-row rounded px-1 cursor-pointer', onClick: () => setSel(f.id) },
        h('span', { className: 'font-medium' }, f.title), h('span', { className: 'truncate', style: sub }, f.user)))) : null,
      h(Section, { title: `Changes on ${base} (${nodeChanges.length} in the last ${RANGE_LABEL[days] || days + ' days'})`, open: true,
        extra: (() => { const unread = nodeChanges.filter((c) => !c.seen && c.status !== 'skipped'); return unread.length ? h('button',
        { type: 'button', onClick: () => markRead(unread), title: `mark the ${unread.length} unread change(s) of this node as read`,
        className: 'rounded px-1.5 py-0.5 text-xs', style: { border: `1px solid ${stroke}`, color: 'var(--ui-accent)' } },
        `✓ read (${unread.length})`) : null })() }, nodeChanges.length ? h('div', { className: 'flex flex-col' }, ...nodeChanges.map(changeRow)) : h('div',
        { style: sub }, 'nothing landed here in this window')))
    : null
  const pickedNode = picked ? byId[picked] : null
  const canvas = h('div', { className: 'relative min-w-0 flex-1 min-h-0' },
    h(MapGraph, { nodes, byId, counts, inherited: inh, picked, onPick: (id) => setPicked(id && byId[id] ? id : null) }),
    pickedNode ? h(MapPopover, { node: pickedNode, byId, changes: changesOf(pickedNode), base, onClose: () => setPicked(null), onDetails: () => { setSel(pickedNode.id); setPicked(null) }, onOpenChange: (c) => setOpenChange({ repo: c.repo, number: c.number }), onRead: markRead }) : null)
  const feed = h('div', { className: 'flex flex-col gap-1 p-3 text-xs' },
    h('div', { className: 'grid gap-2 cockpit-head px-1', style: { gridTemplateColumns: '5.5rem 9rem 1fr 10rem 6rem' } }, h('span', null, 'merged'), h('span', null, 'PR'), h('span', null, 'title'), h('span', null, 'areas'), h('span', null, 'verdict')),
    ...(relevant.length ? relevant.map(changeRow) : [h('div', { style: sub }, inWindow.length ? 'nothing relevant in this window (tick "include skipped" to see the rest)' : `nothing landed on ${base} in this window: widen it, or Scan now`)]))
  const lastScan = Object.values(d.state || {}).map((s) => s.last_scan).filter(Boolean).sort().pop()
  return h('div', { className: 'flex min-h-0 flex-1 flex-col' },
    h('div', { className: 'flex items-center gap-2 px-3 py-1.5 text-xs', style: { borderBottom: `1px solid ${stroke}` } },
      h('div', { className: 'flex items-center gap-1 rounded border p-0.5', style: { borderColor: stroke } }, seg(mode, 'tree', 'Map', setMode), seg(mode, 'feed', `Feed · ${unseenN} unread`, setMode), seg(mode, 'advisories', `Advisories · ${((aq.data && aq.data.advisories) || []).filter((a) => a.alert && !a.acknowledged).length} alert(s)`, setMode)),
      h('div', { className: 'flex items-center gap-1 rounded border p-0.5', style: { borderColor: stroke }, title: 'window for badges, the feed and each node\'s changes' }, ...[1, 7, 14, 30].map((v) => seg(days, v, RANGE_LABEL[v], setDays))),
      mode === 'feed' ? h('label', { className: 'flex items-center gap-1 cursor-pointer' }, h('input', { type: 'checkbox', checked: showAll, onChange: (e) => setShowAll(e.target.checked) }), 'include skipped') : null,
      h('span', { className: 'ml-auto', style: sub }, lastScan ? `last scan ${ago(lastScan)} ago · map built ${d.map.built ? ago(d.map.built) + ' ago' : 'never'}` : 'never scanned'),
      btn(busy ? 'scanning…' : 'Scan now', async () => { setBusy(true); try { const r = await post('/platform-scan',
        { days: 7 }); host.notify({ kind: 'info', title: `${r.base || base} scan`,
        message: (r.out || '').slice(-600) }); refresh() } catch (e) { host.notifyError(e, 'scan failed') } finally { setBusy(false) } },
        { title: `reads of merged pull requests on ${base}; an analyst card for the ones that need a verdict` }),
      btn('Mark all seen', async () => { try { await post('/platform-seen', { all: true }); refresh() } catch (e) { host.notifyError(e, 'failed') } })),
    mode === 'advisories' ? h(AdvisoriesTab, { data: aq.data, onDone: () => aq.refetch && aq.refetch() }) : h('div', { className: 'flex min-h-0 flex-1' },
      h('div', { className: 'overflow-auto p-2', style: { width: '22rem', minWidth: '18rem', borderRight: `1px solid ${stroke}` } }, nodes.length ? tree : h('div', { className: 'text-xs', style: sub }, d.hint || 'no platform map yet. Ask the platform-map skill to write platform/map.yaml, then Scan now')),
      mode === 'feed' ? h(Pane, { onClose: () => setMode('tree') }, feed) : node ? h(Pane, { onClose: () => setSel(null) }, detail) : canvas),
    openChange ? h(ChangeModal, { repo: openChange.repo, number: openChange.number, byId, onClose: () => setOpenChange(null),
      onSeen: async () => { try { await post('/platform-seen', openChange); qc.invalidateQueries({ queryKey: ['cockpit', 'platform-change', openChange.repo,
      openChange.number] }); refresh() } catch (e) { host.notifyError(e, 'failed') } },
      onUnseen: async () => { try { await post('/platform-unseen',
      openChange); qc.invalidateQueries({ queryKey: ['cockpit', 'platform-change', openChange.repo,
      openChange.number] }); refresh() } catch (e) { host.notifyError(e, 'undo seen failed') } } }) : null)
}

export { Platform, MapGraph, MapPopover, ChangeModal, layoutMap, STATUS_MARK, RANGE_LABEL, changeLabel, fileOf }
