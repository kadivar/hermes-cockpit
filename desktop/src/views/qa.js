// SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
// SPDX-License-Identifier: AGPL-3.0-or-later
import { useState, useEffect } from 'react'
import { useQuery, CTX, h, sub, mono, stroke, btn, ago, openFile, trow, SplitList, detailHead } from '../lib/sdk.js'
import { RichMd } from '../lib/markdown.js'
import { runNames, evidenceRel } from '../lib/packwords.js'

// ---------- QA evidence (qa/<ticket>/<run>: results table + screenshots/videos/pdf preview) ----------
const fmtSize = (n) => n > 1e6 ? (n / 1e6).toFixed(1) + ' MB' : n > 1e3 ? Math.round(n / 1e3) + ' KB' : n + ' B'
const verdictMark = (v) => v === 'pass' ? { t: '✅ pass', c: 'var(--ui-success, #2a9d5c)' } : v === 'fail' ? { t: '❌ fail', c: 'var(--ui-danger, #d33)' } : v === 'warn' ? { t: '⚠ partial', c: 'var(--ui-warning, #c98a00)' } : { t: v, c: 'var(--ui-text-tertiary)' }
const blobCache = new Map()
async function mediaUrl(path) {
  if (blobCache.has(path)) return blobCache.get(path)
  const f = await CTX.rest('/qa-file?path=' + encodeURIComponent(path))
  if (f.kind !== 'media') return f
  const bin = atob(f.b64); const arr = new Uint8Array(bin.length); for (let i = 0; i < bin.length; i++) arr[i] = bin.charCodeAt(i)
  const url = URL.createObjectURL(new Blob([arr], { type: f.mime })); const v = { kind: 'media', url, mime: f.mime, size: f.size }
  blobCache.set(path, v); return v
}
function Viewer({ file, onClose }) {
  const [data, setData] = useState(null); const [err, setErr] = useState(null)
  useEffect(() => { setData(null); setErr(null); mediaUrl(file.path).then(setData).catch((e) => setErr(String(e.message || e))) }, [file.path])
  const body = err ? h('div', { className: 'text-xs', style: { color: 'var(--ui-danger, #d33)' } }, err)
    : !data ? h('div', { className: 'text-xs', style: sub }, 'loading')
    : data.kind === 'media' && data.mime.startsWith('image/') ? h('img', { src: data.url, style: { maxWidth: '100%', maxHeight: '70vh', objectFit: 'contain', border: `1px solid ${stroke}`, borderRadius: 4 } })
    : data.kind === 'media' && data.mime.startsWith('video/') ? h('video', { src: data.url, controls: true, autoPlay: false, style: { maxWidth: '100%', maxHeight: '70vh', border: `1px solid ${stroke}`, borderRadius: 4 } })
    : data.kind === 'media' ? h('iframe', { src: data.url, title: file.rel, style: { width: '100%', height: '70vh', border: `1px solid ${stroke}`, borderRadius: 4 } })
    : data.html ? h(RichMd, { className: 'rounded border px-3 py-1', style: { borderColor: stroke }, html: data.html })
    : h('pre', { className: 'whitespace-pre-wrap rounded border p-2 text-xs', style: { ...mono, borderColor: stroke, maxHeight: '70vh', overflow: 'auto' } }, data.text)
  return h('div', { className: 'flex flex-col gap-1 rounded border p-2', style: { borderColor: 'var(--ui-accent)' } },
    h('div', { className: 'flex items-center gap-2 text-xs' }, h('span', { className: 'font-medium truncate', style: mono, title: file.path }, file.rel || file.path.split('/').slice(-2).join('/')), h('span', { style: sub }, fmtSize(file.size || 0)),
      h('span', { className: 'ml-auto flex gap-1' }, btn('Reveal', () => CTX.os.revealPath(file.path)), btn('Open', () => openFile(file.path)), btn('✕', onClose))),
    body)
}
function Run({ run, ticket, onView, selected, names }) {
  const [open, setOpen] = useState(true)
  const named = runNames(names)
  const r = run.results; const byRel = Object.fromEntries(run.files.map((f) => [f.rel, f]))
  const resolve = (rel) => { const k = evidenceRel(rel, named.evidence)
    if (byRel[k]) return byRel[k]
    const pre = k.replace(/\*.*$/, ''); const hit = run.files.find((f) => f.rel.startsWith(pre) || f.rel.split('/').pop().startsWith(pre))
    return hit || { path: run.dir + '/' + rel.replace(/^\.?\//, ''), rel: k, kind: 'other', size: 0 } }
  const counts = r ? { pass: r.rows.filter((x) => x.verdict === 'pass').length, fail: r.rows.filter((x) => x.verdict === 'fail').length, warn: r.rows.filter((x) => x.verdict === 'warn').length } : null
  const media = run.files.filter((f) => f.kind === 'image' || f.kind === 'video' || f.kind === 'pdf')
  return h('div', { className: 'rounded border', style: { borderColor: stroke } },
    h('div', { className: 'flex items-center gap-2 px-2 py-1 text-xs cursor-pointer', onClick: () => setOpen(!open), style: { background: 'rgba(127,127,127,.08)' } },
      h('span', null, open ? '▾' : '▸'), h('span', { className: 'font-medium' }, run.name),
      r ? h('span', { style: sub, title: r.date_detail || '' }, r.date || '') : h('span', { style: sub }, 'no ' + named.results),
      counts ? h(Counts, { c: counts, total: r.rows.length }) : null,
      h('span', { className: 'ml-auto', style: sub }, `${run.files.length} files · ${media.length} media`),
      btn('Reveal', () => CTX.os.revealPath(run.dir)), btn('Open', () => openFile(run.dir + '/' + named.results))),
    open ? h('div', { className: 'flex flex-col gap-2 p-2' },
      r && (r.meta.Environment || r.meta['Under test']) ? h('div', { className: 'text-xs flex flex-col gap-0.5' },
        r.meta['Under test'] ? h('div', null, h('span', { style: sub }, 'under test: '), r.meta['Under test']) : null,
        r.meta.Environment ? h('div', null, h('span', { style: sub }, 'environment: '), r.meta.Environment) : null,
        r.meta['Cypress gate'] ? h('div', null, h('span', { style: sub }, 'cypress gate: '), r.meta['Cypress gate']) : null) : null,
      r && r.rows.length ? h('div', { className: 'grid gap-x-2 gap-y-1 text-xs', style: { gridTemplateColumns: '1.5rem 1fr 5rem minmax(10rem, 1fr)' } },
        h('div', { style: sub }, '#'), h('div', { style: sub }, 'scenario'), h('div', { style: sub }, 'result'), h('div', { style: sub }, 'evidence'),
        ...r.rows.flatMap((row) => { const m = verdictMark(row.verdict); return [
          h('div', { key: 'n' + row.n, style: mono }, row.n), h('div', { key: 's' + row.n, title: row.note }, row.scenario, row.note ? h('span', { style: sub }, ' — ' + row.note) : null),
          h('div', { key: 'r' + row.n, style: { color: m.c } }, m.t),
          h('div', { key: 'e' + row.n, className: 'flex flex-wrap gap-1' }, ...row.evidence.map((e) => { const f = resolve(e.rel); const active = selected && selected.path === f.path
            return h('button', { key: e.rel, type: 'button', onClick: () => onView(f), title: f.path,
              className: 'rounded border px-1 text-[0.6875rem]', style: { borderColor: active ? 'var(--ui-accent)' : stroke,
              color: f.kind === 'image' ? 'var(--ui-accent)' : f.kind === 'video' ? 'var(--ui-success, #2a9d5c)' : 'var(--ui-text-secondary)' } },
              (f.kind === 'image' ? '🖼 ' : f.kind === 'video' ? '▶ ' : f.kind === 'pdf' ? '📄 ' : '') + e.label) }))] })) : null,
      media.length ? h('div', { className: 'flex flex-wrap gap-1 text-xs' }, h('span', { style: sub }, 'all media:'),
        ...media.map((f) => h('button', { key: f.rel, type: 'button', onClick: () => onView(f), title: `${f.rel} · ${fmtSize(f.size)}`,
        className: 'rounded border px-1 text-[0.6875rem]', style: { borderColor: selected && selected.path === f.path ? 'var(--ui-accent)' : stroke } },
        (f.kind === 'image' ? '🖼 ' : f.kind === 'video' ? '▶ ' : '📄 ') + f.rel.split('/').pop()))) : null,
      run.readme ? h(RichMd, { className: 'text-xs', html: run.readme }) : null,
      r ? Object.entries(r.sections).map(([k, html]) => h('details', { key: k, className: 'text-xs' }, h('summary', { className: 'cursor-pointer', style: sub }, k), h(RichMd, { className: 'pl-2', html: html }))) : null) : null)
}
function Evidence({ ticket }) {
  const q = useQuery({ queryKey: ['cockpit', 'qa', ticket], queryFn: () => CTX.rest('/qa?ticket=' + encodeURIComponent(ticket)), refetchInterval: 30000, retry: 1 })
  const [file, setFile] = useState(null)
  if (q.isLoading) return h('div', { className: 'p-2 text-xs', style: sub }, 'loading evidence')
  if (q.error) return h('div', { className: 'p-2 text-xs', style: { color: 'var(--ui-danger, #d33)' } }, String(q.error.message || q.error))
  const d = q.data
  if (!d.dir) return h('div', { className: 'p-2 text-xs', style: sub }, `No qa/${ticket} folder yet: the tester lane has not run a plan for this ticket.`)
  return h('div', { className: 'flex flex-col gap-2' },
    h('div', { className: 'text-xs flex items-center gap-2' }, h('span', { style: sub }, d.dir), btn('Reveal', () => CTX.os.revealPath(d.dir)),
      d.scenarios ? h('details', { className: 'ml-auto' }, h('summary', { className: 'cursor-pointer', style: sub }, `test plan (${runNames(d.names).plan})`), h(RichMd, { className: 'rounded border px-3 py-1 mt-1', style: { borderColor: stroke }, html: d.scenarios })) : null),
    file ? h(Viewer, { file, onClose: () => setFile(null) }) : null,
    ...d.runs.map((run) => h(Run, { key: run.name, run, ticket, onView: setFile, selected: file, names: d.names })),
    !d.runs.length ? h('div', { className: 'text-xs', style: sub }, 'No test runs yet.') : null,
    d.review.length ? h('div', { className: 'text-xs flex flex-wrap gap-1 items-center' }, h('span', { style: sub }, 'review files:'), ...d.review.map((f) => h('button', { key: f.rel, type: 'button', onClick: () => setFile(f), className: 'rounded border px-1 text-[0.6875rem]', style: { borderColor: stroke } }, f.rel))) : null)
}
const QA_COLS = '6rem 3.5rem 4.5rem 6.5rem 1fr 4rem'
// pass / fail / partial / total in fixed slots, tabular digits, zeros dimmed — so the column reads as a table
function Counts({ c, total }) {
  const cell = (n, glyph, color) => h('div', { className: 'text-right whitespace-nowrap', style: { color: n ? color : 'var(--ui-text-quaternary)', fontVariantNumeric: 'tabular-nums' } }, n ? `${n} ${glyph}` : '–')
  return h('div', { className: 'grid gap-x-3', style: { gridTemplateColumns: '3rem 3rem 3rem 3.5rem' } },
    cell(c.pass || 0, '✅', 'var(--ui-success, #2a9d5c)'), cell(c.fail || 0, '❌', 'var(--ui-danger, #d33)'), cell(c.warn || 0, '⚠', 'var(--ui-warning, #c98a00)'),
    h('div', { className: 'text-right whitespace-nowrap', style: { ...sub, fontVariantNumeric: 'tabular-nums' } }, total ? `of ${total}` : '–'))
}
function QaIndex() {
  const q = useQuery({ queryKey: ['cockpit', 'qa', ''], queryFn: () => CTX.rest('/qa'), refetchInterval: 60000, retry: 1 })
  const [selected, setSelected] = useState(null)
  if (q.isLoading) return h('div', { className: 'p-3 text-xs', style: sub }, 'loading')
  if (q.error) return h('div', { className: 'p-3 text-xs', style: { color: 'var(--ui-danger, #d33)' } }, String(q.error.message || q.error))
  return h(SplitList, { cols: QA_COLS, labels: ['ticket', '>runs', 'last run', 'date',
    h('div', { className: 'grid gap-x-3', style: { gridTemplateColumns: '3rem 3rem 3rem 3.5rem' } }, h('div', { className: 'text-right' }, 'pass'),
    h('div', { className: 'text-right' }, 'fail'), h('div', { className: 'text-right' }, 'partial'), h('div', { className: 'text-right' }, 'total')),
    '>age'], rows: q.data.tickets, selected, onSelect: setSelected, empty: 'No test runs under qa/.',
    renderRow: (t) => trow(QA_COLS, { key: t.ticket, onClick: () => setSelected(selected === t.ticket ? null : t.ticket), selected: selected === t.ticket, children: [
      h('div', { key: 't', className: 'font-medium truncate' }, (t.ticket || '').toUpperCase()), h('div', { key: 'r', className: 'text-right', style: mono }, t.runs || 0), h('div', { key: 'l', style: mono }, (t.last_run || '').replace('test_run_', '#')), h('div', { key: 'd', className: 'truncate', style: sub, title: t.date_detail || t.date }, t.date || '–'),
      h('div', { key: 's' }, h(Counts, { c: t.counts || {}, total: t.scenarios })),
      h('div', { key: 'a', className: 'text-right truncate', style: sub }, t.mtime ? ago(new Date(t.mtime * 1000).toISOString()) : '')] }),
    detail: selected ? h('div', { className: 'flex flex-col gap-3 p-3' }, detailHead(selected.toUpperCase(), null, 'test runs and evidence'), h(Evidence, { ticket: selected })) : null })
}

export { Evidence, Run, Viewer, QaIndex, Counts, mediaUrl, fmtSize, verdictMark, QA_COLS }
