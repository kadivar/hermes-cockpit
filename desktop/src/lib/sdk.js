// SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
// SPDX-License-Identifier: AGPL-3.0-or-later

// shared SDK surface: the plugin context (CTX), host/haptic re-exports, the h() helper, REST helpers, and the page's small widgets + CSS.
import { host, haptic, useQuery, useQueryClient, ROUTES_AREA, SIDEBAR_NAV_AREA, SandboxedFrame } from '@hermes/plugin-sdk'
import { useState, useEffect } from 'react'
import { jsx, jsxs } from 'react/jsx-runtime'
import { pressable } from './a11y.js'

let CTX = null
const KEY = ['cockpit', 'list']
const OPEN = new Set(['pending', 'endorsed', 'held', 'returned', 'posted'])
const POLL_MS = 10000

// every element goes through pressable (lib/a11y.js): one with a click handler that is no native control gets a role, a
// place in the tab order and Enter/Space; a button that shows only a sign is named by its title
const h = (tag, props, ...children) => {
  const given = pressable(tag, props, children)
  return children.length > 1 ? jsxs(tag, { ...given, children }) : jsx(tag, { ...given, children: children[0] })
}
const sub = { color: 'var(--ui-text-tertiary)' }
const mono = { fontFamily: 'var(--ui-font-mono, ui-monospace, SFMono-Regular, Menlo, monospace)' }
const stroke = 'var(--ui-stroke-secondary)'
// every text area gets a ✕ that clears it (shown only while it has text); props are the textarea's own
function ClearableTextarea(props) {
  const has = Boolean(props.value && String(props.value).length)
  const clear = () => { if (props.onChange) props.onChange({ target: { value: '' } }) }
  return h('div', { className: 'relative min-w-0 w-full' },
    h('textarea', { ...props, className: (props.className || '') + ' w-full', style: { ...(props.style || {}), paddingRight: '1.6rem' } }),
    has ? h('button', { type: 'button', tabIndex: -1, onMouseDown: (e) => e.preventDefault(), onClick: clear, title: 'clear', className: 'absolute right-1 top-1 rounded px-1 leading-4 text-xs', style: { color: 'var(--ui-text-tertiary)', background: 'rgba(127,127,127,.15)' } }, '✕') : null)
}
const btn = (label, onClick, extra = {}) =>
  h('button', {
    type: 'button',
    onClick: (e) => { e.stopPropagation(); haptic('tap'); onClick() },
    className: 'rounded border px-2 py-0.5 text-xs hover:bg-(--ui-bg-hover,rgba(127,127,127,.12))',
    style: { borderColor: extra.accent ? 'var(--ui-accent)' : stroke, color: extra.danger ? 'var(--ui-danger, #d33)' : extra.accent ? 'var(--ui-accent)' : 'var(--ui-text-secondary)', ...(extra.style || {}) },
    title: extra.title || ''
  }, label)
// one look for every dropdown, its open list included (the theme's colours, not the system's white): options = [[value, label]]
const selectBox = (value, onChange, options, extra = {}) => h('select', { value, onChange: (e) => onChange(e.target.value), className: 'cockpit-input', ...extra }, ...options.map(([v, l]) => h('option', { key: v, value: v }, l)))
const seg = (active, id, label, set) => h('button', { type: 'button', onClick: () => set(id), className: 'px-2 py-0.5 text-xs rounded',
  style: { background: active === id ? 'var(--ui-accent)' : 'transparent', color: active === id ? 'var(--ui-on-accent, #fff)' : 'var(--ui-text-secondary)' } }, label)

