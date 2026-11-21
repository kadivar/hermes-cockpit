// SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
// SPDX-License-Identifier: AGPL-3.0-or-later
import { useState } from 'react'
import { useQuery, CTX, h, sub, mono, stroke, tabs, thead, trow, fmtDur, btn } from '../lib/sdk.js'

// ---------- usage: tokens and estimated cost, every lane + coding tool, by lane / ticket / day / model, per period ----------
const fmtN = (n) => n >= 1e9 ? (n / 1e9).toFixed(2) + 'B' : n >= 1e6 ? (n / 1e6).toFixed(n >= 1e8 ? 0 : n >= 1e7 ? 1 : 2) + 'M' : n >= 1e3 ? (n / 1e3).toFixed(1) + 'k' : String(n || 0)
const fmt$ = (c) => c ? '$' + c.toFixed(2) : '–'
const USAGE_COLS = '1fr 4rem 5rem 5rem 5rem 5.5rem 5rem 5.5rem 4.5rem'
const PERIOD_LABEL = { today: 'today', week: 'last 7 days', month: 'last 30 days', all: 'all time' }
// ---------- pace: how the plan's windows are being spent against the quota ceiling (insight only; /pace) ----------
const VERDICT_COLOR = { ahead: 'var(--ui-warning, #c98a00)', on: 'var(--ui-success, #2a9d5c)', behind: 'var(--ui-accent)' }
const pctOf = (x) => x == null ? '–' : Math.round(x * 100) + '%'
function PaceBar({ w, target }) {
  const clamp = (x) => Math.max(0, Math.min(100, x || 0))
  return h('div', { className: 'flex flex-col gap-1 text-xs' },
    h('div', { className: 'grid items-center gap-3', style: { gridTemplateColumns: '9rem 1fr 11rem' } },
      h('div', { className: 'truncate', style: sub }, w.name),
      h('div', { className: 'relative h-2.5 rounded', style: { background: 'rgba(127,127,127,.18)' }, title: `used ${w.used}% · ideal by now ${w.ideal}% · target ${target}%` },
        h('div', { className: 'h-2.5 rounded', style: { width: clamp(w.used) + '%', background: VERDICT_COLOR[w.verdict] || 'var(--ui-accent)' } }),
        h('div', { className: 'cockpit-pace-ideal absolute', title: `ideal by now: ${w.ideal}%`, style: { left: clamp(w.ideal) + '%', top: '-3px', bottom: '-3px', width: '2px', background: 'var(--ui-text-primary, #222)' } }),
        h('div', { className: 'cockpit-pace-target absolute', title: `target: ${target}%`, style: { left: clamp(target) + '%', top: '-4px', bottom: '-4px', borderLeft: '2px dashed var(--ui-danger, #d33)' } })),
      h('div', { className: 'text-right whitespace-nowrap', style: { fontVariantNumeric: 'tabular-nums' } }, h('span', { className: 'font-medium' }, `${w.used}%`), h('span', { style: sub }, ` · ideal ${w.ideal}% · ${w.verdict}`))),
    h('div', { style: sub }, w.sentence || ''))
}
function PacePanel() {
  const [round, setRound] = useState(0)
  const q = useQuery({ queryKey: ['cockpit', 'pace', round], queryFn: () => CTX.rest(round ? '/pace?fresh=1' : '/pace'), refetchInterval: 300000, retry: 1 })
  const p = q.data
  if (!p || !p.target_pct) return null
  const inp = p.inputs || {}; const e = p.efficiency || {}
  const fact = (label, value) => h('div', { className: 'flex gap-1' }, h('span', { style: sub }, label + ':'), h('span', { style: { fontVariantNumeric: 'tabular-nums' } }, value))
  return h('div', { className: 'flex flex-col gap-2 rounded border px-3 py-2', style: { borderColor: stroke } },
    h('div', { className: 'flex items-center gap-3' }, h('div', { className: 'cockpit-head' }, `plan pace${p.provider ? ' · ' + p.provider : ''}`),
      h('span', { className: 'text-xs', style: sub }, 'insight only: nothing here holds or starts a card'),
      h('span', { className: 'ml-auto' }, btn('Recalculate', () => setRound((r) => r + 1), { title: 'read the plan again now, skipping the five-minute cache' }))),
    p.error ? h('div', { className: 'text-xs', style: { color: 'var(--ui-warning, #c98a00)' } }, `${p.stale ? 'last good reading shown; ' : ''}${p.error}`) : null,
    ...(p.windows || []).map((w) => h(PaceBar, { key: w.name, w, target: p.target_pct })),
    p.binding ? h('div', { className: 'text-xs font-medium' }, `${p.binding} binds: ${p.verdict === 'ahead' ? 'ahead of pace' : p.verdict === 'behind' ? 'behind pace (unused capacity)' : 'on pace'}`) : null,
    h('div', { className: 'flex flex-wrap gap-x-4 gap-y-1 text-xs' },
      fact('target (quota ceiling)', `${p.target_pct}%`), fact('active hours', inp.schedule || 'all hours'), fact('peak hours', inp.peak_hours || 'not counted'),
      fact('on-pace band', `±${inp.band || 3} points`), fact('read at', (p.read_at || '').slice(0, 16).replace('T', ' ') + (p.stale ? ' (stale)' : ''))),
    h('div', { className: 'flex flex-wrap gap-x-4 gap-y-1 text-xs' },
      fact('tokens this week', fmtN(e.tokens || 0)), fact('tokens per card run', e.tokens_per_run == null ? '–' : fmtN(e.tokens_per_run)),
      fact('card runs that failed or were retried', pctOf(e.wasted_share)), fact('Opus share of tokens', pctOf(e.opus_share)), fact('cache reads in input', pctOf(e.cache_read_share))))
}
function Usage() {
  const [period, setPeriod] = useState('week'); const [by, setBy] = useState('who')
  const [stackOnly, setStackOnlyRaw] = useState(() => CTX.storage.get('usageStackOnly', true)); const setStackOnly = (v) => { setStackOnlyRaw(v); CTX.storage.set('usageStackOnly', v) }
  const scope = stackOnly ? 'hermes' : 'all'
  const q = useQuery({ queryKey: ['cockpit', 'usage', period, by, scope], queryFn: () => CTX.rest(`/usage?period=${period}&by=${by}&scope=${scope}`), refetchInterval: 60000, retry: 1 })
  if (q.isLoading) return h('div', { className: 'p-3 text-xs', style: sub }, 'adding up every session')
  if (q.error) return h('div', { className: 'p-3 text-xs', style: { color: 'var(--ui-danger, #d33)' } }, String(q.error.message || q.error))
  const d = q.data; const T = d.totals || {}
  const periodOf = (k) => T[k] || { total: 0, sessions: 0, cost: 0, output: 0, cache_read: 0 }
  const num = (n, cls) => h('div', { className: 'text-right ' + (cls || ''), style: { fontVariantNumeric: 'tabular-nums' } }, n)
  const bar = (w) => h('div', { className: 'grid items-center gap-3 text-xs', style: { gridTemplateColumns: '9rem 1fr 5rem 10rem' } },
    h('div', { className: 'truncate', style: sub }, w.name),
    h('div', { className: 'h-2 rounded', style: { background: 'rgba(127,127,127,.18)' } }, h('div', { className: 'h-2 rounded', style: { width: w.used + '%', background: w.used > 85 ? 'var(--ui-danger, #d33)' : w.used > 60 ? 'var(--ui-warning, #c98a00)' : 'var(--ui-success, #2a9d5c)' } })),
    h('div', { className: 'text-right whitespace-nowrap font-medium', style: { fontVariantNumeric: 'tabular-nums' } }, `${w.used}% used`),
    h('div', { className: 'text-right whitespace-nowrap', style: { ...sub, fontVariantNumeric: 'tabular-nums' }, title: 'resets at ' + w.resets_at }, `resets in ${w.resets_in}`))
  const periodCell = (k, label) => h('div', { className: 'rounded border px-3 py-2 text-xs cursor-pointer', onClick: () => setPeriod(k), style: { borderColor: period === k ? 'var(--ui-accent)' : stroke, background: period === k ? 'rgba(56,139,253,.06)' : 'transparent' } },
    h('div', { className: 'cockpit-head' }, label), h('div', { className: 'text-sm font-medium', style: { fontVariantNumeric: 'tabular-nums' } }, fmtN(periodOf(k).total) + ' tokens'), h('div', { style: sub }, `${periodOf(k).sessions} sessions · est ${fmt$(periodOf(k).cost)} · ${fmtN(periodOf(k).output)} out · ${fmtN(periodOf(k).cache_read)} cached`))
  const sp = d.split || { hermes: 0, outside: 0, hermes_pct: 0, total: 0, hermes_sessions: 0, outside_sessions: 0 }; const pct = sp.hermes_pct || 0; const periodLabel = PERIOD_LABEL[period] || period
  const seg2 = (label, color, value, p) => h('span', { className: 'flex items-center gap-1 whitespace-nowrap' },
    h('span', { className: 'inline-block h-2 w-2 rounded-sm', style: { background: color } }), h('span', { style: sub }, label),
    h('span', { className: 'font-medium', style: { fontVariantNumeric: 'tabular-nums' } }, `${p}%`),
    h('span', { style: { ...sub, fontVariantNumeric: 'tabular-nums' } }, `· ${fmtN(value)}`))
  const splitBar = h('div', { className: 'flex flex-col gap-1 rounded border px-3 py-2', style: { borderColor: stroke } },
    h('div', { className: 'flex items-center gap-3' }, h('div', { className: 'cockpit-head' }, `where the tokens went · ${periodLabel}`),
      h('div', { className: 'ml-auto flex items-center gap-4 text-xs' }, seg2('Hermes stack', 'var(--ui-accent)', sp.hermes, pct),
      seg2('outside (your coding tool)', 'rgba(127,127,127,.55)', sp.outside, Math.round((100 - pct) * 10) / 10),
      h('span', { style: { ...sub, fontVariantNumeric: 'tabular-nums' } }, `${fmtN(sp.total)} total`))),
    h('div', { className: 'flex h-2.5 w-full overflow-hidden rounded', style: { background: 'rgba(127,127,127,.18)' } },
      h('div', { className: 'h-2.5', style: { width: pct + '%', background: 'var(--ui-accent)' }, title: `Hermes stack: ${fmtN(sp.hermes)} tokens in ${sp.hermes_sessions} sessions` }),
      h('div', { className: 'h-2.5', style: { width: (100 - pct) + '%', background: 'rgba(127,127,127,.55)' }, title: `outside Hermes: ${fmtN(sp.outside)} tokens in ${sp.outside_sessions} sessions` })))
  return h('div', { className: 'flex min-h-0 flex-1 flex-col gap-3 overflow-auto p-3' },
    h('div', { className: 'flex items-center gap-3 text-xs' },
      h('label', { className: 'flex items-center gap-1 cursor-pointer' }, h('input', { type: 'checkbox', checked: stackOnly, onChange: (e) => setStackOnly(e.target.checked) }), 'Hermes stack only'),
      h('span', { style: sub }, stackOnly ? 'the numbers below count the lanes, the concierge and the lanes\' coding tool runs; your own coding tool sessions are left out' : 'the numbers below count everything, your own coding tool sessions included')),
    (d.windows || []).length ? h('div', { className: 'flex flex-col gap-1 rounded border px-3 py-2', style: { borderColor: stroke } }, h('div', { className: 'cockpit-head' }, 'provider plan windows'), ...(d.windows || []).map((w) => bar(w))) : null,
    h(PacePanel, {}),
    h('div', { className: 'flex flex-col gap-1 rounded border px-3 py-2', style: { borderColor: stroke } }, h('div', { className: 'cockpit-head' }, 'providers'), ...(d.providers || []).map((p) => h('div', { key: p.provider, className: 'flex items-center gap-3 text-xs' },
      h('span', { className: 'font-medium' }, p.provider),
      h('span', { style: sub }, `${p.turns || 0} turns · ${fmtDur(p.time || 0)}`),
      p.cost == null ? null : h('span', { style: sub }, (p.approximate ? '≈ ' : '') + fmt$(p.cost)),
      p.plan_window ? h('span', { style: sub }, `window ${p.plan_window}`) : null))),
    stackOnly ? null : splitBar,
    h('div', { className: 'grid gap-2', style: { gridTemplateColumns: 'repeat(4, 1fr)' } }, periodCell('today', 'today'), periodCell('week', 'last 7 days'), periodCell('month', 'last 30 days'), periodCell('all', 'all time')),
    h('div', { className: 'flex items-center gap-2 text-xs' }, h('span', { style: sub }, `${PERIOD_LABEL[period] || period}, by`), tabs(by, setBy, [['who', 'lane'], ['ticket', 'origin'], ['day', 'day'], ['model', 'model']]), h('span', { className: 'ml-auto', style: sub }, d.note)),
    h('div', { className: 'cockpit-scroll rounded border', style: { borderColor: stroke } },
      thead(USAGE_COLS, [by === 'who' ? 'lane / source' : by === 'ticket' ? 'origin (ticket or where it came from)' : by, '>sessions', '>time', '>input', '>output', '>cache read', '>cache write', '>total', '>est cost (≈ list price)']),
      ...(d.groups || []).map((g) => trow(USAGE_COLS, { key: g.key,
        children: [h('div', { key: 'k', className: 'truncate font-medium', style: by === 'model' ? mono : {} }, g.key), num(g.sessions),
        h('div', { key: 'd', className: 'text-right', style: { fontVariantNumeric: 'tabular-nums' },
        title: 'running time of the sessions (start to end, or to the last activity)' }, fmtDur(g.seconds)), num(fmtN(g.input)), num(fmtN(g.output)),
        num(fmtN(g.cache_read)), num(fmtN(g.cache_write)), num(fmtN(g.total), 'font-medium'), num(fmt$(g.cost))] })),
      !(d.groups || []).length ? h('div', { className: 'p-4 text-center text-xs', style: sub }, 'nothing in this period') : null),
    h('details', { className: 'text-xs' }, h('summary', { className: 'cursor-pointer', style: sub }, `recent sessions in this period (${(d.recent || []).length})`),
      h('div', { className: 'cockpit-scroll mt-1 rounded border', style: { borderColor: stroke } }, thead('8rem 7rem 6rem 1fr 5rem 6rem 5rem', ['when', 'who', 'ticket', 'session', '>time', '>tokens', '>est']),
        ...(d.recent || []).map((r, i) => trow('8rem 7rem 6rem 1fr 5rem 6rem 5rem',
          { key: i, children: [h('div', { key: 'w', style: sub }, r.when ? r.when.slice(5, 16).replace('T', ' ') : ''),
          h('div', { key: 'o', style: mono }, r.who), h('div', { key: 't' }, r.ticket || ''),
          h('div', { key: 'd', className: 'text-right', style: { fontVariantNumeric: 'tabular-nums' } }, fmtDur(r.seconds)),
          h('div', { key: 's', className: 'truncate', title: r.title }, r.title), num(fmtN(r.input + r.output + r.cache_read + r.cache_write)),
          num((r.estimate ? '≈' : '') + fmt$(r.cost))] })))))
}

export { Usage, PacePanel, fmtN, fmt$, USAGE_COLS, PERIOD_LABEL }
