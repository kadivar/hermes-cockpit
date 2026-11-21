// SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
// SPDX-License-Identifier: AGPL-3.0-or-later
import { useState } from 'react'
import { clockOf } from './live.js'
import { host, CTX, h, sub, mono, stroke, ClearableTextarea, btn, ago, post, detailHead, openWeb } from '../lib/sdk.js'

// the stack advisory watch (cockpit advisories scan, on the pack's schedule): one advisory = what a source says about a
// component the stack runs. The Inbox row, the Inbox's Advisories group and the Platform tab share these; AdvisoryPanel is
// the pane all three open.
const DANGER = 'var(--ui-danger, #d33)', WARN = 'var(--ui-warning, #c98a00)', ACCENT = 'var(--ui-accent)', QUIET = 'var(--ui-text-tertiary)'
const severityColor = (a) => (a.severity === 'critical' || a.exploited ? DANGER : a.severity === 'high' ? WARN : a.severity === 'medium' ? ACCENT : QUIET)
const prodHits = (a) => (a.hits || []).filter((x) => x.production)
// "lodash 4.17.20, php 8.3 +2": the hits' names (production first), at most n, with versions
const hitNames = (a, n = 3) => { const hs = [...prodHits(a), ...(a.hits || []).filter((x) => !x.production)].slice(0, n).map((x) => `${x.name}${x.version ? ' ' + x.version : ''}`); const rest = (a.hits || []).length - hs.length; return hs.join(', ') + (rest > 0 ? ` +${rest}` : '') }
const fixText = (a) => { const f = a.fix || {}; return f.time ? `fix ${ago(f.time)} ago` : f.versions && f.versions.length ? `fixed in ${f.versions.join(', ')}` : '' }
const fixLine = (a) => { const f = a.fix || {}; return f.time ? `fix expected ${String(f.time).replace('T', ' ').slice(0, 16)}${f.versions && f.versions.length ? ' · ' + f.versions.join(', ') : ''}` : f.versions && f.versions.length ? `fixed in ${f.versions.join(', ')}` : 'no fix known yet' }
const alertable = (a) => Boolean(a && a.alert && !a.acknowledged)
// the Inbox row's sentence: severity, exploited, the title, the production hits, the fix
const advisoryWhat = (a) => { const fx = fixText(a); return `${a.severity || 'unknown'} ${a.exploited ? 'exploited ' : ''}advisory: ${a.title || a.id} — hits ${hitNames({ ...a, hits: prodHits(a) }, 3) || 'none in production'}${fx ? ' · ' + fx : ''}` }
// the sources' health in one line: "osv ok 12:30 · kev failed: timeout"
const sourcesHealth = (sources) => Object.entries(sources || {}).map(([n, s]) => (s && s.ok ? `${n} ok ${s.checked ? clockOf(s.checked, 5) : ''}`.trim() : `${n} failed: ${(s && s.error) || 'no answer'}`)).join(' · ')

// an open bump PR that already bumps a package the advisory hits: the fix is in flight
const bumpPill = (p) => h('button', { key: `${p.repo}#${p.number}`, type: 'button', title: `${p.repo}#${p.number} · ${p.title || ''}${p.covers && p.covers.length ? ' · ' + p.covers.join(', ') : ''}`, onClick: (e) => { e.stopPropagation(); if (p.url) openWeb(p.url) },
  className: 'rounded px-1 text-[0.6875rem] whitespace-nowrap', style: { border: `1px solid ${ACCENT}`, color: ACCENT, background: 'rgba(56,139,253,.08)' } }, `🤖 #${p.number}`)