const CSS = `
.cockpit-spin{display:inline-block;animation:cockpitSpin 1s linear infinite}@keyframes cockpitSpin{to{transform:rotate(360deg)}}
@keyframes cockpitPulse{0%{opacity:.9;r:inherit}50%{opacity:.25}100%{opacity:.9}}.cockpit-glow{animation:cockpitPulse 1.8s ease-in-out infinite}
[data-plugin-root='cockpit'] button,[data-plugin-root='cockpit'] .select-none,[data-plugin-root='cockpit'] .cockpit-row{-webkit-user-select:none;user-select:none}
.cockpit-brief{display:grid;grid-template-columns:6.5rem 1fr;gap:.45rem .9rem;align-items:start;font-size:.8rem;line-height:1.45}
.cockpit-brief .k{font-size:.6875rem;text-transform:uppercase;letter-spacing:.04em;color:var(--ui-accent);font-weight:600;padding-top:.15rem}
.cockpit-brief .v{min-width:0}.cockpit-brief .v .t{margin:0}.cockpit-brief ul{list-style:disc;padding-left:1.1rem;margin:.15rem 0 0}.cockpit-brief li{margin:.15rem 0}.cockpit-brief li+li{padding-top:.1rem}
.cockpit-brief .k:nth-of-type(n+2){border-top:1px solid var(--ui-stroke-secondary);padding-top:.5rem}.cockpit-brief .v:nth-of-type(n+2){border-top:1px solid var(--ui-stroke-secondary);padding-top:.45rem}
.cockpit-section{display:flex;flex-direction:column;gap:.5rem}
.cockpit-row{transition:background .08s}.cockpit-row:hover{background:rgba(127,127,127,.09)!important}.cockpit-head{font-size:.6875rem;text-transform:uppercase;letter-spacing:.04em;color:var(--ui-text-tertiary)}
.cockpit-md{font-size:.8rem;line-height:1.5;min-width:0;max-width:100%;overflow-wrap:anywhere}.cockpit-md img{max-width:100%}.cockpit-table{max-width:100%;overflow-x:auto;margin:.5em 0;padding-bottom:2px}.cockpit-table table{margin:0;width:max-content;max-width:none}
/* horizontal scrollers (markdown and ADF tables, grid tables, the board's lanes, code blocks, panes): a thin rounded bar in the host's
   tertiary tone that stays visible while the content is wider — the ::-webkit-scrollbar styling makes Chromium draw a classic bar
   instead of macOS's overlay one that hides until you scroll (the standard scrollbar-* properties would switch that styling off) */
.cockpit-table::-webkit-scrollbar,.cockpit-scroll::-webkit-scrollbar,.cockpit-kb-lanes::-webkit-scrollbar,.cockpit-md pre::-webkit-scrollbar{height:8px;width:8px}
.cockpit-table::-webkit-scrollbar-track,.cockpit-scroll::-webkit-scrollbar-track,.cockpit-kb-lanes::-webkit-scrollbar-track,.cockpit-md pre::-webkit-scrollbar-track{background:color-mix(in srgb,var(--ui-text-tertiary) 10%,transparent);border-radius:999px}
.cockpit-table::-webkit-scrollbar-thumb,.cockpit-scroll::-webkit-scrollbar-thumb,.cockpit-kb-lanes::-webkit-scrollbar-thumb,.cockpit-md pre::-webkit-scrollbar-thumb{background:color-mix(in srgb,var(--ui-text-tertiary) 50%,transparent);border-radius:999px;border:2px solid transparent;background-clip:padding-box}
.cockpit-table::-webkit-scrollbar-thumb:hover,.cockpit-scroll::-webkit-scrollbar-thumb:hover,.cockpit-kb-lanes::-webkit-scrollbar-thumb:hover,.cockpit-md pre::-webkit-scrollbar-thumb:hover{background:color-mix(in srgb,var(--ui-text-tertiary) 75%,transparent)}
.cockpit-table::-webkit-scrollbar-corner,.cockpit-scroll::-webkit-scrollbar-corner{background:transparent}
.cockpit-scroll{overflow-x:auto}
/* tracker document preview (render.render_adf): panels, collapsed expands and status lozenges in the tracker's colours */
.cockpit-doc .cockpit-doc-panel{display:flex;gap:.5rem;align-items:flex-start;border-radius:.375rem;padding:.5rem .625rem;margin:.375rem 0;border:1px solid transparent}.cockpit-doc .cockpit-doc-panel p{margin:0}
.cockpit-doc-info{background:color-mix(in srgb,#388bfd 12%,transparent);border-color:color-mix(in srgb,#388bfd 35%,transparent)!important}.cockpit-doc-note{background:color-mix(in srgb,#a78bfa 12%,transparent);border-color:color-mix(in srgb,#a78bfa 35%,transparent)!important}
.cockpit-doc-warning{background:color-mix(in srgb,#e2a400 14%,transparent);border-color:color-mix(in srgb,#e2a400 40%,transparent)!important}.cockpit-doc-error{background:color-mix(in srgb,#f85149 13%,transparent);border-color:color-mix(in srgb,#f85149 40%,transparent)!important}
.cockpit-doc-success{background:color-mix(in srgb,#2a9d5c 14%,transparent);border-color:color-mix(in srgb,#2a9d5c 40%,transparent)!important}
.cockpit-doc-expand{border:1px solid var(--ui-stroke-tertiary,var(--ui-stroke-secondary));border-radius:.375rem;padding:.25rem .5rem;margin:.375rem 0}.cockpit-doc-expand>summary{cursor:pointer;font-weight:500}.cockpit-doc-expand[open]>summary{margin-bottom:.25rem}
.cockpit-doc-status{display:inline-block;border-radius:.1875rem;padding:0 .3rem;font-size:.6875rem;font-weight:700;letter-spacing:.02em}.cockpit-doc-s-neutral{background:rgba(127,127,127,.2)}.cockpit-doc-s-purple{background:color-mix(in srgb,#a78bfa 25%,transparent);color:#a78bfa}
.cockpit-doc-s-blue{background:color-mix(in srgb,#388bfd 22%,transparent);color:#58a6ff}.cockpit-doc-s-red{background:color-mix(in srgb,#f85149 22%,transparent);color:#f85149}.cockpit-doc-s-yellow{background:color-mix(in srgb,#e2a400 25%,transparent);color:#c98a00}.cockpit-doc-s-green{background:color-mix(in srgb,#2a9d5c 22%,transparent);color:#2a9d5c}
.cockpit-doc-date,.cockpit-doc-mention,.cockpit-doc-media{border-radius:.1875rem;padding:0 .25rem;background:rgba(127,127,127,.15);font-size:.75rem}.cockpit-doc-tasks{list-style:none;padding-left:.5rem}
.cockpit-brief .v{overflow-wrap:anywhere}.cockpit-brief .v pre,.cockpit-brief .v code{white-space:pre-wrap}.cockpit-md h1,.cockpit-md h2,.cockpit-md h3,.cockpit-md h4{font-weight:600;margin:.9em 0 .35em}.cockpit-md h1{font-size:1.05rem}.cockpit-md h2{font-size:.95rem}.cockpit-md h3{font-size:.875rem}
.cockpit-md p{margin:.4em 0}.cockpit-md ul,.cockpit-md ol{padding-left:1.4em;margin:.4em 0}.cockpit-md ul{list-style:disc}.cockpit-md ol{list-style:decimal}.cockpit-md li{margin:.15em 0}
.cockpit-md code{font-family:var(--ui-font-mono,ui-monospace,Menlo,monospace);font-size:.75rem;background:rgba(127,127,127,.14);padding:.05em .3em;border-radius:3px}
.cockpit-md pre{background:rgba(127,127,127,.1);border:1px solid var(--ui-stroke-secondary);border-radius:4px;padding:.5em .7em;overflow:auto;margin:.5em 0}.cockpit-md pre code{background:none;padding:0}
.cockpit-md blockquote{border-left:3px solid var(--ui-stroke-secondary);margin:.5em 0;padding:.1em .8em;color:var(--ui-text-secondary)}.cockpit-md a{color:var(--ui-accent);text-decoration:underline}
.cockpit-md table{border-collapse:collapse;margin:.5em 0;font-size:.75rem}.cockpit-md th,.cockpit-md td{border:1px solid var(--ui-stroke-secondary);padding:.2em .5em;text-align:left}.cockpit-md th{font-weight:600}.cockpit-md hr{border:0;border-top:1px solid var(--ui-stroke-secondary);margin:.8em 0}
.cockpit-diff{font-family:var(--ui-font-mono,ui-monospace,Menlo,monospace);font-size:.72rem;line-height:1.35}.cockpit-diff .f{border:1px solid var(--ui-stroke-secondary);border-radius:4px;margin:.4em 0;overflow:hidden}
.cockpit-diff .fh{display:flex;gap:.6em;align-items:center;padding:.3em .6em;background:rgba(127,127,127,.1);cursor:pointer;font-weight:600}.cockpit-diff .fh .n{flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.cockpit-diff .l{display:grid;grid-template-columns:3.2em 3.2em 1fr;white-space:pre;overflow-x:auto}.cockpit-diff .l .no{text-align:right;padding:0 .4em;color:var(--ui-text-quaternary);user-select:none}
.cockpit-diff .l.a{background:rgba(46,160,67,.16)}.cockpit-diff .l.d{background:rgba(248,81,73,.16)}.cockpit-diff .l.hk{background:rgba(56,139,253,.12);color:var(--ui-text-secondary)}.cockpit-diff .l .t{padding:0 .5em}
.cockpit-diff .l.a .t::before{content:'+';color:#2ea043;margin-right:.3em}.cockpit-diff .l.d .t::before{content:'-';color:#f85149;margin-right:.3em}.cockpit-diff .l.c .t::before{content:' ';margin-right:.3em}
/* Board: the host kanban column and card chrome, read-only */
.cockpit-kb-lanes{display:flex;flex:1;min-height:0;gap:.5rem;overflow-x:auto;padding:.25rem 1rem .75rem}
.cockpit-kb-col{display:flex;flex-direction:column;height:100%;width:16rem;flex-shrink:0;border-radius:.5rem;padding:.5rem;background:color-mix(in srgb,var(--ui-bg-quinary,rgba(127,127,127,.14)) 50%,transparent);transition:background-color .15s}
.cockpit-kb-colhead{display:flex;height:1.25rem;align-items:center;gap:.375rem;padding:0 .25rem;margin-bottom:.375rem}
.cockpit-kb-dot{width:.375rem;height:.375rem;border-radius:9999px;flex-shrink:0}
.cockpit-kb-collabel{font-size:.6875rem;font-weight:500;text-transform:uppercase;letter-spacing:.025em;color:var(--ui-text-tertiary)}
.cockpit-kb-count,.cockpit-kb-age,.cockpit-kb-id{font-size:.625rem;font-variant-numeric:tabular-nums;color:var(--ui-text-quaternary)}
.cockpit-kb-body{position:relative;display:flex;min-height:0;flex:1;flex-direction:column;gap:.5rem;overflow-y:auto;overflow-x:hidden;padding:2px}
.cockpit-kb-empty{pointer-events:none;position:absolute;inset:0;display:grid;place-items:center;font-size:.6875rem;color:var(--ui-text-quaternary)}
.cockpit-kb-card{position:relative;display:flex;flex-direction:column;gap:.5rem;border-radius:.375rem;border:1px solid var(--ui-stroke-tertiary,var(--ui-stroke-secondary));border-left-width:2px;background:var(--ui-bg-elevated);padding:.625rem;cursor:pointer;animation:cockpitKbIn .18s ease-out;transition:background-color .15s,border-color .15s,transform .15s,box-shadow .15s,opacity .18s}
.cockpit-kb-card:hover{background:color-mix(in srgb,var(--ui-accent) 6%,var(--ui-bg-elevated));transform:translateY(-1px);box-shadow:0 2px 10px rgba(0,0,0,.18)}
.cockpit-kb-card.sel{border-color:var(--ui-accent);background:color-mix(in srgb,var(--ui-accent) 7%,transparent)}
.cockpit-kb-card.closed{opacity:.72}.cockpit-kb-card.closed:hover{opacity:1}
.cockpit-kb-card.out{animation:cockpitKbOut .2s ease-in forwards;pointer-events:none}
/* Done: one stacked card per ticket; two offset layers drawn with box-shadow (the card's own surface and stroke), lifted on hover */
.cockpit-kb-stackwrap{display:flex;flex-shrink:0;flex-direction:column;gap:.375rem;margin-bottom:6px}.cockpit-kb-stackwrap.out{animation:cockpitKbOut .2s ease-in forwards;pointer-events:none}
.cockpit-kb-stack{box-shadow:0 3px 0 -1px var(--ui-bg-elevated),0 3px 0 0 var(--ui-stroke-tertiary,var(--ui-stroke-secondary)),0 6px 0 -2px var(--ui-bg-elevated),0 6px 0 -1px var(--ui-stroke-tertiary,var(--ui-stroke-secondary))}
.cockpit-kb-stack:hover{box-shadow:0 3px 0 -1px var(--ui-bg-elevated),0 3px 0 0 var(--ui-stroke-secondary),0 6px 0 -2px var(--ui-bg-elevated),0 6px 0 -1px var(--ui-stroke-secondary),0 2px 10px rgba(0,0,0,.18)}
.cockpit-kb-stack.open{box-shadow:none;opacity:1}.cockpit-kb-stackn{border-radius:999px;padding:0 .375rem;font-size:.625rem;color:var(--ui-text-secondary);background:color-mix(in srgb,var(--ui-text-tertiary) 14%,transparent)}
.cockpit-kb-stackbody{display:flex;flex-direction:column;gap:.375rem;margin-left:.5rem;padding-left:.5rem;border-left:1px dashed var(--ui-stroke-secondary)}
@keyframes cockpitKbIn{from{opacity:0;transform:translateY(4px)}to{opacity:1;transform:none}}
@keyframes cockpitKbOut{to{opacity:0;transform:translateY(-4px)}}
.cockpit-kb-title{display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden;font-size:.8125rem;font-weight:500;line-height:1.375}
.cockpit-kb-sum{display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden;font-size:.6875rem;line-height:1.375;color:var(--ui-text-tertiary)}
.cockpit-kb-line{overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:.6875rem;line-height:1.375}
.cockpit-kb-foot{display:flex;align-items:center;gap:.5rem;white-space:nowrap;font-size:.625rem;color:var(--ui-text-tertiary)}
.cockpit-kb-ticket{font-size:.625rem;color:var(--ui-accent);background:color-mix(in srgb,var(--ui-accent) 12%,transparent);border-radius:.25rem;padding:.05rem .35rem;white-space:nowrap}
.cockpit-cap{font-size:.5625rem;line-height:1rem;font-weight:600;letter-spacing:.02em;border:1px solid;border-radius:999px;padding:0 .4rem;white-space:nowrap;font-variant-numeric:tabular-nums}
.cockpit-kb-flow{font-size:.5625rem;line-height:1rem;color:var(--ui-text-tertiary);background:color-mix(in srgb,var(--ui-text-tertiary) 12%,transparent);border-radius:.25rem;padding:0 .3rem;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:5.5rem;flex:0 1 auto}
.cockpit-kb-sub{font-size:.625rem;font-weight:500;text-transform:uppercase;letter-spacing:.025em}
.cockpit-kb-status{display:inline-flex;align-items:center;gap:.375rem;border-radius:.25rem;padding:.2rem .5rem;font-size:.6875rem;font-weight:600;text-transform:uppercase;letter-spacing:.025em;white-space:nowrap}
.cockpit-kb-lane{display:inline-flex;min-width:0;align-items:center;gap:.25rem;border-radius:9999px;padding:.1rem .45rem .1rem .1rem;font-size:.625rem;font-weight:500}
.cockpit-kb-ava{display:grid;place-items:center;flex-shrink:0;border-radius:9999px;font-size:.5625rem;font-weight:600}
.cockpit-kb-more{flex-shrink:0;border-radius:.375rem;border:1px dashed var(--ui-stroke-secondary);padding:.375rem;font-size:.6875rem;color:var(--ui-text-tertiary);transition:color .15s,border-color .15s,background-color .15s}
.cockpit-kb-more:hover{border-color:var(--ui-text-quaternary);background:var(--chrome-action-hover,rgba(127,127,127,.12));color:var(--ui-text-primary,inherit)}
.cockpit-kb-filter{display:flex;flex-wrap:wrap;align-items:center;gap:.375rem;padding:.375rem .75rem;border-bottom:1px solid var(--ui-stroke-secondary)}
.cockpit-kb-total{border-radius:9999px;background:var(--ui-bg-quaternary,rgba(127,127,127,.18));padding:1px .375rem;font-size:.625rem;font-variant-numeric:tabular-nums;color:var(--ui-text-tertiary)}
.cockpit-kb-chip{border-radius:9999px;border:1px solid;padding:.05rem .5rem;font-size:.6875rem;transition:background-color .15s,color .15s,border-color .15s}
.cockpit-kb-input{min-width:14rem}
@property --cockpit-kb-arc{syntax:'<angle>';inherits:false;initial-value:0deg}
.cockpit-kb-arc{pointer-events:none;position:absolute;inset:-1px;border-radius:inherit;padding:1.5px;background:conic-gradient(from var(--cockpit-kb-arc),transparent 0deg,var(--cockpit-kb-tone,var(--ui-stroke-primary)) 55deg,transparent 110deg);\
-webkit-mask:linear-gradient(#000 0 0) content-box,linear-gradient(#000 0 0);\
mask:linear-gradient(#000 0 0) content-box,linear-gradient(#000 0 0);-webkit-mask-composite:xor;mask-composite:exclude;animation:cockpitKbArc 2.2s linear infinite}
.cockpit-kb-arc.stale{--cockpit-kb-tone:#fbbf24;animation-duration:6s}
@keyframes cockpitKbArc{to{--cockpit-kb-arc:360deg}}
.cockpit-input{border:1px solid var(--ui-stroke-secondary);border-radius:4px;background:var(--ui-bg-elevated,transparent);color:var(--ui-text-primary);padding:.1rem .4rem;font-size:.75rem}
/* the picker's open list is drawn by the system unless its options are given the theme's colours */
select.cockpit-input{color-scheme:light dark}
select.cockpit-input option{background:var(--ui-bg-elevated,Canvas);color:var(--ui-text-primary,CanvasText)}
`

