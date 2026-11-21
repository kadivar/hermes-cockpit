// SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
// SPDX-License-Identifier: AGPL-3.0-or-later
import { useState, useEffect, useRef, useMemo } from 'react'
import { useQuery, CTX, h, sub, mono, stroke, btn, ago, post, SandboxedFrame } from '../lib/sdk.js'
// the terminal widget, bundled as text and written into the frame's own page: the page fetches nothing at run time
import xtermLib from '@xterm/xterm/lib/xterm.js' with { type: 'text' }
import xtermCss from '@xterm/xterm/css/xterm.css' with { type: 'text' }
import fitLib from '@xterm/addon-fit/lib/addon-fit.js' with { type: 'text' }
// code as an inline script may carry it: no closing tag ends the script early, and no map is asked for
const inline = (code) => code.replace(/<\/script/gi, '<\\/script').replace(/\/\/# sourceMappingURL=\S+/g, '')

let termSeq = 0

// ---------- chat with the ticket's coding tool: a real terminal (xterm in a sandboxed frame) on the pty the backend holds,
// one persistent session per ticket; the frame and the page talk over postMessage, the page and the backend over the chat routes ----------
function TerminalModal({ ticket, from, card, onClose }) {
  useEffect(() => { window.__cockpitModalOpen = true; return () => { window.__cockpitModalOpen = false } }, [])
  const [id] = useState(() => 'tm' + (++termSeq)); const frame = useRef(null)
  const [state, setState] = useState({ phase: 'opening' }); const [confirmReset, setConfirmReset] = useState(false)
  const off = useRef(0); const ready = useRef(false); const size = useRef(null)   // the frame's last measured cols/rows
  const send = (msg) => { const w = frame.current && frame.current.contentWindow; if (w) w.postMessage(Object.assign({ cockpitTerm: id }, msg), '*') }
  const open = async (reset) => {
    setState({ phase: 'opening' })
    try {
      const sz = size.current || { cols: 120, rows: 36 }
      const r = await post('/chat-open', { ticket, from: from || undefined, card: card || undefined, reset: Boolean(reset), cols: sz.cols, rows: sz.rows })
      off.current = r.offset || 0
      setState({ phase: 'open', ...r })
      if (ready.current) send({ type: 'data', b64: r.replay || '', clear: true })
      if (size.current) { try { await post('/chat-resize', { ticket, cols: size.current.cols, rows: size.current.rows }) } catch (err) {} }   // the frame may have measured itself before the pty existed
    } catch (e) { setState({ phase: 'error', error: String(e.message || e) }) }
  }
  useEffect(() => { open(false) }, [ticket])
  useEffect(() => {   // frame → page: ready, keystrokes, size
    const onMsg = async (e) => {
      const d = e.data || {}; if (d.cockpitTerm !== id) return
      if (d.type === 'ready') { ready.current = true; if (state.phase === 'open') { const r = await CTX.rest(`/chat-read?ticket=${encodeURIComponent(ticket)}&offset=0`); off.current = r.offset; send({ type: 'data', b64: r.data || '', clear: true }) } }
      else if (d.type === 'input') { try { await post('/chat-write', { ticket, data: d.b64 }) } catch (err) { setState((s) => ({ ...s, phase: 'error', error: String(err.message || err) })) } }
      else if (d.type === 'resize') { size.current = { cols: d.cols, rows: d.rows }; try { await post('/chat-resize', { ticket, cols: d.cols, rows: d.rows }) } catch (err) {} }
    }
    window.addEventListener('message', onMsg); return () => window.removeEventListener('message', onMsg)
  }, [id, ticket, state.phase])
  useEffect(() => {   // page → frame: the pty's new bytes, polled while the modal is open
    if (state.phase !== 'open') return
    let stop = false
    const tick = async () => {
      if (stop) return
      try {
        const r = await CTX.rest(`/chat-read?ticket=${encodeURIComponent(ticket)}&offset=${off.current}`); if (stop) return
        if (r.gone) { setState((s) => ({ ...s, phase: 'ended' })); return }
        if (r.data) { off.current = r.offset; if (ready.current) send({ type: 'data', b64: r.data }) }
        if (!r.alive) { setState((s) => ({ ...s, phase: 'ended' })); return }
      } catch (e) {}
      setTimeout(tick, 120)
    }
    tick(); return () => { stop = true }
  }, [state.phase, ticket])
  useEffect(() => { const k = (e) => { if (e.key === 'Escape' && e.target === document.body) onClose() }; window.addEventListener('keydown', k); return () => window.removeEventListener('keydown', k) }, [])
  const page = `<!doctype html><html><head><meta charset="utf-8"><style>${xtermCss}</style><style>html,body{margin:0;height:100%;background:#0d1117;overflow:hidden}#t{position:absolute;inset:0;padding:6px}</style></head><body><div id="t"></div>
<script>${inline(xtermLib)}</script><script>${inline(fitLib)}</script>
<script>
const ID = ${JSON.stringify(id)}; const post = (m) => parent.postMessage(Object.assign({ cockpitTerm: ID }, m), '*');
const enc = (s) => { const b = new TextEncoder().encode(s); let x = ''; for (const c of b) x += String.fromCharCode(c); return btoa(x) };
const dec = (b64) => { const bin = atob(b64); const a = new Uint8Array(bin.length); for (let i = 0; i < bin.length; i++) a[i] = bin.charCodeAt(i); return a };
const term = new Terminal({ cursorBlink: true, fontSize: 13, fontFamily: 'Menlo, ui-monospace, monospace', theme: { background: '#0d1117', foreground: '#d0d7de', cursor: '#58a6ff' }, scrollback: 20000, allowProposedApi: true });
const fit = new FitAddon.FitAddon(); term.loadAddon(fit); term.open(document.getElementById('t')); fit.fit(); term.focus();
term.onData((d) => post({ type: 'input', b64: enc(d) }));
const sendSize = () => post({ type: 'resize', cols: term.cols, rows: term.rows });
new ResizeObserver(() => { try { fit.fit(); sendSize() } catch (e) {} }).observe(document.getElementById('t'));
window.addEventListener('message', (e) => { const d = e.data || {}; if (d.cockpitTerm !== ID) return; if (d.type === 'data') { if (d.clear) term.reset(); term.write(dec(d.b64)) } if (d.type === 'focus') term.focus() });
post({ type: 'ready' }); sendSize();
</script></body></html>`
  const src = useMemo(() => 'data:text/html;charset=utf-8,' + encodeURIComponent(page), [id])
  const st = state
  return h('div', { role: 'presentation', onClick: onClose, style: { position: 'fixed', inset: 0, zIndex: 1000, background: 'rgba(0,0,0,.72)', display: 'flex', alignItems: 'center', justifyContent: 'center', padding: '2vh 2vw' } },
    h('div', { role: 'presentation', onClick: (e) => { e.stopPropagation(); send({ type: 'focus' }) }, className: 'rounded-lg border flex flex-col', style: { borderColor: stroke, background: '#0d1117', width: '96vw', height: '96vh', overflow: 'hidden' } },
      h('div', { className: 'flex items-center gap-2 px-3 py-1.5 text-xs', style: { borderBottom: `1px solid ${stroke}`, background: 'var(--ui-bg-elevated, #1e1e1e)' } },
        h('span', { className: 'font-medium' }, ticket === 'own' ? 'coding tool · yours' : `${ticket} · coding tool`),
        st.session ? h('span', { style: mono, title: 'your session for this ticket; it persists until the flow ends' }, st.session.slice(0, 8)) : null,
        st.forked_from ? h('span', { style: sub }, `forked from the run ${st.forked_from.slice(0, 8)}`) : st.cwd ? h('span', { style: { ...mono, ...sub }, title: st.cwd }, st.cwd) : null,
        st.phase === 'open' ? h('span', { style: { color: st.alive ? 'var(--ui-success, #2a9d5c)' : 'var(--ui-warning, #c98a00)' } },
          st.attached ? '● re-attached' : '● started') : st.phase === 'ended' ? h('span', { style: { color: 'var(--ui-warning, #c98a00)' } },
          'the process ended · open again to resume') : st.phase === 'error' ? h('span', { style: { color: 'var(--ui-danger, #d33)' } }, st.error) : h('span',
          { style: sub }, 'opening'),
        h('span', { className: 'ml-auto flex items-center gap-1' },
          st.phase === 'ended' ? btn('Resume', () => open(false), { accent: true }) : null,
          confirmReset ? h('span', { className: 'flex items-center gap-1' },
            h('span', { style: { color: 'var(--ui-warning, #c98a00)' } }, 'start a new chat from the latest run? this one stays on disk'),
            btn('Yes', () => { setConfirmReset(false); open(true) }, { danger: true }),
            btn('No', () => setConfirmReset(false))) : btn('Start over from latest run', () => setConfirmReset(true),
            { title: 'fork a fresh chat from the latest run of this ticket; the current conversation stays on disk' }),
          btn('End process', async () => { try { await post('/chat-end', { ticket }); setState((s) => ({ ...s, phase: 'ended' })) } catch (e) {} }, { title: 'stop the terminal process; the conversation stays and resumes next time' }),
          btn('✕ close', onClose, { title: 'hide the terminal; the chat keeps running' }))),
      h('div', { style: { flex: 1, minHeight: 0 } }, h(SandboxedFrame, { ref: frame, src, title: 'chat ' + ticket, style: { width: '100%', height: '100%', border: 0, display: 'block' } }))))
}
// a button that opens the ticket's coding chat; shows whether one exists already
function ChatButton({ ticket, from, card, label }) {
  // on every card and ticket: the chat attaches to the best coding tool session by itself (the card's own run, else the ticket's latest run, else a fresh one)
  const [open, setOpen] = useState(false)
  const q = useQuery({ queryKey: ['cockpit', 'chat-state', ticket, card || ''], queryFn: () => CTX.rest('/chat-state?ticket=' + encodeURIComponent(ticket) + (card ? '&card=' + encodeURIComponent(card) : '')), refetchInterval: 15000, retry: 0, enabled: Boolean(ticket) })
  if (!ticket) return null
  const st = q.data || {}; const best = st.best || {}
  const text = label || (st.exists ? (st.running ? '● Chat' : 'Chat') : 'Chat')
  const title = ticket === 'own' ? 'your own coding tool in the workspace, like one started in a shell: outside every flow, one conversation that persists and resumes here' : st.exists ? `your session ${(st.session || '').slice(0, 8)} (${st.forked_source ? 'forked from ' + st.forked_source : 'fresh'}), since ${st.created ? ago(st.created) + ' ago' : ''}`
    : best.session ? `opens an interactive coding tool forked from ${best.source} (${best.session.slice(0, 8)}, its full context); the chat persists until the flow ends` : `opens a fresh interactive coding tool in ${best.cwd || 'the ticket folder'}; the chat persists until the flow ends`
  return h('span', null, btn(text, () => setOpen(true), { accent: !st.exists, title }),
    open ? h(TerminalModal, { ticket, from, card, onClose: () => setOpen(false) }) : null)
}

export { ChatButton, TerminalModal }