// one line of the Advisories group or the Platform tab: severity, exploited, status, id and title, the production hits, the bump pills, ack, age
function AdvisoryRow({ a, selected, onClick }) {
  const color = severityColor(a)
  return h('div', { onClick, 'data-advisory': a.id, className: 'flex items-center gap-2 px-3 py-0.5 border-b text-xs cursor-pointer', style: { borderColor: stroke, background: selected ? 'rgba(56,139,253,.10)' : undefined } },
    h('span', { className: 'rounded px-1 text-[0.6875rem] font-medium whitespace-nowrap', style: { border: `1px solid ${color}`, color } }, a.severity || 'unknown'),
    a.exploited ? h('span', { title: 'exploited in the wild' }, '⚡') : null,
    h('span', { className: 'whitespace-nowrap', style: sub }, a.status || 'candidate'),
    h('span', { className: 'truncate', title: a.title || '' }, h('span', { style: mono }, a.id), ' ', a.title || ''),
    h('span', { className: 'truncate', style: sub, title: hitNames(a, 12) }, hitNames({ ...a, hits: prodHits(a) }, 2) || 'no production hit'),
    ...((a.bump_prs || []).map(bumpPill)),
    a.acknowledged ? h('span', { className: 'whitespace-nowrap', style: sub, title: a.acknowledged.note || '' }, 'ack') : null,
    h('span', { className: 'ml-auto whitespace-nowrap', style: sub }, a.last_seen ? ago(a.last_seen) + ' ago' : ''))
}

function AdvisoryPanel({ a, onDone }) {
  const [note, setNote] = useState('')
  const [busy, setBusy] = useState(false)
  const act = async (path, body, msg) => { if (busy) return; setBusy(true); try { const r = await post(path, body); host.notify({ kind: 'success', title: msg, message: r.out }); onDone() } catch (e) { host.notifyError(e, 'failed') } finally { setBusy(false) } }
  const color = severityColor(a); const hits = a.hits || []
  const head = `${a.severity || 'unknown'}${a.cvss != null ? ' · cvss ' + a.cvss : ''}${a.exploited ? ' · exploited in the wild' : ''}${a.trust === 'low' ? ' · low trust' : ''}${a.last_seen ? ' · seen ' + ago(a.last_seen) + ' ago' : ''}`
  const cols = { gridTemplateColumns: '1fr 7rem 9rem 1fr 7rem' }
  return h('div', { className: 'flex flex-col gap-2 p-3 text-xs' },
    detailHead(a.id, { text: a.status || 'candidate', color }, head),
    h('div', { className: 'font-medium' }, a.title || ''),
    a.summary ? h('div', { className: 'whitespace-pre-wrap' }, a.summary) : h('div', { style: sub }, '(no summary)'),
    h('div', { className: 'overflow-auto rounded border', style: { borderColor: stroke } },
      h('div', { className: 'cockpit-head grid gap-2 px-2 py-1 border-b', style: { ...cols, borderColor: stroke } }, h('span', null, 'component'), h('span', null, 'version'), h('span', null, 'repo'), h('span', null, 'where'), h('span', null, 'fixed in')),
      ...(hits.length ? hits.map((x, i) => h('div', { key: i, className: 'grid gap-2 px-2 py-0.5 items-center', style: { ...cols, opacity: x.production ? 1 : 0.7 } },
        h('span', { className: 'truncate', title: `${x.kind || ''} ${x.ecosystem || ''}`.trim() }, x.production ? h('span', { className: 'font-medium' }, x.name) : x.name, h('span', { style: sub }, x.production ? ' · production' : ' · dev')),
        h('span', { style: mono }, x.version || '–', x.version_checked === false ? h('span', { style: sub, title: 'matched by name: the version could not be checked' }, ' ?') : null),
        h('span', { className: 'truncate', style: mono }, x.repo || ''), h('span', { className: 'truncate', style: sub, title: x.where || '' }, x.where || ''), h('span', { style: mono }, x.fixed_in || '–')))
        : [h('div', { key: 'none', className: 'px-2 py-1', style: sub }, 'no component of the stack matched (a name-only candidate)')])),
    h('div', null, h('span', { style: sub }, 'fix: '), fixLine(a)),
    h('div', { className: 'flex flex-wrap items-center gap-2' }, h('span', { style: sub }, 'sources: '), (a.via || [a.source]).filter(Boolean).join(', '),
      ...(Array.isArray(a.sources) ? a.sources.filter((s) => s && s.url).map((s) => h('a', { key: s.url, href: s.url, title: s.url, onClick: (e) => { e.preventDefault(); openWeb(s.url) }, style: { color: ACCENT } }, s.name || s.url)) : []),
      a.url ? h('a', { href: a.url, onClick: (e) => { e.preventDefault(); openWeb(a.url) }, style: { color: ACCENT } }, 'open the advisory') : null),
    a.bump_prs && a.bump_prs.length ? h('div', { className: 'flex flex-wrap items-center gap-1' }, h('span', { style: sub }, 'bump PR(s) in flight: '), ...a.bump_prs.map(bumpPill)) : null,
    a.acknowledged
      ? h('div', { className: 'flex flex-col gap-1 rounded border p-2', style: { borderColor: stroke } }, h('div', null, h('span', { style: sub }, `acknowledged ${a.acknowledged.time ? ago(a.acknowledged.time) + ' ago' : ''}: `), a.acknowledged.note || '(no note)'),
          h('div', null, btn('Unacknowledge', () => act('/advisory-unack', { id: a.id }, `${a.id}: unacknowledged`), { disabled: busy, title: 'an alert comes back to the Inbox' })))
      : h('div', { className: 'flex flex-col gap-1' },
          h(ClearableTextarea, { value: note, onChange: (e) => setNote(e.target.value), rows: 2, placeholder: 'why this is fine, or what was done (kept with the advisory)', className: 'rounded border bg-transparent px-1.5 py-1 text-xs', style: { borderColor: stroke } }),
          h('div', { className: 'flex items-center gap-2' },
            btn(busy ? 'working' : 'Acknowledge', () => act('/advisory-ack', { id: a.id, note }, `${a.id} acknowledged`), { accent: true, disabled: busy, title: 'the row leaves the Inbox; the Platform tab keeps it with your note' }),
            h('button', { type: 'button', disabled: busy, onClick: () => act('/advisory-card', { id: a.id }, `${a.id}: analyst card made`),
              className: 'rounded px-2.5 py-0.5 text-xs font-medium disabled:opacity-40', style: { background: ACCENT, color: '#fff' },
              title: 'an analyst assesses it: reachable in the stack, on production, the fix; the verdict lands as a card comment' },
              busy ? 'working' : 'Make an analyst card'),
            h('span', { style: sub }, 'One card per advisory while it is open.'))))
}