// a duration in seconds as people read it: 45s · 12m · 1h 05m · 2d 4h
const fmtDur = (s) => { if (s == null || isNaN(s) || s < 0) return '–'; s = Math.round(s); if (s < 60) return `${s}s`; const m = Math.round(s / 60); if (m < 60) return `${m}m`; const hh = Math.floor(m / 60); const mm = m % 60; if (hh < 24) return `${hh}h ${String(mm).padStart(2, '0')}m`; const d = Math.floor(hh / 24); return `${d}d ${hh % 24}h` }
// a time as the backend sends it: an ISO string, or epoch seconds (a watcher's last_ok, a PR's last_activity), never ms
const toMs = (v) => { if (v === null || v === undefined || v === '') return NaN; const n = typeof v === 'number' ? v : (/^\d+(\.\d+)?$/.test(String(v)) ? Number(v) : NaN); return Number.isNaN(n) ? new Date(v).getTime() : (n < 1e12 ? n * 1000 : n) }
const ago = (iso) => { if (!iso) return ''; const s = Math.max(0, (Date.now() - toMs(iso)) / 1000); return s < 3600 ? `${Math.round(s / 60)} min` : s < 86400 ? `${Math.round(s / 3600)} h` : `${Math.round(s / 86400)} d` }
// POSTs that may run twice without harm (streams, scans, marks): every other POST dispatches work, so the same call is refused while
// one is in flight and for a moment after it returns — a double click or a lagging view must never dispatch twice.
const REPEATABLE = new Set(['/chat-open', '/chat-write', '/chat-resize', '/chat-end', '/open-file', '/open-ide', '/fetch', '/platform-seen', '/pr-seen', '/sweep', '/digest', '/pr-scan', '/platform-scan', '/verify', '/ack', '/bumps-dismiss', '/ci-dismiss', '/vault-reveal'])
const inflight = new Map(); const COOLDOWN_MS = 2000
const post = (path, body) => {
  if (REPEATABLE.has(path)) return CTX.rest(path, { method: 'POST', body })
  const key = path + JSON.stringify(body ?? {})
  if (inflight.has(key)) return Promise.reject(new Error(`${path.slice(1)}: already running — wait for it to finish`))
  const p = CTX.rest(path, { method: 'POST', body }); inflight.set(key, p)
  p.then(() => setTimeout(() => inflight.delete(key), COOLDOWN_MS), () => inflight.delete(key))
  return p
}
// an address from a record (a demo link, a PR, an advisory source) goes to the system only when it is a web address:
// file:, a script or an app's own scheme would open or run something on this machine
const isWeb = (url) => { try { const u = new URL(String(url == null ? '' : url)); return (u.protocol === 'http:' || u.protocol === 'https:') && Boolean(u.host) } catch (e) { return false } }
const openWeb = (url) => { if (!isWeb(url)) return false; CTX.os.openExternal(String(url)); return true }
const openIde = async (body) => { try { const r = await post('/open-ide', body); host.notify({ kind: 'info', message: r.out || 'IDE opened' }) } catch (e) { host.notifyError(e, 'open IDE failed') } }
const openFile = async (path) => { try { await post('/open-file', { path }); } catch (e) { host.notifyError(e, 'open file failed') } }
// one button per PR of a ticket: repo #n, with its state at a glance (👍 approved · n new · merged)
const prButtons = (prs) => (prs || []).length ? h('span', { className: 'flex flex-wrap items-center gap-1' }, ...prs.map((p) =>
  h('button', { key: p.repo + p.number, type: 'button', onClick: (e) => { e.stopPropagation(); haptic('tap'); openWeb(p.url) }, title: `${p.title || ''}\n${p.url}`,
    className: 'rounded border px-2 py-0.5 text-xs whitespace-nowrap', style: { borderColor: p.merged ? 'var(--ui-text-quaternary)' : p.approvals && p.approvals.length ? 'var(--ui-success, #2a9d5c)' : stroke, color: p.merged ? 'var(--ui-text-tertiary)' : 'var(--ui-text-secondary)' } },
    `${p.repo} #${p.number} ↗`, p.role === 'reviewer' ? h('span', { style: sub },
      p.my_threads ? ` · you review · ${p.my_threads.resolved}/${p.my_threads.total} resolved` : ' · you review') : null,
      p.merged ? h('span', { style: sub }, ' merged') : p.approvals && p.approvals.length ? h('span', { style: { color: 'var(--ui-success, #2a9d5c)' } },
      ' 👍') : null, p.new_count ? h('span', { className: 'ml-1 rounded px-1', style: { background: 'var(--ui-warning, #c98a00)', color: '#fff' } },
      `${p.new_count} new`) : null))) : null
