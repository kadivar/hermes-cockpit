// SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
// SPDX-License-Identifier: AGPL-3.0-or-later
import { useState, useEffect, useMemo } from 'react'
import { SandboxedFrame, h, sub, mono, stroke, btn, useQuery, CTX, POLL_MS } from './sdk.js'

// the pack's desktop.mermaid_url (via /repos): the frame imports mermaid from it and draws the diagram; none: the source shows
const useMermaidUrl = () => { const q = useQuery({ queryKey: ['cockpit', 'repos'], queryFn: () => CTX.rest('/repos'), refetchInterval: POLL_MS * 6, retry: 0 }); return (q.data && q.data.mermaid_url) || '' }
const mermaidPage = (url, id, source, pad, size, dark) => `<!doctype html><html><head><meta charset="utf-8"><style>html,body{margin:0;padding:${pad}px;background:transparent;color:#ddd;font:${size}px -apple-system,system-ui,sans-serif}.mermaid{display:flex;justify-content:center}svg{max-width:100%;height:auto}pre{white-space:pre-wrap}</style></head><body>` +
  (url ? `<pre class="mermaid">${source.replace(/</g, '&lt;')}</pre>
<script type="module">
import mermaid from ${JSON.stringify(url)};
const post = (m) => parent.postMessage(Object.assign({ cockpitMermaid: ${JSON.stringify(id)} }, m), '*');
try { mermaid.initialize({ startOnLoad: false, theme: ${dark ? "'dark'" : "'default'"}, securityLevel: 'strict', flowchart: { useMaxWidth: true, htmlLabels: true }, sequence: { useMaxWidth: true } });
  await mermaid.run({ querySelector: '.mermaid' }); post({ height: document.body.scrollHeight });
  new ResizeObserver(() => post({ height: document.body.scrollHeight })).observe(document.body);
} catch (e) { post({ error: String(e && e.message || e), height: document.body.scrollHeight }) }
</script>` : `<pre>${source.replace(/</g, '&lt;')}</pre>`) + '</body></html>'

// ---------- rendered markdown with mermaid diagrams (plans: Before / After flows, sequence diagrams) ----------
const unescapeHtml = (t) => t.replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/&quot;/g, '"').replace(/&#39;/g, "'").replace(/&amp;/g, '&')
// text that goes into innerHTML as text (a file the backend did not render): never markup
const escapeHtml = (t) => String(t).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;')
const MERMAID_RE = /<pre><code class="language-mermaid">([\s\S]*?)<\/code><\/pre>/g
let mermaidSeq = 0
function MermaidModal({ source, onClose }) {
  useEffect(() => { window.__cockpitModalOpen = true; return () => { window.__cockpitModalOpen = false } }, [])
  // the same diagram, rendered again at the window's size; the frame reports its own height, the body scrolls if taller
  const [id] = useState(() => 'mmf' + (++mermaidSeq)); const [height, setHeight] = useState(400); const url = useMermaidUrl()
  useEffect(() => { const onMsg = (e) => { const d = e.data || {}; if (d.cockpitMermaid !== id) return; if (d.height) setHeight(Math.max(300, Math.ceil(d.height) + 24)) }; window.addEventListener('message', onMsg); return () => window.removeEventListener('message', onMsg) }, [id])
  const page = mermaidPage(url, id, source, 12, 14, true)
  const src = 'data:text/html;charset=utf-8,' + encodeURIComponent(page)
  return h('div', { role: 'presentation', onClick: onClose, style: { position: 'fixed', inset: 0, zIndex: 1000, background: 'rgba(0,0,0,.72)', display: 'flex', alignItems: 'center', justifyContent: 'center', padding: '2vh 2vw' } },
    h('div', { role: 'presentation', onClick: (e) => e.stopPropagation(), className: 'rounded-lg border flex flex-col', style: { borderColor: stroke, background: 'var(--ui-bg-elevated, #1e1e1e)', width: '96vw', height: '96vh', overflow: 'hidden' } },
      h('div', { className: 'flex items-center gap-2 px-3 py-1.5 text-xs', style: { borderBottom: `1px solid ${stroke}` } }, h('span', { className: 'font-medium' }, 'Diagram'), h('span', { style: sub }, 'Esc or click outside to close'), h('span', { className: 'ml-auto' }, btn('✕ close', onClose))),
      h('div', { style: { flex: 1, overflow: 'auto' } }, h(SandboxedFrame, { src, title: 'diagram full ' + id, style: { width: '100%', height: height + 'px', border: 0, display: 'block' } }))))
}
function MermaidFrame({ source }) {
  const [id] = useState(() => 'mm' + (++mermaidSeq)); const [height, setHeight] = useState(220); const [err, setErr] = useState(null); const url = useMermaidUrl()
  useEffect(() => { const onMsg = (e) => { const d = e.data || {}; if (d.cockpitMermaid !== id) return; if (d.error) setErr(d.error); else if (d.height) setHeight(Math.min(900, Math.max(80, Math.ceil(d.height) + 16))) }; window.addEventListener('message', onMsg); return () => window.removeEventListener('message', onMsg) }, [id])
  const dark = (getComputedStyle(document.documentElement).colorScheme || '').includes('dark') || true
  const page = mermaidPage(url, id, source, 6, 12, dark)
  const src = 'data:text/html;charset=utf-8,' + encodeURIComponent(page)
  const [full, setFull] = useState(false)
  useEffect(() => { if (!full) return; const k = (e) => { if (e.key === 'Escape') setFull(false) }; window.addEventListener('keydown', k); return () => window.removeEventListener('keydown', k) }, [full])
  return h('div', { className: 'my-1 rounded border relative', style: { borderColor: stroke, background: 'rgba(127,127,127,.06)' } },
    h('button', { type: 'button', onClick: () => setFull(true), title: 'full screen (Esc closes)', className: 'absolute right-1 top-1 rounded px-1.5 text-xs', style: { background: 'rgba(127,127,127,.25)', zIndex: 2 } }, '⤢'),
    full ? h(MermaidModal, { source, onClose: () => setFull(false) }) : null,
    h(SandboxedFrame, { src, title: 'diagram ' + id, style: { width: '100%', height: height + 'px', border: 0, display: 'block' } }),
    err ? h('details', { className: 'px-2 pb-1 text-[0.6875rem]', style: { color: 'var(--ui-danger, #d33)' } }, h('summary', { className: 'cursor-pointer' }, 'diagram did not render: ' + err.slice(0, 120)), h('pre', { className: 'whitespace-pre-wrap', style: mono }, source)) : null)
}
function RichMd({ html, className, style }) {
  const parts = useMemo(() => { const out = []; let last = 0; let m; MERMAID_RE.lastIndex = 0
    while ((m = MERMAID_RE.exec(html || ''))) { if (m.index > last) out.push({ html: html.slice(last, m.index) }); out.push({ mermaid: unescapeHtml(m[1]) }); last = m.index + m[0].length }
    if (last < (html || '').length) out.push({ html: html.slice(last) }); return out }, [html])
  return h('div', { className: 'cockpit-md ' + (className || ''), style }, ...parts.map((p, i) => p.mermaid != null ? h(MermaidFrame, { key: i, source: p.mermaid }) : h('div', { key: i, dangerouslySetInnerHTML: { __html: p.html } })))
}

export { RichMd, MermaidFrame, MermaidModal, unescapeHtml, escapeHtml }