// the Platform tab: every advisory (the backlog and the acknowledged too), the sources' health, the manifest's size
function AdvisoriesTab({ data, onDone }) {
  const [sel, setSel] = useState(null)
  const advs = (data && data.advisories) || []
  const picked = sel ? advs.find((a) => a.id === sel) : null
  const comps = Object.entries(((data && data.manifest) || {}).components || {}).map(([k, n]) => `${n} ${k}`).join(' · ')
  return h('div', { className: 'flex min-h-0 flex-1' },
    h('div', { className: 'flex min-w-0 flex-1 flex-col overflow-auto' },
      h('div', { className: 'px-3 py-1 text-xs border-b', style: { ...sub, borderColor: stroke } }, `${advs.length} advisor${advs.length === 1 ? 'y' : 'ies'} · ${data && data.time ? 'scanned ' + ago(data.time) + ' ago' : 'never scanned'} · stack: ${comps || 'no manifest yet'} · ${sourcesHealth(data && data.sources) || 'no source has run'}`),
      ...(advs.length ? advs.map((a) => h(AdvisoryRow, { key: a.id, a, selected: sel === a.id, onClick: () => setSel(sel === a.id ? null : a.id) })) : [h('div', { key: 'none', className: 'p-3 text-xs', style: sub }, 'no advisory touches the stack')])),
    picked ? h('div', { className: 'overflow-auto', style: { width: '34rem', borderLeft: `1px solid ${stroke}` } }, h(AdvisoryPanel, { a: picked, onDone: () => { setSel(null); onDone && onDone() } })) : null)
}

export { AdvisoryPanel, AdvisoryRow, AdvisoriesTab, bumpPill, advisoryWhat, severityColor, hitNames, fixText, fixLine, sourcesHealth, alertable, prodHits }