// a card's or a ticket's PRs: the open ones as buttons, the merged and closed ones under a collapsed "closed (n)" line
const prList = (prs) => { const open = (prs || []).filter((p) => !p.closed); const shut = (prs || []).filter((p) => p.closed)
  return open.length || shut.length ? h('span', { className: 'flex flex-wrap items-center gap-1' }, prButtons(open),
    shut.length ? h('details', { className: 'text-xs' }, h('summary', { className: 'cursor-pointer', style: sub }, `closed (${shut.length})`), prButtons(shut)) : null) : null }
const useList = () => useQuery({ queryKey: KEY, queryFn: () => CTX.rest('/list'), refetchInterval: POLL_MS, retry: 1 })
// one look for every table on the page: same header, same row metrics, same hover/selection
const thead = (cols, labels) => h('div', { className: 'cockpit-head grid items-center gap-2 px-3 py-1 border-b leading-4', style: { gridTemplateColumns: cols, borderColor: stroke } }, ...labels.map((l, i) => h('div', { key: i, className: typeof l === 'string' && l.startsWith('>') ? 'text-right' : '' }, typeof l === 'string' ? l.replace(/^>/, '') : l)))
const trow = (cols, { key, onClick, selected, title, children }) => h('div', { key, onClick, title, className: 'cockpit-row grid items-center gap-2 px-3 py-1.5 text-xs border-b' + (onClick ? ' cursor-pointer' : ''), style: { gridTemplateColumns: cols, borderColor: stroke, background: selected ? 'var(--ui-bg-selected, rgba(127,127,127,.15))' : 'transparent' } }, ...children)

// ---------- one layout for every view: list left, detail right (opens on click, like the Outbox) ----------
const closeBtn = (onClose) => h('button', { type: 'button', onClick: () => { haptic('tap'); onClose() }, title: 'close (Esc)', className: 'cockpit-head rounded px-1.5 leading-4', style: { background: 'rgba(127,127,127,.12)' } }, '✕ close')
function Pane({ onClose, children }) {
  useEffect(() => { const k = (e) => { if (e.key === 'Escape' && !window.__cockpitModalOpen) onClose() }; window.addEventListener('keydown', k); return () => window.removeEventListener('keydown', k) }, [onClose])
  return h('div', { className: 'min-w-0 flex-1 flex flex-col', style: { minHeight: 0 } },
    h('div', { className: 'cockpit-head flex items-center justify-end px-3 py-1 border-b leading-4', style: { borderColor: stroke } }, closeBtn(onClose)),
    h('div', { className: 'cockpit-scroll min-h-0 flex-1 overflow-auto flex flex-col' }, children))
}
function SplitList({ cols, labels, rows, renderRow, selected, onSelect, onClose, empty, detail, detailWidth, footer }) {   // footer: sits at the bottom of the list column, a gap above it
  const close = onClose || (() => onSelect(null))
  return h('div', { className: 'flex min-h-0 flex-1' },
    h('div', { className: 'cockpit-scroll flex min-w-0 flex-col overflow-auto', style: { flex: selected ? `0 0 ${detailWidth || '46%'}` : '1 1 auto', borderRight: selected ? `1px solid ${stroke}` : 'none' } },
      thead(cols, labels),
      rows.length ? rows.map((r) => renderRow(r)) : h('div', { className: 'p-6 text-center text-xs', style: sub }, empty),
      footer ? h('div', { className: 'cockpit-footer', style: { marginTop: 'auto', paddingTop: '2rem' } }, footer) : null),
    selected ? h(Pane, { onClose: close }, detail) : null)
}
const detailHead = (title, status, right) => h('div', { className: 'flex items-baseline gap-2' }, h('div', { className: 'font-medium text-sm' }, title), status ? h('div', { className: 'text-xs', style: { color: status.color } }, status.text) : null, right ? h('div', { className: 'ml-auto text-xs', style: sub }, right) : null)
const tabs = (tab, setTab, items) => h('div', { className: 'flex items-center gap-1 self-start rounded border p-0.5', style: { borderColor: stroke } }, ...items.filter(Boolean).map(([id, label]) => seg(tab, id, label, setTab)))
// the Brief grid built on the page: fields = [{label, text, items}] — same markup and CSS as the backend-rendered one
function BriefGrid({ fields }) {
  return h('div', { className: 'cockpit-brief' }, ...fields.filter((f) => f.text || (f.items && f.items.length)).flatMap((f, i) => [
    h('div', { key: 'k' + i, className: 'k' }, f.label),
    h('div', { key: 'v' + i, className: 'v' }, f.text ? h('div', { className: 't', style: f.color ? { color: f.color } : {} }, f.text) : null, f.items && f.items.length ? h('ul', null, ...f.items.map((it, j) => h('li', { key: j }, it))) : null)]))
}
// a collapsible section that mounts its content only while open (mermaid frames measure themselves on mount)
function Section({ title, open: initial = false, color, extra, children }) {
  const [open, setOpen] = useState(Boolean(initial))
  return h('div', { className: 'rounded border', style: { borderColor: color || stroke } },
    h('div', { className: 'flex items-center gap-2 px-2 py-1 cursor-pointer select-none', onClick: () => setOpen(!open), style: { background: 'rgba(127,127,127,.06)' } },
      h('span', { style: sub }, open ? '▾' : '▸'), h('span', { className: 'font-medium', style: color ? { color } : {} }, title), extra ? h('span', { className: 'ml-auto flex gap-1', role: 'presentation', onClick: (e) => e.stopPropagation() }, extra) : null),
    open ? h('div', { className: 'px-2.5 py-2 cockpit-section' }, children) : null)
}

function setCTX(ctx) { CTX = ctx }

export { host, haptic, useQuery, useQueryClient, ROUTES_AREA, SIDEBAR_NAV_AREA, SandboxedFrame, jsx }
export { CTX, setCTX, KEY, OPEN, POLL_MS, h, sub, mono, stroke, ClearableTextarea, btn, selectBox, seg, CSS, ago, toMs, fmtDur, post, openIde, openFile, openWeb, isWeb, prButtons, prList, useList, thead, trow, closeBtn, Pane, SplitList, detailHead, tabs, BriefGrid, Section }

// who checks and who endorsed: the lane, never a model name (the record keeps the model for the history)
export const gateOf = () => 'gatekeeper'
export const endorserOf = (r) => (r && r.endorsed && r.endorsed.by) || 'gatekeeper'
